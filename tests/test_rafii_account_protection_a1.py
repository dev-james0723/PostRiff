"""Rafii Account Protection v2, P1 item A1: every interactive session is observed at the token verifier.

Before A1 a session was recorded (pr_sessions row, `session.observed` event) only on /api/me, GET /api/auth/sessions,
bootstrap and invitation acceptance; one that only called workspace APIs was never seen, never announced, and could
not be revoked by id. The verifier (hosted_app.supabase_verifier) now runs the same observe_session as those routes,
in observe mode, inside an HTTP request, once per session per process.

Statement-level tests over a recording cursor, in the style of test_rafii_account_protection_p0.
"""
import base64
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_postriff_account_security as base  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import hosted_app, operator_actions  # noqa: E402
from postriff_phase2.coworker import flags  # noqa: E402
from postriff_phase2.hosted import PostgresWorkspaceRepository  # noqa: E402

SESSION = "session-a1-0123456789"
FLAGS_OK = ((False, False, False), 1)


def jwt(claims):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


TOKEN = jwt({"sub": base.PRINCIPAL, "session_id": SESSION, "aal": "aal2"})


def audits(cursor, kind):
    return [params for sql, params in cursor.executed if "INSERT INTO public.pr_audit_events" in sql and params[2] == kind]


def session_writes(cursor):
    return [sql for sql, _ in cursor.executed if "pr_sessions" in sql]


class DB(base.FakeDB):
    """A connection that records commit/rollback, which the verifier uses around an observation."""
    def __init__(self, cursor, log):
        super().__init__(cursor)
        self.log = log

    def commit(self):
        self.log.append("commit")

    def rollback(self):
        self.log.append("rollback")


class Verifier(unittest.TestCase):
    def setUp(self):
        saved = flags._values
        self.addCleanup(flags.attach, saved)
        # The founder block probe is folded into the flags statement; keep it out of the scripted responses.
        state = dict(operator_actions._STATE)
        self.addCleanup(operator_actions._STATE.update, state)
        operator_actions._STATE.update(status="not_installed", checked=float("inf"))
        self.log, self.cursors, self.alerts, self.get_user_calls = [], [], [], []

    def observe(self):
        flags.attach({"RAFII_ACCOUNT_PROTECTION_V2_MODE": "observe"})

    def verifier(self, *scripts):
        """One FakeCursor per connection, consumed in order."""
        scripts = list(scripts)

        def factory():
            cursor = base.FakeCursor(scripts.pop(0))
            self.cursors.append(cursor)
            return DB(cursor, self.log)

        def get_user(url, token):
            self.get_user_calls.append(token)
            return {"status": 200, "body": {"id": base.PRINCIPAL, "email_confirmed_at": "2026-01-01T00:00:00Z"}}

        verify = hosted_app.supabase_verifier("https://project.supabase.co", "p" * 24, factory, get_user=get_user)
        verify.on_first_sighting = lambda *args: self.alerts.append(args)
        return verify

    def in_request(self, label="Chrome on Mac"):
        binding = hosted_app._REQUEST_LABEL.set(label)
        self.addCleanup(hosted_app._REQUEST_LABEL.reset, binding)

    def test_a_workspace_api_only_first_request_is_observed_once(self):
        self.observe()
        self.in_request("Safari on iPhone")
        verify = self.verifier([FLAGS_OK, ((True,), 1), ((True,), 1), (None, 1)], [FLAGS_OK], [FLAGS_OK])
        for _ in range(3):  # three workspace calls from the new session; no session route is ever called
            self.assertEqual(verify(TOKEN), base.PRINCIPAL)
        first, second, third = self.cursors
        self.assertIn("RETURNING (xmax = 0)", first.executed[1][0])
        self.assertEqual(first.executed[1][1], (base.PRINCIPAL, SESSION, "Safari on iPhone"))
        [event] = audits(first, "session.observed")
        self.assertEqual(json.loads(event[4]), {"client": "Safari on iPhone", "alert": True})
        self.assertEqual(self.log, ["commit"])
        # The alert follows the commit, with the eligibility recorded at the first sighting.
        self.assertEqual(self.alerts, [(base.PRINCIPAL, SESSION, "Safari on iPhone", True)])
        # Steady state: the seen-cache keeps later requests to the one flags statement they always ran.
        self.assertEqual((len(second.executed), len(third.executed)), (1, 1))

    def test_a_session_already_recorded_elsewhere_is_touched_not_announced(self):
        self.observe()
        self.in_request()
        verify = self.verifier([FLAGS_OK, ((False,), 1)])
        verify(TOKEN)
        self.assertEqual((audits(self.cursors[0], "session.observed"), self.alerts), ([], []))
        self.assertTrue(verify.seen.has((base.PRINCIPAL, SESSION)))

    def test_two_concurrent_first_requests_record_one_event(self):
        # Two cold instances (or two threads before either commits): both miss the cache, PostgreSQL's
        # ON CONFLICT(user_id, session_id) lets exactly one insert win (xmax = 0), so one event and one alert.
        self.observe()
        self.in_request()
        winner = [FLAGS_OK, ((True,), 1), ((False,), 1), (None, 1)]
        loser = [FLAGS_OK, ((False,), 1)]
        one, two = self.verifier(winner), self.verifier(loser)
        barrier = threading.Barrier(2)
        label = hosted_app._REQUEST_LABEL.get()

        def call(verify):
            hosted_app._REQUEST_LABEL.set(label)
            barrier.wait()
            verify(TOKEN)

        threads = [threading.Thread(target=call, args=(v,)) for v in (one, two)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(len(audits(cursor, "session.observed")) for cursor in self.cursors), 1)
        self.assertEqual(len(self.alerts), 1)

    def test_flag_off_adds_no_statement(self):
        flags.attach({})
        self.in_request()
        verify = self.verifier([FLAGS_OK])
        verify(TOKEN)
        self.assertEqual(len(self.cursors[0].executed), 1)
        self.assertIn("pr_session_revocations", self.cursors[0].executed[0][0])
        self.assertEqual((self.log, self.alerts), ([], []))

    def test_outside_an_http_request_nothing_is_observed(self):
        # Workers and scripts never bind a label, so a verification there is a pure check.
        self.observe()
        verify = self.verifier([FLAGS_OK])
        verify(TOKEN)
        self.assertEqual(len(self.cursors[0].executed), 1)

    def test_refused_sessions_are_not_observed_and_still_refused(self):
        self.observe()
        self.in_request()
        aal1 = jwt({"sub": base.PRINCIPAL, "session_id": SESSION, "aal": "aal1"})
        for flags_row, token, status in (((False, True, False), TOKEN, 401), ((True, False, False), TOKEN, 401), ((False, False, True), aal1, 403)):
            with self.subTest(flags=flags_row):
                verify = self.verifier([(flags_row, 1)])
                with self.assertRaises(AlphaError) as refused:
                    verify(token)
                self.assertEqual(refused.exception.status, status)
                self.assertEqual(session_writes(self.cursors[-1]), [])
        self.assertEqual(self.alerts, [])

    def test_passkey_proof_tokens_are_checked_but_not_observed(self):
        self.observe()
        self.in_request()
        verify = self.verifier([FLAGS_OK])
        self.assertEqual(verify.proof(TOKEN), base.PRINCIPAL)
        self.assertEqual(session_writes(self.cursors[0]), [])

    def test_an_observation_failure_never_fails_the_request(self):
        self.observe()
        self.in_request()
        cursor_script = [FLAGS_OK]

        class Broken(base.FakeCursor):
            def execute(self, sql, params=None):
                if "pr_sessions" in sql:
                    raise RuntimeError("relation missing")
                super().execute(sql, params)

        verify = self.verifier(cursor_script)
        with mock.patch.object(base, "FakeCursor", Broken), self.assertLogs("postriff.account_protection", "WARNING") as logged:
            self.assertEqual(verify(TOKEN), base.PRINCIPAL)
        self.assertEqual(self.log, ["rollback"])
        self.assertIn("RuntimeError", logged.output[0])
        self.assertNotIn(SESSION, logged.output[0])
        # Not remembered as seen, so the next request tries again.
        self.assertFalse(verify.seen.has((base.PRINCIPAL, SESSION)))

    def test_a_failing_alert_never_fails_the_request(self):
        self.observe()
        self.in_request()
        verify = self.verifier([FLAGS_OK, ((True,), 1), ((True,), 1), (None, 1)])
        verify.on_first_sighting = mock.Mock(side_effect=RuntimeError("mail down"))
        with self.assertLogs("postriff.account_protection", "WARNING"):
            self.assertEqual(verify(TOKEN), base.PRINCIPAL)

    def test_an_api_token_principal_is_not_a_browser_session(self):
        # api_tokens.authorize / repository.transaction resolve prt_ tokens without the session verifier, so they
        # never reach observation; the verifier also refuses to observe one if it ever were handed one.
        self.observe()
        self.in_request()
        verify = self.verifier()
        repository = PostgresWorkspaceRepository(lambda: base.FakeDB(base.FakeCursor([((1, {}, "editor", True, True, True, True), 1)])), verify)
        grant = {"createdBy": base.PRINCIPAL, "tokenId": "t1"}
        with mock.patch.object(repository.api_tokens, "resolve", return_value=grant), \
                mock.patch.object(repository.api_tokens, "validate"), \
                mock.patch("postriff_phase2.agent_runtime_v2.authz.recheck_transaction"):
            with repository.transaction("prt_" + "x" * 40, base.WORKSPACE) as (cur, _, principal):
                self.assertEqual(principal, base.PRINCIPAL)
        self.assertEqual((self.get_user_calls, self.cursors, self.alerts), ([], [], []))
        self.assertEqual(session_writes(cur), [])


class SeenSessionsCache(unittest.TestCase):
    def test_bounded_lru(self):
        seen = hosted_app.SeenSessions(limit=2)
        seen.add(("u", "a"))
        seen.add(("u", "b"))
        self.assertTrue(seen.has(("u", "a")))  # touch: b is now the oldest
        seen.add(("u", "c"))
        self.assertEqual([seen.has(("u", k)) for k in "abc"], [True, False, True])


class RequestLabel(unittest.TestCase):
    def test_the_application_binds_the_browser_label_for_the_request_only(self):
        captured = []

        class Service:
            def me(self, token, client_label=""):
                captured.append(hosted_app._REQUEST_LABEL.get())
                return {}

        app = hosted_app.HostedApplication(Service(), None, {"provider": "supabase"}, "c" * 24)
        status = base.invoke(app, "GET", "/api/me", headers={**base.AUTH, "User-Agent": "Mozilla/5.0 (iPhone) Safari/605.1"})[0]
        self.assertEqual((status, captured), (200, ["Safari on iPhone"]))
        self.assertIsNone(hosted_app._REQUEST_LABEL.get())


if __name__ == "__main__":
    unittest.main()
