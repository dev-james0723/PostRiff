"""Bluesky launch readiness: truthful connection state, refresh safety (mocked transports; never a live call)."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]
from postriff_alpha.domain import AlphaError
from postriff_phase2.atproto_oauth import BlueskyProvider, generate_jwk
from postriff_phase2.channels import connection_state, with_youtube_credential_status, youtube_credential_status
from postriff_phase2.oauth import OAuthService
from rafii_control.founder_metrics_ops import project_connections
from test_hosted_wave1_connectors import BASE, DID, PUBLIC, Wire, ok

NOW = 1_800_000_000.0


def channel(platform="Bluesky", expires=NOW - 3600, **extra):
    return {"platform": platform, "configured": True, "revoked": False, "identityVerified": True, "providerAccountId": DID,
            "expiresAt": expires, "scopes": ["atproto"], "capabilityVerified": False, **extra}


def vault(supported=True, expires=NOW - 3600):
    return {"refreshSupported": supported, "refreshBindingRequired": False, "accessTokenExpiresAt": expires, "revoked": False}


class ConnectionState(unittest.TestCase):
    def test_expired_bluesky_access_with_a_renewing_grant_stays_connected(self):
        view = with_youtube_credential_status(channel(), vault())
        self.assertEqual(connection_state(view, NOW), "read_verified")

    def test_bluesky_without_a_renewing_grant_asks_for_reconnect(self):
        self.assertEqual(connection_state(with_youtube_credential_status(channel(), vault(supported=False)), NOW), "token_expired")
        self.assertEqual(connection_state(with_youtube_credential_status(channel(), None), NOW), "token_expired")

    def test_other_short_lived_platforms_keep_their_behaviour(self):
        view = with_youtube_credential_status(channel("X", refreshSupported=True), vault())
        self.assertEqual(connection_state(view, NOW), "token_expired")

    def test_vault_query_covers_youtube_and_bluesky_only(self):
        class Cur:
            def execute(self, sql, params):
                self.sql, self.params = sql, params

            def fetchall(self):
                return [("w", "c1", True, True, NOW - 60, False)]
        cur = Cur()
        status = youtube_credential_status(cur, ["w"])
        self.assertIn("(provider='youtube' OR provider='bluesky')", cur.sql)
        self.assertEqual(cur.params, (["w"],))
        self.assertTrue(status[("w", "c1")]["refreshSupported"])

    def test_founder_health_does_not_report_a_renewing_bluesky_grant_as_expired(self):
        rows = project_connections([("w", "bsky1", "Bluesky", True, False, True, True, NOW - 3600, ["atproto"], False, NOW - 7200)],
                                   {}, NOW, connection_state, {("w", "bsky1"): vault()})
        row = rows[("w", "bsky1", "identity")]
        self.assertEqual((row[5], row[6], row[7]), ("ok", "read_verified", None))


class Refresh(unittest.TestCase):
    def provider(self, responses):
        wire = Wire(responses)
        return BlueskyProvider(generate_jwk(kid="launch"), BASE, transport=wire, resolver=PUBLIC), wire

    @staticmethod
    def stored():
        return json.dumps({"iss": "https://as.example.com", "tokenEndpoint": "https://as.example.com/oauth/token", "did": DID,
                           "pds": "https://pds.example.com", "jwk": generate_jwk(), "rt": "fixture-refresh", "nonce": None})

    def test_only_a_definitive_answer_ends_the_grant(self):
        for status, body in ((400, {"error": "invalid_grant"}), (401, {"error": "invalid_client"})):
            provider, _ = self.provider([ok(body, status=status)])
            with self.assertRaises(AlphaError) as caught:
                provider.refresh(self.stored())
            self.assertEqual(caught.exception.code, "reauthorization_required")

    def test_outage_or_rate_limit_keeps_the_grant(self):
        for status, body in ((503, {}), (429, {"error": "rate_limited"}), (500, {"error": "internal"})):
            provider, _ = self.provider([ok(body, status=status)])
            with self.assertRaises(AlphaError) as caught:
                provider.refresh(self.stored())
            self.assertEqual(caught.exception.code, "provider_unavailable")


class Metadata(unittest.TestCase):
    """Client identity on rafii.io (B7) and consent-screen links (E2)."""

    @staticmethod
    def mount(**extra):
        values = {"POSTRIFF_BLUESKY_CLIENT_JWK": json.dumps(generate_jwk(kid="launch")), "POSTRIFF_PUBLIC_BASE_URL": "https://rafii.io", **extra}
        adapter, diagnostic = BlueskyProvider.mount(values)
        return adapter, diagnostic

    def test_pinned_origin_on_rafii_io_is_the_client_identity(self):
        adapter, _ = self.mount(POSTRIFF_BLUESKY_CLIENT_ORIGIN="https://rafii.io")
        metadata = adapter.client_metadata()
        self.assertEqual(metadata["client_id"], "https://rafii.io/api/oauth/bluesky/client-metadata.json")
        self.assertEqual(metadata["redirect_uris"], ["https://rafii.io/api/oauth/bluesky/callback"])
        self.assertEqual(metadata["jwks_uri"], "https://rafii.io/api/oauth/bluesky/jwks.json")
        self.assertNotIn("d", adapter.jwks()["keys"][0])  # the public document never carries the private key

    def test_consent_links_stay_off_until_switched_on(self):
        adapter, diagnostic = self.mount()
        self.assertFalse(diagnostic["consentLinks"])
        self.assertFalse({"logo_uri", "tos_uri", "policy_uri"} & set(adapter.client_metadata()))
        adapter, diagnostic = self.mount(POSTRIFF_BLUESKY_CONSENT_LINKS="true")
        metadata = adapter.client_metadata()
        self.assertTrue(diagnostic["consentLinks"])
        self.assertEqual((metadata["logo_uri"], metadata["tos_uri"], metadata["policy_uri"]),
                         ("https://rafii.io/icon", "https://rafii.io/terms", "https://rafii.io/privacy"))

    def test_identity_connect_requests_identity_only(self):
        adapter, _ = self.mount()
        self.assertEqual(adapter.capability_scopes("identity"), ["atproto"])
        self.assertNotIn("transition:generic", adapter.capability_scopes("publish"))


class Resolution(unittest.TestCase):
    """Edge cases (B5), address guard (B6) and outside-dependency protection (D2), all offline."""

    def provider(self, responses, resolver=PUBLIC):
        wire = Wire(responses)
        provider = BlueskyProvider(generate_jwk(kid="launch"), BASE, transport=wire, resolver=resolver)
        provider.clock = lambda: NOW
        return provider, wire

    def test_invalid_handles_are_refused_before_any_request(self):
        provider, wire = self.provider([])
        for bad in ("", "   ", "no-dot", "name.local", "name.localhost", "a..b.social", "-x.bsky.social", "x" * 260 + ".social", "10.0.0.1"):
            with self.assertRaises(AlphaError) as caught:
                provider.normalize_handle(bad)
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(provider.normalize_handle("@Name.Bsky.Social"), "name.bsky.social")
        self.assertEqual(wire.calls, [])

    def test_private_or_mapped_addresses_never_reach_the_network(self):
        for address in ("10.0.0.2", "127.0.0.1", "169.254.169.254", "192.168.1.5", "::1", "fe80::1", "::ffff:10.0.0.2", "fc00::5"):
            family = 10 if ":" in address else 2
            provider, wire = self.provider([], resolver=lambda *a, address=address, family=family, **k: [(family, 1, 6, "", (address, 443))])
            with self.assertRaises(AlphaError):
                provider._get_json("https://pds.example.com/.well-known/oauth-protected-resource")
            self.assertEqual(wire.calls, [], address)

    def test_redirects_are_not_followed(self):
        provider, wire = self.provider([ok({}, status=302, headers={"location": "https://169.254.169.254/"})])
        with self.assertRaises(AlphaError) as caught:
            provider._get_json("https://pds.example.com/.well-known/oauth-protected-resource")
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(len(wire.calls), 1)

    def test_one_retry_then_a_calm_message(self):
        provider, wire = self.provider([ok({}, status=503), ok({}, status=429)])
        with self.assertRaises(AlphaError) as caught:
            provider._get_json("https://plc.directory/" + DID)
        self.assertEqual((caught.exception.status, caught.exception.code), (503, "provider_unavailable"))
        self.assertIn("try again in a minute", str(caught.exception).lower())
        self.assertEqual(len(wire.calls), 2)
        provider, wire = self.provider([ok({}, status=503), ok({"id": DID})])
        self.assertEqual(provider._get_json("https://plc.directory/" + DID), {"id": DID})

    def test_documents_are_cached_briefly_and_per_adapter(self):
        provider, wire = self.provider([ok({"id": DID, "service": []}), ok({"id": DID, "service": []})])
        provider.did_document(DID)
        provider.did_document(DID)
        self.assertEqual(len(wire.calls), 1)
        provider.clock = lambda: NOW + 301
        provider.did_document(DID)
        self.assertEqual(len(wire.calls), 2)
        other, other_wire = self.provider([ok({"id": DID, "service": []})])
        other.did_document(DID)
        self.assertEqual(len(other_wire.calls), 1)

    def test_handle_must_point_back_to_its_account(self):
        doc = {"id": DID, "alsoKnownAs": ["at://someone-else.bsky.social"], "service": []}
        provider, _ = self.provider([ok({"raw": DID}), ok(doc)])
        with self.assertRaises(AlphaError) as caught:
            provider.begin(BASE + "/api/oauth/bluesky/callback", "state", "verifier", "challenge", ["atproto"], "name.bsky.social")
        self.assertEqual(caught.exception.status, 409)


class Custody(unittest.TestCase):
    def service(self, error):
        executed = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                executed.append((sql, params))

        class Db(Cursor):
            def cursor(self):
                return Cursor()

        service = object.__new__(OAuthService)
        service.repository = SimpleNamespace(connection_factory=Db)

        def fail(*args, **kwargs):
            raise error
        service._token_for_worker = fail
        return service, executed

    def test_definitive_refresh_failure_marks_only_the_observed_grant(self):
        error = AlphaError("Bluesky access expired; reconnect the account.", 409, code="reauthorization_required")
        error.bluesky_observed_refresh = "observed-ciphertext"
        service, executed = self.service(error)
        with self.assertRaises(AlphaError):
            service.token_for_worker("w", "bsky1")
        self.assertEqual(len(executed), 1)
        sql, params = executed[0]
        self.assertIn("refresh_supported=false", sql)
        self.assertIn("provider='bluesky'", sql)
        self.assertIn("refresh_ciphertext=%s", sql)
        self.assertEqual(params, ("w", "bsky1", "observed-ciphertext"))

    def test_transient_failure_changes_nothing(self):
        service, executed = self.service(AlphaError("Bluesky did not renew access right now.", 503, code="provider_unavailable"))
        with self.assertRaises(AlphaError):
            service.token_for_worker("w", "bsky1")
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
