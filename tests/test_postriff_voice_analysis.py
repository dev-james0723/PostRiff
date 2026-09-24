import unittest

from postriff_alpha.domain import AlphaError, initial_state
from postriff_phase2 import voice_analysis, voice_sources
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands


def add_sample(state, text, source_id_hint, *, platform="Instagram", language="English"):
    result = voice_sources.apply_action(
        state,
        "voice_samples_import",
        {"format": "json", "records": [{"externalId": source_id_hint, "platform": platform, "language": language, "text": text}]},
        "owner-one",
        100,
    )
    source_id = result["imported"][0]
    voice_sources.apply_action(state, "voice_sample_select", {"sourceId": source_id, "selected": True}, "owner-one", 101)
    voice_sources.apply_action(
        state,
        "voice_sample_grant",
        {"sourceId": source_id, "grants": [{"purpose": "analysis", "route": "local-rules"}], "confirmed": True},
        "owner-one",
        102,
    )
    return source_id


class VoiceAnalysisTests(unittest.TestCase):
    def test_one_sample_builds_a_provisional_profile_with_limited_evidence(self):
        state = initial_state("workspace-one")
        source_id = add_sample(state, "A quiet opening.\n\nA short close.", "one")

        proposal = voice_analysis.build_proposal(state, [source_id], "owner-one", 200)

        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["evidenceSourceIds"], [source_id])
        self.assertTrue(proposal["dimensions"])
        self.assertTrue(all(item['evidenceLevel'] in ('limited', 'insufficient') for item in proposal['dimensions']))
        self.assertTrue(all(item['observation'] not in proposal['observations'] for item in proposal['dimensions'] if item['evidenceLevel'] == 'insufficient'))
        self.assertIn("provisional", " ".join(proposal["unknowns"]).lower())

    def test_conflicting_hashtag_evidence_is_visible_instead_of_becoming_a_rule(self):
        state = initial_state("workspace-one")
        with_tags = add_sample(state, "Useful update. #studio #music", "one")
        without_tags = add_sample(state, "Useful update without tags.", "two")

        proposal = voice_analysis.build_proposal(state, [with_tags, without_tags], "owner-one", 200)
        hashtags = next(item for item in proposal["dimensions"] if item["id"] == "hashtags")

        self.assertEqual(hashtags["evidenceLevel"], "conflicting")
        self.assertEqual(set(hashtags["support"] + hashtags["counterEvidence"]), {with_tags, without_tags})
        self.assertNotIn(hashtags["observation"], proposal["observations"])

    def test_validator_rejects_foreign_citations_and_quarantines_sensitive_inference(self):
        state = initial_state("workspace-one")
        source_id = add_sample(state, "Warm hello!", "one")
        projection = voice_sources.project(state, [source_id], "analysis", "local-rules")

        with self.assertRaisesRegex(AlphaError, "evidence"):
            voice_analysis.validate_proposal(
                {"dimensions": [{"id": "warmth", "observation": "Warm greeting", "support": ["foreign"], "counterEvidence": []}]},
                projection,
            )

        validated = voice_analysis.validate_proposal(
            {"dimensions": [
                {"id": "political_belief", "observation": "Invented belief", "support": [source_id], "counterEvidence": []},
                {"id": "openings", "observation": "Starts with a greeting", "support": [source_id], "counterEvidence": []},
            ]},
            projection,
        )
        self.assertEqual([item["id"] for item in validated["dimensions"]], ["openings"])
        self.assertEqual(validated["quarantined"][0]["reason"], "unsupported_dimension")

    def test_hosted_analysis_saves_a_proposal_without_activating_it(self):
        state = initial_phase2_state("workspace-one", "owner-one", "Owner", "studio", 100)
        source_id = add_sample(state, "First line.\nSecond line.", "one")
        active_before = state["speaker"]["activeRevision"]

        HostedPhase2Commands(clock=lambda: 200)(state, "owner-one", "voice_profile_analyze", {"sourceIds": [source_id], "route": "local-rules"})

        self.assertEqual(state["speaker"]["activeRevision"], active_before)
        self.assertEqual(state["speaker"]["provisional"]["status"], "proposed")
        self.assertEqual(state["speaker"]["provisional"]["analysisRoute"], "local-rules")

    def test_revoked_evidence_blocks_pending_approval_and_restoring_an_old_profile(self):
        commands = HostedPhase2Commands(clock=lambda: 200)
        state = initial_phase2_state("workspace-one", "owner-one", "Owner", "studio", 100)
        source_id = add_sample(state, "Evidence-bound voice.", "one")
        commands(state, "owner-one", "voice_profile_analyze", {"sourceIds": [source_id], "route": "local-rules"})
        voice_sources.apply_action(state, "voice_sample_revoke", {"sourceId": source_id, "confirmed": True}, "owner-one", 201)
        with self.assertRaisesRegex(AlphaError, "evidence"):
            commands(state, "owner-one", "profile_decide", {"decision": "approve"})

        state = initial_phase2_state("workspace-two", "owner-one", "Owner", "studio", 100)
        source_id = add_sample(state, "Approved evidence-bound voice.", "two")
        commands(state, "owner-one", "voice_profile_analyze", {"sourceIds": [source_id], "route": "local-rules"})
        commands(state, "owner-one", "profile_decide", {"decision": "approve"})
        voice_sources.apply_action(state, "voice_sample_revoke", {"sourceId": source_id, "confirmed": True}, "owner-one", 202)
        with self.assertRaisesRegex(AlphaError, "evidence"):
            commands(state, "owner-one", "you_restore_voice", {"revision": 1})


if __name__ == "__main__":
    unittest.main()
