"""Native account moderation contracts with injected data only; no live effects."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_management import MastodonManagement, action_spec, READS
from postriff_phase2.mastodon_moderation import report_rules
from postriff_phase2.contracts import digest

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
                        {'reportCategory': 'unknown'}, {'reportCategory': 'violation'},
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
                      {**settings, 'context': ['home', 'home']}, {**settings, 'expires_in': ''},
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

    def test_report_categories_follow_server_versions_and_exact_rule_choice(self):
        payload = {'targetId': '99', 'reportComment': 'Reviewed reason'}
        legal = action_spec('report_account', {**payload, 'reportCategory': 'legal'}, CAPS, now=1)
        self.assertEqual(legal[2]['category'], 'legal')
        self.assertNotIn('rule_ids', legal[2])
        with self.assertRaises(AlphaError):
            action_spec('report_account', {**payload, 'reportCategory': 'legal'}, {'version': '4.1.9'}, now=1)
        violation = action_spec('report_account', {**payload, 'reportRuleIds': ['8', '7']}, CAPS, now=1)
        self.assertEqual(violation[2]['category'], 'violation')
        self.assertEqual(violation[2]['rule_ids'], ['8', '7'])
        self.assertEqual(violation[3], ('write:reports',))
        for changes in ({'reportRuleIds': ['7'], 'reportCategory': 'spam'},
                        {'reportRuleIds': ['7'], 'reportCategory': 'legal'},
                        {'reportRuleIds': ['7', '7']}, {'reportRuleIds': [7]},
                        {'reportRuleIds': ['https://evil.invalid']}, {'reportRuleIds': ['7'], 'reportCategory': 'other'}):
            with self.subTest(changes=changes), self.assertRaises(AlphaError):
                action_spec('report_account', {**payload, **changes}, CAPS, now=1)
        with self.assertRaises(AlphaError):
            action_spec('report_account', {**payload, 'reportRuleIds': ['7']}, {'version': '3.4.9'}, now=1)
        legacy = action_spec('report_account', payload, {'version': '2.3.0'}, now=1)
        self.assertNotIn('category', legacy[2])

    def test_report_rule_snapshot_uses_requested_instance_ids_and_text(self):
        rules = [{'id': '7', 'text': 'No harassment', 'hint': 'Extra server metadata'},
                 {'id': '8', 'text': 'Mark sensitive media'}]
        expected = [{'id': '8', 'text': 'Mark sensitive media'}, {'id': '7', 'text': 'No harassment'}]
        self.assertEqual(report_rules(rules, ['8', '7']), expected)
        self.assertEqual(report_rules(list(reversed(rules)), ['8', '7']), expected)
        for rows in ({'rules': rules}, [], [{'id': '7', 'text': None}],
                     [{'id': '7', 'text': 'One'}, {'id': '7', 'text': 'Two'}],
                     [{'id': '7', 'text': ''}], [{'id': '7', 'text': 'x' * 4097}]):
            with self.subTest(rows=rows), self.assertRaises(AlphaError):
                report_rules(rows, ['7'])
        self.assertEqual(READS['rules'], ('/api/v1/instance/rules', ()))

    def test_filter_null_is_an_explicit_clear_and_omission_keeps_expiry(self):
        clear = action_spec('filter_update', {'targetId': '7', 'filter': {'expires_in': None}}, CAPS, now=1)
        keep = action_spec('filter_update', {'targetId': '7', 'filter': {'title': 'Filter'}}, CAPS, now=1)
        self.assertEqual(clear[:3], ('PUT', '/api/v2/filters/7', {'expires_in': None}))
        self.assertNotIn('expires_in', keep[2])
        self.assertNotEqual(digest({'expires_in': None}), digest({}))
        create = action_spec('filter_create', {'filter': {'title': 'Filter', 'context': ['home'], 'expires_in': None}}, CAPS, now=1)
        self.assertIsNone(create[2]['expires_in'])
        for expiry in (False, 0, -1, 59, 31536001, '60', 'null', 60.5):
            with self.subTest(expiry=expiry), self.assertRaises(AlphaError):
                action_spec('filter_update', {'targetId': '7', 'filter': {'expires_in': expiry}}, CAPS, now=1)

    def test_filter_expiry_clear_requires_explicit_null_in_independent_lookup(self):
        preview = {'action': 'filter_update', 'targetId': '7', 'path': '/api/v2/filters/7', 'body': {'expires_in': None}}
        provider = SimpleNamespace(api=Mock(return_value={'status': 200, 'body': {'id': '7', 'expires_at': None}}))
        result = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview,
                                            {'status': 200, 'body': {'id': '7', 'expires_at': None}})
        self.assertTrue(result['expiryCleared'])
        self.assertEqual(result['expiryVerification'], 'provider_lookup')
        provider.api.assert_called_once_with({'instance': 'social.example'}, 'GET', '/api/v2/filters/7')
        for lookup in ({'status': 200, 'body': {'id': '7'}},
                       {'status': 200, 'body': {'id': '8', 'expires_at': None}},
                       {'status': 200, 'body': {'id': '7', 'expires_at': '2027-01-01T00:00:00Z'}},
                       {'status': 429, 'body': {}}):
            provider.api.return_value = lookup
            result = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview,
                                                {'status': 200, 'body': {'id': '7'}})
            self.assertIsNone(result['expiryCleared'])
            self.assertEqual(result['state'], 'accepted')

    def test_report_receipt_cannot_silently_downgrade_approved_category_or_rules(self):
        preview = {'action': 'report_account', 'path': '/api/v1/reports',
                   'body': {'account_id': '99', 'category': 'violation', 'rule_ids': ['7', '8']}}
        filed = {'id': '77', 'target_account': {'id': '99'}, 'category': 'violation', 'rule_ids': ['8', '7']}
        result = MastodonManagement._receipt(SimpleNamespace(), {'instance': 'social.example'}, preview, {'status': 200, 'body': filed})
        self.assertTrue(result['reportFiled'])
        for changes in ({'category': 'other'}, {'rule_ids': None}, {'rule_ids': ['7']},
                        {'rule_ids': [7, 8]}, {'rule_ids': ['7', '8', '8']}):
            with self.subTest(changes=changes):
                result = MastodonManagement._receipt(SimpleNamespace(), {'instance': 'social.example'}, preview,
                                                    {'status': 200, 'body': {**filed, **changes}})
                self.assertEqual(result['state'], 'uncertain')
                self.assertNotIn('reportFiled', result)
        preview['body'] = {'account_id': '99', 'category': 'legal'}
        result = MastodonManagement._receipt(SimpleNamespace(), {'instance': 'social.example'}, preview,
                                            {'status': 200, 'body': {**filed, 'category': 'legal'}})
        self.assertTrue(result['reportFiled'])

    def test_filter_mutation_receipt_checks_target_and_deletion_lookup(self):
        provider = SimpleNamespace(api=Mock(return_value={'status': 404}))
        preview = {'action': 'filter_delete', 'targetId': '7', 'path': '/api/v2/filters/7', 'body': {}}
        result = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview, {'status': 200, 'body': {}})
        self.assertEqual(result['state'], 'verified')
        preview['action'] = 'filter_update'
        wrong = MastodonManagement._receipt(provider, {'instance': 'social.example'}, preview, {'status': 200, 'body': {'id': '8'}})
        self.assertEqual(wrong['state'], 'uncertain')
