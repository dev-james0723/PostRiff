"""First Week Ready on disposable PG17 (PRD R-FWR-01..03; AC06–AC10). Real repository commands, Weekly Operator, Queue
read-back and plan entitlements; the writer is the repository's fixture runtime (no provider, no cost)."""
import copy
import datetime as dt
import sys
import unittest
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
import psycopg  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.coworker import flags, runtime as coworker_runtime  # noqa: E402
from postriff_phase2.first_week.service import FirstWeekService  # noqa: E402
from postriff_phase2.hosted import HostedWorkspaceService  # noqa: E402

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
HK = "Asia/Hong_Kong"
VALUES = {**{name: "1" for name in flags.FLAGS}, "RAFII_FIRST_WEEK_ENABLED": "1"}
DRAFT = "Most adult beginners quit piano because they practise pieces, not skills.\nFive minutes on one skill first changes that."


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


class FirstWeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            for name in ("020_credit_quotes.sql", "021_credit_purchases.sql", "022_credit_payment_lifecycle.sql",
                         "048_pricing_credit_catalog_v2.sql", "050_free_lifecycle_bootstrap.sql"):
                db.execute((ROOT / "migrations/postriff" / name).read_text())

    def setUp(self):
        self.clock = [dt.datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo(HK)).timestamp()]
        self.users = {f"tok-{n}-{uuid.uuid4().hex[:12]}": str(uuid.uuid4()) for n in ("owner", "other", "viewer")}
        self.owner, self.other, self.viewer = list(self.users)
        with connection() as db:
            for user in self.users.values():
                db.execute("INSERT INTO auth.users(id) VALUES(%s)", (user,))

        def verify(token):
            if token not in self.users:
                raise AlphaError("Verified session required.", 401)
            return self.users[token]
        verify.session_id = lambda token, principal: f"session-{principal}"
        verify.auth_time = lambda token, principal: self.clock[0]
        self.verify = verify

    def make(self, pricing_v2=False):
        service = HostedWorkspaceService(connection, self.verify, clock=lambda: self.clock[0], public_base_url="https://app.rafii.example",
                                         credits_enabled=True, pricing_v2_enabled=pricing_v2)
        coworker_runtime.attach(service, VALUES)
        service.coworker.clock = lambda: self.clock[0]
        fw = FirstWeekService(service, values=VALUES, clock=lambda: self.clock[0])
        service.first_week = fw
        return service, fw

    def workspace(self, service, token, plan="studio"):
        wid = service.bootstrap(token, plan)["workspaceId"]
        return wid

    def continuation(self, fw, wid, token, key=None, **values):
        body = {"idempotencyKey": key or uuid.uuid4().hex, "consent": True, "platform": "Threads", "language": "en",
                "items": [{"kind": "original", "text": DRAFT}], **values}
        return fw.import_continuation(wid, token, body)

    def journey(self, fw, wid, token):
        return fw.view(wid, token)

    def ready_context(self, fw, wid, token):
        view = self.journey(fw, wid, token)
        if view["missingContext"]:
            fw.set_context(wid, token, {"purpose": "Fill the November cohort", "audience": "Adult piano beginners", "expectedRevision": view["revision"]})
        return self.journey(fw, wid, token)

    def accept(self, fw, wid, token):
        view = self.ready_context(fw, wid, token)
        return fw.accept_draft(wid, token, {"variantId": view["draft"]["variantId"], "variantRevision": view["draft"]["revision"], "expectedRevision": view["revision"]})

    # --- AC06 / AC07: consented continuation ----------------------------------------------------------------------------
    def test_ac06_continuation_imports_selected_text_into_the_chosen_workspace(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        edited = DRAFT + "\nStart tonight."
        result = self.continuation(fw, wid, self.owner, items=[{"kind": "original", "text": DRAFT}, {"kind": "edited", "text": edited}])
        state = service.get(wid, self.owner)["state"]
        variants = {v["id"]: v for v in state["variants"]}
        self.assertEqual(variants[result["variantIds"]["edited"]]["text"], edited)
        self.assertEqual(variants[result["variantIds"]["original"]]["text"], DRAFT)
        self.assertEqual(result["draftVariantId"], result["variantIds"]["edited"])
        self.assertEqual(variants[result["draftVariantId"]]["provenance"]["model"], None)
        self.assertTrue(any(s["id"] == result["sourceId"] for s in state["sources"]))
        self.assertEqual(result["journey"]["step"], "context")
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s", (wid,)).fetchone()[0], 0)   # nothing generated
            events = db.execute("SELECT event,properties FROM pr_product_events WHERE workspace_id=%s AND event='continuation.claimed'", (wid,)).fetchall()
        self.assertEqual(len(events), 1)
        self.assertNotIn(DRAFT[:20], str(events))   # no text in analytics

    def test_ac07_replay_is_idempotent_and_conflicting_reuse_is_refused(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        key = uuid.uuid4().hex
        first = self.continuation(fw, wid, self.owner, key=key)
        again = self.continuation(fw, wid, self.owner, key=key)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["draftVariantId"], first["draftVariantId"])
        self.assertEqual(len(service.get(wid, self.owner)["state"]["variants"]), 1)
        with self.assertRaises(AlphaError) as caught:
            self.continuation(fw, wid, self.owner, key=key, items=[{"kind": "original", "text": "Something else entirely."}])
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_ac07_other_workspace_needs_its_own_explicit_import(self):
        service, fw = self.make()
        mine, theirs = self.workspace(service, self.owner), self.workspace(service, self.other)
        key = uuid.uuid4().hex
        self.continuation(fw, mine, self.owner, key=key)
        with self.assertRaises(AlphaError):   # the key never authorizes: another person's workspace stays closed
            self.continuation(fw, theirs, self.owner, key=key)
        second = self.continuation(fw, theirs, self.other, key=key)
        self.assertFalse(second["replayed"])
        self.assertEqual(len(service.get(mine, self.owner)["state"]["variants"]), 1)

    def test_ac07_consent_limits_and_bad_keys_fail_cleanly(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        cases = [({"consent": False}, "consent_required"), ({"idempotencyKey": "bad key!"}, "unsupported_input"),
                 ({"items": [{"kind": "original", "text": "x" * 8001}]}, "unsupported_input"),
                 ({"items": [{"kind": "original", "text": "   "}]}, "unsupported_input"), ({"platform": "Myspace"}, "unsupported_input")]
        for values, code in cases:
            with self.assertRaises(AlphaError, msg=repr(values)) as caught:
                self.continuation(fw, wid, self.owner, **values)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(service.get(wid, self.owner)["state"].get("variants", []), [])

    # --- AC08: one editable draft, explicit acceptance --------------------------------------------------------------------
    def test_ac08_context_then_acceptance_and_edit_invalidates_acceptance(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.journey(fw, wid, self.owner)
        self.assertEqual(sorted(view["missingContext"]), ["audience", "purpose"])
        stale = view["revision"]
        view = self.ready_context(fw, wid, self.owner)
        self.assertEqual(view["missingContext"], [])
        with self.assertRaises(AlphaError) as caught:   # an old tab's revision is refused
            fw.accept_draft(wid, self.owner, {"variantId": view["draft"]["variantId"], "variantRevision": 1, "expectedRevision": stale})
        self.assertEqual(caught.exception.code, "revision_conflict")
        view = self.accept(fw, wid, self.owner)
        self.assertTrue(view["draft"]["accepted"])
        self.assertEqual(view["step"], "plan")
        state = service.get(wid, self.owner)
        service.mutate(wid, self.owner, state["revision"], "variant_edit", {"variantId": view["draft"]["variantId"], "variantRevision": 1, "text": DRAFT + " Edited."})
        view = self.journey(fw, wid, self.owner)
        self.assertFalse(view["draft"]["accepted"])
        self.assertEqual(view["step"], "accept")
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_product_events WHERE workspace_id=%s AND event='draft.accepted'", (wid,)).fetchone()[0], 1)

    def test_ac08_viewer_cannot_change_the_journey(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        service.bootstrap(self.viewer, "studio")
        with connection() as db:
            db.execute("INSERT INTO pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (wid, self.users[self.viewer]))
        with self.assertRaises(AlphaError) as caught:
            self.continuation(fw, wid, self.viewer)
        self.assertEqual(caught.exception.status, 403)

    # --- AC08 / AC09 / AC10: the week ------------------------------------------------------------------------------------
    def plan(self, service, fw, wid, **values):
        view = self.accept(fw, wid, self.owner)
        return fw.plan(wid, self.owner, {"platform": "Threads", "timeZone": HK, "expectedRevision": view["revision"], **values})

    def test_ac08_unconnected_plan_is_reviewable_without_spend(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        self.assertEqual(len(view["slots"]), 3)
        first = view["slots"][0]
        self.assertEqual((first["status"], first["variantId"]), ("ready", view["draft"]["variantId"]))
        for slot in view["slots"]:
            self.assertEqual(slot["publishBlocker"], "channel_not_connected")
            self.assertTrue(slot["sourceIds"])
        self.assertEqual({s["status"] for s in view["slots"][1:]}, {"planned"})
        self.assertFalse(view["channelConnected"])
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s", (wid,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s", (wid,)).fetchone()[0], 0)

    def test_ac09_scope_freezes_and_changes_are_versioned_with_a_reason(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        ids = [s["id"] for s in view["slots"]]
        view = fw.approve_scope(wid, self.owner, {"slotIds": ids[:2], "expectedRevision": view["revision"]})
        self.assertEqual((view["scope"]["scopeRevision"], view["committed"]), (1, 2))
        self.assertEqual(next(s for s in view["slots"] if s["id"] == ids[2])["status"], "rejected")
        with self.assertRaises(AlphaError):
            fw.approve_scope(wid, self.owner, {"slotIds": ids, "expectedRevision": view["revision"]})   # no reason
        view = fw.approve_scope(wid, self.owner, {"slotIds": ids, "expectedRevision": view["revision"], "reason": "One more post fits"})
        self.assertEqual(view["scope"]["scopeRevision"], 2)
        self.assertEqual(view["scope"]["changes"][-1]["reason"], "One more post fits")
        self.assertEqual(next(s for s in view["slots"] if s["id"] == ids[2])["status"], "planned")

    def test_ac09_replanning_before_commit_replaces_the_suggestion_and_resumes_same_ids(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        week_id = view["week"]["id"]
        resumed = self.journey(fw, wid, self.owner)
        self.assertEqual(resumed["week"]["id"], week_id)          # refresh/reconnect resumes the same week
        view = fw.plan(wid, self.owner, {"platform": "Threads", "timeZone": HK, "postsPerWeek": 2, "expectedRevision": view["revision"]})
        self.assertEqual((view["week"]["id"], len(view["slots"])), (week_id, 2))

    def test_ac10_free_has_no_ai_drafting_but_writes_and_hands_off_truthfully(self):
        service, fw = self.make(pricing_v2=True)
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        self.assertEqual(view["billingMode"], "free_preview")
        ids = [s["id"] for s in view["slots"]]
        view = fw.approve_scope(wid, self.owner, {"slotIds": ids, "expectedRevision": view["revision"]})
        with self.assertRaises(AlphaError) as caught:
            fw.draft_week(wid, self.owner, {"confirmed": True, "expectedRevision": view["revision"]})
        self.assertEqual((caught.exception.status, caught.exception.code), (402, "insufficient_budget"))
        for slot_id in ids[1:]:
            view = fw.write_slot(wid, self.owner, {"weekId": view["week"]["id"], "slotId": slot_id, "text": "My own post about one practice skill.", "expectedRevision": view["revision"]})
        self.assertTrue(all(s["status"] == "ready" for s in view["slots"]))
        for slot_id in ids:
            view = fw.handoff(wid, self.owner, {"weekId": view["week"]["id"], "slotId": slot_id, "action": "export_ready", "expectedRevision": view["revision"]})
        self.assertFalse(view["complete"])
        for slot_id in ids:
            view = fw.handoff(wid, self.owner, {"weekId": view["week"]["id"], "slotId": slot_id, "action": "user_confirmed_used", "expectedRevision": view["revision"]})
        self.assertTrue(view["complete"])
        self.assertTrue(all(s["status"] != "published" for s in view["slots"]))   # assisted, never "published"
        with connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s", (wid,)).fetchone()[0], 0)

    def test_ac10_editing_after_export_marks_the_handoff_stale(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        first = view["slots"][0]
        view = fw.approve_scope(wid, self.owner, {"slotIds": [first["id"]], "expectedRevision": view["revision"]})
        view = fw.handoff(wid, self.owner, {"weekId": view["week"]["id"], "slotId": first["id"], "action": "user_confirmed_used", "expectedRevision": view["revision"]})
        self.assertTrue(view["complete"])
        state = service.get(wid, self.owner)
        service.mutate(wid, self.owner, state["revision"], "variant_edit", {"variantId": first["variantId"], "variantRevision": 1, "text": DRAFT + " Changed."})
        view = self.journey(fw, wid, self.owner)
        self.assertTrue(view["slots"][0]["handoff"]["stale"])
        self.assertFalse(view["complete"])

    def test_legacy_plan_drafts_the_rest_through_the_weekly_operator(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        view = fw.approve_scope(wid, self.owner, {"slotIds": [s["id"] for s in view["slots"]], "expectedRevision": view["revision"]})
        result = fw.draft_week(wid, self.owner, {"confirmed": True, "expectedRevision": view["revision"]})
        statuses = [s["status"] for s in result["journey"]["slots"]]
        self.assertEqual(statuses[0], "ready")
        self.assertTrue(all(s in ("ready", "needs_revision", "needs_input") for s in statuses), statuses)

    def spend(self, service, wid):
        """Everything later weeks could consume: writer runs, usage-ledger rows, Weekly weeks and legacy batches."""
        with connection() as db:
            runs = db.execute("SELECT count(*) FROM pr_agent_runs WHERE workspace_id=%s", (wid,)).fetchone()[0]
            ledger = db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s", (wid,)).fetchone()[0]
            quotes = db.execute("SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s", (wid,)).fetchone()[0]
            batches = db.execute("SELECT writing_batches_remaining FROM pr_entitlements WHERE workspace_id=%s", (wid,)).fetchone()
        weeks = len(service.get(wid, self.owner)["state"]["coworker"]["weekly"]["weeks"])
        return {"runs": runs, "ledger": ledger, "quotes": quotes, "weeks": weeks, "batches": batches[0] if batches else None}

    def test_first_week_limit_drafts_that_week_once_and_never_the_following_weeks(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        view = fw.approve_scope(wid, self.owner, {"slotIds": [s["id"] for s in view["slots"]], "expectedRevision": view["revision"]})
        drafted = fw.draft_week(wid, self.owner, {"confirmed": True, "expectedRevision": view["revision"]})["journey"]
        self.assertEqual(drafted["weeklyDrafting"], "first_week_only")
        first = drafted["week"]["id"]
        state = service.get(wid, self.owner)["state"]
        recipe = next(r for r in state["coworker"]["weekly"]["recipes"] if r["id"] == state["coworker"]["firstWeek"]["recipeId"])
        self.assertEqual((recipe["firstWeek"], recipe["firstWeekId"], recipe["maxCostUsdMicroPerWeek"]), (True, first, 2_000_000))
        before = self.spend(service, wid)
        self.assertGreater(before["runs"], 0, "the first week itself was drafted")
        start = self.clock[0]
        for weeks_later in (1, 2, 3):
            # Friday 10:00 in the recipe's zone: past its planning moment, so an ordinary recipe would plan and draft.
            self.clock[0] = start + weeks_later * 7 * 86400 + 86400
            service.coworker.weekly_cron(max_workspaces=1000)
            with self.assertRaises(AlphaError) as caught:   # the Weekly "prepare" route and the agent tool share this path
                service.coworker.weekly_prepare(wid, self.owner, recipe["id"])
            self.assertEqual((caught.exception.status, caught.exception.code), (409, "weekly_drafting_not_enabled"))
        self.assertEqual(self.spend(service, wid), before)   # no week planned, no run, reservation, quote or batch used
        weeks = service.get(wid, self.owner)["state"]["coworker"]["weekly"]["weeks"]
        self.assertEqual([w["id"] for w in weeks if w["recipeId"] == recipe["id"]], [first])
        # The committed first week itself stays reachable after the calendar moved on (its own Monday, never "next week").
        view = fw.view(wid, self.owner)
        again = fw.draft_week(wid, self.owner, {"confirmed": True, "expectedRevision": view["revision"]})["journey"]
        self.assertEqual(again["week"]["id"], first)
        self.assertEqual(self.spend(service, wid)["weeks"], before["weeks"])

    def test_creator_week_credit_limit_is_one_time(self):
        service, fw = self.make(pricing_v2=True)
        wid = self.workspace(service, self.owner)
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='active' WHERE id='creator-v1'")
            db.execute("UPDATE pr_entitlements SET plan_terms_id='creator-v1',source='subscription' WHERE workspace_id=%s", (wid,))
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,status,current_period_end) VALUES(%s,'creator-v1','active',now()+interval '1 month') "
                       "ON CONFLICT(workspace_id) DO UPDATE SET plan_terms_id='creator-v1',status='active',current_period_end=excluded.current_period_end", (wid,))
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        self.assertEqual(view["billingMode"], "managed_credits")
        view = fw.approve_scope(wid, self.owner, {"slotIds": [s["id"] for s in view["slots"]], "expectedRevision": view["revision"]})
        fw.draft_week(wid, self.owner, {"confirmed": True, "maxCredits": 300, "expectedRevision": view["revision"]})
        state = service.get(wid, self.owner)["state"]
        recipe = next(r for r in state["coworker"]["weekly"]["recipes"] if r["id"] == state["coworker"]["firstWeek"]["recipeId"])
        self.assertEqual((recipe["firstWeek"], recipe["maxCostUsdMicroPerWeek"]), (True, 1_000_000))   # 300 credits = US$1, this week only
        before = self.spend(service, wid)
        self.clock[0] += 8 * 86400
        service.coworker.weekly_cron(max_workspaces=1000)
        with self.assertRaises(AlphaError) as caught:
            service.coworker.weekly_prepare(wid, self.owner, recipe["id"])
        self.assertEqual(caught.exception.code, "weekly_drafting_not_enabled")
        self.assertEqual(self.spend(service, wid), before)

    def test_replanning_a_committed_week_is_refused(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        view = self.plan(service, fw, wid)
        view = fw.approve_scope(wid, self.owner, {"slotIds": [view["slots"][0]["id"]], "expectedRevision": view["revision"]})
        with self.assertRaises(AlphaError) as caught:
            fw.plan(wid, self.owner, {"platform": "Threads", "timeZone": HK, "expectedRevision": view["revision"]})
        self.assertEqual(caught.exception.code, "approval_required")

    def test_continuation_claims_are_counted_per_workspace(self):
        service, fw = self.make()
        mine, theirs = self.workspace(service, self.owner), self.workspace(service, self.other)
        key = uuid.uuid4().hex
        self.continuation(fw, mine, self.owner, key=key)
        self.continuation(fw, mine, self.owner, key=key)   # a replay in the same workspace is the same claim
        self.continuation(fw, theirs, self.other, key=key)
        with connection() as db:
            claims = db.execute("SELECT workspace_id::text,count(*) FROM pr_product_events WHERE event='continuation.claimed' AND workspace_id IN (%s,%s) GROUP BY 1",
                                (mine, theirs)).fetchall()
        self.assertEqual(dict(claims), {mine: 1, theirs: 1})

    def test_subject_is_asked_for_when_the_brand_mode_needs_it(self):
        service, fw = self.make()
        wid = self.workspace(service, self.owner)
        self.continuation(fw, wid, self.owner)
        state = service.get(wid, self.owner)
        service.mutate(wid, self.owner, state["revision"], "mode", {"mode": "business"})
        view = self.journey(fw, wid, self.owner)
        self.assertIn("subject", view["missingContext"])
        self.assertEqual(view["step"], "context")
        view = fw.set_context(wid, self.owner, {"purpose": "Fill the cohort", "audience": "Adult beginners", "subject": "Piano lessons for adults",
                                                "expectedRevision": view["revision"]})
        self.assertEqual((view["missingContext"], view["context"]["subject"]), ([], "Piano lessons for adults"))

    def test_feature_flag_off_is_feature_disabled(self):
        service, _ = self.make()
        wid = self.workspace(service, self.owner)
        off = FirstWeekService(service, values={}, clock=lambda: self.clock[0])
        with self.assertRaises(AlphaError) as caught:
            off.view(wid, self.owner)
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "feature_disabled"))


if __name__ == "__main__":
    unittest.main()
