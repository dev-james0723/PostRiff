"""Synthetic stored-interpretation adversaries. No provider/model/DB by default."""
from copy import deepcopy
from dataclasses import fields
from types import SimpleNamespace
import os
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from postriff_phase2.growth.jev import JevService, DEFAULT_MODEL
from postriff_phase2.growth.router import AIModelRouter
from postriff_phase2.growth.usage import MemoryUsageSink
from postriff_phase2.growth.trends import interpretation_context as I
from postriff_phase2.growth.trends import advanced_pipeline, contracts, enrichment, evidence_pack, judge, judgment_cache, relevance
from postriff_phase2.growth.trends.policy import SourcePolicy
from test_trend_advanced_pipeline import sealed_fixture
from test_trend_enrichment import model_policy

NOW = '2026-09-27T20:01:00Z'
BEFORE = '2026-09-27T20:00:00Z'
AFTER = '2026-10-01T00:00:00Z'
WID = '11111111-1111-4111-8111-111111111111'
ACTOR = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
PRIVATE = 'workspace:' + WID
PERMISSIONS = {name: {'state': 'allow', 'policy_ref': 'synthetic-review',
    'audience_scope': 'shared:fixture', 'expires_at': AFTER} for name in contracts.PERMISSIONS}


def uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'interpretation-test:' + label))


class Cursor:
    """Small SQL response fixture. Unknown SQL fails rather than silently passes."""
    def __init__(self, case):
        self.case = case; self.result = []; self.description = []; self.queries = []
        self.ancestry_ok = True

    def execute(self, sql, args=()):
        self.queries.append((sql, args)); self.result = []; self.description = []
        if 'trend-trust-mutation' in sql:
            return
        if 'interpretation:workspace' in sql:
            self.result = [(deepcopy(self.case.state),)]
        elif 'interpretation:ancestry' in sql:
            self.result = [(len(args[3]) if self.ancestry_ok else 0,)]
        elif 'interpretation:method' in sql:
            self.result = [self.case.methods.get(tuple(args))] if tuple(args) in self.case.methods else []
        elif 'interpretation:sources' in sql:
            self.result = [deepcopy(o) for o in self.case.originals if (o['scope_key'], o['observation_id']) in set(zip(*args))]
            self.description = [SimpleNamespace(name=k) for k in self.result[0]] if self.result else []
        elif 'interpretation:entitlement' in sql:
            self.result = [self.case.entitlement]
        elif 'interpretation:policy_refs' in sql:
            self.result = sorted({(o['scope_key'], o['provider_id'], o['source_policy_version'])
                for o in self.case.originals if o['scope_key'] == args[0] and o['observation_id'] in args[1]})
        else:
            raise AssertionError('Unexpected SQL: ' + sql)

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result


class InterpretationContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sealed = sealed_fixture()

    def setUp(self):
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo',
                     'urllib.request.urlopen', 'urllib.request.OpenerDirector.open'):
            guard = patch(name, side_effect=AssertionError('no network permitted'))
            stub = guard.start(); self.addCleanup(guard.stop); self.addCleanup(stub.assert_not_called)
        manifest = deepcopy(self.sealed['manifest'])
        self.inputs = advanced_pipeline.build_inputs(manifest, now=NOW,
            current_policies=deepcopy(manifest['policy_versions']),
            current_source_rights={o['observation_id']: deepcopy(o['rights']) for o in manifest['source_revisions']})
        self.state = {'brandHub': {'subject': 'synthetic'}, 'phase2': {'channels': []}}
        self.originals = deepcopy(manifest['source_revisions']); self.scope = manifest['scope_key']
        self.methods = {}; self.records = {}; self.cur = Cursor(self)
        self.entitlement = (['retrieve', 'derive_metrics', 'share_across_workspaces'], AFTER, None)
        self.store = Mock(); self.store.connection_factory = Mock(side_effect=AssertionError('new DB connection forbidden'))
        self.store.authorized_scopes.return_value = [self.scope, PRIVATE]
        self.store.get_projection.side_effect = lambda _w, _a, k, oid, **kw: deepcopy(self.records.get((k, oid)))
        self.model_config = model_policy(); self.model_config['tasks'] = ['spread_mechanism', 'platform_fit']
        self.policy_record = {'rights': deepcopy(PERMISSIONS),
            'operations': list(PERMISSIONS), 'contract_operations': list(PERMISSIONS),
            'expires_at': AFTER, 'contract_end': AFTER,
            'manifest': {'reviewed_by': ACTOR, 'review_ref': 'synthetic', 'model_enrichment': self.model_config}}
        self.store._policy.side_effect = lambda *args, **kw: deepcopy(self.policy_record)
        self.store.scope_signature.return_value = 'synthetic-scope-signature'
        self.receipt = self.record('receipt', uid('receipt'), {'input_manifest_digest': manifest['manifest_digest']}, scope=self.scope)
        self.receipt['verification_state'] = 'verified'
        self.store.get_receipt.return_value = deepcopy(self.receipt)
        self.trend = self.record('trend', uid('trend'), {}, scope=self.scope)
        self.cohort = {'platform': self.inputs['frame']['platform'], 'language': self.inputs['frame']['language'],
            'format': 'text', 'niche': 'explicit-test-niche', 'period': 'explicit-period'}
        self.state['coworker'] = {'trendPlatformCohort': deepcopy(self.cohort)}
        self.values = {'RAFII_TREND_' + n + '_ENABLED': 'true' for n in enrichment.REQUIRED_FLAGS}
        self.values['RAFII_TREND_WORKSPACE_ALLOWLIST'] = WID
        self.loaded = {}
        names = {f.name for f in fields(SourcePolicy)}
        policy = SourcePolicy(**{k: v for k, v in manifest['policy_versions'][0].items() if k in names})
        pack = evidence_pack.build(manifest['source_revisions'], scope_key=self.scope,
            cutoff=manifest['recipe']['decision_cutoff'], at=NOW,
            receipt={'scope_key': self.scope, 'verification_state': 'verified', 'digest': 'receipt-fixture'},
            policies={policy.version: policy})
        pack.pop('input_digest'); pack.update(scope_key=PRIVATE, evidence_scope=self.scope,
            receipt_id=self.receipt['object_id'], input_manifest_digest=manifest['manifest_digest'])
        pack['input_digest'] = contracts.digest(pack)
        for task in ('spread_mechanism', 'platform_fit'):
            oid = uid(task); key = contracts.digest(task)
            pdigest = I._policy_digest(self.cur, self.store, WID, ACTOR, [{'scope_key': self.scope,
                'provider_id': self.originals[0]['provider_id'], 'version': self.originals[0]['source_policy_version']}], task, NOW)
            # Run the actual question-set/parser/judge envelope adapter through a
            # deliberately injected in-memory transport. Never hand-invent answers.
            def transport(method, url, *, headers, body, timeout):
                answers = {name: {'type': 'choice', 'choice': 'supported',
                    'probabilities': {k: float(k == 'supported') for k in q['criteria']}}
                    for name, q in body['questions'].items()}
                return {'status': 200, 'body': {'model': DEFAULT_MODEL, 'answers': answers,
                    'usage': {'inputTokens': 1, 'outputTokens': 1}}}
            router = AIModelRouter(jev=JevService('synthetic', transport=transport), usage=MemoryUsageSink(),
                tasks={'trend.' + task: ('evaluate', DEFAULT_MODEL, (), 3.0, 1000)})
            raw = judge.evaluate(router, task, pack, workspace_id=WID, authorized=True, reserved_microusd=1000)
            self.assertEqual(raw['status'], 'ok', raw)
            payload = judgment_cache.envelope(key, raw, scope_key=PRIVATE, expires_at=AFTER,
                dependency_ids=[self.receipt['object_id']], context_revision=relevance.context_revision(self.state), policy_digest=pdigest)
            projection = self.record('model_judgment', oid, payload)
            method_id, version, _ = enrichment.method_identity()
            projection['method_bundle'] = {'method_id': method_id, 'version': version}
            self.records[('model_judgment', oid)] = projection
            self.loaded[task] = {'result_id': oid, 'key': key, 'pack': deepcopy(pack), 'receipt': self.receipt,
                'trend': self.trend, 'method_id': projection['method_bundle']['method_id'], 'expires_at': AFTER,
                'method_version': version, 'context_revision': relevance.context_revision(self.state),
                'source_ids': [o['observation_id'] for o in self.originals],
                'policy_digest': pdigest, 'config': {'model': DEFAULT_MODEL}}
        # Patch only the expensive current receipt reconstruction in the unit
        # fixture; actual _cached, cache envelope and stored adapter run unchanged.
        def load_native(_self, cur, wid, actor, rid, task, state):
            if not _self.enabled(wid):
                raise contracts.ContractError('model_enrichment_disabled')
            return deepcopy(self.loaded[task])
        p = patch.object(enrichment.TrendEnrichment, '_load', load_native)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(enrichment, 'utcnow', return_value=NOW)
        p.start(); self.addCleanup(p.stop)

    def record(self, kind, oid, payload, scope=PRIVATE):
        return {'kind': kind, 'object_id': oid, 'projection_id': uid(kind + ':' + oid), 'revision': 1,
            'scope_key': scope, 'validity': 'valid', 'verification_state': 'pending',
            'available_at': BEFORE, 'expires_at': AFTER, 'payload': deepcopy(payload),
            'policy': {p: True for p in contracts.PERMISSIONS},
            'method_bundle': {'method_id': 'synthetic.' + kind, 'version': '1'}}

    def review(self, record, role):
        record['payload'].update(schema_version=I.SCHEMA, role=role, state='qualified', fixture=False,
            evaluation_digest='e' * 64, provenance={'reviewer_id': ACTOR, 'review_workspace_id': WID,
                'authority': 'synthetic-only', 'decision': 'approved', 'reviewed_at': BEFORE, 'evidence_ref': 'fixture-review'})
        gate = {'state': 'production', 'role': role, 'schema_version': I.SCHEMA,
            'runtime_digest': I.runtime_digest(), 'review_authority': 'synthetic-only', 'reviewer_ids': [ACTOR],
            'cohort': deepcopy(self.cohort), 'minimum_samples': 1, 'allowed_access_methods': ['synthetic_fixture'],
            'period': {'id': self.cohort['period'], 'start': '2026-09-20T00:00:00Z',
                'end': BEFORE, 'preregistered_at': '2026-09-19T00:00:00Z'}}
        self.methods[(record['method_bundle']['method_id'], '1')] = ('qualified', None, {'interpretation_context': gate}, '2026-09-18T00:00:00Z')
        self.records[(record['kind'], record['object_id'])] = record
        return record

    def spread_review(self):
        loaded = self.loaded['spread_mechanism']; raw = self.records[('model_judgment', loaded['result_id'])]['payload']['result']
        e = loaded['pack']['evidence'][0]
        return self.review(self.record('interpretation_review', I.review_id(WID, loaded['result_id']), {
            'judgment_digest': contracts.digest(raw), 'context_digest': relevance.context_revision(self.state),
            'trust_receipt_id': self.receipt['object_id'], 'hypotheses': [{'mechanism': 'practical_utility',
                'evidence_spans': [{'observation_id': e['observation_id'], 'start': 0, 'end': 10, 'text': e['text'][:10]}],
                'alternatives': ['A different observed content mechanism could explain this sample.'],
                'contradictions': [], 'uncertainty': 'Synthetic review; no causal qualification.', 'risk_blocked': False}]}), 'spread')

    def prior(self, scope=None):
        scope = scope or self.scope
        return self.review(self.record('platform_prior', I.prior_id(scope, self.cohort), {
            'cohort': deepcopy(self.cohort), 'drifted': False, 'prior_version': '1', 'workspace_id': None,
            'basis': 'permitted_observations', 'finding': 'A reviewed sample finding.', 'uncertainty': 'No causal claim.',
            'source_bindings': [{'scope_key': self.scope, 'node_id': self.originals[0]['observation_id']}]}, scope=scope), 'prior')

    def load(self, **kwargs):
        return I.load(self.cur, self.store, WID, ACTOR, self.inputs, receipt_id=self.receipt['object_id'],
            state=deepcopy(self.state), values=kwargs.pop('values', self.values), cohort=kwargs.pop('cohort', self.cohort), now=NOW, **kwargs)

    def test_real_native_envelope_is_reachable_but_not_a_review(self):
        result = self.load()
        self.assertEqual(len(result['evidence']), 2)
        self.assertEqual(result['evidence'][0]['choices']['practical_utility'], 'supported')
        self.assertTrue(all(e['qualification'] == 'unqualified' for e in result['evidence']))
        self.assertEqual(result['projection_fields']['spread']['state'], 'unknown')
        self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.assertEqual(len(result['refs']), 3)

    def test_both_pure_functions_run_when_flags_off_without_storage(self):
        with patch.object(I.spread, 'project_spread_hypotheses', wraps=I.spread.project_spread_hypotheses) as s, \
                patch.object(I.platform_priors, 'resolve_prior', wraps=I.platform_priors.resolve_prior) as p:
            result = self.load(values={})
        s.assert_called_once(); p.assert_called_once(); self.store.authorized_scopes.assert_not_called()
        self.assertEqual(result['limitations'], ['disabled']); self.assertEqual(self.cur.queries, [])

    def test_missing_allowlist_does_not_load(self):
        self.assertEqual(self.load(values={**self.values, 'RAFII_TREND_WORKSPACE_ALLOWLIST': ''})['limitations'], ['disabled'])

    def test_actual_preview_isolation_disables_model_context(self):
        from postriff_phase2.deployment import isolated_environment
        from test_consumer_deployment import PreviewIsolation
        requested = {**self.values, **PreviewIsolation().env()}
        with self.assertRaises(ValueError):
            isolated_environment(requested)
        with patch.dict(os.environ, requested, clear=True), patch.object(I.config.flags, '_values', None):
            result = self.load(values=None)
        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['provider_attempts'], 0)

    def test_native_model_flag_off_keeps_prior_reader_local(self):
        self.prior()
        result = self.load(values={**self.values, 'RAFII_TREND_MODEL_ENRICHMENT_ENABLED': 'false'})
        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'shared_hypothesis')

    def test_reviewed_spread_retains_exact_originals_alternatives_and_dag(self):
        review = self.spread_review(); result = self.load(); h = result['projection_fields']['spread']['hypotheses'][0]
        self.assertEqual(h['evidence_spans'], review['payload']['hypotheses'][0]['evidence_spans'])
        self.assertEqual(h['alternatives'], review['payload']['hypotheses'][0]['alternatives'])
        self.assertFalse(result['projection_fields']['spread']['causal_claim'])
        self.assertIn(I._node(review), result['refs'])
        self.assertEqual(self.load(expected=result['bindings'])['bindings'], result['bindings'])

    def test_risk_and_brand_exclusions_override_supported_answer(self):
        review = self.spread_review()
        self.assertEqual(self.load(brand_exclusions=['practical_utility'])['projection_fields']['spread']['state'], 'unknown')
        review['payload']['hypotheses'][0]['risk_blocked'] = True
        self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')

    def test_alternatives_translation_span_bool_and_array_limits_fail_closed(self):
        original = deepcopy(self.spread_review())
        for key, value in [('alternatives', []), ('contradictions', ['x'] * 9), ('uncertainty', ''), ('risk_blocked', 0),
                           ('evidence_spans', []), ('evidence_spans', [{'observation_id': self.originals[0]['observation_id'],
                              'start': False, 'end': 2, 'text': 'a translated gloss'}])]:
            with self.subTest(key=key):
                altered = deepcopy(original); altered['payload']['hypotheses'][0][key] = value
                self.records[(altered['kind'], altered['object_id'])] = altered
                self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')

    def test_native_answer_wrong_type_missing_or_probability_not_domain_confidence(self):
        key = ('model_judgment', self.loaded['spread_mechanism']['result_id']); original = deepcopy(self.records[key])
        for answer in ({'type': 'boolean', 'value': True, 'abstained': False},
                       {'type': 'choice', 'value': 'supported', 'abstained': 0},
                       {'type': 'choice', 'value': float('nan'), 'abstained': False},
                       {'type': 'choice', 'value': 'supported', 'abstained': False, 'probability': .99}):
            self.records[key] = deepcopy(original); self.records[key]['payload']['result']['answers']['utility'] = answer
            self.assertNotIn('spread_mechanism', [r['task'] for r in self.load()['evidence']])

    def test_abstention_is_unknown_not_false_support(self):
        p = self.records[('model_judgment', self.loaded['spread_mechanism']['result_id'])]
        p['payload']['result']['answers']['utility'] = {'type': 'choice', 'value': None, 'abstained': True}
        self.assertEqual(self.load()['evidence'][0]['choices']['practical_utility'], 'unknown')

    def test_method_question_input_model_and_cache_key_drift(self):
        key = ('model_judgment', self.loaded['spread_mechanism']['result_id']); original = deepcopy(self.records[key])
        for name in ('question_digest', 'question_set', 'input_digest', 'executed_model', 'route', 'evaluation_kind'):
            self.records[key] = deepcopy(original); self.records[key]['payload']['result'][name] = 'wrong'
            self.assertNotIn('spread_mechanism', [r['task'] for r in self.load()['evidence']])
        self.records[key] = deepcopy(original); self.records[key]['payload']['key'] = 'wrong'
        self.assertNotIn('spread_mechanism', [r['task'] for r in self.load()['evidence']])

    def test_current_llm_denial_excludes_judgment(self):
        self.records[('model_judgment', self.loaded['spread_mechanism']['result_id'])]['policy']['llm_process'] = False
        self.assertNotIn('spread_mechanism', [r['task'] for r in self.load()['evidence']])

    def test_source_current_raw_llm_or_expiry_denial(self):
        original = deepcopy(self.inputs)
        for op in ('creative', 'llm'):
            self.inputs = deepcopy(original)
            for s in self.inputs['common']['sources']: s['rights'][op] = False
            self.assertEqual(self.load()['evidence'], [])
        self.inputs = deepcopy(original)
        for s in self.inputs['common']['sources']: s['expires_at'] = NOW
        self.assertEqual(self.load()['evidence'], [])

    def test_review_expired_future_unqualified_revoked_or_fabricated(self):
        review = self.spread_review(); key = (review['kind'], review['object_id']); original = deepcopy(review)
        for field, value in [('expires_at', NOW), ('available_at', AFTER), ('validity', 'deleted')]:
            self.records[key] = deepcopy(original); self.records[key][field] = value
            self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')
        self.records[key] = deepcopy(original); self.records[key]['payload']['fixture'] = True
        self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')
        self.records[key] = original
        self.methods[(review['method_bundle']['method_id'], '1')] = ('shadow', None, {}, BEFORE)
        self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')

    def test_review_authority_and_editor_are_current(self):
        self.spread_review(); self.store._actor.side_effect = contracts.ContractError('membership_revoked')
        self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')

    def test_exact_dag_is_required_for_optional_evidence(self):
        self.spread_review(); self.prior(); self.cur.ancestry_ok = False
        result = self.load()
        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_expected_bindings_reject_revocation_or_new_review(self):
        previous = self.load()['bindings']; self.spread_review()
        with self.assertRaisesRegex(ValueError, 'interpretation_binding_changed'): self.load(expected=previous)
        previous = self.load()['bindings']; self.records.pop(('model_judgment', self.loaded['spread_mechanism']['result_id']))
        with self.assertRaisesRegex(ValueError, 'interpretation_binding_changed'): self.load(expected=previous)

    def test_current_member_and_receipt_rejection_cannot_become_optional_unknown(self):
        self.store.authorized_scopes.side_effect = contracts.ContractError('member_revoked')
        with self.assertRaises(ValueError): self.load()
        self.store.authorized_scopes.side_effect = None
        self.store.get_receipt.return_value['verification_state'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'receipt_unavailable'): self.load()

    def test_expired_inputs_cannot_support_a_fresh_interpretation(self):
        self.inputs['expires_at'] = NOW
        with self.assertRaisesRegex(ValueError, 'inputs_outside_current_time'): self.load()

    def test_shared_entitlement_requires_each_current_operation(self):
        self.prior()
        for op in ('retrieve', 'derive_metrics', 'share_across_workspaces'):
            self.entitlement = ([p for p in ('retrieve', 'derive_metrics', 'share_across_workspaces') if p != op], AFTER, None)
            self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.entitlement = (['retrieve', 'derive_metrics', 'share_across_workspaces'], NOW, None)
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_caller_workspace_state_is_not_authority(self):
        with self.assertRaisesRegex(ValueError, 'workspace_state_changed'):
            I.load(self.cur, self.store, WID, ACTOR, self.inputs, receipt_id=self.receipt['object_id'],
                state={'brandHub': {'subject': 'invented'}}, values=self.values, now=NOW)

    def test_qualified_shared_prior_invokes_pure_function_and_keeps_private_unknown(self):
        prior = self.prior(); result = self.load(); p = result['projection_fields']['platform_dna']
        self.assertEqual(p['effective_basis'], 'shared_hypothesis', result['limitations'])
        self.assertEqual(p['historical_fit'], 'unknown'); self.assertEqual(p['private_adjustments'], [])
        self.assertFalse(p['permanent_voice_changed']); self.assertIn(I._node(prior), result['refs'])

    def test_native_sql_datetimes_preserve_registration_and_expiry_gates(self):
        prior = self.prior(); key = (prior['method_bundle']['method_id'], '1')
        method = self.methods[key]; entitlement = self.entitlement
        self.methods[key] = (*method[:3], contracts.instant(method[3]))
        self.entitlement = (entitlement[0], contracts.instant(entitlement[1]), entitlement[2])
        resolved, _, _, _ = I._prior(self.cur, self.store, WID, ACTOR, self.state, prior, self.cohort, NOW)
        self.assertEqual(resolved['qualification'], 'qualified')
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'shared_hypothesis')
        self.entitlement = (entitlement[0], contracts.instant(NOW), None)
        with self.assertRaisesRegex(ValueError, 'prior_entitlement'):
            I._prior(self.cur, self.store, WID, ACTOR, self.state, prior, self.cohort, NOW)
        self.entitlement = (entitlement[0], contracts.instant(AFTER), None)
        self.methods[key] = (*method[:3], contracts.instant(NOW))
        with self.assertRaisesRegex(ValueError, 'prior_preregistered_period'):
            I._prior(self.cur, self.store, WID, ACTOR, self.state, prior, self.cohort, NOW)

    def test_total_prior_bound_abstains_instead_of_hiding_disagreement(self):
        prior = self.prior()
        resolved, sources, _, _ = I._prior(self.cur, self.store, WID, ACTOR, self.state, prior, self.cohort, NOW)
        scopes = ['shared:bounded-' + str(i) for i in range(11)]
        self.store.authorized_scopes.return_value = scopes + [PRIVATE]
        for scope in scopes:
            record = deepcopy(prior); record.update(scope_key=scope,
                object_id=I.prior_id(scope, self.cohort), projection_id=uid(scope))
            self.records[('platform_prior', record['object_id'])] = record
        def bounded_prior(_cur, _store, _wid, _actor, _state, record, _cohort, _now):
            batch = [{**sources[0], 'source_id': uid(record['scope_key'] + ':' + str(i))} for i in range(100)]
            finding = 'conflicting final sample' if record['scope_key'] == scopes[-1] else resolved['finding']
            return {**resolved, 'finding': finding, 'evidence_refs': [s['source_id'] for s in batch]}, batch, [], None
        with patch.object(I, '_prior', side_effect=bounded_prior):
            result = self.load()
        self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.assertEqual(result['projection_fields']['platform_dna']['shared_priors'], [])
        self.assertIn('prior_total_bound', result['limitations'])

    def test_absent_format_niche_or_period_never_inferred_from_brand(self):
        self.prior()
        for key in ('format', 'niche', 'period'):
            cohort = deepcopy(self.cohort); cohort.pop(key)
            result = self.load(cohort=cohort)
            self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'unknown')
            self.assertIn('explicit_cohort_required', result['limitations'])

    def test_drift_retirement_sparse_or_wrong_version_is_unknown(self):
        p = self.prior(); key = (p['kind'], p['object_id']); original = deepcopy(p)
        for name, value in [('drifted', True), ('prior_version', '2'), ('workspace_id', OTHER),
                            ('basis', 'generic_stereotype'), ('finding', float('nan'))]:
            self.records[key] = deepcopy(original); self.records[key]['payload'][name] = value
            self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.records[key] = deepcopy(original)
        self.methods[(p['method_bundle']['method_id'], '1')][2]['interpretation_context']['minimum_samples'] = 2
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_prior_current_rights_contract_scope_and_expiry(self):
        self.prior()
        for op in ('derive_metrics', 'retain_derivatives', 'store_raw', 'share_across_workspaces'):
            for grant in ('unknown', 'deny'):
                with self.subTest(op=op, grant=grant):
                    self.originals[0]['rights'] = deepcopy(PERMISSIONS)
                    self.originals[0]['rights'][op]['state'] = grant
                    self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.originals[0]['rights'] = deepcopy(PERMISSIONS)
        self.originals[0]['rights']['store_raw']['audience_scope'] = PRIVATE
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_prior_source_bounds_duplicates_and_cross_tenant(self):
        p = self.prior(); original = deepcopy(p['payload']['source_bindings'])
        for refs in ([], original * 101, original * 2,
                     [{'scope_key': 'workspace:' + OTHER, 'node_id': original[0]['node_id']} ]):
            p['payload']['source_bindings'] = refs
            self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_prior_period_requires_actual_preregistration_and_source_in_window(self):
        p = self.prior(); gate = self.methods[(p['method_bundle']['method_id'], '1')][2]['interpretation_context']
        original = deepcopy(gate['period'])
        for key, value in [('preregistered_at', NOW), ('start', BEFORE), ('id', 'other'), ('end', AFTER)]:
            gate['period'] = {**original, key: value}
            self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_new_registry_row_cannot_backdate_preregistration(self):
        p = self.prior(); key = (p['method_bundle']['method_id'], '1')
        self.methods[key] = (*self.methods[key][:3], NOW)
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_existing_prose_boundaries_remain_private_and_override_spread(self):
        self.spread_review()
        self.state['profile'] = {'fields': [{'id': 'boundaries-risk', 'value': 'private brand boundary', 'privacy': 'private'}]}
        result = self.load()
        self.assertEqual(result['projection_fields']['spread']['state'], 'unknown')
        self.assertNotIn('private brand boundary', contracts.canonical(result))
        self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        self.state['profile']['fields'][0]['value'] = 'changed boundary'
        with self.assertRaises(ValueError): self.current(result['bindings'])

    def test_malformed_review_containers_remain_unknown(self):
        p = self.spread_review(); original = deepcopy(p['payload'])
        for name, value in [('provenance', []), ('hypotheses', ['wrong']), ('hypotheses', [None])]:
            p['payload'] = {**deepcopy(original), name: value}
            self.assertEqual(self.load()['projection_fields']['spread']['state'], 'unknown')

    def test_private_prior_cannot_self_certify_owned_outcomes(self):
        p = self.prior(PRIVATE); p['payload'].update(workspace_id=WID, basis='actual_published_outcomes',
            job_ids=['invented-1', 'invented-2', 'invented-3'], outcomes_digest='invented',
            outcome_frame={'provider': self.cohort['platform'], 'language': self.cohort['language'], 'format': 'text'})
        self.assertEqual(self.load()['projection_fields']['platform_dna']['historical_fit'], 'unknown')

    def test_no_writes_dispatch_or_new_connections(self):
        self.spread_review(); self.prior(); self.load()
        self.store.connection_factory.assert_not_called()
        for name in ('put_projection', 'put_manifest', 'put_method', 'put_observation'):
            getattr(self.store, name).assert_not_called()
        self.assertTrue(all('INSERT ' not in q and 'UPDATE ' not in q and 'DELETE ' not in q for q, _ in self.cur.queries))

    def current(self, bindings, **kwargs):
        return I.validate_current(self.cur, self.store, WID, ACTOR, self.inputs,
            receipt_id=self.receipt['object_id'], state=deepcopy(self.state), bindings=bindings,
            values=kwargs.pop('values', self.values), now=NOW, **kwargs)

    def test_viewer_read_uses_current_heads_without_edit_locks_or_pack_construction(self):
        self.spread_review(); self.prior(); produced = self.load()
        self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        self.store.lock_dependencies.reset_mock()
        with patch.object(enrichment.TrendEnrichment, '_load', side_effect=AssertionError('GET pack construction forbidden')), \
                patch.object(enrichment.TrendEnrichment, '_model', side_effect=AssertionError('GET model forbidden')):
            self.assertTrue(self.current(produced['bindings']))
        self.store.lock_dependencies.assert_not_called()

    def test_viewer_read_revoked_policy_unknown_scope_or_changed_context_rejected(self):
        produced = self.load(); self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        self.store._policy.side_effect = contracts.ContractError('revoked')
        with self.assertRaises(ValueError): self.current(produced['bindings'])
        self.store._policy.side_effect = lambda *a, **kw: deepcopy(self.policy_record)
        self.store.scope_signature.return_value = 'revoked-sharing'
        with self.assertRaises(ValueError): self.current(produced['bindings'])
        self.store.scope_signature.return_value = 'synthetic-scope-signature'
        self.state['brandHub']['subject'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'read_binding_changed'): self.current(produced['bindings'])

    def test_viewer_read_exact_artifact_head_and_registry_changes(self):
        review = self.spread_review(); produced = self.load()
        self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        review['revision'] += 1
        with self.assertRaisesRegex(ValueError, 'read_artifact_changed'): self.current(produced['bindings'])
        review['revision'] -= 1
        self.methods[(review['method_bundle']['method_id'], '1')][2]['interpretation_context']['runtime_digest'] = 'old'
        with self.assertRaisesRegex(ValueError, 'review_method_unqualified'): self.current(produced['bindings'])

    def test_viewer_read_method_runtime_drift_or_llm_flag_off(self):
        produced = self.load(); self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        with patch.object(enrichment, 'method_identity', return_value=('changed', 'changed', 'changed')):
            with self.assertRaises(ValueError): self.current(produced['bindings'])
        with self.assertRaisesRegex(ValueError, 'read_model_disabled'):
            self.current(produced['bindings'], values={**self.values, 'RAFII_TREND_MODEL_ENRICHMENT_ENABLED': 'false'})

    def test_viewer_read_unknown_without_cohort_remains_readable(self):
        self.state['coworker'].pop('trendPlatformCohort')
        produced = self.load(cohort=None)
        self.records[('receipt', self.receipt['object_id'])] = deepcopy(self.receipt)
        self.assertTrue(self.current(produced['bindings']))

    def test_explicit_cohort_must_be_persisted_and_match_native_frame(self):
        self.prior(); self.state['coworker'].pop('trendPlatformCohort')
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')
        self.state['coworker']['trendPlatformCohort'] = deepcopy(self.cohort)
        self.inputs['frame']['language'] = 'different'
        self.assertEqual(self.load()['projection_fields']['platform_dna']['effective_basis'], 'unknown')

    def test_owned_adapter_reuses_native_publication_reader_and_actual_comparison(self):
        from postriff_phase2.growth.trends import learning, lab_enrichment
        from postriff_phase2.growth.trends import service
        self.state['phase2'].update(channels=[{'id': 'owned-account', 'platform': 'Threads', 'language': 'en'}], jobs=[])
        self.state['sources'] = []
        timestamp = contracts.instant(NOW).timestamp(); published = timestamp - 2 * 86400
        records = []
        for i in range(3):
            binding = {'opportunity_id': uid('own-op' + str(i)), 'trust_receipt_id': self.receipt['object_id'],
                'trend_id': self.trend['object_id'], 'angle_id': 'angle-1', 'selection_digest': contracts.digest(i),
                'channel_id': 'owned-account', 'platform': 'Threads', 'accepted_at': published - 200}
            self.state['sources'].append({'id': 'source-' + str(i), 'active': True, 'origin': {'trendLineage': binding}})
            learning.record_metric_choice(self.state, ACTOR, {'selection_digest': binding['selection_digest'],
                'channel_id': 'owned-account', 'provider': 'threads', 'metric': 'views', 'definition_version': '2026-09',
                'window': '24h', 'objective': 'reach'}, published - 100)
            job = {'id': 'job-' + str(i), 'state': 'verified', 'providerReference': 'native-' + str(i),
                'verifiedAt': published, 'manifest': {'channelId': 'owned-account', 'platform': 'Threads',
                    'payload': {'text': 'original', 'language': 'en'}, 'contentType': {'id': 'opinion'}, 'paidPromotion': False,
                    'trendLineage': [binding], 'trendPublication': {'variantRevision': 1, 'textDigest': contracts.digest('original'),
                        'channelId': 'owned-account', 'platform': 'Threads', 'treatmentChanged': False}}}
            self.state['phase2']['jobs'].append(job)
            self.records[('opportunity', binding['opportunity_id'])] = self.record('opportunity', binding['opportunity_id'], {})
        self.records[('receipt', self.receipt['object_id'])] = self.receipt
        self.records[('trend', self.trend['object_id'])] = self.trend
        frame = {'account': 'owned-account', 'provider': 'threads', 'language': 'en', 'format': 'opinion',
            'window': '24h', 'objective': 'reach', 'definition': '2026-09', 'metric': 'views'}
        metric_cursor = Mock()
        metric_cursor.fetchall.return_value = [('views', 50, 'count', 'available', published + 86400, published + 86401, uid('metric'))]
        # The real _publication/_metric path parses these SQL response rows;
        # no manufactured "measured" result is supplied to the adapter.
        for job in self.state['phase2']['jobs']:
            b = job['manifest']['trendLineage'][0]
            records.append(learning._publication(metric_cursor, WID, self.state, b, b, job, timestamp, '24h'))
        history = lab_enrichment.comparable_history(records, frame, timestamp)
        self.assertTrue(history['comparable'])
        payload = {'job_ids': ['job-' + str(i) for i in range(3)], 'outcome_frame': frame,
            'outcomes_digest': contracts.digest(history)}
        with patch.object(service, 'validate_stored_bindings') as validate:
            observed, deps = I._owned(metric_cursor, self.store, WID, ACTOR, self.state, payload, NOW, read_only=True)
            self.assertEqual(observed, history); self.assertEqual(len(deps), 9)
            self.assertTrue(all(c.kwargs['read_only'] is True for c in validate.call_args_list))
            self.store.lock_dependencies.assert_not_called()
            metric_cursor.fetchall.return_value[0] = ('views', 51, 'count', 'available', published + 86400, published + 86401, uid('metric'))
            with self.assertRaisesRegex(ValueError, 'owned_history_changed'):
                I._owned(metric_cursor, self.store, WID, ACTOR, self.state, payload, NOW, read_only=True)
            self.state['phase2']['jobs'][1]['providerReference'] = 'native-0'
            with self.assertRaisesRegex(ValueError, 'owned_duplicate_native_post'):
                I._owned(metric_cursor, self.store, WID, ACTOR, self.state, payload, NOW, read_only=True)

    def test_portable_wrapper_rejects_unallocated_or_overridden_dsn_without_connection(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('interpretation_portable_fixture',
            Path(__file__).parent / 'phase2/postgres_trend_interpretation.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        before = list(sys.path)
        bad = [None, 'host=example.invalid port=55438 dbname=postgres',
            'host=127.0.0.1 port=5432 dbname=postgres', 'host=127.0.0.1 port=55438 dbname=production',
            'host=127.0.0.1 port=55438 dbname=postgres sslmode=require']
        with patch('psycopg.connect', side_effect=AssertionError('invalid DSN attempted connection')) as connect:
            for dsn in bad:
                with patch.dict(os.environ, {'POSTRIFF_TEST_DSN': dsn} if dsn else {}, clear=True):
                    with self.assertRaises(ValueError): module.main()
                self.assertEqual(sys.path, before)
            with patch.dict(os.environ, {'POSTRIFF_TEST_DSN': 'host=127.0.0.1 port=55438 dbname=postgres', 'PGOPTIONS': ''}, clear=True):
                with self.assertRaises(ValueError): module.main()
            connect.assert_not_called()


@unittest.skipUnless(os.environ.get('TREND_INTERPRETATION_TEST_DSN'), 'explicit disposable interpretation DSN required')
class InterpretationPostgresTests(unittest.TestCase):
    """Actual040 writes/reads; sources, reviews and model transport are synthetic."""
    @classmethod
    def setUpClass(cls):
        from test_trend_enrichment import EnrichmentPostgresTests
        with patch.dict(os.environ, {'TREND_ENRICHMENT_TEST_DSN': os.environ['TREND_INTERPRETATION_TEST_DSN']}):
            EnrichmentPostgresTests.setUpClass.__func__(cls)
        with cls.connect() as db:
            if db.execute("SELECT to_regclass('pr_runtime')").fetchone()[0] is not None:
                raise AssertionError('canonical040 only; pr_runtime must be absent')

    def setUp(self):
        from test_trend_enrichment import EnrichmentPostgresTests
        from postriff_phase2.growth.trends.store import TrendStore
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.getaddrinfo',
                     'urllib.request.urlopen', 'urllib.request.OpenerDirector.open'):
            p = patch(name, side_effect=AssertionError('live network forbidden'))
            guard = p.start(); self.addCleanup(p.stop); self.addCleanup(guard.assert_not_called)
        original = TrendStore.register_policy
        def register(store, value, **kwargs):
            value = deepcopy(value); value['model_enrichment']['tasks'] = ['workspace_fit', 'spread_mechanism', 'platform_fit']
            return original(store, value, **kwargs)
        with patch.object(TrendStore, 'register_policy', register):
            EnrichmentPostgresTests.setUp(self)
        receipt = self.store.get_receipt(self.wid, self.actor, self.rid)
        self.tid = receipt['payload']['trend_id']
        self.advanced = advanced_pipeline.AdvancedPipeline(self.store, values=self.values)
        self.cohort = {'platform': 'bluesky', 'language': 'yue', 'format': 'text', 'niche': 'synthetic-baking', 'period': 'synthetic-period'}
        self.state.setdefault('coworker', {})['trendPlatformCohort'] = deepcopy(self.cohort)
        self.save_state()
        self.queued = self.worker.enqueue(self.wid, self.actor, self.rid, 'spread_mechanism', idempotency_key='native')
        completed = self.worker.tick()
        self.assertEqual(completed['attached'], 1, completed)
        self.assertEqual(len(self.calls), 1)

    def save_state(self):
        with self.connect() as db:
            db.execute('UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s', (json.dumps(self.state), self.wid))

    def context(self, *, actor=None, expected=None, values=None, cursor=None):
        from postriff_phase2.growth.trends.store import utcnow
        actor = actor or self.actor
        with self.store.transaction(cursor) as cur:
            _, _, _, inputs = self.advanced._load(cur, self.wid, actor, self.tid, read_only=actor != self.actor)
            cur.execute('SELECT state FROM pr_workspaces WHERE id=%s', (self.wid,)); state = cur.fetchone()[0]
            result = I.load(cur, self.store, self.wid, actor, inputs, receipt_id=self.rid, state=state,
                values=self.values if values is None else values, cohort=self.cohort, expected=expected, now=utcnow())
            return result

    def validate(self, bindings, *, actor=None, values=None):
        from postriff_phase2.growth.trends.store import utcnow
        with self.store.transaction() as cur:
            _, _, _, inputs = self.advanced._load(cur, self.wid, actor or self.actor, self.tid, read_only=True)
            cur.execute('SELECT state FROM pr_workspaces WHERE id=%s', (self.wid,)); state = cur.fetchone()[0]
            return I.validate_current(cur, self.store, self.wid, actor or self.actor, inputs,
                receipt_id=self.rid, state=state, bindings=bindings, values=self.values if values is None else values, now=utcnow())

    def persist_review(self, *, prior=False, attached=True, qualification='qualified'):
        from datetime import timedelta
        from postriff_phase2.growth.trends.store import utcnow
        with self.store.transaction() as cur:
            now = utcnow()
            native = self.store.get_projection(self.wid, self.actor, 'model_judgment', self.queued['result_id'], cursor=cur)
            loaded = self.worker._load(cur, self.wid, self.actor, self.rid, 'spread_mechanism', self.state)
            sample = loaded['pack']['evidence'][0]
            kind, role = ('platform_prior', 'prior') if prior else ('interpretation_review', 'spread')
            scope = self.scope if prior else 'workspace:' + self.wid
            oid = I.prior_id(scope, self.cohort) if prior else I.review_id(self.wid, native['object_id'])
            provenance = {'reviewer_id': self.actor, 'review_workspace_id': self.wid,
                'authority': 'synthetic-local-fixture', 'decision': 'approved', 'reviewed_at': now, 'evidence_ref': 'fixture-only'}
            payload = {'schema_version': I.SCHEMA, 'role': role, 'state': 'qualified', 'fixture': False,
                'evaluation_digest': 'a' * 64, 'provenance': provenance}
            if prior:
                payload.update(cohort=self.cohort, drifted=False, prior_version='1', workspace_id=None,
                    basis='permitted_observations', finding='Synthetic reviewed sample', uncertainty='Fixture is not a real qualification.',
                    source_bindings=[{'scope_key': self.scope, 'node_id': sample['observation_id']}])
                refs = payload['source_bindings']
            else:
                payload.update(judgment_digest=contracts.digest(native['payload']['result']),
                    trust_receipt_id=self.rid, context_digest=loaded['context_revision'],
                    hypotheses=[{'mechanism': 'practical_utility', 'evidence_spans': [{
                        'observation_id': sample['observation_id'], 'start': 0, 'end': 10, 'text': sample['text'][:10]}],
                        'alternatives': ['Another content mechanism could account for this sample.'], 'contradictions': [],
                        'uncertainty': 'No causal claim.', 'risk_blocked': False}])
                refs = [I._node(native)] if attached else [I._node(loaded['receipt'])]
            control = {'state': 'production', 'role': role, 'schema_version': I.SCHEMA,
                'runtime_digest': I.runtime_digest(), 'review_authority': provenance['authority'], 'reviewer_ids': [self.actor],
                'cohort': self.cohort, 'minimum_samples': 1, 'allowed_access_methods': ['synthetic'],
                'period': {'id': self.cohort['period'], 'start': contracts.iso(self.at - timedelta(days=1)),
                    'end': now, 'preregistered_at': contracts.iso(self.at - timedelta(days=2))}}
            mid = 'fixture.interpretation.' + uuid.uuid4().hex
            self.store.put_method(mid, '1', contracts.digest(control), {'interpretation_context': control}, cursor=cur)
            # Test-only independent operator promotion, never done by the adapter.
            cur.execute('UPDATE pr_trend_method_versions SET qualification=%s WHERE method_id=%s', (qualification, mid))
            if prior:
                # Simulate the earlier registration in this disposable synthetic
                # fixture only. This is not evidence of real-world preregistration.
                cur.execute('UPDATE pr_trend_method_versions SET created_at=%s WHERE method_id=%s',
                    (contracts.iso(self.at - timedelta(days=3)), mid))
            manifest = self.store.put_manifest(scope, refs, decision_cutoff=now, available_at=now,
                retention_until=native['expires_at'], cursor=cur)
            previous = self.store.get_projection(self.wid, self.actor, kind, oid, cursor=cur)
            revision = previous['revision'] + 1 if previous else 1
            self.store.put_projection({'scope_key': scope, 'kind': kind, 'object_id': oid, 'revision': revision,
                'manifest_id': manifest['manifest_id'], 'method_id': mid, 'method_version': '1',
                'decision_cutoff': now, 'available_at': now, 'retention_until': native['expires_at'], 'payload': payload},
                expected_revision=revision - 1 if previous else None, cursor=cur)
            return self.store.get_projection(self.wid, self.actor, kind, oid, cursor=cur)

    def viewer(self):
        viewer = str(uuid.uuid4())
        with self.psycopg.connect(self.dsn) as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (viewer,))
            db.execute('INSERT INTO pr_profiles(user_id) VALUES(%s)', (viewer,))
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (self.wid, viewer))
        return viewer

    def test_current_native_enrichment_adapter_and_viewer_without_prompt_or_edit_lock(self):
        result = self.context()
        self.assertEqual([r['task'] for r in result['evidence']], ['spread_mechanism'])
        self.assertEqual(result['projection_fields']['spread']['state'], 'unknown')
        self.assertEqual(self.context(expected=result['bindings'])['bindings'], result['bindings'])
        viewer = self.viewer()
        with patch.object(self.store, 'lock_dependencies', side_effect=AssertionError('viewer edit lock')), \
                patch.object(enrichment.TrendEnrichment, '_load', side_effect=AssertionError('viewer prompt construction')):
            self.assertTrue(self.validate(result['bindings'], actor=viewer))
        self.assertEqual(len(self.calls), 1)

    def test_spread_review_uses_real_exact_dag_and_method_qualification(self):
        self.persist_review(attached=False)
        self.assertEqual(self.context()['projection_fields']['spread']['state'], 'unknown')
        self.persist_review(qualification='shadow')
        self.assertEqual(self.context()['projection_fields']['spread']['state'], 'unknown')
        accepted = self.persist_review()
        result = self.context()
        self.assertEqual(result['projection_fields']['spread']['state'], 'hypotheses', result['limitations'])
        self.assertIn(I._node(accepted), result['refs'])
        self.assertTrue(self.validate(result['bindings'], actor=self.viewer()))

    def test_shared_prior_actual040_sources_then_current_raw_grant_revoked(self):
        from postriff_phase2.growth.trends.store import utcnow
        review = self.persist_review(prior=True)
        with self.store.transaction() as cur:
            prior, _, _, _ = I._prior(cur, self.store, self.wid, self.actor, self.state, review, self.cohort, utcnow())
            self.assertEqual(prior['qualification'], 'qualified')
        result = self.context()
        self.assertEqual(result['projection_fields']['platform_dna']['effective_basis'], 'shared_hypothesis', result['limitations'])
        self.assertTrue(self.validate(result['bindings'], actor=self.viewer()))
        oid = review['payload']['source_bindings'][0]['node_id']
        with self.connect() as db:
            db.execute("UPDATE pr_trend_observations SET rights=jsonb_set(rights,'{store_raw,state}','\"deny\"') WHERE observation_id=%s", (oid,))
        with self.assertRaises(ValueError): self.validate(result['bindings'])
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT payload FROM pr_trend_projections WHERE projection_id=%s',
                (review['projection_id'],)).fetchone()[0], review['payload'])

    def test_consumer_manifest_exact_dependencies_rollback_and_method_withdrawal(self):
        from postriff_phase2.growth.trends.store import utcnow
        self.persist_review(); result = self.context(); oid = str(uuid.uuid4())
        with self.assertRaisesRegex(RuntimeError, 'synthetic rollback'):
            with self.store.transaction() as cur:
                result = self.context(expected=result['bindings'], cursor=cur)
                manifest = self.store.put_manifest('workspace:' + self.wid, result['refs'], decision_cutoff=utcnow(),
                    available_at=utcnow(), retention_until=result['expires_at'], cursor=cur)
                self.store.put_method('fixture.consumer.' + oid, '1', contracts.digest('fixture'), {}, cursor=cur)
                self.store.put_projection({'scope_key': 'workspace:' + self.wid, 'kind': 'genome', 'object_id': oid,
                    'revision': 1, 'manifest_id': manifest['manifest_id'], 'method_id': 'fixture.consumer.' + oid, 'method_version': '1',
                    'decision_cutoff': utcnow(), 'available_at': utcnow(), 'retention_until': result['expires_at'],
                    'payload': {'interpretation_bindings': result['bindings']}}, cursor=cur)
                raise RuntimeError('synthetic rollback')
        self.assertIsNone(self.store.get_projection(self.wid, self.actor, 'genome', oid))
        native = self.store.get_projection(self.wid, self.actor, 'model_judgment', self.queued['result_id'])
        # Global method identity is shared across fixtures; restore it inside the
        # same rollback-only transaction to avoid touching other owners' state.
        with self.store.transaction() as cur:
            cur.execute('SAVEPOINT method_check')
            cur.execute("UPDATE pr_trend_method_versions SET qualification='withdrawn' WHERE method_id=%s AND version=%s",
                tuple(native['method_bundle'][k] for k in ('method_id', 'version')))
            with self.assertRaises(ValueError):
                self.context(expected=result['bindings'], cursor=cur)
            cur.execute('ROLLBACK TO SAVEPOINT method_check')

    def test_current_context_tenant_membership_and_model_flag_gate(self):
        result = self.context(); viewer = self.viewer()
        with self.assertRaises(ValueError): self.validate(result['bindings'], actor=str(uuid.uuid4()))
        with self.assertRaises(ValueError):
            self.validate(result['bindings'], values={**self.values, 'RAFII_TREND_MODEL_ENRICHMENT_ENABLED': 'false'})
        with self.connect() as db:
            db.execute("UPDATE pr_memberships SET status='revoked' WHERE workspace_id=%s AND user_id=%s", (self.wid, viewer))
        with self.assertRaises(ValueError): self.validate(result['bindings'], actor=viewer)
        self.state['coworker']['trendPlatformCohort']['niche'] = 'changed'; self.save_state()
        with self.assertRaises(ValueError): self.validate(result['bindings'])
        self.assertEqual(len(self.calls), 1)

    def test_integrated_genome_job_manifest_and_authenticated_viewer_service_read(self):
        from postriff_alpha.domain import AlphaError
        from postriff_phase2.hosted import PostgresWorkspaceRepository
        from postriff_phase2.ideas import IdeasService
        from postriff_phase2.growth.trends.service import TrendService
        from test_trend_service import assert_schema
        review = self.persist_review(); prior = self.persist_review(prior=True)
        self.values['RAFII_TREND_GRAPH_GENOME_ENABLED'] = 'true'
        queued = self.advanced.enqueue(self.wid, self.actor, self.tid, kinds=['genome'])['jobs'][0]
        with self.connect() as db:
            controls = db.execute('SELECT payload FROM pr_trend_jobs WHERE job_id=%s', (queued['job_id'],)).fetchone()[0]
        self.assertIn('interpretation_bindings', controls)
        completed = self.advanced.run('workspace:' + self.wid, queued['job_id'])
        self.assertEqual(completed['state'], 'succeeded')
        self.assertTrue(self.advanced.run('workspace:' + self.wid, queued['job_id'])['replayed'])
        with self.store.transaction() as cur:
            projection = self.store.get_projection(self.wid, self.actor, 'genome', self.tid, cursor=cur)
            cur.execute('SELECT manifest_id::text FROM pr_trend_projections WHERE projection_id=%s', (projection['projection_id'],))
            saved = self.store.get_manifest(projection['scope_key'], cur.fetchone()[0], cursor=cur)
            self.assertEqual(saved['digest'], contracts.digest({'inputs': saved['inputs'], 'recipe': saved['recipe'],
                'chunks': [c['digest'] for c in saved['chunks']]}))
            for i, chunk in enumerate(saved['chunks']):
                self.assertEqual(chunk['ordinal'], i); self.assertEqual(chunk['digest'], contracts.digest(chunk['payload']))
            details = json.loads(''.join(c['payload']['json'] for c in saved['chunks']))
            self.assertEqual(contracts.digest({k: v for k, v in details.items() if k != 'manifest_digest'}), saved['document_digest'])
            self.assertEqual(details['manifest_digest'], saved['recipe']['detail_codec']['pure_manifest_digest'])
            frozen = details['details']['interpretation_context']
            self.assertEqual(frozen['bindings'], controls['interpretation_bindings'])
            self.assertEqual(frozen['evidence'][0]['qualification'], 'unqualified')
            self.assertEqual(frozen['projection_fields']['spread']['state'], 'hypotheses')
            I._attached(cur, projection, [I._node(review), I._node(prior)])
        viewer = self.viewer()
        repository = PostgresWorkspaceRepository(self.connect, lambda token: viewer if token == 'viewer-session' else None,
            self.hosted.repository.commands)
        hosted = SimpleNamespace(repository=repository, connection_factory=self.connect,
            ideas=SimpleNamespace(_state=IdeasService._state, _member=IdeasService._member))
        service = TrendService(SimpleNamespace(hosted=hosted, repository=repository, values=self.values, clock=time.time),
            store_factory=lambda _: self.store, cursor_secret=b'synthetic-local-interpretation-key')
        with patch.object(enrichment.TrendEnrichment, '_load', side_effect=AssertionError('viewer prompt rebuild')), \
                patch.object(self.store, 'lock_dependencies', side_effect=AssertionError('viewer edit-only lock')):
            response = service.stored(self.wid, 'viewer-session', 'genome', self.tid)
        assert_schema(self, 'genome_response', response)
        dimensions = {d['dimension']: d for d in response['data']['dimensions']}
        self.assertEqual(len(dimensions), 11)
        self.assertIn('Hypothesis:', dimensions['Why it may spread']['finding'])
        self.assertIn('version 1', dimensions['Platform patterns']['finding'])
        self.assertNotIn('_interpretation_bindings', response['data'])
        self.assertEqual(len(self.calls), 1)
        self.state['coworker']['trendPlatformCohort']['period'] = 'changed-period'; self.save_state()
        with self.assertRaises(AlphaError) as rejected:
            service.stored(self.wid, 'viewer-session', 'genome', self.tid)
        self.assertEqual((rejected.exception.code, rejected.exception.status), ('source_unavailable', 503))

    def test_integrated_genome_queued_binding_change_cannot_execute(self):
        self.persist_review(); self.values['RAFII_TREND_GRAPH_GENOME_ENABLED'] = 'true'
        job = self.advanced.enqueue(self.wid, self.actor, self.tid, kinds=['genome'])['jobs'][0]
        self.persist_review()  # New exact review head; old job cannot silently substitute it.
        with self.assertRaisesRegex(ValueError, 'interpretation_binding_changed'):
            self.advanced.run('workspace:' + self.wid, job['job_id'])
        self.assertIsNone(self.store.get_projection(self.wid, self.actor, 'genome', self.tid))
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM pr_trend_jobs WHERE job_id=%s', (job['job_id'],)).fetchone()[0], 'queued')


if __name__ == '__main__':
    unittest.main()
