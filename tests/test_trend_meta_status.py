"""Public-source UI must never promote owned or synthetic evidence to LIVE."""
import unittest
from datetime import timedelta
import test_trend_contracts as F
from postriff_phase2.growth.trends.contracts import iso,instant
from postriff_phase2.growth.trends.meta_sources import source_status
from postriff_phase2.growth.trends import meta_sources

VERIFICATION_KEYS = {'implemented', 'runtime_bound', 'app_reviewed',
    'verified_scope_or_feature', 'live_read_verified', 'stored_and_processed',
    'production_ui_verified'}


class MetaVerification(unittest.TestCase):
    def test_seven_gates_never_promote_missing_or_synthetic_evidence(self):
        missing = meta_sources.source_verification(None, at=F.NOW, dispatch_enabled=True)
        self.assertEqual(set(missing), VERIFICATION_KEYS)
        self.assertEqual(missing['implemented'], 'VERIFIED')
        self.assertEqual(set(missing.values()), {'VERIFIED', 'UNVERIFIED'})
        self.assertTrue(all(missing[key] == 'UNVERIFIED' for key in VERIFICATION_KEYS - {'implemented'}))
        grant = dict(active=True, latest_successful_read=F.NOW,
            evidence_kind='synthetic', third_party=True, processing_verified=True,
            production_ui_verified=True)
        found = meta_sources.source_verification(grant, at=F.NOW, dispatch_enabled=True)
        self.assertEqual(found['app_reviewed'], 'VERIFIED')
        self.assertEqual(found['verified_scope_or_feature'], 'VERIFIED')
        for gate in ('runtime_bound', 'live_read_verified', 'stored_and_processed', 'production_ui_verified'):
            self.assertEqual(found[gate], 'UNVERIFIED')

    def test_genuine_read_processing_and_runtime_are_separate(self):
        grant = dict(active=True, latest_successful_read=F.NOW,
            evidence_kind='provider_response', third_party=True)
        found = meta_sources.source_verification(grant, at=F.NOW, dispatch_enabled=True)
        self.assertEqual(found['runtime_bound'], 'VERIFIED')
        self.assertEqual(found['live_read_verified'], 'VERIFIED')
        self.assertEqual(found['stored_and_processed'], 'UNVERIFIED')
        processed = meta_sources.source_verification({**grant, 'processing_verified':True},
            at=F.NOW, dispatch_enabled=False)
        self.assertEqual(processed['runtime_bound'], 'BLOCKED')
        self.assertEqual(processed['live_read_verified'], 'VERIFIED')
        self.assertEqual(processed['stored_and_processed'], 'VERIFIED')
        self.assertEqual(processed['production_ui_verified'], 'UNVERIFIED')
        paused = meta_sources.source_verification({**grant, 'next_allowed_at':F.AFTER},
            at=F.NOW, dispatch_enabled=True)
        self.assertEqual(paused['runtime_bound'], 'BLOCKED')
        self.assertEqual(paused['app_reviewed'], 'VERIFIED')

    def test_revocation_expiry_and_unverified_read_fail_closed(self):
        grant = dict(active=True, latest_successful_read=F.NOW,
            evidence_kind='provider_response', third_party=True, processing_verified=True)
        for change in ({'active':False}, {'revoked_at':F.NOW}):
            found = meta_sources.source_verification({**grant, **change},
                at=F.NOW, dispatch_enabled=True)
            self.assertTrue(all(found[key] == 'BLOCKED' for key in VERIFICATION_KEYS -
                {'implemented', 'production_ui_verified'}))
            self.assertEqual(found['production_ui_verified'], 'UNVERIFIED')
        for change in ({'third_party':False}, {'latest_successful_read':F.BEFORE},
                       {'latest_successful_read':F.AFTER}, {'evidence_kind':'owned'}):
            found = meta_sources.source_verification({**grant, **change},
                at=F.NOW, dispatch_enabled=True)
            for key in ('runtime_bound', 'live_read_verified', 'stored_and_processed'):
                self.assertEqual(found[key], 'UNVERIFIED')

class MetaStatus(unittest.TestCase):
    def test_only_current_genuine_third_party_evidence_is_live(self):
        base=dict(active=True,latest_successful_read=F.NOW, evidence_kind='provider_response',third_party=True)
        self.assertEqual(source_status(base,at=F.NOW),'LIVE')
        for patch in ({'active':False},{'evidence_kind':'synthetic'},{'third_party':False},
                      {'latest_successful_read':None},{'latest_successful_read':F.BEFORE},
                      {'next_allowed_at':F.AFTER}):
            with self.subTest(patch=patch):self.assertNotEqual(source_status({**base,**patch},at=F.NOW),'LIVE')
        self.assertEqual(source_status(None,at=F.NOW),'APP_REVIEW_REQUIRED')
        self.assertEqual(source_status({**base,'revoked_at':F.NOW},at=F.NOW),'REVOKED')
        self.assertEqual(source_status({**base,'latest_successful_read':iso(instant(F.NOW)+timedelta(seconds=1))},at=F.NOW),'UNVERIFIED')


class MetaProcessing(unittest.TestCase):
    def test_statistical_candidate_requires_current_verified_storage_status(self):
        from unittest.mock import Mock
        scope, sample = F.SCOPE, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        candidate = {'scope_key':scope, 'projection_id':'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'}
        cur = Mock(description=[])
        cur.fetchall.return_value = [candidate]
        store = Mock()
        for state, expected in (({'validity':'valid', 'verification_state':'verified'}, True),
                                ({'validity':'revoked', 'verification_state':'verified'}, False),
                                ({'validity':'valid', 'verification_state':'pending'}, False),
                                ({'validity':'method_unavailable', 'verification_state':'verified'}, False)):
            store._statuses.return_value = {(scope,candidate['projection_id']):state}
            with self.subTest(state=state):
                self.assertIs(meta_sources.processing_verified(store,cur,scope,sample), expected)
        sql, args = cur.execute.call_args.args
        self.assertEqual(args, (scope,sample))
        for required in ("p.kind='metric_snapshot'", "r.verification_state='verified'",
                         "'local_computation'", "'rafii.trend-dependency-anchor.v1'", "LIMIT 5"):
            self.assertIn(required, sql)
        store._statuses.assert_called_with(cur, [candidate])
        cur.fetchall.return_value = []
        store._statuses.reset_mock()
        self.assertFalse(meta_sources.processing_verified(store,cur,scope,sample))
        store._statuses.assert_not_called()

class MetaHttp(unittest.TestCase):
    def test_public_routes_require_interactive_auth_and_connection_permission(self):
        from test_trend_http import TrendHTTPTests
        harness=TrendHTTPTests('test_static_paths_never_interpreted_as_trend_ids');harness.setUp()
        self.assertEqual(harness.request(['public-sources'],token='')[0],401)
        self.assertEqual(harness.request(['public-sources'],token='prt_api')[0],403)
        harness.repo.role='viewer'
        self.assertEqual(harness.request(['public-sources','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],method='DELETE')[0],403)
        self.assertEqual(harness.request(['public-sources','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],method='POST')[0],404)

class MetaWire(unittest.TestCase):
    def test_database_datetimes_are_serialized_without_double_iso_conversion(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        from postriff_phase2.growth.trends import meta_sources
        class Cursor:
            description=[]
            sql=[]
            def execute(self,sql,args=None):self.sql.append(sql)
            def fetchone(self):return {'installed':True}
            def fetchall(self):return [dict(authorization_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                provider_id='threads',operation='keyword_search',active=True,revoked_at=None,
                latest_successful_read=instant(F.NOW),expires_at=instant(F.AFTER),
                evidence_kind='provider_response',third_party=True)]
        cur=Cursor()
        @contextmanager
        def transaction(*_args):yield None,cur,None,None,None,None
        service=SimpleNamespace(transaction=transaction,values={})
        with patch.object(meta_sources,'utcnow',return_value=F.NOW):
            response=meta_sources.read(service,F.WORKSPACE,'session')
        item=next(v for v in response['data'] if v['provider']=='threads')
        self.assertEqual(item['latest_successful_read'],F.NOW)
        self.assertEqual(item['status'],'PAUSED')
        self.assertEqual(set(item['verification']),VERIFICATION_KEYS)
        self.assertEqual(item['verification']['stored_and_processed'],'UNVERIFIED')
        self.assertEqual(item['verification']['production_ui_verified'],'UNVERIFIED')
        self.assertIn('pg_advisory_xact_lock_shared',cur.sql[1])
        self.assertIn('DISTINCT ON(a.provider_id,a.operation)',cur.sql[2])
        self.assertIn("a.review->>'verified_at' DESC",cur.sql[2])
