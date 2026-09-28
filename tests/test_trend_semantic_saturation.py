"""Pure source-bound semantic saturation tests; synthetic annotations, no DB/I/O."""
from copy import deepcopy
import json
import socket
import unittest
from unittest.mock import patch

from postriff_phase2.growth.trends import copy_density, semantic_admission, semantic_saturation as S

CUTOFF = "2026-09-26T12:00:00Z"
AVAILABLE = "2026-09-26T12:10:00Z"
NOW = "2026-09-26T12:20:00Z"
EXPIRY = "2026-09-27T12:00:00Z"


def fixture(count=5, language="yue"):
    sources, facts = [], {}
    for i in range(count):
        sid = "s" + str(i)
        sources.append({"source_id": sid, "scope_key": "shared:sample", "platform": "native",
            "language": language, "event_at": "2026-09-26T11:30:00Z", "available_at": "2026-09-26T11:31:00Z",
            "expires_at": EXPIRY, "original": True, "creator_key": "provider:creator" + str(i),
            "rights": {"analysis": True, "creative": True, "llm": True, "display": True}})
        facts[sid] = {"provider_id": "provider", "source_identity": sid, "relations": [],
                     "text": "慢啲練，唔係放棄！🎹 piano practice... " + str(i)}
    inputs = {"common": {"scope_key": "shared:sample", "decision_cutoff": CUTOFF, "sources": sources},
        "facts": facts, "frame": {"frame_id": "sample-frame", "platform": "native", "language": language,
            "window_start": "2026-09-26T11:00:00Z", "window_end": CUTOFF,
            "acquisition_policy": "synthetic_sample", "classifier_version": "synthetic-reviewed"},
        "episode_id": "synthetic-episode", "expires_at": EXPIRY}
    return inputs


def item(inputs, refs, *, concept="練琴", claim="慢練有用", stance="supports"):
    return {"id": "synthetic-" + "-".join(refs), "concept": concept, "claim": claim, "stance": stance,
            "language": inputs["frame"]["language"], "uncertainties": ["Synthetic reviewed annotation; no empirical qualification."],
            "evidence_spans": [{"observation_id": sid, "start": 0, "end": len(inputs["facts"][sid]["text"]),
                               "text": inputs["facts"][sid]["text"]} for sid in refs]}


def selected(items):
    return [{"task": "semantic_label_generate", "qualified": True, "available_at": AVAILABLE,
             "expires_at": EXPIRY, "result": {"task": "trend.semantic_label_generate", "status": "ok",
                 "executed_model": "synthetic-reviewed-model", "input_digest": "a" * 64, "items": items}}]


class SemanticSaturationTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo", "urllib.request.urlopen"):
            guard = patch(name, side_effect=AssertionError("No external I/O permitted"))
            mock = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mock.assert_not_called)
        self.inputs = fixture()
        self.selected = selected([item(self.inputs, ["s0", "s1"]), item(self.inputs, ["s2", "s3"], stance="opposes")])

    def build(self, inputs=None, entries=None, adapted=None):
        return S.build_assignments(inputs or self.inputs, entries if entries is not None else self.selected, now=NOW, adapted=adapted)

    def test_real_adapter_candidates_keep_topic_and_opposed_narrative_distinct(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        r = self.build(adapted=adapted)
        topics = [a for a in r["assignments"] if a["dimension"] == "topic"]
        narratives = [a for a in r["assignments"] if a["dimension"] == "narrative"]
        self.assertEqual(len(topics), 4)
        self.assertEqual(len({a["pattern_id"] for a in topics}), 1)
        self.assertEqual(len({a["pattern_id"] for a in narratives}), 2)
        self.assertEqual({a["stance"] for a in narratives}, {"supports", "opposes"})
        self.assertEqual(r["copy_groups"], [])
        self.assertEqual(r["copy_support"], {"topic": "unassessed", "narrative": "unassessed"})
        self.assertEqual(r["audience_fatigue"], "unknown")

    def test_current_model_cutoff_preserves_old_source_window_and_actual_availability(self):
        r = self.build()
        self.assertEqual(r["source_decision_cutoff"], CUTOFF)
        self.assertEqual(r["decision_cutoff"], "2026-09-26T12:20:00Z")
        self.assertTrue(all(a["available_at"] == "2026-09-26T12:10:00Z" for a in r["assignments"]))
        historical = copy_density.measure_saturation({**self.inputs["common"], "frame": self.inputs["frame"], "assignments": r["assignments"]})
        self.assertEqual(historical["dimensions"]["topic"]["classified_count"], 0)
        current = copy_density.measure_saturation({**self.inputs["common"], "decision_cutoff": r["decision_cutoff"],
            "frame": self.inputs["frame"], "assignments": r["assignments"]})
        self.assertEqual(current["frame"]["window_end"], CUTOFF)
        self.assertEqual(current["dimensions"]["topic"]["classified_count"], 4)

    def test_existing_pattern_counts_prevalence_creators_and_unknown_denominator_preserved(self):
        r = self.build()
        measured = copy_density.measure_saturation({**self.inputs["common"], "decision_cutoff": r["decision_cutoff"],
            "frame": self.inputs["frame"], "assignments": r["assignments"], "copy_groups": r["copy_groups"]})
        self.assertEqual(set(measured["dimensions"]), {"topic", "narrative", "hook", "format", "creator"})
        topic, narrative = measured["dimensions"]["topic"], measured["dimensions"]["narrative"]
        self.assertEqual((topic["eligible_count"], topic["classified_count"], topic["unclassified_count"]), (5, 4, 1))
        self.assertEqual(topic["classification_coverage"], .8)
        self.assertEqual(topic["patterns"][0]["classified_share"], 1)
        self.assertEqual(topic["patterns"][0]["unique_creator_support"], 4)
        self.assertEqual([p["classified_share"] for p in narrative["patterns"]], [.5, .5])
        self.assertTrue(all(p["interval"] is not None for p in narrative["patterns"]))
        self.assertIsNone(topic["qualitative_label"])
        # No assertion of semantic copy redundancy: caller must apply the explicit
        # unassessed boundary; the legacy default is not evidence of zero copies.

    def test_unqualified_and_nonsemantic_task_cannot_supply_assignments(self):
        self.selected[0]["qualified"] = False
        self.assertEqual(self.build()["assignments"], [])
        self.selected = [{"task": "culture_explain", "qualified": True, "available_at": AVAILABLE, "expires_at": EXPIRY,
            "result": {"task": "trend.culture_explain", "status": "ok", "executed_model": "synthetic",
                "input_digest": "b" * 64, "items": [{"id": "c", "language": "yue", "explanation": "文化候選",
                    "alternatives": ["另解"], "uncertainties": ["未知"],
                    "evidence_spans": item(self.inputs, ["s0"])["evidence_spans"]}]}}]
        self.assertEqual(self.build()["assignments"], [])

    def test_missing_future_expired_and_inconsistent_annotation_times_abstain(self):
        for field, value in (("available_at", None), ("available_at", "2026-09-26T12:21:00Z"), ("expires_at", NOW)):
            entries = deepcopy(self.selected); entries[0][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.build(entries=entries)["assignments"], [])
        entries = deepcopy(self.selected); entries[0]["result"]["computed_at"] = "2026-09-26T12:21:00Z"
        self.assertEqual(self.build(entries=entries)["assignments"], [])
        entries[0]["result"]["computed_at"] = "2026-09-26T12:09:00Z"
        self.assertEqual(len(self.build(entries=entries)["assignments"]), 8)

    def test_no_computed_timestamp_is_invented_when_db_availability_exists(self):
        result = deepcopy(self.selected[0]["result"])
        self.assertEqual(len(self.build()["assignments"]), 8)
        self.assertEqual(self.selected[0]["result"], result)
        self.assertNotIn("computed_at", result)

    def test_current_rights_revocation_or_privacy_loss_never_reuses_old_adaptation(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        for change in ("llm", "creative", "analysis", "deleted", "revoked", "expired", "scope"):
            inputs = deepcopy(self.inputs)
            for source in inputs["common"]["sources"]:
                if change in ("llm", "creative", "analysis"): source["rights"][change] = False
                elif change in ("deleted", "revoked"): source[change] = True
                elif change == "expired": source["expires_at"] = NOW
                else: source["scope_key"] = "workspace:foreign"
            with self.subTest(change=change):
                self.assertEqual(self.build(inputs=inputs, adapted=adapted)["assignments"], [])

    def test_denied_context_supporter_is_not_silently_removed(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        self.inputs["common"]["sources"][1]["rights"]["llm"] = False
        result = self.build(adapted=adapted)
        self.assertEqual({a["source_id"] for a in result["assignments"]}, {"s2", "s3"})

    def test_future_sources_and_half_open_end_never_gain_current_assignments(self):
        for change in ("event", "available", "end"):
            inputs = deepcopy(self.inputs)
            adapted = semantic_admission.adapt(inputs, self.selected, NOW)
            for source in inputs["common"]["sources"]:
                if change == "event": source["event_at"] = "2026-09-26T12:01:00Z"
                elif change == "available": source["available_at"] = "2026-09-26T12:01:00Z"
                else: source["event_at"] = CUTOFF
            with self.subTest(change=change): self.assertEqual(self.build(inputs=inputs, adapted=adapted)["assignments"], [])

    def test_native_cohort_and_exact_unicode_are_not_translated_or_pooled(self):
        patterns = []
        for language in ("yue", "zh-Hant", "zh-Hans", "yue-en"):
            inputs = fixture(language=language); entries = selected([item(inputs, ["s0"])])
            r = self.build(inputs=inputs, entries=entries)
            topic = next(a for a in r["assignments"] if a["dimension"] == "topic")
            patterns.append(topic["pattern_id"])
            self.assertEqual(topic["native_cohort"]["language"], language)
            self.assertEqual(topic["original_spans"][0]["text"], inputs["facts"]["s0"]["text"])
        self.assertEqual(len(set(patterns)), 4)
        self.selected[0]["result"]["items"][0]["language"] = "en"
        with self.assertRaises(ValueError): self.build()

    def test_conflicting_stance_abstains_narrative_but_preserves_agreed_topic(self):
        entries = selected([item(self.inputs, ["s0"]), item(self.inputs, ["s0"], stance="opposes")])
        forward = self.build(entries=entries)
        entries[0]["result"]["items"].reverse()
        reverse = self.build(entries=entries)
        self.assertEqual(forward["assignments"], reverse["assignments"])
        self.assertEqual([a["dimension"] for a in forward["assignments"]], ["topic"])
        abstain = next(a for a in forward["abstentions"] if a["source_id"] == "s0" and a["dimension"] == "narrative")
        self.assertIn("conflicting_reviewed_assignments", abstain["reasons"])

    def test_conflicting_concepts_and_canonical_aliases_never_first_win(self):
        self.inputs["common"]["sources"][0]["canonical_id"] = "same"
        self.inputs["common"]["sources"][1]["canonical_id"] = "same"
        entries = selected([item(self.inputs, ["s0"]), item(self.inputs, ["s1"], concept="另一件事")])
        self.assertEqual(self.build(entries=entries)["assignments"], [])
        entries[0]["result"]["items"][1]["concept"] = "練琴"
        result = self.build(entries=entries)
        self.assertEqual(len(result["assignments"]), 2)
        self.assertEqual(result["assignments"][0]["evidence_refs"], ["s0", "s1"])

    def test_unknown_stance_abstains_and_describes_remains_distinct(self):
        entries = selected([item(self.inputs, ["s0"], stance="unclear")])
        self.assertEqual([a["dimension"] for a in self.build(entries=entries)["assignments"]], ["topic"])
        entries[0]["result"]["items"].append(item(self.inputs, ["s0"], stance="supports"))
        self.assertEqual([a["dimension"] for a in self.build(entries=entries)["assignments"]], ["topic"])
        entries = selected([item(self.inputs, ["s0"], stance="describes"), item(self.inputs, ["s1"], stance="supports")])
        self.assertEqual({a["stance"] for a in self.build(entries=entries)["assignments"] if a["dimension"] == "narrative"}, {"describes", "supports"})

    def test_precomputed_candidates_must_match_actual_selected_model_outputs(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        for field, value in (("model_id", "forged"), ("qualification", "unqualified"), ("claim", "changed")):
            altered = deepcopy(adapted); altered["candidates"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "binding_changed"):
                self.build(adapted=altered)
        altered = deepcopy(adapted); altered["candidates"] = altered["candidates"][:1]
        with self.assertRaisesRegex(ValueError, "binding_changed"): self.build(adapted=altered)

    def test_tampered_native_span_with_precomputed_adaptation_abstains(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        self.inputs["facts"]["s0"]["text"] = "改咗原文"
        self.assertEqual({a["source_id"] for a in self.build(adapted=adapted)["assignments"]}, {"s2", "s3"})

    def test_bounded_inputs_invalid_review_boolean_and_future_cutoff_fail_closed(self):
        with self.assertRaises(ValueError): self.build(entries=self.selected * 3)
        entries = deepcopy(self.selected); entries[0]["qualified"] = "true"
        with self.assertRaises(ValueError): self.build(entries=entries)
        entries = deepcopy(self.selected); entries[0]["result"]["items"] *= 2
        with self.assertRaises(ValueError): self.build(entries=entries)
        inputs = deepcopy(self.inputs); inputs["common"]["sources"] *= 201
        with self.assertRaises(ValueError): self.build(inputs=inputs)
        with self.assertRaises(ValueError): S.build_assignments(self.inputs, self.selected, now="2026-09-26T11:00:00Z")

    def test_inputs_and_optional_adaptation_not_mutated_and_output_is_serializable(self):
        adapted = semantic_admission.adapt(self.inputs, self.selected, NOW)
        before = deepcopy((self.inputs, self.selected, adapted))
        a = self.build(adapted=adapted); b = self.build()
        self.assertEqual(a, b)
        self.assertEqual((self.inputs, self.selected, adapted), before)
        json.dumps(a, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__": unittest.main()
