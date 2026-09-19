"""Saved interview, proposal-only changes, live roles, stale answer replay and owner activation."""
import copy
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.onboarding_chat import respond

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
TWO = '00000000-0000-0000-0000-000000000002'
def connection(): return psycopg.connect(DSN)
def verify(token): return ONE if token == 'one' else TWO
verify.session_id = lambda token, principal: 'session-test-0123456789abcdef'
verify.auth_time = lambda token, principal: __import__('time').time()
service = HostedWorkspaceService(connection, verify)
snap = service.bootstrap('one', 'studio')
wid = snap['workspaceId']
service.ideas.researcher = None
for action, payload in [('mode',{'mode':'personal'}),('context',{'purpose':'Original purpose','audience':'Original audience'}),('profile_propose',{'tone':'warm'}),('profile_decide',{'decision':'approve'})]:
    service.mutate(wid,'one',service.get(wid,'one')['revision'],action,payload)
with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active') ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='editor',status='active'",(wid,TWO))
conversation = service.ideas.create_conversation(wid, 'two', 'Voice interview')
cid = conversation['conversationId']
before = copy.deepcopy(service.get(wid,'one')['state'])
message = respond(service.ideas,wid,'two',cid,{'expectedSeq':0})
answers={'mode':'business','purpose':'Explain useful skills','audience':'Curious beginners','subject':'A studio','tone':'direct','writing':''}
while not message['body']['onboarding']['complete']:
    question = message['body']['onboarding']['question']
    key = question['key']
    seq = message['seq']
    if key == 'confirm':
        current = service.get(wid,'one')['state']
        assert current['brandHub'] == before['brandHub']
        assert current['speaker'] == before['speaker']
    message = respond(service.ideas,wid,'two',cid,{'expectedSeq':seq,'answer':answers.get(key,'propose')})
    try:
        respond(service.ideas,wid,'two',cid,{'expectedSeq':seq,'answer':'replay'})
        raise AssertionError('stale answer accepted')
    except AlphaError as error: assert error.status == 409
    restored = service.ideas.messages(wid,'two',cid)['messages'][-1]
    assert restored['body'] == message['body']
after = service.get(wid,'one')['state']
assert after['speaker']['activeRevision'] == before['speaker']['activeRevision']
assert after['brandHub'] == before['brandHub']
assert after['variants'] == before['variants']
assert after['phase2']['jobs'] == before['phase2']['jobs']
assert after['speaker']['provisional']['brandContext']['purpose'] == answers['purpose']
try:
    service.mutate(wid,'two',service.get(wid,'two')['revision'],'profile_decide',{'decision':'approve'})
    raise AssertionError('editor activated voice')
except AlphaError as error: assert error.status == 403
service.mutate(wid,'one',service.get(wid,'one')['revision'],'profile_decide',{'decision':'approve'})
after = service.get(wid,'one')['state']
assert after['brandHub']['purpose'] == answers['purpose']
assert after['speaker']['activeRevision'] != before['speaker']['activeRevision']
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_agent_runs WHERE workspace_id=%s',(wid,)).fetchone()[0] == 0
    db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(wid,TWO))
try:
    respond(service.ideas,wid,'two',cid,{'expectedSeq':message['seq'],'answer':'propose'})
    raise AssertionError('viewer answered')
except AlphaError as error: assert error.status == 403
try:
    respond(service.ideas,wid,'prt_'+'a'*43,cid,{'expectedSeq':0})
    raise AssertionError('token onboarding allowed')
except AlphaError as error: assert error.status == 403
print('PASS: durable answers, stale replay, proposal-only voice/context, owner activation, viewer/token denial, zero agent runs')
