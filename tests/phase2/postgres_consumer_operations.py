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
    # One stalled writing run counts as modelStuck; the Rafii Agent Runtime's rows (a task plan waiting on the person, a
    # turn, a live session) never do, however old: the runtime closes its own dead turns and sessions.
    actor='00000000-0000-0000-0000-000000000001'
    conv=db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'fixture') RETURNING id",(wid,actor)).fetchone()[0]
    for key in ('writing-run-fixture','task:fixture','agent:fixture','voice:fixture'):
        db.execute("INSERT INTO public.pr_agent_runs(conversation_id,workspace_id,actor,status,model,reasoning,context_digest,policy_epoch,idempotency_key,updated_at) VALUES(%s,%s,%s,'running','rafii-agent','standard',%s,%s,%s,to_timestamp(%s))",(conv,wid,actor,'a'*64,'b'*64,key,now-601))
    before=db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]
r=snapshot(connection,now)
assert r['status']=='attention' and r['counts']['publicationUncertain']==1 and r['counts']['queueDelayed']==1
assert r['counts']['publicationFailed']==1 and r['counts']['publicationHeld']==1 and r['counts']['researchStuck']==1
assert r['counts']['modelStuck']==1, r['counts']
assert private not in json.dumps(r) and str(wid) not in json.dumps(r) and r['notificationDelivery']=='not_configured'
with connection() as db:assert db.execute('SELECT state FROM public.pr_workspaces WHERE id=%s',(wid,)).fetchone()[0]==before
print('PASS real DB operational counts; no external alert, no contents, no state mutation')

# Production enables notifications v2, whose SUM(bigint) SMS cost is a PostgreSQL numeric
# (Decimal in psycopg), including when there are no SMS rows. Exercise the actual cron
# log and HTTP serialization with real aggregates and inert worker/provider steps.
from types import SimpleNamespace
from unittest.mock import patch
from postriff_phase2.coworker import flags
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import invoke
flags.attach({'RAFII_NOTIFICATIONS_V2_ENABLED': '1'})
service = SimpleNamespace(repository=SimpleNamespace(connection_factory=connection), run_reminders=lambda: {'sent': 0})
app = HostedApplication(service, SimpleNamespace(tick=lambda: {'processed': 0}), {}, 'c' * 24)
with patch('postriff_phase2.coworker.runtime.cron', return_value={'status': 'disabled'}):
    status, _, body = invoke(app, 'GET', '/api/cron/worker', headers={'Authorization': 'Bearer ' + 'c' * 24})
assert status == 200, (status, body)
assert body['phone']['status'] == 'disabled'
assert body['operations']['notificationDelivery'] == 'rafii_v2'
assert body['operations']['sms']['knownCostUsdMicro24h'] == 0
assert all(type(value) is int for value in body['operations']['sms'].values()), body['operations']['sms']
print('PASS notifications-v2 PostgreSQL aggregates serialize through the complete cron log and HTTP response')
