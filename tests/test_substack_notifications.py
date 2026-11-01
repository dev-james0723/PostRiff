"""Offline regressions for Substack manual-target in-app reminders.

Pure payload checks and injected DB boundaries are not live provider acceptance;
the disposable PostgreSQL suite separately checks real SQL, RLS and row locks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import substack_notifications as module
from postriff_phase2.notifications import planner, store
from postriff_phase2.permissions import Membership
from postriff_phase2.substack_service import _content_hash

WORKSPACE = "00000000-0000-4000-8000-000000000101"
OTHER = "00000000-0000-4000-8000-000000000102"
OWNER = "00000000-0000-4000-8000-000000000201"
APPROVER = "00000000-0000-4000-8000-000000000202"
CONNECTION = "sc_" + "1" * 32
DRAFT = "sd_" + "2" * 32
JOB = "sq_" + "3" * 32
TARGET = "2026-10-18T12:00:00Z"
NOW = 1792324801.0


def fixture(workspace_id=WORKSPACE):
    connection = {"id": CONNECTION, "mode": "public_feed", "status": "feed_added",
                  "publicationUrl": "https://rafii-test.substack.com", "feedConsentVersion": 1}
    draft = {"id": DRAFT, "connectionId": CONNECTION, "title": "PRIVATE TITLE", "body": "PRIVATE BODY",
             "format": "markdown", "contentType": "article", "audience": "paid", "scheduledFor": TARGET,
             "status": "approved"}
    digest = _content_hash(draft, connection)
    draft.update(contentHash=digest, approvedHash=digest)
    job = {"id": JOB, "kind": "manual_handoff", "draftId": DRAFT, "connectionId": CONNECTION,
           "contentHash": digest, "idempotencyKey": hashlib.sha256((DRAFT + ":" + digest).encode()).hexdigest(),
           "scheduledFor": TARGET, "status": "pending_manual", "autoPublished": False}
    return {"workspace": {"id": workspace_id, "sample": False},
            "substack": {"version": 1, "connections": [connection], "drafts": [draft], "queue": [job]}}


class DueJobTests(unittest.TestCase):
    def test_due_job_is_current_content_bound_inert_metadata_without_mutation(self):
        state = fixture()
        before = copy.deepcopy(state)
        jobs = module.due_jobs(state, NOW, WORKSPACE)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], JOB)
        self.assertEqual(jobs[0]["scheduledFor"], TARGET)
        self.assertNotIn("PRIVATE", json.dumps(jobs))
        self.assertNotIn("publicationUrl", jobs[0])
        self.assertNotIn("audience", jobs[0])
        self.assertEqual(state, before)

    def test_missing_future_invalid_or_noncanonical_target_is_not_a_due_reminder(self):
        for value in (None, "", "not-a-date", "2026-99-99T12:00:00Z", "2026-10-18T12:00:00+00:00",
                      "2026-10-18T12:00:00.1Z", "2026-10-19T12:00:00Z", 0, True):
            with self.subTest(value=value):
                state = fixture()
                state["substack"]["queue"][0]["scheduledFor"] = value
                self.assertEqual(module.due_jobs(state, NOW), [])
        self.assertEqual(module.due_jobs(fixture(), NOW - 2), [])

    def test_timezone_target_is_due_at_its_exact_boundary(self):
        self.assertEqual(len(module.due_jobs(fixture(), NOW - 1)), 1)
        state = fixture()
        draft, connection, job = (state["substack"][key][0] for key in ("drafts", "connections", "queue"))
        draft["scheduledFor"] = job["scheduledFor"] = "2026-10-18T12:00:00.500000Z"
        digest = _content_hash(draft, connection)
        draft.update(contentHash=digest, approvedHash=digest)
        job.update(contentHash=digest, idempotencyKey=hashlib.sha256((DRAFT + ":" + digest).encode()).hexdigest())
        self.assertEqual(module.due_jobs(state, NOW - 0.6), [])
        self.assertEqual(len(module.due_jobs(state, NOW - 0.5)), 1)

    def test_workspace_identity_sample_deletion_block_and_schema_fail_closed(self):
        for edit in (
            lambda s: s["workspace"].update(id=OTHER),
            lambda s: s["workspace"].update(sample=True),
            lambda s: s["workspace"].pop("sample"),
            lambda s: s.update(accountDeletion={}),
            lambda s: s.update(accountBlock={}),
            lambda s: s["substack"].update(version=True),
            lambda s: s["substack"].update(version=2),
            lambda s: s["substack"].update(queue=None),
        ):
            state = fixture()
            edit(state)
            self.assertEqual(module.due_jobs(state, NOW, WORKSPACE), [])
        for now in (True, None, "now", float("nan"), float("inf")):
            self.assertEqual(module.due_jobs(fixture(), now), [])

    def test_changed_content_or_destination_cannot_reuse_cached_approval(self):
        for name, value in (("title", "Another title"), ("body", "Changed text"), ("format", "plain_text"),
                            ("contentType", "note"), ("audience", "everyone"), ("scheduledFor", None),
                            ("connectionId", "sc_" + "4" * 32), ("approvedHash", None), ("status", "draft")):
            with self.subTest(field=name):
                state = fixture()
                state["substack"]["drafts"][0][name] = value
                self.assertEqual(module.due_jobs(state, NOW), [])
        for name, value in (("mode", "official_mcp_analytics"), ("status", "disconnected"),
                            ("publicationUrl", "https://another.substack.com"),
                            ("publicationUrl", "http://127.0.0.1/")):
            state = fixture()
            state["substack"]["connections"][0][name] = value
            self.assertEqual(module.due_jobs(state, NOW), [])

    def test_job_type_false_success_cancellation_and_hash_must_match(self):
        for name, value in (("kind", "provider_publish"), ("status", "canceled"), ("status", "handoff_prepared"),
                            ("autoPublished", True), ("autoPublished", "false"), ("draftId", "sd_" + "4" * 32),
                            ("connectionId", "sc_" + "4" * 32), ("contentHash", "f" * 64),
                            ("idempotencyKey", "f" * 64)):
            with self.subTest(field=name, value=value):
                state = fixture()
                state["substack"]["queue"][0][name] = value
                self.assertEqual(module.due_jobs(state, NOW), [])

    def test_duplicate_or_injected_identifiers_fail_closed(self):
        for key in ("connections", "drafts", "queue"):
            state = fixture()
            state["substack"][key].append(copy.deepcopy(state["substack"][key][0]))
            self.assertEqual(module.due_jobs(state, NOW), [])
            state = fixture()
            state["substack"][key][0]["id"] = "../../foreign?secret=1"
            self.assertEqual(module.due_jobs(state, NOW), [])

    def test_recomputed_hash_does_not_make_an_invalid_draft_exportable(self):
        state = fixture()
        draft, connection, job = (state["substack"][key][0] for key in ("drafts", "connections", "queue"))
        draft["body"] = ""
        digest = _content_hash(draft, connection)
        draft.update(contentHash=digest, approvedHash=digest)
        job.update(contentHash=digest, idempotencyKey=hashlib.sha256((DRAFT + ":" + digest).encode()).hexdigest())
        self.assertEqual(module.due_jobs(state, NOW), [])

    def test_notification_is_content_free_actor_scoped_and_has_no_outbound_channel(self):
        job = module.due_jobs(fixture(), NOW)[0]
        event = module._event(WORKSPACE, job, APPROVER)
        self.assertEqual(event["actor"], APPROVER)
        self.assertEqual(event["workspace_id"], WORKSPACE)
        self.assertEqual(event["channel_filter"], ("in_app",))
        self.assertNotIn("PRIVATE", json.dumps(event))
        self.assertEqual(event["payload"]["href"], "/app/channels?connect=substack&substackDraft=" + DRAFT)
        self.assertEqual(store._clean_payload(event["payload"]), event["payload"])
        self.assertNotEqual(module._dedupe(job, OWNER), module._dedupe(job, APPROVER))


class RecordingCursor:
    def __init__(self, factory):
        self.factory, self.answer = factory, []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, args=()):
        self.factory.queries.append((sql, args))
        if "to_regclass(" in sql:
            self.answer = [self.factory.schema]
        elif sql == module._CANDIDATES:
            after = args[0]
            self.answer = [(wid,) for wid in self.factory.candidates if after is None or wid > after][:args[3]]
        elif sql.startswith("SELECT state FROM public.pr_workspaces"):
            state = self.factory.states.get(args[0])
            self.answer = [] if state is None else [(copy.deepcopy(state),)]
        elif sql == module._RECIPIENTS:
            self.answer = [(actor,) for actor in self.factory.recipients][:args[2]]
        elif "INSERT INTO public.pr_notification_events" in sql:
            self.answer = [("00000000-0000-4000-8000-000000000301",)]
        elif "INSERT INTO public.pr_notification_deliveries" in sql:
            self.answer = [("00000000-0000-4000-8000-000000000401",)]
        else:
            self.answer = []

    def fetchone(self):
        return self.answer.pop(0) if self.answer else None

    def fetchall(self):
        answer, self.answer = self.answer, []
        return answer


class RecordingDB:
    def __init__(self, factory):
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return RecordingCursor(self.factory)

    def commit(self):
        if self.factory.commit_failure:
            raise RuntimeError("synthetic commit failure")
        self.factory.commits += 1


class RecordingFactory:
    def __init__(self):
        self.states = {WORKSPACE: fixture()}
        self.candidates = [WORKSPACE]
        self.recipients = [OWNER, APPROVER]
        self.schema = tuple("present" for _ in range(6))
        self.queries = []
        self.commits = 0
        self.connections = 0
        self.commit_failure = False

    def __call__(self):
        self.connections += 1
        return RecordingDB(self)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.factory = RecordingFactory()
        self.notifications = SimpleNamespace(enabled=lambda: True, clock=lambda: NOW,
                                             emit=Mock(return_value={"created": True}))
        self.hosted = SimpleNamespace(substack=SimpleNamespace(enabled=True), notifications=self.notifications,
                                      repository=SimpleNamespace(connection_factory=self.factory))

    def test_flags_off_do_not_even_open_database(self):
        self.hosted.substack.enabled = False
        self.assertEqual(module.scan(self.hosted)["status"], "disabled")
        self.hosted.substack.enabled = True
        self.notifications.enabled = lambda: False
        self.assertEqual(module.scan(self.hosted)["status"], "disabled")
        self.assertEqual(self.factory.connections, 0)

    def test_schema_missing_fails_closed_without_emitting(self):
        self.factory.schema = ("present", "present", "present", None, "present", "present")
        self.assertEqual(module.scan(self.hosted)["status"], "schema_unavailable")
        self.notifications.emit.assert_not_called()

    def test_emits_individually_and_never_writes_workspace_or_provider_jobs(self):
        result = module.scan(self.hosted)
        self.assertEqual(result, {"status": "available", "created": 2, "scanned": 1, "failed": 0})
        actors = []
        for call in self.notifications.emit.call_args_list:
            actors.append(call.kwargs["actor"])
            self.assertEqual(call.kwargs["workspace_id"], WORKSPACE)
            self.assertEqual(call.kwargs["channel_filter"], ("in_app",))
            self.assertNotIn("PRIVATE", json.dumps(call.kwargs))
        self.assertEqual(actors, [OWNER, APPROVER])
        self.assertFalse(any("UPDATE public.pr_workspaces" in sql or "pr_publish_jobs" in sql for sql, _ in self.factory.queries))

    def test_current_workspace_state_wins_over_candidate_snapshot(self):
        for change in ("cancel", "disconnect", "workspace", "body"):
            self.setUp()
            state = self.factory.states[WORKSPACE]
            if change == "cancel":
                state["substack"]["drafts"][0]["status"] = "canceled"
            elif change == "disconnect":
                state["substack"]["connections"][0]["status"] = "disconnected"
            elif change == "workspace":
                state["workspace"]["id"] = OTHER
            else:
                state["substack"]["drafts"][0]["body"] = "Changed after candidate selection"
            self.assertEqual(module.scan(self.hosted)["created"], 0)
            self.notifications.emit.assert_not_called()

    def test_no_current_recipient_does_not_spend_an_event_key(self):
        self.factory.recipients = []
        self.assertEqual(module.scan(self.hosted)["created"], 0)
        self.notifications.emit.assert_not_called()

    def test_emit_error_is_isolated_and_next_recipient_can_succeed(self):
        self.notifications.emit.side_effect = [RuntimeError("synthetic outbox failure"), {"created": True}]
        result = module.scan(self.hosted)
        self.assertEqual((result["status"], result["created"], result["failed"]), ("partial", 1, 1))
        self.assertTrue(any("ROLLBACK TO SAVEPOINT substack_notification" in sql for sql, _ in self.factory.queries))

    def test_failed_commit_never_reports_a_created_notification(self):
        self.factory.commit_failure = True
        result = module.scan(self.hosted)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["failed"], 1)

    def test_limit_bounds_delivery_attempts(self):
        result = module.scan(self.hosted, limit=1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(self.notifications.emit.call_count, 1)
        for limit in (0, -1, True, "50"):
            self.setUp()
            self.assertEqual(module.scan(self.hosted, limit=limit)["created"], 0)
            self.assertEqual(self.factory.connections, 0)

    def test_invalid_budget_is_no_work(self):
        for budget in (0, -1, True, "2", float("nan"), float("inf")):
            self.assertEqual(module.scan(self.hosted, budget_seconds=budget)["created"], 0)
        self.assertEqual(self.factory.connections, 0)

    def test_fresh_scan_paginates_past_stale_and_locked_first_candidates(self):
        self.factory.states[WORKSPACE] = None
        self.factory.states[OTHER] = fixture(OTHER)
        self.factory.candidates = [WORKSPACE, OTHER]
        result = module.scan(self.hosted, limit=1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(self.notifications.emit.call_args.kwargs["workspace_id"], OTHER)
        queries = [args for sql, args in self.factory.queries if sql == module._CANDIDATES]
        self.assertEqual([args[0] for args in queries], [None, WORKSPACE])


class OutboxFilterTests(unittest.TestCase):
    def test_real_planner_outbound_preferences_cannot_escape_in_app_filter(self):
        factory = RecordingFactory()
        cur = RecordingCursor(factory)
        job = module.due_jobs(fixture(), NOW)[0]
        event = module._event(WORKSPACE, job, APPROVER)
        member = {"userId": APPROVER, "membership": Membership("approver"), "active": True}
        prefs = {("*", "*"): {"email_mode": "immediate", "push_mode": "immediate"}}
        raw = planner.plan({"event_type": module.EVENT_TYPE, "workspace_id": WORKSPACE}, member, prefs, NOW,
                           email_available=True, push_available=True)
        self.assertTrue(any(item["channel"] == "email" and item["status"] == "pending" for item in raw))
        self.assertTrue(any(item["channel"] == "push" and item["status"] == "pending" for item in raw))
        with patch.object(store, "members", return_value=[member]), patch.object(store, "preference_rows", return_value=prefs), \
                patch.object(store, "recent_counts", return_value={}), patch.object(store, "push_available", return_value=True):
            result = store.emit(cur, **event, now=NOW, email_available=True, push_enabled=True)
        self.assertEqual([item["channel"] for item in result["deliveries"]], ["in_app"])
        self.assertEqual([args[3] for sql, args in factory.queries if "INSERT INTO public.pr_notification_deliveries" in sql], ["in_app"])

    def test_filter_also_blocks_phone_sms_and_digest_even_if_planner_returns_them(self):
        factory = RecordingFactory()
        event = module._event(WORKSPACE, module.due_jobs(fixture(), NOW)[0], APPROVER)
        member = {"userId": APPROVER, "membership": Membership("approver"), "active": True}
        planned = [{"channel": channel, "mode": "in_app" if channel == "in_app" else "immediate",
                    "status": "delivered" if channel == "in_app" else "pending", "next_attempt_at": NOW}
                   for channel in ("in_app", "email", "push", "sms", "phone")]
        with patch.object(store, "members", return_value=[member]), patch.object(store, "preference_rows", return_value={}), \
                patch.object(store, "recent_counts", return_value={}), patch.object(store.planner, "plan", return_value=planned):
            result = store.emit(RecordingCursor(factory), **event, now=NOW)
        self.assertEqual([item["channel"] for item in result["deliveries"]], ["in_app"])


if __name__ == "__main__":
    unittest.main()
