import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from postriff_phase2.growth.trends.service import filters
from postriff_phase2.growth.trends import config
from postriff_phase2.customer_access import FLAG
from postriff_phase2.customer_access import CustomerAccess, BINDING
from postriff_phase2.growth.trends.enrichment import TrendEnrichment
from postriff_phase2.growth.trends.generation import TrendGeneration
from postriff_phase2.growth.trends.advanced_pipeline import AdvancedPipeline
from postriff_phase2.growth.trends.whitespace_admission import WhitespaceAdmission
from postriff_phase2.growth.trends import opportunities, notifications

WID='267f7d90-b11c-470c-9880-733ea7c1d483'

class PaidFixture(CustomerAccess):
    # SQL qualification has separate real-PostgreSQL coverage; no external billing claim here.
    def __init__(self): self.current=True
    def allowed(self,wid,**kwargs): return self.current and wid==WID
    def workspaces(self,**kwargs): return [WID] if self.current else []

class Cursor:
    def __init__(self): self.calls=[]; self.description=[]
    def execute(self,sql,params=()): self.calls.append((sql,params))
    def fetchall(self): return []
    def fetchone(self): return [True]

class Store:
    def __init__(self): self.cur=Cursor()
    @contextmanager
    def transaction(self): yield self.cur
    @contextmanager
    def connection(self): yield self
    @contextmanager
    def cursor(self): yield self.cur


class StudioTrends(unittest.TestCase):
    def test_mastodon_is_a_supported_platform_filter(self):
        self.assertEqual(['mastodon'],filters({'platform':'mastodon'},1800000000)['platforms'])

    def test_customer_mode_cannot_fall_back_to_uuid_allowlist_without_billing_reader(self):
        wid='267f7d90-b11c-470c-9880-733ea7c1d483'
        values={FLAG:'1','RAFII_TREND_INTELLIGENCE_ENABLED':'1','RAFII_TREND_WORKSPACE_ALLOWLIST':wid}
        self.assertFalse(config.workspace_allowed(wid,values))
        self.assertEqual([],config.admitted_workspaces(values))
        values[FLAG]='0'
        self.assertTrue(config.workspace_allowed(wid,values))
        self.assertEqual([wid],config.admitted_workspaces(values))

    def test_all_background_producers_admit_paid_customers_without_legacy_allowlist_and_recheck_revocation(self):
        access=PaidFixture()
        values={FLAG:'1',BINDING:access,'RAFII_NOTIFICATIONS_V2_ENABLED':'1',
                **{name:'1' for name in config.FLAG_NAMES}}
        for path in ('enrichment_plan','generation_plan','enrichment_tick','generation_tick',
                     'advanced_plan','whitespace_plan','notifications','opportunities'):
            with self.subTest(path=path):
                store=Store(); hosted=SimpleNamespace(repository=SimpleNamespace(connection_factory=store.connection))
                if path.startswith(('enrichment','generation')):
                    producer=(TrendGeneration if path.startswith('generation') else TrendEnrichment)(hosted,store=store,values=values)
                    call=producer.tick if path.endswith('tick') else producer.plan_current
                elif path=='advanced_plan': call=AdvancedPipeline(store,values=values).plan_current
                elif path=='whitespace_plan': call=WhitespaceAdmission(store,values=values).plan_current
                elif path=='notifications': call=lambda:notifications.tick(store,values=values)
                else: call=lambda:opportunities.refresh_workspace_candidates(hosted,values=values)
                access.current=True; call()
                self.assertTrue(any(WID in str(params) for _,params in store.cur.calls),path)
                store.cur.calls.clear(); access.current=False; call()
                self.assertEqual([],store.cur.calls,'Revoked billing must not plan, claim, or scan a workspace')

    def test_metric_observability_uses_current_customer_admission_and_fails_closed(self):
        from postriff_phase2.operational_signals import _metric_workspaces
        access=PaidFixture(); cur=Cursor()
        values={FLAG:'1',BINDING:access,'POSTRIFF_METRIC_WORKSPACE_ALLOWLIST':WID}
        self.assertEqual([WID],_metric_workspaces(cur,values))
        access.current=False
        self.assertEqual([],_metric_workspaces(cur,values))
        del values[BINDING]
        self.assertEqual([],_metric_workspaces(cur,values))
        values[FLAG]='0'
        self.assertEqual([WID],_metric_workspaces(cur,values))


if __name__=='__main__':unittest.main()
