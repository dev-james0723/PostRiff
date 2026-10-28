"""H-07: the Discord operations health snapshot behind GET /api/ops/discord/health. Read-only, aggregate-only.

What it is for: the alert rules in scripts/discord_ops_check.py (thresholds in docs/ops/discord-alert-thresholds.json),
the configuration read-back and drift alert of DURABLE-OPEN-CONFIG-PROPOSAL.md option B (the effective connect gate,
server cap, servers used and reviewed flag of the build that answers), and silent-halt detection (due work while
nothing is claimed and nothing is admitted).

Authority: the cron secret, checked exactly as the W-02 shard route checks it (at least 16 ASCII characters, a bearer
compared in constant time, GET only), before the runtime, the database or any provider client starts. Anything else
under the prefix answers the shard route's 404; a wrong or missing secret its 401.

Contents: counts, ages in seconds, booleans and codes. Never a workspace, member, job, channel, server, message,
scope key, token or e-mail, and never customer text. Two operational labels are included on purpose: the source
revision (a commit SHA, as /api/health reports it) and the Vercel deployment id, so a rollback can be read back
from a phone; neither identifies a customer.

Cost, one connection and one READ ONLY transaction with a 2-second statement timeout; every section runs in its own
savepoint, so a missing table answers 'unavailable' for that section only. No pr_workspaces row (customer state)
is read.
- queue and last claim: one pass over public.pr_discord_worker_projection (migration 126; one narrow, content-free
  row per workspace);
- deliveries, traffic and progress: the newest SAMPLE_LIMIT coordinator admissions by request_seq (its unique index),
  filtered by time inside the database;
- unresolved: every publish admission still uncertain, sent but unanswered, or holding a live permit, whatever its age,
  through the partial index pr_discord_admission_unresolved (migration 124; these rows stay until a reviewed release,
  W-02 OPEN-QUESTIONS Q3, so they are few);
- coordinator: the four application-wide rows by primary key, and a count by kind of the rows that carry a hold, a
  block or a circuit (one pass over that operational table);
- servers used: the connect gate's own count (Discord credential rows plus live installation starts; the statement
  the gate runs on every installation start, unindexed and small today, see RUNBOOK-LAUNCH section 7);
- platform: the newest row of public.pr_operational_snapshots (primary key), when migration 060 is applied;
- security: 4xx responses of the last 15 minutes by route family from public.pr_request_metrics (primary key range),
  when 060 is applied, and this instance's own cross-tenant denial counters (postriff_phase2.security_signals).
Safe to call every minute.
"""
import hashlib
import hmac
import os
import re
import time

from postriff_alpha.domain import AlphaError

from . import lane, launch_gate, rate_limits, worker as discord_worker

ROUTE = '/api/ops/discord/health'
PREFIX = '/api/ops/discord/'
VERSION = 1
KIND = 'rafii.discord.ops.health'
SAMPLE_LIMIT = 20000          # at the reviewed 25 requests a second this covers about 13 minutes; see windowCovered
STATEMENT_TIMEOUT = '2000ms'
DELIVERY_WINDOW = 900          # 15 minutes: deliveries, 429s, cross-tenant denials
INVALID_WINDOW = 600           # monitoring.sql Q2
ERROR_WINDOW = 300             # monitoring.sql Q4
SATURATION_WINDOW = 60         # the application budget spent for a whole minute
STUCK_SENT_SECONDS = 120       # docs/w02/monitoring.sql M5
# The reconciliation read-back of a created message (hosted_social: GET /channels/{channel}/messages/{message}). The
# coordinator stores the route as the SHA-256 of its template (rate_limits.route_identity); a test keeps them equal.
READBACK_ROUTE_KEY = hashlib.sha256(b'GET:/channels/{id}/messages/{id}').hexdigest()
GUARDS = {'00:': 'policy', '01:': 'bearer', '10:': 'global', '11:': 'credential', '20:': 'invalid'}   # 'bearer' only with a bearer budget
KINDS = ('policy', 'global', 'credential', 'invalid', 'discovery', 'resource', 'route')
FAMILIES = ('workspace', 'connections', 'discord', 'other')
PLATFORM_COUNTS = ('publicationUncertain', 'queueDelayed', 'publicationFailed', 'publicationHeld')
_SHA = re.compile(r'^[0-9a-f]{40}$')
_DEPLOYMENT = re.compile(r'^dpl_[A-Za-z0-9]{8,40}$')
_ENVIRONMENTS = ('production', 'preview', 'development')


def authorized(app, environ):
    """The W-02 shard route's check, unchanged: the configured cron secret (16 or more ASCII characters) as a bearer."""
    expected = app.cron_secret if app.cron_secret is not None else os.environ.get('CRON_SECRET', '')
    supplied = environ.get('HTTP_AUTHORIZATION', '')
    return bool(isinstance(expected, str) and len(expected) >= 16 and expected.isascii()
                and isinstance(supplied, str) and supplied.isascii()
                and hmac.compare_digest(supplied, 'Bearer ' + expected))


def answer(app, environ, start_response, method, path):
    """The route. 404 and 401 are the shard route's own answers (same messages, raised to the same handler)."""
    if method != 'GET' or path != ROUTE:
        raise AlphaError('This hosted route is unavailable.', 404)
    if not authorized(app, environ):
        raise AlphaError('Cron authorization failed.', 401)
    app._runtime()
    return app._json(start_response, 200, snapshot(app.worker))


def _discord(social):
    providers = getattr(social, 'providers', None)
    return providers.get('discord') if isinstance(providers, dict) else None


def _number(value, digits=1):
    return round(float(value), digits) if discord_worker.finite(value) else None


def _age(now, then, digits=1):
    if not discord_worker.finite(now) or not discord_worker.finite(then) or then <= 0:
        return None
    return round(max(0.0, now - then), digits)


def build(values):
    revision = str(values.get('VERCEL_GIT_COMMIT_SHA') or '')
    deployment = str(values.get('VERCEL_DEPLOYMENT_ID') or '')
    environment = str(values.get('VERCEL_ENV') or '')
    return {'sourceRevision': revision if _SHA.match(revision) else None,
            'deploymentId': deployment if _DEPLOYMENT.match(deployment) else None,
            'environment': environment if environment in _ENVIRONMENTS else None}


def lane_section(social, now, values):
    """lane.status() (the W-02 health indication, version 1) plus the static rule the minute tick acts on."""
    section = dict(lane.status(social, now, values))
    section['staticBlocker'] = (lane.blocker(social, now, values, process_state=False)
                                if section.get('enabled') else 'disabled')
    return section


def config_section(provider, now, values):
    """What the serving build uses (option B of DURABLE-OPEN-CONFIG-PROPOSAL.md). Counts and codes; no workspace id."""
    gate = launch_gate.configuration(values)
    cap, cap_misconfigured = launch_gate.guild_cap(values)
    limiter = getattr(provider, 'rate_limiter', None)
    policy = getattr(limiter, 'policy', None)
    out = {
        'providerMounted': provider is not None,
        'gate': {'mode': gate.mode, 'workspaces': len(gate.workspaces), 'misconfigured': bool(gate.misconfigured)},
        'cap': {'value': cap, 'unlimited': cap is None, 'misconfigured': bool(cap_misconfigured)},
        'productionEnvironment': launch_gate.hosted_production(values),
        'reviewed': bool(getattr(provider, 'production_reviewed', False)) if provider is not None else None,
        'connectionsV2': bool(getattr(provider, 'connections_v2_enabled', False)),
        'authorizationV2': bool(getattr(provider, 'authorization_v2_enabled', False)),
        'rateLimitsV1': bool(getattr(provider, 'rate_v1_enabled', False)),
        'workerV1': bool(discord_worker.enabled(values)),
        'laneFlag': bool(lane.enabled(values)),
        'executionEnabled': bool(getattr(provider, 'execution_enabled', False)) if provider is not None else None,
        'killSwitch': str(values.get('POSTRIFF_OAUTH_DISCORD_DISABLED', '')).lower() == 'true',
        'coordinatorDegraded': bool(getattr(provider, 'rate_coordinator_degraded', False)),
        'policy': {'present': policy is not None, 'valid': None, 'daysLeft': None, 'revision': None},
    }
    if policy is not None:
        valid = discord_worker.finite(now) and policy.issued_at <= now < policy.expires_at
        out['policy'].update(valid=bool(valid), daysLeft=round((policy.expires_at - now) / 86400, 2),
                             revision=policy.revision, appCapacity=policy.app_capacity,
                             appWindowSeconds=policy.app_window_seconds, invalidCapacity=policy.invalid_capacity,
                             invalidWindowSeconds=policy.invalid_window_seconds,
                             bearerCapacity=policy.bearer_capacity or None,
                             bearerWindowSeconds=policy.bearer_window_seconds if policy.bearer_capacity else None)
    # The coordinator's own slot guard (SharedPostgresBudget.SLOT_GUARD_SECONDS, where the build has one): the budget
    # alert divides by what can be admitted, and reading the constant here means a later change moves the alert with it.
    guard = getattr(limiter, 'SLOT_GUARD_SECONDS', None) if limiter is not None else None
    out['policy']['slotGuardSeconds'] = float(guard) if discord_worker.finite(guard) else None
    # What a read refused by a hold is told to wait (rate_limits.HOLD_WAIT_SECONDS, the limiter's B4), or null on a build
    # without it, where a created post's read-back fails under the hold and is parked: the hold alert says which.
    wait = getattr(rate_limits, 'HOLD_WAIT_SECONDS', None)
    out['holdReadWaitSeconds'] = float(wait) if discord_worker.finite(wait) else None
    return out


# --- database sections (each runs inside the caller's savepoint) ------------------------------------------------------

_QUEUE = '''WITH observed AS (SELECT extract(epoch FROM clock_timestamp())::double precision AS at)
SELECT count(p.workspace_id) FILTER (WHERE p.next_at <= observed.at),
       count(p.workspace_id) FILTER (WHERE p.next_at > observed.at AND p.next_at <= observed.at + 300),
       count(p.workspace_id) FILTER (WHERE p.next_at IS NOT NULL),
       coalesce(max(observed.at - p.next_at) FILTER (WHERE p.next_at <= observed.at), 0),
       max(nullif(p.last_claimed_at, 0))
FROM observed LEFT JOIN public.pr_discord_worker_projection p ON true
GROUP BY observed.at'''


def read_queue(cur, now, context):
    cur.execute(_QUEUE)
    due, soon, pending, lag, last_claim = cur.fetchone()
    queue = {'status': 'observed', 'dueWorkspaces': int(due), 'dueWithin5Min': int(soon),
             'pendingWorkspaces': int(pending), 'oldestDueLagSeconds': _number(lag)}
    return queue, {'lastClaimAgeSeconds': _age(now, last_claim)}


_LEDGER = '''WITH observed AS MATERIALIZED (SELECT clock_timestamp() AS at),
sample AS MATERIALIZED (
    SELECT is_publish, state, status_code, rate_scope, route_key, reserved_at, sent_at, outcome_at, credential_kind,
           coalesce(outcome_at, sent_at, reserved_at) AS last_at
    FROM public.pr_discord_request_admissions ORDER BY request_seq DESC LIMIT %(limit)s)
SELECT count(*),
       extract(epoch FROM min(s.reserved_at))::double precision,
       extract(epoch FROM max(s.reserved_at))::double precision,
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'observed' AND s.status_code BETWEEN 200 AND 299),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'observed' AND s.status_code IN (403, 404)),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'observed' AND s.status_code NOT BETWEEN 200 AND 299
                          AND s.status_code NOT IN (403, 404, 429) AND s.status_code < 500),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'observed' AND s.status_code = 429),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'uncertain'),
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'blocked'),
       count(*) FILTER (WHERE s.is_publish AND s.state IN ('reserved', 'sealed', 'sent')
                          AND s.last_at > o.at - make_interval(secs => %(stuck)s)),
       count(*) FILTER (WHERE s.is_publish AND s.state = 'sent'
                          AND s.last_at <= o.at - make_interval(secs => %(stuck)s)
                          AND s.last_at > o.at - make_interval(secs => %(window)s)),
       count(*) FILTER (WHERE s.is_publish AND s.state = 'sent' AND s.last_at <= o.at - make_interval(secs => %(stuck)s)),
       count(*) FILTER (WHERE s.status_code = 429 AND s.last_at > o.at - make_interval(secs => %(window)s)),
       count(*) FILTER (WHERE s.status_code = 429 AND s.rate_scope = 'global'
                          AND s.last_at > o.at - make_interval(secs => %(window)s)),
       count(*) FILTER (WHERE s.last_at > o.at - make_interval(secs => %(invalid)s)
                          AND (s.status_code IN (401, 403)
                               OR (s.status_code = 429 AND coalesce(s.rate_scope, 'unknown') <> 'shared'))),
       count(*) FILTER (WHERE s.outcome_at > o.at - make_interval(secs => %(errors)s) AND s.status_code IS NOT NULL),
       count(*) FILTER (WHERE s.outcome_at > o.at - make_interval(secs => %(errors)s) AND s.status_code >= 500),
       count(*) FILTER (WHERE s.reserved_at > o.at - make_interval(secs => %(saturation)s)
                          AND NOT (%(bearer)s AND s.credential_kind = 'user')),
       count(*) FILTER (WHERE NOT s.is_publish AND s.state = 'uncertain'
                          AND s.last_at > o.at - make_interval(secs => %(window)s)),
       count(*) FILTER (WHERE s.status_code = 401 AND s.last_at > o.at - make_interval(secs => %(window)s)),
       extract(epoch FROM max(s.outcome_at) FILTER (WHERE s.is_publish AND s.state = 'observed'
                                                      AND s.status_code BETWEEN 200 AND 299))::double precision,
       extract(epoch FROM max(s.outcome_at) FILTER (WHERE s.route_key = %(readback)s AND s.state = 'observed'
                                                      AND s.status_code BETWEEN 200 AND 299))::double precision,
       count(*) FILTER (WHERE s.is_publish AND s.last_at > o.at - make_interval(secs => %(window)s)
                          AND s.state = 'observed' AND s.status_code >= 500),
       count(*) FILTER (WHERE %(bearer)s AND s.credential_kind = 'user'
                          AND s.reserved_at > o.at - make_interval(secs => %(saturation)s))
FROM sample s CROSS JOIN observed o'''


def read_ledger(cur, now, context):
    # With a bearer budget the application budget counts the bot's class alone (rate_limits.BEARER_KIND is the other): the
    # admissions of the last minute are given for each, so each can be read against its own cap.
    limiter = getattr(context.get('provider'), 'rate_limiter', None)
    bearer = bool(getattr(limiter, 'bearer_key', None))
    cur.execute(_LEDGER, {'limit': SAMPLE_LIMIT, 'window': DELIVERY_WINDOW, 'stuck': STUCK_SENT_SECONDS,
                          'invalid': INVALID_WINDOW, 'errors': ERROR_WINDOW, 'saturation': SATURATION_WINDOW,
                          'readback': READBACK_ROUTE_KEY, 'bearer': bearer})
    (sampled, oldest, newest, creates, accepted, customer, system, limited, uncertain, blocked, in_flight,
     stuck_new, stuck_all, r429, r429_global, invalid, responses, server_errors, admitted, uncertain_reads,
     unauthorized, last_accepted, last_readback, upstream, bearer_admitted) = cur.fetchone()
    sampled = int(sampled)
    span = _age(now, oldest) if sampled else None
    # The sample is the newest SAMPLE_LIMIT rows: a window is fully seen when the sample is not full or reaches back.
    full = sampled >= SAMPLE_LIMIT

    def covered(seconds):
        return not full or (span is not None and span >= seconds)
    deliveries = {'status': 'observed', 'windowSeconds': DELIVERY_WINDOW, 'windowCovered': covered(DELIVERY_WINDOW),
                  'sampled': sampled, 'sampleLimit': SAMPLE_LIMIT, 'creates': int(creates), 'accepted': int(accepted),
                  'rejectedCustomer': int(customer), 'rejectedSystem': int(system),
                  # 5xx answers to creates: Discord's side (or something between us and Discord), apart from ours (N-9)
                  'rejectedUpstream': int(upstream), 'rateLimited': int(limited),
                  'uncertain': int(uncertain), 'blocked': int(blocked), 'inFlight': int(in_flight),
                  'stuckSent': int(stuck_new), 'stuckSentTotal': int(stuck_all)}
    traffic = {'responses429': int(r429), 'responses429Global': int(r429_global), 'invalid10m': int(invalid),
               'invalidWindowCovered': covered(INVALID_WINDOW), 'responses5m': int(responses),
               'serverErrors5m': int(server_errors), 'admissions60s': int(admitted),
               'bearerAdmissions60s': int(bearer_admitted),
               'uncertainReads': int(uncertain_reads), 'unauthorized': int(unauthorized)}
    progress = {'lastAdmissionAgeSeconds': _age(now, newest), 'lastAcceptedCreateAgeSeconds': _age(now, last_accepted),
                'lastReadbackAgeSeconds': _age(now, last_readback), 'sampleSpanSeconds': span}
    return deliveries, traffic, progress


_GUARD_ROWS = '''SELECT scope_key, kind, manual_hold, limit_count, remaining,
       extract(epoch FROM reset_at)::double precision, extract(epoch FROM blocked_until)::double precision,
       extract(epoch FROM circuit_until)::double precision, extract(epoch FROM updated_at)::double precision,
       extract(epoch FROM policy_expires_at)::double precision, window_seconds
FROM public.pr_discord_rate_state WHERE scope_key = ANY(%s::text[])'''

_KIND_ROWS = '''SELECT kind,
       count(*) FILTER (WHERE manual_hold),
       count(*) FILTER (WHERE blocked_until > clock_timestamp()),
       count(*) FILTER (WHERE circuit_until > clock_timestamp()),
       count(*) FILTER (WHERE circuit_until > clock_timestamp() AND circuit_until >= policy_expires_at - interval '1 second'),
       count(*) FILTER (WHERE greatest(circuit_until, blocked_until) > clock_timestamp()
                          AND updated_at < clock_timestamp() - interval '5 minutes')
FROM public.pr_discord_rate_state
WHERE manual_hold OR blocked_until > clock_timestamp() OR circuit_until > clock_timestamp()
GROUP BY kind'''


def guard_keys(provider):
    """The coordinator's own key derivation for the four application-wide rows (as lane.outlook reads them)."""
    limiter = getattr(provider, 'rate_limiter', None)
    if limiter is None or getattr(limiter, 'policy', None) is None or not hasattr(provider, '_rate_identity'):
        return {}
    marker = '0' * 64
    keys = limiter._keys(provider._rate_identity('bot'), marker, marker, marker)
    found = {key: GUARDS[key[:3]] for key in keys if key[:3] in GUARDS}
    bearer = getattr(limiter, 'bearer_key', None)   # the person's own bearer calls' budget, when the policy has one
    if bearer:
        found[bearer] = GUARDS[bearer[:3]]
    return found


_UNRESOLVED = '''SELECT
    (SELECT count(*) FROM public.pr_discord_request_admissions WHERE state = 'uncertain' AND is_publish),
    (SELECT count(*) FROM public.pr_discord_request_admissions
      WHERE state = 'sent' AND is_publish AND sent_at <= clock_timestamp() - make_interval(secs => %(stuck)s)),
    (SELECT count(*) FROM public.pr_discord_request_admissions
      WHERE state IN ('reserved', 'sealed') AND expires_at > clock_timestamp() AND is_publish),
    (SELECT extract(epoch FROM min(coalesce(sent_at, reserved_at)))::double precision FROM public.pr_discord_request_admissions
      WHERE is_publish AND (state = 'uncertain'
                            OR state = 'sent' AND sent_at <= clock_timestamp() - make_interval(secs => %(stuck)s)))'''


def read_unresolved(cur, now, context):
    cur.execute(_UNRESOLVED, {'stuck': STUCK_SENT_SECONDS})
    uncertain, stuck, live, oldest = cur.fetchone()
    return {'status': 'observed', 'uncertainPublishes': int(uncertain), 'stuckSentPublishes': int(stuck),
            'livePermits': int(live), 'oldestUnresolvedAgeSeconds': _age(now, oldest)}


def _guard(row, now):
    _key, kind, hold, limit, remaining, reset, blocked, circuit, updated, expires, window = row
    rolled = discord_worker.finite(reset) and reset <= now
    ratio = None
    if limit:
        # A rolled invalid-request window starts full again (rate_limits._roll); the application row's 1-second window
        # is read through admissions60s instead.
        ratio = 1.0 if rolled and kind == 'invalid' else round(max(0, remaining or 0) / limit, 4)
    embargo = max(blocked or 0, circuit or 0) - now
    return {'present': True, 'hold': bool(hold), 'blocked': bool(blocked and blocked > now),
            'circuit': bool(circuit and circuit > now), 'embargoSeconds': round(max(0.0, embargo), 1),
            'remaining': remaining, 'limit': limit, 'windowSeconds': window, 'remainingRatio': ratio,
            'resetSeconds': round(max(0.0, reset - now), 1) if discord_worker.finite(reset) else None,
            'unchangedSeconds': _age(now, updated), 'policyDaysLeft': round((expires - now) / 86400, 2)
            if discord_worker.finite(expires) else None}


def read_coordinator(cur, now, context):
    keys = guard_keys(context.get('provider'))
    guards = {name: {'present': False} for name in GUARDS.values() if name != 'bearer' or 'bearer' in keys.values()}
    if keys:
        cur.execute(_GUARD_ROWS, (sorted(keys),))
        for row in cur.fetchall():
            if row[0] in keys:
                guards[keys[row[0]]] = _guard(row, now)
    cur.execute(_KIND_ROWS)
    kinds = {}
    for kind, holds, blocks, circuits, persistent, over in cur.fetchall():
        if kind in KINDS:
            kinds[kind] = {'holds': int(holds), 'blocks': int(blocks), 'circuits': int(circuits),
                           'persistentCircuits': int(persistent), 'openOver5Min': int(over)}
    days = [g['policyDaysLeft'] for g in guards.values() if g.get('policyDaysLeft') is not None]
    return {'status': 'observed' if keys else 'no_coordinator', 'guards': guards, 'kinds': kinds,
            'rowsPolicyDaysLeft': min(days) if days else None}


_SERVERS = ('SELECT (SELECT count(DISTINCT provider_account_id) FROM public.pr_encrypted_credentials '
            "WHERE provider='discord' AND 'bot' = ANY(scopes)), "
            '(SELECT count(*) FROM public.pr_oauth_transactions WHERE ' + launch_gate._IN_FLIGHT + ')')


def read_servers(cur, now, context):
    cur.execute(_SERVERS)
    counted, in_flight = (int(value) for value in cur.fetchone())
    cap = context['cap']
    used = counted + in_flight
    return {'status': 'observed', 'counted': counted, 'inFlight': in_flight, 'used': used,
            'ratio': round(used / cap, 4) if cap else None}


_RETENTION = """SELECT
    (SELECT extract(epoch FROM min(reserved_at))::double precision FROM public.pr_discord_request_admissions
      WHERE state IN ('observed', 'blocked') AND NOT is_publish),
    (SELECT extract(epoch FROM min(reserved_at))::double precision FROM public.pr_discord_request_admissions
      WHERE state IN ('observed', 'blocked') AND is_publish),
    s.n_live_tup, s.n_dead_tup, s.n_tup_del,
    extract(epoch FROM greatest(s.last_autovacuum, s.last_vacuum))::double precision
FROM (SELECT 1) one LEFT JOIN pg_stat_user_tables s
  ON s.schemaname = 'public' AND s.relname = 'pr_discord_request_admissions'"""


def read_retention(cur, now, context):
    """Retention of the coordinator's admissions (rate_limits.SharedPostgresBudget.purge_settled), from the partial index
    of migration 142 and the table's statistics: no scan, no count(*). The two ages are of the oldest SETTLED row of each
    kind; the purge keeps them under their retention, so an age far past it (an alert at three times) means the purge is
    not running or cannot delete."""
    from .rate_limits import SharedPostgresBudget
    cur.execute(_RETENTION)
    oldest_read, oldest_publication, live, dead, deleted, vacuumed = cur.fetchone()

    def count(value):
        return None if value is None else int(value)
    return {'status': 'observed',
            'retentionSeconds': {'reads': int(SharedPostgresBudget.PURGE_READ_SECONDS),
                                 'publications': int(SharedPostgresBudget.PURGE_PUBLICATION_SECONDS)},
            'oldestSettledReadAgeSeconds': _age(now, oldest_read),
            'oldestSettledPublicationAgeSeconds': _age(now, oldest_publication),
            'liveRowsEstimate': count(live), 'deadRowsEstimate': count(dead), 'rowsDeletedTotal': count(deleted),
            'lastVacuumAgeSeconds': _age(now, vacuumed)}


_BOOKING = """WITH observed AS MATERIALIZED (SELECT clock_timestamp() AS at),
sample AS MATERIALIZED (
    SELECT is_publish, reserved_at, sent_at, coalesce(sent_at, reserved_at) AS wire
    FROM public.pr_discord_request_admissions ORDER BY request_seq DESC LIMIT %(limit)s)
SELECT count(*) FILTER (WHERE s.wire > o.at),
       extract(epoch FROM max(s.wire) FILTER (WHERE s.wire > o.at))::double precision,
       count(*) FILTER (WHERE NOT s.is_publish AND s.sent_at > s.reserved_at + interval '5 milliseconds'
                          AND s.reserved_at > o.at - make_interval(secs => %(window)s)),
       coalesce(sum(extract(epoch FROM s.sent_at - s.reserved_at)) FILTER (WHERE NOT s.is_publish
                  AND s.sent_at > s.reserved_at + interval '5 milliseconds'
                  AND s.reserved_at > o.at - make_interval(secs => %(window)s)), 0)::double precision,
       coalesce(max(extract(epoch FROM s.sent_at - s.reserved_at)) FILTER (WHERE NOT s.is_publish
                  AND s.sent_at > s.reserved_at + interval '5 milliseconds'
                  AND s.reserved_at > o.at - make_interval(secs => %(window)s)), 0)::double precision,
       extract(epoch FROM o.at)::double precision
FROM sample s CROSS JOIN observed o GROUP BY o.at"""


def read_booking(cur, now, context):
    """Booking (rate_limits.SharedPostgresBudget.reserve): how many admissions still wait for their wire time, how far ahead the
    latest lies, and what the reads booked in the last minute waited. `horizonSeconds` close to `bookAheadSeconds` means the booked
    horizon is full and callers are being refused again (the saturation that `remaining` used to show). Reads only: a create's
    booked wait is not recorded (its reserved_at is its slot); `aheadNow` counts creates as well."""
    from .rate_limits import SharedPostgresBudget
    cur.execute(_BOOKING, {'limit': SAMPLE_LIMIT, 'window': SATURATION_WINDOW})
    row = cur.fetchone()
    ahead, furthest, booked, total, longest, db_now = row if row else (0, None, 0, 0.0, 0.0, now)
    horizon = max(0.0, furthest - db_now) if furthest is not None and db_now is not None else 0.0
    return {'status': 'observed', 'bookAheadSeconds': float(SharedPostgresBudget.BOOK_AHEAD_SECONDS),
            'aheadNow': int(ahead), 'horizonSeconds': round(horizon, 3),
            'bookedReads60s': int(booked), 'bookedReadWaitSeconds60s': round(float(total), 3),
            'meanBookedReadWaitSeconds60s': round(float(total) / int(booked), 3) if int(booked) else 0.0,
            'maxBookedReadWaitSeconds60s': round(float(longest), 3)}


def read_platform(cur, now, context):
    cur.execute("SELECT to_regclass('public.pr_operational_snapshots') IS NOT NULL")
    if not cur.fetchone()[0]:
        return {'status': 'not_installed'}
    cur.execute('SELECT extract(epoch FROM observed_at)::double precision, status, counts '
                'FROM public.pr_operational_snapshots ORDER BY minute DESC LIMIT 1')
    row = cur.fetchone()
    if not row:
        return {'status': 'empty'}
    counts = row[2] if isinstance(row[2], dict) else {}
    return {'status': 'observed', 'ageSeconds': _age(now, row[0]), 'snapshotStatus': row[1] if row[1] in ('ok', 'attention') else None,
            **{name: counts[name] for name in PLATFORM_COUNTS if type(counts.get(name)) is int}}


def family(route_pattern):
    """A request-metrics route pattern (identifiers already masked) as one of FAMILIES."""
    route = route_pattern.split(' ', 1)[-1] if isinstance(route_pattern, str) else ''
    if '/discord' in route:
        return 'discord'
    if route.startswith('/api/workspaces/:id/channels'):
        return 'connections'
    if route.startswith('/api/workspaces/'):
        return 'workspace'
    return 'other'


def read_requests(cur, now, context):
    cur.execute("SELECT to_regclass('public.pr_request_metrics') IS NOT NULL")
    if not cur.fetchone()[0]:
        return {'status': 'not_installed'}
    cur.execute("SELECT route_pattern, sum(request_count) FROM public.pr_request_metrics "
                "WHERE minute > clock_timestamp() - make_interval(secs => %s) AND status_class = '4xx' GROUP BY 1",
                (DELIVERY_WINDOW,))
    counts = dict.fromkeys(FAMILIES, 0)
    for pattern, count in cur.fetchall():
        counts[family(pattern)] += int(count or 0)
    return {'status': 'observed', 'windowSeconds': DELIVERY_WINDOW, **counts}


def _savepoint(cur, errors, name, read, now, context):
    cur.execute('SAVEPOINT discord_ops')
    try:
        value = read(cur, now, context)
        cur.execute('RELEASE SAVEPOINT discord_ops')
        return value
    except Exception as error:  # a missing table or a timeout answers for this section only
        cur.execute('ROLLBACK TO SAVEPOINT discord_ops')
        errors.append({'section': name, 'error': type(error).__name__})
        return None


def _unavailable(name, errors):
    error = next((e['error'] for e in errors if e['section'] in (name, 'database')), None)
    return {'status': 'unavailable', **({'error': error} if error else {})}


def snapshot(worker, values=None, *, clock=time.time, monotonic=time.monotonic):
    """The health payload (version 1). Never raises for a database problem: the failing sections say 'unavailable'."""
    values = os.environ if values is None else values
    started = monotonic()
    social = getattr(worker, 'social', None)
    provider = _discord(social)
    now = clock()
    config = config_section(provider, now, values)
    result = {'version': VERSION, 'kind': KIND, 'source': 'health_route', 'observedAt': None, 'build': build(values),
              'lane': lane_section(social, now, values), 'config': config}
    errors, found = [], {}
    context = {'provider': provider, 'cap': config['cap']['value']}
    factory = getattr(worker, 'connection_factory', None)
    try:
        if factory is None:
            raise RuntimeError('no connection factory')
        with factory() as db, db.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute("SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', '500ms', true), "
                        "extract(epoch FROM clock_timestamp())::double precision", (STATEMENT_TIMEOUT,))
            db_now = float(cur.fetchone()[2])
            result['observedAt'] = round(db_now, 3)
            for name, read in (('queue', read_queue), ('ledger', read_ledger), ('unresolved', read_unresolved), ('coordinator', read_coordinator),
                               ('retention', read_retention), ('booking', read_booking), ('servers', read_servers), ('platform', read_platform),
                               ('requests', read_requests)):
                found[name] = _savepoint(cur, errors, name, read, db_now, context)
    except Exception as error:
        errors.append({'section': 'database', 'error': type(error).__name__})
    queue = found.get('queue')
    ledger = found.get('ledger')
    result['queue'] = queue[0] if queue else _unavailable('queue', errors)
    result['deliveries'] = ledger[0] if ledger else _unavailable('ledger', errors)
    result['unresolved'] = found.get('unresolved') or _unavailable('unresolved', errors)
    progress = {'lastClaimAgeSeconds': None, 'lastAdmissionAgeSeconds': None, 'lastAcceptedCreateAgeSeconds': None,
                'lastReadbackAgeSeconds': None, 'sampleSpanSeconds': None}
    progress.update(queue[1] if queue else {})
    progress.update(ledger[2] if ledger else {})
    progress['status'] = 'observed' if queue and ledger else 'partial' if queue or ledger else 'unavailable'
    result['progress'] = progress
    coordinator = found.get('coordinator') or _unavailable('coordinator', errors)
    coordinator['traffic'] = ledger[1] if ledger else {'status': 'unavailable'}
    coordinator['retention'] = found.get('retention') or _unavailable('retention', errors)
    coordinator['booking'] = found.get('booking') or _unavailable('booking', errors)
    result['coordinator'] = coordinator
    config['servers'] = found.get('servers') or _unavailable('servers', errors)
    result['platform'] = found.get('platform') or _unavailable('platform', errors)
    from .. import security_signals
    result['security'] = {'instance': security_signals.summary(), 'responses4xx': found.get('requests') or _unavailable('requests', errors)}
    result['errors'] = errors
    result['elapsedMs'] = round((monotonic() - started) * 1000, 1)
    return result
