"""Disposable PostgreSQL acceptance: real SQL/services, fake SMS/Push/Phone only."""
from local_pg_target import selected_target
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.coworker import flags
from postriff_phase2.notifications import push,sms,sms_delivery,store
from postriff_phase2.notifications.service import NotificationService
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider

DSN=selected_target(require_dsn=True).dsn()
ONE,TWO=str(uuid.uuid4()),str(uuid.uuid4())
def connection(): return psycopg.connect(DSN)
def verify(token):
    if token not in (ONE,TWO): raise AlphaError('Session required.',401)
    return token
verify.auth_time=lambda *_:time.time()
verify.session_id=lambda token,_: 'test-'+token
class Identity:
    def delete_user(self,_): return True
hosted=HostedWorkspaceService(connection,verify,vault=CredentialVault(CredentialVault.generate_key()),identity=Identity(),public_base_url='https://app.rafii.example')
with connection() as db:
    db.cursor().executemany('INSERT INTO auth.users VALUES(%s)',[(ONE,),(TWO,)])
wid=hosted.bootstrap(ONE,'assist')['workspaceId']
other=hosted.bootstrap(TWO,'assist')['workspaceId']
values={'RAFII_NOTIFICATIONS_V2_ENABLED':'1','RAFII_SMS_ENABLED':'1','RAFII_SMS_ESCALATION_ENABLED':'1','RAFII_WEB_PUSH_ENABLED':'1',
        'POSTRIFF_PUBLIC_BASE_URL':'https://app.rafii.example','POSTRIFF_VAPID_SUBJECT':'https://app.rafii.example'}
keys=push.generate_vapid_keys()
values.update(POSTRIFF_VAPID_PUBLIC_KEY=keys['publicKey'],POSTRIFF_VAPID_PRIVATE_KEY=keys['privateKey'])
flags.attach(values)
fake=sms.FakeSMSTransport()
class FakePush:
    name='fake_push'
    def send(self,*_args,**_kwargs): return {'state':'sent','providerRef':'local-push'}
ns=hosted.notifications=NotificationService(hosted,values,sms_transport=fake,push_transport=FakePush())
phone=hosted.phone=PhoneService(hosted,{'RAFII_PHONE_ENABLED':'1'},provider=FakeTelephonyProvider())
def sql(query,*args):
    with connection() as db:
        cur=db.execute(query,args)
        return cur.fetchall() if cur.description else []
def denied(fn,status):
    try: fn()
    except AlphaError as e: assert e.status==status,(e.status,str(e))
    else: raise AssertionError('Expected refusal')
def consent(**extra):
    return ns.set_sms(wid,ONE,{'mode':'important_only','consent':True,'consentVersion':sms.CONSENT_VERSION,**extra})
emission_clock={}
def emit(kind='publish.failed',**extra):
    if kind.startswith('security.'): extra.setdefault('actor',ONE)
    at=time.time()
    # Bind each persisted schedule to its exact injected emission clock.
    with patch.object(ns,'clock',return_value=at),connection() as db:
        result=ns.emit(db.cursor(),workspace_id=wid,event_type=kind,dedupe_key=extra.pop('dedupe_key',str(uuid.uuid4())),**extra)
    emission_clock[result['eventId']]=at
    return result
def deliveries(event): return sql("SELECT id::text,channel,status,extract(epoch from next_attempt_at),failure_detail FROM pr_notification_deliveries WHERE event_id=%s",event['eventId'])
def sms_row(event): return next(r for r in deliveries(event) if r[1]=='sms')
def force_due(event): sql("UPDATE pr_notification_deliveries SET next_attempt_at=now()-interval '1 second' WHERE event_id=%s AND channel='sms'",event['eventId'])
def send(event):
    force_due(event)
    worker=ns.worker()
    claimed=[r for r in worker.claim(channel='sms',limit=1) if r['eventId']==event['eventId']]
    assert len(claimed)==1,claimed
    result=sms_delivery.send(worker,claimed[0]); worker.complete(claimed[0],result)
    return result
def clear():
    sql('DELETE FROM pr_notification_events WHERE workspace_id=%s',wid)
    sql('DELETE FROM pr_notification_preferences WHERE user_id=%s',ONE)
    sql('DELETE FROM pr_push_subscriptions WHERE user_id=%s',ONE)
    if ns.sms_transport is not fake: ns.sms_transport=fake
    fake.sent.clear(); fake.outcomes.clear()
def subscribe():
    vault=hosted.oauth.vault
    enc=[vault.encrypt(x)[0] for x in ('https://fcm.googleapis.com/fake','key','auth')]
    sql('INSERT INTO pr_push_subscriptions(user_id,endpoint_sha256,endpoint_ciphertext,p256dh_ciphertext,auth_ciphertext,key_id) VALUES(%s,%s,%s,%s,%s,%s)',
        ONE,hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),*enc,vault.key_id)

# Baseline, separate consent, explicit API opt-in, and durable timing.
assert sms_row(emit())[2]=='suppressed'
denied(lambda:consent(),409)
phone.start_verification(wid,ONE,{'number':'+12025550123'})
phone.confirm_verification(wid,ONE,{'code':'123456'})
phone.save_preferences(wid,ONE,{'enabled':True})
assert not ns.preferences(wid,ONE)['sms']['consented']
ns.set_preference(wid,ONE,{'scope':'all','category':'*','sms_mode':'off'})
assert sms_row(emit())[2]=='suppressed'
denied(lambda:ns.set_sms(wid,ONE,{'mode':'important_only'}),400)
consent()
subscribe()
event=emit(); row=sms_row(event)
assert row[2]=='pending' and 599 <= float(row[3])-emission_clock[event['eventId']] <= 601,row
timely=emit('campaign.approval_required',time_sensitive=True)
assert 1799 <= float(sms_row(timely)[3])-emission_clock[timely['eventId']] <= 1801
ordinary=emit('campaign.approval_required'); assert sms_row(ordinary)[2]=='suppressed'
repeat=emit(dedupe_key='one-event'); again=emit(dedupe_key='one-event')
assert not again['created'] and len([d for d in deliveries(repeat) if d[1]=='sms'])==1
assert sql("SELECT count(*) FROM pr_notification_deliveries WHERE event_id=%s AND channel='phone'",event['eventId'])[0][0]==0
print('PASS defaults off, verified/calling alone never grant SMS, explicit consent, 10/30-minute durable timing and dedupe')

# Authenticated push/email navigation, in-app marks and authoritative resolution cancel unsent SMS.
for channel in ('push','email','in_app'):
    event=emit()
    d=next(d for d in deliveries(event) if d[1]==channel)
    denied(lambda:ns.acknowledge(other,TWO,d[0]),404)
    if channel=='in_app': ns.mark(wid,ONE,d[0],'read')
    else: ns.acknowledge(wid,ONE,d[0])
    assert sms_row(event)[2]=='cancelled'
    assert sql('SELECT source_channel FROM pr_notification_acknowledgements WHERE event_id=%s AND user_id=%s',event['eventId'],ONE)[0][0]==channel
event=emit()
with connection() as db: store.resolve(db.cursor(),event['eventId'])
assert sms_row(event)[2]=='cancelled'
event=emit(); ns.mark_all_read(wid,ONE); assert sms_row(event)[2]=='cancelled'
group=str(uuid.uuid4()); batch=[emit(),emit()]
for item in batch: sql("UPDATE pr_notification_deliveries SET digest_id=%s WHERE event_id=%s AND channel='email'",group,item['eventId'])
ns.acknowledge(wid,ONE,next(d[0] for d in deliveries(batch[0]) if d[1]=='email'))
assert all(sms_row(item)[2]=='cancelled' for item in batch)
assert not fake.sent
clear(); consent()
# State removal is authoritatively resolved through the domain hook and again at egress.
before={'phase2':{'jobs':[{'id':'job-local','state':'failed','attempts':[{}]}]}}
event=emit(entity_type='job',entity_id='job-local',dedupe_key='publish.failed:job-local:1')
with connection() as db: ns.effect(db.cursor(),wid,before,{'phase2':{'jobs':[]}},ONE)
assert sms_row(event)[2]=='cancelled'
print('PASS strong cross-channel acknowledgement, cross-user isolation, read-all and domain resolution cancel escalation')

# Fresh boundary checks: no-push immediate, membership/permission, expiry, consent, quiet, mute, caps.
clear(); consent(); event=emit()
assert abs(float(sms_row(event)[3])-emission_clock[event['eventId']])<2
assert send(event)['state']=='sent' and len(fake.sent)==1
clear();consent();event=emit(entity_type='job',entity_id='missing-job',dedupe_key='publish.failed:missing-job:1')
assert send(event)['state']=='expired' and sms_row(event)[2]=='cancelled' and not fake.sent
clear();consent();subscribe();event=emit()
sql('DELETE FROM pr_push_subscriptions WHERE user_id=%s',ONE)
ns.set_preference(wid,ONE,{'scope':'all','category':'*','smart_escalation':False})
assert send(event)['state']=='preference' and not fake.sent
for name in ('expiry','membership','permission','consent','consent_version','mute','quiet','security'):
    clear(); consent(); event=emit('security.account_change' if name=='security' else 'publish.failed')
    if name=='security': assert sms_row(event)[2]=='suppressed'; continue
    if name=='expiry': sql("UPDATE pr_notification_events SET expires_at=now()-interval '1 second' WHERE id=%s",event['eventId'])
    if name=='membership': sql("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",wid,ONE)
    if name=='permission': sql("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",wid,ONE)
    if name=='consent': sql("UPDATE pr_sms_consents SET status='opted_out' WHERE user_id=%s",ONE)
    if name=='consent_version': sql("UPDATE pr_sms_consents SET version='obsolete' WHERE user_id=%s",ONE)
    if name=='mute': ns.set_preference(wid,ONE,{'scope':'all','category':'*','mute_hours':1})
    if name=='quiet':
        # The end is exclusive: 00:00–23:59 leaves 23:59 unquiet. Bracket
        # the real UTC minute so this refusal test also covers midnight.
        minute=int(time.time()//60)%1440
        ns.set_preference(wid,ONE,{'scope':'all','category':'*','quiet_start':(minute-60)%1440,'quiet_end':(minute+60)%1440,'time_zone':'UTC'})
    result=send(event)
    assert result['state'] in ('expired','membership','preference','defer'),(name,result)
    assert not fake.sent,(name,result)
    sql("UPDATE pr_memberships SET status='active',role='owner' WHERE workspace_id=%s AND user_id=%s",wid,ONE)
clear(); consent()
for i in range(3):
    event=emit(); result=send(event) if sms_row(event)[2]=='pending' else {'state':'preference'}
assert len(fake.sent)==2 and result['state']=='preference'
sql("UPDATE pr_notification_deliveries SET sms_dispatch_started_at=now()-interval '2 hours' WHERE channel='sms' AND user_id=%s",ONE)
for i in range(3):
    event=emit(); result=send(event) if sms_row(event)[2]=='pending' else {'state':'preference'}
assert len(fake.sent)==4 and result['state']=='preference'
clear();consent(); events=[emit() for _ in range(3)]
for event in events: force_due(event)
def concurrent(_):
    w=ns.worker()
    rows=w.claim(channel='sms',limit=1)
    for r in rows: w.complete(r,sms_delivery.send(w,r))
with ThreadPoolExecutor(max_workers=3) as pool: list(pool.map(concurrent,range(3)))
assert len(fake.sent)==2,len(fake.sent)
print('PASS no-push immediate Important Texts, expiry, membership/permission, consent, quiet/mute and serialized hourly/daily limits')

# Unknown acceptance and crash-after-dispatch are terminal; known pre-acceptance rejection can retry.
clear();consent();fake.outcomes=[{'state':'uncertain','detail':'+12025550123 private provider body'}]
event=emit(); assert send(event)['state']=='uncertain'
assert sms_row(event)[2]=='uncertain'; ns.worker().tick(); assert len(fake.sent)==1
clear();consent();event=emit();force_due(event);w=ns.worker();r=w.claim(channel='sms')[0]
sql("UPDATE pr_notification_deliveries SET sms_dispatch_started_at=now(),lease_until=now()-interval '1 second' WHERE id=%s",r['id'])
ns.worker().tick();assert sms_row(event)[2]=='uncertain' and not fake.sent
clear();consent();fake.outcomes=[{'state':'transient'}];event=emit();assert send(event)['state']=='transient'
assert sms_row(event)[2]=='pending';assert send(event)['state']=='sent';assert len(fake.sent)==2
clear();consent();event=emit();ns.values['RAFII_SMS_PROVIDER_DAILY_LIMIT']='0';assert send(event)['state']=='preference';assert not fake.sent
ns.values.pop('RAFII_SMS_PROVIDER_DAILY_LIMIT')
print('PASS fake acceptance, uncertain response/crash never resend, known rejection retry and provider cap')

# Signed provider receipts, replay, STOP/START semantics, and terminal monotonicity.
clear();consent(); event=emit()
provider=sms.TwilioSMSTransport({'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'synthetic','TWILIO_SMS_MESSAGING_SERVICE_SID':'MG'+'b'*32,
                              'POSTRIFF_PUBLIC_BASE_URL':ns.base_url},transport=lambda _: (201,{'sid':'SM'+'c'*32}))
ns.sms_transport=provider
assert send(event)['state']=='config'
assert sql('SELECT sms_dispatch_started_at FROM pr_notification_deliveries WHERE id=%s',sms_row(event)[0])[0][0] is None
event=emit();ns.values.update(RAFII_SMS_USD_MICRO_PER_SEGMENT='10000',RAFII_SMS_DAILY_USD_MICRO='1')
assert send(event)['state']=='preference'
event=emit()
ns.values.update(RAFII_SMS_USD_MICRO_PER_SEGMENT='10000',RAFII_SMS_DAILY_USD_MICRO='100000')
assert send(event)['state']=='sent'
path='/api/notifications/sms/webhook/'+sms_row(event)[0]
def receipt(path,**fields):
    data={'AccountSid':provider.account,'MessageSid':'SM'+'c'*32,**fields}
    wire=provider.base_url+path+''.join(k+str(data[k]) for k in sorted(data))
    sig=base64.b64encode(hmac.new(provider.auth.encode(),wire.encode(),hashlib.sha1).digest()).decode()
    return ns.sms_webhook(path,data,sig)
denied(lambda:ns.sms_webhook(path,{},'bad'),401)
assert receipt(path,MessageStatus='accepted')['applied']
assert receipt(path,MessageStatus='delivered',NumSegments='2',Price='-0.015',PriceUnit='USD')['applied']
assert sql('SELECT sms_segments,sms_cost_usd_micro FROM pr_notification_deliveries WHERE id=%s',sms_row(event)[0])[0]==(2,15000)
assert sms_row(event)[2]=='delivered'
assert receipt(path,MessageStatus='delivered')['duplicate']
receipt(path,MessageStatus='failed');assert sms_row(event)[2]=='delivered'
pending=emit()
receipt('/api/notifications/sms/inbound',From='+12025550123',Body='STOP',OptOutType='STOP')
texts=ns.preferences(wid,ONE)['sms'];assert not texts['consented'] and texts['provider_blocked']
assert sms_row(pending)[2]=='cancelled'
assert phone.settings(wid,ONE)['preferences']['enabled'],'STOP must not disable Phone Mode'
denied(consent,409)
receipt('/api/notifications/sms/inbound',From='+12025550123',Body='START',OptOutType='START')
assert not ns.preferences(wid,ONE)['sms']['consented']
consent()
# A separate known provider failed receipt is final, with no automatic retry.
clear();consent();event=emit();assert send(event)['state']=='sent'
ns.sms_transport=provider
sql("UPDATE pr_notification_deliveries SET provider='twilio_sms',provider_ref=%s WHERE id=%s",'SM'+'d'*32,sms_row(event)[0])
receipt('/api/notifications/sms/webhook/'+sms_row(event)[0],MessageSid='SM'+'d'*32,MessageStatus='failed')
assert sms_row(event)[2]=='failed'
# STOP arriving before any application consent still blocks a later opt-in.
sql('DELETE FROM pr_sms_consents WHERE user_id=%s',ONE)
receipt('/api/notifications/sms/inbound',MessageSid='SM'+'e'*32,From='+12025550123',Body='STOP')
denied(consent,409)
assert ns.preferences(wid,ONE)['sms']['provider_blocked']
receipt('/api/notifications/sms/inbound',MessageSid='SM'+'f'*32,From='+12025550123',Body='START')
print('PASS signed accepted/delivered/failed callbacks, numeric segments/cost, replay, STOP before/after consent disables SMS only, START never grants consent')

# Number replacement invalidates old consent. Never store plaintext in deliveries/log receipts/consent.
clear();consent();event=emit()
sql('UPDATE pr_phone_numbers SET phone_hash=%s WHERE user_id=%s','f'*64,ONE)
assert sms_row(event)[2]=='suppressed'
assert not ns.preferences(wid,ONE)['sms']['consented']
consent(); assert ns.preferences(wid,ONE)['sms']['consented']
wire=json.dumps(sql('SELECT row_to_json(d)::text FROM pr_notification_deliveries d WHERE user_id=%s',ONE))
wire+=json.dumps(sql('SELECT row_to_json(c)::text FROM pr_sms_consents c WHERE user_id=%s',ONE))+json.dumps(fake.sent)
assert '+12025550123' not in wire and 'private provider body' not in wire
for table in ('pr_sms_consents','pr_notification_acknowledgements'):
    for role in ('anon','authenticated'):
        with connection() as db:
            db.execute('SET ROLE '+role)
            try:db.execute('SELECT * FROM '+table)
            except psycopg.errors.InsufficientPrivilege:db.rollback()
            else:raise AssertionError('Client read server-only '+table)
    assert sql('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=%s',table)[0]==(True,True)
flags.attach({**values,'RAFII_SMS_ENABLED':'0'})
assert hosted.delete_account(wid,ONE,'DELETE')['workspaceDeleted']
for table in ('pr_sms_consents','pr_notification_acknowledgements','pr_notification_deliveries'):
    assert sql('SELECT count(*) FROM '+table+' WHERE user_id=%s',ONE)[0][0]==0
print('PASS binding invalidation, no plaintext in rows/receipts, forced RLS/server-only denial and account deletion with sending off')
from pathlib import Path
with connection() as db: db.execute((Path(__file__).resolve().parents[2]/'migrations/postriff/034_unified_notifications.sql').read_text())
print('PASS forward migration re-application')
print(json.dumps({'status':'PASS','execution':'disposable PostgreSQL / fake and injected provider transport','realSMS':0}))
