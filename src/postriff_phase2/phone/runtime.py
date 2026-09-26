"""Attach to existing hosted service and existing cron. Flags off means no phone query or egress."""
import copy

from postriff_alpha.domain import AlphaError

from . import contracts, delivery, store
from .service import PhoneService


def attach(hosted, values):
    from ..deployment import isolated_environment
    values = isolated_environment(values)
    provider = None
    if values.get('RAFII_PHONE_PROVIDER') == 'fake':
        if values.get('VERCEL') or values.get('POSTRIFF_ENVIRONMENT')=='production':
            raise ValueError('Fake telephony is local-only')
        from .providers.fake import FakeTelephonyProvider
        provider = FakeTelephonyProvider()
    elif values.get('RAFII_PHONE_PROVIDER') == 'twilio':
        from .providers.twilio import TwilioProvider
        provider = TwilioProvider(values)
    hosted.phone = PhoneService(hosted, values, provider=provider)
    return hosted.phone


def cron(hosted, max_items=10):
    phone = getattr(hosted,'phone',None)
    if not phone or not phone.config.enabled('RAFII_PHONE_ENABLED'):
        return {'status':'disabled'}
    # Recovery can end/reconcile an existing accepted call even when new outbound calls are disabled.
    with hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT id::text,state FROM public.pr_phone_calls WHERE state IN (\'requested\',\'dialing\',\'ambiguous\',\'ringing\',\'ending\') ORDER BY requested_at LIMIT %s', (max_items,))
        work = cur.fetchall()
        cur.execute('SELECT id::text FROM public.pr_phone_calls WHERE state IN (\'answered\',\'live\') AND answered_at+make_interval(secs=>max_seconds)<now() LIMIT %s', (max_items,))
        expired = [r[0] for r in cur.fetchall()]
    for call_id in expired:
        phone.hangup(call_id)
    for call_id, state in work:
        (delivery.deliver if state=='requested' else delivery.reconcile)(phone,call_id)
    scheduled = schedule_tick(phone,max_items) if phone.config.enabled('RAFII_PHONE_SCHEDULED_ENABLED') else 0
    proactive = proactive_tick(phone,max_items) if phone.config.enabled('RAFII_PHONE_PROACTIVE_ENABLED') else 0
    return {'status':'ok','reconciled':len(work),'expired':len(expired),'scheduled':scheduled,'proactive':proactive}


def principal_phone(phone, workspace_id, principal):
    from ..automation_runs import principal_repository
    repository, capability = principal_repository(phone.hosted,workspace_id,principal,'edit')
    hosted = copy.copy(phone.hosted)
    hosted.repository = repository
    # request() uses the authenticated transaction principal, never a caller-provided user id.
    return PhoneService(hosted,phone.config.values,provider=phone.provider,runtime=phone.agent(),clock=phone.clock), capability


def schedule_tick(phone, limit):
    from .. import campaigns
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT id::text,user_id::text,workspace_id::text,conversation_id::text,schedule,extract(epoch from next_at) '
                    'FROM public.pr_phone_schedules WHERE enabled AND next_at<=now() ORDER BY next_at LIMIT %s FOR UPDATE SKIP LOCKED', (limit,))
        rows = cur.fetchall()
        for sid, _user, _ws, _conv, schedule, _at in rows:
            # Commit the due slot before dialing. Crashes may skip one briefing, never replay an ambiguous dial.
            next_at = campaigns.next_occurrence(schedule,phone.clock()+1)['scheduledFor']
            cur.execute('UPDATE public.pr_phone_schedules SET next_at=to_timestamp(%s) WHERE id=%s',(next_at,sid))
        db.commit()
    for sid,user,ws,conv,_schedule,at in rows:
        scoped,capability = principal_phone(phone,ws,user)
        try:
            scoped.request(ws,capability,{'idempotencyKey':f'schedule:{sid}:{int(at)}','conversationId':conv},kind='scheduled',reason_key='schedule:'+sid)
        except AlphaError:
            # Quiet hours, opt-out, revoked membership, limits: skip this slot; no catch-up/redial loops.
            pass
    return len(rows)


def proactive_tick(phone, limit):
    """Consumes phone outbox rows, independently of the normal email/push retry worker."""
    with phone.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute('SELECT d.id::text,d.user_id::text,d.workspace_id::text,e.event_type,coalesce(e.grouping_key,e.dedupe_key) '
                    'FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id=d.event_id '
                    'WHERE d.channel=\'phone\' AND (d.status=\'pending\' OR (d.status=\'claimed\' AND d.next_attempt_at<now()-interval \'5 minutes\')) AND d.next_attempt_at<=now() AND (e.expires_at IS NULL OR e.expires_at>now()) '
                    'ORDER BY d.next_attempt_at LIMIT %s FOR UPDATE OF d SKIP LOCKED',(limit,))
        rows=cur.fetchall()
        for did,*_rest in rows:
            cur.execute('UPDATE public.pr_notification_deliveries SET status=\'claimed\',attempts=1,next_attempt_at=now() WHERE id=%s',(did,))
        db.commit()
    for did,user,ws,event,group in rows:
        scoped,capability=principal_phone(phone,ws,user)
        try:
            result=scoped.request(ws,capability,{'idempotencyKey':'notification:'+did},kind='proactive',reason_key=event+':'+group[:100],event_type=event)
            status='sent' if result['state'] not in ('ambiguous','failed','cancelled') else 'failed'
            failure=None if status=='sent' else 'uncertain'
        except AlphaError as error:
            result,status,failure={'id':None},'suppressed','preference'
        with phone.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute('UPDATE public.pr_notification_deliveries SET status=%s,provider=%s,provider_ref=%s,failure_class=%s WHERE id=%s AND status=\'claimed\'',
                        (status,phone.provider.name if phone.provider else None,result['id'],failure,did))
            db.commit()
    return len(rows)
