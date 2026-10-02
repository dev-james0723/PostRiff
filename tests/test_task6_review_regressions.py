"""Task6 reviewer regressions: synthetic rows and recording payment callable only."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
from postriff_alpha.domain import AlphaError
from postriff_phase2 import hosted, plan_pricing
from postriff_phase2.billing import Billing
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from test_surviving_pricing_catalog import Cursor, VARIANT

WORKSPACE='00000000-0000-4000-8000-000000000001'
ACTOR='00000000-0000-4000-8000-000000000002'

class CatalogGate(unittest.TestCase):
    def test_malformed_monthly_credits_are_unknown_unavailable_not_coerced(self):
        for raw in (True,-1,'3500',{'private':'secret'},None,3500.0):
            with self.subTest(raw=raw):
                ent={'monthlyCredits':raw,'creditPolicy':V2_POLICY_VERSION}
                row=('creator-v1','creator','Creator',5900,'USD','active',True,ent,'')
                result=plan_pricing._plan_view(row,v2=True,variant=VARIANT,credits_enabled=True)
                self.assertIsNone(result['monthlyCredits'])
                self.assertNotIn('monthlyCredits',result['entitlements'])
                self.assertEqual(result['checkout'],'not_yet_available')
                self.assertNotIn('secret',str(result))
    def test_free_is_zero_and_valid_creator_quantity_matches_nested_projection(self):
        free=('free-v1','free','Free',0,'USD','active',False,{'monthlyCredits':True},'')
        self.assertEqual(plan_pricing._plan_view(free,v2=True)['monthlyCredits'],0)
        paid=('creator-v1','creator','Creator',5900,'USD','active',True,{'monthlyCredits':3500,'creditPolicy':V2_POLICY_VERSION},'')
        shown=plan_pricing._plan_view(paid,v2=True,variant=VARIANT,credits_enabled=True)
        self.assertEqual((shown['monthlyCredits'],shown['entitlements']['monthlyCredits'],shown['checkout']),(3500,3500,'available'))
    def test_rollback_catalog_does_not_reopen_migrated_legacy_sale(self):
        shown=plan_pricing.public_catalog(Cursor(True),False)
        self.assertEqual(shown['plans'][0]['checkout'],'not_yet_available')

class PaymentCursor:
    def __init__(self, sale): self.sale=sale;self.row=None;self.queries=[]
    def execute(self,sql,args=()):
        self.queries.append(sql)
        if 'SELECT status,provider_price_id,plan' in sql:
            self.row=('active','synthetic-legacy-price','studio',self.sale) if 'new_checkout_enabled' in sql else ('active','synthetic-legacy-price','studio')
        elif 'SELECT 1 FROM public.pr_plan_terms' in sql:
            self.row=(1,) if self.sale or 'new_checkout_enabled' not in sql else None
        elif 'SELECT provider_customer_id,status' in sql:self.row=None
        elif 'SELECT provider_customer_id FROM public.pr_subscriptions' in sql:self.row=('synthetic-retained-customer',)
        else:raise AssertionError(sql)
    def fetchone(self): return self.row

class Repository:
    def __init__(self, cur):self.cur=cur
    @contextmanager
    def transaction(self,token,workspace):yield self.cur,('workspace','actor','owner',True,True,True,True),ACTOR

class LegacySaleGate(unittest.TestCase):
    def service(self, sale):
        cur=PaymentCursor(sale)
        provider=SimpleNamespace(id='stripe',create_checkout_session=Mock(return_value={'id':'synthetic-session'}))
        svc=object.__new__(hosted.HostedWorkspaceService)
        svc.billing=SimpleNamespace(provider=provider,pricing_v2_enabled=False,lifecycle=Mock())
        svc.repository=Repository(cur);svc.public_base_url='https://synthetic.invalid';svc.clock=lambda:1800000000
        svc.email_lookup=lambda actor:'synthetic@example.invalid'
        return svc,cur,provider
    def test_disabled_legacy_checkout_never_calls_payment_provider(self):
        svc,cur,provider=self.service(False)
        with patch.object(hosted,'throttle'),patch.object(hosted,'audit'):
            with self.assertRaises(AlphaError) as caught:svc.billing_checkout(WORKSPACE,'synthetic-token','studio-v1')
        self.assertEqual(caught.exception.status,409);provider.create_checkout_session.assert_not_called()
    def test_enabled_pre048_legacy_checkout_still_works(self):
        svc,cur,provider=self.service(True)
        with patch.object(hosted,'throttle'),patch.object(hosted,'audit'):
            self.assertEqual(svc.billing_checkout(WORKSPACE,'synthetic-token','studio-v1'),{'id':'synthetic-session'})
        provider.create_checkout_session.assert_called_once()
    def test_disabled_new_sale_preserves_existing_customer_portal(self):
        svc,cur,provider=self.service(False)
        result=Billing.availability(svc.billing,cur,WORKSPACE)
        self.assertFalse(result['checkoutAvailable']);self.assertTrue(result['portalAvailable'])
