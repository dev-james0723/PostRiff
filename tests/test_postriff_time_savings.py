"""Time Back rules without a database (docs/raffi-time-back/ENGINEERING.md §16): baselines and their precedence, the
saving formula and its provenance, dedupe keys, the metadata allowlist, display reconciliation, which state changes
count as completed outcomes, failure isolation around the worker hook, input bounds and the HTTP surface.
PostgreSQL behaviour (ledger, RLS, worker, repair) is covered by tests/phase2/postgres_time_savings.py."""
import io
import json
import random
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2 import time_savings as tb
from postriff_phase2.api_tokens import route_scope
from postriff_phase2.hosted_app import HostedApplication

WS = "00000000-0000-0000-0000-00000000000a"
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"
NOW = 1_800_000_000.0


class FakeCursor:
    """Records statements; fails on the first statement containing `fail_on`; answers every read with nothing."""
    def __init__(self, fail_on=None):
        self.statements, self.fail_on = [], fail_on

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("database fault")

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def job(state="verified", approver=ONE, actor=ONE, job_id="a" * 32):
    return {"id": job_id, "state": state, "approvedBy": approver, "approvedAt": NOW - 60, "verification": {"method": "provider_lookup", "at": NOW} if state == "verified" else None,
            "manifest": {"actor": actor, "variantId": "v" * 32, "channelId": "c" * 32, "platform": "LinkedIn"}}


class Baselines(unittest.TestCase):
    def test_defaults_are_versioned_and_conservative(self):
        self.assertEqual(tb.resolve_baseline("draft"), (480, "raffi_default", tb.DEFAULTS_VERSION))
        self.assertEqual({kind: tb.resolve_baseline(kind)[0] for kind in tb.TASK_KINDS},
                         {"draft": 480, "adapt": 240, "publish": 180, "campaign_plan": 900, "recurring_setup": 600})

    def test_override_beats_personalized_beats_default(self):
        self.assertEqual(tb.resolve_baseline("draft", 1500, [600, 900, 1200]), (1500, "user_override", tb.OVERRIDE_VERSION))
        self.assertEqual(tb.resolve_baseline("draft", None, [600, 900, 1200]), (900, "personalized", tb.PERSONALIZED_VERSION))
        self.assertEqual(tb.resolve_baseline("draft", None, [600, 900])[1], "raffi_default", "two answers are not enough")

    def test_personalized_median_is_the_lower_median_of_the_latest_seven(self):
        self.assertEqual(tb.resolve_baseline("publish", None, [300, 600, 900, 1200])[0], 600)
        # Newest first: only the latest seven count, so the three old 14400s fall out of the window.
        self.assertEqual(tb.resolve_baseline("publish", None, [60] * 7 + [14400] * 3)[0], 60)

    def test_saving_floors_at_zero_and_labels_provenance(self):
        self.assertEqual(tb.saving(480, None, "raffi_default"), (480, "estimated"))
        self.assertEqual(tb.saving(900, None, "personalized"), (900, "personalized"))
        self.assertEqual(tb.saving(900, None, "user_override"), (900, "personalized"))
        self.assertEqual(tb.saving(480, 130, "raffi_default"), (350, "measured"))
        self.assertEqual(tb.saving(480, 4000, "personalized"), (0, "measured"))


class Keys(unittest.TestCase):
    def test_dedupe_key_is_stable_and_scoped(self):
        base = tb.dedupe_key(WS, ONE, "publish", "verified_publication", "job:" + "a" * 32)
        self.assertRegex(base, r"^[0-9a-f]{64}$")
        self.assertEqual(base, tb.dedupe_key(WS, ONE, "publish", "verified_publication", "job:" + "a" * 32))
        variants = {tb.dedupe_key(WS.replace("a", "b"), ONE, "publish", "verified_publication", "job:" + "a" * 32),
                    tb.dedupe_key(WS, TWO, "publish", "verified_publication", "job:" + "a" * 32),
                    tb.dedupe_key(WS, ONE, "draft", "verified_publication", "job:" + "a" * 32),
                    tb.dedupe_key(WS, ONE, "publish", "verified_publication", "job:" + "b" * 32),
                    tb.dedupe_key(WS, ONE, "publish", "verified_publication", "job:" + "a" * 32, "time-back-v2")}
        self.assertNotIn(base, variants)
        self.assertEqual(len(variants), 5)

    def test_metadata_allowlist_strips_free_form_content(self):
        cleaned = tb.clean_metadata({"platform": "LinkedIn", "language": "zh-Hant-HK", "channelId": "c" * 32, "groupRef": "run:" + "r" * 36, "source": "worker",
                                     "caption": "Our launch is live!", "prompt": "write a post", "email": "a@b.c", "token": "secret"})
        self.assertEqual(cleaned, {"platform": "LinkedIn", "language": "zh-Hant-HK", "channelId": "c" * 32, "groupRef": "run:" + "r" * 36, "source": "worker"})
        self.assertEqual(tb.clean_metadata({"language": "繁體中文"}), {"language": "繁體中文"}, "a language name, not content")
        self.assertEqual(tb.clean_metadata({"platform": "<script>alert(1)</script>", "source": "anything", "channelId": 7, "language": "x" * 40}), {})
        self.assertEqual(tb.clean_metadata("not a dict"), {})


class Display(unittest.TestCase):
    def test_breakdown_minutes_add_up_to_the_displayed_total(self):
        rng = random.Random(7)
        for _ in range(2000):
            parts = [rng.randint(0, 20000) for _ in range(rng.randint(1, 5))]
            minutes = tb.allocate_minutes(parts)
            self.assertEqual(sum(minutes), tb.display_minutes(sum(parts)), parts)
            for part, shown in zip(parts, minutes):
                self.assertIn(shown, (part // 60, part // 60 + 1))
                if part % 60 == 0:
                    self.assertEqual(shown, part // 60, "no minute for a part without seconds towards it")

    def test_display_rounds_to_the_nearest_minute(self):
        self.assertEqual([tb.display_minutes(s) for s in (0, 29, 30, 89, 90, 31320)], [0, 0, 1, 1, 2, 522])

    def test_ranges(self):
        self.assertEqual(tb.range_start("7d", NOW), NOW - 7 * 86400)
        self.assertEqual(tb.range_start("30d", NOW), NOW - 30 * 86400)
        self.assertIsNone(tb.range_start("all", NOW))
        new_year_utc = datetime(datetime.fromtimestamp(NOW, timezone.utc).year, 1, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(tb.range_start("year", NOW), new_year_utc)
        self.assertEqual(tb.range_start("year", NOW, "Asia/Hong_Kong"), new_year_utc - 8 * 3600)
        self.assertEqual(tb.range_start("year", NOW, "Not/AZone"), new_year_utc)
        with self.assertRaises(AlphaError):
            tb.range_start("forever", NOW)


def state_with(jobs=(), occurrences=(), tasks=(), variants=()):
    return {"variants": list(variants), "phase2": {"jobs": list(jobs)}, "raffi": {"campaignPlanning": {"occurrences": list(occurrences), "recurringTasks": list(tasks)}}}


class Outcomes(unittest.TestCase):
    def test_a_new_publish_job_completes_its_draft(self):
        found = tb.completed_outcomes(state_with(), state_with(jobs=[job(state="scheduled")]))
        self.assertEqual(found, [{"taskKind": "draft", "variantId": "v" * 32, "principal": ONE, "at": NOW - 60, "channelId": "c" * 32}])
        self.assertEqual(tb.completed_outcomes(state_with(jobs=[job()]), state_with(jobs=[job()])), [], "an existing job is not a new completion")

    def test_generation_suggestions_and_mismatched_approvals_complete_nothing(self):
        generated = state_with(variants=[{"id": "v" * 32, "platform": "LinkedIn", "revisions": [{"origin": "ideas-candidate"}]}])
        self.assertEqual(tb.completed_outcomes(state_with(), generated), [])
        self.assertEqual(tb.completed_outcomes(state_with(), state_with(jobs=[job(state="scheduled", approver=TWO)])), [])

    def test_a_person_approving_an_automation_post_completes_its_draft(self):
        before = {"id": "o1", "items": [{"key": "LinkedIn||English", "state": "ready_for_review", "variantId": "v" * 32}]}
        approved = {"id": "o1", "items": [{"key": "LinkedIn||English", "state": "approved", "approvedVia": "human", "variantId": "v" * 32,
                                           "decision": {"decision": "approve", "by": TWO, "at": NOW}}]}
        self.assertEqual(tb.completed_outcomes(state_with(occurrences=[before]), state_with(occurrences=[approved])),
                         [{"taskKind": "draft", "variantId": "v" * 32, "principal": TWO, "at": NOW, "channelId": None}])
        self.assertEqual(tb.completed_outcomes(state_with(occurrences=[approved]), state_with(occurrences=[approved])), [])
        standing = {"id": "o1", "items": [{**approved["items"][0], "approvedVia": "owner_preauthorization"}]}
        self.assertEqual(tb.completed_outcomes(state_with(occurrences=[before]), state_with(occurrences=[standing])), [], "pre-authorization is not a review")

    def test_recurring_setup_counts_activation_only(self):
        draft = {"id": "t" * 32, "status": "draft", "schedule": {"kind": "weekly"}}
        active = {**draft, "status": "active", "activatedBy": ONE, "activatedAt": NOW}
        self.assertEqual(tb.completed_outcomes(state_with(tasks=[draft]), state_with(tasks=[active])),
                         [{"taskKind": "recurring_setup", "taskId": "t" * 32, "principal": ONE, "at": NOW}])
        self.assertEqual(len(tb.completed_outcomes(state_with(), state_with(tasks=[active]))), 1, "created active by chat")
        self.assertEqual(tb.completed_outcomes(state_with(tasks=[{**draft, "status": "paused"}]), state_with(tasks=[active])), [], "a resume is not setup")
        self.assertEqual(tb.completed_outcomes(state_with(tasks=[active]), state_with(tasks=[active])), [])
        once = {**active, "schedule": {"kind": "once"}}
        self.assertEqual(tb.completed_outcomes(state_with(tasks=[draft]), state_with(tasks=[once])), [], "a one-time post is not a recurring workflow")

    def test_malformed_state_completes_nothing(self):
        self.assertEqual(tb.completed_outcomes({}, {"phase2": {"jobs": "x"}, "raffi": {"campaignPlanning": None}}), [])

    def test_group_follows_derivations_to_the_root_run(self):
        root = {"id": "r" * 32, "provenance": {"runId": "11111111-1111-1111-1111-111111111111"}}
        child = {"id": "c" * 32, "provenance": {"runId": "22222222-2222-2222-2222-222222222222", "derivedFrom": root["id"]}}
        loop = {"id": "l" * 32, "provenance": {"derivedFrom": "l" * 32}}
        variants = {v["id"]: v for v in (root, child, loop)}
        self.assertEqual(tb.group_ref(variants, child), "run:11111111-1111-1111-1111-111111111111")
        self.assertEqual(tb.group_ref(variants, loop), "variant:" + "l" * 32)


class Isolation(unittest.TestCase):
    def test_only_a_verified_job_can_earn_publish_time(self):
        for state in ("published", "uncertain", "failed", "provider_accepted", "processing", "held", "canceled"):
            cur = FakeCursor()
            self.assertEqual(tb.record_verified_publish(cur, WS, job(state=state))["reason"], "not_verified", state)
            self.assertEqual(cur.statements, [], state)

    def test_an_approver_who_is_not_the_manifest_actor_earns_nothing(self):
        cur = FakeCursor()
        self.assertEqual(tb.record_verified_publish(cur, WS, job(approver=TWO))["reason"], "no_beneficiary")
        self.assertEqual(cur.statements, [])

    def test_a_database_fault_is_contained_and_left_for_repair(self):
        failures, verified = [], job()
        cur = FakeCursor(fail_on="pr_memberships")
        result = tb.record_verified_publish(cur, WS, verified, failures=failures)
        self.assertEqual(result, {"recorded": False, "reason": "pending_repair"})
        self.assertEqual(verified["timeSavings"], "pending")
        self.assertEqual(verified["state"], "verified")
        self.assertEqual(failures, ["RuntimeError"])
        self.assertTrue(cur.statements[0].startswith("SAVEPOINT time_back_"))
        self.assertTrue(any(s.startswith("ROLLBACK TO SAVEPOINT time_back_") for s in cur.statements))

    def test_a_broken_transaction_is_reported_not_raised(self):
        failures = []
        self.assertEqual(tb.guarded(FakeCursor(fail_on="SAVEPOINT"), lambda: 1, failures=failures)[0], None)
        self.assertEqual(failures, ["RuntimeError"])

    def test_time_back_runs_after_a_failing_first_hook_whose_error_still_surfaces(self):
        calls = []

        class Recorder:
            def record_verified_publish(self, cur, workspace_id, job):
                calls.append(workspace_id)

        def audience(cur, workspace_id, job):
            raise KeyError("provider")

        hook = tb.with_time_back(audience, Recorder())
        with self.assertRaises(KeyError):
            hook(FakeCursor(), WS, job())
        self.assertEqual(calls, [WS])
        tb.with_time_back(None, Recorder())(FakeCursor(), WS, job())
        self.assertEqual(calls, [WS, WS])


class Bounds(unittest.TestCase):
    def heartbeat(self, cur=None, **changes):
        payload = {"clientSessionKey": "k" * 24, "workflowKey": "variant:" + "v" * 32, "taskKind": "draft", "activeSeconds": 30, "sequence": 1, **changes}
        return tb.upsert_active_session(cur or FakeCursor(), WS, ONE, payload, NOW)

    def test_heartbeats_reject_free_form_and_out_of_range_values(self):
        cur = FakeCursor()
        self.heartbeat(cur)
        self.assertTrue(any("INSERT INTO public.pr_active_work_sessions" in s for s in cur.statements), "well-formed input reaches the database")
        for changes in ({"clientSessionKey": "short"}, {"workflowKey": "variant:has spaces and prose"}, {"workflowKey": "page:" + "x" * 10},
                        {"workflowKey": "variant:" + "v" * 65}, {"taskKind": "reporting"}, {"taskKind": "campaign_plan"},
                        {"activeSeconds": -1}, {"activeSeconds": 86401}, {"activeSeconds": True}, {"activeSeconds": 12.5}, {"sequence": 0}):
            with self.subTest(changes=changes), self.assertRaises(AlphaError):
                self.heartbeat(**changes)

    def test_calibrations_are_bounded(self):
        for payload in ({"taskKind": "campaign_plan", "source": "prompt", "manualSeconds": 600}, {"taskKind": "draft", "source": "guess", "manualSeconds": 600},
                        {"taskKind": "draft", "source": "prompt", "manualSeconds": 59}, {"taskKind": "draft", "source": "prompt", "manualSeconds": 14401},
                        {"taskKind": "draft", "source": "prompt", "manualSeconds": True}, {"taskKind": "draft", "source": "settings_override"}, "600"):
            with self.subTest(payload=payload), self.assertRaises(AlphaError):
                tb.record_calibration(FakeCursor(), WS, ONE, payload, NOW)

    def test_record_outcome_rejects_unsupported_input_before_any_sql(self):
        for args in (("campaign_plan", "activated_campaign", "campaign:x"), ("draft", "verified_publication", "variant:x"), ("draft", "accepted_draft", "has spaces"),
                     ("draft", "accepted_draft", ""), ("reporting", "accepted_draft", "variant:x")):
            cur = FakeCursor()
            with self.subTest(args=args), self.assertRaises(AlphaError):
                tb.record_outcome(cur, WS, ONE, *args, None, NOW)
            self.assertEqual(cur.statements, [])
        with self.assertRaises(AlphaError):
            tb.record_outcome(FakeCursor(), WS, ONE, "draft", "accepted_draft", "variant:x", ["free text"], NOW)
        with self.assertRaises(AlphaError):
            tb.record_outcome(FakeCursor(), WS, ONE, "draft", "accepted_draft", "variant:x", None, None)

    def test_an_unknown_beneficiary_writes_nothing(self):
        cur = FakeCursor()
        self.assertEqual(tb.record_outcome(cur, WS, "worker-7", "publish", "verified_publication", "job:x", None, NOW)["reason"], "no_beneficiary")
        self.assertEqual(cur.statements, [])


class Surface(unittest.TestCase):
    def test_api_tokens_have_no_time_back_scope(self):
        for method, tail in (("GET", ["time-savings"]), ("POST", ["time-savings", "activity"]), ("POST", ["time-savings", "calibrations"])):
            self.assertIsNone(route_scope(method, ["api", "workspaces", WS, *tail]))

    def test_the_service_refuses_api_tokens_before_reading_anything(self):
        class Repository:
            def verify_session(self, token):
                raise AssertionError("an API token must not reach session verification")

        with self.assertRaises(AlphaError) as raised:
            tb.TimeSavingsService(Repository()).summary(WS, "prt_" + "x" * 40)
        self.assertEqual((raised.exception.status, raised.exception.code), (403, "token_scope_denied"))
        with self.assertRaises(AlphaError) as raised:
            tb.TimeSavingsService(Repository()).summary("not-a-workspace", "session-token-" + "x" * 30)
        self.assertEqual(raised.exception.status, 403)

    def test_routes_reach_the_time_back_service(self):
        calls = []

        class TimeSavings:
            def summary(self, workspace_id, token, range_key):
                calls.append(("summary", workspace_id, range_key))
                return {"range": range_key}

            def activity(self, workspace_id, token, body):
                calls.append(("activity", workspace_id, body["sequence"]))
                return {"accepted": True}

            def calibrate(self, workspace_id, token, body):
                calls.append(("calibrate", workspace_id, body["taskKind"]))
                return {"taskKind": body["taskKind"]}

        class Service:
            time_savings = TimeSavings()

        app = HostedApplication(Service(), None, {"provider": "dev"})
        auth = {"Authorization": "Bearer " + "s" * 40, "X-PostRiff-Request": "founder-alpha"}

        def call(method, path, body=None, query=""):
            raw = json.dumps(body).encode() if body is not None else b""
            environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
                       "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "https", "HTTP_HOST": "postriff.example", "HTTP_ORIGIN": "https://postriff.example",
                       **{"HTTP_" + key.upper().replace("-", "_"): value for key, value in auth.items()}}
            captured = {}
            body_out = b"".join(app(environ, lambda status, headers: captured.update(status=status)))
            return int(captured["status"].split()[0]), json.loads(body_out)

        self.assertEqual(call("GET", f"/api/workspaces/{WS}/time-savings", query="range=7d"), (200, {"range": "7d"}))
        self.assertEqual(call("GET", f"/api/workspaces/{WS}/time-savings")[1], {"range": "30d"})
        self.assertEqual(call("POST", f"/api/workspaces/{WS}/time-savings/activity", {"sequence": 3})[0], 200)
        self.assertEqual(call("POST", f"/api/workspaces/{WS}/time-savings/calibrations", {"taskKind": "draft"})[0], 200)
        self.assertEqual(call("DELETE", f"/api/workspaces/{WS}/time-savings", {})[0], 404)
        self.assertEqual(calls, [("summary", WS, "7d"), ("summary", WS, "30d"), ("activity", WS, 3), ("calibrate", WS, "draft")])


if __name__ == "__main__":
    unittest.main()
