import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from postriff_phase2.growth.trends import opportunity_lab as lab, exposures


class OpportunityLab(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((Path(__file__).parent/"fixtures/trends/advanced/lab.json").read_text())
        for target in ("socket.socket","socket.create_connection","urllib.request.urlopen"):
            mock=patch(target,side_effect=AssertionError("no egress")); mock.start(); self.addCleanup(mock.stop)

    def completed(self):
        self.p["run"]=lab.freeze_run(self.p)
        self.p["run"]=lab.evaluate_run(self.p)
        return self.p["run"]

    def test_freeze_is_not_queued_job_and_contains_server_refs(self):
        r=lab.freeze_run(self.p)
        self.assertEqual(r["state"],"unavailable")
        self.assertEqual(r["failure_reason"],"evaluation_not_executed")
        self.assertEqual(r["kind"],"lab_run")
        self.assertEqual(r["context_revision"],"brand_1")
        self.assertEqual(r["trust_receipt_id"],"receipt_a")
        self.assertEqual(len(r["draft_digest"]),64)
        self.assertNotIn("text",r)

    def test_request_mismatch_and_other_workspace_rejected(self):
        self.p["request"]={"draft_revision":2}
        with self.assertRaises(ValueError): lab.freeze_run(self.p)
        self.p.pop("request"); self.p["context"]["workspace_id"]="other"
        with self.assertRaises(ValueError): lab.freeze_run(self.p)

    def test_platform_and_unsaved_draft_fail_closed(self):
        p=copy.deepcopy(self.p); p["target_platform"]="youtube"
        with self.assertRaisesRegex(ValueError,"platform"): lab.freeze_run(p)
        p=copy.deepcopy(self.p); p["draft"]["saved"]=False
        with self.assertRaisesRegex(ValueError,"saved"): lab.freeze_run(p)

    def test_selective_patch_does_not_mutate_draft_or_publisher(self):
        self.completed(); before=copy.deepcopy(self.p)
        result=lab.select_patches({**self.p,"selected_edit_ids":["edit_a"]})
        self.assertEqual(len(result["patches"]),1)
        self.assertTrue(result["invalidate_approval"])
        self.assertTrue(result["requires_existing_variant_edit"])
        self.assertEqual(result["expected_revision"],1)
        self.assertFalse(result["publisher_mutated"])
        self.assertEqual(self.p,before)

    def test_draft_unsaved_change_even_same_revision_is_stale(self):
        self.completed(); self.p["draft"]["text"]+=" Edited unsaved text."
        result=lab.project_run(self.p)
        self.assertEqual(result["state"],"stale")
        self.assertEqual(result["diagnostics"],[])
        self.assertEqual(lab.select_patches({**self.p,"selected_edit_ids":["edit_a"]})["patches"],[])

    def test_context_content_change_and_revision_change_stale(self):
        self.completed(); self.p["context"]["brand_voice"]="new"
        self.assertIn("context_digest_changed",lab.project_run(self.p)["stale_reasons"])
        self.p["context"]["revision"]="brand_2"
        self.assertEqual(lab.project_run(self.p)["state"],"stale")

    def test_source_loss_receipt_expiry_and_method_change_stale(self):
        self.completed()
        for change in ("rights","expiry","method"):
            p=copy.deepcopy(self.p)
            if change=="rights": p["sources"][0]["rights"]["creative"]=False
            if change=="expiry": p["decision_cutoff"]="2026-09-29T00:00:00Z"
            if change=="method": p["lab_method_version"]="v2"
            with self.subTest(change=change): self.assertEqual(lab.project_run(p)["state"],"stale")

    def test_invented_user_experience_never_enters_suggested_edit(self):
        self.p["findings"][0]["suggested_edit"]["after"]="I tested this with 100 clients."
        result=self.completed()
        finding=next(f for f in result["diagnostics"] if f["dimension"]=="hook_crowding")
        self.assertTrue(finding["requires_user_fact"])
        self.assertIsNone(finding["suggested_edit"])

    def test_approved_user_fact_can_support_personal_edit(self):
        self.p["context"]["approved_user_fact_refs"]=["owned_fact"]
        self.p["findings"][0].update(user_fact_refs=["owned_fact"])
        self.p["findings"][0]["suggested_edit"]["after"]="I tested this."
        result=self.completed()
        self.assertIsNotNone(next(f for f in result["diagnostics"] if f["dimension"]=="hook_crowding")["suggested_edit"])

    def test_no_own_history_means_unknown_format_fit(self):
        self.p["findings"][0].update(dimension="format_fit",historical_claim=True,claim="Your best format")
        r=self.completed()
        self.assertEqual(next(f for f in r["diagnostics"] if f["dimension"]=="format_fit")["assessment"],"unknown")

    def test_future_findings_abstain(self):
        self.p["findings"][0]["available_at"]="2027-01-01T00:00:00Z"
        self.assertTrue(all(f["assessment"]=="unknown" for f in self.completed()["diagnostics"]))

    def test_comparison_history_change_and_future_run_invalidate(self):
        self.completed()
        p=copy.deepcopy(self.p); p["own_history"]={"new":"actual history"}
        self.assertIn("own_history_digest_changed",lab.project_run(p)["stale_reasons"])
        p=copy.deepcopy(self.p); p["run"]["decision_cutoff"]="2027-01-01T00:00:00Z"
        self.assertIn("run_not_available_at_cutoff",lab.project_run(p)["stale_reasons"])

    def test_invented_personal_experience_in_claim_abstains(self):
        self.p["findings"][0]["claim"]="I tested this with my clients."
        r=self.completed()
        self.assertEqual(next(f for f in r["diagnostics"] if f["dimension"]=="hook_crowding")["assessment"],"unknown")

    def event(self,id,kind,**kw):
        return {"event_id":id,"event_type":kind,"exposure_id":"exposure","workspace_id":"workspace_a",
                "event_at":f"2026-09-26T{12+int(id):02}:00:00Z","available_at":f"2026-09-26T{12+int(id):02}:00:00Z",**kw}

    def test_clicked_never_published_has_no_attributed_outcome(self):
        self.p["events"]=[self.event("0","exposure",eligible_candidate_ids=["opp"],chosen_candidate_id="opp"),self.event("1","acceptance",angle_id="angle")]
        r=exposures.build_lineage(self.p)
        self.assertEqual((r["exposure_count"],r["published_count"],r["missing_outcomes"]),(1,0,1))
        self.assertIsNone(r["causal_effect"])

    def test_only_verified_approved_published_revision_and_changed_angle(self):
        self.p["events"]=[self.event("0","exposure",eligible_candidate_ids=["opp"],chosen_candidate_id="opp"),
                          self.event("1","acceptance",angle_id="old"),self.event("2","approval",draft_id="draft",draft_revision=2),
                          self.event("3","published",draft_id="draft",draft_revision=2,verified=True,platform_post_id="post",platform="bluesky",angle_id="new"),
                          self.event("4","outcome",publication_event_id="3",rights={"analysis":True},complete=True,metric_value=3,metric_definition="likes",horizon_hours=1)]
        r=exposures.build_lineage(self.p)
        self.assertEqual(r["published_count"],1)
        self.assertTrue(r["exposures"][0]["published"][0]["treatment_changed"])
        self.assertEqual(len(r["exposures"][0]["outcomes"]),1)
        self.p["events"][3]["draft_revision"]=3
        self.assertEqual(exposures.build_lineage(self.p)["published_count"],0)

    def test_creator_baseline_excludes_self_future_tenant_paid_and_wrong_metric(self):
        target={"post_id":"target","account_id":"account","platform":"bluesky","format":"text","language":"yue","horizon_hours":6,"metric_definition":"likes"}
        row={**target,"workspace_id":"workspace_a","post_id":"past","value":10,"verified_published":True,"complete":True,"paid_promotion":False,"rights":{"analysis":True},"available_at":"2026-09-26T12:00:00Z","observed_at":"2026-09-26T12:00:00Z"}
        rows=[row,{**row,"post_id":"target"},{**row,"available_at":"2027-01-01T00:00:00Z"},{**row,"workspace_id":"other"},{**row,"paid_promotion":True},{**row,"metric_definition":"views"}]
        r=exposures.creator_baseline({**self.p,"target":target,"outcomes":rows})
        self.assertEqual((r["count"],r["median"],r["excluded_count"]),(1,10,5))


if __name__=="__main__": unittest.main()
