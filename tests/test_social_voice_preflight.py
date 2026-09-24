import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from postriff_phase2.oauth import CredentialVault

spec = importlib.util.spec_from_file_location('social_voice_preflight', ROOT / 'scripts/check_social_voice_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class SocialPreflightTests(unittest.TestCase):
    def configured(self):
        return {'POSTRIFF_PUBLIC_BASE_URL': 'https://app.example', 'NEXT_PUBLIC_APP_URL': 'https://app.example',
                'POSTRIFF_CREDENTIAL_KEY': CredentialVault.generate_key(),
                'POSTRIFF_OAUTH_INSTAGRAM_CLIENT_ID': 'instagram-id', 'POSTRIFF_OAUTH_INSTAGRAM_CLIENT_SECRET': 'synthetic-private-instagram',
                'POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID': 'linkedin-id', 'POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET': 'synthetic-private-linkedin'}

    def test_missing_settings_are_actionable_and_not_live_success(self):
        result = preflight.inspect_environment({})
        self.assertFalse(result['configured'])
        self.assertFalse(result['liveOAuthVerified'])
        self.assertTrue(all(item['setupIssues'] for item in result['providers']))

    def test_configured_is_only_static_and_does_not_leak_secrets(self):
        values = self.configured()
        report = preflight.inspect_environment(values)
        self.assertTrue(report['configured'])
        self.assertFalse(report['liveOAuthVerified'])
        self.assertFalse(report['liveHistoryVerified'])
        for key, value in values.items():
            if key.endswith('_SECRET') or key == 'POSTRIFF_CREDENTIAL_KEY':
                self.assertNotIn(value, json.dumps(report))
        linkedin = next(item for item in report['providers'] if item['id'] == 'linkedin')
        self.assertFalse(linkedin['historyAvailableForApp'])

    def test_bad_key_mismatched_origin_and_callback_userinfo_are_rejected(self):
        for overrides in ({'POSTRIFF_CREDENTIAL_KEY': 'invalid-private-key'}, {'NEXT_PUBLIC_APP_URL': 'https://other.example'}, {'POSTRIFF_PUBLIC_BASE_URL': 'https://password@app.example'}):
            with self.subTest(overrides=overrides):
                result = preflight.inspect_environment({**self.configured(), **overrides})
                self.assertFalse(result['configured'])
                self.assertNotIn('invalid-private-key', json.dumps(result))
                self.assertNotIn('password@', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
