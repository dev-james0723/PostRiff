"""Offline regression tests. Mock PASS cannot establish Pinterest Trial access."""
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from postriff_alpha.domain import AlphaError
from postriff_phase2.wave3_connectors import PinterestProvider
from test_hosted_wave1_connectors import Wire, ok


class PinterestTrialReadiness(unittest.TestCase):
    def provider(self, responses=(), sandbox=True, client='1615884'):
        return PinterestProvider(client, 'MOCK-SECRET', sandbox=sandbox, transport=Wire(list(responses)))

    def grant(self, provider):
        return provider._grant({'access_token': 'MOCK-AT', 'refresh_token': 'MOCK-RT',
                                'scope': 'user_accounts:read boards:read', 'expires_in': 3600})

    def test_readonly_trial_mount_requires_sandbox(self):
        values = {"POSTRIFF_OAUTH_PINTEREST_CLIENT_ID": "1615884", "POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET": "MOCK-SECRET",
                  "POSTRIFF_PINTEREST_TRIAL_READONLY": "1"}
        adapter, diagnostic = PinterestProvider.mount(values, transport=Wire([]))
        self.assertIsNone(adapter)
        self.assertEqual(diagnostic['configurationState'], 'invalid_configuration')

    def test_readonly_trial_mount_records_reads_and_denies_pin_post(self):
        wire = Wire([ok({'username': 'MOCK_HANDLE', 'id': '1234567'})])
        values = {"POSTRIFF_OAUTH_PINTEREST_CLIENT_ID": "1615884", "POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET": "MOCK-SECRET",
                  "POSTRIFF_PINTEREST_TRIAL_READONLY": "1", "POSTRIFF_PINTEREST_SANDBOX": "true",
                  "POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID": "00000000-0000-0000-0000-000000000501",
                  "POSTRIFF_PINTEREST_TRIAL_ACTOR_ID": "00000000-0000-0000-0000-000000000502",
                  "POSTRIFF_PINTEREST_TRIAL_USERNAME": "MOCK_HANDLE",
                  "POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT": str(int(time.time()) + 3600)}
        adapter, _ = PinterestProvider.mount(values, transport=wire)
        grant = self.grant(adapter)
        with patch('builtins.print') as output:
            adapter.identity(grant['accessToken'])
            self.assertEqual(output.call_count, 2)
            self.assertNotIn('MOCK-AT', str(output.call_args_list))
            with self.assertRaises(AlphaError):
                adapter.api(grant['accessToken'], 'POST', '/v5/pins', body={})
        self.assertEqual(len(wire.calls), 1)

    def test_exact_identity_consent_and_callback(self):
        p = self.provider()
        redirect = 'https://isolated.example/api/oauth/pinterest/callback'
        url = p.authorize_url(redirect, 'MOCK-STATE', 'unused', p.capability_scopes('identity'))
        self.assertEqual(parse_qs(urlparse(url).query), {'client_id': ['1615884'], 'redirect_uri': [redirect],
            'response_type': ['code'], 'scope': ['user_accounts:read'], 'state': ['MOCK-STATE']})
        self.assertEqual(set(p.capability_scopes('publish')), {'user_accounts:read', 'boards:read', 'pins:read', 'pins:write'})

    def test_access_and_refresh_deny_other_host_or_app_before_network(self):
        p = self.provider()
        grant = self.grant(p)
        for target in [self.provider(sandbox=False), self.provider(client='9999999')]:
            with self.subTest(host=target.environment, client=target.client_id):
                with self.assertRaises(AlphaError):
                    target.identity(grant['accessToken'])
                with self.assertRaises(AlphaError):
                    target.refresh(grant['refreshToken'])
                self.assertIsNone(target.inspect_scopes(grant['accessToken']))
                self.assertEqual(target.transport.calls, [])

    def test_legacy_provenance_missing_requires_reconsent(self):
        p = self.provider()
        with self.assertRaises(AlphaError):
            p.identity(json.dumps({'v': 1, 'at': 'LEGACY', 'scope': ['user_accounts:read']}))
        with self.assertRaises(AlphaError):
            p.refresh('LEGACY-RT')
        self.assertEqual(p.transport.calls, [])

    def test_malformed_grants_are_rejected_without_token_disclosure(self):
        p = self.provider()
        base = {'access_token': 'MOCK-SECRET-AT', 'scope': 'user_accounts:read'}
        for overrides in [{'access_token': ''}, {'access_token': 123}, {'access_token': 'bad\nheader'},
                          {'scope': None}, {'scope': ''}, {'refresh_token': ''}, {'refresh_token': 42},
                          {'expires_in': -1}, {'expires_in': True}, {'expires_in': '3600'}]:
            with self.subTest(overrides=overrides), self.assertRaises(AlphaError) as caught:
                p._grant({**base, **overrides})
            self.assertNotIn('MOCK-SECRET-AT', str(caught.exception))

    def test_refresh_rotation_and_retention_preserve_binding(self):
        p = self.provider([ok({'access_token': 'NEW', 'scope': 'user_accounts:read', 'refresh_token': 'ROTATED'}),
                           ok({'access_token': 'NEWER', 'scope': 'user_accounts:read'})])
        old = self.grant(p)
        rotated = p.refresh(old['refreshToken'])
        retained = p.refresh(rotated['refreshToken'])
        self.assertEqual(json.loads(rotated['refreshToken'])['rt'], 'ROTATED')
        self.assertEqual(retained['refreshToken'], rotated['refreshToken'])
        self.assertEqual([c['form']['refresh_token'] for c in p.transport.calls], ['MOCK-RT', 'ROTATED'])
        self.assertTrue(all(c['url'] == p.SANDBOX + '/v5/oauth/token' for c in p.transport.calls))

    def test_empty_sandbox_pages_keep_following_bookmarks(self):
        p = self.provider([ok({'items': [], 'bookmark': 'NEXT'}),
                           ok({'items': [{'id': '1234567', 'name': 'Test board'}]})])
        boards = p.destinations(self.grant(p)['accessToken'])
        self.assertEqual([b['id'] for b in boards], ['1234567'])
        self.assertIn('bookmark=NEXT', p.transport.calls[1]['url'])

    def test_repeated_bookmark_fails_closed(self):
        p = self.provider([ok({'items': [], 'bookmark': 'LOOP'})] * 2)
        with self.assertRaises(AlphaError):
            p.destinations(self.grant(p)['accessToken'])
        self.assertEqual(len(p.transport.calls), 2)

    def test_page_limit_does_not_return_a_partial_board_list(self):
        p = self.provider([ok({'items': [{'id': '1234567'}], 'bookmark': 'MORE'})])
        p.MAX_BOARD_PAGES = 1
        with self.assertRaises(AlphaError):
            p.destinations(self.grant(p)['accessToken'])

    def test_unauthorized_denied_rate_limited_boards_do_not_retry(self):
        for status in [401, 403, 429]:
            p = self.provider([ok({'message': 'PRIVATE PROVIDER DETAIL'}, status)])
            with self.subTest(status=status), self.assertRaises(AlphaError) as caught:
                p.destinations(self.grant(p)['accessToken'])
            self.assertNotIn('PRIVATE PROVIDER DETAIL', str(caught.exception))
            self.assertEqual(len(p.transport.calls), 1)


if __name__ == '__main__':
    unittest.main()
