"""Run after postgres_repository.py; disposable SQL and synthetic worker only."""
import copy
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Billing, FixturePaymentProvider, require_plan_capacity
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.hosted_worker import PostgresWorker
DSN="host=127.0.0.1 port=55438 dbname=postgres"
ONE="00000000-0000-0000-0000-000000000001"
TWO="00000000-0000-0000-0000-000000000002"
now=time.time()
def connection(): return psycopg.connect(DSN,client_encoding="utf8")
def verify(token): return ONE if token=="one" else TWO
service=HostedWorkspaceService(connection,verify,clock=lambda:now)
with connection() as db:
    wid=str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s",(ONE,)).fetchone()[0])
provider=FixturePaymentProvider()
billing=Billing(provider=provider)
def apply(cur,id,at,end):
    body=json.dumps({"id":id,"type":"subscription.updated","createdAt":at,"workspaceId":wid,"planTermsId":"assist-v1","currentPeriodEnd":end}).encode()
    return billing.process_webhook(cur,provider.sign(body),body)
with connection() as db:
    cur=db.cursor(); end=now+30*86400
    apply(cur,"guard-first",now,end)
    db.execute("UPDATE public.pr_entitlements SET writing_batches_remaining=7 WHERE workspace_id=%s",(wid,))
    apply(cur,"guard-same-period",now+1,end)
    assert db.execute("SELECT writing_batches_remaining FROM public.pr_entitlements WHERE workspace_id=%s",(wid,)).fetchone()[0]==7
    apply(cur,"guard-next-period",now+2,end+30*86400)
    assert db.execute("SELECT writing_batches_remaining FROM public.pr_entitlements WHERE workspace_id=%s",(wid,)).fetchone()[0]==100
    try: require_plan_capacity(cur,wid,"members")
    except AlphaError as e: assert e.code=="plan_limit_reached"
    else: raise AssertionError("full member allowance accepted")
    db.execute("UPDATE public.pr_entitlements SET members=2,connected_accounts=0 WHERE workspace_id=%s",(wid,))
    require_plan_capacity(cur,wid,"members")
    try: require_plan_capacity(cur,wid,"connected_accounts","new-channel")
    except AlphaError as e: assert e.code=="plan_limit_reached"
    else: raise AssertionError("zero account allowance accepted")
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')",(wid,TWO))
    try: require_plan_capacity(cur,wid,"members")
    except AlphaError: pass
    else: raise AssertionError("second new join accepted at limit")
# Private spend does not leave the server for a viewer.
owner=service.usage(wid,"one"); viewer=service.usage(wid,"two")
assert owner["budget"] is not None and viewer["budget"] is None
assert all("estimatedUsdMicro" not in row and "actualUsdMicro" not in row for row in viewer["ledger"])
assert viewer["billing"]["checkoutAvailable"] is False and viewer["billing"]["portalAvailable"] is False
assert all("chargeBatch" in row for row in owner["ledger"])
# The direct authenticated database path also hides raw costs from non-owners.
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2]/"migrations/postriff/014_billing_cost_visibility.sql").read_text())
    db.execute("INSERT INTO public.pr_usage_ledger(workspace_id,member_id,kind,dimension,cost_state,charge_batch,idempotency_key) VALUES(%s,%s,'reserve','tool','estimated',false,'cost-privacy-test')",(wid,ONE))
for principal,visible in [(ONE,True),(TWO,False)]:
    with connection() as db:
        db.execute("SET ROLE authenticated")
        db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)",(principal,))
        rows=db.execute("SELECT estimated_usd_micro FROM public.pr_usage_ledger WHERE workspace_id=%s",(wid,)).fetchall()
        assert bool(rows)==visible
# A paid workspace is not held by the expired trial timestamp left in its snapshot.
with connection() as db:
    state=db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s",(wid,)).fetchone()[0]
    state["phase2"]["trial"]["expiresAt"]=now-1
    state["phase2"]["jobs"][0].update(state="scheduled",attempts=[],nextAt=0,leaseUntil=0,leaseOwner=None,cancelRequested=False)
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),wid))
assert PostgresWorker(connection,clock=lambda:now).claim() is not None
# Expiry prevents a new provider submission, while uncertain jobs can still be reconciled.
with connection() as db:
    state=db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s",(wid,)).fetchone()[0]
    job=state["phase2"]["jobs"][0]
    job.update(state="scheduled",attempts=[],nextAt=0,leaseUntil=0,leaseOwner=None,cancelRequested=False)
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(state),wid))
    db.execute("UPDATE public.pr_subscriptions SET status='trial',current_period_end=to_timestamp(%s) WHERE workspace_id=%s",(now-1,wid))
class Social:
    submits=0; checks=0
    def submit(self,manifest): self.submits+=1; raise AssertionError("expired trial submitted")
    def reconcile(self,manifest,job): self.checks+=1; return {"state":"uncertain","confirmed":"Synthetic inconclusive reconciliation"}
social=Social(); worker=PostgresWorker(connection,social=social,clock=lambda:now)
worker.step()
with connection() as db:
    current=db.execute("SELECT state FROM public.pr_workspaces WHERE id=%s",(wid,)).fetchone()[0]
    assert current["phase2"]["jobs"][0]["state"]=="held"
    current["phase2"]["jobs"][0].update(state="uncertain",nextAt=0)
    db.execute("UPDATE public.pr_workspaces SET state=%s::jsonb WHERE id=%s",(json.dumps(current),wid))
worker.step()
assert social.submits==0 and social.checks==1
assert service.usage(wid,"one")["lifecycle"]["canPublish"] is False
print(json.dumps({"status":"pass","execution":"disposable local PostgreSQL; synthetic worker","checks":["same period does not refill","new period refills once","member and account caps","non-owner spend redaction","expired trial stops submission","uncertain posts still reconcile"]}))
