"""Wave 4A provider contracts and no-network OAuth fixtures."""
import json
import unittest
from urllib.parse import parse_qs, urlparse

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.provider_base import NORMALIZED_CAPABILITY_KEYS, NORMALIZED_CAPABILITY_VALUES
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave4_connectors import (
    BilibiliProvider, DouyinProvider, GoogleBusinessProfileProvider, KuaishouProvider, WeiboProvider,
)


def response(body, status=200):
    return {"status": status, "headers": {}, "body": body}


class Wire:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers=None, form=None, body=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body, "data": data})
        if not self.replies:
            raise AssertionError("Unexpected provider request")
        return self.replies.pop(0)


class CapabilityContract(unittest.TestCase):
    providers = (WeiboProvider, BilibiliProvider, DouyinProvider, KuaishouProvider, GoogleBusinessProfileProvider)

    def test_every_wave4a_provider_declares_every_listed_capability(self):
        for provider in self.providers:
            with self.subTest(provider=provider.id):
                matrix = provider.normalized_capabilities()
                self.assertEqual(tuple(matrix), NORMALIZED_CAPABILITY_KEYS)
                self.assertTrue(set(matrix.values()) <= NORMALIZED_CAPABILITY_VALUES)

    def test_unverified_weibo_and_bilibili_oauth_never_become_connect_actions(self):
        for provider in (WeiboProvider, BilibiliProvider):
            with self.subTest(provider=provider.id):
                self.assertEqual(provider("client", "secret").capability_scopes("identity"), [])
                self.assertEqual(provider.normalized_capabilities()["identity"], "requires_review")

    def test_registry_requires_each_independent_wave4_flag(self):
        values = {"POSTRIFF_OAUTH_DOUYIN_CLIENT_ID": "client", "POSTRIFF_OAUTH_DOUYIN_CLIENT_SECRET": "secret"}
        disabled = registry_from_environment(values, transport=Wire([]))
        self.assertIn("douyin", disabled)
        self.assertFalse(disabled["douyin"].execution_enabled)
        values["POSTRIFF_OAUTH_DOUYIN_ENABLED"] = "true"
        flagged = registry_from_environment(values, transport=Wire([]))
        self.assertFalse(flagged["douyin"].execution_enabled)
        values["POSTRIFF_OAUTH_DOUYIN_VERIFIED"] = "true"
        verified = registry_from_environment(values, transport=Wire([]))
        self.assertTrue(verified["douyin"].execution_enabled)

    def test_catalog_is_secret_free_and_keeps_readiness_gates_independent(self):
        values = {
            "POSTRIFF_OAUTH_DOUYIN_CLIENT_ID": "client-id-sensitive", "POSTRIFF_OAUTH_DOUYIN_CLIENT_SECRET": "secret-sensitive",
            "POSTRIFF_OAUTH_DOUYIN_ENABLED": "true", "POSTRIFF_OAUTH_DOUYIN_APP_CREATED": "true",
            "POSTRIFF_OAUTH_DOUYIN_APPROVED_SCOPES": "user_info", "POSTRIFF_OAUTH_DOUYIN_OAUTH_LIVE_TESTED": "true",
        }
        registry = registry_from_environment(values, transport=Wire([]))
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), registry, "https://rafii.example")
        item = next(entry for entry in service.provider_catalog() if entry["id"] == "douyin")
        encoded = json.dumps(item)
        self.assertNotIn("client-id-sensitive", encoded)
        self.assertNotIn("secret-sensitive", encoded)
        self.assertTrue(item["readinessChecklist"]["providerAppCreated"])
        self.assertTrue(item["readinessChecklist"]["oauthLiveTest"])
        self.assertFalse(item["readinessChecklist"]["tokenRefreshLiveTest"])
        self.assertFalse(item["readinessChecklist"]["productionEnabled"])
        self.assertFalse(item["connectReady"])
        self.assertEqual(item["capabilities"]["identity"], True)
        self.assertEqual(item["capabilities"]["publish"], False)

        values["POSTRIFF_OAUTH_DOUYIN_VERIFIED"] = "true"
        verified_registry = registry_from_environment(values, transport=Wire([]))
        verified_service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), verified_registry, "https://rafii.example")
        verified = next(entry for entry in verified_service.provider_catalog() if entry["id"] == "douyin")
        self.assertTrue(verified["connectReady"])


class DouyinOAuth(unittest.TestCase):
    def test_identity_exchange_refresh_and_enterprise_detection(self):
        wire = Wire([
            response({"data": {"access_token": "AT", "refresh_token": "RT", "expires_in": 86400, "open_id": "open-1", "scope": "user_info"}}),
            response({"data": {"error_code": 0, "nickname": "Creator", "avatar": "https://example.invalid/a.jpg", "e_account_role": {"role": "enterprise"}}}),
            response({"data": {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 86400, "open_id": "open-1", "scope": "user_info"}}),
        ])
        provider = DouyinProvider("key", "secret", transport=wire)
        url = provider.authorize_url("https://rafii.example/callback", "state", "challenge", ["user_info"])
        query = parse_qs(urlparse(url).query)
        self.assertEqual((query["client_key"], query["scope"], query["state"]), (["key"], ["user_info"], ["state"]))
        grant = provider.exchange("code", "verifier", "https://rafii.example/callback")
        self.assertEqual(grant["scopes"], ["user_info"])
        self.assertNotIn("secret", json.dumps(grant))
        identity = provider.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["accountType"]), ("open-1", "enterprise"))
        refreshed = provider.refresh("RT")
        self.assertEqual((json.loads(refreshed["accessToken"])["at"], refreshed["refreshToken"]), ("AT2", "RT2"))

    def test_provider_denial_does_not_leak_description(self):
        provider = DouyinProvider("key", "secret", transport=Wire([response({"data": {"error_code": 2100005, "description": "sensitive upstream detail"}})]))
        with self.assertRaisesRegex(AlphaError, "Douyin did not complete") as caught:
            provider.exchange("bad", "verifier", "https://rafii.example/callback")
        self.assertNotIn("sensitive", str(caught.exception))


class KuaishouOAuth(unittest.TestCase):
    def test_website_flow_identity_and_rotating_refresh(self):
        wire = Wire([
            response({"access_token": "AT", "refresh_token": "RT", "expires_in": 7200, "open_id": "kwai-1", "scopes": ["user_info"]}),
            response({"result": 1, "user_info": {"name": "Kwai creator", "bigHead": "https://example.invalid/k.jpg"}}),
            response({"accessToken": "AT2", "refreshToken": "RT2", "expiresIn": 7200, "openId": "kwai-1", "scopes": "user_info"}),
        ])
        provider = KuaishouProvider("app", "secret", transport=wire)
        query = parse_qs(urlparse(provider.authorize_url("https://rafii.example/callback", "state", "challenge", ["user_info"])).query)
        self.assertEqual((query["app_id"], query["ua"]), (["app"], ["pc"]))
        grant = provider.exchange("code", "unused", "https://rafii.example/callback")
        self.assertEqual(provider.identity(grant["accessToken"])["providerAccountId"], "kwai-1")
        refreshed = provider.refresh("RT")
        self.assertEqual(refreshed["refreshToken"], "RT2")
        self.assertEqual(wire.calls[1]["method"], "GET")


class GoogleBusinessOAuth(unittest.TestCase):
    def test_pkce_offline_account_location_picker_scope_inspection_and_revoke(self):
        wire = Wire([
            response({"access_token": "AT", "refresh_token": "RT", "expires_in": 3600,
                      "scope": "openid profile https://www.googleapis.com/auth/business.manage"}),
            response({"sub": "google-user", "name": "Business owner"}),
            response({"aud": "client", "scope": "openid profile https://www.googleapis.com/auth/business.manage"}),
            response({"accounts": [{"name": "accounts/100"}, {"name": "accounts/200"}]}),
            response({"locations": [{"name": "locations/10", "title": "Downtown"}]}),
            response({"locations": [{"name": "locations/20", "title": "Uptown"}]}),
            response({"accounts": [{"name": "accounts/100"}]}),
            response({"locations": [{"name": "locations/10", "title": "Downtown"}]}),
            response({}, 200),
        ])
        provider = GoogleBusinessProfileProvider("client", "secret", transport=wire)
        auth = parse_qs(urlparse(provider.authorize_url("https://rafii.example/callback", "state", "challenge", provider.SCOPES["identity"])).query)
        self.assertEqual((auth["code_challenge_method"], auth["access_type"], auth["prompt"]), (["S256"], ["offline"], ["consent"]))
        grant = provider.exchange("code", "verifier", "https://rafii.example/callback")
        self.assertEqual(provider.identity(grant["accessToken"])["providerAccountId"], "google-user")
        self.assertIn(GoogleBusinessProfileProvider.BUSINESS_SCOPE, provider.inspect_scopes(grant["accessToken"], "google-user"))
        destinations = provider.destinations(grant["accessToken"])
        self.assertEqual([item["id"] for item in destinations], ["accounts/100/locations/10", "accounts/200/locations/20"])
        selected = provider.with_destination(grant["accessToken"], "accounts/100/locations/10")
        self.assertEqual(json.loads(selected)["location"], "accounts/100/locations/10")
        self.assertTrue(provider.revoke(selected))

    def test_location_identifier_is_strict(self):
        self.assertTrue(GoogleBusinessProfileProvider.valid_destination_id("accounts/123/locations/456"))
        for value in ("accounts/123", "https://evil.example", "accounts/a/locations/1", "accounts/1/locations/2?x=1"):
            self.assertFalse(GoogleBusinessProfileProvider.valid_destination_id(value))


if __name__ == "__main__":
    unittest.main()
