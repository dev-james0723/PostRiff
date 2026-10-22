"""Synthetic provider contracts; no live Mastodon/account acceptance claimed."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.mastodon_management import MastodonManagement


class InteractionReadbackTests(unittest.TestCase):
    def receipt(self, action, lookup, scopes=('read:statuses', 'read:follows'), write=None):
        provider = SimpleNamespace(api=Mock(return_value=lookup))
        preview = {'action': action, 'targetId': '42', 'body': {}, 'accountId': '100@mastodon.social'}
        result = MastodonManagement._receipt(provider, {'instance': 'mastodon.social'}, preview,
            write or {'status': 200, 'body': {'id': '42'}}, granted_scopes=scopes)
        return result, provider.api

    def test_six_status_actions_require_exact_independent_state(self):
        for action, field, value in [('favourite', 'favourited', True), ('unfavourite', 'favourited', False),
                ('reblog', 'reblogged', True), ('unreblog', 'reblogged', False),
                ('bookmark', 'bookmarked', True), ('unbookmark', 'bookmarked', False)]:
            with self.subTest(action=action):
                result, api = self.receipt(action, {'status': 200, 'body': {'id': '42', field: value,
                    'content': 'PRIVATE_STATUS_CONTENT_NOT_PERSISTED'}})
                self.assertEqual(result['state'], 'verified')
                self.assertEqual(result['verification'], 'provider_status_lookup')
                self.assertEqual(result['readback']['observed'], {field: value})
                api.assert_called_once_with({'instance': 'mastodon.social'}, 'GET', '/api/v1/statuses/42')
                self.assertNotIn('PRIVATE_STATUS_CONTENT', json.dumps(result))

    def test_response_acceptance_is_not_readback_proof(self):
        for body in ({'id': '42'}, {'id': '999', 'favourited': True}, {'id': 42, 'favourited': True},
                     {'id': '42', 'favourited': 1}, {'id': '42', 'favourited': 'true'},
                     {'id': '42', 'favourited': False}, []):
            with self.subTest(body=body):
                result, _ = self.receipt('favourite', {'status': 200, 'body': body},
                    write={'status': 200, 'body': {'id': '42', 'favourited': True}})
                self.assertEqual(result['state'], 'accepted')
                self.assertEqual(result['verification'], 'unavailable')
                self.assertNotEqual(result['readback']['state'], 'confirmed')

    def test_write_only_authority_does_not_trigger_an_unauthorized_read(self):
        for action, granted, required in [('favourite', ['write:favourites'], 'read:statuses'),
                ('mute', ['write:mutes', 'read:mutes'], 'read:follows'),
                ('block', ['write:blocks', 'read:blocks'], 'read:follows')]:
            with self.subTest(action=action):
                result, api = self.receipt(action, {'status': 200, 'body': {}}, scopes=granted)
                self.assertEqual(result['state'], 'accepted')
                self.assertEqual(result['readback']['state'], 'permission_required')
                self.assertEqual(result['readback']['requiredScope'], required)
                api.assert_not_called()
        result, api = self.receipt('bookmark', {'status': 200, 'body': {'id': '42', 'bookmarked': True}}, scopes=['read'])
        self.assertEqual(result['state'], 'verified'); self.assertEqual(api.call_count, 1)

    def test_relationship_proof_matches_only_requested_account_and_boolean(self):
        for action, fields in [('mute', {'muting': True}), ('unmute', {'muting': False}),
                ('block', {'blocking': True}), ('unblock', {'blocking': False}),
                ('follow', {'following': True, 'requested': False}),
                ('unfollow', {'following': False, 'requested': False})]:
            with self.subTest(action=action):
                result, api = self.receipt(action, {'status': 200, 'body': [{'id': '42', **fields,
                    'note': 'PRIVATE_RELATIONSHIP_NOTE_NOT_PERSISTED'}]})
                self.assertEqual(result['state'], 'verified')
                self.assertEqual(result['verification'], 'provider_relationship_lookup')
                self.assertEqual(result['readback']['observed'], fields)
                api.assert_called_once_with({'instance': 'mastodon.social'}, 'GET', '/api/v1/accounts/relationships?id%5B%5D=42')
                self.assertNotIn('PRIVATE_RELATIONSHIP_NOTE', json.dumps(result))
        for rows in ([{'id': '43', 'blocking': True}], [{'id': '42', 'blocking': True}] * 2,
                {'id': '42', 'blocking': True}, [{'id': '42', 'blocking': 1}], [], [{'id': '42'}]):
            with self.subTest(rows=rows):
                result, _ = self.receipt('block', {'status': 200, 'body': rows})
                self.assertEqual(result['state'], 'accepted')
                self.assertEqual(result['verification'], 'unavailable')

    def test_follow_request_is_pending_until_target_approves(self):
        result, _ = self.receipt('follow', {'status': 200, 'body': [{'id': '42', 'following': False, 'requested': True}]})
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['readback']['state'], 'pending')
        self.assertTrue(result['followRequestPending'])
        for fields in ({'following': False}, {'following': False, 'requested': True},
                {'following': True, 'requested': False}):
            result, _ = self.receipt('unfollow', {'status': 200, 'body': [{'id': '42', **fields}]})
            self.assertEqual(result['state'], 'accepted')

    def test_failed_or_rate_limited_read_preserves_known_write_acceptance_without_retry(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                result, api = self.receipt('favourite', {'status': status, 'body': {}})
                self.assertEqual(result['state'], 'accepted')
                self.assertEqual(result['readback']['httpStatus'], status)
                self.assertEqual(api.call_count, 1)
        for error in (AlphaError('synthetic timeout', 503), TimeoutError('synthetic'), OSError('synthetic')):
            provider = SimpleNamespace(api=Mock(side_effect=error))
            result = MastodonManagement._receipt(provider, {'instance': 'mastodon.social'},
                {'action': 'favourite', 'targetId': '42'}, {'status': 200, 'body': {'id': '42'}},
                granted_scopes=['read:statuses'])
            self.assertEqual(result['state'], 'accepted')
            self.assertEqual(result['readback']['state'], 'unavailable')
            self.assertEqual(provider.api.call_count, 1)

    def test_rejected_or_uncertain_write_never_reads(self):
        for status in (401, 403, 422, 429, 500, 503):
            result, api = self.receipt('favourite', {'status': 200, 'body': {'id': '42', 'favourited': True}},
                write={'status': status, 'body': {}})
            self.assertIn(result['state'], ('rejected', 'uncertain'))
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
