"""Exercise the real default wrapper without network or credentials."""
import io
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler
from postriff_alpha.domain import AlphaError
from postriff_phase2.providers import http_transport, _NoRedirect

class Response(io.BytesIO):
    status = 200
    headers = {'X-Test': 'yes'}

class TransportContract(unittest.TestCase):
    def call(self, raw=b'{"ok":true}', error=None):
        class Opener:
            def open(self, fullurl, data=None, timeout=None):
                if timeout != 20:
                    raise AssertionError('timeout lost')
                if error:
                    raise error
                return Response(raw)
        with patch('postriff_phase2.providers.build_opener', return_value=Opener()) as build:
            result = http_transport('GET', 'https://example.invalid/test')
            handlers = build.call_args.args
            self.assertTrue(any(isinstance(h, _NoRedirect) for h in handlers))
            tls = next(h for h in handlers if isinstance(h, HTTPSHandler))
            self.assertEqual(tls._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(tls._context.check_hostname)
            return result

    def test_supported_signature_and_tls(self):
        self.assertEqual(self.call()['body'], {'ok': True})

    def test_success_and_error_response_caps(self):
        for error in (False, True):
            with self.subTest(error=error), self.assertRaisesRegex(AlphaError, 'limit exceeded'):
                raw = b'x' * 262145
                self.call(raw, HTTPError('https://example.invalid', 500, 'error', {}, io.BytesIO(raw)) if error else None)

    def test_http_error_and_malformed_json(self):
        self.assertEqual(self.call(error=HTTPError('https://example.invalid', 403, '', {}, io.BytesIO(b'{"error":"denied"}')))['status'], 403)
        self.assertEqual(self.call(b'not json')['body'], {'raw': 'not json'})

    def test_timeout_diagnostic_is_redacted(self):
        for error in (TimeoutError('secret-token'), URLError('secret-token')):
            with self.assertRaises(AlphaError) as caught:
                self.call(error=error)
            self.assertNotIn('secret-token', str(caught.exception))

    def test_redirects_and_plain_http_rejected(self):
        with self.assertRaises(AlphaError):
            _NoRedirect().redirect_request(None, None, None, None, None)
        with self.assertRaises(AlphaError):
            http_transport('GET', 'http://example.invalid')
