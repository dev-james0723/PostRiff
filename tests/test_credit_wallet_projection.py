"""Actual customer usage projection with synthetic SQL rows; no database/I/O."""
import copy
import unittest
from unittest.mock import Mock, patch
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import POLICY_VERSION, V2_POLICY_VERSION


class Cursor:
    def __init__(self, policy): self.policy=policy; self.one=None; self.many=[]
    def execute(self, sql, args=()):
        self.one=None; self.many=[]
        if "p.entitlements->>'creditPolicy'" in sql:
            self.one=('studio',self.policy,'active')
        elif "meta->'credits'->>'source'" in sql:
            self.many=[('internal-grant-id','verified-stripe-invoice')]
        elif "to_regclass('public.pr_plan_price_variants')" in sql:
            self.one=(False,)
        elif 'FROM public.pr_subscriptions' in sql:
            self.one=None
        elif 'SELECT kind,dimension,cost_state' in sql or 'FROM public.pr_plan_terms ORDER BY' in sql:
            self.many=[]
        else: raise AssertionError('Unexpected actual usage projection SQL: '+sql)
    def fetchone(self): return self.one
    def fetchall(self): return self.many


class CreditWalletProjection(unittest.TestCase):
    def test_candidate_and_v2_customer_usage_exclude_lots_without_changing_book_values(self):
        for policy in (POLICY_VERSION,V2_POLICY_VERSION):
            for switch in (False,True):
                with self.subTest(policy=policy,creditsEnabled=switch):
                    wallet={'availableMilliCredits':1000,'heldMilliCredits':2000,
                            'usedMilliCredits':15000,'debtMilliCredits':0,
                            'currentPeriodGrantMilliCredits':30000,'currentPeriodExpiresAt':1800000060,
                            'lots':[{'grantId':'internal-grant-id','milli':30000,'available':1000}]}
                    original=copy.deepcopy(wallet)
                    ledger=Ledger(credits_enabled=switch)
                    ledger._credit_book.view=Mock(return_value=wallet)
                    with patch.object(ledger,'ensure_entitlement',return_value={'planTermsId':'synthetic'}), \
                         patch.object(ledger,'_budget',return_value={'windowKind':'month','spent':0,'reserved':0,'warn':0,'stop':0,'status':'candidate'}):
                        result=ledger.usage_view(Cursor(policy),'synthetic-workspace','synthetic-actor')['credits']
                    self.assertNotIn('lots',result)
                    self.assertEqual(result['purchasedCredits'], [])
                    self.assertNotIn('internal-grant-id', repr(result))
                    for key in original.keys()-{'lots'}: self.assertEqual(result[key],original[key])
                    self.assertEqual(wallet,original,'Public projection must not mutate the accounting book')


if __name__=='__main__': unittest.main()
