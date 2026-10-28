"""Default-off Discord REST admission in the existing PostgreSQL connection.

Operational pacing is a reviewed, expiring policy, not a provider quota claim.
HTTP runs after transactions commit. A publish permit cannot replace approval:
it is sealed with the existing intent and consumed once after a live SQL guard.
Shared tables contain opaque keys/statuses, never tokens, bodies or content.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError

STATE = 'public.pr_discord_rate_state'
ROUTES = 'public.pr_discord_route_buckets'
ADMISSIONS = 'public.pr_discord_request_admissions'
MAX_EPOCH = 253402300799.0  # representable through year9999; excessive hints hold
SLOT_EPSILON = 1e-6  # one tick of the database clock (timestamptz keeps whole microseconds)
MAX_PERMIT_SECONDS = 10.0  # SafetyPolicy.parse refuses a longer permit_ttl_seconds: the longest a permit can wait to be used
# A sent row's expiry is at or after the moment it was marked sent, give or take the time consume's UPDATE waited for
# its lock (statement_timeout is 5 s). Bounding the unresolved scan by expires_at, which the partial index holds, as
# well as by the sent time keeps it to the unresolved rows of the last window plus margin, however many old ones leaked.
SENT_SLACK = 6.0
# What a READ refused by an operator or coordinator hold is told to wait. Nothing was sent and nothing is lost by waiting: the
# read-back of a post that was already created defers by it (and gets its check back) instead of failing five times.
HOLD_WAIT_SECONDS = 300.0
# What the read-back of a post that was already created is told to wait when the coordinator cannot admit any request (none
# attached, degraded, its policy ended, its database down). Nothing was sent and the receipt is kept: the lookup is asked again
# later and its check is refunded (hosted_social.reconcile_discord). Creates are not affected: they stay fail-closed.
COORDINATOR_WAIT_SECONDS = 300.0
# What a reservation is told to wait when the database did not give it its lock or finish its statement in time (RateCoordinatorBusy):
# nothing was admitted and nothing was sent, so the caller asks again soon. It used to be an unavailable coordinator, which a worker
# turns into a release of 300 s for the post, and which the review reproduced as 253 such errors in 12 seconds at 24 loops and 20 ms
# of statement latency.
BUSY_WAIT_SECONDS = 1.5
# The transaction-level advisory lock that serializes the retention purge (purge_settled): one deleter at a time, the others
# return at once. Not a row or table lock; it conflicts with nothing the coordinator does.
PURGE_LOCK = int.from_bytes(hashlib.sha256(b'postriff.discord.admissions.purge').digest()[:8], 'big') >> 1
# The longest a caller may be made to wait for the slot it is booked (SharedPostgresBudget, BOOK_AHEAD_SECONDS below).
BOOK_AHEAD_SECONDS = 1.0
# The credential kind charged to the bearer budget when the reviewed policy carries one (SafetyPolicy.bearer_capacity): a request
# authorized with the person's own OAuth bearer (the lane's grant check GET /oauth2/@me, the profile read after a token exchange or
# refresh, the server list). The bot token, the client secret's token calls and a webhook's secret stay in the application budget.
BEARER_KIND = 'user'
_BOOK_AHEAD = contextvars.ContextVar('postriff_discord_book_ahead', default=(0.0, None))


@contextmanager
def booking(seconds=BOOK_AHEAD_SECONDS, tally=None):
    """Within this block the calling thread may be booked a slot up to `seconds` ahead instead of being refused when the
    window is full (the lane's preflight, create permit and read-back). It is per call, by context variable: a direct
    provider call, another thread, the minute worker and a web request never see it and keep the immediate answer, a slot now
    or a refusal. Never longer than BOOK_AHEAD_SECONDS. `tally`, a dict with 'bookings' and 'bookedWaitSeconds', is added to
    for every booking made inside the block, so a caller can count its own (the coordinator's own totals are per process)."""
    token = _BOOK_AHEAD.set((max(0.0, min(float(seconds), BOOK_AHEAD_SECONDS)), tally))
    try:
        yield
    finally:
        _BOOK_AHEAD.reset(token)


def current_book_ahead():
    """How far ahead the calling context may be booked: 0.0 (the immediate answer) unless inside booking()."""
    return _BOOK_AHEAD.get()[0]


@contextmanager
def web_reads(seconds=BOOK_AHEAD_SECONDS):
    """Within this block a WEB call that makes several reads in a row (a server's channel list, a re-check, the last step of a
    connection: four to six requests to Discord) is booked like the lane: where the window is full each read is given the
    earliest exact slot up to `seconds` ahead instead of the immediate refusal. While the lane saturates the window, the slot kept
    for immediate callers cannot carry five reads in a row, so such a call almost never completed; booked, it waits its turn.
    A call that makes one read stays immediate: this is for the others. A caller that is already booking (the lane) keeps its own
    horizon and tally. AS-BUILT, "Web calls that read several times"."""
    if current_book_ahead() > 0:
        yield
        return
    with booking(seconds):
        yield


def web_booked(call, *args, **kwargs):
    """`call(*args, **kwargs)` inside web_reads()."""
    with web_reads():
        return call(*args, **kwargs)


NICKNAME_TEMPLATE = 'PATCH:/guilds/{id}/members/@me'   # the one Discord write the sender-name feature makes
NICKNAME_ENV = 'POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED'
_ID = re.compile(r'^[0-9]{5,25}$')
_HASH = re.compile(r'^[a-f0-9]{64}$')
_LABEL = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')


class RateCoordinatorUnavailable(AlphaError):
    def __init__(self):
        super().__init__('Discord request coordination is unavailable. Restore the reviewed rate policy or reconnect; no request was sent.',
                         503, code='discord_rate_coordinator_unavailable')


class RateCoordinatorBusy(RateCoordinatorUnavailable):
    """The database did not give a coordinator transaction its lock (lock_timeout) or did not finish its statement
    (statement_timeout) in the time the coordinator allows (_transaction). The transaction was rolled back, so nothing it was to
    record was recorded: a reservation admitted nothing (its caller is told to ask again soon: RateDelayed 'coordinator_busy'), an
    observation can be tried once more. Anything else that fails stays a plain RateCoordinatorUnavailable."""


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
    """Private transport signal: consume denied before provider I/O began.

    cause 'permit_expired': the sealed permit reached its end unconsumed. cause 'permit_blocked': an embargo or hold
    observed after sealing blocked the unconsumed permit (observe()), and consume() refused it; retry_after_seconds is
    then what is left of that embargo."""
    def __init__(self, permit_id, seconds, cause='permit_expired'):
        super().__init__(seconds, cause=cause, scope='permit')
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
        'GET:/guilds/{id}/members/{id}', NICKNAME_TEMPLATE}
    if template not in allowed:
        raise RateCoordinatorUnavailable()
    if template == NICKNAME_TEMPLATE and os.environ.get(NICKNAME_ENV) != 'true':
        # The write exists only while its capability is on, read now (no import-time read, no cache, only the exact
        # string `true`). This gates NEW admissions only: observe, abandon and reconcile act on admissions that already
        # exist, and turning the capability off must not strand them.
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


_BEARER_FIELDS = ('bearer_capacity', 'bearer_window_seconds')


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
    # The person's own bearer calls (kind `user`) on a budget of their own, an exact sliding window like the application's: this
    # many requests per this many seconds (the owner's D-2 option 1; docs/w02/OPEN-QUESTIONS.md, Q21). Both or neither: a policy
    # without the pair has no separate bearer budget (bearer_capacity 0) and those calls stay in the application budget, as before,
    # so a policy issued before this field existed is still valid and a build can be rolled back by issuing one.
    bearer_capacity: int = 0
    bearer_window_seconds: float = 1.0

    @classmethod
    def parse(cls, raw):
        try:
            value = json.loads(raw) if isinstance(raw, str) and len(raw) <= 4096 else raw
            fields = set(cls.__dataclass_fields__)
            required = fields - set(_BEARER_FIELDS)
            if (not isinstance(value, dict) or set(value) not in (required | {'version'}, fields | {'version'})
                    or type(value['version']) is not int or value['version'] != 1):
                raise ValueError()
            numbers = (fields & set(value)) - {'revision', 'egress_scope'}
            if any(not valid_number(value[k]) for k in numbers):
                raise ValueError()
            for k in ('app_capacity', 'invalid_capacity', 'failure_threshold', 'read_attempts', 'bearer_capacity'):
                if k in value and type(value[k]) is not int:
                    raise ValueError()
            if (not _LABEL.fullmatch(value['revision']) or not _LABEL.fullmatch(value['egress_scope'])
                    or not 0 <= value['issued_at'] < value['expires_at'] <= MAX_EPOCH
                    or value['expires_at'] - value['issued_at'] > 86400 * 31
                    or not 1 <= value['app_capacity'] <= 100000 or not 1 <= value['invalid_capacity'] <= 100000
                    or not 1 <= value['failure_threshold'] <= 100 or not 1 <= value['read_attempts'] <= 5
                    or any(not .05 <= value[k] <= 86400 for k in
                           ('app_window_seconds', 'unknown_window_seconds', 'invalid_window_seconds', 'circuit_seconds'))
                    or not .05 <= value['permit_ttl_seconds'] <= 10
                    or 'bearer_capacity' in value and (not 1 <= value['bearer_capacity'] <= 100000
                                                       or not .05 <= value['bearer_window_seconds'] <= 86400)):
                raise ValueError()
            return cls(**{k: value[k] for k in fields if k in value})
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
    Uncertain sends conservatively retain one slot across resets until resolved,
    or until they can no longer reach Discord: their scope's window plus
    UNOBSERVED_MARGIN_SECONDS. The application-wide row is an exact sliding
    window over the admissions themselves (_slide), not a fixed one.

    Two budgets, when the reviewed policy carries the pair (SafetyPolicy.bearer_capacity): the person's own bearer calls (BEARER_KIND)
    are charged to a second row of the same kind (scope key 01:, kind `policy` so that no schema changes), an exact sliding window of
    its own cap and window; every other credential is charged to the application row (00:), whose window then counts those alone.
    The classes share the admissions table and nothing else that is counted: a request of one class cannot take a slot of the other.
    A bearer request also holds the application row, to see its hold and embargo (the runbook's stop covers it) without being charged.
    """
    # The longest an admitted request can still be on its way to Discord after it was marked sent: the transport's
    # 20-second socket timeout (providers.http_transport) plus allowance for DNS, TLS set-up and clock skew. A request
    # whose answer was never observed keeps counting against a scope for that scope's window plus this margin, never
    # longer: after it nothing it did can fall inside any window the scope still holds.
    UNOBSERVED_MARGIN_SECONDS = 30.0
    # Headroom for the delay between a request's wire time (the database clock when it was admitted, or when its permit
    # was used) and the moment it reaches Discord, which differs from request to request (the commit, a thread waking,
    # the connection, a busy machine). Wire times are exact on the database clock; two requests a window apart can still
    # arrive less than a window apart when the earlier one is the slower by more than the slack between them. A slot
    # frees this long after the window (at most a tenth of it). The owner's reading of "25 requests a second" (D-16): the
    # coordinator never admits more than 25 stamped requests in any sliding second (exact, pinned by the randomized
    # brute-force and the 24-thread tests), arrival at Discord is REPORTED (the probe's peak and share of windows) and not a
    # failure, and stays far under Discord's real limit of 50; so the headroom is 0.05 s, not the 0.1 s that also kept
    # arrivals under 25 against a slow tail. The sustained rate is cap x window / (window + guard): 23.8 of 25 a second.
    # Chosen over pacing at the wire (a send time on the permit and a wait in the transport) because it needs no field in the
    # Permit (the sender claim rebuilds it), no sleep in the request path and no change to the transport, and costs nothing
    # while demand is below the cap. Measured with the probe tests/discord_ceiling_probe.py (24 threads, a mock Discord, real
    # PostgreSQL), arrivals in a trailing second at the mock: with no added delay and with 50 and 100 ms of it (wire delay
    # p99.9 up to 127 ms) none above 25, peak 25; with 300 ms 1 to 3 of about 190 (0.5 to 1.6 percent), peak 26, at 0.05 as at
    # 0.1 s. The capacity harness reports the real spread (wire jitter p99.9): the guard is the constant to set from it.
    SLOT_GUARD_SECONDS = 0.05
    # Booking (docs/w02/OPEN-QUESTIONS.md, Q19). A caller inside booking() that finds the window full is not refused and left to
    # ask again: it is given the earliest slot that is exact (_booking_slot), if that is at most the caller's book-ahead away
    # (never more than BOOK_AHEAD_SECONDS), and reserve/reserve_read return when the slot has come, with no lock held. The
    # admission is stored with the slot as its wire time (a read: sent_at; a create's permit: reserved_at), so the ceiling is
    # the same rule, only a wire time may lie ahead of the clock. Polling a full window was a lottery for the next freed slot
    # (12 shards: 17 lock statements and one release a post, 24 shards: 48 and 7); a booking is one statement and a place in
    # line. The wait is in reserve only: never in consume, never between seal and consume. Set to 0 it restores the old behaviour.
    BOOK_AHEAD_SECONDS = BOOK_AHEAD_SECONDS
    # A permit is booked only if it will still live this long after its slot, and not past the lease or approval deadline the
    # caller named: its seal and consume (about 0.16 s) must fit inside its life, and a create with a permit lifetime shorter than
    # this (tests use 0.05 s) is refused as before.
    BOOK_MIN_LIFE_SECONDS = 0.5
    # Slots of every window that bookings leave to callers that cannot wait (a web request keeps the immediate answer): without
    # them a window kept full by bookings would refuse every web request for as long as the load lasts.
    IMMEDIATE_RESERVE = 1
    # A booked read that slept at least this long asks, in one short statement just before it is sent, whether an embargo, a
    # circuit or a hold began meanwhile, and is not sent if so (it stays spent). Shorter waits are the delay every admission
    # already has between its commit and the wire.
    BOOK_GATE_MIN_SECONDS = 0.025
    # How many times a route's circuit after a 403 may double: circuit_seconds x 2**5 = 16 minutes at most.
    DENIAL_BACKOFF_STEPS = 5
    # Retention (purge_settled). An admission the coordinator can no longer count is deleted: it counts for the application
    # window only for one span after its wire time (a second and a tenth), and unresolved it counts for _horizon at most, and
    # only while it is unresolved; a settled row counts for nothing. What is kept past that is the record. A read is kept an
    # hour (the health payload's windows are at most 15 minutes, a sender-name claim ends 15 minutes after its permit), a
    # publication two days (the owner's approved window): nothing reads a created post's row again after its approval's hour
    # (the unique intent and binding indexes only have to outlast a stale worker, whose lease and approval are long over), the
    # read-back that follows is a new row, and two days let a person read the incident of the day before yesterday; each
    # further day costs 0.8 to 1.8 GB at 100 posts a minute (docs/w02/OPEN-QUESTIONS.md, Q16). An unresolved row (sent,
    # uncertain, reserved, sealed) is never deleted: it is the evidence a person reviews.
    PURGE_BATCH = 2000                    # rows one statement deletes at most
    PURGE_ROUNDS = 3                      # rounds one call runs while they come back full
    PURGE_READ_SECONDS = 3600.0           # a settled admission that is not a publication
    PURGE_PUBLICATION_SECONDS = 172800.0  # a settled publication: two days
    PURGE_SETTLE_GRACE_SECONDS = 600.0    # a row settled more recently than this stays, however old its reservation

    def __init__(self, connection_factory, application_id, *, policy=None, sleep=time.sleep, monotonic=time.monotonic, **_compat):
        if not isinstance(application_id, str) or not _ID.fullmatch(application_id):
            raise RateCoordinatorUnavailable()
        self.connection_factory, self.application_id = connection_factory, application_id
        self.application_key = _digest(application_id)
        self._sleep, self._monotonic = sleep, monotonic
        self._booking_lock = threading.Lock()
        # Counts since this process started, read by the lane (booking_stats): bookings made, the seconds they were booked
        # ahead in all, booked reads stopped at the gate, and bookings refused because the horizon was full.
        self._booking = {'bookings': 0, 'bookedWaitSeconds': 0.0, 'gateStops': 0, 'horizonRefusals': 0}
        # The legacy runtime constructor can attach an inert coordinator. OAuth
        # attaches the reviewed policy before use; absence never enables a request.
        self.policy = SafetyPolicy.parse(policy) if policy is not None else None

    def _bearer(self, identity):
        """Whether a request with this identity is charged to the bearer budget: the policy carries one and the credential is the
        person's own bearer. Everything else is charged to the application budget, as every request used to be."""
        return self.policy is not None and self.policy.bearer_capacity > 0 and identity.kind == BEARER_KIND

    @property
    def bearer_key(self):
        """The scope key of the bearer budget's row, None when the policy has none (for the lane's outlook and the health payload)."""
        return '01:' + self.application_key if self.policy is not None and self.policy.bearer_capacity > 0 else None

    def _class(self):
        """The class the application row's window counts: None while there is one budget (every admission), else 'bot' (all but
        the bearer kind), the other being 'bearer'."""
        return 'bot' if self.policy is not None and self.policy.bearer_capacity > 0 else None

    @contextmanager
    def _transaction(self):
        try:
            with self.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT set_config('lock_timeout','2000ms',true),set_config('statement_timeout','5000ms',true)")
                yield cur
        except (RateCoordinatorUnavailable, RateDelayed):
            raise
        except Exception as error:
            if getattr(error, 'sqlstate', None) in ('55P03', '57014'):   # lock_not_available, query_canceled: a rollback
                raise RateCoordinatorBusy() from None
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

    def _scan_limit(self, cap, window):
        """How many of the newest admissions hold every one that can still occupy a slot (_window_state).

        A slot is occupied from an admission's wire time (sent_at, else reserved_at) for one span, and a permit is used
        at most MAX_PERMIT_SECONDS after it was reserved, so an occupied slot belongs to an admission reserved within
        span + MAX_PERMIT_SECONDS. At most `cap` admissions are made in any span (the invariant _slide keeps), so this
        many of the newest cover that time with one span to spare. Fewer than `cap` would refuse nothing wrongly."""
        span = self._span(window)
        return min(100000, max(cap + 1, cap * (math.ceil((span + MAX_PERMIT_SECONDS) / span) + 1)))

    def _window_state(self, cur, cap, window, at=None, klass=None):
        """The database clock (or the instant `at`) and what the application window holds then, in ONE statement.

        It must be a statement of its own, started after the application row's lock was granted: in READ COMMITTED a
        statement keeps the snapshot it began with, so one that waited for the lock cannot see the admission the previous
        holder committed meanwhile (reading it in the lock statement admitted 18 in a second at a cap of 10).

        An admission occupies a slot from the moment it can reach Discord, its `sent_at` (a read is sent when it is
        admitted, a create when its permit is consumed), else from its reservation, for one span. Older ones that may
        still reach Discord keep a slot too (`held`): a permit not yet used or expired, and a request sent but never
        answered, for _horizon at most. Returns (now, {cap, window, held, occupied, unused}); `unused` is the part of
        `occupied` that is permits still to be used (they may be used at any later time: a booking counts them in every window).

        `klass` is None while there is one budget: every admission counts. With a bearer budget (SafetyPolicy.bearer_capacity) the
        admissions are two classes, each counted only in its own window: 'bearer' (the person's own bearer, BEARER_KIND) or 'bot'
        (every other credential). The newest rows are taken first, of both classes, and the class picked from them: a class filter
        inside the scan would read a quiet class's whole history, and the newest rows cover both classes' caps (_scan_limit).
        """
        span, horizon = self._span(window) + SLOT_EPSILON, self._horizon(window)
        clock, lead = ('clock_timestamp()', ()) if at is None else ('to_timestamp(%s::double precision)', (at,))
        held_class = array_class = ''
        scan = self._scan_limit(cap, window)
        if klass is not None:
            p = self.policy
            scan = self._scan_limit(p.app_capacity + p.bearer_capacity, min(p.app_window_seconds, p.bearer_window_seconds))
            held_class, array_class = ((f" AND credential_kind='{BEARER_KIND}'", ' AND newest.bearer') if klass == 'bearer'
                                       else (f" AND credential_kind<>'{BEARER_KIND}'", ' AND NOT newest.bearer'))
        cur.execute(f'''WITH tick AS MATERIALIZED (SELECT {clock} AS at),
            newest AS MATERIALIZED (SELECT coalesce(sent_at,reserved_at) AS wire,
                    state IN ('reserved','sealed') AND expires_at>(SELECT at FROM tick) AS unused,
                    credential_kind='{BEARER_KIND}' AS bearer
                FROM {ADMISSIONS} WHERE application_key=%s ORDER BY request_seq DESC LIMIT %s)
            SELECT extract(epoch from tick.at)::double precision,
                (SELECT count(*) FROM {ADMISSIONS} WHERE application_key=%s{held_class}
                    AND coalesce(sent_at,reserved_at)<=tick.at-make_interval(secs=>%s)
                    AND state IN ('reserved','sealed','sent','uncertain')
                    AND (state IN ('reserved','sealed') AND expires_at>tick.at
                         OR state IN ('sent','uncertain') AND expires_at>tick.at-make_interval(secs=>%s)
                            AND coalesce(sent_at,reserved_at)>tick.at-make_interval(secs=>%s))),
                array(SELECT extract(epoch from newest.wire)::double precision FROM newest
                    WHERE newest.wire>tick.at-make_interval(secs=>%s){array_class}),
                array(SELECT extract(epoch from newest.wire)::double precision FROM newest
                    WHERE newest.unused AND newest.wire>tick.at-make_interval(secs=>%s){array_class})
            FROM tick''', (*lead,self.application_key,scan,
                           self.application_key,span,horizon+SENT_SLACK,horizon,span,span))
        value = cur.fetchone()
        if (not value or len(value) != 4 or not valid_number(value[0]) or type(value[1]) is not int or value[1] < 0
                or not isinstance(value[2], list) or not all(valid_number(s) for s in value[2])
                or not isinstance(value[3], list) or not all(valid_number(s) for s in value[3])):
            raise RateCoordinatorUnavailable()
        return value[0], {'cap': cap, 'window': window, 'held': value[1], 'occupied': sorted(value[2]),
                          'unused': sorted(value[3])}

    def _reading(self, cur, row, klass=None):
        """`now` after the locks, as _policy(cur) reads it, with the window's inputs for the stored cap and window.

        _slide asks again (_window_state at that `now`) only if a reviewed policy has just changed either."""
        now, reading = self._window_state(cur, row['cap'], row['window'], None, klass)
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        self.policy.require_current(now)
        return now, reading

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
        if self._bearer(identity):
            # The person's own bearer: charged to the bearer budget's row (01:), which sorts after the application row and is locked
            # with it, so the runbook's hold on the application row (00:) stops these requests too. The application row is only
            # looked at (hold, embargo), never charged: its window counts the bot's class alone (_reserve).
            result['01:' + self.application_key] = ('policy', p.bearer_capacity, p.bearer_window_seconds)
        if bucket is None:
            # Cold aliases share one probe within the auth + major resource.
            # Discord separates top-level guild/channel resources; app/global,
            # credential and invalid-request gates above still span all majors.
            # Key-generation changes require a quiesced, reconciled rollout.
            result['30:' + _digest(identity.auth_key + ':' + major)] = ('discovery', 1, p.unknown_window_seconds)
        return result

    _COLUMNS = '''scope_key,kind,limit_count,remaining,window_seconds,extract(epoch from reset_at)::double precision,
                extract(epoch from blocked_until)::double precision,extract(epoch from circuit_until)::double precision,error_streak,manual_hold,
                observation_seq,policy_revision,extract(epoch from policy_expires_at)::double precision,
                learned,extract(epoch from fresh_after)::double precision'''
    _FIELDS = ('kind','cap','left','window','reset','blocked','circuit','streak','hold','seq','policy','policyExpires','learned','freshAfter')

    def _locked(self, cur, keys, *, shared_keys=(), fresh=None):
        """Seed, then lock, every scope row; return {key: row}.

        `fresh`, when given, is filled with the keys this very transaction created: such a row has no admission yet,
        so there is nothing to count or lock for it."""
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
            ORDER BY source.scope_key COLLATE "C" ON CONFLICT(scope_key) DO NOTHING RETURNING scope_key''',tuple(parameters))
        if fresh is not None:
            fresh.update(row[0] for row in cur.fetchall())
        columns = self._COLUMNS
        shared = sorted(shared_keys)
        if shared:
            if (not set(shared) < set(ordered) or '00:'+self.application_key not in shared
                    or any(key[:3] not in ('00:','01:','10:','11:','20:','40:') for key in shared)):
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
        rows = {value[0]:dict(zip(self._FIELDS,value[1:])) for value in values}
        expected = {'00:':'policy','01:':'policy','10:':'global','11:':'credential','20:':'invalid','40:':'resource'}
        if any(rows[key]['kind'] != expected[key[:3]] for key in shared):
            raise RateCoordinatorUnavailable()
        return rows

    def _changed(self, rows, ordered, previous, forward):
        """The scopes whose stored state differs from `previous`, in lock order: the only ones worth writing.

        Reservation still locks and validates every scope. Avoid rewriting unchanged guards (and their updated_at
        index) while holding app00. Compare all stored fields, including policy renewal; never infer immutability
        merely from a scope's kind or nullable capacity."""
        if sorted(previous) != ordered:
            raise RateCoordinatorUnavailable()
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
        return changed

    def _store_batch(self, cur, rows, *, locked_keys, forward=True, previous=None):
        ordered = sorted(locked_keys)
        # Both callers pass the unchanged key set used by _locked in this same
        # transaction. A missing/extra state must not turn into an unlocked write.
        if not ordered or sorted(rows) != ordered:
            raise RateCoordinatorUnavailable()
        if previous is not None:
            ordered = self._changed(rows, ordered, previous, forward)
            if not ordered:
                return
        cte, update, parameters = self._store_parts(rows, ordered, forward)
        cur.execute(f'WITH {cte} {update}',parameters)
        changed = cur.fetchall()
        if (cur.rowcount != len(ordered) or len(changed) != len(ordered) or any(len(value) != 1 for value in changed)
                or sorted(value[0] for value in changed) != ordered):
            raise RateCoordinatorUnavailable()

    def _store_parts(self, rows, ordered, forward):
        """The statement that writes the state of the scopes `ordered`, as (CTE, UPDATE ... RETURNING scope_key, params)."""
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
        cte = f'''scope_store(limit_count,remaining,window_seconds,reset_at,blocked_until,circuit_until,error_streak,
            manual_hold,observation_seq,policy_revision,policy_expires_at,learned,fresh_after,scope_key) AS MATERIALIZED (VALUES {values})'''
        update = f'''UPDATE {STATE} AS target SET limit_count=source.limit_count,remaining=source.remaining,window_seconds=source.window_seconds,
            reset_at=source.reset_at,blocked_until=source.blocked_until,circuit_until=source.circuit_until,error_streak=source.error_streak,
            manual_hold=source.manual_hold,observation_seq=source.observation_seq,policy_revision=source.policy_revision,
            policy_expires_at=source.policy_expires_at,learned=source.learned,fresh_after=source.fresh_after,
            revision=target.revision+1,updated_at=clock_timestamp() FROM scope_store AS source
            WHERE target.scope_key=source.scope_key RETURNING target.scope_key'''
        return cte, update, tuple(parameters)

    def _span(self, window):
        """How long an admission occupies a slot of the application window: the window and its headroom."""
        return window + min(self.SLOT_GUARD_SECONDS, window / 10)

    def _horizon(self, window):
        """How long an admission whose answer was never observed keeps counting against a scope with this window."""
        return window + self.UNOBSERVED_MARGIN_SECONDS

    def _pending(self, cur, key, now, since=None):
        # Lock before filtering expiry: consume may have passed its final clock
        # check while holding an admission and commit sent after that expiry.
        # READ COMMITTED re-reads that row after the lock wait; the outer count
        # must see the committed state. Consume/seal never acquire scope locks.
        # `since` (epoch seconds) drops sent/uncertain rows marked sent at or before it from the locked set and the
        # count: such a request cannot still reach Discord inside any window this scope holds (_horizon), and is
        # no longer in flight in any transaction. Reserved/sealed rows are bounded by their own expiry.
        recent = '' if since is None else (" AND (state NOT IN ('sent','uncertain')"
                                           " OR coalesce(sent_at,reserved_at)>to_timestamp(%s))")
        cur.execute(f'''WITH locked_pending AS MATERIALIZED (
            SELECT state,expires_at FROM {ADMISSIONS} WHERE scope_keys @> ARRAY[%s]::text[]
            AND state IN ('reserved','sealed','sent','uncertain'){recent} ORDER BY request_seq FOR UPDATE)
            SELECT count(*) FROM locked_pending WHERE
            (state IN ('sent','uncertain') OR state IN ('reserved','sealed') AND expires_at>to_timestamp(%s))''',
            (key,now) if since is None else (key,since,now))
        return cur.fetchone()[0]

    def _alias_pending(self, cur, alias, permit, meta, now, since=None):
        # One row per durable admission: OR does not duplicate a request already
        # present on both keys. Other routes on the OLD bucket are not migrated;
        # only this exact auth/route/major joins the new alias. The caller holds
        # mapping -> all scope locks -> observing admission, in that order.
        # Include expired reserved/sealed rows in the locking step. Filtering
        # them first could miss an in-flight consume, then map its sent row
        # without charging it. Counts and alias mapping share these row locks.
        # `since` bounds unobserved sent/uncertain rows exactly as in _pending.
        recent = '' if since is None else (" AND (state NOT IN ('sent','uncertain')"
                                           " OR coalesce(sent_at,reserved_at)>to_timestamp(%s))")
        cur.execute(f'''WITH locked_alias AS MATERIALIZED (
            SELECT scope_keys,state,expires_at FROM {ADMISSIONS} WHERE id<>%s::uuid
            AND (scope_keys @> ARRAY[%s]::text[] OR (auth_key=%s AND route_key=%s AND major_key=%s))
            AND state IN ('reserved','sealed','sent','uncertain'){recent} ORDER BY request_seq FOR UPDATE)
            SELECT count(*),count(*) FILTER (WHERE NOT scope_keys @> ARRAY[%s]::text[])
            FROM locked_alias WHERE
            (state IN ('sent','uncertain') OR state IN ('reserved','sealed') AND expires_at>to_timestamp(%s))''',
            (permit.id,alias,permit.identity.auth_key,*meta,*(() if since is None else (since,)),alias,now))
        values = cur.fetchone()
        if (not values or len(values) != 2 or any(type(v) is not int or v < 0 for v in values)
                or values[1] > values[0]):
            raise RateCoordinatorUnavailable()
        return values

    def _roll(self, cur, key, row, now, *, forward=True, fresh=False):
        if forward and row['policy'] != self.policy.revision and row['kind'] in ('policy','invalid','discovery'):
            # A new reviewed policy can tighten immediately, not refill mid-window.
            cap, window = {'policy':(self.policy.app_capacity,self.policy.app_window_seconds),
                           'invalid':(self.policy.invalid_capacity,self.policy.invalid_window_seconds),
                           'discovery':(1,self.policy.unknown_window_seconds)}[row['kind']]
            if key[:3] == '01:':  # the bearer budget's row is a policy row of its own cap and window
                cap, window = self.policy.bearer_capacity, self.policy.bearer_window_seconds
            used = max(0,row['cap']-row['left'])
            active_prior = row['policyExpires'] > now
            row['cap'] = min(row['cap'],cap) if active_prior else cap
            row['window'] = max(row['window'],window) if active_prior else window
            row['left'] = min(row['left'],max(0,row['cap']-used))
        # A refilled learned window waits for an answer to a request of that NEW window to establish its real reset
        # (freshAfter). If no such answer can arrive any more (every request of the window was lost, or answered
        # without headers) that wait must not last for ever: once the longest an answer can take has passed (the
        # window plus the margin) the countdown is stale and the window is refilled once more, as a cold one is probed.
        learned = row['kind'] == 'route' and row['learned']
        waiting = learned and row['freshAfter'] is not None
        lapsed = waiting and row['freshAfter'] + self._horizon(row['window']) <= now
        if waiting and not lapsed and row['left'] <= 0 and not fresh and self._window_unused(cur, key, row['freshAfter'], now):
            # Nothing is left to send AND nothing of this window can ever answer: every permit reserved on the route since
            # the refill expired unused (a slow step, a released job) and no request was sent. The wait for an answer would
            # last for ever, so the route is probed again at once, as a cold one is. (It used to stay closed until the
            # policy expired, up to 31 days.) A request that WAS sent keeps the wait until its answer or the lapse above.
            lapsed = True
        if row['cap'] is not None and (row['reset'] <= now or lapsed) and row['kind'] != 'policy':
            # The application row never refills: _slide derives its left/reset from the admissions at each reservation.
            if waiting and not lapsed:
                # No second refill from a stale countdown. A response to a
                # request from this new window must establish its real reset.
                raise RateCoordinatorUnavailable()
            # An unobserved request carries into this window only while it can still reach Discord (_horizon).
            # A row this transaction has just created has no admission yet: nothing to count, nothing to lock.
            pending = (self._pending(cur,key,now,since=now-self._horizon(row['window']))
                       if row['kind'] != 'invalid' and not fresh else 0)
            row['left'] = max(0,row['cap']-pending)
            if learned and row['left'] > 0:
                row['freshAfter'],row['reset'] = now,self.policy.expires_at
            else:
                # No slot to admit means no request to answer: wait one window and count again, never the sentinel
                # (a caller told to wait until the policy expires would hold its post for good).
                row['reset'] = now + row['window']
        elif waiting and row['left'] <= 0:
            # Still waiting for the answer that establishes the window, with nothing left to send: quote a poll or
            # the lapse of the wait, whichever is sooner, not the sentinel. (Denied below, so this is never stored.)
            row['reset'] = min(now + row['window'], row['freshAfter'] + self._horizon(row['window']))

    def _window_unused(self, cur, key, fresh_after, now):
        """True when no permit on the scope is still usable and no request on it was sent since `fresh_after`."""
        cur.execute(f'''SELECT count(*) FROM {ADMISSIONS} WHERE scope_keys @> ARRAY[%s]::text[]
            AND (state IN ('reserved','sealed') AND expires_at>to_timestamp(%s) OR sent_at>=to_timestamp(%s))''',
            (key,now,fresh_after))
        count = cur.fetchone()[0]
        if type(count) is not int or count < 0:
            raise RateCoordinatorUnavailable()
        return count == 0

    @staticmethod
    def _fits(wires, at, span, slots):
        """Whether one more admission with wire time `at` is exact: no window of one span that contains `at` would then hold
        more than `slots`. `wires` ascend and may include booked ones later than `at`. A window (e - span, e] contains `at` for
        every end e from `at` up to, not including, at + span; its count only rises at a wire time, so the ends to look at are
        `at` itself and each later wire time inside that reach. With no wire later than `at` this is len(wires) < slots."""
        if slots <= 0:
            return False
        for end in [at] + [w for w in wires if at < w < at + span]:
            if bisect_right(wires, end) - bisect_right(wires, end - span) + 1 > slots:
                return False
        return True

    def _earliest_fit(self, wires, at, span, slots):
        """The first instant at or after `at` at which _fits holds: the wait quoted to a caller that cannot be booked."""
        for t in sorted({at} | {w + span for w in wires if w + span > at}):
            if self._fits(wires, t, span, slots):
                return t
        return wires[-1] + span if wires else at

    @staticmethod
    def _booking_slot(wires, unused, at, span, slots):
        """The earliest instant at or after `at`, and not before any wire already stored, at which an admission is exact in
        every window that holds it; None when no booking can be exact. A permit still to be used may be used at any later time,
        so for a booking it counts in every window: it is taken out of the wires and out of the slots. That is what keeps the
        count exact when a permit is used after a booking that lies more than a span ahead of the permit's reservation."""
        rest = list(wires)
        for w in unused:
            rest.remove(w)
        free = slots - len(unused)
        if free <= 0:
            return None
        slot = max(at, wires[-1]) if wires else at
        if len(rest) >= free:
            slot = max(slot, rest[len(rest) - free] + span)
        return slot

    def _published(self, row, wires, unused, now, window, span, slots):
        """The values the application row keeps for those who read it (lane.outlook, the health payload), the same whatever the
        writer's own mode, as of this write (a refusal writes nothing). They answer one question for the capacity bookings may
        fill (`slots`: the cap less the held and less IMMEDIATE_RESERVE): can a booking of the whole BOOK_AHEAD_SECONDS be made?

        `left` is the room the booked horizon still has, the bookings that could still be made at its end: `slots` less the
        permits still to be used (each counts in every window, as in _booking_slot) less the other wires that still hold their
        slot when the horizon ends. It is 0 exactly when _booking_slot would refuse a booking of the whole horizon, and then
        `reset` is the instant from which one would not be (the wire whose leaving makes room, less the horizon); otherwise
        `reset` is now, nothing to wait for. It used to count only the wires up to now, which a saturated lane always fills:
        remaining was 0 in 21 of 35 busy readings of the first hosted run while a booking was possible at once. With no
        booking (BOOK_AHEAD_SECONDS 0) the horizon ends now: `left` is the free slots and `reset` the next wire to leave, or
        now + window, as the row has always held. `wires` are the wires after this admission; `unused` the permits among them."""
        horizon = self.BOOK_AHEAD_SECONDS
        rest = list(wires)
        for w in unused:
            rest.remove(w)
        free = slots - len(unused)
        busy = 0  # the wires still in their slot when the horizon ends, in the arithmetic of the booking decision (_slide)
        for w in reversed(rest):
            if w + span - now <= horizon:
                break
            busy += 1
        row['left'] = max(0, free - busy)
        row['reset'] = now if horizon > 0 else now + window
        if row['left'] == 0:
            row['reset'] = (rest[len(rest) - free] + span - horizon) if 0 < free <= len(rest) else now + window

    def _slide(self, cur, row, now, reading, book=0.0, create=False, klass=None):
        """Set the application row's `left` and `reset` from the admissions themselves (an exact sliding window).

        What is counted. Every admission occupies one slot from its wire time `w` (sent_at when it has one, else
        reserved_at) until w + span, whatever became of it (answered, released, blocked, expired): none is refunded
        inside its span, as the fixed window never refunded one inside its own. A permit that has not been used yet
        occupies a slot from its reservation and, once older than a span, until it is used (then from sent_at) or expires;
        an admission sent and never answered occupies one for at most _horizon. Such older admissions are `held` (see
        _window_state). A slot is free only STRICTLY more than one span after the wire time that held it.

        Exactness. This reservation holds its policy row FOR UPDATE from before `now` is read until it commits and admits
        only where one more wire time keeps every window of one span at `cap` or fewer (_fits; with every wire at or before
        `now`, as before bookings existed, that is occupied slots + held < cap). Using a permit (consume) moves it from "held"
        to "occupying from sent_at" without changing the count, and no other event adds to it. So at every instant at most
        `cap` wire times lie in any half-open span, hence at most `cap` in any CLOSED interval of one window: no trailing
        second of wire times holds more than `cap`. The requests themselves arrive at the wire some time after their wire
        time; that spread is what the span's headroom (SLOT_GUARD_SECONDS) absorbs: arrivals stay within `cap` per window
        whenever the spread is at most the headroom. A database clock behind a wire time already stamped is waited out,
        not trusted: that wire time is simply still inside its span.

        Booking (`book` > 0, a caller inside booking()). Where the window is full the caller is given the earliest exact
        instant after every wire already stored (_booking_slot), when that is at most `book` ahead: the wire time may lie in
        the future, nothing else about the rule changes. Bookings fill only cap - IMMEDIATE_RESERVE of every window, so a caller
        that cannot wait (a web request) always finds a slot. Beyond `book` the caller is refused, with the wait until a
        booking is possible.

        left, reset: see _published. Returns (the booked wire time, or None for an immediate admission). A refusal leaves
        `left` 0 and `reset` at the instant the refused caller may ask again.

        `row` is the policy row the request is charged to: the application's, or the bearer budget's (`klass` says which window the
        reading counts: _window_state). Everything above holds for either, with its own cap and window.
        """
        cap, window = row['cap'], row['window']
        span = self._span(window) + SLOT_EPSILON
        if (reading['cap'], reading['window']) != (cap, window):
            # a reviewed policy changed the cap or window just now: the reading answered for the old ones
            _now, reading = self._window_state(cur, cap, window, now, klass)
        slots = cap - reading['held']
        wires, unused = reading['occupied'], reading['unused']  # ascending wire times that are still inside their span
        row['left'], row['reset'] = 0, now + window  # resolution alone can free a slot: poll once per window
        if slots <= 0:
            return None
        if wires and wires[-1] > now + self.BOOK_AHEAD_SECONDS + .05:
            # A wire time further ahead than any booking reaches: the database clock stepped back since it was stamped. It is
            # waited out, not trusted: that wire is simply still inside its span and every wire counts, as before bookings.
            if len(wires) >= slots:
                row['reset'] = wires[len(wires) - slots] + span
                return None
            row['left'] = slots - len(wires)
            row['reset'] = wires[0] + span if row['left'] == 1 else now + window
            return None
        # what bookings may fill: callers that cannot wait (book 0) may use the reserve as well
        slots_b = slots - (min(self.IMMEDIATE_RESERVE, slots - 1) if self.BOOK_AHEAD_SECONDS > 0 else 0)
        mine = slots if book <= 0 else slots_b
        if self._fits(wires, now, span, mine):
            self._published(row, sorted(wires + [now]), unused + [now] if create else unused, now, window, span, slots_b)
            row['left'] += 1  # published as it will stand once this admission is debited (_reserve debits every capped row)
            return None
        if book <= 0:
            row['reset'] = self._earliest_fit(wires, now, span, slots)  # the oldest one that must go before a slot is free
            return None
        slot = self._booking_slot(wires, unused, now, span, slots_b)
        if slot is None:  # permits still to be used fill every slot
            return None
        if slot - now > book:
            row['reset'] = slot - book  # a booking is possible from here
            return None
        self._published(row, sorted(wires + [slot]), unused + [slot] if create else unused, now, window, span, slots_b)
        row['left'] += 1  # the booking is the admission; the debit takes it back
        return slot

    def _insert_parts(self, permit, route, major, bucket, keys, binding, read_sent, slot=None):
        """The admission's INSERT ... SELECT, to be run after a `reservation_clock` CTE: (statement, params).

        `slot` is a booked wire time (epoch seconds): a read is stored sent at it, a create's permit reserved at it. Unbooked,
        the parameter is 0 and the wire time is the reservation clock, as it always was."""
        if read_sent and (permit.method != 'GET' or binding is not None or permit.binding_hash is not None):
            raise RateCoordinatorUnavailable()
        wire = 'greatest(at,to_timestamp(%s::double precision))'
        read_columns = ',state,sent_at' if read_sent else ''
        read_values = f",'sent',{wire}" if read_sent else ''
        reserved_value = 'at' if read_sent else wire
        # Store and compare the SAME database-clock value. Lock/storage latency
        # can exhaust an immutable expiry after reserve() calculated it. A
        # rejected insert raises inside the transaction and rolls back debits.
        insert=f'''INSERT INTO {ADMISSIONS}(id,application_key,auth_key,credential_key,credential_kind,
            method,path_key,route_key,major_key,bucket_key,scope_keys,is_publish,binding_hash,workspace_id,
            publication_id,manifest_digest,authorization_digest,approval_digest,worker_key,lease_key,channel_key,expires_at,reserved_at{read_columns})
            SELECT %s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),{reserved_value}{read_values}
            FROM reservation_clock WHERE to_timestamp(%s)>at'''
        parameters=(permit.id,self.application_key,permit.identity.auth_key,permit.identity.credential_key,permit.identity.kind,
             permit.method,permit.path_key,route,major,bucket,sorted(keys),binding is not None,permit.binding_hash,
             *(binding.get(k) if binding else None for k in ('workspaceId','publicationId','manifestDigest','authorizationDigest',
                  'approvalDigest','workerKey','leaseKey','channelKey')),permit.expires_at,0.0 if slot is None else slot,permit.expires_at)
        return insert, parameters

    def _insert(self, cur, permit, route, major, bucket, keys, binding, *, read_sent=False, slot=None):
        insert, parameters = self._insert_parts(permit, route, major, bucket, keys, binding, read_sent, slot)
        cur.execute('WITH reservation_clock AS MATERIALIZED (SELECT clock_timestamp() AS at) '+insert,parameters)
        if cur.rowcount != 1:
            raise RateDelayed(.05,cause='permit_expired',scope='permit')

    def _store_and_insert(self, cur, rows, keys, previous, permit, route, major, bucket, binding, read_sent, slot=None):
        """Write the changed scope states and the admission in ONE statement: one round trip under the application lock.

        Both are data-modifying parts of the same statement, so they succeed or fail together exactly as the two
        statements did inside the transaction. The admission is not inserted if its permit already expired (the clock is
        read here, after the lock waits): the caller rolls everything back. The statement answers with the keys it
        wrote, checked against the keys that had to be written."""
        ordered = sorted(keys)
        if not ordered or sorted(rows) != ordered:
            raise RateCoordinatorUnavailable()
        changed = self._changed(rows, ordered, previous, True)
        if not changed:
            return self._insert(cur, permit, route, major, bucket, keys, binding, read_sent=read_sent, slot=slot)
        cte, update, stored = self._store_parts(rows, changed, True)
        insert, admitted = self._insert_parts(permit, route, major, bucket, keys, binding, read_sent, slot)
        cur.execute(f'''WITH {cte}, written AS ({update}),
            reservation_clock AS MATERIALIZED (SELECT clock_timestamp() AS at)
            {insert} RETURNING (SELECT array_agg(scope_key ORDER BY scope_key COLLATE "C") FROM written)''',(*stored,*admitted))
        if cur.rowcount != 1:
            raise RateDelayed(.05,cause='permit_expired',scope='permit')
        written = cur.fetchone()
        if not written or len(written) != 1 or written[0] != changed:
            raise RateCoordinatorUnavailable()

    def reserve_read(self, method, path, *, identity, book_ahead=0.0):
        """Authorize one GET atomically with its debit, committed before I/O.

        `sent` is the authorization linearization point, as in consume(). A lost
        response retains the spent admission. Publishing never uses this path.
        `book_ahead` (seconds, only inside booking()): a full window books the read a slot up to that far ahead and this call
        returns when the slot has come; 0 refuses at once, as it always did.
        """
        if method != 'GET':
            raise RateCoordinatorUnavailable()
        return self._reserve(method, path, identity=identity, read_sent=True, book_ahead=book_ahead)

    def reserve(self, method, path, *, identity, binding=None, valid_until=None, book_ahead=0.0):
        return self._reserve(method, path, identity=identity, binding=binding, valid_until=valid_until, book_ahead=book_ahead)

    def _book_ahead(self, requested):
        """What a call may be booked ahead: what its caller asked, never more than BOOK_AHEAD_SECONDS, and nothing below
        5 ms (a wait that short is the delay between commit and wire every admission already has)."""
        book = min(float(requested or 0.0), float(self.BOOK_AHEAD_SECONDS))
        return book if book >= .005 else 0.0

    def booking_stats(self):
        """Counts since this process started: bookings made, the seconds they were booked ahead in all, booked reads stopped at
        the gate (an embargo, circuit or hold began while they waited) and calls refused because the booked horizon was full."""
        with self._booking_lock:
            return dict(self._booking)

    def _count_booking(self, **increments):
        with self._booking_lock:
            for name, amount in increments.items():
                self._booking[name] += amount
        tally = _BOOK_AHEAD.get()[1]
        if tally is not None and 'bookings' in increments:  # the caller's own count (booking(tally=...)): this thread's context
            tally['bookings'] += increments['bookings']
            tally['bookedWaitSeconds'] += increments['bookedWaitSeconds']

    def _reserve(self, method, path, *, identity, binding=None, valid_until=None, read_sent=False, book_ahead=0.0):
        """Admit one request (or reserve one permit), and for a booking wait for its slot. A database that gives the reservation
        no lock in time or does not finish its statement (RateCoordinatorBusy) rolled the transaction back: nothing was admitted
        and nothing sent, so the caller is told to ask again soon, as for any other spent budget, and not that the coordinator is
        unavailable (which a worker turns into a 300-second release of the post)."""
        try:
            return self._reserve_once(method, path, identity=identity, binding=binding, valid_until=valid_until,
                                      read_sent=read_sent, book_ahead=book_ahead)
        except RateCoordinatorBusy:
            raise RateDelayed(BUSY_WAIT_SECONDS, cause='coordinator_busy', scope='application') from None

    def _reserve_once(self, method, path, *, identity, binding=None, valid_until=None, read_sent=False, book_ahead=0.0):
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
        book = self._book_ahead(book_ahead)
        with self._transaction() as cur:
            bucket, _seq = self._map(cur,identity,route,major)
            keys = self._keys(identity,route,major,bucket)
            # The application row is held from this statement to the commit: one statement reads the clock (wall time
            # after lock waits) and the application window, one writes the result, then the commit.
            # With a bearer budget a request is charged to one of two policy rows: the bearer's own for the person's bearer, the
            # application's for every other credential. A bearer request holds the application row as well but only looks at it
            # (its hold and embargo, which stop every request): it is neither refused by its count nor debited.
            bearer = self._bearer(identity)
            charged = ('01:' if bearer else '00:') + self.application_key
            looked_at = '00:' + self.application_key if bearer else None
            klass = 'bearer' if bearer else self._class()
            fresh = set()
            rows = self._locked(cur,keys,fresh=fresh)
            previous = {key:dict(row) for key,row in rows.items()}
            now, reading = self._reading(cur,rows[charged],klass)
            read_at = self._monotonic()  # when `now` was read: a booked wait is counted from here, on this process's clock
            wait, wait_scope = 0.0, 'unknown'
            slot = None
            for key,row in rows.items():
                self._roll(cur,key,row,now,fresh=key in fresh)
                if row['hold']:
                    if read_sent:
                        # A read has no effect to be unsure of, so a hold is a wait for it; a create is refused outright.
                        raise RateDelayed(HOLD_WAIT_SECONDS,cause='hold',scope='embargo')
                    raise RateCoordinatorUnavailable()
                if key == charged:
                    # sets left/reset; denied below like any capped row unless this is a booking
                    slot = self._slide(cur,row,now,reading,book,create=not read_sent,klass=klass)
                embargo = max((row['blocked'] or 0)-now,(row['circuit'] or 0)-now)
                if embargo > wait:
                    wait,wait_scope = embargo,'embargo'
                if row['cap'] is not None and key != looked_at and row['left'] <= 0:
                    if row['reset']-now > wait:
                        kind = {'policy':'application','discovery':'discovery'}.get(row['kind'],'unknown')
                        if row['kind'] == 'route':
                            kind = 'learned_route' if row['learned'] else 'unknown_route'
                        wait,wait_scope = row['reset']-now,kind
            if wait > 0:
                if book and wait_scope == 'application':
                    self._count_booking(horizonRefusals=1)
                raise RateDelayed(wait,scope=wait_scope)
            # A permit lives as long as its caller can use it: the policy's permit lifetime, the caller's own deadline
            # (a create's lease and approval) and the policy's end; no window ends it. A window that ends while the
            # permit is unused refills its row counting this permit as pending (_roll), and the application window
            # keeps a slot for it until it is used or expires (_slide), so using it late is paid for in the later window.
            # It used to end with the earliest reset of its rows (at most the 1-second application window): 11.5% of the
            # create preflights of a 5,000-post run were repeated because the permit died before it could be sealed.
            # A booked permit's life starts at its slot, and a booking never reaches past the caller's own deadline: it is
            # refused (as an immediate admission would be at a full window) unless the permit, whole, still ends before the
            # lease or approval ends and lives long enough after its slot to be sealed and used.
            ttl = self.policy.permit_ttl_seconds
            deadline = min(self.policy.expires_at,valid_until if valid_number(valid_until) else MAX_EPOCH)
            if slot is not None and ((not read_sent and ttl < self.BOOK_MIN_LIFE_SECONDS) or slot+ttl > deadline):
                raise RateDelayed(slot-now,scope='application')
            expiry = round(min((now if slot is None else slot)+ttl,deadline),6)
            # A fixed headroom margin rejects usable short provider windows
            # and can repeatedly restart OAuth. INSERT and consume independently
            # compare this frozen deadline with the live DB clock; never extend
            # the deadline merely to make a short reservation succeed.
            if expiry <= now:
                raise RateDelayed(.05,cause='window_expiring',scope='permit')
            for key,row in rows.items():
                if row['cap'] is not None and row['kind'] != 'invalid' and key != looked_at:
                    row['left'] -= 1
            permit = Permit(str(uuid.uuid4()),self.application_key,method,_digest(path),identity,binding_hash(binding),expiry)
            self._store_and_insert(cur,rows,keys,previous,permit,route,major,bucket,binding,read_sent,slot)
        if slot is not None:
            self._wait_for_slot(permit,slot-now,read_at,read_sent,
                                deadline-now if valid_number(valid_until) and not read_sent else None)
        return permit

    def _wait_for_slot(self, permit, booked, read_at, read_sent, deadline_in=None):
        """Sleep until the booked slot has come: after the commit, no lock held. `booked` seconds after the database clock was
        read, counted on this process's monotonic clock from the moment that reading arrived, so the time the reservation itself
        took is not slept twice and a send is never early (the reading reached us a moment after it was taken). Then, for a read
        that slept, the gate: one last look at whether anything stopped its route meanwhile. `deadline_in`, for a create, is how
        many seconds after the reading the caller's own deadline (its lease or approval) falls: the sleep stops there, whatever
        was booked, and the permit is left to expire unused (a booking is only made while the slot and the permit's life fit
        before it, so this is the process that stalled, or a clock that moved)."""
        self._count_booking(bookings=1,bookedWaitSeconds=booked)
        slept = 0.0
        for _ in range(int(booked/.1)+20):  # slices of 0.1 s; the bound only guards a sleep that never advances a clock
            elapsed = self._monotonic()-read_at
            if deadline_in is not None and elapsed >= deadline_in:
                raise RateDelayed(.05,cause='permit_expired',scope='permit')
            remaining = booked-elapsed
            if remaining <= 0:
                break
            pause = min(remaining,.1)
            if deadline_in is not None:
                pause = min(pause,max(deadline_in-elapsed,.001))
            self._sleep(pause)
            slept += pause
        if read_sent and slept >= self.BOOK_GATE_MIN_SECONDS:
            self._start_gate(permit)

    def _start_gate(self, permit):
        """The last look before a booked read is sent: did an embargo, a circuit or a hold begin on any scope it was admitted
        under while it waited? One statement in its own short transaction, no scope lock and no application lock. If so the read
        is closed as blocked (its slot stays spent, nothing is refunded) and not sent, and the caller is told how long to wait:
        a hold as in _reserve, an embargo for what is left of it. What can still go out after an embargo begins is bounded by
        the time between this look and the wire, the delay every admission has."""
        with self._transaction() as cur:
            cur.execute(f'''UPDATE {ADMISSIONS} a SET state='blocked',outcome_at=clock_timestamp()
                WHERE a.id=%s::uuid AND a.state='sent' AND NOT a.is_publish AND a.method='GET' AND EXISTS (
                    SELECT 1 FROM {STATE} r WHERE r.scope_key=ANY(a.scope_keys)
                        AND (r.manual_hold OR r.blocked_until>clock_timestamp() OR r.circuit_until>clock_timestamp()))
                RETURNING (SELECT bool_or(r.manual_hold) FROM {STATE} r WHERE r.scope_key=ANY(a.scope_keys)),
                    extract(epoch from (SELECT max(greatest(r.blocked_until,r.circuit_until)) FROM {STATE} r
                        WHERE r.scope_key=ANY(a.scope_keys)))::double precision,
                    extract(epoch from clock_timestamp())::double precision''',(permit.id,))
            stopped = cur.fetchone()
        if stopped:
            held, until, now = stopped
            self._count_booking(gateStops=1)
            if held:
                raise RateDelayed(HOLD_WAIT_SECONDS,cause='hold',scope='embargo')
            raise RateDelayed(max(.05,until-now) if valid_number(until) and valid_number(now) else .05,cause='embargo',scope='embargo')

    def _admission(self, cur, permit, *, clock=False):
        """Lock the permit's admission row and check it is this permit's; with clock=True also return the database
        clock read in the SAME statement, after the row lock was granted: (row, now). Observation holds scope locks
        while it does this, so every statement saved here shortens the time other requests wait for them."""
        columns = '''request_seq,application_key,auth_key,credential_key,credential_kind,method,path_key,
            route_key,major_key,bucket_key,scope_keys,binding_hash,state,intent_id,extract(epoch from expires_at)::double precision,
            extract(epoch from reserved_at)::double precision'''
        if clock:
            cur.execute(f'''WITH adm AS MATERIALIZED (SELECT {columns} FROM {ADMISSIONS} WHERE id=%s::uuid FOR UPDATE),
                tick AS MATERIALIZED (SELECT clock_timestamp() AS at FROM adm)
                SELECT adm.*,extract(epoch from tick.at)::double precision FROM adm CROSS JOIN tick''', (permit.id,))
        else:
            cur.execute(f'SELECT {columns} FROM {ADMISSIONS} WHERE id=%s::uuid FOR UPDATE', (permit.id,))
        value = cur.fetchone()
        if not value:
            raise RateCoordinatorUnavailable()
        now = None
        if clock:
            value, now = value[:-1], value[-1]
            if not valid_number(now):
                raise RateCoordinatorUnavailable()
        row = dict(zip(('seq','application','auth','credential','kind','method','path','route','major','bucket','keys',
                        'binding','state','intent','expires','reserved'),value))
        if (row['application'] != self.application_key or permit.application_key != self.application_key
                or row['auth'] != permit.identity.auth_key or row['credential'] != permit.identity.credential_key
                or row['kind'] != permit.identity.kind or row['method'] != permit.method or row['path'] != permit.path_key
                or row['binding'] != permit.binding_hash or abs(row['expires']-permit.expires_at) > .000002):
            raise RateCoordinatorUnavailable()
        return (row, now) if clock else row

    def seal(self, cur, permit, binding, intent_id, valid_until):
        """Called only in the existing workspace transaction; no scope locks."""
        if not isinstance(permit,Permit) or binding_hash(binding) != permit.binding_hash or not permit.binding_hash:
            raise RateCoordinatorUnavailable()
        row = self._admission(cur,permit)
        now = self._policy(cur)
        if row['state'] == 'blocked' and row['intent'] is None:
            # observe() blocked this reserved permit (an embargo or hold seen before sealing). No intent exists and
            # the permit was never consumed, so nothing was or can be sent with it: a rate wait for the embargo's
            # remaining time, like a permit that expired before sealing.
            wait = self._blocked_unsent_wait(cur,permit,now)
            if wait is not None:
                raise RateDelayed(wait,cause='permit_blocked',scope='embargo')
        if row['state'] != 'reserved':
            raise RateCoordinatorUnavailable()
        if min(row['expires'],valid_until) <= now:
            raise RateDelayed(max(.05,(row['expires'] or now)-now),cause='permit_expired')
        cur.execute(f"UPDATE {ADMISSIONS} SET state='sealed',intent_id=%s,sealed_at=clock_timestamp() WHERE id=%s::uuid AND state='reserved'", (intent_id,permit.id))
        if cur.rowcount != 1:
            raise RateCoordinatorUnavailable()

    def _stopped(self, cur, scope_keys):
        """(held, until, now) when a manual hold, an embargo or an open circuit is on any of these scopes now, else None. One
        statement, no lock: it only reads the state rows, so it can take no part in a deadlock and delays no reservation."""
        cur.execute(f'''SELECT coalesce(bool_or(r.manual_hold),false),
                extract(epoch from max(greatest(r.blocked_until,r.circuit_until)))::double precision,
                extract(epoch from clock_timestamp())::double precision
            FROM {STATE} r WHERE r.scope_key=ANY(%s::text[])
                AND (r.manual_hold OR r.blocked_until>clock_timestamp() OR r.circuit_until>clock_timestamp())''', (scope_keys,))
        held, until, now = cur.fetchone()
        if not valid_number(now) or (until is not None and not valid_number(until)) or held not in (True, False):
            raise RateCoordinatorUnavailable()
        return (held, until, now) if held or until is not None else None

    def consume(self, permit, method, path, *, binding=None, intent_id=None, authorize=None):
        if (not isinstance(permit,Permit) or method != permit.method or _digest(path) != permit.path_key
                or binding_hash(binding) != permit.binding_hash):
            raise RateCoordinatorUnavailable()
        if self.policy is None:
            raise RateCoordinatorUnavailable()
        stopped = None
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
            if permit.binding_hash and row['state'] == 'blocked' and row['intent'] == intent_id:
                # observe() blocked this sealed, never-consumed permit (an embargo or hold seen after sealing). Refused
                # here, before any transport: the fenced caller may prove its intent unsent (confirm_blocked_publish)
                # and retry once the embargo is over. Only this admission can carry the intent to a POST.
                wait = self._blocked_unsent_wait(cur,permit,now)
                if wait is not None:
                    raise RateDelayed(wait,cause='permit_blocked',scope='embargo')
            if row['state'] != expected_state or permit.binding_hash and row['intent'] != intent_id:
                raise RateCoordinatorUnavailable()
            if min(row['expires'],deadline if deadline is not None else MAX_EPOCH) <= now:
                raise RateDelayed(.05,cause='permit_expired')
            if row['reserved'] > now + SLOT_EPSILON:
                # A booked permit is not to be used before its slot: its slot is where the ceiling counts it. reserve() returns
                # only when the slot has come, so nothing in the shipped flow gets here; this is the defence if something does.
                raise RateDelayed(row['reserved']-now,cause='permit_early',scope='permit')
            # A hold, an embargo or a circuit may have begun on any scope this permit was admitted under since it was reserved
            # (the runbook's hold is an UPDATE of the state row; it touches no admission), and observe() blocks the permits still
            # unused only when it sees one. Looked at here, just before the permit would be marked sent: the admission is closed
            # `blocked` in this transaction, which commits, and the caller is refused after the commit (below), so the refusal
            # is the one observe() gives a sealed permit it blocked and confirm_blocked_publish proves the intent unsent.
            stopped = self._stopped(cur,row['keys'])
            if stopped:
                cur.execute(f"UPDATE {ADMISSIONS} SET outcome_at=clock_timestamp(),state='blocked' WHERE id=%s::uuid AND state=%s AND sent_at IS NULL",
                            (permit.id,expected_state))
            else:
                cur.execute(f"UPDATE {ADMISSIONS} SET state='sent',sent_at=clock_timestamp() WHERE id=%s::uuid AND state=%s", (permit.id,expected_state))
            if cur.rowcount != 1:
                raise RateCoordinatorUnavailable()
        if stopped:
            held, until, at = stopped
            wait = max(.05,until-at) if until is not None else .05
            if permit.binding_hash:
                raise RateDelayed(wait,cause='permit_blocked',scope='embargo')
            if held:
                raise RateDelayed(HOLD_WAIT_SECONDS,cause='hold',scope='embargo')
            raise RateDelayed(wait,cause='embargo',scope='embargo')
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

    def _blocked_unsent_wait(self, cur, permit, now):
        """For an admission observe() blocked before it was ever consumed: the seconds left of the embargo or circuit
        on its scopes (at least .05; .05 when a hold blocked it), or None when it was ever sent."""
        cur.execute(f'''SELECT a.sent_at IS NULL,
                extract(epoch from (SELECT max(greatest(r.blocked_until,r.circuit_until)) FROM {STATE} r
                                    WHERE r.scope_key=ANY(a.scope_keys)))::double precision
            FROM {ADMISSIONS} a WHERE a.id=%s::uuid''', (permit.id,))
        unsent, until = cur.fetchone()
        if not unsent:
            return None
        return max(.05,until-now) if valid_number(until) else .05

    def confirm_blocked_publish(self, cur, permit, binding, intent_id):
        """Prove, in its owner's workspace transaction, that this sealed publish never left: observe() blocked the
        admission before it was consumed (state 'blocked', bound to this intent, sealed, no sent_at). consume() is
        the only way from a publish permit to its POST and commits 'sent' before any transport, so the intent cannot
        have been, and can no longer be, sent. Changes nothing; refuses anything else."""
        if (not isinstance(permit, Permit) or not permit.binding_hash
                or binding_hash(binding) != permit.binding_hash):
            raise RateCoordinatorUnavailable()
        row = self._admission(cur, permit)
        if row['state'] != 'blocked' or row['intent'] != intent_id:
            raise RateCoordinatorUnavailable()
        cur.execute(f'''SELECT sent_at IS NULL AND sealed_at IS NOT NULL AND is_publish
            FROM {ADMISSIONS} WHERE id=%s::uuid''', (permit.id,))
        if cur.fetchone() != (True,):
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
                shared_keys = tuple(key for key in keys if key[:3] in ('00:','01:','10:','11:','20:','40:'))
            rows = self._locked(cur,keys,shared_keys=shared_keys) if shared_keys else self._locked(cur,keys)
            previous = {key:dict(row) for key,row in rows.items()}
            immutable_guards = {key:dict(rows[key]) for key in shared_keys}
            admission, now = self._admission(cur,permit,clock=True)   # one statement: the row lock, then the clock
            if shared_keys:
                # Decided on the same clock as the rest of the observation, after the admission row is held: the shared
                # path is abandoned by rollback, which releases that row and every SHARE lock together.
                if (any(row['hold'] or max(row['blocked'] or 0,row['circuit'] or 0)>now for row in rows.values())
                        or any(row['kind'] == 'discovery' for row in rows.values())
                        or any(row['kind'] != 'route' or not row['learned'] for key,row in rows.items() if key not in shared_keys)):
                    raise _ExclusiveObservationRequired()
            if admission['state'] != 'sent':
                raise RateCoordinatorUnavailable()  # duplicate observation cannot reset a circuit
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
            # The alias's own window, or the one this response reports, whichever is longer, plus the margin.
            horizon = self._horizon(max(rows[header_route]['window'],reset_hint-now)) if header_route else 0
            pending,unmapped = (self._alias_pending(cur,header_route,permit,meta,now,since=now-horizon)
                                if header_route else (0,0))
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
                    since = now-self._horizon(row['window'])
                    own = int(admission['reserved'] > since)  # this response's own request is among the rows counted
                    row['left'] = max(0,1-max(0,self._pending(cur,key,now,since=since)-own))
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
                        elif fresh:
                            row['left'] = min(row['left'],int(left))
                        # else: an answer to a request from before this row's last refill describes the window that
                        # ended; the refill already charged what was then in flight, so it cannot tighten the new one.
                    elif any(name in headers for name in ('x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset-after','x-ratelimit-reset')):
                        row['hold'] = True  # malformed numeric hints need operator review
                    if classification['status'] == 403 or classification['webhookInvalid']:
                        # A refusal of THIS route on THIS resource (the bot lacks a permission, was removed from the
                        # server, or the webhook is gone). Discord counts it as an invalid request, and 10,000 of those in
                        # ten minutes ban the shared egress address, so the route is not retried at once: a circuit of
                        # circuit_seconds, doubling with each consecutive refusal (the streak, cleared by an answer)
                        # up to DENIAL_BACKOFF_STEPS doublings (16 minutes at the reviewed 30 s). It used to last the
                        # whole policy (up to 31 days): the bot re-added, the permission restored, the customer told
                        # "waiting for shared request capacity" for a month.
                        row['streak'] += 1
                        steps = min(row['streak'] - 1, self.DENIAL_BACKOFF_STEPS)
                        row['circuit'] = max(row['circuit'] or 0,now+self.policy.circuit_seconds*2**steps)
                    elif transport_failure or classification['status'] >= 500:
                        row['streak'] += 1
                        if row['streak'] >= self.policy.failure_threshold:
                            row['circuit'] = max(row['circuit'] or 0,now+self.policy.circuit_seconds)
                    elif 200 <= classification['status'] < 400 and seq >= row['seq']:
                        row['streak'] = 0  # never clears an already open circuit
                    # A 404 on anything else (a message that was deleted, a member who left) is an answer about one
                    # object, not a fault of the route, and is no invalid request: it opens no circuit.
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
                alias_key = '50:' + _digest(permit.identity.auth_key + ':' + new_bucket + ':' + meta[1])
                # The mapping row and the admissions that join the new alias, in one statement (two tables, no row twice).
                cur.execute(f'''WITH routed AS (UPDATE {ROUTES} SET bucket_key=%s,observation_seq=%s,updated_at=clock_timestamp()
                    WHERE auth_key=%s AND route_key=%s AND major_key=%s RETURNING 1)
                    UPDATE {ADMISSIONS} SET bucket_key=%s,scope_keys=array_append(scope_keys,%s)
                    WHERE auth_key=%s AND route_key=%s AND major_key=%s AND state IN ('reserved','sealed','sent','uncertain')
                    AND NOT scope_keys @> ARRAY[%s]::text[]''',
                    (new_bucket,seq,permit.identity.auth_key,*meta,new_bucket,alias_key,permit.identity.auth_key,*meta,alias_key))
            # A request whose outcome is unknown stays `uncertain` and keeps its slot for _horizon, because a write may
            # have happened and nothing says it did not. A read has no effect to be unsure of and, once the transport has
            # returned (here: raised), nothing of it is still on its way: it is resolved now as a server failure, so it
            # holds its slot only for its own span like any answered request. Left `uncertain` it was a leak that a
            # remote party could cause on demand (a read that fails after the answer arrived).
            lost = transport_failure and not (permit.method == 'GET' and permit.binding_hash is None)
            cur.execute(f'''UPDATE {ADMISSIONS} SET state=%s,status_code=%s,rate_scope=%s,outcome_at=clock_timestamp()
                WHERE id=%s::uuid AND state='sent' ''',
                ('uncertain' if lost else 'observed',classification['status'],classification['scope'],permit.id))
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

    def abandon_unsent_nickname(self, permit):
        """Retire only a guarded, unbound nickname PATCH denied before IO.

        No quota refund or fabricated provider response. Otherwise a known
        unsent request would retain a discovery slot after its window expires.
        Silent for an admission that is already settled (`observed`, `blocked`): a late denied writer must not degrade it.
        """
        if (not isinstance(permit, Permit) or permit.method != 'PATCH' or permit.binding_hash is not None
                or permit.identity.kind != 'bot'):
            raise RateCoordinatorUnavailable()
        with self._transaction() as cur:
            row = self._admission(cur, permit)
            if row['intent'] is not None or row['route'] != _digest(NICKNAME_TEMPLATE):
                raise RateCoordinatorUnavailable()
            if row['state'] in ('observed', 'blocked'):
                return  # A late denied writer cannot degrade an already reconciled admission.
            if row['state'] != 'sent':
                raise RateCoordinatorUnavailable()
            cur.execute(f"UPDATE {ADMISSIONS} SET state='blocked',outcome_at=clock_timestamp() WHERE id=%s::uuid AND state='sent' AND NOT is_publish AND method='PATCH' AND route_key=%s", (permit.id, _digest(NICKNAME_TEMPLATE)))
            if cur.rowcount != 1:
                raise RateCoordinatorUnavailable()

    def reconcile_nickname(self, cur, permit, guild_id):
        """Retire one idempotent nickname operation after a later live read.

        Caller holds the workspace/credential custody and expired edit claim,
        and has freshly observed this exact bot member. No provider status is
        invented, no quota is refunded, and publication permits never qualify.
        """
        path = f'/guilds/{guild_id}/members/@me'
        if (not isinstance(permit, Permit) or permit.method != 'PATCH' or permit.binding_hash is not None or permit.identity.kind != 'bot'
                or not _ID.fullmatch(guild_id) or permit.path_key != _digest(path)):
            raise RateCoordinatorUnavailable()
        row = self._admission(cur, permit)
        if row['intent'] is not None or row['route'] != _digest(NICKNAME_TEMPLATE):
            raise RateCoordinatorUnavailable()
        self._settle_nickname(cur, permit.id, row['state'], row['reserved'], row['expires'])

    def reconcile_nickname_by_id(self, cur, admission_id, guild_id):
        """reconcile_nickname for a caller that kept only the admission's id, independent of the bot token.

        The permit-based method compares the credential digest, so after a token rotation it refuses for good and an
        uncertain nickname admission could never be retired. Everything else is required of the row itself: this
        application's, a bot's unbound non-publish PATCH of this exact path and the nickname route, no intent."""
        if not isinstance(admission_id, str) or not isinstance(guild_id, str) or not _ID.fullmatch(guild_id):
            raise RateCoordinatorUnavailable()
        try:
            admission_id = str(uuid.UUID(admission_id))
        except (ValueError, AttributeError, TypeError):
            raise RateCoordinatorUnavailable() from None
        cur.execute(f'''SELECT method,is_publish,credential_kind,binding_hash,intent_id,route_key,path_key,state,
            extract(epoch from expires_at)::double precision,extract(epoch from reserved_at)::double precision
            FROM {ADMISSIONS} WHERE id=%s::uuid AND application_key=%s FOR UPDATE''', (admission_id, self.application_key))
        value = cur.fetchone()
        if not value or len(value) != 10:
            raise RateCoordinatorUnavailable()
        method, publish, kind, binding, intent, route, path, state, expires, reserved = value
        if (method != 'PATCH' or publish is not False or kind != 'bot' or binding is not None or intent is not None
                or route != _digest(NICKNAME_TEMPLATE) or path != _digest(f'/guilds/{guild_id}/members/@me')
                or not valid_number(expires) or not valid_number(reserved)):
            raise RateCoordinatorUnavailable()
        self._settle_nickname(cur, admission_id, state, reserved, expires)

    def _settle_nickname(self, cur, admission_id, state, reserved, expires):
        """Settle an already validated nickname admission; silent when it is settled, refused while it may still be live."""
        if state in ('observed', 'blocked'):
            return  # first: a late duplicate of a settled admission is silent, however young it is
        now = self._now(cur)
        if state not in ('reserved', 'sent', 'uncertain') or reserved + 120 > now or expires > now:
            raise RateCoordinatorUnavailable()
        # `observed` records the later member read, not the original PATCH's
        # HTTP result. Keep status_code NULL and preserve every spent scope.
        cur.execute(f"UPDATE {ADMISSIONS} SET state='observed',outcome_at=clock_timestamp(),status_code=NULL,rate_scope='unknown' WHERE id=%s::uuid AND state IN ('reserved','sent','uncertain') AND NOT is_publish AND method='PATCH' AND route_key=%s", (admission_id, _digest(NICKNAME_TEMPLATE)))
        if cur.rowcount != 1:
            raise RateCoordinatorUnavailable()

    # --- retention -----------------------------------------------------------------------------------------------

    # now(), not clock_timestamp(): a volatile function cannot bound an index scan, and then a call with nothing to delete would
    # walk every young row of the partial index (66 ms at 50,000 rows) instead of none. The transaction is a few ms old.
    _PURGE_SQL = """WITH doomed AS MATERIALIZED (
            SELECT request_seq FROM {admissions}
            WHERE application_key=%s AND {publication} AND state IN ('observed','blocked')
              AND reserved_at<now()-make_interval(secs=>%s)
              AND coalesce(outcome_at,reserved_at)<now()-make_interval(secs=>%s)
            ORDER BY reserved_at LIMIT %s FOR UPDATE SKIP LOCKED),
        gone AS (DELETE FROM {admissions} a USING doomed d
                 WHERE a.request_seq=d.request_seq AND a.state IN ('observed','blocked') RETURNING 1)
        SELECT count(*) FROM gone"""

    def _purge_round(self):
        """One transaction: (reads deleted, publications deleted), or None when another caller is purging."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT set_config('lock_timeout','1000ms',true),set_config('statement_timeout','5000ms',true),"
                        "pg_try_advisory_xact_lock(%s)", (PURGE_LOCK,))
            row = cur.fetchone()
            if not row or row[2] is not True:
                return None
            counts = []
            for publication, seconds in (('NOT is_publish', self.PURGE_READ_SECONDS), ('is_publish', self.PURGE_PUBLICATION_SECONDS)):
                cur.execute(self._PURGE_SQL.format(admissions=ADMISSIONS, publication=publication),
                            (self.application_key, seconds, self.PURGE_SETTLE_GRACE_SECONDS, self.PURGE_BATCH))
                count = cur.fetchone()[0]
                if type(count) is not int or count < 0:
                    raise RateCoordinatorUnavailable()
                counts.append(count)
            return tuple(counts)

    def purge_settled(self):
        """Delete the settled admissions that are past their retention, a bounded batch at a time. Never raises.

        Reads: `observed` or `blocked`, not a publication, reserved more than PURGE_READ_SECONDS ago. Publications: the same
        past PURGE_PUBLICATION_SECONDS. A row that settled in the last PURGE_SETTLE_GRACE_SECONDS stays whatever its age (a
        late reconciliation of an old row must find it again if its caller repeats). Nothing unresolved is touched, and no
        scope row: windows, embargoes, circuits and holds are the coordinator's, not retention's. It reads and deletes only
        this application's admissions, never takes the application row's lock (or any scope lock), skips rows another
        transaction holds, and one purger runs at a time (a transaction-level advisory lock; the others return `busy`).
        Idempotent. Each statement is bounded by PURGE_BATCH rows, 1 s of lock wait and 5 s of run time.

        Returns {'status': 'ok' | 'busy' | 'denied' | 'timeout' | 'error', 'reads': n, 'publications': n, 'rounds': n,
        'more': True when the last round came back full}. `denied` is a role without DELETE on the table. No database
        message is returned or logged: the exception class only."""
        outcome = {'status': 'ok', 'reads': 0, 'publications': 0, 'rounds': 0, 'more': False}
        try:
            for _ in range(self.PURGE_ROUNDS):
                done = self._purge_round()
                if done is None:
                    outcome['status'] = 'busy' if outcome['rounds'] == 0 else outcome['status']
                    outcome['more'] = outcome['rounds'] > 0 and outcome['more']
                    break
                outcome['rounds'] += 1
                outcome['reads'] += done[0]
                outcome['publications'] += done[1]
                outcome['more'] = max(done) >= self.PURGE_BATCH
                if not outcome['more']:
                    break
        except Exception as error:
            code = getattr(error, 'sqlstate', None)
            outcome['status'] = 'denied' if code == '42501' else 'timeout' if code in ('55P03', '57014') else 'error'
            outcome['error'] = type(error).__name__
        return outcome

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
