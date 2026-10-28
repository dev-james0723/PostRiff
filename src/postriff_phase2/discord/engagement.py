"""Consent-bound Discord REST engagement. No Gateway, privileged intents or model egress.

Provider messages are returned only to the consenting member and are never stored.
Workspace state keeps minimal consent, cooldown and exact human reply manifests;
replies use the existing fenced Discord publication worker, never AudienceService's
direct sender. Native server snapshots and bounded derived metrics remain separate.
"""
import copy
import json
import math
import uuid
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError
from ..agent_runtime_v2.authz import human_only
from ..contracts import resolve_time
from ..permissions import Membership, require
from . import authorization as auth
from . import message_content

KEY = 'discordEngagement'
SCHEMA = 'rafii.discord.engagement.v1'
REPLY_SCHEMA = 'rafii.discord.reply.v1'
KINDS = ('analytics', 'inbox', 'reply')
CONSENT_SECONDS = 30 * 86400
REVIEW_SECONDS = 600
READ_COOLDOWN = 15
PAGE_SIZE = 50
MAX_POSTS = 10
LIMITS = {
    'messageContentIntent': 'off_unless_separately_approved', 'gateway': False,
    'inbox': 'Latest 50 messages in the approved text or announcement channel only. Limited mode shows replies to Rafii-managed messages and bot mentions; Discord may withhold text. Extended channel text needs provider access and separate personal consent.',
    'analytics': 'Approximate server counts are native snapshots. Reactions and observed replies cover at most 10 Rafii-managed messages; reply counts are a lower bound in the latest page, never total engagement.',
    'unavailable': ['impressions', 'reach', 'unique people', 'server Insights', 'all-time reply totals', 'threads and DMs'],
    'retention': 'Incoming message text, author profiles and reaction-user lists are not retained. Reply approvals retain the parent message/author IDs and a content digest. Consent lasts 30 days; unapproved reviews expire after 10 minutes.',
    'broaderAccess': 'Extended channel text is implemented behind an expiring app-specific approval record and a fresh Discord Application intent-flag check, plus separate personal channel consent. The current intent-OFF mode cannot read general message text. Rafii never enables the intent here.',
}


def fail(message='Approve access to this exact Discord server and channel first.', code='discord_engagement_consent_required'):
    raise AlphaError(message, 409, code=code)


def root(state):
    return state.setdefault('phase2', {}).setdefault(KEY, {'consents': [], 'reviews': [], 'reads': {}})


def channel_for(state, connection):
    channel = next((c for c in state.get('phase2', {}).get('channels', [])
                    if c.get('id') == connection and c.get('platform') == 'Discord' and not c.get('revoked')), None)
    if not channel or not channel.get('identityVerified'):
        fail('This Discord connection is unavailable.', 'discord_connection_required')
    return channel


def target_for(state, connection, destination):
    record = auth.destination(state, channel_for(state, connection), destination)
    return {k: copy.deepcopy(record.get(k)) for k in auth.IDENTITY + auth.LABELS}


def target_digest(target):
    return auth.digest({'schema': SCHEMA, 'target': target})


def consent_for(state, actor, target, kind, now):
    consent = next((c for c in state.get('phase2', {}).get(KEY, {}).get('consents', [])
                    if c.get('actor') == actor and c.get('destinationId') == target['id']
                    and c.get('connectionId') == target['connectionId']), None)
    if (kind not in KINDS or not consent or consent.get('schema') != SCHEMA
            or consent.get('targetDigest') != target_digest(target)
            or consent.get('status') != 'granted' or consent.get('permissions', {}).get(kind) is not True
            or type(consent.get('expiresAt')) not in (int, float) or not math.isfinite(consent['expiresAt'])
            or consent['expiresAt'] <= now
            or kind == 'reply' and consent.get('permissions', {}).get('inbox') is not True):
        fail()
    return consent


def reply_current(state, manifest, now):
    """Pure worker/engine fence. A new consent can never resurrect an old reply."""
    try:
        if manifest.get('schema') != REPLY_SCHEMA or manifest.get('operation') != 'discord.reply':
            return False
        target = target_for(state, manifest['channelId'], manifest['destinationId'])
        consent = consent_for(state, manifest['actor'], target, 'reply', now)
        binding = manifest['engagementReply']
        return (manifest['workspaceId'] == state['workspace']['id']
                and consent['id'] == binding['consentId']
                and consent.get('contentAccess', 'mentions_only') == binding.get('contentAccess', 'mentions_only')
                and consent.get('contentEvidenceDigest') == binding.get('contentEvidenceDigest')
                and manifest['providerAccountId'] == target['guildId']
                and manifest['platform'] == 'Discord' and manifest.get('media') == []
                and auth.snowflake(binding['parentMessageId']) and auth.snowflake(binding['parentAuthorId'])
                and isinstance(binding['parentContentDigest'], str) and len(binding['parentContentDigest']) == 64
                and binding['textDigest'] == auth.digest(manifest['payload']['text'])
                and manifest['actor'] == binding['reviewedBy']
                and manifest['timing']['timestamp'] + REVIEW_SECONDS <= consent['expiresAt'])
    except (AlphaError, KeyError, TypeError, ValueError):
        return False


def metric(value, *, source, definition, lower_bound=False):
    valid = type(value) is int and value >= 0
    return {'value': value if valid else None, 'availability': 'available' if valid else 'unavailable',
            'source': source, 'definition': definition, 'lowerBound': lower_bound}


def validate_parent(manifest, body):
    """Fresh provider proof before a reply write; a changed parent needs review."""
    target, reply = manifest['discord']['target'], manifest['engagementReply']
    mentions = body.get('mentions') if isinstance(body.get('mentions'), list) else []
    if (body.get('id') != reply['parentMessageId'] or body.get('channel_id') != target['channelId']
            or body.get('guild_id', target['guildId']) != target['guildId']
            or (body.get('author') or {}).get('id') != reply['parentAuthorId']
            or body.get('type', 0) not in (0, 19) or not isinstance(body.get('content'), str) or not body['content']
            or (reply.get('contentAccess', 'mentions_only') != 'approved_content'
                and not any(isinstance(m, dict) and m.get('id') == target['botUserId'] for m in mentions))
            or auth.digest(body['content']) != reply['parentContentDigest']):
        fail('The Discord parent message changed or its content is restricted. Prepare a new exact reply review.', 'discord_reply_parent_changed')


def managed_messages(state, target):
    found = {}
    for job in reversed(state.get('phase2', {}).get('jobs', [])):
        manifest = job.get('manifest') or {}
        original = (manifest.get('discord') or {}).get('target') or {}
        reference = job.get('providerReference')
        if (job.get('state') != 'verified' or job.get('privacyErased') or manifest.get('privacyErased')
                or manifest.get('platform') != 'Discord' or manifest.get('workspaceId') != target['workspaceId']
                or manifest.get('channelId') != target['connectionId']
                or any(original.get(k) != target.get(k) for k in ('applicationId', 'botUserId', 'guildId', 'channelId'))
                or not isinstance(reference, str)):
            continue
        channel, _, message = reference.partition('/')
        if channel == target['channelId'] and auth.snowflake(message):
            found.setdefault(message, job['id'])
        if len(found) >= MAX_POSTS:
            break
    return found


def message_view(item, target, managed, *, extended=False):
    """Filter before returning data; unrelated server messages never reach the UI."""
    if (not isinstance(item, dict) or item.get('channel_id') != target['channelId']
            or item.get('guild_id', target['guildId']) != target['guildId'] or not auth.snowflake(item.get('id'))):
        return None
    author = item.get('author') if isinstance(item.get('author'), dict) else {}
    if not auth.snowflake(author.get('id')) or author['id'] == target['botUserId']:
        return None
    reference = item.get('message_reference') if isinstance(item.get('message_reference'), dict) else {}
    parent = reference.get('message_id')
    referenced = (reference.get('type', 0) == 0 and parent in managed
                  and reference.get('channel_id', target['channelId']) == target['channelId']
                  and reference.get('guild_id', target['guildId']) == target['guildId'])
    mentions = item.get('mentions') if isinstance(item.get('mentions'), list) else []
    mentioned = any(isinstance(m, dict) and m.get('id') == target['botUserId'] for m in mentions)
    if not referenced and not mentioned and not extended:
        return None
    content = item.get('content')
    readable = (mentioned or extended) and isinstance(content, str) and bool(content)
    # No inference from an empty content field: it can mean withheld content.
    return {'id': item['id'], 'parentMessageId': parent if referenced else None,
            'content': content[:2000] if readable else None,
            'contentAvailability': ('visible_approved_content' if extended else 'visible_bot_mention') if readable else 'restricted',
            'author': str(author.get('username') or author['id'])[:100] if readable else None,
            'replyable': readable and item.get('type', 0) in (0, 19),
            'url': f"https://discord.com/channels/{target['guildId']}/{target['channelId']}/{item['id']}"}


def annotate_capabilities(views, state, actor, now, provider):
    """Availability is consent-scoped, not implied by a bot scope or a UI label."""
    enabled = ready(provider)
    for view in views:
        if view.get('platform') != 'Discord':
            continue
        view['discordEngagement'] = {'implemented': True, 'enabled': enabled, 'limits': copy.deepcopy(LIMITS)}
        if not enabled or view.get('connectionState') in ('disconnected', 'revoked'):
            continue
        for capability, kind, evidence in (
                ('analytics', 'analytics', 'Native approximate server counts plus reactions and bounded observed replies on Rafii-managed messages. No impressions or reach.'),
                ('comments_read', 'inbox', 'Partial REST inbox: replies to Rafii-managed messages and bot mentions. Discord may withhold message content.'),
                ('reply', 'reply', 'Each exact text, parent message, channel and time needs your own approval. No automatic replies.')):
            granted = False
            for destination in next((c.get('discordDestinations', []) for c in state.get('phase2', {}).get('channels', []) if c.get('id') == view['id']), []):
                try:
                    target = target_for(state, view['id'], destination['id'])
                    consent_for(state, actor, target, kind, now)
                    granted = True
                except (AlphaError, KeyError, TypeError):
                    pass
            view['capabilities'][capability] = {
                'level': 'Direct' if granted else 'Assisted', 'availability': 'scoped' if granted else 'consent_required',
                'evidence': evidence + ('' if granted else ' Approve access for an exact channel in Discord analytics & conversations.'),
                'capabilityVersion': 2, 'verifiedAt': now if granted else None}


def ready(provider):
    return bool(provider and getattr(provider, 'engagement_v1_enabled', False)
                and getattr(provider, 'authorization_v2_enabled', False)
                and getattr(provider, 'connections_v2_enabled', False)
                and getattr(provider, 'rate_v1_enabled', False)
                and getattr(provider, 'production_reviewed', False) and getattr(provider, 'execution_enabled', True)
                and getattr(provider, 'rate_limiter', None) is not None
                and not getattr(provider, 'rate_coordinator_degraded', False))


class DiscordEngagementService:
    def __init__(self, repository, oauth, commands, clock):
        self.repository, self.oauth, self.commands, self.clock = repository, oauth, commands, clock

    @property
    def provider(self):
        return self.oauth.providers.get('discord')

    def _enabled(self):
        if not ready(self.provider):
            fail('Discord engagement is paused until its independently approved rollout and shared rate coordinator are ready.', 'discord_engagement_disabled')

    @staticmethod
    def _state(row):
        return json.loads(row[1]) if isinstance(row[1], str) else copy.deepcopy(row[1])

    def _gate(self, cur, state, actor, connection, destination, kind, expected=None):
        self._enabled()
        target = target_for(state, connection, destination)
        consent = consent_for(state, actor, target, kind, self.clock())
        if expected and (target != expected['target'] or consent['id'] != expected['consent']['id']):
            fail('Discord access changed during this request. Review the channel and consent again.')
        message_content.assert_binding(self.provider, target, consent, self.clock())
        grant = self.oauth.discord_grant_for_worker(target['workspaceId'], connection, cur=cur)
        if not auth.grant_matches({'discord': {'target': target}}, grant, self.provider.session(grant['accessToken'])):
            fail('Discord installation or credential origin changed.', 'discord_connection_required')
        return {'target': target, 'consent': consent, 'grant': grant}

    def _context(self, workspace, token, connection, destination, kind, expected=None):
        human_only(token)
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(Membership.from_row(*row[2:7]), 'reply' if kind == 'reply' else 'read')
            state = self._state(row)
            context = self._gate(cur, state, actor, connection, destination, kind, expected)
            return context, state, actor

    def _guard(self, workspace, token, connection, destination, kind, expected):
        def authorize():
            self._context(workspace, token, connection, destination, kind, expected)
            return True
        return authorize

    def _live(self, context, guard):
        provider, target = self.provider, context['target']
        evidence = provider.authorize_destination(context['grant']['accessToken'], target, read_authorize=guard)
        if not evidence.get('userPermissions', 0) & provider.READ_HISTORY:
            fail('The linked Discord user needs Read Message History in this channel.', 'discord_read_permission_required')
        return message_content.verify(provider, target, context['consent'], guard, self.clock())

    def status(self, workspace, token, connection):
        human_only(token)
        with self.repository.transaction(token, workspace) as (_, row, actor):
            state = self._state(row)
            channel = channel_for(state, connection)
            targets = []
            for item in channel.get('discordDestinations', []):
                try:
                    target = target_for(state, connection, item['id'])
                except (AlphaError, KeyError, TypeError):
                    continue
                consent = next((c for c in state.get('phase2', {}).get(KEY, {}).get('consents', [])
                                if c.get('actor') == actor and c.get('destinationId') == target['id']), None)
                permissions = {}
                for kind in KINDS:
                    try:
                        consent_for(state, actor, target, kind, self.clock())
                        permissions[kind] = True
                    except AlphaError:
                        permissions[kind] = False
                extended_policy = message_content.policy(self.provider, self.clock())
                targets.append({'target': target, 'targetDigest': target_digest(target), 'permissions': permissions,
                                'contentAccess': (consent or {}).get('contentAccess', 'mentions_only'),
                                'broaderContentEligible': bool(extended_policy and extended_policy['botUserId'] == target['botUserId']),
                                'expiresAt': consent.get('expiresAt') if consent and any(permissions.values()) else None})
            jobs = [{'id': j['id'], 'state': j['state'], 'approvedAt': j['approvedAt'],
                     'parentMessageId': j['manifest']['engagementReply']['parentMessageId'],
                     'text': j['manifest']['payload']['text'], 'timing': j['manifest']['timing'],
                     'url': j.get('providerUrl'), 'cancelRequested': j.get('cancelRequested', False),
                     'approvalDigest': j['approvalDigest'], 'previewDispatchPending': j.get('previewDispatchPending', False)}
                    for j in state.get('phase2', {}).get('jobs', [])
                    if j.get('manifest', {}).get('operation') == 'discord.reply'
                    and j['manifest'].get('channelId') == connection and j.get('approvedBy') == actor]
            return {'implemented': True, 'enabled': ready(self.provider), 'destinations': targets,
                    'canReply': Membership.from_row(*row[2:7]).allows('reply'), 'jobs': jobs[-20:], 'limits': copy.deepcopy(LIMITS)}

    def consent(self, workspace, token, connection, payload):
        human_only(token)
        permissions = payload.get('permissions')
        content_access = payload.get('contentAccess', 'mentions_only')
        if content_access not in message_content.MODES:
            fail('Choose limited or separately approved channel content access.')
        if (payload.get('confirmed') is not True or not isinstance(permissions, dict)
                or set(permissions) != set(KINDS) or any(type(v) is not bool for v in permissions.values())
                or permissions['reply'] and not permissions['inbox']):
            fail('Choose explicit read permissions; replying also needs inbox access. Confirm this exact channel.')
        if any(permissions.values()):
            self._enabled()
        snapshot = self.repository.get(workspace, token)
        def change(state, actor):
            target = target_for(state, connection, payload.get('destinationId'))
            if payload.get('targetDigest') != target_digest(target):
                fail('The Discord destination changed. Reload before approving access.')
            content_policy = message_content.policy(self.provider, self.clock()) if content_access == 'approved_content' else None
            if any(permissions.values()) and content_access == 'approved_content' and (not content_policy or content_policy['botUserId'] != target['botUserId']):
                message_content.deny()
            records = root(state)['consents']
            records[:] = [c for c in records if not (c.get('actor') == actor and c.get('destinationId') == target['id'])]
            if len(records) >= 1000:
                fail('The workspace consent limit was reached. Remove unused channel access first.')
            records.append({'schema': SCHEMA, 'id': str(uuid.uuid4()), 'actor': actor, 'workspaceId': workspace,
                            'connectionId': connection, 'destinationId': target['id'], 'targetDigest': target_digest(target),
                            'permissions': permissions, 'contentAccess': content_access,
                            'contentEvidenceDigest': auth.digest(content_policy) if content_policy else None,
                            'status': 'granted' if any(permissions.values()) else 'revoked',
                            'at': self.clock(), 'expiresAt': self.clock() + CONSENT_SECONDS})
            # Every change, including revocation, fences pending replies. Unknown
            # deliveries retain their receipts and remain reconciliation-only.
            for job in state.get('phase2', {}).get('jobs', []):
                if (job.get('manifest', {}).get('operation') == 'discord.reply' and job.get('approvedBy') == actor
                        and job['manifest'].get('destinationId') == target['id']
                        and job['state'] not in ('verified', 'failed', 'canceled')):
                    job['cancelRequested'] = True
            root(state)['reviews'][:] = [r for r in root(state)['reviews']
                                         if r.get('actor') != actor or r['manifest']['destinationId'] != target['id']]
            return state
        def fence(cur, state, actor):
            if any(permissions.values()):
                self._gate(cur, state, actor, connection, payload.get('destinationId'),
                           'reply' if permissions['reply'] else 'inbox' if permissions['inbox'] else 'analytics')
        self.repository.command(workspace, token, snapshot['revision'], change,
                                requirement='reply' if permissions['reply'] else 'read', after=fence,
                                audit_event=lambda _: ('discord.engagement_consent', connection, {'destinationId': payload.get('destinationId'), **permissions}))
        return self.status(workspace, token, connection)

    def read(self, workspace, token, connection, payload):
        kind, destination = payload.get('kind'), payload.get('destinationId')
        if kind not in ('analytics', 'inbox'):
            fail('Choose analytics or inbox.', 'discord_engagement_input')
        context, state, actor = self._context(workspace, token, connection, destination, kind)
        # Durable per-user cooldown complements (never substitutes for) the
        # shared provider ledger. Failed reads still consume this refresh slot.
        with self.repository.transaction(token, workspace) as (cur, row, current_actor):
            current = self._state(row)
            self._gate(cur, current, current_actor, connection, destination, kind, context)
            key = auth.digest([actor, connection, destination, kind])
            reads = root(current)['reads']
            last = reads.get(key, 0)
            if self.clock() - last < READ_COOLDOWN:
                raise AlphaError('Wait 15 seconds before refreshing this Discord view.', 429, code='discord_engagement_cooldown')
            reads = {k: v for k, v in reads.items() if self.clock() - v < READ_COOLDOWN}
            reads[key] = self.clock()
            root(current)['reads'] = reads
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(current), workspace))
            from ..hosted import audit
            audit(cur, workspace, actor, 'discord.engagement_read', connection, {'destinationId': destination, 'kind': kind})
        guard = self._guard(workspace, token, connection, destination, kind, context)
        extended = self._live(context, guard)
        target = context['target']
        provider = self.provider
        managed = managed_messages(state, target)
        page = provider._json(provider._bot('GET', f"/channels/{target['channelId']}/messages?limit={PAGE_SIZE}", read_authorize=guard), list)
        if len(page) > PAGE_SIZE:
            fail('Discord returned an invalid page.', 'discord_engagement_response')
        messages = [view for item in page if (view := message_view(item, target, managed, extended=extended)) is not None]
        result = {'kind': kind, 'target': target, 'observedAt': self.clock(), 'coverage': 'latest_page_only',
                  'pageLimit': PAGE_SIZE, 'mayHaveOlderMessages': len(page) == PAGE_SIZE,
                  'contentAccess': 'approved_content' if extended else 'mentions_only', 'limits': copy.deepcopy(LIMITS)}
        if kind == 'inbox':
            result['messages'] = messages
        else:
            guild = provider._json(provider._bot('GET', f"/guilds/{target['guildId']}?with_counts=true", read_authorize=guard), dict)
            if guild.get('id') != target['guildId']:
                fail('Discord returned another server.', 'discord_engagement_response')
            result['server'] = {k: metric(guild.get(field), source='discord_native_snapshot', definition=field)
                                for k, field in (('approximateMembers', 'approximate_member_count'), ('approximateOnline', 'approximate_presence_count'))}
            posts = []
            for message, job in managed.items():
                body = provider._json(provider._bot('GET', f"/channels/{target['channelId']}/messages/{message}", read_authorize=guard), dict)
                if (body.get('id') != message or body.get('channel_id') != target['channelId']
                        or (body.get('author') or {}).get('id') != target['botUserId']):
                    fail('A managed-message lookup did not match its approved origin.', 'discord_engagement_response')
                reactions = body.get('reactions', [])
                count = sum(r['count'] for r in reactions) if isinstance(reactions, list) and all(
                    isinstance(r, dict) and type(r.get('count')) is int and r['count'] >= 0 for r in reactions) else None
                replies = sum(m['parentMessageId'] == message for m in messages)
                posts.append({'messageId': message, 'jobId': job,
                              'reactions': metric(count, source='discord_native_message', definition='Sum of Discord reaction counts; not unique people.'),
                              'repliesObserved': metric(replies, source='rafii_derived_latest_page', definition='Replies referencing this Rafii-managed message in the fetched page only.', lower_bound=True)})
            result['managedMessages'] = posts
            result['unavailableMetrics'] = ['impressions', 'reach', 'allTimeReplies']
        guard()  # Revoked or changed access cannot return an in-flight result.
        return result

    def _parent(self, workspace, token, connection, context, message):
        if not auth.snowflake(message):
            fail('Choose an exact Discord message.', 'discord_engagement_input')
        target = context['target']
        guard = self._guard(workspace, token, connection, target['id'], 'reply', context)
        extended = self._live(context, guard)
        body = self.provider._json(self.provider._bot('GET', f"/channels/{target['channelId']}/messages/{message}", read_authorize=guard), dict)
        _, state, _ = self._context(workspace, token, connection, target['id'], 'reply', context)
        view = message_view(body, target, managed_messages(state, target), extended=extended)
        if not view or view['id'] != message or not view['replyable']:
            fail('Discord has withheld this message or it is no longer replyable. Open Discord to review it.', 'discord_message_content_restricted')
        guard()
        return body, view

    def preview(self, workspace, token, connection, payload):
        human_only(token)
        text = payload.get('text')
        if (not isinstance(text, str) or not text.strip() or '\x00' in text
                or len(text.encode('utf-16-le')) // 2 > 2000):
            fail('Write an exact plain-text reply of at most 2,000 characters.', 'discord_engagement_input')
        context, _, actor = self._context(workspace, token, connection, payload.get('destinationId'), 'reply')
        body, parent = self._parent(workspace, token, connection, context, payload.get('parentMessageId'))
        now = self.clock()
        if payload.get('localTime') is None:
            local = datetime.fromtimestamp((int(now) // 60 + 1) * 60, timezone.utc).strftime('%Y-%m-%dT%H:%M')
            timing = resolve_time(local, 'UTC', 0, now)
        else:
            timing = resolve_time(payload.get('localTime'), payload.get('timeZone'), payload.get('fold'), now)
        snapshot = self.repository.get(workspace, token)
        result = {}
        def change(state, principal):
            target = target_for(state, connection, payload.get('destinationId'))
            consent = consent_for(state, principal, target, 'reply', self.clock())
            if principal != actor or consent['id'] != context['consent']['id'] or target != context['target']:
                fail('Discord access changed. Prepare a new review.')
            identifier = str(uuid.uuid4())
            manifest = {'schema': REPLY_SCHEMA, 'workspaceId': workspace, 'actor': principal, 'platform': 'Discord',
                        'operation': 'discord.reply', 'channelId': connection, 'account': channel_for(state, connection)['account'],
                        'providerAccountId': target['guildId'], 'variantId': identifier, 'contentRevision': 1,
                        'payload': {'text': text, 'language': ''}, 'media': [], 'timing': timing,
                        'expiresAt': timing['timestamp'] + REVIEW_SECONDS, 'execution': 'hosted-live',
                        'engagementReply': {'consentId': consent['id'], 'contentAccess': consent.get('contentAccess', 'mentions_only'),
                                            'contentEvidenceDigest': consent.get('contentEvidenceDigest'), 'parentMessageId': parent['id'],
                                            'parentAuthorId': body['author']['id'], 'parentContentDigest': auth.digest(body['content']),
                                            'textDigest': auth.digest(text), 'reviewedBy': principal}}
            if getattr(self.commands.engine, 'worker_binding', None) is not None:
                manifest['workerBinding'] = copy.deepcopy(self.commands.engine.worker_binding)
            auth.freeze_manifest(state, channel_for(state, connection), manifest, target['id'])
            manifest['idempotencyKey'] = auth.digest(manifest)
            if not reply_current(state, manifest, self.clock()):
                fail('The schedule exceeds your current channel consent. Review access or choose an earlier time.')
            reviews = root(state)['reviews']
            reviews[:] = [r for r in reviews if r['expiresAt'] > self.clock()]
            if sum(r['actor'] == principal for r in reviews) >= 20:
                fail('Finish or wait for the existing reply reviews to expire before creating another.')
            review = {'id': identifier, 'actor': principal, 'manifest': manifest, 'digest': auth.digest(manifest),
                      'expiresAt': now + REVIEW_SECONDS, 'status': 'needs_review'}
            reviews.append(review)
            result.update(reviewId=identifier, manifest=copy.deepcopy(manifest), digest=review['digest'], expiresAt=review['expiresAt'], parent=parent)
            return state
        def fence(cur, state, principal):
            self._gate(cur, state, principal, connection, payload.get('destinationId'), 'reply', context)
        self.repository.command(workspace, token, snapshot['revision'], change, requirement='reply', after=fence,
                                audit_event=lambda _: ('discord.reply_reviewed', connection, {'destinationId': payload.get('destinationId')}))
        return result

    def approve(self, workspace, token, connection, payload):
        human_only(token)
        if payload.get('confirmed') is not True:
            fail('Review and approve the exact reply, parent, destination and time.')
        self._enabled()
        snapshot = self.repository.get(workspace, token)
        # Actor and digest are checked again in the final locked command.
        review = next((r for r in snapshot['state'].get('phase2', {}).get(KEY, {}).get('reviews', [])
                       if r.get('id') == payload.get('reviewId') and r['manifest'].get('channelId') == connection), None)
        if not review:
            fail('This reply review is unavailable. Prepare a new one.')
        manifest = review['manifest']
        context, _, actor = self._context(workspace, token, connection, manifest['destinationId'], 'reply')
        if review['actor'] != actor or review['digest'] != payload.get('digest'):
            fail('Only the member who reviewed this exact reply may approve it.')
        existing = next((j for j in snapshot['state'].get('phase2', {}).get('jobs', [])
                         if j.get('id') == review.get('jobId')), None)
        if existing:
            return {'jobId': existing['id'], 'state': existing['state'], 'approvalDigest': existing['approvalDigest'], 'duplicate': True}
        body, _ = self._parent(workspace, token, connection, context, manifest['engagementReply']['parentMessageId'])
        if (auth.digest(body['content']) != manifest['engagementReply']['parentContentDigest']
                or body['author']['id'] != manifest['engagementReply']['parentAuthorId']):
            fail('The parent message changed. Prepare and approve a new review.')
        # Reads can update unrelated state. Use the latest revision, but only the
        # original server-frozen review; never accept a client-supplied manifest.
        snapshot = self.repository.get(workspace, token)
        result = {}
        def change(state, principal):
            current = next((r for r in root(state)['reviews'] if r['id'] == review['id']), None)
            if (not current or current['actor'] != principal or current['digest'] != payload.get('digest')
                    or current['manifest'] != manifest or auth.digest(manifest) != current['digest']
                    or current['expiresAt'] <= self.clock() or not reply_current(state, manifest, self.clock())
                    or not auth.manifest_current(state, channel_for(state, connection), manifest)
                    or manifest.get('workerBinding') != getattr(self.commands.engine, 'worker_binding', None)):
                fail('This reply review or access changed. Prepare a new one.')
            jobs = state['phase2'].setdefault('jobs', [])
            job = next((j for j in jobs if j['id'] == manifest['discord']['publicationId']), None)
            auth.assert_no_unresolved_repeat(state, manifest, excluding=job['id'] if job else None)
            if not job:
                # The same owner ceiling as every other Discord approval, counted under this command's workspace row lock.
                auth.assert_workspace_hourly_ceiling(state, manifest['timing']['timestamp'])
                # Live plan/security checks run under the same transaction below.
                job = {'id': manifest['discord']['publicationId'], 'manifest': copy.deepcopy(manifest),
                       'approvalDigest': current['digest'], 'approvedAt': self.clock(), 'approvedBy': principal,
                       'state': 'scheduled', 'events': [], 'attempts': [], 'checks': 0, 'leaseOwner': None,
                       'leaseUntil': 0, 'nextAt': manifest['timing']['timestamp'], 'cancelRequested': False}
                job['discordAuthorization'] = auth.approval(job)
                self.commands.engine.event(job, 'scheduled', 'Human approved this exact Discord reply, parent, destination and time.')
                if manifest.get('workerBinding') is not None:
                    job['previewDispatchPending'] = True
                    self.commands.engine.event(job, 'held', 'Approved preview reply; dispatch requires an explicit action in this deployment.')
                jobs.append(job)
            elif job['approvalDigest'] != current['digest']:
                fail('This operation already has another approval.')
            current.update(status='approved', jobId=job['id'])
            result.update(jobId=job['id'], state=job['state'], approvalDigest=job['approvalDigest'])
            return state
        def fence(cur, state, principal):
            self._gate(cur, state, principal, connection, manifest['destinationId'], 'reply', context)
            from ..billing import require_publishing
            from ..security_holds import assert_clear
            require_publishing(cur, workspace, self.clock())
            assert_clear(cur, principal)
        self.repository.command(workspace, token, snapshot['revision'], change, requirement='reply', after=fence,
                                audit_event=lambda _: ('discord.reply_approved', result.get('jobId'), {'destinationId': manifest['destinationId']}))
        return result

    def cancel(self, workspace, token, connection, payload):
        human_only(token)
        snapshot = self.repository.get(workspace, token)
        def change(state, actor):
            job = next((j for j in state.get('phase2', {}).get('jobs', []) if j.get('id') == payload.get('jobId')
                        and j.get('approvedBy') == actor and j.get('manifest', {}).get('operation') == 'discord.reply'
                        and j['manifest'].get('channelId') == connection), None)
            if not job:
                fail('This reply is unavailable.')
            job['cancelRequested'] = True
            if not auth.unresolved_delivery(job) and job['state'] not in ('verified', 'failed', 'canceled'):
                self.commands.engine.event(job, 'canceled', 'The approving member canceled this reply before dispatch.')
            return state
        self.repository.command(workspace, token, snapshot['revision'], change, requirement='reply',
                                audit_event=lambda _: ('discord.reply_canceled', payload.get('jobId'), {}))
        return {'jobId': payload.get('jobId'), 'cancelRequested': True,
                'note': 'Further sends are fenced. A message already accepted by Discord is retained for reconciliation.'}
