"""Mastodon publication steps fenced by the existing durable Queue job.

Only a committed intent may precede a write. An interrupted write with no saved
provider ID is never repeated; known media IDs are polled without re-uploading.
"""
import copy
import hashlib
import html
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from postriff_alpha.domain import AlphaError
from .mastodon_protocol import discover, validate_status
from .social_connectors import multipart

SAFE_STAGES = ('media_wait', 'rate_wait')
STAGES = (*SAFE_STAGES, 'media_upload_attempted', 'publish_attempted', 'provider_accepted', 'native_scheduled')


class LocalCooldown(Exception):
    def __init__(self, receipt):
        self.receipt = receipt


def can_resume(job):
    if job.get('manifest', {}).get('platform') != 'Mastodon' or job.get('state') not in ('submitting', 'processing', 'scheduled'):
        return False
    try:
        return checked_progress(job.get('progress'), job['manifest'])['stage'] in SAFE_STAGES
    except AlphaError:
        return False


def approved_bytes(social, manifest, asset):
    storage = social.assets.storage
    name = asset.get('objectName') or asset['id']
    if asset.get('normalizedLibrary'):
        return storage.get_bounded(manifest['workspaceId'], 'file', name, asset['bytes'])
    if str(asset.get('mime', '')).startswith('video/'):
        return storage.get_verified_video(manifest['workspaceId'], name, expected_bytes=asset['bytes'],
            expected_mime=asset['mime'], expected_etag=asset['etag'])
    return storage.get(manifest['workspaceId'], 'media', name)


def native_reconcile(provider, token, manifest, job, now):
    """Read an accepted server schedule; absence alone never proves publication."""
    progress = checked_progress(job['progress'], manifest)
    session = provider.session(token)
    reference = progress['reference']
    expected = manifest.get('publishOptions') or {}
    response = provider.api(session, 'GET', '/api/v1/scheduled_statuses/' + reference)
    data = response.get('body') if isinstance(response.get('body'), dict) else {}
    params = data.get('params') if isinstance(data.get('params'), dict) else {}
    if response.get('status') == 200:
        try:
            same_time = abs(datetime.fromisoformat(str(data.get('scheduled_at')).replace('Z', '+00:00')).timestamp()
                - datetime.fromisoformat(progress['scheduledAt'].replace('Z', '+00:00')).timestamp()) < 1
        except (ValueError, TypeError, KeyError): same_time = False
        if (str(data.get('id')) == reference and same_time and params.get('text') == manifest['payload']['text']
                and params.get('visibility') == expected.get('visibility', 'public')
                and (params.get('spoiler_text') or '') == expected.get('spoiler_text', '')
                and [str(i) for i in params.get('media_ids') or []] == [a['id'] for a in progress['attachments']]):
            progress['retryAt'] = now + 60
            return {'state': 'processing', 'reference': reference, 'progress': progress, 'verification': 'provider_lookup',
                    'confirmed': 'The exact server schedule is pending. A saved schedule is not a published post.'}
        return {'state': 'uncertain', 'reference': reference, 'confirmed': 'The server schedule changed after approval; check it manually. Nothing was resubmitted.'}
    if response.get('status') != 404 or not progress['attachments']:
        return {'state': 'uncertain', 'reference': reference, 'confirmed': 'Native schedule lookup is unavailable or the schedule disappeared. Absence does not prove publication; check Mastodon before any new post.'}
    account_id, host = manifest['providerAccountId'].split('@', 1)
    response = provider.api(session, 'GET', '/api/v1/accounts/' + account_id + '/statuses?limit=40&exclude_reblogs=true')
    rows = response.get('body')
    if response.get('status') != 200 or not isinstance(rows, list):
        return {'state': 'uncertain', 'reference': reference, 'confirmed': 'Native publication read-back is unavailable. No replacement post was sent.'}
    matched = []
    for row in rows[:40]:
        if not isinstance(row, dict): continue
        plain = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>|</p>\s*<p>', ' ', str(row.get('content', ''))))).split())
        try:
            created = datetime.fromisoformat(str(row.get('created_at')).replace('Z', '+00:00')).timestamp()
            due = datetime.fromisoformat(progress['scheduledAt'].replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError): continue
        if (str((row.get('account') or {}).get('id')) == account_id and due - 60 <= created <= now + 60
                and plain == ' '.join(manifest['payload']['text'].split())
                and row.get('visibility') == expected.get('visibility', 'public')
                and row.get('spoiler_text', '') == expected.get('spoiler_text', '')
                and [str(a.get('id')) for a in row.get('media_attachments') or [] if isinstance(a, dict)] == [a['id'] for a in progress['attachments']]
                and re.fullmatch(r'[0-9]{1,40}', str(row.get('id', '')))):
            matched.append(row)
    if len(matched) == 1:
        row = matched[0]
        progress.update(stage='provider_accepted', reference=str(row['id']))
        progress.pop('retryAt', None)
        result = {'state': 'verified', 'reference': str(row['id']), 'progress': progress, 'verification': 'provider_lookup',
                  'confirmed': 'Account read-back found the exact approved media IDs, content and visibility after the server schedule disappeared. Fediverse delivery is not guaranteed.'}
        from .outcomes import valid_receipt_url
        if valid_receipt_url(row.get('url'), 'Mastodon', manifest['providerAccountId']): result['url'] = row['url']
        return result
    return {'state': 'uncertain', 'reference': reference, 'confirmed': 'No unique publication matched the saved native media and approved content in the latest 40 posts. Check Mastodon; do not resubmit.'}


def checked_progress(value, manifest):
    if (not isinstance(value, dict) or value.get('version') != 3 or value.get('stage') not in STAGES
            or set(value) - {'version', 'stage', 'attachments', 'retryAt', 'retryCount', 'reference', 'scheduledAt'}):
        raise AlphaError('Invalid durable Mastodon progress.', 409)
    attachments = value.get('attachments')
    approved = manifest.get('media') or []
    if not isinstance(attachments, list) or len(attachments) != len(approved) or len(attachments) > 4:
        raise AlphaError('Mastodon progress does not match the approved attachments.', 409)
    for item, asset in zip(attachments, approved):
        if (not isinstance(item, dict) or set(item) != {'hash', 'state', 'id'} or item['hash'] != asset.get('hash')
                or not re.fullmatch(r'[a-f0-9]{64}', str(item['hash']))
                or item['state'] not in ('pending', 'attempted', 'uploaded', 'ready')
                or (item['state'] in ('uploaded', 'ready') and not re.fullmatch(r'[0-9]{1,40}', str(item['id'])))
                or (item['state'] in ('pending', 'attempted') and item['id'] is not None)):
            raise AlphaError('Invalid Mastodon media custody progress.', 409)
    retry_at = value.get('retryAt')
    if retry_at is not None and (type(retry_at) not in (int, float) or not math.isfinite(retry_at) or retry_at < 0):
        raise AlphaError('Invalid Mastodon retry time.', 409)
    count = value.get('retryCount', 0)
    if type(count) is not int or not 0 <= count <= 20:
        raise AlphaError('Invalid Mastodon retry count.', 409)
    if value.get('reference') is not None and not re.fullmatch(r'[0-9]{1,40}', str(value['reference'])):
        raise AlphaError('Invalid Mastodon resource reference.', 409)
    if value['stage'] in ('provider_accepted', 'native_scheduled') and not value.get('reference'):
        raise AlphaError('Mastodon acceptance needs a saved resource ID.', 409)
    if value.get('scheduledAt') is not None:
        try:
            parsed = datetime.fromisoformat(value['scheduledAt'].replace('Z', '+00:00'))
            if parsed.tzinfo is None: raise ValueError('timezone')
        except (TypeError, ValueError):
            raise AlphaError('Invalid native Mastodon schedule.', 409)
    if value['stage'] in SAFE_STAGES and any(a['state'] == 'attempted' for a in attachments):
        raise AlphaError('An unresolved media write cannot resume automatically.', 409)
    if value['stage'] in ('publish_attempted', 'provider_accepted', 'native_scheduled') and any(a['state'] != 'ready' for a in attachments):
        raise AlphaError('Mastodon publication needs all approved media ready.', 409)
    return copy.deepcopy(value)


def backoff(response, now, count, key):
    """Honor both standard and Mastodon retry headers, with a bounded fallback."""
    headers = {str(k).lower(): str(v) for k, v in (response.get('headers') or {}).items()}
    waits = [min(1800, 15 * 2 ** min(count, 7))]
    for name in ('retry-after', 'x-ratelimit-reset'):
        raw = headers.get(name, '')
        if len(raw) > 80: continue
        try:
            if name == 'retry-after' and raw.isdigit():
                seconds = int(raw)
            else:
                try: instant = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                except ValueError: instant = parsedate_to_datetime(raw)
                if instant.tzinfo is None: raise ValueError('timezone')
                seconds = instant.timestamp() - now
            if math.isfinite(seconds): waits.append(seconds)
        except (ValueError, TypeError, OverflowError): pass
    jitter = int(hashlib.sha256((key + str(count)).encode()).hexdigest()[:4], 16) % 5
    return now + min(604800, max(1, max(waits)) + jitter)


def advance(social, manifest, job, checkpoint, now):
    provider = social._provider(manifest)
    if provider is None:
        return {'state': 'held', 'confirmed': 'Mastodon publishing is unavailable. Nothing was sent.'}
    grant = social.oauth.token_for_worker(manifest['workspaceId'], manifest['channelId'])
    required = set(provider.publish_required)
    if not required.issubset(grant.get('scopes', [])):
        return {'state': 'held', 'confirmed': 'Reconnect with the approved publishing permissions.'}
    session = provider.session(grant['accessToken'])
    expected_host = str(manifest.get('providerAccountId', '')).rsplit('@', 1)[-1]
    if session['instance'] != expected_host:
        return {'state': 'held', 'confirmed': 'The connected Mastodon instance changed; prepare a fresh review.'}
    progress = job.get('progress')
    progress = checked_progress(progress, manifest) if progress else {
        'version': 3, 'stage': 'media_wait', 'attachments': [
            {'hash': a['hash'], 'state': 'pending', 'id': None} for a in manifest.get('media', [])], 'retryCount': 0}

    def save(stage, external=False):
        progress['stage'] = stage
        checked_progress(progress, manifest)
        try:
            checkpoint(copy.deepcopy(progress), before_external=external)
        except AlphaError as error:
            if not external or error.status != 429: raise
            # The transaction refused BEFORE dispatch. It is safe to restore this
            # unsent intent and wait; known media IDs remain attached to the job.
            for item in progress['attachments']:
                if item['state'] == 'attempted': item['state'] = 'pending'
            progress.update(stage='rate_wait', retryAt=now() + 300, retryCount=min(20, progress.get('retryCount', 0) + 1))
            checkpoint(copy.deepcopy(progress), before_external=False)
            raise LocalCooldown({'state': 'processing', 'progress': copy.deepcopy(progress),
                                 'confirmed': 'Rafii’s per-account or per-instance safety budget deferred this unsent write for five minutes.'}) from None

    def result(state, message):
        return {'state': state, 'confirmed': message, 'progress': copy.deepcopy(progress),
                **({'reference': progress['reference']} if progress.get('reference') else {})}

    def wait(response, message):
        count = progress.get('retryCount', 0)
        if count >= 20:
            return result('held', 'Mastodon processing or throttling exceeded bounded checks; review the existing media before continuing.')
        progress.update(retryCount=count + 1, retryAt=backoff(response, now(), count, manifest['idempotencyKey']))
        save('rate_wait' if response.get('status') == 429 else 'media_wait')
        if progress['retryAt'] > now() + 3600:
            return result('held', 'The instance requires a longer cooldown; automatic writes are stopped. Review after its retry time.')
        return result('processing', message)

    if progress['stage'] in ('provider_accepted', 'native_scheduled'):
        return result('provider_accepted', 'The saved Mastodon resource is awaiting read-back; no new publication was sent.')
    if progress['stage'] not in SAFE_STAGES:
        return result('uncertain', 'A prior Mastodon write has an unresolved outcome; check the account before any new upload or publication.')
    if progress.get('retryAt', 0) > now():
        return result('processing', 'Waiting for the Mastodon processing or rate-limit retry time; nothing new was sent.')
    caps = discover(provider.transport, session['instance'])
    body = validate_status(manifest['payload']['text'], manifest.get('publishOptions') or {}, manifest.get('media') or [], caps, now=now())
    for index, asset in enumerate(manifest.get('media') or []):
        item = progress['attachments'][index]
        if item['state'] == 'ready': continue
        if item['state'] == 'uploaded':
            response = provider.api(session, 'GET', '/api/v1/media/' + item['id'])
            data = response.get('body') if isinstance(response.get('body'), dict) else {}
            if response.get('status') == 200 and str(data.get('id')) == item['id'] and data.get('url'):
                item['state'] = 'ready'; save('media_wait'); continue
            if response.get('status') in (401, 403, 404, 410, 422):
                return result('held', 'Mastodon media is unavailable or permission was revoked; review before continuing. No re-upload was sent.')
            return wait(response, 'The same Mastodon media ID is still processing; publication has not started.')
        if social.assets is None:
            return result('held', 'Media storage unavailable. Nothing was uploaded.')
        mime = str(asset.get('mime') or '')
        limits = caps.get('media', {})
        formats = limits.get('supported_mime_types')
        if not mime.startswith(('image/', 'video/', 'audio/')) or (formats is not None and mime not in formats):
            return result('held', 'This Mastodon instance does not support the approved media format.')
        # Renew the fenced lease and recheck approval before reading bounded private bytes.
        save('media_wait', external=True)
        raw = approved_bytes(social, manifest, asset)
        maximum = limits.get('image_size_limit' if mime.startswith('image/') else 'audio_size_limit' if mime.startswith('audio/') else 'video_size_limit', 40_000_000)
        if (len(raw) != asset.get('bytes') or hashlib.sha256(raw).hexdigest() != asset.get('hash')
                or type(maximum) is not int or len(raw) > maximum):
            return result('held', 'The approved attachment changed or exceeds this instance’s limit. Nothing was uploaded.')
        item['state'] = 'attempted'; save('media_upload_attempted', external=True)
        form, content_type = multipart([('description', asset.get('alt', ''))], [('file', 'attachment', mime, raw)])
        response = provider.api(session, 'POST', '/api/v2/media', headers={'Content-Type': content_type}, data=form)
        # A definitive route-not-found rejection permits the older official endpoint.
        if response.get('status') == 404:
            save('media_upload_attempted', external=True)
            response = provider.api(session, 'POST', '/api/v1/media', headers={'Content-Type': content_type}, data=form)
        data = response.get('body') if isinstance(response.get('body'), dict) else {}
        media_id = str(data.get('id', ''))
        if response.get('status') == 429:
            item['state'] = 'pending'
            return wait(response, 'The instance rejected this upload due to throttling; resume after its retry time.')
        if response.get('status') in (400, 401, 403, 422):
            item['state'] = 'pending'; save('media_wait')
            return result('held', 'Mastodon rejected the media or publishing permission; correct it and review again.')
        if response.get('status') not in (200, 202) or not re.fullmatch(r'[0-9]{1,40}', media_id):
            return result('uncertain', 'The upload outcome is unknown. Automatic re-upload is stopped; no post was sent.')
        item.update(id=media_id, state='ready' if response.get('status') == 200 and data.get('url') else 'uploaded')
        save('media_wait')
        if item['state'] == 'uploaded':
            return wait({}, 'Mastodon accepted the media; its saved ID will be polled by the next worker.')
    progress.pop('retryAt', None)
    save('publish_attempted', external=True)
    response = provider.api(session, 'POST', '/api/v1/statuses',
        headers={'Idempotency-Key': hashlib.sha256(manifest['idempotencyKey'].encode()).hexdigest()},
        body={**body, 'media_ids': [a['id'] for a in progress['attachments']]})
    data = response.get('body') if isinstance(response.get('body'), dict) else {}
    status_id = str(data.get('id', ''))
    if response.get('status') == 200 and re.fullmatch(r'[0-9]{1,40}', status_id):
        progress['reference'] = status_id
        if body.get('scheduled_at'):
            progress['scheduledAt'] = body['scheduled_at']; save('native_scheduled')
        else: save('provider_accepted')
        return result('provider_accepted', 'Mastodon accepted the exact approved operation; provider read-back is pending.')
    if response.get('status') == 429:
        return wait(response, 'Mastodon rejected publication due to throttling; no status was accepted. Resume after its retry time.')
    if response.get('status') in (400, 401, 403, 422):
        save('media_wait')
        return result('held', 'Mastodon rejected the post or permissions. Review before another publication attempt.')
    return result('uncertain', 'Mastodon publication may have happened; the committed write intent prevents automatic resubmission.')
