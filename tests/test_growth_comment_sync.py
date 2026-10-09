"""Bounded comment re-sync inside the native reading step: own posts only, no handles, tombstones kept, fenced."""
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from postriff_phase2.growth import comment_sync as C
from postriff_phase2.growth import metric_schedule as M
from test_growth_metric_schedule import FakeDB, Clock

WID = "267f7d90-b11c-470c-9880-733ea7c1d483"
NOW = 1_760_000_000.0
IG_SCOPES = sorted(M.NATIVE_ANALYTICS_SCOPES["instagram"] | C.COMMENT_SCOPES["instagram"])


def row(**extra):
    return {"id": "r", "workspaceId": WID, "jobId": "job", "connectionId": "ig", "provider": "instagram", "postId": "1789",
            "offset": "t0", "anchorAt": NOW - 60, "attempts": 1, "maxAttempts": 5, **extra}


class Pieces(unittest.TestCase):
    def test_only_young_owned_post_readings_are_due(self):
        self.assertTrue(C.due(row(), NOW))
        self.assertTrue(C.due(row(offset="backfill", anchorAt=NOW - 29 * 86400), NOW))
        self.assertFalse(C.due(row(anchorAt=NOW - 30 * 86400), NOW))
        self.assertFalse(C.due(row(anchorAt=None), NOW))
        self.assertFalse(C.due(row(provider="youtube"), NOW))
        self.assertFalse(C.due({"provider": "instagram", "anchorAt": NOW}, NOW))   # not a scheduled reading

    def test_fetch_asks_for_one_bounded_page_without_author_handles(self):
        seen = []
        def transport(method, url, **kw):
            seen.append((method, url))
            return {"status": 200, "body": {"data": [
                {"id": "c1", "text": "  How do you warm up?  ", "username": "someone", "timestamp": "2026-10-04T22:40:12+0000"},
                {"id": "c2", "text": "x" * 5000},
                {"id": True, "text": "bad id"}, {"text": "no id"}, "junk"]}}
        result = C.fetch(transport, "synthetic-token", "instagram", "1789")
        method, url = seen[0]
        query = parse_qs(urlparse(url).query)
        self.assertEqual((method, urlparse(url).path.endswith("/1789/comments")), ("GET", True))
        self.assertEqual(query["fields"], ["id,text,timestamp"])
        self.assertEqual(query["limit"], [str(C.PAGE_LIMIT)])
        self.assertNotIn("username", url)
        self.assertEqual([c["id"] for c in result["comments"]], ["c1", "c2"])
        self.assertEqual(result["comments"][0]["text"], "How do you warm up?")
        self.assertEqual(len(result["comments"][1]["text"]), C.MAX_TEXT)
        self.assertIsNotNone(result["comments"][0]["at"])
        self.assertTrue(all("username" not in c and "author" not in c for c in result["comments"]))
        self.assertTrue(C.endpoint("threads", "9").endswith("/9/replies"))

    def test_store_is_an_idempotent_upsert_that_never_touches_tombstones(self):
        db = FakeDB(lambda text, params: None)
        C.store(db, WID, "ig", "instagram", "1789", [{"id": "c1", "text": "Hi", "at": None}])
        text, params = db.sql[0]
        self.assertIn("ON CONFLICT(workspace_id,provider,provider_comment_id) DO UPDATE", text)
        self.assertIn("WHERE public.pr_audience_threads.tombstoned_at IS NULL", text)
        self.assertNotIn("author_handle", text)
        self.assertEqual(params[:5], (WID, "ig", "instagram", "1789", "c1"))


class OAuth:
    providers = {"instagram": SimpleNamespace(platform="Instagram", account_scoped_direct=True, execution_enabled=True)}

    def __init__(self, scopes):
        self.scopes = scopes

    def token_for_worker(self, *_):
        return {"accessToken": "synthetic-token", "provider": "instagram", "scopes": self.scopes}


class Scheduler(unittest.TestCase):
    INSIGHTS = {"status": 200, "body": {"data": [{"name": "views", "values": [{"value": 0}]}]}}
    COMMENTS = {"status": 200, "body": {"data": [{"id": "c1", "text": "When is the next recital?"}]}}

    def scheduler(self, scopes=IG_SCOPES, comments_direct=True, comment_reply=None):
        calls = []
        def transport(method, url, **kw):
            calls.append(urlparse(url).path.rsplit("/", 1)[-1])
            if url.split("?")[0].endswith("/comments"):
                if isinstance(comment_reply, Exception):
                    raise comment_reply
                return comment_reply or self.COMMENTS
            return self.INSIGHTS
        db = FakeDB(lambda text, params: [("Direct" if comments_direct else "Unsupported",)] if "capability='comments_read'" in text else [])
        s = M.MetricScheduler(db, OAuth(scopes), transport=transport, workspace_allowlist={WID}, clock=Clock(NOW), env={})
        s._eligible = lambda r: "read"
        return s, calls

    def test_a_due_reading_also_reads_one_comment_page(self):
        s, calls = self.scheduler()
        outcome = s.read(row(), {})
        self.assertEqual(outcome["state"], "done")
        self.assertEqual(calls, ["insights", "comments"])
        self.assertEqual(outcome["comments"], [{"id": "c1", "text": "When is the next recital?", "at": None}])

    def test_no_comment_scope_no_direct_capability_or_an_old_post_means_no_comment_call(self):
        for case in ("scope", "capability", "old"):
            with self.subTest(case=case):
                s, calls = self.scheduler(scopes=sorted(M.NATIVE_ANALYTICS_SCOPES["instagram"]) if case == "scope" else IG_SCOPES,
                                          comments_direct=case != "capability")
                outcome = s.read(row(anchorAt=NOW - 31 * 86400, offset="backfill") if case == "old" else row(), {})
                self.assertEqual(outcome["state"], "done")
                self.assertEqual(calls, ["insights"])
                self.assertIsNone(outcome.get("comments"))

    def test_a_failing_comment_page_never_fails_the_reading(self):
        s, calls = self.scheduler(comment_reply=RuntimeError("provider said no"))
        outcome = s.read(row(), {})
        self.assertEqual((outcome["state"], outcome.get("comments")), ("done", None))
        s, _ = self.scheduler(comment_reply={"status": 403, "body": {}})
        self.assertIsNone(s.read(row(), {}).get("comments"))

    def completion(self, comments_direct_at_commit):
        def answer(text, params):
            if text.startswith("SELECT state ? 'accountDeletion'"):
                return [(False,)]
            if "FROM public.pr_encrypted_credentials" in text:
                return [("instagram", IG_SCOPES)]
            if "capability='analytics'" in text:
                return [("Direct",)]
            if "capability='comments_read'" in text:
                return [("Direct" if comments_direct_at_commit else "Unsupported",)]
            if "to_regclass('public.pr_growth_purges')" in text:
                return [(False,)]
            if text.startswith("UPDATE public.pr_metric_reads"):
                return [(1,)]
            return None
        db = FakeDB(answer)
        s = M.MetricScheduler(db, OAuth(IG_SCOPES), transport=None, workspace_allowlist={WID}, clock=Clock(NOW), env={})
        s.provider_allowed = lambda provider: True
        outcome = {"state": "done", "found": {"views": 0}, "endpoint": "x", "readAt": NOW,
                   "comments": [{"id": "c1", "text": "Hi", "at": None}]}
        self.assertTrue(s.complete(row(), outcome))
        return db, outcome

    def test_comments_are_stored_only_inside_the_fenced_completion_and_a_revoke_blocks_them(self):
        db, outcome = self.completion(True)
        statements = [t for t, _ in db.sql]
        upsert = next(i for i, t in enumerate(statements) if t.startswith("INSERT INTO public.pr_audience_threads"))
        fence = next(i for i, t in enumerate(statements) if t.startswith("UPDATE public.pr_metric_reads SET status='done'"))
        self.assertGreater(upsert, fence)
        self.assertTrue(any("capability='comments_read' FOR SHARE" in t for t in statements))
        self.assertEqual(outcome["commentsStored"], 1)
        db, outcome = self.completion(False)
        self.assertFalse([t for t, _ in db.sql if t.startswith("INSERT INTO public.pr_audience_threads")])
        self.assertTrue([t for t, _ in db.sql if t.startswith("INSERT INTO public.pr_metric_observations")])
        self.assertEqual(outcome.get("commentsStored", 0), 0)


if __name__ == "__main__":
    unittest.main()
