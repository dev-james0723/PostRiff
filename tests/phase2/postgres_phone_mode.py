"""Real repository/runtime/command/ledger acceptance; synthetic phone and model only. No external egress."""
from local_pg_target import selected_target
import asyncio
import copy
import json
import os
import time
import uuid

os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
import psycopg
from agents.testing import ScriptedModel, assistant_message, function_call
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.agent_runtime_v2 import config, live
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.phone import contracts, delivery, store, webhooks
from postriff_phase2.phone.providers.fake import FakeTelephonyProvider
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.session import PhoneSessionController, bridge
from postriff_phase2.phone.runtime import schedule_tick, proactive_tick
from postriff_phase2.phone.providers.twilio import TwilioProvider
from postriff_phase2.phone.asgi import create_app, create_lazy_app
from starlette.testclient import TestClient
from contextlib import asynccontextmanager
import base64
import hashlib
import hmac

DSN = selected_target(require_dsn=True).dsn()
ONE, TWO = '00000000-0000-0000-0000-000000000001', str(uuid.uuid4())
clock = [time.time()]
def connection(): return psycopg.connect(DSN)
def verify(token):
    if token not in (ONE,TWO): raise AlphaError('Verified session required.',401)
    return token
verify.auth_time = lambda *_: clock[0]
verify.session_id = lambda token, _principal: 'test-session-'+token
class Identity:
    def delete_user(self, _principal): return True
service = HostedWorkspaceService(connection,verify,vault=CredentialVault(CredentialVault.generate_key()),identity=Identity(),clock=lambda:clock[0])
with connection() as db:
    db.execute('INSERT INTO auth.users VALUES(%s)',(TWO,))
    db.execute("UPDATE pr_workspaces SET state='{}'::jsonb")
wid = service.bootstrap(ONE,'studio')['workspaceId']
other = service.bootstrap(TWO,'studio')['workspaceId']
approve_budgets(connection,wid)
models = {}
def scripts(*steps): models['rafii_manager'] = ScriptedModel(list(steps))
def model_factory(_workload,name): return models.setdefault(name,ScriptedModel([]))
cfg = config.RuntimeConfig.from_environment({'OPENAI_API_KEY':'fake-phone-test-key','RAFII_AGENT_V2_ENABLED':'1','RAFII_VOICE_ENABLED':'1','RAFII_SPECIALISTS_ENABLED':'1'})
def fake_live(*_args,**_kwargs): return {'status':201,'body':{'session':{'id':'fake-browser-live'},'transport':{'type':'webrtc','sdp':'v=0\r\n'}}}
runtime = AgentRuntimeService(service,cfg,model_factory=model_factory,live_transport=fake_live,clock=lambda:clock[0])
provider = FakeTelephonyProvider()
values = {key:'1' for key in contracts.FLAGS}
values.update(RAFII_PHONE_MAX_SECONDS='60',RAFII_PHONE_USD_MICRO_PER_MINUTE='10000')
phone = service.phone = PhoneService(service,values,provider=provider,runtime=runtime)
def sql(query,*args):
    with connection() as db:
        cur=db.execute(query,args)
        return cur.fetchall() if cur.description else []
def denied(fn,status=None):
    try: fn()
    except AlphaError as error:
        assert status is None or status==error.status,(status,error.status,str(error))
        return error
    raise AssertionError('Unexpectedly authorized')
def read_call(cid):
    with connection() as db: return store.call(db.cursor(),cid)
def event(cid,state,eid=None,ref=None,**extra):
    data={'eventId':eid or uuid.uuid4().hex,'callRef':ref or 'fake_'+cid,'state':state,**extra}
    url='https://phone.test/api/phone/events/'+cid
    return webhooks.apply(phone,cid,url,data,provider.sign(url,data))
def reply(text): return [assistant_message(json.dumps({'answer':text,'speakable':text,'language':'en','follow_ups':[]}))]
def request(key=None,**extra): return phone.request(wid,ONE,{'idempotencyKey':key or uuid.uuid4().hex,**extra})
def age_calls(): sql("UPDATE pr_phone_calls SET requested_at=now()-interval '6 minutes'")

# Personal verification, encryption, fresh-session fence and minimal browser disclosure.
denied(lambda:request(),409)
phone.start_verification(wid,ONE,{'number':'+12025550123'})
denied(lambda:phone.start_verification(wid,ONE,{'number':'+12025550123'}),429)
denied(lambda:phone.confirm_verification(wid,ONE,{'code':'000000'}),400)
phone.confirm_verification(wid,ONE,{'code':'123456'})
# The lifecycle fixture ages calls by six minutes. Keep its local day away from
# midnight so that aging doesn't accidentally remove today's daily-limit rows.
fixture_zone='Etc/GMT+12' if time.gmtime(clock[0]).tm_hour<12 else 'UTC'
phone.save_preferences(wid,ONE,{'enabled':True,'timeZone':fixture_zone})
data = phone.settings(wid,ONE)
assert data['number']=={'lastFour':'0123','verified':True}
assert '+12025550123' not in json.dumps(data)
encrypted = sql('SELECT phone_ciphertext FROM pr_phone_numbers WHERE user_id=%s',ONE)[0][0]
assert '+12025550123' not in encrypted
assert not phone.settings(other,TWO)['number']
print('PASS verified encrypted identity, verification rate/attempts, cross-account disclosure')

# Two known drafts, seeded fixture content; edits use actual author-edit commands, not fixture writes.
d1,d2 = uuid.uuid4().hex,uuid.uuid4().hex
opening = 'We have spent many evenings reflecting on small steps that make piano practice feel possible. Join us for a gentle, friendly start.'
edited = 'Small steps make piano practice feel possible. Come try one with us.'
def seed(state,_actor):
    state['variants']=[{'id':draft,'platform':'LinkedIn','language':'English','text':text,'revision':1,'needsReview':True,'revisions':[],'localPreferences':{},'openings':[],'unknowns':[],'createdAt':i}
                       for i,(draft,text) in enumerate(((d1,'First LinkedIn draft'),(d2,opening)))]
    return state
service.repository.command(wid,ONE,service.get(wid,ONE)['revision'],seed)
conv = service.ideas.create_conversation(wid,ONE,'Same Rafii')['conversationId']
scripts(reply('The second LinkedIn draft is ready for your edits.'))
runtime.turn(wid,ONE,{'message':'We will work on the second LinkedIn draft.','conversationId':conv,'idempotencyKey':uuid.uuid4().hex})
models['rafii_manager'].assert_complete()
voice = live.VoiceSessions(runtime,transport=fake_live)
v = voice.start(wid,ONE,{'conversationId':conv,'sdp':'v=0\r\n','locale':'en'})
voice.end(wid,ONE,v['voiceSessionId'],{})

call = request('acceptance-call',conversationId=conv)
cid = call['id']
assert call['state']=='ringing' and provider.create_count==1
assert request('acceptance-call',conversationId=conv)['id']==cid and provider.create_count==1
denied(lambda:phone.view(other,TWO,cid),404)
denied(lambda:request('second-active-call'),409)
event(cid,'answered','accepted-answer')
assert event(cid,'answered','accepted-answer')['duplicate']
event(cid,'ringing')
assert read_call(cid)['state']=='answered'
sql('UPDATE pr_phone_calls SET media_claimed_at=now() WHERE id=%s',cid)
controller = PhoneSessionController(phone,cid)
assert 'second LinkedIn' in json.dumps(controller.configuration())
# Settings save -> authenticated phone configuration: every advertised voice, with the caller's name.
from postriff_phase2.agent_runtime_v2 import style as saved_style
service.update_profile(ONE, {'displayName': 'James Au'})
for selected_voice in saved_style.VOICES:
    service.update_profile(ONE, {'agentStyle': {'voice': selected_voice}})
    assert controller.configuration()['audio']['output']['voice'] == selected_voice
    assert '"James"' in controller.opening_greeting
service.update_profile(ONE, {'agentStyle': {'voice': 'marin'}})
print('PASS six saved Settings voices and authenticated first name reach phone Live configuration')
controller.started('fake-live-phone')
controller.transcript({'type':'session.input_transcript.delta','delta':'Open the second LinkedIn draft and cut the opening in half. Make it warmer.'})
scripts([function_call('workspace_summary',{},call_id='workspace')],
        [function_call('draft_get',{'draftId':d2},call_id='read')],
        [function_call('draft_edit',{'draftId':d2,'revision':1,'text':edited},call_id='edit')],
        reply('I shortened and warmed the second LinkedIn draft. It is saved in Rafii and needs your publishing review.'))
spoken = controller.delegate({'delegation':{'id':'edit-second','target':'client'}})
models['rafii_manager'].assert_complete()
assert 'shortened' in spoken['content'],spoken
assert controller.delegate({'delegation':{'id':'edit-second','target':'client'}})==spoken
state=service.get(wid,ONE)['state']
assert state['variants'][0]['text']=='First LinkedIn draft'
assert state['variants'][1]['text']==edited and state['variants'][1]['revision']==2 and state['variants'][1]['needsReview']
assert not state['phase2']['jobs']
controller.transcript({'type':'session.input_transcript.delta','delta':'Publish it.'})
scripts()
publication=controller.delegate({'delegation':{'id':'publish','target':'client'}})
models['rafii_manager'].assert_complete()
assert any(word in publication['content'].lower() for word in ('approval','approve','review','publish')) and not service.get(wid,ONE)['state']['phase2']['jobs'],publication
phone.hangup(cid,live_seconds=3)
denied(lambda:controller.runtime.service.get(wid,controller.capability),409)
assert sql('SELECT count(*) FROM pr_messages WHERE conversation_id=%s',conv)[0][0]>=6
print('PASS text/browser/phone continuity; real second-draft edit; verified speakable result; publish approval; closed-call capability')

# Ambiguous create never retries: recover with provider read/signed callback, then end.
age_calls()
provider.outcome='ambiguous'
uncertain=request('ambiguous-test')
before=provider.create_count
assert uncertain['state']=='ambiguous'
delivery.deliver(phone,uncertain['id'])
assert provider.create_count==before
delivery.reconcile(phone,uncertain['id'])
assert read_call(uncertain['id'])['state']=='ringing' and provider.create_count==before
event(uncertain['id'],'no_answer',durationSeconds=0)
assert read_call(uncertain['id'])['state']=='no_answer'
event(uncertain['id'],'answered')
assert read_call(uncertain['id'])['state']=='no_answer'
print('PASS ambiguous create reconciliation, single dial, duplicate and out-of-order signed events')

# Membership revocation and phone preference revocation deny delegated tools.
age_calls(); provider.outcome='ringing'
revoked=request('revoked-call')
event(revoked['id'],'answered')
c=PhoneSessionController(phone,revoked['id'])
sql("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s",wid,ONE)
denied(lambda:c.runtime.service.get(wid,c.capability),403)
sql("UPDATE pr_memberships SET status='active' WHERE workspace_id=%s AND user_id=%s",wid,ONE)
phone.save_preferences(wid,ONE,{'enabled':False})
denied(lambda:c.runtime.service.get(wid,c.capability),409)
phone.hangup(revoked['id'],live_seconds=0)
phone.save_preferences(wid,ONE,{'enabled':True,'scheduledCalls':True,'quietStart':0,'quietEnd':0})
age_calls()

# Existing schedule parser and existing cron slot execution, one call per slot, no parallel scheduler.
schedule=phone.save_schedule(wid,ONE,{'conversationId':conv,'schedule':{'weekdays':['Monday'],'localTime':'09:00','timeZone':'UTC'}})
sql('UPDATE pr_phone_schedules SET next_at=now()-interval \'1 minute\' WHERE id=%s',schedule['id'])
before=provider.create_count
assert schedule_tick(phone,10)==1 and provider.create_count==before+1
assert schedule_tick(phone,10)==0 and provider.create_count==before+1
last=sql("SELECT id::text FROM pr_phone_calls WHERE kind='scheduled'")[0][0]
phone.hangup(last,live_seconds=0)
phone.delete_schedule(wid,ONE,schedule['id'])
print('PASS membership/opt-out fencing, weekly schedule parser and exactly-once cron slot')

# Opt-in Notification V2 attention channel, no routine/security escalation, max two automatic calls and fallback.
from postriff_phase2.notifications.service import NotificationService
os.environ['RAFII_NOTIFICATIONS_V2_ENABLED']='1'
service.notifications=NotificationService(service,values={})
service.notifications.email_transport=None
service.notifications.push_transport=None
phone.save_preferences(wid,ONE,{'proactiveCalls':True,'eventAllowlist':['campaign.blocked','campaign.approval_required','publish.failed']})
age_calls()
with connection() as db:
    plan=service.notifications.emit(db.cursor(),workspace_id=wid,event_type='campaign.blocked',dedupe_key='blocked-test',actor=ONE,payload={'title':'Campaign blocked','detail':'Contact +12025550123'})
    assert any(d['channel']=='phone' and d['status']=='pending' for d in plan['deliveries']),plan
assert '+12025550123' not in json.dumps(sql('SELECT payload FROM pr_notification_events'))
before=provider.create_count
assert proactive_tick(phone,10)==1 and provider.create_count==before+1
assert proactive_tick(phone,10)==0
automatic=sql("SELECT id::text FROM pr_phone_calls WHERE kind='proactive'")[0][0]
event(automatic,'busy')
assert sql("SELECT count(*) FROM pr_notification_events WHERE event_type='phone.call_failed'")[0][0]>=1
age_calls()
with connection() as db:
    for kind in ('publish.verified','campaign.approval_required','publish.failed'):
        result=service.notifications.emit(db.cursor(),workspace_id=wid,event_type=kind,dedupe_key='never-call:'+kind,actor=ONE,payload={'title':'Update'})
        assert not any(d['channel']=='phone' and d['status']=='pending' for d in result['deliveries']),result
print('PASS Notification V2 phone outbox opt-in/single delivery/daily cap; routine and non-deadline approvals never call; fallback; phone payload redaction')

# Real signed ASGI websocket → synthetic GPT-Live event wire → shared Agent → actual draft command → outbound audio.
age_calls()
class LocalTwilio(TwilioProvider):
    real=True  # Exercise real-provider billing policy; every REST request is intercepted below.
    def __init__(self):
        self.end_confirmed=True
        self.requests=[]
        super().__init__({'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'local-only-secret','TWILIO_PHONE_NUMBER':'+12025550100','RAFII_PHONE_PUBLIC_BASE_URL':'https://phone.test'},transport=self.transport_fixture)
    def transport_fixture(self,method,url,fields=None):
        self.requests.append(method)
        if method=='POST' and isinstance(fields,list): return 201,{'sid':'CA'+'b'*32,'status':'ringing'}
        if method=='POST' and not self.end_confirmed: return 0,{}
        return 200,{'sid':'CA'+'b'*32,'status':'completed'}
twilio=LocalTwilio()
phone.config.values['RAFII_PHONE_ALLOWED_COUNTRY_CODES']='+1'
phone.provider=twilio
wire=request('signed-media',conversationId=conv)
wc=wire['id']
sql("UPDATE pr_phone_calls SET state='answered',answered_at=now() WHERE id=%s",wc)
new_text='Small steps make practice possible. Let’s try one together.'
scripts([function_call('draft_get',{'draftId':d2},call_id='ws-read')],
        [function_call('draft_edit',{'draftId':d2,'revision':2,'text':new_text},call_id='ws-edit')],
        reply('I saved the warmer opening in your second LinkedIn draft. Publishing still requires review.'))
class LiveWire:
    def __init__(self): self.queue=asyncio.Queue(); self.sent=[]; self.audio_count=0; self.spoken=[]
    def __aiter__(self): return self
    async def __anext__(self): return await self.queue.get()
    async def send(self,event):
        self.sent.append(event)
        kind=event['type']
        if kind=='session.start': await self.queue.put({'type':'session.started','session':{'id':'fake-live-media'}})
        elif kind=='session.instructions.append': await self.queue.put({'type':'session.output_audio.delta','delta':base64.b64encode(b'fake-greeting').decode()})
        elif kind=='session.input_audio.append':
            self.audio_count+=1
            text='Open the second LinkedIn draft and cut the opening in half. Make it warmer.' if self.audio_count==1 else 'Publish it.'
            await self.queue.put({'type':'session.input_transcript.delta','delta':text})
            await self.queue.put({'type':'session.delegation.created','delegation':{'id':'audio-'+str(self.audio_count),'target':'client'}})
        elif kind=='session.commentary.append':
            self.spoken.append(event['content'])
            await self.queue.put({'type':'session.output_transcript.delta','delta':event['content']})
            await self.queue.put({'type':'session.output_audio.delta','delta':base64.b64encode(b'fake-spoken-result').decode()})
        elif kind=='session.close': await self.queue.put({'type':'session.closed','usage':{'seconds':4}})
live_wire=None
@asynccontextmanager
async def connect():
    global live_wire
    live_wire=LiveWire()
    yield live_wire
def media_signature(cid):
    url='wss://phone.test/api/phone/media/'+cid
    return base64.b64encode(hmac.new(twilio.auth.encode(),url.encode(),hashlib.sha1).digest()).decode()
# Exercise the lazy, media-only deployment host, with HTTP still on the existing API.
app=create_lazy_app(values=values,application_factory=lambda:create_app(service,phone,connect,media_only=True))
with TestClient(app) as client, TestClient(create_app(service,phone,connect)) as api_client:
    try:
        with client.websocket_connect('/api/phone/media/'+wc,headers={'x-twilio-signature':'bad'}): raise AssertionError('Unsigned media accepted')
    except Exception as error:
        assert type(error).__name__=='WebSocketDisconnect',type(error)
    with client.websocket_connect('/api/phone/media/'+wc,headers={'x-twilio-signature':media_signature(wc)}) as ws:
        ws.send_json({'event':'start','start':{'accountSid':twilio.account,'callSid':'CA'+'b'*32,'streamSid':'MZ-local','mediaFormat':{'encoding':'audio/x-mulaw','sampleRate':8000,'channels':1}}})
        assert ws.receive_json()['event']=='media'
        ws.send_json({'event':'media','media':{'payload':base64.b64encode(b'fake-user-audio').decode()}})
        assert ws.receive_json()['event']=='clear'  # interruption clears queued phone playback
        assert ws.receive_json()['event']=='media'
        models['rafii_manager'].assert_complete()
        assert 'saved' in live_wire.spoken[0].lower(),live_wire.spoken
        snapshot=api_client.get('/api/workspaces/'+wid,headers={'Authorization':'Bearer '+ONE,'X-PostRiff-Request':'founder-alpha'})
        assert snapshot.status_code==200,snapshot.text
        assert snapshot.json()['state']['variants'][1]['text']==new_text
        scripts()
        ws.send_json({'event':'media','media':{'payload':base64.b64encode(b'fake-publish-audio').decode()}})
        assert ws.receive_json()['event']=='clear'
        assert ws.receive_json()['event']=='media'
        assert not service.get(wid,ONE)['state']['phase2']['jobs']
        twilio.end_confirmed=False
        ws.send_json({'event':'stop'})
        try:
            ws.receive_json()
        except Exception as error:
            assert type(error).__name__=='WebSocketDisconnect',type(error)
assert read_call(wc)['state']=='ending',read_call(wc)
assert sql('SELECT live_usage_seconds FROM pr_phone_calls WHERE id=%s',wc)[0][0]==4
denied(lambda:request('no-redial-during-uncertain-hangup'),409)
before=twilio.requests.count('POST')
delivery.reconcile(phone,wc)
assert read_call(wc)['state']=='completed' and twilio.requests.count('POST')==before,'Confirmed provider end must not submit another hangup'
assert sql('SELECT telephony_cost_usd_micro FROM pr_phone_calls WHERE id=%s',wc)[0][0] is None,'Hold real telephony usage until final provider duration'
done={'AccountSid':twilio.account,'CallSid':'CA'+'b'*32,'CallStatus':'completed','CallDuration':'42','SequenceNumber':'final'}
url='https://phone.test/api/phone/webhooks/'+wc
signed=url+''.join(key+done[key] for key in sorted(done))
sig=base64.b64encode(hmac.new(twilio.auth.encode(),signed.encode(),hashlib.sha1).digest()).decode()
webhooks.apply(phone,wc,url,done,sig)
assert read_call(wc)['state']=='completed' and read_call(wc)['duration_seconds']==42
assert sql('SELECT telephony_cost_usd_micro,live_usage_seconds FROM pr_phone_calls WHERE id=%s',wc)[0]==(10000,4)
assert webhooks.apply(phone,wc,url,done,sig)['duplicate']
settled=sql('SELECT count(*) FROM pr_usage_ledger')[0][0]
phone.finish(wc,'completed',42,live_seconds=4)
assert sql('SELECT count(*) FROM pr_usage_ledger')[0][0]==settled,'Late usage/duration replay must not charge again'
phone.provider=provider
print('PASS signed ASGI audio roundtrip → actual draft visible through web API → verified spoken result; interruption; publish approval; uncertain hangup fences redial; signed final duration and usage reconciliation')

# Failure and hangup while a real backend turn waits on its model: no late mutation or orphan running agent row.
from threading import Event
from concurrent.futures import ThreadPoolExecutor
sql("UPDATE pr_phone_calls SET requested_at=now()-interval '1 day'")
waiting=request('hangup-during-tool',conversationId=conv)
event(waiting['id'],'answered')
waiting_controller=PhoneSessionController(phone,waiting['id'])
entered,released=Event(),Event()
class PausedModel(ScriptedModel):
    async def get_response(self,*args,**kwargs):
        entered.set()
        await asyncio.to_thread(released.wait,10)
        return await super().get_response(*args,**kwargs)
models['rafii_manager']=PausedModel([[function_call('draft_edit',{'draftId':d2,'revision':3,'text':'Must not be saved after hangup'},call_id='late-edit')],reply('Saved.')])
waiting_controller.transcript({'type':'session.input_transcript.delta','delta':'Make the second LinkedIn draft warmer.'})
with ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(waiting_controller.delegate,{'delegation':{'id':'late-tool','target':'client'}})
    assert entered.wait(10),'Model never started'
    waiting_controller.closed=True
    phone.hangup(waiting['id'],live_seconds=0)
    released.set()
    assert future.result(timeout=20) is None
assert service.get(wid,ONE)['state']['variants'][1]['text']==new_text
assert sql("SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s AND status='running' AND idempotency_key LIKE 'agent:%%'",wid)[0][0]==0
print('PASS hangup during backend work: next mutation denied, exact phone-owned run cancelled, saved draft preserved')

# Regression: a confirmed zero-cost failure cannot keep its original ten-minute
# ceiling charged all day. Partial/unknown settlement still retains the full hold.
from postriff_phase2.phone import billing, planner
sql("UPDATE pr_phone_calls SET requested_at=now()-interval '1 day'")
saved_values=dict(phone.config.values)
phone.config.values.update(RAFII_PHONE_MAX_SECONDS='600',RAFII_PHONE_USD_MICRO_PER_MINUTE='170000',RAFII_PHONE_DAILY_USD_MICRO='3000000')
attempts=[]
outcome=[(401,{'code':20003,'message':'Secret provider payload +12025550123'})]
def reject_or_accept(method,url,fields=None):
    attempts.append(method)
    return outcome[0]
check_provider=TwilioProvider({'TWILIO_ACCOUNT_SID':'AC'+'a'*32,'TWILIO_AUTH_TOKEN':'local-only-secret','TWILIO_PHONE_NUMBER':'+12025550100','RAFII_PHONE_PUBLIC_BASE_URL':'https://phone.test'},transport=reject_or_accept)
phone.provider=check_provider
failed=request('confirmed-provider-rejection')
assert failed['state']=='failed' and failed['failure']=='provider_auth' and 'verified' in failed['failureMessage']
assert '+12025550123' not in json.dumps(failed)
assert sql('SELECT provider_call_ref,live_cost_usd_micro,telephony_cost_usd_micro,reserved_usd_micro FROM pr_phone_calls WHERE id=%s',failed['id'])[0]==(None,0,0,270000)
assert request('confirmed-provider-rejection')['id']==failed['id'] and attempts==['POST']
outcome[0]=(403,{'code':21216})
second=phone.request(wid,ONE,{'idempotencyKey':'too-soon-after-failed-call'},dispatch=False)
delivery.deliver(phone,second['id'])  # Delivery must use settled costs too.
assert read_call(second['id'])['state']=='failed' and read_call(second['id'])['failure_class']=='provider_destination'
assert attempts==['POST','POST']
outcome[0]=(201,{'sid':'CA'+'d'*32,'status':'ringing'})
held=request('real-provider-usage-unknown')
sql("UPDATE pr_phone_calls SET state='answered',answered_at=now(),media_claimed_at=now() WHERE id=%s",held['id'])
phone.finish(held['id'],'completed')
sql("UPDATE pr_phone_calls SET requested_at=now()-interval '6 minutes' WHERE requested_at>=to_timestamp(%s)",planner.day_start(clock[0],fixture_zone))
assert sql('SELECT live_cost_usd_micro,telephony_cost_usd_micro FROM pr_phone_calls WHERE id=%s',held['id'])[0]==(None,None)
assert attempts==['POST','POST','POST']
assert sql(f'SELECT {billing.DAILY_COST_SQL} FROM pr_phone_calls WHERE id=%s',held['id'])[0][0]==270000
phone.finish(held['id'],'completed',42)
assert sql(f'SELECT {billing.DAILY_COST_SQL} FROM pr_phone_calls WHERE id=%s',held['id'])[0][0]==270000,'Partial settlement retains full ceiling'
phone.finish(held['id'],'completed',42,live_seconds=4)
with connection() as db:
    from postriff_phase2.permissions import Membership
    attention=phone.notification_context(db.cursor(),{'userId':ONE,'membership':Membership.from_row('owner',True,True,True,True)},
        {'event_type':'publish.failed','workspace_id':wid,'grouping_key':'budget-check'})
assert 170000 <= attention['reserved_cost'] < 270000,attention
outcome[0]=(400,{'code':21212})
after_settlement=request('settled-usage-allows-next-call')
assert after_settlement['state']=='failed' and after_settlement['failure']=='provider_caller'
assert attempts==['POST','POST','POST','POST']
phone.config.values.clear(); phone.config.values.update(saved_values)
phone.provider=provider
print('PASS confirmed provider errors masked; immediate explicit retry/idempotency; zero-cost failures release daily capacity at request and delivery; unknown/partial holds retained; actual costs shared with notification policy')

# Credit-mode calls use the existing wallet/quote/reservation path, never an implicit spend.
import sys
sys.path.insert(0,os.path.join(os.getcwd(),'scripts'))
from launch_credit_fixture import configure as credit_fixture
credit_fixture(service,connection)
assert service.bootstrap(TWO,'studio')['workspaceId']==other
phone.provider=provider
phone.start_verification(other,TWO,{'number':'+12025550124'})
phone.confirm_verification(other,TWO,{'code':'123456'})
phone.save_preferences(other,TWO,{'enabled':True,'scheduledCalls':True,'quietStart':0,'quietEnd':0})
price=phone.settings(other,TWO)['spending']
assert price['usesCredits'] and price['ceilingMilliCredits']>0
before_count=provider.create_count
before_quotes=sql('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',other)[0][0]
for limit in (None,True,0,price['ceilingMilliCredits']-1):
    denied(lambda:phone.request(other,TWO,{'idempotencyKey':uuid.uuid4().hex,'maxMilliCredits':limit}),402)
assert provider.create_count==before_count
assert sql('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',other)[0][0]==before_quotes
credit_call=phone.request(other,TWO,{'idempotencyKey':'approved-credit-call','maxMilliCredits':price['ceilingMilliCredits']})
assert provider.create_count==before_count+1
duplicate=phone.request(other,TWO,{'idempotencyKey':'approved-credit-call','maxMilliCredits':0})
assert duplicate['id']==credit_call['id'] and provider.create_count==before_count+1
with connection() as db:
    wallet=service.ledger.credits.view(db.cursor(),other)
assert wallet['heldMilliCredits']==price['ceilingMilliCredits'],wallet
event(credit_call['id'],'answered',ref=read_call(credit_call['id'])['provider_call_ref'])
scoped,capability,bound=phone.scoped_runtime(credit_call['id'])
scoped.model_factory=None  # Exercise production reservation logic without opening a model connection.
def open_manager(runtime,cap,binding):
    return runtime._open_run(other,cap,binding['conversation_id'],'Make it warmer.','voice','agent:'+uuid.uuid4().hex,
                             'trace_'+uuid.uuid4().hex,[],model='rafii-agent',reserve_for='standard_reasoning')
quotes=sql('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',other)[0][0]
denied(lambda:open_manager(scoped,capability,bound),402)
assert sql('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',other)[0][0]==quotes
phone.hangup(credit_call['id'],live_seconds=0)
with connection() as db:
    wallet=service.ledger.credits.view(db.cursor(),other)
assert wallet['heldMilliCredits']==0 and wallet['usedMilliCredits']==0,wallet
sql("UPDATE pr_phone_calls SET requested_at=to_timestamp(%s)-interval '6 minutes' WHERE workspace_id=%s",clock[0],other)
denied(lambda:phone.request(other,TWO,{'idempotencyKey':'automatic-no-credit-limit'},kind='scheduled'),402)
phone.save_preferences(other,TWO,{'maxMilliCreditsPerCall':price['ceilingMilliCredits']})
automatic=phone.request(other,TWO,{'idempotencyKey':'automatic-approved-credit-limit'},kind='scheduled')
phone.hangup(automatic['id'],live_seconds=0)
# The same Manager can reserve against the remaining approved call limit. Unknown
# usage stays committed; releases free capacity; a model cannot enlarge the limit.
sql("UPDATE pr_phone_calls SET requested_at=to_timestamp(%s)-interval '6 minutes' WHERE workspace_id=%s",clock[0],other)
with connection() as db:
    service.ledger.credits.grant(db.cursor(),other,TWO,'phone-agent-synthetic-grant',500000,source='local-phone-test-only')
route=cfg.route('standard_reasoning',reason='phone reservation acceptance')
manager_cost=cfg.estimate_usd_micro(route.model,24000,4000)
from postriff_phase2.credit_meter import millicredits
maximum=price['ceilingMilliCredits']+2*millicredits(manager_cost)
agent_call=phone.request(other,TWO,{'idempotencyKey':'phone-manager-credit-call','maxMilliCredits':maximum})
event(agent_call['id'],'answered',ref=read_call(agent_call['id'])['provider_call_ref'])
scoped,capability,bound=phone.scoped_runtime(agent_call['id'])
scoped.model_factory=None
first_run,first_hold=open_manager(scoped,capability,bound)
second_run,second_hold=open_manager(scoped,capability,bound)
with connection() as db:
    service.ledger.settle(db.cursor(),other,first_hold['reservationId'],'unknown')
denied(lambda:open_manager(scoped,capability,bound),402)
with connection() as db:
    service.ledger.reconcile_unknown(db.cursor(),other,first_hold['reservationId'],'failed',0,operator='local-test',evidence='synthetic provider confirms zero use')
third_run,third_hold=open_manager(scoped,capability,bound)
assert len({first_run,second_run,third_run})==3
denied(lambda:open_manager(scoped,capability,bound),402)
with connection() as db:
    for hold in (second_hold,third_hold): service.ledger.settle(db.cursor(),other,hold['reservationId'],'failed',0)
sql("UPDATE pr_agent_runs SET status='completed' WHERE id=ANY(%s::uuid[])",[first_run,second_run,third_run])
phone.hangup(agent_call['id'],live_seconds=0)
denied(lambda:open_manager(scoped,capability,bound),409)
assert service.delete_account(other,TWO,'DELETE')['workspaceDeleted']
print('PASS credit-mode call approval, exact component holds, bounded shared Manager spend/unknown holds/releases, retry idempotency, release and standing automatic-call limit')

# Server-only RLS for every private phone table.
tables=('pr_phone_numbers','pr_phone_preferences','pr_phone_verification_limits','pr_phone_calls','pr_phone_provider_events','pr_phone_delegations','pr_phone_schedules')
for table in tables:
    with connection() as db:
        db.execute('SET ROLE authenticated')
        try: db.execute('SELECT * FROM public.'+table)
        except psycopg.errors.InsufficientPrivilege: db.rollback()
        else: raise AssertionError('Client could enumerate '+table)
print('PASS PostgreSQL grants and RLS: client roles cannot read identity/call/delegation tables')

# User-authored trigger and discussion: only a reviewed, matching rule can create one phone delivery.
from postriff_phase2.phone import rules
service.notifications.clock=lambda:clock[0]  # Keep the persisted event clock aligned with this fixture's phone clock.
rule_id=str(uuid.uuid4())
draft={'id':rule_id,'when':'Call me if a scheduled post fails twice in one day',
       'discuss':'Tell me which post failed and what I can do','enabled':False}
phone.save_preferences(wid,ONE,{'eventAllowlist':[],'customRules':[draft]})
reviewed=phone.settings(wid,ONE)['preferences']['customRules'][0]
assert not reviewed['enabled'] and reviewed['countAtLeast']==2 and reviewed['sameEntity']
phone.save_preferences(wid,ONE,{'customRules':[{**reviewed,'enabled':True}]})
assert phone.settings(wid,ONE)['preferences']['customRules'][0]['enabled']
sql("UPDATE pr_phone_calls SET requested_at=now()-interval '2 days'")
with connection() as db:
    one=service.notifications.emit(db.cursor(),workspace_id=wid,event_type='publish.failed',dedupe_key='custom-first',
                                   entity_type='post',entity_id='post-custom-1',actor=ONE,payload={'title':'First post failure'})
    assert not any(d['channel']=='phone' for d in one['deliveries']),one
with connection() as db:
    two=service.notifications.emit(db.cursor(),workspace_id=wid,event_type='publish.failed',dedupe_key='custom-second',
                                   entity_type='post',entity_id='post-custom-1',actor=ONE,payload={'title':'Second post failure'})
    if not any(d['channel']=='phone' and d['status']=='pending' for d in two['deliveries']):
        from postriff_phase2.permissions import Membership
        context=phone.notification_context(db.cursor(),{'userId':ONE,'membership':Membership.from_row('owner',True,True,True,True)},
            {'event_type':'publish.failed','workspace_id':wid,'grouping_key':'custom-second','entity_id':'post-custom-1'})
        current=context.pop('prefs') if context else {}
        why=planner.eligibility('proactive',current,now=phone.clock(),event_type='publish.failed',**context) if context else 'no_context'
        raise AssertionError((two,why,context.get('custom_rule_ref'),current.get('customRules')))
before=provider.create_count
assert proactive_tick(phone,10)==1 and provider.create_count==before+1
assert proactive_tick(phone,10)==0
custom_call=sql("SELECT id::text,reason_key FROM pr_phone_calls WHERE reason_key LIKE 'publish.failed:rule:%%' ORDER BY requested_at DESC LIMIT 1")[0]
assert rules.reason_ref(custom_call[1])==(rule_id,reviewed['version'])
assert phone.proactive_briefing(read_call(custom_call[0]))==draft['discuss']
phone.hangup(custom_call[0],live_seconds=0)
phone.save_preferences(wid,ONE,{'customRules':[{**reviewed,'discuss':'Explain the failure and next step','enabled':True}]})
assert not phone.settings(wid,ONE)['preferences']['customRules'][0]['enabled']
with connection() as db:
    three=service.notifications.emit(db.cursor(),workspace_id=wid,event_type='publish.failed',dedupe_key='custom-third',
                                     entity_type='post',entity_id='post-custom-1',actor=ONE,payload={'title':'Third post failure'})
    assert not any(d['channel']=='phone' for d in three['deliveries']),three
print('PASS custom phone rule review, same-post threshold, single fake call, spoken topic and edit revocation')

# Revocation removes identity/schedules; deletion cascades all phone data even when global switch is off.
phone.delete_number(wid,ONE)
assert not phone.settings(wid,ONE)['number']
assert not phone.settings(wid,ONE)['preferences']['enabled']
denied(lambda:phone.start_verification(wid,ONE,{'number':'+12025550123'}),429)
sql("UPDATE pr_phone_verification_limits SET last_sent_at=now()-interval '2 minutes' WHERE user_id=%s",ONE)
phone.start_verification(wid,ONE,{'number':'+12025550123'})
phone.confirm_verification(wid,ONE,{'code':'123456'})
phone.config.values['RAFII_PHONE_ENABLED']='0'
assert service.delete_account(wid,ONE,'DELETE')['workspaceDeleted']
for table in tables:
    assert sql('SELECT count(*) FROM public.'+table)[0][0]==0,table
print('PASS number revocation and account-deletion cascades with global egress disabled')
print(json.dumps({'execution':'local fake transport + actual Rafii runtime and PostgreSQL','status':'PASS','realCalls':0}))
