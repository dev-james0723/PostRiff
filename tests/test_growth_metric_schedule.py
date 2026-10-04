import unittest
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.providers import ThreadsProvider


class Hooks(unittest.TestCase):
    def test_workspace_list_is_explicit_and_invalid_entries_deny_the_whole_list(self):
        wid = "267f7d90-b11c-470c-9880-733ea7c1d483"
        self.assertEqual(M.allowed_workspaces({M.WORKSPACE_ALLOWLIST: wid}), {wid})
        for raw in ("", "*", wid + ",*", wid + ",", "other", [wid]):
            with self.subTest(raw=raw):
                self.assertFalse(M.allowed_workspaces({M.WORKSPACE_ALLOWLIST: raw}))
        self.assertFalse(M.workspace_enabled(None, wid))
        denied = M.MetricScheduler(None, None, transport=None)
        self.assertFalse(M.workspace_enabled(denied, wid))
        self.assertEqual(denied.claim(10), [])  # no DB needed, no claims outside admission

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
            providers = {"threads": ThreadsProvider("synthetic-client", "synthetic-secret", production_reviewed=True)}
            def token_for_worker(self, ws, conn):
                if token_error:
                    raise token_error
                return {"accessToken": "t", "provider": "threads", "scopes": sorted(M.NATIVE_ANALYTICS_SCOPES["threads"])}
        def transport(method, url, **kw):
            if isinstance(reply, Exception):
                raise reply
            return reply
        s = M.MetricScheduler(None, OAuth(), transport=transport, workspace_allowlist={"w"})
        s._eligible = lambda row: "read"
        return s

    ROW = {"workspaceId": "w", "connectionId": "c", "provider": "threads", "postId": "p"}

    def test_missed_horizon_never_calls_provider_or_manufactures_old_reading(self):
        s=self.scheduler({'status':200,'body':{}})
        s.clock=lambda:1000+3600+601
        outcome=s.read({**self.ROW,'offset':'1h','anchorAt':1000},{})
        self.assertEqual(outcome['state'],'unavailable')
        self.assertEqual(outcome['failure'],'horizon_missed')
        self.assertFalse(outcome.get('providerRead'))

    def test_backfill_has_no_historic_horizon_and_late_response_is_unqualified(self):
        s=self.scheduler({'status':200,'body':{'data':[]}})
        s.clock=lambda:1000000
        self.assertEqual(s.read({**self.ROW,'offset':'backfill','anchorAt':1000},{})['state'],'done')
        at=[1000+3600]
        s=self.scheduler()
        s.clock=lambda:at[0]
        def transport(*args,**kw):
            at[0]+=601
            return {'status':200,'body':{'data':[{'name':'views','total_value':{'value':12}}]}}
        s.transport=transport
        outcome=s.read({**self.ROW,'offset':'1h','anchorAt':1000},{})
        self.assertEqual(outcome['state'],'unavailable')
        self.assertEqual(outcome['failure'],'horizon_missed')
        self.assertTrue(outcome['providerRead'])
        self.assertTrue(outcome['found'])  # retain only as a current untimed snapshot at fenced completion

    def test_review_pause_workspace_and_scopes_are_rechecked_before_insights(self):
        for case in ("unreviewed", "malformed_review", "paused", "second_workspace", "no_allowlist", "missing_scope", "wrong_provider"):
            with self.subTest(case=case):
                s = self.scheduler({"status": 200, "body": {}})
                calls = []
                s.transport = lambda *a, **k: calls.append(a) or {"status": 200, "body": {}}
                row = dict(self.ROW)
                if case == "unreviewed":
                    s.oauth.providers["threads"].production_reviewed = False
                elif case == "malformed_review":
                    s.oauth.providers["threads"].production_reviewed = "false"
                elif case == "paused":
                    s.oauth.providers["threads"].execution_enabled = False
                elif case == "second_workspace":
                    row["workspaceId"] = "other"
                elif case == "no_allowlist":
                    s.workspace_allowlist = frozenset()
                else:
                    s.oauth.token_for_worker = lambda *a: {"accessToken": "t", "provider": "instagram" if case == "wrong_provider" else "threads", "scopes": ["threads_basic"]}
                self.assertEqual(s.read(row, {})["state"], "cancelled")
                self.assertEqual(calls, [])

    def test_introspection_or_revocation_during_grant_fetch_suppresses_read(self):
        for eligibility_after_grant, expected in (("cancel", "cancelled"), ("wait", "transient")):
            with self.subTest(eligibility=eligibility_after_grant):
                s = self.scheduler({"status": 200, "body": {}})
                eligibility = iter(("read", eligibility_after_grant))
                s._eligible = lambda row: next(eligibility)
                calls = []
                s.transport = lambda *a, **k: calls.append(a)
                self.assertEqual(s.read(self.ROW, {})["state"], expected)
                self.assertEqual(calls, [])

    def test_provider_attempt_signals_do_not_report_unknown_cost_as_zero(self):
        for reply, state in (({"status": 429, "body": {}}, "retry"), (AlphaError("native rejection", 404), "unavailable")):
            with self.subTest(reply=reply):
                s = self.scheduler(reply)
                s.claim = lambda limit: [dict(self.ROW, id="r", attempts=1, maxAttempts=5)]
                s.complete = lambda row, outcome: True
                with self.assertLogs("postriff.growth.metric_reads", "INFO") as logs:
                    result = s.tick()
                self.assertEqual((result["providerReads"], result["providerErrors"], result[state], result["costUnknownReads"]), (1, 1, 1, 1))
                self.assertIn('"costUsd": null', logs.output[-1])
                self.assertNotIn("access_token", logs.output[-1])
                self.assertNotIn("synthetic-token", logs.output[-1])

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
