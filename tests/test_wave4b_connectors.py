"""Wave 4B provider contracts and no-network fixtures."""
import base64
import hashlib
import hmac
import json
import unittest
from urllib.parse import parse_qs, urlparse

from postriff_alpha.domain import AlphaError
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.provider_base import NORMALIZED_CAPABILITY_KEYS, NORMALIZED_CAPABILITY_VALUES
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave4b_connectors import (
    LineOfficialAccountProvider, RedditProvider, ZhihuProvider, verify_line_signature,
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


class Wave4BContracts(unittest.TestCase):
    providers = (LineOfficialAccountProvider, RedditProvider, ZhihuProvider)

    def test_every_provider_declares_the_complete_normalized_contract(self):
        for provider in self.providers:
            with self.subTest(provider=provider.id):
                matrix = provider.normalized_capabilities()
                self.assertEqual(tuple(matrix), NORMALIZED_CAPABILITY_KEYS)
                self.assertTrue(set(matrix.values()) <= NORMALIZED_CAPABILITY_VALUES)

    def test_line_and_zhihu_fail_closed_without_browser_fallback(self):
        for provider in (LineOfficialAccountProvider, ZhihuProvider):
            with self.subTest(provider=provider.id):
                adapter = provider("client", "credential")
                self.assertEqual(adapter.capability_scopes("identity"), [])
                with self.assertRaisesRegex(AlphaError, "awaiting"):
                    adapter.authorize_url("redirect", "state", "challenge", [])

    def test_reddit_requires_flag_and_provider_approval_independently(self):
        values = {
            "POSTRIFF_OAUTH_REDDIT_CLIENT_ID": "client", "POSTRIFF_OAUTH_REDDIT_CLIENT_SECRET": "credential",
            "POSTRIFF_OAUTH_REDDIT_CONTACT": "u/rafii_builder", "POSTRIFF_OAUTH_REDDIT_ENABLED": "true",
        }
        registry = registry_from_environment(values, transport=Wire([]))
        service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), registry, "https://rafii.example")
        blocked = next(item for item in service.provider_catalog() if item["id"] == "reddit")
        self.assertFalse(blocked["connectReady"])
        self.assertEqual(blocked["capabilities"]["identity"], True)
        self.assertEqual(blocked["capabilities"]["publish"], False)

        values["POSTRIFF_OAUTH_REDDIT_VERIFIED"] = "true"
        approved = registry_from_environment(values, transport=Wire([]))
        approved_service = OAuthService(None, None, CredentialVault(CredentialVault.generate_key()), approved, "https://rafii.example")
        ready = next(item for item in approved_service.provider_catalog() if item["id"] == "reddit")
        self.assertTrue(ready["connectReady"])


class LineWebhookSecurity(unittest.TestCase):
    def test_signature_covers_the_exact_raw_body(self):
        material = "fixture-key-material"
        raw = b'{"destination":"U123","events":[]}'
        signature = base64.b64encode(hmac.new(material.encode(), raw, hashlib.sha256).digest()).decode()
        self.assertTrue(verify_line_signature(material, raw, signature))
        self.assertFalse(verify_line_signature(material, raw + b" ", signature))
        self.assertFalse(verify_line_signature(material, raw, "invalid"))


class RedditOAuth(unittest.TestCase):
    def test_identity_oauth_refresh_and_revoke_use_descriptive_user_agent(self):
        wire = Wire([
            response({"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "scope": "identity"}),
            response({"id": "t2_member", "name": "member_name", "icon_img": "https://example.invalid/icon.png"}),
            response({"access_token": "AT2", "expires_in": 3600, "scope": "identity"}),
            response({}, 200),
        ])
        provider = RedditProvider("client", "credential", "u/rafii_builder", transport=wire)
        query = parse_qs(urlparse(provider.authorize_url("https://rafii.example/callback", "state", "unused", ["identity"])).query)
        self.assertEqual((query["duration"], query["scope"], query["state"]), (["permanent"], ["identity"], ["state"]))
        grant = provider.exchange("code", "server-verifier", "https://rafii.example/callback")
        self.assertNotIn("credential", json.dumps(grant))
        identity = provider.identity(grant["accessToken"])
        self.assertEqual((identity["providerAccountId"], identity["handle"]), ("t2_member", "u/member_name"))
        refreshed = provider.refresh("RT")
        self.assertEqual((json.loads(refreshed["accessToken"])["at"], refreshed["refreshToken"]), ("AT2", "RT"))
        self.assertTrue(provider.revoke(refreshed["accessToken"]))
        self.assertTrue(all("User-Agent" in call["headers"] for call in wire.calls))
        self.assertIn("by /u/rafii_builder", wire.calls[0]["headers"]["User-Agent"])

    def test_upstream_error_details_are_not_exposed(self):
        provider = RedditProvider("client", "credential", "u/rafii_builder", transport=Wire([response({"error": "sensitive upstream detail"}, 403)]))
        with self.assertRaisesRegex(AlphaError, "provider did not complete") as caught:
            provider.exchange("bad", "verifier", "https://rafii.example/callback")
        self.assertNotIn("sensitive", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
