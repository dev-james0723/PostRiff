"""YouTube creator surfaces share Rafii membership, token custody, jobs and approval records."""
import copy
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError
from ..permissions import require
from .api import ACTION_CAPABILITY, DESTRUCTIVE, YouTubeApi, redacted, validate_caption, validate_image
from .journal import UploadJournal, purge_expired_data
from .model import CAPABILITIES, READ, MANAGE, UPLOAD, capability_matrix, has_scopes, lifecycle, merged_update, project_public_gate, resource_id, validate_video, YouTubeError
from .uploads import UploadEngine, upload_view
from .capacity import CapacityController, CapacityPolicy


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def requirement(action):
    if action in ('comment.moderate',) or action.startswith(('chat.delete', 'chat.ban', 'chat.unban', 'chat.add_moderator', 'chat.remove_moderator')):
        return 'moderate'
    if action.startswith('comment.') or action in ('chat.send', 'chat.poll', 'chat.close_poll'):
        return 'reply'
    return 'approve'


class YouTubeCreatorService:
    def __init__(self, service):
        self.service, self.repository, self.oauth, self.clock = service, service.repository, service.oauth, service.clock
        self.journal = UploadJournal(service.connection_factory, service.oauth.vault)
        self.capacity = CapacityController(service.connection_factory,
            CapacityPolicy.from_environment(service.oauth.providers.get('youtube'), os.environ), clock=self.clock)
        self._capacities = {}
        self.oauth.identity_admission = self._identity_admission
        self.engine = UploadEngine(self.journal, self.worker_api, self.video_chunk, clock=self.clock, finalize=self.finalize_upload,
                                   chunk_size=os.environ.get('POSTRIFF_YOUTUBE_UPLOAD_CHUNK_BYTES'))
        from .notifications import PushNotifications
        self.notifications = PushNotifications(self)
        from .agent import YouTubePublishingAgent
        self.agent = YouTubePublishingAgent(self)

    def retention(self):
        """Cleanup remains owned by shared cron even when fleet dispatch is enabled."""
        # Retention continues after feature rollback; legacy deployments may lack 089.
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pr_youtube_cache')")
            has_schema = cur.fetchone()[0] is not None
            if has_schema:
                purge_expired_data(cur, agent_context=True)
                cur.execute("SELECT to_regclass('public.pr_youtube_quota_daily')")
                if cur.fetchone()[0] is None:
                    return {'dataCleanup': True, 'blocker': 'youtube_capacity_schema_097_required'}
                cur.execute("DELETE FROM public.pr_youtube_rate_windows WHERE window_start<now()-interval '1 day'")
                cur.execute("DELETE FROM public.pr_youtube_quota_daily WHERE quota_date<(now() AT TIME ZONE 'America/Los_Angeles')::date-90")
        return {'dataCleanup': has_schema}

    def maintenance(self, *, dispatch=True):
        cleanup = self.retention()
        provider = self.oauth.providers.get('youtube')
        if cleanup.get('blocker') or not provider or not getattr(provider, 'creator_enabled', False):
            return {'enabled': False, **cleanup}
        if not dispatch:
            return {'enabled': True, **cleanup, 'scheduler': 'isolated_youtube_fleet'}
        result = self.identity_one()
        result.pop('_selection', None)
        result.pop('selected', None)
        try:
            renewed = self.notifications.renew_one()
        except AlphaError:
            renewed = False
        return {'enabled': True, **result, 'notificationLeaseRenewed': renewed,
                'publishingAgent': self.agent.dispatch_one()}

    def fleet_schema_ready(self):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT to_regclass('public.pr_youtube_cache'),to_regclass('public.pr_youtube_quota_daily'),
                to_regclass('public.pr_worker_tenants')""")
            row = cur.fetchone()
        return bool(row and all(row))

    def claim_identity(self, *, excluded=()):
        """Claim-only seam for fleet concurrency acceptance; no provider request."""
        exclusion = ''.join(' AND NOT (c.workspace_id::text=%s AND c.connection_id=%s)' for _ in excluded)
        parameters = tuple(value for pair in excluded for value in pair)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT c.workspace_id::text,c.connection_id FROM public.pr_encrypted_credentials c
                JOIN public.pr_workspaces w ON w.id=c.workspace_id
                LEFT JOIN public.pr_youtube_cache k ON k.workspace_id=c.workspace_id AND k.connection_id=c.connection_id
                  AND k.cache_key='authorization-check'
                WHERE c.provider='youtube' AND c.revoked_at IS NULL AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
                  AND (k.expires_at IS NULL OR k.expires_at<=now())""" + exclusion + """
                ORDER BY k.refreshed_at NULLS FIRST,c.updated_at LIMIT 100 FOR KEY SHARE OF w SKIP LOCKED""", parameters)
            candidates = cur.fetchall()
            row = None
            for candidate in candidates:
                # Disconnect owns workspace -> credential. Acquire workspace
                # key-share locks above before any credential lock or child FK
                # insert; skip busy credentials within this bounded due set.
                cur.execute("""SELECT c.workspace_id::text,c.connection_id FROM public.pr_encrypted_credentials c
                    JOIN public.pr_workspaces w ON w.id=c.workspace_id
                    LEFT JOIN public.pr_youtube_cache k ON k.workspace_id=c.workspace_id AND k.connection_id=c.connection_id
                      AND k.cache_key='authorization-check'
                    WHERE c.workspace_id=%s AND c.connection_id=%s AND c.provider='youtube' AND c.revoked_at IS NULL
                      AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
                      AND (k.expires_at IS NULL OR k.expires_at<=now()) FOR UPDATE OF c SKIP LOCKED""", candidate)
                selected = cur.fetchone()
                if not selected:
                    continue
                cur.execute("""INSERT INTO public.pr_youtube_cache(workspace_id,connection_id,cache_key,source,data,expires_at)
                    VALUES(%s,%s,'authorization-check','Rafii operational lease','{}'::jsonb,now()+interval '5 minutes')
                    ON CONFLICT(workspace_id,connection_id,cache_key) DO UPDATE SET expires_at=excluded.expires_at,refreshed_at=now()
                    WHERE pr_youtube_cache.expires_at<=now() RETURNING connection_id""", selected)
                if cur.fetchone():
                    row = selected
                    break
        return row

    def identity_one(self, *, excluded=()):
        """Commit a short identity lease before network I/O; return internal selection."""
        row = self.claim_identity(excluded=excluded)
        checked, intervention = False, None
        if row:
            workspace, connection = row
            try:
                # Reuse Rafii's read-only revalidation so token expiry and the
                # shared composer's one-hour trust window advance together.
                result = self.oauth.reverify_for_worker(workspace, connection)
                if result.get('state') == 'reauthorization_required':
                    intervention = 'youtube_revoked_oauth'
                elif result.get('state') == 'client_binding_missing':
                    error = AlphaError('Reconnect this channel to bind its current OAuth client.', 409, code='youtube_oauth_binding_required')
                    self.operational_error(workspace, connection, error, 'oauth.binding')
                    intervention = error.code
                elif result.get('state') == 'read_verified':
                    with self.service.connection_factory() as db, db.cursor() as cur:
                        cur.execute('SELECT extract(epoch from access_expires_at)::float8 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL', (workspace, connection))
                        expiry = cur.fetchone()
                    ttl = min(1800, max(30, expiry[0] - self.clock() - 300)) if expiry and expiry[0] else 300
                    self._cache(workspace, connection, 'authorization-check', {'verifiedAt': self.clock()}, 'Google OAuth and YouTube Data API', ttl=ttl)
                    checked = True
            except AlphaError as error:
                if error.code == 'youtube_revoked_oauth':
                    intervention = error.code
                elif error.code in ('youtube_oauth_binding_required', 'youtube_oauth_binding_changed'):
                    self.operational_error(workspace, connection, error, 'oauth.binding')
                    intervention = error.code
        result = {'selected': bool(row), 'authorizationChecked': checked, '_selection': row}
        if intervention:
            result['reconnectionRequired'] = intervention
        return result

    def _identity_admission(self, workspace, provider):
        from .fleet import before_request
        before_request()
        self.capacity_for(provider).record_identity(workspace)

    def _member(self, workspace, token, connection, right='read', fresh=False, *, policy_required=True):
        from ..hosted import _membership
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            require(_membership(row), right)
            if fresh:
                self.repository.assert_fresh(token, actor)
            cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace, connection))
            found = cur.fetchone()
            if not found:
                raise AlphaError('Connection unavailable.', 404)
            if policy_required:
                self.oauth.youtube_policy.require_user(cur, workspace, actor, token,
                    self.oauth.providers.get('youtube'), force=True)
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        return actor, resource_id(found[0], 'channel'), state

    def settings(self, workspace, connection):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT monetary_authorized,memberships_authorized,evidence FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s', (workspace, connection))
            row = cur.fetchone()
        return {'monetary': bool(row and row[0]), 'memberships': bool(row and row[1])}, (row[2] if row else {})

    def capacity_for(self, provider):
        policy = CapacityPolicy.from_environment(provider, os.environ)
        key = (policy.project_key, getattr(provider, 'client_id', ''))
        if key not in self._capacities:
            self._capacities[key] = CapacityController(self.service.connection_factory, policy, clock=self.clock)
        return self._capacities[key]

    def account_usage(self, workspace, connection, provider=None):
        capacity = self.capacity_for(provider) if provider is not None else self.capacity
        def record(method, bucket, units):
            from .fleet import before_request
            before_request()
            capacity.record(workspace, connection, method, bucket, units)
        return record

    def _api(self, workspace, connection, channel=None):
        grant = self.oauth.token_for_worker(workspace, connection, youtube_policy_required=True)
        if grant['provider'] != 'youtube':
            raise AlphaError('Connection unavailable.', 404)
        canonical = grant.get('providerAccountId')
        if canonical and channel and canonical != channel:
            raise AlphaError('The approved YouTube channel identity changed. Review again.', 409)
        if not channel:
            with self.service.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT provider_account_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL", (workspace, connection))
                found = cur.fetchone()
            if not found:
                raise AlphaError('Connection unavailable.', 404)
            channel = found[0]
        provider = self.oauth.provider_for_grant(grant)
        return YouTubeApi(provider, grant, channel, clock=self.clock, account_usage=self.account_usage(workspace, connection, provider),
                          chat_resource=lambda kind, ident, chat: self.chat_resource(workspace, connection, kind, ident, chat),
                          on_error=lambda error, method: self.operational_error(workspace, connection, error, method,
                              expected_access_token=grant['accessToken'], expected_generation=grant.get('authorizationGeneration')),
                          before_request=lambda: self.journal.assert_authorized(workspace, connection, grant.get('authorizationGeneration')))

    def operational_error(self, workspace, connection, error, method, *, expected_access_token=None, expected_generation=None):
        category = getattr(error, 'category', None) or getattr(error, 'code', '')
        if category in ('revoked_oauth', 'youtube_revoked_oauth'):
            self.oauth.mark_youtube_revoked(workspace, connection, expected_access_token=expected_access_token,
                                           expected_generation=expected_generation)
            return
        if category not in ('quota', 'upload_limit', 'channel_restriction', 'project_restriction', 'capacity_delay',
                            'youtube_oauth_binding_required', 'youtube_oauth_binding_changed'):
            return
        key = 'operational-alert:' + category + ':' + datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        if self._cached(workspace, connection, key):
            return
        alert = {'category': category, 'method': method, 'observedAt': self.clock(),
                 'retryAt': getattr(error, 'retry_at', None), 'source': 'Official YouTube API response'}
        self._cache(workspace, connection, key, alert, source=alert['source'], ttl=86400)
        from ..hosted import audit
        with self.service.connection_factory() as db, db.cursor() as cur:
            audit(cur, workspace, None, 'youtube.operational_alert', connection, alert)

    def chat_resource(self, workspace, connection, kind, ident, chat):
        """Bind moderation targets to this workspace's observed chat, never a caller-supplied ID alone."""
        cached = self._cached(workspace, connection, ('chat-moderators:' if kind == 'moderator' else 'chat-events:') + chat) or {}
        entries = list(cached.get('items', []))
        if cached.get('activePoll'):
            entries.append(cached['activePoll'])
        for item in entries:
            snippet = item.get('snippet') or {}
            if item.get('id') == ident and snippet.get('liveChatId') == chat:
                if kind != 'poll' or snippet.get('type') == 'pollEvent':
                    return True
        actions = {'ban': 'chat.ban', 'moderator': 'chat.add_moderator', 'message': 'chat.send', 'poll': 'chat.poll'}
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT manifest,receipt FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s AND manifest->>'action'=%s AND status IN ('accepted','verified') AND updated_at>now()-interval '30 days'", (workspace, connection, actions[kind]))
            rows = cur.fetchall()
        return any((m.get('inputs') or {}).get('liveChatId') == chat and (r.get('result') or {}).get('id') == ident for m, r in rows)

    def _cached(self, workspace, connection, key):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT data FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND cache_key=%s AND expires_at>now()', (workspace, connection, key))
            row = cur.fetchone()
        return row[0] if row else None

    def _cache(self, workspace, connection, key, data, source='YouTube Data API', ttl=1800, *, authorization_generation=None):
        with self.service.connection_factory() as db, db.cursor() as cur:
            # Operational timestamps/alerts carry no provider content. They
            # still must not resurrect rows after disconnect. Provider-derived
            # content always supplies the exact generation from its API grant.
            if authorization_generation is None:
                authorization_generation = self.journal._generation(cur, (workspace, connection))
            self.journal.assert_authorized(workspace, connection, authorization_generation, cursor=cur, locked=True)
            cur.execute('INSERT INTO public.pr_youtube_cache(workspace_id,connection_id,cache_key,source,data,expires_at) VALUES(%s,%s,%s,%s,%s::jsonb,now()+make_interval(secs=>%s)) ON CONFLICT(workspace_id,connection_id,cache_key) DO UPDATE SET source=excluded.source,data=excluded.data,refreshed_at=now(),expires_at=excluded.expires_at', (workspace, connection, key, source, json.dumps(data), min(ttl, 30 * 86400)))

    def identity(self, workspace, connection, api):
        key = 'identity:' + hashlib.sha256(api.grant['accessToken'].encode()).hexdigest()[:24]
        cached = self._cached(workspace, connection, key)
        if cached:
            return cached
        items = api.call('channels.list', {'part': 'snippet,statistics,contentDetails,status,brandingSettings', 'mine': True, 'maxResults': 50}).get('items', [])
        item = next((x for x in items if x.get('id') == api.channel_id), None)
        if not item:
            raise AlphaError('This grant no longer resolves to the connected channel. Reconnect the intended channel.', 409, code='youtube_channel_changed')
        auth, evidence = self.settings(workspace, connection)
        item['eligibility'] = {k: bool(v.get('verified') and v.get('source') in ('YouTube Data API', 'YouTube Analytics API')
                                     and v.get('channelId') == api.channel_id and v.get('observedAt', 0) > self.clock() - 30 * 86400)
                               for k, v in (evidence.get('eligibility') or {}).items()}
        self._cache(workspace, connection, key, item, authorization_generation=api.grant.get('authorizationGeneration'))
        return item

    def _matrix(self, workspace, connection, api):
        authorizations, evidence = self.settings(workspace, connection)
        identity = self.identity(workspace, connection, api)
        return capability_matrix(api.provider, api.grant.get('scopes'), identity, evidence.get('acceptance'), authorizations), identity, authorizations

    def _allow(self, workspace, connection, api, capability, *, eligibility_probe=False):
        matrix, _, _ = self._matrix(workspace, connection, api)
        row = matrix[capability]
        if not row['canExecute'] and not (eligibility_probe and row['state'] == 'BLOCKED — ACCOUNT ELIGIBILITY'
                and api.provider.creator_enabled and has_scopes(api.grant['scopes'], CAPABILITIES[capability][1])):
            raise AlphaError(row['label'] + ': ' + row['reason'], 409, code='youtube_capability_blocked')

    def overview(self, workspace, token, connection):
        _, channel, _ = self._member(workspace, token, connection)
        api = self._api(workspace, connection, channel)
        matrix, identity, authorizations = self._matrix(workspace, connection, api)
        from ..hosted import _membership
        with self.repository.transaction(token, workspace) as (_, row, _):
            member = _membership(row)
        reads = {'connected', 'identity', 'comment_read', 'analytics', 'shorts_analytics', 'live_chat_read'}
        for name, capability in matrix.items():
            right = ('read' if name in reads else 'owner' if name in ('monetary_analytics', 'memberships')
                     else 'moderate' if name in ('moderation', 'live_moderation')
                     else 'reply' if name in ('top_level_comment', 'reply', 'comment_edit', 'comment_delete', 'live_chat_write')
                     else 'approve')
            if capability['canExecute'] and not member.allows(right):
                capability.update(canExecute=False, state='NOT AUTHORIZED',
                                  reason='Your workspace role does not authorize this creator action.')
        with self.service.connection_factory() as db, db.cursor() as cur:
            purge_expired_data(cur)
            cur.execute("SELECT method,bucket,count(*),sum(estimated_units) FROM public.pr_youtube_usage WHERE workspace_id=%s AND connection_id=%s AND attempted_at>=(date_trunc('day',now() AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'America/Los_Angeles') GROUP BY method,bucket ORDER BY method", (workspace, connection))
            usage = [{'method': x[0], 'bucket': x[1], 'attempts': x[2], 'estimatedUnits': x[3]} for x in cur.fetchall()]
            cur.execute('SELECT operation_key,state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s ORDER BY updated_at DESC LIMIT 50', (workspace, connection))
            uploads = [{'operationKey': x[0], **upload_view(x[1])} for x in cur.fetchall()]
            cur.execute("SELECT data FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND cache_key LIKE 'operational-alert:%%' AND expires_at>now() ORDER BY refreshed_at DESC LIMIT 20", (workspace, connection))
            alerts = [x[0] for x in cur.fetchall()]
        proof = api.provider.project_evidence
        return {'channelId': channel, 'identity': identity, 'capabilities': matrix, 'sensitiveAuthorizations': authorizations,
                'actualScopes': list(api.grant['scopes']), 'uploads': uploads, 'operationalAlerts': alerts,
                'counterProvenance': 'YouTube Data API',
                'project': {k: proof.get(k, {'status': 'unverified'}) for k in ('projectId', 'oauthVerification', 'youtubeComplianceAudit', 'publicUploadEligibility', 'quota')},
                'quota': {'source': 'Current official method contracts; Rafii attempts only', 'actualProjectRemaining': None,
                          'remainingState': 'UNVERIFIED', 'workspaceUsageToday': usage,
                          'admission': self.capacity_for(api.provider).snapshot(workspace),
                          'officialDefaults': {'videoUploads': {'limit': 100, 'unitsPerInsert': 1}, 'search': {'limit': 100}, 'general': {'limit': 10000}},
                          'resetTimeZone': 'America/Los_Angeles', 'note': 'Defaults are not this project’s allocation. Other API clients and failed requests can consume project quota.'},
                'readiness': {'implementation': 'IMPLEMENTED / E2E NOT PROVEN', 'googleApproval': 'verified' if project_public_gate(api.provider) else 'unverified',
                              'realE2E': 'unproven', 'production': 'NOT READY'}}

    def _read_guard(self, workspace, token, connection, resource, probe=False):
        from ..hosted import throttle
        sensitive = resource in ('revenue', 'members', 'membership_levels', 'report_ingest') or probe
        _, channel, _ = self._member(workspace, token, connection, 'owner' if sensitive else 'read', fresh=probe)
        with self.repository.transaction(token, workspace) as (cur, _, _):
            throttle(cur, 'youtube-read:' + workspace + ':' + connection, 120, 600)
            if resource in ('analytics', 'revenue'):
                throttle(cur, 'youtube-analytics:' + workspace + ':' + connection, 24, 600)
        return self._api(workspace, connection, channel)

    def _require_financial_reporting(self, workspace, token, connection, api, report_type):
        from .reporting import NON_MONETARY_TYPES
        if report_type in NON_MONETARY_TYPES:
            return
        self._member(workspace, token, connection, 'owner', fresh=True)
        auth, _ = self.settings(workspace, connection)
        if not auth['monetary'] or not has_scopes(api.grant['scopes'], CAPABILITIES['monetary_analytics'][1]):
            raise AlphaError('Financial or unclassified reports require intentional revenue authorization and its Google permission.', 403)

    def read(self, workspace, token, connection, resource, query=None):
        x = query or {}
        probe = x.get('eligibilityProbe') is True and resource in ('revenue', 'members', 'membership_levels', 'chat_moderators', 'comments')
        api = self._read_guard(workspace, token, connection, resource, probe)
        page = x.get('pageToken')
        if page is not None and (not isinstance(page, str) or len(page) > 2048):
            raise AlphaError('Invalid pagination cursor.', 400)
        pagination = {'maxResults': 50, **({'pageToken': page} if page else {})}
        if resource == 'videos':
            if x.get('id'):
                return {'source': 'YouTube Data API', 'items': [redacted(api.owned('videos', x['id']))]}
            channel = self.identity(workspace, connection, api)
            return {'source': 'YouTube Data API', **api.call('playlistItems.list', {'part': 'snippet,contentDetails', 'playlistId': channel['contentDetails']['relatedPlaylists']['uploads'], **pagination})}
        if resource in ('categories', 'languages'):
            method = 'videoCategories.list' if resource == 'categories' else 'i18nLanguages.list'
            return {'source': 'YouTube Data API', **api.call(method, {'part': 'snippet', **({'regionCode': x.get('regionCode', 'US')} if resource == 'categories' else {})})}
        if resource == 'playlists':
            self._allow(workspace, connection, api, 'identity')
            return {'source': 'YouTube Data API', **api.call('playlists.list', {'part': 'snippet,status,contentDetails,localizations', 'mine': True, **pagination})}
        if resource in ('playlist_items', 'playlist_images'):
            api.owned('playlists', x.get('playlistId'))
            return {'source': 'YouTube Data API', **api.call('playlistItems.list' if resource == 'playlist_items' else 'playlistImages.list', {'part': 'snippet', 'playlistId': x['playlistId'], **pagination})}
        if resource == 'captions':
            self._allow(workspace, connection, api, 'captions'); api.owned('videos', x.get('videoId'))
            return {'source': 'YouTube Data API', **api.call('captions.list', {'part': 'snippet', 'videoId': x['videoId']})}
        if resource == 'comments':
            self._allow(workspace, connection, api, 'comment_read')
            params = {'part': 'snippet,replies', 'order': 'time', 'textFormat': 'plainText', **pagination}
            if x.get('videoId'):
                api.owned('videos', x['videoId']); params['videoId'] = x['videoId']
            else:
                params['allThreadsRelatedToChannelId'] = api.channel_id
            if x.get('moderationStatus'):
                self._allow(workspace, connection, api, 'moderation', eligibility_probe=probe)
                if x['moderationStatus'] not in ('published', 'heldForReview', 'likelySpam'):
                    raise AlphaError('Choose a supported comment moderation filter.', 400)
                params['moderationStatus'] = x['moderationStatus']
            if x.get('search'):
                if not isinstance(x['search'], str) or len(x['search']) > 200:
                    raise AlphaError('Comment search is too long.', 400)
                params['searchTerms'] = x['search']
            body = api.call('commentThreads.list', params)
            if probe and api.provider.real_transport and x.get('moderationStatus') == 'heldForReview':
                self.record_eligibility(workspace, connection, api.channel_id, 'moderation', api.channel_id)
            self.ingest_comments(workspace, connection, api, body.get('items', []))
            if x.get('unanswered') is True:
                body['items'] = [v for v in body.get('items', []) if v.get('snippet', {}).get('totalReplyCount', 0) == 0]
            return {'source': 'YouTube Data API', **body, 'filterCoverage': 'Unanswered means no replies in the returned page; all-reply paging is available separately.'}
        if resource == 'replies':
            self._allow(workspace, connection, api, 'comment_read'); api.comment(x.get('parentId'))
            return {'source': 'YouTube Data API', **api.call('comments.list', {'part': 'snippet', 'parentId': x['parentId'], 'textFormat': 'plainText', **pagination})}
        if resource in ('analytics', 'revenue'):
            cap = 'monetary_analytics' if resource == 'revenue' else 'analytics'
            self._allow(workspace, connection, api, cap, eligibility_probe=probe)
            auth, _ = self.settings(workspace, connection)
            key = 'analytics:' + fingerprint(x | {'resource': resource})
            cached = self._cached(workspace, connection, key)
            if cached:
                return cached
            report = api.analytics('revenue' if resource == 'revenue' else x.get('report', 'daily'), x.get('startDate'), x.get('endDate'), video_id=x.get('videoId'), playlist_id=x.get('playlistId'), monetary_authorized=auth['monetary'])
            if resource == 'revenue' and api.provider.real_transport:
                self.record_eligibility(workspace, connection, api.channel_id, 'monetary_analytics', 'analytics.reports.query')
            self._cache(workspace, connection, key, report, 'YouTube Analytics API', 3600, authorization_generation=api.grant.get('authorizationGeneration'))
            return report
        if resource in ('broadcasts', 'streams'):
            self._allow(workspace, connection, api, 'identity')
            method = 'liveBroadcasts.list' if resource == 'broadcasts' else 'liveStreams.list'
            params = {'part': 'snippet,status,contentDetails' + (',cdn' if resource == 'streams' else ''), **pagination}
            if x.get('id'):
                return {'source': 'YouTube Live Streaming API', 'items': [redacted(api.owned('liveBroadcasts' if resource == 'broadcasts' else 'liveStreams', x['id']))]}
            params['mine'] = True
            return {'source': 'YouTube Live Streaming API', **redacted(api.call(method, params))}
        if resource == 'chat':
            api.owned_chat(x.get('liveChatId'), x.get('broadcastId'))
            self._allow(workspace, connection, api, 'live_chat_read', eligibility_probe=True)
            from .live_chat import read_chat
            body = read_chat(self, workspace, connection, api, x)
            if api.provider.real_transport and not body.get('deferred') and not body.get('streamTimeout'):
                self.record_eligibility(workspace, connection, api.channel_id, 'live_chat_read', x['liveChatId'])
            return body
        if resource == 'chat_moderators':
            api.owned_chat(x.get('liveChatId'), x.get('broadcastId'))
            self._allow(workspace, connection, api, 'live_moderation', eligibility_probe=probe)
            body = api.call('liveChatModerators.list', {'liveChatId': x['liveChatId'], 'part': 'snippet', **pagination})
            if api.provider.real_transport:
                self.record_eligibility(workspace, connection, api.channel_id, 'live_moderation', x['liveChatId'])
            self._cache(workspace, connection, 'chat-moderators:' + x['liveChatId'], body, 'YouTube Live Streaming API', 600, authorization_generation=api.grant.get('authorizationGeneration'))
            return {'source': 'YouTube Live Streaming API', **body}
        if resource in ('members', 'membership_levels'):
            self._allow(workspace, connection, api, 'memberships', eligibility_probe=probe)
            body = api.call('members.list' if resource == 'members' else 'membershipsLevels.list', {'part': 'snippet', **(pagination if resource == 'members' else {})})
            if api.provider.real_transport:
                self.record_eligibility(workspace, connection, api.channel_id, 'memberships', resource)
            return {'source': 'YouTube Data API', **body}
        if resource == 'report_ingest':
            self._allow(workspace, connection, api, 'reporting')
            auth, _ = self.settings(workspace, connection)
            from .reporting import ingest
            job = api.call('reporting.jobs.get', {'jobId': resource_id(x.get('jobId'), 'resource')})
            self._require_financial_reporting(workspace, token, connection, api, job.get('reportTypeId'))
            return ingest(self, workspace, connection, api, resource_id(x.get('jobId'), 'resource'), resource_id(x.get('reportId'), 'resource'), monetary_authorized=auth['monetary'] and has_scopes(api.grant['scopes'], CAPABILITIES['monetary_analytics'][1]), job=job)
        if resource in ('report_types', 'report_jobs', 'reports'):
            self._allow(workspace, connection, api, 'reporting')
            method = {'report_types': 'reporting.reportTypes.list', 'report_jobs': 'reporting.jobs.list', 'reports': 'reporting.jobs.reports.list'}[resource]
            params = {'pageSize': 50, **({'pageToken': page} if page else {})}
            if resource == 'reports':
                params['jobId'] = resource_id(x.get('jobId'), 'resource')
                job = api.call('reporting.jobs.get', {'jobId': params['jobId']})
                self._require_financial_reporting(workspace, token, connection, api, job.get('reportTypeId'))
            include_money = x.get('includeMonetary') is True
            if include_money:
                self._require_financial_reporting(workspace, token, connection, api, None)
            body = api.call(method, params)
            if resource in ('report_types', 'report_jobs') and not include_money:
                from .reporting import NON_MONETARY_TYPES
                field = 'reportTypes' if resource == 'report_types' else 'jobs'
                key = 'id' if resource == 'report_types' else 'reportTypeId'
                body[field] = [item for item in body.get(field, []) if item.get(key) in NON_MONETARY_TYPES]
                body['filterCoverage'] = 'Financial, system-managed and unclassified report jobs/types are excluded from this page.'
            return {'source': 'YouTube Reporting API', **body}
        raise AlphaError('This YouTube read surface is unsupported.', 404)

    def sensitive(self, workspace, token, connection, body):
        from ..hosted import audit
        if body.get('capability') not in ('monetary', 'memberships') or type(body.get('enabled')) is not bool or body.get('confirmed') is not True:
            raise AlphaError('Confirm the sensitive creator capability explicitly.', 400)
        self._member(workspace, token, connection, 'owner', fresh=True)
        column = 'monetary_authorized' if body['capability'] == 'monetary' else 'memberships_authorized'
        with self.repository.transaction(token, workspace) as (cur, _, actor):
            cur.execute('INSERT INTO public.pr_youtube_settings(workspace_id,connection_id,' + column + ') VALUES(%s,%s,%s) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET ' + column + '=excluded.' + column + ',updated_at=now()', (workspace, connection, body['enabled']))
            if not body['enabled']:
                cur.execute("DELETE FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND (cache_key LIKE 'analytics:%%' OR cache_key LIKE 'members%%')", (workspace, connection))
                if body['capability'] == 'monetary':
                    cur.execute('DELETE FROM public.pr_youtube_reporting_coverage WHERE workspace_id=%s AND connection_id=%s', (workspace, connection))
            audit(cur, workspace, actor, 'youtube.sensitive_authorization', connection, {'capability': body['capability'], 'enabled': body['enabled']})
        return {'capability': body['capability'], 'authorized': body['enabled'], 'oauthRequired': body['enabled']}

    def never_published(self, workspace, connection, video_id):
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state FROM public.pr_youtube_uploads WHERE workspace_id=%s AND connection_id=%s AND state->>'videoId'=%s", (workspace, connection, video_id))
            rows = cur.fetchall()
        return any(x[0].get('neverPublished') is True for x in rows)

    def _image(self, workspace, state, asset_id, podcast=False):
        asset = next((a for a in state.get('phase2', {}).get('assets', []) if a.get('id') == asset_id), None)
        if not asset or not self.service.assets or not str(asset.get('mime', '')).startswith('image/'):
            raise AlphaError('Choose an existing private workspace image.', 400)
        raw = self.service.assets.storage.get(workspace, 'media', asset.get('objectName') or asset['id'])
        mime = validate_image(raw, podcast)
        return raw, mime, fingerprint({'assetId': asset_id, 'sha256': hashlib.sha256(raw).hexdigest()})

    @staticmethod
    def _schedule_tracking_error():
        return AlphaError('The exact upload schedule approval changed or is ambiguous. Review this same video before continuing.',
                          409, code='youtube_schedule_tracking_conflict')

    @staticmethod
    def _schedule_tracking_root(key, upload, channel, workspace_state):
        """Bind to the immutable approved upload, never merely a matching Video ID."""
        from ..contracts import digest
        workspace, connection, operation = key
        jobs = [job for job in workspace_state.get('phase2', {}).get('jobs', [])
                if job.get('manifest', {}).get('workspaceId') == workspace
                and job.get('manifest', {}).get('channelId') == connection
                and job.get('manifest', {}).get('idempotencyKey') == operation]
        if len(jobs) != 1:
            raise YouTubeCreatorService._schedule_tracking_error()
        job, manifest = jobs[0], jobs[0]['manifest']
        upload_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if (manifest.get('providerAccountId') != channel or not upload.get('videoId')
                or upload.get('manifestDigest') != upload_digest or job.get('approvalDigest') != digest(manifest)
                or not job.get('approvedBy') or job.get('approvedBy') != manifest.get('actor')):
            raise YouTubeCreatorService._schedule_tracking_error()
        return {'workspaceId': workspace, 'connectionId': connection, 'channelId': channel,
                'videoId': upload['videoId'], 'operationKey': operation, 'uploadManifestDigest': upload_digest,
                'uploadApprovalDigest': job['approvalDigest'], 'jobId': job['id']}

    @staticmethod
    def _schedule_action_chain(rows, root):
        """A predecessor chain orders approvals; readback updated_at is not authority."""
        records = {}
        for action_id, manifest, digest, status, receipt in rows:
            if status in ('prepared', 'failed'):
                continue
            binding = manifest.get('uploadScheduleBinding') or {}
            plan = manifest.get('plan') or {}
            if (fingerprint(manifest) != digest or any(binding.get(k) != v for k, v in root.items())
                    or manifest.get('workspaceId') != root['workspaceId']
                    or manifest.get('connectionId') != root['connectionId']
                    or manifest.get('channelId') != root['channelId']
                    or manifest.get('action') not in ('video.schedule', 'video.cancel_schedule')
                    or plan.get('action') != manifest['action'] or plan.get('method') != 'videos.update'
                    or plan.get('targetId') != root['videoId'] or (plan.get('body') or {}).get('id') != root['videoId']
                    or manifest.get('inputs', {}).get('id') != root['videoId']):
                raise YouTubeCreatorService._schedule_tracking_error()
            records[action_id] = {'id': action_id, 'manifest': manifest, 'digest': digest,
                                  'status': status, 'receipt': receipt, 'previous': binding.get('previousAction')}
        if not records:
            return None
        predecessors = set()
        for record in records.values():
            previous = record['previous']
            if previous is not None:
                if (not isinstance(previous, dict) or previous.get('id') not in records
                        or previous.get('digest') != records[previous['id']]['digest']):
                    raise YouTubeCreatorService._schedule_tracking_error()
                predecessors.add(previous['id'])
        heads = set(records) - predecessors
        if len(heads) != 1:
            raise YouTubeCreatorService._schedule_tracking_error()
        head = records[heads.pop()]
        seen, record = set(), head
        while record is not None:
            if record['id'] in seen:
                raise YouTubeCreatorService._schedule_tracking_error()
            seen.add(record['id'])
            record = records[record['previous']['id']] if record['previous'] is not None else None
        if len(seen) != len(records):
            raise YouTubeCreatorService._schedule_tracking_error()
        return head

    def _schedule_action_head(self, cur, root):
        cur.execute("""SELECT id::text,manifest,manifest_digest,status,receipt FROM public.pr_youtube_actions
            WHERE workspace_id=%s AND connection_id=%s AND status NOT IN ('prepared','failed')
              AND manifest->'uploadScheduleBinding'->>'operationKey'=%s
              AND manifest->'uploadScheduleBinding'->>'uploadManifestDigest'=%s""",
                    (root['workspaceId'], root['connectionId'], root['operationKey'], root['uploadManifestDigest']))
        return self._schedule_action_chain(cur.fetchall(), root)

    def _upload_schedule_binding(self, workspace, connection, channel, video_id, workspace_state, *, cursor=None, locked=False):
        def read(cur):
            cur.execute("""SELECT operation_key,state FROM public.pr_youtube_uploads
                WHERE workspace_id=%s AND connection_id=%s AND state->>'videoId'=%s"""
                        + (' FOR UPDATE' if locked else ''), (workspace, connection, video_id))
            rows = [(operation, upload) for operation, upload in cur.fetchall()
                    if upload.get('options', {}).get('publishAt') and upload.get('stage') not in ('failed', 'canceled', 'published')
                    and (upload.get('stage') == 'native_scheduled' or upload.get('nativeScheduleTracking') is True
                         or upload.get('steps', {}).get('visibility', {}).get('status') == 'verified')]
            if not rows:
                return None  # Standalone owned-video actions retain their existing behavior.
            if len(rows) != 1:
                raise self._schedule_tracking_error()
            operation, upload = rows[0]
            root = self._schedule_tracking_root((workspace, connection, operation), upload, channel, workspace_state)
            head = self._schedule_action_head(cur, root)
            if head and head['status'] != 'verified':
                raise AlphaError('Reconcile the preceding approved schedule change before preparing another write.',
                                 409, code='youtube_schedule_verification_pending')
            return {**root, 'previousAction': {'id': head['id'], 'digest': head['digest']} if head else None}
        if cursor is not None:
            return read(cursor)
        with self.service.connection_factory() as db, db.cursor() as cur:
            return read(cur)

    def preview(self, workspace, token, connection, body):
        action, inputs = body.get('action'), body.get('inputs', {})
        if action not in ACTION_CAPABILITY:
            raise AlphaError('Choose a supported creator action.', 400)
        probe = body.get('eligibilityProbe') is True
        actor, channel, state = self._member(workspace, token, connection, 'owner' if probe else requirement(action), fresh=probe)
        api = self._api(workspace, connection, channel)
        self._allow(workspace, connection, api, ACTION_CAPABILITY[action], eligibility_probe=probe)
        if action == 'reporting.create':
            self._require_financial_reporting(workspace, token, connection, api, inputs.get('reportTypeId'))
        if action in ('broadcast.create', 'broadcast.edit', 'video.edit'):
            visibility = ((inputs.get('body') or inputs.get('patch') or {}).get('status') or {}).get('privacyStatus')
            if visibility in ('public', 'unlisted') and not project_public_gate(api.provider):
                raise AlphaError('Public and unlisted publication need independent Google approval evidence.', 409, code='youtube_project_restriction')
        plan = api.plan(action, inputs, never_published=self.never_published(workspace, connection, inputs.get('id')))
        if action == 'reporting.delete':
            self._require_financial_reporting(workspace, token, connection, api, plan.get('reportTypeId'))
        if (plan.get('media') or {}).get('assetId'):
            if body.get('rightsConfirmed') is not True:
                raise AlphaError('Confirm your rights to the selected image.', 400)
            _, _, media_digest = self._image(workspace, state, plan['media']['assetId'], plan['media']['kind'] == 'podcast')
            plan['mediaDigest'] = media_digest
        destructive = action in DESTRUCTIVE or (action == 'comment.moderate' and (inputs.get('banAuthor') or inputs.get('moderationStatus') == 'rejected')) or (action == 'chat.ban' and inputs.get('permanent') is True) or (action == 'broadcast.transition' and inputs.get('broadcastStatus') == 'complete')
        manifest = {'workspaceId': workspace, 'connectionId': connection, 'channelId': channel, 'action': action,
                    'inputs': inputs, 'plan': plan, 'destructive': destructive, 'eligibilityProbe': probe, 'rightsConfirmed': body.get('rightsConfirmed') is True,
                    'approvalExpiresAt': self.clock() + 600}
        if action in ('video.schedule', 'video.cancel_schedule'):
            binding = self._upload_schedule_binding(workspace, connection, channel, inputs.get('id'), state)
            if binding is not None:
                manifest['uploadScheduleBinding'] = binding
        digest = fingerprint(manifest)
        operation_key = body.get('operationKey') or str(uuid.uuid4())
        resource_id(operation_key, 'resource')
        from ..hosted import audit, throttle
        with self.repository.transaction(token, workspace) as (cur, _, actor):
            # A late planning read must not recreate prepared data after disconnect.
            self.journal.assert_authorized(workspace, connection, api.grant.get('authorizationGeneration'), cursor=cur, locked=True)
            throttle(cur, 'youtube-preview:' + workspace + ':' + connection, 30, 600)
            cur.execute("INSERT INTO public.pr_youtube_actions(workspace_id,connection_id,actor,operation_key,manifest,manifest_digest,status) VALUES(%s,%s,%s,%s,%s::jsonb,%s,'prepared') ON CONFLICT(workspace_id,connection_id,operation_key) DO NOTHING RETURNING id::text", (workspace, connection, actor, operation_key, json.dumps(manifest), digest))
            result = cur.fetchone()
            if not result:
                raise AlphaError('This operation key already has a review or result. Open its existing receipt.', 409, code='youtube_idempotency_conflict')
            audit(cur, workspace, actor, 'youtube.action_prepared', result[0], {'action': action, 'connectionId': connection, 'digest': digest, 'destructive': destructive})
        return {'id': result[0], 'digest': digest, 'manifest': redacted(manifest), 'executed': False,
                'confirmationTarget': plan.get('targetId') or inputs.get('id') or inputs.get('videoId') or inputs.get('liveChatId')}

    def approve(self, workspace, token, connection, action_id, body):
        if body.get('confirmed') is not True:
            raise AlphaError('Approve the exact creator action first.', 400)
        from ..hosted import _membership, audit, throttle
        with self.repository.transaction(token, workspace) as (cur, row, actor):
            cur.execute('SELECT manifest,manifest_digest,status,receipt,actor::text FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=%s FOR UPDATE', (workspace, connection, action_id))
            saved = cur.fetchone()
            if not saved:
                raise AlphaError('Creator action unavailable.', 404)
            manifest, digest, status, receipt, owner = saved
            if status == 'privacy_erased' or manifest.get('privacyErased'):
                raise AlphaError('This action contains erased YouTube API data. Prepare and approve a new operation.', 409, code='youtube_privacy_erased')
            require(_membership(row), 'owner' if manifest['eligibilityProbe'] else requirement(manifest['action']))
            if manifest['destructive'] or manifest['eligibilityProbe']:
                self.repository.assert_fresh(token, actor)
            if body.get('digest') != digest or fingerprint(manifest) != digest:
                raise AlphaError('The exact review changed. Prepare a fresh review.', 409)
            if status != 'prepared':
                return {'id': action_id, 'status': status, 'receipt': receipt, 'retried': False}
            if manifest['approvalExpiresAt'] < self.clock():
                raise AlphaError('The exact review expired. Prepare a fresh review.', 409)
            if manifest['action'] in ('video.schedule', 'video.cancel_schedule'):
                workspace_state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                # This short row lock serializes approval intent for this upload.
                # It is released with started before any Google request begins.
                binding = self._upload_schedule_binding(workspace, connection, manifest['channelId'],
                                                        manifest['inputs'].get('id'), workspace_state, cursor=cur, locked=True)
                if binding != manifest.get('uploadScheduleBinding'):
                    raise self._schedule_tracking_error()
            target = manifest['plan'].get('targetId') or manifest['inputs'].get('id') or manifest['inputs'].get('videoId') or manifest['inputs'].get('liveChatId')
            if manifest['destructive'] and (not target or body.get('confirmationTarget') != target):
                raise AlphaError('Confirm the exact YouTube resource ID for this destructive action.', 400)
            throttle(cur, 'youtube-write:' + workspace + ':' + connection, 20, 60)
            # Committed intent fences duplicate submits, including destructive operations.
            cur.execute("UPDATE public.pr_youtube_actions SET status='started',updated_at=now() WHERE id::text=%s", (action_id,))
            audit(cur, workspace, actor, 'youtube.action_approved', action_id, {'action': manifest['action'], 'connectionId': connection, 'digest': digest, 'destructive': manifest['destructive']})
        remote_accepted = False
        api = None
        try:
            _, channel, state = self._member(workspace, token, connection, requirement(manifest['action']))
            if channel != manifest['channelId']:
                raise AlphaError('The approved channel changed.', 409)
            api = self._api(workspace, connection, channel)
            self._allow(workspace, connection, api, ACTION_CAPABILITY[manifest['action']], eligibility_probe=manifest['eligibilityProbe'])
            if manifest['action'] == 'reporting.create':
                self._require_financial_reporting(workspace, token, connection, api, manifest['inputs'].get('reportTypeId'))
            if manifest['action'] in ('broadcast.create', 'broadcast.edit', 'video.edit'):
                visibility = ((manifest['inputs'].get('body') or manifest['inputs'].get('patch') or {}).get('status') or {}).get('privacyStatus')
                if visibility in ('public', 'unlisted') and not project_public_gate(api.provider):
                    raise AlphaError('Google approval evidence changed before publication. Review again.', 409, code='youtube_project_restriction')
            plan = api.plan(manifest['action'], manifest['inputs'], never_published=self.never_published(workspace, connection, manifest['inputs'].get('id')))
            if manifest['action'] == 'reporting.delete':
                self._require_financial_reporting(workspace, token, connection, api, plan.get('reportTypeId'))
            if manifest['plan'].get('mediaDigest'):
                _, _, plan['mediaDigest'] = self._image(workspace, state, plan['media']['assetId'], plan['media']['kind'] == 'podcast')
            if fingerprint(plan) != fingerprint(manifest['plan']):
                raise AlphaError('The resource or media changed after review; prepare a new review to preserve omitted fields.', 409)
            reader = lambda asset_id: self._image(workspace, state, asset_id, (plan.get('media') or {}).get('kind') == 'podcast')[0]
            result = plan['result'] if plan.get('noop') else api.execute(plan, media_reader=reader)
            remote_accepted = True
            # Persist the response before any read-back. A later GET failure cannot erase remote acceptance.
            secret = result.get('cdn', {}).get('ingestionInfo', {}).get('streamName') if isinstance(result, dict) else None
            ciphertext, key_id = self.oauth.vault.encrypt(secret) if secret else (None, None)
            receipt = {'source': 'YouTube Data API', 'channelId': channel, 'action': manifest['action'], 'acceptedAt': self.clock(),
                       'actionId': action_id, 'approvalDigest': digest,
                       'result': redacted(result), 'execution': 'real' if api.provider.real_transport else 'transport-injected'}
            with self.service.connection_factory() as db, db.cursor() as cur:
                self.journal.assert_authorized(workspace, connection, api.grant.get('authorizationGeneration'), cursor=cur, locked=True)
                cur.execute("UPDATE public.pr_youtube_actions SET status='accepted',receipt=%s::jsonb,secret_ciphertext=%s,secret_key_id=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND id::text=%s AND privacy_erased_at IS NULL", (json.dumps(receipt), ciphertext, key_id, workspace, connection, action_id))
                if not cur.rowcount:
                    return {'id': action_id, 'status': 'privacy_erased', 'receipt': None, 'dataRemoved': True, 'retried': False}
            try:
                verification = self.verify_action(api, plan, result)
            except AlphaError as error:
                if getattr(error, 'category', None) == 'revoked_oauth' or error.code == 'youtube_revoked_oauth':
                    raise
                verification = {'verified': False, 'method': 'readback_unavailable', 'note': 'The official write was accepted; verification must be retried without repeating the write.'}
            status = 'verified' if verification.get('verified') else 'accepted'
            receipt = {'source': 'YouTube Data API', 'channelId': channel, 'action': manifest['action'], 'acceptedAt': self.clock(),
                       'actionId': action_id, 'approvalDigest': digest,
                       'result': redacted(result), 'verification': verification, 'execution': 'real' if api.provider.real_transport else 'transport-injected'}
            with self.service.connection_factory() as db, db.cursor() as cur:
                self.journal.assert_authorized(workspace, connection, api.grant.get('authorizationGeneration'), cursor=cur, locked=True)
                cur.execute('UPDATE public.pr_youtube_actions SET status=%s,receipt=%s::jsonb,secret_ciphertext=%s,secret_key_id=%s,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND id::text=%s AND privacy_erased_at IS NULL', (status, json.dumps(receipt), ciphertext, key_id, workspace, connection, action_id))
                if not cur.rowcount:
                    return {'id': action_id, 'status': 'privacy_erased', 'receipt': None, 'dataRemoved': True, 'retried': False}
                audit(cur, workspace, actor, 'youtube.action_result', action_id, {'action': manifest['action'], 'status': status, 'connectionId': connection})
            if manifest['eligibilityProbe'] and api.provider.real_transport:
                self.record_eligibility(workspace, connection, channel, ACTION_CAPABILITY[manifest['action']], result.get('id') or plan.get('targetId'))
            return {'id': action_id, 'status': status, 'receipt': receipt}
        except (AlphaError, OSError, TimeoutError) as error:
            ambiguous = remote_accepted or getattr(error, 'ambiguous', False) or isinstance(error, (OSError, TimeoutError))
            status = 'outcome_unknown' if ambiguous else 'failed'
            receipt = {'category': getattr(error, 'category', getattr(error, 'code', 'creator_operation_failed')), 'message': str(error) if isinstance(error, AlphaError) else 'Remote outcome is unknown.', 'retriableAutomatically': False,
                       'actionId': action_id, 'approvalDigest': digest}
            with self.service.connection_factory() as db, db.cursor() as cur:
                if api is not None:
                    self.journal.assert_authorized(workspace, connection, api.grant.get('authorizationGeneration'), cursor=cur, locked=True)
                else:
                    cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR KEY SHARE', (workspace,))
                cur.execute('UPDATE public.pr_youtube_actions SET status=%s,receipt=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND id::text=%s AND privacy_erased_at IS NULL', (status, json.dumps(receipt), workspace, connection, action_id))
                if not cur.rowcount:
                    return {'id': action_id, 'status': 'privacy_erased', 'receipt': None, 'dataRemoved': True, 'retried': False}
                audit(cur, workspace, actor, 'youtube.action_result', action_id, {'action': manifest['action'], 'status': status, 'category': receipt['category'], 'connectionId': connection})
            return {'id': action_id, 'status': status, 'receipt': receipt}

    def actions(self, workspace, token, connection):
        self._member(workspace, token, connection)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT id::text,manifest,status,receipt,extract(epoch from updated_at) FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s ORDER BY updated_at DESC LIMIT 50', (workspace, connection))
            return {'actions': [{'id': x[0], 'action': x[1]['action'], 'status': x[2], 'receipt': x[3], 'updatedAt': float(x[4])} for x in cur.fetchall()]}

    def stream_secret(self, workspace, token, connection, action_id):
        from ..hosted import audit
        actor, _, _ = self._member(workspace, token, connection, 'owner', fresh=True)
        with self.repository.transaction(token, workspace) as (cur, _, _):
            cur.execute('SELECT secret_ciphertext,secret_key_id FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=%s', (workspace, connection, action_id))
            row = cur.fetchone()
            if not row or not row[0]:
                raise AlphaError('Stream configuration unavailable.', 404)
            secret = self.oauth.vault.decrypt(row[0], row[1])
            audit(cur, workspace, actor, 'youtube.stream_secret_viewed', action_id, {'connectionId': connection})
        return {'streamKey': secret, 'sensitive': True}

    def stream_configuration(self, workspace, token, connection, stream_id):
        actor, channel, _ = self._member(workspace, token, connection, 'owner', fresh=True)
        api = self._api(workspace, connection, channel)
        # Reading an existing owned stream's configuration does not establish
        # eligibility to create or start a new broadcast.
        self._allow(workspace, connection, api, 'identity')
        stream = api.owned('liveStreams', resource_id(stream_id, 'resource'))
        from ..hosted import audit
        with self.service.connection_factory() as db, db.cursor() as cur:
            audit(cur, workspace, actor, 'youtube.stream_configuration_viewed', str(uuid.uuid4()), {'connectionId': connection})
        return {'streamId': stream_id, 'cdn': stream.get('cdn'), 'sensitive': True, 'source': 'YouTube Live Streaming API'}

    def upload_recovery(self, workspace, token, connection, operation_key, body=None):
        actor, channel, state = self._member(workspace, token, connection, 'approve', fresh=body is not None)
        key = (workspace, connection, resource_id(operation_key, 'resource'))
        with self.journal.lock(key):
            saved = self.journal.load(key)
            job = next((job for job in state.get('phase2', {}).get('jobs', [])
                        if job.get('manifest', {}).get('channelId') == connection
                        and job.get('manifest', {}).get('idempotencyKey') == operation_key), None)
            if not saved or not job or job['manifest'].get('providerAccountId') != channel:
                raise AlphaError('The exact upload and its approval record are unavailable.', 404)
            unsafe = (saved.get('stage') in ('failed', 'canceled', 'session_expired')
                      or (not saved.get('videoId') and not saved.get('sessionCiphertext'))
                      or job.get('approvedBy') != actor
                      or not self.service.commands.engine.current(state, job['manifest']))
            review = {'channelId': channel, 'operationKey': operation_key, 'videoId': saved.get('videoId'),
                      'options': saved['options'], 'stage': saved['stage'], 'errorCategory': saved.get('errorCategory'),
                      'bytesSent': saved['bytesSent'], 'totalBytes': saved['totalBytes'],
                      'approvalDigest': job.get('approvalDigest'), 'canResume': not unsafe,
                      'effect': 'The original approver may resume and probe this same upload session or accepted Video ID for up to 36 hours. A replacement upload will not be created.'}
            digest = fingerprint(review)
            if body is None:
                return {'manifest': review, 'digest': digest, 'executed': False}
            if body.get('confirmed') is not True or body.get('digest') != digest or unsafe:
                raise AlphaError('Approve this exact recoverable upload first. Ended or unjournaled uploads cannot be restarted.', 409)
            # API authorization and independent project/eligibility gates are refreshed before releasing the hold.
            self.worker_api(job['manifest'])
            if saved['stage'] != 'held':
                return {'status': saved['stage'], 'resumed': False}
            saved.setdefault('recoveryAttempts', []).append({'at': self.clock(), 'actor': actor, 'previousCategory': saved.get('errorCategory')})
            saved.update(stage='uploaded_private' if saved.get('videoId') else 'uploading', retryAt=self.clock(), transientFailures=0)
            from ..hosted import audit
            with self.repository.transaction(token, workspace) as (cur, row, _):
                latest = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                latest_job = next((x for x in latest.get('phase2', {}).get('jobs', []) if x.get('id') == job['id']), None)
                if (not latest_job or latest_job.get('approvalDigest') != job.get('approvalDigest')
                        or not self.service.commands.engine.current(latest, latest_job['manifest'])):
                    raise AlphaError('The upload approval changed before recovery.', 409)
                cur.execute("SELECT 1 FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE", (workspace, connection))
                if not cur.fetchone():
                    raise AlphaError('This upload connection was revoked before recovery.', 409, code='youtube_revoked_oauth')
                self.journal.save(key, saved, cursor=cur)
                latest_job.update(state='provider_accepted', nextAt=self.clock(), progress={'version': 2, **upload_view(saved)})
                latest_job['youtubeRecoveryApproval'] = {'approvedBy': actor, 'digest': job['approvalDigest'],
                    'approvedAt': self.clock(), 'expiresAt': self.clock() + 36 * 3600}
                cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(latest), workspace))
                audit(cur, workspace, actor, 'youtube.upload_resumed', job['id'], {'operationKey': operation_key, 'connectionId': connection})
            return {'status': saved['stage'], 'resumed': True, 'replacementUpload': False}

    def record_eligibility(self, workspace, connection, channel, capability, reference):
        gate = CAPABILITIES[capability][2]
        if gate not in ('thumbnail', 'live', 'chat', 'moderation', 'live_moderation', 'monetary', 'memberships'):
            return
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute("INSERT INTO public.pr_youtube_settings(workspace_id,connection_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (workspace, connection))
            cur.execute('SELECT evidence FROM public.pr_youtube_settings WHERE workspace_id=%s AND connection_id=%s FOR UPDATE', (workspace, connection))
            evidence = cur.fetchone()[0]
            evidence.setdefault('eligibility', {})[gate] = {'verified': True, 'channelId': channel,
                'source': 'YouTube Analytics API' if gate == 'monetary' else 'YouTube Data API', 'reference': reference, 'observedAt': self.clock()}
            cur.execute('UPDATE public.pr_youtube_settings SET evidence=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND connection_id=%s', (json.dumps(evidence), workspace, connection))
            cur.execute("DELETE FROM public.pr_youtube_cache WHERE workspace_id=%s AND connection_id=%s AND cache_key LIKE 'identity:%%'", (workspace, connection))

    @staticmethod
    def verify_action(api, plan, result):
        method = plan.get('method', '')
        if plan.get('noop'):
            return {'verified': True, 'method': 'official-existing-membership-read'}
        resource = method.split('.')[0]
        rid = result.get('id') if isinstance(result, dict) else None
        if method.endswith(('.insert', '.update')) and resource in ('videos', 'playlists', 'liveBroadcasts', 'liveStreams') and rid:
            current = api.owned(resource, rid)
            fields = plan.get('body') or {}
            exact = all(part == 'id' or all(current.get(part, {}).get(k) == v for k, v in values.items()) for part, values in fields.items())
            if plan.get('action') == 'video.cancel_schedule':
                exact = (exact and rid == fields.get('id') and current.get('id') == fields.get('id')
                         and current.get('status', {}).get('publishAt') is None)
            return {'verified': exact, 'method': resource + '.list', 'resourceId': rid, 'observed': redacted(current)}
        if method.endswith('.delete') and resource in ('videos', 'playlists', 'liveBroadcasts', 'liveStreams'):
            body = api.call(resource + '.list', {'part': 'id', 'id': plan['params']['id']})
            return {'verified': not body.get('items'), 'method': resource + '.list', 'resourceId': plan['params']['id']}
        if resource == 'liveBroadcasts' and method.endswith(('.bind', '.transition')):
            current = api.owned(resource, plan['params']['id'])
            matched = (current.get('contentDetails', {}).get('boundStreamId') == plan['params'].get('streamId') if method.endswith('.bind')
                       else current.get('status', {}).get('lifeCycleStatus') == plan['params']['broadcastStatus'])
            archive = None
            if current.get('status', {}).get('lifeCycleStatus') == 'complete':
                try:
                    video = api.owned('videos', current['id'])
                    archive = {'videoId': video['id'], **lifecycle(video), 'source': 'YouTube Data API'}
                except AlphaError:
                    archive = {'state': 'not_yet_available'}
            return {'verified': matched, 'method': 'liveBroadcasts.list', 'resourceId': current['id'], 'observed': redacted(current), 'archive': archive}
        if resource == 'thumbnails':
            current = api.owned('videos', plan['params']['videoId'])
            urls = {v.get('url') for v in current.get('snippet', {}).get('thumbnails', {}).values()}
            returned = {v.get('url') for item in result.get('items', []) for v in item.values() if isinstance(v, dict)}
            return {'verified': bool((urls & returned) - {None}), 'method': 'videos.list', 'resourceId': current['id']}
        if resource == 'captions':
            video = (plan.get('body') or {}).get('snippet', {}).get('videoId') or (result.get('snippet') or {}).get('videoId') or plan.get('videoId')
            if not video:
                return {'verified': False, 'method': 'captions.list', 'note': 'Caption video identity is needed for read-back.'}
            items = api.call('captions.list', {'videoId': video, 'part': 'snippet'}).get('items', [])
            rid = rid or plan.get('params', {}).get('id')
            current = next((item for item in items if item['id'] == rid), None)
            if method.endswith('.delete'):
                return {'verified': current is None, 'method': 'captions.list', 'resourceId': rid}
            expected = (plan.get('body') or {}).get('snippet') or {}
            exact = current is not None and all(current.get('snippet', {}).get(k) == v for k, v in expected.items())
            serving = current and current.get('snippet', {}).get('status') == 'serving'
            return {'verified': bool(exact and serving), 'method': 'captions.list', 'resourceId': rid,
                    'processing': current.get('snippet', {}).get('status') if current else 'missing'}
        if resource == 'playlistItems':
            rid = rid or plan.get('params', {}).get('id')
            items = api.call('playlistItems.list', {'id': rid, 'part': 'snippet'}).get('items', [])
            expected = (plan.get('body') or {}).get('snippet') or {}
            exact = len(items) == 1 and all(items[0].get('snippet', {}).get(k) == v for k, v in expected.items())
            return {'verified': not items if method.endswith('.delete') else exact, 'method': 'playlistItems.list', 'resourceId': rid}
        if resource in ('comments', 'commentThreads') and method.endswith(('.insert', '.update')):
            rid = result.get('snippet', {}).get('topLevelComment', {}).get('id') if resource == 'commentThreads' else rid
            current = api.comment(rid)
            expected = (plan.get('body') or {}).get('snippet') or {}
            expected = expected.get('topLevelComment', {}).get('snippet', expected)
            return {'verified': current.get('snippet', {}).get('textOriginal') == expected.get('textOriginal'),
                    'method': 'comments.list', 'resourceId': rid, 'observed': redacted(current)}
        if resource == 'comments' and method.endswith('.delete'):
            items = api.call('comments.list', {'id': plan['params']['id'], 'part': 'snippet'}).get('items', [])
            return {'verified': not items, 'method': 'comments.list', 'resourceId': plan['params']['id']}
        if resource == 'comments' and method.endswith('.setModerationStatus'):
            target, rid = plan['params']['moderationStatus'], plan['params']['id']
            if target == 'rejected':
                return {'verified': False, 'method': 'official-write-receipt', 'note': 'Rejected-comment read-back is not exposed reliably; receipt is retained without inventing a PASS.'}
            current = api.comment(rid)
            return {'verified': current.get('snippet', {}).get('moderationStatus') == target, 'method': 'comments.list', 'resourceId': rid}
        if resource == 'playlistImages' and rid:
            items = api.call('playlistImages.list', {'part': 'snippet', 'id': rid}).get('items', [])
            return {'verified': len(items) == 1 and items[0].get('id') == rid, 'method': 'playlistImages.list', 'resourceId': rid,
                    'note': 'Current public method documentation and discovery disagree on the list filter; real acceptance remains required.'}
        if method == 'reporting.jobs.create' and rid:
            current = api.call('reporting.jobs.get', {'jobId': rid})
            return {'verified': current.get('id') == rid and current.get('reportTypeId') == plan['body']['reportTypeId'], 'method': 'reporting.jobs.get', 'resourceId': rid}
        return {'verified': False, 'method': 'official-write-receipt', 'note': 'Write accepted; resource-specific read-back or eventual processing acceptance remains unproven.'}

    def reconcile_action(self, workspace, token, connection, action_id):
        """Read only. Accepted writes can be verified again, and uncertain creates are never repeated."""
        actor, channel, _ = self._member(workspace, token, connection)
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT manifest,status,receipt FROM public.pr_youtube_actions WHERE workspace_id=%s AND connection_id=%s AND id::text=%s', (workspace, connection, action_id))
            row = cur.fetchone()
        if not row or row[1] not in ('accepted', 'verified', 'outcome_unknown', 'started'):
            raise AlphaError('There is no accepted or ambiguous creator action to reconcile.', 409)
        manifest, status, receipt = row
        if manifest['channelId'] != channel:
            raise AlphaError('Channel identity changed.', 409)
        if not receipt or 'result' not in receipt:
            return {'id': action_id, 'status': status, 'receipt': receipt, 'note': 'No immutable accepted resource was recorded. Manual reconciliation is required; the write was not repeated.'}
        api = self._api(workspace, connection, channel)
        verification = self.verify_action(api, manifest['plan'], receipt['result'])
        receipt['verification'] = verification
        if verification.get('verified'):
            status = 'verified'
        from ..hosted import audit
        with self.service.connection_factory() as db, db.cursor() as cur:
            self.journal.assert_authorized(workspace, connection, api.grant.get('authorizationGeneration'), cursor=cur, locked=True)
            cur.execute('UPDATE public.pr_youtube_actions SET status=%s,receipt=%s::jsonb,updated_at=now() WHERE workspace_id=%s AND connection_id=%s AND id::text=%s AND privacy_erased_at IS NULL', (status, json.dumps(receipt), workspace, connection, action_id))
            if not cur.rowcount:
                return {'id': action_id, 'status': 'privacy_erased', 'receipt': None, 'dataRemoved': True, 'writeRepeated': False}
            audit(cur, workspace, actor, 'youtube.action_reconciled', action_id, {'status': status, 'connectionId': connection})
        return {'id': action_id, 'status': status, 'receipt': receipt, 'writeRepeated': False}

    def worker_api(self, manifest):
        if manifest.get('privacyErased'):
            raise AlphaError('Erased YouTube approvals cannot dispatch provider operations.', 409, code='youtube_privacy_erased')
        api = self._api(manifest['workspaceId'], manifest['channelId'], manifest.get('providerAccountId'))
        raw_options = copy.deepcopy(manifest.get('publishOptions') or {})
        native_time = raw_options.pop('publishAt', None)
        options = validate_video(raw_options, manifest.get('media') or [], manifest.get('payload', {}).get('text', ''))
        if native_time:
            options['publishAt'] = native_time  # Only initial validation/finalization require a future time; read-back must work after publication.
        self._allow(manifest['workspaceId'], manifest['channelId'], api, 'upload')
        identity = self.identity(manifest['workspaceId'], manifest['channelId'], api)
        if manifest['media'][0].get('duration', 0) > 900 and identity.get('status', {}).get('longUploadsStatus') != 'allowed':
            raise AlphaError('This channel has not proven eligibility for uploads longer than 15 minutes.', 409, code='youtube_channel_restriction')
        if options['privacyStatus'] in ('public', 'unlisted'):
            self._allow(manifest['workspaceId'], manifest['channelId'], api, 'schedule' if options.get('publishAt') else options['privacyStatus'] + '_publish')
        for present, cap in ((options.get('thumbnailAssetId'), 'thumbnail'), (options.get('captionTracks'), 'captions'), (options.get('playlistIds'), 'playlists'), (options.get('podcastPlaylistId'), 'podcasts')):
            if present:
                self._allow(manifest['workspaceId'], manifest['channelId'], api, cap)
        return api

    def upload(self, manifest, cancel=False, reconciliation=False):
        return self.engine.step(manifest, cancel=cancel, allow_initialize=not reconciliation)

    def reconcile_legacy(self, manifest, reference):
        """A pre-journal job can be inspected, but can never enter upload initiation."""
        if not reference:
            return {'state': 'held', 'confirmed': 'The legacy job has no immutable Video ID or resumable session. Reconcile it manually; Rafii will not repeat the upload.'}
        api = self._api(manifest['workspaceId'], manifest['channelId'])
        current = api.owned('videos', resource_id(reference, 'video'))
        observed = lifecycle(current)
        return {'state': 'held', 'reference': reference, 'url': 'https://www.youtube.com/watch?v=' + reference,
                'confirmed': 'The legacy Video ID resolves to the connected channel with state ' + observed['stage'] + '. Review its metadata and visibility separately; Rafii will not upload it again.'}

    def video_chunk(self, manifest, offset, size):
        if not self.service.assets:
            raise AlphaError('Private video storage is unavailable.', 503)
        asset, storage = manifest['media'][0], self.service.assets.storage
        verified = asset.get('verified') or {}
        if (asset.get('bucket') != storage.video_bucket or verified.get('container') is not True
                or verified.get('locationChecked') is not True or asset.get('durationSource') != 'container'):
            raise AlphaError('Re-verify and approve this video before upload.', 409)
        info = storage.object_info(manifest['workspaceId'], 'video', asset['objectName'])
        if (info['bytes'], info['mime'], info['etag']) != (asset['bytes'], asset['mime'], asset['etag']):
            raise AlphaError('The approved video changed.', 409, code='youtube_media_changed')
        piece = storage.read_range(manifest['workspaceId'], 'video', asset['objectName'], offset, size)
        if not piece['ranged'] and offset != 0:
            raise AlphaError('Private storage did not honor the resume range; no bytes were sent.', 503)
        return piece['data']

    def _finalize_native_schedule(self, key, state, current, api):
        """Reconcile an approved native schedule; this path never writes to Google."""
        state['nativeScheduleTracking'] = True
        channel, video_id = api.channel_id, state['videoId']
        if current.get('id') != video_id or current.get('snippet', {}).get('channelId') != channel:
            state.update(stage='held', errorCategory='youtube_schedule_tracking_conflict')
            return state
        try:
            with self.service.connection_factory() as db, db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (key[0],))
                row = cur.fetchone()
                if not row:
                    raise self._schedule_tracking_error()
                workspace_state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                root = self._schedule_tracking_root(key, state, channel, workspace_state)
                head = self._schedule_action_head(cur, root)
        except AlphaError:
            state.update(stage='held', errorCategory='youtube_schedule_tracking_conflict')
            return state
        target, canceled = state['options'].get('publishAt'), False
        if head:
            receipt = head['receipt'] or {}
            verification = receipt.get('verification') or {}
            prior_observed = verification.get('observed') or {}
            plan_status = (head['manifest']['plan'].get('body') or {}).get('status') or {}
            canceled = head['manifest']['action'] == 'video.cancel_schedule'
            target = plan_status.get('publishAt')
            verified = (head['status'] == 'verified' and verification.get('verified') is True
                        and receipt.get('actionId') == head['id'] and receipt.get('approvalDigest') == head['digest']
                        and receipt.get('channelId') == channel and receipt.get('action') == head['manifest']['action']
                        and receipt.get('source') == 'YouTube Data API'
                        and receipt.get('execution') == ('real' if api.provider.real_transport else 'transport-injected')
                        and (receipt.get('result') or {}).get('id') == video_id
                        and verification.get('resourceId') == video_id and verification.get('method') == 'videos.list'
                        and prior_observed.get('id') == video_id
                        and prior_observed.get('snippet', {}).get('channelId') == channel
                        and prior_observed.get('status', {}).get('privacyStatus') == 'private'
                        and plan_status.get('privacyStatus') == 'private'
                        and prior_observed.get('status', {}).get('publishAt') == target
                        and (target is None if canceled else isinstance(target, str) and bool(target)))
            if not verified:
                previous = state.setdefault('steps', {}).get('scheduleTracking', {})
                same = previous.get('actionId') == head['id'] and previous.get('approvalDigest') == head['digest']
                checks = previous.get('checks', 0) + 1 if same else 1
                state['steps']['scheduleTracking'] = {'status': head['status'], 'actionId': head['id'],
                    'approvalDigest': head['digest'], 'checks': checks, 'reconciliationOnly': True,
                    'humanInterventionRequired': checks >= 3}
                state.update(stage='held' if checks >= 3 else 'native_schedule_reconciling',
                             errorCategory='youtube_schedule_intervention_required' if checks >= 3 else 'youtube_schedule_verification_pending',
                             retryAt=self.clock() + 60)
                return state  # Even matching provider state cannot promote an unknown action.
            state.setdefault('steps', {})['scheduleTracking'] = {'status': 'verified', 'actionId': head['id'],
                'approvalDigest': head['digest'], 'reconciliationOnly': True, 'source': 'YouTube Data API',
                'observedAt': self.clock()}
        observed, status = lifecycle(current), current.get('status', {})
        if canceled:
            if observed['stage'] != 'processed_private' or status.get('privacyStatus') != 'private' or status.get('publishAt') is not None:
                state.update(stage='held', errorCategory='youtube_schedule_changed')
                return state
            state.update(stage='canceled', cancelRequested=True, privacyStatus='private', publishAt=None, published=False)
            state.pop('errorCategory', None)
            state.pop('retryAt', None)
            return state
        try:
            planned_at = datetime.fromisoformat(target.replace('Z', '+00:00'))
            if planned_at.tzinfo is None:
                raise ValueError('Missing schedule timezone')
        except (AttributeError, TypeError, ValueError):
            state.update(stage='held', errorCategory='youtube_schedule_tracking_conflict')
            return state
        if observed['stage'] == 'native_scheduled' and observed.get('publishAt') == target:
            state.update(observed, privacyStatus='private', retryAt=self.clock() + 300)
        elif (observed['stage'] == 'published' and observed['privacyStatus'] == state['options']['privacyStatus']
              and self.clock() >= planned_at.timestamp()):
            state.update(observed, neverPublished=False, publishAt=target)
        else:
            state.update(stage='held', errorCategory='youtube_schedule_changed')
            return state
        state.pop('errorCategory', None)
        return state

    def finalize_upload(self, key, state, current, api, save):
        options, video_id = state['options'], state['videoId']
        observed = lifecycle(current)
        if observed['stage'] == 'published':
            state['neverPublished'] = False
        from .model import upload_body
        approved = upload_body(options)
        for part in ('snippet', 'localizations', 'recordingDetails'):
            if part in approved and any(current.get(part, {}).get(k) != v for k, v in approved[part].items()):
                state.update(stage='held', errorCategory='youtube_metadata_readback_mismatch')
                return state
        approved_status = {k: v for k, v in approved['status'].items() if k not in ('privacyStatus', 'publishAt')}
        if any(current.get('status', {}).get(k) != v for k, v in approved_status.items()):
            state.update(stage='held', errorCategory='youtube_declaration_readback_mismatch')
            return state
        if (state.get('stage') in ('native_scheduled', 'native_schedule_reconciling')
                or state.get('nativeScheduleTracking') is True
                or (options.get('publishAt') and state.get('steps', {}).get('visibility', {}).get('status') == 'verified')):
            # Recovery may reset stage to uploaded_private. The durable marker
            # still forbids restoring a superseded schedule or uploading again.
            return self._finalize_native_schedule(key, state, current, api)
        ws, connection, _ = key
        with self.service.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (ws,))
            workspace_state = cur.fetchone()[0]
        steps = []
        if options.get('thumbnailAssetId'):
            steps.append(('thumbnail', 'thumbnail.set', {'id': video_id, 'assetId': options['thumbnailAssetId']}))
        for i, track in enumerate(options.get('captionTracks', [])):
            steps.append(('caption:' + str(i), 'caption.insert', {'videoId': video_id, 'track': track}))
        for playlist_id in dict.fromkeys(options.get('playlistIds', []) + ([options['podcastPlaylistId']] if options.get('podcastPlaylistId') else [])):
            if playlist_id == options.get('podcastPlaylistId') and api.owned('playlists', playlist_id).get('status', {}).get('podcastStatus') != 'enabled':
                state.update(stage='held', errorCategory='podcast_not_enabled')
                return state
            steps.append(('playlist:' + playlist_id, 'playlist.add', {'playlistId': playlist_id, 'videoId': video_id}))
        for name, action, inputs in steps:
            previous = state['steps'].get(name, {})
            if previous.get('status') == 'accepted':
                if name.startswith('caption:'):
                    tracks = api.call('captions.list', {'part': 'snippet', 'videoId': video_id, 'id': previous['resourceId']}).get('items', [])
                    status = tracks[0].get('snippet', {}).get('status') if tracks else None
                    if status == 'failed':
                        state.update(stage='held', errorCategory='caption_processing_failed'); return state
                    if status not in ('serving',):
                        state.update(stage='processing', retryAt=self.clock() + 60); return state
                if previous.get('plan') and previous.get('result') is not None:
                    verification = self.verify_action(api, previous['plan'], previous['result'])
                    if not verification.get('verified'):
                        state.update(stage='held', errorCategory=name.split(':')[0] + '_verification_pending')
                        return state
                    previous['verification'] = verification
                elif name == 'thumbnail':
                    state.update(stage='held', errorCategory='thumbnail_receipt_unavailable')
                    return state
                continue
            if previous.get('status') in ('started', 'outcome_unknown'):
                # Playlist membership is discoverable and safe to reconcile. Caption insertion has no content idempotency guarantee.
                if action != 'playlist.add':
                    state.update(stage='held', errorCategory='post_upload_outcome_unknown'); return state
                plan = api.plan(action, inputs)
                if not plan.get('noop'):
                    state.update(stage='held', errorCategory='playlist_outcome_unknown'); return state
            else:
                plan = api.plan(action, inputs)
            state['steps'][name] = {'status': 'started', 'action': action}
            save(key, state)
            try:
                def reader(asset_id):
                    frozen = next((item for item in state.get('attachments', []) if item['id'] == asset_id), None)
                    raw = self._image(ws, workspace_state, asset_id)[0]
                    if not frozen or hashlib.sha256(raw).hexdigest() != frozen['hash']:
                        raise AlphaError('The approved thumbnail changed. No thumbnail bytes were sent.', 409, code='youtube_media_changed')
                    return raw
                result = plan['result'] if plan.get('noop') else api.execute(plan, media_reader=reader)
                state['steps'][name] = {'status': 'accepted', 'resourceId': result.get('id'), 'acceptedAt': self.clock(),
                                        'source': 'YouTube Data API', 'plan': plan, 'result': redacted(result)}
                save(key, state)
                state.update(stage='processing', retryAt=self.clock() + 2)
                return state  # one independently journaled post-upload operation per worker lease
            except AlphaError as error:
                if getattr(error, 'category', None) == 'revoked_oauth' or error.code == 'youtube_revoked_oauth':
                    raise
                state['steps'][name] = {'status': 'outcome_unknown' if getattr(error, 'ambiguous', False) else 'failed', 'category': getattr(error, 'category', 'api_error')}
                state.update(stage='held', errorCategory=state['steps'][name]['category']); save(key, state); return state
        target = {'privacyStatus': 'private' if options.get('publishAt') else options['privacyStatus']}
        if options.get('publishAt'):
            target['publishAt'] = options['publishAt']
            if datetime.fromisoformat(options['publishAt'].replace('Z', '+00:00')).timestamp() <= self.clock():
                state.update(stage='held', errorCategory='youtube_invalid_scheduling_state'); return state
        status = current.get('status', {})
        if any(status.get(k) != v for k, v in target.items()):
            if not has_scopes(api.grant['scopes'], (MANAGE,)):
                state.update(stage='held', errorCategory='scope_missing'); return state
            state['steps']['visibility'] = {'status': 'started', 'target': target}
            save(key, state)
            body = merged_update('videos', current, {'status': target})
            try:
                api.call('videos.update', {'part': 'status'}, body)
            except AlphaError as error:
                if getattr(error, 'category', None) == 'revoked_oauth' or error.code == 'youtube_revoked_oauth':
                    raise
                state.update(stage='outcome_unknown' if getattr(error, 'ambiguous', False) else 'held', errorCategory=getattr(error, 'category', 'api_error'))
                return state
            current = api.owned('videos', video_id)
            status = current.get('status', {})
        if any(status.get(k) != v for k, v in target.items()) or status.get('selfDeclaredMadeForKids') != options['madeForKids'] or status.get('containsSyntheticMedia') != options['containsSyntheticMedia']:
            state.update(stage='held', errorCategory='youtube_readback_mismatch'); return state
        state['steps']['visibility'] = {'status': 'verified', 'observedAt': self.clock(), 'source': 'YouTube Data API'}
        state.update(lifecycle(current), retryAt=self.clock() + 300)
        if state['stage'] == 'native_scheduled':
            state['nativeScheduleTracking'] = True
        if state['stage'] == 'published':
            state['neverPublished'] = False
        state.update(privacyStatus=status.get('privacyStatus'), publishAt=status.get('publishAt'))
        return state

    def ingest_comments(self, workspace, connection, api, items):
        from .comments import ingest
        ingest(self.service.connection_factory, workspace, connection, api.channel_id, items, self.clock())
