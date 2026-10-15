"""RAPv2 acceptance matrix, the rows that need no database (2026-10-15).

Each test names the matrix row(s) it answers (RAP-nnn, tests/acceptance-matrix.json in the RAPv2 delivery packet). The
database-backed rows are tests/phase2/postgres_rapv2_acceptance.py. A row the shipped code does not meet is an
`expectedFailure` here, so CI stays green while the gap is open and fails as an unexpected success once it closes.
Synthetic identities only; no provider is called.
"""
import io
import json
import logging
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_phase2 import account_protection  # noqa: E402
from postriff_phase2.email import Mailer, NullTransport  # noqa: E402
from postriff_phase2.hosted_app import HostedApplication, supabase_verifier  # noqa: E402
from postriff_phase2.notifications import email_render  # noqa: E402

AT = 1_791_996_977.0  # 2026-10-14T16:56:17Z
BASE = "https://app.rafii.example"
SESSION = "session-acceptance-0123456789"
USER_ID = base.PRINCIPAL


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        self.hrefs += [value for name, value in attrs if name in ("href", "src") and value]


def links(html, text):
    parser = Links()
    parser.feed(html)
    return parser.hrefs + re.findall(r"https?://\S+", text)


def legacy_alert(device="Safari on iPhone", zone="America/Los_Angeles"):
    transport = NullTransport()
    Mailer(transport, "Rafii <security@rafii.example>", BASE).new_device("person@example.invalid", device, AT, f"{BASE}/app/account/profile", time_zone=zone)
    return transport.sent[0]


def v2_alert(locale="en", href="/app/account/profile", device="Safari on iPhone"):
    return email_render.render("security_alert", locale=locale, values={"title": "New sign-in to your account"}, base_url=BASE, href=href,
                               transactional=True, details=[("Browser", device), ("Time", account_protection.security_time(AT, "America/Los_Angeles", numeric=True))])


class Labels(unittest.TestCase):
    def test_rap029_a_generic_mozilla_agent_is_never_the_classification(self):
        for agent, label in {"Mozilla/5.0": "Unrecognized browser", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)": "Browser on Mac",
                             "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36": "Chrome on Mac"}.items():
            with self.subTest(agent=agent):
                self.assertEqual(account_protection.browser_label(agent), label)
                self.assertNotIn("Mozilla", account_protection.browser_label(agent))

    def test_rap030_rap125_no_or_garbage_agent_is_unrecognized_with_no_invented_hardware(self):
        for agent in (None, "", "   ", "\x00\x01", "x" * 5000, "<img src=x onerror=alert(1)>", "() { :; }; /bin/sh"):
            with self.subTest(agent=repr(agent)[:20]):
                self.assertEqual(account_protection.browser_label(agent), account_protection.UNRECOGNIZED)


class SecurityEmail(unittest.TestCase):
    SECRETS = (SESSION, USER_ID, "203.0.113.7", "eyJhbGciOi", "sb-access-token", "123456")

    def test_rap072_no_session_id_ip_token_cookie_or_otp_in_either_alert(self):
        # The alert's inputs are only the label, the time and the profile link: nothing else can reach the body.
        for mail in (legacy_alert(), v2_alert()):
            body = mail["text"] + mail["html"] + mail["subject"]
            for secret in self.SECRETS:
                self.assertNotIn(secret, body)
            self.assertNotIn("person@example.invalid", mail.get("html", "") + mail.get("text", ""))

    def test_rap073_rap136_the_call_to_action_is_the_canonical_app_link(self):
        self.assertIn(f"{BASE}/app/account/profile", legacy_alert()["text"])
        for href in ("https://evil.example/app/account/profile", "//evil.example/x", "javascript:alert(1)", "/app/account/profile"):
            with self.subTest(href=href):
                rendered = v2_alert(href=href)
                self.assertTrue(rendered["url"].startswith(BASE + "/app"), rendered["url"])
                hosts = {re.match(r"https?://([^/]+)", link).group(1) for link in links(rendered["html"], rendered["text"]) if link.startswith("http")}
                self.assertEqual(hosts, {"app.rafii.example"}, hosts)

    def test_rap074_markup_in_the_user_agent_never_reaches_the_email(self):
        label = account_protection.browser_label('Mozilla/5.0 <script>alert(1)</script><a href="https://evil.example">x</a>')
        for mail in (legacy_alert(device=label), v2_alert(device="<script>alert(1)</script>")):
            self.assertNotIn("<script>", mail["html"])
            self.assertNotIn("evil.example", mail["html"] + mail["text"])

    def test_rap075_pacific_daylight_time_in_october(self):
        for mail in (legacy_alert(), v2_alert()):
            for body in (mail["text"], mail["html"]):
                self.assertIn("09:56 PDT", body)
                self.assertNotIn("PST", body)

    def test_rap122_indianapolis_uses_its_own_offset_and_dst(self):
        self.assertEqual(account_protection.security_time(AT, "America/Indiana/Indianapolis"),
                         "14 October 2026, 12:56 EDT (America/Indiana/Indianapolis) · 16:56 UTC")
        self.assertEqual(account_protection.security_time(1_799_946_000.0, "America/Indiana/Indianapolis"),
                         "14 January 2027, 12:00 EST (America/Indiana/Indianapolis) · 17:00 UTC")

    def test_rap124_simplified_chinese_renders_its_own_copy_and_unknown_locales_fall_back_explicitly(self):
        hans = v2_alert(locale="zh-CN")
        self.assertIn('lang="zh-Hans"', hans["html"])
        self.assertNotIn("{", hans["subject"] + hans["text"])
        self.assertNotEqual(hans["subject"], v2_alert(locale="en")["subject"])
        fallback = v2_alert(locale="tlh")
        self.assertIn('lang="en"', fallback["html"])
        self.assertEqual(fallback["subject"], v2_alert(locale="en")["subject"])

    def test_rap130_no_credential_email_or_user_id_in_any_link(self):
        from postriff_phase2.notifications.sms import acknowledgement_path
        delivery = "6f1c2a3b-0000-4000-8000-00000000abcd"
        mails = [legacy_alert(), v2_alert(href=acknowledgement_path("/app/account/profile", delivery))]
        for mail in mails:
            for link in links(mail["html"], mail["text"]):
                with self.subTest(link=link[:60]):
                    for secret in (*self.SECRETS, "person@example.invalid", "token=", "access_token", "code="):
                        self.assertNotIn(secret, link)

    def test_rap076_no_location_is_invented(self):
        for mail in (legacy_alert(), v2_alert()):
            for place in ("Los Angeles", "California", "United States", "Hong Kong", "near "):
                self.assertNotIn(place, mail["text"].replace("America/Los_Angeles", ""))


class Hygiene(unittest.TestCase):
    def app(self):
        def get_user(url, access_token):
            return {"status": 200, "body": {"id": USER_ID, "email_confirmed_at": "2026-10-01T00:00:00Z"}}

        verify = supabase_verifier("https://project.supabase.co", "p" * 24, None, get_user=get_user)
        cursor = base.FakeCursor([((True,), 1), (("", None, "", "", False), 1), *base.STYLE_READ])
        return HostedApplication(base.service(cursor, verify), None, {"provider": "supabase"}, "c" * 24)

    def test_rap129_an_authenticated_request_logs_no_token_session_or_user(self):
        access = base.jwt({"sub": USER_ID, "session_id": SESSION, "aal": "aal1"})
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        previous = root.level
        root.setLevel(logging.DEBUG)
        try:
            status, body = base.invoke(self.app(), "GET", "/api/me", headers={"Authorization": "Bearer " + access, "User-Agent": "Mozilla/5.0 (iPhone) Safari/605.1"})
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        self.assertEqual(status, 200)
        logged = stream.getvalue()
        self.assertIn("request.completed", logged)
        for secret in (access, access.split(".")[1], SESSION, USER_ID, "Bearer"):
            self.assertNotIn(secret, logged)

    def test_rap145_api_me_keeps_every_field_older_clients_read(self):
        access = base.jwt({"sub": USER_ID, "session_id": SESSION, "aal": "aal1"})
        status, body = base.invoke(self.app(), "GET", "/api/me", headers={"Authorization": "Bearer " + access})
        self.assertEqual(status, 200)
        self.assertLessEqual({"userId", "displayName", "sessionId", "mfa", "preferences"}, set(body))
        self.assertLessEqual({"available", "enforced", "enforcedAt", "aal"}, set(body["mfa"]))
        self.assertLessEqual({"timeZone", "locale", "alertNewDevice"}, set(body["preferences"]))

    def test_rap131_no_fingerprinting_or_cross_site_tracking_in_the_web_sources(self):
        forbidden = re.compile(r"OfflineAudioContext|WEBGL_debug_renderer_info|navigator\.plugins|hardwareConcurrency|deviceMemory|"
                               r"fingerprintjs|clientjs|googletagmanager|google-analytics\.com|connect\.facebook\.net|\bfbq\(|\bgtag\(")
        hits = [f"{path.relative_to(ROOT)}:{match.group(0)}" for path in (ROOT / "web" / "src").rglob("*") if path.suffix in (".ts", ".tsx", ".js", ".mjs")
                for match in [forbidden.search(path.read_text(errors="ignore"))] if match]
        self.assertEqual(hits, [])
        dependencies = json.loads((ROOT / "web" / "package.json").read_text())
        names = {*dependencies.get("dependencies", {}), *dependencies.get("devDependencies", {})}
        self.assertEqual({name for name in names if re.search(r"fingerprint|clientjs|evercookie", name)}, set())


class SecurityCenterRevokeUI(unittest.TestCase):
    CARD = (ROOT / "web" / "src" / "features" / "account" / "security-card.tsx").read_text()

    def test_rap058_the_current_session_has_no_revoke_button(self):
        # Both revoke affordances (row button and its menu) are rendered only for other, live sessions.
        self.assertEqual(self.CARD.count("!session.current && !session.revoked"), 3)
        self.assertIn("This device stays signed in.", self.CARD)

    @unittest.expectedFailure
    def test_rap057_single_revoke_says_provider_refresh_coverage_is_unknown(self):
        # The API denies the session id at once, but a single revoke does not revoke Supabase's refresh token and the
        # card never says so (nor shows revoke-others' refreshRevoked). Known gap: recorded FAIL in the results.
        revoke_ui = self.CARD[self.CARD.index("async function revoke(sessionId"):self.CARD.index("return (", self.CARD.index("async function revokeOthers"))]
        self.assertRegex(revoke_ui + self.CARD, r"refreshRevoked|refresh token|until (it|they) (next )?refresh")


class RevokeOthersCoverage(unittest.TestCase):
    def revoke(self, identity):
        cursor = base.FakeCursor([(None, 2), (None, 1)])
        svc = base.service(cursor, base.verifier(), identity=identity)
        svc.repository.assert_fresh = lambda token, principal: None
        return svc.revoke_other_sessions("t")

    def test_rap056_provider_refresh_revocation_is_reported_not_assumed(self):
        class Refused(base.FakeIdentity):
            def logout_others(self, access_token):
                return False

        self.assertEqual(self.revoke(Refused([]))["refreshRevoked"], False)
        self.assertEqual(self.revoke(base.FakeIdentity([]))["refreshRevoked"], True)
        self.assertEqual(self.revoke(None)["refreshRevoked"], False)  # no identity admin: never claimed


if __name__ == "__main__":
    unittest.main()
