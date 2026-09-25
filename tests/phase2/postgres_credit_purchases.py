"""Signed synthetic payment events on disposable PostgreSQL; no network access."""
import hashlib,hmac,json,time,uuid
from pathlib import Path
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_meter import POLICY_VERSION

ROOT=Path(__file__).resolve().parents[2]
DSN='host=127.0.0.1 port=55438 dbname=postgres'
NOW=int(time.time());ACTOR=str(uuid.uuid4());SECRET='synthetic-webhook-only'
def connection(): return psycopg.connect(DSN,client_encoding='utf8')
def verify(token):
    if token!='fixture': raise AlphaError('Denied',403)
    return ACTOR
verify.session_id=lambda token,principal:'fixture-credit-purchase-session'
verify.auth_time=lambda token,principal:NOW
calls=[]
def transport(method,url,headers=None,form=None):
    calls.append(form);sid='cs_'+form['metadata[credit_order_id]']
    return {'status':200,'body':{'id':sid,'url':'https://checkout.stripe.com/c/pay/'+sid}}
provider=StripePaymentProvider('sk_test_fixture',SECRET,transport=transport,clock=lambda:NOW)
with connection() as db:
    assert db.info.host == '127.0.0.1' and db.info.port == 55438, 'Synthetic fixture must remain in disposable PostgreSQL'
    db.execute('INSERT INTO auth.users(id) VALUES(%s)', (ACTOR,))
    for file in ('020_credit_quotes.sql','021_credit_purchases.sql'):
        db.execute((ROOT/'migrations/postriff'/file).read_text())
service=HostedWorkspaceService(connection,verify,clock=lambda:NOW,billing_provider=provider,credits_enabled=True,public_base_url='https://example.invalid',email_lookup=lambda actor:'synthetic@example.invalid')
assert hasattr(service,'billing_credit_checkout'),'Hosted credit checkout must be wired'
service.credit_purchases_enabled=True
snap=service.bootstrap('fixture','studio');wid=snap['workspaceId']
with connection() as db:
    cur=db.cursor();service.ledger.ensure_entitlement(cur,wid,None)
    ent={'writingBatches':10,'mediaCredits':1,'members':2,'connectedAccounts':3,'storageMb':200,'creditPolicy':POLICY_VERSION}
    db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('test-purchases','studio',997,'Synthetic purchases',0,'active',%s::jsonb)",(json.dumps(ent),))
    db.execute("UPDATE pr_entitlements SET plan_terms_id='test-purchases' WHERE workspace_id=%s",(wid,))
    db.execute("INSERT INTO pr_credit_packs VALUES('test-pack','Synthetic credits',%s,'price_fixture',1000,'usd',100000,false,true)",(POLICY_VERSION,))
assert service.billing_credit_packs(wid,'fixture')['available']
order=service.billing_credit_checkout(wid,'fixture','test-pack','same-request-0001')
assert len(calls)==1
assert service.billing_credit_checkout(wid,'fixture','test-pack','same-request-0001')['orderId']==order['orderId']
assert len(calls)==1
with connection() as db: assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==0

def event(kind,obj,event_id,created=NOW):
    raw=json.dumps({'id':event_id,'type':kind,'created':created,'livemode':False,'data':{'object':obj}}).encode()
    signature=hmac.new(SECRET.encode(),f'{NOW}.'.encode()+raw,hashlib.sha256).hexdigest()
    return f't={NOW},v1={signature}',raw
payment={'id':order['sessionId'],'mode':'payment','payment_status':'paid','payment_intent':'pi_fixture','amount_total':1000,'currency':'usd','metadata':{'credit_order_id':order['orderId']}}
refund={'id':'re_fixture','payment_intent':'pi_fixture','amount':250,'currency':'usd','status':'succeeded'}
service.billing_webhook(*event('refund.created',refund,'evt_refund_first'))
service.billing_webhook(*event('checkout.session.completed',payment,'evt_paid'))
with connection() as db: assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==75000
assert service.billing_webhook(*event('checkout.session.completed',payment,'evt_paid'))['outcome']=='duplicate'
service.billing_webhook(*event('checkout.session.async_payment_succeeded',payment,'evt_paid_again'))
with connection() as db: assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==75000
service.billing_webhook(*event('refund.failed',{**refund,'status':'failed'},'evt_refund_failed',NOW+1))
with connection() as db: assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==100000
# Older refund status cannot overwrite the latest one.
service.billing_webhook(*event('refund.updated',refund,'evt_stale_refund',NOW))
with connection() as db: assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==100000
# Payment fields must match the server-side order.
try: service.billing_webhook(*event('checkout.session.completed',{**payment,'amount_total':1},'evt_bad_amount'))
except AlphaError as error: assert error.status==409
else: raise AssertionError('Mismatched payment accepted')
sig,raw=event('checkout.session.completed',payment,'evt_bad_signature')
try: service.billing_webhook(sig,raw+b' ')
except AlphaError as error: assert error.status==401
else: raise AssertionError('Invalid signature accepted')
service.credit_purchases_enabled=False
try: service.billing_credit_checkout(wid,'fixture','test-pack','disabled-request-1')
except AlphaError as error: assert error.status==503
else: raise AssertionError('Disabled checkout opened')
# Pausing new purchases cannot prevent refunds already owed.
service.billing_webhook(*event('refund.created',{**refund,'id':'re_second','amount':500},'evt_refund_second',NOW+2))
with connection() as db:
    assert service.ledger.credits.view(db.cursor(),wid)['availableMilliCredits']==50000
    db.execute('SET LOCAL ROLE authenticated')
    try:
        with db.transaction(): db.execute('SELECT * FROM pr_credit_orders')
    except psycopg.errors.InsufficientPrivilege: pass
    else: raise AssertionError('Private orders exposed')
print('PASS: server-bound checkout, no pre-payment credits, replay safety, refund-before-funding, failed/stale refunds, signature, amounts, pause and RLS')
