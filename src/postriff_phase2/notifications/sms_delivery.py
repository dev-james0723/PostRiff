"""SMS egress and signed receipts for the existing notification queue, not a separate inbox/outbox.

Commit a dispatch marker before the provider call. A crash after that marker is terminal uncertain; it never
re-dials/resends. Consent, binding and per-user/global limits are serialized at this boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from postriff_alpha.domain import AlphaError
from . import catalog, planner, sms, store


def identity_vault(service):
    phone = getattr(service.hosted,'phone',None)
    if phone: return phone.vault
    from ..oauth import CredentialVault
    key = service.values.get('RAFII_PHONE_ENCRYPTION_KEY')
    return CredentialVault(key) if key else getattr(getattr(service.hosted,'oauth',None),'vault',None)


def _limit(values, name, default, maximum):
    try: return min(maximum,max(0,int(values.get(name,default))))
    except (ValueError,TypeError): return 0  # malformed configuration fails closed


def provider_stop(cur, user_id, binding):
    # Persist STOP even before the person ever opted in. The block belongs to this phone binding.
    cur.execute("""INSERT INTO public.pr_sms_consents(user_id,phone_hash,status,version,source,provider_blocked,opted_out_at)
                   SELECT user_id,phone_hash,'opted_out',%s,'provider',true,now() FROM public.pr_phone_numbers
                   WHERE user_id=%s AND phone_hash=%s
                   ON CONFLICT(user_id) DO UPDATE SET phone_hash=excluded.phone_hash,status='opted_out',source='provider',provider_blocked=true,
                   security_sms=false,opted_out_at=now(),updated_at=now()""", (sms.CONSENT_VERSION,user_id,binding))
    if cur.rowcount: store.cancel_sms(cur,user_id=user_id,reason='provider_stop')


def send(worker, row):
    service = worker.sms_service
    if not service: return {'state':'config','detail':'sms_disabled'}
    transport = service.sms_transport
    now = worker.clock()
    with worker.connection_factory() as db, db.cursor() as cur:
        # Same lock order as number replacement: identity -> consent -> event -> delivery.
        cur.execute('SELECT phone_ciphertext,key_id,phone_hash,verified_at IS NOT NULL FROM public.pr_phone_numbers WHERE user_id=%s FOR UPDATE', (row['userId'],))
        number = cur.fetchone()
        cur.execute('SELECT 1 FROM public.pr_sms_consents WHERE user_id=%s FOR UPDATE', (row['userId'],))
        cur.fetchone()
        cur.execute("""SELECT event_type,entity_type,entity_id,dedupe_key,extract(epoch from expires_at),resolved_at,sms_policy,time_sensitive,actor::text
                       FROM public.pr_notification_events WHERE id=%s FOR UPDATE""", (row['eventId'],))
        e = cur.fetchone()
        cur.execute("SELECT status,lease_owner,sms_dispatch_started_at,sms_escalation FROM public.pr_notification_deliveries WHERE id=%s FOR UPDATE", (row['id'],))
        d = cur.fetchone()
        if not d or d[0]!='claimed' or d[1]!=worker.worker_id:
            return {'state':'preference','detail':'sms_claim_lost'}
        if d[2]: return {'state':'uncertain','detail':'sms_dispatch_already_started'}
        if not e: return {'state':'expired','detail':'event_missing'}
        event = {'event_type':e[0],'workspace_id':row['workspaceId'],'actor':e[8], 'expires_at':float(e[4]) if e[4] else None,
                 'resolved_at':e[5],'sms_policy':e[6],'time_sensitive':e[7]}
        recipient = store.person(cur,row['userId'])
        if not recipient: return {'state':'membership','detail':'account_deleted'}
        if row['workspaceId'] and not any(m['userId']==row['userId'] for m in planner.audience(store.members(cur,row['workspaceId']),event)):
            return {'state':'membership','detail':'membership_or_permission_changed'}
        if store.domain_resolved(cur,e[0],e[1],e[2],e[3],row['workspaceId'],now=now):
            store.resolve(cur,row['eventId']); db.commit()
            return {'state':'expired','detail':'resolved'}
        prefs = planner.effective_preferences(store.preference_rows(cur,row['userId']),row['workspaceId'],catalog.spec(e[0])['category'])
        prefs.setdefault('time_zone',recipient.get('time_zone'))
        context = service.sms_context(cur,recipient,event)
        cur.execute('SELECT 1 FROM public.pr_notification_acknowledgements WHERE event_id=%s AND user_id=%s', (row['eventId'],row['userId']))
        context['acknowledged'] = cur.fetchone() is not None
        reason = sms.eligibility(event,prefs,context,now,store.sms_counts(cur,row['userId'],now,exclude=row['id']))
        if not reason and e[6]=='escalate' and d[3]:
            if not prefs.get('smart_escalation',True) or not context['escalation_enabled']: reason='smart_escalation_off'
        if reason:
            return {'state':'expired' if reason in ('expired','acknowledged','resolved') else 'preference','detail':reason}
        if planner.in_quiet_hours(now,prefs):
            due = planner.quiet_end_after(now,prefs)
            if event['expires_at'] and due>=event['expires_at']: return {'state':'expired','detail':'expired'}
            return {'state':'defer','nextAt':due,'detail':'quiet_hours'}
        if not transport or not transport.configured: return {'state':'config','detail':'sms_unconfigured'}
        try:
            message = sms.render(e[0],recipient.get('locale'),service.base_url,row['id'],
                                 max_segments=_limit(service.values,'RAFII_SMS_MAX_SEGMENTS',2,2))
            vault = identity_vault(service)
            plaintext = vault.decrypt(number[0],number[1])
        except Exception:
            return {'state':'config','detail':'sms_identity_or_copy_unavailable'}
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('notification:sms:provider',0))")
        rate = _limit(service.values,'RAFII_SMS_USD_MICRO_PER_SEGMENT',0,1000000)
        reserve = rate*message['segments']
        budget = _limit(service.values,'RAFII_SMS_DAILY_USD_MICRO',0,100000000)
        cap = _limit(service.values,'RAFII_SMS_PROVIDER_DAILY_LIMIT',100,10000)
        if transport.real and (not rate or not budget): return {'state':'config','detail':'sms_cost_unconfigured'}
        cur.execute("""SELECT count(*),coalesce(sum(coalesce(sms_cost_usd_micro,sms_reserved_usd_micro,0)),0)
                       FROM public.pr_notification_deliveries WHERE channel='sms' AND sms_dispatch_started_at>to_timestamp(%s)""", (now-86400,))
        count, cost = cur.fetchone()
        if count>=cap or (budget and int(cost)+reserve>budget): return {'state':'preference','detail':'sms_provider_or_cost_limit'}
        cur.execute("""UPDATE public.pr_notification_deliveries SET sms_dispatch_started_at=to_timestamp(%s),sms_phone_hash=%s,
                       sms_segments=%s,sms_reserved_usd_micro=%s,provider=%s WHERE id=%s AND status='claimed' AND lease_owner=%s""",
                    (now,number[2],message['segments'],reserve,transport.name,row['id'],worker.worker_id))
        db.commit()  # durable uncertainty fence BEFORE egress
    try:
        result = transport.send(number=plaintext,text=message['text'],delivery_id=row['id'],idempotency_key=row['key'])
    except Exception:
        result = {'state':'uncertain'}
    # A transport cannot leak provider text into delivery rows or logs.
    state = result.get('state') if isinstance(result,dict) else None
    if state not in ('sent','transient','permanent','config','uncertain'): state='uncertain'
    ref = result.get('providerRef') if isinstance(result,dict) else None
    if state=='sent' and not re.fullmatch(r'SM[0-9a-fA-F]{32}',str(ref)): state='uncertain'
    if state in ('transient','permanent','config'):
        # These outcomes are permitted only for known pre-acceptance rejection. A crash before recording this
        # reconciliation leaves the dispatch marker and is conservatively uncertain, never a duplicate.
        with worker.connection_factory() as db, db.cursor() as cur:
            if result.get('providerStop') is True: provider_stop(cur,row['userId'],number[2])
            cur.execute("UPDATE public.pr_notification_deliveries SET sms_dispatch_started_at=NULL,sms_reserved_usd_micro=0 WHERE id=%s AND status='claimed' AND lease_owner=%s",
                        (row['id'],worker.worker_id)); db.commit()
    elif state=='sent':
        metrics = sms.receipt_metrics(result.get('segments'))
        cost = result.get('costUsdMicro')
        if isinstance(cost,int) and not isinstance(cost,bool) and 0<=cost<=100000000: metrics['costUsdMicro']=cost
        if metrics:
            with worker.connection_factory() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_notification_deliveries SET sms_segments=coalesce(%s,sms_segments),sms_cost_usd_micro=coalesce(%s,sms_cost_usd_micro) WHERE id=%s AND sms_dispatch_started_at IS NOT NULL",
                            (metrics.get('segments'),metrics.get('costUsdMicro'),row['id'])); db.commit()
    return {'state':state,'provider':transport.name,'providerRef':ref if state=='sent' else None,
            'templateVersion':message['version'],'detail':'sms_'+state}


def webhook(service, path, parameters, signature):
    provider = service.sms_transport
    if not isinstance(provider,sms.TwilioSMSTransport) or not provider.verify_webhook(provider.base_url+path,parameters,signature):
        raise AlphaError('Invalid SMS signature.',401,code='sms_signature')
    def scalar(key):
        value = parameters.get(key,'')
        return value[0] if isinstance(value,list) and len(value)==1 else value if isinstance(value,str) else ''
    sid = scalar('MessageSid')
    if scalar('AccountSid')!=provider.account or not re.fullmatch(r'SM[0-9a-fA-F]{32}',sid):
        raise AlphaError('Invalid SMS receipt.',400)
    inbound = path=='/api/notifications/sms/inbound'
    state = scalar('MessageStatus') or scalar('SmsStatus')
    opt = scalar('OptOutType').upper()
    if inbound:
        # Standard STOP variants work even without Advanced Opt-Out. The message body is never persisted.
        word = scalar('Body').strip().upper()
        if word in ('STOP','STOPALL','UNSUBSCRIBE','CANCEL','END','QUIT'): opt='STOP'
        if word in ('START','UNSTOP'): opt='START'
        state = opt if opt in ('STOP','START') else 'ignored'
    elif state not in ('accepted','queued','sending','sent','delivered','failed','undelivered'):
        raise AlphaError('Invalid SMS lifecycle.',400)
    event_id = f'{sid}:{state}:{scalar("ErrorCode")[:10]}'
    digest = hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest()
    with service.hosted.repository.connection_factory() as db, db.cursor() as cur:
        user_id, delivery_id, binding = None,None,None
        if inbound:
            try:
                number = sms.phone_number(scalar('From'))
                vault = identity_vault(service)
                binding = hmac.new(vault.fernet._signing_key,number.encode(),hashlib.sha256).hexdigest()
            except Exception: raise AlphaError('Invalid SMS sender.',400) from None
            cur.execute('SELECT user_id::text FROM public.pr_phone_numbers WHERE phone_hash=%s ORDER BY user_id FOR UPDATE', (binding,))
            users = [r[0] for r in cur.fetchall()]
        else:
            delivery_id = path.rsplit('/',1)[-1]
            if not re.fullmatch(r'[0-9a-fA-F-]{36}',delivery_id): raise AlphaError('SMS delivery unavailable.',404)
            cur.execute("""SELECT user_id::text,sms_phone_hash FROM public.pr_notification_deliveries WHERE id::text=%s AND channel='sms'
                           AND provider='twilio_sms' AND sms_dispatch_started_at IS NOT NULL
                           AND (provider_ref IS NULL OR provider_ref=%s)""", (delivery_id,sid))
            row = cur.fetchone()
            if not row: raise AlphaError('SMS delivery unavailable.',404)
            user_id,binding = row
            users = [user_id]
        cur.execute("""INSERT INTO public.pr_notification_provider_events(provider,event_id,delivery_id,kind,payload_digest,outcome)
                       VALUES('twilio_sms',%s,%s,%s,%s,'applied') ON CONFLICT DO NOTHING RETURNING event_id""", (event_id,delivery_id,state,digest))
        if not cur.fetchone(): return {'duplicate':True}
        if opt=='STOP' or scalar('ErrorCode')=='21610':
            for user in users:
                provider_stop(cur,user,binding)
        elif inbound and opt=='START':
            # Provider unblock never grants consent: a fresh explicit application opt-in is still needed.
            for user in users:
                cur.execute('UPDATE public.pr_sms_consents SET provider_blocked=false,updated_at=now() WHERE user_id=%s AND phone_hash=%s', (user,binding))
        if not inbound:
            metrics = sms.receipt_metrics(scalar('NumSegments'),scalar('Price'),scalar('PriceUnit'))
            cur.execute("UPDATE public.pr_notification_deliveries SET sms_segments=coalesce(%s,sms_segments),sms_cost_usd_micro=coalesce(%s,sms_cost_usd_micro) WHERE id::text=%s",
                        (metrics.get('segments'),metrics.get('costUsdMicro'),delivery_id))
            status = 'delivered' if state=='delivered' else 'failed' if state in ('failed','undelivered') else 'sent'
            cur.execute("""UPDATE public.pr_notification_deliveries SET provider_ref=%s,status=%s,updated_at=now(),lease_owner=NULL,lease_until=NULL,
                           sent_at=coalesce(sent_at,now()),delivered_at=CASE WHEN %s='delivered' THEN coalesce(delivered_at,now()) ELSE delivered_at END,
                           failed_at=CASE WHEN %s='failed' THEN coalesce(failed_at,now()) ELSE failed_at END,
                           failure_class=CASE WHEN %s='failed' THEN 'permanent' ELSE NULL END,failure_detail=CASE WHEN %s='failed' THEN 'sms_provider_failed' ELSE NULL END
                           WHERE id::text=%s AND status IN ('claimed','sent','uncertain')""", (sid,status,status,status,status,status,delivery_id))
        db.commit()
    return {'applied':True}
