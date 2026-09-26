import unittest

from postriff_phase2.growth import backfill as B
from postriff_phase2.growth import history_import as H


class Listing(unittest.TestCase):
    def test_threads_page_uses_query_token_and_keeps_only_caption_length(self):
        seen = []
        def transport(method, url, **kw):
            seen.append((url, kw))
            return {"status": 200, "body": {"data": [{"id": "1", "timestamp": "2026-09-20T10:00:00+0000", "text": "你好", "permalink": "https://www.threads.net/p/1"},
                                                     {"id": "2", "timestamp": "bad", "permalink": "javascript:alert(1)"}, "junk"],
                                            "paging": {"cursors": {"after": "C"}, "next": "https://n"}}}
        page = H.list_page(transport, "threads", "tok", "PREV")
        self.assertIn("/me/threads?", seen[0][0])
        self.assertIn("access_token=tok", seen[0][0])
        self.assertIn("after=PREV", seen[0][0])
        self.assertEqual(page["next"], "C")
        first, second = page["posts"]
        self.assertEqual(first["captionChars"], 2)
        self.assertEqual(set(first) & {"text", "caption", "captionSha256"}, set())   # no text, no guessable hash
        self.assertIsNone(second["publishedAt"])
        self.assertIsNone(second["permalink"])

    def test_instagram_page_uses_bearer_header_and_last_page_has_no_cursor(self):
        seen = []
        def transport(method, url, **kw):
            seen.append((url, kw))
            return {"status": 200, "body": {"data": [], "paging": {"cursors": {"after": "C"}}}}
        page = H.list_page(transport, "instagram", "tok")
        self.assertNotIn("tok", seen[0][0])
        self.assertEqual(seen[0][1]["headers"], {"Authorization": "Bearer tok"})
        self.assertIsNone(page["next"])

    def test_next_page_without_a_usable_cursor_is_incomplete_but_keeps_posts(self):
        post = {"id": "9", "timestamp": "2026-09-20T10:00:00+0000"}
        for paging in ({"next": "https://n"}, {"next": "https://n", "cursors": {"after": ""}}, {"next": "https://n", "cursors": []}):
            with self.subTest(paging=paging):
                page = H.list_page(lambda *a, **k: {"status": 200, "body": {"data": [post], "paging": paging}}, "threads", "t")
                self.assertEqual((page["incomplete"], page["next"], len(page["posts"])), (True, None, 1))
        for paging in ("junk", {"cursors": None}, {}):
            with self.subTest(last_page=paging):
                page = H.list_page(lambda *a, **k: {"status": 200, "body": {"data": [post], "paging": paging}}, "threads", "t")
                self.assertEqual((page["incomplete"], page["next"]), (False, None))

    def test_non_200_raises_with_status(self):
        with self.assertRaises(H.HistoryHTTP) as ctx:
            H.list_page(lambda *a, **k: {"status": 429}, "threads", "t")
        self.assertEqual(ctx.exception.status, 429)
        with self.assertRaises(ValueError):
            H.list_page(lambda *a, **k: {}, "linkedin", "t")

    def test_flag_needs_metric_reads_too(self):
        self.assertFalse(H.enabled({H.FLAG: "1"}))
        self.assertTrue(H.enabled({H.FLAG: "1", "POSTRIFF_METRIC_READS": "1"}))


class Purge(unittest.TestCase):
    def test_marking_is_one_insert_and_never_breaks_the_disconnect(self):
        class Cur:
            def __init__(self, fail):
                self.sql, self.fail = [], fail
            def execute(self, sql, params=None):
                self.sql.append(sql)
                if self.fail and "INSERT INTO public.pr_growth_purges" in sql:
                    raise RuntimeError("secret-bearing failure")
            def fetchone(self):
                return (True,)
        ok = Cur(False)
        H.mark_for_purge(ok, "w", "c")
        work = [q for q in ok.sql if not q.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK", "SELECT to_regclass"))]
        self.assertEqual(len(work), 1)                      # no run, reading or post locks inside the disconnect
        self.assertIn("attempts=0", work[0])
        self.assertNotIn("requested_at=now()", work[0])     # keeps when the purge was first owed
        broken = Cur(True)
        with self.assertLogs("postriff.growth.metric_reads", "WARNING") as logs:
            self.assertIsNone(H.mark_for_purge(broken, "w", "c"))
        self.assertTrue(any(q.startswith("ROLLBACK TO SAVEPOINT") for q in broken.sql))
        self.assertIn('"event": "history_import.purge_mark_failed"', logs.output[0])
        self.assertNotIn("secret-bearing", logs.output[0])

    def test_post_commit_purge_and_sweep_never_raise(self):
        def broken():
            raise RuntimeError("database down")
        with self.assertLogs("postriff.growth.metric_reads", "WARNING"):
            self.assertEqual(H.purge_after_disconnect(broken, "w", "c")["status"], "unavailable")
        with self.assertLogs("postriff.growth.metric_reads", "WARNING"):
            self.assertEqual(H.sweep_pending_purges(broken)["status"], "unavailable")


class Backfill(unittest.TestCase):
    def test_candidates_window_platform_and_verification(self):
        now = 1_000_000_000.0
        state = {"phase2": {"jobs": [
            {"id": "a", "providerReference": "p", "verification": {"at": now - 86400}, "manifest": {"platform": "Instagram", "channelId": "c"}},
            {"id": "b", "providerReference": "p2", "verification": {"at": now - 91 * 86400}, "manifest": {"platform": "Threads", "channelId": "c"}},
            {"id": "c", "providerReference": None, "verification": {"at": now}, "manifest": {"platform": "Threads", "channelId": "c"}},
            {"id": "d", "providerReference": "p3", "verification": {"at": now}, "manifest": {"platform": "LinkedIn", "channelId": "c"}},
            "junk"]}}
        self.assertEqual(B.candidates(state, now), [("a", "c", "instagram", "p", now - 86400)])
        self.assertEqual(B.candidates({}, now), [])

    def test_cli_requires_database_url_and_bounds_days(self):
        import io
        out = io.StringIO()
        self.assertEqual(B.main([], env={}, out=out), 2)
        self.assertEqual(B.main(["--days", "120"], env={}, out=out), 2)


if __name__ == "__main__":
    unittest.main()
