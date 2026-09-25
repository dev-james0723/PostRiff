"""Transactional email unit tests: templates, NullTransport, ResendTransport, Mailer resilience, trial Reminders."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.email import Mailer, NullTransport, Reminders, ResendTransport

BASE = "https://app.example.test"
CONTEXTS = {
    "invitation": {"inviter_label": "<script>alert(1)</script>", "role": "editor", "accept_url": f"{BASE}/invite/raw-token-123", "expires_at": 1_800_000_000},
    "welcome": {"app_url": f"{BASE}/app"},
    "trial_ending": {"days_left": 3, "expires_at": 1_800_000_000, "pricing_url": f"{BASE}/pricing"},
    "trial_ended": {"pricing_url": f"{BASE}/pricing", "export_note": "<script>x</script> export"},
    "payment_failed": {"grace_until": 1_800_000_000, "billing_url": f"{BASE}/settings/billing"},
    "subscription_activated": {"plan_label": "Studio <script>", "billing_url": f"{BASE}/settings/billing"},
}
LINKS = {"invitation": "accept_url", "welcome": "app_url", "trial_ending": "pricing_url", "trial_ended": "pricing_url", "payment_failed": "billing_url", "subscription_activated": "billing_url"}


def mailer(transport=None):
    return Mailer(transport or NullTransport(), "hello@example.test", BASE)


class Templates(unittest.TestCase):
    def test_every_kind_renders_link_footer_and_escapes(self):
        m = mailer()
        for kind, ctx in CONTEXTS.items():
            subject, text, html = m.render(kind, **ctx)
            link = ctx[LINKS[kind]]
            self.assertIn(link, text, kind)
            self.assertIn(f'href="{link}"', html, kind)
            self.assertIn(f"{BASE}/privacy", text, kind)
            self.assertIn(f"{BASE}/privacy", html, kind)
            self.assertIn("You received this because you have a Rafii account.", text)
            self.assertNotIn("<script>", html, kind)
            if "<script>" in str(ctx):
                self.assertIn("&lt;script&gt;", html, kind)
            self.assertIn('style="max-width:560px', html)
            self.assertNotIn("<img", html)
            self.assertNotIn("\n", subject)

    def test_subject_lines(self):
        m = mailer()
        self.assertEqual(m.render("invitation", **CONTEXTS["invitation"])[0], "You’re invited to a Rafii workspace")
        self.assertEqual(m.render("welcome", **CONTEXTS["welcome"])[0], "Welcome to Rafii")
        self.assertEqual(m.render("trial_ending", **CONTEXTS["trial_ending"])[0], "Your Rafii trial ends in 3 days")
        self.assertEqual(m.render("trial_ended", **CONTEXTS["trial_ended"])[0], "Your Rafii trial has ended")
        self.assertEqual(m.render("payment_failed", **CONTEXTS["payment_failed"])[0], "Action needed: payment failed")
        self.assertEqual(m.render("subscription_activated", plan_label="Studio", billing_url=f"{BASE}/b")[0], "Your Studio plan is active")

    def test_render_rejects_unknown_kind_and_relative_links(self):
        m = mailer()
        with self.assertRaises(AlphaError):
            m.render("newsletter", app_url=f"{BASE}/x")
        with self.assertRaises(AlphaError):
            m.render("welcome", app_url="/app")
        with self.assertRaises(AlphaError):
            m.render("welcome", app_url="javascript:alert(1)")


class Transports(unittest.TestCase):
    def test_null_transport_records(self):
        transport = NullTransport()
        m = Mailer(transport, "hello@example.test", BASE)
        result = m.welcome("  Person@Example.test ", f"{BASE}/app")
        self.assertFalse(result["sent"])
        self.assertEqual(len(transport.sent), 1)
        message = transport.sent[0]
        self.assertEqual(message["to"], "person@example.test")
        self.assertEqual(message["from"], "hello@example.test")
        self.assertEqual(message["tags"], [{"name": "kind", "value": "welcome"}])
        self.assertIn(f"{BASE}/app", message["text"])

    def test_resend_transport_builds_request(self):
        calls = []

        def fake(method, url, headers=None, form=None, body=None):
            calls.append((method, url, headers, form, body))
            return {"status": 200, "headers": {}, "body": {"id": "re_1"}}

        transport = ResendTransport("re_secret_key", transport=fake)
        result = transport.send({"from": "hello@example.test", "to": "a@b.test", "subject": "Hi", "html": "<p>Hi</p>", "text": "Hi", "tags": [{"name": "kind", "value": "welcome"}]})
        self.assertEqual(result, {"id": "re_1"})
        method, url, headers, form, body = calls[0]
        self.assertEqual((method, url, form), ("POST", "https://api.resend.com/emails", None))
        self.assertEqual(headers["Authorization"], "Bearer re_secret_key")
        self.assertEqual(body, {"from": "hello@example.test", "to": ["a@b.test"], "subject": "Hi", "html": "<p>Hi</p>", "text": "Hi", "tags": [{"name": "kind", "value": "welcome"}]})

    def test_resend_transport_maps_failures(self):
        transport = ResendTransport("k", transport=lambda *a, **k: {"status": 422, "headers": {}, "body": {"message": "bad from"}})
        with self.assertRaises(AlphaError) as failed:
            transport.send({"from": "x@y.test", "to": "a@b.test", "subject": "s", "html": "h", "text": "t"})
        self.assertEqual(failed.exception.status, 502)
        self.assertNotIn("bad from", str(failed.exception))
        with self.assertRaises(AlphaError) as unconfigured:
            ResendTransport("")
        self.assertEqual(unconfigured.exception.status, 503)


class Resilience(unittest.TestCase):
    def test_mailer_never_raises(self):
        class Broken:
            def send(self, message):
                raise AlphaError("The email service did not accept this message.", 502)

        m = Mailer(Broken(), "hello@example.test", BASE)
        self.assertEqual(m.invitation("a@b.test", "Sam", "editor", f"{BASE}/invite/t", 1_800_000_000)["sent"], False)
        self.assertEqual(m.payment_failed("a@b.test", 1_800_000_000, f"{BASE}/billing")["sent"], False)
        transport = NullTransport()
        m = Mailer(transport, "hello@example.test", BASE)
        self.assertFalse(m.welcome("not-an-email", f"{BASE}/app")["sent"])
        self.assertFalse(m.welcome("a@b.test", "/relative")["sent"])
        self.assertEqual(transport.sent, [])
        with self.assertRaises(AlphaError):
            Mailer(transport, "", BASE)


class FakeCursor:
    """Records SQL; serves trial rows for the SELECT and enforces dedupe_key uniqueness for the INSERT."""

    def __init__(self, ending=(), ended=()):
        self.ending, self.ended, self.keys, self.executed, self.marked = list(ending), list(ended), set(), [], []
        self._pending = None

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if sql.startswith("SELECT"):
            start, end, limit = params
            rows = [r for r in self.ending + self.ended if start <= r[2] <= end]
            self._pending = ("rows", rows[:limit])
        elif sql.startswith("INSERT"):
            key = params[3]
            self._pending = ("row", None if key in self.keys else (f"n-{len(self.keys)}",))
            self.keys.add(key)
        elif sql.startswith("UPDATE"):
            self.marked.append(params[0])
            self._pending = ("row", None)

    def fetchall(self):
        return self._pending[1] if self._pending and self._pending[0] == "rows" else []

    def fetchone(self):
        return self._pending[1] if self._pending and self._pending[0] == "row" else None


class TrialReminders(unittest.TestCase):
    def test_dedupe_and_missing_email(self):
        now = 1_700_000_000.0
        transport = NullTransport()
        m = Mailer(transport, "hello@example.test", BASE)
        cur = FakeCursor(ending=[("w1", "u1", now + 2.5 * 86400), ("w2", "u2", now + 2.5 * 86400)], ended=[("w3", "u3", now - 3600)])
        reminders = Reminders(m, lambda user_id: None if user_id == "u2" else f"{user_id}@example.test", clock=lambda: now)
        self.assertEqual(reminders.run(cur), {"sent": 0, "skipped": 3})
        self.assertEqual([msg["to"] for msg in transport.sent], ["u1@example.test", "u3@example.test"])
        self.assertIn("ends in 3 days", transport.sent[0]["subject"])
        self.assertIn("has ended", transport.sent[1]["subject"])
        self.assertEqual(len(cur.marked), 0)
        self.assertIn(f"trial_ending:w1:{int(now + 2.5 * 86400)}", cur.keys)
        # Second sweep: every key already exists, nothing is sent again.
        self.assertEqual(reminders.run(cur, now=now), {"sent": 0, "skipped": 3})
        self.assertEqual(len(transport.sent), 2)

    def test_bounded_per_run(self):
        now = 1_700_000_000.0
        transport = NullTransport()
        rows = [(f"w{i}", f"u{i}", now + 2.5 * 86400 + i) for i in range(80)]
        cur = FakeCursor(ending=rows)
        result = Reminders(Mailer(transport, "hello@example.test", BASE), lambda u: f"{u}@example.test", clock=lambda: now).run(cur)
        self.assertEqual(result, {"sent": 0, "skipped": 50})
        self.assertEqual(len(transport.sent), 50)
        # Addresses never reach the notifications ledger.
        self.assertFalse(any("@" in str(params) for _, params in cur.executed))


if __name__ == "__main__":
    unittest.main()
