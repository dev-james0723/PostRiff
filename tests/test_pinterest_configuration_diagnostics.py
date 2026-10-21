"""Secret-free, fail-closed Pinterest setup diagnostics; synthetic values and zero network."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_phase2.oauth import OAuthService
from postriff_phase2.providers import registry_from_environment

NOW = 1_800_000_000
SECRET = 'SYNTHETIC-PINTEREST-SECRET'


def configured():
    return {'POSTRIFF_OAUTH_PINTEREST_CLIENT_ID':'1615884',
            'POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET':SECRET,
            'POSTRIFF_PINTEREST_TRIAL_READONLY':'1',
            'POSTRIFF_PINTEREST_SANDBOX':'false',
            'POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT':'production',
            'POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID':'00000000-0000-0000-0000-000000000501',
            'POSTRIFF_PINTEREST_TRIAL_ACTOR_ID':'00000000-0000-0000-0000-000000000502',
            'POSTRIFF_PINTEREST_TRIAL_USERNAME':'synthetic_account',
            'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(NOW + 3600)}


def catalog(values):
    wire = Mock(side_effect=AssertionError('No provider request is allowed in configuration diagnostics.'))
    with patch('postriff_phase2.wave3_connectors.time.time', return_value=NOW):
        registry = registry_from_environment(values, transport=wire)
        service = OAuthService.__new__(OAuthService)
        service.providers = registry
        service.vault = SimpleNamespace(fernet=True)
        service.public_base_url = 'https://rafii.test'
        service.youtube_public_base_url = None
        service.clock = lambda: NOW
        result = service.provider_catalog()
    wire.assert_not_called()
    return registry, next(p for p in result if p['id'] == 'pinterest'), result


class PinterestConfigurationDiagnostics(unittest.TestCase):
    def assert_closed(self, registry, view, code):
        self.assertNotIn('pinterest', registry)
        self.assertEqual(registry.diagnostics['pinterest']['configurationIssueCode'], code)
        self.assertEqual(view['configurationState'], 'invalid_configuration')
        self.assertFalse(view['configured'])
        self.assertFalse(view['connectReady'])
        self.assertFalse(view['publicConnectionReady'])
        self.assertFalse(view['readinessChecklist']['productionEnabled'])
        self.assertEqual(view['credentialPresence'], {'clientId':True, 'clientSecret':True})
        rendered = json.dumps(view)
        self.assertNotIn(SECRET, rendered)
        self.assertFalse(any('blank, whitespace or placeholder' in issue for issue in view['setupIssues']))

    def test_expired_private_pilot_is_not_misreported_as_blank_credentials(self):
        values = configured() | {'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(NOW - 1)}
        original = dict(values)
        registry, view, _ = catalog(values)
        self.assert_closed(registry, view, 'pinterest_trial_expired')
        self.assertTrue(any('window has expired' in issue for issue in view['setupIssues']))
        self.assertEqual(values, original)  # No implicit extension or config repair.

    def test_expiry_boundary_is_closed(self):
        registry, view, _ = catalog(configured() | {'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(NOW)})
        self.assert_closed(registry, view, 'pinterest_trial_expired')

    def test_invalid_pilot_identity_or_expiry_is_diagnosed_without_exposing_private_settings(self):
        for extra in ({'POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID':'*'},
                      {'POSTRIFF_PINTEREST_TRIAL_ACTOR_ID':'not-an-actor'},
                      {'POSTRIFF_PINTEREST_TRIAL_USERNAME':'private account'},
                      {'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':'not-a-time'},
                      {'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(NOW + 90000)}):
            with self.subTest(extra=extra):
                registry, view, _ = catalog(configured() | extra)
                self.assert_closed(registry, view, 'pinterest_trial_configuration_invalid')
                self.assertTrue(any('bounded expiry settings' in issue for issue in view['setupIssues']))
                self.assertNotIn(next(iter(extra.values())), json.dumps(view))

    def test_conflicting_trial_host_cannot_mount_and_names_environment_setup(self):
        for extra in ({'POSTRIFF_PINTEREST_SANDBOX':'true'},
                      {'POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT':'https://private.invalid'}):
            with self.subTest(extra=extra):
                registry, view, _ = catalog(configured() | extra)
                self.assert_closed(registry, view, 'pinterest_trial_environment_invalid')
                self.assertTrue(any('environment and Sandbox' in issue for issue in view['setupIssues']))
                self.assertNotIn('private.invalid', json.dumps(view))

    def test_invalid_callback_reports_safe_registered_origin_remediation(self):
        registry, view, _ = catalog(configured() | {
            'POSTRIFF_OAUTH_PINTEREST_CALLBACK_ORIGIN':'http://private.invalid/oauth?secret=PRIVATE'})
        self.assert_closed(registry, view, 'pinterest_callback_origin_invalid')
        self.assertTrue(any('callback origin' in issue for issue in view['setupIssues']))
        self.assertIsNone(view['callbackUri'])
        self.assertFalse(view['readinessChecklist']['redirectUriConfigured'])
        self.assertNotIn('private.invalid', json.dumps(view))
        self.assertNotIn('PRIVATE', json.dumps(view))

    def test_missing_or_invalid_pair_keeps_actual_credential_diagnostic(self):
        for secret in (None, '', ' ', 'placeholder'):
            with self.subTest(secret=secret):
                values = configured() | {'POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT':str(NOW - 1)}
                if secret is None:
                    del values['POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET']
                else:
                    values['POSTRIFF_OAUTH_PINTEREST_CLIENT_SECRET'] = secret
                registry, view, _ = catalog(values)
                self.assertNotIn('pinterest', registry)
                self.assertNotIn('configurationIssueCode', registry.diagnostics['pinterest'])
                self.assertFalse(view['connectReady'])
                self.assertTrue(any(('CLIENT_SECRET' if secret is None else 'blank, whitespace or placeholder') in issue
                                    for issue in view['setupIssues']))

    def test_valid_bounded_pilot_stays_private_and_no_unrelated_provider_diagnosis_changes(self):
        registry, view, all_views = catalog(configured())
        self.assertIn('pinterest', registry)
        self.assertNotIn('configurationIssueCode', registry.diagnostics['pinterest'])
        self.assertTrue(view['connectReady'])
        self.assertTrue(view['trialReadonly'])
        self.assertFalse(view['publicConnectionReady'])
        self.assertFalse(view['readinessChecklist']['productionEnabled'])
        facebook = next(p for p in all_views if p['id'] == 'facebook')
        self.assertTrue(any('POSTRIFF_OAUTH_FACEBOOK_CLIENT_ID' in issue for issue in facebook['setupIssues']))
        self.assertFalse(any('Pinterest Trial' in issue for issue in facebook['setupIssues']))


if __name__ == '__main__':
    unittest.main()
