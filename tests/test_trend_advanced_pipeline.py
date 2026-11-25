"""Independent sealed-receipt -> local advanced consumer acceptance.

Every source is synthetic. Python sockets/HTTP clients are forbidden. Real SQL
cases require an explicitly allocated disposable database; no application DSNs.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import Mock, patch
import uuid

from postriff_phase2.growth.trends import advanced_pipeline as A
from postriff_phase2.growth.trends import contracts, receipts, revocation
from postriff_phase2.growth.trends.pipeline import TrendPipeline, decode_manifest
from postriff_phase2.growth.trends.outbox import TrendOutbox
from postriff_phase2.growth.trends.store import TrendStore, TrendStorageError, row, rows
from test_trend_metrics import fixture
from test_trend_receipts import pack

NOW = '2026-09-27T20:01:00Z'
PERMISSIONS = {name: {'state': 'allow', 'policy_ref': 'synthetic-policy:v1',
                     'audience_scope': 'shared:fixture', 'expires_at': '2026-10-30T00:00:00Z'}
               for name in contracts.PERMISSIONS}


def flags(*workspaces):
    result = {'RAFII_TREND_' + name + '_ENABLED': 'true'
              for name in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS', 'GRAPH_GENOME', 'SATURATION', 'FORECASTS')}
    result['RAFII_TREND_WORKSPACE_ALLOWLIST'] = ','.join(workspaces)
    return result


def sealed_fixture():
    """Use the receipt algorithm, not a hand-invented manifest structure."""
    _, kwargs, registry, _ = pack()
    chosen = [deepcopy(kwargs['observations'][i]) for i in (0, 1, 60, 61, 150, 151)]
    for i, source in enumerate(chosen):
        source['rights'] = deepcopy(PERMISSIONS)
        source['payload'].update(is_repost=False, author_key='synthetic-creator-' + str(i),
                                 text='SYNTHETIC ONLY agent workflow\noriginal detail ' + str(i))
        source['payload_digest'] = contracts.digest(source['payload'])
    chosen[-1]['payload']['relations'] = [{'type': 'reply', 'target': chosen[-2]['source_identity']}]
    chosen[-1]['payload_digest'] = contracts.digest(chosen[-1]['payload'])
    selected = {o['observation_id'] for o in chosen}
    kwargs.update(observations=chosen, membership_events=[m for m in kwargs['membership_events'] if m['observation_id'] in selected],
                  baseline_window_specs=[])
    kwargs['source_policies'][0]['rights'] = deepcopy(PERMISSIONS)
    out = receipts.create_receipt(**kwargs)
    verified = receipts.verify_receipt(out['receipt'], out['manifest'], registry,
                                      at=NOW, current_policies=kwargs['source_policies'])
    if verified['state'] != 'verified':
        raise AssertionError('synthetic receipt must actually verify: ' + str(verified))
    return out


def thousand_source_receipt():
    """A full size receipt with unique identities; no duplicated support IDs."""
    _, kwargs, registry, _ = pack()
    seed = sealed_fixture()['manifest']
    template = seed['source_revisions'][-1]
    member = seed['membership_revisions'][-1]
    sources, members = [], []
    for i in range(1000):
        source = deepcopy(template)
        identity = 'synthetic-large-' + str(i)
        source.update(observation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)), source_identity=identity,
                      revision_identity='r1:' + identity)
        source['deletion_key'] = source['observation_id']
        source['payload'].update(native_id=identity, author_key=identity,
                                 text='SYNTHETIC opening\ndetail ' + str(i),
                                 relations=[{'type': 'reply', 'target': 'synthetic-large-' + str(i - 1)}] if i else [])
        source['payload_digest'] = contracts.digest(source['payload'])
        sources.append(source)
        members.append({**deepcopy(member), 'event_id': 'membership-' + identity,
                        'observation_id': source['observation_id'], 'input_revision_identity': source['revision_identity']})
    kwargs.update(observations=sources, membership_events=members, source_policies=seed['policy_versions'], baseline_window_specs=[])
    out = receipts.create_receipt(**kwargs)
    status = receipts.verify_receipt(out['receipt'], out['manifest'], registry, at=NOW,
                                     current_policies=kwargs['source_policies'])
    if status['state'] != 'verified':
        raise AssertionError(status)
    return out


class NoProviderIO(unittest.TestCase):
    def setUp(self):
        super().setUp()
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo',
                     'urllib.request.urlopen', 'urllib.request.OpenerDirector.open'):
            guard = patch(name, side_effect=AssertionError('provider/network I/O forbidden'))
            mock = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mock.assert_not_called)


def dedicated_test_dsn(environ=None):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from local_pg_target import selected_target
    env = os.environ if environ is None else environ
    target = selected_target(env, validate_fixture_dsns=False)
    if any(env.get(k) for k in ('PGSERVICE', 'PGHOSTADDR')):
        raise ValueError('libpq address/service overrides forbidden')
    dedicated = env.get('TREND_ADVANCED_TEST_DSN')
    raw = dedicated or env.get('POSTRIFF_TEST_DSN')
    if not raw:
        raise ValueError('explicit disposable advanced test DSN required')
    p = conninfo_to_dict(raw)
    if set(p) - {'host', 'port', 'dbname', 'user'}:
        raise ValueError('only explicit local host/port/dbname/user permitted')
    if dedicated:
        valid = (p.get('host') == '127.0.0.1' and p.get('port') == '56451'
                 and p.get('dbname', '').startswith('trend_advanced_'))
    else:
        valid = (p.get('host') == '127.0.0.1' and p.get('port') == str(target.port) and p.get('dbname') == 'postgres')
    if not valid:
        raise ValueError('allocated advanced DB or exact disposable CI runner required')
    return make_conninfo(**p, connect_timeout='5')


class AdvancedPure(NoProviderIO):
    @classmethod
    def setUpClass(cls):
        cls.sealed = sealed_fixture()

    def inputs(self, manifest=None, now=NOW, current_policies=None, current_source_rights=None):
        sealed = deepcopy(manifest or self.sealed['manifest'])
        # Independent current snapshots are explicit inputs. Tests may change
        # either current side without silently rewriting the historical seal.
        policies = deepcopy(sealed['policy_versions'] if current_policies is None else current_policies)
        grants = deepcopy({o['observation_id']: o['rights'] for o in sealed['source_revisions']}
                          if current_source_rights is None else current_source_rights)
        return A.build_inputs(sealed, now=now, current_policies=policies, current_source_rights=grants)

    def test_actual_sealed_manifest_has_six_sources_and_current_window_only_counts_two(self):
        inputs = self.inputs()
        self.assertEqual(len(inputs['common']['sources']), 6)
        result = A.build_projection('saturation', inputs, now=NOW)
        for d in result['payload']['dimensions']:
            self.assertEqual(d['eligible'], 2)
            self.assertIsNone(d['assessment'])
        hook = result['details']['dimensions']['hook']
        self.assertEqual((hook['classified_count'], hook['redundant_count']), (2, 1))
        self.assertEqual(result['details']['dimensions']['format']['redundant_count'], 0)

    def test_window_order_does_not_change_frame(self):
        manifest = deepcopy(self.sealed['manifest'])
        manifest['recipe']['window_specs'].reverse()
        self.assertEqual(self.inputs(manifest)['frame'], self.inputs()['frame'])

    def test_future_cutoff_and_array_bound_rejected_before_compute(self):
        with self.assertRaisesRegex(ValueError, 'future_cutoff'):
            self.inputs(now='2026-09-27T19:59:59Z')
        manifest = deepcopy(self.sealed['manifest'])
        manifest['source_revisions'] *= 168
        with self.assertRaisesRegex(ValueError, 'source_bound'):
            self.inputs(manifest)

    def test_unknown_expired_wrong_scope_and_denied_policy_do_not_grant_analysis(self):
        for permission in ('derive_metrics', 'retain_derivatives'):
            for change in ({'state': 'unknown'}, {'state': 'deny'}, {'expires_at': NOW}, {'audience_scope': 'shared:other'}):
                for owner in ('source', 'policy'):
                    with self.subTest(permission=permission, change=change, owner=owner):
                        m = deepcopy(self.sealed['manifest'])
                        targets = m['source_revisions'] if owner == 'source' else m['policy_versions']
                        for target in targets:
                            target['rights'][permission].update(change)
                        if owner == 'source' and 'audience_scope' in change:
                            with self.assertRaisesRegex(ValueError, 'rights_scope_mismatch'):
                                self.inputs(m)
                        else:
                            self.assertEqual(self.inputs(m)['common']['sources'], [])

    def test_creative_denial_keeps_numeric_analysis_but_no_text_patterns(self):
        m = deepcopy(self.sealed['manifest'])
        m['policy_versions'][0]['rights']['store_raw']['state'] = 'deny'
        inputs = self.inputs(m)
        self.assertEqual(len(inputs['common']['sources']), 6)
        self.assertTrue(all(v['text'] is None for v in inputs['facts'].values()))
        self.assertEqual(A.local_text_patterns(inputs)['items'], [])

    def test_repost_and_unknown_originality_never_become_copy_support(self):
        m = deepcopy(self.sealed['manifest'])
        m['source_revisions'][0]['payload']['is_repost'] = True
        m['source_revisions'][1]['payload'].pop('is_repost')
        for source in m['source_revisions'][:2]:
            source['payload_digest'] = contracts.digest(source['payload'])
        out = A.local_text_patterns(self.inputs(m))
        self.assertEqual(len(out['items']), 4)
        self.assertNotIn('SYNTHETIC ONLY', contracts.canonical(out))
        self.assertEqual(out['modalities'], {'visual': 'unknown', 'audio': 'unknown', 'ocr': 'unknown'})
        self.assertFalse(out['media_downloaded'])
        self.assertFalse(out['full_video_understanding'])

    def test_genome_missing_semantic_modalities_are_unknown(self):
        out = A.build_projection('genome', self.inputs(), now=NOW)
        for key in ('topic_narrative', 'emotional_framing', 'visual_grammar', 'audio', 'hook'):
            self.assertEqual(out['details']['dimensions'][key]['state'], 'unknown')
            self.assertIsNone(out['details']['dimensions'][key]['value'])
        self.assertFalse(out['details']['qualified'])
        self.assertEqual(out['details']['origin'], 'unknown')

    def test_current_llm_denial_on_either_side_cannot_admit_semantic_dimension(self):
        inputs = self.inputs()
        sid = inputs['common']['sources'][0]['source_id']
        semantic = {'hook': {'value': 'synthetic semantic candidate', 'evidence_refs': [sid],
                            'available_at': inputs['common']['decision_cutoff'], 'expires_at': inputs['expires_at'],
                            'derivation_kind': 'model_interpretation', 'method_version': 'synthetic',
                            'confidence_basis': 'test fixture only'}}
        # Pure builder positive control is not a durable qualification assertion.
        allowed = A.build_projection('genome', inputs, now=NOW, semantic_dimensions=semantic)
        self.assertEqual(allowed['details']['dimensions']['hook']['state'], 'supported')
        sealed = deepcopy(self.sealed['manifest'])
        for owner in ('policy', 'source'):
            with self.subTest(owner=owner):
                policies = deepcopy(sealed['policy_versions'])
                grants = {o['observation_id']: deepcopy(o['rights']) for o in sealed['source_revisions']}
                if owner == 'policy':
                    policies[0]['rights']['llm_process']['state'] = 'deny'
                else:
                    grants[sid]['llm_process']['state'] = 'deny'
                current = self.inputs(sealed, current_policies=policies, current_source_rights=grants)
                out = A.build_projection('genome', current, now=NOW, semantic_dimensions=semantic)
                self.assertEqual(out['details']['dimensions']['hook']['state'], 'unknown')
                self.assertIsNone(out['details']['dimensions']['hook']['value'])
                self.assertEqual(sealed, self.sealed['manifest'])

    def test_missing_current_permissions_never_fall_back_to_sealed_grants(self):
        self.assertEqual(self.inputs(current_policies=[])['common']['sources'], [])
        self.assertEqual(self.inputs(current_source_rights={})['common']['sources'], [])

    def test_graph_requires_declared_relation_and_display_permission(self):
        inputs = self.inputs()
        out = A.build_projection('graph', inputs, now=NOW)
        self.assertEqual(sum(e['basis']=='observed' for e in out['payload']['edges']),1)
        self.assertTrue(any(n['node_type']=='phrase' for n in out['details']['nodes']))
        for source in inputs['common']['sources']:
            source['rights']['display'] = False
        out = A.build_projection('graph', inputs, now=NOW)
        self.assertEqual(out['payload']['edges'], [])
        self.assertFalse(any(n.get('node_type') == 'creator' for n in out['details']['nodes']))

    def test_late_source_and_future_membership_cannot_expand_frozen_input(self):
        m = deepcopy(self.sealed['manifest'])
        future = deepcopy(m['source_revisions'][0])
        future.update(revision_identity='future-revision', revision_sequence=999, available_at='2026-09-28T00:00:00Z')
        future['payload']['text'] = 'FUTURE SECRET'
        m['source_revisions'].append(future)
        later = deepcopy(m['membership_revisions'][0])
        later.update(event_id='later', revision_sequence=999, episode_id='new-episode', available_at='2026-09-28T00:00:00Z')
        m['membership_revisions'].append(later)
        self.assertEqual(self.inputs(m), self.inputs())

    def test_forecast_between_hour_boundaries_rounds_target_without_moving_issuance(self):
        issued = '2026-09-27T20:17:31Z'
        out = A.build_projection('forecast_candidate', self.inputs(now=issued), now=issued,
                                 forecast_options={'seasonal_period': 3})['payload']
        self.assertEqual(contracts.iso(contracts.instant(out['issued_at'])), issued)
        self.assertEqual(contracts.iso(contracts.instant(out['target_start'])), '2026-09-27T21:00:00Z')
        self.assertEqual(next(p for p in out['predictions'] if p['method'] == 'last_value')['point'], 2)
        self.assertEqual(out['state'], 'candidate')
        self.assertFalse(out['forecast_wording_enabled'])
        self.assertEqual(out['qualification'], 'unqualified')

    def test_forecast_embargo_respects_receipt_availability(self):
        out = A.build_projection('forecast_candidate', self.inputs(), now=NOW,
                                 forecast_options={'embargo_hours': 1})['payload']
        self.assertTrue(all(p['state'] == 'unavailable' and p['point'] is None for p in out['predictions']))

    def test_forecast_candidate_keeps_sealed_result_and_explicit_cohorts(self):
        from postriff_phase2.growth.trends import forecast
        output = A.build_projection('forecast_candidate', self.inputs(), now=NOW)
        result = output['details']
        self.assertTrue(forecast._intact(result, 'prediction_digest'))
        self.assertEqual(result['execution_state'], 'offline')
        self.assertTrue(result['fixture'])
        self.assertEqual(output['payload']['execution_kind'], 'local_computation')
        self.assertNotIn('prediction_recipe', output['payload'])
        self.assertTrue(result['prediction_recipe']['history'])
        self.assertTrue(all(w['cohort'] == result['target']['cohort'] for w in result['prediction_recipe']['history']))

    def test_private_forecast_scope_is_adapted_before_seal_without_rewriting_sources(self):
        from types import SimpleNamespace
        inputs=self.inputs(); original=deepcopy(inputs)
        scope=inputs['common']['scope_key'];wid=str(uuid.uuid4())
        records=[{'observation_id':o['observation_id'],'provider_id':o['provider_id'],
            'source_policy_version':o['source_policy_version'],'rights':deepcopy(o['rights'])}
            for o in self.sealed['manifest']['source_revisions'] if o['observation_id'] in {s['source_id'] for s in inputs['common']['sources']}]
        rights=deepcopy(records[0]['rights'])
        policy={'expires_at':inputs['expires_at'],'contract_end':inputs['expires_at'],'rights':rights}
        store=SimpleNamespace(_policy=Mock(return_value=policy));worker=A.AdvancedPipeline(store)
        entitlement={'operations':['retrieve','derive_metrics','share_across_workspaces'],'expires_at':inputs['expires_at'],'revoked_at':None}
        with patch.object(A,'row',return_value=entitlement),patch.object(A,'rows',return_value=records):
            private=worker._forecast_workspace_inputs(Mock(),wid,inputs,NOW)
            output=A.build_projection('forecast_candidate',private,now=NOW)['details']
            self.assertEqual(output['scope_key'],'workspace:'+wid)
            self.assertTrue(A.forecast._intact(output,'prediction_digest'))
            self.assertTrue(all(s['scope_key']=='workspace:'+wid for s in private['common']['sources']))
            self.assertEqual(inputs,original)
            entitlement['operations']=['retrieve']
            with self.assertRaisesRegex(TrendStorageError,'forecast_source_entitlement'):
                worker._forecast_workspace_inputs(Mock(),wid,inputs,NOW)
            entitlement['operations']=['retrieve','derive_metrics','share_across_workspaces']
            records[0]['rights']['share_across_workspaces']['state']='unknown'
            with self.assertRaisesRegex(TrendStorageError,'forecast_source_sharing_denied'):
                worker._forecast_workspace_inputs(Mock(),wid,inputs,NOW)

    def test_forecast_options_reject_nan_bool_horizon_and_unbounded_values(self):
        for options in ({'bin_hours': float('nan')}, {'horizon_steps': True}, {'horizon_steps': 169},
                        {'seasonal_period': 0}, {'unexpected': 1}, {'embargo_hours': -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                A.build_projection('forecast_candidate', self.inputs(), now=NOW, forecast_options=options)

    def test_flags_off_allowlist_missing_and_individual_gates_do_not_open_db(self):
        workspace, actor, trend = [str(uuid.uuid4()) for _ in range(3)]
        for values in ({}, flags(), {**flags(workspace), 'RAFII_TREND_RADAR_ENABLED': 'false'},
                       {**flags(workspace), 'RAFII_TREND_TRUST_RECEIPTS_ENABLED': 'false'},
                       {**flags(workspace), 'RAFII_TREND_GRAPH_GENOME_ENABLED': 'false'}):
            store = Mock()
            store.transaction.side_effect = AssertionError('disabled path opened database')
            pipeline = A.AdvancedPipeline(store, values=values, clock=lambda: NOW)
            self.assertEqual(pipeline.enqueue(workspace, actor, trend, kinds=['graph']), {'state': 'disabled', 'jobs': []})
            store.transaction.assert_not_called()
        pipeline = A.AdvancedPipeline(Mock(), values={}, clock=lambda: NOW)
        self.assertEqual(pipeline.tick()['state'], 'disabled')
        self.assertEqual(pipeline.plan_current()['state'], 'disabled')
        pipeline.store.transaction.assert_not_called()

    def test_kind_and_tick_bounds_fail_before_database(self):
        pipeline = A.AdvancedPipeline(Mock(), values=flags(), clock=lambda: NOW)
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for kinds in ([], ['bogus'], ['graph'] * 6, 'graph'):
            with self.subTest(kinds=kinds), self.assertRaises(ValueError):
                pipeline.enqueue(*ids, kinds=kinds)
        for limit in (0, 6, True, float('nan')):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                pipeline.tick(limit=limit)
        pipeline.store.transaction.assert_not_called()

    def test_unqualified_model_judgment_never_supplies_semantics(self):
        store = Mock()
        store.get_projection.return_value = {'validity': 'valid', 'payload': {
            'task': 'genome', 'model_id': 'synthetic', 'cohort': 'en', 'input_digest': 'a' * 64,
            'result': {'dimensions': {'hook': {'derivation_kind': 'model_interpretation', 'value': 'UNQUALIFIED'}}}}}
        p = A.AdvancedPipeline(store, values={'RAFII_TREND_MODEL_ENRICHMENT_ENABLED': 'true'})
        control = {'workspace_id': str(uuid.uuid4()), 'actor_id': str(uuid.uuid4()),
                   'judgment_id': str(uuid.uuid4()), 'input_manifest_digest': 'a' * 64}
        cur = Mock(); cur.fetchone.return_value = ({'workspace':{'id':control['workspace_id']}},)
        with patch('postriff_phase2.growth.trends.semantic_admission.current_annotations', return_value=None):
            self.assertEqual(p._annotations(cur, control['workspace_id'], control['actor_id'], str(uuid.uuid4()), self.inputs()), ([], [], []))
        store.lock_dependencies.assert_not_called()

    def test_dsn_guard_rejects_application_remote_and_libpq_overrides(self):
        local = 'host=127.0.0.1 port=56451 dbname=trend_advanced_test user=ouxianxing'
        self.assertIn('trend_advanced_test', dedicated_test_dsn({'TREND_ADVANCED_TEST_DSN': local}))
        self.assertIn('55438', dedicated_test_dsn({'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55438 dbname=postgres'}))
        for env in ({'POSTRIFF_DATABASE_URL': local}, {'TREND_ADVANCED_TEST_DSN': local.replace('56451', '55438')},
                    {'TREND_ADVANCED_TEST_DSN': local.replace('trend_advanced_test', 'trend_base')},
                    {'TREND_ADVANCED_TEST_DSN': local.replace('127.0.0.1', 'db.example.com')},
                    {'TREND_ADVANCED_TEST_DSN': local + ' hostaddr=198.51.100.1'},
                    {'TREND_ADVANCED_TEST_DSN': local, 'PGSERVICE': 'app'},
                    {'TREND_ADVANCED_TEST_DSN': local, 'PGHOSTADDR': '198.51.100.1'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                dedicated_test_dsn(env)

    def test_thousand_source_receipt_keeps_full_support_and_bounds_public_payloads(self):
        sealed = thousand_source_receipt()
        inputs = self.inputs(sealed['manifest'])
        self.assertEqual(len(inputs['common']['sources']), 1000)
        for kind in ('genome', 'graph', 'creative_pattern'):
            with self.subTest(kind=kind):
                out = A.build_projection(kind, inputs, now=NOW)
                # Leave headroom for SQL jsonb formatting and durable metadata.
                self.assertLess(len(contracts.canonical(out['payload']).encode()), 48_000)
                if kind == 'genome':
                    full = out['details']['dimensions']['language_cultural_usage']['evidence_refs']
                    self.assertEqual(len(full), 1000)
                    self.assertTrue(all(len(d['evidence_refs']) <= 100 for d in out['payload']['dimensions']))
                elif kind == 'graph':
                    self.assertLessEqual(len(out['payload']['nodes']), 40)
                    self.assertLessEqual(len(out['payload']['edges']), 80)
                    ids = {n['id'] for n in out['payload']['nodes']}
                    self.assertTrue(all(e['from'] in ids and e['to'] in ids for e in out['payload']['edges']))
                    self.assertTrue(out['payload']['truncated'])
                else:
                    self.assertEqual(len(out['details']['items']), 1000)
                    self.assertEqual(len(out['payload']['items']), 20)
                    self.assertEqual(out['payload']['total_items'], 1000)
                    self.assertTrue(out['payload']['truncated'])


@unittest.skipUnless(os.environ.get('TREND_ADVANCED_TEST_DSN') or os.environ.get('POSTRIFF_TEST_DSN'),
                     'explicit disposable PostgreSQL DSN required')
class AdvancedPostgres(NoProviderIO):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg, cls.dsn = psycopg, dedicated_test_dsn()
        # SQL uses clock_timestamp for current-rights checks. Freeze one UTC
        # instant for this fixture, then shift the actual receipt corpus to it.
        cls.NOW = contracts.iso(datetime.now(timezone.utc) - timedelta(seconds=2))
        now = contracts.instant(cls.NOW)
        cls.end = contracts.iso(now + timedelta(days=2))
        cls.start = contracts.iso(now - timedelta(days=35))
        cls.cutoff = contracts.iso(now.replace(minute=0, second=0, microsecond=0))
        cls.scope = 'shared:advanced-' + uuid.uuid4().hex[:12]
        cls.provider = 'advanced-synthetic-' + uuid.uuid4().hex[:12]
        with psycopg.connect(cls.dsn) as db:
            if not db.execute("SELECT to_regclass('public.pr_trend_jobs')").fetchone()[0]:
                raise RuntimeError('Use portable postgres_trend_advanced wrapper to apply040 on the disposable DB')
            for table in ('pr_profiles', 'pr_workspaces', 'pr_memberships'):
                db.execute('DROP POLICY IF EXISTS trend_advanced_synthetic_test ON ' + table)
                db.execute('CREATE POLICY trend_advanced_synthetic_test ON ' + table + ' FOR ALL TO service_role USING(true) WITH CHECK(true)')

        def connect():
            db = psycopg.connect(cls.dsn)
            db.execute('SET ROLE service_role')
            return db
        cls.store = TrendStore(connect, offline_replay=True)
        cls.store.ensure_scope(cls.scope)
        cls.PERMISSIONS = {name: {**grant, 'audience_scope': cls.scope, 'expires_at': cls.end}
                           for name, grant in PERMISSIONS.items()}
        cls.policy = {'id': 'advanced-synthetic-policy', 'version': 'policy-v1', 'provider_id': cls.provider,
                      'operation': 'read', 'scope_key': cls.scope, 'rights': cls.PERMISSIONS,
                      'reviewed_by': 'synthetic-test', 'review_ref': 'synthetic-only', 'effective_at': cls.start,
                      'expires_at': cls.end, 'retention_seconds': 40 * 86400, 'readiness': 'ready', 'revoked_at': None}
        cls.store.register_contract(cls.provider, 'fixture-v1', list(contracts.PERMISSIONS), cls.start, cls.end, {})
        cls.store.register_policy(cls.policy, provider_contract_version='fixture-v1')
        originals = sealed_fixture()['manifest']['source_revisions']
        delta = contracts.instant(cls.cutoff) - contracts.instant('2026-09-27T20:00:00Z')
        cls.sources = []
        for original in originals:
            source = deepcopy(original)
            source.update(scope_key=cls.scope, provider_id=cls.provider, rights=deepcopy(cls.PERMISSIONS),
                          retention_until=cls.end, observation_id=str(uuid.uuid4()))
            source['deletion_key'] = source['observation_id']
            for key in ('event_at', 'received_at', 'available_at'):
                source[key] = contracts.iso(contracts.instant(source[key]) + delta)
            cls.sources.append(source)
        with cls.store.transaction() as cur:
            for source in cls.sources:
                cls.store.put_observation(source, cursor=cur)
        outbox = TrendOutbox(cls.store)
        outbox.enqueue(cls.scope, 'advanced-seal-' + uuid.uuid4().hex, 'trend.ingested', {
            'provider_id': cls.provider, 'decision_cutoff': cls.cutoff,
            'observation_ids': [o['observation_id'] for o in cls.sources], 'coverage_epoch': 'epoch-v1',
            'completeness': 'complete_within_scope', 'markers': [],
            'coverage_interval': {'start': contracts.iso(contracts.instant(cls.cutoff) - timedelta(hours=3)), 'end': cls.cutoff}})
        pipeline = TrendPipeline(cls.store, clock=lambda: cls.NOW)
        # The isolated DB can retain earlier acceptance receipts. Use the real
        # consumer until this fixture's ingestion event, including its normal
        # no-op handling for unrelated content-free operational events.
        for _ in range(100):
            claim = outbox.claim('advanced-seal-test', 'synthetic', lease_seconds=300)
            if not claim:
                raise AssertionError('fixture ingestion event was not claimable')
            outbox.consume(claim, pipeline.consume)
            if claim['scope_key'] == cls.scope and claim['event_type'] == 'trend.ingested':
                break
        else:
            raise AssertionError('fixture ingestion exceeded bounded outbox drain')
        with cls.store.transaction() as cur:
            cur.execute('SELECT receipt_id::text, payload, verification_state FROM pr_trend_trust_receipts WHERE scope_key=%s', (cls.scope,))
            saved = rows(cur)
        if len(saved) != 1 or saved[0]['verification_state'] != 'verified':
            raise AssertionError('real ingestion must produce exactly one verified sealed receipt: ' + str(saved))
        cls.receipt_id = saved[0]['receipt_id']
        cls.trend_id = saved[0]['payload']['trend_id']

    def setUp(self):
        super().setUp()
        self.actor, self.workspace = self.tenant()
        self.output_scope = 'workspace:' + self.workspace
        self.values = flags(self.workspace)
        self.pipeline = A.AdvancedPipeline(self.store, values=self.values, clock=lambda: self.NOW)
        self.addCleanup(self.cancel_queued)

    def tenant(self, entitled=True):
        actor, workspace = str(uuid.uuid4()), str(uuid.uuid4())
        with self.psycopg.connect(self.dsn) as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (actor,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)', (actor,))
            db.execute('INSERT INTO pr_workspaces(id) VALUES(%s)', (workspace,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'owner','active')", (workspace, actor))
        if entitled:
            self.store.grant_entitlement(workspace, self.scope, ['retrieve', 'derive_metrics', 'share_across_workspaces'], self.end)
        return actor, workspace

    def cancel_queued(self):
        self.cancel_scope(self.output_scope)

    def cancel_scope(self, scope):
        with self.store.transaction() as cur:
            cur.execute("UPDATE pr_trend_jobs SET state='cancelled',cancellation_requested=true WHERE scope_key=%s AND state IN ('queued','retry_wait')", (scope,))

    @contextmanager
    def rollback(self):
        db = self.store.connection_factory()
        try:
            with db.cursor() as cur:
                yield cur
        finally:
            db.rollback()
            db.close()

    def enqueue(self, *kinds, cursor=None):
        return self.pipeline.enqueue(self.workspace, self.actor, self.trend_id,
                                     kinds=kinds or ('genome', 'graph', 'saturation', 'creative_pattern'), cursor=cursor)

    def execute(self, kind='graph', cursor=None):
        job = self.enqueue(kind, cursor=cursor)['jobs'][0]
        result = self.pipeline.run(self.output_scope, job['job_id'], cursor=cursor)
        self.assertEqual(result['state'], 'succeeded')
        return job, result

    def projection(self, kind='graph', cursor=None):
        return self.store.get_projection(self.workspace, self.actor, kind, self.trend_id, cursor=cursor)

    def test_sealed_receipt_enqueue_run_auth_projection_and_exact_dependency(self):
        jobs = self.enqueue()['jobs']
        self.assertEqual({j['kind'] for j in jobs}, {'genome', 'graph', 'saturation', 'creative_pattern'})
        for job in jobs:
            self.assertEqual(str(uuid.UUID(job['job_id'])), job['job_id'])
            result = self.pipeline.run(self.output_scope, job['job_id'])
            self.assertEqual(result['state'], 'succeeded')
            projection = self.projection(job['kind'])
            self.assertEqual(projection['scope_key'], self.output_scope)
            self.assertEqual(projection['validity'], 'valid')
            self.assertEqual(projection['payload']['trust_receipt_id'], self.receipt_id)
            self.assertIsNone(projection['receipt_id'])  # cross-scope dependency, not a same-scope FK
            with self.store.transaction() as cur:
                cur.execute('''SELECT parent.kind,parent.object_id::text,parent.revision
                    FROM pr_trend_projections output JOIN pr_trend_input_manifests m
                      ON(m.scope_key,m.manifest_id)=(output.scope_key,output.manifest_id)
                    JOIN pr_trend_dependencies d ON(d.scope_key,d.node_id)=(m.scope_key,m.manifest_id)
                    JOIN pr_trend_projections parent ON(parent.scope_key,parent.projection_id)=(d.input_scope_key,d.input_node_id)
                    WHERE output.scope_key=%s AND output.projection_id=%s''', (self.output_scope, projection['projection_id']))
                parents = rows(cur)
                self.assertIn(('receipt', self.receipt_id), [(r['kind'], r['object_id']) for r in parents])
                cur.execute('SELECT payload FROM pr_trend_jobs WHERE job_id=%s AND scope_key=%s', (job['job_id'], self.output_scope))
                self.assertNotIn('SYNTHETIC ONLY', contracts.canonical(row(cur)['payload']))
        graph = self.projection()['payload']
        edges = graph['edges']
        self.assertEqual(len(edges), 7)
        replies = [e for e in edges if e['relation'] == 'reply']
        associations = [e for e in edges if e['relation'] == 'co_occurrence']
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]['basis'], 'observed')
        self.assertEqual(len(associations), 6)
        node_ids = {n['id'] for n in graph['nodes']}
        source_ids = {s['observation_id'] for s in self.sources}
        for edge in edges:
            self.assertIn(edge['from'], node_ids)
            self.assertIn(edge['to'], node_ids)
            self.assertTrue(edge['evidence_refs'])
            self.assertLessEqual(set(edge['evidence_refs']), source_ids)
            self.assertIn('no origin, influence or causal assertion', edge['limitation'])
        for edge in associations:
            self.assertEqual(edge['basis'], 'hypothesized')

    def test_enqueue_and_completed_run_are_idempotent(self):
        job, _ = self.execute()
        again = self.enqueue('graph')['jobs'][0]
        self.assertEqual(again['job_id'], job['job_id'])
        self.assertTrue(self.pipeline.run(self.output_scope, job['job_id'])['replayed'])
        self.assertEqual(self.projection()['revision'], 1)

    def test_genome_retains_actual_bounded_context_and_original_seed_details(self):
        import json
        self.execute('genome')
        saved = self.projection('genome')
        self.assertTrue(saved['payload']['narrative_variants'])
        with self.store.transaction() as cur:
            cur.execute('SELECT manifest_id::text FROM pr_trend_projections WHERE scope_key=%s AND projection_id=%s',
                        (self.output_scope, saved['projection_id']))
            manifest = self.store.get_manifest(self.output_scope, cur.fetchone()[0], cursor=cur)
        details = json.loads(''.join(c['payload']['json'] for c in manifest['chunks']))
        self.assertEqual(contracts.digest({k: v for k, v in details.items() if k != 'manifest_digest'}), manifest['document_digest'])
        reconstructed = details['details']['context_and_seeds']
        self.assertEqual(reconstructed['observed_original_count'], 6)
        self.assertTrue(any(len(b['member_ids']) == 2 for b in reconstructed['bundles']))
        self.assertTrue(all(s['stance'] == 'unknown' and s['provisional'] for s in reconstructed['seeds']))
        self.assertFalse(reconstructed['qualified'])

    def test_whitespace_candidate_job_is_private_gated_and_does_not_invent_opportunity(self):
        self.assertEqual(self.enqueue('whitespace_candidate')['state'], 'disabled')
        self.values['RAFII_TREND_WHITESPACE_ENABLED'] = 'true'
        self.execute('whitespace_candidate')
        saved = self.projection('whitespace_candidate')
        self.assertEqual(saved['scope_key'], self.output_scope)
        self.assertEqual(saved['payload']['opportunities'], [])
        self.assertEqual(saved['payload']['semantic_qualification'], 'unqualified')
        self.assertEqual(saved['payload']['trust_receipt_id'], self.receipt_id)
        with self.rollback() as cur:
            revocation.revoke_source(self.store, self.scope, self.provider, self.sources[0]['source_identity'], cursor=cur)
            self.assertIsNone(self.projection('whitespace_candidate', cursor=cur)['payload'])

    def test_atomic_failure_after_projection_rolls_back_job_and_result(self):
        job = self.enqueue('genome')['jobs'][0]
        with patch.object(self.pipeline.jobs, 'finish_local', side_effect=RuntimeError('synthetic commit boundary crash')):
            with self.assertRaisesRegex(RuntimeError, 'commit boundary'):
                self.pipeline.run(self.output_scope, job['job_id'])
        self.assertIsNone(self.projection('genome'))
        with self.store.transaction() as cur:
            cur.execute('SELECT state,attempts FROM pr_trend_jobs WHERE scope_key=%s AND job_id=%s', (self.output_scope, job['job_id']))
            saved = row(cur)
        self.assertEqual(saved['state'], 'queued')
        self.assertEqual(saved['attempts'], 0)
        self.assertEqual(self.pipeline.run(self.output_scope, job['job_id'])['state'], 'succeeded')

    def test_tick_executes_typed_jobs_and_preserves_future_due_job(self):
        job = self.enqueue('graph')['jobs'][0]
        with self.store.transaction() as cur:
            cur.execute("UPDATE pr_trend_jobs SET due_at=clock_timestamp()+interval '1 day' WHERE scope_key=%s AND job_id=%s", (self.output_scope, job['job_id']))
        self.assertEqual(self.pipeline.tick(limit=5)['results'], [])
        with self.store.transaction() as cur:
            cur.execute('UPDATE pr_trend_jobs SET due_at=clock_timestamp() WHERE scope_key=%s AND job_id=%s', (self.output_scope, job['job_id']))
        results = self.pipeline.tick(limit=5)['results']
        self.assertEqual([(r['job_id'], r['state']) for r in results], [(job['job_id'], 'succeeded')])

    def test_flag_off_after_enqueue_prevents_claim_and_output(self):
        job = self.enqueue('graph')['jobs'][0]
        self.values['RAFII_TREND_GRAPH_GENOME_ENABLED'] = 'false'
        self.assertEqual(self.pipeline.run(self.output_scope, job['job_id'])['state'], 'disabled')
        self.assertIsNone(self.projection())

    def test_two_entitled_tenants_get_independent_outputs_and_foreign_actor_is_denied(self):
        actor2, workspace2 = self.tenant()
        self.execute()
        self.assertIsNone(self.store.get_projection(workspace2, actor2, 'graph', self.trend_id))
        p2 = A.AdvancedPipeline(self.store, values=flags(workspace2), clock=lambda: self.NOW)
        job2 = p2.enqueue(workspace2, actor2, self.trend_id, kinds=['graph'])['jobs'][0]
        self.assertEqual(p2.run('workspace:' + workspace2, job2['job_id'])['state'], 'succeeded')
        two = self.store.get_projection(workspace2, actor2, 'graph', self.trend_id)
        self.assertNotEqual(two['projection_id'], self.projection()['projection_id'])
        with self.assertRaises(ValueError):
            self.store.get_projection(self.workspace, actor2, 'graph', self.trend_id)
        with self.assertRaises(ValueError):
            p2.run(self.output_scope, job2['job_id'])

    def test_unentitled_tenant_cannot_enqueue_public_source(self):
        actor, workspace = self.tenant(entitled=False)
        p = A.AdvancedPipeline(self.store, values=flags(workspace), clock=lambda: self.NOW)
        with self.assertRaises(ValueError):
            p.enqueue(workspace, actor, self.trend_id)

    def test_membership_revocation_after_enqueue_blocks_compute(self):
        job = self.enqueue('graph')['jobs'][0]
        with self.rollback() as cur:
            cur.execute('DELETE FROM pr_memberships WHERE workspace_id=%s AND user_id=%s', (self.workspace, self.actor))
            with self.assertRaises(ValueError):
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)

    def test_source_delete_immediately_invalidates_existing_workspace_output(self):
        self.execute()
        with self.rollback() as cur:
            revocation.revoke_source(self.store, self.scope, self.provider, self.sources[0]['source_identity'], cursor=cur)
            result = self.projection(cursor=cur)
            self.assertEqual(result['verification_state'], 'inputs_deleted')
            self.assertIsNone(result['payload'])

    def test_policy_revoke_after_enqueue_blocks_run_and_existing_output(self):
        self.execute('genome')
        job = self.enqueue('graph')['jobs'][0]
        with self.rollback() as cur:
            revocation.revoke_policy(self.store, self.scope, self.provider, 'policy-v1', cursor=cur)
            with self.assertRaises(ValueError):
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)
            self.assertIsNone(self.projection('genome', cursor=cur)['payload'])

    def test_entitlement_revoke_hides_previously_derived_workspace_graph(self):
        self.execute()
        with self.rollback() as cur:
            revocation.revoke_entitlement(self.store, self.workspace, self.scope, cursor=cur)
            result = self.projection(cursor=cur)
            self.assertTrue(result is None or result['payload'] is None,
                            'workspace output must recheck shared-source entitlement, not only its root workspace')

    def test_current_unknown_derivative_right_blocks_frozen_manifest_compute(self):
        from psycopg.types.json import Jsonb
        job = self.enqueue('graph')['jobs'][0]
        with self.rollback() as cur:
            rights = deepcopy(self.PERMISSIONS)
            rights['retain_derivatives']['state'] = 'unknown'
            cur.execute('UPDATE pr_trend_source_policies SET rights=%s WHERE scope_key=%s AND provider_id=%s',
                        (Jsonb(rights), self.scope, self.provider))
            with self.assertRaises(ValueError):
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)

    def test_current_display_denial_does_not_publish_creator_graph(self):
        from psycopg.types.json import Jsonb
        job = self.enqueue('graph')['jobs'][0]
        with self.rollback() as cur:
            rights = deepcopy(self.PERMISSIONS)
            rights['display_excerpt']['state'] = 'deny'
            cur.execute('UPDATE pr_trend_source_policies SET rights=%s WHERE scope_key=%s AND provider_id=%s',
                        (Jsonb(rights), self.scope, self.provider))
            try:
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)
            except ValueError:
                return  # fail-closed admission is also safe
            projected = self.projection(cursor=cur)
            text = contracts.canonical(projected['payload']) if projected and projected['payload'] else ''
            self.assertNotIn('synthetic-creator-', text)

    def test_current_raw_right_revocation_cannot_reuse_sealed_text_for_new_patterns(self):
        from psycopg.types.json import Jsonb
        job = self.enqueue('creative_pattern')['jobs'][0]
        with self.rollback() as cur:
            rights = deepcopy(self.PERMISSIONS)
            rights['store_raw']['state'] = 'unknown'
            cur.execute('UPDATE pr_trend_source_policies SET rights=%s WHERE scope_key=%s AND provider_id=%s',
                        (Jsonb(rights), self.scope, self.provider))
            try:
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)
            except ValueError:
                return
            output = self.projection('creative_pattern', cursor=cur)
            payload = output['payload'] if output and output['payload'] else {}
            self.assertEqual(payload.get('items', []), [],
                             'current store_raw permission must constrain new text derivation just like sealed grants')

    def test_current_observation_raw_right_revocation_cannot_reuse_sealed_text(self):
        from psycopg.types.json import Jsonb
        job = self.enqueue('creative_pattern')['jobs'][0]
        with self.rollback() as cur:
            rights = deepcopy(self.PERMISSIONS)
            rights['store_raw']['state'] = 'deny'
            cur.execute('UPDATE pr_trend_observations SET rights=%s WHERE scope_key=%s AND provider_id=%s',
                        (Jsonb(rights), self.scope, self.provider))
            try:
                self.pipeline.run(self.output_scope, job['job_id'], cursor=cur)
            except ValueError:
                return
            output = self.projection('creative_pattern', cursor=cur)
            payload = output['payload'] if output and output['payload'] else {}
            self.assertEqual(payload.get('items', []), [],
                             'current observation grant also constrains reuse independently of policy and seal')

    def test_sealed_manifest_or_executable_drift_cannot_silently_run_new_method(self):
        job = self.enqueue('graph')['jobs'][0]
        method = A._method('graph')
        with patch.object(A, '_method', return_value={**method, 'artifact_digest': 'f' * 64}):
            with self.assertRaisesRegex(ValueError, 'frozen_input_changed'):
                self.pipeline.run(self.output_scope, job['job_id'])
        self.assertIsNone(self.projection())

    def test_enqueuing_receipts_uses_only_verified_records(self):
        with self.rollback() as cur:
            result = self.pipeline.enqueue_from_receipts(cur, self.workspace, self.actor, [
                {'trend_id': self.trend_id, 'verification_state': 'pending'},
                {'trend_id': self.trend_id, 'verification_state': 'verified'}], kinds=['graph'])
            self.assertEqual(len(result), 1)
            self.assertEqual(len(result[0]['jobs']), 1)

    def test_tick_cancels_changed_method_job_without_projection(self):
        job = self.enqueue('graph')['jobs'][0]
        method = A._method('graph')
        with patch.object(A, '_method', return_value={**method, 'artifact_digest': 'f' * 64}):
            result = self.pipeline.tick(limit=5)
        self.assertEqual([(r['job_id'], r['state']) for r in result['results']], [(job['job_id'], 'cancelled')])
        self.assertIsNone(self.projection())
        with self.store.transaction() as cur:
            cur.execute('SELECT state,payload FROM pr_trend_jobs WHERE scope_key=%s AND job_id=%s', (self.output_scope, job['job_id']))
            saved = row(cur)
        self.assertEqual(saved['state'], 'cancelled')
        self.assertEqual(saved['payload'], {})

    def test_real_producer_rotates_workspaces_and_deduplicates_stored_receipts(self):
        with self.store.transaction() as cur:
            cur.execute("SELECT to_regclass('public.pr_runtime')")
            self.assertIsNone(cur.fetchone()[0], 'producer acceptance must use baseline+040 without omitted003')
        _, workspace2 = self.tenant()
        self.addCleanup(self.cancel_scope, 'workspace:' + workspace2)
        clock = [self.NOW]
        p = A.AdvancedPipeline(self.store, values=flags(self.workspace, workspace2), clock=lambda: clock[0])
        scopes = [self.output_scope, 'workspace:' + workspace2]
        def planned_workspaces():
            with self.store.transaction() as cur:
                cur.execute('SELECT DISTINCT scope_key FROM pr_trend_jobs WHERE scope_key=ANY(%s)', (scopes,))
                return {r[0] for r in cur.fetchall()}
        first = p.plan_current(max_workspaces=1, trend_limit=1)
        self.assertEqual(first['workspaces'], 1)
        self.assertGreaterEqual(first['planned'], 4)
        seen = planned_workspaces()
        self.assertEqual(len(seen), 1)
        clock[0] = contracts.iso(contracts.instant(clock[0]) + timedelta(seconds=1))
        second = p.plan_current(max_workspaces=1, trend_limit=1)
        self.assertEqual(second['workspaces'], 1)
        self.assertEqual(planned_workspaces(), set(scopes))
        with self.store.transaction() as cur:
            cur.execute('SELECT count(*) FROM pr_trend_jobs WHERE scope_key=ANY(%s)', (scopes,))
            count = cur.fetchone()[0]
        clock[0] = contracts.iso(contracts.instant(clock[0]) + timedelta(seconds=1))
        p.plan_current(max_workspaces=1, trend_limit=1)
        with self.store.transaction() as cur:
            cur.execute('SELECT count(*) FROM pr_trend_jobs WHERE scope_key=ANY(%s)', (scopes,))
            self.assertEqual(cur.fetchone()[0], count)
            cur.execute("SELECT cursor_value,generation FROM pr_trend_provider_cursors WHERE scope_key=ANY(%s) AND provider_id='rafii.local.advanced' AND partition_key='workspace-scan-v1'", (scopes,))
            saved = cur.fetchall()
            self.assertTrue(all(r[1] >= 1 for r in saved))
            checkpoints = [r[0] for r in saved]
        self.assertEqual(len(checkpoints), 2)
        self.assertTrue(all(c and c['after_object_id'] is None for c in checkpoints))
        result = p.tick(limit=5)
        self.assertTrue(any(r['state'] == 'succeeded' for r in result['results']))

    def test_producer_cursor_and_created_jobs_roll_back_together(self):
        enqueue = self.pipeline.jobs.enqueue

        def crash(*args, **kwargs):
            enqueue(*args, **kwargs)
            raise RuntimeError('synthetic producer crash after job insertion')

        with patch.object(self.pipeline.jobs, 'enqueue', side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, 'producer crash'):
                self.pipeline.plan_current(max_workspaces=1, trend_limit=1)
        with self.store.transaction() as cur:
            cur.execute('SELECT count(*) FROM pr_trend_jobs WHERE scope_key=%s', (self.output_scope,))
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute("SELECT count(*) FROM pr_trend_provider_cursors WHERE scope_key=%s AND provider_id='rafii.local.advanced' AND partition_key='workspace-scan-v1'", (self.output_scope,))
            self.assertEqual(cur.fetchone()[0], 0)
        result = self.pipeline.plan_current(max_workspaces=1, trend_limit=1)
        self.assertEqual(result['workspaces'], 1)
        self.assertGreaterEqual(result['planned'], 4)
