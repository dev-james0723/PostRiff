"""Real tool registry -> authenticated stored service, including model-right denials."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from postriff_phase2.agent_runtime_v2 import contracts, tool_adapter
from postriff_phase2.agent_runtime_v2.context import EffectLedger
from postriff_phase2.coworker import runtime
from postriff_phase2.growth.trends import tools
from test_trend_service import make_service, fixture_row, WID, TID, RID, OID, EID


class TrendToolTests(unittest.TestCase):
    def setUp(self):
        self.svc, self.repo, self.store = make_service()
        tools.register()
        self.ctx = SimpleNamespace(service=SimpleNamespace(coworker=self.svc.coworker, notifications=SimpleNamespace()), workspace_id=WID,
            token='session', ledger=EffectLedger())
        patcher = patch.object(runtime, 'ensure', side_effect=lambda service: service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, name, args=None):
        tool = tool_adapter.REGISTRY[name]
        tool_adapter._check_schema(tool.schema, args or {})
        return tool.executor(self.ctx, args or {})

    def test_all_routes_are_registered_idempotently_with_bounded_effects(self):
        expected = set().union(*map(set, tools.SCOPES.values()))
        self.assertTrue(expected <= tool_adapter.REGISTRY.keys())
        before = {name: tool_adapter.REGISTRY[name] for name in expected}
        tools.register()
        self.assertEqual(before, {name: tool_adapter.REGISTRY[name] for name in expected})
        for name in expected:
            spec = tool_adapter.REGISTRY[name].spec
            self.assertTrue(spec.voice)
            self.assertIn(spec.effect, (contracts.READ, contracts.CREATE_DRAFT, contracts.MUTATE_REVERSIBLE))
        self.assertEqual(tool_adapter.REGISTRY['trend_watch_create'].spec.permission, 'edit')

    def test_full_search_filters_reach_current_scoped_service_and_remain_model_safe(self):
        out = self.call('trend_search', {'query': 'music', 'platforms': 'bluesky', 'languages': 'en',
                                      'view': 'for_you', 'limit': 3})
        self.assertTrue(out['ok'])
        selected = next(c[2] for c in reversed(self.store.calls) if c[0] == 'list')
        self.assertEqual(selected['platforms'], ['bluesky'])
        self.assertEqual(selected['languages'], ['en'])
        self.store.rows['trend', TID]['policy']['llm_process'] = False
        safe = self.call('trend_search')
        self.assertEqual(safe['data']['data']['data'], [])
        denied = self.call('trend_detail', {'trend_id': TID})
        self.assertFalse(denied['ok'])
        self.assertEqual(denied['code'], 'forbidden')

    def test_stored_resource_display_right_does_not_grant_model_processing(self):
        self.store.rows['language_pattern', EID] = fixture_row('language_pattern', EID, {'fixture': 'not a model grant'})
        self.store.rows['language_pattern', EID]['policy']['llm_process'] = False
        out = self.call('trend_language_patterns')
        self.assertFalse(out['ok'])
        self.assertNotIn('not a model grant', str(out))
        self.store.rows['opportunity', OID]['policy']['llm_process'] = False
        self.assertFalse(self.call('trend_opportunity', {'opportunity_id': OID})['ok'])

    def test_create_and_disable_watch_reuse_real_revisioned_mutation_and_ledger(self):
        saved = self.call('trend_watch_create', {'trend_id': TID, 'platforms': ['bluesky'],
            'threshold': 'coverage_change', 'idempotency_key': 'tool-create'})
        self.assertTrue(saved['ok'])
        self.assertEqual(self.store.watches[0]['payload']['notification_policy'], 'in_app')
        disabled = self.call('trend_watch_disable', {'watch_id': EID, 'expected_revision': 1, 'idempotency_key': 'tool-disable'})
        self.assertTrue(disabled['ok'])
        self.assertFalse(self.store.watches[0]['enabled'])
        self.assertEqual(len(self.ctx.ledger.changed), 2)

    def test_foreign_member_flags_and_malformed_filter_fail_before_result(self):
        self.ctx.token = 'not-authorized'
        self.assertFalse(self.call('trend_receipt', {'trend_id': TID, 'receipt_id': RID})['ok'])
        self.ctx.token = 'session'
        self.assertFalse(self.call('trend_search', {'platforms': 'invented-platform'})['ok'])
        self.svc.coworker.values['RAFII_TREND_INTELLIGENCE_ENABLED'] = '0'
        self.assertFalse(self.call('trend_watches')['ok'])

    def test_lab_model_right_denial_precedes_durable_job_creation(self):
        self.store.rows['opportunity', OID]['policy']['llm_process'] = False
        result = self.call('trend_lab_check', {'draft_id': 'draft', 'draft_revision': 1, 'opportunity_id': OID,
            'opportunity_revision': 1, 'target_platform': 'bluesky', 'idempotency_key': 'tool-lab'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'forbidden')
        self.assertFalse(any(c[0] == 'enqueue' for c in self.store.calls))


if __name__ == '__main__':
    unittest.main()
