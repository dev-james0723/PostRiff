"""Synthetic credit-mode browser fixture. Imported only by the disposable dev harness."""
import json
from pathlib import Path
from postriff_phase2.billing import Ledger
from postriff_phase2.model_runtime import ServerModelRuntime
from postriff_phase2.credit_meter import POLICY_VERSION


def configure(service, connection):
    root=Path(__file__).resolve().parents[1]
    with connection() as db:
        assert db.info.host=='127.0.0.1','Credit fixture must stay on loopback'
        db.execute((root/'migrations/postriff/020_credit_quotes.sql').read_text())
        db.execute((root/'migrations/postriff/021_credit_purchases.sql').read_text())
        db.execute((root/'migrations/postriff/022_credit_payment_lifecycle.sql').read_text())
    def transport(method,url,headers=None,body=None):
        payload=json.loads(body['messages'][1]['content'].split('\n\n')[0])
        variants=[{'platform':d['platform'],'language':d['languageId'],**({'channelId':d['channelId']} if d.get('channelId') else {}),
            'text':'Synthetic credit-test draft for '+d.get('account',d['platform'])+'.', 'sourceIds':[], 'warnings':['Synthetic writer: not a model-quality result.']} for d in payload['destinations']]
        return {'status':200,'body':{'choices':[{'message':{'content':json.dumps({'variants':variants})}}],
                'usage':{'cost':0.01,'prompt_tokens':10,'completion_tokens':20}}}
    runtime=ServerModelRuntime('synthetic-only',model='test/credit-writer',prices={'test/credit-writer':(1,1)},transport=transport)
    runtime.provider='synthetic-credit-provider'
    service.ledger=Ledger(credits_enabled=True)
    service.billing.ledger=service.ledger
    service.ideas.ledger=service.ledger
    service.ideas.runtime=runtime
    service.ideas.runtimes=[runtime]
    service.ideas._discover_cli=False
    from postriff_phase2.billing_stripe import StripePaymentProvider
    from postriff_phase2.credit_purchases import CreditPurchases
    def checkout_transport(method, url, headers=None, form=None):
        session='cs_'+form['metadata[credit_order_id]']
        return {'status':200,'body':{'id':session,'url':'https://checkout.stripe.com/c/pay/'+session}}
    provider=StripePaymentProvider('sk_test_local_synthetic','local-test-payment-signature',transport=checkout_transport)
    service.billing.provider=provider
    service.credit_purchases=CreditPurchases(service.ledger._credit_book,provider)
    service.credit_purchases_enabled=True

    original=service.bootstrap
    def bootstrap(token, *args, **kwargs):
        result=original(token,*args,**kwargs)
        wid=result['workspaceId']; actor=service.verify_session(token)
        ent={'writingBatches':10,'mediaCredits':1,'connectedAccounts':3,'members':3,'storageMb':200,'creditPolicy':POLICY_VERSION}
        with connection() as db:
            cur=db.cursor();service.ledger.ensure_entitlement(cur,wid,None)
            db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES('dev-credit-fixture','studio',998,'Synthetic credit fixture',0,'active',%s::jsonb) ON CONFLICT(id) DO NOTHING",(json.dumps(ent),))
            db.execute("UPDATE pr_entitlements SET plan_terms_id='dev-credit-fixture' WHERE workspace_id=%s",(wid,))
            service.ledger.credits.grant(cur,wid,actor,'dev-fixture-grant',50000,None,source='local-test-only')
            db.execute("INSERT INTO pr_credit_packs VALUES('dev-pack','Synthetic test credits',%s,'price_synthetic',1000,'usd',1000000,false,true) ON CONFLICT(id) DO NOTHING",(POLICY_VERSION,))
            service.ledger._budget(cur,'workspace:'+wid,'month')
            service.ledger._budget(cur,'global','day')
            db.execute("UPDATE pr_budgets SET status='approved' WHERE scope IN (%s,'global')",('workspace:'+wid,))
        return result
    service.bootstrap=bootstrap
