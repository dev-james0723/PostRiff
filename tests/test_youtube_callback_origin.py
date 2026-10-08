"""Synthetic callback-origin contracts; no provider, database or deployment calls."""
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import OAuthService
from postriff_phase2.productivity_connectors import ProductivityConnectorService


LEGACY = 'https://legacy.example'
DEDICATED = 'https://rafii.example'


def invoke_callback(app, provider='youtube'):
    captured = {}
    raw = b''.join(app({
        'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/oauth/' + provider + '/callback',
        'QUERY_STRING': 'state=synthetic-state&code=synthetic-code&error=access_denied&iss=https%3A%2F%2Faccounts.example&next=https%3A%2F%2Fevil.example',
        'HTTP_HOST': 'evil.example', 'HTTP_X_FORWARDED_HOST': 'evil.example',
        'wsgi.url_scheme': 'https', 'wsgi.input': io.BytesIO(b''),
    }, lambda status, headers: captured.update(status=status, headers=dict(headers))))
    return captured, raw


class YouTubeCallbackOriginTests(unittest.TestCase):
    def test_unset_or_empty_override_preserves_legacy_origin_and_other_provider_callbacks(self):
        for override in (None, ''):
            with self.subTest(override=override):
                service = OAuthService(None, None, None, {}, LEGACY, youtube_public_base_url=override)
                self.assertEqual(service.callback_uri('youtube'), LEGACY + '/api/oauth/youtube/callback')
                self.assertEqual(service.callback_uri('linkedin'), LEGACY + '/api/oauth/linkedin/callback')

    def test_dedicated_origin_is_youtube_only_and_normalizes_a_root_slash(self):
        service = OAuthService(None, None, None, {}, LEGACY, youtube_public_base_url=DEDICATED + '/')
        self.assertEqual(service.callback_uri('youtube'), DEDICATED + '/api/oauth/youtube/callback')
        self.assertEqual(service.callback_uri('linkedin'), LEGACY + '/api/oauth/linkedin/callback')
        # Gmail remains composed with the original global base, not the YouTube override.
        gmail = ProductivityConnectorService(None, None, {'gmail': object()}, LEGACY, flags={})
        self.assertEqual(gmail.callback_uri('gmail'), LEGACY + '/api/oauth/gmail/callback')

    def test_invalid_dedicated_origins_fail_closed_without_affecting_other_providers(self):
        invalid = ('http://rafii.example', 'https://rafii.example/path', 'https://rafii.example//',
                   'https://rafii.example?query=1', 'https://rafii.example?', 'https://rafii.example#fragment',
                   'https://rafii.example#', 'https://owner@rafii.example', 'https://@rafii.example',
                   'https://owner:password@rafii.example', 'https://rafii.example:invalid',
                   'https://rafii.example:65536', ' https://rafii.example', 'https://rafii.example\n',
                   'https://rafii.example\\evil', 'https://', '//rafii.example', ' ', 123)
        for override in invalid:
            with self.subTest(override=override):
                service = OAuthService(None, None, None, {}, LEGACY, youtube_public_base_url=override)
                with self.assertRaises(AlphaError) as error:
                    service.callback_uri('youtube')
                self.assertEqual(error.exception.status, 503)
                self.assertEqual(service.callback_uri('linkedin'), LEGACY + '/api/oauth/linkedin/callback')

    def test_public_hot_and_cold_callbacks_use_same_fixed_origin_and_drop_unknown_inputs(self):
        for hot in (False, True):
            with self.subTest(hot=hot):
                service = SimpleNamespace(
                    oauth=OAuthService(None, None, None, {}, LEGACY, youtube_public_base_url=DEDICATED),
                    productivity_connectors=ProductivityConnectorService(None, None, {}, LEGACY, flags={}),
                ) if hot else None
                app = HostedApplication(service=service)
                app._runtime = Mock(side_effect=AssertionError('Public callback must not initialize providers or DB.'))
                with patch.dict(os.environ, {'POSTRIFF_PUBLIC_BASE_URL': LEGACY,
                                           'POSTRIFF_YOUTUBE_PUBLIC_BASE_URL': DEDICATED}, clear=True):
                    result, raw = invoke_callback(app)
                    self.assertEqual(result['status'], '302 Found')
                    location = urlsplit(result['headers']['Location'])
                    self.assertEqual((location.scheme, location.netloc, location.path), ('https', 'rafii.example', '/channels/connect'))
                    query = parse_qs(location.query)
                    self.assertEqual(set(query), {'provider', 'state', 'code', 'error', 'iss'})
                    self.assertEqual(query['provider'], ['youtube'])
                    self.assertEqual(query['state'], ['synthetic-state'])
                    self.assertEqual(query['code'], ['synthetic-code'])
                    self.assertEqual((raw, result['headers']['Cache-Control'], result['headers']['Referrer-Policy']),
                                     (b'', 'no-store', 'no-referrer'))
                    other, _ = invoke_callback(app, 'linkedin')
                    self.assertTrue(other['headers']['Location'].startswith(LEGACY + '/channels/connect?'))
                    gmail, _ = invoke_callback(app, 'gmail')
                    self.assertTrue(gmail['headers']['Location'].startswith(LEGACY + '/connectors/connect?'))
                app._runtime.assert_not_called()

    def test_hot_callback_uses_mounted_configuration_and_unset_cold_callback_stays_legacy(self):
        app = HostedApplication(SimpleNamespace(oauth=OAuthService(None, None, None, {}, LEGACY,
                                                                 youtube_public_base_url=DEDICATED)))
        with patch.dict(os.environ, {'POSTRIFF_PUBLIC_BASE_URL': 'https://other.example',
                                   'POSTRIFF_YOUTUBE_PUBLIC_BASE_URL': 'https://unused.example'}, clear=True):
            result, _ = invoke_callback(app)
        self.assertTrue(result['headers']['Location'].startswith(DEDICATED + '/channels/connect?'))
        for override in (None, ''):
            values = {'POSTRIFF_PUBLIC_BASE_URL': LEGACY}
            if override is not None:
                values['POSTRIFF_YOUTUBE_PUBLIC_BASE_URL'] = override
            with patch.dict(os.environ, values, clear=True):
                result, _ = invoke_callback(HostedApplication())
            self.assertTrue(result['headers']['Location'].startswith(LEGACY + '/channels/connect?'))

    def test_malformed_public_override_fails_before_runtime_and_preserves_gmail(self):
        for hot in (False, True):
            with self.subTest(hot=hot):
                service = SimpleNamespace(oauth=OAuthService(None, None, None, {}, LEGACY,
                    youtube_public_base_url='https://rafii.example/path')) if hot else None
                app = HostedApplication(service)
                app._runtime = Mock(side_effect=AssertionError('Malformed origin must not initialize runtime.'))
                with patch.dict(os.environ, {'POSTRIFF_PUBLIC_BASE_URL': LEGACY,
                                           'POSTRIFF_YOUTUBE_PUBLIC_BASE_URL': 'https://rafii.example/path'}, clear=True):
                    result, _ = invoke_callback(app)
                    self.assertEqual(result['status'], '503 Service Unavailable')
                    self.assertNotIn('Location', result['headers'])
                    gmail, _ = invoke_callback(app, 'gmail')
                    self.assertTrue(gmail['headers']['Location'].startswith(LEGACY + '/connectors/connect?'))
                app._runtime.assert_not_called()

    def test_preview_override_cannot_send_codes_outside_approved_staging_origin(self):
        values = {'VERCEL_ENV': 'preview', 'POSTRIFF_STAGING_PUBLIC_BASE_URL': 'https://staging.example',
                  'POSTRIFF_PUBLIC_BASE_URL': 'https://staging.example'}
        self.assertIsNone(OAuthService.youtube_origin_from_environment(values))
        values['POSTRIFF_YOUTUBE_PUBLIC_BASE_URL'] = 'https://staging.example/'
        self.assertEqual(OAuthService.youtube_origin_from_environment(values), 'https://staging.example/')
        values['POSTRIFF_YOUTUBE_PUBLIC_BASE_URL'] = DEDICATED
        with self.assertRaises(AlphaError):
            OAuthService.youtube_origin_from_environment(values)
        app = HostedApplication()
        app._runtime = Mock(side_effect=AssertionError('Rejected preview origin must not initialize runtime.'))
        with patch.dict(os.environ, values, clear=True):
            result, _ = invoke_callback(app)
        self.assertEqual(result['status'], '503 Service Unavailable')
        self.assertNotIn('Location', result['headers'])
        app._runtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()
