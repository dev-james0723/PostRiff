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



WID = "267f7d90-b11c-470c-9880-733ea7c1d483"
ENROLLED = "0ceb3635-0000-4000-8000-000000000003"
SELF_SERVE = {"POSTRIFF_METRIC_SELF_SERVE_ENABLED": "1", "POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES": "5"}


class FakeDB:
    """A scripted connection: `answer(sql, params)` returns the rows for each statement; every statement is kept."""

    def __init__(self, answer):
        self.answer, self.sql, self.commits = answer, [], 0
        self._rows, self.rowcount = [], 0

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def commit(self):
        self.commits += 1

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        self.sql.append((text, params))
        rows = self.answer(text, params)
        self._rows = list(rows or [])
        self.rowcount = len(self._rows) if rows is not None else 1

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


def enrollment_answer(status="active", enrollment_table=True, extra=None):
    def answer(text, params):
        if extra is not None:
            found = extra(text, params)
            if found is not None:
                return found
        if "to_regclass('public.pr_feature_enrollments')" in text:
            return [(enrollment_table,)]
        if "SELECT status FROM public.pr_feature_enrollments" in text:
            return [(status,)] if status and params[0] == ENROLLED else []
        if "SELECT workspace_id::text FROM public.pr_feature_enrollments" in text:
            return [(ENROLLED,)] if status == "active" else []
        return []
    return answer


class Admission(unittest.TestCase):
    def test_enrolled_workspace_is_admitted_without_env_listing(self):
        db = FakeDB(enrollment_answer())
        s = M.MetricScheduler(db, None, transport=None, workspace_allowlist={WID}, env=SELF_SERVE)
        self.assertTrue(s.workspace_allowed(WID))
        self.assertTrue(s.workspace_allowed(ENROLLED))
        self.assertTrue(M.workspace_enabled(s, ENROLLED))

    def test_wildcard_unenrolled_revoked_paused_or_denied_workspaces_stay_denied(self):
        for case in ("unenrolled", "revoked", "paused", "denied", "no_table", "wildcard"):
            with self.subTest(case=case):
                env = dict(SELF_SERVE)
                status = {"revoked": "revoked", "unenrolled": None}.get(case, "active")
                if case == "paused":
                    env.pop("POSTRIFF_METRIC_SELF_SERVE_ENABLED")
                if case == "denied":
                    env["RAFII_FEATURE_WORKSPACE_DENYLIST"] = ENROLLED
                db = FakeDB(enrollment_answer(status=status, enrollment_table=case != "no_table"))
                allow = M.allowed_workspaces({M.WORKSPACE_ALLOWLIST: "*"}) if case == "wildcard" else frozenset()
                s = M.MetricScheduler(db, None, transport=None, workspace_allowlist=allow, env=env)
                target = "*" if case == "wildcard" else ENROLLED
                self.assertFalse(s.workspace_allowed(target))
                self.assertEqual(s.claim(10), [])

    def test_claim_admits_the_env_list_and_active_enrollments_only(self):
        claims = []
        def extra(text, params):
            if text.startswith("UPDATE public.pr_metric_reads r SET status='claimed'"):
                claims.append(params[2])
                return []
            return None
        db = FakeDB(enrollment_answer(extra=extra))
        M.MetricScheduler(db, None, transport=None, workspace_allowlist={WID}, env=SELF_SERVE).claim(10)
        self.assertTrue(claims)
        self.assertTrue(all(admitted == sorted([WID, ENROLLED]) for admitted in claims), claims)
        claims.clear()
        M.MetricScheduler(db, None, transport=None, workspace_allowlist={WID}, env={}).claim(10)
        self.assertTrue(all(admitted == [WID] for admitted in claims), claims)
        claims.clear()
        quiet = FakeDB(enrollment_answer(status=None, extra=extra))
        self.assertEqual(M.MetricScheduler(quiet, None, transport=None, env=SELF_SERVE).claim(10), [])
        self.assertEqual(claims, [])   # nobody admitted: no claim statement at all

    def test_unenrollment_closes_this_workspaces_open_reads_as_not_admitted(self):
        db = FakeDB(lambda text, params: [("r1",), ("r2",)])
        self.assertEqual(M.close_unadmitted_reads(db, ENROLLED), 2)
        text, params = db.sql[-1]
        self.assertIn("status='cancelled'", text)
        self.assertIn("failure_class='not_admitted'", text)
        self.assertIn("status IN ('pending','claimed')", text)
        self.assertEqual(params, (ENROLLED,))


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class WindowTruth(unittest.TestCase):
    ANCHOR = 1_760_000_000.0

    def row(self, offset, **extra):
        return {"id": "r", "workspaceId": WID, "jobId": "job", "connectionId": "c", "provider": "threads", "postId": "p",
                "offset": offset, "anchorAt": self.ANCHOR, "attempts": 1, "maxAttempts": 5, **extra}

    def test_product_default_tolerances(self):
        self.assertEqual(M.WINDOW_TOLERANCE, {"t0": 900, "1h": 1200, "24h": 10800, "7d": 86400})
        for offset, seconds in M.OFFSETS:
            deadline = self.ANCHOR + seconds + M.WINDOW_TOLERANCE[offset]
            self.assertFalse(M.window_missed(self.row(offset), deadline))
            self.assertTrue(M.window_missed(self.row(offset), deadline + 1))
        self.assertFalse(M.window_missed(self.row("backfill"), self.ANCHOR + 400 * 86400))
        self.assertFalse(M.window_missed({"offset": "1h"}, self.ANCHOR + 10 ** 9))

    def test_late_claim_never_fills_the_missed_window(self):
        calls = []
        class OAuth:
            providers = {"threads": ThreadsProvider("synthetic-client", "synthetic-secret", production_reviewed=True)}
            def token_for_worker(self, *a):
                calls.append("token")
                return {"accessToken": "t", "provider": "threads", "scopes": sorted(M.NATIVE_ANALYTICS_SCOPES["threads"])}
        late = self.ANCHOR + 3600 + 3 * 3600      # a '1h' row claimed three hours after its window opened
        s = M.MetricScheduler(None, OAuth(), transport=lambda *a, **k: calls.append("insights"), workspace_allowlist={WID}, clock=Clock(late))
        s._eligible = lambda row: "read"
        outcome = s.read(self.row("1h"), {})
        self.assertEqual((outcome["state"], outcome["failure"], outcome.get("providerRead")), ("unavailable", "window_missed", False))
        self.assertEqual(calls, [])

    def complete_with(self, row, outcome, clock, admitted=True):
        def answer(text, params):
            if text.startswith("SELECT state ? 'accountDeletion'"):
                return [(False,)]
            if "FROM public.pr_encrypted_credentials" in text:
                return [("threads", sorted(M.NATIVE_ANALYTICS_SCOPES["threads"]))]
            if "capability='analytics'" in text:
                return [("Direct",)]
            if "to_regclass('public.pr_growth_purges')" in text:
                return [(False,)]
            if text.startswith("UPDATE public.pr_metric_reads"):
                return [(1,)]
            return []
        db = FakeDB(answer)
        s = M.MetricScheduler(db, None, transport=None, workspace_allowlist={WID} if admitted else (), clock=clock, env={})
        s.provider_allowed = lambda provider: True
        recorded = s.complete(row, outcome)
        return db, recorded

    def test_a_read_taken_in_time_is_recorded_and_a_late_one_is_closed_as_missed(self):
        row = self.row("1h")
        in_time = {"state": "done", "found": {"views": 0}, "endpoint": "x", "readAt": self.ANCHOR + 3600 + 600}
        db, recorded = self.complete_with(row, dict(in_time), Clock(self.ANCHOR + 3600 + 1300))
        self.assertTrue(recorded)
        inserts = [p for t, p in db.sql if t.startswith("INSERT INTO public.pr_metric_observations")]
        self.assertEqual(len(inserts), 6)
        self.assertTrue(all(p[9] == self.ANCHOR + 3600 + 600 for p in inserts))   # observed at the real read time
        late = dict(in_time, readAt=self.ANCHOR + 3600 + 1201)
        db, recorded = self.complete_with(row, late, Clock(self.ANCHOR + 3600 + 1300))
        self.assertTrue(recorded)
        self.assertFalse([t for t, _ in db.sql if t.startswith("INSERT INTO public.pr_metric_observations")])
        closed = next((t, p) for t, p in db.sql if t.startswith("UPDATE public.pr_metric_reads SET status=%s"))
        self.assertEqual(closed[1][:3], ("unavailable", None, "window_missed"))
        self.assertEqual(late["state"], "unavailable")

    def test_admission_revoked_before_commit_is_fenced_after_the_workspace_lock(self):
        row = self.row("t0")
        outcome = {"state": "done", "found": {"views": 5}, "endpoint": "x", "readAt": self.ANCHOR + 10}
        db, recorded = self.complete_with(row, outcome, Clock(self.ANCHOR + 20), admitted=False)
        self.assertTrue(recorded)
        self.assertEqual((outcome["state"], outcome["failure"]), ("cancelled", "not_admitted"))
        self.assertFalse([t for t, _ in db.sql if t.startswith("INSERT INTO public.pr_metric_observations")])
        lock = next(i for i, (t, _) in enumerate(db.sql) if t.startswith("SELECT state ? 'accountDeletion'") and "FOR UPDATE" in t)
        self.assertEqual(lock, 0)

if __name__ == "__main__":
    unittest.main()
