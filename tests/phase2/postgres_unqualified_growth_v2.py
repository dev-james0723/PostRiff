"""Owned actual PostgreSQL; synthetic provider/identity only, no external calls."""
import copy
import json
import time
import unittest
import uuid
from unittest.mock import Mock, patch
from types import SimpleNamespace

from phase2 import postgres_image_credits_v2 as fixture
from postriff_alpha.domain import AlphaError
from postriff_phase2.growth.service import GrowthService
from postriff_phase2.growth.history_import import HistoryImporter
from postriff_phase2.growth.scout_runtime import run_workspace
from postriff_phase2.radar.sources import Sources
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2 import automation_runs


class UnqualifiedGrowthV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixture.ImageCreditV2.setUpClass()

    def setUp(self):
        self.fx=fixture.ImageCreditV2(); self.fx.setUp()
        self.host=self.fx.service; self.wid=self.fx.wid; self.http=Mock(return_value={'posts':[]})
        self.g=GrowthService(self.host,env={'POSTRIFF_GROWTH':'1','POSTRIFF_RADAR':'1',
            'POSTRIFF_RADAR_SOURCES':'bluesky,exa','EXA_API_KEY':'synthetic-only',
            'POSTRIFF_RADAR_EXA_REQUEST_MICRO':'200000','POSTRIFF_RADAR_PRICE_REVIEWED_AT':
            __import__('datetime').datetime.fromtimestamp(fixture.NOW,__import__('datetime').timezone.utc).isoformat(),
            'POSTRIFF_RADAR_QUICK_USD_CAP':'2','POSTRIFF_GROWTH_DAILY_USD_CAP':'5',
            'POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP':'2','POSTRIFF_RADAR_MONITORING':'1'},clock=lambda:self.fx.now[0])
        self.r=self.g.radar; self.r.sources=Sources(self.g.env,http=self.http,clock=self.g.clock)
        self.r.action(self.wid,'synthetic',self.host.get(self.wid,'synthetic')['revision'],'radar_consent',
                      {'sources':['bluesky','exa'],'ai':False,'confirmed':True})

    def refusal(self,call):
        with self.assertRaises(AlphaError) as caught: call()
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'growth_credit_bridge_unavailable'))

    def quote(self,sources=None):
        return self.r.quote(self.wid,'synthetic',{'mode':'quick','query':'piano practice',
            'sources':sources or ['exa'],'useAi':False,'requestKey':str(uuid.uuid4())})

    def legacy(self):
        with fixture.connection() as db:
            db.execute("INSERT INTO public.pr_trials(user_id,workspace_id,plan,started_at,expires_at) "
                       "VALUES(%s,%s,'studio',to_timestamp(%s),to_timestamp(%s)) "
                       "ON CONFLICT(user_id) DO UPDATE SET workspace_id=excluded.workspace_id,plan=excluded.plan,"
                       "started_at=excluded.started_at,expires_at=excluded.expires_at",
                       (self.fx.actor,self.wid,self.fx.now[0],self.fx.now[0]+14*86400))
            db.execute("UPDATE pr_entitlements SET plan_terms_id=(SELECT id FROM pr_plan_terms WHERE plan='trial' ORDER BY version DESC LIMIT 1) WHERE workspace_id=%s",(self.wid,))

    def test_free_and_creator_refuse_paid_acquisition_without_quote_or_io(self):
        for mode in ('free','creator'):
            if mode=='creator': self.fx.paid()
            with self.subTest(mode=mode):
                self.refusal(self.quote); self.http.assert_not_called()
                with fixture.connection() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM pr_radar_runs WHERE workspace_id=%s',(self.wid,)).fetchone()[0],0)
                catalog=self.r.catalog(self.wid,'synthetic')
                self.assertFalse(catalog['paidScanAvailable']); self.assertFalse(catalog['aiAnalysisAvailable'])
                self.assertFalse(catalog['monitoringAvailable'])
                self.assertEqual(next(s['status'] for s in catalog['sources'] if s['id']=='exa'),'credit_bridge_unavailable')

    def test_explicit_zero_source_survives_free_with_no_customer_credit_quote(self):
        self.g.env['POSTRIFF_RADAR_CREDIT_BILLING']='1'
        q=self.quote(['bluesky']); self.assertEqual(q['maximumUsdMicro'],0); self.assertEqual(q['customerCharge'],'none')
        started=self.r.start(self.wid,'synthetic',q['id'],{'confirmed':True}); self.assertEqual(started['status'],'running')
        self.r.advance(self.wid,'synthetic',q['id']); self.assertEqual(self.http.call_count,1)
        with fixture.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s',(self.wid,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND meta ? 'credits'",(self.wid,)).fetchone()[0],0)

    def test_old_paid_quote_refuses_start_after_actual_entitlement_transition(self):
        self.legacy(); q=self.quote(); self.fx.paid()
        self.refusal(lambda:self.r.start(self.wid,'synthetic',q['id'],{'confirmed':True})); self.http.assert_not_called()
        with fixture.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM pr_radar_runs WHERE id=%s',(q['id'],)).fetchone()[0],'quoted')

    def test_running_scan_refuses_next_io_after_actual_entitlement_transition(self):
        self.legacy(); q=self.quote(); self.r.start(self.wid,'synthetic',q['id'],{'confirmed':True}); self.fx.paid()
        self.refusal(lambda:self.r.advance(self.wid,'synthetic',q['id'])); self.http.assert_not_called()
        self.r.action(self.wid,'synthetic',self.host.get(self.wid,'synthetic')['revision'],'radar_stop',{'scanId':q['id']})
        with fixture.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM pr_radar_runs WHERE id=%s',(q['id'],)).fetchone()[0],'cancelled')

    def test_scout_refuses_without_claim_or_retrieval(self):
        broker=Mock(); service=Mock(hosted=self.host,values={},clock=lambda:self.fx.now[0])
        result=run_workspace(service,self.wid,time.monotonic()+1000,broker=broker)
        self.assertEqual(result['reason'],'growth_credit_bridge_unavailable'); broker.search_items.assert_not_called()
        self.assertNotIn('scoutLease',self.host.get(self.wid,'synthetic')['state'].get('coworker',{}).get('listening',{}))

    def test_history_enqueue_worker_refuse_but_saved_status_is_readable(self):
        transport=Mock(); importer=HistoryImporter(fixture.connection,self.host.oauth,transport=transport,hosted=self.host)
        self.refusal(lambda:importer.request(self.wid,'synthetic','no-paid-connection',{'confirmed':True}))
        self.assertFalse(importer._eligible({'workspaceId':self.wid,'connectionId':'no-paid-connection'}))
        self.assertEqual(importer.status(self.wid,'synthetic','no-paid-connection')['status'],'none'); transport.assert_not_called()

    def test_direct_research_and_url_campaign_deny_before_source_selection(self):
        service=CoworkerService(self.host)
        with patch('postriff_phase2.coworker.flags.enabled',return_value=True), \
             patch.object(service,'_broker') as broker, \
             patch('postriff_phase2.coworker.source_intake.normalize') as normalize:
            for mode in ('free','creator'):
                if mode=='creator': self.fx.paid()
                with self.subTest(mode=mode):
                    self.refusal(lambda:service.research_search(self.wid,'synthetic','piano practice'))
                    self.refusal(lambda:service.source_campaign(self.wid,'synthetic',
                        {'format':'url','url':'https://fixture.invalid/article'}))
                    broker.assert_not_called(); normalize.assert_not_called()

    def test_fresh_broker_guard_refuses_after_actual_plan_transition(self):
        from postriff_phase2.coworker.research_broker import ResearchBroker
        service=CoworkerService(self.host); self.legacy()
        provider=Mock(id='synthetic',kind='fixture',hosted_ok=True)
        provider.capabilities.return_value={'operations':['search']}
        provider.readiness.return_value={'state':'ready'}
        broker=ResearchBroker(state={},providers=[provider])
        with patch.object(service,'_broker',return_value=broker):
            funded=service._funded_research_broker(self.wid,'synthetic',{})
        self.fx.paid()
        self.refusal(lambda:funded.search_items('piano practice',{'limit':1}))
        provider.search.assert_not_called()

    def test_real_automation_transaction_refuses_v2_before_search(self):
        state=copy.deepcopy(self.host.get(self.wid,'synthetic')['state'])
        state.setdefault('raffi',{})['campaignPlanning']={
            'occurrences':[{'id':'synthetic-occ','taskId':'synthetic-task'}],
            'recurringTasks':[{'id':'synthetic-task'}]}
        with fixture.connection() as db:
            db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s',(json.dumps(state),self.wid))
        task={'workflow':{'research':{'onNothing':'draft'}}}
        claim={'workspaceId':self.wid,'actor':self.fx.actor,'binding':None,
               'task':task,'occurrence':{'id':'synthetic-occ'}}
        worker=SimpleNamespace(service=self.host,clock=self.g.clock)
        with patch('postriff_phase2.automation_research.find') as find:
            for mode in ('free','creator'):
                if mode=='creator': self.fx.paid()
                with self.subTest(mode=mode):
                    self.refusal(lambda:automation_runs.research_step(worker,claim,self.host.repository,'synthetic'))
                    find.assert_not_called()
                    with fixture.connection() as db:
                        saved=db.execute('SELECT state FROM pr_workspaces WHERE id=%s',(self.wid,)).fetchone()[0]
                    self.assertNotIn('lifecycle',saved['raffi']['campaignPlanning']['occurrences'][0])


if __name__=='__main__': unittest.main(verbosity=2)
