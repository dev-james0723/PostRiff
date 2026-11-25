"""Actual PG catalog/check parity; parent-owned 55439 runner, synthetic HTTP only."""
import json
import unittest
import uuid

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.preview import ROUTE, SCOPES
from postgres_growth_credit_rewrite import RewriteCreditPG, connection

class BaseCheckCatalogPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):RewriteCreditPG.setUpClass()

    def setUp(self):
        self.f=RewriteCreditPG(methodName='test_full_pipeline_committed_credit_hold_actual_sum_and_quote_free_replay')
        self.f.setUp()

    def status(self):return self.f.g.catalog(self.f.wid,'synthetic-growth')['baseChecks']

    def approve(self,**changes):
        policy=json.loads(self.f.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW'])
        self.f.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW']=json.dumps({**policy,'paidBaseChecks':True,**changes})

    def check(self):
        return self.f.g.check(self.f.wid,'synthetic-growth',{'text':'One idea. Another idea!',
            'platform':'Threads','language':'en','confirmed':True,'requestKey':str(uuid.uuid4())})

    def financial(self):
        with connection() as db:
            return (db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND kind IN ('reserve','settle','release')",(self.f.wid,)).fetchone(),
                    db.execute("SELECT scope,status,spent_usd_micro,reserved_usd_micro FROM pr_budgets WHERE scope IN (%s,%s) ORDER BY scope",SCOPES).fetchall(),
                    db.execute("SELECT scope,calls,reserved_micro FROM pr_growth_budgets WHERE scope IN (%s,%s)",(SCOPES[0],'platform-preview:'+self.f.wid)).fetchall())

    def test_managed_readiness_matches_real_supported_check_without_customer_credits(self):
        self.assertEqual(self.status(),{'billingMode':'managed_credits','available':False,'reason':'funding_unavailable'})
        before=self.financial()
        self.approve()
        self.assertEqual(self.status(),{'billingMode':'managed_credits','available':True,'reason':None})
        self.assertEqual(self.financial(),before) # Catalog itself grants/holds/spends nothing.
        self.assertEqual(self.f.g.preview_status(self.f.wid,'synthetic-growth')['postDoctor']['remaining'],0)
        result=self.check()
        self.assertEqual(result['userCreditsCharged'],0)
        self.assertEqual(len(self.f.sent),1)
        self.assertEqual(self.f.sent[0]['body']['model'],ROUTE.split(':',2)[2])
        self.assertEqual((self.f.wallet()['heldMilliCredits'],self.f.wallet()['usedMilliCredits']),(0,0))
        self.assertEqual(self.status()['reason'],'rate_limited')

    def test_budget_windows_holds_withdrawal_consent_permission_and_flags_are_current(self):
        self.approve()
        with connection() as db:db.execute("UPDATE pr_budgets SET status='candidate' WHERE scope=%s",(SCOPES[1],))
        self.assertEqual(self.status()['reason'],'funding_unavailable')
        with self.assertRaises(AlphaError):self.check()
        self.assertEqual(self.f.sent,[])
        with connection() as db:db.execute("UPDATE pr_budgets SET status='approved',stop_usd_micro=1000000,spent_usd_micro=999999,reserved_usd_micro=0,window_start=date_trunc('month',now())-interval '1 month' WHERE scope=%s",(SCOPES[1],))
        self.assertTrue(self.status()['available']) # old spend resets as the real ledger window does
        with connection() as db:db.execute("UPDATE pr_budgets SET reserved_usd_micro=990000 WHERE scope=%s",(SCOPES[1],))
        self.assertEqual(self.status()['reason'],'funding_unavailable') # holds survive the boundary
        with self.assertRaises(AlphaError):self.check()
        self.assertEqual(self.f.sent,[])
        with connection() as db:db.execute("UPDATE pr_budgets SET reserved_usd_micro=0 WHERE scope=%s",(SCOPES[1],))
        self.f.g.env['POSTRIFF_AI_PAUSED']='1';self.assertFalse(self.status()['available'])
        self.f.g.env.pop('POSTRIFF_AI_PAUSED')
        self.f.g.env['POSTRIFF_POST_DOCTOR']='0';self.assertEqual(self.status()['reason'],'feature_disabled')
        self.f.g.env['POSTRIFF_POST_DOCTOR']='1'
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        self.f.g.action(self.f.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[]})
        self.assertEqual(self.status()['reason'],'consent_required')
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        self.f.g.action(self.f.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[ROUTE]})
        with connection() as db:db.execute("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(self.f.wid,self.f.actor))
        self.assertEqual(self.status()['reason'],'permission_required')
        self.assertEqual(self.f.sent,[])

    def test_current_expired_creator_uses_unchanged_free_lifetime_contract(self):
        with connection() as db:db.execute("UPDATE pr_subscriptions SET status='active',cancel_at_period_end=true,current_period_end=to_timestamp(%s) WHERE workspace_id=%s",(self.f.now[0]-1,self.f.wid))
        preview=self.f.g.preview_status(self.f.wid,'synthetic-growth')
        self.assertEqual(preview['postDoctor'],{'remaining':0,'eligible':False,'reason':'used'})
        self.assertEqual(preview['genome']['maxPosts'],20)
        self.assertEqual(self.status(),{'billingMode':'free','available':False,'reason':'used'})
        self.assertEqual(self.f.g.preview_status(self.f.wid,'synthetic-growth'),preview)
        self.assertEqual(self.f.sent,[])

if __name__=='__main__':unittest.main(verbosity=2)
