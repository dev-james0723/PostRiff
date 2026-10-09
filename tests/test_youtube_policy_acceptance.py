"""Small policy-gate contracts. Real tenant/RLS/OAuth checks live in the CI PG group."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.youtube.model import READ, UPLOAD
from postriff_phase2.youtube.policy_acceptance import YouTubePolicyAcceptance
from postriff_phase2.youtube.provider import YouTubeProvider


class YouTubePolicyTests(unittest.TestCase):
    def setUp(self):
        self.oauth = SimpleNamespace(repository=Mock(), public_base_url='https://rafii.example', youtube_public_base_url=None)
        self.gate = YouTubePolicyAcceptance(self.oauth)
        self.provider = YouTubeProvider('synthetic-client', 'synthetic-secret', transport=Mock())
        self.policy = {'id': 'policy', 'privacy': {'revision': 'privacy-v1'}, 'terms': {'revision': 'terms-v1'}}

    def test_only_nonpublic_standard_read_only_is_compatible(self):
        for capability in ('identity', 'posts_read'):
            self.assertFalse(self.gate.required(self.provider, capability=capability, scopes=[READ]))
        for options in ({'force': True}, {'capability': 'publish'}, {'scopes': [READ, UPLOAD]}):
            self.assertTrue(self.gate.required(self.provider, **options))
        for attr, value in (('creator_enabled', True), ('authorization_lane', 'agentic'),
                            ('policy_public_binding', True), ('production_reviewed', True)):
            with self.subTest(attr=attr):
                provider = SimpleNamespace(id='youtube', **{attr: value})
                self.assertTrue(self.gate.required(provider))
        self.oauth.youtube_public_base_url = 'https://rafii.example'
        self.assertTrue(self.gate.required(self.provider))
        self.assertFalse(self.gate.required(SimpleNamespace(id='gmail'), force=True, scopes=['mail']))
        self.assertFalse(self.gate.required(SimpleNamespace(id='calendar'), force=True))
        self.assertTrue(self.gate.required(None, force=True))

    def test_generic_callback_pin_preserves_nonpublic_standard_read_only(self):
        self.provider.callback_origin = 'https://legacy.example'
        cursor = Mock()
        self.assertFalse(self.gate.required(self.provider, scopes=[READ]))
        self.gate.require_user(cursor, 'w', 'u', 'session', self.provider, scopes=[READ])
        cursor.execute.assert_not_called()
        self.oauth.youtube_public_base_url = 'https://rafii.example'
        self.assertTrue(self.gate.required(self.provider, scopes=[READ]))

    def test_legacy_read_does_not_touch_new_schema(self):
        cursor = Mock()
        self.assertIsNone(self.gate.require_user(cursor, 'w', 'u', 'session', self.provider, scopes=[READ]))
        self.gate.assert_connection('w', 'c', self.provider, scopes=[READ], cur=cursor)
        cursor.execute.assert_not_called()

    def test_no_schema_or_current_document_is_fail_closed_and_not_a_draft(self):
        for results in ([(None, None, None)], [('revision', 'acceptance', 'binding'), None]):
            cursor = Mock()
            cursor.fetchone.side_effect = results
            with self.assertRaises(AlphaError) as caught:
                self.gate._current(cursor)
            self.assertEqual(caught.exception.code, 'youtube_policy_not_ready')

    def test_only_registered_https_same_origin_documents_are_presented(self):
        for url in ('http://rafii.example/privacy', 'https://evil.example/privacy',
                    'https://person@rafii.example/privacy', 'https://rafii.example/privacy?draft=1'):
            with self.subTest(url=url):
                cursor = Mock()
                cursor.fetchone.side_effect = [('r', 'a', 'b'),
                    ('policy', 'p1', url, 'a'*64, 't1', 'https://rafii.example/terms', 'b'*64, 1)]
                with self.assertRaises(AlphaError) as caught:
                    self.gate._current(cursor)
                self.assertEqual(caught.exception.code, 'youtube_policy_not_ready')

    def test_pending_state_requires_same_current_policy_and_actual_holders_receipt(self):
        self.provider.creator_enabled = True
        self.gate._current = Mock(return_value=self.policy)
        self.gate._receipt = Mock(return_value={'id': 'actual-user-receipt'})
        for snapshot in (None, {'policyId': 'old', 'receiptId': 'actual-user-receipt'},
                         {'policyId': 'policy', 'receiptId': 'another-user-receipt'}):
            with self.subTest(snapshot=snapshot), self.assertRaises(AlphaError) as caught:
                self.gate.require_pending(Mock(), 'w', 'actual-user', 'session', self.provider, [READ],
                    {'policyAcceptance': snapshot})
            self.assertEqual(caught.exception.code, 'youtube_policy_acceptance_required')
        snapshot = {'policyId': 'policy', 'receiptId': 'actual-user-receipt'}
        self.assertEqual(self.gate.require_pending(Mock(), 'w', 'actual-user', 'session', self.provider,
            [READ], {'policyAcceptance': snapshot}), snapshot)

    def test_spoofed_receipt_identity_timestamp_and_api_tokens_cannot_accept(self):
        valid = {'policyId': 'p', 'privacyRevision': 'p1', 'termsRevision': 't1', 'confirmed': True}
        for extra in ('userId', 'workspaceId', 'receiptId', 'acceptedAt', 'approved'):
            with self.subTest(extra=extra), self.assertRaises(AlphaError):
                self.gate.accept('w', 'session', {**valid, extra: 'spoofed'})
        with self.assertRaises(AlphaError) as caught:
            self.gate.accept('w', 'prt_synthetic', valid)
        self.assertEqual(caught.exception.code, 'youtube_policy_interactive_required')
        self.oauth.repository.transaction.assert_not_called()

    def test_every_provider_dispatch_rechecks_but_revocation_remains_available(self):
        self.gate.assert_connection = Mock()
        grant = {'scopes': [READ, UPLOAD], 'authorizationGeneration': 'generation',
                 '_youtubePolicyContext': {'workspace': 'w', 'connection': 'c', 'force': True}}
        routed = self.gate.guarded_provider(self.provider, grant)
        routed.transport('GET', self.provider.API + '/channels')
        self.gate.assert_connection.assert_called_once()
        self.gate.assert_connection.side_effect = self.gate._acceptance_required()
        before = self.provider.transport.call_count
        with self.assertRaises(AlphaError):
            routed.transport('GET', self.provider.API + '/videos')
        self.assertEqual(self.provider.transport.call_count, before)
        routed.transport('POST', self.provider.REVOKE)
        self.assertEqual(self.provider.transport.call_count, before + 1)


if __name__ == '__main__':
    unittest.main()
