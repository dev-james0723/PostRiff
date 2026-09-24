"""Milestone C unit tests: credential vault, PKCE, capability taxonomy, tz-db, OAuth routes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2 import channels
from postriff_phase2.contracts import resolve_time
from postriff_phase2.hosted_app import HostedApplication
from postriff_phase2.oauth import CredentialVault, OAuthService, pkce_pair
from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke


class Vault(unittest.TestCase):
    def test_roundtrip_key_binding_and_unconfigured(self):
        key = CredentialVault.generate_key()
        vault = CredentialVault(key)
        ciphertext, key_id = vault.encrypt("secret-token")
        self.assertNotIn("secret-token", ciphertext)
        self.assertEqual(vault.decrypt(ciphertext, key_id), "secret-token")
        with self.assertRaises(AlphaError):
            vault.decrypt(ciphertext, "other-key-id")
        with self.assertRaises(AlphaError):
            CredentialVault(CredentialVault.generate_key()).decrypt(ciphertext, key_id)
        with self.assertRaises(AlphaError) as unconfigured:
            CredentialVault(None).encrypt("x")
        self.assertEqual(unconfigured.exception.status, 503)

    def test_pkce_pair_is_s256(self):
        import base64
        import hashlib
        verifier, challenge = pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertEqual(challenge, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="))


class Taxonomy(unittest.TestCase):
    def test_levels_require_evidence_and_states_are_independent(self):
        matrix = channels.unsupported_matrix()
        self.assertEqual({v["level"] for v in matrix.values()}, {"Unsupported"})
        with self.assertRaises(AlphaError):
            channels.set_level(matrix, "publish", "Direct", "", None, 1)
        channels.set_level(matrix, "identity", "Direct", "identity matched", 1.0, 1)
        self.assertEqual(matrix["publish"]["level"], "Unsupported")  # identity never implies publish
        with self.assertRaises(AlphaError):
            channels.set_level(matrix, "teleport", "Direct", "x", 1.0, 1)
        assisted = channels.assisted_matrix()
        self.assertEqual((assisted["publish"]["level"], assisted["analytics"]["level"]), ("Assisted", "Unsupported"))

    def test_connection_state_dimensions(self):
        now = 1000.0
        base = {"configured": True, "revoked": False, "identityVerified": True, "expiresAt": 2000.0, "scopes": ["w"], "capabilityVerified": True, "providerAccountId": "p"}
        self.assertEqual(channels.connection_state(base, now), "publish_verified")
        self.assertEqual(channels.connection_state({**base, "capabilityVerified": False}, now), "read_verified")
        self.assertEqual(channels.connection_state({**base, "scopes": []}, now), "scope_missing")
        self.assertEqual(channels.connection_state({**base, "expiresAt": 10.0}, now), "token_expired")
        self.assertEqual(channels.connection_state({**base, "revoked": True}, now), "reauthorization_required")
        self.assertEqual(channels.connection_state({**base, "configured": False}, now), "disconnected")

    def test_resolve_time_records_tzdb(self):
        timing = resolve_time("2027-03-14T02:30:00", "UTC", None, 1_800_000_000)
        self.assertTrue(timing["tzdb"].startswith(("tzdata ", "system:")))


class FakeOAuth:
    public_base_url = 'https://postriff.example'
    def channels(self, w, t): return {"channels": [], "providers": []}
    def start(self, w, t, p, cap): return {"authorizeUrl": f"https://{p}.example/auth", "capability": cap}
    def complete(self, w, t, p, state, code, error=None): return {"connected": bool(code and not error), "confirmAccount": True}
    def verify(self, w, t, c): return {"connectionId": c, "state": "read_verified"}
    def disconnect(self, w, t, c): return {"connectionId": c, "disconnected": True}


class Routes(unittest.TestCase):
    def test_channel_routes_and_public_callback_redirect(self):
        service = FakeService()
        service.oauth = FakeOAuth()
        app = HostedApplication(service, FakeWorker(), {"projectUrl": "x", "publishableKey": "public", "flow": "pkce"}, "c" * 24)
        auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}
        status, _, listed = invoke(app, "GET", "/api/workspaces/w/channels", headers=auth)
        self.assertEqual((status, listed["channels"]), (200, []))
        status, _, started = invoke(app, "POST", "/api/workspaces/w/channels/linkedin/oauth/start", {"capability": "publish"}, auth)
        self.assertEqual((status, started["capability"]), (201, "publish"))
        status, _, done = invoke(app, "POST", "/api/workspaces/w/channels/linkedin/oauth/complete", {"state": "s" * 32, "code": "c"}, auth)
        self.assertEqual((status, done["connected"]), (200, True))
        status, _, verified = invoke(app, "POST", "/api/workspaces/w/channels/conn1/verify", {}, auth)
        self.assertEqual((status, verified["state"]), (200, "read_verified"))
        status, _, gone = invoke(app, "DELETE", "/api/workspaces/w/channels/conn1", {}, auth)
        self.assertEqual((status, gone["disconnected"]), (200, True))
        # Public callback never exchanges: it redirects state/code to the app and drops unknown params.
        environ_extra = {"QUERY_STRING": "state=abc&code=xyz&evil=1", "wsgi.url_scheme": "https"}
        captured = {}
        raw = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/api/oauth/linkedin/callback", "HTTP_HOST": "postriff.example", **environ_extra}, lambda s, h: captured.update(status=s, headers=dict(h))))
        self.assertEqual(captured["status"], "302 Found")
        self.assertEqual(captured["headers"]["Location"], "https://postriff.example/channels/connect?state=abc&code=xyz&provider=linkedin")
        self.assertEqual(raw, b"")

    def test_callback_uri_requires_public_https_base(self):
        with self.assertRaises(AlphaError):
            OAuthService(None, None, CredentialVault(None), {}, "http://localhost:4330").callback_uri("linkedin")
        self.assertEqual(OAuthService(None, None, CredentialVault(None), {}, "https://app.postriff.example/").callback_uri("x"), "https://app.postriff.example/api/oauth/x/callback")


if __name__ == "__main__":
    unittest.main()
