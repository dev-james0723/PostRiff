import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import metric_schedule as M


class Hooks(unittest.TestCase):
    def test_scheduling_runs_after_a_failing_hook_and_the_error_still_reaches_the_worker(self):
        seen = []
        scheduler = SimpleNamespace(on_post_verified=lambda cur, ws, job: seen.append("scheduled"))
        def audience(cur, ws, job):
            raise RuntimeError("replies failed")
        with self.assertRaises(RuntimeError):
            M.then_schedule(audience, scheduler)(None, "ws", {})
        self.assertEqual(seen, ["scheduled"])

    def test_flag_default_off(self):
        self.assertFalse(M.enabled({}))
        self.assertFalse(M.enabled({M.FLAG: "true"}))
        self.assertTrue(M.enabled({M.FLAG: "1"}))

    def test_backoff_is_bounded_and_deterministic(self):
        self.assertEqual(M.backoff("r", 1), M.backoff("r", 1))
        self.assertLess(M.backoff("r", 20), M.MAX_BACKOFF + 30)
        self.assertGreaterEqual(M.backoff("r", 1), 60)


class Read(unittest.TestCase):
    def scheduler(self, reply=None, token_error=None):
        class OAuth:
            providers = {}
            def token_for_worker(self, ws, conn):
                if token_error:
                    raise token_error
                return {"accessToken": "t"}
        def transport(method, url, **kw):
            if isinstance(reply, Exception):
                raise reply
            return reply
        s = M.MetricScheduler(None, OAuth(), transport=transport)
        s._eligible = lambda row: True
        return s

    ROW = {"workspaceId": "w", "connectionId": "c", "provider": "threads", "postId": "p"}

    def test_classification(self):
        cases = [({"status": 200, "body": {"data": []}}, None, "done"),
                 ({"status": 429}, None, "transient"),
                 ({"status": 503}, None, "transient"),
                 ({"status": 403}, None, "unavailable"),
                 (AlphaError("net", 503), None, "transient"),
                 (None, AlphaError("revoked", 404), "unavailable"),
                 (ValueError("odd"), None, "transient")]
        for reply, token_error, expected in cases:
            with self.subTest(reply=reply, token_error=token_error):
                self.assertEqual(self.scheduler(reply, token_error).read(self.ROW, {})["state"], expected)

    def test_a_failing_completion_does_not_stop_the_step(self):
        s = self.scheduler({"status": 200, "body": {}})
        rows = [dict(self.ROW, id=str(i), attempts=1, maxAttempts=5) for i in range(3)]
        s.claim = lambda limit: rows
        done = []
        def complete(row, outcome):
            if row["id"] == "0":
                raise RuntimeError("database hiccup")
            done.append(row["id"])
            return True
        s.complete = complete
        result = s.tick()
        self.assertEqual((result["status"], result["error"], result["done"], done), ("ok", 1, 2, ["1", "2"]))

    def test_grant_reused_within_a_tick(self):
        s = self.scheduler({"status": 200, "body": {}})
        calls = []
        original = s.oauth.token_for_worker
        s.oauth.token_for_worker = lambda ws, c: calls.append(c) or original(ws, c)
        grants = {}
        s.read(self.ROW, grants)
        s.read(self.ROW, grants)
        self.assertEqual(calls, ["c"])


if __name__ == "__main__":
    unittest.main()
