"""Regression tests for the fixes that must land before coworker flags go on in production (PR #9): the weekly cron's
credit binding and idle writes, the notification centre's mark-all and security link, and hardening of the public
and weekly routes."""
import contextlib
import copy
import io
import json
import pathlib
import time
import unittest
from unittest import mock

from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags, http as coworker_http, weekly_operator
from postriff_phase2.coworker.service import CoworkerService
from postriff_phase2.notifications import detector, store, webhooks

ROOT = pathlib.Path(__file__).resolve().parents[1]


class FlagsOn:
    """Attach a flag source for one test and restore the previous one afterwards."""

    def __init__(self, *names):
        self.values = {name: "1" for name in names}

    def __enter__(self):
        self.saved = flags._values
        flags.attach(self.values)

    def __exit__(self, *_exc):
        flags._values = self.saved


class Repository:
    """Records which repository a credit check opened."""

    def __init__(self, name, log):
        self.name, self.log = name, log

    @contextlib.contextmanager
    def transaction(self, token, workspace_id):
        self.log.append((self.name, token, workspace_id))
        yield object(), ({"members": []},), "owner-1"


class Book:
    def policy(self, _cur, _workspace_id):
        return False   # stop right after the transaction opens: which repository it used is all this test needs


class Ideas:
    def __init__(self, repository):
        from postriff_phase2.credit_requests import CreditRequests
        self.repository = repository
        self.ledger = type("Ledger", (), {"credits": Book()})()
        self.credit_requests = CreditRequests(self)

    def _member(self, _row):
        return {"role": "owner"}


class BoundIdeasTest(unittest.TestCase):
    def test_the_cron_copy_checks_credits_through_its_own_repository(self):
        log = []
        original = Repository("session", log)
        hosted = type("Hosted", (), {})()
        hosted.ideas = Ideas(original)
        worker = Repository("worker", log)
        service = CoworkerService(hosted)
        with mock.patch("postriff_phase2.credit_requests.require"):
            bound = service._bound_ideas(worker)
            bound.credit_requests.authorize("w1", "capability", None, {"model": None}, "turn")
        self.assertIs(bound.repository, worker)
        self.assertIs(bound.credit_requests.ideas, bound)
        self.assertEqual(log, [("worker", "capability", "w1")])
        # The shared pipeline is untouched.
        self.assertIs(hosted.ideas.repository, original)
        self.assertIs(hosted.ideas.credit_requests.ideas, hosted.ideas)


def week_with(state, slots):
    return {"id": "wk1", "weekOf": "2026-09-28", "state": state, "slots": slots, "history": [], "blockedReason": None}


class IdleWeekTest(unittest.TestCase):
    def service_for(self, week):
        state = {"coworker": {"weekly": {"recipes": [], "weeks": [week], "revision": 1}}}
        repository = type("Repo", (), {"get": lambda _self, _w, _t: {"state": copy.deepcopy(state), "revision": 1}})()
        service = CoworkerService(type("Hosted", (), {"repository": repository})(), clock=lambda: 1_790_000_000)
        return service, repository

    def test_a_blocked_week_with_nothing_to_check_is_not_rewritten(self):
        slot = {"id": "s1", "status": "needs_input", "reason": "Answer this", "question": "Answer this"}
        week = week_with("needs_input", [slot])
        weekly_operator.settle(week, 1_790_000_000)   # the stored week is already settled
        service, repository = self.service_for(week)
        with mock.patch.object(CoworkerService, "_command_as") as command:
            result = service._quality_and_settle("w1", "t", repository, {"expectImages": False}, "wk1", "owner-1", [])
        command.assert_not_called()
        # `advanced` stays true: only a week already in review answers false (the web and the agent read it that way).
        self.assertTrue(result["advanced"])
        self.assertEqual(result["week"]["state"], "needs_input")

    def test_a_week_whose_state_changes_is_still_saved(self):
        week = week_with("generating", [{"id": "s1", "status": "needs_input", "reason": "Answer this"}])
        service, repository = self.service_for(week)
        with mock.patch.object(CoworkerService, "_command_as", return_value=None) as command:
            service._quality_and_settle("w1", "t", repository, {"expectImages": False}, "wk1", "owner-1", [])
        command.assert_called_once()


class WeeklyCronIsolationTest(unittest.TestCase):
    def test_one_recipes_unexpected_error_does_not_stop_the_next_workspace(self):
        recipe = {"id": "r1", "createdBy": "owner-1", "status": "active", "timeZone": "UTC", "planningDay": 0, "planningHour": 0}

        class Cursor:
            def execute(self, *_a):
                pass

            def fetchall(self):
                return [("w1", [recipe]), ("w2", [dict(recipe, id="r2")])]

        @contextlib.contextmanager
        def connection():
            db = mock.Mock()
            db.cursor.return_value = contextlib.nullcontext(Cursor())
            yield db

        hosted = type("Hosted", (), {"connection_factory": staticmethod(connection)})()
        service = CoworkerService(hosted, clock=lambda: 1_790_000_000)
        calls = []

        def prepare(workspace_id, _token, recipe_id, **_kw):
            calls.append(workspace_id)
            if workspace_id == "w1":
                raise TypeError("can only concatenate str (not \"object\") to str")
            return {"week": {"state": "ready_for_review"}}

        with FlagsOn("RAFII_WEEKLY_OPERATOR_ENABLED"), mock.patch.object(service, "weekly_prepare", side_effect=prepare), \
                mock.patch.object(weekly_operator, "due", return_value=True):
            result = service.weekly_cron(deadline=time.monotonic() + 60)
        self.assertEqual(calls, ["w1", "w2"])
        self.assertEqual(result["prepared"][0]["error"], "TypeError")
        self.assertEqual(result["prepared"][1]["state"], "ready_for_review")


class RecordingCursor:
    def __init__(self, results=(), rowcount=0, rows=()):
        self.results, self.rowcount, self.rows, self.sql = list(results), rowcount, list(rows), []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.rows


class MarkAllReadTest(unittest.TestCase):
    def test_every_unread_notification_in_the_workspace_is_marked_in_one_statement(self):
        ids = [f"d{i}" for i in range(37)]
        cur = RecordingCursor(results=[(0,)], rowcount=37, rows=[(i,) for i in ids])
        result = store.mark_all_read(cur, "user-1", "w1")
        self.assertEqual(result, {"changed": 37, "unread": 0, "verified": True})
        select, update, recount = cur.sql
        self.assertIn("status='delivered'", select[0])
        self.assertTrue(select[0].endswith("FOR UPDATE"))
        self.assertNotIn("LIMIT", select[0])
        self.assertEqual(select[1], ("user-1", "w1"))
        self.assertTrue(update[0].startswith("UPDATE public.pr_notification_deliveries SET status='read'"))
        # Only the rows it targeted are updated and recounted: one arriving meanwhile is not a failure.
        self.assertEqual(update[1], (ids,))
        self.assertEqual(recount[1], (ids,))

    def test_nothing_unread_is_a_verified_no_op(self):
        cur = RecordingCursor(rows=[])
        self.assertEqual(store.mark_all_read(cur, "user-1", "w1"), {"changed": 0, "unread": 0, "verified": True})
        self.assertEqual(len(cur.sql), 1)

    def test_the_route_is_read_all(self):
        notifications = mock.Mock()
        notifications.mark_all_read.return_value = {"changed": 2, "unread": 0, "verified": True}
        service = type("Service", (), {"notifications": notifications, "coworker": object()})()
        app = mock.Mock()
        app._body.return_value = {}
        coworker_http.handle(app, {}, None, service, "token", "POST", ["api", "workspaces", "w1", "notifications", "read-all"])
        notifications.mark_all_read.assert_called_once_with("w1", "token")
        notifications.mark.assert_not_called()


class SecurityLinkTest(unittest.TestCase):
    def test_security_notices_open_a_page_that_exists(self):
        cur = RecordingCursor()
        cur.fetchall = lambda: [("a1", "user-1", "session.alerted"), ("a2", "user-1", "mfa.enabled")]
        events = detector.security_events(cur)
        self.assertEqual({e["payload"]["href"] for e in events}, {"/app/account/profile"})
        self.assertTrue((ROOT / "web/src/app/app/account/profile/page.tsx").is_file())


class Unreadable(io.RawIOBase):
    def read(self, *_a):
        raise AssertionError("the body must not be read")


class PublicWebhookTest(unittest.TestCase):
    def app_with(self, enabled):
        notifications = mock.Mock()
        notifications.enabled.return_value = enabled
        service = type("Service", (), {"notifications": notifications, "coworker": object()})()
        app = mock.Mock()
        app._runtime.return_value = service
        return app

    def test_off_answers_404_before_reading_anything(self):
        environ = {"CONTENT_LENGTH": "12", "wsgi.input": Unreadable()}
        with self.assertRaises(AlphaError) as caught:
            coworker_http.public(self.app_with(False), environ, None, "POST", "/api/notifications/email/webhook")
        self.assertEqual(caught.exception.status, 404)

    def test_a_size_that_is_not_a_number_is_a_400_not_a_500(self):
        environ = {"CONTENT_LENGTH": "twelve", "wsgi.input": Unreadable()}
        with self.assertRaises(AlphaError) as caught:
            coworker_http.public(self.app_with(True), environ, None, "POST", "/api/notifications/email/webhook")
        self.assertEqual(caught.exception.status, 400)


class WeeklyPrepareRouteTest(unittest.TestCase):
    def call(self, body):
        coworker = mock.Mock()
        coworker.weekly_prepare.return_value = {"week": {}}
        service = type("Service", (), {"notifications": object(), "coworker": coworker})()
        app = mock.Mock()
        app._body.return_value = body
        coworker_http.handle(app, {}, None, service, "token", "POST", ["api", "workspaces", "w1", "coworker", "weekly", "recipes", "r1", "prepare"])
        return coworker.weekly_prepare

    def test_bad_counts_are_refused_and_good_ones_clamped_with_a_time_budget(self):
        for bad in ("many", "3", [3], 2.5, float("inf"), True):
            with self.assertRaises(AlphaError) as caught:
                self.call({"maxSlots": bad})
            self.assertEqual(caught.exception.status, 400)
        for given, expected in ((-4, 1), (50, 12), (None, 8), (3, 3)):
            prepare = self.call({"maxSlots": given})
            kwargs = prepare.call_args.kwargs
            self.assertEqual(kwargs["max_slots"], expected)
            self.assertGreater(kwargs["deadline"], time.monotonic())


class UnsubscribeApplyTest(unittest.TestCase):
    token = {"userId": "user-1", "scope": "*", "category": "digest"}

    def test_a_deleted_accounts_link_no_longer_works(self):
        cur = RecordingCursor(results=[(1,)])
        with self.assertRaises(AlphaError) as caught:
            webhooks.apply_unsubscribe(cur, self.token)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(len(cur.sql), 1)

    def test_a_repeated_click_writes_nothing(self):
        cur = RecordingCursor(results=[None, (True,)])
        self.assertEqual(webhooks.apply_unsubscribe(cur, self.token), {"unsubscribed": True})
        self.assertFalse(any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in cur.sql))

    def test_the_first_click_unsubscribes_and_is_audited(self):
        cur = RecordingCursor(results=[None, None, (True,)])
        self.assertEqual(webhooks.apply_unsubscribe(cur, self.token), {"unsubscribed": True})
        inserts = [sql for sql, _ in cur.sql if sql.startswith("INSERT")]
        self.assertEqual(len(inserts), 2)
        self.assertIn("pr_audit_events", inserts[1])


class RouteDescribeTest(unittest.TestCase):
    def test_a_coworker_page_whose_feature_is_off_is_described_as_off(self):
        from postriff_phase2.site_agent import tools
        ctx = type("Ctx", (), {"now": 1_790_000_000})()
        with FlagsOn():
            data = tools.route_describe(ctx, "weekly")["data"]
        self.assertFalse(data["canOpen"])
        self.assertIn("isn't turned on", data["summary"])
        with FlagsOn("RAFII_WEEKLY_OPERATOR_ENABLED"), mock.patch.object(tools, "_can_open", return_value=(True, None)):
            data = tools.route_describe(ctx, "weekly")["data"]
        self.assertTrue(data["canOpen"])
        self.assertIn("recipes", data["summary"])


class RouteManifestTest(unittest.TestCase):
    def test_the_coworker_pages_are_known_to_the_site_agent(self):
        server = (ROOT / "src/postriff_phase2/site_agent/route_manifest.json").read_bytes()
        self.assertEqual(server, (ROOT / "web/src/lib/site-agent/route-manifest.json").read_bytes())
        patterns = {r["pattern"] for r in json.loads(server)["routes"]}
        for pattern, page in (("/app/weekly", "web/src/app/app/weekly/page.tsx"), ("/app/workspace/personalization", "web/src/app/app/workspace/personalization/page.tsx")):
            self.assertIn(pattern, patterns)
            self.assertTrue((ROOT / page).is_file())


if __name__ == "__main__":
    unittest.main()
