"""The cron.completed log line carries what each coworker step did as statuses, exception type names and counts, and
never a workspace id, a query, a reason or other text."""
import json
import unittest

from postriff_phase2.coworker import runtime


class CronSummaryTest(unittest.TestCase):
    def test_steps_become_statuses_and_counts_without_ids_or_text(self):
        result = {
            "notifications": {"status": "ok", "scanned": 3, "delivery": {"sent": 2, "failed": 0, "note": "x"}},
            "weekly": {"prepared": [{"workspaceId": "4f1c-secret-ws", "recipeId": "r1", "state": "ready_for_review"},
                                    {"workspaceId": "9a2b-secret-ws", "recipeId": "r2", "error": "Choose a connected account for Ms Chan's recital"}],
                       "stoppedEarly": True},
            "learning": {"error": "TypeError"},
            "listening": {"workspaces": [{"workspaceId": "4f1c-secret-ws", "skipped": "not_due"}, {"workspaceId": "7c3d-secret-ws", "new": 2}]},
            "retention": {"productEventsRemoved": 12},
            "odd": {"error": "a message, not a type", "reason": "the coworker cron budget is used up", "query": "piano recital Hong Kong"},
            "deferred": "not a dict",
        }
        summary = runtime.summary(result)
        self.assertEqual(summary["notifications"], {"status": "ok", "scanned": 3, "delivery": {"sent": 2, "failed": 0}})
        self.assertEqual(summary["weekly"], {"prepared": {"count": 2, "outcomes": {"state:ready_for_review": 1, "error": 1}}, "stoppedEarly": True})
        self.assertEqual(summary["learning"], {"error": "TypeError"})
        self.assertEqual(summary["listening"], {"workspaces": {"count": 2, "outcomes": {"skipped:not_due": 1, "done": 1}}})
        self.assertEqual(summary["retention"], {"productEventsRemoved": 12})
        self.assertEqual(summary["odd"], {"error": "error"})
        self.assertNotIn("deferred", summary)
        logged = json.dumps(summary)
        for secret in ("secret-ws", "r1", "Ms Chan", "piano", "budget is used up", "a message"):
            self.assertNotIn(secret, logged)

    def test_nothing_to_summarize(self):
        self.assertEqual(runtime.summary(None), {})
        self.assertEqual(runtime.summary({"status": "disabled"}), {"status": "disabled"})
        self.assertEqual(runtime.summary({"status": "unavailable", "error": "ImportError"}), {"status": "unavailable", "error": "ImportError"})


if __name__ == "__main__":
    unittest.main()
