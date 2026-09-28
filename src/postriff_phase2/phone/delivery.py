"""Phone egress: one committed claim, one request. Lost results are reconciled, never redialed."""
from postriff_alpha.domain import AlphaError

from ..permissions import Membership
from . import billing, contracts, planner, store


def deliver(service, call_id):
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id, lock=True)
        if not value or value['state'] != 'requested' or value.get('direction') == 'inbound':
            return
        service._lock(cur, value['user_id'])
        identity = store.number(cur, value['user_id'])
        prefs = store.prefs(cur, value['user_id'], value['workspace_id'])
        cur.execute('SELECT role,can_publish,can_reply,can_moderate,can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id '
                    'WHERE workspace_id=%s AND m.user_id=%s AND m.status=\'active\' AND p.deleted_at IS NULL', (value['workspace_id'], value['user_id']))
        member = cur.fetchone()
        route = service.agent().cfg.route('voice_front_end', reason='phone delivery')
        start = planner.day_start(service.clock(), prefs['timeZone'])
        cur.execute(f'SELECT count(*) FILTER(WHERE kind<>\'explicit\'),count(*),coalesce(sum({billing.DAILY_COST_SQL}),0) FROM public.pr_phone_calls WHERE user_id=%s '
                    'AND requested_at>=to_timestamp(%s) AND id<>%s', (value['user_id'], start, call_id))
        automatic, count, reserved = cur.fetchone()
        blocker = planner.eligibility(value['kind'], prefs, now=service.clock(), verified=bool(identity and identity['verified'] and identity['hash']==value['number_hash']),
                    membership=bool(member and Membership.from_row(*member).allows('edit')), configured=bool(service.provider and service.provider.configured and (not service.provider.real or service.config.telephony_rate>0)),
                    live_configured=route.available and service.agent().cfg.enabled('RAFII_AGENT_V2_ENABLED'), flags=service.config.public(),
                    event_type=value['reason_key'].split(':',1)[0], daily_calls=int(count if value['kind']=='explicit' else automatic),
                    reserved_cost=int(reserved), estimate=value['reserved_usd_micro'], daily_budget=service.config.daily_budget)
        if blocker:
            cur.execute('UPDATE public.pr_phone_calls SET failure_class=%s WHERE id=%s', (blocker, call_id))
            db.commit()
        else:
            number = service.vault.decrypt(identity['ciphertext'], identity['key_id'])
            if service.provider.real:
                import re
                allowed=[c for c in service.config.values.get('RAFII_PHONE_ALLOWED_COUNTRY_CODES','').split(',') if re.fullmatch(r'\+[1-9][0-9]{0,2}',c)]
                if not any(number.startswith(c) for c in allowed):
                    blocker='phone_country'
                    cur.execute('UPDATE public.pr_phone_calls SET failure_class=%s WHERE id=%s',(blocker,call_id))
                    db.commit()
        if not blocker:
            cur.execute('UPDATE public.pr_phone_calls SET state=\'dialing\',dialing_at=now() WHERE id=%s', (call_id,))
            db.commit()
    if blocker:
        service.finish(call_id, 'cancelled')
        return
    try:
        receipt = service.provider.create_outbound_call(number=number, call_id=call_id, max_seconds=value['max_seconds'])
    except Exception:
        from .contracts import CallReceipt
        receipt = CallReceipt('ambiguous')
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        current = store.call(cur, call_id, lock=True)
        if not current:
            # Deletion waits for active-call reconciliation, so this cannot become an orphan call silently.
            if receipt.call_ref:
                service.provider.end_call(receipt.call_ref)
            return
        if receipt.failure in contracts.PROVIDER_FAILURES:
            cur.execute('UPDATE public.pr_phone_calls SET failure_class=%s WHERE id=%s', (receipt.failure, call_id))
        if receipt.call_ref:
            if current['provider_call_ref'] and current['provider_call_ref'] != receipt.call_ref:
                raise AlphaError('Provider call binding changed.', 409)
            cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=%s WHERE id=%s', (receipt.call_ref, call_id))
        if current['state'] not in contracts.TERMINAL and current['state'] != 'ending':
            store.set_state(cur, current, receipt.state if receipt.state not in contracts.TERMINAL else 'dialing')
        db.commit()
    if current['state'] == 'ending':
        service.hangup(call_id)
    elif receipt.state in contracts.TERMINAL:
        service.finish(call_id, receipt.state)


def reconcile(service, call_id):
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id)
        if not value or value['state'] not in ('dialing','ambiguous','ringing','ending'):
            return
        identity = store.number(cur, value['user_id'])
    is_inbound = value.get('direction') == 'inbound'
    if (not identity and not is_inbound) or not service.provider:
        return  # unknown acceptance is kept charged/reserved until an operator can reconcile
    try:
        if is_inbound:
            receipt = service.provider.reconcile_inbound(value['provider_call_ref'])
        else:
            receipt = service.provider.reconcile(number=service.vault.decrypt(identity['ciphertext'], identity['key_id']), call_id=call_id,
                                call_ref=value['provider_call_ref'], requested_at=float(value['requested_at']))
    except Exception:
        return
    if not receipt.call_ref:
        return
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        current = store.call(cur, call_id, lock=True)
        if current['provider_call_ref'] and current['provider_call_ref'] != receipt.call_ref:
            return
        cur.execute('UPDATE public.pr_phone_calls SET provider_call_ref=%s WHERE id=%s', (receipt.call_ref, call_id))
        if current['state'] != 'ending' and receipt.state not in contracts.TERMINAL:
            store.set_state(cur, current, receipt.state)
        db.commit()
    if receipt.state in contracts.TERMINAL:
        service.finish(call_id, receipt.state,receipt.duration_seconds)
    elif current['state'] == 'ending':
        service.hangup(call_id)
