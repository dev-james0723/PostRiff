import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1]), *sys.path]):
    from scripts.competitor_bench.import_observations import freeze_manifest, validate_manifest, import_observations, build_query_grid
    from scripts.competitor_bench.run_candidates import run_candidates
    from scripts.competitor_bench.report import run_report, compare_behavior


class Competitor(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((Path(__file__).parent/"fixtures/trends/advanced/competitor.json").read_text())
        for target in ("socket.socket","socket.create_connection","urllib.request.urlopen"):
            mock=patch(target,side_effect=AssertionError("no egress")); mock.start(); self.addCleanup(mock.stop)

    def test_manifest_frozen_and_no_product_rows_is_not_run(self):
        result=run_report(self.p)
        self.assertEqual(result["observations"]["state"],"NOT_RUN")
        self.assertEqual(result["evidence_classes"]["validated"],"NOT_RUN")
        self.assertEqual(len(result["manifest"]["topics"]),30)
        self.p["manifest"]["topics"][0]["split"]="holdout"
        with self.assertRaisesRegex(ValueError,"digest"): validate_manifest(self.p["manifest"])

    def test_query_grid_preserves_native_language_and_only_permitted_geography(self):
        grid=build_query_grid({"aliases_by_language":{"en":["AI agents","AI agent"],"yue":["AI 幫手"]},"permitted_geographies":["HK"]})
        self.assertEqual(len(grid),9)
        self.assertEqual({r["geography"] for r in grid},{"HK"})
        self.assertTrue(any(r["query"]=="AI 幫手" for r in grid))

    def snapshot(self):
        query=self.p["manifest"]["query_grid"][0]
        return {"snapshot_id":"synthetic_import_contract","product":"fixture_only_not_vendor","rights":{"import":True,"analysis":True},
                "rights_ref":"fixture_rights","source_at":"2026-09-26T00:00:00Z","retrieved_at":"2026-09-26T01:00:00Z",
                "available_at":"2026-09-26T01:00:00Z","retention_until":"2026-10-01T00:00:00Z","evidence_hash":"fixture_digest",**query}

    def test_hidden_size_refresh_fields_are_incomparable_not_zero(self):
        p={**self.p,"observations":[self.snapshot()]}
        row=import_observations(p)["observations"][0]
        self.assertFalse(row["comparable"])
        self.assertIsNone(row["size_definition"])
        self.assertEqual(row["visible_fields"],{})
        p["observations"][0]["source_at"]=None
        self.assertIsNone(import_observations(p)["observations"][0]["source_at"])

    def test_future_snapshot_or_later_membership_rejected(self):
        for key in ("available_at","retrieved_at","source_at","membership_available_at"):
            row=self.snapshot(); row[key]="2027-01-01T00:00:00Z"
            result=import_observations({**self.p,"observations":[row]})
            with self.subTest(key=key): self.assertEqual(result["observations"],[])

    def test_revoked_expired_and_unfrozen_imports_rejected(self):
        for change in ({"revoked":True},{"retention_until":"2020-01-01T00:00:00Z"},{"evidence_hash":"not_frozen"}):
            r=import_observations({**self.p,"observations":[{**self.snapshot(),**change}]})
            with self.subTest(change=change): self.assertEqual(r["state"],"NOT_RUN")

    def counts(self,values,**kw):
        return {"observations":[{"count":v,"exposure_hours":1,"coverage_epoch":"same","complete":True} for v in values],**kw}

    def test_zero_mad_and_zero_count_baseline_abstain(self):
        r=run_candidates(self.counts([0,0,0,1]))["candidates"]
        self.assertIsNone(r["robust_mad"]["value"])
        self.assertEqual(r["count_residual"]["state"],"abstained")

    def test_robust_mad_exact_ewma_cusum_and_exposure_counts(self):
        r=run_candidates(self.counts([1,2,3,4,10],alpha=.5,cusum_warmup=2))["candidates"]
        self.assertAlmostEqual(r["robust_mad"]["value"],7.5/1.4826)
        self.assertEqual(r["ewma"]["baseline"],3.125)
        self.assertEqual(len(r["cusum"]["path"]),3)
        self.assertGreater(r["cusum"]["value"],r["cusum"]["path"][0]["positive"])
        p=self.counts([10,20,30]); p["observations"][1]["exposure_hours"]=2; p["observations"][2]["exposure_hours"]=3
        self.assertEqual(run_candidates(p)["candidates"]["count_residual"]["value"],0)

    def test_count_overdispersion_uses_negative_binomial(self):
        r=run_candidates(self.counts([0,100,0,100,120]))["candidates"]["count_residual"]
        self.assertEqual(r["model"],"negative_binomial")
        self.assertGreater(r["nb_alpha"],0)

    def test_outage_and_query_coverage_change_abstain(self):
        for key,value in (("complete",False),("coverage_epoch","changed")):
            p=self.counts([1,2,3]); p["observations"][1][key]=value
            with self.subTest(key=key): self.assertEqual(run_candidates(p)["state"],"incomparable")

    def test_single_author_burst_gate_and_nonidentifiability(self):
        p=self.counts([1,2,1000]); p["observations"][-1]["creator_counts"]={"same_author":1000}
        self.assertEqual(run_candidates(p)["concentration_gate"],"blocked")
        result=compare_behavior({"observed_ranking":["a","b","c"],"candidate_rankings":{"mad":["a","b","c"],"ewma":["a","b","c"],"other":["c","b","a"]}})
        self.assertIn(["mad","ewma"],result["non_identifiability"])
        self.assertEqual(result["agreement"]["other"]["kendall_tau"],-1)
        self.assertFalse(result["proprietary_formula_recovered"])

    def test_report_never_treats_unbacked_ranking_as_observed(self):
        self.p["comparison"]={"observed_ranking":["a"],"candidate_rankings":{"mad":["a"]}}
        self.assertEqual(run_report(self.p)["comparison"]["state"],"NOT_RUN")

    def test_count_models_and_creator_coverage_fail_closed(self):
        with self.assertRaises(ValueError): run_candidates(self.counts([1,2,2.5]))
        p=self.counts([1,2,1000]); p["observations"][-1]["creator_counts"]={f"author{i}":1 for i in range(10)}
        self.assertEqual(run_candidates(p)["concentration_gate"],"unknown")


if __name__=="__main__": unittest.main()
