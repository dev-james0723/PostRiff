"""Only the proven Threads Inbox adapter may issue synthetic comment/reply calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.inbox_providers import adapter_for


class InboxProviderAdapter(unittest.TestCase):
    def test_unsupported_provider_has_no_adapter(self):
        self.assertIsNone(adapter_for("instagram"))
        self.assertIsNone(adapter_for("linkedin"))

    def test_threads_page_and_two_step_reply_are_bounded(self):
        adapter = adapter_for("threads")
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"status": 200, "body": {"id": "777" if url.endswith("/threads") else "789", "data": []}}

        adapter.list_comments("123", "synthetic", transport, after="cursor", limit=50)
        self.assertIn("after=cursor", calls[0][1])
        self.assertEqual(adapter.send_reply({"providerAccountId": "111", "replyToCommentId": "456", "text": "Thanks"}, "synthetic", transport)["state"], "submitted")
        self.assertEqual([call[0] for call in calls], ["GET", "POST", "POST"])

    def test_permission_refusal_and_inconclusive_publish_are_fenced(self):
        adapter = adapter_for("threads")
        manifest = {"providerAccountId": "111", "replyToCommentId": "456", "text": "Thanks"}
        calls = []

        def refused(method, url, **kwargs):
            calls.append(url)
            return {"status": 403, "body": {}}

        self.assertEqual(adapter.send_reply(manifest, "synthetic", refused)["state"], "held")
        self.assertEqual(len(calls), 1)

        def inconclusive(method, url, **kwargs):
            calls.append(url)
            return {"status": 200 if url.endswith("/threads") else 503, "body": {"id": "777"} if url.endswith("/threads") else {}}

        self.assertEqual(adapter.send_reply(manifest, "synthetic", inconclusive)["state"], "uncertain")
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
