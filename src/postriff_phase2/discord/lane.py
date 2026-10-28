"""W-02 parallel Discord lane. Default off; no schema, queue, lock or scheduler of its own.

Cron shards call /api/cron/discord-worker/<shard> every minute (vercel.json). Each invocation runs ONE bounded loop of
the existing Discord-only worker step under its own lease owner id: workspace rows are claimed FOR UPDATE SKIP LOCKED,
one job per claim and at most one live Discord lease per workspace, the lease owner and lease id are rechecked at every
step, every Discord request is admitted by the shared PostgreSQL coordinator, and an intent is sealed before any POST.
Loops may overlap each other, the existing /api/cron/worker (which leaves Discord to this lane only while the flag is
on and blocker(process_state=False) says the lane can run; otherwise it keeps the frozen Discord path) and a person's
own "post now" nudge. That overlap is safe by the lease protocol; keeping Discord to one scheduler is a preference.

The loop only adds waiting. Before each claim it asks blocker() and reads the coordinator's application-wide rows
without locks: an operator hold (manual_hold) stops it, an embargo or a spent budget (the application window or the
invalid-request budget) is slept out instead of claiming work that cannot be sent, and it stops when no work is due
soon. It never extends an approval, a lease or a permit, never retries a create, and stops admitting steps early
enough that the last one ends inside the function's time limit.
"""
import copy
import json
import logging
import math
import os
import random
import re
import threading
import time
import uuid

from postriff_alpha.domain import AlphaError
from . import worker as discord_worker
from .rate_limits import RateDelayed
from ..hosted_worker import PostgresWorker

ENV_ENABLED = 'POSTRIFF_DISCORD_PARALLEL_WORKER_V1_ENABLED'
ENV_SECONDS = 'POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS'
ENV_STEPS = 'POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_STEPS'
ROUTE = '/api/cron/discord-worker/'
# Cron entries in vercel.json (a test keeps them equal); the route accepts up to MAX_SHARDS so a reviewed change of
# the cron list needs no code change, and nothing outside that range can start a loop.
SHARDS = 12
MAX_SHARDS = 32
# vercel.json maxDuration of api/index.py (a test keeps them equal). A step admitted just before the deadline may
# still make seven Discord requests (the bot identity twice when its 60-second cache is cold, the guild, two members,
# the channel list, the create) at the transport's 20-second timeout, plus its database transactions: the step
# reserve. The budget starts when the route runs, so a cold start's imports before it get their own allowance. The
# margin is room, not a bound: the default database factory (hosted_app.postgres_factory) opens a connection per
# transaction with an 8-second connect timeout and sets no statement_timeout, so nothing caps a step's database time.
FUNCTION_SECONDS = 300
STEP_RESERVE_SECONDS = 160
COLD_START_SECONDS = 20
MARGIN_SECONDS = 30
# 300 - 160 - 20 - 30 = 90. A larger configured budget is clamped to it, never refused (limits()).
MAX_SECONDS = FUNCTION_SECONDS - STEP_RESERVE_SECONDS - COLD_START_SECONDS - MARGIN_SECONDS
# Under the one-minute cron period, so a shard normally has one loop at a time.
DEFAULT_SECONDS = 50
DEFAULT_STEPS = 600
MAX_STEPS = 5000
# A miss sleeps until the soonest due work if it is this close (a read-back is due five seconds after its create);
# otherwise, or after this many misses in a row, the loop ends and the next cron minute starts a new one.
IDLE_HORIZON_SECONDS = 10
MAX_IDLE_MISSES = 6
# While the flag is on, the minute tick logs one warning when its own Discord report (discord_report: the oldest due,
# unleased Discord job in its bounded sample) is later than this: shard crons that do not fire or cannot claim, a lane
# that cannot keep up with a burst, or a minute tick that kept Discord because the lane could not run anywhere.
LAG_WARNING_SECONDS = 300
# A document the claim cannot read (a null where a list belongs, a missing key) is set aside, not retried: its workspace
# is skipped this long, behind every other workspace, and at most this many are set aside by one claim; one more is
# not a document but the claim code itself, and raises as before.
QUARANTINE_SECONDS = 300
MAX_QUARANTINES_PER_CLAIM = 2
# A post the shared budget released unsent (the application window spent, or a create permit that ended unused) keeps
# its place in the queue, at most this many times; after that the release costs the turn as it always did.
MAX_POSITION_RESTORES = 3
SHAPE_ERRORS = (AttributeError, IndexError, KeyError, TypeError, ValueError)
_SHARD = re.compile(r'^(0|[1-9][0-9]?)$')
_GUARDS = ('00:', '10:', '11:', '20:')  # application policy, bot global, bot credential, invalid-request budget
_OUTLOOK = '''WITH observed AS (SELECT extract(epoch from clock_timestamp())::double precision AS at)
    SELECT observed.at,r.scope_key,r.kind,r.manual_hold,r.remaining,extract(epoch from r.reset_at)::double precision,
        extract(epoch from r.blocked_until)::double precision,extract(epoch from r.circuit_until)::double precision
    FROM observed LEFT JOIN public.pr_discord_rate_state r ON r.scope_key=ANY(%s::text[])'''
_SOONEST = '''SELECT extract(epoch from clock_timestamp())::double precision,min(next_at)
    FROM public.pr_discord_worker_projection WHERE next_at IS NOT NULL'''
# The loop's own look at the queue: _SOONEST without the workspaces set aside (LaneWorker.claim dates their rotation
# cursor ahead and skips them). Counting them would keep every shard busy claiming nothing until their window ends;
# the lag warning keeps reading _SOONEST, because their posts are late all the same.
_CLAIMABLE = '''SELECT extract(epoch from clock_timestamp())::double precision,min(next_at)
    FROM public.pr_discord_worker_projection
    WHERE next_at IS NOT NULL AND last_claimed_at<=extract(epoch from clock_timestamp())::double precision'''
COUNTERS = ('steps', 'claimed', 'posted', 'verified', 'held', 'uncertain', 'rateDelayed', 'leaseLost', 'recoveries',
            'retries', 'deadLetters', 'claimMisses', 'rejected', 'notSent', 'uncertainCreates', 'rateWaits', 'idleWaits',
            'permitWaits', 'quarantined', 'positionsKept')
_QUARANTINED = [0]  # workspaces this process has set aside since it started; a count, never an identifier
_QUARANTINE_LOCK = threading.Lock()


def quarantined():
    """How many workspaces this process has set aside since it started (LaneWorker._quarantine)."""
    return _QUARANTINED[0]


def enabled(values=None):
    """Exact string, like the other Discord flags. The lane also needs the Discord worker lease protocol on."""
    values = os.environ if values is None else values
    return values.get(ENV_ENABLED) == 'true' and discord_worker.enabled(values)


def limits(values=None):
    """(seconds, steps) of one invocation. A time budget above MAX_SECONDS is clamped to it, so tightening the cap never
    turns an existing setting into a refusal; anything else out of range refuses (503, nothing claimed)."""
    values = os.environ if values is None else values
    try:
        seconds = float(values.get(ENV_SECONDS, DEFAULT_SECONDS))
        steps = int(values.get(ENV_STEPS, DEFAULT_STEPS))
    except (ValueError, TypeError, OverflowError):
        seconds = steps = None
    if seconds is None or not math.isfinite(seconds) or seconds < 5 or not 1 <= steps <= MAX_STEPS:
        raise AlphaError('The Discord lane needs at least 5 seconds (it uses at most %d) and 1 to %d steps.'
                         % (MAX_SECONDS, MAX_STEPS), 503, code='discord_lane_configuration')
    return min(seconds, float(MAX_SECONDS)), steps


def shard(text):
    """The shard number from the route suffix, or None for anything else."""
    if not isinstance(text, str) or not _SHARD.match(text) or int(text) >= MAX_SHARDS:
        return None
    return int(text)


def disabled(number, values=None):
    # Answered without the runtime: status() sees no provider, so policyDaysLeft is None here.
    return {'version': 1, 'lane': 'discord', 'enabled': False, 'shard': number, 'processed': 0,
            'status': status(None, time.time(), values)}


class PacedSocial:
    """The provider facade the lane's worker sees: one change, a refused create permit waits like a refused read.

    The existing step reserves the create's permit only after its four preflight reads. Refused there, it releases
    the job, so at a saturated budget those reads are spent again and again and little is created. Reads already
    wait in-process up to one second for the next window; this gives the create permit the same bounded wait. It
    happens before any intent is sealed, the job keeps its live lease, and the step rechecks every fence after it.
    Longer waits (an embargo, a learned channel window) are refused as before and the job is released unsent.
    """
    def __init__(self, social, *, wait_seconds=1.0, sleep=time.sleep, monotonic=time.monotonic):
        self._social, self._wait, self._sleep, self._monotonic = social, wait_seconds, sleep, monotonic
        self.permit_waits = 0

    def __getattr__(self, name):
        return getattr(self._social, name)

    def reserve_discord_send(self, manifest, **kwargs):
        deadline = self._monotonic() + self._wait
        while True:
            try:
                return self._social.reserve_discord_send(manifest, **kwargs)
            except RateDelayed as error:
                pause = error.retry_after_seconds + random.uniform(.005, .03)
                # Only a spent application window, or a permit that lapsed at that window's end while it was being
                # stored. A deadline already passed (lease or approval) is refused at once, as before.
                window = error.rate_scope_kind == 'application' or (error.rate_scope_kind == 'permit'
                                                                    and error.rate_cause == 'permit_expired')
                if not window or self._monotonic() + pause > deadline:
                    raise
                self.permit_waits += 1
                self._sleep(pause)


class LaneWorker(PostgresWorker):
    """One invocation's own lease owner and counters. Every claim, check and send is the inherited code."""
    def __init__(self, base, number, *, sleep=time.sleep, monotonic=time.monotonic, values=None):
        super().__init__(base.connection_factory, social=PacedSocial(base.social, sleep=sleep, monotonic=monotonic),
                         clock=base.clock,
                         worker_id='discord-lane-%d-%s' % (number, uuid.uuid4().hex),
                         on_verified=getattr(base, 'on_verified', None),
                         worker_binding=getattr(base, 'worker_binding', None), discord_workers=True)
        self.environment = values  # what this invocation was started with, for blocker()
        self.lane_counts = dict.fromkeys(('posted', 'verified', 'rejected', 'notSent', 'uncertainCreates', 'positionsKept'), 0)
        self.discord_stats['quarantined'] = 0
        self._examining = None  # the workspace the claim is reading, so a failure of its document can be pinned on it
        self._before = None  # that workspace's queue position as the claim found it (see _discord_rate_released)

    def _discord_candidates(self, cur):
        """The inherited selection, except that a workspace set aside (see claim) is not offered again until its
        window ends, and the workspace being read is noted. Nothing else changes: same statements, same order."""
        for row in super()._discord_candidates(cur):
            cursor = (row[2].get('phase2') or {}).get(discord_worker.CURSOR) if isinstance(row[2], dict) else None
            until = cursor.get('quarantinedUntil') if isinstance(cursor, dict) else None
            if discord_worker.finite(until) and until > self.clock():
                continue
            self._examining = row[0]
            phase2 = row[2].get('phase2') if isinstance(row[2], dict) else None
            jobs = phase2.get('jobs') if isinstance(phase2, dict) else None
            self._before = {'workspace': row[0], 'cursor': copy.deepcopy(cursor),
                            'dispatched': {job['id']: job.get('lastDispatchedAt') for job in jobs
                                           if isinstance(job, dict) and 'id' in job} if isinstance(jobs, list) else {}}
            yield row
            self._examining = None  # only reached when the claim went on to the next candidate

    def claim(self, **options):
        """One workspace's unreadable document must not stop the lane (G2E-C-10).

        A job with `events: null` raised in the claim, rolling it back, and the cursor order (least recently served
        first) offered the same workspace first again: no other workspace was ever claimed. Here the failure is
        pinned on the workspace being read, that workspace is set aside (_quarantine) and the claim goes on to the
        next one. Only the unscoped Discord claim of the loop; anything else, and a failure that is not the shape of
        a document (a database error, a lost revision), is the inherited behaviour."""
        scoped = any(options.get(key) is not None for key in ('workspace_id', 'job_id', 'approval_digest', 'dispatch_principal'))
        if not options.get('discord_only') or scoped:
            return super().claim(**options)
        for attempt in range(MAX_QUARANTINES_PER_CLAIM + 1):
            self._examining = self._before = None
            try:
                selected = super().claim(**options)
                before = self._before
                if selected and not selected.get('reconciliation') and before and before['workspace'] == selected['workspaceId']:
                    selected['positionBefore'] = {'cursor': before['cursor'],
                                                  'lastDispatchedAt': before['dispatched'].get(selected['job'].get('id'))}
                return selected
            except SHAPE_ERRORS as error:
                workspace = self._examining
                if workspace is None or attempt == MAX_QUARANTINES_PER_CLAIM:
                    raise
                try:
                    self._quarantine(workspace, error)
                except Exception:
                    raise error from None  # it could not be set aside: the failure stays what it was

    def renew_discord_lease(self, claimed):
        """F5: the renewal after the preflight stays; there is no second one after the intent is sealed.

        _seal_discord_dispatch has just extended the lease to LEASE_SECONDS under the workspace lock, and consume()'s
        live guard (_authorize_discord_rate_send) rechecks the lease, cancellation, approval, role and grant under that
        lock, later than a second renewal could. The second renewal was one more whole-document transaction on the
        seal-to-consume path, where 83 percent of the permit expiries of the 5,000-post run happened. A lease or
        approval lost after the seal is caught by that guard instead: the permit is not consumed, no POST starts, the
        sealed intent stays, and the post ends uncertain (this method used to return False and end the step). Only
        once the guard exists: a sealed post without it (rate limits off, which the lane never runs with) renews."""
        if claimed.get('discordIntent') is not None and callable((claimed.get('discordDispatch') or {}).get('rateAuthorize')):
            return True
        return super().renew_discord_lease(claimed)

    def _discord_rate_released(self, state, job, claimed, now, *, scope, cause):
        """F2: a post released unsent because of the shared budget keeps its place in the queue.

        A claim stamps the post's lastDispatchedAt and the workspace's rotation cursor before the preflight, so a
        release used to send the post behind its never-claimed siblings and its workspace to the back of the round
        (median re-claim delay 729 s in the 5,000-post run, for the 25 percent of workspaces it hit). When the cause
        is system-wide (the application window was spent, or a create permit ended unused) both stamps are put back
        as the claim found them and the retry is due at once. Causes that are one tenant's resource (a learned or
        unknown route or channel window, an embargo, a provider 429), and a transient preflight, keep the penalty:
        otherwise workspaces sharing a full channel could take their turn over and over. At most
        MAX_POSITION_RESTORES times per post, whatever else bounds its retries. Ordering metadata only: no
        authorization, lease or intent changes."""
        before = claimed.get('positionBefore')
        if (not before or job.get('state') != 'scheduled' or not (scope == 'application' or cause == 'permit_expired')
                or job.get('discordPositionRestores', 0) >= MAX_POSITION_RESTORES):
            return
        phase2 = state['phase2']
        if before['cursor'] is None:
            phase2.pop(discord_worker.CURSOR, None)
        else:
            phase2[discord_worker.CURSOR] = copy.deepcopy(before['cursor'])
        if before['lastDispatchedAt'] is None:
            job.pop('lastDispatchedAt', None)
        else:
            job['lastDispatchedAt'] = before['lastDispatchedAt']
        job['nextAt'] = job[discord_worker.KEY]['rateDelayedUntil'] = now
        job['discordPositionRestores'] = job.get('discordPositionRestores', 0) + 1
        self.lane_counts['positionsKept'] += 1

    def _quarantine(self, workspace_id, error):
        """Put the workspace behind every other one for QUARANTINE_SECONDS: its rotation cursor is dated that far ahead
        and marked, in its own short transaction (the failed claim's has rolled back). Nothing else in the document
        changes, so a repaired document is claimed again by itself when the window ends. Counted; one log line, the
        exception class only: no workspace, job, channel, content or lease owner id."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (workspace_id,))
            row = cur.fetchone()
            if not row:
                return
            revision, raw = row
            state = json.loads(raw) if isinstance(raw, str) else raw
            until = self._db_now(cur) + QUARANTINE_SECONDS
            state['phase2'][discord_worker.CURSOR] = {'version': 1, 'lastClaimedAt': until, 'quarantinedUntil': until}
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                        (json.dumps(state), workspace_id, revision))
            if cur.rowcount != 1:
                raise AlphaError('Discord quarantine lost its workspace revision.', 409)
        self.discord_stats['quarantined'] += 1
        with _QUARANTINE_LOCK:
            _QUARANTINED[0] += 1
        logging.getLogger('postriff.request').warning(json.dumps({
            'event': 'discord.lane.quarantined', 'error': type(error).__name__, 'quarantineSeconds': QUARANTINE_SECONDS}))

    def complete(self, claimed, result):
        # What Discord did, counted before the inherited fenced write; that write decides the job's state.
        if isinstance(result, dict) and (claimed.get('job') or {}).get('manifest', {}).get('platform') == 'Discord':
            if claimed.get('reconciliation'):
                self.lane_counts['verified'] += result.get('state') == 'verified'
            else:
                evidence = result.get('discordDeliveryEvidence')
                self.lane_counts[{'accepted': 'posted', 'rejected': 'rejected',
                                  'not_sent': 'notSent'}.get(evidence, 'uncertainCreates')] += 1
        return super().complete(claimed, result)


def _discord(social):
    providers = getattr(social, 'providers', None)
    return providers.get('discord') if isinstance(providers, dict) else None


def blocker(social, now, values=None, *, process_state=True):
    """Why the lane cannot run at `now` (epoch seconds), or None when it can.

    The one readiness test, in two scopes. The static causes (a bad lane budget, rate limits off, no coordinator or
    policy, a policy not valid at `now`) stop the lane in every process. process_state=True, the default, adds this
    process's own coordinator state (a lost observation): the lane asks that full rule before every claim (process
    clock, then the database clock the coordinator itself refuses by), so a degraded process stops its own loops.
    tick() asks process_state=False: a coordinator degraded only in the minute cron's process cannot send there either,
    so the tick still leaves Discord to the lane loops of healthy processes. Pure: no database, network or clock of
    its own; it reads the given environment (the lane budget, as the shard route does), this process's Discord
    provider and `now`. It cannot see whether the shard crons fire at all; warn_if_lagging covers that.
    """
    try:
        limits(values)
    except AlphaError:
        return 'configuration'  # every shard answers 503 discord_lane_configuration and claims nothing
    provider = _discord(social)
    limiter = getattr(provider, 'rate_limiter', None)
    policy = getattr(limiter, 'policy', None)
    if provider is None or not getattr(provider, 'rate_v1_enabled', False) or limiter is None or policy is None:
        # POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED off, or no shared coordinator with a reviewed policy.
        return 'coordinator_unavailable'
    if process_state and getattr(provider, 'rate_coordinator_degraded', False):
        # This process lost track of an observation; every later request here is refused before transport.
        return 'coordinator_degraded'
    if not discord_worker.finite(now) or not policy.issued_at <= now < policy.expires_at:
        return 'coordinator_unavailable'  # outside the reviewed policy's validity: the coordinator refuses everything
    return None


def status(social, now, values=None):
    """This process's lane health at `now`: a stable, documented shape (version 1) for the minute cron's report, the
    shard answers and a protected health route. Pure and cheap: no database, network or secret; codes, numbers and
    booleans only.

    enabled: the flag and the lease protocol (enabled()). ready: the lane runs here now. blocker: why not, the full
    rule for this process ('disabled', 'configuration', 'coordinator_unavailable', 'coordinator_degraded'), or None.
    maxSeconds, maxSteps: the invocation budget after clamping, None when misconfigured. shards: the cron entries.
    policyDaysLeft: days until the reviewed policy expires (negative once expired, two decimals), None when no policy
    is visible to the caller. quarantined: workspaces this process has set aside since it started because the claim
    could not read their document (LaneWorker.claim); a count, never an identifier.
    """
    values = os.environ if values is None else values
    on = enabled(values)
    try:
        seconds, steps = limits(values)
    except AlphaError:
        seconds = steps = None
    reason = blocker(social, now, values) if on else 'disabled'
    policy = getattr(getattr(_discord(social), 'rate_limiter', None), 'policy', None)
    days = round((policy.expires_at - now) / 86400, 2) if policy is not None and discord_worker.finite(now) else None
    return {'version': 1, 'enabled': on, 'ready': reason is None, 'blocker': reason, 'maxSeconds': seconds,
            'maxSteps': steps, 'shards': SHARDS, 'policyDaysLeft': days, 'quarantined': quarantined()}


_NOT_READ = object()


def projected_lag(worker):
    """How long the oldest due Discord work in the projection has waited, in seconds (0.0 when none is overdue), or
    None when the projection cannot be read. Every workspace, in one indexed statement (the shards' due probe).
    Never raises: a monitoring read cannot fail the minute cron."""
    try:
        with worker.connection_factory() as db, db.cursor() as cur:
            cur.execute(_SOONEST)
            now, soonest = cur.fetchone()
    except Exception:
        return None
    if not discord_worker.finite(now):
        return None
    return 0.0 if soonest is None else max(0.0, now - soonest)


def warn_if_lagging(result, reason=None, projected=_NOT_READ):
    """One WARNING, discord.lane.lagging, when due Discord work has waited longer than the threshold, or when the
    tick could not see its Discord queue.

    tick() calls it whenever the flag is on, with the readiness verdict it acted on and, when the lane owns Discord,
    the projection's lag (projected_lag(): every workspace). The tick's own report (discordWorker.queue) samples only
    the first 256 workspaces, so it alone cannot see lagging work beyond them, and when that report fails its status
    is 'unavailable'. It warns when either lag passes the threshold, when the report is unavailable, or when the lane
    owns Discord and the projection cannot be read; the line says which. Counts and codes only. Returns whether it
    warned.
    """
    report = result.get('discordWorker') if isinstance(result, dict) else None
    queue = report.get('queue') if isinstance(report, dict) else None
    queue = queue if isinstance(queue, dict) else {}
    sampled = queue.get('oldestEligibleLagSeconds')
    sampled = sampled if discord_worker.finite(sampled) else None
    read = projected is not _NOT_READ
    projected = projected if read and discord_worker.finite(projected) else None
    unavailable = queue.get('status') == 'unavailable'
    lags = [lag for lag in (sampled, projected) if lag is not None]
    if not (lags and max(lags) > LAG_WARNING_SECONDS or unavailable or read and projected is None):
        return False
    counts = {key: queue[key] for key in ('depth', 'held', 'uncertain', 'deadLetters') if type(queue.get(key)) is int}
    # No workspace, job, channel, content, credential or lease owner id.
    logging.getLogger('postriff.request').warning(json.dumps({
        'event': 'discord.lane.lagging',
        'oldestEligibleLagSeconds': None if sampled is None else round(sampled, 1),
        'projectedLagSeconds': None if projected is None else round(projected, 1),
        'thresholdSeconds': LAG_WARNING_SECONDS,
        'report': 'unavailable' if unavailable else 'sample',
        'projection': ('unreadable' if projected is None else 'read') if read else 'not_read',
        'laneOwnsDiscord': reason is None, 'laneBlocker': reason, **counts}))
    return True


def outlook(lane):
    """(blocker or None, seconds to wait) from blocker() and the coordinator's own rows, read without locks.

    Advisory only: every request is still admitted, or refused, by the coordinator itself. The scope keys come from
    the coordinator's own derivation, so this read and its reservations look at the same rows.
    """
    values = getattr(lane, 'environment', None)
    reason = blocker(lane.social, lane.clock(), values)
    if reason:
        return reason, 0.0
    provider = _discord(lane.social)
    marker = '0' * 64
    keys = sorted(key for key in provider.rate_limiter._keys(provider._rate_identity('bot'), marker, marker, marker)
                  if key[:3] in _GUARDS)
    with lane.connection_factory() as db, db.cursor() as cur:
        cur.execute(_OUTLOOK, (keys,))
        rows = cur.fetchall()
    now = rows[0][0] if rows else None
    reason = blocker(lane.social, now, values)  # at a policy's edges the coordinator's clock decides
    if reason:
        return reason, 0.0
    wait = 0.0
    for _, key, kind, hold, remaining, reset, blocked, circuit in rows:
        if key is None:
            continue
        if hold:
            # The runbook's kill switch is the policy row; the coordinator itself holds the credential row after a 401.
            return ('operator_hold' if kind == 'policy' else 'coordinator_hold'), 0.0
        wait = max(wait, (blocked or 0) - now, (circuit or 0) - now)
        # Like the coordinator's _reserve: every capped row with nothing left refuses until its reset, the application
        # policy and the invalid-request budget alike (remaining is NULL exactly on the uncapped rows; migration 124).
        if remaining is not None and remaining <= 0 and reset is not None:
            wait = max(wait, reset - now)
    return None, wait


def soonest_due(lane):
    """Seconds until the soonest due Discord work the loop can claim (negative when overdue), or None."""
    with lane.connection_factory() as db, db.cursor() as cur:
        cur.execute(_CLAIMABLE)
        now, soonest = cur.fetchone()
    return None if soonest is None or not discord_worker.finite(now) else soonest - now


def _projection_ready(lane):
    """Whether this invocation's loop starts (True) or why not: blocker()'s reason, False when the projection table
    (migration 126) is missing, or 'idle'. It replaced a bare schema check, hence the name.

    A shard that cannot run opens no connection; an idle one opens one, for one statement. First blocker() on this
    process's clock, pure as before, so a broken configuration still ends every invocation with its WARNING. Then
    one statement: the database clock and the soonest next_at in the projection. The loop claims only through
    due_workspaces_sql on that projection (a row whose next_at has passed), so when nothing is due within the idle
    horizon it could claim nothing: it stops as idle before the coordinator read (outlook) and before any claim,
    which is where it stopped before, one claim miss and two queries later. Otherwise the loop runs exactly as
    before. The second blocker() is outlook()'s: at a policy's edges the coordinator's own clock decides.
    """
    values = getattr(lane, 'environment', None)
    reason = blocker(lane.social, lane.clock(), values)
    if reason:
        return reason
    try:
        with lane.connection_factory() as db, db.cursor() as cur:
            cur.execute(_CLAIMABLE)
            now, soonest = cur.fetchone()
    except Exception as error:
        if getattr(error, 'sqlstate', None) == '42P01' or type(error).__name__ == 'UndefinedTable':
            return False
        raise
    reason = blocker(lane.social, now, values)
    if reason:
        return reason
    if soonest is None or soonest - now > IDLE_HORIZON_SECONDS:
        return 'idle'
    return True


def run(worker, number, values=None, *, started=None, request_id=None, sleep=time.sleep, monotonic=time.monotonic,
        rng=None):
    """One bounded loop. `started` is the request's own start, so cold-start setup counts against the budget."""
    values = os.environ if values is None else values
    if not enabled(values):
        return disabled(number, values)
    seconds, max_steps = limits(values)
    started = monotonic() if started is None else started
    deadline = started + seconds
    rng = rng or random.Random()
    lane = LaneWorker(worker, number, sleep=sleep, monotonic=monotonic, values=values)
    counts = dict.fromkeys(COUNTERS, 0)
    waited = {'rate': 0.0, 'idle': 0.0}
    stopped, error, misses = None, None, 0
    try:
        ready = _projection_ready(lane)
        if ready is not True:
            stopped = ready or 'schema'
        while stopped is None:
            remaining = deadline - monotonic()
            if lane._stopping:
                stopped = 'shutdown'
            elif counts['steps'] >= max_steps:
                stopped = 'step_budget'
            elif remaining <= 0:
                stopped = 'time_budget'
            if stopped:
                break
            blocker, wait = outlook(lane)
            if blocker:
                stopped = blocker
                break
            if wait > 0:
                pause = wait * (1 + .2 * rng.random()) + .01
                if pause >= remaining:
                    stopped = 'rate_wait'
                    break
                counts['rateWaits'] += 1
                waited['rate'] += pause
                sleep(pause)
                continue
            counts['steps'] += 1
            if lane.step(discord_only=True):
                misses = 0
                continue
            misses += 1
            due = soonest_due(lane)
            if due is None or due > IDLE_HORIZON_SECONDS or misses > MAX_IDLE_MISSES:
                stopped = 'idle'
                break
            # Overdue but not claimable: another loop holds that workspace, or its work is not this worker's.
            pause = max(due, min(1.0, .05 * 2 ** misses)) * (1 + .2 * rng.random())
            if pause >= deadline - monotonic():
                stopped = 'idle'
                break
            counts['idleWaits'] += 1
            waited['idle'] += pause
            sleep(pause)
    except BaseException as caught:
        stopped, error = 'error', type(caught).__name__
        raise
    finally:
        stats = lane.discord_stats
        counts.update(claimed=stats['claims'], held=stats['held'], uncertain=stats['uncertain'],
                      rateDelayed=stats['rateDelays'], leaseLost=stats['leaseLost'], recoveries=stats['recoveries'],
                      retries=stats['retries'], deadLetters=stats['deadLetters'], claimMisses=stats['claimMisses'],
                      permitWaits=lane.social.permit_waits, quarantined=stats['quarantined'], **lane.lane_counts)
        result = {'version': 1, 'lane': 'discord', 'enabled': True, 'shard': number, 'stoppedBy': stopped,
                  'elapsedSeconds': round(monotonic() - started, 3), 'processed': counts['claimed'],
                  'budget': {'maxSeconds': seconds, 'maxSteps': max_steps}, 'counters': counts,
                  'waitedSeconds': {key: round(value, 3) for key, value in waited.items()},
                  'status': status(lane.social, lane.clock(), values),  # as the invocation ends
                  **({'error': error} if error else {})}
        # Counts and reasons only: no workspace, job, channel, content or credential.
        quiet = stopped in ('time_budget', 'step_budget', 'idle', 'rate_wait', 'operator_hold')
        logging.getLogger('postriff.request').log(logging.INFO if quiet else logging.WARNING,
                                                  json.dumps({'event': 'discord.lane.completed',
                                                              'requestId': request_id, **result}))
    return result
