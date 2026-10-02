"""Parent-owned PG17 only; actual Growth/Ledger and synthetic physical transports."""
import copy
import json
import unittest
import uuid

from postriff_alpha.domain import AlphaError
from postriff_phase2 import voice_sources
from postriff_phase2.growth.preview import MODEL, ROUTE, SCOPES
from growth_phase1_fixtures import Models
from postgres_growth_credit_rewrite import RewriteCreditPG, connection


class GenomeCatalogPG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):RewriteCreditPG.setUpClass()

    def setUp(self):
        self.f=RewriteCreditPG(methodName='test_full_pipeline_committed_credit_hold_actual_sum_and_quote_free_replay')
        self.f.setUp()

    def approve(self,**changes):
        policy=json.loads(self.f.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW'])
        self.f.g.env['POSTRIFF_GROWTH_PLATFORM_PREVIEW']=json.dumps({**policy,'paidBaseChecks':True,'workspaceDailyRuns':3,**changes})

    def status(self):return self.f.g.catalog(self.f.wid,'synthetic-growth')['genomeAnalysis']

    def body(self,count=1,**changes):
        return {'data':'text,platform,language,post_id,published_at\n'+''.join(
            f'Owned idea {i}.,Threads,en,genome-{i},2026-09-{i%28+1:02d}\n' for i in range(count)),
            'account':'synthetic-owned-genome','ownContent':True,'retainText':True,'confirmed':True,
            'requestKey':str(uuid.uuid4()),**changes}

    def run_genome(self,body):return self.f.g.imports(self.f.wid,'synthetic-growth',body)

    def money(self):
        with connection() as db:
            return (self.f.wallet(),db.execute('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',(self.f.wid,)).fetchone(),
                    db.execute("SELECT count(*),coalesce(sum((meta->'credits'->>'milli')::bigint),0) FROM pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'",(self.f.wid,)).fetchone())

    def test_managed_twenty_posts_committed_platform_hold_actual_sum_replay_and_no_lifetime(self):
        self.assertEqual(self.status()['reason'],'funding_unavailable')
        self.approve();before=self.money();committed=[];transport=self.f.runtime.transport
        def physical(*args,**kwargs):
            with connection() as db:
                rows=db.execute("SELECT r.estimated_usd_micro,r.meta,r.id::text FROM pr_usage_ledger r WHERE r.workspace_id=%s AND r.kind='reserve' AND r.meta->'platformPreview'->>'kind'='genome' AND NOT EXISTS(SELECT 1 FROM pr_usage_ledger s WHERE s.workspace_id=r.workspace_id AND s.reservation_id=r.id AND s.cost_state IN ('actual','released'))",(self.f.wid,)).fetchall()
            self.assertEqual(len(rows),1);self.assertNotIn('credits',rows[0][1]);committed.append(rows[0])
            return transport(*args,**kwargs)
        self.f.runtime.transport=physical
        self.assertTrue(self.status()['available']);self.assertEqual(self.money(),before)
        body=self.body(20,maxPosts=999,quantity=1,maximumUsdMicro=0,maxMilliCredits=0)
        result=self.run_genome(body)
        self.assertEqual((result['genome']['postCount'],result['userCreditsCharged']),(20,0))
        self.assertEqual(len(self.f.sent),40);self.assertTrue(all(r[0]==800000 for r in committed))
        self.assertEqual(self.run_genome(body),result);self.assertEqual(len(self.f.sent),40)
        self.assertEqual(self.money(),before)
        with connection() as db:
            rows=db.execute("SELECT s.actual_usd_micro,s.meta FROM pr_usage_ledger s JOIN pr_usage_ledger r ON r.id=s.reservation_id WHERE r.workspace_id=%s AND r.kind='reserve' AND r.meta->'platformPreview'->>'kind'='genome' AND s.kind='settle'",(self.f.wid,)).fetchall()
        self.assertEqual([r[0] for r in rows],[160000]);self.assertTrue(all('credits' not in r[1] for r in rows))
        self.assertTrue(self.status()['available']) # Managed has no Free one-time Genome gate.
        self.run_genome(self.body(1));self.assertEqual(len(self.f.sent),42)
        self.assertEqual(committed[-1][0],40000);self.assertEqual(self.status()['reason'],'rate_limited')
        self.assertEqual(self.money(),before)

    def test_independent_aggregate_capacity_current_windows_holds_and_withdrawal_before_io(self):
        self.approve();scope=SCOPES[1]
        with connection() as db:old=db.execute('SELECT status,stop_usd_micro,spent_usd_micro,reserved_usd_micro,window_start FROM pr_budgets WHERE scope=%s',(scope,)).fetchone()
        try:
            with connection() as db:db.execute("UPDATE pr_budgets SET status='approved',stop_usd_micro=799999,spent_usd_micro=0,reserved_usd_micro=0 WHERE scope=%s",(scope,))
            catalog=self.f.g.catalog(self.f.wid,'synthetic-growth')
            self.assertTrue(catalog['baseChecks']['available']);self.assertFalse(catalog['genomeAnalysis']['available'])
            saved=self.f.host.get(self.f.wid,'synthetic-growth')
            with self.assertRaises(AlphaError):self.run_genome(self.body(20))
            self.assertEqual(self.f.host.get(self.f.wid,'synthetic-growth'),saved);self.assertEqual(self.f.sent,[])
            with connection() as db:db.execute("UPDATE pr_budgets SET stop_usd_micro=1000000,spent_usd_micro=999999,reserved_usd_micro=0,window_start=date_trunc('month',now())-interval '1 month' WHERE scope=%s",(scope,))
            self.assertTrue(self.status()['available'])
            with connection() as db:db.execute('UPDATE pr_budgets SET reserved_usd_micro=200001 WHERE scope=%s',(scope,))
            self.assertFalse(self.status()['available'])
            with self.assertRaises(AlphaError):self.run_genome(self.body(20))
            with connection() as db:db.execute("UPDATE pr_budgets SET status='candidate',reserved_usd_micro=0 WHERE scope=%s",(scope,))
            self.assertFalse(self.status()['available'])
            with self.assertRaises(AlphaError):self.run_genome(self.body(1))
            self.assertEqual(self.f.sent,[])
        finally:
            with connection() as db:db.execute('UPDATE pr_budgets SET status=%s,stop_usd_micro=%s,spent_usd_micro=%s,reserved_usd_micro=%s,window_start=%s WHERE scope=%s',(*old,scope))

    def test_real_csv_owner_selected_grants_and_twenty_post_input_limits(self):
        self.approve(paidBaseChecks=False)
        with self.assertRaises(AlphaError):self.run_genome(self.body(1,paidBaseChecks=True))
        self.approve()
        with self.assertRaises(AlphaError):self.run_genome(self.body(21,quantity=20,maxPosts=999))
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        def seed(state,actor):
            voice_sources.apply_action(state,'voice_samples_import',{'format':'json','records':[{'text':'Selected owned idea.','platform':'Threads','externalId':'selected-only','account':'synthetic'}]},actor,self.f.now[0])
            source=state['sources'][-1];voice_sources.apply_action(state,'voice_sample_select',{'sourceId':source['id'],'selected':True},actor,self.f.now[0])
            return state
        self.f.host.repository.command(self.f.wid,'synthetic-growth',saved['revision'],seed,requirement='owner')
        selected=self.f.host.get(self.f.wid,'synthetic-growth')['state']['sources'][-1]['id']
        with connection() as db:db.execute("UPDATE pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(self.f.wid,self.f.actor))
        self.assertTrue(self.status()['available']);self.assertFalse(self.status()['csvImport']['available'])
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        payload={'sourceIds':[selected],'ownContent':True,'retainText':True,'confirmed':True,'requestKey':str(uuid.uuid4())}
        with self.assertRaises(AlphaError):self.run_genome(payload)
        self.assertEqual(self.f.sent,[])
        with connection() as db:db.execute("UPDATE pr_memberships SET role='owner' WHERE workspace_id=%s AND user_id=%s",(self.f.wid,self.f.actor))
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        def grant(state,actor):
            voice_sources.apply_action(state,'voice_sample_grant',{'sourceId':selected,'confirmed':True,'grants':[{'purpose':'analysis','route':ROUTE}]},actor,self.f.now[0]);return state
        self.f.host.repository.command(self.f.wid,'synthetic-growth',saved['revision'],grant,requirement='owner')
        with connection() as db:db.execute("UPDATE pr_memberships SET role='editor' WHERE workspace_id=%s AND user_id=%s",(self.f.wid,self.f.actor))
        result=self.run_genome({**payload,'requestKey':str(uuid.uuid4())})
        self.assertEqual((result['genome']['postCount'],result['userCreditsCharged'],len(self.f.sent)),(1,0,2))

    def test_current_pause_feature_provider_price_consent_and_midrun_revalidation(self):
        self.approve();before=self.money()
        self.f.g.env['POSTRIFF_GENOME']='0';self.assertFalse(self.status()['available'])
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.f.g.env['POSTRIFF_GENOME']='1';self.f.g.env['POSTRIFF_AI_PAUSED']='1'
        self.assertFalse(self.status()['available'])
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.f.g.env.pop('POSTRIFF_AI_PAUSED')
        prices=copy.deepcopy(self.f.runtime.prices);providers=copy.deepcopy(self.f.runtime.allowed_providers)
        self.f.runtime.allowed_providers={MODEL:['other']};self.assertFalse(self.status()['available'])
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.f.runtime.allowed_providers=providers;self.f.runtime.prices[MODEL]=(100.,100.)
        self.assertFalse(self.status()['available'])
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.f.runtime.prices=prices
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        self.f.g.action(self.f.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[]})
        self.assertEqual(self.status()['reason'],'consent_required')
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        saved=self.f.host.get(self.f.wid,'synthetic-growth')
        self.f.g.action(self.f.wid,'synthetic-growth',saved['revision'],'growth_consent',{'confirmed':True,'routes':[ROUTE]})
        self.assertEqual(self.f.sent,[])
        def change(index,body):
            if index==0:self.f.runtime.prices[MODEL]=(100.,100.)
        self.f.hook=change
        with self.assertRaises(AlphaError):self.run_genome(self.body(2))
        self.assertEqual(len(self.f.sent),1);self.assertEqual(self.money(),before)
        with connection() as db:
            rows=db.execute("SELECT s.actual_usd_micro FROM pr_usage_ledger s JOIN pr_usage_ledger r ON r.id=s.reservation_id WHERE r.workspace_id=%s AND r.kind='reserve' AND r.meta->'platformPreview'->>'kind'='genome' AND s.kind='settle'",(self.f.wid,)).fetchall()
        self.assertEqual(rows,[(4000,)])

    def test_expired_creator_free_genome_keeps_independent_lifetime_and_recent_twenty(self):
        self.approve(paidBaseChecks=False)
        with connection() as db:db.execute("UPDATE pr_subscriptions SET status='active',cancel_at_period_end=true,current_period_end=now()-interval '1 second' WHERE workspace_id=%s",(self.f.wid,))
        preview=self.f.g.preview_status(self.f.wid,'synthetic-growth')
        self.assertEqual(preview['postDoctor']['reason'],'used');self.assertEqual(preview['genome']['remaining'],1)
        self.assertEqual(self.status()['billingMode'],'free');self.assertTrue(self.status()['available'])
        body=self.body(20,quantity=1,maxPosts=999)
        result=self.run_genome(body)
        self.assertEqual((result['genome']['postCount'],result['userCreditsCharged'],len(self.f.sent)),(20,0,40))
        self.assertEqual(self.run_genome(body),result)
        self.assertEqual(self.status()['reason'],'used')
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.assertEqual(len(self.f.sent),40)
        self.assertEqual(self.f.g.preview_status(self.f.wid,'synthetic-growth')['genome']['maxPosts'],20)

    def test_legacy_history_keeps_existing_one_run_daily_path_without_operator_preview(self):
        with connection() as db:
            db.execute("UPDATE pr_entitlements SET plan_terms_id='studio-v1',source='subscription' WHERE workspace_id=%s",(self.f.wid,))
            db.execute("UPDATE pr_subscriptions SET plan_terms_id='studio-v1',price_variant_id=NULL WHERE workspace_id=%s",(self.f.wid,))
        self.f.g.env.pop('POSTRIFF_GROWTH_PLATFORM_PREVIEW');models=Models();self.f.g.router_factory=models.router
        self.assertEqual(self.status()['billingMode'],'legacy');self.assertTrue(self.status()['available'])
        result=self.run_genome(self.body())
        self.assertEqual(result['genome']['postCount'],1);self.assertEqual(len(models.calls),2)
        self.assertEqual(self.status()['reason'],'rate_limited')
        with self.assertRaises(AlphaError):self.run_genome(self.body())
        self.assertEqual(len(models.calls),2);self.assertEqual(self.f.sent,[])

if __name__=='__main__':unittest.main(verbosity=2)
