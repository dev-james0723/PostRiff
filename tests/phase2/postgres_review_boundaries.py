"""Additional current-rights and existing action boundaries on the owned test DB."""
import json
import os
from pathlib import Path
import runpy
import uuid

ROOT=Path(__file__).resolve().parents[2]
proof=runpy.run_path(str(ROOT/'tests/phase2/postgres_review.py'))
globals().update({key:proof[key] for key in ('host','co','r','wid','foreign','ONE','TWO','clock','connection','refused','models','seed_review','review')})
jobs=seed_review(host,wid,'one',clock[0]);conn=jobs[0]['manifest']['channelId']
scope={'channelIds':[conn],'publicationPeriod':{'start':review.iso(clock[0]-7*86400),'end':review.iso(clock[0]),'timezone':'UTC'},'horizon':'24h','cutoffAt':review.iso(clock[0]),'nativeMetric':[{'provider':'threads','nativeName':'views','unit':'count','definitionVersion':review.insights.DEFINITION_VERSION}]}
checks=[]
for patch in ({'workspaceId':foreign},{'channelIds':['foreign']},{'formatIds':['foreign']},{'tagSelection':[{'tagId':'foreign','kind':'theme','classificationVersion':0}]}):
    refused(400,lambda patch=patch:r.read(wid,'one',{**scope,**patch}))
checks.append('forged workspace, connection, format and classification identifiers rejected by server scope')
p=r.read(wid,'one',scope)
body={'workspaceRevision':host.repository.get(wid,'one')['revision'],'idempotencyKey':str(uuid.uuid4()),'scope':scope,'contextDigest':p['contextDigest'],'basisDigest':p['basisDigest'],'humanNotes':['Synthetic scope-isolation test'],'frequency':'weekly'}
s=r.create_snapshot(wid,'one',body)['record']
formats=(None,'markdown','csv','pdf')
for format_ in formats:
    refused(403,lambda format_=format_:r.snapshot(wid,'two',s['snapshotId'],1,format_=format_))
    refused(404,lambda format_=format_:r.snapshot(foreign,'two',s['snapshotId'],1,format_=format_))
with connection() as db:db.execute("UPDATE public.pr_memberships SET status='revoked' WHERE user_id=%s AND workspace_id=%s",(ONE,wid))
try:
    for format_ in formats:refused(403,lambda format_=format_:r.snapshot(wid,'one',s['snapshotId'],1,format_=format_))
    refused(403,lambda:r.create_snapshot(wid,'one',body))
finally:
    with connection() as db:db.execute("UPDATE public.pr_memberships SET status='active' WHERE user_id=%s AND workspace_id=%s",(ONE,wid))
checks.append('foreign member, foreign workspace snapshot ID and revoked membership cannot read, export or replay')
assert 'review' not in host.get(wid,'one')['state'].get('coworker',{})
checks.append('generic workspace presentation omits private snapshot values and idempotent results')
co.values['RAFII_GROWTH_EXPERIMENTS_ENABLED']='1'
p=r.read(wid,'one',scope);takeaway=next(t for t in p['takeaways'] if t['nextStep']['kind']=='propose')
proposal={'hypothesisId':takeaway['nextStep']['hypothesisId'],'minimumPerArm':5,'windowDays':14,'idempotencyKey':str(uuid.uuid4()),'reviewScope':scope,'reviewContextDigest':p['contextDigest'],'reviewBasisDigest':p['basisDigest']}
e=co.growth_loop.propose(wid,'one',proposal)['record']
assert co.growth_loop.propose(wid,'one',proposal)['record']['id']==e['id']
co.growth_loop.experiment_action(wid,'one',e['id'],{'action':'accept'})
checks.append('scope-bound existing hypothesis proposal is idempotent and explicitly owner-accepted')
row=p['nativeResults'][0]
with connection() as db:
    db.execute('UPDATE public.pr_metric_observations SET value=value+1 WHERE id=%s',(row['observationId'],))
try:
    refused(409,lambda:co.growth_loop.experiment_action(wid,'one',e['id'],{'action':'prepare'}))
    refused(409,lambda:co.growth_loop.propose(wid,'one',proposal))
finally:
    with connection() as db:db.execute('UPDATE public.pr_metric_observations SET value=value-1 WHERE id=%s',(row['observationId'],))
with connection() as db:db.execute("UPDATE public.pr_channel_capabilities SET level='Unsupported' WHERE workspace_id=%s AND connection_id=%s AND capability='analytics'",(wid,conn))
refused(409,lambda:co.growth_loop.experiment_action(wid,'one',e['id'],{'action':'prepare'}))
assert not models.calls
checks.append('changed metric or revoked analytics right invalidates prepare and proposal replay before model dispatch')
evidence={'status':'PASS','execution':'real owned disposable PG/services; synthetic native data and zero live dispatch','sourceSha':os.environ['POSTRIFF_SOURCE_SHA'],'checks':checks,'realModelCalls':0,'nativeAcceptance':False}
Path(os.environ['POSTRIFF_REVIEW_EVIDENCE_DIR'],'boundaries.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(evidence))
