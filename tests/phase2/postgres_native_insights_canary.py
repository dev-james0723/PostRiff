"""Native canary admission and no-retention contract on disposable PostgreSQL.
All identities, credentials and provider responses are synthetic.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.metric_schedule import MetricScheduler, NATIVE_ANALYTICS_SCOPES
from postriff_phase2.providers import InstagramProvider

ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
CONN = "native-canary-instagram"
def connection(): return psycopg.connect("host=127.0.0.1 port=55438 dbname=postgres", client_encoding="utf8")
def verify(token):
    if token != "one": raise AlphaError("Verified session required.", 401)
    return ONE
service = HostedWorkspaceService(connection, verify)
adapter = InstagramProvider("synthetic-client", "synthetic-secret")
adapter.identity = lambda token: {"providerAccountId": "123456"}
service.oauth.providers = {"instagram": adapter}
service.oauth.token_for_worker = lambda *args: {"provider": "instagram", "accessToken": "synthetic",
                                               "scopes": list(NATIVE_ANALYTICS_SCOPES["instagram"])}
calls = []
def transport(method, url, **kwargs):
    calls.append(url)
    return {"status": 200, "body": {"data": [{"id": "987654"}, {"id": "888"}] if "/media?" in url else
                    [{"name": "reach", "values": [{"value": 12}]}]}}
with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    foreign = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0])
    db.execute("UPDATE public.pr_memberships SET role='owner',status='active' WHERE user_id=%s", (ONE,))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,%s,'instagram','123456','sealed','fixture',%s)",
               (wid, CONN, list(NATIVE_ANALYTICS_SCOPES["instagram"])))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,%s,'analytics','Direct')", (wid, CONN))
probe = MetricScheduler(connection, service.oauth, transport=transport, workspace_allowlist={wid})
def run(): return probe.probe(wid, "one", CONN, {"confirmed": True})
def refused(status, operation):
    before = len(calls)
    try: operation()
    except AlphaError as error: assert error.status == status, (error.status, status)
    else: raise AssertionError("Expected refusal")
    assert len(calls) == before
first = run()
assert first["state"] == "done" and first["found"] == {"reach": 12} and len(calls) == 2
assert adapter.production_reviewed is False and adapter.account_scoped_direct is True
with connection() as db:
    for table in ("pr_owned_posts", "pr_metric_reads", "pr_metric_observations", "pr_history_imports"):
        assert db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (wid,)).fetchone()[0] == 0
    audits = db.execute("SELECT kind,meta FROM public.pr_audit_events WHERE workspace_id=%s AND kind LIKE 'metric_reads.canary_%%' ORDER BY at,id", (wid,)).fetchall()
    assert len(audits) == 2 and all("synthetic" not in json.dumps(meta) for _, meta in audits)
refused(403, lambda: probe.probe(foreign, "one", CONN, {"confirmed": True}))
refused(403, lambda: probe.probe(wid, "prt_synthetic", CONN, {"confirmed": True}))
with connection() as db: db.execute("UPDATE public.pr_memberships SET role='viewer' WHERE user_id=%s", (ONE,))
refused(403, run)
with connection() as db:
    db.execute("UPDATE public.pr_memberships SET role='owner' WHERE user_id=%s", (ONE,))
    db.execute("UPDATE public.pr_encrypted_credentials SET scopes=ARRAY['instagram_business_basic'] WHERE connection_id=%s", (CONN,))
refused(409, run)
with connection() as db: db.execute("UPDATE public.pr_encrypted_credentials SET scopes=%s WHERE connection_id=%s", (list(NATIVE_ANALYTICS_SCOPES["instagram"]), CONN))
adapter.execution_enabled = False
refused(409, run)
adapter.execution_enabled = True
adapter.account_scoped_direct = False
refused(409, run)
adapter.account_scoped_direct = True
with connection() as db: db.execute("INSERT INTO public.pr_growth_purges(workspace_id,connection_id) VALUES(%s,%s)", (wid, CONN))
refused(409, run)
with connection() as db: db.execute("DELETE FROM public.pr_growth_purges WHERE workspace_id=%s AND connection_id=%s", (wid, CONN))
assert run()["state"] == "done" and run()["state"] == "done"
refused(429, run)
# Opt-in public customer mode: real local billing SQL, synthetic invoice/provider facts only.
from postriff_phase2.customer_access import CustomerAccess
from postriff_phase2.hosted import bucket
from time import time
now = time()
with connection() as db:
    db.execute((Path(__file__).resolve().parents[2] / 'migrations/postriff/057_founder_billing_events.sql').read_text())
    db.execute("UPDATE public.pr_plan_terms SET status='active',provider_price_id='price_canary_fixture' WHERE id='studio-v1'")
    db.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,status,current_period_end) VALUES(%s,'studio-v1','stripe','sub_canary_fixture','active',to_timestamp(%s)) ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,provider=excluded.provider,provider_subscription_id=excluded.provider_subscription_id,status='active',current_period_end=excluded.current_period_end", (wid, now + 3600))
    with db.cursor() as cur: service.ledger.ensure_entitlement(cur, wid, 'studio')
    db.execute("UPDATE public.pr_entitlements SET plan_terms_id='studio-v1',source='subscription' WHERE workspace_id=%s", (wid,))
    db.execute("INSERT INTO public.pr_invoices(invoice_id,provider,workspace_id,subscription_id,period_start,period_end,amount_paid,currency,status,livemode,event_id,event_at) VALUES('invoice_canary_fixture','stripe',%s,'sub_canary_fixture',to_timestamp(%s),to_timestamp(%s),1900,'usd','paid',true,'event_canary_fixture',now())", (wid, now - 3600, now + 3600))
    db.execute('DELETE FROM public.pr_auth_throttle WHERE bucket=%s', (bucket(f'insights-canary:{wid}:{ONE}'),))
probe.customer_access = CustomerAccess(connection)
# App-role Direct is intentionally insufficient in public-customer mode.
refused(409, run)
adapter.production_reviewed = True
assert run()['state'] == 'done'
with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='expired' WHERE workspace_id=%s", (wid,))
refused(404, run)
with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='active' WHERE workspace_id=%s", (wid,))
def revoke_during_read(method, url, **kwargs):
    result = transport(method, url, **kwargs)
    if '/insights?' in url:
        with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='expired' WHERE workspace_id=%s", (wid,))
    return result
probe.transport = revoke_during_read
assert run()['state'] == 'cancelled'
with connection() as db:
    for table in ('pr_owned_posts', 'pr_metric_reads', 'pr_metric_observations', 'pr_history_imports'):
        assert db.execute(f'SELECT count(*) FROM public.{table} WHERE workspace_id=%s', (wid,)).fetchone()[0] == 0
with connection() as db:
    db.execute("UPDATE public.pr_subscriptions SET status='active' WHERE workspace_id=%s", (wid,))
    db.execute('DELETE FROM public.pr_auth_throttle WHERE bucket=%s', (bucket(f'insights-canary:{wid}:{ONE}'),))
probe.transport = transport
before = len(calls)
def expire_during_identity(token):
    with connection() as db:
        db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s', (time()-1, wid, CONN))
    return {'providerAccountId': '123456'}
adapter.identity = expire_during_identity
expired = run()
assert expired['state'] == 'cancelled' and expired['found'] == {} and len(calls) == before
with connection() as db: db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=NULL WHERE workspace_id=%s AND connection_id=%s', (wid, CONN))
adapter.identity = lambda token: {'providerAccountId': '123456'}
def expire_during_insights(method, url, **kwargs):
    result = transport(method, url, **kwargs)
    if '/insights?' in url:
        with connection() as db:
            db.execute('UPDATE public.pr_encrypted_credentials SET access_expires_at=to_timestamp(%s) WHERE workspace_id=%s AND connection_id=%s', (time()-1, wid, CONN))
    return result
probe.transport = expire_during_insights
expired = run()
assert expired['state'] == 'cancelled' and expired['found'] == {}
print(json.dumps({"execution": "disposable-db; synthetic providers", "checks": [
    "account-scoped canary succeeds without declaring provider reviewed",
    "one media and one insights GET; no imported or scheduled data",
    "content-free audit; membership, interactive sign-in and exact allowlist",
    "stored/live scopes, provider pause, purge admission and three requests/hour",
    "ordinary paid SQL admission requires public review; billing expiry before and during read cancels without retention",
    "credential expiry during identity prevents media dispatch; expiry during insights suppresses values"]}))
