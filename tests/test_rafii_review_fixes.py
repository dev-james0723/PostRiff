"""Regression tests for the WP10-WP11 adversarial review findings (see HANDOFF.md, "Review findings").

Each test pins one fixed defect: the week-ready count, automation approval/failure parity and per-subscription
activation in the notification detector; send-time opt-outs; expired approvals in the weekly Queue read-back;
time-zone-correct performance features, the 7-day weekly window and deterministic anomalies; content-addressed
sources; array schemas with items; the weekly-prepare ledger claiming only what the call drafted; Svix signature
headers with odd bytes; the push transport refusing redirects; and the registry's production-workflow and
product-copy leak gates.
"""
import base64
import hashlib
import hmac
import os
import pathlib
import tempfile
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError
from postriff_phase2 import skill_registry
from postriff_phase2.coworker import performance, source_intake, weekly_operator
from postriff_phase2.notifications import detector, planner, push, webhooks

HK = ZoneInfo("Asia/Hong_Kong")


class DetectorTest(unittest.TestCase):
    NOW = 1_790_150_400

    def test_week_ready_counts_only_drafted_and_checked_posts(self):
        week = {"id": "wk1", "weekOf": "2026-09-28", "state": "ready_for_review",
                "slots": [{"status": "ready"}, {"status": "channel_unavailable"}, {"status": "needs_input"}, {"status": "rejected"}]}
        event = next(e for e in detector.from_state("ws", {"coworker": {"weekly": {"weeks": [week]}}}, self.NOW) if e["event_type"] == "campaign.week_ready")
        self.assertEqual(event["payload"]["count"], 1)

    def automation_state(self, items, notices=None):
        return {"raffi": {"campaignPlanning": {"recurringTasks": [{"id": "t1", "name": "Weekly specials"}],
                                               "occurrences": [{"id": "o1", "taskId": "t1", "lifecycle": "drafted", "items": items, "notices": notices or {}}]}}}

    def test_automation_approval_requests_follow_the_worker_notice_and_voided_approvals_ask_again(self):
        waiting = [{"key": "a", "platform": "LinkedIn", "state": "ready_for_review", "reason": None}]
        self.assertFalse([e for e in detector.from_state("ws", self.automation_state(waiting), self.NOW) if e["event_type"] == "campaign.approval_required"])
        asked = [e for e in detector.from_state("ws", self.automation_state(waiting, {"reviewSentAt": self.NOW}), self.NOW) if e["event_type"] == "campaign.approval_required"]
        self.assertEqual([e["dedupe_key"] for e in asked], [f"automation_review:o1:{self.NOW}"])
        voided = [{"key": "a", "platform": "LinkedIn", "state": "ready_for_review", "reason": "The draft changed. Approve it again.", "changedAt": self.NOW + 60}]
        again = [e for e in detector.from_state("ws", self.automation_state(voided, {"reviewSentAt": self.NOW}), self.NOW) if e["dedupe_key"].startswith("approval_again:")]
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["payload"]["platform"], "LinkedIn")

    def test_item_level_failures_are_publish_failed(self):
        items = [{"key": "a", "platform": "Threads", "state": "failed", "reason": "It couldn't be queued in time.", "changedAt": self.NOW}]
        failed = [e for e in detector.from_state("ws", self.automation_state(items), self.NOW) if e["event_type"] == "publish.failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("queued in time", failed[0]["payload"]["reason"])

    def test_generated_images_and_source_campaigns_waiting_on_the_person_have_producers(self):
        state = {"phase2": {"assets": [{"id": "img1", "origin": "rafii_agent", "lineage": {"operation": "generated"}}, {"id": "up1", "origin": "upload"}],
                            "jobs": []},
                 "coworker": {"sourceCampaigns": [{"id": "sc1", "status": "needs_source"}, {"id": "sc2", "status": "ready_for_review"}]}}
        types = [(e["event_type"], e["entity_id"]) for e in detector.from_state("ws", state, self.NOW)]
        self.assertIn(("asset.review_required", "img1"), types)
        self.assertNotIn(("asset.review_required", "up1"), types)
        self.assertIn(("research.needs_input", "sc1"), types)
        self.assertNotIn(("research.needs_input", "sc2"), types)

    def test_subscription_active_is_keyed_on_the_subscription_not_the_renewal(self):
        class Cursor:
            def __init__(self, sub):
                self.sub, self.last = sub, None

            def execute(self, sql, params=None):
                self.last = sql

            def fetchone(self):
                return self.sub if "pr_subscriptions" in self.last else None

            def fetchall(self):
                return []
        now = time.time()
        first = Cursor(("active", now, now + 30 * 86400, now, "sub_123"))
        renewal = Cursor(("active", now + 31 * 86400, now + 60 * 86400, now + 31 * 86400, "sub_123"))
        keys = [next(e["dedupe_key"] for e in detector.from_database(c, "ws", c.sub[3]) if e["event_type"] == "billing.subscription_active") for c in (first, renewal)]
        self.assertEqual(keys[0], keys[1])      # a renewal is not a new activation


class SendTimePreferenceTest(unittest.TestCase):
    def test_opt_outs_are_rechecked_at_send_time_and_transactional_notices_ignore_them(self):
        now = 1_790_000_000
        self.assertEqual(planner.opted_out("publish.failed", "email", "immediate", {"email_unsubscribed": True}, now), "unsubscribed")
        self.assertEqual(planner.opted_out("publish.failed", "push", "immediate", {"muted_until": now + 60}, now), "muted")
        self.assertEqual(planner.opted_out("campaign.drafts_ready", "email", "digest", {"digest_frequency": "off"}, now), "digest_off")
        self.assertIsNone(planner.opted_out("publish.failed", "email", "immediate", {"email_unsubscribed": False}, now))
        self.assertIsNone(planner.opted_out("billing.payment_failed", "email", "immediate", {"email_unsubscribed": True, "muted_until": now + 60}, now))

    def test_a_narrower_resubscribe_overrides_a_broader_unsubscribe(self):
        rows = {("*", "*"): {"email_unsubscribed": True}, ("ws", "publishing"): {"email_unsubscribed": False}}
        self.assertIs(planner.effective_preferences(rows, "ws", "publishing")["email_unsubscribed"], False)
        self.assertIs(planner.effective_preferences(rows, "ws", "weekly")["email_unsubscribed"], True)


class WeeklyQueueReadBackTest(unittest.TestCase):
    NOW = 1_790_150_400

    def week(self, statuses):
        return {"id": "wk", "state": "ready_for_review", "history": [], "slots": [{"id": f"s{i}", "status": "accepted", "variantId": f"v{i}"} for i in range(len(statuses))]}

    def test_one_expired_approval_blocks_the_week_even_when_another_post_is_scheduled(self):
        week = self.week([0, 1])
        state = {"phase2": {"reviews": [{"status": "stale", "manifest": {"variantId": "v0"}}], "jobs": [{"state": "scheduled", "manifest": {"variantId": "v1"}}]}}
        weekly_operator.sync_from_queue(state, week, self.NOW)
        self.assertEqual([s["status"] for s in week["slots"]], ["approval_expired", "scheduled"])
        self.assertEqual(week["state"], "approval_expired")
        self.assertIn("expired", week["blockedReason"])
        self.assertFalse(any("every accepted post was approved" in (h.get("note") or "") for h in week["history"]))

    def test_every_approval_expired_blocks_the_week_and_renewal_reopens_it(self):
        week = self.week([0])
        state = {"phase2": {"reviews": [{"status": "stale", "manifest": {"variantId": "v0"}}], "jobs": []}}
        weekly_operator.sync_from_queue(state, week, self.NOW)
        self.assertEqual(week["state"], "approval_expired")
        state["phase2"]["jobs"] = [{"state": "scheduled", "manifest": {"variantId": "v0"}}]
        weekly_operator.sync_from_queue(state, week, self.NOW)
        self.assertEqual(week["state"], "scheduled")


class PerformanceWindowTest(unittest.TestCase):
    def job(self, local, zone="Asia/Hong_Kong"):
        stamp = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(zone)).timestamp()
        return {"manifest": {"timing": {"timestamp": stamp, "timeZone": zone}, "payload": {"text": "Hello"}}}

    def test_features_use_the_posts_own_time_zone(self):
        self.assertEqual(performance.features(self.job("2026-09-26T07:00"))["weekday"], "weekend")     # Saturday morning in Hong Kong
        self.assertEqual(performance.features(self.job("2026-09-26T07:00"))["time"], "morning")
        self.assertEqual(performance.features(self.job("2026-09-24T09:00", "America/New_York"))["time"], "morning")
        self.assertEqual(performance.features(self.job("2026-09-24T20:00", "America/New_York"))["time"], "later")

    def rows(self, now, recent_value):
        cohort = {"provider": "threads", "language": "en", "definitionVersion": "2026-09"}
        rows = [{"postId": f"p{i}", "jobId": f"j{i}", "provider": "threads", "metric": "views", "value": 500 + i, "cohort": cohort,
                 "publishedAt": now - (20 + i) * 86400, "observedAt": now} for i in range(6)]
        rows.append({"postId": "new", "jobId": "jnew", "provider": "threads", "metric": "views", "value": recent_value, "cohort": cohort,
                     "publishedAt": now - 86400, "observedAt": now})
        return rows

    def test_anomalies_need_enough_history_and_a_large_deviation(self):
        now = 1_790_150_400
        self.assertEqual(performance.anomalies(self.rows(now, 520), now), [])
        low = performance.anomalies(self.rows(now, 50), now)
        self.assertEqual([a["postId"] for a in low], ["new"])
        self.assertIn("not a pattern", low[0]["reason"])
        self.assertEqual([a["postId"] for a in performance.anomalies(self.rows(now, 5000), now)], ["new"])
        self.assertEqual(performance.anomalies(self.rows(now, 50)[3:], now), [])     # fewer than MIN_ARM earlier posts


class SourceIdentityTest(unittest.TestCase):
    def test_the_same_source_gets_the_same_id(self):
        first = source_intake.normalize("text", {"text": "Our autumn menu adds three pastries."}, now=1)
        second = source_intake.normalize("text", {"text": "Our autumn menu adds three pastries."}, now=2)
        other = source_intake.normalize("text", {"text": "Our winter menu adds two pies."}, now=1)
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["id"], other["id"])
        for key in ("schema", "id", "format", "title", "text", "segments", "provenance", "createdAt", "untrusted"):
            self.assertIn(key, first)
        self.assertEqual((first["format"], first["title"]), ("text", "Our autumn menu adds three pastries."))


class ToolSchemaTest(unittest.TestCase):
    def test_every_array_parameter_declares_items(self):
        from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
        domain_tools.ensure_registered()
        missing = []

        def walk(name, schema, path):
            if not isinstance(schema, dict):
                return
            if schema.get("type") == "array" and "items" not in schema:
                missing.append(f"{name}:{path}")
            for key, child in (schema.get("properties") or {}).items():
                walk(name, child, f"{path}.{key}")
            if isinstance(schema.get("items"), dict):
                walk(name, schema["items"], f"{path}[]")
        for name, tool in tool_adapter.REGISTRY.items():
            walk(name, tool.schema, "")
        self.assertEqual(missing, [])


class PrepareLedgerTest(unittest.TestCase):
    def test_only_posts_drafted_by_this_call_are_reported_as_changes(self):
        from contextlib import contextmanager
        from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter
        from postriff_phase2.coworker import flags
        domain_tools.ensure_registered()
        week = {"id": "wk", "weekOf": "2026-09-28", "state": "ready_for_review", "blockedReason": None,
                "slots": [{"id": "a", "platform": "LinkedIn", "status": "ready", "variantId": "va"}, {"id": "b", "platform": "Threads", "status": "scheduled", "variantId": "vb"}]}

        class Coworker:
            calls = []

            def weekly_prepare(self, *args, **kwargs):
                self.calls.append(kwargs)
                return {"week": week, "advanced": False, "drafted": 0, "draftedSlotIds": [], "verified": True}

        class Ledger:
            def __init__(self):
                self.changed, self.refs = [], []

            def reference(self, *args):
                self.refs.append(args)

        class Ctx:
            workspace_id, token = "ws", "tok"
            ledger = Ledger()
            service = type("S", (), {"coworker": Coworker()})()

            def remaining(self):
                return None

            @contextmanager
            def workspace(self):
                yield None, None, None, None, {"variants": [{"id": "va"}, {"id": "vb"}]}
        flags.attach({"RAFII_WEEKLY_OPERATOR_ENABLED": "1"})
        try:
            from unittest import mock
            ctx = Ctx()
            with mock.patch("postriff_phase2.coworker.agent_tools._service", return_value=ctx.service):
                result = tool_adapter.REGISTRY["weekly_plan_prepare"].executor(ctx, {"recipeId": "r1"})
        finally:
            flags.attach(None)
        self.assertEqual(ctx.ledger.changed, [])                 # nothing was drafted in this call
        self.assertTrue(result["alreadyPrepared"])
        self.assertEqual(result["draftedThisCall"], 0)
        self.assertEqual(Coworker.calls[-1]["max_slots"], 2)      # a bounded batch per agent turn


class WebhookAndPushTest(unittest.TestCase):
    def test_a_signature_header_with_non_ascii_bytes_is_a_rejection_not_a_crash(self):
        raw_key = os.urandom(32)   # generated per run; never a stored credential
        configured = "whsec_" + base64.b64encode(raw_key).decode()
        now = int(time.time())
        body = b'{"type":"email.delivered","data":{}}'
        with self.assertRaises(AlphaError) as caught:
            webhooks.verify_svix(configured, {"svix-id": "msg_1", "svix-timestamp": str(now), "svix-signature": "v1,ééé"}, body, now=now)
        self.assertEqual(caught.exception.status, 401)
        good = base64.b64encode(hmac.new(raw_key, f"msg_1.{now}.".encode() + body, hashlib.sha256).digest()).decode()
        self.assertTrue(webhooks.verify_svix(configured, {"svix-id": "msg_1", "svix-timestamp": str(now), "svix-signature": f"v1,{good}"}, body, now=now))

    def test_the_push_transport_never_follows_a_redirect(self):
        self.assertIsNone(push._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))


class RegistryGateTest(unittest.TestCase):
    def test_probe_workflows_must_be_entered_by_production_code(self):
        self.assertEqual(skill_registry.production_workflows(), {"rafii-weekly-operator", "rafii-source-to-campaign", "rafii-engagement-triage"})

    def test_product_copy_is_scanned_for_one_persons_examples(self):
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / "web/src/features/coworker/weekly"
            path.mkdir(parents=True)
            (path / "x.tsx").write_text("placeholder='Piano masterclasses in Hong Kong'\nplaceholder='New bakeries nearby'\n")
            findings = skill_registry.copy_leak_findings(root)
        self.assertEqual([(f[1], f[2]) for f in findings], [("web/src/features/coworker/weekly/x.tsx", 1)])
        repo = pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(skill_registry.copy_leak_findings(repo), [])


if __name__ == "__main__":
    unittest.main()
