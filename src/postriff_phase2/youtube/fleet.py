"""Isolated, opt-in YouTube lanes. This module provisions no scheduler or runtime.

The request ceiling counts YouTube API admissions (and a conservative WebSub
renewal slot); OAuth refresh transport retains its own existing timeout. Budgets
stop starting new requests, not an already-running network call.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import os
import time

from postriff_alpha.domain import AlphaError
from .model import YouTubeError

_BUDGET = ContextVar('youtube_fleet_budget', default=None)
LANES = ('upload', 'identity', 'planner')


def enabled(environ=None):
    values = os.environ if environ is None else environ
    return values.get('POSTRIFF_YOUTUBE_FLEET_ENABLED') == '1' and values.get('POSTRIFF_YOUTUBE_CREATOR_ENABLED') == '1'


@dataclass(frozen=True)
class Limits:
    items: int
    seconds: float
    requests: int


def limits(lane, environ=None):
    if lane not in LANES:
        raise AlphaError('Unknown YouTube worker lane.', 404, code='not_found')
    values = os.environ if environ is None else environ
    prefix = 'POSTRIFF_YOUTUBE_FLEET_' + lane.upper()
    try:
        result = Limits(int(values.get(prefix + '_MAX_ITEMS', 10)), float(values.get(prefix + '_MAX_SECONDS', 20)),
                        int(values.get(prefix + '_MAX_REQUESTS', 60)))
    except (ValueError, TypeError, OverflowError):
        raise AlphaError('Invalid YouTube fleet budget.', 503, code='youtube_fleet_configuration') from None
    if not 1 <= result.items <= 25 or not math.isfinite(result.seconds) or not 1 <= result.seconds <= 45 or not 1 <= result.requests <= 200:
        raise AlphaError('Use one to 25 items, one to 45 seconds, and one to 200 API requests.', 503,
                         code='youtube_fleet_configuration')
    return result


@dataclass
class Budget:
    limit: Limits
    started: float
    requests: int = 0

    def available(self):
        return self.requests < self.limit.requests and time.monotonic() - self.started < self.limit.seconds


@contextmanager
def request_budget(configured):
    budget = Budget(configured, time.monotonic())
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def before_request():
    """Called before normal project admission, never an authorization substitute."""
    budget = _BUDGET.get()
    if budget is None:
        return
    if not budget.available():
        error = YouTubeError('capacity_delay', 'This bounded worker invocation used its API/time budget. The same operation resumes later.',
                             status=429, retryable=True, retry_at=time.time() + 5)
        error.capacity_reason = 'fleet_budget'
        raise error
    budget.requests += 1


def claim_planner(agent, excluded=()):
    """Claim-only seam; no OAuth/provider invocation or publication authority."""
    return agent._select_candidate(fleet=True, exclude_workspaces=excluded)


def release_planner(agent, candidate):
    """A stale/crashed worker cannot clear a newer worker's lease."""
    with agent.service.connection_factory() as db, db.cursor() as cur:
        cur.execute("""UPDATE public.pr_workspaces SET state=state#-'{youtubeAgent,fleetLease}',revision=revision+1
            WHERE id=%s AND state#>>'{youtubeAgent,fleetLease,id}'=%s""", (candidate[0], candidate[4]))


def run_lane(service, worker, lane, environ=None):
    """Server configuration only; caller authenticates CRON_SECRET before runtime creation."""
    values = os.environ if environ is None else environ
    if lane not in LANES:
        raise AlphaError('Unknown YouTube worker lane.', 404, code='not_found')
    if not enabled(values) or (lane == 'planner' and values.get('POSTRIFF_YOUTUBE_AGENTIC_ENABLED') != '1'):
        return {'enabled': False, 'lane': lane, 'processed': 0, 'providerVerified': False}
    configured = limits(lane, values)
    creator = getattr(service, 'youtube', None)
    provider = getattr(getattr(creator, 'oauth', None), 'providers', {}).get('youtube')
    if not creator or not provider or not getattr(provider, 'creator_enabled', False):
        return {'enabled': False, 'lane': lane, 'processed': 0, 'providerVerified': False, 'blocker': 'youtube_creator_unavailable'}
    if not creator.fleet_schema_ready():
        return {'enabled': False, 'lane': lane, 'processed': 0, 'providerVerified': False, 'blocker': 'youtube_schema_089_097_required'}
    result = {'enabled': True, 'lane': lane, 'processed': 0, 'providerVerified': False,
              'budget': {'maxItems': configured.items, 'maxSeconds': configured.seconds, 'maxApiRequests': configured.requests}}
    with request_budget(configured) as budget:
        if lane == 'upload':
            receipt = worker.tick_youtube(configured.items, configured.seconds)
            result.update(processed=receipt['processed'], capacityIntervention=receipt.get('capacityIntervention'))
        else:
            seen, verified, dispatched, interventions = set(), 0, 0, 0
            while result['processed'] < configured.items and budget.available():
                if lane == 'identity':
                    receipt = creator.identity_one(excluded=tuple(seen))
                    selection = receipt.get('_selection')
                    if not receipt.get('selected') or not selection:
                        break
                    selection = tuple(selection)
                    verified += int(bool(receipt.get('authorizationChecked')))
                    interventions += int(bool(receipt.get('reconnectionRequired')))
                else:
                    receipt = creator.agent.dispatch_one(fleet=True, exclude_workspaces=tuple(seen))
                    selection = receipt.get('_workspace')
                    if not selection:
                        break
                    dispatched += int(bool(receipt.get('dispatched')))
                    interventions += int(bool(receipt.get('interventionRequired')))
                if selection in seen:
                    raise AlphaError('The fleet selector repeated an invocation claim.', 503, code='youtube_fleet_selection')
                seen.add(selection)
                result['processed'] += 1
            if lane == 'identity':
                result.update(identitiesVerified=verified, interventions=interventions, notificationLeaseRenewed=False)
                if budget.available():
                    try:
                        before_request()
                        result['notificationLeaseRenewed'] = bool(creator.notifications.renew_one())
                    except AlphaError:
                        pass
            else:
                result.update(plansQueued=dispatched, interventions=interventions)
        result['apiAdmissionAttempts'] = budget.requests
        result['budgetExhausted'] = not budget.available()
    return result
