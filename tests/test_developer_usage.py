"""Quota authority comes only from an operator allowlist of verified UUIDs."""
import os
from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.developer_usage import ai_usage_exempt
from postriff_phase2.model_runtime import ServerModelRuntime, check_level_ceiling
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import invoke
from postriff_phase2.credit_requests import CreditRequests
from postriff_phase2.phone import billing

DEV = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'


class DeveloperUsageTests(unittest.TestCase):
    def test_disabled_and_invalid_configuration_fail_closed(self):
        for configured in ('', '*', 'JamesAU0723', DEV + ',invalid'):
            with self.subTest(configured=configured), patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': configured}):
                self.assertFalse(ai_usage_exempt(DEV))

    @patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': DEV})
    def test_exact_uuid_only_and_runtime_quota_skip(self):
        self.assertTrue(ai_usage_exempt(DEV))
        for actor in (OTHER, None, 'JamesAU0723', {'aiUsageExempt': True}):
            self.assertFalse(ai_usage_exempt(actor))
        with patch('postriff_phase2.model_runtime.level_of', side_effect=AssertionError('quota reached')):
            check_level_ceiling(Mock(), 'model', {}, actor=DEV)

    @patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': DEV})
    def test_phone_credit_exemption_keeps_session_identity(self):
        phone = Mock()
        self.assertEqual(billing.authorities(phone, Mock(), 'w', DEV, 1, maximum=None,
            conversation_id='c', number_hash='h', kind='manual', reason='', costs=(1, 2)), (None, None))
        approve = billing.manager_approval(phone, 'call')
        for value in (None, {'workspace_id': 'w', 'user_id': OTHER, 'state': 'live'},
                      {'workspace_id': 'w', 'user_id': DEV, 'state': 'completed'}):
            with patch.object(billing.store, 'call', return_value=value), self.assertRaises(AlphaError):
                approve(Mock(), 'w', DEV, 1, 100, Mock(), 'run')
        with patch.object(billing.store, 'call', return_value={'workspace_id': 'w', 'user_id': DEV, 'state': 'live'}):
            self.assertEqual(approve(Mock(), 'w', DEV, 1, 100, Mock(), 'run'), (None, {'phoneCallId': 'call'}))

    @patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': DEV})
    def test_credit_authorization_exemption_keeps_edit_permission(self):
        ideas = Mock()
        ideas.repository.transaction.return_value = nullcontext((Mock(), (1,), DEV))
        requests = CreditRequests(ideas)
        with patch('postriff_phase2.credit_requests.require') as require:
            self.assertIsNone(requests.authorize('w', 'session', 1, {}, 'turn'))
            require.assert_called_once_with(ideas._member.return_value, 'edit')
            ideas.ledger.credits.authorize.assert_not_called()
        ideas.repository.transaction.return_value = nullcontext((Mock(), (1,), DEV))
        with patch('postriff_phase2.credit_requests.require', side_effect=AlphaError('Forbidden', 403)), self.assertRaises(AlphaError):
            requests.authorize('w', 'session', 1, {}, 'turn')

    @patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': DEV, 'POSTRIFF_BUDGET_POLICY': 'paid-2026-09-24'})
    def test_reasoning_catalog_lifts_only_developer_quota_hint(self):
        runtime = ServerModelRuntime('synthetic', model='test/model', prices={'test/model': (1, 1)})
        with patch('postriff_phase2.model_runtime.level_quote', return_value={'ceilingUsd': 3, 'typicalUsd': 1}):
            ordinary = runtime.list_supported_reasoning('test/model', actor=OTHER)
            developer = runtime.list_supported_reasoning('test/model', actor=DEV)
        self.assertFalse(next(r for r in ordinary if r['id'] == 'thorough')['available'])
        self.assertTrue(next(r for r in developer if r['id'] == 'thorough')['available'])

    @patch.dict(os.environ, {'RAFII_AI_UNLIMITED_USER_IDS': DEV})
    def test_catalog_uses_verified_actor_not_request_identity(self):
        catalog = Mock(return_value={'models': []})
        verify = Mock(return_value=DEV)
        service = SimpleNamespace(ideas=SimpleNamespace(model_catalog=catalog), verify_session=verify)
        app = HostedApplication(service)
        self.assertEqual(invoke(app, 'GET', '/api/ideas/models')[0], 200)
        catalog.assert_called_with()
        verify.assert_not_called()
        self.assertEqual(invoke(app, 'GET', '/api/ideas/models', headers={'Authorization': 'Bearer ' + 'x' * 32})[0], 200)
        catalog.assert_called_with(actor=DEV)
        verify.return_value = OTHER
        self.assertEqual(invoke(app, 'GET', '/api/ideas/models', headers={'Authorization': 'Bearer ' + 'x' * 32, 'X-Developer': DEV})[0], 200)
        catalog.assert_called_with()


if __name__ == '__main__':
    unittest.main()
