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


if __name__ == "__main__":
    unittest.main()
