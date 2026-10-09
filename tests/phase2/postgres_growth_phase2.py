"""Real service + disposable PostgreSQL. No real credentials, AI or publishing."""
import sys,json,time,uuid,os
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
def connection():return psycopg.connect(os.environ.get('POSTRIFF_TEST_DSN','host=127.0.0.1 port=55438 dbname=postgres'))
def verify(token):
    if token in ('one','two'):return ONE if token=='one' else TWO
    raise AlphaError('Verified session required.',401)
def refused(status,fn,code=None):
    try:fn()
    except AlphaError as e:
        assert e.status==status,(status,e.status,str(e))
        assert code is None or e.code==code,(code,e.code,str(e));return
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
# Readiness on a migrated database: this workspace's own rows only, no model call, no write.
def set_role(name):
    with connection() as db:db.execute("UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s",(name,wid,ONE))
with connection() as db:audit_before=db.execute('SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s',(wid,)).fetchone()[0]
ready=g.catalog(wid,'one')['readiness']
assert set(ready)=={'studio','results','audience','patterns','measurement'},ready
assert (ready['studio']['state'],ready['results']['state'],ready['results']['reasonCodes'],ready['results']['canRead'],ready['results']['canRun'])==('ready','setup_required',['growth_consent_required'],True,False),ready
assert ready['results']['nextStep']=={'kind':'consent','href':'/app/growth?view=results&permissions=true'},ready['results']
assert ready['results']['lastSuccessfulReadAt'],ready['results']
assert (ready['measurement']['state'],ready['measurement']['reasonCodes'])==('feature_disabled',['measurement_off']),ready['measurement']
assert (ready['patterns']['state'],ready['patterns']['reasonCodes'])==('insufficient_data',['sample_below_minimum']),ready['patterns']
assert (ready['audience']['state'],ready['audience']['reasonCodes'])==('setup_required',['growth_consent_required']),ready['audience']
for name in ('editor','viewer'):
    set_role(name);other=g.catalog(wid,'one')['readiness']
    assert other['results']['nextStep']=={'kind':'contact_owner'} and not other['results']['canRun'],(name,other['results'])
    assert not other['patterns']['canRun'] and ('role_edit_required' in other['results']['reasonCodes'])==(name=='viewer'),(name,other)
set_role('owner')
with connection() as db:assert db.execute('SELECT count(*) FROM public.pr_audit_events WHERE workspace_id=%s',(wid,)).fetchone()[0]==audit_before
assert not models.calls
checks.append('catalog readiness on a migrated database: owner consent step, contact_owner for editors and viewers, measurement off, fifty-post patterns minimum; no model call or write')
# Imported history: a lifetime backfill reading at its age, shown apart from the 1h/24h/7d windows.
cohort_before=c.overview(wid,'one')['calibration']['largestCohort']
with connection() as db:
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'phase2-ig','analytics','Direct') ON CONFLICT(workspace_id,connection_id,capability) DO UPDATE SET level='Direct'",(wid,))
    db.execute("INSERT INTO public.pr_owned_posts(workspace_id,connection_id,provider,provider_post_id,published_at,media_type,source) VALUES(%s,'phase2-ig','instagram','ig-history-1',now()-interval '2 days','IMAGE','history_import')",(wid,))
    db.execute("INSERT INTO public.pr_metric_reads(workspace_id,connection_id,provider,provider_post_id,read_offset,source,anchor_at,due_at,status) VALUES(%s,'phase2-ig','instagram','ig-history-1','backfill','history_import',now()-interval '2 days',now()-interval '2 days','done')",(wid,))
    for metric in ('reach','views','likes','comments','saved','shares'):
        db.execute("INSERT INTO public.pr_metric_observations(workspace_id,connection_id,provider,provider_post_id,metric,definition_version,value,unit,availability,observed_at,read_offset) VALUES(%s,'phase2-ig','instagram','ig-history-1',%s,'2026-09',0,'count','available',now()-interval '2 days'+interval '23 minutes','backfill')",(wid,metric))
seen=c.overview(wid,'one')
history=seen['history']
assert len(history)==1 and history[0]['state']=='backfill' and history[0]['platform']=='Instagram' and history[0]['ageSeconds']==1380,history
assert [(m['metric'],m['value'],m['availability']) for m in history[0]['metrics']]==[(m,0.0,'available') for m in ('reach','views','likes','comments','saved','shares')],history
assert len(seen['posts'])==6 and all(w['horizon']!='backfill' for p in seen['posts'] for w in p['windows']),seen['posts']
assert seen['calibration']['largestCohort']==cohort_before,(seen['calibration'],cohort_before)
assert 'never used for reviews' in seen['historyNotice']
checks.append('imported history: six measured zeros shown as a backfill reading at its age, kept out of windows, reviews and calibration')
refused(404,lambda:GrowthService(host,env={}).closed_loop.overview(wid,'one'))
refused(403,lambda:c.overview(foreign,'one'))
refused(403,lambda:c.overview(wid,'prt_invalid'))
assert c.overview(wid,'one')['posts'] and not models.calls
initial=c.overview(wid,'one')
assert initial['measurement']=={'enabled':False,'analyticsConnections':1}
def window(h):
    post=next(p for p in c.overview(wid,'one')['posts'] if p['jobId']==job)
    return next(w for w in post['windows'] if w['horizon']==h)
assert window('1h')['state']=='disabled' and not window('1h')['available']
assert window('24h')['state']=='measured' and window('24h')['available']
from postriff_phase2.growth.metric_schedule import schedule
verified=next(j for j in saved()['state']['phase2']['jobs'] if j['id']==job)
g.env['POSTRIFF_METRIC_READS']='1'
from types import SimpleNamespace
assert window('1h')['state']=='disabled'
host.metric_reads=SimpleNamespace(workspace_allowed=lambda candidate:False)
assert window('1h')['state']=='disabled'
host.metric_reads=SimpleNamespace(workspace_allowed=lambda candidate:candidate==wid)
with connection() as db,db.cursor() as cur:
    schedule(cur,wid,verified['manifest']['channelId'],'threads',verified['providerReference'],job,verified['verification']['at'],'verification')
assert window('1h')['state']=='scheduled' and window('7d')['state']=='pending_horizon'
assert window('7d')['dueAt']>clock[0]
with connection() as db:
    db.execute("UPDATE public.pr_metric_reads SET status='dead',failure_class='retry_exhausted' WHERE workspace_id=%s AND job_id=%s AND read_offset='1h'",(wid,job))
assert window('1h')['state']=='unavailable' and window('1h')['reason']=='retry_exhausted'
with connection() as db:
    db.execute("DELETE FROM public.pr_metric_reads WHERE workspace_id=%s AND job_id=%s AND read_offset='1h'",(wid,job))
assert window('1h')['state']=='unscheduled'
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND capability='analytics'",(wid,))
assert c.overview(wid,'one')['measurement']['analyticsConnections']==0
assert window('7d')['state']=='rights_unavailable'
with connection() as db:
    db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND capability='analytics'",(wid,))
    db.execute("DELETE FROM public.pr_metric_reads WHERE workspace_id=%s AND job_id=%s AND read_offset='7d'",(wid,job))
assert window('7d')['state']=='unscheduled' and window('7d')['dueAt']>clock[0]
g.env.pop('POSTRIFF_METRIC_READS')
del host.metric_reads
assert not models.calls
checks.append('real SQL reading states distinguish measured, disabled, scheduled, future horizon, exhausted, unscheduled and revoked rights without dispatch')
refused(403,lambda:c.report(wid,'one',body(jobId=job,horizon='24h')))
consent(False)
refused(403,lambda:c.mine(wid,'one',body(days=14)))
consent();checks.append('flags, interactive sessions, cross-workspace isolation and separate comment consent')
# A run that failed before any model call: the same key reports failed (never re-runs); a new key may retry.
real_router=g.router_factory
def unavailable(sink,writer):raise RuntimeError('fixture provider unavailable')
g.router_factory=unavailable
failed=body(jobId=job,horizon='24h');calls_before=len(models.calls)
def reserved():
    with connection() as db:return db.execute('SELECT coalesce(sum(calls),0) FROM public.pr_growth_budgets WHERE scope=%s',(wid+':postmortem',)).fetchone()[0]
refused(503,lambda:c.report(wid,'one',failed),'growth_request_failed')
after_failure=reserved()
refused(409,lambda:c.report(wid,'one',failed),'growth_request_failed')
assert reserved()==after_failure and len(models.calls)==calls_before
g.router_factory=real_router
checks.append('a run that failed before any model call is reported as failed for its key and never re-run; a fresh key may retry')
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
# Usage recorded, then the outcome was lost: the same key stays uncertain and nothing is sent or reserved again.
def lost():raise RuntimeError('fixture explanation outcome lost')
with connection() as db:usage_before=db.execute('SELECT count(*) FROM public.pr_model_usage_events WHERE workspace_id=%s',(wid,)).fetchone()[0]
models.before_chat=lost;uncertain=body(jobId=job,horizon='24h')
refused(503,lambda:c.report(wid,'one',uncertain),'growth_request_unknown')
models.before_chat=None
with connection() as db:
    assert db.execute('SELECT count(*) FROM public.pr_model_usage_events WHERE workspace_id=%s',(wid,)).fetchone()[0]>usage_before
    assert db.execute('SELECT status FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND request_key=%s',(wid,uncertain['requestKey'])).fetchone()[0]=='unknown'
calls_before=len(models.calls);after_unknown=reserved()
refused(409,lambda:c.report(wid,'one',uncertain),'growth_request_unknown')
assert len(models.calls)==calls_before and reserved()==after_unknown
checks.append('usage recorded with an uncertain outcome keeps its key, re-sends nothing and reserves nothing again')
# A review made under older AI permission is stale and its lesson cannot be approved.
r2=c.report(wid,'one',body(jobId=job,horizon='24h'))
clock[0]+=1;consent()
assert next(x for x in c.overview(wid,'one')['reports'] if x['id']==r2['id'])['status']=='stale'
refused(409,lambda:action('postmortem_lesson_approve',{'reportId':r2['id'],'lessonId':(r2['lessons'] or [{'id':'outcome:none'}])[0]['id'],'confirmed':True}),'growth_input_changed')
checks.append('changing AI permission makes an earlier review stale and blocks approving its lesson')
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
for name,payload in (('postmortem_lesson_approve',{'reportId':r['id'],'lessonId':r['lessons'][0]['id'],'confirmed':True}),
                     ('creator_calibration_approve',{'calibrationId':str(uuid.uuid4()),'confirmed':True}),
                     ('creator_calibration_restore',{'calibrationId':str(uuid.uuid4()),'confirmed':True}),
                     ('genome_restore',{'genomeId':str(uuid.uuid4()),'confirmed':True})):
    refused(403,lambda:action(name,payload))
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
refused(409,lambda:action('creator_calibration_propose',{}))
seed(host,wid,'one',calibration=True)
p=action('creator_calibration_propose',{});assert c.overview(wid,'one')['calibration']['versions'][0]['status']=='proposed'
action('creator_calibration_approve',{'calibrationId':p['calibrationId'],'confirmed':True})
with connection() as db,db.cursor() as cur:assert c.active_calibration(cur,wid,saved()['state'])['candidates']
p2=action('creator_calibration_propose',{});action('creator_calibration_approve',{'calibrationId':p2['calibrationId'],'confirmed':True})
action('creator_calibration_restore',{'calibrationId':p['calibrationId'],'confirmed':True})
assert next(v for v in c.overview(wid,'one')['calibration']['versions'] if v['id']==p['calibrationId'])['status']=='approved'
checks.append('daily allowance, unknown cost ledger, fifty-post chronological calibration, owner approve and restore; editors are refused every approval server-side')
# Owner measurement enrollment on a real database: own status only, owner only, leaving closes open readings.
from postriff_phase2.growth.metric_schedule import schedule as schedule_reads
measured=GrowthService(host,env={**ENV,'POSTRIFF_METRIC_READS':'1','POSTRIFF_METRIC_SELF_SERVE_ENABLED':'1','POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES':'5'},router_factory=models.router,clock=lambda:clock[0])
host.metric_reads=SimpleNamespace(workspace_allowed=lambda candidate:False)
view=measured.measurement_enrollment(wid,'one','GET')
assert view=={'feature':'growth_measurement','status':'none','eligible':True,'reason':'enrollment_open','admitted':False,'collecting':True},view
assert measured.catalog(wid,'one')['readiness']['measurement']['reasonCodes'][:1]==['measurement_enrollment_required']
refused(400,lambda:measured.measurement_enrollment(wid,'one','POST',{}))
assert measured.measurement_enrollment(wid,'one','POST',{'confirmed':True})['admitted'] is True
assert 'measurement_enrollment_required' not in measured.catalog(wid,'one')['readiness']['measurement']['reasonCodes']
with connection() as db,db.cursor() as cur:
    schedule_reads(cur,wid,'phase2-ig','instagram','ig-enrolled-1','job-enrolled-1',clock[0],'verification')
set_role('editor')
for method,payload in (('GET',None),('POST',{'confirmed':True}),('DELETE',None)):refused(403,lambda:measured.measurement_enrollment(wid,'one',method,payload))
set_role('owner')
left=measured.measurement_enrollment(wid,'one','DELETE')
assert (left['status'],left['admitted'])==('revoked',False),left
with connection() as db:
    closed=db.execute("SELECT status,failure_class FROM public.pr_metric_reads WHERE workspace_id=%s AND provider_post_id='ig-enrolled-1'",(wid,)).fetchall()
    kinds=db.execute("SELECT kind FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'feature.%%' ORDER BY at",(wid,)).fetchall()
assert closed and all(row==('cancelled','not_admitted') for row in closed),closed
assert [k[0] for k in kinds][-2:]==['feature.enrolled','feature.unenrolled'],kinds
del host.metric_reads
checks.append('owner-only measurement enrollment returns only its own status; leaving closes every open reading as not_admitted')
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
