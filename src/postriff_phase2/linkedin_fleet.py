"""Opt-in bounded production LinkedIn workers. Existing approvals remain authority.

No capability, token, quota or approval is invented by enabling concurrency.
Provider 429 backoff, immutable approval expiry, tenant locks and dispatch fences
are the same PostgresWorker path as interactive execution.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from postriff_alpha.domain import AlphaError
from .hosted_worker import PostgresWorker


def configuration(values=None):
    values = os.environ if values is None else values
    if str(values.get('POSTRIFF_LINKEDIN_FLEET_ENABLED', '')).lower() != 'true':
        return {'enabled': False, 'workers': 0, 'maxJobs': 0, 'maxSeconds': 0}
    fields = [('WORKERS', 8, 1, 8), ('MAX_JOBS', 25, 1, 25), ('MAX_SECONDS', 45, 1, 45)]
    parsed = []
    for name, default, minimum, maximum in fields:
        raw = values.get('POSTRIFF_LINKEDIN_FLEET_' + name, default)
        try:
            if isinstance(raw, bool) or not str(raw).isdigit():
                raise ValueError
            number = int(raw)
            if not minimum <= number <= maximum:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise AlphaError('LinkedIn fleet limits are invalid; dispatch is paused.', 503, code='linkedin_fleet_configuration') from None
        parsed.append(number)
    return dict(enabled=True, workers=parsed[0], maxJobs=parsed[1], maxSeconds=parsed[2])


def tick(base_worker, values=None):
    config = configuration(values)
    if not config['enabled']:
        return {'enabled': False, 'processed': 0, 'externalExecution': False}
    provider = getattr(base_worker.social, 'providers', {}).get('linkedin')
    if (not provider or not getattr(provider, 'execution_enabled', True)
            or not getattr(provider, 'member_publishing_approved', lambda: False)()):
        return {'enabled': True, 'processed': 0, 'externalExecution': False, 'state': 'provider_access_unavailable', 'budget': config}
    def run(_):
        worker = PostgresWorker(base_worker.connection_factory, social=base_worker.social,
                                clock=base_worker.clock, worker_binding=base_worker.worker_binding,
                                on_verified=base_worker.on_verified)
        try:
            return worker.tick_linkedin(config['maxJobs'], config['maxSeconds'])
        except Exception as error:
            # Unknown effects are never resubmitted here. A next invocation must
            # reconcile the persisted lease/intent through the normal worker.
            return {'processed': 0, 'state': 'worker_error', 'errorType': type(error).__name__}
    with ThreadPoolExecutor(max_workers=config['workers'], thread_name_prefix='rafii-linkedin') as pool:
        results = list(pool.map(run, range(config['workers'])))
    return {'enabled': True, 'processed': sum(item['processed'] for item in results),
            'execution': 'bounded-linkedin-fleet', 'budget': config,
            'errors': [item['errorType'] for item in results if item.get('errorType')],
            'workers': results}
