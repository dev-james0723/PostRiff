"""No-network adversarial checks for Substack mode, feed, and handoff boundaries."""
import json
from pathlib import Path
import socket
import ssl
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.substack import (
    CAPABILITY_STATUSES, CONNECTION_MODES, MAX_FEED_BYTES, MAX_FEED_ITEMS,
    METRIC_PROVENANCE, _pinned_public_feed_get, build_manual_handoff,
    fetch_public_feed, get_substack_capabilities, normalize_imported_metric,
    normalize_public_feed, require_substack_capability, unavailable_metric,
    validate_publication_url,
)


PUBLICATION = "https://pianoresearch.substack.com"
PUBLIC_IP = "93.184.216.34"


def rss(items=None, extra=""):
    items = items if items is not None else (
        '<item><title><![CDATA[<b>Piano</b> &amp; practice]]></title>'
        '<link>https://pianoresearch.substack.com/p/practice</link>'
        '<description><![CDATA[<p>Useful <strong>public excerpt</strong>.</p>'
        '<script>secretScript()</script><style>secretStyle</style>'
        '<img src="https://tracking.invalid/pixel" onerror="secretHandler()">]]></description>'
        '<pubDate>Sun, 18 Oct 2026 12:00:00 -0400</pubDate>'
        '<content:encoded><![CDATA[PRIVATE_FULL_BODY_DO_NOT_IMPORT]]></content:encoded></item>'
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            '<channel><title>Piano research</title><description>Public publication</description>'
            + items + extra + '</channel></rss>').encode()


def response(body=None, status=200, headers=None):
    return {"status": status, "body": rss() if body is None else body,
            "headers": {"content-type": "application/rss+xml; charset=utf-8"} if headers is None else headers}


def resolver_for(*addresses):
    return Mock(return_value=[(socket.AF_INET6 if ":" in address else socket.AF_INET,
                              socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses])


class SubstackCapabilityTests(unittest.TestCase):
    def test_capability_vocabulary_and_primary_workflows(self):
        matrix = get_substack_capabilities()
        self.assertTrue(set(entry["status"] for entry in matrix.values()) <= CAPABILITY_STATUSES)
        for key in ("draft_create", "draft_edit", "draft_preview", "draft_approval", "manual_handoff",
                    "editorial_schedule", "public_feed_read", "account_connect", "publication_analytics",
                    "notes_create", "post_publish", "post_schedule", "comments_read", "subscribers_read"):
            self.assertIn(key, matrix)
            self.assertEqual(set(matrix[key]), {"status", "reason", "evidence"})
        self.assertEqual(matrix["public_feed_read"]["status"], "available")
        self.assertEqual(matrix["post_publish"]["status"], "requires_official_approval")
        self.assertEqual(matrix["notes_create"]["status"], "requires_official_approval")
        json.dumps(matrix)

    def test_capability_results_are_not_mutable_shared_state(self):
        changed = get_substack_capabilities()
        changed["post_publish"]["status"] = "available"
        changed["notes_create"]["evidence"].clear()
        current = get_substack_capabilities()
        self.assertEqual(current["post_publish"]["status"], "requires_official_approval")
        self.assertTrue(current["notes_create"]["evidence"])

    def test_claimed_approval_and_scope_do_not_create_an_implementation(self):
        for mode in CONNECTION_MODES:
            with self.subTest(mode=mode):
                context = {"mode": mode, "official_approval": True, "publishing_authorized": True,
                           "official_contract_verified": True, "account_authenticated": True,
                           "scopes": ["notes.write", "posts.write", "subscribers.write"],
                           "is_admin": True, "is_bestseller": True}
                matrix = get_substack_capabilities(context)
                for action in ("account_connect", "post_publish", "post_schedule", "notes_create", "newsletter_send", "subscriber_changes"):
                    self.assertNotEqual(matrix[action]["status"], "available")
                    with self.assertRaises(AlphaError):
                        require_substack_capability(action, context)

    def test_mcp_mode_cannot_promote_reads_into_write_or_profile_access(self):
        matrix = get_substack_capabilities({"mode": "official_mcp_analytics", "is_admin": True, "is_bestseller": True})
        for action in ("notes_create", "notes_analytics", "post_publish", "post_schedule", "newsletter_send",
                       "comments_reply", "subscriber_changes", "payment_manage", "profile_read"):
            self.assertEqual(matrix[action]["status"], "unsupported", action)
        self.assertEqual(matrix["publication_analytics"]["status"], "requires_official_approval")

    def test_mcp_eligibility_is_not_inferred_from_subscriber_counts(self):
        for eligibility in ({"is_admin": False}, {"is_bestseller": False}):
            matrix = get_substack_capabilities({"mode": "official_mcp_analytics", "paid_subscribers": 1000000, **eligibility})
            self.assertEqual(matrix["publication_analytics"]["status"], "requires_account_eligibility")
        matrix = get_substack_capabilities({"mode": "official_mcp_analytics", "paid_subscribers": 1000000})
        self.assertNotEqual(matrix["publication_analytics"]["status"], "available")

    def test_revoked_mcp_read_permission_is_not_connected(self):
        matrix = get_substack_capabilities({"mode": "official_mcp_analytics", "status": "revoked"})
        self.assertEqual(matrix["publication_analytics"]["status"], "permission_missing")

    def test_unknown_actions_and_modes_fail_closed(self):
        for context in ({"mode": "cookie_session"}, {"mode": "rss_is_oauth"}, {"mode": []}, "bad-context", [], False):
            with self.assertRaises(AlphaError):
                get_substack_capabilities(context)
        with self.assertRaises(AlphaError) as error:
            require_substack_capability("invented_write")
        self.assertEqual(error.exception.code, "substack_capability_unavailable")
        with self.assertRaises(AlphaError):
            require_substack_capability({"status": "available"})
        self.assertEqual(require_substack_capability("manual_handoff")["status"], "available")


class SubstackPublicationUrlTests(unittest.TestCase):
    def test_normalizes_only_publication_home_and_feed(self):
        for suffix in ("", "/", "/feed", "/feed/"):
            target = validate_publication_url(PUBLICATION + suffix)
            self.assertEqual(target, {"host": "pianoresearch.substack.com", "publication_url": PUBLICATION, "feed_url": PUBLICATION + "/feed"})
        self.assertEqual(validate_publication_url("https://PianoResearch.substack.com")["publication_url"], PUBLICATION)

    def test_ssrf_credentials_services_and_ambiguous_urls_are_rejected(self):
        # Deliberately fake userinfo assembled as URL fields, never a stored credential.
        fake_userinfo = ":".join(("user", "password"))
        credentialed_feed = urlunsplit(("https", fake_userinfo + "@pianoresearch.substack.com", "/feed", "", ""))
        attacks = [
            None, "", {}, [], 42, "http://pianoresearch.substack.com", "file:///etc/passwd",
            "https://localhost", "https://127.0.0.1", "https://2130706433", "https://[::1]",
            "https://169.254.169.254/latest/meta-data", "https://private.internal/feed",
            "https://substack.com", "https://www.substack.com", "https://mcp.substack.com",
            "https://api.substack.com", "https://publisher-api.substack.com", "https://auth.substack.com",
            "https://support.substack.com", "https://account.substack.com", "https://login.substack.com",
            "https://pianoresearch.substack.com.evil.example/feed", "https://x.pianoresearch.substack.com",
            "https://pianoresearch.substack.com@127.0.0.1/feed", credentialed_feed,
            "https://@pianoresearch.substack.com/feed", "https://pianoresearch.substack.com:443/feed",
            "https://pianoresearch.substack.com:8443/feed", "https://pianoresearch.substack.com:bad/feed",
            "https://pianoresearch.substack.com./feed", "https://-bad.substack.com", "https://bad-.substack.com",
            "https://pianoresearch.substack.com/feed?token=private", "https://pianoresearch.substack.com/feed?",
            "https://pianoresearch.substack.com/#private", "https://pianoresearch.substack.com/#",
            "https://pianoresearch.substack.com/p/specific-post", "https://pianoresearch.substack.com/%66eed",
            "https://pianoresearch.substack.com//feed", "https://pianoresearch.substack.com/../feed",
            "https://pianoresearch.substack.com\\@127.0.0.1/feed", "https://piano%72esearch.substack.com/feed",
            "https://рianoresearch.substack.com", " https://pianoresearch.substack.com", "https://pianoresearch.substack.com\n",
            "https://piano\tresearch.substack.com", "https://pianoresearch.substack.com/\x00feed",
        ]
        for value in attacks:
            with self.subTest(value=value), self.assertRaises(AlphaError):
                validate_publication_url(value)


class SubstackFeedNormalizationTests(unittest.TestCase):
    def test_rss_excerpts_are_inert_and_do_not_claim_identity_or_analytics(self):
        parsed = normalize_public_feed(rss(), PUBLICATION)
        self.assertEqual(parsed["itemCount"], 1)
        item = parsed["items"][0]
        self.assertEqual(item["title"], "Piano & practice")
        self.assertEqual(item["publishedAt"], "2026-10-18T16:00:00+00:00")
        self.assertIn("Useful public excerpt", item["summary"])
        for text in ("secretScript", "secretStyle", "secretHandler", "tracking.invalid", "PRIVATE_FULL_BODY", "<"):
            self.assertNotIn(text, item["summary"])
        for name in ("accountAuthenticated", "ownershipVerified", "analyticsConnected", "publishingAuthorized"):
            self.assertIs(parsed[name], False)
        self.assertEqual(parsed["provenance"], "public_feed")

    def test_atom_namespace_links_and_summary(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Piano</title><entry><title>New</title><link rel="alternate" href="https://pianoresearch.substack.com/p/new"/><summary>Public only</summary><published>2026-10-18T16:00:00Z</published></entry></feed>'
        parsed = normalize_public_feed(raw, PUBLICATION)
        self.assertEqual(parsed["itemCount"], 1)
        self.assertEqual(parsed["items"][0]["summary"], "Public only")

    def test_foreign_private_javascript_and_tracking_links_are_omitted(self):
        links = ["javascript:alert(1)", "https://evil.example/p/x", "https://127.0.0.1/p/x",
                 PUBLICATION + "/p/x?private_key=secret", PUBLICATION + "/api/private", PUBLICATION + "/p/good",
                 PUBLICATION + "/p/good", "https://user@pianoresearch.substack.com/p/x"]
        entries = "".join(f"<item><title>Entry</title><link>{link}</link></item>" for link in links)
        parsed = normalize_public_feed(rss(entries), PUBLICATION)
        self.assertEqual([item["url"] for item in parsed["items"]], [PUBLICATION + "/p/good"])
        self.assertIsNone(parsed["items"][0]["publishedAt"])

    def test_no_date_or_empty_feed_is_not_a_fabricated_value(self):
        parsed = normalize_public_feed(rss(""), PUBLICATION)
        self.assertEqual(parsed["items"], [])
        self.assertEqual(parsed["itemCount"], 0)
        self.assertNotIn("subscribers", parsed)
        parsed = normalize_public_feed(rss('<item><link>' + PUBLICATION + '/p/date</link><pubDate>nonsense</pubDate></item>'), PUBLICATION)
        self.assertIsNone(parsed["items"][0]["publishedAt"])

    def test_dtd_entities_malformed_html_and_wrong_encoding_are_rejected(self):
        attacks = [b"", None, {}, b"<html>unavailable</html>", b"<rss><channel>",
                   b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><channel><title>&xxe;</title></channel></rss>',
                   b'<!DOCTYPE rss [<!ENTITY a "abc"><!ENTITY b "&a;&a;&a;">]><rss><channel><title>&b;</title></channel></rss>',
                   b'<!doctype rss><rss><channel/></rss>', b"\xff\xfe<rss/>",
                   '<rss><channel/></rss>'.encode("utf-16"), b"<rss>\x00<channel/></rss>",
                   b"<rss></rss>"]
        for value in attacks:
            with self.subTest(value=str(value)[:100]), self.assertRaises(AlphaError):
                normalize_public_feed(value, PUBLICATION)

    def test_response_and_structure_limits_are_enforced(self):
        with self.assertRaises(AlphaError):
            normalize_public_feed(b" " * (MAX_FEED_BYTES + 1), PUBLICATION)
        with self.assertRaises(AlphaError):
            normalize_public_feed(rss("<x/>" * 10001), PUBLICATION)
        entries = "".join(f"<item><link>{PUBLICATION}/p/{i}</link><description>" + "x" * 1500 + "</description></item>" for i in range(MAX_FEED_ITEMS + 10))
        parsed = normalize_public_feed(rss(entries), PUBLICATION)
        self.assertEqual(parsed["itemCount"], MAX_FEED_ITEMS)
        self.assertEqual(len(parsed["items"][0]["summary"]), 1200)


class SubstackFeedTransportTests(unittest.TestCase):
    def test_fetch_dispatches_one_get_to_the_canonical_feed(self):
        wire = Mock(return_value=response(headers={"Content-Type": "application/rss+xml"}))
        parsed = fetch_public_feed(PUBLICATION, transport=wire)
        wire.assert_called_once_with("GET", PUBLICATION + "/feed")
        self.assertEqual(parsed["itemCount"], 1)

    def test_bad_url_is_rejected_before_transport(self):
        wire = Mock()
        with self.assertRaises(AlphaError):
            fetch_public_feed("https://169.254.169.254/", transport=wire)
        wire.assert_not_called()

    def test_redirects_authentication_and_unavailable_responses_are_not_followed(self):
        for status in (301, 302, 307, 308, 401, 403, 404, 500, 503):
            wire = Mock(return_value=response(status=status, headers={"location": "http://169.254.169.254/"}))
            with self.subTest(status=status), self.assertRaises(AlphaError):
                fetch_public_feed(PUBLICATION, transport=wire)
            self.assertEqual(wire.call_count, 1)

    def test_rate_limit_and_timeout_are_explicit_errors(self):
        with self.assertRaises(AlphaError) as error:
            fetch_public_feed(PUBLICATION, transport=Mock(return_value=response(status=429)))
        self.assertEqual(error.exception.status, 429)
        with self.assertRaises(AlphaError) as error:
            fetch_public_feed(PUBLICATION, transport=Mock(side_effect=TimeoutError("fixture")))
        self.assertEqual(error.exception.status, 503)

    def test_generic_html_wrong_type_compression_and_oversize_are_rejected(self):
        attacks = [response(b"<html>unavailable</html>", headers={"content-type": "text/html"}),
                   response(headers={}), response(headers={"content-type": "application/json"}),
                   response(headers={"content-type": "application/rss+xml", "content-encoding": "gzip"}),
                   response(b" " * (MAX_FEED_BYTES + 1)), "not-a-response"]
        for value in attacks:
            with self.subTest(response=str(value)[:70]), self.assertRaises(AlphaError):
                fetch_public_feed(PUBLICATION, transport=Mock(return_value=value))

    def test_all_dns_answers_must_be_public_and_no_socket_opens_on_denial(self):
        attacks = [("127.0.0.1",), ("169.254.169.254",), ("10.0.0.1",), ("::1",),
                   ("fd00::1",), ("fe80::1",), ("224.0.0.1",), ("::ffff:127.0.0.1",),
                   ("64:ff9b::7f00:1",), ("64:ff9b::a00:1",), ("2002:7f00:1::",),
                   (PUBLIC_IP, "10.1.2.3"), ()]
        with patch("postriff_phase2.substack.socket.create_connection") as connect:
            for addresses in attacks:
                with self.subTest(addresses=addresses), self.assertRaises(AlphaError):
                    _pinned_public_feed_get("GET", PUBLICATION + "/feed", resolver=resolver_for(*addresses))
            connect.assert_not_called()

    def test_dns_resolution_errors_are_a_recoverable_unavailable_state(self):
        with self.assertRaises(AlphaError) as error:
            _pinned_public_feed_get("GET", PUBLICATION + "/feed", resolver=Mock(side_effect=socket.gaierror("fixture")))
        self.assertEqual(error.exception.code, "substack_feed_unavailable")

    def test_pinned_transport_is_get_only_even_when_called_directly(self):
        resolver = Mock()
        with self.assertRaises(AlphaError):
            _pinned_public_feed_get("POST", PUBLICATION + "/feed", resolver=resolver)
        with self.assertRaises(AlphaError):
            _pinned_public_feed_get("GET", PUBLICATION, resolver=resolver)
        resolver.assert_not_called()

    def test_dns_is_resolved_once_tls_keeps_hostname_and_headers_exclude_secrets(self):
        resolver = resolver_for(PUBLIC_IP)
        raw_socket, tls, conn, upstream = Mock(), Mock(), Mock(), Mock()
        conn._context = tls
        conn.getresponse.return_value = upstream
        upstream.status = 200
        upstream.read.return_value = rss()
        upstream.getheaders.return_value = [("Content-Type", "application/rss+xml")]
        with patch("postriff_phase2.substack.ssl.create_default_context", return_value=tls) as default_tls, \
             patch("postriff_phase2.substack.http.client.HTTPSConnection", return_value=conn) as https, \
             patch("postriff_phase2.substack.socket.create_connection", return_value=raw_socket) as connect:
            result = _pinned_public_feed_get("GET", PUBLICATION + "/feed",
                                             headers={"Authorization": "Bearer secret", "Cookie": "session=secret"}, resolver=resolver)
        self.assertEqual(result["status"], 200)
        resolver.assert_called_once_with("pianoresearch.substack.com", 443, type=socket.SOCK_STREAM)
        connect.assert_called_once_with((PUBLIC_IP, 443), timeout=10)
        default_tls.assert_called_once_with()
        https.assert_called_once_with("pianoresearch.substack.com", timeout=10, context=tls)
        tls.wrap_socket.assert_called_once_with(raw_socket, server_hostname="pianoresearch.substack.com")
        args, kwargs = conn.request.call_args
        self.assertEqual(args, ("GET", "/feed"))
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertNotIn("Cookie", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Accept-Encoding"], "identity")
        upstream.read.assert_called_once_with(MAX_FEED_BYTES + 1)
        conn.close.assert_called_once_with()

    def test_tls_failure_closes_raw_socket_and_connection(self):
        raw_socket, tls, conn = Mock(), Mock(), Mock()
        tls.wrap_socket.side_effect = ssl.SSLError("fixture TLS failure")
        conn._context = tls
        with patch("postriff_phase2.substack.ssl.create_default_context", return_value=tls), \
             patch("postriff_phase2.substack.http.client.HTTPSConnection", return_value=conn), \
             patch("postriff_phase2.substack.socket.create_connection", return_value=raw_socket), \
             self.assertRaises(AlphaError) as error:
            _pinned_public_feed_get("GET", PUBLICATION + "/feed", resolver=resolver_for(PUBLIC_IP))
        self.assertEqual(error.exception.status, 503)
        raw_socket.close.assert_called_once_with()
        conn.close.assert_called_once_with()


class SubstackManualHandoffTests(unittest.TestCase):
    def test_manual_export_cannot_be_an_approval_publish_or_provider_schedule_receipt(self):
        draft = {"title": "Practice", "body": "Review this draft.", "scheduledFor": "2026-10-19T12:00:00-04:00",
                 "autoPublished": True, "providerReceipt": "forged", "status": "published", "approved": True}
        handoff = build_manual_handoff(PUBLICATION, draft)
        self.assertEqual(handoff["status"], "manual_action_required")
        self.assertEqual(handoff["scheduledFor"], "2026-10-19T16:00:00+00:00")
        self.assertEqual(handoff["schedulingMode"], "rafii_editorial_reminder")
        self.assertIs(handoff["autoPublished"], False)
        self.assertIs(handoff["providerScheduled"], False)
        self.assertIsNone(handoff["providerReceipt"])
        self.assertNotIn("approved", handoff)
        self.assertEqual(len(handoff["contentHash"]), 64)

    def test_hash_binds_destination_content_audience_and_editorial_time(self):
        draft = {"title": "Practice", "body": "Review this draft."}
        original = build_manual_handoff(PUBLICATION, draft)["contentHash"]
        self.assertEqual(original, build_manual_handoff(PUBLICATION + "/feed", draft)["contentHash"])
        changes = [{"title": "Another"}, {"body": "Changed"}, {"audience": "paid"},
                   {"contentType": "note"}, {"format": "plain_text"}, {"scheduledFor": "2026-10-19T16:00:00Z"}]
        for change in changes:
            self.assertNotEqual(original, build_manual_handoff(PUBLICATION, {**draft, **change})["contentHash"])
        self.assertNotEqual(original, build_manual_handoff("https://different.substack.com", draft)["contentHash"])

    def test_content_is_a_text_payload_with_escaped_preview(self):
        body = '<script>alert("danger")</script>\n[Link](javascript:alert(1))'
        result = build_manual_handoff(PUBLICATION, {"title": "Plain text", "body": body})
        self.assertEqual(result["renderAs"], "text")
        self.assertEqual(result["body"], body)
        self.assertNotIn("<script>", result["bodyHtmlEscaped"])
        self.assertIn("&lt;script&gt;", result["bodyHtmlEscaped"])

    def test_handoff_preserves_reviewed_body_exactly_and_notes_need_no_title(self):
        body = "  Reviewed text\r\nSecond line.  \n"
        result = build_manual_handoff(PUBLICATION, {"body": body, "contentType": "note"})
        self.assertEqual(result["title"], "")
        self.assertEqual(result["body"], body)
        with self.assertRaises(AlphaError):
            build_manual_handoff(PUBLICATION, {"body": body, "contentType": "article"})

    def test_media_handoff_is_text_preparation_and_requires_manual_media(self):
        for content_type in ("podcast", "video"):
            result = build_manual_handoff(PUBLICATION, {"title": "Practice", "body": "Show notes", "contentType": content_type, "audience": "everyone"})
            self.assertIs(result["mediaPreparationRequired"], True)
            self.assertIs(result["autoPublished"], False)
            self.assertIn("add and review the required media", result["instructions"])
            self.assertEqual(result["audience"], "everyone")
        legacy = build_manual_handoff(PUBLICATION, {"title": "Practice", "body": "Draft", "audience": "all"})
        self.assertEqual(legacy["audience"], "everyone")

    def test_malformed_empty_and_unsupported_drafts_fail(self):
        valid = {"title": "Piano", "body": "Draft"}
        attacks = [None, [], {**valid, "body": ""}, {**valid, "body": "x\x00y"},
                   {**valid, "title": "Hidden\nAction"}, {**valid, "body": "\ud800"},
                   {**valid, "body": "x" * 200001}, {**valid, "format": "html"},
                   {**valid, "contentType": "unsupported_media"}, {**valid, "audience": "all_email_addresses"},
                   {**valid, "scheduledFor": "tomorrow"}, {**valid, "scheduledFor": "2026-10-19T12:00:00"}]
        for value in attacks:
            with self.subTest(draft=str(value)[:70]), self.assertRaises(AlphaError):
                build_manual_handoff(PUBLICATION, value)


class SubstackMetricProvenanceTests(unittest.TestCase):
    def test_imported_metrics_keep_source_time_and_are_not_official(self):
        metric = normalize_imported_metric("subscriber_count", 123, observed_at="2026-10-18T12:00:00-04:00", source="User-provided export.csv")
        self.assertEqual(metric["provenance"], "imported")
        self.assertIs(metric["verifiedOfficial"], False)
        self.assertEqual(metric["observedAt"], "2026-10-18T16:00:00+00:00")
        self.assertEqual(metric["source"], "User-provided export.csv")
        self.assertEqual(METRIC_PROVENANCE, {"verified_official", "imported", "derived", "unavailable"})

    def test_unavailable_is_null_not_a_fabricated_zero(self):
        metric = unavailable_metric("notes_views", "No authorized official metric contract.")
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["provenance"], "unavailable")
        self.assertIs(metric["verifiedOfficial"], False)

    def test_metric_type_and_timestamp_ambiguity_are_rejected(self):
        for value in (True, None, "123", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(AlphaError):
                normalize_imported_metric("count", value, observed_at="2026-10-18T12:00:00Z", source="export.csv")
        with self.assertRaises(AlphaError):
            normalize_imported_metric("count", 3, observed_at="2026-10-18", source="export.csv")
        with self.assertRaises(AlphaError):
            normalize_imported_metric("../secret", 3, observed_at="2026-10-18T12:00:00Z", source="export.csv")


if __name__ == "__main__":
    unittest.main()
