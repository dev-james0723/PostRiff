"""Writing like the author by default, without changing what consent means.

A writing grant may cover every model Rafii's managed writer offers (one class route) instead of one model id; each
draft still records the exact route it used and the sample revisions it read. A turn that asks to write like the author
when no chosen sample may be used by that writer gets its draft in a neutral voice with a note, for every caller."""
import unittest

from postriff_alpha.domain import AlphaError
from postriff_phase2 import voice_sources
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.ideas import VOICE_FALLBACK_NOTE, IdeasService
from postriff_phase2.model_runtime import ServerModelRuntime

SOL = "cloud:vercel-ai-gateway:openai/gpt-6-sol"
SONNET = "cloud:vercel-ai-gateway:anthropic/claude-sonnet-5"


def workspace(grants):
    state = {"sources": [], "speaker": {"revisions": []}, "variants": []}
    imported = voice_sources.apply_action(state, "voice_samples_import", {"format": "pasted", "text": "Short openings. No hashtags."}, "owner", 100)["imported"][0]
    voice_sources.apply_action(state, "voice_sample_select", {"sourceId": imported, "selected": True}, "owner", 101)
    if grants:
        voice_sources.apply_action(state, "voice_sample_grant", {"sourceId": imported, "grants": grants, "confirmed": True}, "owner", 102)
    return state, imported


class ClassGrantTest(unittest.TestCase):
    def test_one_grant_covers_every_managed_writer_model_and_nothing_else(self):
        state, sample = workspace([{"purpose": "generation", "route": voice_sources.MANAGED_WRITER_ROUTE}])
        for route in (SOL, SONNET):
            self.assertEqual([s["id"] for s in voice_sources.project(state, [sample], "generation", route)["samples"]], [sample], route)
        for route in ("cloud:claude-code:sonnet", "cloud:codex:gpt-6", "local-cli", "cloud:vercel-ai-gateway:"):
            self.assertEqual(voice_sources.project(state, [sample], "generation", route)["excluded"][0]["reason"], "route_not_granted", route)
        # Writing only: the class never grants analysis.
        self.assertEqual(voice_sources.project(state, [sample], "analysis", SOL)["excluded"][0]["reason"], "purpose_not_granted")

    def test_the_draft_binds_the_exact_route_and_later_checks_still_pass(self):
        state, sample = workspace([{"purpose": "generation", "route": voice_sources.MANAGED_WRITER_ROUTE}])
        retrieved = voice_sources.retrieve(state, [sample], "generation", SOL)
        self.assertEqual(retrieved["route"], SOL)
        voice_sources.validate_bindings(state, {"mode": "personalized", "route": SOL, "bindings": retrieved["bindings"]})
        # Withdrawing the class grant withdraws it for every model at once.
        voice_sources.apply_action(state, "voice_sample_grant", {"sourceId": sample, "grants": [{"purpose": "analysis", "route": "local-rules"}], "confirmed": True}, "owner", 103)
        with self.assertRaises(AlphaError):
            voice_sources.validate_bindings(state, {"mode": "personalized", "route": SOL, "bindings": retrieved["bindings"]})

    def test_the_class_is_never_an_analysis_grant_nor_a_route_to_draft_with(self):
        state, sample = workspace(None)
        with self.assertRaises(AlphaError):
            voice_sources.apply_action(state, "voice_sample_grant", {"sourceId": sample, "grants": [{"purpose": "analysis", "route": voice_sources.MANAGED_WRITER_ROUTE}], "confirmed": True}, "owner", 102)
        with self.assertRaises(AlphaError):
            voice_sources.project(state, [sample], "generation", voice_sources.MANAGED_WRITER_ROUTE)

    def test_exact_grants_keep_their_meaning(self):
        state, sample = workspace([{"purpose": "generation", "route": SOL}])
        self.assertTrue(voice_sources.project(state, [sample], "generation", SOL)["samples"])
        self.assertEqual(voice_sources.project(state, [sample], "generation", SONNET)["excluded"][0]["reason"], "route_not_granted")

    def test_the_catalogue_names_the_class_only_for_managed_writer_models(self):
        fixture = FixtureAgentRuntime()
        managed = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])
        ideas = IdeasService(None, None, runtime=fixture, runtimes=[fixture, managed], researcher=False)
        models = {m["id"]: m for m in ideas.model_catalog()["models"]}
        self.assertEqual((models["openai/gpt-6-sol"]["voiceRoute"], models["openai/gpt-6-sol"]["voiceRouteClass"]), (SOL, voice_sources.MANAGED_WRITER_ROUTE))
        self.assertEqual((models["deterministic-preview"]["voiceRoute"], models["deterministic-preview"]["voiceRouteClass"]), ("local-cli", None))


class NeutralFallbackTest(unittest.TestCase):
    def project(self, state, payload):
        managed = ServerModelRuntime("key", model="openai/gpt-6-sol", models=["openai/gpt-6-sol"])
        fixture = FixtureAgentRuntime()
        ideas = IdeasService(None, None, runtime=fixture, runtimes=[fixture, managed], researcher=False)
        return ideas._project(state, {"voiceMode": "personalized", **payload}, managed, "openai/gpt-6-sol", "quick",
                              [{"platform": "LinkedIn", "language": "English"}], "A note on practice", {"intent": "post", "warnings": []})

    def test_an_interactive_turn_without_an_allowed_sample_drafts_neutral_and_says_so(self):
        for grants in (None, [{"purpose": "generation", "route": "cloud:claude-code:sonnet"}]):
            state, sample = workspace(grants)
            for payload in ({}, {"voiceSourceIds": [sample]}, {"voiceSourceIds": ["missing-sample"]}):
                projected = self.project(state, payload)
                self.assertEqual(projected["voiceContext"]["mode"], "neutral", (grants, payload))
                self.assertIn(VOICE_FALLBACK_NOTE, projected["reminders"])
                self.assertEqual(projected["request"]["styleDirectives"], {})

    def test_an_allowed_sample_is_used_and_recorded_with_the_exact_route(self):
        state, sample = workspace([{"purpose": "generation", "route": voice_sources.MANAGED_WRITER_ROUTE}])
        projected = self.project(state, {})
        self.assertEqual(projected["voiceContext"]["mode"], "personalized")
        self.assertEqual(projected["voiceContext"]["route"], SOL)
        self.assertEqual([b["id"] for b in projected["voiceContext"]["bindings"]], [sample])
        self.assertNotIn(VOICE_FALLBACK_NOTE, projected["reminders"])

    def test_a_malformed_request_is_still_refused(self):
        state, _ = workspace(None)
        with self.assertRaises(AlphaError) as caught:
            self.project(state, {"voiceSourceIds": [1, 2]})
        self.assertEqual(caught.exception.status, 400)


if __name__ == "__main__":
    unittest.main()
