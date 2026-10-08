"""Canonical-origin move (postriff-phase2-private.vercel.app → rafii.io).

Changing POSTRIFF_PUBLIC_BASE_URL must not break providers whose console still lists only the earlier callback, must
not change the Bluesky client_id that existing grants refresh with, and must never take an origin from a request.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]
from postriff_phase2 import providers
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.provider_base import fixed_https_origin

NEW, OLD = "https://rafii.io", "https://postriff-phase2-private.vercel.app"
LINKEDIN = {"POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID": "client-id", "POSTRIFF_OAUTH_LINKEDIN_CLIENT_SECRET": "client-secret"}


def service(values):
    return OAuthService(None, None, CredentialVault(None), providers.registry_from_environment(values), values.get("POSTRIFF_PUBLIC_BASE_URL"))


class FixedOrigin(unittest.TestCase):
    def test_accepts_only_a_bare_https_origin(self):
        self.assertEqual(fixed_https_origin("https://Rafii.IO/"), NEW)
        self.assertEqual(fixed_https_origin(" https://rafii.io:8443 "), "https://rafii.io:8443")
        for bad in (None, "", "http://rafii.io", "https://rafii.io/app", "https://u:p@rafii.io", "https://rafii.io?x=1",
                    "https://rafii.io#f", "rafii.io", "https://", "https://rafii.io:99999", 7):
            self.assertIsNone(fixed_https_origin(bad), bad)


class CallbackOrigin(unittest.TestCase):
    def test_callbacks_follow_the_public_origin_by_default(self):
        self.assertEqual(service({"POSTRIFF_PUBLIC_BASE_URL": NEW, **LINKEDIN}).callback_uri("linkedin"), NEW + "/api/oauth/linkedin/callback")

    def test_a_provider_can_keep_its_registered_callback_while_the_app_moves(self):
        values = {"POSTRIFF_PUBLIC_BASE_URL": NEW, "POSTRIFF_OAUTH_LINKEDIN_CALLBACK_ORIGIN": OLD + "/", **LINKEDIN}
        oauth = service(values)
        self.assertEqual(oauth.callback_uri("linkedin"), OLD + "/api/oauth/linkedin/callback")
        self.assertTrue(oauth.providers.diagnostics["linkedin"]["callbackOriginPinned"])
        # The landing page after the provider returns is still the canonical origin.
        landing = OAuthService.callback_redirect(oauth.public_base_url, "linkedin", {"state": "s", "code": "c"})
        self.assertTrue(landing.startswith(NEW + "/channels/connect?"))

    def test_a_malformed_override_is_ignored_not_guessed(self):
        values = {"POSTRIFF_PUBLIC_BASE_URL": NEW, "POSTRIFF_OAUTH_LINKEDIN_CALLBACK_ORIGIN": "http://evil.example/x", **LINKEDIN}
        oauth = service(values)
        self.assertEqual(oauth.callback_uri("linkedin"), NEW + "/api/oauth/linkedin/callback")
        self.assertFalse(oauth.providers.diagnostics["linkedin"]["callbackOriginPinned"])

    def test_unmounted_provider_and_public_callback_config_use_the_public_origin(self):
        self.assertEqual(OAuthService(None, None, None, {}, NEW).callback_uri("x"), NEW + "/api/oauth/x/callback")


class BlueskyClientPin(unittest.TestCase):
    def values(self, **extra):
        return {"POSTRIFF_PUBLIC_BASE_URL": NEW, "POSTRIFF_BLUESKY_CLIENT_JWK": json.dumps(generate_jwk(kid="rafii-2026-09")), **extra}

    def test_unpinned_client_follows_the_public_origin(self):
        oauth = service(self.values())
        bluesky = oauth.providers["bluesky"]
        self.assertEqual(bluesky.client_id, NEW + "/api/oauth/bluesky/client-metadata.json")
        self.assertEqual(oauth.callback_uri("bluesky"), NEW + "/api/oauth/bluesky/callback")
        self.assertFalse(oauth.providers.diagnostics["bluesky"]["clientOriginPinned"])

    def test_pinned_client_keeps_client_id_metadata_and_callback_together(self):
        oauth = service(self.values(POSTRIFF_BLUESKY_CLIENT_ORIGIN=OLD))
        bluesky = oauth.providers["bluesky"]
        metadata = bluesky.client_metadata()
        self.assertEqual(bluesky.client_id, OLD + "/api/oauth/bluesky/client-metadata.json")
        self.assertEqual(metadata["client_id"], bluesky.client_id)
        self.assertEqual(metadata["redirect_uris"], [OLD + "/api/oauth/bluesky/callback"])
        self.assertEqual(metadata["jwks_uri"], OLD + "/api/oauth/bluesky/jwks.json")
        self.assertEqual(oauth.callback_uri("bluesky"), metadata["redirect_uris"][0])
        self.assertTrue(oauth.providers.diagnostics["bluesky"]["clientOriginPinned"])

    def test_generic_callback_override_cannot_split_bluesky_from_its_metadata(self):
        oauth = service(self.values(POSTRIFF_OAUTH_BLUESKY_CALLBACK_ORIGIN=OLD))
        self.assertEqual(oauth.callback_uri("bluesky"), oauth.providers["bluesky"].client_metadata()["redirect_uris"][0])

    def test_malformed_pin_does_not_mount(self):
        registry = providers.registry_from_environment(self.values(POSTRIFF_BLUESKY_CLIENT_ORIGIN="http://old.example"))
        self.assertNotIn("bluesky", registry)
        self.assertEqual(registry.diagnostics["bluesky"]["configurationState"], "invalid_configuration")

    def test_direct_construction_is_unchanged(self):
        self.assertEqual(BlueskyProvider(generate_jwk(kid="k"), NEW + "/").client_id, NEW + "/api/oauth/bluesky/client-metadata.json")


if __name__ == "__main__":
    unittest.main()
