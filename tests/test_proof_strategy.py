"""Growth Loop proof v2 rules and the next-week strategy loop (PRD R-PROOF-01/02): the pure parts of AC26 (figures,
material digest, correction notes), AC27 (proposals, versioned decisions, scope, applied/not-applied with reasons,
revocation stops future use, identity and voice untouched) and AC34 (immature periods, assisted exports never
inflate verified publications)."""
import copy
import hashlib
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import flags, growth_loop, weekly_operator
from postriff_phase2.proof import model, strategy

DAY = 86400


def at(zone, *parts):
    return datetime(*parts, tzinfo=ZoneInfo(zone)).timestamp()


NOW = at("UTC", 2026, 10, 7, 12, 0)


def counts(**figures):
    base = {name: model.figure(1, definition="d", evidence={"ids": ["a"]}) for name in model.FIGURES}
    base.update(figures)
    return {"definitionVersion": model.DEFINITION_VERSION, "frequency": "weekly", "asOf": NOW, "sourceWatermark": {"queue": NOW}, "figures": base}


class PeriodTest(unittest.TestCase):
    def test_zone_rule_recipe_then_preferences_then_profile_then_utc(self):
        state = {"coworker": {"weekly": {"recipes": [{"id": "b", "status": "active", "timeZone": "Asia/Tokyo", "createdAt": 5},
                                                     {"id": "a", "status": "active", "timeZone": "Asia/Hong_Kong", "createdAt": 1},
                                                     {"id": "c", "status": "paused", "timeZone": "Europe/London", "createdAt": 0}]}}}
        self.assertEqual(model.workspace_zone(state, "Europe/Paris", "America/Chicago"), ("Asia/Hong_Kong", "recipe"))
        self.assertEqual(model.workspace_zone({}, "Europe/Paris", "America/Chicago"), ("Europe/Paris", "notification_preferences"))
        self.assertEqual(model.workspace_zone({}, "Not/AZone", "America/Chicago"), ("America/Chicago", "profile"))
        self.assertEqual(model.workspace_zone({}, None, ""), ("UTC", "default_utc"))

    def test_periods_are_local_civil_periods_dst_safe(self):
        zone = "America/New_York"
        start, end = model.latest_completed(at(zone, 2026, 11, 4, 9, 0), "weekly", zone)
        self.assertEqual((start, end), (at(zone, 2026, 10, 26, 0, 0), at(zone, 2026, 11, 2, 0, 0)))
        self.assertEqual(end - start, 7 * DAY + 3600)           # contains the fall-back Sunday
        month = model.latest_completed(at(zone, 2026, 11, 4, 9, 0), "monthly", zone)
        self.assertEqual(month, (at(zone, 2026, 10, 1), at(zone, 2026, 11, 1)))
        self.assertEqual(model.period_for("2026-10-05", "weekly", "UTC"), (at("UTC", 2026, 10, 5), at("UTC", 2026, 10, 12)))
        self.assertIsNone(model.period_for("2026-10-06", "weekly", "UTC"))     # not a Monday
        self.assertIsNone(model.period_for("2026-10-02", "monthly", "UTC"))
        self.assertIsNone(model.period_for("not a date", "weekly", "UTC"))

    def test_proof_id_is_the_growth_loop_id_for_utc(self):
        start, _end = model.latest_completed(NOW, "weekly", "UTC")
        legacy_start, _ = growth_loop.period(NOW, "weekly")
        self.assertEqual(start, legacy_start)
        self.assertEqual(model.proof_id("w1", "weekly", start), "gp_" + hashlib.sha256(f"w1:weekly:{int(legacy_start)}".encode()).hexdigest()[:20])

    def test_ac34_immature_period_is_partial_and_figures_unavailable_are_not_zero(self):
        start, end = model.latest_completed(NOW, "weekly", "UTC")
        self.assertFalse(model.maturity(end, NOW)["mature"])
        self.assertTrue(model.maturity(end, end + model.MATURITY_SECONDS)["mature"])
        figures = counts()["figures"]
        self.assertEqual(model.overall_state(figures, mature=False), "partial")
        self.assertEqual(model.overall_state(figures, mature=True), "available")
        figures["outcomes"] = model.unavailable("d", "results_unavailable")
        self.assertIsNone(figures["outcomes"]["value"])
        self.assertEqual(model.overall_state(figures, mature=True), "partial")


class FigureTest(unittest.TestCase):
    def test_unresolved_slots_count_open_slots_in_the_period_with_evidence(self):
        state = {"coworker": {"weekly": {"recipes": [{"id": "r"}], "weeks": [{"id": "wk1", "slots": [
            {"id": "s1", "status": "needs_source", "localTime": "2026-09-29T09:00", "timeZone": "Asia/Hong_Kong"},
            {"id": "s2", "status": "accepted", "localTime": "2026-09-30T09:00", "timeZone": "Asia/Hong_Kong"},
            {"id": "s3", "status": "ready", "localTime": "2026-10-01T09:00", "timeZone": "Asia/Hong_Kong"},
            {"id": "s4", "status": "rejected", "localTime": "2026-10-01T10:00", "timeZone": "Asia/Hong_Kong"},
            {"id": "s5", "status": "planned", "localTime": "2026-10-09T09:00", "timeZone": "Asia/Hong_Kong"}]}]}}}
        start, end = model.period_bounds(datetime(2026, 9, 30).date(), "weekly", "Asia/Hong_Kong")
        result = model.unresolved_slots(state, start, end)
        self.assertEqual(result["value"], 2)
        self.assertEqual(result["evidence"], {"slotIds": ["s1", "s3"], "weekIds": ["wk1"]})
        self.assertEqual(result["byReason"], {"needs_source": 1, "ready": 1})
        self.assertEqual(model.unresolved_slots({}, start, end)["reason"], "weekly_not_set_up")

    def test_ac26_digest_ignores_as_of_and_watermarks_but_not_values_or_evidence(self):
        first = counts()
        later = copy.deepcopy(first)
        later["asOf"] += 3600
        later["sourceWatermark"] = {"queue": NOW + 5}
        later["figures"]["acceptedWork"]["definition"] = "reworded"
        self.assertEqual(model.digest(first), model.digest(later))
        late = copy.deepcopy(first)
        late["figures"]["verifiedPublications"] = model.figure(2, definition="d", evidence={"jobIds": ["j1", "j2"]})
        self.assertNotEqual(model.digest(first), model.digest(late))
        note = model.corrections(first, late)
        self.assertEqual(note, [{"figure": "verifiedPublications", "before": 1, "after": 2}])
        swapped = copy.deepcopy(first)
        swapped["figures"]["acceptedWork"]["evidence"] = {"ids": ["b"]}
        self.assertEqual(model.corrections(first, swapped), [{"figure": "acceptedWork", "before": 1, "after": 1, "evidenceOnly": True}])
        redefined = copy.deepcopy(first)
        redefined["definitionVersion"] = "rafii.proof.v3"
        self.assertNotEqual(model.digest(first), model.digest(redefined))

    def test_evidence_is_sorted_unique_and_bounded(self):
        figure = model.figure(3, definition="d", evidence={"jobIds": ["b", "a", "a", None]})
        self.assertEqual(figure["evidence"], {"jobIds": ["a", "b"]})
        big = model.figure(500, definition="d", evidence={"ids": [str(i) for i in range(500)]})
        self.assertEqual(len(big["evidence"]["ids"]), model.EVIDENCE_LIMIT)
        self.assertTrue(big["evidenceTruncated"])

    def test_jsonable_drops_unsafe_values(self):
        from decimal import Decimal
        self.assertEqual(model.jsonable({"a": Decimal("2"), "b": Decimal("1.5"), "c": float("nan"), "d": object(), "e": [1, "x"]}),
                         {"a": 2, "b": 1.5, "c": None, "d": None, "e": [1, "x"]})


def experiment(**extra):
    base = {"id": "ge_1", "status": "complete", "decision": None, "hypothesisRevision": 2, "dimension": "opening", "expiresAt": NOW + 30 * DAY, "updatedAt": NOW,
            "cohort": {"provider": "threads", "connectionId": "ch1", "language": "en", "contentTypeId": "tutorial_how_to"},
            "result": {"supportedFactor": "question"}}
    base.update(extra)
    return base


def workspace():
    return {"phase2": {"channels": [{"id": "ch1", "platform": "Threads", "account": "@one"}, {"id": "ch2", "platform": "LinkedIn", "account": "Page"}]},
            "coworker": {"growthLoop": {"goals": [{"id": "g1", "name": "Teach more adults", "status": "active"}], "experiments": [experiment()], "proofs": []}},
            "sources": [{"id": "src1", "active": True, "kind": "idea", "title": "Practice streaks"}],
            "speaker": {"activeRevision": "voice-3"}, "learning": {"revision": 4}, "brandHub": {"subject": "Piano lessons"}}


class StrategyTest(unittest.TestCase):
    def test_proposals_are_deterministic_and_skip_decided_or_unsupported(self):
        state = workspace()
        actions = [{"id": "act1", "action": "save_idea", "itemId": "bi_x", "outcomeRefs": [{"type": "source", "id": "src1"}], "channelId": None},
                   {"id": "act2", "action": "dismiss", "outcomeRefs": []},
                   {"id": "act3", "action": "save_idea", "outcomeRefs": [{"type": "source", "id": "gone"}]}]
        first = strategy.proposals(state, "w1", actions, NOW)
        self.assertEqual([p["kind"] for p in first], ["experiment_preference", "brief_topic"])
        self.assertEqual(first, strategy.proposals(copy.deepcopy(state), "w1", actions, NOW))
        self.assertEqual(first[0]["scope"], {"goalId": "g1", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to"})
        self.assertIn("not a proven cause", first[0]["statement"])
        self.assertEqual(first[1]["basis"], {"briefActionId": "act1", "sourceId": "src1", "itemId": "bi_x"})
        state["coworker"]["growthLoop"]["experiments"] = [experiment(decision="applied"), experiment(id="ge_2", result={"supportedFactor": None}),
                                                          experiment(id="ge_3", expiresAt=NOW - 1)]
        self.assertEqual([p["kind"] for p in strategy.proposals(state, "w1", actions, NOW)], ["brief_topic"])

    def test_ac27_versioned_state_machine(self):
        self.assertEqual(strategy.transition("proposed", "accept"), "accepted")
        self.assertEqual(strategy.transition("proposed", "edit"), "edited")
        self.assertEqual(strategy.transition("proposed", "reject"), "rejected")
        self.assertEqual(strategy.transition("accepted", "revoke"), "revoked")
        self.assertEqual(strategy.transition("edited", "edit"), "edited")
        for status, action in (("rejected", "accept"), ("revoked", "accept"), ("accepted", "reject"), ("revoked", "revoke"), ("proposed", "revoke")):
            with self.assertRaises(AlphaError) as caught:
                strategy.transition(status, action)
            self.assertEqual(caught.exception.code, "invalid_transition")

    def test_edits_only_narrow_scope(self):
        state = workspace()
        scope = {"goalId": "g1", "channelId": None, "language": None, "contentType": None}
        self.assertEqual(strategy.narrow(scope, {"channelId": "ch2", "language": "zh-Hant"}, state)["channelId"], "ch2")
        with self.assertRaises(AlphaError) as caught:
            strategy.narrow({**scope, "channelId": "ch1"}, {"channelId": "ch2"}, state)
        self.assertEqual(caught.exception.code, "scope_widened")
        for edits in ({"channelId": "foreign"}, {"goalId": "nope"}, {"language": "not a tag"}, {"contentType": "Bad Type"}, {"voice": "x"}):
            with self.assertRaises(AlphaError):
                strategy.narrow(scope, edits, state)
        with self.assertRaises(AlphaError):
            strategy.clean_statement("  ")

    def test_next_week_start_is_the_following_local_monday(self):
        start, iso = strategy.next_week_start(at("Asia/Hong_Kong", 2026, 10, 4, 23, 0), "Asia/Hong_Kong")   # a Sunday night
        self.assertEqual(iso, "2026-10-05")
        self.assertEqual(start, at("Asia/Hong_Kong", 2026, 10, 5))

    def test_adoption_starts_at_the_first_week_not_planned_yet(self):
        """A stored week is never planned again, so a decision adopted after next week was planned starts the week
        after (and says which weeks it skips) instead of claiming a week it can't reach."""
        now = at("Asia/Hong_Kong", 2026, 10, 10, 18, 0)   # Saturday: the 12 October plan may already exist
        state = workspace()
        start, first, skipped = strategy.first_unplanned_week(state, now, "Asia/Hong_Kong")
        self.assertEqual((first, skipped), ("2026-10-12", []))
        self.assertEqual(start, at("Asia/Hong_Kong", 2026, 10, 12))
        state["coworker"]["weekly"] = {"weeks": [{"id": "wk_a", "weekOf": "2026-10-12"}, {"id": "wk_b", "weekOf": "2026-10-19"},
                                                 {"id": "wk_old", "weekOf": "2026-10-05"}, {"id": "wk_later", "weekOf": "2026-11-02"}]}
        start, first, skipped = strategy.first_unplanned_week(state, now, "Asia/Hong_Kong")
        self.assertEqual((first, skipped), ("2026-10-26", ["2026-10-12", "2026-10-19"]))
        self.assertEqual(start, at("Asia/Hong_Kong", 2026, 10, 26))
        # The first unplanned week then applies it; the skipped planned weeks were never going to.
        exp = strategy.proposals(state, "w1", [], now)[0]
        strategy.project(state, {**exp, "revision": 2, "status": "accepted", "appliesFrom": start, "appliesFromDate": first, "decidedAt": now})
        slots = [{"id": "s1", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to", "localTime": "2026-10-27T09:00", "status": "planned"}]
        self.assertEqual(strategy.apply_to_week(state, slots, "2026-10-26")["appliedDecisions"][0]["id"], exp["id"])

    def test_the_planning_note_states_the_weeks_truthfully(self):
        from postriff_phase2.proof.service import planning_note
        note = planning_note("accepted", "2026-10-19", ["2026-10-12"])
        self.assertIn("from the week of 2026-10-19 on", note)
        self.assertIn("The week of 2026-10-12 was already planned, so it does not use this decision.", note)
        many = planning_note("edited", "2026-10-26", ["2026-10-12", "2026-10-19"])
        self.assertIn("The weeks of 2026-10-12 and 2026-10-19 were already planned, so they do not use this decision.", many)
        self.assertNotIn("already planned", planning_note("accepted", "2026-10-12", []))
        self.assertIn("stop using it now", planning_note("revoked", None))
        self.assertIn("not proposed again", planning_note("rejected", None))

    def test_a_slot_gets_a_decision_only_while_its_current_version_still_fits(self):
        """for_slot re-checks the latest version: an edit that narrowed the scope away from the slot, a disconnected
        account, a goal that is no longer active or a withdrawn source keeps the decision out of the writer brief."""
        state = workspace()
        exp, topic = strategy.proposals(state, "w1", [{"id": "act1", "action": "save_idea", "outcomeRefs": [{"type": "source", "id": "src1"}]}], NOW)
        exp = {**exp, "scope": {**exp["scope"], "contentType": None, "language": None}}   # planned while format and language were open
        self._accept(state, exp)
        self._accept(state, topic)
        slot = {"id": "s1", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to",
                "strategyDecisions": [{"id": exp["id"], "revision": 2}, {"id": topic["id"], "revision": 2}]}
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {exp["id"], topic["id"]})
        self._accept(state, {**exp, "scope": {**exp["scope"], "contentType": "deep_point_of_view"}}, revision=3, status="edited")   # narrowed after planning
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {topic["id"]})
        self._accept(state, {**exp, "scope": {**exp["scope"], "language": "zh-Hant"}}, revision=4, status="edited")
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {topic["id"]})
        self._accept(state, exp, revision=5, status="edited")
        state["phase2"]["channels"][0]["revoked"] = True                                   # the account it is scoped to was disconnected
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {topic["id"]})   # the topic names no account
        state["phase2"]["channels"][0]["revoked"] = False
        state["coworker"]["growthLoop"]["goals"][0]["status"] = "paused"                    # its goal is no longer active
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, set())
        state["coworker"]["growthLoop"]["goals"][0]["status"] = "active"
        state["sources"][0]["active"] = False                                             # the saved idea was withdrawn
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {exp["id"]})
        state["sources"][0]["active"] = True
        self.assertEqual({d["decisionId"] for d in strategy.for_slot(state, slot)}, {exp["id"], topic["id"]})

    def _accept(self, state, proposal, revision=2, status="accepted", applies="2026-10-12"):
        strategy.project(state, {**proposal, "revision": revision, "status": status, "appliesFrom": None, "appliesFromDate": applies, "decidedAt": NOW})

    def test_ac27_applied_with_slots_or_not_applied_with_a_reason(self):
        state = workspace()
        exp, topic = strategy.proposals(state, "w1", [{"id": "act1", "action": "save_idea", "outcomeRefs": [{"type": "source", "id": "src1"}]}], NOW)
        self._accept(state, exp)
        self._accept(state, topic)
        slots = [{"id": "s1", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to", "localTime": "2026-10-12T09:00", "status": "planned"},
                 {"id": "s2", "channelId": "ch1", "language": "en-GB", "contentType": "tutorial_how_to", "localTime": "2026-10-14T09:00", "status": "needs_source"},
                 {"id": "s3", "channelId": "ch2", "language": "en", "contentType": "deep_point_of_view", "localTime": "2026-10-13T09:00", "status": "planned"},
                 {"id": "s4", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to", "localTime": "2026-10-11T09:00", "status": "channel_unavailable"}]
        result = strategy.apply_to_week(state, slots, "2026-10-12")
        applied = {a["id"]: a for a in result["appliedDecisions"]}
        self.assertEqual(applied[exp["id"]]["slotIds"], ["s1", "s2"])        # every matching slot, never a blocked channel
        self.assertEqual(applied[topic["id"]]["slotIds"], ["s1"])            # one post, the earliest matching slot
        self.assertEqual(result["notApplied"], [])
        self.assertEqual(result["slotDecisions"]["s1"], [{"id": exp["id"], "revision": 2}, {"id": topic["id"], "revision": 2}])
        early = strategy.apply_to_week(state, slots, "2026-10-05")
        self.assertEqual({n["reason"] for n in early["notApplied"]}, {"applies_from_later"})
        state["sources"][0]["active"] = False
        state["coworker"]["growthLoop"]["goals"][0]["status"] = "paused"
        reasons = {n["id"]: n["reason"] for n in strategy.apply_to_week(state, slots, "2026-10-12")["notApplied"]}
        self.assertEqual(reasons, {exp["id"]: "goal_not_active", topic["id"]: "source_unavailable"})
        state["coworker"]["growthLoop"]["goals"][0]["status"] = "active"
        self.assertEqual(strategy.apply_to_week(state, slots[2:3], "2026-10-12")["notApplied"][0]["reason"], "no_matching_slot")
        # A brief topic is one post: once a stored week applied it, later weeks record why it is not applied again.
        state["sources"][0]["active"] = True
        state["coworker"]["weekly"] = {"weeks": [{"weekOf": "2026-10-12", "appliedDecisions": [{"id": topic["id"], "revision": 2}]}]}
        later = strategy.apply_to_week(state, slots, "2026-10-19")
        self.assertEqual({n["id"]: n["reason"] for n in later["notApplied"]}, {topic["id"]: "already_applied"})
        self.assertEqual([a["id"] for a in later["appliedDecisions"]], [exp["id"]])
        self.assertEqual([a["id"] for a in strategy.apply_to_week(state, slots, "2026-10-12")["appliedDecisions"]], [exp["id"], topic["id"]])   # re-planning that same week

    def test_ac27_revocation_stops_future_use_and_projection_is_bounded(self):
        state = workspace()
        [exp] = strategy.proposals(state, "w1", [], NOW)
        self._accept(state, exp)
        slot = {"id": "s1", "channelId": "ch1", "language": "en", "contentType": "tutorial_how_to", "strategyDecisions": [{"id": exp["id"], "revision": 2}]}
        self.assertEqual(strategy.for_slot(state, slot)[0]["decisionId"], exp["id"])
        self.assertEqual(strategy.for_slot(state, slot, {"ge_1"}), [])       # already an approved experiment preference
        self._accept(state, {**exp, "statement": "Edited wording"}, revision=3, status="edited")
        self.assertEqual(strategy.for_slot(state, slot)[0]["statement"], "Edited wording")
        self._accept(state, exp, revision=4, status="revoked")
        self.assertEqual(strategy.active(state), [])
        self.assertEqual(strategy.for_slot(state, slot), [])
        for n in range(strategy.MAX_ACTIVE):
            self._accept(state, {**exp, "id": f"sd_{n:020d}"})
        with self.assertRaises(AlphaError) as caught:
            self._accept(state, {**exp, "id": "sd_" + "f" * 20})
        self.assertEqual(caught.exception.code, "too_many_active_decisions")


class ReviewFixesTest(unittest.TestCase):
    def test_proposals_are_not_capped_before_known_ids_are_skipped(self):
        state = workspace()
        state["coworker"]["growthLoop"]["experiments"] = [experiment(id=f"ge_{n}", updatedAt=NOW - n) for n in range(4)]
        actions = [{"id": f"act{n}", "action": "save_idea", "outcomeRefs": [{"type": "source", "id": "src1"}]} for n in range(2)]
        candidates = strategy.proposals(state, "w1", actions, NOW)
        self.assertEqual(len(candidates), 6)                                  # the service applies the cap after skipping decided ids
        self.assertEqual(len({p["id"] for p in candidates}), 6)

    def test_oversized_counts_keep_exact_totals_and_short_flagged_evidence(self):
        many = [f"{n:036d}" for n in range(model.EVIDENCE_LIMIT)]
        figures = {name: model.figure(len(many), definition="d", evidence={"a": many, "b": many, "c": many}) for name in model.FIGURES}
        counts = {"definitionVersion": model.DEFINITION_VERSION, "frequency": "weekly", "figures": figures, "padding": "x" * model.MAX_COUNTS_BYTES}
        bounded = model.bounded(counts)
        self.assertTrue(all(len(ids) == 10 for f in bounded["figures"].values() for ids in f["evidence"].values()))
        self.assertTrue(all(f["evidenceTruncated"] and f["value"] == model.EVIDENCE_LIMIT for f in bounded["figures"].values()))
        small = {"definitionVersion": "v", "frequency": "weekly", "figures": {"acceptedWork": model.figure(1, definition="d", evidence={"a": ["x"]})}}
        self.assertEqual(model.bounded(copy.deepcopy(small)), small)          # under the bound nothing changes

    def test_corrections_record_large_values_as_changed(self):
        big = {"provider_native": None, "user_declared": {"counts": {f"type_{n}": n for n in range(60)}}}
        before = counts(outcomes=model.figure(None, definition="d", data_state="unavailable"))
        after = counts(outcomes=model.figure(big, definition="d", evidence={"resultIds": ["r1"]}))
        [entry] = [e for e in model.corrections(before, after) if e["figure"] == "outcomes"]
        self.assertEqual(entry["after"], {"changed": True})
        self.assertIsNone(entry["before"])

    def test_proof_service_exposes_enabled_with_the_flag_semantics(self):
        from postriff_phase2.proof import service as proof_service
        self.assertTrue(proof_service.enabled({"RAFII_PROOF_V2_ENABLED": "on"}))
        self.assertFalse(proof_service.enabled({"RAFII_PROOF_V2_ENABLED": "off"}))
        with mock.patch.object(flags, "_values", {"RAFII_PROOF_V2_ENABLED": "1"}):
            self.assertTrue(proof_service.enabled())
        with mock.patch.object(flags, "_values", {}):
            self.assertFalse(proof_service.enabled())

    def test_non_owners_never_see_cost_in_corrections_or_watermarks(self):
        from postriff_phase2.proof.service import ProofService
        correction = [{"figure": "providerCost", "before": {"actualUsdMicro": 1}, "after": {"actualUsdMicro": 9}},
                      {"figure": "verifiedPublications", "before": 1, "after": 2}]
        watermark = {"queue": 1.0, "usage": 2.0}
        hidden, mark = ProofService._redact_meta(correction, watermark, owner=False)
        self.assertEqual(hidden, [{"figure": "providerCost", "restricted": True}, correction[1]])
        self.assertEqual(mark, {"queue": 1.0})
        self.assertEqual(ProofService._redact_meta(correction, watermark, owner=True), (correction, watermark))
        redacted = ProofService._redact({"figures": {"providerCost": {"value": {"actualUsdMicro": 9}}}, "sourceWatermark": {"usage": 2.0, "queue": 1.0}}, False)
        self.assertEqual(redacted["figures"]["providerCost"]["dataState"], "restricted")
        self.assertEqual(redacted["sourceWatermark"], {"queue": 1.0})


class PlanningIntegrationTest(unittest.TestCase):
    """planning_context and plan_week consume decisions only with RAFII_PROOF_V2_ENABLED; identity and voice never change."""

    def recipe_state(self):
        state = workspace()
        state["phase2"]["channels"][0]["platform"] = "Threads"
        recipe = weekly_operator.save_recipe(state, {"goals": ["Teach more adults"], "timeZone": "Asia/Hong_Kong",
                                                     "contentMix": {"tutorial_how_to": 1.0}, "destinations": [{"channelId": "ch1", "postsPerWeek": 2, "language": "en"}]},
                                             "owner", NOW)
        [exp] = strategy.proposals(state, "w1", [], NOW)
        strategy.project(state, {**exp, "revision": 2, "status": "accepted", "appliesFrom": None, "appliesFromDate": "2026-10-12", "decidedAt": NOW})
        return state, recipe, exp

    def test_flag_off_keeps_the_existing_plan_shape(self):
        state, recipe, _exp = self.recipe_state()
        with mock.patch.object(flags, "_values", {}):
            week = weekly_operator.plan_week(state, recipe, NOW)
            context = growth_loop.planning_context(state, week["slots"][0], NOW)
        self.assertNotIn("appliedDecisions", week)
        self.assertTrue(all("strategyDecisions" not in s for s in week["slots"]))
        self.assertNotIn("strategyDecisions", context)

    def test_ac27_flag_on_records_applied_decisions_and_feeds_the_writer_without_identity_changes(self):
        state, recipe, exp = self.recipe_state()
        identity = copy.deepcopy({k: state.get(k) for k in ("speaker", "learning", "brandHub")})
        with mock.patch.object(flags, "_values", {"RAFII_PROOF_V2_ENABLED": "1"}):
            week = weekly_operator.plan_week(state, recipe, NOW)
            self.assertEqual(week["weekOf"], "2026-10-12")
            self.assertEqual(week["appliedDecisions"][0]["id"], exp["id"])
            self.assertEqual(week["notApplied"], [])
            slot = next(s for s in week["slots"] if s.get("strategyDecisions"))
            brief = weekly_operator.slot_brief(recipe, slot, state)
            self.assertIn(exp["id"], brief)
            context = growth_loop.planning_context(state, slot, NOW)
            self.assertEqual(context["strategyDecisions"][0]["revision"], 2)
            self.assertIn("Queue approval remain required", context["constraints"])
            strategy.project(state, {**exp, "revision": 3, "status": "revoked"})
            self.assertEqual(growth_loop.planning_context(state, slot, NOW)["strategyDecisions"], [])
            early = weekly_operator.plan_week(state, recipe, NOW - 7 * DAY)
            self.assertEqual(early["appliedDecisions"], [])
        self.assertEqual({k: state.get(k) for k in ("speaker", "learning", "brandHub")}, identity)


if __name__ == "__main__":
    unittest.main()
