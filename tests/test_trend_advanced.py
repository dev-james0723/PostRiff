import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from postriff_phase2.growth.trends import context, narratives, graph, genome, copy_density, whitespace
from postriff_phase2.growth.trends import media_extraction, creative_patterns, platform_priors, spread, exposures

FIXTURES = Path(__file__).parent / "fixtures/trends/advanced"


class Advanced(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((FIXTURES / "saturation.json").read_text())
        for target in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
            mock = patch(target, side_effect=AssertionError("offline suite attempted egress"))
            mock.start()
            self.addCleanup(mock.stop)

    def evidence(self, **values):
        return {"available_at": "2026-09-26T12:00:00Z", "evidence_refs": ["s0"], **values}

    def test_exact_100_80_20_and_19_over_80(self):
        result = copy_density.measure_saturation(self.p)
        self.assertEqual(set(result["dimensions"]), {"topic", "narrative", "hook", "format", "creator"})
        hook = result["dimensions"]["hook"]
        self.assertEqual((hook["eligible_count"], hook["classified_count"], hook["unclassified_count"]), (100, 80, 20))
        self.assertEqual(hook["classification_coverage"], .8)
        common = next(p for p in hook["patterns"] if p["pattern_id"] == "common")
        self.assertEqual(common["classified_share"], .25)
        self.assertEqual(hook["redundancy_ratio"], 19/80)
        self.assertIsNotNone(common["interval"])
        self.assertEqual(result["audience_fatigue"], "unknown")
        self.assertEqual(result["dimensions"]["topic"]["classified_count"], 0)

    def test_unassessed_copy_is_null_not_measured_zero(self):
        self.p['copy_groups']=[]
        raw=copy_density.measure_saturation(self.p)
        row=raw['dimensions']['hook']
        self.assertEqual(row['classified_count'],80)
        self.assertTrue(row['patterns'])
        self.assertIsNone(row['redundancy_ratio'])
        wire=copy_density.to_stored_projection(raw)['payload']
        metric=next(r['metric'] for r in wire['dimensions'] if r['dimension']=='hook')
        self.assertEqual(metric['null_reason'],'copy_support_unassessed')
        members=[r['source_id'] for r in self.p['assignments'] if r['dimension']=='hook']
        self.p['copy_comparisons']={'hook':self.evidence(member_ids=members,evidence_refs=members,complete=True)}
        assessed=copy_density.measure_saturation(self.p)['dimensions']['hook']
        self.assertEqual(assessed['redundancy_ratio'],0)
        self.assertEqual(assessed['copy_support'],'assessed')
        self.p['copy_comparisons']['hook']['member_ids']=members[:2]
        self.assertIsNone(copy_density.measure_saturation(self.p)['dimensions']['hook']['redundancy_ratio'])

    def test_copy_groups_cannot_overlap(self):
        self.p["copy_groups"].append(copy.deepcopy(self.p["copy_groups"][0]))
        with self.assertRaisesRegex(ValueError, "disjoint"):
            copy_density.measure_saturation(self.p)

    def test_low_coverage_never_reassuring_label(self):
        self.p["assignments"] = self.p["assignments"][:10]
        result = copy_density.measure_saturation(self.p)["dimensions"]["hook"]
        self.assertFalse(result["evidence_floor_met"])
        self.assertIsNone(result["qualitative_label"])

    def test_creative_revocation_preserves_lawful_measurement(self):
        for row in self.p["sources"]:
            row["rights"]["creative"] = False
        result = copy_density.measure_saturation(self.p)
        self.assertEqual(result["dimensions"]["hook"]["eligible_count"], 100)
        self.assertEqual(result["dimensions"]["hook"]["classified_count"], 0)
        self.assertEqual(result["dimensions"]["creator"]["known_author_count"], 100)

    def test_future_assignments_and_future_sources_excluded(self):
        self.p["assignments"][0]["available_at"] = "2027-01-01T00:00:00Z"
        self.p["sources"][1]["available_at"] = "2027-01-01T00:00:00Z"
        result = copy_density.measure_saturation(self.p)["dimensions"]["hook"]
        self.assertEqual((result["eligible_count"], result["classified_count"]), (99,78))

    def test_conflicting_canonical_assignments_reject(self):
        self.p["sources"][21]["canonical_id"] = "c20"
        with self.assertRaisesRegex(ValueError, "conflicting"):
            copy_density.measure_saturation(self.p)

    def test_creator_concentration_exact(self):
        for i, source in enumerate(self.p["sources"]):
            source["creator_key"] = "a" if i<80 else "b"
        c = copy_density.measure_saturation(self.p)["dimensions"]["creator"]
        self.assertEqual(c["largest_creator_share"], .8)
        self.assertAlmostEqual(c["effective_creator_count"], 1/(.8**2+.2**2))

    def test_context_bounds_and_missing_branches(self):
        self.p.update(root_id="s0", relations=[self.evidence(source_id="s0",target_id=f"s{i}",relation_type="reply") for i in range(1,30)])
        result = context.build_context_bundle(self.p)
        self.assertEqual(len(result["member_ids"]), 21)
        self.assertIn("processing_bound", result["missing_context"])
        self.assertEqual(result["context_completeness"], "partial")

    def test_context_single_post_is_partial_and_future_reply_absent(self):
        self.p.update(root_id="s0", relations=[self.evidence(source_id="s0",target_id="s1",relation_type="reply",available_at="2027-01-01T00:00:00Z")])
        result = context.build_context_bundle(self.p)
        self.assertEqual(result["member_ids"], ["s0"])
        self.assertEqual(result["context_completeness"], "partial")

    def test_overlapping_bundles_do_not_multiply_posts_and_stances_stay_separate(self):
        self.p.update(episode_id="episode", bundles=[self.evidence(bundle_id=b,scope_key="sample",member_ids=["s0","s1"],evidence_refs=["s0","s1"]) for b in ("b0","b1")],
                      seeds=[self.evidence(seed_id=s,stance=stance,language="yue",original_spans=["真係 useful！"],bundle_ids=["b0"],claim="quoted",concept="test") for s,stance in (("n0","support"),("n1","oppose"))])
        result=narratives.build_narrative(self.p)
        self.assertEqual(result["unique_original_posts"],2)
        self.assertEqual([r["stance"] for r in result["seeds"]],["support","oppose"])
        self.assertEqual(result["seeds"][0]["original_spans"],["真係 useful！"])
        self.assertTrue(result["seeds"][0]["provisional"])

    def graph_payload(self):
        self.p["sources"][0]["creator_key"]="same_name"
        self.p["sources"][1].update(platform="x",creator_key="same_name")
        self.p["nodes"]=[self.evidence(node_id=n,node_type="creator",scope_key="sample",platform=p,creator_key="same_name",label="same_name",evidence_refs=[ref]) for n,p,ref in (("a","x","s1"),("b","bluesky","s0"))]
        self.p["edges"]=[self.evidence(edge_id="e",edge_type="co_occurrence",source_id="a",target_id="b",scope_key="sample",event_start="2026-09-26T12:00:00Z",event_end="2026-09-26T12:00:00Z",evidence_kind="calculated_association",method_version="v1")]
        self.p["claims"]=[self.evidence(claim_id="interpretation",depends_on=["e"],claim_type="association"),self.evidence(claim_id="opportunity",depends_on=["interpretation"],claim_type="hypothesis")]
        return self.p

    def test_graph_identity_first_seen_is_not_origin(self):
        result=graph.project_graph(self.graph_payload())
        self.assertEqual(len(result["nodes"]),2)
        self.assertEqual(len(result["claims"]),2)
        self.assertEqual(result["origin"],"unknown")
        self.assertFalse(result["causal_claims"])
        self.assertEqual(result["edges"],result["table"])

    def test_graph_sole_source_loss_invalidates_transitive_claims(self):
        payload=self.graph_payload()
        payload["sources"][0]["revoked"]=True
        result=graph.project_graph(payload)
        self.assertEqual(result["edges"],[])
        self.assertEqual(result["claims"],[])
        self.assertEqual(set(result["invalid_claim_ids"]),{"interpretation","opportunity"})

    def test_graph_future_edge_and_causal_type_blocked(self):
        payload=self.graph_payload()
        payload["edges"][0]["available_at"]="2027-01-01T00:00:00Z"
        self.assertEqual(graph.project_graph(payload)["edges"],[])
        payload["edges"][0]["available_at"]="2026-09-26T12:00:00Z"
        payload["edges"][0]["edge_type"]="causes"
        self.assertEqual(graph.project_graph(payload)["edges"],[])

    def test_genome_missing_modalities_and_native_evidence(self):
        self.p["dimensions"]={"language_cultural_usage":self.evidence(value="真係 useful！",derivation_kind="observation"),"visual_grammar":self.evidence(value="red background",derivation_kind="observation",inspected=True)}
        result=genome.build_genome(self.p)["dimensions"]
        self.assertEqual(result["language_cultural_usage"]["value"],"真係 useful！")
        self.assertIsNone(result["visual_grammar"]["value"])
        self.assertIsNone(result["audio"]["value"])

    def whitespace_payload(self):
        self.p["candidates"]=[self.evidence(candidate_id="gap",gap_type="unanswered_question",demand_strength="supported",demand_evidence_refs=["s0","s1"],
            supply_search_scope=self.evidence(qualified=True,frame_id="frame",retrieval_coverage=.9,context_complete=True),
            credibility=self.evidence(workspace_id="workspace_a",approved=True),originality_review="supported",proposed_contribution="Explain the missing practical steps.")]
        return self.p

    def test_whitespace_admits_only_supported_gap(self):
        result=whitespace.find_whitespace(self.whitespace_payload())
        self.assertEqual(len(result["opportunities"]),1)
        self.assertEqual(result["semantic_qualification"],"unqualified")

    def test_no_weak_demand_or_bad_retrieval_whitespace(self):
        p=self.whitespace_payload()
        p["candidates"][0]["demand_strength"]="weak"
        p["candidates"][0]["supply_search_scope"]["retrieval_coverage"]=.1
        result=whitespace.find_whitespace(p)
        self.assertFalse(result["opportunities"])
        self.assertIn("weak_or_missing_observed_demand",result["rejected"][0]["reasons"])
        self.assertIn("supply_comparison_insufficient",result["rejected"][0]["reasons"])

    def test_deleted_replies_cannot_establish_unanswered(self):
        p=self.whitespace_payload(); p["candidates"][0]["supply_search_scope"]["context_complete"]=False
        self.assertFalse(whitespace.find_whitespace(p)["opportunities"])

    def media_payload(self):
        self.p["sources"][0]["rights"]["transcript"]=True
        self.p["limits"]={"max_bytes":1000,"max_tokens":1000,"max_processing_seconds":10,"max_cost":0}
        self.p["clips"]=[self.evidence(clip_id="clip",duration_seconds=30,size_bytes=50,processing_tokens=100,processing_seconds=1,estimated_cost=0,
            available_modalities=["transcript"],keyframes=[],extractions={"transcript":[self.evidence(start_seconds=0,end_seconds=5,text="原文",derivation_kind="observation")],
                "visual":[self.evidence(start_seconds=0,end_seconds=5,descriptor="unseen scene",derivation_kind="observation",frame_ref="f")]})]
        return self.p

    def test_transcript_does_not_imply_video_audio(self):
        r=creative_patterns.build_creative_pattern(self.media_payload())["patterns"][0]["modalities"]
        self.assertEqual(r["transcript"]["state"],"available")
        self.assertEqual(r["visual"]["items"],[])
        self.assertEqual(r["audio"]["state"],"unknown")

    def test_timecodes_outside_clip_rejected(self):
        p=self.media_payload(); p["clips"][0]["extractions"]["transcript"][0]["end_seconds"]=31
        self.assertEqual(creative_patterns.build_creative_pattern(p)["patterns"][0]["modalities"]["transcript"]["items"],[])

    def test_visual_timecode_requires_actual_supplied_frame_reference(self):
        p=self.media_payload()
        p["sources"][0]["rights"]["visual"]=True
        p["clips"][0]["available_modalities"].append("visual")
        self.assertEqual(creative_patterns.build_creative_pattern(p)["patterns"][0]["modalities"]["visual"]["items"],[])
        p["clips"][0]["keyframes"]=[self.evidence(frame_id="f",at_seconds=1)]
        self.assertEqual(creative_patterns.build_creative_pattern(p)["patterns"][0]["modalities"]["visual"]["state"],"available")

    def test_media_resource_duration_count_and_frame_limits(self):
        p=self.media_payload(); p["clips"][0]["duration_seconds"]=91
        p["clips"][0]["keyframes"]=[{}]*13
        p["clips"]*=3
        r=media_extraction.check_media_eligibility(p)
        self.assertEqual(r["state"],"unavailable")
        self.assertIn("clip_count_limit",r["clips"][0]["reasons"])
        self.assertIn("duration_limit",r["clips"][0]["reasons"])
        self.assertIn("keyframe_limit",r["clips"][0]["reasons"])

    def test_explicit_media_caps_required(self):
        self.assertEqual(media_extraction.check_media_eligibility(self.p)["reasons"],["explicit_resource_caps_required"])

    def test_priors_separate_private_actuals_no_stereotype_wins(self):
        self.p["cohort"]={"platform":"bluesky","format":"text","language":"yue","niche":"education","period":"2026-09"}
        shared=self.evidence(**self.p["cohort"],qualification="qualified",finding="short")
        private={**shared,"workspace_id":"workspace_a","basis":"actual_published_outcomes","finding":"long"}
        self.p["priors"]=[shared,private]
        r=platform_priors.resolve_prior(self.p)
        self.assertTrue(r["conflict"])
        self.assertEqual(r["effective_basis"],"private_outcomes")
        self.p["priors"]=[shared]
        self.assertEqual(platform_priors.resolve_prior(self.p)["historical_fit"],"unknown")

    def test_spread_requires_alternatives_and_respects_exclusions(self):
        self.p["hypotheses"]=[self.evidence(mechanism="humor",alternatives=["practical utility"]),self.evidence(mechanism="fear_urgency",alternatives=["news"])]
        self.p["brand_exclusions"]=["fear_urgency"]
        r=spread.project_spread_hypotheses(self.p)
        self.assertEqual([h["mechanism"] for h in r["hypotheses"]],["humor"])
        self.assertFalse(r["causal_claim"])

    def test_inputs_not_mutated_and_json_serializable(self):
        before=copy.deepcopy(self.p)
        json.dumps(copy_density.measure_saturation(self.p),allow_nan=False)
        self.assertEqual(self.p,before)

    def test_lineage_future_child_and_cycle_reject(self):
        self.p["links"]=[self.evidence(parent_id="a",child_id="b",relation="continuation",parent_end="2026-09-26T10:00:00Z",child_start="2027-01-01T00:00:00Z")]
        with self.assertRaises(ValueError): narratives.link_episodes(self.p)

    def test_genome_model_interpretation_needs_explicit_model_rights(self):
        self.p["dimensions"]={"hook":self.evidence(value="model assertion",derivation_kind="model_interpretation")}
        self.assertIsNone(genome.build_genome(self.p)["dimensions"]["hook"]["value"])

    def test_projection_adapters_preserve_distinct_metric_denominators(self):
        wire=copy_density.to_stored_projection(copy_density.measure_saturation(self.p))
        self.assertEqual(wire["kind"],"saturation")
        hook=next(d for d in wire["payload"]["dimensions"] if d["dimension"]=="hook")
        self.assertEqual(hook["metric"]["value"],19/80)
        self.assertEqual(hook["metric"]["denominator"],"classified_original_observations")


if __name__ == "__main__":
    unittest.main()
