"""R3 actual entry methods with synthetic SQL/transport sentinels; no DB/network."""
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
import hashlib
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.coworker.research_broker import ResearchBroker
from postriff_phase2.growth import credit_admission, scout_runtime, history_import
from postriff_phase2.growth.trends import credit_admission as trend_guard, enrichment, media_jobs
from postriff_phase2.growth.trends.store import TrendStore
from postriff_phase2.growth.trends.providers import bluesky, web
from postriff_phase2 import automation_runs
import test_growth_unqualified_v2 as old_growth
import test_task9_trends_funding_v2 as trend_fixtures
import test_trend_worker as old_worker
import test_trend_contracts as F

CODE='growth_credit_bridge_unavailable'
W=F.WORKSPACE

class Environment:
    def __init__(self, *, now=200, expiry=100, enabled=True, status='trial', terms='trial-v1'):
        self.now=now;self.expiry=expiry;self.status=status;self.terms=terms
        self.plan='trial' if terms=='trial-v1' else 'studio';self.policy=None
        self.depth=0;self.calls=[];self.sql=[];self.locked=False
        self.cur=Cursor(self)
        self.host=SimpleNamespace(billing=SimpleNamespace(pricing_v2_enabled=enabled),clock=self.clock,
            connection_factory=self.connection,ideas=SimpleNamespace(_member=lambda row:SimpleNamespace(allows=lambda permission:True)))
        self.repo=SimpleNamespace(transaction=self.transaction,get=lambda *a:{'state':{}})
        self.host.repository=self.repo
    def clock(self):
        self.assert_lock_for_clock = self.locked
        return self.now
    @contextmanager
    def transaction(self,*args):
        self.depth+=1
        try:yield self.cur,(1,{}),'actor'
        finally:self.depth-=1;self.locked=False
    def connection(self):return Database(self)
    def physical(self, result=None, *, expire=False, error=False):
        assert self.depth==0,'No synthetic transport under transaction/row lock'
        self.calls.append('physical')
        if expire:self.now=200
        if error:raise OSError('Synthetic failed attempt')
        return [] if result is None else result

class Cursor:
    def __init__(self,env):self.env=env;self.result=None;self.description=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,params=()):
        e=self.env;e.sql.append((sql,params));self.result=None
        if 'SELECT id FROM public.pr_workspaces' in sql:e.locked=True;self.result=(W,)
        elif sql.startswith('SELECT status,extract'):self.result=(e.status,None,False,e.expiry,e.terms)
        elif sql.startswith('UPDATE public.pr_subscriptions'):e.status=params[0]
        elif sql.startswith('SELECT plan_terms_id'):self.result=(e.terms,)
        elif sql.startswith('INSERT INTO public.pr_entitlements'):e.plan='free';e.terms='free-v1';e.policy=None
        elif '/* trends:funding */' in sql:self.result={'plan':e.plan,'credit_policy':e.policy}
        elif '/* trends:beneficiaries */' in sql:self.result={'workspace_id':W}
        elif "SELECT p.plan,p.entitlements->>'creditPolicy'" in sql:self.result=(e.plan,e.policy)
        elif "state ? 'accountDeletion'" in sql:self.result=(False,)
        elif 'SELECT state FROM public.pr_workspaces' in sql:e.locked=True;self.result=({},)
        elif sql.startswith(('SET LOCAL','UPDATE public.pr_workspaces')):pass
        elif sql.startswith('INSERT INTO public.pr_radar_runs'):self.result=('run',)
        elif 'public.pr_radar_runs' in sql:pass
        elif sql.startswith('SELECT 1 FROM public.pr_workspaces'):pass
        elif 'pr_strategy_hypotheses' in sql:pass
        else:raise AssertionError('Unexpected synthetic SQL: '+sql)
    def fetchone(self):return self.result
    def fetchall(self):return [] if self.result is None else [self.result]

class Database:
    def __init__(self,e):self.e=e
    def __enter__(self):self.e.depth+=1;return self
    def __exit__(self,*args):self.e.depth-=1;self.e.locked=False
    def cursor(self):return self.e.cur
    def transaction(self):return transaction_cursor(self.e)
    def commit(self):pass

def coworker(e,providers=None):
    c=CoworkerService.__new__(CoworkerService);c.hosted=e.host;c.clock=e.host.clock
    p=SimpleNamespace(id='synthetic',capabilities=lambda:{'operations':['search']},readiness=lambda state:{'state':'ready'},search=lambda *a:e.physical())
    c._broker=lambda state:ResearchBroker(providers or [p]);return c

class ExpiredAcquisition(unittest.TestCase):
    def denied(self,call):
        with self.assertRaises(AlphaError) as got:call()
        self.assertEqual(got.exception.code,CODE)
    def test_direct_research_entry_expires_without_usage_get(self):
        e=Environment();self.denied(lambda:coworker(e)._funded_research_broker(W,'session',{}).search_items('synthetic'))
        self.assertEqual(e.calls,[]);self.assertEqual(e.plan,'free');self.assertTrue(e.assert_lock_for_clock)
    def test_research_expiry_between_actual_fallback_providers(self):
        e=Environment(now=50)
        first=SimpleNamespace(id='first',capabilities=lambda:{'operations':['search']},readiness=lambda s:{'state':'ready'},search=lambda *a:e.physical(expire=True,error=True))
        second=SimpleNamespace(id='second',capabilities=first.capabilities,readiness=first.readiness,search=lambda *a:e.physical())
        broker=coworker(e,[first,second])._funded_research_broker(W,'session',{})
        self.denied(lambda:broker.search_items('synthetic'));self.assertEqual(len(e.calls),1)
    def test_true_legacy_and_unexpired_trial_controls(self):
        for enabled in (False,True):
            for status,terms in (('trial','trial-v1'),('active','studio-v1')):
                e=Environment(now=50,enabled=enabled,status=status,terms=terms)
                result=coworker(e)._funded_research_broker(W,'session',{}).search_items('synthetic')
                self.assertEqual(result['status'],'ok');self.assertEqual(len(e.calls),1)
    def test_actual_disabled_v2_config_keeps_approved_legacy_lifecycle(self):
        e=Environment(enabled=False)
        coworker(e)._funded_research_broker(W,'session',{}).search_items('synthetic')
        self.assertEqual(e.status,'expired');self.assertEqual(e.plan,'trial');self.assertEqual(len(e.calls),1)
    def test_radar_paid_entry_refuses_expired_stored_trial(self):
        e=Environment();r,_,_,sources=old_growth.UnsupportedV2().radar('legacy')
        r.host=e.host;r.g.hosted=e.host;r.tx=e.transaction;r.clock=e.host.clock
        with patch('postriff_phase2.radar.service._membership',return_value={}),patch('postriff_phase2.radar.service.require'):
            self.denied(lambda:r.quote(W,'session',{'mode':'quick','query':'piano','sources':['exa'],'requestKey':'synthetic-radar-key'}))
        sources.search.assert_not_called()
    def test_radar_queued_paid_dispatch_refuses_without_transport(self):
        e=Environment();r,_,_,sources=old_growth.UnsupportedV2().radar('legacy','running')
        r.host=e.host;r.g.hosted=e.host;r.tx=e.transaction;r.clock=e.host.clock
        with patch('postriff_phase2.radar.service._membership',return_value={}),patch('postriff_phase2.radar.service.require'):
            self.denied(lambda:r.advance(W,'session','run'))
        sources.search.assert_not_called()
    def test_scout_entry_refuses_before_lease_or_retrieval(self):
        e=Environment();service=SimpleNamespace(hosted=e.host,clock=e.host.clock,values={})
        broker=SimpleNamespace(search_items=Mock())
        with patch('postriff_phase2.growth.trends.config.workspace_allowed',return_value=False),patch.object(scout_runtime,'reserve',return_value=None) as reserve:
            result=scout_runtime.run_workspace(service,W,time.monotonic()+1000,broker=broker)
        self.assertEqual(result.get('reason'),CODE);reserve.assert_not_called();broker.search_items.assert_not_called()
    def test_automation_entry_refuses_before_any_research_attempt(self):
        e=Environment();service=e.host;service.automation_research=SimpleNamespace(search=Mock(),read=Mock())
        claim={'workspaceId':W,'task':{'workflow':{'research':{}}},'occurrence':{'id':'occ'},'actor':'actor','binding':{}}
        def update(_s,_w,_o,_a,fn,_b):fn({},claim['occurrence'],claim['task'],e.cur);return {}
        with patch.object(automation_runs,'_update_run',side_effect=update):
            self.denied(lambda:automation_runs.research_step(SimpleNamespace(service=service,clock=e.host.clock),claim,e.repo,'cap'))
        service.automation_research.search.assert_not_called()
    def test_history_worker_expires_before_credentials_or_page(self):
        e=Environment();oauth=SimpleNamespace(token_for_worker=Mock());transport=Mock()
        importer=history_import.HistoryImporter(e.connection,oauth,transport=transport)
        importer.hosted=e.host;importer._finish=Mock();importer._store_page=Mock()
        with patch.object(history_import.metric_schedule,'analytics_direct',return_value=True),patch.object(history_import,'purge_pending',return_value=False):
            result=importer.run_one({'workspaceId':W,'connectionId':'owned','provider':'threads','createdAt':200,'cursor':None,'pages':0,'attempts':1,'id':'run'},time.monotonic()+100)
        self.assertEqual(result,'cancelled');oauth.token_for_worker.assert_not_called();transport.assert_not_called()
    def test_history_expiry_between_physical_pages(self):
        e=Environment(now=50);oauth=SimpleNamespace(token_for_worker=lambda *a:{'accessToken':'synthetic'})
        importer=history_import.HistoryImporter(e.connection,oauth,transport=Mock());importer.hosted=e.host;importer._finish=Mock();importer._store_page=Mock(return_value=0)
        def page(*a):e.physical(expire=True);return {'posts':[],'next':'another','incomplete':False}
        with patch.object(history_import.metric_schedule,'analytics_direct',return_value=True),patch.object(history_import,'purge_pending',return_value=False),patch.object(history_import,'list_page',side_effect=page):
            result=importer.run_one({'workspaceId':W,'connectionId':'owned','provider':'threads','createdAt':200,'cursor':None,'pages':0,'attempts':1,'id':'run'},time.monotonic()+100)
        self.assertEqual(result,'cancelled');self.assertEqual(len(e.calls),1)
    def test_trends_model_and_paid_provider_expire_before_transport(self):
        for method in ('model','provider','shared'):
            e=Environment();store=SimpleNamespace(hosted=e.host,transaction=lambda:transaction_cursor(e))
            with self.subTest(method=method):
                if method=='model':self.denied(lambda:trend_guard.require_dispatch(store,W))
                else:self.denied(lambda:trend_guard.require_provider_dispatch(store,'workspace:'+W if method=='provider' else 'shared:synthetic',web.CAPABILITY,1))
                self.assertEqual(e.calls,[])
    def test_trends_expiry_between_physical_attempts_with_real_store_transaction(self):
        e=Environment(now=50);store=TrendStore(e.connection);store.hosted=e.host
        trend_guard.require_dispatch(store,W);e.physical(expire=True)
        self.denied(lambda:trend_guard.require_dispatch(store,W));self.assertEqual(len(e.calls),1)
    def test_known_zero_bluesky_and_saved_trends_reads_do_not_require_paid_authority(self):
        store=SimpleNamespace(transaction=Mock(side_effect=AssertionError('unmetered must not enter paid guard')))
        trend_guard.require_provider_dispatch(store,'workspace:'+W,bluesky.CAPABILITY,0);store.transaction.assert_not_called()
        e=Environment();TrendStore(e.connection)
        self.assertEqual(e.sql,[])
    def test_missing_actual_server_authority_never_defaults_to_legacy_paid_io(self):
        e=Environment(now=50)
        self.denied(lambda:credit_admission.require_qualified_entry(e.cur,W))
        self.denied(lambda:trend_guard.require_dispatch(TrendStore(e.connection),W))
        e.host.billing.pricing_v2_enabled='true'
        self.denied(lambda:coworker(e)._funded_research_broker(W,'session',{}))
        self.assertEqual(e.calls,[]);self.assertEqual(e.sql,[])
    def test_trend_model_actual_execute_refuses_expired_trial_before_transport(self):
        e=Environment();fixture=trend_fixtures.ModelFunding()
        fixture.store=TrendStore(e.connection,hosted=e.host);fixture.hosted=e.host
        fixture.transport=Mock(side_effect=AssertionError('expired trial must not reach synthetic model transport'))
        self.denied(lambda:fixture.execute_evaluator());fixture.transport.assert_not_called()
        self.assertEqual(e.plan,'free')
    def test_remote_media_actual_stage_expires_before_head_or_next_range(self):
        for now in (50,200):
            e=Environment(now=now);store=TrendStore(e.connection)
            coordinator=media_jobs.MediaJobs(e.host,store=store)
            loaded={'runtime':{'clips':[{'clip_id':'clip','media_sha256':hashlib.sha256(b'abc').hexdigest()}]},
                    'media':{'clip':{'objectName':'synthetic.mp4','bytes':3,'mime':'video/mp4','etag':'e'}}}
            storage=SimpleNamespace(object_info=lambda *a:e.physical({'bytes':3,'mime':'video/mp4','etag':'e'},expire=True),
                                    read_range=Mock(side_effect=AssertionError('expired range must not be requested')))
            with self.subTest(now=now),tempfile.TemporaryDirectory() as directory:
                self.denied(lambda:coordinator._stage(directory,W,loaded,lambda _:None,storage))
                self.assertEqual(len(e.calls),1 if now==50 else 0);storage.read_range.assert_not_called()
            self.assertIs(store.hosted,e.host)
    def test_model_constructor_binds_actual_host_to_existing_private_store(self):
        e=Environment();store=TrendStore(e.connection)
        coordinator=enrichment.TrendEnrichment(e.host,store=store)
        self.assertIs(coordinator.store.hosted,e.host)
        self.denied(lambda:trend_guard.require_dispatch(store,W))

@contextmanager
def transaction_cursor(e):
    with e.transaction() as (cur,_,__):yield cur

class ExpiredTrendWorker(old_worker.WorkerHarness):
    def setUp(self):
        super().setUp();self.e=Environment();self.store.hosted=self.e.host
        original=old_worker.ProbeCursor.execute
        def execute(cur,sql,params=None):
            if ('/* trends:funding */' in sql or '/* trends:beneficiaries */' in sql or
                sql.startswith(('SELECT id FROM public.pr_workspaces','SELECT status,extract','UPDATE public.pr_subscriptions','SELECT plan_terms_id','INSERT INTO public.pr_entitlements'))):
                self.e.cur.execute(sql,params);cur.result=[] if self.e.cur.result is None else [self.e.cur.result]
            else:original(cur,sql,params)
        p=patch.object(old_worker.ProbeCursor,'execute',execute);p.start();self.addCleanup(p.stop)
    def test_expired_worker_refuses_before_claim_or_adapter(self):
        result=self.worker.tick();self.assertEqual(result['dispatched'],0);self.assertEqual(result.get('reason_code'),CODE)
        self.jobs.claim.assert_not_called();self.adapter.assert_not_called()
    def test_expiry_after_claim_refuses_before_physical_adapter(self):
        self.e.now=50;start=self.start
        def changed(claim):value=start(claim);self.e.now=200;return value
        self.jobs.start.side_effect=changed
        result=self.worker.tick();self.assertEqual(result['dispatched'],0);self.adapter.assert_not_called()

if __name__=='__main__':unittest.main()
