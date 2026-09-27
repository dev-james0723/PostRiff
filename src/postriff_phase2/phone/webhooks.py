"""Signed, provider-bound status events. Raw provider payloads are discarded."""
from postriff_alpha.domain import AlphaError

from . import contracts, store


def apply(service, call_id, url, parameters, signature):
    provider = service.provider
    if not provider or not provider.verify_webhook(url, parameters, signature):
        raise AlphaError('Invalid phone webhook signature.', 401, code='phone_signature')
    try:
        event = provider.normalize_event(parameters)
    except (ValueError,KeyError,TypeError):
        raise AlphaError('Invalid phone event.',400) from None
    if event.state not in contracts.STATES or not event.call_ref or not 1 <= len(event.event_id) <= 200:
        raise AlphaError('Invalid phone event.', 400)
    duration = event.duration_seconds
    if duration is not None and (type(duration) is not int or not 0 <= duration <= 86400):
        raise AlphaError('Invalid phone duration.', 400)
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id, lock=True)
        if not value or value['provider'] != provider.name or (value['provider_call_ref'] and value['provider_call_ref'] != event.call_ref):
            raise AlphaError('Call unavailable.', 404)
        cur.execute('INSERT INTO public.pr_phone_provider_events(provider,event_id,call_id,state) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id',
                    (provider.name, event.event_id, call_id, event.state))
        if not cur.fetchone():
            return {'duplicate': True}
        cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=coalesce(provider_call_ref,%s) WHERE id=%s', (event.call_ref, call_id))
        if event.state not in contracts.TERMINAL:
            store.set_state(cur, value, event.state, duration)
        db.commit()
    if event.state in contracts.TERMINAL:
        service.finish(call_id, event.state, duration)
    return {'applied': True}
