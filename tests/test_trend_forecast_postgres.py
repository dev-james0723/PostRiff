"""Real disposable SQL acceptance; every observation/review is SYNTHETIC.

The actual AdvancedPipeline producer exercises the unqualified path. A separate
explicitly reviewed synthetic time series exercises positive qualification. It
is not evidence of any live population, model accuracy or production promotion.
Historical imports/timestamps below exist only inside the disposable test DB.
"""
from copy import deepcopy
from datetime import timedelta
import os
import unittest
from unittest.mock import patch
import uuid

from postriff_phase2.growth.trends import advanced_pipeline, contracts, forecast
from postriff_phase2.growth.trends import forecast_admission as admission, forecast_evaluation as evaluation
from postriff_phase2.growth.trends import revocation
from postriff_phase2.growth.trends.pipeline import encode_manifest, decode_manifest
from postriff_phase2.growth.trends.store import TrendStore, TrendStorageError, bounded_json, row
import test_trend_advanced_pipeline as advanced_fixture
import test_trend_forecast as pure_fixture


def dedicated_test_dsn(environ=None):
    """Exact disposable runner only; reject all libpq redirect channels first."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from local_pg_target import selected_target
    env = os.environ if environ is None else environ
    target = selected_target(env, validate_fixture_dsns=False)
    if any(k in env for k in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS')):
        raise ValueError('libpq overrides forbidden')
    raw = env.get('POSTRIFF_TEST_DSN')
    if not raw:
        raise ValueError('explicit portable PostgreSQL runner required')
    p = conninfo_to_dict(raw)
    if (set(p) - {'host', 'port', 'dbname', 'user'} or p.get('host') != '127.0.0.1'
            or p.get('port') != str(target.port) or p.get('dbname') != 'postgres'):
        raise ValueError('exact disposable PostgreSQL target required')
    return make_conninfo(**p, connect_timeout='5')


class ForecastTargetGuard(unittest.TestCase):
    def test_exact_local_target_and_all_redirects_without_connect(self):
        import psycopg
        raw = 'host=127.0.0.1 port=55438 dbname=postgres'
        with patch.object(psycopg, 'connect', side_effect=AssertionError('no connection')):
            self.assertIn('55438', dedicated_test_dsn({'POSTRIFF_TEST_DSN': raw}))
            for name in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR', 'PGOPTIONS'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    dedicated_test_dsn({'POSTRIFF_TEST_DSN': raw, name: ''})
            for extra in (' hostaddr=198.51.100.1', ' service=prod', ' options=-csearch_path=public',
                          ' sslmode=require', ' password=not-a-real-password'):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    dedicated_test_dsn({'POSTRIFF_TEST_DSN': raw + extra})
            for bad in (raw.replace('55438', '5432'), raw.replace('postgres', 'production'),
                        raw.replace('127.0.0.1', 'localhost'), raw.replace('127.0.0.1', 'db.invalid')):
                with self.assertRaises(ValueError): dedicated_test_dsn({'POSTRIFF_TEST_DSN': bad})


@unittest.skipUnless(os.environ.get('POSTRIFF_TEST_DSN'), 'explicit disposable PostgreSQL runner required')
class ForecastPostgres(advanced_fixture.NoProviderIO):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.dsn = dedicated_test_dsn()
        original = advanced_fixture.sealed_fixture

        def synthetic_recognized_access():
            result = original()
            # The real pipeline will recompute a new seal over these SQL fixture
            # sources. No old receipt's verified state/digest is reused.
            for source in result['manifest']['source_revisions']:
                source['provenance'] = {'access_method': 'official_public_stream',
                                        'test_label': 'SYNTHETIC_REVIEWED_SQL_FIXTURE_ONLY'}
            return result

        with patch.object(advanced_fixture, 'sealed_fixture', synthetic_recognized_access):
            advanced_fixture.AdvancedPostgres.setUpClass.__func__(cls)
        cls.import_store = cls.store
        cls.role = 'forecast_acceptance_' + uuid.uuid4().hex[:12]
        cls.wid, cls.actor, cls.reviewer, cls.other_wid, cls.other_actor = [str(uuid.uuid4()) for _ in range(5)]
        with psycopg.connect(cls.dsn) as db:
            db.execute('CREATE ROLE ' + cls.role + ' NOSUPERUSER NOBYPASSRLS INHERIT')
            db.execute('GRANT service_role TO ' + cls.role)
            for actor in (cls.actor, cls.reviewer, cls.other_actor):
                db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor,))
                db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)', (actor,))
            for wid, actor in ((cls.wid, cls.actor), (cls.other_wid, cls.other_actor)):
                db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (wid,))
                db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')", (wid, actor))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'editor','active')", (cls.wid, cls.reviewer))

        def connect():
            db = psycopg.connect(cls.dsn)
            db.execute('SET ROLE ' + cls.role)
            return db

        cls.connect = staticmethod(connect)
        cls.store = TrendStore(connect)
        cls.seed_store = TrendStore(connect, offline_replay=True)
        cls.output_scope = 'workspace:' + cls.wid
        for scope in (cls.output_scope, 'workspace:' + cls.other_wid): cls.store.ensure_scope(scope)
        cls.store.grant_entitlement(cls.wid, cls.scope, ['retrieve', 'derive_metrics', 'share_across_workspaces'], cls.end)
        cls.values = advanced_fixture.flags(cls.wid, cls.other_wid)

    def setUp(self):
        super().setUp()
        self.db = self.connect(); self.cur = self.db.cursor()
        self.addCleanup(self.db.close); self.addCleanup(self.db.rollback)
        self.adapter = admission.ForecastAdmission(self.store, values=self.values)
        self.evaluator = evaluation.ForecastEvaluation(self.store, values=self.values)
        self.now = self.clock(); self.expiry = self.end
        self.methods = {}
        self._seed_reviewed_series()

    def clock(self):
        self.cur.execute('SELECT clock_timestamp() AS now')
        return row(self.cur)['now']

    def register(self, role, descriptor=None):
        if descriptor is None:
            control = {'state': 'production', 'role': role, 'runtime_digest': admission.runtime_digest(),
                       'review_authority': 'SYNTHETIC_SQL_REVIEW', 'reviewer_ids': [self.reviewer],
                       'evidence_class': 'retained_observed_data', 'allowed_access_methods': ['official_public_stream']}
            descriptor = {'method_id': 'synthetic.forecast.' + role + '.' + uuid.uuid4().hex,
                          'method_version': 'reviewed-synthetic-v1', 'artifact_digest': contracts.digest(control),
                          'config': {'forecast_admission': control}}
        self.store.put_method(descriptor['method_id'], descriptor['method_version'], descriptor['artifact_digest'],
                              descriptor['config'], cursor=self.cur)
        # Explicit synthetic SQL review; normal put_method never promotes.
        self.cur.execute("UPDATE pr_trend_method_versions SET qualification='qualified' WHERE method_id=%s AND version=%s",
                         (descriptor['method_id'], descriptor['method_version']))
        self.methods[role] = descriptor
        return descriptor

    def provenance(self, at):
        return {'reviewer_id': self.reviewer, 'authority': 'SYNTHETIC_SQL_REVIEW', 'reviewed_at': at,
                'decision': 'approved', 'evidence_ref': 'SYNTHETIC_SQL_FIXTURE_NOT_LIVE_QUALIFICATION'}

    def projection(self, kind, payload, refs, *, at=None, document=None, method=None):
        at = at or self.clock(); method = method or self.methods[kind.removeprefix('forecast_')]
        kwargs = {}
        if document is not None:
            document = deepcopy(document); document['manifest_digest'] = contracts.digest(document)
            recipe, chunks = encode_manifest(document)
            kwargs = {'recipe': recipe, 'chunks': chunks, 'document_digest': document['manifest_digest']}
        manifest = self.seed_store.put_manifest(self.output_scope, refs, decision_cutoff=at, available_at=at,
                                                retention_until=self.expiry, cursor=self.cur, **kwargs)
        payload = deepcopy(payload)
        if document is not None:
            key = 'prediction' if kind == 'forecast_candidate' else 'report'
            payload[key + '_ref'] = {'manifest_id': manifest['manifest_id'], 'document_digest': document['manifest_digest']}
            payload['source_bindings_ref'] = deepcopy(payload[key + '_ref'])
        oid = str(uuid.uuid4())
        self.seed_store.put_projection({'scope_key': self.output_scope, 'kind': kind, 'object_id': oid, 'revision': 1,
            'manifest_id': manifest['manifest_id'], 'method_id': method['method_id'], 'method_version': method['method_version'],
            'decision_cutoff': at, 'available_at': at, 'retention_until': self.expiry, 'payload': payload}, expected_revision=0, cursor=self.cur)
        record = self.store.get_projection(self.wid, self.actor, kind, oid, revision=1, cursor=self.cur)
        return {**record, 'manifest_id': manifest['manifest_id']}

    @staticmethod
    def ref(record): return {'object_id': record['object_id'], 'revision': record['revision']}

    @staticmethod
    def node(record): return {'scope_key': record['scope_key'], 'node_id': record['projection_id']}

    def _seed_reviewed_series(self):
        helper = pure_fixture.Forecast(); helper.setUp(); self.addCleanup(helper.doCleanups)
        p = helper.series(); shift = contracts.instant(self.now) - timedelta(minutes=5) - contracts.instant(p['decision_cutoff'])
        for window in p['history']:
            for key in ('window_start', 'window_end', 'available_at'):
                window[key] = contracts.iso(contracts.instant(window[key]) + shift)
        p['origins'] = [contracts.iso(contracts.instant(v) + shift) for v in p['origins']]
        p['decision_cutoff'] = contracts.iso(contracts.instant(p['decision_cutoff']) + shift)
        p['scope_key'] = self.output_scope
        self.sid = str(uuid.uuid4()); self.provider = 'synthetic-forecast-' + uuid.uuid4().hex
        start = contracts.iso(contracts.instant(p['history'][0]['window_start']) - timedelta(days=1))
        rights = {op: {'state': 'allow', 'policy_ref': 'SYNTHETIC_SQL_REVIEW', 'audience_scope': self.output_scope,
                       'expires_at': self.expiry} for op in contracts.PERMISSIONS}
        self.seed_store.register_contract(self.provider, 'v1', list(rights), start, self.expiry,
                                          {'test_label': 'SYNTHETIC_ONLY'}, cursor=self.cur)
        self.seed_store.register_policy({'scope_key': self.output_scope, 'provider_id': self.provider, 'version': 'v1',
            'rights': rights, 'effective_at': start, 'expires_at': self.expiry, 'retention_seconds': 40*86400,
            'readiness': 'ready', 'test_label': 'SYNTHETIC_ONLY'}, provider_contract_version='v1', cursor=self.cur)
        # Explicit offline fixture import: production APIs never preserve these
        # historical policy timestamps. Adapters below use the real live store.
        self.cur.execute('UPDATE pr_trend_provider_contracts SET available_at=%s WHERE provider_id=%s', (start, self.provider))
        self.cur.execute('UPDATE pr_trend_source_policies SET available_at=%s WHERE provider_id=%s', (start, self.provider))
        payload = {'platform': 'bluesky', 'native_id': self.sid, 'text': 'SYNTHETIC REVIEWED SERIES SOURCE ONLY',
                   'author_status': 'known', 'author_key': 'synthetic-forecast-author', 'is_repost': False}
        self.seed_store.put_observation({'schema_version': contracts.SCHEMA_VERSION, 'observation_id': self.sid,
            'scope_key': self.output_scope, 'provider_id': self.provider, 'source_identity': self.sid,
            'revision_identity': 'v1', 'revision_sequence': 1, 'kind': 'raw_post', 'operation': 'create',
            'event_at': start, 'received_at': start, 'available_at': start, 'retention_until': self.expiry,
            'coverage_epoch': 'synthetic-v1', 'source_policy_version': 'v1', 'provider_contract_version': 'v1',
            'rights': rights, 'payload': payload, 'payload_digest': contracts.digest(payload), 'time_basis': 'provider_event',
            'provenance': {'access_method': 'official_public_stream', 'test_label': 'SYNTHETIC_REVIEWED_SQL_FIXTURE_ONLY'},
            'deletion_key': self.sid}, cursor=self.cur)
        p['sources'] = [{'source_id': self.sid, 'scope_key': self.output_scope, 'platform': 'bluesky', 'original': True,
                         'event_at': start, 'available_at': start, 'expires_at': self.expiry, 'rights': {'analysis': True}}]
        for window in p['history']: window['evidence_refs'] = [self.sid]
        self.p = p; self.prediction = forecast.predict_candidates(p)
        self.source_ref = {'scope_key': self.output_scope, 'node_id': self.sid}
        self.bindings = [{'source_id': self.sid, **self.source_ref}]
        for role in ('candidate', 'preregistration', 'qualification'): self.register(role)
        self.register('evaluation', evaluation.method_descriptor(allowed_access_methods=['official_public_stream']))
        self.register('admission', admission.method_descriptor())
        receipt = self.store.get_projection(self.wid, self.actor, 'receipt', self.receipt_id, cursor=self.cur)
        self.candidate = self.projection('forecast_candidate', {'schema_version': 'trend.forecast.candidate.v1',
            'trend_id': self.trend_id, 'test_label': 'SYNTHETIC_REVIEWED_SQL_FIXTURE_ONLY'},
            [self.source_ref, self.node(receipt)], document={'artifact': self.prediction, 'source_bindings': self.bindings})
        self.pre = self.preregister(self.candidate, self.prediction, p['origins'], p['holdout_episode_ids'])

    def preregister(self, candidate, prediction, origins, holdouts, *, missing_slot=False):
        split = {'target': prediction['target'], 'method_bundle': prediction['method_bundle'],
                 'origins': sorted(contracts.instant(v).isoformat() for v in origins),
                 'holdout_episode_ids': sorted(holdouts), 'excluded_training_episode_ids': sorted(holdouts), 'holdout_group_ids': []}
        pre_at = contracts.iso(min(contracts.instant(v) for v in origins) - timedelta(hours=2))
        slot = {'trend_id': candidate['payload']['trend_id'], 'target_start': prediction['target_start'],
                'target_digest': contracts.digest(prediction['target']),
                **{k: prediction['target'][k] for k in ('cohort', 'horizon_steps', 'bin_hours')}}
        slots = [slot]
        if missing_slot: slots.append({**slot, 'target_start': contracts.iso(contracts.instant(slot['target_start']) + timedelta(hours=1))})
        plan = {**deepcopy(split), 'evaluation_cutoff': self.clock(), 'candidate_selection': {'slots': slots}}
        gate = {'preregistered_at': pre_at, 'holdout_opened_at': min(origins, key=contracts.instant),
                'target_digest': contracts.digest(prediction['target']), 'method_digest': contracts.digest(prediction['method_bundle']),
                'evaluation_plan_digest': contracts.digest(split), 'primary_loss': 'mae', 'min_episodes': 5, 'min_pairs': 10,
                'coverage_tolerance': .05}
        return self.projection('forecast_preregistration', {'schema_version': 'trend.forecast.preregistration.v1',
            'plan': gate, 'preregistration_digest': forecast.preregistration_digest(gate),
            'evaluation_plan': plan, 'provenance': self.provenance(pre_at)}, [self.source_ref], at=pre_at)

    def evaluate(self, candidate=None, pre=None):
        return self.evaluator.evaluate(self.wid, self.actor, self.ref(pre or self.pre),
                                       [self.ref(candidate or getattr(self, 'evaluation_candidate', self.candidate))], cursor=self.cur)

    def prepare_review(self):
        self.evaluated = self.evaluate()
        self.assertEqual(self.evaluated['payload']['state'], 'evaluated')
        hydrated = deepcopy(self.evaluated); self.adapter._hydrate(self.cur, hydrated, 'report')
        report = hydrated['payload']['report']; gate = self.pre['payload']['plan']
        # Qualification is learned before issuing the prediction it may admit.
        # Preserve the originally preregistered historical candidate selection;
        # issue a new synthetic prediction only after the evaluation cutoff.
        self.evaluation_candidate = self.candidate
        target_start = contracts.iso(contracts.instant(self.p['decision_cutoff']) + timedelta(hours=1))
        self.prediction = forecast.predict_candidates({**self.p, 'decision_cutoff': self.clock(), 'target_start': target_start})
        self.candidate = self.projection('forecast_candidate', {'schema_version': 'trend.forecast.candidate.v1',
            'trend_id': self.trend_id, 'test_label': 'SYNTHETIC_REVIEWED_SQL_FIXTURE_ONLY'},
            [self.source_ref, self.node(self.evaluation_candidate)],
            document={'artifact': self.prediction, 'source_bindings': self.bindings})
        self.review = self.projection('forecast_qualification', {'schema_version': 'trend.forecast.qualification.v1',
            'candidate': self.ref(self.candidate), 'evaluation': self.ref(self.evaluated), 'preregistration': self.ref(self.pre),
            'prediction_digest': self.prediction['prediction_digest'], 'report_digest': report['report_digest'],
            'dataset_digest': report['dataset_digest'], **{k: gate[k] for k in ('target_digest', 'method_digest', 'evaluation_plan_digest')},
            'preregistration_digest': self.pre['payload']['preregistration_digest'], 'provenance': self.provenance(self.clock())},
            [self.node(r) for r in (self.candidate, self.evaluated, self.pre)])
        self.args = {'candidate': self.ref(self.candidate), 'evaluation': self.ref(self.evaluated), 'review': self.ref(self.review), 'cursor': self.cur}
        return report

    def test_actual_040_no003_restricted_role_and_direct_browser_denial(self):
        self.cur.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
        self.assertEqual(self.cur.fetchone(), (False, False))
        self.cur.execute("SELECT to_regclass('public.pr_runtime'),relforcerowsecurity FROM pg_class WHERE oid='public.pr_trend_projections'::regclass")
        self.assertEqual(self.cur.fetchone(), (None, True))
        for table in ('pr_trend_observations', 'pr_trend_projections', 'pr_trend_manifest_chunks'):
            with self.subTest(table=table), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                with self.db.transaction():
                    self.cur.execute('SET LOCAL ROLE authenticated')
                    self.cur.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (self.actor,))
                    self.cur.execute('SELECT * FROM ' + table)

    def test_actual_advanced_candidate_chunk_hydration_and_insufficient_evaluation(self):
        pipeline = advanced_pipeline.AdvancedPipeline(self.store, values=self.values)
        job = pipeline.enqueue(self.wid, self.actor, self.trend_id, kinds=('forecast_candidate',), cursor=self.cur)['jobs'][0]
        output = pipeline.run(self.output_scope, job['job_id'], cursor=self.cur)
        self.assertEqual(output['state'], 'succeeded')
        candidate = self.store.get_projection(self.wid, self.actor, 'forecast_candidate', output['object_id'], cursor=self.cur)
        root = candidate['payload']; self.assertNotIn('source_bindings', root)
        self.assertEqual(root['prediction_ref'], root['source_bindings_ref'])
        self.assertLess(len(contracts.canonical(root).encode()), 65536)
        hydrated = deepcopy(candidate); self.adapter._hydrate(self.cur, hydrated, 'prediction')
        prediction = hydrated['payload']['prediction']
        self.assertTrue(forecast._intact(prediction, 'prediction_digest'))
        self.assertEqual(prediction['execution_state'], 'offline')
        self.assertEqual(prediction['scope_key'], self.output_scope)
        self.assertTrue(hydrated['payload']['source_bindings'])
        self.assertEqual({b['scope_key'] for b in hydrated['payload']['source_bindings']}, {self.scope})
        self.assertEqual(len(hydrated['payload']['source_bindings']), len({r for h in prediction['prediction_recipe']['history'] for r in h['evidence_refs']} | set(prediction['evidence_refs'])))
        # The actual producer stays shadow. A synthetic SQL review of its exact
        # registry row is necessary even to run this operator-only evaluation.
        pre = self.preregister(candidate, prediction, [self.cutoff], ['synthetic-unobserved-holdout'])
        with self.assertRaisesRegex(TrendStorageError, 'production_method_required'): self.evaluate(candidate, pre)
        control = {'forecast_admission': {'state': 'production', 'role': 'candidate', 'runtime_digest': admission.runtime_digest()}}
        self.cur.execute("UPDATE pr_trend_method_versions SET qualification='qualified',config=%s WHERE method_id=%s AND version=%s",
                         (bounded_json(control), candidate['method_bundle']['method_id'], candidate['method_bundle']['version']))
        result = self.evaluate(candidate, pre)
        self.assertEqual(result['payload']['state'], 'insufficient_history')
        self.assertFalse(result['payload']['forecast_wording_enabled'])

    def test_synthetic_reviewed_positive_actual_evaluate_admit_persist_read_and_retry(self):
        report = self.prepare_review()
        self.assertEqual(report['metrics'][forecast.CANDIDATE]['count'], 10)
        self.assertEqual(set(report['metrics']), {'last_value', 'seasonal_naive', forecast.CANDIDATE})
        saved = self.adapter.persist(self.wid, self.actor, **self.args)
        self.assertEqual(saved['payload']['state'], 'qualified')
        replay = self.adapter.read(self.wid, self.actor, saved['object_id'], revision=1, cursor=self.cur)
        self.assertEqual(replay['payload']['predictions'], saved['payload']['predictions'])
        again = self.adapter.persist(self.wid, self.actor, **self.args)
        self.assertEqual(again['projection_id'], saved['projection_id'])
        self.assertEqual(self.evaluate()['projection_id'], self.evaluated['projection_id'])
        self.cur.execute('SELECT m.input_count FROM pr_trend_input_manifests m JOIN pr_trend_projections p USING(scope_key,manifest_id) WHERE p.projection_id=%s', (saved['projection_id'],))
        self.assertEqual(self.cur.fetchone()[0], 5)
        self.cur.execute('SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s AND kind=\'forecast\'', (self.output_scope,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_actual_producer_rechecks_each_current_shared_grant_before_workspace_computation(self):
        pipeline = advanced_pipeline.AdvancedPipeline(self.store, values=self.values)
        job = pipeline.enqueue(self.wid, self.actor, self.trend_id, kinds=('forecast_candidate',), cursor=self.cur)['jobs'][0]
        changes = [
            ("UPDATE pr_trend_entitlements SET operations=array_remove(operations,'share_across_workspaces') WHERE workspace_id=%s AND scope_key=%s", (self.wid, self.scope)),
            ("UPDATE pr_trend_observations SET rights=jsonb_set(rights,'{share_across_workspaces,state}','\"deny\"') WHERE scope_key=%s", (self.scope,)),
            ("UPDATE pr_trend_source_policies SET rights=jsonb_set(rights,'{share_across_workspaces,state}','\"deny\"') WHERE scope_key=%s", (self.scope,)),
            ("UPDATE pr_trend_provider_contracts SET operations=array_remove(operations,'share_across_workspaces') WHERE provider_id=%s", (type(self).provider,)),
        ]
        for sql, args in changes:
            with self.subTest(sql=sql), self.db.transaction(force_rollback=True):
                self.cur.execute(sql, args)
                with self.assertRaises(TrendStorageError): pipeline.run(self.output_scope, job['job_id'], cursor=self.cur)
        self.assertEqual(pipeline.run(self.output_scope, job['job_id'], cursor=self.cur)['state'], 'succeeded')

    def test_preregistered_missing_slot_never_scores_favorable_subset(self):
        pre = self.preregister(self.candidate, self.prediction, self.p['origins'], self.p['holdout_episode_ids'], missing_slot=True)
        result = self.evaluate(pre=pre)
        self.assertEqual(result['reason'], 'missing_preregistered_candidates'); self.assertEqual(len(result['missing_slots']), 1)
        self.cur.execute("SELECT count(*) FROM pr_trend_projections WHERE scope_key=%s AND kind='forecast_evaluation'", (self.output_scope,))
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_exact_preregistered_candidate_refs_also_evaluate(self):
        payload = deepcopy(self.pre['payload'])
        payload['evaluation_plan']['candidate_selection'] = {'candidate_refs': [self.ref(self.candidate)]}
        pre = self.projection('forecast_preregistration', payload, [self.source_ref], at=self.pre['available_at'])
        result = self.evaluate(pre=pre)
        self.assertEqual(result['payload']['state'], 'evaluated')

    def test_thousand_bindings_roundtrip_real_chunks_without_truncating_or_granting_missing_sources(self):
        bindings = [{'source_id': str(uuid.uuid4()), 'scope_key': self.output_scope} for _ in range(999)]
        bindings = self.bindings + [{**b, 'node_id': b['source_id']} for b in bindings]
        candidate = self.projection('forecast_candidate', {'schema_version': 'trend.forecast.candidate.v1',
            'trend_id': self.trend_id, 'test_label': 'SYNTHETIC_INVALID_UNSUPPORTED_BINDINGS_SIZE_TEST'},
            [self.source_ref, self.node(self.candidate)],
            document={'artifact': self.prediction, 'source_bindings': bindings})
        self.cur.execute('SELECT octet_length(payload::text) FROM pr_trend_projections WHERE projection_id=%s', (candidate['projection_id'],))
        self.assertLess(self.cur.fetchone()[0], 65536)
        self.cur.execute('SELECT count(*) FROM pr_trend_manifest_chunks WHERE manifest_id=%s', (candidate['manifest_id'],))
        self.assertGreater(self.cur.fetchone()[0], 3)
        hydrated = deepcopy(candidate); self.adapter._hydrate(self.cur, hydrated, 'prediction')
        self.assertEqual(hydrated['payload']['source_bindings'], bindings)
        # Hydration is not source authority. Every supplied reference must still
        # match the actual recipe and be a current ancestor before evaluation.
        pre = self.preregister(candidate, self.prediction, self.p['origins'], self.p['holdout_episode_ids'])
        with self.assertRaisesRegex(TrendStorageError, 'source_binding'): self.evaluate(candidate, pre)

    def test_late_preregistration_rejected_from_durable_timestamp(self):
        self.cur.execute('UPDATE pr_trend_projections SET available_at=clock_timestamp() WHERE projection_id=%s', (self.pre['projection_id'],))
        with self.assertRaisesRegex(TrendStorageError, 'preregistration_binding'): self.evaluate()

    def test_current_policy_revocation_blocks_evaluation_and_admission_retry(self):
        self.prepare_review(); saved = self.adapter.persist(self.wid, self.actor, **self.args)
        revocation.revoke_policy(self.store, self.output_scope, self.provider, 'v1', cursor=self.cur)
        for action in (self.evaluate, lambda: self.adapter.persist(self.wid, self.actor, **self.args),
                       lambda: self.adapter.read(self.wid, self.actor, saved['object_id'], revision=1, cursor=self.cur)):
            with self.assertRaises(TrendStorageError): action()
        visible = self.store.get_projection(self.wid, self.actor, 'forecast', saved['object_id'], cursor=self.cur)
        self.assertIsNone(visible['payload'])

    def test_tenant_and_reviewer_current_authority_are_required(self):
        self.prepare_review()
        self.assertIsNone(self.store.get_projection(self.other_wid, self.other_actor, 'forecast_candidate', self.candidate['object_id'], cursor=self.cur))
        with self.assertRaisesRegex(TrendStorageError, 'workspace_access_denied'):
            self.adapter.admit(self.wid, self.other_actor, **self.args)
        self.cur.execute("UPDATE pr_memberships SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (self.wid, self.reviewer))
        with self.assertRaisesRegex(TrendStorageError, 'workspace_access_denied'): self.adapter.admit(self.wid, self.actor, **self.args)

    def test_method_downgrade_blocks_current_read_even_when_general_store_valid(self):
        self.prepare_review(); saved = self.adapter.persist(self.wid, self.actor, **self.args)
        method = self.methods['evaluation']
        self.cur.execute("UPDATE pr_trend_method_versions SET qualification='shadow' WHERE method_id=%s AND version=%s", (method['method_id'], method['method_version']))
        self.assertEqual(self.store.get_projection(self.wid, self.actor, 'forecast', saved['object_id'], cursor=self.cur)['validity'], 'valid')
        with self.assertRaisesRegex(TrendStorageError, 'production_method_required'):
            self.adapter.read(self.wid, self.actor, saved['object_id'], revision=1, cursor=self.cur)

    def test_missing_source_and_review_dag_edges_fail_closed(self):
        self.prepare_review()
        for manifest, node, action, error in (
            (self.evaluation_candidate['manifest_id'], self.sid, self.evaluate, 'source_dag_missing'),
            (self.review['manifest_id'], self.evaluated['projection_id'], lambda: self.adapter.admit(self.wid, self.actor, **self.args), 'review_dag_missing')):
            with self.subTest(error=error):
                with self.db.transaction(force_rollback=True):
                    self.cur.execute('DELETE FROM pr_trend_dependencies WHERE node_id=%s AND input_node_id=%s', (manifest, node))
                    with self.assertRaisesRegex(TrendStorageError, error): action()

    def test_foreign_scope_dependency_and_sealed_document_tamper_fail(self):
        foreign_node = str(uuid.uuid4())
        self.seed_store._node(self.cur, 'workspace:' + self.other_wid, foreign_node, 'projection', self.now, self.expiry)
        with self.assertRaisesRegex(self.psycopg.errors.InsufficientPrivilege, 'dependency scope denied'):
            with self.db.transaction():
                self.store.add_dependency('workspace:' + self.other_wid, foreign_node, self.output_scope, self.sid, cursor=self.cur)
        ref = self.candidate['payload']['prediction_ref']
        self.cur.execute("UPDATE pr_trend_manifest_chunks SET payload=jsonb_set(payload,'{json}',to_jsonb((payload->>'json')||' ')) WHERE manifest_id=%s AND ordinal=0", (ref['manifest_id'],))
        with self.assertRaisesRegex(TrendStorageError, 'chunk|digest|manifest'): self.evaluate()

    def test_raw_storage_rights_denied_without_revoking_aggregate_grants(self):
        self.cur.execute("UPDATE pr_trend_observations SET rights=jsonb_set(rights,'{store_raw,state}','\"deny\"') WHERE observation_id=%s", (self.sid,))
        with self.assertRaises(TrendStorageError): self.evaluate()


if __name__ == '__main__': unittest.main()
