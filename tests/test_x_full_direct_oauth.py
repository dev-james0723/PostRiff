"""Synthetic Direct-only authorization gates; no provider acceptance claims."""
import unittest
from urllib.parse import parse_qs, urlparse
import test_x_connect_only_p0 as connect_fixture
from test_x_connect_only_p0 import PILOT, CONFIG
from test_hosted_wave1_connectors import Wire
from postriff_alpha.domain import AlphaError
from postriff_phase2.channels import assisted_matrix, direct_only_matrix
from postriff_phase2.oauth import OAuthService

PUBLIC = {
    **CONFIG,
    'POSTRIFF_OAUTH_X_PUBLIC_CONNECT_ENABLED': 'true',
    'POSTRIFF_OAUTH_X_CUSTOMER_ACCESS_APPROVED': 'true',
    'POSTRIFF_OAUTH_X_REVIEWED': 'true',
    'POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS': '3',
    'POSTRIFF_OAUTH_X_DIRECT_MANAGEMENT_ENABLED': 'true',
}

class DirectOAuth(unittest.TestCase):
    def service(self, values):
        fixture = connect_fixture.ConnectP0()
        service = fixture.service(values, Wire([]))
        return fixture, service

    def test_public_customer_start_has_no_pilot_workspace_requirement(self):
        fixture, service = self.service(PUBLIC)
        started = service.start('workspace', 'session', 'x', 'identity')
        self.assertEqual(started['capability'], 'identity')
        self.assertEqual(service.providers['x'].customer_connect_workspaces, frozenset())
        self.assertEqual(fixture.wire.calls, [])
        catalog = {p['id']: p for p in service.provider_catalog()}
        self.assertTrue(catalog['x']['publicConnectionReady'])
        self.assertFalse(catalog['x']['liveVerified'])

    def test_pilot_never_advertises_public_even_with_owner_review(self):
        _, service = self.service({**PILOT, 'POSTRIFF_OAUTH_X_REVIEWED': 'true'})
        catalog = {p['id']: p for p in service.provider_catalog()}
        self.assertTrue(catalog['x']['connectReady'])
        self.assertFalse(catalog['x']['publicConnectionReady'])

    def test_progressive_publish_uses_official_scopes_and_pkce(self):
        fixture, service = self.service(PUBLIC)
        started = service.start('workspace', 'session', 'x', 'publish')
        query = parse_qs(urlparse(started['authorizeUrl']).query)
        self.assertEqual(set(query['scope'][0].split()), set(service.providers['x'].capability_scopes('publish')))
        self.assertIn('tweet.write', query['scope'][0])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(fixture.wire.calls, [])
        with self.assertRaises(AlphaError):
            service.start('workspace', 'session', 'x', 'unofficial_browser_publish')
        self.assertEqual(fixture.wire.calls, [])

    def test_public_flags_do_not_replace_required_entitlement_or_cost_allowance(self):
        for change in (
            {'POSTRIFF_OAUTH_X_CUSTOMER_ACCESS_APPROVED': 'false'},
            {'POSTRIFF_OAUTH_X_REVIEWED': 'false'},
            {'POSTRIFF_OAUTH_X_MAX_DAILY_IDENTITY_CALLS': '0'},
        ):
            fixture, service = self.service({**PUBLIC, **change})
            with self.assertRaises(AlphaError):
                service.start('workspace', 'session', 'x', 'identity')
            self.assertEqual(fixture.wire.calls, [])

    def test_scopes_alone_never_produce_direct_management(self):
        _, service = self.service(PUBLIC)
        adapter = service.providers['x']
        adapter.publishing_release_enabled = True
        adapter.implemented_capabilities = frozenset({'publish', 'schedule'})
        granted = list(adapter.capability_scopes('publish'))
        adapter.cost_admission_ready = False
        matrix = OAuthService._capabilities(adapter, 'publish', granted, [], 100)
        self.assertEqual(matrix['publish']['level'], 'Unsupported')
        self.assertEqual(matrix['publish']['reasonCode'], 'x_app_access_unverified')
        adapter.x_access_evidence = {'entitlements': frozenset({'x_api_v2'}),
            'expiresAt': 200, 'evidenceRef': 'synthetic:unit-test', 'publicCustomerVerified': False}
        matrix = OAuthService._capabilities(adapter, 'publish', granted, [], 100, workspace_id='workspace')
        self.assertEqual(matrix['publish']['reasonCode'], 'x_cost_admission_required')
        self.assertNotIn('Assisted', str(matrix))
        adapter.cost_admission_ready = True
        matrix = OAuthService._capabilities(adapter, 'publish', granted, [], 100, workspace_id='workspace')
        self.assertEqual(matrix['publish']['reasonCode'], 'x_cost_admission_required')
        adapter.cost_capability_ready = lambda ws, cap: ws == 'workspace' and cap in ('publish', 'schedule')
        matrix = OAuthService._capabilities(adapter, 'publish', granted, [], 100, workspace_id='workspace')
        self.assertEqual(matrix['publish']['level'], 'Direct')
        self.assertEqual(matrix['analytics']['level'], 'Unsupported')

    def test_legacy_x_handoff_projection_does_not_mutate_other_platforms(self):
        matrix = assisted_matrix()
        original = repr(matrix)
        for platform in ('X', 'Twitter', 'x'):
            projected = direct_only_matrix({'platform': platform}, matrix)
            self.assertEqual(projected['publish']['level'], 'Unsupported')
            self.assertNotIn('Assisted', repr(projected))
        self.assertEqual(repr(matrix), original)
        self.assertIs(direct_only_matrix({'platform': 'LinkedIn'}, matrix), matrix)

if __name__ == '__main__':
    unittest.main()
