"""Real service + disposable PostgreSQL. No real credentials, AI or publishing."""
import sys,json,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService,ROUTES,current_genome
from postriff_phase2.growth.closed_loop import SUMMARY_ROUTE
from growth_phase2_fixtures import Models,Writer,ENV,seed
ONE='00000000-0000-0000-0000-000000000001';TWO='00000000-0000-0000-0000-000000000002'
def connection():return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres')
def verify(token):
    if token in ('one','two'):return ONE if token=='one' else TWO
    raise AlphaError('Verified session required.',401)
def refused(status,fn):
    try:fn()
    except AlphaError as e:assert e.status==status,(status,e.status,str(e));return
    raise AssertionError('Expected refusal '+str(status))
with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(ONE,)).fetchone()[0])
    foreign=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner'")
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))
clock=[time.time()];host=HostedWorkspaceService(connection,verify,clock=lambda:clock[0],ideas_runtime=Writer());host.bootstrap('one','studio')
models=Models();g=host.growth=GrowthService(host,env=ENV,router_factory=models.router,clock=lambda:clock[0]);c=g.closed_loop
checks=[]
def saved():return host.get(wid,'one')
def action(name,payload):return g.action(wid,'one',saved()['revision'],name,payload)
def consent(audience=True):return action('growth_consent',{'confirmed':True,'routes':[*ROUTES,SUMMARY_ROUTE],'audience':audience})
def body(**kw):return {'confirmed':True,'requestKey':str(uuid.uuid4()),**kw}
job=seed(host,wid,'one')['jobId']
refused(404,lambda:GrowthService(host,env={}).closed_loop.overview(wid,'one'))
refused(403,lambda:c.overview(foreign,'one'))
refused(403,lambda:c.overview(wid,'prt_invalid'))
assert c.overview(wid,'one')['posts'] and not models.calls
refused(403,lambda:c.report(wid,'one',body(jobId=job,horizon='24h')))
consent(False)
refused(403,lambda:c.mine(wid,'one',body(days=14)))
consent();checks.append('flags, interactive sessions, cross-workspace isolation and separate comment consent')
b=body(jobId=job,horizon='24h');r=c.report(wid,'one',b);n=len(models.calls)
assert r['comparisons'][0]['status']=='aligned' and r['explanation']['cause']=='not_established'
assert c.report(wid,'one',b)==r and len(models.calls)==n
assert r['lessons'][0]['grade']=='limited' and not current_genome(saved()['state'])
refused(400,lambda:action('postmortem_lesson_approve',{'reportId':r['id'],'lessonId':r['lessons'][0]['id']}))
action('postmortem_lesson_approve',{'reportId':r['id'],'lessonId':r['lessons'][0]['id'],'confirmed':True})
assert current_genome(saved()['state'])['statements'][0]['grade']=='limited'
assert g.genome(wid,'one')['evidence'][job]['text']
refused(409,lambda:action('postmortem_lesson_approve',{'reportId':r['id'],'lessonId':r['lessons'][0]['id'],'confirmed':True}))
checks.append('frozen prediction, native outcomes, exact replay, owner lesson approval and inspectable evidence')
with connection() as db:db.execute("UPDATE public.pr_metric_observations SET value=97 WHERE workspace_id=%s AND job_id=%s AND metric='likes'",(wid,job))
refused(409,lambda:c.report(wid,'one',b))
assert c.overview(wid,'one')['reports'][0]['status']=='stale'
# Permission revocation before the second model request prevents disclosure to that model.
clock[0]+=1;models.before=lambda:consent(False)
before=len(models.calls)
refused(409,lambda:c.report(wid,'one',body(jobId=job,horizon='24h')))
assert len(models.calls)==before+1
consent();checks.append('corrected-reading replay rejection and revocation before next model dispatch')
b=body(days=14);mined=c.mine(wid,'one',b)
assert mined['analyzed']==6 and mined['withheld']==1 and len(mined['clusters'])==4,mined
count=len(models.calls);assert c.mine(wid,'one',b)==mined and len(models.calls)==count
assert 'alice@example.com' not in json.dumps([call for call in models.calls if call[0]=='evaluate'])
assert 'private_handle' not in json.dumps(mined)
group=mined['clusters'][0];beforejobs=saved()['state']['phase2']['jobs']
first=action('audience_suggestion_create',{'clusterId':group['id'],'confirmed':True})
second=action('audience_suggestion_create',{'clusterId':group['id'],'confirmed':True})
assert first['sourceId']==second['sourceId']
s=next(s for s in saved()['state']['sources'] if s['id']==first['sourceId']);assert s['needsFactCheck'] and s['audienceEvidence']
assert c.audience(wid,'one')['conversion']['suggestedTopics']==4
assert c.audience(wid,'one')['conversion']['rate']==0
assert saved()['state']['phase2']['jobs']==beforejobs and c.audience(wid,'one')['conversion']['savedTopics']==1
with connection() as db:db.execute('UPDATE public.pr_audience_threads SET tombstoned_at=now() WHERE id=%s',(group['evidenceIds'][0],))
refused(409,lambda:action('audience_suggestion_create',{'clusterId':group['id'],'confirmed':True}))
refused(409,lambda:c.mine(wid,'one',b))
checks.append('redacted bounded comment decisions, privacy abstention, replay, reviewable idea, dedupe and tombstone fencing')
# Cap starts before another model attempt; one more run is available today.
second_run=c.mine(wid,'one',body(days=14));count=len(models.calls)
# Identical topics across runs reuse an existing idea rather than creating a duplicate.
matching=next(i for i in second_run['clusters'] if i['suggestion']['question']==group['suggestion']['question']) if group['count']>1 else None
if matching:assert action('audience_suggestion_create',{'clusterId':matching['id'],'confirmed':True})['sourceId']==first['sourceId']
refused(429,lambda:c.mine(wid,'one',body(days=14)));assert len(models.calls)==count
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_model_usage_events WHERE workspace_id=%s AND cost_usd_micro IS NULL',(wid,)).fetchone()[0]>0
    db.execute("UPDATE public.pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
refused(403,lambda:action('creator_calibration_propose',{}))
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
refused(409,lambda:action('creator_calibration_propose',{}))
seed(host,wid,'one',calibration=True)
p=action('creator_calibration_propose',{});assert c.overview(wid,'one')['calibration']['versions'][0]['status']=='proposed'
action('creator_calibration_approve',{'calibrationId':p['calibrationId'],'confirmed':True})
with connection() as db,db.cursor() as cur:assert c.active_calibration(cur,wid,saved()['state'])['candidates']
p2=action('creator_calibration_propose',{});action('creator_calibration_approve',{'calibrationId':p2['calibrationId'],'confirmed':True})
action('creator_calibration_restore',{'calibrationId':p['calibrationId'],'confirmed':True})
assert next(v for v in c.overview(wid,'one')['calibration']['versions'] if v['id']==p['calibrationId'])['status']=='approved'
checks.append('daily allowance, unknown cost ledger, fifty-post chronological calibration, owner approve and restore')
with connection() as db:
    for table in ('pr_postmortems','pr_audience_clusters','pr_comment_judgments','pr_creator_calibrations'):
        for role in ('anon','authenticated'):assert not db.execute("SELECT has_table_privilege(%s,%s,'SELECT')",(role,'public.'+table)).fetchone()[0]
    db.execute("UPDATE public.pr_audience_clusters SET expires_at=now()-interval '1 second'")
    db.execute("UPDATE public.pr_comment_judgments SET expires_at=now()-interval '1 second'")
g.sweep()
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_audience_clusters WHERE workspace_id=%s',(wid,)).fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM public.pr_comment_judgments WHERE workspace_id=%s',(wid,)).fetchone()[0]==0
    db.execute('DELETE FROM public.pr_workspaces WHERE id=%s',(wid,))
    for table in ('pr_postmortems','pr_audience_clusters','pr_comment_judgments','pr_creator_calibrations'):
        assert db.execute('SELECT count(*) FROM public.'+table+' WHERE workspace_id=%s',(wid,)).fetchone()[0]==0
checks.append('service-only RLS, retention expiration and workspace deletion cascade')
print(json.dumps({'status':'PASS','execution':'disposable PostgreSQL, synthetic observations and deterministic models','checks':checks,'realModelCalls':0}))
