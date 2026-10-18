"""Synthetic verified-claim controls; no Supabase, database, MFA ceremony or network."""
import base64
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.hosted_identity import verified_auth_time
from postriff_phase2.permissions import STEP_UP_WINDOW

PRINCIPAL = '00000000-0000-0000-0000-000000000001'
NOW = 1_800_000_000


def token(**claims):
    payload = {'sub': PRINCIPAL, **claims}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return 'synthetic.' + encoded + '.not-a-real-signature'


def repository():
    repo = PostgresWorkspaceRepository.__new__(PostgresWorkspaceRepository)
    repo.verify_session = SimpleNamespace(auth_time=verified_auth_time)
    repo.clock = lambda: NOW
    return repo


class VerifiedSessionFreshness(unittest.TestCase):
    def test_refreshed_token_cannot_reauthorize_sensitive_action(self):
        refreshed = token(iat=NOW, amr=[{'method': 'oauth', 'timestamp': NOW - 3600}])
        with patch('time.time', return_value=NOW), self.assertRaises(AlphaError) as rejected:
            repository().assert_fresh(refreshed, PRINCIPAL)
        self.assertEqual((rejected.exception.status, rejected.exception.code), (403, 'step_up_required'))

    def test_iat_without_signed_method_is_stale(self):
        with patch('time.time', return_value=NOW):
            self.assertEqual(verified_auth_time(token(iat=NOW), PRINCIPAL), 0)
            with self.assertRaises(AlphaError):
                repository().assert_fresh(token(iat=NOW), PRINCIPAL)

    def test_recent_existing_signin_methods_still_pass(self):
        for method in ('oauth', 'password', 'otp', 'passkey', 'totp', 'mfa/webauthn'):
            with self.subTest(method=method), patch('time.time', return_value=NOW):
                recent = token(iat=NOW, amr=[{'method': method, 'timestamp': NOW - 30}])
                self.assertEqual(verified_auth_time(recent, PRINCIPAL), NOW - 30)
                repository().assert_fresh(recent, PRINCIPAL)

    def test_new_mfa_is_fresh_but_a_token_refresh_does_not_change_that_time(self):
        amr = [{'method': 'password', 'timestamp': NOW - 3600}, {'method': 'totp', 'timestamp': NOW - 30}]
        with patch('time.time', return_value=NOW):
            before = verified_auth_time(token(iat=NOW - 30, amr=amr), PRINCIPAL)
            after = verified_auth_time(token(iat=NOW, amr=amr), PRINCIPAL)
        self.assertEqual(before, NOW - 30)
        self.assertEqual(after, before)

    def test_malformed_nonfinite_bool_or_future_method_time_is_stale(self):
        bad_amr = [None, {}, 'oauth', [], [{}], [{'method': 'oauth', 'timestamp': True}],
                   [{'method': 'oauth', 'timestamp': '1800000000'}],
                   [{'method': 'oauth', 'timestamp': float('nan')}],
                   [{'method': 'oauth', 'timestamp': float('inf')}],
                   [{'method': 'oauth', 'timestamp': 10**1000}],
                   [{'method': 'oauth', 'timestamp': -1}],
                   [{'method': 'oauth', 'timestamp': NOW + 1}],
                   [{'method': '', 'timestamp': NOW}]]
        for amr in bad_amr:
            with self.subTest(amr=amr), patch('time.time', return_value=NOW):
                self.assertEqual(verified_auth_time(token(iat=NOW, amr=amr), PRINCIPAL), 0)
                with self.assertRaises(AlphaError):
                    repository().assert_fresh(token(iat=NOW, amr=amr), PRINCIPAL)

    def test_the_existing_600_second_window_is_preserved(self):
        self.assertEqual(STEP_UP_WINDOW, 600)
        with patch('time.time', return_value=NOW):
            repository().assert_fresh(token(iat=NOW, amr=[{'method': 'oauth', 'timestamp': NOW - 600}]), PRINCIPAL)
            with self.assertRaises(AlphaError):
                repository().assert_fresh(token(iat=NOW, amr=[{'method': 'oauth', 'timestamp': NOW - 601}]), PRINCIPAL)

    def test_subject_mismatch_remains_unauthorized(self):
        with patch('time.time', return_value=NOW), self.assertRaises(AlphaError) as rejected:
            verified_auth_time(token(sub='other', iat=NOW, amr=[{'method': 'oauth', 'timestamp': NOW}]), PRINCIPAL)
        self.assertEqual(rejected.exception.status, 401)


if __name__ == '__main__':
    unittest.main()
