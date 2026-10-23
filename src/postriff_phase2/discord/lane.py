"""W-02 parallel Discord lane. Default off; no schema, queue, lock or scheduler of its own.

Cron shards call /api/cron/discord-worker/<shard> every minute (vercel.json). Each invocation runs ONE bounded loop of
the existing Discord-only worker step under its own lease owner id: workspace rows are claimed FOR UPDATE SKIP LOCKED,
one job per claim and at most one live Discord lease per workspace, the lease owner and lease id are rechecked at every
step, every Discord request is admitted by the shared PostgreSQL coordinator, and an intent is sealed before any POST.
Loops may overlap each other, the existing /api/cron/worker (which leaves Discord to this lane only while the flag is
on and blocker() says the lane can run in its process; otherwise it keeps the frozen Discord path) and a person's own
"post now" nudge. That overlap is safe by the lease protocol; keeping Discord to one scheduler is a preference.

The loop only adds waiting. Before each claim it reads the coordinator's application-wide rows without locks: an
operator hold (manual_hold) stops it, an embargo or a spent window is slept out instead of claiming work that cannot
be sent, and it stops when no work is due soon. It never extends an approval, a lease or a permit, never retries a
create, and stops admitting steps early enough that the last one ends inside the function's time limit.
"""
import json
import logging
import math
import os
import random
import re
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
# that cannot keep up with a burst, or a minute tick that kept Discord because the lane could not run in its process.
LAG_WARNING_SECONDS = 300
_SHARD = re.compile(r'^(0|[1-9][0-9]?)$')
_GUARDS = ('00:', '10:', '11:', '20:')  # application policy, bot global, bot credential, invalid-request budget
_OUTLOOK = '''WITH observed AS (SELECT extract(epoch from clock_timestamp())::double precision AS at)
    SELECT observed.at,r.scope_key,r.kind,r.manual_hold,r.remaining,extract(epoch from r.reset_at)::double precision,
        extract(epoch from r.blocked_until)::double precision,extract(epoch from r.circuit_until)::double precision
    FROM observed LEFT JOIN public.pr_discord_rate_state r ON r.scope_key=ANY(%s::text[])'''
_SOONEST = '''SELECT extract(epoch from clock_timestamp())::double precision,min(next_at)
    FROM public.pr_discord_worker_projection WHERE next_at IS NOT NULL'''
COUNTERS = ('steps', 'claimed', 'posted', 'verified', 'held', 'uncertain', 'rateDelayed', 'leaseLost', 'recoveries',
            'retries', 'deadLetters', 'claimMisses', 'rejected', 'notSent', 'uncertainCreates', 'rateWaits', 'idleWaits',
            'permitWaits')


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


def disabled(number):
    return {'version': 1, 'lane': 'discord', 'enabled': False, 'shard': number, 'processed': 0}


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
        self.lane_counts = dict.fromkeys(('posted', 'verified', 'rejected', 'notSent', 'uncertainCreates'), 0)

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


def blocker(social, now, values=None):
    """Why the lane cannot run in this process at `now` (epoch seconds), or None when it can.

    The one readiness test. tick() asks it (process clock) before it leaves Discord to the lane, and every lane
    iteration asks it before claiming (process clock, then the database clock the coordinator itself refuses by), so
    the minute worker never hands Discord to loops that would refuse to run. Pure: no database, network or clock of
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
    if getattr(provider, 'rate_coordinator_degraded', False):
        # This process lost track of an observation; every later request here is refused before transport.
        return 'coordinator_degraded'
    if not discord_worker.finite(now) or not policy.issued_at <= now < policy.expires_at:
        return 'coordinator_unavailable'  # outside the reviewed policy's validity: the coordinator refuses everything
    return None


def warn_if_lagging(result, reason=None):
    """One WARNING, discord.lane.lagging, when this tick's Discord report shows due work later than the threshold.

    tick() calls it whenever the flag is on, with the readiness verdict it acted on. It reads only the report the tick
    already made (discordWorker.queue, the existing sample of at most 256 workspaces), so it adds no query, and it
    logs counts and codes only. Returns whether it warned.
    """
    report = result.get('discordWorker') if isinstance(result, dict) else None
    queue = report.get('queue') if isinstance(report, dict) else None
    lag = queue.get('oldestEligibleLagSeconds') if isinstance(queue, dict) else None
    if not discord_worker.finite(lag) or lag <= LAG_WARNING_SECONDS:
        return False
    counts = {key: queue[key] for key in ('depth', 'held', 'uncertain', 'deadLetters') if type(queue.get(key)) is int}
    # No workspace, job, channel, content, credential or lease owner id.
    logging.getLogger('postriff.request').warning(json.dumps({
        'event': 'discord.lane.lagging', 'oldestEligibleLagSeconds': round(lag, 1),
        'thresholdSeconds': LAG_WARNING_SECONDS, 'laneOwnsDiscord': reason is None, 'laneBlocker': reason, **counts}))
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
    """Seconds until the soonest due Discord work in the projection (negative when overdue), or None."""
    with lane.connection_factory() as db, db.cursor() as cur:
        cur.execute(_SOONEST)
        now, soonest = cur.fetchone()
    return None if soonest is None or not discord_worker.finite(now) else soonest - now


def _projection_ready(lane):
    with lane.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_discord_worker_projection')")
        return cur.fetchone()[0] is not None


def run(worker, number, values=None, *, started=None, request_id=None, sleep=time.sleep, monotonic=time.monotonic,
        rng=None):
    """One bounded loop. `started` is the request's own start, so cold-start setup counts against the budget."""
    values = os.environ if values is None else values
    if not enabled(values):
        return disabled(number)
    seconds, max_steps = limits(values)
    started = monotonic() if started is None else started
    deadline = started + seconds
    rng = rng or random.Random()
    lane = LaneWorker(worker, number, sleep=sleep, monotonic=monotonic, values=values)
    counts = dict.fromkeys(COUNTERS, 0)
    waited = {'rate': 0.0, 'idle': 0.0}
    stopped, error, misses = None, None, 0
    try:
        if not _projection_ready(lane):
            stopped = 'schema'
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
                      permitWaits=lane.social.permit_waits, **lane.lane_counts)
        result = {'version': 1, 'lane': 'discord', 'enabled': True, 'shard': number, 'stoppedBy': stopped,
                  'elapsedSeconds': round(monotonic() - started, 3), 'processed': counts['claimed'],
                  'budget': {'maxSeconds': seconds, 'maxSteps': max_steps}, 'counters': counts,
                  'waitedSeconds': {key: round(value, 3) for key, value in waited.items()},
                  **({'error': error} if error else {})}
        # Counts and reasons only: no workspace, job, channel, content or credential.
        quiet = stopped in ('time_budget', 'step_budget', 'idle', 'rate_wait', 'operator_hold')
        logging.getLogger('postriff.request').log(logging.INFO if quiet else logging.WARNING,
                                                  json.dumps({'event': 'discord.lane.completed',
                                                              'requestId': request_id, **result}))
    return result
