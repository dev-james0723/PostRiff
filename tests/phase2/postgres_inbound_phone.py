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

alice, wa = new_user(); bob, wb = new_user()
ca = service.ideas.create_conversation(wa, alice, 'Alice private conversation')['conversationId']
cb = service.ideas.create_conversation(wb, bob, 'Bob private conversation')['conversationId']
denied(lambda: inbound.issue(phone, wa, bob, {}), 403)
denied(lambda: inbound.issue(phone, wa, alice, {'conversationId': cb}), 404)
old = verify.auth_time; verify.auth_time = lambda *_: 0
denied(lambda: inbound.issue(phone, wa, alice, {}), 403)
verify.auth_time = old
ticket_a = inbound.issue(phone, wa, alice, {'conversationId': ca})
ticket_b = inbound.issue(phone, wb, bob, {'conversationId': cb})
assert not phone.settings(wa, alice)['number']  # SMS verification is not required for an authenticated incoming call.
assert ticket_a['code'] not in json.dumps(phone.settings(wa, alice))
assert ticket_a['code'] not in json.dumps(sql('SELECT code_hash FROM pr_phone_inbound_codes'))
assert not http_requests
denied(lambda: inbound.status(phone, wa, bob, ticket_a['id']), 403)
denied(lambda: inbound.issue(phone, wa, alice, {}), 429)
begin('call_alice'); begin('call_bob')
cid_a = inbound.authenticate(phone, 'call_alice', ticket_a['code'])
cid_b = inbound.authenticate(phone, 'call_bob', ticket_b['code'])
assert cid_a and cid_b and read(cid_a)['user_id'] == alice and read(cid_b)['user_id'] == bob
assert read(cid_a)['conversation_id'] == ca and read(cid_b)['conversation_id'] == cb
assert read(cid_a)['direction'] == 'inbound' and read(cid_a)['provider_call_ref'] == 'call_alice'
assert inbound.status(phone, wa, alice, ticket_a['id'])['state'] == 'used'
denied(lambda: phone.view(wb, bob, cid_a), 404)
ra, cap, _ = phone.scoped_runtime(cid_a)
denied(lambda: ra.service.repository.get(wb, cap), 403)
assert inbound.authenticate(phone, 'call_alice', ticket_a['code']) is None
before = len(http_requests); delivery.deliver(phone, cid_a); assert len(http_requests) == before
sql("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", wa, alice)
denied(lambda: ra.service.repository.get(wa, cap), 403)
done('call_alice', cid_a); done('call_bob', cid_b)
print('PASS account/conversation isolation, no SMS requirement, fresh login, one-use secret, scoped runtime revocation, no outbound egress')

u, w = new_user(); t = inbound.issue(phone, w, u, {})
sql("UPDATE pr_phone_inbound_codes SET expires_at=now()-interval '1 second' WHERE id=%s", t['id'])
begin('call_expired'); assert inbound.authenticate(phone, 'call_expired', t['code']) is None
assert sql('SELECT count(*) FROM pr_phone_calls WHERE user_id=%s', u) == [(0,)]
u, w = new_user(); t = inbound.issue(phone, w, u, {})
inbound.revoke(phone, w, u, t['id']); begin('call_revoked')
assert inbound.authenticate(phone, 'call_revoked', t['code']) is None
u, w = new_user(); t = inbound.issue(phone, w, u, {})
begin('call_guesses')
for _ in range(3): assert inbound.authenticate(phone, 'call_guesses', '0000') is None
assert inbound.authenticate(phone, 'call_guesses', t['code']) is None
u, w = new_user(); t = inbound.issue(phone, w, u, {})
begin('call_budget'); phone.config.values['RAFII_PHONE_DAILY_USD_MICRO'] = '0'
assert inbound.authenticate(phone, 'call_budget', t['code']) is None
assert sql('SELECT count(*) FROM pr_phone_calls WHERE user_id=%s', u) == [(0,)]
phone.config.values.pop('RAFII_PHONE_DAILY_USD_MICRO')
u, w = new_user(); t = inbound.issue(phone, w, u, {})
begin('call_race1'); begin('call_race2')
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda ref: inbound.authenticate(phone, ref, t['code']), ['call_race1', 'call_race2']))
assert sum(bool(x) for x in results) == 1
cid = next(x for x in results if x); done(read(cid)['provider_call_ref'], cid)
assert sql('SELECT count(*) FROM pr_phone_calls WHERE user_id=%s', u) == [(1,)]
print('PASS expired/revoked code, three guesses, budget rejection, concurrent replay has exactly one call and reservation set')

# Free provider/audio fixtures, but real same-conversation draft edit and signed HTTP lifecycle.
sql("UPDATE pr_phone_inbound_sessions SET started_at=now()-interval '2 hours'")
u, w = new_user(); conv = service.ideas.create_conversation(w, u, 'Phone edit')['conversationId']
draft = uuid.uuid4().hex
def seed(state, _):
    state['variants'] = [{'id': draft, 'platform': 'LinkedIn', 'language': 'English', 'text': 'Original piano practice draft.', 'revision': 1, 'needsReview': True, 'revisions': [], 'localPreferences': {}, 'openings': [], 'unknowns': [], 'createdAt': 1}]
    return state
service.repository.command(w, u, service.get(w, u)['revision'], seed)
edited = 'Small steps make practice possible.'
def reply(text): return [assistant_message(json.dumps({'answer': text, 'speakable': text, 'language': 'en', 'follow_ups': []}))]
models['rafii_manager'] = ScriptedModel([[function_call('draft_get', {'draftId': draft}, call_id='read')],
    [function_call('draft_edit', {'draftId': draft, 'revision': 1, 'text': edited}, call_id='write')], reply('Saved in this conversation, pending your publishing review.')])
connections = []; wires = []
class Wire:
    def __init__(self): self.queue, self.sent = asyncio.Queue(), []
    def __aiter__(self): return self
    async def __anext__(self): return await self.queue.get()
    async def send(self, event):
        self.sent.append(event)
        kind = event['type']
        if kind == 'session.start': await self.queue.put({'type': 'session.started', 'session': {'id': 'synthetic-inbound-live'}})
        elif kind == 'session.instructions.append': await self.queue.put({'type': 'session.output_audio.delta', 'delta': base64.b64encode(b'hello').decode()})
        elif kind == 'session.input_audio.append':
            await self.queue.put({'type': 'session.input_transcript.delta', 'delta': 'Shorten my piano draft to Small steps make practice possible.'})
            await self.queue.put({'type': 'session.delegation.created', 'delegation': {'id': 'inbound-edit', 'target': 'client'}})
        elif kind == 'session.commentary.append':
            await self.queue.put({'type': 'session.output_transcript.delta', 'delta': event['content']})
            await self.queue.put({'type': 'session.output_audio.delta', 'delta': base64.b64encode(b'saved').decode()})
            await self.queue.put({'type': 'session.closed', 'usage': {'seconds': 4}})
        elif kind == 'session.close': await self.queue.put({'type': 'session.closed', 'usage': {'seconds': 4}})
@asynccontextmanager
async def connect():
    connections.append(1); wire = Wire(); wires.append(wire); yield wire
app = create_app(service, phone, connect)
ref = 'call_media'
provider_calls[ref] = {'id': ref, 'direction': 'inbound', 'from': '+12025550199', 'to': '+12025550100', 'status': 'in-progress', 'duration': 0}
with TestClient(app) as client:
    headers = {'Authorization': 'Bearer ' + u, 'X-PostRiff-Request': 'founder-alpha'}
    response = client.post('/api/workspaces/' + w + '/phone/inbound-codes', json={'conversationId': conv}, headers=headers)
    assert response.status_code == 201, response.text
    assert 'no-store' in response.headers.get('cache-control', '')
    t = response.json()
    socket_headers = {'X-Dial-Signature': sign(values['DIAL_AUDIO_SIGNING_SECRET'], ref.encode())}
    with client.websocket_connect('/api/phone/dial/media/' + ref, headers=socket_headers) as socket:
        socket.send_json({'type': 'call_connected', 'call_id': ref, 'direction': 'inbound', 'from': '+12025550199', 'to': '+12025550100',
                          'formats': {'inbound': 'mulaw_8000', 'outbound': 'mulaw_8000'}, 'reconnect': False})
        socket.send_json({'type': 'media', 'payload': base64.b64encode(b'pre-auth private words').decode()})
        while socket.receive_json()['type'] != 'media': pass
        assert not connections, 'Greeting must not open Live'
        for digit in t['code']: socket.send_json({'type': 'dtmf', 'digit': digit})
        while socket.receive_json() != {'type': 'media', 'payload': base64.b64encode(b'hello').decode()}: pass
        socket.send_json({'type': 'media', 'payload': base64.b64encode(b'authenticated speech').decode()})
        frames = []
        while True:
            event = socket.receive_json(); frames.append(event)
            if event['type'] == 'end_call':
                provider_calls[ref].update(status='completed', duration=8)
                socket.send_json({'type': 'call_ended'}); break
        assert {'type': 'media', 'payload': base64.b64encode(b'saved').decode()} in frames
    status = inbound.status(phone, w, u, t['id']); cid = status['call']['id']
    deadline = time.monotonic() + 5
    while read(cid)['live_usage_seconds'] is None and time.monotonic() < deadline: time.sleep(.02)
    assert read(cid)['state'] == 'completed' and read(cid)['live_usage_seconds'] == 4
    assert service.get(w, u)['state']['variants'][0]['text'] == edited
    assert service.get(w, u)['state']['variants'][0]['needsReview']
    assert not service.get(w, u)['state']['phase2']['jobs']
    assert len(connections) == 1
    assert t['code'] not in json.dumps(wires[0].sent) and 'pre-auth private words' not in json.dumps(wires[0].sent)
    models['rafii_manager'].assert_complete()
    event = {'id': 'evt_inbound_end', 'type': 'call.ended', 'relatedObject': {'id': ref}, 'data': {'callId': ref, 'direction': 'inbound',
        'from': '+12025550199', 'to': '+12025550100', 'status': 'completed', 'durationSeconds': 8}}
    def callback(value):
        body = json.dumps(value).encode()
        return client.post('/api/phone/dial/events', content=body, headers={'Content-Type': 'application/json', 'X-Dial-Signature': sign(values['DIAL_WEBHOOK_SIGNING_SECRET'], body),
            'X-Dial-Event-ID': value['id'], 'X-Dial-Event-Type': value['type']})
    assert callback(event).status_code == 200
    assert callback(event).json()['duplicate']
    assert read(cid)['duration_seconds'] == 8
    for key in ('live_reservation_id', 'telephony_reservation_id'):
        assert sql("SELECT cost_state FROM pr_usage_ledger WHERE reservation_id=%s AND cost_state IN ('actual','released')", read(cid)[key])
    event['data']['direction'] = 'outbound'; event['data']['from'], event['data']['to'] = event['data']['to'], event['data']['from']
    event['id'] = 'evt_wrong_direction'
    assert callback(event).status_code == 404
    event['id'] = 'evt_unbound_end'
    event['data'].update(direction='inbound', to='+12025550100', **{'from': '+12025550199', 'callId': 'call_unbound'})
    event['relatedObject']['id'] = 'call_unbound'
    assert callback(event).json() == {'ignored': True}
    try:
        with client.websocket_connect('/api/phone/dial/media/call_unsigned'): pass
    except WebSocketDisconnect: pass
    else: raise AssertionError('Unsigned inbound WebSocket accepted')
    for ref, mutation in [('call_wrong_line', {'to': '+12025550200'}), ('call_reconnect', {'reconnect': True})]:
        with client.websocket_connect('/api/phone/dial/media/' + ref, headers={'X-Dial-Signature': sign(values['DIAL_AUDIO_SIGNING_SECRET'], ref.encode())}) as socket:
            socket.send_json({'type': 'call_connected', 'call_id': ref, 'direction': 'inbound', 'from': '+12025550199', 'to': '+12025550100',
                              'formats': {'inbound': 'mulaw_8000', 'outbound': 'mulaw_8000'}, **mutation})
            assert socket.receive_json() == {'type': 'end_call'}
    assert len(connections) == 1
print('PASS signed inbound greeting/keypad → same real agent draft edit → audio reply; no publishing; no secret/audio before auth; final event dedupe and usage')

# Server-only code/rate-limit tables, active-call exclusion and membership checks at use time.
for role in ('anon', 'authenticated'):
    for table in ('pr_phone_inbound_codes', 'pr_phone_inbound_sessions'):
        with connection() as db:
            db.execute('SET ROLE ' + role)
            try: db.execute('SELECT * FROM ' + table)
            except psycopg.errors.InsufficientPrivilege: db.rollback()
            else: raise AssertionError('Client role read phone sign-in material')
sql("UPDATE pr_phone_inbound_sessions SET started_at=now()-interval '2 hours'")
u, w = new_user(); t = inbound.issue(phone, w, u, {})
begin('call_active1'); first = inbound.authenticate(phone, 'call_active1', t['code']); assert first
sql("UPDATE pr_phone_inbound_codes SET created_at=now()-interval '1 minute' WHERE id=%s", t['id'])
t2 = inbound.issue(phone, w, u, {})
begin('call_active2'); assert inbound.authenticate(phone, 'call_active2', t2['code']) is None
assert inbound.status(phone, w, u, t2['id'])['state'] == 'ready', 'Failed admission must roll back code consumption'
assert sql('SELECT count(*) FROM pr_phone_calls WHERE user_id=%s', u) == [(1,)]
done('call_active1', first)
sql("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", w, u)
assert inbound.authenticate(phone, 'call_active2', t2['code']) is None
u, w = new_user(); t = inbound.issue(phone, w, u, {})
assert service.delete_account(w, u, 'DELETE')['workspaceDeleted']
assert sql('SELECT count(*) FROM pr_phone_inbound_codes WHERE id=%s', t['id']) == [(0,)]
phone.config.values['RAFII_PHONE_INBOUND_ENABLED'] = '0'
denied(lambda: inbound.issue(phone, wb, bob, {}), 409)
denied(lambda: inbound.begin(phone, 'call_disabled', '+12025550123'), 409)
phone.config.values['RAFII_PHONE_INBOUND_ENABLED'] = '1'
sql("UPDATE pr_phone_inbound_sessions SET started_at=now()-interval '2 hours'")
for n in range(3): assert inbound.begin(phone, 'call_throttle' + str(n), '+12025550444')
assert not inbound.begin(phone, 'call_throttle3', '+12025550444')
phone.config.values['RAFII_PHONE_INBOUND_AUTH_DAILY_USD_MICRO'] = '0'
assert not inbound.begin(phone, 'call_operator_budget', '+12025550555')
phone.config.values.pop('RAFII_PHONE_INBOUND_AUTH_DAILY_USD_MICRO')
sql("UPDATE pr_phone_inbound_sessions SET started_at=now()-interval '3 days'")
sql("UPDATE pr_phone_inbound_codes SET expires_at=now()-interval '2 days'")
with connection() as db: inbound.cleanup(phone, db.cursor())
assert sql('SELECT count(*) FROM pr_phone_inbound_codes') == [(0,)]
assert sql('SELECT count(*) FROM pr_phone_inbound_sessions') == [(0,)]
assert read(cid)['state'] == 'completed', 'Ephemeral cleanup must preserve settled call history'
print('PASS server-only RLS, active-call exclusion/rollback, revoked membership, account deletion, disabled flag, shared caller/operator limits, retention cleanup')
assert all(method == 'GET' for method, _ in http_requests)
print('PASS inbound phone integration: real local SQL/HTTP/WebSockets/agent; synthetic provider and model; zero paid calls')
