"""No network: bounded post discovery and provider page parsing for Inbox refresh."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.audience_sync import eligible_posts, parse_threads_page


class InboxSyncContract(unittest.TestCase):
    def test_only_recent_verified_posts_for_exact_connection(self):
        now = 10_000_000
        jobs = [
            {"state": "verified", "manifest": {"platform": "Threads", "channelId": "a"}, "providerReference": str(i),
             "verification": {"at": now - i}}
            for i in range(20)
        ]
        jobs += [{"state": "submitted", "manifest": {"platform": "Threads", "channelId": "a"}, "providerReference": "999"},
                 {"state": "verified", "manifest": {"platform": "Threads", "channelId": "b"}, "providerReference": "888"}]
        self.assertEqual(eligible_posts(jobs, "a", "threads", now, limit=3), ["0", "1", "2"])

    def test_repeated_items_dedupe_and_cursor_is_bounded(self):
        page = {"data": [{"id": "1", "text": "hello"}, {"id": "1", "text": "hello"}, {"id": "2", "text": "bye"}],
                "paging": {"cursors": {"after": "x" * 400}}}
        items, cursor = parse_threads_page(page)
        self.assertEqual([item["id"] for item in items], ["1", "2"])
        self.assertIsNone(cursor)

    def test_untrusted_page_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_threads_page({"data": "not a list"})


if __name__ == "__main__":
    unittest.main()
