"""Official owned-post previews and authenticated, short-lived selection receipts.

No arbitrary URL fetching, public-platform scraping, background sync or model calls.
Read permission, retained sample selection and AI route consent are separate gates.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlparse

from postriff_alpha.domain import AlphaError
from .providers import GRAPH_VERSION

PAGE_LIMIT = 25
RECEIPT_TTL = 600
MAX_RECEIPT = 400_000
LINKEDIN_VERSION = '202609'


def _text(value, limit=8000):
    return value.strip() if isinstance(value, str) and len(value) <= limit else ''


def _public_url(value, roots):
    value = _text(value, 2048)
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    return value if parsed.scheme == 'https' and not parsed.username and not parsed.password and any(host == root or host.endswith('.' + root) for root in roots) else None


def _response(response):
    status, body = response.get('status'), response.get('body')
    if status in (401, 403):
        raise AlphaError('Historical-post access was denied. Reconnect with the required read permission and account type.', 409, code='history_permission_required')
    if status == 429:
        raise AlphaError('The social provider is rate limiting. No posts were imported; try again later.', 429)
    if status != 200 or not isinstance(body, dict) or body.get('error'):
        raise AlphaError('Historical posts could not be read from the provider. This is not an empty history.', 502)
    return body


def fetch_page(adapter, access_token, account_id, cursor=None, limit=PAGE_LIMIT):
    """One bounded page scoped to a server-resolved authenticated account only."""
    if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
        raise AlphaError('Read between 1 and 25 posts per page.')
    if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r'[A-Za-z0-9_.~=-]{1,2048}', cursor)):
        raise AlphaError('This post cursor is invalid.')
    headers = {'Authorization': 'Bearer ' + access_token}
    if adapter.id == 'instagram':
        if not isinstance(account_id, str) or not re.fullmatch(r'\d{1,40}', account_id):
            raise AlphaError('Instagram account identity could not be verified.', 409)
        params = {'fields': 'id,caption,timestamp,media_type,permalink,thumbnail_url,media_url', 'limit': limit}
        if cursor:
            params['after'] = cursor
        body = _response(adapter.transport('GET', f'https://graph.instagram.com/{GRAPH_VERSION}/{account_id}/media?' + urlencode(params), headers=headers))
        rows = body.get('data')
        paging = body.get('paging', {})
        if not isinstance(paging, dict) or not isinstance(paging.get('cursors', {}), dict):
            raise AlphaError('Instagram returned invalid pagination metadata.', 502)
        next_cursor = paging.get('cursors', {}).get('after') if paging.get('next') else None
        if paging.get('next') and not next_cursor:
            raise AlphaError('Instagram indicated more posts but supplied no usable cursor. Coverage is incomplete.', 502)
    elif adapter.id == 'linkedin':
        if not getattr(adapter, 'history_approved', False):
            raise AlphaError('LinkedIn history requires approved r_member_social access. Paste or import your own posts instead.', 409, code='history_approval_required')
        if not isinstance(account_id, str) or not re.fullmatch(r'urn:li:person:[A-Za-z0-9_-]{1,100}', account_id):
            raise AlphaError('Only the authenticated LinkedIn member can be read.', 409)
        if cursor is not None and (not cursor.isdigit() or len(cursor) > 5 or int(cursor) > 5000):
            raise AlphaError('This LinkedIn page cursor is invalid.')
        start = int(cursor or '0')
        headers.update({'Linkedin-Version': LINKEDIN_VERSION, 'X-Restli-Protocol-Version': '2.0.0'})
        params = {'q': 'author', 'author': account_id, 'count': limit, 'start': start, 'sortBy': 'LAST_MODIFIED'}
        body = _response(adapter.transport('GET', 'https://api.linkedin.com/rest/posts?' + urlencode(params), headers=headers))
        rows = body.get('elements')
        paging = body.get('paging', {})
        if not isinstance(paging, dict) or not isinstance(paging.get('links', []), list):
            raise AlphaError('LinkedIn returned invalid pagination metadata.', 502)
        links = paging.get('links', [])
        next_cursor = str(start + limit) if any(isinstance(link, dict) and link.get('rel') == 'next' for link in links) else None
    else:
        raise AlphaError('This provider does not support historical-post import here.', 409)
    if not isinstance(rows, list) or len(rows) > limit:
        raise AlphaError('The provider returned an invalid or oversized post page.', 502)
    if next_cursor is not None and (not isinstance(next_cursor, str) or not re.fullmatch(r'[A-Za-z0-9_.~=-]{1,2048}', next_cursor)):
        raise AlphaError('The provider returned an invalid pagination cursor.', 502)
    if next_cursor is not None and next_cursor == cursor:
        raise AlphaError('The provider repeated a pagination cursor. No further coverage can be confirmed.', 502)
    posts, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        post_id = _text(row.get('id'), 300)
        text = _text(row.get('caption') if adapter.id == 'instagram' else row.get('commentary'))
        if not post_id or not text or post_id in seen:
            continue
        if adapter.id == 'linkedin' and (row.get('author') != account_id or row.get('lifecycleState') != 'PUBLISHED' or row.get('reshareContext')):
            continue
        owner = row.get('owner')
        if adapter.id == 'instagram' and owner and (not isinstance(owner, dict) or str(owner.get('id')) != account_id):
            continue
        published = _text(row.get('timestamp'), 80)
        if published:
            try:
                parsed = datetime.fromisoformat(published.replace('Z', '+00:00'))
                published = parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else ''
            except ValueError:
                published = ''
        if adapter.id == 'linkedin' and type(row.get('publishedAt')) is int:
            try:
                published = datetime.fromtimestamp(row['publishedAt'] / 1000, timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                pass
        permalink = _public_url(row.get('permalink'), ('instagram.com',)) if adapter.id == 'instagram' else 'https://www.linkedin.com/feed/update/' + quote(post_id, safe=':')
        thumbnail = _public_url(row.get('thumbnail_url') or (row.get('media_url') if row.get('media_type') == 'IMAGE' else None), ('cdninstagram.com', 'fbcdn.net')) if adapter.id == 'instagram' else None
        media_type = _text(row.get('media_type'), 50) if adapter.id == 'instagram' else 'POST'
        posts.append({'id': post_id, 'externalPostId': post_id, 'provider': adapter.id, 'providerAccountId': account_id,
                      'text': text, 'publishedAt': published, 'permalink': permalink, 'thumbnailUrl': thumbnail,
                      'mediaType': media_type or 'UNKNOWN', 'platform': adapter.platform})
        seen.add(post_id)
    dates = sorted(post['publishedAt'] for post in posts if post['publishedAt'])
    coverage = {'startedFromBeginning': cursor is None, 'endReached': next_cursor is None,
                'from': dates[0] if dates else None, 'to': dates[-1] if dates else None,
                'undatedCount': sum(not post['publishedAt'] for post in posts), 'eligibleCount': len(posts)}
    return {'posts': posts, 'nextCursor': next_cursor, 'scannedCount': len(rows), 'skippedCount': len(rows) - len(posts),
            'partialCoverage': cursor is not None or next_cursor is not None, 'coverage': coverage,
            'coverageNote': 'Coverage refers only to retrieved eligible captions. Empty captions, duplicates and ineligible posts are excluded; a final page alone does not prove complete account coverage.'}


def seal_page(vault, binding, page, now):
    payload = {'schema': 'rafii.owned-post-selection.v1', 'binding': binding, 'page': page, 'issuedAt': now, 'expiresAt': now + RECEIPT_TTL}
    encrypted, key = vault.encrypt(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    receipt = key + '.' + encrypted
    if len(receipt) > MAX_RECEIPT:
        raise AlphaError('The selected page is too large. Load fewer posts.', 413)
    return receipt


def open_page(vault, receipt, binding, now):
    try:
        if not isinstance(receipt, str) or len(receipt) > MAX_RECEIPT:
            raise ValueError()
        key, encrypted = receipt.split('.', 1)
        if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', encrypted) or base64.urlsafe_b64encode(base64.urlsafe_b64decode(encrypted)).decode() != encrypted:
            raise ValueError()
        data = json.loads(vault.decrypt(encrypted, key))
        if data.get('schema') != 'rafii.owned-post-selection.v1' or data.get('binding') != binding or not data['issuedAt'] - 30 <= now < data['expiresAt']:
            raise ValueError()
        if not isinstance(data.get('page'), dict):
            raise ValueError()
        return data['page']
    except (ValueError, KeyError, TypeError, AlphaError) as error:
        raise AlphaError('This post selection expired or the account changed. Load the posts again.', 409) from error


def revoke_connection_samples(state, connection_id, actor, now):
    """Revoke only officially imported samples from this connection, never manual text."""
    from . import voice_sources
    ids = [source['id'] for source in state.get('sources', []) if source.get('kind') == 'voice_sample' and source.get('active')
           and source.get('voiceOrigin') == 'official_api' and source.get('connectionId') == connection_id]
    for source_id in ids:
        voice_sources.apply_action(state, 'voice_sample_revoke', {'sourceId': source_id, 'confirmed': True}, actor, now)
    return len(ids)


class SocialHistoryService:
    def __init__(self, oauth):
        self.oauth = oauth
        self.repository, self.clock = oauth.repository, oauth.clock

    def _binding(self, cur, workspace_id, actor, connection_id):
        cur.execute('SELECT provider,provider_account_id,access_ciphertext,key_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL', (workspace_id, connection_id))
        row = cur.fetchone()
        if not row:
            raise AlphaError('Connection unavailable.', 404)
        provider, account, ciphertext, key = row
        return {'workspace': workspace_id, 'actor': actor, 'connection': connection_id, 'account': account, 'provider': provider,
                'credential': hashlib.sha256(self.oauth.vault.decrypt(ciphertext, key).encode()).hexdigest()}

    def _current(self, workspace_id, token, connection_id, throttle_read=False):
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError('An interactive sign-in is required to import social history.', 403)
        from .hosted import _membership, throttle
        from .permissions import require
        with self.repository.transaction(token, workspace_id) as (cur, row, actor):
            require(_membership(row), 'manage_connections')
            if throttle_read:
                throttle(cur, f'social-history:{workspace_id}:{actor}', 30, 300)
            return self._binding(cur, workspace_id, actor, connection_id)

    def _access(self, workspace_id, token, connection_id):
        binding = self._current(workspace_id, token, connection_id, throttle_read=True)
        adapter = self.oauth._provider(binding['provider'])
        if not adapter.capability_scopes('posts_read'):
            raise AlphaError('Historical-post access is unavailable for this app. You can still paste your own writing samples.', 409, code='history_approval_required')
        grant = self.oauth.token_for_worker(workspace_id, connection_id)
        if adapter.id == 'linkedin' and 'r_member_social' not in grant['scopes']:
            raise AlphaError('LinkedIn has not granted r_member_social to this connection. Reconnect with approved read access, or paste your own posts.', 409, code='history_permission_required')
        identity = adapter.identity(grant['accessToken'])
        if identity['providerAccountId'] != binding['account']:
            raise AlphaError('The social account identity changed. Reconnect it.', 409)
        binding['credential'] = hashlib.sha256(grant['accessToken'].encode()).hexdigest()
        if self._current(workspace_id, token, connection_id) != binding:
            raise AlphaError('The connection changed. Load it again.', 409)
        return adapter, grant, binding

    def preview(self, workspace_id, token, connection_id, payload):
        if payload.get('confirmed') is not True:
            raise AlphaError('Confirm reading this connected account for the sample picker.', 400)
        adapter, grant, binding = self._access(workspace_id, token, connection_id)
        page = fetch_page(adapter, grant['accessToken'], binding['account'], payload.get('cursor'), payload.get('limit', PAGE_LIMIT))
        if self._current(workspace_id, token, connection_id) != binding:
            raise AlphaError('The connection changed while reading. Load it again.', 409)
        return {**page, 'connectionId': connection_id, 'providerAccountId': binding['account'], 'receipt': seal_page(self.oauth.vault, binding, page, self.clock()), 'expiresAt': self.clock() + RECEIPT_TTL}

    def retain(self, workspace_id, token, connection_id, payload):
        from . import voice_sources
        if payload.get('confirmedAuthorship') is not True:
            raise AlphaError('Confirm that the selected writing is yours and may be retained as samples.', 400)
        selections = payload.get('selections', [{'receipt': payload.get('receipt'), 'postIds': payload.get('postIds')}])
        if not isinstance(selections, list) or not 1 <= len(selections) <= 4:
            raise AlphaError('Select from at most four verified pages per import.')
        ids = []
        for selection in selections:
            chosen = selection.get('postIds') if isinstance(selection, dict) else None
            if not isinstance(chosen, list) or not 1 <= len(chosen) <= PAGE_LIMIT or any(not isinstance(value, str) for value in chosen) or len(set(chosen)) != len(chosen):
                raise AlphaError('Select between 1 and 25 distinct posts from each page.')
            ids.extend(chosen)
        ids = list(dict.fromkeys(ids))
        if len(ids) > voice_sources.MAX_RECORDS:
            raise AlphaError('Retain at most 50 distinct samples at once.')
        labels = payload.get('labels', {})
        if not isinstance(labels, dict) or set(labels) - set(ids) or any(not isinstance(label, str) or label not in voice_sources.LABELS for label in labels.values()):
            raise AlphaError('Choose a supported writing classification for selected posts only.')
        adapter, grant, binding = self._access(workspace_id, token, connection_id)
        by_id, coverages = {}, {}
        for selection in selections:
            page = open_page(self.oauth.vault, selection.get('receipt'), binding, self.clock())
            available = {post['id']: post for post in page['posts']}
            if set(selection['postIds']) - available.keys():
                raise AlphaError('A selected post was not in its verified page.', 409)
            for post_id in selection['postIds']:
                if post_id in by_id and by_id[post_id] != available[post_id]:
                    raise AlphaError('A repeated post changed between pages. Reload before retaining it.', 409)
                by_id[post_id] = available[post_id]
                coverages[post_id] = page.get('coverage', {})
        if adapter.id == 'instagram':
            # Recheck current read permission; a locally retained token is not proof.
            fetch_page(adapter, grant['accessToken'], binding['account'], limit=1)
        def retain(state, actor):
            records = [{'externalId': post_id, 'text': by_id[post_id]['text'], 'platform': adapter.platform, 'account': binding['account'],
                        'title': f"{adapter.platform} post {post_id}", 'publishedAt': by_id[post_id]['publishedAt'], 'partialCoverage': True,
                        **({'label': labels[post_id]} if post_id in labels else {})} for post_id in ids]
            result = voice_sources.apply_action(state, 'voice_samples_import', {'format': 'json', 'records': records}, actor, self.clock())
            touched = set(result['imported'] + result['revised'])
            for source in state.get('sources', []):
                if source['id'] in touched:
                    post_id = source['externalId']
                    post = by_id[post_id]
                    source.update(voiceOrigin='official_api', connectionId=connection_id, providerAccountId=binding['account'], authoredByConfirmed=actor,
                                  provider=adapter.id, externalPostId=post_id, permalink=post.get('permalink'), mediaType=post.get('mediaType', 'UNKNOWN'),
                                  thumbnailUrl=post.get('thumbnailUrl'), importedAt=self.clock(),
                                  sourceCoverage={'selectionOnly': True, 'verifiedPages': len(selections), 'providerPage': coverages[post_id]})
            self.oauth.commands.engine.invalidate(state)
            return state
        def recheck(cur, _state, actor):
            if self._binding(cur, workspace_id, actor, connection_id) != binding:
                raise AlphaError('The connection changed before retention. Load the posts again.', 409)
        return self.repository.command(workspace_id, token, payload.get('expectedRevision'), retain, requirement='manage_connections', after=recheck,
                                       audit_event=lambda state: ('voice.social_samples_retained', connection_id, {'selectedCount': len(ids), 'provider': adapter.id}))
