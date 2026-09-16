"""Milestone D unit tests: fixture webhook signing, privacy notice/rights/diagnostics, insights rules, routes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights, privacy
from postriff_phase2.billing import FixturePaymentProvider
from postriff_phase2.hosted_app import HostedApplication
from test_postriff_phase2_hosted import FakeService, FakeWorker, invoke


class Webhooks(unittest.TestCase):
    def test_fixture_provider_signature_and_shape(self):
        provider = FixturePaymentProvider("s")
        body = json.dumps({"id": "e1", "type": "subscription.activated", "createdAt": 1, "workspaceId": "w"}).encode()
        self.assertEqual(provider.parse_webhook(provider.sign(body), body)["id"], "e1")
        with self.assertRaises(AlphaError):
            provider.parse_webhook("nope", body)
        with self.assertRaises(AlphaError):
            provider.parse_webhook(provider.sign(b"{}"), b"{}")


class Privacy(unittest.TestCase):
    def test_notice_rights_and_sanitized_diagnostics(self):
        notice = privacy.notice()
        self.assertIn("legal review", notice["status"])
        self.assertIn("provider_tokens", notice["retention"])
        with self.assertRaises(AlphaError):
            privacy.rights_declaration({"ownsOrLicensed": False})
        self.assertTrue(privacy.rights_declaration({"ownsOrLicensed": True, "aiGenerated": True})["aiGenerated"])
        state = {"sources": [{"text": "SECRET BODY"}], "variants": [{"text": "DRAFT BODY"}], "phase2": {"channels": [{"platform": "LinkedIn"}], "jobs": [{"state": "scheduled"}], "assets": []}}
        package = privacy.diagnostics_package(state, True, "w")
        self.assertNotIn("SECRET BODY", json.dumps(package))
        self.assertEqual(package["counts"]["sources"], 1)
        with self.assertRaises(AlphaError):
            privacy.diagnostics_package(state, False, "w")


class Insights(unittest.TestCase):
    def test_rates_and_comparison_rules(self):
        self.assertEqual(insights.rate(None, 10)["display"], "Unavailable")
        self.assertEqual(insights.rate(5, 0)["display"], "undefined (denominator 0)")
        self.assertEqual(insights.rate(5, 20)["value"], "1/4")
        cohort = {"provider": "threads", "language": "English", "contentTypeId": "t", "definitionVersion": "2026-09"}
        posts = [{"cohort": cohort, "metrics": {"views": {"value": v}}} for v in (10, 20, None)]
        self.assertEqual(insights.compare(posts, "views")["interpretation"], "insufficient_sample")
        posts.append({"cohort": cohort, "metrics": {"views": {"value": 30}}})
        result = insights.compare(posts, "views")
        self.assertEqual((result["interpretation"], result["mean"], result["missing"]), ("observation_only", "20", 1))
        with self.assertRaises(AlphaError):
            insights.compare(posts + [{"cohort": {**cohort, "language": "繁體中文"}, "metrics": {}}], "views")


class FakeAudience:
    def threads(self, w, t): return {"threads": [], "limits": "x"}
    def draft_reply(self, w, t, thread, body): return {"draftId": "d1", "origin": body.get("origin", "manual")}
    def reply_preview(self, w, t, d): return {"digest": "abc", "action": "Send this reply as @x"}
    def approve_reply(self, w, t, d, digest, confirmed): return {"draftId": d, "status": "approved" if confirmed and digest == "abc" else "draft"}


class FakeRequests:
    def list(self, w, t): return {"requests": []}


class Routes(unittest.TestCase):
    def test_usage_privacy_analytics_audience_routes(self):
        service = FakeService()
        service.usage = lambda w, t: {"entitlement": {"writingBatchesRemaining": 9}, "overage": "stop"}
        service.data_requests = FakeRequests()
        service.data_request = lambda w, t, kind, body: {"kind": kind, "status": "completed"}
        service.analytics = lambda w, t: {"state": "limited", "posts": []}
        service.audience = FakeAudience()
        service.billing_webhook = lambda sig, raw: {"outcome": "applied" if sig == "ok" else "rejected"}
        app = HostedApplication(service, FakeWorker(), {"provider": "dev", "flow": "dev"}, "c" * 24)
        auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}
        status, _, catalog = invoke(app, "GET", "/api/catalog")
        self.assertEqual((status, catalog["authMode"]), (200, "dev"))
        status, _, usage = invoke(app, "GET", "/api/workspaces/w/usage", headers=auth)
        self.assertEqual((status, usage["overage"]), (200, "stop"))
        status, _, notice = invoke(app, "GET", "/api/privacy/notice")
        self.assertEqual((status, "retention" in notice), (200, True))
        status, _, req = invoke(app, "POST", "/api/workspaces/w/data-requests", {"kind": "export"}, auth)
        self.assertEqual((status, req["kind"]), (201, "export"))
        status, _, analytics = invoke(app, "GET", "/api/workspaces/w/analytics/summary", headers=auth)
        self.assertEqual((status, analytics["state"]), (200, "limited"))
        status, _, draft = invoke(app, "POST", "/api/workspaces/w/audience/threads/th1/reply-drafts", {"origin": "ai_fixture"}, auth)
        self.assertEqual((status, draft["origin"]), (201, "ai_fixture"))
        status, _, approved = invoke(app, "POST", "/api/workspaces/w/audience/reply-drafts/d1/reply", {"digest": "abc", "confirmed": True}, auth)
        self.assertEqual((status, approved["status"]), (200, "approved"))
        status, _, hook = invoke(app, "POST", "/api/billing/webhook", {"id": "e"}, {"X-PostRiff-Billing-Signature": "ok"})
        self.assertEqual((status, hook["outcome"]), (200, "applied"))



class LiveBillingRoutes(unittest.TestCase):
    """Checkout/portal routes are owner mutations behind the application guard; the webhook prefers Stripe's header;
    the cron tick now carries the reminder sweep. The service is faked; the real gate logic lives in the PG script."""

    def setUp(self):
        self.service = FakeService()
        self.app = HostedApplication(self.service, FakeWorker(), {"provider": "supabase", "flow": "pkce"}, "c" * 24)
        self.auth = {"Authorization": "Bearer " + "t" * 32, "X-PostRiff-Request": "founder-alpha"}

    def test_checkout_and_portal_routes(self):
        status, _, session = invoke(self.app, "POST", "/api/workspaces/w/billing/checkout", {"planTermsId": "assist-v1", "successPath": "/app/account/billing?ok=1"}, self.auth)
        self.assertEqual((status, session["url"], session["plan"], session["success"]), (201, "https://checkout.stripe.test/s", "assist-v1", "/app/account/billing?ok=1"))
        status, _, refused = invoke(self.app, "POST", "/api/workspaces/w/billing/checkout", {"planTermsId": "studio-v1"}, self.auth)
        self.assertEqual((status, "not yet available" in refused["error"]), (409, True))
        status, _, portal = invoke(self.app, "POST", "/api/workspaces/w/billing/portal", {"returnPath": "/app/account/billing"}, self.auth)
        self.assertEqual((status, portal["url"]), (200, "https://billing.stripe.test/p"))
        status, _, none = invoke(self.app, "POST", "/api/workspaces/w/billing/portal", {"returnPath": "/nowhere"}, self.auth)
        self.assertEqual((status, "No billing account" in none["error"]), (409, True))
        status, _, _ = invoke(self.app, "POST", "/api/workspaces/w/billing/checkout", {"planTermsId": "assist-v1"}, {"Authorization": "Bearer " + "t" * 32})
        self.assertEqual(status, 403)  # application guard on mutations
        status, _, _ = invoke(self.app, "POST", "/api/workspaces/w/billing/unknown", {}, self.auth)
        self.assertEqual(status, 404)

    def test_webhook_prefers_stripe_signature_header(self):
        seen = {}
        self.service.billing_webhook = lambda sig, raw: seen.setdefault("sig", sig) or {"outcome": "ignored"}
        status, _, _ = invoke(self.app, "POST", "/api/billing/webhook", {"id": "evt_1", "type": "charge.refunded"}, {"Stripe-Signature": "t=1,v1=abc", "X-PostRiff-Billing-Signature": "legacy"})
        self.assertEqual((status, seen["sig"]), (200, "t=1,v1=abc"))

    def test_cron_tick_includes_reminder_sweep(self):
        status, _, result = invoke(self.app, "GET", "/api/cron/worker", headers={"Authorization": "Bearer " + "c" * 24})
        self.assertEqual((status, result["reminders"], result["processed"]), (200, {"sent": 0, "skipped": 0}, 0))


class DisabledProvider(unittest.TestCase):
    def test_disabled_provider_refuses_every_webhook_and_is_the_default_without_stripe(self):
        from postriff_phase2.billing import DisabledPaymentProvider
        from postriff_phase2.hosted_app import billing_from_environment
        with self.assertRaises(AlphaError) as refused:
            DisabledPaymentProvider().parse_webhook("t=1,v1=x", b"{}")
        self.assertEqual(refused.exception.status, 503)
        provider, mailer = billing_from_environment({})
        self.assertEqual((provider.id, type(mailer.transport).__name__), ("disabled", "NullTransport"))
        provider, mailer = billing_from_environment({"STRIPE_SECRET_KEY": "sk", "STRIPE_WEBHOOK_SECRET": "wh", "RESEND_API_KEY": "re", "EMAIL_FROM": "PostRiff <hello@postriff.test>", "POSTRIFF_PUBLIC_BASE_URL": "https://app.postriff.test/"})
        self.assertEqual((provider.id, type(mailer.transport).__name__, mailer.public_base_url), ("stripe", "ResendTransport", "https://app.postriff.test"))
        with self.assertRaises(ValueError):
            billing_from_environment({"RESEND_API_KEY": "re"})


if __name__ == "__main__":
    unittest.main()
