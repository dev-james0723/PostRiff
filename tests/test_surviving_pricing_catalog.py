"""Pricing contracts reused from surviving commits; fake cursors/transports only."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from postriff_alpha.domain import AlphaError
from postriff_phase2 import plan_pricing as pricing
from postriff_phase2.credit_meter import V2_POLICY_VERSION
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke

VARIANT = {'priceVariantId':'creator-59-v1','planTermsId':'creator-v1','priceId':'synthetic-price','status':'active','amountCents':5900,'currency':'USD'}

class Cursor:
    def __init__(self,present=True,malformed=False):
        self.present=present;self.malformed=malformed;self.calls=[];self.row=None;self.rows=[]
    def execute(self,sql,args=None):
        self.calls.append(sql)
        if "to_regclass" in sql:self.row=(self.present,)
        elif "FROM public.pr_plan_price_variants WHERE id" in sql:self.row=('creator-59-v1','creator-v1','synthetic-price','active',5900,'USD')
        elif "WHERE id IN ('trial-v1'" in sql:
            if not self.present:assert 'new_checkout_enabled' not in sql
            self.rows=[('studio-v1','studio','Studio',1900,'USD','active',False,{'writingBatches':10},'synthetic-legacy')]
        elif 'FROM public.pr_plan_terms' in sql and 'ORDER BY price_cents' in sql:
            self.rows=[('free-v1','free','Free',0,'USD','active',False,{},''),('creator-v1','creator','Creator',5900,'USD','active',True,{'monthlyCredits':3500,'creditPolicy':V2_POLICY_VERSION,'members': {'secret':'private'} if self.malformed else 1,'providerSecret':'private'},'')]
        elif 'SELECT plan,status,catalog_state,new_checkout_enabled' in sql:self.row=('creator','active','public',True,V2_POLICY_VERSION) if 'creditPolicy' in sql else ('creator','active','public',True)
        elif 'SELECT status,provider_subscription_id' in sql:self.row=None
        elif 'UNION ALL SELECT id FROM public.pr_plan_terms' in sql:self.rows=[('creator-59-v1',)]
        else:raise AssertionError(sql)
    def fetchone(self):return self.row
    def fetchall(self):return self.rows

class PublicCatalog(unittest.TestCase):
    def catalog(self,cur,enabled,credits_enabled=False):
        fn=getattr(pricing,'public_catalog',None)
        self.assertTrue(callable(fn),'The surviving server-owned public catalog must be available')
        return fn(cur,enabled,credits_enabled=credits_enabled)
    def test_pre048_legacy_does_not_read_new_columns(self):
        result=self.catalog(Cursor(False),False)
        self.assertEqual((result['pricing'],result['plans'][0]['priceCents']),('legacy',1900))
    def test_v2_before048_refuses_cleanly(self):
        with self.assertRaises(AlphaError) as caught:self.catalog(Cursor(False),True)
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'catalog_unavailable'))
    def test_free_creator_and_disabled_credit_checkout(self):
        result=self.catalog(Cursor(),True)
        self.assertEqual([p['plan'] for p in result['plans']],['free','creator'])
        self.assertEqual((result['plans'][0]['priceCents'],result['plans'][1]['priceCents'],result['plans'][1]['monthlyCredits']),(0,5900,3500))
        self.assertEqual([p['checkout'] for p in result['plans']],['not_applicable','not_yet_available'])
        self.assertFalse(result['topUps']['available'])
    def test_customer_entitlements_reject_private_and_malformed_values(self):
        result=self.catalog(Cursor(malformed=True),True)
        self.assertNotIn('members',result['plans'][1]['entitlements'])
        self.assertNotIn('private',str(result))
    def test_public_api_uses_the_catalog_without_a_session(self):
        service=FakeService();service.plans=Mock(return_value={'pricing':'v2','plans':[]})
        status,_,body=invoke(HostedApplication(service,FakeWorker()),'GET','/api/plans')
        self.assertEqual(status,200);self.assertEqual(body,{'pricing':'v2','plans':[]});service.plans.assert_called_once_with()

class Checkout(unittest.TestCase):
    def test_no_price_assignment_when_credits_cannot_be_spent(self):
        value=pricing.PlanPricing();value.ledger=SimpleNamespace(credits=None)
        with patch.object(value,'assign',return_value=VARIANT) as assign:
            with self.assertRaises(AlphaError) as caught:value.checkout(Cursor(),'00000000-0000-4000-8000-000000000001','creator-v1')
            self.assertEqual((caught.exception.status,caught.exception.code),(409,'credits_unavailable'));assign.assert_not_called()

if __name__=='__main__':unittest.main()
