"""LinkedIn token contract regressions; synthetic, never live account evidence."""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.providers import LinkedInProvider


class LinkedInTokenLifecycle(unittest.TestCase):
    def adapter(self, body, status=200):
        calls = []
        def transport(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"status": status, "headers": {}, "body": body}
        return LinkedInProvider("synthetic-client", "synthetic-secret", transport=transport), calls

    def test_missing_or_invalid_access_expiry_never_becomes_nonexpiring(self):
        for expiry in (None, 0, -1, True, "5184000", float("nan"), float("inf")):
            for operation in ("exchange", "refresh"):
                with self.subTest(expiry=repr(expiry), operation=operation):
                    provider, _ = self.adapter({"access_token": "synthetic-token", "expires_in": expiry})
                    with self.assertRaises(AlphaError):
                        if operation == "exchange":
                            provider.exchange("synthetic-code", "verifier", "https://example.invalid/api/oauth/linkedin/callback")
                        else:
                            provider.refresh("synthetic-refresh")

    def test_invalid_access_token_is_rejected_before_custody(self):
        for token in (None, "", "contains whitespace", 42, {"token": "bad"}):
            with self.subTest(token=repr(token)):
                provider, _ = self.adapter({"access_token": token, "expires_in": 3600})
                with self.assertRaises(AlphaError):
                    provider.refresh("synthetic-refresh")

    def test_actual_lifetime_and_absent_partner_refresh_are_preserved(self):
        provider, calls = self.adapter({"access_token": "synthetic-token", "expires_in": 1234,
                                       "scope": "openid,profile,w_member_social"})
        grant = provider.exchange("synthetic-code", "verifier", "https://example.invalid/api/oauth/linkedin/callback")
        self.assertEqual(grant["expiresIn"], 1234)
        self.assertIsNone(grant["refreshToken"])
        self.assertEqual(grant["scopes"], ["openid", "profile", "w_member_social"])
        self.assertEqual(calls[0][1], "https://www.linkedin.com/oauth/v2/accessToken")
        self.assertEqual(calls[0][2]["form"]["grant_type"], "authorization_code")

    def test_refresh_retains_original_only_when_provider_omits_rotation(self):
        provider, calls = self.adapter({"access_token": "synthetic-token", "expires_in": 1200})
        grant = provider.refresh("synthetic-original-refresh")
        self.assertEqual(grant["refreshToken"], "synthetic-original-refresh")
        self.assertEqual(grant["expiresIn"], 1200)
        self.assertEqual(calls[0][2]["form"]["grant_type"], "refresh_token")
        provider, _ = self.adapter({"access_token": "synthetic-token", "expires_in": 1200,
                                   "refresh_token": "synthetic-rotated-refresh"})
        self.assertEqual(provider.refresh("synthetic-original-refresh")["refreshToken"], "synthetic-rotated-refresh")

    def test_invalid_rotated_refresh_is_not_stored_or_silently_replaced(self):
        for token in (None, "", "contains whitespace", 42, {"token": "bad"}):
            with self.subTest(token=repr(token)):
                provider, _ = self.adapter({"access_token": "synthetic-token", "expires_in": 3600,
                                           "refresh_token": token})
                with self.assertRaises(AlphaError):
                    provider.refresh("synthetic-original-refresh")

    def test_revoked_refresh_requests_reconnection_without_leaking_response(self):
        provider, _ = self.adapter({"error": "invalid_grant", "error_description": "PRIVATE_RESPONSE"}, status=400)
        with self.assertRaises(AlphaError) as raised:
            provider.refresh("synthetic-original-refresh")
        self.assertEqual(raised.exception.code, "reauthorization_required")
        self.assertNotIn("PRIVATE_RESPONSE", str(raised.exception))

    def test_partner_refresh_renews_before_the_access_token_expires(self):
        self.assertEqual(LinkedInProvider.refresh_margin, 300)

    def test_documented_invalid_request_refresh_revocation_requires_reconnect(self):
        provider, _ = self.adapter({'error': 'invalid_request', 'error_description':
                                    'The provided authorization grant or refresh token is invalid, expired or revoked'}, status=400)
        with self.assertRaises(AlphaError) as raised:
            provider.refresh('synthetic-original-refresh')
        self.assertEqual(raised.exception.code, 'reauthorization_required')

    def test_invalid_request_configuration_failure_is_not_user_revocation(self):
        for code in ('invalid_client', 'invalid_request'):
            provider, _ = self.adapter({'error': code, 'error_description':
                                        'A required parameter client_id is missing. PRIVATE_RESPONSE'}, status=400)
            with self.assertRaises(AlphaError) as raised:
                provider.refresh('synthetic-original-refresh')
            self.assertNotEqual(raised.exception.code, 'reauthorization_required')
            self.assertNotIn('PRIVATE_RESPONSE', str(raised.exception))

    def test_invalid_local_refresh_never_reaches_provider(self):
        for token in (None, '', 'bad token', 42):
            provider, calls = self.adapter({'access_token': 'synthetic-token', 'expires_in': 3600})
            with self.subTest(token=repr(token)), self.assertRaises(AlphaError):
                provider.refresh(token)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
