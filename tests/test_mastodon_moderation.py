"""Native account moderation contracts with injected data only; no live effects."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_management import MastodonManagement, action_spec, READS

CAPS = {'version': '4.4.0'}


class ModerationTests(unittest.TestCase):
    def test_report_is_exact_bounded_and_not_forwarded_by_default(self):
        method, path, body, scopes, right = action_spec('report_account',
            {'targetId': '99', 'reportComment': 'Reviewed reason', 'reportStatusIds': ['123']}, CAPS, now=1)
        self.assertEqual((method, path, right), ('POST', '/api/v1/reports', 'moderate'))
        self.assertEqual(body, {'account_id': '99', 'status_ids': ['123'], 'comment': 'Reviewed reason', 'forward': False, 'category': 'other'})
        self.assertEqual(scopes, ('write:reports', 'read:statuses'))

    def test_report_rejects_unsafe_targets_payloads_and_unsupported_categories(self):
        for changes in ({'targetId': 'https://evil.invalid'}, {'reportForward': 'true'},
                        {'reportCategory': 'legal'}, {'reportCategory': 'violation'},
                        {'reportStatusIds': ['1', '1']}, {'reportStatusIds': ['https://evil.invalid']},
                        {'reportComment': 'x' * 1001}):
            with self.subTest(changes=changes), self.assertRaises(AlphaError):
                action_spec('report_account', {'targetId': '99', 'reportComment': 'Reason', **changes}, CAPS, now=1)

    def test_filter_create_update_delete_use_only_official_account_endpoints(self):
        settings = {'title': 'Reviewed filter', 'context': ['public', 'home'],
                    'keywords_attributes': [{'keyword': 'example', 'whole_word': True}]}
        method, path, body, scopes, right = action_spec('filter_create', {'filter': settings}, CAPS, now=1)
        self.assertEqual((method, path, right), ('POST', '/api/v2/filters', 'moderate'))
        self.assertEqual(body['context'], ['home', 'public']); self.assertEqual(body['filter_action'], 'warn')
        self.assertEqual(scopes, ('read:filters', 'write:filters'))
        update = action_spec('filter_update', {'targetId': '7', 'filter': {'keywords_attributes': [
            {'id': '8', '_destroy': True}, {'id': '9', 'keyword': 'new', 'whole_word': False}]}}, CAPS, now=1)
        self.assertEqual(update[:2], ('PUT', '/api/v2/filters/7'))
        self.assertEqual(action_spec('filter_delete', {'targetId': '7'}, CAPS, now=1)[:2], ('DELETE', '/api/v2/filters/7'))
        self.assertEqual(READS['filters'], ('/api/v2/filters', ('read:filters',)))

    def test_filters_fail_closed_on_version_unknown_fields_and_ambiguous_changes(self):
        settings = {'title': 'Filter', 'context': ['home']}
        for value in ({**settings, 'admin': True}, {**settings, 'context': []},
                      {**settings, 'context': ['home', 'home']}, {**settings, 'expires_in': None},
                      {**settings, 'expires_in': True}, {**settings, 'keywords_attributes': [{'keyword': 'x', 'whole_word': 'true'}]}):
            with self.subTest(value=value), self.assertRaises(AlphaError):
                action_spec('filter_create', {'filter': value}, CAPS, now=1)
        with self.assertRaises(AlphaError):
            action_spec('filter_create', {'filter': settings}, {'version': '3.5.0'}, now=1)
        with self.assertRaises(AlphaError):
            action_spec('filter_create', {'filter': {**settings, 'filter_action': 'blur'}}, {'version': '4.2.0'}, now=1)
        with self.assertRaises(AlphaError):
            action_spec('filter_update', {'targetId': '7', 'filter': {'keywords_attributes': [
                {'id': '8', '_destroy': True}, {'id': '8', 'keyword': 'new'}]}}, CAPS, now=1)

    def test_actor_approval_admission_precedes_provider_io(self):
        manager = object.__new__(MastodonManagement)
        manager._approved_action = Mock(side_effect=AlphaError('No exact approval', 403))
        manager._grant = Mock()
        with self.assertRaises(AlphaError):
            manager.execute('w', 'actor', 'c', 'a', {'confirmed': True, 'digest': 'exact'})
        manager._grant.assert_not_called()

    def test_report_receipt_is_filing_not_moderator_enforcement(self):
        preview = {'action': 'report_account', 'body': {'account_id': '99'}, 'path': '/api/v1/reports'}
        result = MastodonManagement._receipt(SimpleNamespace(), {'instance': 'social.example'}, preview,
            {'status': 200, 'body': {'id': '77', 'target_account': {'id': '99'}, 'forwarded': False, 'action_taken': False}})
        self.assertEqual(result['state'], 'accepted'); self.assertTrue(result['reportFiled'])
        self.assertIn('not moderator enforcement', result['moderationOutcome'])
        wrong = MastodonManagement._receipt(SimpleNamespace(), {'instance': 'social.example'}, preview,
            {'status': 200, 'body': {'id': '77', 'target_account': {'id': '100'}}})
        self.assertEqual(wrong['state'], 'uncertain')

    def test_filter_mutation_receipt_checks_target_and_deletion_lookup(self):
        provider = SimpleNamespace(api=Mock(return_value={'status': 404}))
        preview = {'action': 'filter_delete', 'targetId': '7', 'path': '/api/v2/filters/7', 'body': {}}
        result = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview, {'status': 200, 'body': {}})
        self.assertEqual(result['state'], 'verified')
        preview['action'] = 'filter_update'
        wrong = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview, {'status': 200, 'body': {'id': '8'}})
        self.assertEqual(wrong['state'], 'uncertain')
