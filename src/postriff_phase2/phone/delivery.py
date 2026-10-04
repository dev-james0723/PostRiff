"""Phone egress: one committed claim, one request. Lost results are reconciled, never redialed."""
from postriff_alpha.domain import AlphaError

from ..permissions import Membership
from . import billing, contracts, planner, rules, store


def deliver(service, call_id):
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        value = store.call(cur, call_id, lock=True)
        if not value or value['state'] != 'requested' or value.get('direction') == 'inbound':
            return
        service._lock(cur, value['user_id'])
        number = service.resolve_destination(cur, value)
        prefs = store.prefs(cur, value['user_id'], value['workspace_id'])
        if service._system_ref(value):
            prefs = {**prefs, 'enabled': True}
        cur.execute('SELECT role,can_publish,can_reply,can_moderate,can_manage_connections FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id '
                    'WHERE workspace_id=%s AND m.user_id=%s AND m.status=\'active\' AND p.deleted_at IS NULL', (value['workspace_id'], value['user_id']))
        member = cur.fetchone()
        custom_ref = rules.reason_ref(value['reason_key']) if value['kind']=='proactive' else None
        custom_event_current = True
        if custom_ref:
            delivery_id = value['idempotency_key'].split(':', 1)[1] if value['idempotency_key'].startswith('notification:') else ''
            cur.execute('SELECT e.event_type=%s AND e.workspace_id=%s AND e.resolved_at IS NULL '
                        'AND (e.expires_at IS NULL OR e.expires_at>now()) AND e.occurred_at>now()-interval \'15 minutes\' '
                        'FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id '
                        'WHERE d.id::text=%s AND d.user_id=%s AND d.workspace_id=%s',
                        (value['reason_key'].split(':',1)[0], value['workspace_id'], delivery_id, value['user_id'], value['workspace_id']))
            fresh = cur.fetchone()
            custom_event_current = bool(fresh and fresh[0])
        route = service.agent().cfg.route('voice_front_end', reason='phone delivery')
        start = planner.day_start(service.clock(), planner.effective_preferences(prefs, service.config.public())['timeZone'])
        cur.execute(f'SELECT count(*) FILTER(WHERE kind<>\'explicit\'),count(*),coalesce(sum({billing.DAILY_COST_SQL}),0) FROM public.pr_phone_calls WHERE user_id=%s '
                    'AND requested_at>=to_timestamp(%s) AND id<>%s', (value['user_id'], start, call_id))
        automatic, count, reserved = cur.fetchone()
        cur.execute('SELECT count(*) FROM public.pr_phone_calls WHERE user_id=%s AND id<>%s AND NOT(state=ANY(%s))',
                    (value['user_id'], call_id, list(contracts.TERMINAL)))
        active_calls = int(cur.fetchone()[0])
        if planner.founder_scope(service.config.public()):
            active_calls = store.active_founder_contacts(cur, value['user_id'], value['workspace_id'], exclude_call_id=call_id)
        blocker = planner.eligibility(value['kind'], prefs, now=service.clock(), verified=bool(number),
                    membership=bool(member and Membership.from_row(*member).allows('edit')), configured=bool(service.provider and service.provider.configured and (not service.provider.real or service.config.telephony_rate>0)),
                    live_configured=route.available and service.agent().cfg.enabled('RAFII_AGENT_V2_ENABLED'), flags=service.config.public(),
                    event_type=value['reason_key'].split(':',1)[0], daily_calls=int(count if value['kind']=='explicit' else automatic),
                    custom_rule_ref=custom_ref,
                    active_calls=active_calls,
                    reserved_cost=int(reserved), estimate=value['reserved_usd_micro'], daily_budget=service.config.daily_budget)
        if not custom_event_current:
            blocker = 'event_not_allowed'
        if blocker:
            cur.execute('UPDATE public.pr_phone_calls SET failure_class=%s WHERE id=%s', (blocker, call_id))
            db.commit()
        else:
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
    bypass_amd = (
        service._system_ref(value)
        and str(service.config.values.get('JAMES_DAILY_CALL_ACCEPTANCE_BYPASS_AMD', '')).lower() in ('1','true','yes','on')
    )
    try:
        receipt = service.provider.create_outbound_call(
            number=number,
            call_id=call_id,
            max_seconds=value['max_seconds'],
            detect_machine=not bypass_amd,
        )
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
        number = None if value.get('direction') == 'inbound' else service.resolve_destination(cur, value)
    is_inbound = value.get('direction') == 'inbound'
    if (not number and not is_inbound) or not service.provider:
        return  # unknown acceptance is kept charged/reserved until an operator can reconcile
    try:
        if is_inbound:
            receipt = service.provider.reconcile_inbound(value['provider_call_ref'])
        else:
            receipt = service.provider.reconcile(number=number, call_id=call_id,
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
