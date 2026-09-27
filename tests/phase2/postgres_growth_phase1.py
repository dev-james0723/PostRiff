"""Actual Phase 1 services on disposable PostgreSQL, deterministic models, no real credentials/network."""
import copy
import io
import json
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.growth import performance
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2 import memory
from growth_phase1_fixtures import ENV, MODEL, Models, Writer

ONE='00000000-0000-0000-0000-000000000001'
TWO='00000000-0000-0000-0000-000000000002'
TOKEN='fixture-one'
clock=[time.time()]
checks=[]


def connection():return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres')
def verify(token):
    if token in (TOKEN,'fixture-two'):return ONE if token==TOKEN else TWO
    raise AlphaError('Verified session required.',401)
def refused(status,fn):
    try:fn()
    except AlphaError as e:
        assert e.status==status,(e.status,status,str(e))
        return e
    raise AssertionError('Expected refusal '+str(status))


with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(ONE,)).fetchone()[0])
    foreign=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))

models=Models()
host=HostedWorkspaceService(connection,verify,clock=lambda:clock[0],ideas_runtime=Writer())
host.bootstrap(TOKEN,'studio')
growth=host.growth=GrowthService(host,env=ENV,router_factory=models.router,clock=lambda:clock[0])
def saved():return host.get(wid,TOKEN)
def action(name,payload):return growth.action(wid,TOKEN,saved()['revision'],name,payload)
def mutate(name,payload):return host.mutate(wid,TOKEN,saved()['revision'],name,payload)
def advance():clock[0]+=86400
def draft():return saved()['state']['variants'][0]
def checkbody(**extra):return {'variantId':draft()['id'],'variantRevision':draft()['revision'],'confirmed':True,'requestKey':str(uuid.uuid4()),**extra}
def check():return growth.check(wid,TOKEN,checkbody())
def consent():return action('growth_consent',{'confirmed':True,'routes':[*ROUTES,'cloud:vercel-ai-gateway:'+MODEL]})
def seed(state,actor):
    state['variants']=[{'id':'growth-draft','text':'One idea. Another idea!','platform':'Threads','language':'en','revision':1,
                        'sourceIds':[],'revisions':[],'warnings':[],'unknowns':[],'needsReview':True,'voiceRevision':None}]
    return state
host.repository.command(wid,TOKEN,saved()['revision'],seed)

assert growth.catalog(wid,TOKEN)['postDoctor']
off=GrowthService(host,env={},router_factory=models.router)
refused(404,lambda:off.check(wid,TOKEN,checkbody()))
refused(403,lambda:growth.check(wid,TOKEN,checkbody()))
assert len(models.calls)==0
consent()
refused(403,lambda:growth.catalog(wid,'prt_untrusted'))
refused(403,lambda:growth.check(foreign,TOKEN,checkbody()))
refused(403,lambda:growth.check(wid,'fixture-two',checkbody()))
checks.append('default off, consent, API token and workspace isolation')

body=checkbody();result=growth.check(wid,TOKEN,body)
assert len(result['dimensions'])==9 and '_scores' not in result and '_judgment' not in result
assert draft()['postDoctor']['revision']==1
count=len(models.calls)
assert growth.check(wid,TOKEN,body)==result and len(models.calls)==count
refused(409,lambda:growth.check(wid,TOKEN,{**body,'variantRevision':4}))
rewrite=growth.rewrite(wid,TOKEN,{'checkId':result['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())})
assert rewrite['grounding']=='passed' and len(rewrite['changes'])==2
assert rewrite['before']['questionSet']==rewrite['after']['questionSet']
action('post_doctor_accept',{'rewriteId':rewrite['runId'],'changeIds':['0']})
assert draft()['text']=='A clearer opening. Another idea!' and draft()['revision']==2 and draft()['needsReview']
assert 'postDoctor' not in draft()
refused(409,lambda:action('post_doctor_accept',{'rewriteId':rewrite['runId'],'changeIds':['1']}))
refused(409,lambda:growth.check(wid,TOKEN,body))
checks.append('check ledger, exact replay, rewrite/recheck, selective edits and stale rejection')

# Ten signed checks/day and one rewrite/day, shared workspace + global monetary reservations.
refused(429,lambda:growth.rewrite(wid,TOKEN,{'checkId':check()['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())}))
advance();models.ungrounded=True
latest=check()
refused(409,lambda:growth.rewrite(wid,TOKEN,{'checkId':latest['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())}))
models.ungrounded=False
advance();latest=check()
rewrite=growth.rewrite(wid,TOKEN,{'checkId':latest['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())})
action('post_doctor_accept',{'rewriteId':rewrite['runId'],'changeIds':[c['id'] for c in rewrite['changes']]})
assert draft()['postDoctor']['revision']==draft()['revision']
assert draft()['postDoctor']['evaluation']['answers']
checks.append('rewrite quota, grounding rejection and full recheck binding')

# A consent change during the model request is fenced at completion. The actual attempt is still in the ledger.
advance()
models.before=lambda:action('growth_consent',{'confirmed':True,'routes':[]})
refused(409,check)
consent()
with connection() as db:
    rows=db.execute('SELECT status,cost_usd_micro FROM public.pr_model_usage_events WHERE workspace_id=%s',(wid,)).fetchall()
    assert rows and all(r[1] is None for r in rows),'Unknown is never a fabricated zero'
    assert db.execute("SELECT count(*) FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND status='cancelled'",(wid,)).fetchone()[0]>=1
checks.append('in-flight revocation fencing and actual-attempt ledger')

advance();latest=check();before=len(models.calls)
models.before_chat=lambda:mutate('memory_egress',{'cloud':False,'confirmed':True})
refused(409,lambda:growth.rewrite(wid,TOKEN,{'checkId':latest['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())}))
assert len(models.calls)==before+1,'Revocation must stop grounding/recheck before another model receives context'
checks.append('memory revocation stops the next model call')

# The CSV corpus remains the existing voice-source store; proposed rules do not silently become approved.
csv='text,platform,language,post_id\nMy first own teaching note.,Threads,en,g1\nMy second own teaching note.,Threads,en,g2\nMy third own teaching note.,Threads,en,g3\n'
import_body={'data':csv,'account':'my-owned-account','ownContent':True,'retainText':True,'confirmed':True,'requestKey':str(uuid.uuid4())}
refused(400,lambda:growth.imports(wid,TOKEN,{**import_body,'ownContent':False}))
proposed=growth.imports(wid,TOKEN,import_body)['genome']
assert proposed['postCount']==3 and proposed['measuredPosts']==0 and proposed['statements']
assert growth.genome(wid,TOKEN)['active'] is None
action('genome_approve',{'genomeId':proposed['id'],'confirmed':True})
assert growth.genome(wid,TOKEN)['active']['id']==proposed['id']
voice=next(f['body'] for f in memory.render_files(saved()['state']) if f['name']=='VOICE.md')
assert 'Approved Creator Genome' in voice
share=action('share_card_create',{'genomeId':proposed['id'],'statementIds':[proposed['statements'][0]['id']],'confirmed':True})
token=share['path'].split('/')[-1]
public=growth.share(token)
assert set(public)=={'labels','description'} and csv not in json.dumps(public)
action('share_card_revoke',{'shareId':share['shareId']})
refused(404,lambda:growth.share(token))
advance()
source_ids=[s['id'] for s in saved()['state']['sources'] if s.get('kind')=='voice_sample']
second=growth.imports(wid,TOKEN,{'sourceIds':source_ids,'ownContent':True,'retainText':True,'confirmed':True,'requestKey':str(uuid.uuid4())})['genome']
action('genome_approve',{'genomeId':second['id'],'confirmed':True})
action('genome_restore',{'genomeId':proposed['id'],'confirmed':True})
assert growth.genome(wid,TOKEN)['active']['id']==proposed['id']
share=action('share_card_create',{'genomeId':proposed['id'],'statementIds':[proposed['statements'][0]['id']],'confirmed':True})
token=share['path'].split('/')[-1]
mutate('voice_sample_select',{'sourceId':source_ids[0],'selected':False})
assert growth.genome(wid,TOKEN)['active'] is None
assert all(v['status']=='stale' for v in growth.genome(wid,TOKEN)['versions'])
refused(404,lambda:growth.share(token))
refused(409,lambda:action('genome_restore',{'genomeId':proposed['id'],'confirmed':True}))
checks.append('owned history, proposed/approve/restore, voice reuse, label-only sharing and revocation')

# An existing sample grant cannot re-enable an analysis route revoked at workspace level.
advance()
for source_id in source_ids[1:]:
    mutate('voice_sample_grant',{'sourceId':source_id,'confirmed':True,'grants':[{'purpose':'analysis','route':ROUTES[0]}]})
action('growth_consent',{'confirmed':True,'routes':[ROUTES[1]]})
before=len(models.calls)
refused(403,lambda:growth.imports(wid,TOKEN,{'sourceIds':source_ids[1:],'ownContent':True,'retainText':True,'confirmed':True,'requestKey':str(uuid.uuid4())}))
assert len(models.calls)==before,'Sample grants must intersect the current workspace consent'
checks.append('workspace route revocation overrides older sample grants')

advance()
for _ in range(10):check()
before=len(models.calls)
refused(429,check)
assert len(models.calls)==before,'An exhausted daily allowance must stop before model dispatch'
checks.append('ten signed checks per day enforced before model dispatch')

# A public result never stores draft text, raw probabilities, IP or private identifiers, with a 3/day allowance.
public_body={'text':'My anonymous private draft','platform':'Threads','language':'en','confirmed':True}
for _ in range(3):assert growth.public_check(public_body,'127.0.0.42')['dimensions']
refused(429,lambda:growth.public_check(public_body,'127.0.0.42'))
with connection() as db:
    stored=json.dumps(db.execute('SELECT subject_hash,result FROM public.pr_public_checks').fetchall())
    assert '127.0.0.42' not in stored and public_body['text'] not in stored and 'probabilities' not in stored
    db.execute("UPDATE public.pr_public_checks SET expires_at=now()-interval '1 second'")
assert growth.sweep()['publicChecksRemoved']==3
checks.append('anonymous minimization, abuse allowance and retention cleanup')

# Verified feedback: exact frozen revision, observations at each horizon and an identical peer cohort.
job_ids=[str(uuid.uuid4()) for _ in range(5)]
def seed_jobs(state,actor):
    state['phase2']['jobs']=[]
    for i,job_id in enumerate(job_ids):
        manifest={'platform':'Threads','channelId':'matching-account','contentRevision':3,'contentType':{'formatId':'text'},
                  'payload':{'text':'Exact published draft','language':'en'},'payloadDigest':'exact',
                  'postDoctor':{'levels':result['dimensions'],'questionSet':result['questionSet'],'revision':3}}
        state['phase2']['jobs'].append({'id':job_id,'state':'verified' if i<4 else 'sending','manifest':manifest,
                                      'providerReference':'observed-'+str(i),'verification':{'at':clock[0],'method':'fixture-provider-lookup'} if i<4 else None})
    return state
host.repository.command(wid,TOKEN,saved()['revision'],seed_jobs)
with connection() as db,db.cursor() as cur:
    for i,job in enumerate(saved()['state']['phase2']['jobs'][:4]):
        performance.on_verified(cur,wid,job)
        cur.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,job_id,metric,definition_version,value,unit,availability,observed_at,read_offset) VALUES(%s,'matching-account','threads',%s,%s,'likes','native-v1',%s,'count','available',now(),'24h')",(wid,job['providerReference'],job['id'],[5,10,15,30][i]))
feedback=growth.feedback(wid,TOKEN,job_ids[3])
observed=next(r for r in feedback['readings'] if r['horizon']=='24h')['metrics']['likes']
assert observed['baselineCount']==3 and observed['median']==10 and observed['multiple']==3
assert feedback['prediction']['contentRevision']==3
assert feedback['readings'][0]['status']=='unavailable'
assert growth.feedback(wid,TOKEN,job_ids[4])['reason']=='publication_not_verified'
checks.append('verified revision prediction and official like-for-like 1h/24h/7d feedback')

# Schema access is service-only, and workspace deletion cascades the private tables.
with connection() as db:
    for role in ('anon','authenticated'):
        for table in ('pr_post_history','pr_genome_versions','pr_post_doctor_runs','pr_predictions','pr_share_cards','pr_public_checks','pr_growth_budgets'):
            assert not db.execute('SELECT has_table_privilege(%s,%s,\'SELECT\')',(role,'public.'+table)).fetchone()[0]
    db.execute('DELETE FROM public.pr_workspaces WHERE id=%s',(wid,))
    for table in ('pr_post_history','pr_genome_versions','pr_post_doctor_runs','pr_predictions','pr_share_cards'):
        assert db.execute('SELECT count(*) FROM public.'+table+' WHERE workspace_id=%s',(wid,)).fetchone()[0]==0
checks.append('RLS privileges and deletion cascades')
print(json.dumps({'status':'PASS','execution':'disposable PostgreSQL + zero-network deterministic models','checks':checks,'realModelCalls':0}))
