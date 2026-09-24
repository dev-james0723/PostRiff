"""Durable managed run, unknown cost, replay and late-cancel settlement. No external I/O."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.model_runtime import ServerModelRuntime

DSN='host=127.0.0.1 port=55438 dbname=postgres'
ONE='00000000-0000-0000-0000-000000000001'
def connection(): return psycopg.connect(DSN)
def verify(token): return ONE
verify.session_id=lambda *_:'consumer-model-test-session'
verify.auth_time=lambda *_:__import__('time').time()
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2]/'migrations/postriff/016_api_tokens.sql').read_text())
service=HostedWorkspaceService(connection,verify)
snapshot=service.bootstrap('one','studio'); wid=snapshot['workspaceId']
cid=service.ideas.create_conversation(wid,'one','model safety')['conversationId']
seen=[]
def failing(method,url,**kwargs):
    # Another connection must already see the run and reservation before network I/O.
    with connection() as db:
        run=db.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key='uncertain-model'",(wid,)).fetchone()
        assert run, 'provider was called before run commit'
        assert db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE run_id::text=%s AND kind='reserve'",run).fetchone()[0]==1
    seen.append(run[0]); raise TimeoutError('synthetic transport timeout')
runtime=ServerModelRuntime('synthetic',transport=failing)
service.ideas.runtimes=[runtime]
payload={'model':runtime.model,'text':'Write a short question about music for Threads.','sourceIds':[],'idempotencyKey':'uncertain-model','destinations':[{'platform':'Threads','language':'zh-Hant'}]}
from consumer_fixtures import approve_budgets
# The presence of a gateway key does not approve either spending budget.
for scope in (None, 'global', 'workspace:'+wid):
    if scope:
        approve_budgets(connection,wid)
        with connection() as db:db.execute("UPDATE public.pr_budgets SET status='candidate' WHERE scope=%s",(scope,))
    try:service.ideas.turn(wid,'one',cid,{**payload,'idempotencyKey':'unapproved-budget'})
    except AlphaError as error:assert error.status==402
    else:raise AssertionError('unapproved spending budget allowed model I/O')
    assert seen==[]
approve_budgets(connection,wid)
try: service.ideas.turn(wid,'one',cid,payload)
except AlphaError as e: assert e.status==502
else: raise AssertionError('failure hidden')
repeat=service.ideas.turn(wid,'one',cid,payload)
assert repeat['status']=='failed' and len(seen)==1
with connection() as db:
    assert db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE run_id::text=%s AND cost_state='estimated_unknown'",(seen[0],)).fetchone()[0]==1
    assert db.execute("SELECT reserved_usd_micro FROM public.pr_budgets WHERE scope=%s",('workspace:'+wid,)).fetchone()[0]>0

# Reconciliation is terminal once, even with a different key/outcome.
with connection() as db, db.cursor() as cur:
    reservation=db.execute("SELECT id::text FROM public.pr_usage_ledger WHERE run_id::text=%s AND kind='reserve'",(seen[0],)).fetchone()[0]
    service.ideas.ledger.settle(cur,wid,reservation,'failed',25000)
    first=db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM public.pr_budgets WHERE scope=%s",('workspace:'+wid,)).fetchone()
    service.ideas.ledger.settle(cur,wid,reservation,'completed',900000,'different-key')
    assert first==db.execute("SELECT spent_usd_micro,reserved_usd_micro FROM public.pr_budgets WHERE scope=%s",('workspace:'+wid,)).fetchone()
    assert first==(25000,0)

# Missing provider usage must retain unknown cost, not manufacture zero.
def no_usage(*args,**kwargs):
    import json
    return {'status':200,'body':{'choices':[{'message':{'content':json.dumps({'variants':[{'platform':'Threads','language':'zh-Hant','text':'你喜歡甚麼音樂？','sourceIds':[],'unknowns':[],'warnings':[]}]})}}]}}
runtime.transport=no_usage
unknown=service.ideas.turn(wid,'one',cid,{**payload,'idempotencyKey':'no-usage'})
assert unknown['status']=='completed'
assert unknown['usage']['costUsd'] is None and unknown['usage']['ledgerCostState']=='estimated_unknown'

# A cancellation during the call is visible (no transaction blocks it); late text is discarded.
def cancelled(*args,**kwargs):
    with connection() as db:
        run=db.execute("SELECT id::text FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key='cancel-late'",(wid,)).fetchone()[0]
    service.ideas.cancel(wid,'one',run)
    result=no_usage();result['body']['usage']={'cost':0.01,'prompt_tokens':100,'completion_tokens':20}
    return result
runtime.transport=cancelled
late=service.ideas.turn(wid,'one',cid,{**payload,'idempotencyKey':'cancel-late'})
assert late['status']=='cancelled' and not late.get('artifact')
with connection() as db:
    assert db.execute("SELECT actual_usd_micro FROM public.pr_usage_ledger WHERE run_id::text=%s AND cost_state='released'",(late['runId'],)).fetchone()[0]==10000
print('PASS: managed commit-before-I/O, timeout replay, unknown usage, terminal settlement and late cancellation')

# Source consent can change while the provider is running: no stale artifact survives.
import json
snap=service.get(wid,'one');state=snap['state']
state['sources'].append({'id':'consumer-fact','kind':'text','active':True,'sourcePolicy':'public_quote','egressConsent':['local','cloud'],'facts':[{'id':'fact-1','approved':True,'text':'The event is on Saturday.'}]})
with connection() as db:
    db.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s',(json.dumps(state),wid))
def revoke_during_call(*args,**kwargs):
    snap=service.get(wid,'one')
    service.mutate(wid,'one',snap['revision'],'source_policy',{'sourceId':'consumer-fact','policy':'public_quote','egressConsent':['local'],'confirmed':True})
    result=no_usage();result['body']['usage']={'cost':0.01,'prompt_tokens':100,'completion_tokens':20}
    return result
runtime.transport=revoke_during_call
revoked=service.ideas.turn(wid,'one',cid,{**payload,'sourceIds':['consumer-fact'],'idempotencyKey':'revoke-during-call'})
assert revoked['status']=='failed' and not revoked.get('artifact')

# The initiating API credential can be revoked independently of its owner membership.
created = service.repository.api_tokens.create(wid, 'one', {'name':'late grant test','scopes':['read','draft'],'expiresDays':30})
def revoke_api_during_call(*args, **kwargs):
    service.repository.api_tokens.revoke(wid, 'one', created['item']['tokenId'])
    result = no_usage(); result['body']['usage'] = {'cost':0.01,'prompt_tokens':100,'completion_tokens':20}
    return result
runtime.transport = revoke_api_during_call
try:
    service.ideas.turn(wid, created['secret'], cid, {**payload,'idempotencyKey':'api-grant-revoked'})
except AlphaError as error:
    assert error.status == 401
else:
    raise AssertionError('revoked API credential received the completion response')
with connection() as db:
    row = db.execute("SELECT status,artifact FROM public.pr_agent_runs WHERE workspace_id=%s AND idempotency_key='api-grant-revoked'", (wid,)).fetchone()
    assert row[0] == 'failed' and row[1] is None

def revoke_session_during_call(*args, **kwargs):
    with connection() as db:
        db.execute('INSERT INTO public.pr_session_revocations(user_id,session_id) VALUES(%s,%s)', (ONE,'consumer-model-test-session'))
    result = no_usage(); result['body']['usage'] = {'cost':0.01,'prompt_tokens':100,'completion_tokens':20}
    return result
runtime.transport = revoke_session_during_call
revoked_session = service.ideas.turn(wid, 'one', cid, {**payload,'idempotencyKey':'session-revoked'})
assert revoked_session['status'] == 'failed' and not revoked_session.get('artifact')
with connection() as db:
    db.execute('DELETE FROM public.pr_session_revocations WHERE user_id=%s', (ONE,))
print('PASS: revoking initiating API token or session discards late generated content while retaining usage')

# Simulate process termination after commit. Cron reconciles status and holds spend; never dispatches again.
class ProcessStopped(BaseException):pass
def crash(*args,**kwargs):raise ProcessStopped()
runtime.transport=crash
try:service.ideas.turn(wid,'one',cid,{**payload,'idempotencyKey':'process-crash'})
except ProcessStopped:pass
with connection() as db:
    db.execute("UPDATE public.pr_agent_runs SET updated_at=now()-interval '20 minutes' WHERE workspace_id=%s AND idempotency_key='process-crash'",(wid,))
assert service.ideas.recover_stalled()=={'recovered':1,'providerRequests':0}
assert service.ideas.recover_stalled()['recovered']==0
with connection() as db,db.cursor() as cur:
    before=db.execute("SELECT reserved_usd_micro FROM public.pr_budgets WHERE scope=%s",('workspace:'+wid,)).fetchone()[0]
    db.execute("UPDATE public.pr_budgets SET window_start=now()-interval '2 months' WHERE scope=%s",('workspace:'+wid,))
    assert service.ideas.ledger._budget(cur,'workspace:'+wid,'month')['reserved']==before
    assert before>0
    db.execute('UPDATE public.pr_entitlements SET writing_batches_remaining=1 WHERE workspace_id=%s',(wid,))
try:service.ideas.turn(wid,'one',cid,{**payload,'idempotencyKey':'reserved-quota'})
except AlphaError as e:assert e.status==402
else:raise AssertionError('outstanding reservations failed to protect batch allowance')
print('PASS: source revocation during call, crashed run recovery, retained cross-window reserves and concurrent quota protection')
