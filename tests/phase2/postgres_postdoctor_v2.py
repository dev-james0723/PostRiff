"""Real service/DB, deterministic models. No real accounts, paid calls or publishing."""
from local_pg_target import selected_target
import sys, time, uuid, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService, ROUTES
from growth_phase1_fixtures import Models, Writer, ENV, MODEL

from growth_postdoctor_v2_fixtures import ComparisonModels

def connection():return psycopg.connect(selected_target().dsn())
ONE='00000000-0000-0000-0000-000000000001';TOKEN='fixture-one';clock=[time.time()]
def refused(status, fn):
    try:fn()
    except AlphaError as e:assert e.status==status,(status,e.status,str(e));return e
    raise AssertionError('Expected refusal')
with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))
models=ComparisonModels();env={**ENV,'POSTRIFF_POST_DOCTOR_V2':'1'}
host=HostedWorkspaceService(connection,lambda _:ONE,clock=lambda:clock[0],ideas_runtime=Writer())
host.bootstrap(TOKEN,'studio')
growth=host.growth=GrowthService(host,env=env,router_factory=models.router,clock=lambda:clock[0])
def saved():return host.get(wid,TOKEN)
def action(name,payload):return growth.action(wid,TOKEN,saved()['revision'],name,payload)
def draft():return saved()['state']['variants'][0]
def seed(state,actor):
    state['variants']=[{'id':'v2-draft','text':'One idea. Another idea!','platform':'Threads','language':'en','revision':1,
        'sourceIds':[],'revisions':[],'warnings':[],'unknowns':[],'needsReview':True,'voiceRevision':None}]
    return state
host.repository.command(wid,TOKEN,saved()['revision'],seed)
action('growth_consent',{'confirmed':True,'routes':[*ROUTES,'cloud:vercel-ai-gateway:'+MODEL]})
def checkbody(**kw):return {'variantId':draft()['id'],'variantRevision':draft()['revision'],'confirmed':True,'requestKey':str(uuid.uuid4()),**kw}
def rewritebody(result):return {'checkId':result['runId'],'model':MODEL,'facts':{},'confirmed':True,'requestKey':str(uuid.uuid4())}
first=growth.check(wid,TOKEN,checkbody())
assert first['questionSet']=='postdoctor.v2'
assert first['missingContext']=={'audience':['creator.audience']}
body=rewritebody(first);result=growth.rewrite(wid,TOKEN,body)
assert result['comparison']['recommended']=='candidate' and result['comparison']['orderChecked']
count=len(models.calls)
assert growth.rewrite(wid,TOKEN,body)==result and len(models.calls)==count
# A new goal invalidates the old check/rewrite/replay, even without a text edit.
old_body=checkbody(goal='conversation');old_check=growth.check(wid,TOKEN,old_body)
assert old_check['goal']=='conversation'
new_check=growth.check(wid,TOKEN,checkbody(goal='authority'))
assert new_check['goal']=='authority' and new_check['contextDigest']!=old_check['contextDigest']
refused(409,lambda:growth.check(wid,TOKEN,old_body))
refused(409,lambda:action('post_doctor_accept',{'rewriteId':result['runId'],'changeIds':['0','1']}))
# Full acceptance freezes exact goal, contexts and accepted IDs; partial needs recheck.
clock[0]+=86400
result=growth.rewrite(wid,TOKEN,rewritebody(new_check))
action('post_doctor_accept',{'rewriteId':result['runId'],'changeIds':['0','1']})
frozen=draft()['postDoctor']
assert frozen['goal']=='authority' and frozen['contextDigest']==new_check['contextDigest']
assert frozen['comparison']['candidateDigest']==frozen['textDigest']
assert frozen['acceptedChangeIds']==['0','1']
clock[0]+=86400
fresh=growth.check(wid,TOKEN,checkbody(goal='conversation'))
result=growth.rewrite(wid,TOKEN,rewritebody(fresh))
action('post_doctor_accept',{'rewriteId':result['runId'],'changeIds':['0']})
assert 'postDoctor' not in draft()
# Context and rubric changes invalidate replay and publication advice.
ctx_body=checkbody(goal='authority');ctx_check=growth.check(wid,TOKEN,ctx_body)
def change_audience(state,actor):state.setdefault('brandHub',{})['audience']='Piano teachers';return state
host.repository.command(wid,TOKEN,saved()['revision'],change_audience)
refused(409,lambda:growth.check(wid,TOKEN,ctx_body))
assert 'postDoctor' not in draft(), 'Stale audience advice must not attach to publication'
# Revocation during the first comparison stops the swapped call and fences storage.
clock[0]+=86400
host.mutate(wid,TOKEN,saved()['revision'],'variant_edit',{'variantId':draft()['id'],'variantRevision':draft()['revision'],'text':'A new original. Another idea!'})
latest=growth.check(wid,TOKEN,checkbody())
models.compare_hook=lambda:action('growth_consent',{'confirmed':True,'routes':[]})
count=len(models.calls)
refused(409,lambda:growth.rewrite(wid,TOKEN,rewritebody(latest)))
assert len(models.calls)==count+4 # writer, grounding, recheck, first comparison only
print(json.dumps({'status':'PASS','checks':['missing context','grounded comparison in both orders','no-cost replay','revocation between comparison calls'],'realModelCalls':0}))
