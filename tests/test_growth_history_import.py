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


class Stage3B(unittest.TestCase):
    def test_provider_overdelivery_is_bounded_and_malformed_data_is_not_completion(self):
        response = {"status": 200, "body": {"data": [{"id": str(i), "text": "private caption"} for i in range(500)]}}
        page = H.list_page(lambda *a, **k: response, "threads", "synthetic")
        self.assertEqual(len(page["posts"]), 25)
        self.assertTrue(all(set(p) == {"id", "publishedAt", "mediaType", "mediaProductType", "permalink", "captionChars"} for p in page["posts"]))
        self.assertNotIn("private caption", str(page))
        with self.assertRaises(H.HistoryHTTP):
            H.list_page(lambda *a, **k: {"status": 200, "body": {"data": {"wrong": []}}}, "threads", "synthetic")

    def test_completed_bounds_never_fetch_another_page(self):
        from unittest.mock import Mock
        importer = H.HistoryImporter(None, Mock(), transport=Mock())
        importer._eligible = Mock(return_value=True)
        importer._finish = Mock()
        run = {"id": "r", "workspaceId": "w", "connectionId": "c", "createdAt": 1, "cursor": None, "pages": 12, "posts": 300}
        self.assertEqual(importer.run_one(run, 999999), "done")
        importer.transport.assert_not_called()

    def test_provider_consent_describes_owned_history_with_metadata_only_retention_and_separate_confirmation(self):
        from postriff_phase2.providers import ThreadsProvider, InstagramProvider
        for provider in (ThreadsProvider, InstagramProvider):
            copy = provider.EXPLAIN["analytics"]
            self.assertNotIn("posts it created", copy)
            for word in ("90 days", "300 posts", "12 pages", "never caption text", "caption hashes", "Disconnecting", "alone does not start"):
                self.assertIn(word, copy)

    def test_default_off_requires_both_exact_flags(self):
        for env in ({}, {H.FLAG: "0", "POSTRIFF_METRIC_READS": "1"}, {H.FLAG: "1", "POSTRIFF_METRIC_READS": "0"}, {H.FLAG: "true", "POSTRIFF_METRIC_READS": "1"}):
            self.assertFalse(H.enabled(env))

class HistoryImportHTTP(unittest.TestCase):
    def test_gate_and_route_do_not_request_history_on_a_read_or_when_off(self):
        import io, json
        from types import SimpleNamespace
        from unittest.mock import Mock
        from postriff_phase2.hosted_app import HostedApplication
        history = Mock()
        history.status.return_value = {'status':'none'}
        history.request.return_value = {'status':'pending'}
        service = SimpleNamespace(oauth=SimpleNamespace(), history_import=history)
        app = HostedApplication(service, public_auth={})
        def call(method, body=None):
            raw=json.dumps(body).encode() if body is not None else b''
            environ={'REQUEST_METHOD':method,'PATH_INFO':'/api/workspaces/w/channels/c/history-import','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'wsgi.url_scheme':'https','HTTP_HOST':'rafii.example','HTTP_ORIGIN':'https://rafii.example','HTTP_AUTHORIZATION':'Bearer '+ 'i'*32,'HTTP_X_POSTRIFF_REQUEST':'founder-alpha'}
            captured={}
            result=b''.join(app(environ,lambda status,headers:captured.update(status=status))).decode()
            return captured['status'],json.loads(result)
        self.assertEqual(call('GET'), ('200 OK', {'status':'none'}))
        history.request.assert_not_called()

        self.assertEqual(call('POST',{'confirmed':True}), ('202 Accepted', {'status':'pending'}))
        history.request.assert_called_once_with('w','i'*32,'c',{'confirmed':True})
        del service.history_import
        history.reset_mock()
        for method in ('GET','POST'):
            status,body=call(method,{'confirmed':True} if method=='POST' else None)
            self.assertEqual(status,'404 Not Found')
            self.assertEqual(body['code'],'feature_disabled')
        history.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
