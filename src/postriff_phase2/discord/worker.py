"""Discord lease policy for the existing hosted worker; no IO or separate queue.

Only a versioned, fenced pre-handoff marker proves that an abandoned operation
was unsent. Any intent or provider evidence always wins over that marker.
"""
import hashlib
import math
import os

KEY = 'discordWorker'
CURSOR = 'discordWorkerCursor'
VERSION = 1
LEASE_SECONDS = 45
MAX_UNSENT_ATTEMPTS = 3
MAX_UNCONSUMED_PERMIT_RECOVERIES = 8
MAX_CANDIDATES = 8
# A paused Discord (execution disabled, authorization or rate limits off) is a wait, not a verdict about a post: it is
# released unsent for this long and asked again (K1).
PAUSED_RETRY_SECONDS = 60
QUEUE_WORKSPACE_LIMIT = 256


def enabled(values=None):
    values = os.environ if values is None else values
    return values.get('POSTRIFF_DISCORD_WORKER_V1_ENABLED', '').lower() in ('1', 'true')


def managed(job):
    return (job.get('manifest', {}).get('platform') == 'Discord'
            and isinstance(job.get(KEY), dict) and job[KEY].get('version') == VERSION)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def owns(job, claimed, worker_id, now):
    original = claimed.get('job') or {}
    workspace = claimed.get('workspaceId')
    return bool(managed(job) and finite(now) and finite(job.get('leaseUntil'))
                and job['leaseUntil'] > now and workspace
                and job.get('manifest', {}).get('workspaceId') == workspace
                and original.get('manifest', {}).get('workspaceId') == workspace
                and job.get('id') == original.get('id')
                and job.get('approvalDigest') == original.get('approvalDigest')
                and job.get('leaseOwner') == worker_id
                and job.get('leaseId') and job['leaseId'] == original.get('leaseId')
                and job[KEY].get('leaseId') == job['leaseId']
                and job[KEY].get('publicationId') == job['id']
                and job[KEY].get('approvalDigest') == job.get('approvalDigest'))


def has_effect(job):
    # discordUnsentDispatches is an archive of transactionally blocked, never
    # consumed admissions. Active/ambiguous intents and receipts still win.
    return any(job.get(key) for key in (
        'discordDispatchIntents', 'discordReceipts', 'providerReference', 'container',
        'providerUpload', 'providerAssets', 'providerThread', 'progress', 'url', 'verification'))


def pending_unsent(job):
    operation = job.get(KEY) or {}
    return bool(managed(job) and operation.get('stage') == 'pending'
                and operation.get('leaseId') and operation['leaseId'] == job.get('leaseId')
                and operation.get('publicationId') == job.get('id')
                and operation.get('approvalDigest') == job.get('approvalDigest')
                and not has_effect(job)
                and not any(a.get('discordIntentId') for a in job.get('attempts', [])))


def recovery(job, now):
    if (not managed(job) or not finite(now) or not finite(job.get('leaseUntil'))
            or job['leaseUntil'] > now or job.get('state') not in ('claimed', 'submitting')):
        return None
    return 'unsent' if pending_unsent(job) else 'reconcile'


def in_flight(jobs, now, excluding=None):
    return any(j.get('id') != excluding and j.get('manifest', {}).get('platform') == 'Discord'
               and j.get('leaseOwner') and finite(j.get('leaseUntil')) and j['leaseUntil'] > now
               for j in jobs)


def begin(job, now, reconciliation):
    prior = job.get(KEY) if managed(job) else {}
    job[KEY] = {'version': VERSION, 'publicationId': job['id'], 'approvalDigest': job['approvalDigest'],
                'leaseId': job['leaseId'], 'claimedAt': now,
                'stage': 'reconcile' if reconciliation else 'pending',
                **{key: prior.get(key, 0) for key in ('unsentFailures', 'recoveries', 'renewals','rateReadRetries','ratePermitRetries')}}


def attempt_count(job):
    # A graceful release never spent a provider attempt; retain its audit record.
    return sum(a.get('unsentReason') not in ('shutdown', 'rate_delayed') for a in job.get('attempts', []))


def retry_delay(job):
    failures = max(1, min(MAX_UNSENT_ATTEMPTS, int(job.get(KEY, {}).get('unsentFailures', 1))))
    base = min(60, 5 * 2 ** (failures - 1))
    seed = hashlib.sha256((str(job['id']) + ':' + str(job.get('leaseId'))).encode()).digest()
    return base * (.75 + int.from_bytes(seed[:2], 'big') / 65535 * .5)


def release_unsent(job, now, reason, *, retry_after_seconds=None):
    """Release only proven-unsent work; a rate pause never consumes an attempt."""
    if reason not in ('preflight_transient', 'lease_expired', 'shutdown', 'rate_delayed') or not pending_unsent(job):
        raise ValueError('Only a proven unsent fenced operation can be released.')
    operation = job[KEY]
    if reason not in ('shutdown', 'rate_delayed'):
        operation['unsentFailures'] += 1
    if reason == 'lease_expired':
        operation['recoveries'] += 1
    if job.get('attempts'):
        job['attempts'][-1].update(endedAt=now, unsentReason=reason)
    exhausted = reason not in ('shutdown', 'rate_delayed') and (
        operation['unsentFailures'] >= MAX_UNSENT_ATTEMPTS or attempt_count(job) >= MAX_UNSENT_ATTEMPTS)
    operation.update(stage='released', releasedAt=now, releaseReason=reason)
    job['leaseOwner'], job['leaseUntil'] = None, 0
    job['state'] = 'failed' if exhausted else 'scheduled'
    if reason == 'rate_delayed':
        cooldown = (max(.001, float(retry_after_seconds))
                    if finite(retry_after_seconds) else 300.0)
        job['nextAt'] = now + cooldown
        operation['rateDelayedUntil'] = job['nextAt']
        # A rate wait is not permission to extend approval. Hold it when the
        # provider's deadline reaches/passes that approval, preserving both.
        if job['nextAt'] >= job['manifest']['expiresAt']:
            job['state'] = 'held'
    else:
        job['nextAt'] = now + (1 if reason == 'shutdown' else retry_delay(job))
    if exhausted:
        operation['deadLetter'] = {'at': now, 'reason': 'pre_handoff_exhausted',
                                   'attempts': attempt_count(job)}
    job['nextAction'] = ('Discord rate wait outlasts approval; review the frozen destination and approve again'
                         if reason == 'rate_delayed' and job['state'] == 'held' else
                         'Await Discord shared rate budget; no POST occurred and this approval remains frozen'
                         if reason == 'rate_delayed' else
                         'Correct the pre-handoff failure and create a new exact approval' if exhausted else
                         'Await unsent backoff; the same frozen destination and approval must remain valid')
    return job['state']


def transient_preflight(error):
    # This classification is used ONLY before a durable intent, never for POST.
    from postriff_alpha.domain import AlphaError
    return (isinstance(error, (TimeoutError, ConnectionError))
            or isinstance(error, AlphaError) and (error.status == 429 or 500 <= error.status <= 599))
