"""Notification core, HTML email, Web Push and webhooks (adaptive coworker spec §14-§18; architecture lock N1-N5, E1-E2).

Deterministic and offline: the planner's decisions (recipients, urgency, quiet hours across DST, digests, mute,
unsubscribe, transactional exceptions, rate limits), every email template in every shipped locale, RFC 8291/8292
Web Push with an independent decryption, the push-endpoint allowlist, Svix webhook verification and signed
unsubscribe tokens, and the detector's publish-truth mapping.
"""
import base64
import json
import os
import re
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from postriff_phase2.coworker import flags
from postriff_phase2.notifications import catalog, detector, email_render, planner, push, webhooks
from postriff_phase2.permissions import Membership

REQUIRED_EVENTS = ("campaign.week_ready", "campaign.drafts_ready", "campaign.approval_required", "campaign.blocked", "research.needs_input", "asset.review_required",
                   "publish.scheduled", "publish.verified", "publish.failed", "publish.uncertain", "automation.completed", "automation.failed",
                   "channel.reconnect_required", "engagement.needs_attention", "opportunity.detected", "analytics.weekly_ready", "analytics.anomaly_detected",
                   "learning.preference_proposed", "budget.threshold_reached", "billing.payment_failed", "billing.trial_ending", "billing.subscription_active",
                   "security.new_device", "security.account_change")
BASE = "https://app.rafii.example"


def at(zone, *parts):
    return datetime(*parts, tzinfo=ZoneInfo(zone)).timestamp()


def member(user, role, **flags_):
    return {"userId": user, "membership": Membership(role, flags_), "active": True, "time_zone": None}


class CatalogTest(unittest.TestCase):
    def test_every_required_event_family_is_catalogued_with_a_template(self):
        for event in REQUIRED_EVENTS:
            spec = catalog.spec(event)
            self.assertIn(spec["category"], catalog.CATEGORIES, event)
            self.assertIn(spec["template"], email_render.TEMPLATES, event)
            self.assertIn(spec["audience"], catalog.AUDIENCES, event)

    def test_defaults_follow_the_spec(self):
        for event in ("publish.failed", "publish.uncertain", "campaign.approval_required", "channel.reconnect_required", "billing.payment_failed", "security.new_device"):
            self.assertEqual(catalog.spec(event)["email"], "immediate", event)
        self.assertEqual(catalog.spec("publish.verified")["email"], "digest")       # never one email per post
        self.assertEqual(catalog.spec("publish.verified")["push"], "off")
        self.assertEqual((catalog.spec("campaign.week_ready")["email"], catalog.spec("campaign.week_ready")["push"]), ("immediate", "immediate"))
        for event in ("opportunity.detected", "learning.preference_proposed"):
            self.assertEqual((catalog.spec(event)["email"], catalog.spec(event)["push"]), ("digest", "off"), event)


class PlannerTest(unittest.TestCase):
    def plan(self, event_type, prefs=None, now=None, push_available=True, recent=None, zone="Asia/Hong_Kong"):
        event = {"event_type": event_type, "workspace_id": "ws1"}
        return {r["channel"]: r for r in planner.plan(event, {"userId": "u1", "time_zone": zone}, prefs or {}, now or at(zone, 2026, 9, 24, 14, 0),
                                                         push_available=push_available, recent=recent)}

    def test_routine_success_goes_to_the_digest_and_centre_only(self):
        plan = self.plan("publish.verified")
        self.assertEqual(plan["in_app"]["status"], "delivered")
        self.assertEqual(plan["email"]["mode"], "digest")
        self.assertNotIn("push", plan)

    def test_failures_are_immediate_on_every_channel(self):
        plan = self.plan("publish.failed")
        self.assertEqual((plan["email"]["mode"], plan["email"]["status"]), ("immediate", "pending"))
        self.assertEqual(plan["push"]["status"], "pending")

    def test_preference_precedence_is_most_specific_first(self):
        rows = {("*", "*"): {"email_mode": "off"}, ("ws1", "approvals"): {"email_mode": "immediate"}, ("ws1", "*"): {"email_mode": "digest"}}
        self.assertEqual(planner.effective_preferences(rows, "ws1", "approvals")["email_mode"], "immediate")
        self.assertEqual(planner.effective_preferences(rows, "ws1", "publishing")["email_mode"], "digest")
        self.assertEqual(planner.effective_preferences(rows, "ws2", "publishing")["email_mode"], "off")

    def test_quiet_hours_defer_push_and_routine_email_in_the_persons_zone(self):
        prefs = {("*", "*"): {"quiet_start": 22 * 60, "quiet_end": 7 * 60, "time_zone": "Europe/London"}}
        night = at("Europe/London", 2026, 9, 24, 23, 30)
        plan = self.plan("campaign.approval_required", prefs, night, zone="Europe/London")
        wake = datetime.fromtimestamp(plan["push"]["next_attempt_at"], ZoneInfo("Europe/London"))
        self.assertEqual((wake.hour, wake.minute, wake.day), (7, 0, 25))
        self.assertEqual(plan["push"]["reason"], "quiet_hours")
        self.assertGreater(plan["email"]["next_attempt_at"], night)             # action email waits too
        critical = self.plan("publish.failed", prefs, night, zone="Europe/London")
        self.assertEqual(critical["email"]["next_attempt_at"], night)            # a failure email is not held back
        self.assertGreater(critical["push"]["next_attempt_at"], night)           # but it does not buzz at night

    def test_quiet_hours_end_is_correct_across_a_dst_change(self):
        prefs = {("*", "*"): {"quiet_start": 22 * 60, "quiet_end": 7 * 60, "time_zone": "America/New_York"}}
        # 2026-11-01 02:00 EDT → 01:00 EST. At 23:00 on 31 October the window ends at 07:00 EST on 1 November.
        night = at("America/New_York", 2026, 10, 31, 23, 0)
        wake = planner.quiet_end_after(night, prefs[("*", "*")])
        local = datetime.fromtimestamp(wake, ZoneInfo("America/New_York"))
        self.assertEqual((local.month, local.day, local.hour, local.minute, local.utcoffset().total_seconds()), (11, 1, 7, 0, -5 * 3600))
        self.assertEqual(wake - night, 9 * 3600)                                 # 8 wall-clock hours + the repeated hour
        spring = planner.quiet_end_after(at("America/New_York", 2027, 3, 13, 23, 0), prefs[("*", "*")])
        self.assertEqual(datetime.fromtimestamp(spring, ZoneInfo("America/New_York")).hour, 7)

    def test_security_breaks_quiet_hours_and_cannot_be_unsubscribed(self):
        prefs = {("*", "*"): {"quiet_start": 0, "quiet_end": 1439, "email_unsubscribed": True, "email_mode": "off", "time_zone": "UTC"}}
        now = at("UTC", 2026, 9, 24, 12, 0)
        plan = planner.plan({"event_type": "security.new_device", "workspace_id": None}, {"userId": "u1"}, prefs, now)
        email = next(r for r in plan if r["channel"] == "email")
        self.assertEqual((email["status"], email["next_attempt_at"]), ("pending", now))

    def test_unsubscribe_and_mute_suppress_non_transactional_mail(self):
        now = at("UTC", 2026, 9, 24, 12, 0)
        unsub = self.plan("campaign.week_ready", {("*", "*"): {"email_unsubscribed": True}}, now)
        self.assertEqual((unsub["email"]["status"], unsub["email"]["reason"]), ("suppressed", "unsubscribed"))
        muted = self.plan("publish.failed", {("*", "*"): {"muted_until": now + 3600}}, now)
        self.assertEqual((muted["email"]["status"], muted["push"]["status"]), ("suppressed", "suppressed"))
        self.assertEqual(muted["in_app"]["status"], "delivered")
        billing = self.plan("billing.payment_failed", {("*", "*"): {"muted_until": now + 3600, "email_unsubscribed": True}}, now)
        self.assertEqual(billing["email"]["status"], "pending")                   # transactional exception

    def test_push_needs_an_explicit_subscription(self):
        plan = self.plan("publish.failed", push_available=False)
        self.assertEqual((plan["push"]["status"], plan["push"]["reason"]), ("suppressed", "no_subscription"))

    def test_rate_limits_downgrade_instead_of_dropping(self):
        plan = self.plan("campaign.approval_required", recent={"email": 12, "push": 6})
        self.assertEqual((plan["email"]["mode"], plan["email"]["status"]), ("digest", "pending"))
        self.assertEqual(plan["push"]["reason"], "rate_limited")
        critical = self.plan("publish.failed", recent={"push": 6})
        self.assertEqual(critical["push"]["status"], "pending")

    def test_digest_is_scheduled_at_the_local_digest_hour(self):
        now = at("Asia/Hong_Kong", 2026, 9, 24, 14, 0)
        plan = self.plan("publish.verified", now=now)
        local = datetime.fromtimestamp(plan["email"]["next_attempt_at"], ZoneInfo("Asia/Hong_Kong"))
        self.assertEqual((local.day, local.hour), (25, catalog.DIGEST_HOUR))
        weekly = self.plan("publish.verified", {("*", "*"): {"digest_frequency": "weekly"}}, now)
        local = datetime.fromtimestamp(weekly["email"]["next_attempt_at"], ZoneInfo("Asia/Hong_Kong"))
        self.assertEqual((local.weekday(), local.hour), (0, catalog.DIGEST_HOUR))
        off = self.plan("publish.verified", {("*", "*"): {"digest_frequency": "off"}}, now)
        self.assertEqual(off["email"]["status"], "suppressed")

    def test_recipients_come_from_permissions_not_from_the_event(self):
        people = [member("owner", "owner"), member("editor", "editor"), member("approver", "approver"), member("viewer", "viewer"), member("pub", "editor", can_publish=True)]
        ids = lambda event, actor=None: sorted(m["userId"] for m in planner.audience(people, {"event_type": event}, actor))  # noqa: E731
        self.assertEqual(ids("campaign.approval_required"), ["approver", "owner", "pub"])
        self.assertEqual(ids("billing.payment_failed"), ["owner"])
        self.assertEqual(ids("security.new_device", "editor"), ["editor"])
        self.assertNotIn("viewer", ids("campaign.week_ready"))


class EmailTest(unittest.TestCase):
    LOCALES = ("en", "zh-Hant-HK", "zh-Hant", "zh-Hans", "yue-Hant-HK")

    def test_every_template_renders_in_every_locale_with_one_cta_and_a_text_twin(self):
        for template in email_render.TEMPLATES:
            for locale in self.LOCALES:
                with self.subTest(template=template, locale=locale):
                    out = email_render.render(template, locale=locale, values={"platform": "LinkedIn", "count": 4, "weekOf": "2026-09-28", "recipe": "Weekly",
                                                                                 "title": "Something", "reason": "A reason", "endsAt": "1 October", "planName": "Pro", "why": "It matches"},
                                              base_url=BASE, href="/app/queue", workspace_name="Harbour Bakery", unsubscribe_url=BASE + "/api/notifications/unsubscribe?token=x")
                    self.assertEqual(out["html"].count('class="rf-cta-a"'), 1)
                    self.assertIn(BASE + "/app/queue", out["text"])
                    self.assertNotIn("\n", out["subject"])
                    self.assertNotIn("{", out["subject"] + out["preheader"] + out["text"])
                    self.assertEqual(out["templateVersion"], email_render.TEMPLATE_VERSION)
                    self.assertIn('name="color-scheme" content="light dark"', out["html"])
                    self.assertIn("<h1", out["html"])
                    self.assertLess(len(out["html"].encode()), 102_000)            # Gmail clips above ~102 KB
                    self.assertIn(f'lang="{email_render.resolve_locale(locale)}"', out["html"])

    def test_values_are_escaped_and_links_stay_on_the_app(self):
        out = email_render.render("publish_failed", values={"platform": "<script>alert(1)</script>", "reason": "\"><img src=x onerror=alert(1)>"},
                                  base_url=BASE, href="javascript:alert(1)")
        self.assertNotIn("<script>", out["html"])
        self.assertNotIn("<img", out["html"])
        self.assertEqual(out["url"], BASE + "/app")
        external = email_render.render("publish_failed", base_url=BASE, href="https://evil.example/app")
        self.assertEqual(external["url"], BASE + "/app")
        with self.assertRaises(ValueError):
            email_render.render("publish_failed", base_url="http://insecure.example")

    def test_subject_and_preheader_carry_no_private_content(self):
        private = "Our Q4 launch draft says revenue grew 212%"
        out = email_render.render("weekly_ready", values={"count": 3, "weekOf": "2026-09-28", "title": private, "reason": private}, base_url=BASE, href="/app/weekly")
        self.assertNotIn("212", out["subject"] + out["preheader"])

    def test_unsubscribe_headers_only_for_non_transactional_mail(self):
        url = BASE + "/api/notifications/unsubscribe?token=abc"
        routine = email_render.render("weekly_ready", base_url=BASE, unsubscribe_url=url)
        self.assertEqual(routine["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        security = email_render.render("security_alert", base_url=BASE, unsubscribe_url=url, transactional=True, values={"title": "A new device signed in"})
        self.assertEqual(security["headers"], {})
        self.assertNotIn("token=abc", security["html"])

    def test_locale_resolution(self):
        self.assertEqual([email_render.resolve_locale(x) for x in ("en-GB", "zh-TW", "zh-HK", "yue-Hant-HK", "zh-CN", "zh-Hans-SG", "fr")],
                         ["en", "zh-Hant", "zh-Hant-HK", "zh-Hant-HK", "zh-Hans", "zh-Hans", "en"])


class PushTest(unittest.TestCase):
    def subscription(self):
        receiver = ec.generate_private_key(ec.SECP256R1())
        public = receiver.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        auth = b"0123456789abcdef"
        return receiver, {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "p256dh": push.b64u(public), "auth": push.b64u(auth)}

    def test_rfc8291_round_trip(self):
        receiver, sub = self.subscription()
        body = push.payload("Rafii", "A post couldn't be published", "/app/queue?job=1", "publish", "publishing")
        encrypted = push.encrypt(body, sub["p256dh"], sub["auth"])
        self.assertEqual(int.from_bytes(encrypted[16:20], "big"), push.RECORD_SIZE)
        self.assertEqual(push.decrypt(encrypted, receiver, sub["auth"]), body)

    def test_vapid_header_is_a_verifiable_es256_jwt(self):
        keys = push.generate_vapid_keys()
        vapid = push.Vapid(keys["privateKey"], keys["publicKey"], "mailto:ops@rafii.example")
        header = vapid.authorization("https://fcm.googleapis.com/fcm/send/abc", now=1_800_000_000)
        token, key = re.match(r"vapid t=([^,]+), k=(.+)$", header).groups()
        head, claims, signature = token.split(".")
        payload = json.loads(push.unb64u(claims))
        self.assertEqual(payload["aud"], "https://fcm.googleapis.com")
        self.assertEqual(payload["sub"], "mailto:ops@rafii.example")
        self.assertLessEqual(payload["exp"] - 1_800_000_000, 24 * 3600)
        raw = push.unb64u(signature)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64u(key))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_endpoint_allowlist_blocks_internal_and_unknown_hosts(self):
        for good in ("https://fcm.googleapis.com/fcm/send/x", "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/Q", "https://db5p.notify.windows.com/w/?token=x"):
            self.assertTrue(push.endpoint_allowed(good), good)
        for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://169.254.169.254/latest", "https://evil.example/fcm.googleapis.com",
                    "https://fcm.googleapis.com.evil.example/x", "https://user@fcm.googleapis.com/x"):
            self.assertFalse(push.endpoint_allowed(bad), bad)

    def test_payload_is_minimal_and_same_origin(self):
        body = json.loads(push.payload("Rafii", "x" * 500, "https://evil.example", "t", "c"))
        self.assertEqual(body["url"], "/app")
        self.assertLessEqual(len(body["body"]), 120)
        self.assertEqual(set(body), {"title", "body", "url", "tag", "category"})

    def test_transport_outcomes(self):
        _, sub = self.subscription()
        keys = push.generate_vapid_keys()
        vapid = push.Vapid(keys["privateKey"], keys["publicKey"], "mailto:ops@rafii.example")
        for status, headers, state in ((201, {}, "sent"), (410, {}, "gone"), (404, {}, "gone"), (429, {"retry-after": "120"}, "transient"), (403, {}, "config"),
                                       (413, {}, "permanent"), (None, {}, "uncertain"), (503, {}, "transient")):
            sent = []
            transport = push.WebPushTransport(vapid, post=lambda url, h, body, s=status, hd=headers: sent.append((url, h, body)) or {"status": s, "headers": hd})
            result = transport.send(sub, b'{"title":"t"}', urgency="high", topic="publish:job-1")
            self.assertEqual(result["state"], state, status)
            self.assertEqual(sent[0][1]["Content-Encoding"], "aes128gcm")
            self.assertTrue(sent[0][1]["Authorization"].startswith("vapid t="))
            self.assertNotIn(b"title", sent[0][2])                              # the body on the wire is encrypted
        blocked = push.WebPushTransport(vapid, post=lambda *a: self.fail("an unlisted endpoint must never be called")).send({**sub, "endpoint": "https://10.0.0.5/x"}, b"{}")
        self.assertEqual(blocked["state"], "permanent")


class WebhookTest(unittest.TestCase):
    SIGNING = "whsec_" + base64.b64encode(os.urandom(32)).decode()  # generated per run

    def test_verified_event_is_parsed(self):
        body = json.dumps({"type": "email.delivered", "data": {"email_id": "re_1", "tags": [{"name": "delivery_id", "value": "d1"}]}}).encode()
        headers = webhooks.sign_svix(self.SIGNING, "msg_1", int(time.time()), body)
        self.assertEqual(webhooks.verify_svix(self.SIGNING, headers, body)["type"], "email.delivered")

    def test_tampered_stale_or_unsigned_bodies_are_rejected(self):
        body = b'{"type":"email.bounced"}'
        now = int(time.time())
        headers = webhooks.sign_svix(self.SIGNING, "msg_2", now, body)
        from postriff_alpha.domain import AlphaError
        for bad_headers, bad_body in ((headers, body + b" "), (webhooks.sign_svix(self.SIGNING, "msg_2", now - 3600, body), body),
                                      ({**headers, "svix-signature": "v1,AAAA"}, body), ({"svix-id": "x"}, body),
                                      (webhooks.sign_svix("whsec_" + base64.b64encode(b"another-key-that-is-32-bytes!!!!").decode(), "msg_2", now, body), body)):
            with self.assertRaises(AlphaError) as caught:
                webhooks.verify_svix(self.SIGNING, bad_headers, bad_body)
            self.assertEqual(caught.exception.status, 401)

    def test_unsubscribe_token(self):
        key = webhooks.signing_key({"POSTRIFF_CREDENTIAL_KEY": "k" * 44})
        token = webhooks.unsubscribe_token(key, "u1", "ws1", "weekly", now=1_000)
        self.assertEqual(webhooks.read_unsubscribe_token(key, token, now=2_000), {"userId": "u1", "scope": "ws1", "category": "weekly"})
        from postriff_alpha.domain import AlphaError
        with self.assertRaises(AlphaError):
            webhooks.read_unsubscribe_token(key, token[:-2] + ("AA" if not token.endswith("AA") else "BB"), now=2_000)
        with self.assertRaises(AlphaError):
            webhooks.read_unsubscribe_token(key, token, now=1_000 + 181 * 86400)


class DetectorTest(unittest.TestCase):
    def state(self, job_state, attempts=1):
        return {"phase2": {"channels": [{"id": "c1", "platform": "LinkedIn", "account": "Studio page", "expiresAt": 0}],
                           "jobs": [{"id": "j1", "state": job_state, "attempts": [{}] * attempts, "events": [{"message": "LinkedIn rejected the post"}],
                                     "manifest": {"channelId": "c1"}}], "reviews": [{"id": "r1", "status": "needs_review", "manifest": {"channelId": "c1"}}]}}

    def test_only_verified_is_published(self):
        types = lambda s: {e["event_type"] for e in detector.from_state("ws", self.state(s), 1_000) if e.get("entity_type") == "job"}  # noqa: E731
        self.assertEqual(types("verified"), {"publish.verified"})
        self.assertEqual(types("published"), set())
        self.assertEqual(types("provider_accepted"), set())
        self.assertEqual(types("uncertain"), {"publish.uncertain"})
        self.assertEqual(types("failed"), {"publish.failed"})
        self.assertEqual(types("held"), {"campaign.blocked"})
        self.assertEqual(types("scheduled"), {"publish.scheduled"})

    def test_dedupe_keys_follow_the_state_version(self):
        first = next(e for e in detector.from_state("ws", self.state("failed", 1), 1_000) if e["event_type"] == "publish.failed")
        again = next(e for e in detector.from_state("ws", self.state("failed", 1), 2_000) if e["event_type"] == "publish.failed")
        retried = next(e for e in detector.from_state("ws", self.state("failed", 2), 2_000) if e["event_type"] == "publish.failed")
        self.assertEqual(first["dedupe_key"], again["dedupe_key"])
        self.assertNotEqual(first["dedupe_key"], retried["dedupe_key"])

    def test_reviews_reconnects_and_weeks(self):
        state = self.state("scheduled")
        state["phase2"]["channels"].append({"id": "c2", "platform": "Threads", "connectionState": "token_expired"})
        state["coworker"] = {"weekly": {"weeks": [{"id": "wk1", "state": "ready_for_review", "weekOf": "2026-09-28", "slots": [{}, {}]}]}}
        kinds = {e["event_type"] for e in detector.from_state("ws", state, 1_000)}
        self.assertTrue({"campaign.approval_required", "channel.reconnect_required", "campaign.week_ready"} <= kinds)


class LegacyEmailBridgeTest(unittest.TestCase):
    def tearDown(self):
        flags.attach(None)

    def test_v2_owns_automation_and_billing_notices_but_not_invitations(self):
        from postriff_phase2.email import Mailer, NullTransport
        transport = NullTransport()
        mailer = Mailer(transport, "Rafii <no-reply@rafii.example>", BASE)
        flags.attach({"RAFII_NOTIFICATIONS_V2_ENABLED": "1"})
        routed = mailer._deliver("publish_failed", "owner@example.com", automation_name="Weekly", review_url=BASE + "/app")
        self.assertEqual(routed, {"sent": False, "kind": "publish_failed", "reason": "routed_to_notifications_v2"})
        self.assertEqual(transport.sent, [])
        mailer.invitation("new@example.com", "A teammate", "editor", BASE + "/invite", 2_000_000_000)
        self.assertEqual(len(transport.sent), 1)
        flags.attach({})
        mailer._deliver("publish_failed", "owner@example.com", automation_name="Weekly", review_url=BASE + "/app")
        self.assertEqual(len(transport.sent), 2)                                   # flag off: unchanged legacy path

    def test_resend_request_carries_the_idempotency_key_and_list_unsubscribe(self):
        from postriff_phase2.email import ResendTransport
        calls = []
        transport = ResendTransport("re_test_key", transport=lambda method, url, headers=None, body=None: calls.append((headers, body)) or {"status": 200, "body": {"id": "re_1"}})
        receipt = transport.send({"from": "a@rafii.example", "to": "b@example.com", "subject": "s", "html": "<p>x</p>", "text": "x",
                                  "headers": {"List-Unsubscribe": "<https://x>"}, "idempotencyKey": "ntf_abc", "tags": [{"name": "delivery_id", "value": "d1"}]})
        self.assertEqual(receipt, {"id": "re_1"})
        headers, body = calls[0]
        self.assertEqual(headers["Idempotency-Key"], "ntf_abc")
        self.assertEqual(body["headers"], {"List-Unsubscribe": "<https://x>"})


class DeliverabilityCheckTest(unittest.TestCase):
    """The SPF/DKIM/DMARC runbook check, on fixture DNS answers (it never queries DNS in tests)."""
    def setUp(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("dns_check", Path(__file__).resolve().parents[1] / "scripts" / "rafii_email_dns_check.py")
        self.dns = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.dns)

    def test_healthy_domain(self):
        result = self.dns.assess("notify.rafii.example", ["v=spf1 include:amazonses.com ~all"], ["p=MIGfMA0GCSqGSIb3DQEBAQUAA"],
                                 ["v=DMARC1; p=quarantine; rua=mailto:dmarc@rafii.example"])
        self.assertEqual(result["status"], "ok")

    def test_missing_or_weak_records(self):
        result = self.dns.assess("notify.rafii.example", ["v=spf1 include:_spf.google.com ~all", "v=spf1 -all"], [], ["v=DMARC1; p=none"])
        levels = {(f["check"], f["level"]) for f in result["findings"]}
        self.assertIn(("spf", "error"), levels)
        self.assertIn(("dkim", "error"), levels)
        self.assertIn(("dmarc", "warning"), levels)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.dns.organisational("notify.rafii.example"), "rafii.example")


if __name__ == "__main__":
    unittest.main()
