"""Real PostgreSQL/services/transactions; synthetic native identities, zero external calls."""
import copy
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(Path(__file__).parent)]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.coworker import review
from growth_phase2_fixtures import ENV,Models,Writer
from review_fixture import seed_review

ONE='00000000-0000-0000-0000-000000000001';TWO='00000000-0000-0000-0000-000000000002'
DSN=os.environ['POSTRIFF_TEST_DSN']
assert 'host=127.0.0.1' in DSN and 'port=55404' in DSN,'Dedicated disposable PG only'
def connection():return psycopg.connect(DSN)
def verify(token):
    if token in ('one','two'):return ONE if token=='one' else TWO
    raise AlphaError('Verified session required.',401)
def refused(status,fn):
    try:fn()
    except AlphaError as exc:assert exc.status==status,(status,exc.status,str(exc));return
    raise AssertionError('Expected refusal '+str(status))
with connection() as db:
    wid=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(ONE,)).fetchone()[0])
    foreign=str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s',(TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET status='active',role='owner' WHERE user_id IN (%s,%s)",(ONE,TWO))
    db.execute("UPDATE public.pr_workspaces SET state='{}' WHERE id=%s",(wid,))
clock=[time.time()]
host=HostedWorkspaceService(connection,verify,clock=lambda:clock[0],ideas_runtime=Writer());host.bootstrap('one','studio')
models=Models();host.growth=GrowthService(host,env={**ENV,'POSTRIFF_METRIC_READS':'1'},router_factory=models.router,clock=lambda:clock[0]);host.metric_reads=SimpleNamespace(workspace_allowed=lambda candidate:candidate==wid)
co=CoworkerService(host,{'POSTRIFF_SOURCE_SHA':os.environ['POSTRIFF_SOURCE_SHA']},clock=lambda:clock[0]);host.coworker=co;r=co.review
jobs=seed_review(host,wid,'one',clock[0]);conn=jobs[0]['manifest']['channelId']
scope={'channelIds':[conn],'publicationPeriod':{'start':review.iso(clock[0]-7*86400),'end':review.iso(clock[0]),'timezone':'UTC'},'horizon':'24h','cutoffAt':review.iso(clock[0]),'nativeMetric':[{'provider':'threads','nativeName':'views','unit':'count','definitionVersion':review.insights.DEFINITION_VERSION}]}
checks=[]
def current():return host.get(wid,'one')
def body(**extra):return {'workspaceRevision':current()['revision'],'idempotencyKey':str(uuid.uuid4()),**extra}
p=r.read(wid,'one',scope)
assert p['coverage']['eligible']==12 and p['groups'][0]['sampleSize']==12,p['coverage']
assert not models.calls and len(p['takeaways'])<=3
assert 'SYNTHETIC-SECRET' not in json.dumps(p)
refused(403,lambda:r.read(foreign,'one',scope));refused(401,lambda:r.read(wid,'invalid',scope))
checks.append('authorized exact native identities, metric-local times, sanitized endpoints, no model calls')
view_body=body(name='Dynamic week',filterDefinition={'channelIds':[conn],'relativeDateRule':{'kind':'this_week','timezone':'America/New_York'}},expectedRevision=0)
v=r.save_view(wid,'one',view_body)['record'];same=r.save_view(wid,'one',view_body)['record'];assert v==same
refused(409,lambda:r.save_view(wid,'one',{**view_body,'name':'Other body'}))
before=r.views(wid,'one')['views'][0]['resolvedContext']['publicationPeriod'];clock[0]+=8*86400
after=r.views(wid,'one')['views'][0]['resolvedContext']['publicationPeriod'];assert before!=after;clock[0]-=8*86400
updates=[body(id=v['id'],name='Concurrent '+str(i),filterDefinition=v['filterDefinition'],expectedRevision=v['revision']) for i in range(2)]
def update(b):
    try:r.save_view(wid,'one',b);return 'saved'
    except AlphaError as e:return e.status
with ThreadPoolExecutor(2) as pool:results=list(pool.map(update,updates))
assert sorted(map(str,results))==['409','saved'],results
checks.append('Saved View idempotency/body conflict, relative reopen, serialized optimistic concurrency')
e=p['nativeResults'][0];jid=e['publicationBinding']['jobId']
class_body=body(jobId=jid,manifestDigest=e['publicationBinding']['manifestDigest'],expectedRevision=0,tags=[{'tagId':'piano','kind':'series','label':'Piano teaching'}],source='ai_suggestion',confirmed=False)
r.classify(wid,'one',class_body);assert r.views(wid,'one')['classificationVersion']==0
class_body=body(**{k:v for k,v in class_body.items() if k not in ('workspaceRevision','idempotencyKey')});class_body['confirmed']=True
classified=r.classify(wid,'one',class_body)['record'];assert classified['version']==1
tag_scope={**scope,'tagSelection':[{'tagId':'piano','kind':'series','classificationVersion':1}]}
assert r.read(wid,'one',tag_scope)['coverage']['publications']==1
r.classify(wid,'one',body(jobId=jid,manifestDigest=e['publicationBinding']['manifestDigest'],expectedRevision=1,tags=[],source='human',confirmed=True))
assert r.read(wid,'one',tag_scope)['coverage']['publications']==1
assert r.read(wid,'one',{**tag_scope,'tagSelection':[{'tagId':'piano','kind':'series','classificationVersion':2}]})['coverage']['publications']==0
checks.append('unconfirmed suggestion excluded, versioned human confirmation and historical classification membership')
p=r.read(wid,'one',scope)
snapshot_body=body(scope=scope,contextDigest=p['contextDigest'],basisDigest=p['basisDigest'],humanNotes=['=SUM(A1:A2)','繁體中文週回顧，支持證據與反證。'],frequency='weekly')
s=r.create_snapshot(wid,'one',snapshot_body)['record']
assert r.create_snapshot(wid,'one',snapshot_body)['record']==s
assert r.snapshot(wid,'one',s['snapshotId'],1)==s
exports=[r.snapshot(wid,'one',s['snapshotId'],1,format_=f) for f in ('markdown','csv','pdf')]
assert all(x['payloadDigest']==s['payloadDigest'] and s['snapshotId'] in x['content'] and '繁體中文' in x['content'] for x in exports)
assert "'=SUM" in exports[1]['content']
p=r.read(wid,'one',scope)
s2=r.create_snapshot(wid,'one',body(scope=scope,contextDigest=p['contextDigest'],basisDigest=p['basisDigest'],humanNotes=['New note'],frequency='weekly',snapshotId=s['snapshotId'],expectedVersion=1))['record']
assert s2['version']==2 and r.snapshot(wid,'one',s['snapshotId'],1)['humanNotes']==s['humanNotes']
checks.append('fixed reports immutable versions, replay idempotency and three renderer payload parity / CSV injection')
# A failure in the same cursor after the state UPDATE must roll everything back.
p=r.read(wid,'one',scope);rev=current()['revision'];before_count=len(current()['state']['coworker']['review']['snapshots'])
original=r._snapshot_current
def failure(*args):raise AlphaError('Simulated current-rights race',403)
r._snapshot_current=failure
refused(403,lambda:r.create_snapshot(wid,'one',body(scope=scope,contextDigest=p['contextDigest'],basisDigest=p['basisDigest'],humanNotes=[],frequency='weekly')))
r._snapshot_current=original
assert current()['revision']==rev and len(current()['state']['coworker']['review']['snapshots'])==before_count
checks.append('prepare/commit current-rights race rolls back workspace state and revision')
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
refused(403,lambda:r.create_snapshot(wid,'one',snapshot_body))
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
checks.append('membership demotion blocks snapshot mutation and replay')
with connection() as db:db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND capability='analytics'",(wid,))
restricted=r.read(wid,'one',scope);assert not restricted['groups'] and all(e['value'] is None and not e['sourceRef'] for e in restricted['nativeResults'])
for f in (None,'markdown','csv','pdf'):refused(403,lambda:r.snapshot(wid,'one',s['snapshotId'],1,format_=f))
refused(403,lambda:r.create_snapshot(wid,'one',snapshot_body))
with connection() as db:db.execute("UPDATE public.pr_channel_capabilities SET level='Direct' WHERE workspace_id=%s AND capability='analytics'",(wid,))
checks.append('current grant revocation blocks new reads, snapshot replay and every export format')
with connection() as db:db.execute("UPDATE public.pr_metric_observations SET availability='unavailable',value=NULL WHERE workspace_id=%s AND id::text=%s",(wid,s['nativeResults'][0]['observationId']))
refused(409,lambda:r.snapshot(wid,'one',s['snapshotId'],1))
with connection() as db:db.execute("UPDATE public.pr_metric_observations SET availability='available',value=%s WHERE workspace_id=%s AND id::text=%s",(s['nativeResults'][0]['value'],wid,s['nativeResults'][0]['observationId']))
with connection() as db:db.execute('DELETE FROM public.pr_metric_observations WHERE workspace_id=%s AND id::text=%s',(wid,s['nativeResults'][0]['observationId']))
refused(410,lambda:r.snapshot(wid,'one',s['snapshotId'],1,format_='csv'))
checks.append('availability correction and deleted observation invalidate frozen-source replay')
assert not models.calls
result={'status':'PASS','execution':'real disposable PG/services; synthetic native evidence','sourceSha':os.environ['POSTRIFF_SOURCE_SHA'],'checks':checks,'realModelCalls':0,'nativeAcceptance':False}
destination=os.environ.get('POSTRIFF_REVIEW_EVIDENCE_DIR')
if destination:Path(destination,'postgres.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
