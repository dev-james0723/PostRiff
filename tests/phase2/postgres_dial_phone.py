"""Real PostgreSQL + signed Dial ASGI + shared Rafii commands; synthetic SMS/REST/Live only."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch
from pydantic import TypeAdapter
from openai.types.live.instructions_append_event_param import InstructionsAppendEventParam
from openai.types.live.commentary_append_event_param import CommentaryAppendEventParam

os.environ['OPENAI_AGENTS_DISABLE_TRACING']='1'
import psycopg
from agents.testing import ScriptedModel, assistant_message, function_call
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.agent_runtime_v2 import config
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.phone import contracts, delivery, store
from postriff_phase2.phone.providers.dial import DialProvider
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.asgi import create_app, create_lazy_app
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

DSN=os.environ['POSTRIFF_TEST_DSN']
USER=str(uuid.uuid4())
def connection():return psycopg.connect(DSN)
def verify(token):
    if token!=USER:raise AlphaError('Verified session required.',401)
    return token
verify.auth_time=lambda *_:time.time()
verify.session_id=lambda *_:'dial-local-session'
service=HostedWorkspaceService(connection,verify,vault=CredentialVault(CredentialVault.generate_key()))
with connection() as db:db.execute('INSERT INTO auth.users VALUES(%s)',(USER,))
wid=service.bootstrap(USER,'studio')['workspaceId']
approve_budgets(connection,wid)
models={}
def scripts(*steps):models['rafii_manager']=ScriptedModel(list(steps))
def reply(text):return [assistant_message(json.dumps({'answer':text,'speakable':text,'language':'en','follow_ups':[]}))]
cfg=config.RuntimeConfig.from_environment({'OPENAI_API_KEY':'synthetic-no-egress','RAFII_AGENT_V2_ENABLED':'1','RAFII_VOICE_ENABLED':'1','RAFII_SPECIALISTS_ENABLED':'1'})
runtime=AgentRuntimeService(service,cfg,model_factory=lambda _workload,name:models.setdefault(name,ScriptedModel([])))
values={'DIAL_API_KEY':'sk_live_synthetic','DIAL_PHONE_NUMBER':'+12025550100','DIAL_AUDIO_SIGNING_SECRET':'audio-local',
        'DIAL_WEBHOOK_SIGNING_SECRET':'webhook-local','DIAL_VERIFICATION_SECRET':'v'*32,'RAFII_PHONE_PUBLIC_BASE_URL':'https://phone.test',
        'RAFII_PHONE_ALLOWED_COUNTRY_CODES':'+1','RAFII_PHONE_USD_MICRO_PER_MINUTE':'10000','RAFII_PHONE_MAX_SECONDS':'60',
        'RAFII_PHONE_ENABLED':'1','RAFII_PHONE_OUTBOUND_ENABLED':'1','RAFII_PHONE_VERIFICATION_ENABLED':'1'}


class DialHTTP:
    def __init__(self):self.calls={};self.posts=0;self.ambiguous=False;self.sms=[]
    def __call__(self,method,path,fields=None,headers=None):
        if path=='/self-hosted':return 200,{'enabled':True,'access':'granted','activeMode':'audio','audio':{
            'wsUrl':'wss://phone.test/api/phone/dial/media','audioInboundFormat':'mulaw_8000','audioOutboundFormat':'mulaw_8000'}}
        if path=='/numbers':return 200,{'numbers':[{'number':'+12025550100','setupStatus':'ready','callingEnabled':True,'capabilities':['call','sms']}]}
        if path=='/account':return 200,{'limits':{'maxCallDurationSeconds':300}}
        if path=='/messages':self.sms.append(fields);return 201,{'message':{'id':'message_local'}}
        if path=='/calls' and method=='POST':
            self.posts+=1
            ref='call_'+str(self.posts)
            self.calls[ref]={'id':ref,'direction':'outbound','from':fields['fromNumber'],'to':fields['to'],
                'instruction':fields['outboundInstruction'],'status':'ringing','duration':0,'voiceRuntime':'self-hosted-audio'}
            return (0,{}) if self.ambiguous else (201,{'call':self.calls[ref]})
        if path=='/calls':return 200,{'calls':list(self.calls.values())}
        if path.startswith('/calls/'):return 200,{'call':self.calls.get(path.rsplit('/',1)[1],{})}
        raise AssertionError('Unexpected outbound request')


http=DialHTTP();provider=DialProvider(values,transport=http)
phone=service.phone=PhoneService(service,values,provider=provider,runtime=runtime)
def sql(query,*args):
    with connection() as db:
        cur=db.execute(query,args);return cur.fetchall() if cur.description else []
def read(cid):
    with connection() as db:return store.call(db.cursor(),cid)
def denied(fn,status):
    try:fn()
    except AlphaError as error:assert error.status==status,(error.status,str(error));return
    raise AssertionError('Unexpected permission')
def sign(secret,payload):
    at=str(int(time.time()));return 't='+at+',v1='+hmac.new(secret.encode(),at.encode()+b'.'+payload,hashlib.sha256).hexdigest()
def request(key,**extra):return phone.request(wid,USER,{'idempotencyKey':key,**extra})
def age():sql("UPDATE pr_phone_calls SET requested_at=now()-interval '6 minutes' WHERE user_id=%s",USER)
def finished(cid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        value=read(cid)
        if value['state'] in contracts.TERMINAL and value['live_usage_seconds'] is not None:return value
        time.sleep(.05)
    raise AssertionError(('Call did not settle',read(cid)['state'],read(cid)['live_usage_seconds']))

# Real private challenge storage, wrong-code limits, number-bound confirmation, no secret in settings.
with patch('postriff_phase2.phone.providers.dial.secrets.randbelow',return_value=123456):phone.start_verification(wid,USER,{'number':'+12025550123'})
denied(lambda:phone.confirm_verification(wid,USER,{'code':'000000'}),400)
phone.confirm_verification(wid,USER,{'code':'123456'})
assert sql('SELECT verification_ref,verification_attempts FROM pr_phone_numbers WHERE user_id=%s',USER)==[(None,2)]
phone.save_preferences(wid,USER,{'enabled':True,'quietStart':0,'quietEnd':0})
public=json.dumps(phone.settings(wid,USER))
assert '+12025550123' not in public and '123456' not in public and values['DIAL_API_KEY'] not in public
assert not phone.config.enabled('RAFII_PHONE_PROACTIVE_ENABLED') and not phone.config.enabled('RAFII_PHONE_SCHEDULED_ENABLED')

# Existing conversation and real draft command path.
draft=uuid.uuid4().hex
def seed(state,_actor):
    state['variants']=[{'id':draft,'platform':'LinkedIn','language':'English','text':'A long piano-practice opening.',
        'revision':1,'needsReview':True,'revisions':[],'localPreferences':{},'openings':[],'unknowns':[],'createdAt':1}]
    return state
service.repository.command(wid,USER,service.get(wid,USER)['revision'],seed)
conv=service.ideas.create_conversation(wid,USER,'Dial continuity')['conversationId']
scripts(reply('We will edit your piano draft.'))
runtime.turn(wid,USER,{'message':'Remember our piano draft for this call.','conversationId':conv,'idempotencyKey':uuid.uuid4().hex})
models['rafii_manager'].assert_complete()
call=request('dial-local-call',conversationId=conv);cid=call['id'];ref=read(cid)['provider_call_ref']
assert call['provider']=='dial' and call['state']=='ringing' and http.posts==1
assert request('dial-local-call',conversationId=conv)['id']==cid and http.posts==1


class LiveWire:
    def __init__(self):self.queue=asyncio.Queue();self.sent=[];self.auto_close=True
    def __aiter__(self):return self
    async def __anext__(self):return await self.queue.get()
    async def send(self,event):
        self.sent.append(event);kind=event['type']
        if kind=='session.instructions.append': TypeAdapter(InstructionsAppendEventParam).validate_python(event)
        if kind=='session.commentary.append': TypeAdapter(CommentaryAppendEventParam).validate_python(event)
        if kind=='session.start':await self.queue.put({'type':'session.started','session':{'id':'synthetic-dial-live'}})
        elif kind=='session.instructions.append':await self.queue.put({'type':'session.output_audio.delta','delta':base64.b64encode(b'fake-greeting').decode()})
        elif kind=='session.input_audio.append':
            await self.queue.put({'type':'session.input_transcript.delta','delta':'Shorten our piano draft to Small steps make practice possible.'})
            await self.queue.put({'type':'session.delegation.created','delegation':{'id':'dial-edit','target':'client'}})
        elif kind=='session.commentary.append':
            await self.queue.put({'type':'session.output_transcript.delta','delta':event['content']})
            await self.queue.put({'type':'session.output_audio.delta','delta':base64.b64encode(b'fake-result').decode()})
            if self.auto_close:await self.queue.put({'type':'session.closed','usage':{'seconds':4}})
        elif kind=='session.close':await self.queue.put({'type':'session.closed','usage':{'seconds':4}})


wire=None;connect_count=0
@asynccontextmanager
async def connect():
    global wire,connect_count
    connect_count+=1;wire=LiveWire();yield wire


def connected(ref):return {'type':'call_connected','call_id':ref,'direction':'outbound','from':'+12025550100','to':'+12025550123',
    'formats':{'inbound':'mulaw_8000','outbound':'mulaw_8000'},'instruction':http.calls[ref]['instruction'],'reconnect':False}
def socket_headers(ref):return {'X-Dial-Signature':sign(values['DIAL_AUDIO_SIGNING_SECRET'],ref.encode())}
app=create_lazy_app(values=values,application_factory=lambda:create_app(service,phone,connect,media_only=True))
api=TestClient(create_app(service,phone,connect))
edited='Small steps make practice possible.'
scripts([function_call('draft_get',{'draftId':draft},call_id='dial-read')],
        [function_call('draft_edit',{'draftId':draft,'revision':1,'text':edited},call_id='dial-write')],
        reply('I shortened our piano draft. It is saved in Rafii and still needs your publishing review.'))
with TestClient(app) as client,api:
    with __import__('contextlib').suppress(WebSocketDisconnect):
        with client.websocket_connect('/api/phone/dial/media/'+ref,headers={'X-Dial-Signature':'invalid'}) as socket:
            raise AssertionError('Unsigned socket accepted')
    assert connect_count==0
    with client.websocket_connect('/api/phone/dial/media/'+ref,headers=socket_headers(ref)) as socket:
        socket.send_json(connected(ref))
        socket.send_json({'type':'ping_pong','timestamp':42})
        socket.send_json({'type':'dtmf','digit':'1'})
        socket.send_json({'type':'media','payload':base64.b64encode(b'caller-audio').decode(),'seq':1})
        received=[]
        while True:
            value=socket.receive_json();received.append(value)
            if value['type']=='end_call':
                http.calls[ref].update(status='completed',duration=7)
                socket.send_json({'type':'call_ended','reason':'customer_hangup'})
                break
        assert {'type':'ping_pong','timestamp':42} in received
        assert {'type':'media','payload':base64.b64encode(b'fake-result').decode()} in received
    models['rafii_manager'].assert_complete()
    assert 'piano draft' in json.dumps(wire.sent[0])
    saved=service.get(wid,USER)['state']['variants'][0]
    assert saved['text']==edited and saved['revision']==2 and saved['needsReview']
    assert not service.get(wid,USER)['state']['phase2']['jobs']
    value=finished(cid)
    assert value['state']=='completed' and value['live_usage_seconds']==4
    assert sql('SELECT count(*) FROM pr_phone_delegations WHERE call_id=%s',cid)==[(1,)]
    assert sql('SELECT count(*) FROM pr_messages WHERE conversation_id=%s',conv)[0][0]>=4
    print('PASS signed Dial audio/keepalive → same Rafii conversation → real draft edit → audio reply → confirmed hang-up/usage; no publication')

    # Signed late duration and duplicate status deliveries use the existing event/settlement ledger.
    event={'id':'evt_dial_end','object':'event','type':'call.ended','version':1,'relatedObject':{'id':ref},'data':{
        'callId':ref,'direction':'outbound','from':'+12025550100','to':'+12025550123','status':'completed','durationSeconds':7}}
    def callback(event):
        body=json.dumps(event).encode()
        return api.post('/api/phone/dial/events',content=body,headers={'Content-Type':'application/json',
            'X-Dial-Signature':sign(values['DIAL_WEBHOOK_SIGNING_SECRET'],body),'X-Dial-Event-ID':event['id'],'X-Dial-Event-Type':event['type']})
    assert callback(event).status_code==200
    assert callback(event).json()['duplicate']
    assert read(cid)['duration_seconds']==7
    for name in ('live_reservation_id','telephony_reservation_id'):
        assert sql("SELECT cost_state FROM pr_usage_ledger WHERE reservation_id=%s AND cost_state IN ('actual','released')",read(cid)[name])==[('actual',)]
    stale=dict(event,id='evt_dial_old',type='call.status_changed',data={**event['data'],'status':{'state':'Ringing'}})
    assert callback(stale).status_code==200 and read(cid)['state']=='completed'
    tampered=json.dumps(event).encode()+b' '
    assert api.post('/api/phone/dial/events',content=tampered,headers={'X-Dial-Signature':sign(values['DIAL_WEBHOOK_SIGNING_SECRET'],json.dumps(event).encode())}).status_code==401
    assert api.post('/api/phone/dial/events',content=b'{}',headers={'Content-Length':'999999'}).status_code==413
    print('PASS real SQL signed callbacks, duplicate/out-of-order events, final duration and both usage settlements')

    # Lost create response is bound by exact call instruction using GET only, never another dial.
    age();http.ambiguous=True
    uncertain=request('dial-lost-response',conversationId=conv)
    assert uncertain['state']=='ambiguous';posts=http.posts
    delivery.deliver(phone,uncertain['id']);delivery.reconcile(phone,uncertain['id'])
    assert http.posts==posts and read(uncertain['id'])['state']=='ringing'
    uref=read(uncertain['id'])['provider_call_ref'];http.calls[uref].update(status='no-answer',duration=0)
    event.update(id='evt_dial_unanswered',relatedObject={'id':uref},data={**event['data'],'callId':uref,'status':'no-answer','durationSeconds':0})
    assert callback(event).status_code==200 and read(uncertain['id'])['state']=='no_answer'
    print('PASS accepted-but-lost response reconciliation without duplicate calls')

    # The HTTP/cron process cannot send frames on another worker's socket: ending state fences the live worker.
    age();http.ambiguous=False
    ending=request('dial-external-end',conversationId=conv);eref=read(ending['id'])['provider_call_ref']
    with client.websocket_connect('/api/phone/dial/media/'+eref,headers=socket_headers(eref)) as socket:
        socket.send_json(connected(eref))
        socket.send_json({'type':'dtmf','digit':'1'})
        while socket.receive_json()!= {'type':'media','payload':base64.b64encode(b'fake-greeting').decode()}:pass
        assert phone.end(wid,USER,ending['id'])=={'ended':False,'state':'ending'}
        while socket.receive_json()['type']!='end_call':pass
        http.calls[eref].update(status='completed',duration=2)
        socket.send_json({'type':'call_ended','reason':'customer_hangup'})
    assert finished(ending['id'])['state']=='completed'
    # A signed reconnect must not create a second voice session or replay agent mutations.
    before=connect_count
    with client.websocket_connect('/api/phone/dial/media/'+eref,headers=socket_headers(eref)) as socket:
        meta=connected(eref);meta['reconnect']=True;socket.send_json(meta)
        assert socket.receive_json()=={'type':'end_call'}
    assert connect_count==before
    print('PASS cross-worker end signal, closed-call tool fencing and reconnect refuses duplicate sessions')

    # A person who declines never opens a Live session or permits access to the conversation.
    age();declined=request('dial-human-declines',conversationId=conv);dref=read(declined['id'])['provider_call_ref']
    before=connect_count
    with client.websocket_connect('/api/phone/dial/media/'+dref,headers=socket_headers(dref)) as socket:
        socket.send_json(connected(dref));socket.send_json({'type':'dtmf','digit':'2'})
        while socket.receive_json()['type']!='end_call':pass
        http.calls[dref].update(status='completed',duration=2)
        socket.send_json({'type':'call_ended','reason':'customer_hangup'})
    value=finished(declined['id'])
    assert value['state']=='declined' and value['media_claimed_at'] is None and value['live_usage_seconds']==0
    assert connect_count==before
    print('PASS declined/voicemail guard: generic prompt only, no Live session or private workspace access')

# A carrier hang-up says nothing about voice success. Exercise both callback orders.
for carrier_first in (True, False):
    age();failed_call=request('dial-live-failure-'+str(carrier_first));fcid=failed_call['id']
    sql("UPDATE pr_phone_calls SET state='live',answered_at=now(),media_claimed_at=now() WHERE id=%s",fcid)
    if carrier_first: phone.finish(fcid,'completed',11,live_seconds=1)
    phone.record_media_failure(fcid)
    phone.finish(fcid,'completed',11,live_seconds=1)
    assert read(fcid)['state']=='failed' and read(fcid)['failure_class']=='live_failed'
    public=store.public_call(read(fcid))
    assert 'phone connected' in public['failureMessage'].lower()
    assert sql("SELECT status,artifact#>>'{voice,state}' FROM pr_agent_runs WHERE id=%s",read(fcid)['voice_run_id'])==[('failed','failed')]
    assert read(fcid)['duration_seconds']==11 and read(fcid)['live_usage_seconds']==1
print('PASS media failure survives carrier-completed callbacks in either order; duration and usage still reconcile')

print('PASS Dial PostgreSQL acceptance; execution=synthetic providers and model, real local database and agent commands')

# Failed setup checks never consume a fixed daily manual-call allowance. Exercise
# request-time AND dispatch-time policy with the real SQL ledger, no provider POST.
previous_posts=http.posts
provider.transport=lambda *_args,**_kwargs:(403,{'code':'cloudflare_1010'})
for attempt in range(7):
    call=request('dial-network-retry-'+str(attempt))
    assert call['state']=='failed',call
    assert read(call['id'])['failure_class']=='provider_transport',read(call['id'])
assert http.posts==previous_posts
assert sql("SELECT count(*) FROM pr_phone_calls WHERE user_id=%s AND idempotency_key LIKE 'dial-network-retry-%%'",USER)==[(7,)]
print('PASS seven same-day manual retries after network rejection; SQL dispatch, safe reason, no provider POST')
