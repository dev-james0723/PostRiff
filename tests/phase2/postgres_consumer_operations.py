"""Read-only server aggregates use durable state; expose no identifiers or content."""
import json
import time
import psycopg
from postriff_phase2.operational_signals import snapshot

def connection():return psycopg.connect('host=127.0.0.1 port=55438 dbname=postgres')
now=time.time()
with connection() as db:
    wid=db.execute('SELECT id FROM public.pr_workspaces LIMIT 1').fetchone()[0]
    private='PRIVATE-CONTENT'
    jobs=[{'state':'uncertain','leaseUntil':now-1,'text':private},{'state':'scheduled','nextAt':now-121}, {'state':'scheduled','nextAt':now+10}, {'state':'verified','nextAt':0}, {'state':'failed'},{'state':'held'}]
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps({'phase2':{'jobs':jobs},'private':private}),wid))
    db.execute("INSERT INTO public.pr_research_requests(workspace_id,idempotency_key,request_digest,status,created_at) VALUES(%s,'synthetic','fixture','pending',to_timestamp(%s))",(wid,now-601))
    before=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
r=snapshot(connection,now)
assert r['status']=='attention' and r['counts']['publicationUncertain']==1 and r['counts']['queueDelayed']==1
assert r['counts']['publicationFailed']==1 and r['counts']['publicationHeld']==1 and r['counts']['researchStuck']==1
assert private not in json.dumps(r) and str(wid) not in json.dumps(r) and r['notificationDelivery']=='not_configured'
with connection() as db:assert db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]==before
print('PASS real DB operational counts; no external alert, no contents, no state mutation')
