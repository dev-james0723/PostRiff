"""G2-OUT service rules that need no database (PRD R-OUT-02/03, AC17/AC19 pure cases, AC29 pagination/idempotency)."""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2.results import service

NOW = 1_790_870_000.0


class FlagTest(unittest.TestCase):
    def test_off_unless_explicitly_on(self):
        self.assertFalse(service.enabled({}))
        self.assertFalse(service.enabled({"RAFII_RESULTS_ENABLED": "0"}))
        self.assertTrue(service.enabled({"RAFII_RESULTS_ENABLED": "true"}))

    def test_disabled_answers_feature_disabled(self):
        with self.assertRaises(AlphaError) as caught:
            service.require_enabled({})
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))


class LikelyBotTest(unittest.TestCase):
    def test_known_crawlers_previews_and_scripts(self):
        for agent in ("Googlebot/2.1", "facebookexternalhit/1.1", "Slackbot-LinkExpanding 1.0", "WhatsApp/2.23", "TelegramBot (like TwitterBot)",
                      "Mozilla/5.0 (compatible; bingbot/2.0)", "curl/8.1", "python-requests/2.31", "HeadlessChrome/120", "LinkedInBot/1.0",
                      "Discordbot/2.0", "Mozilla/5.0 (compatible; Embedly/0.2)", "SkypeUriPreview", "", None):
            self.assertTrue(service.likely_bot(agent, "GET", None), agent)

    def test_ordinary_browsers_and_prefetch(self):
        safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        self.assertFalse(service.likely_bot(safari, "GET", None))
        self.assertTrue(service.likely_bot(safari, "HEAD", None))          # no person follows a HEAD request
        self.assertTrue(service.likely_bot(safari, "GET", "prefetch"))     # speculative loads are not clicks


class RedirectLocationTest(unittest.TestCase):
    def test_appends_ref_and_keeps_query_and_fragment(self):
        self.assertEqual(service.redirect_location("https://example.org/book", "AbCdEfGhIj01.20261001"),
                         "https://example.org/book?rafii_ref=AbCdEfGhIj01.20261001")
        self.assertEqual(service.redirect_location("https://example.org/book?utm_source=ig&x=a%20b#slots", "AbCdEfGhIj01.20261001"),
                         "https://example.org/book?utm_source=ig&x=a%20b&rafii_ref=AbCdEfGhIj01.20261001#slots")
        self.assertEqual(service.redirect_location("https://example.org/?", "AbCdEfGhIj01.20261001"), "https://example.org/?rafii_ref=AbCdEfGhIj01.20261001")


class DestinationTest(unittest.TestCase):
    def resolver(self, host, port, type=None):     # noqa: A002 - socket.getaddrinfo's keyword
        return [(2, 1, 6, "", ({"internal.example.org": "10.0.0.5", "loopback.example.org": "127.0.0.1"}.get(host, "93.184.216.34"), port))]

    def test_ac19_public_https_destinations_only(self):
        ok = service.validate_destination("https://example.org/book?x=1", self.resolver)
        self.assertEqual(ok, "https://example.org/book?x=1")
        # A pasted address in any language is stored percent-encoded, so the redirect header stays valid.
        self.assertEqual(service.validate_destination("https://example.org/課程?班=一&q=a%20b", self.resolver),
                         "https://example.org/%E8%AA%B2%E7%A8%8B?%E7%8F%AD=%E4%B8%80&q=a%20b")
        with self.assertRaises(AlphaError):
            service.validate_destination("https://例子.org/", self.resolver)        # hosts must be ASCII (no lookalikes)
        for bad in ("http://example.org/", "https://localhost/", "https://10.0.0.1/", "https://internal.example.org/", "https://loopback.example.org/",
                    "https://user:pass@example.org/", "https://example.org:8443/", "javascript:alert(1)", "https://example.local/", "//example.org/x",
                    "https://example.org/a b", "https://example.org/?rafii_ref=x", "x" * 3000, None, 42):
            with self.assertRaises(AlphaError, msg=repr(bad)) as caught:
                service.validate_destination(bad, self.resolver)
            self.assertEqual(caught.exception.status, 400)
            self.assertIn(caught.exception.code, ("link_destination_unsafe", "link_destination_invalid"))

    def test_own_redirect_is_not_a_destination(self):
        with self.assertRaises(AlphaError):
            service.validate_destination("https://app.example.org/api/l/AbCdEfGhIj01", self.resolver, own_origin="https://app.example.org")


class IdempotencyTest(unittest.TestCase):
    def test_key_shape(self):
        self.assertEqual(service.idempotency_key({"idempotencyKey": "declare-123e4567"}), "declare-123e4567")
        for payload in ({}, {"idempotencyKey": "short"}, {"idempotencyKey": "has space in it"}, {"idempotencyKey": "x" * 81}, {"idempotencyKey": 12345678}):
            with self.assertRaises(AlphaError) as caught:
                service.idempotency_key(payload)
            self.assertEqual(caught.exception.code, "idempotency_key_required")

    def test_digest_ignores_key_and_order_but_not_content(self):
        a = service.request_digest("result_declare", None, {"idempotencyKey": "k1-aaaaaaaa", "type": "lead", "quantity": 1})
        b = service.request_digest("result_declare", None, {"quantity": 1, "type": "lead", "idempotencyKey": "k2-bbbbbbbb"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, service.request_digest("result_declare", None, {"type": "lead", "quantity": 2}))
        self.assertNotEqual(a, service.request_digest("result_amend", "x", {"type": "lead", "quantity": 1}))

    def test_expected_revision(self):
        self.assertEqual(service.expected_revision({"expectedRevision": 3}), 3)
        for payload in ({}, {"expectedRevision": "3"}, {"expectedRevision": True}, {"expectedRevision": 0}):
            with self.assertRaises(AlphaError) as caught:
                service.expected_revision(payload)
            self.assertEqual(caught.exception.code, "revision_required")


class PaginationTest(unittest.TestCase):
    def test_ac29_page_bounds(self):
        self.assertEqual(service.page_limit(None), 25)
        self.assertEqual(service.page_limit("50"), 50)
        self.assertEqual(service.page_limit(1), 1)
        for bad in ("0", "51", "-1", "ten", 51, 0, "1.5"):
            with self.assertRaises(AlphaError, msg=repr(bad)):
                service.page_limit(bad)

    def test_cursor_roundtrip_and_tampering(self):
        cursor = service.encode_cursor(NOW + 0.123, "6f1c0f5e-7b0c-4c39-a4a5-6b8c2b0c9d11")
        self.assertEqual(service.decode_cursor(cursor), (NOW + 0.123, "6f1c0f5e-7b0c-4c39-a4a5-6b8c2b0c9d11"))
        self.assertIsNone(service.decode_cursor(None))
        for bad in ("nope", "W10", "WyJhIiwiYiJd", "x" * 300):
            with self.assertRaises(AlphaError):
                service.decode_cursor(bad)


class HealthTest(unittest.TestCase):
    def test_states(self):
        h = service.connection_health
        self.assertEqual(h("active", None, None, None, None, NOW)["dataState"], "unavailable")
        self.assertEqual(h("active", NOW - 60, NOW - 120, None, None, NOW)["dataState"], "available")
        self.assertEqual(h("active", NOW - 60, NOW - 3600, None, None, NOW)["lagSeconds"], 3540)
        late = h("active", NOW - 60, NOW - 60, "signature_mismatch", NOW - 10, NOW)
        self.assertEqual((late["dataState"], late["reason"]), ("partial", "signature_mismatch"))
        self.assertEqual(h("active", NOW - 8 * 86400, NOW - 8 * 86400, None, None, NOW)["dataState"], "stale")
        self.assertEqual(h("paused", NOW - 60, NOW - 60, None, None, NOW)["reason"], "paused")
        self.assertEqual(h("removed", NOW - 60, NOW - 60, None, None, NOW)["dataState"], "unavailable")

    def test_summary_state(self):
        s = service.summary_state
        self.assertEqual(s({"connections": 0, "paused": 0, "errored": 0, "declarations": False}, NOW - 10, NOW), "unavailable")
        self.assertEqual(s({"connections": 1, "paused": 0, "errored": 0, "declarations": False}, NOW - 10, NOW), "available")
        self.assertEqual(s({"connections": 0, "paused": 0, "errored": 0, "declarations": True}, NOW + 10, NOW), "partial")   # the period is still open
        self.assertEqual(s({"connections": 2, "paused": 0, "errored": 1, "declarations": True}, NOW - 10, NOW), "partial")
        self.assertEqual(s({"connections": 1, "paused": 0, "errored": 0, "declarations": False}, NOW, NOW), "partial")      # "until now" is open


if __name__ == "__main__":
    unittest.main()
