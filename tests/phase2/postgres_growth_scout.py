"""Local disposable PostgreSQL; synthetic signals/writer/observations. No real egress."""
from local_pg_target import selected_target
import copy
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'src'),str(Path(__file__).resolve().parents[1])]
import psycopg
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault
from postriff_phase2.coworker import flags, runtime, listening
from postriff_phase2.growth import scout as S, scout_outcomes as O, scout_runtime as R
from test_growth_scout import item, Judge, WL, NOW
from consumer_fixtures import approve_budgets

DSN=selected_target().dsn()
OWNER='00000000-0000-0000-0000-000000000091'; OTHER='00000000-0000-0000-0000-000000000092'; VIEWER='00000000-0000-0000-0000-000000000093'
connection=lambda:psycopg.connect(DSN)
with connection() as db:
    for user in (OWNER,OTHER,VIEWER): db.execute('INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING',(user,))
service=HostedWorkspaceService(connection,lambda token:token,clock=lambda:NOW,vault=CredentialVault(CredentialVault.generate_key()),public_base_url='https://fixture.invalid')
values={k:'1' for k in ('RAFII_LISTENING_ENABLED','RAFII_ACTIVE_SCOUT_ENABLED','RAFII_TREND_OBJECTS_ENABLED','RAFII_OPPORTUNITY_FLIPPER_ENABLED','RAFII_PERFORMANCE_LEARNING_ENABLED')}
runtime.attach(service,values)
wid=service.bootstrap(OWNER,'studio')['workspaceId']; other=service.bootstrap(OTHER,'studio')['workspaceId']; service.bootstrap(VIEWER,'studio')
with connection() as db:
    db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')",(wid,VIEWER))
approve_budgets(connection,wid)
def state():return service.get(wid,OWNER)['state']
def command(fn):return service.repository.command(wid,OWNER,service.get(wid,OWNER)['revision'],fn)
checks=[]
def check(label,value):
    assert value,label
    checks.append(label);print('PASS',label,flush=True)
def seed(s,actor):
    service.commands.upsert_verified_channel(s,actor,{'id':'scout-li','platform':'LinkedIn','account':'Synthetic','accountType':'member','scopes':['w_member_social'],'verifiedAt':NOW,'expiresAt':NOW+10**8,'capabilityVersion':1,'providerAccountId':'fixture'})
    s['brandHub']={'audience':'local bakers'}
    wl=copy.deepcopy(WL);listening.root(s)['watchlists']=[wl]
    p=S.prepare(s,wl,[item(1),item(2)],wid,NOW,judge=Judge());S.store(s,wl,p,NOW)
    return s
command(seed)
# The prepared signal pass holds no workspace lock during broker/model work.
def due_again(s,actor):
    listening.root(s)['watchlists'][0]['lastRunAt']=0
    return s
command(due_again)
class Broker:
    def search_items(self,query,scope):
        with connection() as db:
            db.execute('SELECT id FROM pr_workspaces WHERE id=%s FOR UPDATE NOWAIT',(wid,))
        return {'status':'ok','items':[item(1),item(2)]}
with patch('postriff_phase2.growth.scout_runtime.research.allowed',return_value=True):
    completed=R.run_workspace(service.coworker,wid,time.monotonic()+60,broker=Broker(),judge=Judge())
check('claim commits before broker HTTP and completion is fenced',completed['status']=='ok' and 'scoutLease' not in listening.root(state()))

op=service.coworker.listening_view(wid,OWNER)['opportunities'][0];plan=op['executionPlans'][0]
a=service.coworker.opportunity_create(wid,OWNER,op['id'],plan['id']);b=service.coworker.opportunity_create(wid,OWNER,op['id'],plan['id'])
check('idempotent verified creation',a['verified'] and a==b)
source=next(s for s in state()['sources'] if s['id']==a['sourceId'])
check('intent and native plan retained without approving third-party facts',source['facts']==[] and source['origin']['executionPlan']['id']==plan['id'])
for token,target in ((VIEWER,wid),(OTHER,other)):
    try: service.coworker.opportunity_create(target,token,op['id'],plan['id']); ok=False
    except Exception: ok=True
    check('viewer/cross-tenant creation refused '+token[-2:],ok)
conv=service.ideas.create_conversation(wid,OWNER,'Scout fixture')
run=service.ideas.turn(wid,OWNER,conv['conversationId'],{'text':source['text'],'sourceIds':[source['id']],'destinations':[{'platform':'LinkedIn','channelId':'scout-li','language':'en'}]})
with connection() as db:
    row=db.execute('SELECT id::text,status,artifact,artifact_hash FROM pr_agent_runs WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 1',(wid,)).fetchone()
check('synthetic writer completed',row[1]=='completed')
check('artifact preserves server-owned scout lineage',row[2]['scoutLineage'][0]['executionPlan']['id']==plan['id'])
service.ideas.apply(wid,OWNER,service.get(wid,OWNER)['revision'],row[0],row[3])
variant=next(v for v in state()['variants'] if v.get('scoutLineage'))
check('draft carries opportunity execution lineage',variant['scoutLineage'][0]['sourceId']==source['id'])
# Synthetic verified publication rows and appended observations, never a real publication.
def jobs(s,actor):
    rows=[]
    for i in range(7):
        v=copy.deepcopy(variant);v['id']=f'fixture-v{i}';v['platform']='Threads';v['scoutLineage'][0]['executionPlan'].update(platform='Threads',account='scout-th',primaryObjective='reach')
        s['variants'].append(v)
        rows.append({'id':f'fixture-j{i}','state':'verified','providerReference':f'fixture-p{i}','approvedAt':NOW-100000+i*1000,'manifest':{'platform':'Threads','channelId':'scout-th','variantId':v['id'],'payload':{'language':'en','text':'A supported observation'},'contentType':{'id':'text'}}})
    s['phase2']['jobs']=rows
    # Fixture aligns stored execution with the synthetic Threads outcomes.
    current=listening.root(s)['opportunities'][0]
    current['executionPlans'][0].update(platform='Threads',account='scout-th',primaryObjective='reach')
    service.commands.upsert_verified_channel(s,actor,{'id':'scout-th','platform':'Threads','account':'Synthetic Threads','accountType':'member','scopes':['threads_basic'],'verifiedAt':NOW,'expiresAt':NOW+10**8,'capabilityVersion':1,'providerAccountId':'fixture-th'})
    return s
command(jobs)
from postriff_phase2 import insights
snapshot=state()
with connection() as db,db.cursor() as cur:
    for i in range(7):
        for offset in ('1h','24h','7d'):
            insights.record_observations(cur,wid,'scout-th','threads',f'fixture-p{i}',f'fixture-j{i}',{'views':300 if i==6 else 100},'synthetic-fixture',NOW,read_offset=offset)
    # A failed later metric read must not replace existing valid evidence.
    insights.record_observations(cur,wid,'scout-th','threads','fixture-p6','fixture-j6',{},'synthetic-fixture',NOW+1,read_offset='24h')
    rows=O.refresh(cur,wid,snapshot,NOW)
    result=O.evaluate(next(r for r in rows if r['id']=='fixture-j6' and r['window']=='24h'),rows)
check('verified job to metrics to double-down lineage',result['state']=='double_down_candidate' and result['value']==300 and result['samples']==6)
first=service.coworker.opportunity_create(wid,OWNER,op['id'],plan['id'],'fixture-j6')
second=service.coworker.opportunity_create(wid,OWNER,op['id'],plan['id'],'fixture-j6')
check('observed sequel is verified and idempotent',first==second and first['sourceId']!=a['sourceId'])
try:
    service.coworker.opportunity_create(wid,OWNER,op['id'],plan['id'],'fixture-j1');refused=False
except Exception:refused=True
check('weak or insufficient observed outcome cannot make sequel',refused)
check('1h never durable strategy',O.evaluate(next(r for r in rows if r['id']=='fixture-j6' and r['window']=='1h'),rows)['state']=='observing')
with connection() as db:
    db.execute("SET LOCAL ROLE authenticated");db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)",(OTHER,))
    count=db.execute('SELECT count(*) FROM pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
    check('RLS hides other workspace state',count==0)
# Repeated-evidence planning uses the existing hypothesis table and owner action.
with connection() as db:
    h=db.execute("""INSERT INTO pr_strategy_hypotheses(workspace_id,platform,dimension,cohort,statement,metric,arm_a,arm_b,sample_a,sample_b,effect,evidence_ids,counter_evidence_ids,confidence,expires_at)
                    VALUES(%s,'Threads','scout_opening_fixture',%s::jsonb,'Question openings may support reach for this account. Observed association only.','views','question','statement',5,5,0.5,'["fixture-j6"]','["fixture-j0"]','low',now()+interval '30 days') RETURNING id::text""",
                 (wid,json.dumps({'account':'scout-th','provider':'threads','objective':'reach','language':'en','format':'text','window':'24h','definition':'v1'}))).fetchone()[0]
try:service.coworker.hypothesis_decide(wid,VIEWER,h,'accepted');refused=False
except Exception:refused=True
check('viewer cannot accept a planning preference',refused)
check('performance HTTP payload serializes real PostgreSQL timestamps',bool(json.dumps(service.coworker.performance_view(wid,OWNER))))
accepted=service.coworker.hypothesis_decide(wid,OWNER,h,'accepted')
check('owner explicitly accepts repeated evidence without voice mutation',accepted['verified'] and accepted['status']=='supported' and not accepted['causal'])
service.coworker.hypothesis_decide(wid,OWNER,h,'dismissed')
with connection() as db:
    check('accepted preference can be withdrawn',db.execute('SELECT status FROM pr_strategy_hypotheses WHERE id=%s',(h,)).fetchone()[0]=='dismissed')
def expired_media(s,actor):
    root=listening.root(s);root['mediaPurgeAt']=NOW-1
    root['mediaCache']=[{'expiresAt':NOW-1}]
    root['opportunities'][0]['evidence'][0]['mediaEvidence']={'rights':{'retainUntil':NOW-1}}
    return s
command(expired_media)
receipt=service.coworker.retention_sweep()
check('cron physically purges expired media summaries',receipt['scoutMediaWorkspacesPurged']==1 and 'mediaEvidence' not in listening.root(state())['opportunities'][0]['evidence'][0])

# Tenant deletion cleans bounded persisted scout data with the workspace.
with connection() as db:
    db.execute('DELETE FROM pr_workspaces WHERE id=%s',(wid,))
    check('workspace deletion removes scout and metric records',db.execute('SELECT count(*) FROM pr_metric_observations WHERE workspace_id=%s',(wid,)).fetchone()[0]==0)
print(json.dumps({'execution':'local synthetic','passed':len(checks)}))
