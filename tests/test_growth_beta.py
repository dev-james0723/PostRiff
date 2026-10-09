"""Growth Beta boundaries; synthetic native contracts never authorize a provider."""
import copy
import unittest
from unittest.mock import patch

from postriff_phase2.growth import scout_outcomes
from postriff_phase2.growth.trends import learning


def native_pair():
    row = {"id": "job-1", "providerPostId": "post-1", "account": "owned-1", "provider": "fixture",
           "language": "en", "format": "text", "window": "24h", "objective": "follower_conversion",
           "definition": "fixture-v1", "publishedAt": 100, "metrics": {}}
    for metric, value in (("follows", 5), ("profile_visits", 100)):
        row["metrics"][metric] = {"value": value, "coverage": "available", "receipt": "observation-" + metric,
            "observedAt": 86500, "provider": "fixture", "account": "owned-1", "window": "24h",
            "definition": "fixture:fixture-v1:" + metric, "unit": "count", "attributionScope": "post",
            "scopeId": "post-1", "periodStart": 100, "periodEnd": 86500,
            "sourceEndpoint": "fixture://native-insights"}
    return row


class FollowerBoundary(unittest.TestCase):
    def test_unqualified_native_pair_unavailable(self):
        self.assertIsNone(scout_outcomes.objective_measure(native_pair())[0])

    def test_follower_objective_rejects_proxy_choice(self):
        state = {"sources": [{"active": True, "origin": {"trendLineage": {"selection_digest": "s", "channel_id": "c"}}}],
                 "phase2": {"channels": [{"id": "c", "platform": "Threads"}]}}
        with self.assertRaisesRegex(ValueError, "follower_conversion_unavailable"):
            learning.record_metric_choice(state, "actor", {"selection_digest": "s", "channel_id": "c",
                "provider": "threads", "metric": "views", "definition_version": "2026-09",
                "window": "24h", "objective": "follower_conversion"}, 100)
        self.assertNotIn("coworker", state)

    def test_conversion_rejects_mismatched_contract(self):
        # The real production registry is empty. Qualification is injected only
        # into this local arithmetic test, using a synthetic provider/endpoint.
        from postriff_phase2.growth import follower_conversion as conversion
        admitted = {("fixture", "fixture-v1"): {"endpoint": "fixture://native-insights", "scope": "post"}}
        with patch.object(conversion, "REVIEWED_CONTRACTS", admitted):
            self.assertAlmostEqual(scout_outcomes.objective_measure(native_pair())[0], .05)
            for field, changed in (("provider", "other"), ("account", "other"), ("window", "7d"),
                    ("definition", "fixture:old:profile_visits"), ("periodStart", 101), ("periodEnd", 86501),
                    ("attributionScope", "account"), ("scopeId", "other"), ("sourceEndpoint", "other"),
                    ("coverage", "unavailable"), ("receipt", None), ("unit", "percent")):
                with self.subTest(field=field):
                    row = native_pair()
                    row["metrics"]["profile_visits"][field] = changed
                    self.assertIsNone(scout_outcomes.objective_measure(row)[0])

    def test_conversion_zero_denominator_unavailable(self):
        from postriff_phase2.growth import follower_conversion as conversion
        with patch.object(conversion, "REVIEWED_CONTRACTS", {("fixture", "fixture-v1"): {
                "endpoint": "fixture://native-insights", "scope": "post"}}):
            for value in (0, None, float("nan"), float("inf"), -1, True):
                with self.subTest(value=value):
                    row = native_pair()
                    row["metrics"]["profile_visits"]["value"] = value
                    self.assertIsNone(scout_outcomes.objective_measure(row)[0])
            row = native_pair()
            row["metrics"]["follows"]["value"] = 0
            self.assertEqual(scout_outcomes.objective_measure(row)[0], 0)

    def test_saved_proxy_never_enters_learning(self):
        choice = {"id": "choice", "confirmed": True, "selected_by": "actor", "selected_at": 100,
            "selection_digest": "s", "channel_id": "c", "provider": "threads", "metric": "views",
            "definition_version": "2026-09", "window": "24h", "objective": "follower_conversion"}
        state = {"coworker": {"trendLearning": {"metricChoices": [choice]}}}
        self.assertIsNone(learning._choice(state, {"selection_digest": "s"}, {"channelId": "c", "platform": "Threads"}, 200, "24h"))


class BetaStatus(unittest.TestCase):
    wid = "00000000-0000-4000-8000-000000000001"

    def test_status_fails_closed_without_workspace_and_trust(self):
        from postriff_phase2.growth.trends import beta
        values = {"RAFII_TREND_" + k + "_ENABLED": "1" for k in ("INTELLIGENCE", "RADAR", "TRUST_RECEIPTS")}
        self.assertEqual(beta.status(self.wid, {}, metric_reads_enabled=False)["state"], "feature_off")
        self.assertEqual(beta.status(self.wid, values, metric_reads_enabled=False)["state"], "workspace_not_allowlisted")
        values["RAFII_TREND_WORKSPACE_ALLOWLIST"] = self.wid
        result = beta.status(self.wid, values, metric_reads_enabled=True)
        self.assertEqual((result["state"], result["acquisition"], result["radar_available"]), ("stored_radar", "none", True))
        values["RAFII_TREND_PROVIDER_OPERATIONS_ENABLED"] = "1"
        self.assertEqual(beta.status(self.wid, values, metric_reads_enabled=True)["acquisition"], "none")
        values["RAFII_TREND_ALLOWED_OPERATIONS"] = "bluesky:live_sample"
        self.assertEqual(beta.status(self.wid, values, metric_reads_enabled=True)["acquisition"], "unverified")
        values["RAFII_TREND_TRUST_RECEIPTS_ENABLED"] = "0"
        self.assertFalse(beta.status(self.wid, values, metric_reads_enabled=True)["radar_available"])

    def test_tracking_states_preserve_missing_and_zero(self):
        from postriff_phase2.growth.trends.beta import horizon_state
        self.assertEqual(horizon_state(None, 200, 100), "unscheduled")
        self.assertEqual(horizon_state(None, 0, 100), "unscheduled")
        for status, measured, expected in (("done", True, "measured"), ("done", False, "unavailable"),
                ("claimed", False, "pending"), ("unavailable", False, "unavailable"),
                ("cancelled", False, "disconnected"), ("pending", False, "scheduled"),
                ("dead", False, "unavailable")):
            self.assertEqual(horizon_state({"status": status, "measured": measured}, 0, 100), expected)

    def test_missed_windows_and_cancellations_keep_their_real_reason(self):
        from postriff_phase2.growth.trends.beta import horizon_state
        missed = {"status": "unavailable", "measured": False, "reason": "window_missed"}
        self.assertEqual(horizon_state(missed, 0, 100), "missed")
        self.assertEqual(horizon_state({**missed, "status": "done"}, 0, 100), "missed")
        cases = (("not_admitted", True, "not_entitled"), ("not_admitted", False, "not_entitled"),
                 ("analytics_scope_missing", True, "rights_unavailable"), ("not_eligible", True, "rights_unavailable"),
                 ("analytics_scope_missing", False, "disconnected"), ("not_eligible", False, "disconnected"),
                 (None, False, "disconnected"))
        for reason, live, expected in cases:
            with self.subTest(reason=reason, live=live):
                row = {"status": "cancelled", "measured": False, "reason": reason, "credential_live": live}
                self.assertEqual(horizon_state(row, 0, 100), expected)

    def test_tracking_reads_credential_liveness_for_this_workspace_only(self):
        from postriff_phase2.growth.trends.beta import tracking
        class Cursor:
            def __init__(self):
                self.sql = []
            def execute(self, sql, params=()):
                self.sql.append((" ".join(sql.split()), params))
                text = self.sql[-1][0]
                self.rows = ([(True,)] if "to_regclass" in text else [("live",)] if "pr_channel_capabilities" in text
                             else [("live",)] if "pr_encrypted_credentials" in text
                             else [("job-1", "live", "threads", "p1", "1h", "cancelled", 3700.0, "not_admitted", False),
                                   ("job-1", "live", "threads", "p1", "24h", "cancelled", 86500.0, "not_eligible", False),
                                   ("job-1", "live", "threads", "p1", "7d", "unavailable", 604900.0, "window_missed", False)])
            def fetchone(self):
                return self.rows[0]
            def fetchall(self):
                return self.rows
        cur = Cursor()
        state = {"phase2": {"channels": [{"id": "live"}], "jobs": [{"id": "job-1", "state": "verified", "providerReference": "p1",
                                                                    "verification": {"at": 100}, "manifest": {"platform": "Threads", "channelId": "live"}}]}}
        result = tracking(cur, "w1", state, 200, enabled=True)
        states = {h["window"]: h["state"] for h in result["posts"][0]["horizons"]}
        self.assertEqual(states, {"t0": "unscheduled", "1h": "not_entitled", "24h": "rights_unavailable", "7d": "missed"})
        credential = next(params for sql, params in cur.sql if "pr_encrypted_credentials" in sql)
        self.assertEqual(credential, ("w1",))

    def test_growth_tracking_covers_all_visible_posts_without_dispatch(self):
        from postriff_phase2.growth.trends.beta import tracking
        class NoQueries:
            def execute(self, *_):
                raise AssertionError('Disabled tracking must not query schedules or dispatch work')
        state={'phase2':{'jobs':[{'id':str(i),'state':'verified','providerReference':str(i),
                                 'verification':{'at':100},'manifest':{'platform':'Threads','channelId':'owned'}}
                                for i in range(300)]}}
        limited=tracking(NoQueries(),'workspace',state,200,enabled=False)
        self.assertTrue(limited['truncated'])
        full=tracking(NoQueries(),'workspace',state,200,enabled=False,limit=300)
        self.assertEqual(len(full['posts']),300)
        self.assertFalse(full['truncated'])
        self.assertTrue(all(h['state']=='disabled' for p in full['posts'] for h in p['horizons']))
        for invalid in (0,301,True):
            with self.assertRaises(ValueError):tracking(NoQueries(),'workspace',state,200,enabled=False,limit=invalid)


class ComparableFeedback(unittest.TestCase):
    def test_scout_outcome_rejects_a_foreign_native_post_for_the_job(self):
        job = {"id": "job-1", "state": "verified", "providerReference": "native-1",
               "manifest": {"channelId": "account-1", "platform": "Threads", "scoutLineage": []}}
        state = {"phase2": {"jobs": [job]}}
        post = {"jobId": "job-1", "publishedState": "verified", "connectionId": "account-2",
                "provider": "threads", "providerPostId": "native-1", "definitionVersion": "v1", "metrics": {}}
        from postriff_phase2 import insights
        with patch.object(insights, "summary", return_value={"posts": [post]}):
            self.assertEqual(scout_outcomes.refresh(None, "workspace-1", state, 100), [])
            post["connectionId"] = "account-1"
            post["providerPostId"] = "native-2"
            self.assertEqual(scout_outcomes.refresh(None, "workspace-1", state, 100), [])
            post["providerPostId"] = "native-1"
            post["publishedState"] = "unknown"
            self.assertEqual(scout_outcomes.refresh(None, "workspace-1", state, 100), [])

    def test_scout_metric_keeps_its_own_definition_version(self):
        post = {"provider": "threads", "connectionId": "account-1", "definitionVersion": "old",
                "language": "en", "contentTypeId": "text", "metrics": {"views": {
                    "availability": "available", "readOffset": "24h", "value": 7,
                    "definitionVersion": "native-v2", "observedAt": 100}}}
        row = scout_outcomes.from_insights(post, {"id": "job-1"},
                                           {"primaryObjective": "reach", "opportunityId": "op-1", "id": "plan-1"}, "24h")
        self.assertEqual(row["metrics"]["views"]["definition"], "threads:native-v2:views")

    def test_jev_cannot_be_dispatched_as_a_growth_oracle(self):
        from unittest.mock import Mock
        from postriff_phase2.growth.trends import judge
        router = Mock()
        for task in ('popularity', 'velocity', 'reach', 'views', 'follower_growth', 'follower_conversion'):
            with self.assertRaisesRegex(ValueError, 'unknown_trend_evaluation_task'):
                judge.evaluate(router, task, {}, workspace_id='w', authorized=True, reserved_microusd=1)
        router.evaluator.assert_not_called()

    def test_provider_parser_rejects_nonfinite_native_numbers(self):
        from postriff_phase2 import insights
        for value in (float('inf'), float('nan'), -1, True):
            result = insights.fetch_post_insights(lambda *a: {"status": 200, "body": {"data": [{"name": "views", "values": [{"value": value}]}]}}, 'local', 'threads', 'p')
            self.assertEqual(result['found'], {})

    def test_same_native_id_never_shares_account_or_publication(self):
        from postriff_phase2 import insights
        rows = [(p, 'same', j, 'views', 'v1', 10, 'count', 'available', 100, 100, a, '24h')
                for p, j, a in [('threads', 'j1', 'a1'), ('threads', 'j2', 'a2'), ('instagram', 'j3', 'a3')]]
        jobs = [{'id': j, 'providerReference': 'same', 'state': 'verified', 'manifest': {'channelId': a, 'platform': p, 'payload': {'language': 'en'}, 'contentType': {'id': j}}}
                for p, _, j, *rest in rows for a in [rest[-2]]]
        with patch.object(insights, 'latest_observations', return_value=rows):
            posts = insights.summary(None, 'w', jobs, 100, basis='24h')['posts']
        self.assertEqual(len(posts), 3)
        self.assertEqual({p['contentTypeId'] for p in posts}, {'j1', 'j2', 'j3'})
        self.assertEqual({p['cohort']['account'] for p in posts}, {'a1', 'a2', 'a3'})

    def test_non_24h_outcomes_never_enter_hypotheses(self):
        for window in ("1h", "7d"):
            with patch.object(learning.performance, "hypotheses_from") as engine:
                self.assertEqual(learning.hypotheses({"window": window, "exposures": []}, 100), [])
                engine.assert_not_called()

    def test_relative_comparison_requires_five_and_positive_baseline(self):
        target = {"value": 20, "treatment_state": "unchanged", "paid_promotion": False}
        peers = [{"post_id": str(i), "value": 10 + i} for i in range(5)]
        for count, median in ((4, 10), (5, 0), (5, None)):
            result = learning.comparison(target, {"count": count, "median": median}, peers)
            self.assertIsNone(result["relative_value"])
        result = learning.comparison(target, {"count": 5, "median": 10}, peers)
        self.assertEqual(result["relative_value"], 1)
        self.assertEqual(len(result["evidence_ids"]), 5)
        self.assertFalse(result["causal"])
        self.assertIsNone(learning.comparison({**target, "value": 1e308}, {"count": 5, "median": 1e-308}, peers)["relative_value"])


if __name__ == "__main__":
    unittest.main()
