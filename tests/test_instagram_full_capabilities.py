import unittest
from types import SimpleNamespace

from postriff_phase2.audience import AudienceService
from postriff_phase2.contracts import digest
from postriff_phase2.growth.metric_schedule import MetricScheduler
from postriff_phase2.hosted_social import HostedSocial
from postriff_phase2.oauth import OAuthService
from postriff_phase2.providers import InstagramProvider


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, args=()):
        self.executed.append((sql, args))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class InstagramFullCapabilityTests(unittest.TestCase):
    def adapter(self):
        adapter = InstagramProvider("client", "secret", transport=lambda *_args, **_kwargs: {"status": 200, "body": {}})
        self.assertFalse(adapter.production_reviewed)
        self.assertTrue(adapter.account_scoped_direct)
        return adapter

    def test_grant_preserves_verified_contracts_without_promoting_unverified_insights(self):
        adapter = self.adapter()
        granted = [
            "instagram_business_basic",
            "instagram_business_content_publish",
            "instagram_business_manage_insights",
            "instagram_business_manage_comments",
        ]
        matrix = OAuthService._capabilities(adapter, "comments_read", granted, [], 1234, "token")
        for capability in ("publish", "schedule", "comments_read", "reply"):
            self.assertEqual(matrix[capability]["level"], "Direct", capability)
        self.assertEqual(matrix["analytics"]["level"], "Unsupported")

    def test_metric_scheduler_accepts_account_scoped_instagram_grant(self):
        adapter = self.adapter()
        scheduler = MetricScheduler(None, SimpleNamespace(providers={"instagram": adapter}), transport=None)
        self.assertTrue(scheduler.provider_allowed("instagram"))

    def test_hosted_social_accepts_account_scoped_instagram_provider(self):
        adapter = self.adapter()
        social = HostedSocial(SimpleNamespace(), {"instagram": adapter})
        self.assertIs(social._provider({"platform": "Instagram"}), adapter)

    def test_instagram_comment_ingestion_uses_instagram_graph(self):
        cur = Cursor(rows=[("Direct",)])
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"status": 200, "body": {"data": [{"id": "comment-1", "text": "Nice", "username": "reader"}]}}

        oauth = SimpleNamespace(token_for_worker=lambda *_: {"accessToken": "token"})
        audience = AudienceService(None, oauth, lambda: 1, transport=transport)
        outcome = audience.ingest_replies(cur, "workspace", "connection", "instagram", "media-1", 1)
        self.assertEqual(outcome, {"availability": "available", "ingested": 1})
        self.assertEqual(calls[0][0], "GET")
        self.assertIn("graph.instagram.com", calls[0][1])
        self.assertIn("/media-1/comments?", calls[0][1])

    def test_instagram_approved_reply_uses_comment_reply_endpoint(self):
        manifest = {
            "provider": "instagram",
            "connectionId": "connection",
            "replyToCommentId": "comment-1",
            "text": "Thanks!",
        }
        approval = {"requiresReconfirmation": False, "manifest": manifest, "digest": digest(manifest)}
        cur = Cursor(rows=[(approval,)])
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"status": 200, "body": {"id": "reply-1"}}

        oauth = SimpleNamespace(token_for_worker=lambda *_: {"accessToken": "token"})
        audience = AudienceService(None, oauth, lambda: 1, transport=transport, reply_sender_enabled=True)
        outcome = audience.send_approved(cur, "workspace", "draft-1", 1)
        self.assertEqual(outcome["state"], "submitted")
        self.assertEqual(outcome["reference"], "reply-1")
        self.assertEqual(calls[0][0], "POST")
        self.assertIn("graph.instagram.com", calls[0][1])
        self.assertIn("/comment-1/replies", calls[0][1])
        self.assertEqual(calls[0][2]["form"]["message"], "Thanks!")


if __name__ == "__main__":
    unittest.main()
