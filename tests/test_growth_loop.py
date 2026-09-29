import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.coworker import growth_loop as loop
from postriff_phase2.notifications import detector, catalog

NOW = 1_800_000_000
COHORT = {"provider": "threads", "connectionId": "channel-one", "language": "en", "contentTypeId": "text", "definitionVersion": "2026-09"}


def payload(**extra):
    return {"name": "Publish consistently", "goalType": "consistency", "primaryMetric": "verified_posts", "baselineValue": 0,
            "targetValue": 12, "targetAt": "2030-01-01", "idempotencyKey": "goal-request-one", **extra}


def experiment():
    return {"id": "e1", "status": "running", "history": [], "cohort": COHORT, "metric": "views", "dimension": "opening",
            "variantFactor": "question", "controlFactor": "statement", "minimumPerArm": 5, "startedAt": NOW - 20 * 86400,
            "endAt": NOW - 86400, "sourcePostIds": ["source"], "expiresAt": NOW + 86400, "decision": None}


def rows(a=5, b=5):
    return [{"jobId": f"{arm}-{n}", "cohort": copy.deepcopy(COHORT), "metric": "views", "value": value,
             "features": {"opening": arm}, "publishedAt": NOW - 10 * 86400, "observedAt": NOW - 9 * 86400}
            for arm, count, value in [("question", a, 200), ("statement", b, 100)] for n in range(count)]


class GrowthLoopTests(unittest.TestCase):
    def test_primary_goal_idempotency_and_conflict(self):
        state = {}
        first = loop.create_goal(state, "one", payload(), "owner", NOW)
        self.assertEqual(first, loop.create_goal(state, "one", payload(), "owner", NOW))
        self.assertEqual(len(loop.view(state)["goals"]), 1)
        with self.assertRaises(AlphaError): loop.create_goal(state, "one", payload(name="Other"), "owner", NOW)
        with self.assertRaises(AlphaError): loop.create_goal(state, "one", payload(idempotencyKey="second-request"), "owner", NOW)

    def test_invalid_numeric_and_foreign_channel(self):
        for value in [True, float("nan"), float("inf"), -1, "12"]:
            with self.assertRaises(AlphaError): loop.create_goal({}, "one", payload(targetValue=value), "owner", NOW)
        with self.assertRaises(AlphaError): loop.create_goal({}, "one", payload(channelId="foreign"), "owner", NOW)

    def test_unavailable_metric_is_null(self):
        state = {"phase2": {"channels": [{"id": "channel-one", "platform": "Threads"}]}}
        goal = loop.create_goal(state, "one", payload(goalType="follower_growth", primaryMetric="followers", channelId="channel-one"), "owner", NOW)
        result = loop.goal_progress(goal, [], state, NOW)
        self.assertIsNone(result["currentValue"])
        self.assertIsNone(result["currentValueAt"])
        self.assertEqual(result["coverage"]["status"], "unavailable")

    def test_verified_receipts_exclude_failed_and_unverified(self):
        state = {}
        goal = loop.create_goal(state, "one", payload(), "owner", NOW)
        state["phase2"] = {"jobs": [{"id": "one", "state": "verified", "providerReference": "p1", "verification": {"at": NOW + 1}},
                                     {"id": "two", "state": "failed", "providerReference": "p2", "verification": {"at": NOW + 1}},
                                     {"id": "three", "state": "submitted", "providerReference": "p3", "verification": {"at": NOW + 1}}]}
        self.assertEqual(loop.goal_progress(goal, [], state, NOW + 2)["currentValue"], 1)

    def test_minimum_sample_and_no_early_result(self):
        self.assertEqual(loop.measure(experiment(), rows(4, 5), NOW)[0], "insufficient_data")
        with self.assertRaises(AlphaError): loop.measure(experiment(), rows(), NOW - 2 * 86400)

    def test_robust_medians_counter_evidence_and_no_causal_claim(self):
        data = rows()
        data[0]["value"] = 50
        data[1]["value"] = 100_000
        state, result = loop.measure(experiment(), data, NOW)
        self.assertEqual(state, "complete")
        self.assertEqual(result["medianVariant"], 200)
        self.assertEqual(result["counterEvidenceIds"], ["question-0"])
        self.assertFalse(result["causal"])

    def test_account_language_window_and_source_controls(self):
        data = rows()
        for row in data:
            row["cohort"].update({"account": "channel-one", "window": "24h"})
        foreign = copy.deepcopy(data[0]); foreign["jobId"] = "foreign"; foreign["cohort"]["connectionId"] = "other"
        misbound = copy.deepcopy(data[0]); misbound["jobId"] = "misbound"; misbound["cohort"]["account"] = "other"
        wrong_window = copy.deepcopy(data[0]); wrong_window["jobId"] = "wrong-window"; wrong_window["cohort"]["window"] = "7d"
        old = copy.deepcopy(data[0]); old["jobId"] = "old"; old["publishedAt"] = NOW - 50 * 86400
        source = copy.deepcopy(data[0]); source["jobId"] = "source"
        state, result = loop.measure(experiment(), data + [foreign, misbound, wrong_window, old, source, data[0]], NOW)
        self.assertEqual(result["samples"], {"variant": 5, "control": 5})
        self.assertEqual(len(result["observations"]), 10)

    def test_missing_or_equal_data_has_no_supported_factor(self):
        data = rows(); data.append({**data[0], "jobId": "missing", "value": None})
        self.assertIsNone(loop.measure(experiment(), data, NOW)[1]["supportedFactor"])
        for r in data: r["value"] = 100
        self.assertIsNone(loop.measure(experiment(), data, NOW)[1]["supportedFactor"])

    def test_hypotheses_keep_each_accounts_native_metric(self):
        data = rows()
        instagram = [{**r, 'jobId': 'ig-' + r['jobId'], 'metric': 'reach',
                      'cohort': {**r['cohort'], 'provider': 'instagram', 'connectionId': 'instagram-one'}} for r in data]
        hypotheses = loop.performance.hypotheses_from(data + instagram, NOW)
        self.assertEqual({(h['cohort']['provider'], h['metric']) for h in hypotheses}, {('threads', 'views'), ('instagram', 'reach')})

    def test_next_week_prepared_excludes_rejected_and_later_weeks(self):
        from datetime import datetime, timezone
        start, end = loop.period(NOW, 'weekly')
        current_week = datetime.fromtimestamp(end, timezone.utc).date().isoformat()
        later_week = datetime.fromtimestamp(end + loop.WEEK, timezone.utc).date().isoformat()
        state = {'coworker': {'weekly': {'recipes': [], 'weeks': [
            {'weekOf': current_week, 'slots': [{'variantId': 'accepted', 'acceptedAt': end+1}, {'variantId': 'rejected', 'acceptedAt': end+1, 'status': 'rejected'}]},
            {'weekOf': later_week, 'slots': [{'variantId': 'later', 'acceptedAt': end+1}]}
        ]}}}
        self.assertEqual(loop.proof_counts(state, start, end)['nextWeekPrepared'], 1)

    def test_strategy_requires_explicit_decision_and_is_scoped_reversible(self):
        e = experiment(); e.update({"status": "complete", "result": {"supportedFactor": "question"}})
        state = {"coworker": {"growthLoop": {"goals": [], "proofs": [], "experiments": [e]}}}
        slot = {"channelId": "channel-one", "platform": "Threads", "language": "en", "contentType": "text"}
        self.assertEqual(loop.planning_context(state, slot, NOW)["approvedStrategyPreferences"], [])
        e["decision"] = "applied"
        self.assertEqual(len(loop.planning_context(state, slot, NOW)["approvedStrategyPreferences"]), 1)
        self.assertEqual(loop.planning_context(state, {**slot, "channelId": "other"}, NOW)["approvedStrategyPreferences"], [])
        e["decision"] = "revoked"
        self.assertEqual(loop.planning_context(state, slot, NOW)["approvedStrategyPreferences"], [])

    def test_proof_excludes_unused_drafts_and_has_safe_notifications(self):
        start, end = loop.period(NOW, "weekly")
        state = {"variants": [{"id": "unused"}], "phase2": {"jobs": [{"id": "yes", "state": "verified", "providerReference": "real", "verification": {"at": start + 1}},
                {"id": "failed", "state": "failed", "providerReference": "bad", "verification": {"at": start + 1}}]}}
        counts = loop.proof_counts(state, start, end)
        self.assertEqual((counts["verifiedPublishedPosts"], counts["preparedPosts"]), (1, 0))
        loop.root(state)["proofs"].append({"id": "gp_one", "frequency": "weekly", "href": "/app/analytics?proof=gp_one", "counts": counts})
        event = next(e for e in detector.from_state("one", state, NOW) if e["event_type"] == "weekly_proof.generated")
        self.assertNotIn("unused", json_text(event))
        self.assertEqual(catalog.EVENTS[event["event_type"]]["email"], "digest")


def json_text(value):
    import json
    return json.dumps(value)


if __name__ == "__main__": unittest.main()
