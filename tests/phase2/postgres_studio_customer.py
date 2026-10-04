"""Customer admission uses real SQL, synthetic signed-billing-shaped facts, no external dispatch."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.customer_access import CustomerAccess, FLAG
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.growth.service import GrowthService, ROUTES
from postriff_phase2.growth.trends import config
from growth_phase1_fixtures import ENV, Models, Writer

ONE = '00000000-0000-0000-0000-000000000001'
def connection(): return psycopg.connect(os.environ['POSTRIFF_TEST_DSN'])
def verify(token):
    if token == 'one': return ONE
    raise AlphaError('Sign in.', 401)

host = HostedWorkspaceService(connection, verify, ideas_runtime=Writer())
host.bootstrap('one','studio')
with connection() as db:
    wid = str(db.execute('SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s', (ONE,)).fetchone()[0])
    foreign = str(db.execute('SELECT id FROM public.pr_workspaces WHERE id<>%s', (wid,)).fetchone()[0])
    with db.cursor() as cur:host.ledger.ensure_entitlement(cur,wid,'studio')
clock = [time.time()]
access = CustomerAccess(connection, clock=lambda: clock[0])
assert access.status(wid)['reason'] == 'billing_evidence_unavailable'
with connection() as db: db.execute((ROOT/'migrations/postriff/057_founder_billing_events.sql').read_text())
assert not access.allowed(wid)
with connection() as db:
    db.execute("UPDATE public.pr_plan_terms SET status='active',provider_price_id='price_fixture' WHERE id IN ('studio-v1','assist-v1','assist-bounded-v1')")
    db.execute("INSERT INTO public.pr_subscriptions(workspace_id,plan_terms_id,provider,provider_subscription_id,status,current_period_end) VALUES(%s,'studio-v1','stripe','sub_customer','active',to_timestamp(%s)) ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id=excluded.plan_terms_id,provider=excluded.provider,provider_subscription_id=excluded.provider_subscription_id,status='active',current_period_end=excluded.current_period_end", (wid, clock[0]+3600))
    db.execute("UPDATE public.pr_entitlements SET plan_terms_id='studio-v1',source='subscription' WHERE workspace_id=%s", (wid,))
    db.execute("INSERT INTO public.pr_invoices(invoice_id,provider,workspace_id,subscription_id,period_start,period_end,amount_paid,currency,status,livemode,event_id,event_at) VALUES('invoice_customer','stripe',%s,'sub_customer',to_timestamp(%s),to_timestamp(%s),1900,'usd','paid',false,'event_fixture',now())", (wid,clock[0]-3600,clock[0]+3600))
assert not access.allowed(wid), 'test-mode invoice is not live paid admission'
with connection() as db: db.execute("UPDATE public.pr_invoices SET livemode=true WHERE invoice_id='invoice_customer'")
assert access.allowed(wid) and access.status(wid)['plan'] == 'studio'
assert access.workspaces() == [wid]
assert not access.allowed(foreign)
for table, field, bad, good in [('pr_subscriptions','status','expired','active'),
    ('pr_subscriptions','provider','fixture','stripe'),('pr_entitlements','source','manual','subscription'),
    ('pr_invoices','subscription_id','foreign-subscription','sub_customer'),
    ('pr_plan_terms','status','proposed','active')]:
    with connection() as db:
        clause = "WHERE id='studio-v1'" if table=='pr_plan_terms' else "WHERE invoice_id='invoice_customer'" if table=='pr_invoices' else 'WHERE workspace_id=%s'
        db.execute(f'UPDATE public.{table} SET {field}=%s {clause}', (bad,) if table in ('pr_plan_terms','pr_invoices') else (bad,wid))
    assert not access.allowed(wid), (table,field,bad)
    with connection() as db: db.execute(f'UPDATE public.{table} SET {field}=%s {clause}', (good,) if table in ('pr_plan_terms','pr_invoices') else (good,wid))
with connection() as db: db.execute("UPDATE public.pr_entitlements SET plan_terms_id='assist-v1' WHERE workspace_id=%s", (wid,))
assert not access.allowed(wid), 'subscription/entitlement mismatch'
with connection() as db: db.execute("UPDATE public.pr_entitlements SET plan_terms_id='studio-v1' WHERE workspace_id=%s", (wid,))
clock[0] += 3601
assert not access.allowed(wid) and access.workspaces() == []
clock[0] -= 3601
values={**ENV,FLAG:'1','RAFII_TREND_INTELLIGENCE_ENABLED':'1','_RAFII_CUSTOMER_ACCESS':access}
assert config.workspace_allowed(wid, values), 'paid customer does not need a hardcoded UUID allowlist'
assert not config.workspace_allowed(foreign, values)
models = Models()
growth = host.growth = GrowthService(host, env=values, router_factory=models.router, clock=lambda: clock[0])
assert growth.catalog(wid,'one')['customerAccess']['qualified']
consent = {'confirmed':True,'routes':list(ROUTES)}
growth.action(wid,'one',host.get(wid,'one')['revision'],'growth_consent',consent)
body={'text':'A small practical beginning.','platform':'Threads','confirmed':True,'requestKey':'customer-paid-check-0001'}
result = growth.check(wid,'one',body)
assert result and models.calls
for role in ('editor','viewer'):
    with connection() as db:db.execute('UPDATE public.pr_memberships SET role=%s WHERE workspace_id=%s AND user_id=%s',(role,wid,ONE))
    assert growth.catalog(wid,'one')['postDoctor']
    try:growth.action(wid,'one',host.get(wid,'one')['revision'],'growth_consent',consent)
    except AlphaError as error:assert error.status==403
    else:raise AssertionError('Non-owner granted model consent')
    body['requestKey']='customer-role-'+role+'-0001'
    if role=='editor':assert growth.check(wid,'one',body)
    else:
        before=len(models.calls)
        try:growth.check(wid,'one',body)
        except AlphaError as error:assert error.status==403
        else:raise AssertionError('Read-only member dispatched a model')
        assert len(models.calls)==before
with connection() as db:db.execute("UPDATE public.pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(wid,ONE))
from postriff_phase2.growth.history_import import HistoryImporter
from postriff_phase2.providers import ThreadsProvider
host.oauth.providers['threads']=ThreadsProvider('synthetic','synthetic',production_reviewed=True)
history=HistoryImporter(connection,host.oauth,transport=lambda *a,**k:None,customer_access=access)
with connection() as db:
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'customer-history','analytics','Direct')",(wid,))
    db.execute("INSERT INTO public.pr_encrypted_credentials(workspace_id,connection_id,provider,provider_account_id,access_ciphertext,key_id,scopes) VALUES(%s,'customer-history','threads','synthetic','sealed','k',%s)",(wid,['threads_basic','threads_manage_insights']))
history.request(wid,'one','customer-history',{'confirmed':True})
run=history.claim(1)[0]
assert history._eligible(run)
host.oauth.providers['threads'].production_reviewed=False
assert not history._eligible(run), 'account-scoped or app-role access cannot admit public paid history'
host.oauth.providers['threads'].production_reviewed=True
with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='expired' WHERE workspace_id=%s",(wid,))
assert not history._eligible(run)
assert history._store_page(run,{'posts':[],'next':None},clock[0]-90*86400,True) is None
count=len(models.calls)
assert not growth.catalog(wid,'one')['postDoctor']
try: growth.check(wid,'one',body)
except AlphaError as error: assert error.status==403 and error.code=='paid_studio_required'
else: raise AssertionError('expired paid replay accepted')
assert len(models.calls)==count and not config.workspace_allowed(wid,values)
with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='active' WHERE workspace_id=%s",(wid,))
def revoke():
    with connection() as db: db.execute("UPDATE public.pr_subscriptions SET status='expired' WHERE workspace_id=%s",(wid,))
models.before = revoke
body['requestKey']='customer-paid-check-0002'
try: growth.check(wid,'one',body)
except AlphaError as error: assert error.status in (403,409)
else: raise AssertionError('result committed after billing revocation during dispatch')
with connection() as db:
    assert db.execute("SELECT status FROM public.pr_post_doctor_runs WHERE workspace_id=%s AND request_key=%s", (wid,body['requestKey'])).fetchone()[0]=='cancelled'
    assert db.execute('SELECT count(*) FROM public.pr_plan_terms').fetchone()[0]==4
    for role in ('anon','authenticated'):
        assert not db.execute("SELECT has_table_privilege(%s,'public.pr_invoices','SELECT')",(role,)).fetchone()[0]
print(json.dumps({'execution':'local disposable PostgreSQL; synthetic billing/model fixtures only',
    'checks':['existing terms only','live-vs-test invoice','current paid period','entitlement reconciliation','foreign workspace','owner/editor/viewer','expired replay','mid-dispatch revocation','history review/paid fences','Trends without UUID allowlist','RLS']}))
