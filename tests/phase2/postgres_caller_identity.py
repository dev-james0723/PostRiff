"""Real SQL/HTTP/signed ASGI/agent mutations; all telephony and model transports are synthetic."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

os.environ['OPENAI_AGENTS_DISABLE_TRACING'] = '1'
import psycopg
from agents.testing import ScriptedModel, assistant_message, function_call
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.agent_runtime_v2 import config
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
from postriff_phase2.phone import inbound, store, delivery, contracts
from postriff_phase2.phone.service import PhoneService
from postriff_phase2.phone.providers.dial import DialProvider
from postriff_phase2.phone.asgi import create_app
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

DSN = os.environ['POSTRIFF_TEST_DSN']
users = set()
def connection(): return psycopg.connect(DSN)
def verify(token):
    if token not in users: raise AlphaError('Sign in.', 401)
    return token
verify.auth_time = lambda *_: time.time()
verify.session_id = lambda *_: 'synthetic-inbound-session'
class Identity:
    def delete_user(self, _principal): return True
service = HostedWorkspaceService(connection, verify, vault=CredentialVault(CredentialVault.generate_key()), identity=Identity())
def sql(query, *args):
    with connection() as db:
        cur = db.execute(query, args)
        return cur.fetchall() if cur.description else []
def new_user():
    user = str(uuid.uuid4()); users.add(user)
    sql('INSERT INTO auth.users VALUES(%s)', user)
    workspace = service.bootstrap(user, 'studio')['workspaceId']
    approve_budgets(connection, workspace)
    return user, workspace
def denied(work, status):
    try: work()
    except AlphaError as error: assert error.status == status, (error.status, str(error)); return
    raise AssertionError('Unexpected permission')
models = {}
cfg = config.RuntimeConfig.from_environment({'OPENAI_API_KEY': 'synthetic-inbound-no-egress', 'RAFII_AGENT_V2_ENABLED': '1', 'RAFII_VOICE_ENABLED': '1', 'RAFII_SPECIALISTS_ENABLED': '1'})
runtime = AgentRuntimeService(service, cfg, model_factory=lambda _, name: models.setdefault(name, ScriptedModel([])))
values = {'DIAL_API_KEY': 'sk_live_synthetic_' + uuid.uuid4().hex, 'DIAL_PHONE_NUMBER': '+12025550100',  # pragma: allowlist secret -- generated fixture, HTTP transport injected below
          'DIAL_AUDIO_SIGNING_SECRET': uuid.uuid4().hex, 'DIAL_WEBHOOK_SIGNING_SECRET': uuid.uuid4().hex,
          'DIAL_VERIFICATION_SECRET': uuid.uuid4().hex, 'RAFII_PHONE_PUBLIC_BASE_URL': 'https://phone.test',
          'RAFII_PHONE_USD_MICRO_PER_MINUTE': '10000', 'RAFII_PHONE_MAX_SECONDS': '60',
          'RAFII_PHONE_ENABLED': '1', 'RAFII_PHONE_INBOUND_ENABLED': '1'}
provider_calls, http_requests = {}, []
def http(method, path, fields=None, headers=None):
    http_requests.append((method, path))
    assert method == 'GET' and path.startswith('/calls/'), 'No outgoing call/SMS or account mutation is allowed'
    return 200, {'call': provider_calls.get(path.rsplit('/', 1)[-1], {})}
provider = DialProvider(values, transport=http)
phone = service.phone = PhoneService(service, values, provider=provider, runtime=runtime)
def begin(ref):
    assert inbound.begin(phone, ref, '+1202555' + str(len(provider_calls)).zfill(4))
    provider_calls[ref] = {'id': ref, 'direction': 'inbound', 'to': '+12025550100', 'from': '+12025550123', 'status': 'in-progress', 'duration': 0}
def done(ref, cid):
    provider_calls[ref].update(status='completed', duration=5)
    phone.finish(cid, 'completed', 5, live_seconds=0)
def read(cid):
    with connection() as db: return store.call(db.cursor(), cid)
def sign(secret, payload):
    timestamp = str(int(time.time()))
    return 't=' + timestamp + ',v1=' + hmac.new(secret.encode(), timestamp.encode() + b'.' + payload, hashlib.sha256).hexdigest()

from postriff_phase2.phone import call_auth
from postriff_phase2.hosted_identity import verified_session_id
from unittest.mock import patch

# Supabase is replaced at its existing identity seam. No biometrics/provider calls in this suite.
def jwt(user, *, timestamp=None, session=None, method='passkey'):
    claims = {'sub': user, 'session_id': session or 'proof-'+uuid.uuid4().hex, 'aal': 'aal1', 'iat': time.time(),
              'amr': [{'method': method, 'timestamp': int(time.time() if timestamp is None else timestamp)}]}
    return 'synthetic.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.signature'
old_verify = verify
def auth(token):
    if token.startswith('synthetic.'):
        claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'=='))
        return old_verify(claims['sub'])
    return old_verify(token)
auth.auth_time = lambda *_: time.time()
auth.session_id = lambda token,u: verified_session_id(token,u) if token.startswith('synthetic.') else 'caller-identity-synthetic-session'
auth.aal = lambda *_: 'aal2'
auth.proof = auth
service.repository.verify_session = auth
service.public_base_url = 'https://rafii.test'
class Passkeys(Identity):
    def __init__(self): self.passkeys={}
    def registered_passkeys(self,user): return [{'id':p} for p in self.passkeys.get(user,[])]
identity=service.identity=Passkeys()
from postriff_phase2.notifications.service import NotificationService
service.notifications=NotificationService(service, {})
service.notifications.enabled=lambda:True
service.notifications.push_enabled=lambda:False


def setup():
    # Reset admission count fixture windows, never production records.
    sql("UPDATE pr_phone_inbound_sessions SET started_at=now()-interval '2 hours'")
    u,w=new_user(); t=inbound.issue(phone,w,u,{})
    caller='+1202'+str(int(uuid.uuid4().hex[:7],16)).zfill(7)
    ref='pair_'+uuid.uuid4().hex
    assert inbound.begin(phone,ref,caller)
    cid=inbound.authenticate(phone,ref,t['code']);assert cid
    phone.finish(cid,'completed',1,live_seconds=0)
    route=call_auth.trusted(phone,w,u)['callers'][0]['id']
    assert not any(x in json.dumps(call_auth.trusted(phone,w,u)) for x in (caller,t['code']))
    passkey=str(uuid.uuid4());identity.passkeys[u]=[passkey]
    return u,w,caller,route,passkey

def repeat(u,caller):
    ref='repeat_'+uuid.uuid4().hex
    assert inbound.begin(phone,ref,caller)
    c=call_auth.create(phone,ref);assert c
    assert call_auth.create(phone,ref)==c
    assert call_auth.consume(phone,ref,c) is None
    assert sql('SELECT call_id FROM pr_phone_inbound_sessions WHERE provider_call_ref=%s',ref)==[(None,)]
    return ref,c

def approve(u,c,_passkey=None,*,proof=None):
    return call_auth.approve(phone,u,c,{'passkeyToken':proof or jwt(u)})

u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
other,ow=new_user()
denied(lambda:call_auth.status(phone,other,c),404)
denied(lambda:call_auth.approve(phone,other,c,{}),404)
denied(lambda:call_auth.approve(phone,u,c,{}),409) # the normal signed-in session is not a passkey proof
denied(lambda:approve(u,c,factor,proof=jwt(u,timestamp=1)),409)
denied(lambda:approve(u,c,factor,proof=jwt(other)),409)
assert approve(u,c,factor)['state']=='approved'
assert call_auth.consume(phone,'different-provider-call',c) is None
with ThreadPoolExecutor(max_workers=2) as pool:
    result=list(pool.map(lambda _:call_auth.consume(phone,ref,c),range(2)))
assert sum(bool(v) for v in result)==1
assert call_auth.poll(phone,ref,c)=='consumed'
denied(lambda:call_auth.approve(phone,u,c,{}),409)
assert call_auth.consume(phone,ref,c) is None
print('PASS trusted route only, exact call binding, fresh passkey AMR not iat, wrong user, atomic racing consumption, replay')

for mode in ('expire','hangup','revoke','factor','membership','session','deny','cancel'):
    u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
    if mode not in ('deny','cancel'): approve(u,c,factor)
    if mode=='expire': sql("UPDATE pr_phone_auth_challenges SET expires_at=created_at+interval '1 millisecond',created_at=created_at-interval '2 seconds' WHERE id=%s",c);phone.clock=lambda:time.time()+2
    elif mode=='hangup': inbound.ended(phone,ref)
    elif mode=='revoke': call_auth.trusted(phone,w,u,revoke=route,proof_token=jwt(u))
    elif mode=='factor': identity.passkeys[u]=[]
    elif mode=='membership': sql("UPDATE pr_memberships SET status='revoked' WHERE user_id=%s AND workspace_id=%s",u,w)
    elif mode=='session': sql('INSERT INTO pr_session_revocations(user_id,session_id) SELECT user_id,approved_session_id FROM pr_phone_auth_challenges WHERE id=%s',c)
    else: call_auth.dismiss(phone,u,c,mode)
    assert call_auth.consume(phone,ref,c) is None, mode
    phone.clock=time.time
    assert sql('SELECT call_id FROM pr_phone_inbound_sessions WHERE provider_call_ref=%s',ref)==[(None,)]
print('PASS expiry, hangup, route/factor/membership/session revocation, deny, cancel: no admission')

u,w,caller,route,factor=setup()
sql("UPDATE pr_phone_inbound_codes SET created_at=now()-interval '1 minute' WHERE user_id=%s",u)
old_code=inbound.issue(phone,w,u,{})
ref,c=repeat(u,caller)
call_auth.dismiss(phone,u,c,'fallback');assert call_auth.fallback(phone,ref)
assert inbound.authenticate(phone,ref,old_code['code']) is None
sql("UPDATE pr_phone_inbound_codes SET created_at=now()-interval '1 minute' WHERE user_id=%s",u)
t=inbound.issue(phone,w,u,{})
assert inbound.authenticate(phone,ref,t['code'])
assert call_auth.poll(phone,ref,c)=='fallback'
# Ambiguous caller route cannot even create a challenge.
u2,w2=new_user()
sql('INSERT INTO pr_phone_trusted_callers(user_id,workspace_id,caller_hash,verified_at) VALUES(%s,%s,%s,now())',u2,w2,inbound.digest(phone,'caller',caller))
ref2='ambiguous_'+uuid.uuid4().hex
assert inbound.begin(phone,ref2,caller);assert call_auth.create(phone,ref2) is None
print('PASS new-code recovery, ambiguous mapping fallback, caller ID cannot select an account')

u,w,caller,route,factor=setup()
ref='no_notice_'+uuid.uuid4().hex
assert inbound.begin(phone,ref,caller)
with patch.object(service.notifications,'enabled',return_value=False):
    assert call_auth.create(phone,ref) is None
assert sql('SELECT count(*) FROM pr_phone_auth_challenges WHERE provider_call_ref=%s',ref)==[(0,)]
with patch.object(service.notifications,'emit',return_value={'deliveries':[]}):
    assert call_auth.create(phone,ref) is None
assert sql('SELECT state FROM pr_phone_auth_challenges WHERE provider_call_ref=%s',ref)==[('fallback',)]
# All waiting exposure counts against subsequent signed admissions, including when the
# bootstrap call has already been funded. Never silently spend outside the operator cap.
from postriff_phase2.phone.code_speech import RESERVE_USD_MICRO
original_config=phone.config
failed,total=sql("SELECT count(*) FILTER(WHERE call_id IS NULL),count(*) FROM pr_phone_inbound_sessions WHERE started_at>now()-interval '1 day'")[0]
base_exposure=(failed+1)*phone.config.telephony_rate+(total+1)*RESERVE_USD_MICRO
phone.config=type(original_config)({**values,'RAFII_PHONE_INBOUND_AUTH_DAILY_USD_MICRO':str(base_exposure)})
assert not inbound.begin(phone,'budget_'+uuid.uuid4().hex,'+12025550999')
phone.config=original_config
print('PASS missing/disabled notification falls back; operator admission budget includes repeat waiting')

u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
approve(u,c,factor)
call_auth.dismiss(phone,u,c,'deny')
ref2='fatigue_'+uuid.uuid4().hex
assert inbound.begin(phone,ref2,caller);assert call_auth.create(phone,ref2) is None
assert not call_auth.fallback(phone,ref)
for role in ('anon','authenticated'):
    for table in ('pr_phone_trusted_callers','pr_phone_auth_challenges','pr_phone_passkey_proof_uses'):
        with connection() as db:
            db.execute('SET ROLE '+role)
            try: db.execute('SELECT * FROM '+table)
            except psycopg.errors.InsufficientPrivilege: db.rollback()
            else: raise AssertionError('Browser role can access server table')
assert sql("SELECT count(*) FROM pg_class WHERE relname IN ('pr_phone_trusted_callers','pr_phone_auth_challenges','pr_phone_passkey_proof_uses') AND relrowsecurity AND relforcerowsecurity")==[(3,)]
assert sql('SELECT count(*) FROM pr_phone_passkey_proof_uses WHERE user_id=%s',u)==[(1,)]
assert service.delete_account(w,u,'DELETE')['workspaceDeleted']
assert sql('SELECT count(*) FROM pr_phone_auth_challenges WHERE id=%s',c)==[(0,)]
assert sql('SELECT count(*) FROM pr_phone_trusted_callers WHERE id=%s',route)==[(0,)]
assert sql('SELECT count(*) FROM pr_phone_passkey_proof_uses WHERE user_id=%s',u)==[(0,)]
print('PASS deny suppression, forced RLS, browser grants denied, deletion cascades')
print('PASS caller identity PostgreSQL: synthetic Supabase/provider, no network effects')

# A cancellation/hang-up during remote passkey-session verification wins. No DB locks held over I/O.
u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
original=auth.proof
calls=[]
def hanging_up(proof):
    calls.append(1);inbound.ended(phone,ref);return original(proof)
with patch.object(auth,'proof',side_effect=hanging_up):
    denied(lambda:approve(u,c,factor),409)
assert calls==[1] and call_auth.consume(phone,ref,c) is None

# A proof session may not be the app's ordinary authorization session.
u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
denied(lambda:approve(u,c,factor,proof=jwt(u,session='caller-identity-synthetic-session')),409)

# Three syntactically valid but failed/uncertain passkey proofs consume the ceremony cap.
u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
for bad in (jwt(u,timestamp=1),jwt(u,method='mfa/webauthn'),jwt(other)):
    denied(lambda bad=bad:approve(u,c,factor,proof=bad),409)
denied(lambda:approve(u,c,factor),409)
assert sql('SELECT ceremony_attempts FROM pr_phone_auth_challenges WHERE id=%s',c)==[(3,)]
print('PASS in-flight hangup invalidation, distinct proof session, failed-proof accounting, three-ceremony cap')

# Exact same passkey-created session cannot approve call B even when the user/passkey are identical.
u,w,caller,route,factor=setup();ref,c=repeat(u,caller)
sql("UPDATE pr_phone_auth_challenges SET created_at=created_at-interval '2 minutes' WHERE id=%s",c)
ref2,c2=repeat(u,caller)
shared_proof=jwt(u)
assert approve(u,c,factor,proof=shared_proof)['state']=='approved'
denied(lambda:approve(u,c2,factor,proof=shared_proof),409)
denied(lambda:call_auth.trusted(phone,w,u,revoke=route,proof_token=shared_proof),409)
assert call_auth.trusted(phone,w,u)['callers'][0]['id']==route
assert call_auth.consume(phone,ref2,c2) is None
# Transactional, private-free notification once per exact call; no email/SMS/phone delivery.
notices=sql("SELECT e.payload,d.user_id::text,d.channel FROM pr_notification_events e JOIN pr_notification_deliveries d ON d.event_id=e.id WHERE e.dedupe_key=%s",'phone-auth:'+c2)
assert notices and all(n[1]==u and n[2] in ('in_app','push') for n in notices)
assert any(n[2]=='in_app' for n in notices)
assert notices[0][0]['title']=='Verify this Rafii agent call'
assert notices[0][0]['detail']=='Tap to verify with Face ID, Touch ID, Windows Hello, or a security key. If you did not start it, do not approve.'
assert notices[0][0]['href']=='/app/phone/verify-call?challenge='+c2
assert caller not in json.dumps(notices) and inbound.digest(phone,'caller',caller) not in json.dumps(notices)
assert sql('SELECT count(*) FROM pr_notification_events WHERE dedupe_key=%s','phone-auth:'+c2)==[(1,)]
print('PASS cross-action passkey-session replay rejection; exact-user biometric push deep link; no code/caller/hash/private payload; no extra channels')

# HTTP through normal origin/token guards; uses the same service calls and no-store responses.
app=create_app(service,phone)
with TestClient(app) as client:
    headers={'Authorization':'Bearer '+u,'X-PostRiff-Request':'founder-alpha'}
    response=client.get('/api/phone/verify-call/'+c2,headers=headers)
    assert response.status_code==200,response.text
    assert 'no-store' in response.headers['cache-control']
    assert not any(k in response.json() for k in ('caller_hash','provider_call_ref','factor_challenge_id','factor_id'))
    assert client.get('/api/phone/verify-call/'+c2,headers={**headers,'Authorization':'Bearer '+other}).status_code==404
    assert client.post('/api/phone/verify-call/'+c2+'/deny',json={},headers={**headers,'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/phone/verify-call/'+c2+'/deny',json={},headers=headers).json()['state']=='denied'
print('PASS HTTP authentication, wrong-user denial, origin guard, no-store, safe display metadata')

# Signed repeat-call media → exact HTTP passkey ceremony → private Live. Real DB/ASGI, fake provider.
u,w,caller,route,factor=setup()
connections=[];wires=[]
class Wire:
    def __init__(self): self.queue=asyncio.Queue();self.sent=[]
    def __aiter__(self): return self
    async def __anext__(self): return await self.queue.get()
    async def send(self,event):
        self.sent.append(event)
        if event['type']=='session.start': await self.queue.put({'type':'session.started','session':{'id':'synthetic-repeat-live'}})
        elif event['type']=='session.instructions.append': await self.queue.put({'type':'session.output_audio.delta','delta':base64.b64encode(b'authenticated greeting').decode()})
        elif event['type']=='session.close': await self.queue.put({'type':'session.closed','usage':{'seconds':1}})
@asynccontextmanager
async def live_connection():
    connections.append(True);wire=Wire();wires.append(wire);yield wire
ref='media_repeat_'+uuid.uuid4().hex
provider_calls[ref]={'id':ref,'direction':'inbound','from':caller,'to':provider.originating_number,'status':'in-progress','duration':0}
with TestClient(create_app(service,phone,live_connection)) as client:
    with client.websocket_connect('/api/phone/dial/media/'+ref,headers={'X-Dial-Signature':sign(values['DIAL_AUDIO_SIGNING_SECRET'],ref.encode())}) as socket:
        socket.send_json({'type':'call_connected','call_id':ref,'direction':'inbound','from':caller,'to':provider.originating_number,'formats':{'inbound':'mulaw_8000','outbound':'mulaw_8000'},'reconnect':False})
        while socket.receive_json()['type']!='media': pass
        assert not connections
        socket.send_json({'type':'media','payload':base64.b64encode(b'private pre-auth audio').decode()})
        for digit in '123456789012*': socket.send_json({'type':'dtmf','digit':digit})
        challenge=sql('SELECT id::text FROM pr_phone_auth_challenges WHERE provider_call_ref=%s',ref)[0][0]
        headers={'Authorization':'Bearer '+u,'X-PostRiff-Request':'founder-alpha'}
        data=client.post('/api/phone/verify-call/'+challenge+'/approve',json={'passkeyToken':jwt(u)},headers=headers)
        assert data.status_code==200,data.text
        while socket.receive_json()!={'type':'media','payload':base64.b64encode(b'authenticated greeting').decode()}: pass
        assert len(connections)==1
        provider_calls[ref].update(status='completed',duration=1)
        socket.send_json({'type':'call_ended'})
    assert call_auth.poll(phone,ref,challenge)=='consumed'
    assert not any('private pre-auth audio' in json.dumps(w.sent) or base64.b64encode(b'private pre-auth audio').decode() in json.dumps(w.sent) for w in wires)
print('PASS signed repeat media + HTTP passkey proof, no caller-ID/DTMF bypass, no Live/pre-auth audio before consumed challenge')
