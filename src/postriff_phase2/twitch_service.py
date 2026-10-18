"""Twitch native workspace service: real custody, exact consent and durable dispatch.

No live call occurs at construction, overview, or when release gates are closed.
All outbound writes originate from an approved, actor/tenant/generation-bound row.
The queue commits a dispatch fence before attempting the provider. An interrupted
or ambiguous write is never retried automatically. Native results and webhooks are
untrusted data, encrypted at rest, and never instruction or permission evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError
from .permissions import Membership, require
from .twitch_eventsub import EVENT_TYPES, SubscriptionTrust, TwitchWebhookError, TwitchWebhookVerifier

APP_ORIGIN = 'https://rafii.io'
APP_TOKEN = 'https://id.twitch.tv/oauth2/token'
HELIX = 'https://api.twitch.tv/helix'
APPROVAL_SECONDS = 600
MAX_SCHEDULE_SECONDS = 30 * 86400
CONTENT_TTL = 86400
PRE_DISPATCH = ('draft', 'approved', 'paused')
TERMINAL = ('cancelled', 'succeeded', 'accepted', 'partial', 'failed', 'outcome_unknown', 'expired', 'revoked')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_CONNECTION = re.compile(r'^[A-Za-z0-9_.:-]{1,120}$')
ACTION_COLUMNS = ('id', 'workspace_id', 'connection_id', 'actor', 'action', 'generation',
    'payload', 'manifest', 'payload_hash', 'state', 'execute_at', 'approval_deadline',
    'expires_at', 'approved_at', 'approved_by', 'agent_origin', 'permission_token',
    'lease_id', 'dispatched_at', 'completed_at', 'result', 'error', 'created_at', 'updated_at')
ACTION_SELECT = ','.join(ACTION_COLUMNS)
LIMITATIONS = [
    'Offline contracts are verified separately from live OAuth, EventSub delivery and production deployment.',
    'Each write needs approval of its exact payload, destination, authorization generation and execution time.',
    'Stream Schedule creates calendar entries. An encoder and ingest connection start an actual broadcast.',
    'Stream keys use the separate recent-sign-in secret route and never enter agent context or ordinary results.',
    'Viewer count is a live sample. General Helix does not expose Creator Dashboard watch time, retention or revenue.',
    'Clip download links are short-lived and require a rights declaration. No general VOD download or upload API is claimed.',
]


def _error(code, status=409):
    return AlphaError('Twitch request cannot proceed: ' + code.replace('_', ' ') + '.', status, code='twitch_' + code)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise _error('invalid_payload', 400) from None


def _object(value, keys):
    if not isinstance(value, dict) or not value.keys() <= set(keys):
        raise _error('invalid_fields', 400)
    if len(_json(value).encode()) > 32768:
        raise _error('payload_too_large', 413)
    return value


def _identifier(value, *, connection=False):
    if not isinstance(value, str) or not (_CONNECTION if connection else _UUID).fullmatch(value):
        raise _error('resource_unavailable', 404)
    return value


def _epoch(value):
    return value.timestamp() if isinstance(value, datetime) else float(value)


def _iso(value):
    return datetime.fromtimestamp(_epoch(value), timezone.utc).isoformat().replace('+00:00', 'Z')


def _when(value, now):
    if value is None:
        return now
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value):
        raise _error('invalid_execution_time', 400)
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        raise _error('invalid_execution_time', 400) from None
    if not math.isfinite(result) or not now <= result <= now + MAX_SCHEDULE_SECONDS:
        raise _error('execution_time_out_of_range', 400)
    return result


def _is_agent():
    from .agent_runtime_v2 import authz
    return authz.IN_TOOL.get() or authz.ACTIVE_CONTEXT.get() is not None


def _right(action, *, write=True):
    if not write:
        return 'read'
    if action.startswith('twitch.eventsub.') or action in ('twitch.stream.key.get', 'twitch.clip.download'):
        return 'manage_connections'
    if action.startswith(('twitch.moderation.', 'twitch.automod.', 'twitch.shield.', 'twitch.ban.', 'twitch.timeout.', 'twitch.warning.')):
        return 'moderate'
    if action.startswith('twitch.chat.'):
        return 'moderate' if any(part in action for part in ('delete', 'clear', 'settings', 'color', 'pin', 'announcement', 'shoutout')) else 'reply'
    return 'approve'


def _audit(cur, ws, actor, kind, subject, meta=None):
    from .hosted import audit
    audit(cur, ws, actor, 'twitch.' + kind, str(subject), meta)


class TwitchService:
    def __init__(self, service, *, clock=None, content_storage_approved=False, agent_processing_approved=False):
        self.service = service
        self.repository = service.repository
        self.factory = service.connection_factory
        self.oauth = service.oauth
        self.vault = service.oauth.vault
        self.clock = clock or service.clock
        self.content_storage_approved = content_storage_approved is True
        self.agent_processing_approved = agent_processing_approved is True
        self.verifier = TwitchWebhookVerifier(clock=self.clock)
        # Runs inside the existing workspace -> credential custody transaction.
        self.oauth.twitch_lifecycle = self.lifecycle

    @property
    def provider(self):
        return self.oauth.providers.get('twitch')

    @property
    def enabled(self):
        provider = self.provider
        return bool(provider and provider.execution_enabled and provider.public_connect_enabled and provider.commercial_approved)

    def _enabled(self):
        if not self.enabled:
            raise _error('release_blocked')
        self.provider.assert_enabled()

    @staticmethod
    def _ready(cur):
        cur.execute("SELECT to_regclass('public.pr_twitch_actions') IS NOT NULL")
        return bool(cur.fetchone()[0])

    def _require_ready(self, cur):
        if not self._ready(cur):
            raise _error('migration_pending', 503)

    def _seal(self, value):
        ciphertext, key = self.vault.encrypt(_json(value))
        return {'ciphertext': ciphertext, 'keyId': key}

    def _open(self, value):
        if not value:
            return {}
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or set(value) != {'ciphertext', 'keyId'}:
            raise _error('stored_content_invalid', 503)
        return json.loads(self.vault.decrypt(value['ciphertext'], value['keyId']))

    def _credential(self, cur, ws, conn, *, lock=False, active=True):
        _identifier(ws); _identifier(conn, connection=True)
        cur.execute('SELECT provider,provider_account_id,scopes,access_ciphertext,key_id,revoked_at,access_expires_at '
                    'FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s' + (' FOR UPDATE' if lock else ''), (ws, conn))
        row = cur.fetchone()
        if not row or row[0] != 'twitch':
            raise _error('connection_unavailable', 404)
        if active and (row[5] is not None or not row[3]):
            raise _error('reauthorization_required')
        generation = None
        binding_invalid = False
        if row[3] and self.provider:
            try:
                generation = self.provider.credential_generation(self.vault.decrypt(row[3], row[4]))
            except AlphaError:
                if active:
                    raise
                binding_invalid = True
        return {'provider': row[0], 'providerAccountId': row[1], 'scopes': list(row[2] or []),
                'generation': generation, 'revoked': row[5] is not None or binding_invalid, 'expires': row[6]}

    def _connection_view(self, cur, ws, conn, state):
        credential = self._credential(cur, ws, conn, active=False)
        channel = next((item for item in state.get('phase2', {}).get('channels', []) if item.get('id') == conn and item.get('platform') == 'Twitch'), {})
        return {'id': conn, 'account': channel.get('account') or 'Twitch account',
            'providerAccountId': credential['providerAccountId'], 'scopes': credential['scopes'],
            'status': 'reauthorization_required' if credential['revoked'] else 'connected',
            'authorizationGeneration': credential['generation']}

    def readiness(self, *, schema=False):
        return {'publicConnect': self.enabled, 'configured': self.provider is not None,
                'commercialApproved': bool(self.provider and self.provider.commercial_approved),
                'contentStorageApproved': self.content_storage_approved, 'agentProcessingApproved': self.agent_processing_approved,
                'migrationReady': schema, 'productionVerified': False, 'liveOAuthVerified': False,
                'liveEventSubVerified': False, 'callback': APP_ORIGIN + '/api/oauth/twitch/callback'}

    def list_connections(self, ws, token):
        with self.repository.transaction(token, ws) as (cur, row, _):
            require(Membership.from_row(*row[2:7]), 'read')
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            cur.execute("SELECT connection_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND provider='twitch' ORDER BY connection_id LIMIT 100", (ws,))
            identifiers = [r[0] for r in cur.fetchall()]
            connections = [self._connection_view(cur, ws, conn, state) for conn in identifiers]
            return {'connections': connections, 'capabilities': [], 'readiness': self.readiness(schema=self._ready(cur)), 'limitations': LIMITATIONS}

    def _capabilities(self, connection, member, context=None):
        from .twitch_native import OPERATIONS, capabilities
        entries = capabilities()
        if isinstance(entries, dict):
            entries = entries.get('capabilities', [])
        items = []
        held = set(connection['scopes'])
        for entry in entries:
            item = dict(entry)
            op = OPERATIONS.get(item['action'])
            if op is None:
                items.append(item)
                continue
            reasons = []
            if not self.enabled:
                reasons.append('Operator release and commercial authorization are pending.')
            if connection['status'] != 'connected':
                reasons.append('Reconnect this account.')
            if not any(set(option) <= held for option in op.scope_options):
                reasons.append('Grant the exact Twitch permissions for this action.')
            if not member.allows(_right(op.action, write=op.write or op.risk == 'secret' or op.action == 'twitch.clip.download')):
                reasons.append('Your current workspace role cannot perform this action.')
            if op.risk == 'secret':
                reasons.append('Use the separate recent-sign-in encoder secret handler.')
            if op.eligibility and (not context or context['accountType'] not in ('affiliate', 'partner')):
                reasons.append('Twitch account eligibility requires a fresh provider check.')
            if op.requires_live and (not context or not context['isLive']):
                reasons.append('This operation requires a live broadcast; preview checks Twitch again.')
            if op.action == 'twitch.clip.download':
                reasons.append('Use the approved rights declaration and secure download-link route.')
            item.update(availability={'state': 'blocked' if reasons else 'available', 'reasons': reasons},
                verification='blocked' if reasons else 'unverified', offlineContract='verified',
                fields=op.fields, write=op.write, requiredScopes=[list(option) for option in op.scope_options],
                canUpgrade=self.enabled and member.allows('manage_connections') and not any(set(option) <= held for option in op.scope_options),
                interactiveAvailable=op.action in ('twitch.stream.key.get','twitch.clip.download') and self.enabled and connection['status']=='connected' and member.allows('manage_connections') and any(set(option)<=held for option in op.scope_options) and (op.action!='twitch.clip.download' or self.content_storage_approved),
                workspacePermission=_right(op.action, write=op.write or op.risk == 'secret' or op.action=='twitch.clip.download'),
                effects=list(op.effects), risk=op.risk, schedulable=op.schedulable)
            items.append(item)
        for name, spec in EVENT_TYPES.items():
            reasons = []
            if not self.content_storage_approved:
                reasons.append('Event content storage requires recorded purpose authorization.')
            if not self.enabled:
                reasons.append('Operator release and commercial authorization are pending.')
            if connection['status'] != 'connected':
                reasons.append('Reconnect this account.')
            if not any(set(option) <= held for option in spec['scope_options']):
                reasons.append('Grant the exact Twitch permissions for this subscription.')
            if not member.allows('manage_connections'):
                reasons.append('Connection-management permission is required.')
            items.append({'action': 'twitch.eventsub.subscribe.' + name, 'label': 'Receive ' + name,
                'group': 'eventsub', 'write': True, 'fields': {}, 'requiredScopes': spec['scopes'],
                'availability': {'state': 'blocked' if reasons else 'available', 'reasons': reasons},
                'verification': 'blocked' if reasons else 'unverified', 'offlineContract': 'verified',
                'canUpgrade': self.enabled and member.allows('manage_connections') and not any(set(option) <= held for option in spec['scope_options']),
                'workspacePermission': 'manage_connections',
                'effects': ['Creates a signed EventSub webhook subscription for this account. Event content is encrypted and expires within 24 hours.'],
                'risk': 'subscription', 'schedulable': False})
        items.append({'action': 'twitch.eventsub.unsubscribe', 'label': 'Stop an EventSub subscription',
            'group': 'eventsub', 'write': True, 'fields': {'subscriptionId': {'type': 'string', 'label': 'Rafii subscription ID', 'required': True, 'maxLength': 36}},
            'requiredScopes': [], 'workspacePermission': 'manage_connections', 'canUpgrade': False, 'liveVerified': False,
            'availability': {'state': 'available' if self.enabled and member.allows('manage_connections') else 'blocked', 'reasons': []},
            'verification': 'unverified', 'effects': ['Stops the selected webhook and purges its stored event content.'], 'risk': 'subscription', 'schedulable': False})
        for action, label, fields in (
                ('twitch.account.verify', 'Verify account eligibility and live status', {}),
                ('twitch.eventsub.events', 'Read received chat and notifications', {
                    'after': {'type': 'integer', 'label': 'After event ID', 'minimum': 0, 'maximum': 9007199254740991},
                    'limit': {'type': 'integer', 'label': 'Events per page', 'minimum': 1, 'maximum': 100}})):
            items.append({'action': action, 'label': label, 'group': 'account' if 'account' in action else 'eventsub',
                'write': False, 'fields': fields, 'requiredScopes': [], 'workspacePermission': 'read',
                'availability': {'state': 'available' if self.enabled and connection['status'] == 'connected' else 'blocked',
                    'reasons': [] if self.enabled else ['Operator release and commercial authorization are pending.']},
                'verification': 'unverified', 'effects': [], 'risk': 'read', 'schedulable': False})
        return items

    def overview(self, ws, token, conn):
        with self.repository.transaction(token, ws) as (cur, row, _):
            member = Membership.from_row(*row[2:7]); require(member, 'read')
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            connection = self._connection_view(cur, ws, conn, state)
            ready = self._ready(cur)
            actions, subscriptions, context = [], [], None
            if ready:
                cur.execute('SELECT account_type,is_live FROM public.pr_twitch_context WHERE workspace_id=%s AND connection_id=%s AND generation=%s AND expires_at>to_timestamp(%s)', (ws, conn, connection['authorizationGeneration'], self.clock()))
                cached = cur.fetchone()
                if cached:
                    context = {'accountType': cached[0], 'isLive': cached[1]}
                cur.execute('SELECT ' + ACTION_SELECT + ' FROM public.pr_twitch_actions WHERE workspace_id=%s AND connection_id=%s ORDER BY created_at DESC,id DESC LIMIT 50', (ws, conn))
                actions = [self._present(dict(zip(ACTION_COLUMNS, a))) for a in cur.fetchall()]
                cur.execute('SELECT id::text,type,version,state,provider_subscription_id FROM public.pr_twitch_subscriptions WHERE workspace_id=%s AND connection_id=%s AND generation=%s ORDER BY created_at DESC LIMIT 100', (ws, conn, connection['authorizationGeneration']))
                subscriptions = [dict(zip(('id', 'type', 'version', 'state', 'providerSubscriptionId'), r)) for r in cur.fetchall()]
            return {'workspaceId': ws, 'connection': connection, 'capabilities': self._capabilities(connection, member, context),
                'actions': actions, 'eventSub': {'subscriptions': subscriptions, 'retentionHours': 24, 'historicalChatAvailable': False},
                'readiness': self.readiness(schema=ready), 'limitations': LIMITATIONS}

    def _grant(self, ws, conn):
        self._enabled()
        grant = self.oauth.token_for_worker(ws, conn)
        if grant.get('provider') != 'twitch' or not grant.get('providerAccountId') or not grant.get('authorizationGeneration'):
            raise _error('credential_binding_invalid')
        return grant

    def _fence(self, cur, ws, conn, grant):
        credential = self._credential(cur, ws, conn, lock=True)
        if (credential['generation'] != grant['authorizationGeneration'] or credential['providerAccountId'] != grant['providerAccountId']
                or set(credential['scopes']) != set(grant['scopes'])):
            raise _error('authorization_changed')
        return credential

    def _provider_context(self, grant):
        """Only provider-returned identity/eligibility/live state may satisfy predicates."""
        provider = self.oauth.provider_for_grant(grant)
        headers = {'Client-Id': provider.client_id, 'Authorization': 'Bearer ' + provider.raw_access_token(grant['accessToken'])}
        try:
            users = provider.transport('GET', HELIX + '/users', headers=headers)
            streams = provider.transport('GET', HELIX + '/streams?' + urlencode({'user_id': grant['providerAccountId']}), headers=headers)
            user_rows = users['body']['data']; stream_rows = streams['body']['data']
            if users['status'] != 200 or streams['status'] != 200 or not isinstance(user_rows, list) or len(user_rows) != 1 or user_rows[0]['id'] != grant['providerAccountId'] or not isinstance(stream_rows, list) or len(stream_rows) > 1:
                raise ValueError
            if stream_rows and stream_rows[0].get('user_id') != grant['providerAccountId']:
                raise ValueError
            account_type = user_rows[0].get('broadcaster_type', '')
            if account_type not in ('', 'affiliate', 'partner'):
                raise ValueError
            return {'accountType': account_type, 'isLive': bool(stream_rows), 'observedAt': self.clock()}
        except Exception:
            raise _error('eligibility_unverified', 503) from None

    def _save_context(self, cur, ws, conn, grant, context):
        cur.execute('INSERT INTO public.pr_twitch_context(workspace_id,connection_id,generation,account_type,is_live,observed_at,expires_at) '
            'VALUES(%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(workspace_id,connection_id) DO UPDATE SET '
            'generation=excluded.generation,account_type=excluded.account_type,is_live=excluded.is_live,observed_at=excluded.observed_at,expires_at=excluded.expires_at',
            (ws, conn, grant['authorizationGeneration'], context['accountType'], context['isLive'], context['observedAt'], context['observedAt'] + 300))

    def _prepare(self, action, payload, grant, context, *, rights_confirmed=False, marker_attestation=False):
        from .twitch_native import OPERATIONS, prepare_operation
        if action.startswith('twitch.eventsub.subscribe.'):
            _object(payload, ())
            event_type = action[len('twitch.eventsub.subscribe.'):]
            spec = EVENT_TYPES.get(event_type)
            if not self.content_storage_approved:
                raise _error('eventsub_content_storage_not_authorized', 403)
            if not spec or not any(set(option) <= set(grant['scopes']) for option in spec['scope_options']):
                raise _error('eventsub_scope_missing', 403)
            if spec['eligible'] and context['accountType'] not in ('affiliate', 'partner'):
                raise _error('account_ineligible', 403)
            condition = {'broadcaster_user_id': grant['providerAccountId']}
            if spec['moderator']:
                condition['moderator_user_id'] = grant['providerAccountId']
            if spec['chat']:
                condition['user_id'] = grant['providerAccountId']
            return {'action': action, 'payload': {}, 'type': event_type, 'version': spec['version'], 'condition': condition,
                'write': True, 'effects': ['Creates this webhook subscription and stores encrypted event data for up to 24 hours.'], 'risk': 'subscription'}
        if action == 'twitch.eventsub.unsubscribe':
            _object(payload, ('subscriptionId',)); _identifier(payload.get('subscriptionId'))
            return {'action': action, 'payload': payload, 'write': True, 'risk': 'subscription', 'effects': ['Stops the selected subscription and purges its events.']}
        op = OPERATIONS.get(action)
        if op is None:
            raise _error('operation_unavailable', 404)
        rights = None
        if op.resource_policy:
            from .twitch_native import verify_resource_access, validate_operation_payload, resource_ids_for_operation, RightsEvidence
            provider = self.oauth.provider_for_grant(grant)
            payload = validate_operation_payload(action, payload)
            kind, resource_ids = resource_ids_for_operation(action, payload)
            if kind == 'marker_settings':
                if marker_attestation is not True or not context['isLive']:
                    raise _error('past_broadcasts_attestation_required', 403)
                # Twitch exposes no Helix setting that proves VOD storage is on.
                # Preserve the user's exact declaration, never invent API proof.
                evidence_now = self.clock()
                rights = RightsEvidence(grant['providerAccountId'], grant['providerAccountId'], kind, (), provider.client_id,
                    evidence_now, evidence_now + 300, ownership_verified=True,
                    metadata_json='{"past_broadcasts_enabled":true,"broadcast_type":"live"}')
            else:
                rights = verify_resource_access(kind, resource_ids, client_id=provider.client_id,
                access_token=provider.raw_access_token(grant['accessToken']), subject_id=grant['providerAccountId'],
                broadcaster_id=grant['providerAccountId'], scopes=grant['scopes'], transport=provider.transport, now=self.clock(),
                reuse_authorized=rights_confirmed, storage_authorized=rights_confirmed and self.content_storage_approved)
        return prepare_operation(action, payload, subject_id=grant['providerAccountId'], broadcaster_id=grant['providerAccountId'],
            scopes=grant['scopes'], account_type=context['accountType'], live=context['isLive'], rights=rights, now=self.clock())

    @staticmethod
    def _manifest(prepared):
        return prepared.as_dict() if hasattr(prepared, 'as_dict') else prepared

    def read(self, ws, token, conn, action, body):
        from .twitch_native import OPERATIONS, execute
        _object(body, ('payload',))
        payload = body.get('payload', {})
        if _is_agent() and (not self.agent_processing_approved or action not in ('twitch.stream.get','twitch.analytics.stream.snapshot','twitch.channel.followers.total')):
            raise _error('agent_data_purpose_not_authorized', 403)
        if action == 'twitch.account.verify':
            _object(payload, ())
            with self.repository.transaction(token, ws) as (cur, row, _):
                require(Membership.from_row(*row[2:7]), 'read'); self._credential(cur, ws, conn)
            grant = self._grant(ws, conn); context = self._provider_context(grant)
            with self.repository.transaction(token, ws) as (cur, row, _):
                require(Membership.from_row(*row[2:7]), 'read'); self._fence(cur, ws, conn, grant)
                self._require_ready(cur); self._save_context(cur, ws, conn, grant, context)
                return {'action': action, 'status': 'confirmed', 'confirmed': True, 'data': context}
        if action == 'twitch.eventsub.events':
            return self.events(ws, token, conn, payload)
        op = OPERATIONS.get(action)
        if op is None or op.write or op.risk == 'secret' or action == 'twitch.clip.download':
            raise _error('explicit_approval_required', 403)
        # Authenticate membership before token validation or any external read.
        with self.repository.transaction(token, ws) as (cur, row, _):
            require(Membership.from_row(*row[2:7]), 'read'); self._credential(cur, ws, conn)
        grant = self._grant(ws, conn)
        context = self._provider_context(grant) if op.eligibility or op.requires_live else {'accountType': '', 'isLive': False, 'observedAt': self.clock()}
        prepared = self._prepare(action, payload, grant, context)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            require(Membership.from_row(*row[2:7]), 'read'); self._fence(cur, ws, conn, grant)
            provider = self.oauth.provider_for_grant(grant)
            result = execute(provider.client_id, provider.raw_access_token(grant['accessToken']), prepared, provider.transport, now=self.clock())
            _audit(cur, ws, actor, 'read', conn, {'action': action, 'generation': grant['authorizationGeneration']})
            return result

    def preview(self, ws, token, conn, body):
        from .twitch_native import OPERATIONS
        _object(body, ('action', 'payload', 'executeAt', 'rightsConfirmed', 'pastBroadcastsEnabled'))
        if _is_agent() and not self.agent_processing_approved:
            raise _error('agent_data_purpose_not_authorized', 403)
        action, payload = body.get('action'), body.get('payload', {})
        if not isinstance(action, str):
            raise _error('operation_unavailable', 404)
        op = OPERATIONS.get(action)
        special = action.startswith('twitch.eventsub.subscribe.') or action == 'twitch.eventsub.unsubscribe'
        sensitive = op is not None and (op.risk == 'secret' or action == 'twitch.clip.download')
        if not special and (op is None or (not op.write and not sensitive)):
            raise _error('read_does_not_need_queue', 400)
        rights_confirmed = body.get('rightsConfirmed') is True
        marker_attestation = body.get('pastBroadcastsEnabled') is True
        if 'pastBroadcastsEnabled' in body and (op is None or op.resource_policy != 'marker_settings' or not marker_attestation or _is_agent()):
            raise _error('invalid_marker_attestation', 403)
        if 'rightsConfirmed' in body and (action != 'twitch.clip.download' or not rights_confirmed):
            raise _error('invalid_rights_declaration', 400)
        if action == 'twitch.clip.download' and (not rights_confirmed or not self.content_storage_approved):
            raise _error('rights_declaration_required', 403)
        if sensitive and _is_agent():
            raise _error('interactive_secret_access_required', 403)
        # PostgreSQL timestamps use microseconds; hash exactly that precision.
        now = round(self.clock(), 6); execute_at = _when(body.get('executeAt'), now)
        if execute_at != now and (special or sensitive or not op.schedulable):
            raise _error('operation_not_schedulable', 400)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            self._require_ready(cur); require(Membership.from_row(*row[2:7]), _right(action))
            self._credential(cur, ws, conn)
            if sensitive:
                self.repository.assert_fresh(token, actor)
        grant = self._grant(ws, conn)
        context = self._provider_context(grant)
        prepared = self._prepare(action, payload, grant, context, rights_confirmed=rights_confirmed, marker_attestation=marker_attestation)
        manifest = self._manifest(prepared)
        normalized = manifest.get('payload', payload)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            self._require_ready(cur); require(Membership.from_row(*row[2:7]), _right(action))
            self._fence(cur, ws, conn, grant)
            if action == 'twitch.eventsub.unsubscribe':
                self._subscription(cur, ws, conn, payload['subscriptionId'], grant['authorizationGeneration'])
            generation = grant['authorizationGeneration']
            envelope = {'v': 1, 'workspace': ws, 'connection': conn, 'actor': str(actor), 'generation': generation,
                'action': action, 'payload': normalized, 'manifest': manifest, 'executeAt': execute_at,
                'rightsConfirmed': rights_confirmed, 'pastBroadcastsEnabled': marker_attestation, 'scheduled': body.get('executeAt') is not None}
            digest = hashlib.sha256(_json(envelope).encode()).hexdigest()
            identifier = str(uuid.uuid4())
            permission_token = None
            if _is_agent():
                from .agent_runtime_v2.agent_permissions import load
                permission_token = load(cur, ws, actor, now=now).token()
            cur.execute('INSERT INTO public.pr_twitch_actions(id,workspace_id,connection_id,actor,action,generation,payload,manifest,payload_hash,state,execute_at,approval_deadline,expires_at,agent_origin,permission_token,created_at,updated_at) '
                "VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,'draft',to_timestamp(%s),to_timestamp(%s),to_timestamp(%s),%s,%s,to_timestamp(%s),to_timestamp(%s))",
                (identifier, ws, conn, actor, action, generation, _json(self._seal(normalized)), _json(self._seal(envelope)), digest,
                 execute_at, now + APPROVAL_SECONDS, max(execute_at, now) + APPROVAL_SECONDS, _is_agent(), permission_token, now, now))
            self._save_context(cur, ws, conn, grant, context)
            _audit(cur, ws, actor, 'preview', identifier, {'action': action, 'payloadHash': digest, 'generation': generation, 'agentOrigin': _is_agent()})
            return self._present(self._action(cur, ws, conn, identifier))

    def _action(self, cur, ws, conn, identifier, *, lock=False):
        _identifier(identifier)
        cur.execute('SELECT ' + ACTION_SELECT + ' FROM public.pr_twitch_actions WHERE id=%s AND workspace_id=%s AND connection_id=%s' + (' FOR UPDATE' if lock else ''), (identifier, ws, conn))
        row = cur.fetchone()
        if not row:
            raise _error('action_unavailable', 404)
        return dict(zip(ACTION_COLUMNS, row))

    def _present(self, action):
        envelope = self._open(action['manifest'])
        manifest = envelope.get('manifest', {})
        return {'id': str(action['id']), 'actorId': str(action['actor']), 'action': action['action'], 'payload': self._open(action['payload']),
            'payloadHash': action['payload_hash'], 'state': action['state'], 'executeAt': _iso(action['execute_at']),
            'expiresAt': _iso(action['approval_deadline']), 'generation': action['generation'],
            'scheduled': envelope.get('scheduled') is True,
            'declarations': {'rightsConfirmed': envelope.get('rightsConfirmed') is True, 'pastBroadcastsEnabled': envelope.get('pastBroadcastsEnabled') is True},
            'effects': manifest.get('effects', []), 'risk': manifest.get('risk', 'write'),
            'result': self._open(action['result']) if action['result'] else None, 'error': action['error']}

    def _integrity(self, action):
        envelope = self._open(action['manifest'])
        actual = hashlib.sha256(_json(envelope).encode()).hexdigest()
        if not hmac.compare_digest(actual, action['payload_hash']) or any((
                envelope.get('workspace') != str(action['workspace_id']), envelope.get('connection') != action['connection_id'],
                envelope.get('actor') != str(action['actor']), envelope.get('generation') != action['generation'],
                envelope.get('action') != action['action'], envelope.get('payload') != self._open(action['payload']),
                envelope.get('executeAt') != _epoch(action['execute_at']))):
            raise _error('approval_integrity_failed')
        return envelope

    def approve(self, ws, token, conn, identifier, body):
        from .agent_runtime_v2.api_guard import require_session_token
        require_session_token(token)
        if _is_agent():
            raise _error('human_approval_required', 403)
        _object(body, ('payloadHash', 'confirmed'))
        if body.get('confirmed') is not True or not isinstance(body.get('payloadHash'), str):
            raise _error('explicit_approval_required', 400)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            self._enabled(); self._require_ready(cur)
            credential = self._credential(cur, ws, conn, lock=True)
            action = self._action(cur, ws, conn, identifier, lock=True)
            require(Membership.from_row(*row[2:7]), _right(action['action']))
            if str(action['actor']) != str(actor):
                raise _error('approval_actor_mismatch', 403)
            self._integrity(action)
            if action['generation'] != credential['generation']:
                raise _error('authorization_changed')
            if not hmac.compare_digest(action['payload_hash'], body['payloadHash']):
                raise _error('approval_payload_changed')
            if self.clock() >= _epoch(action['approval_deadline']):
                raise _error('approval_expired')
            if action['state'] == 'approved':
                return self._present(action)
            if action['state'] != 'draft':
                raise _error('action_not_approvable')
            self.repository.assert_fresh(token, actor)
            cur.execute("UPDATE public.pr_twitch_actions SET state='approved',approved_by=%s,approved_at=to_timestamp(%s),updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s", (actor, self.clock(), self.clock(), identifier, ws, conn))
            _audit(cur, ws, actor, 'approved', identifier, {'payloadHash': action['payload_hash'], 'action': action['action'], 'generation': action['generation']})
            return self._present(self._action(cur, ws, conn, identifier))

    def cancel(self, ws, token, conn, identifier, body, *, pause=False):
        _object(body, ())
        with self.repository.transaction(token, ws) as (cur, row, actor):
            self._require_ready(cur); self._credential(cur, ws, conn, lock=True, active=False)
            action = self._action(cur, ws, conn, identifier, lock=True)
            require(Membership.from_row(*row[2:7]), _right(action['action']))
            if action['state'] not in PRE_DISPATCH:
                raise _error('action_already_dispatched')
            state = 'paused' if pause else 'cancelled'
            cur.execute('UPDATE public.pr_twitch_actions SET state=%s,updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s', (state, self.clock(), identifier, ws, conn))
            _audit(cur, ws, actor, state, identifier, {'action': action['action']})
            return self._present(self._action(cur, ws, conn, identifier))

    @contextmanager
    def _worker_transaction(self, ws, conn, identifier):
        """Same global lock order as OAuth and human commands; no stale role cache."""
        with self.factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ws,))
            found = cur.fetchone()
            if not found:
                raise _error('workspace_unavailable', 403)
            state = json.loads(found[0]) if isinstance(found[0], str) else found[0]
            if state.get('accountDeletion') or state.get('accountBlock'):
                raise _error('workspace_blocked', 403)
            credential = self._credential(cur, ws, conn, lock=True)
            action = self._action(cur, ws, conn, identifier, lock=True)
            cur.execute('SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status=\'active\' AND p.deleted_at IS NULL', (ws, action['actor']))
            member = cur.fetchone()
            if not member:
                raise _error('membership_revoked', 403)
            require(Membership.from_row(*member), _right(action['action']))
            if action['generation'] != credential['generation']:
                raise _error('authorization_changed')
            if action['agent_origin']:
                if not self.agent_processing_approved:
                    raise _error('agent_data_purpose_not_authorized',403)
                from .agent_runtime_v2.agent_permissions import load
                if load(cur, ws, str(action['actor']), now=self.clock()).token() != action['permission_token']:
                    raise _error('agent_permission_changed', 403)
            if action['approved_at'] is None or str(action['approved_by']) != str(action['actor']):
                raise _error('human_approval_required', 403)
            if self.clock() >= _epoch(action['expires_at']):
                raise _error('execution_expired')
            yield cur, action, credential

    def _finish(self, cur, action, state, *, result=None, error=None):
        cur.execute('UPDATE public.pr_twitch_actions SET state=%s,result=%s::jsonb,error=%s,completed_at=to_timestamp(%s),updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s',
            (state, _json(self._seal(result)) if result is not None else None, error, self.clock(), self.clock(), action['id'], action['workspace_id'], action['connection_id']))
        _audit(cur, str(action['workspace_id']), action['actor'], state, action['id'], {'action': action['action'], 'payloadHash': action['payload_hash'], 'error': error})

    def _blocked_action(self, ws, conn, identifier, reason):
        # Called after a failed transaction rolls back. Never turn an in-flight
        # or completed action into a retryable state, or expose exception text.
        with self.factory() as db, db.cursor() as cur:
            cur.execute('SELECT id FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (ws,))
            if not cur.fetchone():
                return
            cur.execute('SELECT connection_id FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s FOR UPDATE', (ws, conn))
            if not cur.fetchone():
                return
            action = self._action(cur, ws, conn, identifier, lock=True)
            if action['state'] == 'approved':
                self._finish(cur, action, 'failed', error=reason)
            elif action['state'] == 'dispatching':
                self._finish(cur, action, 'outcome_unknown', error='dispatch_interrupted')

    def dispatch_one(self, ws, conn, identifier):
        from .twitch_native import execute, TwitchNativeError
        if not self.enabled:
            return {'state': 'blocked', 'reason': 'release_blocked'}
        try:
            # First recheck actor/tenant/approval before any token-validation egress.
            with self._worker_transaction(ws, conn, identifier) as (_, initial, _):
                if initial['state'] != 'approved' or _epoch(initial['execute_at']) > round(self.clock(),6):
                    return {'state': initial['state'], 'dispatched': False}
                if initial['action'] in ('twitch.stream.key.get', 'twitch.clip.download'):
                    return {'state': 'approved', 'interactiveAccessRequired': True}
                self._integrity(initial)
            grant = self._grant(ws, conn)
            context = self._provider_context(grant)
            with self._worker_transaction(ws, conn, identifier) as (cur, action, _):
                self._fence(cur, ws, conn, grant)
                if action['state'] != 'approved':
                    return {'state': action['state'], 'dispatched': False}
                envelope = self._integrity(action)
                prepared = self._prepare(action['action'], envelope['payload'], grant, context, rights_confirmed=envelope['rightsConfirmed'], marker_attestation=envelope.get('pastBroadcastsEnabled', False))
                if self._manifest(prepared) != envelope['manifest']:
                    raise _error('approved_manifest_changed')
                lease = str(uuid.uuid4())
                cur.execute("UPDATE public.pr_twitch_actions SET state='dispatching',lease_id=%s,dispatched_at=to_timestamp(%s),updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s", (lease, self.clock(), self.clock(), identifier, ws, conn))
                if action['action'].startswith('twitch.eventsub.subscribe.'):
                    self._persist_subscription(cur, action, prepared)
                # Commit the fence before any native mutation, including EventSub.
            with self._worker_transaction(ws, conn, identifier) as (cur, action, _):
                self._fence(cur, ws, conn, grant)
                if action['state'] != 'dispatching' or str(action['lease_id']) != lease:
                    return {'state': action['state'], 'dispatched': False}
                try:
                    if action['action'].startswith('twitch.eventsub.'):
                        result = self._execute_eventsub(cur, action, prepared, grant)
                    else:
                        provider = self.oauth.provider_for_grant(grant)
                        result = execute(provider.client_id, provider.raw_access_token(grant['accessToken']), prepared, provider.transport, now=self.clock())
                    final = 'succeeded' if result.get('confirmed') is True else 'partial' if result.get('status') == 'partial' else 'accepted'
                    self._finish(cur, action, final, result=result)
                    return {'id': identifier, 'state': final, 'result': result}
                except TwitchNativeError as exc:
                    final = 'outcome_unknown' if exc.unknown_result else 'failed'
                    self._finish(cur, action, final, error=exc.reason)
                    return {'id': identifier, 'state': final, 'error': exc.reason}
                except Exception:
                    self._finish(cur, action, 'outcome_unknown', error='provider_outcome_unknown')
                    return {'id': identifier, 'state': 'outcome_unknown'}
        except AlphaError as exc:
            safe = getattr(exc, 'code', None) or 'execution_blocked'
            self._blocked_action(ws, conn, identifier, safe[:120])
            return {'id': identifier, 'state': 'blocked', 'reason': safe}

    def secret_access(self, ws, token, conn, identifier, body):
        """One recent-session retrieval; no secret is stored, audited or sent to agents."""
        from .agent_runtime_v2.api_guard import require_session_token
        from .twitch_native import execute, execute_sensitive
        _object(body, ('payloadHash', 'confirmed'))
        require_session_token(token)
        if _is_agent() or body.get('confirmed') is not True:
            raise _error('interactive_secret_access_required', 403)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            require(Membership.from_row(*row[2:7]), 'manage_connections')
            self.repository.assert_fresh(token, actor)
            self._credential(cur, ws, conn, lock=True)
            action = self._action(cur, ws, conn, identifier, lock=True)
            if action['action'] not in ('twitch.stream.key.get', 'twitch.clip.download') or str(action['actor']) != str(actor) or action['state'] != 'approved':
                raise _error('secret_action_unavailable', 403)
            if not isinstance(body.get('payloadHash'), str) or not hmac.compare_digest(body['payloadHash'], action['payload_hash']):
                raise _error('approval_payload_changed')
            self._integrity(action)
        grant = self._grant(ws, conn)
        context = self._provider_context(grant)
        with self.repository.transaction(token, ws) as (cur, row, actor):
            require(Membership.from_row(*row[2:7]), 'manage_connections')
            self.repository.assert_fresh(token, actor); self._fence(cur, ws, conn, grant)
            action = self._action(cur, ws, conn, identifier, lock=True)
            if action['state'] != 'approved' or action['generation'] != grant['authorizationGeneration'] or self.clock() >= _epoch(action['expires_at']):
                raise _error('secret_action_expired')
            envelope = self._integrity(action)
            prepared = self._prepare(action['action'], envelope['payload'], grant, context, rights_confirmed=envelope['rightsConfirmed'])
            if self._manifest(prepared) != envelope['manifest']:
                raise _error('approved_manifest_changed')
            provider = self.oauth.provider_for_grant(grant)
            if action['action'] == 'twitch.stream.key.get':
                delivered = []
                result = execute_sensitive(provider.client_id, provider.raw_access_token(grant['accessToken']), prepared, provider.transport, secret_sink=delivered.append, now=self.clock())
                result['data'] = {'streamKey': delivered.pop()}
            else:
                result = execute(provider.client_id, provider.raw_access_token(grant['accessToken']), prepared, provider.transport, now=self.clock())
            self._finish(cur, action, 'succeeded', result={'secretDelivered': True, 'stored': False})
            return {'action': action['action'], 'secretResult': result, 'stored': False, 'displayOnce': True}

    def lifecycle(self, cur, ws, conn, event, generation):
        if not self._ready(cur):
            if event in ('connected', 'scope_changed'):
                raise _error('migration_pending', 503)
            return
        # Keep a content-free audit/queue receipt, purge all provider content.
        cur.execute("UPDATE public.pr_twitch_actions SET state=CASE WHEN state='dispatching' THEN 'outcome_unknown' WHEN state IN ('draft','approved','paused') THEN 'revoked' ELSE state END,payload='{}'::jsonb,manifest='{}'::jsonb,result=NULL,error=%s,updated_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s AND generation<>coalesce(%s,'')", (event, self.clock(), ws, conn, generation if event == 'connected' else None))
        # Serialize with any callback before taking the DELETE snapshot. A
        # callback already holding this subscription lock must commit first;
        # then its just-arrived encrypted event is included in the purge.
        cur.execute("UPDATE public.pr_twitch_subscriptions SET state='cleanup_pending',secret_ciphertext='',updated_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s AND generation<>coalesce(%s,'') AND state NOT IN ('inactive','revoked')", (self.clock(), ws, conn, generation if event == 'connected' else None))
        cur.execute('DELETE FROM public.pr_twitch_events WHERE workspace_id=%s AND connection_id=%s', (ws, conn))
        cur.execute('DELETE FROM public.pr_twitch_context WHERE workspace_id=%s AND connection_id=%s', (ws, conn))

    def _subscription(self, cur, ws, conn, identifier, generation=None, *, lock=False):
        _identifier(identifier)
        cur.execute('SELECT id::text,generation,provider_subscription_id,type,version,condition,state,secret_ciphertext,secret_key_id FROM public.pr_twitch_subscriptions WHERE id=%s AND workspace_id=%s AND connection_id=%s' + (' FOR UPDATE' if lock else ''), (identifier, ws, conn))
        row = cur.fetchone()
        if not row or (generation is not None and row[1] != generation):
            raise _error('subscription_unavailable', 404)
        return dict(zip(('id','generation','providerId','type','version','condition','state','ciphertext','keyId'), row))

    def _persist_subscription(self, cur, action, prepared):
        identifier = str(uuid.uuid4())
        secret, key = self.vault.encrypt(secrets.token_urlsafe(32))
        cur.execute('INSERT INTO public.pr_twitch_subscriptions(id,workspace_id,connection_id,generation,action_id,type,version,condition,state,secret_ciphertext,secret_key_id) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'pending',%s,%s) ON CONFLICT(workspace_id,connection_id,generation,type,version) DO NOTHING RETURNING id", (identifier, action['workspace_id'], action['connection_id'], action['generation'], action['id'], prepared['type'], prepared['version'], _json(prepared['condition']), secret, key))
        if not cur.fetchone():
            raise _error('subscription_already_registered')

    def _app_token(self):
        self._enabled()
        provider = self.provider
        try:
            response = provider.transport('POST', APP_TOKEN, form={'client_id': provider.client_id, 'client_secret': provider.client_secret, 'grant_type': 'client_credentials'})
            token = response['body']['access_token']
            if response['status'] != 200 or not isinstance(token, str) or not re.fullmatch(r'[\x21-\x7e]{1,4096}', token):
                raise ValueError
            return token
        except Exception:
            raise _error('app_token_unavailable', 503) from None

    def _execute_eventsub(self, cur, action, prepared, grant):
        from .twitch_native import TwitchNativeError
        headers = {'Client-Id': self.provider.client_id, 'Authorization': 'Bearer ' + self._app_token()}
        ws, conn = str(action['workspace_id']), action['connection_id']
        if action['action'] == 'twitch.eventsub.unsubscribe':
            item = self._subscription(cur, ws, conn, prepared['payload']['subscriptionId'], action['generation'], lock=True)
            if not item['providerId']:
                raise _error('provider_subscription_id_unverified')
            response = self.provider.transport('DELETE', HELIX + '/eventsub/subscriptions?' + urlencode({'id': item['providerId']}), headers=headers)
            if response.get('status') not in (204, 404):
                raise TwitchNativeError('eventsub_delete_failed', unknown_result=response.get('status', 500) >= 500)
            cur.execute("UPDATE public.pr_twitch_subscriptions SET state='inactive',secret_ciphertext='' WHERE id=%s AND workspace_id=%s AND connection_id=%s", (item['id'], ws, conn))
            cur.execute('DELETE FROM public.pr_twitch_events WHERE subscription_id=%s AND workspace_id=%s AND connection_id=%s', (item['id'], ws, conn))
            return {'action': action['action'], 'status': 'confirmed', 'confirmed': True, 'data': {'subscriptionId': item['id'], 'state': 'inactive'}}
        cur.execute('SELECT id::text FROM public.pr_twitch_subscriptions WHERE workspace_id=%s AND connection_id=%s AND action_id=%s', (ws, conn, action['id']))
        row = cur.fetchone()
        if not row:
            raise _error('subscription_trust_missing')
        item = self._subscription(cur, ws, conn, row[0], action['generation'])
        callback = APP_ORIGIN + '/api/twitch/eventsub/' + item['id']
        body = {'type': item['type'], 'version': item['version'], 'condition': item['condition'], 'transport': {'method': 'webhook', 'callback': callback, 'secret': self.vault.decrypt(item['ciphertext'], item['keyId'])}}
        # Callback trust is already committed. The callback uses a separate short
        # receipt transaction and does not wait for this workspace dispatch lock.
        response = self.provider.transport('POST', HELIX + '/eventsub/subscriptions', headers=headers, body=body)
        if response.get('status') != 202:
            raise TwitchNativeError('eventsub_create_failed', unknown_result=response.get('status', 500) >= 500)
        rows = response.get('body', {}).get('data')
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0].get('id'), str) or rows[0].get('type') != item['type'] or rows[0].get('version') != item['version'] or rows[0].get('condition') != item['condition']:
            raise TwitchNativeError('eventsub_create_response_invalid', unknown_result=True)
        provider_id = rows[0]['id']
        cur.execute('UPDATE public.pr_twitch_subscriptions SET provider_subscription_id=coalesce(provider_subscription_id,%s),updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s AND (provider_subscription_id IS NULL OR provider_subscription_id=%s)', (provider_id, self.clock(), item['id'], ws, conn, provider_id))
        if cur.rowcount != 1:
            raise TwitchNativeError('eventsub_provider_binding_conflict', unknown_result=True)
        return {'action': action['action'], 'status': 'accepted', 'confirmed': False, 'data': {'subscriptionId': item['id'], 'providerSubscriptionId': provider_id, 'state': 'verification_pending'}}

    def webhook(self, identifier, headers, raw):
        _identifier(identifier)
        # No workspace mutation lock here: Create Subscription can wait on the
        # challenge. Trust row CAS + generation predicates make that race safe.
        with self.factory() as db, db.cursor() as cur:
            cur.execute('SELECT workspace_id::text,connection_id FROM public.pr_twitch_subscriptions WHERE id=%s', (identifier,))
            target = cur.fetchone()
            if not target:
                raise _error('webhook_unavailable', 404)
            ws, conn = target
            item = self._subscription(cur, ws, conn, identifier, lock=True)
            if item['state'] not in ('pending', 'enabled') or not item['ciphertext']:
                raise _error('webhook_inactive', 410)
            # A plain SELECT sees the last committed custody grant. A concurrent
            # revoke purges this event after the callback commit; dispatch fences
            # and inbox reads additionally require the current generation.
            credential = self._credential(cur, ws, conn)
            if credential['generation'] != item['generation']:
                raise _error('webhook_generation_revoked', 410)
            trusted = SubscriptionTrust(item['providerId'] or '', item['type'], item['version'], item['condition'], ws, conn,
                item['generation'], self.vault.decrypt(item['ciphertext'], item['keyId']), allow_pending_binding=item['state'] == 'pending')
            try:
                verified = self.verifier.verify(headers, raw, trusted)
            except TwitchWebhookError:
                raise _error('webhook_authentication_failed', 403) from None
            if verified.kind == 'notification' and not self.content_storage_approved:
                # Authenticated acknowledgement without storing viewer content.
                # Existing data is purged by maintenance after purpose withdrawal.
                return b'', False
            cur.execute('SELECT id FROM public.pr_twitch_events WHERE subscription_id=%s AND message_id=%s', (identifier, verified.message_id))
            if cur.fetchone():
                return verified.challenge or b'', True
            if verified.kind == 'webhook_callback_verification':
                cur.execute("UPDATE public.pr_twitch_subscriptions SET provider_subscription_id=%s,state='enabled',updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s AND (provider_subscription_id IS NULL OR provider_subscription_id=%s)", (verified.subscription_id, self.clock(), identifier, ws, conn, verified.subscription_id))
                if cur.rowcount != 1:
                    raise _error('webhook_binding_conflict')
            if verified.kind == 'revocation':
                cur.execute("UPDATE public.pr_twitch_subscriptions SET state='revoked',secret_ciphertext='',updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s", (self.clock(), identifier, ws, conn))
                cur.execute('DELETE FROM public.pr_twitch_events WHERE subscription_id=%s AND workspace_id=%s AND connection_id=%s', (identifier, ws, conn))
            sealed, key = self.vault.encrypt(_json({'event': verified.event, 'reason': verified.revocation_reason}))
            cur.execute('INSERT INTO public.pr_twitch_events(subscription_id,workspace_id,connection_id,generation,message_id,type,message_kind,payload_ciphertext,payload_key_id,received_at,expires_at) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT(subscription_id,message_id) DO NOTHING',
                (identifier, ws, conn, item['generation'], verified.message_id, item['type'], verified.kind, sealed, key, self.clock(), self.clock() + CONTENT_TTL))
            return verified.challenge or b'', False

    def events(self, ws, token, conn, payload):
        _object(payload, ('after', 'limit'))
        if not self.content_storage_approved:
            raise _error('eventsub_content_storage_not_authorized',403)
        after, limit = payload.get('after', 0), payload.get('limit', 50)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise _error('invalid_event_page', 400)
        if _is_agent():
            raise _error('viewer_content_egress_not_authorized', 403)
        with self.repository.transaction(token, ws) as (cur, row, _):
            require(Membership.from_row(*row[2:7]), 'read')
            credential = self._credential(cur, ws, conn)
            self._require_ready(cur)
            cur.execute('SELECT e.id,e.type,e.message_kind,e.payload_ciphertext,e.payload_key_id,e.received_at FROM public.pr_twitch_events e JOIN public.pr_twitch_subscriptions s ON s.id=e.subscription_id '
                "WHERE e.workspace_id=%s AND e.connection_id=%s AND e.generation=%s AND e.id>%s AND e.expires_at>to_timestamp(%s) AND s.state='enabled' ORDER BY e.id LIMIT %s", (ws, conn, credential['generation'], after, self.clock(), limit))
            rows = cur.fetchall()
            events = [{'id': row[0], 'type': row[1], 'kind': row[2], 'data': json.loads(self.vault.decrypt(row[3], row[4])), 'receivedAt': _iso(row[5])} for row in rows]
            return {'action': 'twitch.eventsub.events', 'status': 'confirmed', 'confirmed': True, 'data': events,
                'pagination': {'after': rows[-1][0] if rows else after}, 'provenance': {'source': 'signed_eventsub', 'historyAvailable': False}}

    def maintenance(self, *, limit=25):
        """Bounded local cleanup/recovery first; never replays a native mutation."""
        limit = max(1, min(int(limit), 100))
        with self.factory() as db, db.cursor() as cur:
            if not self._ready(cur):
                return {'enabled': False, 'migrationReady': False}
            now = self.clock()
            cur.execute("UPDATE public.pr_twitch_actions SET state='expired',error='approval_expired',updated_at=to_timestamp(%s) WHERE state IN ('draft','paused') AND approval_deadline<=to_timestamp(%s)", (now, now))
            cur.execute("UPDATE public.pr_twitch_actions SET state='expired',error='execution_expired',updated_at=to_timestamp(%s) WHERE state='approved' AND expires_at<=to_timestamp(%s)", (now, now))
            cur.execute("UPDATE public.pr_twitch_actions SET state='outcome_unknown',error='interrupted_dispatch_never_retried',updated_at=to_timestamp(%s) WHERE state='dispatching' AND dispatched_at<=to_timestamp(%s)", (now, now - 300))
            recovered = cur.rowcount
            cur.execute("UPDATE public.pr_twitch_actions SET payload='{}'::jsonb,manifest='{}'::jsonb,result=NULL WHERE state IN ('cancelled','succeeded','accepted','partial','failed','outcome_unknown','expired','revoked') AND updated_at<=to_timestamp(%s) AND manifest<>'{}'::jsonb", (now - CONTENT_TTL,))
            # Keep actions -> subscriptions -> events order, including cleanup.
            # An inverse event/action order can deadlock with disconnect/unsubscribe.
            if not self.content_storage_approved:
                cur.execute("UPDATE public.pr_twitch_subscriptions SET state='cleanup_pending',secret_ciphertext='',updated_at=to_timestamp(%s) WHERE state IN ('pending','enabled')",(now,))
                cur.execute('DELETE FROM public.pr_twitch_events')
            else:
                cur.execute('DELETE FROM public.pr_twitch_events WHERE expires_at<=to_timestamp(%s)', (now,))
            purged = cur.rowcount
            cur.execute("UPDATE public.pr_twitch_events SET state='processed',processed_at=to_timestamp(%s) WHERE id IN (SELECT id FROM public.pr_twitch_events WHERE state='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT %s)", (now, limit))
            processed = cur.rowcount
            cur.execute("SELECT workspace_id::text,connection_id,id::text FROM public.pr_twitch_actions WHERE state='approved' AND execute_at<=to_timestamp(%s) AND action NOT IN ('twitch.stream.key.get','twitch.clip.download') ORDER BY execute_at,id LIMIT %s", (now, limit))
            candidates = cur.fetchall()
        executions = [self.dispatch_one(*row) for row in candidates] if self.enabled else []
        validation = self.validation_tick(limit=min(limit, 10)) if self.enabled else {'enabled': False}
        cleanup = self.cleanup_subscriptions(limit=min(limit, 10)) if self.enabled else {'enabled': False}
        return {'enabled': self.enabled, 'purgedEvents': purged, 'processedEvents': processed, 'recoveredUnknown': recovered,
            'actions': executions, 'validation': validation, 'subscriptionCleanup': cleanup}

    def validation_tick(self, *, limit=10, startup=False):
        """Durable cursor resumes an idle-session sweep across worker restarts.

        Continuous workers call this until next is null; cron also calls it. A
        finished sweep starts again within 55 minutes. Rollout must demonstrate
        that configured worker capacity completes every customer's sweep hourly.
        """
        if not self.enabled:
            return {'enabled': False}
        now = self.clock(); lease = str(uuid.uuid4())
        with self.factory() as db, db.cursor() as cur:
            self._require_ready(cur)
            cur.execute("INSERT INTO public.pr_twitch_maintenance(name) VALUES('validation') ON CONFLICT DO NOTHING")
            cur.execute("SELECT cursor,lease_until,completed_at FROM public.pr_twitch_maintenance WHERE name='validation' FOR UPDATE")
            cursor, lease_until, completed = cur.fetchone()
            if (lease_until and _epoch(lease_until)>now) or (not startup and cursor is None and completed and _epoch(completed)>now-3300):
                return {'enabled': True, 'state': 'waiting'}
            cur.execute("UPDATE public.pr_twitch_maintenance SET lease_id=%s,lease_until=to_timestamp(%s) WHERE name='validation'", (lease, now+600))
        result = self.oauth.validate_twitch_connections(limit=limit, after=cursor)
        with self.factory() as db, db.cursor() as cur:
            cur.execute("UPDATE public.pr_twitch_maintenance SET cursor=%s::jsonb,lease_until=NULL,completed_at=CASE WHEN %s THEN to_timestamp(%s) ELSE NULL END WHERE name='validation' AND lease_id=%s",
                (_json(result['next']) if result['next'] else None, result['next'] is None, self.clock(), lease))
        return result

    def cleanup_subscriptions(self, *, limit=10):
        """Previously authorized revocation cleanup. DELETE+404 is idempotent.

        A create with an unknown provider ID is never recreated or deleted by a
        guessed ID. The operator must reconcile that subscription first.
        """
        if not self.enabled:
            return {'enabled': False}
        with self.factory() as db, db.cursor() as cur:
            cur.execute("SELECT id::text,workspace_id::text,connection_id,provider_subscription_id FROM public.pr_twitch_subscriptions WHERE state='cleanup_pending' AND provider_subscription_id IS NOT NULL ORDER BY updated_at LIMIT %s", (limit,))
            rows = cur.fetchall()
        if not rows:
            return {'deleted': 0}
        headers = {'Client-Id': self.provider.client_id, 'Authorization': 'Bearer '+self._app_token()}
        deleted = 0
        for identifier, ws, conn, provider_id in rows:
            try:
                response = self.provider.transport('DELETE', HELIX+'/eventsub/subscriptions?'+urlencode({'id': provider_id}), headers=headers)
            except Exception:
                continue
            if response.get('status') not in (204,404):
                continue
            with self.factory() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_twitch_subscriptions SET state='inactive',secret_ciphertext='',updated_at=to_timestamp(%s) WHERE id=%s AND workspace_id=%s AND connection_id=%s AND state='cleanup_pending' AND provider_subscription_id=%s", (self.clock(),identifier,ws,conn,provider_id))
                deleted += cur.rowcount
        return {'deleted': deleted}

    def reconcile(self, ws, token, conn, identifier, body):
        """An explicit provider GET may confirm an accepted clip. Never resend it."""
        from .twitch_native import prepare_operation, execute
        _object(body, ())
        with self.repository.transaction(token,ws) as (cur,row,_):
            require(Membership.from_row(*row[2:7]),'read'); self._credential(cur,ws,conn)
            action=self._action(cur,ws,conn,identifier)
            if action['state'] not in ('accepted','outcome_unknown'):
                return self._present(action)
            previous=self._open(action['result']) if action['result'] else {}
            confirmation=previous.get('confirmation')
            if not isinstance(confirmation,dict) or confirmation.get('action')!='twitch.clip.lookup':
                raise _error('provider_result_requires_manual_reconciliation')
        grant=self._grant(ws,conn)
        prepared=prepare_operation('twitch.clip.lookup',confirmation['payload'],subject_id=grant['providerAccountId'],
            broadcaster_id=grant['providerAccountId'],scopes=grant['scopes'],now=self.clock())
        with self.repository.transaction(token,ws) as (cur,row,_):
            require(Membership.from_row(*row[2:7]),'read'); self._fence(cur,ws,conn,grant)
            action=self._action(cur,ws,conn,identifier,lock=True)
            if action['generation']!=grant['authorizationGeneration'] or action['state'] not in ('accepted','outcome_unknown'):
                raise _error('action_authorization_changed')
            provider=self.oauth.provider_for_grant(grant)
            result=execute(provider.client_id,provider.raw_access_token(grant['accessToken']),prepared,provider.transport,now=self.clock())
            expected=set(confirmation['payload']['id'])
            found={item.get('id') for item in result.get('data',[]) if isinstance(item,dict)}
            if expected == found:
                self._finish(cur,action,'succeeded',result={'action':action['action'],'status':'confirmed','confirmed':True,'data':result['data'],'reconciledBy':'twitch.clip.lookup'})
            return self._present(self._action(cur,ws,conn,identifier))

