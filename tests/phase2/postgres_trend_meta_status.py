"""Cloud PostgreSQL status gates with synthetic records and real local computation.

No provider/model traffic. The provider_response marker is deliberately seeded
test data, never proof of a real public read or production UI acceptance.
Run as its own disposable PostgreSQL target; no tests execute on import.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
import postgres_trend_meta as fixtures
from postriff_phase2.growth.trends import meta_sources
from postriff_phase2.growth.trends.contracts import iso
from postriff_phase2.growth.trends.pipeline import TrendPipeline
from postriff_phase2.growth.trends.providers.base import observation
from postriff_phase2.growth.trends.store import TrendStore, utcnow


class MetaStatusPostgres(unittest.TestCase):
    # Reuse only fixture helpers. Inheriting its TestCase would rerun its suite.
    setUpClass = classmethod(fixtures.MetaPostgres.setUpClass.__func__)
    setUp = fixtures.MetaPostgres.setUp
    connect = fixtures.MetaPostgres.connect
    new_workspace = fixtures.MetaPostgres.new_workspace
    grant = fixtures.MetaPostgres.grant

    def sample(self, grant, *, evidence_kind='provider_response', third_party=True):
        p, at = grant['policy'], utcnow()
        event_at = iso(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
                       - timedelta(minutes=20))
        native_id = str(uuid4().int)
        value = observation(policy=p, source_identity=p.provider_id + ':' + native_id,
            revision_identity='synthetic-status-v1', sequence=1, kind='raw_post', operation='create',
            payload={'platform':p.provider_id, 'native_id':native_id, 'author_status':'unknown',
                     'text':'Synthetic music conversation about piano practice and concert preparation.',
                     'language':'en'}, event_at=event_at, received_at=at, available_at=at,
            coverage_epoch='synthetic-status', contract_version=fixtures.meta.PROTOCOL,
            access_method='official_graph_json')
        value['provenance'].update(review_id=grant['id'], evidence_kind=evidence_kind,
                                   third_party=third_party)
        self.store.put_observation(value)
        return value

    def compute(self, grant, source, *, offline=False):
        store = TrendStore(self.connect, offline_replay=offline)
        pipeline = TrendPipeline(store, max_observations=5, max_episodes=1)
        event = {'event_id':str(uuid4()), 'event_type':'trend.ingested',
            'scope_key':grant['policy'].scope_key,
            'payload':{'provider_id':grant['policy'].provider_id, 'decision_cutoff':utcnow(),
                'observation_ids':[source['observation_id']], 'coverage_epoch':'synthetic-status',
                'completeness':'partial'}}
        with store.transaction() as cur:
            result = pipeline.consume(cur,event)
        self.assertTrue(result.get('receipts'), result)
        self.assertTrue(all(r['verification_state']=='verified' for r in result['receipts']), result)
        return result

    def read_source(self, grant):
        workspace = grant['workspace']
        @contextmanager
        def transaction(requested, _token):
            self.assertEqual(requested,workspace)
            with self.store.transaction() as cur:
                yield self.store,cur,None,None,None,None
        # The HTTP authentication/role boundary is covered by its dedicated tests.
        service = SimpleNamespace(transaction=transaction, values={
            'RAFII_TREND_INTELLIGENCE_ENABLED':'1', 'RAFII_TREND_RADAR_ENABLED':'1',
            'RAFII_TREND_PROVIDER_OPERATIONS_ENABLED':'1',
            'RAFII_TREND_ALLOWED_OPERATIONS':'threads:keyword_search'})
        result = meta_sources.read(service,workspace,'synthetic-interactive-session')
        return next(item for item in result['data'] if item['provider']=='threads')

    def test_read_requires_actual_verified_statistical_processing(self):
        grant = self.grant()
        source = self.sample(grant)
        before = self.read_source(grant)['verification']
        self.assertEqual(before['live_read_verified'],'VERIFIED')
        self.assertEqual(before['stored_and_processed'],'UNVERIFIED')
        self.compute(grant,source)
        after = self.read_source(grant)['verification']
        self.assertEqual(set(after),set(meta_sources.VERIFICATION_KEYS))
        for key in meta_sources.VERIFICATION_KEYS[:-1]:
            self.assertEqual(after[key],'VERIFIED',key)
        self.assertEqual(after['production_ui_verified'],'UNVERIFIED')

    def test_pending_receipt_or_generic_model_child_does_not_qualify(self):
        for invalid in ('pending','generic_model'):
            with self.subTest(invalid=invalid):
                grant = self.grant(workspace=self.new_workspace())
                self.compute(grant,self.sample(grant))
                with self.connect() as db:
                    if invalid=='pending':
                        db.execute("UPDATE public.pr_trend_trust_receipts SET verification_state='pending' WHERE scope_key=%s",
                            (grant['policy'].scope_key,))
                    else:
                        db.execute("UPDATE public.pr_trend_projections SET kind='model_interpretation' WHERE scope_key=%s AND kind='metric_snapshot'",
                            (grant['policy'].scope_key,))
                gates = self.read_source(grant)['verification']
                self.assertEqual(gates['live_read_verified'],'VERIFIED')
                self.assertEqual(gates['stored_and_processed'],'UNVERIFIED')

    def test_offline_or_synthetic_inputs_never_qualify(self):
        for offline, evidence in ((True,'provider_response'),(False,'synthetic')):
            with self.subTest(offline=offline,evidence=evidence):
                grant = self.grant(workspace=self.new_workspace())
                self.compute(grant,self.sample(grant,evidence_kind=evidence),offline=offline)
                gates = self.read_source(grant)['verification']
                self.assertEqual(gates['stored_and_processed'],'UNVERIFIED')
                self.assertEqual(gates['production_ui_verified'],'UNVERIFIED')
                if evidence=='synthetic':
                    self.assertEqual(gates['live_read_verified'],'UNVERIFIED')

    def test_unrelated_workspace_or_new_unprocessed_sample_cannot_borrow_receipt(self):
        grant = self.grant()
        self.compute(grant,self.sample(grant))
        self.assertEqual(self.read_source(grant)['verification']['stored_and_processed'],'VERIFIED')
        foreign = self.grant(workspace=self.new_workspace())
        self.sample(foreign)
        self.assertEqual(self.read_source(foreign)['verification']['stored_and_processed'],'UNVERIFIED')
        self.sample(grant)
        self.assertEqual(self.read_source(grant)['verification']['stored_and_processed'],'UNVERIFIED')

    def test_current_lineage_and_grant_revocation_withdraw_verification(self):
        for invalid in ('ancestor','projection','authorization'):
            with self.subTest(invalid=invalid):
                grant = self.grant(workspace=self.new_workspace())
                source = self.sample(grant)
                self.compute(grant,source)
                with self.connect() as db:
                    if invalid=='ancestor':
                        db.execute("UPDATE public.pr_trend_nodes SET validity='revoked' WHERE scope_key=%s AND node_id=%s",
                            (grant['policy'].scope_key,source['observation_id']))
                    elif invalid=='projection':
                        db.execute('''UPDATE public.pr_trend_nodes SET validity='revoked'
                            WHERE scope_key=%s AND node_id IN (SELECT projection_id FROM public.pr_trend_projections
                                WHERE scope_key=%s AND kind='metric_snapshot')''',
                            (grant['policy'].scope_key,grant['policy'].scope_key))
                    else:
                        db.execute('UPDATE public.pr_trend_meta_authorizations SET revoked_at=clock_timestamp() WHERE authorization_id=%s',
                            (grant['id'],))
                gates = self.read_source(grant)['verification']
                self.assertNotEqual(gates['stored_and_processed'],'VERIFIED')
                if invalid=='authorization':
                    for key in meta_sources.VERIFICATION_KEYS[1:-1]:
                        self.assertEqual(gates[key],'BLOCKED')


if __name__=='__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MetaStatusPostgres))
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
