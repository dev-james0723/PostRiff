"""Bounded SYNTHETIC acceptance; no DB, provider, OAuth, publishing or model calls.

Reuse native observation tuples, Growth's five-post-per-arm threshold and its
existing closed-loop fixture. Native provider names describe shapes, not grants.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from postriff_phase2 import insights
from postriff_phase2.coworker import performance as hypotheses
from postriff_phase2.growth import metric_schedule, performance, postmortem
from postriff_phase2.growth.trends import beta
from postriff_phase2.providers import InstagramProvider
from test_growth_closed_loop import observations as closed_loop_fixture


SYNTHETIC = "SYNTHETIC — no real account, post, grant or measurement"
NOW = 1_800_000_000
WORKSPACE = "synthetic-workspace"
ACCOUNT = "synthetic-instagram-account"


def native_fixture(count=10, missing=False, unrelated_time=False):
    """SYNTHETIC SQL-shaped per-metric +24h observations, same owned cohort."""
    jobs, rows = [], []
    for i in range(count):
        jid, pid = f"synthetic-job-{i}", f"synthetic-native-{i}"
        observed = NOW - (count - i) * 86400
        published = observed - 86400
        jobs.append({"id": jid, "state": "verified", "providerReference": pid,
                     "verification": {"at": published}, "approvedAt": published,
                     "manifest": {"platform": "Instagram", "channelId": ACCOUNT,
                                  "contentType": {"id": "text", "formatId": "text"},
                                  "payload": {"language": "en", "text":
                                      "Synthetic question?" if i < count // 2 else "Synthetic statement."}}})
        # SQL orders metrics alphabetically. Comments are not the primary reach
        # metric; an independently updated reading may have a different time.
        if unrelated_time:
            rows.append(("instagram", pid, jid, "comments", insights.DEFINITION_VERSION,
                         1, "count", "available", NOW - 60, NOW, ACCOUNT, "24h"))
        rows.append(("instagram", pid, jid, "reach", insights.DEFINITION_VERSION,
                     None if missing else (200 if i < count // 2 else 100),
                     "count", "unavailable" if missing else "available",
                     observed, observed + 1, ACCOUNT, "24h"))
    return {"execution": "synthetic", "label": SYNTHETIC,
            "state": {"phase2": {"jobs": jobs, "channels": [
                {"id": ACCOUNT, "platform": "Instagram"}]}}, "rows": rows}


def outputs(fixture):
    with patch.object(insights, "latest_observations", return_value=fixture["rows"]):
        summary = insights.summary(None, WORKSPACE, fixture["state"]["phase2"]["jobs"], NOW, basis="24h")
        rows = hypotheses.observations(None, WORKSPACE, fixture["state"], NOW)
    return summary, rows, hypotheses.hypotheses_from(rows, NOW)


def postmortem_fixture(count=12, missing=False):
    """SYNTHETIC reuse of the repository's frozen-score/observed-outcome fixture."""
    posts, predictions = closed_loop_fixture(count)
    renamed = {}
    for i, post in enumerate(posts):
        old = post["id"]
        post["id"] = f"synthetic-closed-loop-{i}"
        post["connectionId"] = "synthetic-threads-account"
        post["synthetic"] = True
        reading = post["readings"]["24h"]["shares"]
        reading.update(observedAt=NOW - (count - i) * 86400,
                       availability="unavailable" if missing else "available",
                       value=None if missing else reading["value"])
        renamed[post["id"]] = predictions[old]
    job = {"id": posts[-1]["id"], "manifest": {"payload": {"text": SYNTHETIC}}}
    return posts, renamed, postmortem.build(job, renamed[job["id"]], posts, renamed, "24h")


class SyntheticAnalyticsAcceptance(unittest.TestCase):
    def test_sufficient_native_data_is_observation_with_traceable_qualified_hypotheses(self):
        fixture = native_fixture()
        summary, rows, recommendations = outputs(fixture)
        self.assertEqual(insights.compare(summary["posts"], "reach")["interpretation"], "observation_only")
        self.assertTrue(recommendations, "Positive control must emit a recommendation")
        index = {row["jobId"]: row for row in rows}
        for recommendation in recommendations:
            self.assertTrue(recommendation["evidence_ids"])
            self.assertTrue(set(recommendation["evidence_ids"]) <= index.keys())
            self.assertEqual(recommendation["cohort"]["provider"], "instagram")
            self.assertEqual(recommendation["cohort"]["account"], ACCOUNT)
            self.assertEqual(recommendation["cohort"]["window"], "24h")
            self.assertEqual(recommendation["metric"], "reach")
            self.assertEqual(recommendation["date_from"], min(row[8] for row in fixture["rows"]))
            self.assertEqual(recommendation["date_to"], max(row[8] for row in fixture["rows"]))
            self.assertIn("may", recommendation["statement"])
            self.assertIn("not proven to cause", recommendation["statement"])

    def test_insufficient_history_and_unavailable_data_withhold_outcome_recommendations(self):
        for count, missing, expected in ((0, False, "no_data"), (2, False, "insufficient_sample"),
                                         (10, True, "insufficient_sample")):
            with self.subTest(count=count, missing=missing):
                summary, _, recommendations = outputs(native_fixture(count, missing))
                self.assertEqual(insights.compare(summary["posts"], "reach")["interpretation"], expected)
                self.assertEqual(recommendations, [])
                if missing:
                    self.assertTrue(all(p["metrics"]["reach"]["value"] is None for p in summary["posts"]))
        for count, missing in ((2, False), (12, True)):
            _, _, report = postmortem_fixture(count, missing)
            self.assertEqual(report["lessons"], [])
            if missing:
                self.assertEqual(report["reading"]["status"], "unavailable")

    def test_missing_analytics_authorization_identified_before_transport(self):
        provider = InstagramProvider("synthetic-client", "synthetic-secret", production_reviewed=True)
        oauth = SimpleNamespace(providers={"instagram": provider},
            token_for_worker=lambda *_: {"accessToken": "synthetic-token", "provider": "instagram",
                                         "scopes": ["instagram_business_basic"]})
        transport = Mock(side_effect=AssertionError("Synthetic missing authorization must not dispatch"))
        scheduler = metric_schedule.MetricScheduler(None, oauth, transport=transport,
                                                    workspace_allowlist={WORKSPACE})
        # Isolate the scope check after workspace/provider admission, as existing
        # test_growth_metric_schedule.Read does; this does not authorize a grant.
        scheduler._eligible = lambda _: "read"
        outcome = scheduler.read({"workspaceId": WORKSPACE, "connectionId": ACCOUNT,
                                  "provider": "instagram", "postId": "synthetic-native-0"}, {})
        self.assertEqual((outcome["state"], outcome["failure"]), ("cancelled", "analytics_scope_missing"))
        self.assertNotIn("found", outcome)
        transport.assert_not_called()

        class SyntheticReadOnlyCursor:
            def execute(self, sql, params=None):
                if not sql.startswith("SELECT"):
                    raise AssertionError("Acceptance cursor must remain read-only")
            def fetchone(self):
                return (True,)
            def fetchall(self):
                return []  # Schema exists, but no Direct analytics authorization.

        tracking = beta.tracking(SyntheticReadOnlyCursor(), WORKSPACE, native_fixture(1)["state"], NOW, enabled=True)
        self.assertTrue(all(h["state"] == "rights_unavailable" for h in tracking["posts"][0]["horizons"]))
        self.assertEqual(outputs(native_fixture(10, missing=True))[2], [])

    def test_missing_invalid_and_unavailable_values_never_become_measured_zero(self):
        for value in (None, True, False, -1, float("nan"), float("inf"), "0"):
            with self.subTest(value=value):
                fetched = insights.fetch_post_insights(lambda *_: {"status": 200, "body": {
                    "data": [{"name": "reach", "values": [{"value": value}]}]}},
                    "synthetic-token", "instagram", "synthetic-native")
                self.assertEqual(fetched["found"], {})
                cursor = Mock()
                insights.record_observations(cursor, WORKSPACE, ACCOUNT, "instagram", "synthetic-native",
                                              "synthetic-job", fetched["found"], fetched["endpoint"], NOW)
                for call in cursor.execute.call_args_list:
                    params = call.args[1]
                    self.assertIsNone(params[7])
                    self.assertEqual(params[8], "unavailable")
        fixture = native_fixture(1, missing=True)
        fixture["rows"][0] = (*fixture["rows"][0][:5], 0, *fixture["rows"][0][6:])
        summary, _, _ = outputs(fixture)
        marked_unavailable = summary["posts"][0]["metrics"]["reach"]
        self.assertEqual((marked_unavailable["value"], marked_unavailable["display"]),
                         (None, "Unavailable"))
        post = {"id": "synthetic-unavailable", "readings": {"24h": {"reach": {
            "value": 0, "availability": "unavailable"}}}}
        result = performance.compare(post, [], "24h")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["metrics"]["reach"]["value"])

    def test_true_measured_zero_survives_parser_storage_display_and_comparison(self):
        fetched = insights.fetch_post_insights(lambda *_: {"status": 200, "body": {"data": [
            {"name": "reach", "total_value": {"value": 0}}]}},
            "synthetic-token", "instagram", "synthetic-native")
        self.assertEqual(fetched["found"], {"reach": 0})
        cursor = Mock()
        insights.record_observations(cursor, WORKSPACE, ACCOUNT, "instagram", "synthetic-native",
                                      "synthetic-job", fetched["found"], fetched["endpoint"], NOW)
        reach = next(c.args[1] for c in cursor.execute.call_args_list if c.args[1][5] == "reach")
        self.assertEqual((reach[7], reach[8]), (0, "available"))
        fixture = native_fixture(4)
        fixture["rows"][0] = (*fixture["rows"][0][:5], 0, *fixture["rows"][0][6:])
        summary, _, _ = outputs(fixture)
        zero = summary["posts"][0]["metrics"]["reach"]
        self.assertEqual((zero["value"], zero["display"], zero["availability"]), (0, "0", "available"))
        self.assertEqual(insights.compare(summary["posts"], "reach")["measured"], 4)
        post = {"id": "synthetic-zero", "readings": {"24h": {"reach": zero}}}
        self.assertEqual(performance.compare(post, [], "24h")["status"], "observed")
        self.assertEqual(performance.compare(post, [], "24h")["metrics"]["reach"]["value"], 0)

    def test_hypothesis_range_uses_its_supporting_metric_time(self):
        fixture = native_fixture(unrelated_time=True)
        _, _, recommendations = outputs(fixture)
        self.assertTrue(recommendations)
        times = [r[8] for r in fixture["rows"] if r[3] == "reach"]
        for recommendation in recommendations:
            self.assertEqual([recommendation["date_from"], recommendation["date_to"]],
                             [min(times), max(times)], "Recommendation range must use reach, not comments")

    def test_postmortem_lessons_emit_supporting_evidence_time_range(self):
        posts, _, report = postmortem_fixture()
        self.assertTrue(report["lessons"], "Positive control must emit a lesson")
        times = {p["id"]: p["readings"]["24h"]["shares"]["observedAt"] for p in posts}
        for lesson in report["lessons"]:
            evidence = lesson["evidenceIds"] + lesson["counterEvidenceIds"]
            self.assertTrue(evidence)
            self.assertEqual(lesson["metric"], "shares")
            self.assertEqual(lesson["provenance"], ["official"])
            self.assertEqual(lesson["cohort"]["connectionId"], "synthetic-threads-account")
            self.assertEqual(report["horizon"], "24h")
            self.assertIn("association, not a cause", lesson["text"])
            self.assertEqual(lesson.get("dateRange", report.get("dateRange")),
                             [min(times[i] for i in evidence), max(times[i] for i in evidence)],
                             "24h age is not the calendar range of supporting evidence")


if __name__ == "__main__":
    unittest.main()
