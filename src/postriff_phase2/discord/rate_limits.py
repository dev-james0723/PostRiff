"""Default-off Discord REST admission in the existing PostgreSQL connection.

Operational pacing is a reviewed, expiring policy, not a provider quota claim.
HTTP runs after transactions commit. A publish permit cannot replace approval:
it is sealed with the existing intent and consumed once after a live SQL guard.
Shared tables contain opaque keys/statuses, never tokens, bodies or content.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError

STATE = 'public.pr_discord_rate_state'
ROUTES = 'public.pr_discord_route_buckets'
ADMISSIONS = 'public.pr_discord_request_admissions'
MAX_EPOCH = 253402300799.0  # representable through year9999; excessive hints hold
_ID = re.compile(r'^[0-9]{5,25}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')
_LABEL = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')


class RateCoordinatorUnavailable(AlphaError):
    def __init__(self):
        super().__init__('Discord request coordination is unavailable. Restore the reviewed rate policy or reconnect; no request was sent.',
                         503, code='discord_rate_coordinator_unavailable')


class _ExclusiveObservationRequired(RateCoordinatorUnavailable):
    """Rollback the read-sharing attempt before retrying this outcome once."""


class RateDelayed(AlphaError):
    """Denied before HTTP, with an unshortened provider/DB deadline."""
    def __init__(self, seconds=300.0, *, cause='rate_budget', scope='unknown'):
        super().__init__('Discord is waiting for shared request capacity; no request was sent.',
                         429, code='discord_rate_delayed')
        self.retry_after_seconds = max(.001, float(seconds)) if valid_number(seconds) and seconds > 0 else 300.0
        self.rate_cause = cause
        self.rate_scope_kind = scope if scope in ('application','discovery','learned_route','unknown_route',
                                                 'embargo','permit','unknown') else 'unknown'


class UnconsumedPublishPermit(RateDelayed):
    """Private transport signal: consume denied before provider I/O began."""
    def __init__(self, permit_id, seconds):
        super().__init__(seconds, cause='permit_expired', scope='permit')
        self.permit_id = permit_id


class ReadAdmissionDelayed(RateDelayed):
    """Minted only when a GET is denied inside pre-transport admission."""
    def __init__(self, error):
        super().__init__(error.retry_after_seconds, cause=error.rate_cause, scope=error.rate_scope_kind)


def observation_remaining(previous, reported, *, first, pending, newly_mapped=0, current_unmapped=0):
    """Conservative credit after one response, with distinct admission counts.

    A first valid response replaces the one-slot probe with header capacity.
    Its reported remaining already includes this observing request. All OTHER
    unresolved admissions are counted once across the old route/alias union.
    For a known alias, debit newly mapped work (including this request only if
    not previously mapped), then only tighten; never refill from a response.
    Sent work may already appear in the provider's count: without proof, reserve
    that uncertainty conservatively rather than grant capacity twice.
    """
    if (type(first) is not bool or any(type(v) is not int or v < 0 for v in
            (previous,reported,pending,newly_mapped,current_unmapped)) or current_unmapped > 1
            or newly_mapped > pending):
        raise RateCoordinatorUnavailable()
    ceiling = max(0,reported-pending)
    return ceiling if first else max(0,min(previous-newly_mapped-current_unmapped,ceiling))


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def seconds(value, *, maximum=MAX_EPOCH):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= maximum else None


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def route_identity(method, path):
    """Bounded REST templates with exact allowlisted read query shapes.

    Secret-bearing form bodies and webhook path tokens never enter stored
    route labels; raw paths become hashes. Only exact supported shapes pass.
    """
    if method not in ('GET', 'POST', 'DELETE', 'PUT', 'PATCH') or not isinstance(path, str) or len(path) > 500:
        raise RateCoordinatorUnavailable()
    url = urlsplit(path)
    if not path.startswith('/') or url.scheme or url.netloc or url.fragment or '%' in url.path or '//' in url.path:
        raise RateCoordinatorUnavailable()
    if url.path.startswith('/webhooks/'):
        # Token is never stored: only a template and hashed webhook/token major.
        match = re.fullmatch(r'/webhooks/([0-9]{5,25})/([A-Za-z0-9_-]{20,256})(?:/messages/([0-9]{5,25}))?', url.path)
        if (not match or method not in ('GET', 'POST') or method == 'POST' and (match[3] or url.query != 'wait=true')
                or method == 'GET' and url.query):
            raise RateCoordinatorUnavailable()
        return (method + ':/webhooks/{id}/{token}' + ('/messages/{id}' if match[3] else ''),
                _digest('webhooks:' + match[1] + ':' + match[2]))
    if url.query:
        try:
            query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise RateCoordinatorUnavailable() from None
        server_list = (url.path == '/users/@me/guilds' and not set(query) - {'limit', 'after'}
                       and query.get('limit') == ['200'] and ('after' not in query or
                           len(query['after']) == 1 and _ID.fullmatch(query['after'][0])))
        message_page = (re.fullmatch(r'/channels/[0-9]{5,25}/messages', url.path)
                        and query == {'limit': ['50']})
        guild_counts = (re.fullmatch(r'/guilds/[0-9]{5,25}', url.path)
                        and query == {'with_counts': ['true']})
        if method != 'GET' or not (server_list or message_page or guild_counts):
            raise RateCoordinatorUnavailable()
    parts = url.path.strip('/').split('/')
    if len(parts) > 8 or any(not p or p in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_@-]+', p) for p in parts):
        raise RateCoordinatorUnavailable()
    major = 'none'
    if parts[0] in ('channels', 'guilds'):
        if len(parts) < 2 or not _ID.fullmatch(parts[1]):
            raise RateCoordinatorUnavailable()
        major = parts[0] + ':' + parts[1]
    elif parts[0] == 'users':
        if parts[1:2] != ['@me']:
            raise RateCoordinatorUnavailable()
        if len(parts) == 4 and parts[2] == 'guilds' and _ID.fullmatch(parts[3]):
            major = 'guilds:' + parts[3]
    elif parts[0] != 'oauth2':
        raise RateCoordinatorUnavailable()
    template = method + ':/' + '/'.join('{id}' if _ID.fullmatch(p) else p for p in parts)
    allowed = {
        'GET:/users/@me', 'GET:/users/@me/guilds', 'DELETE:/users/@me/guilds/{id}',
        'GET:/oauth2/@me', 'GET:/oauth2/applications/@me', 'POST:/oauth2/token', 'POST:/oauth2/token/revoke',
        'GET:/channels/{id}', 'GET:/channels/{id}/messages', 'GET:/channels/{id}/messages/{id}',
        'POST:/channels/{id}/messages', 'GET:/guilds/{id}', 'GET:/guilds/{id}/channels',
        'GET:/guilds/{id}/members/{id}'}
    if template not in allowed:
        raise RateCoordinatorUnavailable()
    return template, _digest(major)


def _headers(response):
    raw = response.get('headers') if isinstance(response, dict) else None
    return {k.lower(): v for k, v in raw.items() if isinstance(k, str)} if isinstance(raw, dict) else {}


def retry_hint(response, now):
    """Return (delay, malformed). Missing/invalid429 hints never grant capacity."""
    header = _headers(response).get('retry-after')
    body = response.get('body') if isinstance(response, dict) else None
    raw = [v for v in (header, body.get('retry_after') if isinstance(body, dict) else None) if v is not None]
    values = []
    malformed = not raw
    for value in raw:
        number = seconds(value)
        if number is None and isinstance(value, str):
            try:
                dt = parsedate_to_datetime(value)
                number = max(0, dt.timestamp() - now) if dt.tzinfo else None
            except (ValueError, TypeError, OverflowError):
                number = None
        if number is None or now + number > MAX_EPOCH:
            malformed = True
        else:
            values.append(number)
    return max(values, default=0.0), malformed


def _retry_after(response):
    # Compatibility only. Transport uses the DB observation's computed delay.
    import time
    delay, invalid = retry_hint(response, time.time())
    return delay if not invalid else 300.0


def classify_response(response, credential_kind='bot'):
    headers = _headers(response)
    status = response.get('status') if isinstance(response, dict) else None
    scope = str(headers.get('x-ratelimit-scope', '')).lower()
    body = response.get('body') if isinstance(response, dict) else None
    global_limit = status == 429 and (scope == 'global' or str(headers.get('x-ratelimit-global')).lower() == 'true'
                                      or isinstance(body, dict) and body.get('global') is True)
    if global_limit:
        scope = 'global'  # conflicting shared/global evidence takes stricter accounting
    webhook_invalid = status == 404 and credential_kind == 'webhook'
    return {'status': status if type(status) is int and 100 <= status <= 599 else 503,
            'scope': scope if scope in ('global', 'shared', 'user') else 'unknown',
            'global': global_limit, 'invalid': status in (401, 403) or webhook_invalid or status == 429 and scope != 'shared',
            'permanent': status in (400, 401, 403, 404), 'webhookInvalid': webhook_invalid}


@dataclass(frozen=True)
class SafetyPolicy:
    revision: str
    issued_at: float
    expires_at: float
    egress_scope: str
    app_capacity: int
    app_window_seconds: float
    unknown_window_seconds: float
    invalid_capacity: int
    invalid_window_seconds: float
    failure_threshold: int
    circuit_seconds: float
    permit_ttl_seconds: float
    read_attempts: int

    @classmethod
    def parse(cls, raw):
        try:
            value = json.loads(raw) if isinstance(raw, str) and len(raw) <= 4096 else raw
            fields = set(cls.__dataclass_fields__)
            if not isinstance(value, dict) or set(value) != fields | {'version'} or type(value['version']) is not int or value['version'] != 1:
                raise ValueError()
            numbers = fields - {'revision', 'egress_scope'}
            if any(not valid_number(value[k]) for k in numbers):
                raise ValueError()
            for k in ('app_capacity', 'invalid_capacity', 'failure_threshold', 'read_attempts'):
                if type(value[k]) is not int:
                    raise ValueError()
            if (not _LABEL.fullmatch(value['revision']) or not _LABEL.fullmatch(value['egress_scope'])
                    or not 0 <= value['issued_at'] < value['expires_at'] <= MAX_EPOCH
                    or value['expires_at'] - value['issued_at'] > 86400 * 31
                    or not 1 <= value['app_capacity'] <= 100000 or not 1 <= value['invalid_capacity'] <= 100000
                    or not 1 <= value['failure_threshold'] <= 100 or not 1 <= value['read_attempts'] <= 5
                    or any(not .05 <= value[k] <= 86400 for k in
                           ('app_window_seconds', 'unknown_window_seconds', 'invalid_window_seconds', 'circuit_seconds'))
                    or not .05 <= value['permit_ttl_seconds'] <= 10):
                raise ValueError()
            return cls(**{k: value[k] for k in fields})
        except (ValueError, TypeError, KeyError, OverflowError):
            raise RateCoordinatorUnavailable() from None

    def require_current(self, now):
        if not self.issued_at <= now < self.expires_at:
            raise RateCoordinatorUnavailable()


@dataclass(frozen=True)
class RequestIdentity:
    auth_key: str
    credential_key: str
    kind: str

    @classmethod
    def make(cls, application, kind, credential, user_id=None):
        if not _ID.fullmatch(application) or kind not in ('bot', 'user', 'oauth', 'webhook') or not isinstance(credential, str) or not credential:
            raise RateCoordinatorUnavailable()
        if user_id is not None and not _ID.fullmatch(user_id):
            raise RateCoordinatorUnavailable()
        fingerprint = _digest(credential)
        account = fingerprint if kind == 'webhook' else application if kind != 'user' else user_id or 'unverified:' + fingerprint
        return cls(_digest(kind + ':' + account), _digest(kind + ':' + application + ':' + fingerprint), kind)


def publish_binding(job, workspace, worker):
    """Hash all approval authority plus the worker fence; no customer text."""
    from .authorization import digest
    try:
        manifest = job['manifest']
        target = manifest['discord']['target']
        if (workspace != manifest['workspaceId'] or target['workspaceId'] != workspace
                or job['id'] != manifest['discord']['publicationId'] or not worker
                or not job.get('leaseId') or not _HASH.fullmatch(job['approvalDigest'])
                or not _HASH.fullmatch(job['discordAuthorization']['digest'])):
            raise ValueError()
        return {'workspaceId': str(uuid.UUID(workspace)), 'publicationId': job['id'],
                'manifestDigest': digest(manifest), 'authorizationDigest': job['discordAuthorization']['digest'],
                'approvalDigest': job['approvalDigest'], 'workerKey': _digest(worker),
                'leaseKey': _digest(job['leaseId']), 'channelKey': _digest(target['channelId']),
                'applicationKey': _digest(target['applicationId']),
                **({'webhookKey': _digest(target['webhookId'])} if target.get('senderKind') == 'webhook' else {})}
    except (KeyError, ValueError, TypeError, AttributeError):
        raise RateCoordinatorUnavailable() from None


def binding_hash(binding):
    from .authorization import digest
    return digest(binding) if binding is not None else None


@dataclass(frozen=True)
class Permit:
    id: str
    application_key: str
    method: str
    path_key: str
    identity: RequestIdentity
    binding_hash: str | None
    expires_at: float


class SharedPostgresBudget:
    """Short ordered SQL reservations; no workspace reads during rate locks.

    Mapping row -> sorted scope rows is the lock order for reserve/observe.
    Seal/consume use workspace -> credential -> admission only. They never take
    scope locks. Lost/ambiguous admissions are never refunded in their window.
    Uncertain sends conservatively retain one slot across resets until resolved.
    """
    def __init__(self, connection_factory, application_id, *, policy=None, **_compat):
        if not isinstance(application_id, str) or not _ID.fullmatch(application_id):
            raise RateCoordinatorUnavailable()
        self.connection_factory, self.application_id = connection_factory, application_id
        self.application_key = _digest(application_id)
        # The legacy runtime constructor can attach an inert coordinator. OAuth
        # attaches the reviewed policy before use; absence never enables a request.
        self.policy = SafetyPolicy.parse(policy) if policy is not None else None

    @contextmanager
    def _transaction(self):
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT set_config('lock_timeout','2000ms',true),set_config('statement_timeout','5000ms',true)")
                yield cur
        except (RateCoordinatorUnavailable, RateDelayed):
            raise
        except Exception:
            raise RateCoordinatorUnavailable() from None

    @staticmethod
    def _now(cur):
        cur.execute('SELECT extract(epoch from clock_timestamp())::double precision')
        row = cur.fetchone()
        if not row or not valid_number(row[0]):
            raise RateCoordinatorUnavailable()
        return row[0]

    def _policy(self, cur, *, forward=True):
        now = self._now(cur)
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        if forward:
            self.policy.require_current(now)
        return now

    def _map(self, cur, identity, route, major):
        # Stable routes need only one round trip. A missing row is not a lock:
        # concurrent cold creation still resolves through INSERT + locked reread
        # before any scope lock is acquired.
        cur.execute(f'''SELECT bucket_key,observation_seq FROM {ROUTES}
            WHERE auth_key=%s AND route_key=%s AND major_key=%s FOR UPDATE''', (identity.auth_key, route, major))
        row = cur.fetchone()
        if row:
            return row
        cur.execute(f'''INSERT INTO {ROUTES}(auth_key,route_key,major_key)
            VALUES(%s,%s,%s) ON CONFLICT DO NOTHING''', (identity.auth_key, route, major))
        cur.execute(f'''SELECT bucket_key,observation_seq FROM {ROUTES}
            WHERE auth_key=%s AND route_key=%s AND major_key=%s FOR UPDATE''', (identity.auth_key, route, major))
        row = cur.fetchone()
        if not row:
            raise RateCoordinatorUnavailable()
        return row

    def _keys(self, identity, route, major, bucket):
        p = self.policy
        result = {
            '00:' + self.application_key: ('policy', p.app_capacity, p.app_window_seconds),
            '10:' + identity.auth_key: ('global', None, None),
            '11:' + identity.credential_key: ('credential', None, None),
            '20:' + _digest(p.egress_scope): ('invalid', p.invalid_capacity, p.invalid_window_seconds),
            '40:' + major: ('resource', None, None),
            '50:' + _digest(identity.auth_key + ':' + (bucket or route) + ':' + major): ('route', 1, p.unknown_window_seconds)}
        if bucket is None:
            # Cold aliases share one probe within the auth + major resource.
            # Discord separates top-level guild/channel resources; app/global,
            # credential and invalid-request gates above still span all majors.
            # Key-generation changes require a quiesced, reconciled rollout.
            result['30:' + _digest(identity.auth_key + ':' + major)] = ('discovery', 1, p.unknown_window_seconds)
        return result

    def _locked(self, cur, keys, *, shared_keys=()):
        ordered = sorted(keys)
        if not ordered:
            raise RateCoordinatorUnavailable()
        parameters = []
        for key in ordered:
            kind, cap, window = keys[key]
            parameters.extend((key,kind,cap,cap,window,self.policy.revision,self.policy.expires_at))
        # Skip only committed existing seed keys; concurrent invisible inserts still
        # meet ON CONFLICT in the same ordered subset. Every requested scope is
        # locked, reread and cardinality-checked below before policy/debit use.
        # Bound values and fresh post-lock clocks are unchanged.
        values = ','.join(['(%s::text,%s::text,%s::integer,%s::integer,%s::double precision,%s::text,to_timestamp(%s::double precision))'] * len(ordered))
        cur.execute(f'''WITH scope_seed(scope_key,kind,limit_count,remaining,window_seconds,policy_revision,policy_expires_at)
            AS MATERIALIZED (VALUES {values})
            INSERT INTO {STATE}(scope_key,kind,limit_count,remaining,window_seconds,reset_at,policy_revision,policy_expires_at)
            SELECT source.scope_key,source.kind,source.limit_count,source.remaining,source.window_seconds,
                clock_timestamp(),source.policy_revision,source.policy_expires_at
            FROM scope_seed AS source
            WHERE NOT EXISTS(SELECT 1 FROM {STATE} AS existing WHERE existing.scope_key=source.scope_key)
            ORDER BY source.scope_key COLLATE "C" ON CONFLICT(scope_key) DO NOTHING''',tuple(parameters))
        columns = '''scope_key,kind,limit_count,remaining,window_seconds,extract(epoch from reset_at)::double precision,
                extract(epoch from blocked_until)::double precision,extract(epoch from circuit_until)::double precision,error_streak,manual_hold,
                observation_seq,policy_revision,extract(epoch from policy_expires_at)::double precision,
                learned,extract(epoch from fresh_after)::double precision'''
        shared = sorted(shared_keys)
        if shared:
            if (not set(shared) < set(ordered) or '00:'+self.application_key not in shared
                    or any(key[:3] not in ('00:','10:','11:','20:','40:') for key in shared)):
                raise RateCoordinatorUnavailable()
            mutable = sorted(set(ordered)-set(shared))
            # Materialization + COUNT consumes every common SHARE lock before
            # the mutable route locks. All forward/exclusive paths need app00
            # UPDATE, so they cannot enter admission scans during this phase.
            cur.execute(f'''WITH scope_lock AS MATERIALIZED (
                WITH guarded AS MATERIALIZED (
                    SELECT {columns} FROM {STATE} WHERE scope_key=ANY(%s::text[])
                    ORDER BY scope_key COLLATE "C" FOR SHARE),
                mutable AS MATERIALIZED (
                    SELECT {columns} FROM {STATE} AS target
                    CROSS JOIN (SELECT count(*) AS guarded_count FROM guarded) AS fence
                    WHERE target.scope_key=ANY(%s::text[]) AND fence.guarded_count=%s::integer
                    ORDER BY target.scope_key COLLATE "C" FOR UPDATE OF target)
                SELECT * FROM guarded UNION ALL SELECT * FROM mutable)
                SELECT * FROM scope_lock ORDER BY scope_key COLLATE "C"''',(shared,mutable,len(shared)))
        else:
            cur.execute(f'''WITH scope_lock AS MATERIALIZED (
                SELECT {columns} FROM {STATE} WHERE scope_key=ANY(%s::text[])
                ORDER BY scope_key COLLATE "C" FOR UPDATE)
                SELECT * FROM scope_lock ORDER BY scope_key COLLATE "C"''',(ordered,))
        values = cur.fetchall()
        if (len(values) != len(ordered) or any(len(value) != 15 for value in values)
                or [value[0] for value in values] != ordered):
            raise RateCoordinatorUnavailable()
        fields = ('kind','cap','left','window','reset','blocked','circuit','streak','hold','seq','policy','policyExpires','learned','freshAfter')
        rows = {value[0]:dict(zip(fields,value[1:])) for value in values}
        expected = {'00:':'policy','10:':'global','11:':'credential','20:':'invalid','40:':'resource'}
        if any(rows[key]['kind'] != expected[key[:3]] for key in shared):
            raise RateCoordinatorUnavailable()
        return rows

    def _store_batch(self, cur, rows, *, locked_keys, forward=True, previous=None):
        ordered = sorted(locked_keys)
        # Both callers pass the unchanged key set used by _locked in this same
        # transaction. A missing/extra state must not turn into an unlocked write.
        if not ordered or sorted(rows) != ordered:
            raise RateCoordinatorUnavailable()
        if previous is not None:
            if sorted(previous) != ordered:
                raise RateCoordinatorUnavailable()
            # Reservation still locks and validates every scope. Avoid rewriting
            # unchanged guards (and their updated_at index) while holding app00.
            # Compare all stored fields, including policy renewal; never infer
            # immutability merely from a scope's kind or nullable capacity.
            fields = ('cap','left','window','reset','blocked','circuit','streak',
                      'hold','seq','policy','policyExpires','learned','freshAfter')
            changed = []
            for key in ordered:
                effective = dict(rows[key])
                if forward:
                    effective['policy'] = self.policy.revision
                    effective['policyExpires'] = max(effective['policyExpires'],self.policy.expires_at)
                if any(effective[field] != previous[key][field] for field in fields):
                    changed.append(key)
            ordered = changed
            if not ordered:
                return
        parameters = []
        for key in ordered:
            row = rows[key]
            parameters.extend((row['cap'],row['left'],row['window'],row['reset'],row['blocked'],row['circuit'],row['streak'],row['hold'],
                row['seq'],self.policy.revision if forward else row['policy'],
                max(row['policyExpires'],self.policy.expires_at) if forward else row['policyExpires'],
                row['learned'],row['freshAfter'],key))
        values = ','.join(['(%s::integer,%s::integer,%s::double precision,to_timestamp(%s::double precision),to_timestamp(%s::double precision),'
            'to_timestamp(%s::double precision),%s::integer,%s::boolean,%s::bigint,%s::text,to_timestamp(%s::double precision),'
            '%s::boolean,to_timestamp(%s::double precision),%s::text)'] * len(ordered))
        cur.execute(f'''WITH scope_store(limit_count,remaining,window_seconds,reset_at,blocked_until,circuit_until,error_streak,
            manual_hold,observation_seq,policy_revision,policy_expires_at,learned,fresh_after,scope_key) AS MATERIALIZED (VALUES {values})
            UPDATE {STATE} AS target SET limit_count=source.limit_count,remaining=source.remaining,window_seconds=source.window_seconds,
            reset_at=source.reset_at,blocked_until=source.blocked_until,circuit_until=source.circuit_until,error_streak=source.error_streak,
            manual_hold=source.manual_hold,observation_seq=source.observation_seq,policy_revision=source.policy_revision,
            policy_expires_at=source.policy_expires_at,learned=source.learned,fresh_after=source.fresh_after,
            revision=target.revision+1,updated_at=clock_timestamp() FROM scope_store AS source
            WHERE target.scope_key=source.scope_key RETURNING target.scope_key''',tuple(parameters))
        changed = cur.fetchall()
        if (cur.rowcount != len(ordered) or len(changed) != len(ordered) or any(len(value) != 1 for value in changed)
                or sorted(value[0] for value in changed) != ordered):
            raise RateCoordinatorUnavailable()

    def _pending(self, cur, key, now):
        # Lock before filtering expiry: consume may have passed its final clock
        # check while holding an admission and commit sent after that expiry.
        # READ COMMITTED re-reads that row after the lock wait; the outer count
        # must see the committed state. Consume/seal never acquire scope locks.
        cur.execute(f'''WITH locked_pending AS MATERIALIZED (
            SELECT state,expires_at FROM {ADMISSIONS} WHERE scope_keys @> ARRAY[%s]::text[]
            AND state IN ('reserved','sealed','sent','uncertain') ORDER BY request_seq FOR UPDATE)
            SELECT count(*) FROM locked_pending WHERE
            (state IN ('sent','uncertain') OR state IN ('reserved','sealed') AND expires_at>to_timestamp(%s))''', (key,now))
        return cur.fetchone()[0]

    def _alias_pending(self, cur, alias, permit, meta, now):
        # One row per durable admission: OR does not duplicate a request already
        # present on both keys. Other routes on the OLD bucket are not migrated;
        # only this exact auth/route/major joins the new alias. The caller holds
        # mapping -> all scope locks -> observing admission, in that order.
        # Include expired reserved/sealed rows in the locking step. Filtering
        # them first could miss an in-flight consume, then map its sent row
        # without charging it. Counts and alias mapping share these row locks.
        cur.execute(f'''WITH locked_alias AS MATERIALIZED (
            SELECT scope_keys,state,expires_at FROM {ADMISSIONS} WHERE id<>%s::uuid
            AND (scope_keys @> ARRAY[%s]::text[] OR (auth_key=%s AND route_key=%s AND major_key=%s))
            AND state IN ('reserved','sealed','sent','uncertain') ORDER BY request_seq FOR UPDATE)
            SELECT count(*),count(*) FILTER (WHERE NOT scope_keys @> ARRAY[%s]::text[])
            FROM locked_alias WHERE
            (state IN ('sent','uncertain') OR state IN ('reserved','sealed') AND expires_at>to_timestamp(%s))''',
            (permit.id,alias,permit.identity.auth_key,*meta,alias,now))
        values = cur.fetchone()
        if (not values or len(values) != 2 or any(type(v) is not int or v < 0 for v in values)
                or values[1] > values[0]):
            raise RateCoordinatorUnavailable()
        return values

    def _roll(self, cur, key, row, now, *, forward=True):
        if forward and row['policy'] != self.policy.revision and row['kind'] in ('policy','invalid','discovery'):
            # A new reviewed policy can tighten immediately, not refill mid-window.
            cap, window = {'policy':(self.policy.app_capacity,self.policy.app_window_seconds),
                           'invalid':(self.policy.invalid_capacity,self.policy.invalid_window_seconds),
                           'discovery':(1,self.policy.unknown_window_seconds)}[row['kind']]
            used = max(0,row['cap']-row['left'])
            active_prior = row['policyExpires'] > now
            row['cap'] = min(row['cap'],cap) if active_prior else cap
            row['window'] = max(row['window'],window) if active_prior else window
            row['left'] = min(row['left'],max(0,row['cap']-used))
        if row['cap'] is not None and row['reset'] <= now:
            if row['kind'] == 'route' and row['learned'] and row['freshAfter'] is not None:
                # No second refill from a stale countdown. A response to a
                # request from this new window must establish its real reset.
                raise RateCoordinatorUnavailable()
            pending = self._pending(cur,key,now) if row['kind'] != 'invalid' else 0
            row['left'] = max(0,row['cap']-pending)
            if row['kind'] == 'route' and row['learned']:
                row['freshAfter'],row['reset'] = now,self.policy.expires_at
            else:
                row['reset'] = now + row['window']

    def _insert(self, cur, permit, route, major, bucket, keys, binding, *, read_sent=False):
        if read_sent and (permit.method != 'GET' or binding is not None or permit.binding_hash is not None):
            raise RateCoordinatorUnavailable()
        read_columns = ',state,sent_at' if read_sent else ''
        read_values = ",'sent',at" if read_sent else ''
        # Store and compare the SAME database-clock value. Lock/storage latency
        # can exhaust an immutable expiry after reserve() calculated it. A
        # rejected insert raises inside the transaction and rolls back debits.
        insert=f'''INSERT INTO {ADMISSIONS}(id,application_key,auth_key,credential_key,credential_kind,
            method,path_key,route_key,major_key,bucket_key,scope_keys,is_publish,binding_hash,workspace_id,
            publication_id,manifest_digest,authorization_digest,approval_digest,worker_key,lease_key,channel_key,expires_at,reserved_at{read_columns})
            SELECT %s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),at{read_values}
            FROM reservation_clock WHERE to_timestamp(%s)>at'''
        parameters=(permit.id,self.application_key,permit.identity.auth_key,permit.identity.credential_key,permit.identity.kind,
             permit.method,permit.path_key,route,major,bucket,sorted(keys),binding is not None,permit.binding_hash,
             *(binding.get(k) if binding else None for k in ('workspaceId','publicationId','manifestDigest','authorizationDigest',
                  'approvalDigest','workerKey','leaseKey','channelKey')),permit.expires_at,permit.expires_at)
        cur.execute('WITH reservation_clock AS MATERIALIZED (SELECT clock_timestamp() AS at) '+insert,parameters)
        if cur.rowcount != 1:
            raise RateDelayed(.05,cause='permit_expired',scope='permit')

    def reserve_read(self, method, path, *, identity):
        """Authorize one GET atomically with its debit, committed before I/O.

        `sent` is the authorization linearization point, as in consume(). A lost
        response retains the spent admission. Publishing never uses this path.
        """
        if method != 'GET':
            raise RateCoordinatorUnavailable()
        return self._reserve(method, path, identity=identity, read_sent=True)

    def reserve(self, method, path, *, identity, binding=None, valid_until=None):
        return self._reserve(method, path, identity=identity, binding=binding, valid_until=valid_until)

    def _reserve(self, method, path, *, identity, binding=None, valid_until=None, read_sent=False):
        template, major = route_identity(method,path)
        route = _digest(template)
        if not isinstance(identity, RequestIdentity):
            raise RateCoordinatorUnavailable()
        if binding is not None:
            bot_route = (re.fullmatch(r'/channels/[0-9]{5,25}/messages', path)
                         and binding.get('channelKey') == _digest(path.split('/')[2])
                         and 'webhookKey' not in binding)
            webhook_route = (template == 'POST:/webhooks/{id}/{token}' and identity.kind == 'webhook'
                             and binding.get('webhookKey') == _digest(path.split('/')[2])
                             and _HASH.fullmatch(str(binding.get('channelKey', ''))))
            if method != 'POST' or binding.get('applicationKey') != self.application_key or not (bot_route or webhook_route):
                raise RateCoordinatorUnavailable()
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        with self._transaction() as cur:
            bucket, _seq = self._map(cur,identity,route,major)
            keys = self._keys(identity,route,major,bucket)
            rows = self._locked(cur,keys)
            previous = {key:dict(row) for key,row in rows.items()}
            now = self._policy(cur)  # wall time after lock waits
            wait, wait_scope = 0.0, 'unknown'
            for key,row in rows.items():
                self._roll(cur,key,row,now)
                if row['hold']:
                    raise RateCoordinatorUnavailable()
                embargo = max((row['blocked'] or 0)-now,(row['circuit'] or 0)-now)
                if embargo > wait:
                    wait,wait_scope = embargo,'embargo'
                if row['cap'] is not None and row['left'] <= 0:
                    if row['reset']-now > wait:
                        kind = {'policy':'application','discovery':'discovery'}.get(row['kind'],'unknown')
                        if row['kind'] == 'route':
                            kind = 'learned_route' if row['learned'] else 'unknown_route'
                        wait,wait_scope = row['reset']-now,kind
            if wait > 0:
                raise RateDelayed(wait,scope=wait_scope)
            expiry = round(min(now+self.policy.permit_ttl_seconds,self.policy.expires_at,
                         *(r['reset'] for r in rows.values() if r['cap'] is not None),
                         valid_until if valid_number(valid_until) else MAX_EPOCH),6)
            # A fixed headroom margin rejects usable short provider windows
            # and can repeatedly restart OAuth. INSERT and consume independently
            # compare this frozen deadline with the live DB clock; never extend
            # the deadline merely to make a short reservation succeed.
            if expiry <= now:
                raise RateDelayed(.05,cause='window_expiring',scope='permit')
            for key,row in rows.items():
                if row['cap'] is not None and row['kind'] != 'invalid':
                    row['left'] -= 1
            self._store_batch(cur,rows,locked_keys=keys,previous=previous)
            permit = Permit(str(uuid.uuid4()),self.application_key,method,_digest(path),identity,binding_hash(binding),expiry)
            self._insert(cur,permit,route,major,bucket,keys,binding,read_sent=read_sent)
        return permit

    def _admission(self, cur, permit):
        cur.execute(f'''SELECT request_seq,application_key,auth_key,credential_key,credential_kind,method,path_key,
            route_key,major_key,bucket_key,scope_keys,binding_hash,state,intent_id,extract(epoch from expires_at)::double precision,
            extract(epoch from reserved_at)::double precision
            FROM {ADMISSIONS} WHERE id=%s::uuid FOR UPDATE''', (permit.id,))
        value = cur.fetchone()
        if not value:
            raise RateCoordinatorUnavailable()
        row = dict(zip(('seq','application','auth','credential','kind','method','path','route','major','bucket','keys',
                        'binding','state','intent','expires','reserved'),value))
        if (row['application'] != self.application_key or permit.application_key != self.application_key
                or row['auth'] != permit.identity.auth_key or row['credential'] != permit.identity.credential_key
                or row['kind'] != permit.identity.kind or row['method'] != permit.method or row['path'] != permit.path_key
                or row['binding'] != permit.binding_hash or abs(row['expires']-permit.expires_at) > .000002):
            raise RateCoordinatorUnavailable()
        return row

    def seal(self, cur, permit, binding, intent_id, valid_until):
        """Called only in the existing workspace transaction; no scope locks."""
        if not isinstance(permit,Permit) or binding_hash(binding) != permit.binding_hash or not permit.binding_hash:
            raise RateCoordinatorUnavailable()
        row = self._admission(cur,permit)
        now = self._policy(cur)
        if row['state'] != 'reserved':
            raise RateCoordinatorUnavailable()
        if min(row['expires'],valid_until) <= now:
            raise RateDelayed(max(.05,(row['expires'] or now)-now),cause='permit_expired')
        cur.execute(f"UPDATE {ADMISSIONS} SET state='sealed',intent_id=%s,sealed_at=clock_timestamp() WHERE id=%s::uuid AND state='reserved'", (intent_id,permit.id))
        if cur.rowcount != 1:
            raise RateCoordinatorUnavailable()

    def consume(self, permit, method, path, *, binding=None, intent_id=None, authorize=None):
        if (not isinstance(permit,Permit) or method != permit.method or _digest(path) != permit.path_key
                or binding_hash(binding) != permit.binding_hash):
            raise RateCoordinatorUnavailable()
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        with self._transaction() as cur:
            if permit.binding_hash:
                self._policy(cur)
            # Live guard obtains workspace -> credential BEFORE admission. It
            # returns the current approval/lease deadline, never a cached boolean.
            deadline = authorize(cur) if permit.binding_hash and callable(authorize) else None
            if permit.binding_hash and not valid_number(deadline):
                raise RateCoordinatorUnavailable()
            row = self._admission(cur,permit)
            now = self._policy(cur)
            expected_state = 'sealed' if permit.binding_hash else 'reserved'
            if row['state'] != expected_state or permit.binding_hash and row['intent'] != intent_id:
                raise RateCoordinatorUnavailable()
            if min(row['expires'],deadline if deadline is not None else MAX_EPOCH) <= now:
                raise RateDelayed(.05,cause='permit_expired')
            cur.execute(f"UPDATE {ADMISSIONS} SET state='sent',sent_at=clock_timestamp() WHERE id=%s::uuid AND state=%s", (permit.id,expected_state))
            if cur.rowcount != 1:
                raise RateCoordinatorUnavailable()
        # Transaction is committed BEFORE provider I/O. A crash now retains the
        # intent and spent admission. It can never manufacture a fresh POST.

    def abandon_expired_publish(self, cur, permit, binding, intent_id):
        """Fence a proven unconsumed intent in its owner's workspace transaction.

        Never releases sent/observed/uncertain admissions or refunds quota.
        The old frozen deadline and intent remain durable evidence.
        """
        if (not isinstance(permit, Permit) or not permit.binding_hash
                or binding_hash(binding) != permit.binding_hash):
            raise RateCoordinatorUnavailable()
        row = self._admission(cur, permit)
        now = self._now(cur)
        if row['state'] != 'sealed' or row['intent'] != intent_id or row['expires'] > now:
            raise RateCoordinatorUnavailable()
        cur.execute(f'''UPDATE {ADMISSIONS} SET state='blocked',outcome_at=clock_timestamp()
            WHERE id=%s::uuid AND state='sealed' AND intent_id=%s
                AND sent_at IS NULL AND outcome_at IS NULL AND expires_at<=clock_timestamp()''',
            (permit.id, intent_id))
        if cur.rowcount != 1:
            raise RateCoordinatorUnavailable()

    def observe(self, permit, response, *, transport_failure=False):
        classification = classify_response(response,permit.identity.kind)
        headers = _headers(response)
        raw_bucket = headers.get('x-ratelimit-bucket')
        new_bucket = _digest(raw_bucket) if isinstance(raw_bucket,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',raw_bucket) else None
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        share = self._share_get_observation(permit,classification,new_bucket,transport_failure)
        try:
            return self._observe_once(permit,response,classification,headers,raw_bucket,new_bucket,transport_failure,share)
        except _ExclusiveObservationRequired:
            # The exception crossed _transaction, so all locks/writes rolled
            # back. Retry this existing outcome once; no provider I/O repeats.
            return self._observe_once(permit,response,classification,headers,raw_bucket,new_bucket,transport_failure,False)

    @staticmethod
    def _share_get_observation(permit, classification, new_bucket, transport_failure):
        return (permit.method == 'GET' and permit.binding_hash is None and classification['status'] == 200
                and not transport_failure and not classification['invalid'] and not classification['global']
                and classification['scope'] != 'shared' and new_bucket is not None)

    def _observe_once(self, permit, response, classification, headers, raw_bucket, new_bucket, transport_failure, share):
        with self._transaction() as cur:
            # Mapping -> scope -> admission is consistent with reservation.
            # A permit is immutable; read its route metadata without taking a lock.
            cur.execute(f'SELECT route_key,major_key FROM {ADMISSIONS} WHERE id=%s::uuid', (permit.id,))
            meta = cur.fetchone()
            if not meta:
                raise RateCoordinatorUnavailable()
            bucket, seen = self._map(cur,permit.identity,*meta)
            keys = self._keys(permit.identity,*meta,bucket)
            if new_bucket:
                keys.update(self._keys(permit.identity,*meta,new_bucket))
            # Include old scopes (including an unknown probe) for tightening.
            cur.execute(f'SELECT scope_keys FROM {ADMISSIONS} WHERE id=%s::uuid', (permit.id,))
            original = cur.fetchone()[0]
            for key in original:
                if key not in keys:
                    keys[key] = ('route',1,self.policy.unknown_window_seconds)
            shared_keys = ()
            header_key = '50:'+_digest(permit.identity.auth_key+':'+new_bucket+':'+meta[1]) if new_bucket else None
            # Cold/discovery and historical alias-transition observations retain
            # the original exclusive path and its complete admission lock order.
            if (share and bucket == new_bucket and bucket is not None
                    and not any(key.startswith('30:') for key in keys)
                    and {key for key in keys if key.startswith('50:')} == {header_key}):
                shared_keys = tuple(key for key in keys if key[:3] in ('00:','10:','11:','20:','40:'))
            rows = self._locked(cur,keys,shared_keys=shared_keys) if shared_keys else self._locked(cur,keys)
            previous = {key:dict(row) for key,row in rows.items()}
            immutable_guards = {key:dict(rows[key]) for key in shared_keys}
            if shared_keys:
                guard_now = self._policy(cur,forward=False)
                if (any(row['hold'] or max(row['blocked'] or 0,row['circuit'] or 0)>guard_now for row in rows.values())
                        or any(row['kind'] == 'discovery' for row in rows.values())
                        or any(row['kind'] != 'route' or not row['learned'] for key,row in rows.items() if key not in shared_keys)):
                    raise _ExclusiveObservationRequired()
            admission = self._admission(cur,permit)
            if admission['state'] != 'sent':
                raise RateCoordinatorUnavailable()  # duplicate observation cannot reset a circuit
            now = self._policy(cur,forward=False)
            seq = admission['seq']
            limit,left,after,absolute = (seconds(headers.get(name)) for name in
                ('x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset-after','x-ratelimit-reset'))
            valid_hint = (limit is not None and 1 <= limit <= 100000 and limit.is_integer()
                          and left is not None and left.is_integer() and left <= limit
                          and (after is not None and after > 0 and now+after <= MAX_EPOCH
                               or absolute is not None and now < absolute <= MAX_EPOCH))
            if shared_keys and not valid_hint:
                # No alias/admission scan or outcome write has happened yet.
                # Release every SHARE lock by rollback; never upgrade in place.
                raise _ExclusiveObservationRequired()
            reset_hint = max(now+after if after is not None and after > 0 and now+after <= MAX_EPOCH else now,
                             absolute if absolute is not None and now < absolute <= MAX_EPOCH else now)
            retry, bad_retry = retry_hint(response,now) if classification['status'] == 429 else (0,False)
            old_route = next((k for k in admission['keys'] if k.startswith('50:')),None)
            header_route = ('50:' + _digest(permit.identity.auth_key + ':' + new_bucket + ':' + meta[1])
                            if new_bucket else old_route)
            if old_route is None or header_route not in rows or rows[header_route]['kind'] != 'route':
                raise RateCoordinatorUnavailable()
            was_learned = {key:row['learned'] for key,row in rows.items() if row['kind']=='route'}
            fresh_header = False
            pending,unmapped = self._alias_pending(cur,header_route,permit,meta,now) if header_route else (0,0)
            current_unmapped = int(header_route not in admission['keys'])
            if header_route:
                # Even a failed response cannot escape its newly discovered
                # alias debit. First valid learning below replaces probe credit.
                rows[header_route]['left'] = max(0,rows[header_route]['left']-unmapped-current_unmapped)
            for key,row in rows.items():
                # Known provider budgets never refill from an observation.
                # First valid learning can replace an unlearned probe counter.
                if row['kind'] == 'invalid' and classification['invalid']:
                    self._roll(cur,key,row,now,forward=False)
                    row['left'] = max(0,row['left']-1)
                    if row['left'] == 0:
                        row['blocked'] = max(row['blocked'] or 0,row['reset'])
                if row['kind'] == 'credential' and classification['status'] == 401:
                    # Pacing-policy renewal must never revive a rejected grant.
                    # Reconnect/approved credential replacement produces a new
                    # fingerprint; the rejected fingerprint remains blocked.
                    row['hold'] = True
                if row['kind'] == 'discovery' and not transport_failure:
                    # This is a cold-probe semaphore, not a provider quota.
                    # A completed response lets the next unknown route discover
                    # its headers. Route/app slots remain spent in this window.
                    row['left'] = max(0,1-max(0,self._pending(cur,key,now)-1))
                if row['kind'] == 'route':
                    if raw_bucket is not None and new_bucket is None:
                        row['hold'] = True
                    if valid_hint:
                        fresh = row['freshAfter'] is None or admission['reserved'] >= row['freshAfter']
                        accepted = key == header_route and seq >= seen and seq >= row['seq'] and fresh
                        if accepted:
                            row['cap'],row['window'] = int(limit),max(.05,reset_hint-now)
                            row['learned'] = True
                            # A sentinel policy deadline is replaced only by a
                            # fresh observed reset. Existing embargoes never shrink.
                            row['reset'] = reset_hint if row['freshAfter'] is not None else max(row['reset'],reset_hint)
                            row['freshAfter'] = None
                            first = not was_learned[key] and 200 <= classification['status'] < 400 and not transport_failure
                            row['left'] = observation_remaining(row['left'],int(left),first=first,pending=pending)
                            fresh_header = True
                        else:
                            row['left'] = min(row['left'],int(left))
                    elif any(name in headers for name in ('x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset-after','x-ratelimit-reset')):
                        row['hold'] = True  # malformed numeric hints need operator review
                    if classification['status'] in (403,404):
                        row['circuit'] = max(row['circuit'] or 0,self.policy.expires_at)
                    if transport_failure or classification['status'] >= 500:
                        row['streak'] += 1
                        if row['streak'] >= self.policy.failure_threshold:
                            row['circuit'] = max(row['circuit'] or 0,now+self.policy.circuit_seconds)
                    elif 200 <= classification['status'] < 400 and seq >= row['seq']:
                        row['streak'] = 0  # never clears an already open circuit
                embargo = (classification['status'] == 429 and
                           (row['kind'] == 'global' and classification['global']
                            or row['kind'] == 'resource' and classification['scope'] == 'shared'
                            or row['kind'] == 'route' and not classification['global']))
                if embargo:
                    row['blocked'] = max(row['blocked'] or 0,now+retry)
                    row['hold'] = row['hold'] or bad_retry
                    if row['left'] is not None:
                        row['left'] = 0
                # Response ordering is a route/bucket fence. Common guards use
                # locked quota/embargo state, never this response sequence.
                # Advancing their unused sequence rewrites otherwise unchanged
                # application-wide guards while every peer waits on app00.
                if key not in shared_keys and row['kind'] == 'route':
                    row['seq'] = max(row['seq'],seq)
            # Apply this response once per scope, then merge final alias state.
            # Doing inheritance before increments made streaks depend on key
            # sort order and could count the same failure twice.
            if old_route:
                old = rows[old_route]
                for key,row in rows.items():
                    if row['kind'] != 'route' or key == old_route:
                        continue
                    if was_learned[old_route]:
                        row['left'] = min(row['left'],old['left'])
                    row['blocked'] = max(row['blocked'] or 0,old['blocked'] or 0) or None
                    row['hold'] = row['hold'] or old['hold']
                    row['circuit'] = max(row['circuit'] or 0,old['circuit'] or 0) or None
                    row['streak'] = max(row['streak'],old['streak'])
                    if old['freshAfter'] is not None:
                        if not (key == header_route and fresh_header and admission['reserved'] >= old['freshAfter']):
                            row['freshAfter'] = max(row['freshAfter'] or 0,old['freshAfter'])
                            row['reset'] = max(row['reset'],old['reset'])
                            row['learned'] = True  # retain the inherited no-second-refill barrier
                        # A fresh response satisfies this barrier and replaces
                        # its policy-expiry sentinel; do not inherit that reset.
                    elif row['freshAfter'] is None:
                        row['reset'] = max(row['reset'],old['reset'])
                    row['seq'] = max(row['seq'],old['seq'])
            if any(rows[key] != original for key,original in immutable_guards.items()):
                raise RateCoordinatorUnavailable()  # future mutation under SHARE fails closed
            mutable_rows = {key:row for key,row in rows.items() if key not in shared_keys}
            self._store_batch(cur,mutable_rows,locked_keys=set(keys)-set(shared_keys),forward=False,
                              previous={key:previous[key] for key in mutable_rows})
            if new_bucket and seq >= seen:
                cur.execute(f'''UPDATE {ROUTES} SET bucket_key=%s,observation_seq=%s,updated_at=clock_timestamp()
                    WHERE auth_key=%s AND route_key=%s AND major_key=%s''', (new_bucket,seq,permit.identity.auth_key,*meta))
                alias_key = '50:' + _digest(permit.identity.auth_key + ':' + new_bucket + ':' + meta[1])
                cur.execute(f'''UPDATE {ADMISSIONS} SET bucket_key=%s,scope_keys=array_append(scope_keys,%s)
                    WHERE auth_key=%s AND route_key=%s AND major_key=%s AND state IN ('reserved','sealed','sent','uncertain')
                    AND NOT scope_keys @> ARRAY[%s]::text[]''', (new_bucket,alias_key,permit.identity.auth_key,*meta,alias_key))
            cur.execute(f'''UPDATE {ADMISSIONS} SET state=%s,status_code=%s,rate_scope=%s,outcome_at=clock_timestamp()
                WHERE id=%s::uuid AND state='sent' ''',
                ('uncertain' if transport_failure else 'observed',classification['status'],classification['scope'],permit.id))
            if cur.rowcount != 1:
                raise RateCoordinatorUnavailable()
            if shared_keys and any(row['hold'] or max(row['blocked'] or 0,row['circuit'] or 0)>now for row in rows.values()):
                raise _ExclusiveObservationRequired()
            for key,row in rows.items():
                if row['hold'] or max(row['blocked'] or 0,row['circuit'] or 0) > now:
                    # Stop unused permits admitted before a later embargo. A
                    # consumed request precedes this linearization point; its
                    # provider effect remains evidence, never an automatic retry.
                    cur.execute(f'''UPDATE {ADMISSIONS} SET state='blocked',outcome_at=clock_timestamp()
                        WHERE state IN ('reserved','sealed') AND scope_keys @> ARRAY[%s]::text[]''', (key,))
        return {**classification,'retryAfterSeconds':retry,'retryHintMalformed':bad_retry}

    def abandon_unsent_read(self, permit):
        """Retire a GET whose final local consent check denied before transport.

        No quota refund, policy extension, provider observation or replacement
        permit. The spent slot lasts through its normal window; this known
        unsent request cannot remain an unresolved response forever.
        """
        if not isinstance(permit, Permit) or permit.method != 'GET' or permit.binding_hash is not None:
            raise RateCoordinatorUnavailable()
        with self._transaction() as cur:
            row = self._admission(cur, permit)
            if row['state'] != 'sent' or row['intent'] is not None:
                raise RateCoordinatorUnavailable()
            cur.execute(f"UPDATE {ADMISSIONS} SET state='blocked',outcome_at=clock_timestamp() WHERE id=%s::uuid AND state='sent' AND NOT is_publish AND method='GET'", (permit.id,))
            if cur.rowcount != 1:
                raise RateCoordinatorUnavailable()

    def note_transport_failure(self, permit):
        return self.observe(permit,{'status':503,'headers':{}},transport_failure=True)

    def report(self):
        """Internal bounded aggregates, not customer data or a capacity claim."""
        try:
            with self._transaction() as cur:
                cur.execute(f'''WITH sample AS MATERIALIZED(SELECT state,status_code,rate_scope FROM {ADMISSIONS}
                    WHERE application_key=%s ORDER BY request_seq DESC LIMIT 2048)
                    SELECT state,rate_scope,count(*),count(*) FILTER(WHERE status_code=429)
                    FROM sample GROUP BY state,rate_scope''', (self.application_key,))
                rows = cur.fetchall()
                counts = [{'state':row[0],'scope':row[1],'requests':row[2],'responses429':row[3]} for row in rows]
                cur.execute(f'''WITH recent AS MATERIALIZED(SELECT scope_keys FROM {ADMISSIONS}
                    WHERE application_key=%s ORDER BY request_seq DESC LIMIT 2048), scopes AS(
                    SELECT DISTINCT unnest(scope_keys) AS scope_key FROM recent)
                    SELECT r.kind,count(*) FILTER(WHERE r.manual_hold),
                        count(*) FILTER(WHERE r.circuit_until>clock_timestamp()),
                        count(*) FILTER(WHERE r.blocked_until>clock_timestamp()),
                        coalesce(max(greatest(0,extract(epoch from r.blocked_until-clock_timestamp()))),0)::double precision
                    FROM {STATE} r JOIN scopes s USING(scope_key) GROUP BY r.kind''',(self.application_key,))
                return {'status':'sampled','sampleLimit':2048,'counts':counts,'scopes':[
                    {'kind':r[0],'manualHolds':r[1],'openCircuits':r[2],'embargoes':r[3],'maxEmbargoSeconds':r[4]}
                    for r in cur.fetchall()]}
        except RateCoordinatorUnavailable:
            return {'status':'unavailable'}
