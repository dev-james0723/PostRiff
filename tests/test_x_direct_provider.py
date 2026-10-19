"""Synthetic provider boundary tests. No network or real credentials."""
import json
import unittest
from unittest.mock import patch
from postriff_alpha.domain import AlphaError
from postriff_phase2.social_connectors import XProvider
from postriff_phase2.x_direct_cost import XCostAdmissionError


class XDirectProviderTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response = {"status": 200, "body": {"data": {"id": "123", "username": "example"}}}
        def transport(method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            return self.response
        self.provider = XProvider("fixture-client", "fixture-secret", transport=transport)
        self.grant = self.provider._grant({"access_token": "fixture-access", "refresh_token": "fixture-refresh",
            "scope": "tweet.read users.read tweet.write media.write offline.access", "expires_in": 7200})

    def test_no_assisted_or_unbound_legacy_execution(self):
        self.assertFalse(self.provider.assisted_fallback)
        old = json.dumps({"v": 1, "at": "old-access", "scope": ["tweet.read"]})
        with self.assertRaises(AlphaError):
            self.provider.api(old, "GET", "/2/users/me")
        self.assertEqual([], self.requests)

    def test_other_client_cannot_use_access_or_refresh(self):
        other = XProvider("other-client", "other-secret", transport=self.provider.transport)
        with self.assertRaises(AlphaError):
            other.bearer(self.grant["accessToken"])
        with self.assertRaises(AlphaError):
            other.refresh(self.grant["refreshToken"])
        self.assertEqual([], self.requests)

    def test_reconnect_changes_generation_not_refresh(self):
        second = self.provider._grant({"access_token": "other", "scope": "tweet.read users.read", "expires_in": 7200})
        self.assertNotEqual(self.provider.authorization_generation(self.grant["accessToken"]),
                            self.provider.authorization_generation(second["accessToken"]))
        with self.assertRaises(AlphaError):
            self.provider.preserve_destination(self.grant["accessToken"], second["accessToken"])

    def test_refresh_rotates_and_inherits_only_omitted_scopes(self):
        self.response = {"status": 200, "body": {"access_token": "rotated-access", "refresh_token": "rotated-refresh", "expires_in": 7200}}
        rotated = self.provider.refresh(self.grant["refreshToken"])
        self.assertEqual(self.grant["scopes"], rotated["scopes"])
        self.assertEqual(self.provider.authorization_generation(self.grant["accessToken"]),
                         self.provider.authorization_generation(rotated["accessToken"]))
        self.assertEqual("fixture-refresh", self.requests[0][2]["form"]["refresh_token"])
        self.assertEqual("rotated-refresh", json.loads(rotated["refreshToken"])["rt"])
        self.assertEqual(rotated["accessToken"], self.provider.preserve_destination(self.grant["accessToken"], rotated["accessToken"]))
        self.response["body"]["scope"] = "tweet.read users.read"
        self.assertEqual(["tweet.read", "users.read"], self.provider.refresh(rotated["refreshToken"])["scopes"])

    def test_raw_refresh_is_rejected_before_http(self):
        with self.assertRaises(AlphaError):
            self.provider.refresh("fixture-refresh")
        self.assertEqual([], self.requests)

    def test_invalid_expiry_cannot_extend_access(self):
        for expiry in [None, True, 0, -1, float("inf"), float("nan")]:
            with self.subTest(expiry=expiry), self.assertRaises(AlphaError):
                self.provider._grant({"access_token": "a", "scope": "tweet.read", "expires_in": expiry})

    def test_data_requires_server_cost_context_before_http(self):
        with self.assertRaises(XCostAdmissionError):
            self.provider.api(self.grant["accessToken"], "GET", "/2/users/me")
        self.assertEqual([], self.requests)

    def test_exact_body_and_resource_bound_reach_admission(self):
        payload = {"text": "Approved fixture https://example.com"}
        with patch("postriff_phase2.x_direct_cost.admit_x_request", return_value="synthetic-reservation") as admit:
            self.provider.api(self.grant["accessToken"], "POST", "/2/tweets", json_body=payload, max_resources=1)
        admit.assert_called_once_with(method="POST", path="/2/tweets", body=payload, query={}, max_resources=1)
        self.assertEqual(payload, self.requests[0][2]["body"])
        self.assertNotIn("json_body", self.requests[0][2])
        self.assertNotIn("max_resources", self.requests[0][2])
        self.assertEqual("Bearer fixture-access", self.requests[0][2]["headers"]["Authorization"])

    def test_identity_also_requires_admission(self):
        with patch("postriff_phase2.x_direct_cost.admit_x_request", return_value="synthetic-reservation") as admit:
            identity = self.provider.identity(self.grant["accessToken"])
        self.assertEqual("123", identity["providerAccountId"])
        admit.assert_called_once_with(method="GET", path="/2/users/me", body=None,
                                      query={"user.fields": "profile_image_url"}, max_resources=1)

    def test_auth_override_external_urls_and_duplicate_query_denied(self):
        for key in ["Authorization", "authorization", "Host", "Cookie"]:
            with self.subTest(header=key), self.assertRaises(AlphaError):
                self.provider.api(self.grant["accessToken"], "GET", "/2/users/me", headers={key: "wrong"})
        for path in ["https://example.com/2/users/me", "/2/users/me?max_results=1&max_results=100", "/2/../users/me"]:
            with self.subTest(path=path), self.assertRaises(AlphaError):
                self.provider.api(self.grant["accessToken"], "GET", path)
        self.assertEqual([], self.requests)

    def test_disconnect_revokes_matching_refresh_then_access(self):
        self.response = {"status": 200, "body": {}}
        self.assertTrue(self.provider.revoke_grant(self.grant["accessToken"], self.grant["refreshToken"]))
        self.assertEqual(["refresh_token", "access_token"], [x[2]["form"]["token_type_hint"] for x in self.requests])
        self.assertTrue(all(x[1] == XProvider.REVOKE for x in self.requests))

    def test_disconnect_cannot_combine_generations(self):
        second = self.provider._grant({"access_token": "new", "refresh_token": "new-refresh",
            "scope": "tweet.read users.read", "expires_in": 7200})
        with self.assertRaises(AlphaError):
            self.provider.revoke_grant(self.grant["accessToken"], second["refreshToken"])
        self.assertEqual([], self.requests)

    def test_transport_timeout_is_distinct_from_admission_denial(self):
        def timeout(*args, **kwargs):
            raise AlphaError("Provider unreachable", 503)
        self.provider.transport = timeout
        with patch("postriff_phase2.x_direct_cost.admit_x_request", return_value="synthetic-reservation"):
            with self.assertRaises(AlphaError) as caught:
                self.provider.api(self.grant["accessToken"], "POST", "/2/tweets", body={"text": "Synthetic"})
        self.assertEqual(caught.exception.code, "x_provider_transport_unknown")
