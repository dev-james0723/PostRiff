"""Sandbox-only TikTok OAuth configuration: source-bound, credential-free offline tests."""
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import registry_from_environment
from postriff_phase2.wave3_connectors import TikTokProvider
from scripts.tiktok_sandbox_preflight import evaluate

TEST_ORIGIN = "https://sandbox-oauth-preview.example"
OLD_ORIGIN = "https://postriff-phase2-private.vercel.app"


def config(**overrides):
    values = {
        "VERCEL_ENV": "preview",
        "POSTRIFF_PUBLIC_BASE_URL": TEST_ORIGIN,
        "POSTRIFF_TIKTOK_SANDBOX_ENABLED": "true",
        "POSTRIFF_OAUTH_TIKTOK_CLIENT_ID": "production-client-key-example",
        "POSTRIFF_OAUTH_TIKTOK_CLIENT_SECRET": "production-client-secret-example",
        "POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_ID": "sandbox-client-key-example",
        "POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_SECRET": "sandbox-client-secret-example",
        "POSTRIFF_CREDENTIAL_KEY": CredentialVault.generate_key(),
    }
    values.update(overrides)
    return values


def catalog(values):
    registry = registry_from_environment(values)
    service = OAuthService(None, None, CredentialVault(values.get("POSTRIFF_CREDENTIAL_KEY")),
                           registry, values.get("POSTRIFF_PUBLIC_BASE_URL"))
    return registry, next(p for p in service.provider_catalog() if p["id"] == "tiktok"), service


class SandboxOAuthReadiness(unittest.TestCase):
    def test_sandbox_selects_only_separate_credentials(self):
        values = config()
        registry, entry, service = catalog(values)
        adapter = registry["tiktok"]
        self.assertTrue(adapter.sandbox_mode)
        self.assertEqual(adapter.client_id, "sandbox-client-key-example")
        self.assertEqual(adapter.client_secret, "sandbox-client-secret-example")
        self.assertEqual(adapter.capability_scopes("identity"), ["user.info.basic"])
        self.assertEqual(service.callback_uri("tiktok"), TEST_ORIGIN + "/api/oauth/tiktok/callback")
        self.assertTrue(entry["connectReady"])
        self.assertFalse(entry["productionReviewed"])
        self.assertFalse(entry["readinessChecklist"]["productionEnabled"])

    def test_off_by_default_preserves_existing_production_lane(self):
        values = config(POSTRIFF_TIKTOK_SANDBOX_ENABLED="false")
        registry, entry, _ = catalog(values)
        self.assertFalse(registry["tiktok"].sandbox_mode)
        self.assertEqual(registry["tiktok"].client_id, "production-client-key-example")
        self.assertTrue(entry["connectReady"])
        self.assertFalse(evaluate(values)["readyForHumanIdentityOAuth"])

    def test_sandbox_missing_pair_never_falls_back_to_production(self):
        values = config()
        del values["POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_SECRET"]
        registry, entry, _ = catalog(values)
        self.assertNotIn("tiktok", registry)
        self.assertFalse(entry["connectReady"])
        self.assertEqual(registry.diagnostics["tiktok"]["missingVariables"],
                         ["POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_SECRET"])
        self.assertNotIn("production-client-secret-example", json.dumps(entry))

    def test_sandbox_placeholder_is_rejected_without_secret_leak(self):
        values = config(POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_SECRET="change-me")
        registry, entry, _ = catalog(values)
        self.assertNotIn("tiktok", registry)
        self.assertEqual(entry["configurationState"], "invalid_configuration")
        self.assertNotIn("change-me", json.dumps(entry))

    def test_sandbox_never_mounts_in_vercel_production(self):
        values = config(VERCEL_ENV="production")
        registry, entry, _ = catalog(values)
        self.assertNotIn("tiktok", registry)
        self.assertEqual(entry["configurationState"], "sandbox_forbidden_environment")
        self.assertFalse(entry["connectReady"])
        self.assertIn("Sandbox", " ".join(entry["setupIssues"]))

    def test_sandbox_rejects_canonical_prod_origin(self):
        for origin in ("https://rafii.io", "https://www.rafii.io", OLD_ORIGIN):
            with self.subTest(origin=origin):
                registry, entry, _ = catalog(config(POSTRIFF_PUBLIC_BASE_URL=origin))
                self.assertNotIn("tiktok", registry)
                self.assertFalse(entry["connectReady"])

    def test_sandbox_rejects_production_callback_pin_even_on_preview(self):
        registry, entry, _ = catalog(config(POSTRIFF_OAUTH_TIKTOK_CALLBACK_ORIGIN="https://rafii.io"))
        self.assertNotIn("tiktok", registry)
        self.assertEqual(entry["configurationState"], "sandbox_forbidden_environment")

    def test_review_publish_flags_do_not_unlock_sandbox(self):
        values = config(POSTRIFF_OAUTH_TIKTOK_REVIEWED="true",
                        POSTRIFF_OAUTH_TIKTOK_PUBLISH_APPROVED="true",
                        POSTRIFF_OAUTH_TIKTOK_PUBLISH_LIVE_TESTED="true",
                        POSTRIFF_OAUTH_TIKTOK_ENABLED="true")
        registry, entry, _ = catalog(values)
        adapter = registry["tiktok"]
        self.assertFalse(adapter.production_reviewed)
        self.assertFalse(adapter.publishing_permission)
        self.assertFalse(adapter.publish_live_tested)
        self.assertFalse(entry["publicConnectionReady"])
        self.assertFalse(entry["readinessChecklist"]["productionEnabled"])
        self.assertFalse(evaluate(values)["postingAuthorized"])

    def test_no_secrets_in_preflight_and_no_tiktok_requests(self):
        values = config()
        def deny_network(*args, **kwargs):
            raise AssertionError("This preflight cannot call TikTok")
        registry = registry_from_environment(values, transport=deny_network)
        self.assertIn("tiktok", registry)
        report = evaluate(values)
        text = json.dumps(report)
        for secret in ("sandbox-client-secret-example", "sandbox-client-key-example",
                       "production-client-secret-example", values["POSTRIFF_CREDENTIAL_KEY"]):
            self.assertNotIn(secret, text)
        self.assertEqual(report["providerRequestsMade"], 0)
        self.assertTrue(report["readyForHumanIdentityOAuth"])
        self.assertFalse(report["liveOAuthVerified"])

    def test_identity_authorize_url_never_leaks_secret_or_publish_scope(self):
        registry, _, service = catalog(config())
        url = registry["tiktok"].authorize_url(service.callback_uri("tiktok"), "synthetic-state", "synthetic-challenge",
                                               registry["tiktok"].capability_scopes("identity"))
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["scope"], ["user.info.basic"])
        self.assertEqual(query["client_key"], ["sandbox-client-key-example"])
        self.assertEqual(query["redirect_uri"], [TEST_ORIGIN + "/api/oauth/tiktok/callback"])
        self.assertEqual(query["state"], ["synthetic-state"])
        self.assertNotIn("client_secret", url)
        self.assertNotIn("video.publish", url)

    def test_sandbox_publishing_worker_fails_closed_even_if_review_mutated(self):
        from postriff_phase2.hosted_social import HostedSocial

        registry, _, _ = catalog(config())
        adapter = registry["tiktok"]
        adapter.production_reviewed = True  # simulate a later code path making a mistaken grant claim
        class ForbiddenOAuth:
            def token_for_worker(self, *_):
                raise AssertionError("Sandbox publisher must not read any private account tokens")
        hosted = HostedSocial(ForbiddenOAuth(), {"tiktok": adapter},
                              transport=lambda *_args, **_kw: (_ for _ in ()).throw(
                                  AssertionError("No provider post requests permitted")))
        result = hosted.submit({"platform": "TikTok"})
        self.assertEqual(result["state"], "held")
        self.assertIn("Nothing was posted", result["confirmed"])

    def test_missing_vault_blocks_preflight(self):
        values = config()
        values.pop("POSTRIFF_CREDENTIAL_KEY")
        report = evaluate(values)
        self.assertFalse(report["readyForHumanIdentityOAuth"])
        self.assertTrue(any("POSTRIFF_CREDENTIAL_KEY" in issue for issue in report["issues"]))

    def test_non_tiktok_review_flag_remains_independent(self):
        values = config(POSTRIFF_OAUTH_FACEBOOK_CLIENT_ID="facebook-id-example",
                        POSTRIFF_OAUTH_FACEBOOK_CLIENT_SECRET="facebook-secret-example",
                        POSTRIFF_OAUTH_FACEBOOK_REVIEWED="true")
        registry, _, _ = catalog(values)
        self.assertTrue(registry["facebook"].production_reviewed)
        self.assertFalse(registry["tiktok"].production_reviewed)


if __name__ == "__main__":
    unittest.main()
