"""Offline regressions for audited personalization boundaries; no provider calls."""
import copy
import json
import unittest
from datetime import datetime, timezone

from postriff_alpha import learning
from postriff_alpha.domain import initial_state
from postriff_phase2 import learning_extract, learning_model, learning_signals, memory, voice_sources
from postriff_phase2.model_runtime import ServerModelRuntime

NOW = 1_800_000_000.0
DESTINATION = [{"platform": "LinkedIn", "language": "en"}]


def workspace():
    state = initial_state("p0-regression-only")
    state["memoryEgress"] = {"cloud": True}
    state["speaker"] = {"activeRevision": None, "revisions": []}
    state["learning"] = learning.initial("test")
    return state


def remember(state, **scope):
    return learning.remember(state, {"ruleKey": "hashtags.use", "polarity": "avoid", "statement": "No hashtags.",
                                     "scope": {"platform": "LinkedIn", "language": "en", **scope}, "source": "chat"}, now=NOW)


def profile(state, **extra):
    state["speaker"] = {"activeRevision": 1, "revisions": [{"revision": 1, "profile": {
        "tone": "PRIVATE_TONE_SENTINEL", "observations": ["Private style observation."], **extra}}]}
    return state["speaker"]["revisions"][0]


def edit_event(index, campaign="campaign-a", platform="LinkedIn", content="promotion"):
    return {"id": f"e{index}", "kind": "draft.edited", "at": NOW, "subject": {"variantId": f"v{index}", "fromRevision": 1, "toRevision": 2},
            "scope": {"platform": platform, "language": "en", "contentTypeId": content, "campaignId": campaign},
            "features": {"before": {"hashtags": 1}, "after": {"hashtags": 0}}}


class MemoryP0(unittest.TestCase):
    def test_approved_preference_reaches_system_without_voice_and_after_voice_stales(self):
        state = workspace()
        item = remember(state)
        for stale in (False, True):
            with self.subTest(stale=stale):
                if stale:
                    profile(state)["stale"] = True
                shared = memory.projection(state, "cloud", DESTINATION)
                self.assertEqual(shared["learned"]["used"], [item["id"]])
                prompt = ServerModelRuntime._system_prompt({"memory": shared["files"]})
                self.assertIn("No hashtags.", prompt)
                self.assertNotIn("PRIVATE_TONE_SENTINEL", prompt)

    def test_tone_shares_consent_and_currentness_of_voice_file(self):
        for mutation in ("cloud_off", "stale", "expired", "invalid_expiry"):
            with self.subTest(mutation=mutation):
                state = workspace()
                revision = profile(state)
                if mutation == "cloud_off":
                    state["memoryEgress"]["cloud"] = False
                elif mutation == "stale":
                    revision["stale"] = True
                else:
                    revision["profile"]["expiresAt"] = "2000-01-01T00:00:00Z" if mutation == "expired" else "invalid"
                shared = memory.projection(state, "cloud", DESTINATION)
                self.assertEqual(shared["tone"], "warm")
                self.assertNotIn("PRIVATE_TONE_SENTINEL", json.dumps(shared))
        state = workspace()
        profile(state)
        self.assertEqual(memory.projection(state, "cloud", DESTINATION)["tone"], "PRIVATE_TONE_SENTINEL")

    def test_revised_source_cannot_revive_approved_old_voice_even_after_regrant(self):
        state = workspace()
        source = {"id": "voice-1", "kind": "voice_sample", "active": True, "selected": True, "revision": 2,
                  "contentHash": "new", "text": "New sample.", "purposeGrants": ["generation"],
                  "useGrants": [{"purpose": "generation", "route": "cloud:vercel-ai-gateway:openai/gpt-4.1-mini"}]}
        state["sources"] = [source]
        profile(state, evidenceSourceIds=["voice-1"], sourceBindings=[{"id": "voice-1", "revision": 1, "contentHash": "old"}])
        shared = memory.projection(state, "cloud", DESTINATION, voice_route="cloud:vercel-ai-gateway:openai/gpt-4.1-mini")
        self.assertEqual(shared["tone"], "warm")
        self.assertNotIn("Private style observation.", str(shared["files"]))
        self.assertNotIn("stale", state["speaker"]["revisions"][0], "projection must not mutate persisted state")

    def test_writer_projection_uses_filtered_tone_in_final_message_builder(self):
        from postriff_phase2.ideas import IdeasService
        runtime = ServerModelRuntime("offline-test-no-credential", model="openai/gpt-4.1-mini",
                                     transport=lambda *a, **k: self.fail("No dispatch in regression test"))
        service = IdeasService(None, None, runtime=runtime, runtimes=[runtime], researcher=False)
        for denied in ("cloud_off", "stale"):
            state = workspace()
            revision = profile(state)
            if denied == "cloud_off":
                state["memoryEgress"]["cloud"] = False
            else:
                revision["stale"] = True
            projected = service._project(state, {"sourceIds": [], "voiceMode": "neutral"}, runtime, runtime.model,
                                         "quick", DESTINATION, "Describe a five-minute pause.", {"intent": "draft"})
            messages = runtime._messages(projected["request"], "quick")
            self.assertNotIn("PRIVATE_TONE_SENTINEL", json.dumps(messages))
            self.assertEqual(projected["request"]["tone"], "warm")

    def test_cloud_off_omits_preference_body_and_binding(self):
        state = workspace()
        item = remember(state)
        state["memoryEgress"]["cloud"] = False
        shared = memory.projection(state, "cloud", DESTINATION)
        self.assertEqual(shared["files"], [])
        self.assertEqual(shared["learned"]["used"], [])
        self.assertIn(item["id"], shared["learned"]["omitted"])

    def test_scope_survives_approval_and_only_enters_matching_projection(self):
        state = workspace()
        remember(state, contentTypeId="promotion", campaignId="campaign-a")
        for platform, content, campaign, expected in (
            ("LinkedIn", "promotion", "campaign-a", True),
            ("LinkedIn", "promotion", "campaign-b", False),
            ("Threads", "promotion", "campaign-a", False),
            ("LinkedIn", "reflection", "campaign-a", False),
            ("LinkedIn", "promotion", None, False),
        ):
            shared = memory.projection(state, "cloud", [{"platform": platform, "language": "en"}], content, campaign_id=campaign)
            self.assertEqual("No hashtags." in ServerModelRuntime._system_prompt({"memory": shared["files"]}), expected)
            self.assertEqual(bool(shared["learned"]["used"]), expected)


class LearningScopeP0(unittest.TestCase):
    def test_extractor_keeps_campaign_and_content_type_and_does_not_pool_campaigns(self):
        events = [edit_event(i) for i in range(3)]
        proposals = learning_extract.consolidate(*learning_extract.observations(events), workspace(), NOW)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["scope"], {"platform": "LinkedIn", "language": "en", "contentTypeId": "promotion", "campaignId": "campaign-a"})
        events = [edit_event(0), edit_event(1), edit_event(2, "campaign-b")]
        self.assertEqual(learning_extract.consolidate(*learning_extract.observations(events), workspace(), NOW), [])

    def test_platform_promotion_never_promotes_campaign_or_content_type(self):
        events = [edit_event(i, platform="LinkedIn" if i < 3 else "Threads") for i in range(6)]
        proposal = learning_extract.consolidate(*learning_extract.observations(events), workspace(), NOW)[0]
        self.assertEqual(proposal["scope"], {"platform": None, "language": "en", "contentTypeId": "promotion", "campaignId": "campaign-a"})

    def test_linked_campaign_is_in_actual_edit_signal_and_ambiguous_links_are_not_learned(self):
        before = workspace()
        before["variants"] = [{"id": "v0", "platform": "LinkedIn", "language": "en", "contentTypeId": "promotion", "text": "A thought. #topic", "revision": 1,
                               "revisions": [{"revision": 1, "text": "A thought. #topic", "origin": "ideas-candidate"}]}]
        after = copy.deepcopy(before)
        after["variants"][0].update(text="A thought.", revision=2)
        after["variants"][0]["revisions"].append({"revision": 2, "text": "A thought.", "origin": "author-edit"})
        campaigns = [{"id": "campaign-a", "status": "draft", "items": [{"kind": "draft", "variantId": "v0"}]}]
        after["raffi"] = {"campaignPlanning": {"campaigns": campaigns}}
        event = learning_signals.derive_events(before, after, "owner", NOW)[0]
        self.assertEqual(event["scope"]["campaignId"], "campaign-a")
        campaigns.append({"id": "campaign-b", "status": "draft", "items": [{"kind": "draft", "variantId": "v0"}]})
        ambiguous = learning_signals.derive_events(before, after, "owner", NOW)[0]
        self.assertEqual(learning_extract.observations([ambiguous]), ([], []))

    def test_model_extractor_keeps_scopes_separate_without_calling_model(self):
        state = workspace()
        events = [edit_event(i, campaign="campaign-a" if i < 2 else "campaign-b") for i in range(4)]
        state["variants"] = [{"id": f"v{i}", "sourceIds": [], "revisions": [{"revision": 1, "text": "Before #topic"}, {"revision": 2, "text": "After"}]} for i in range(4)]
        extractor = learning_model.ModelExtractor(lambda *args: self.fail("No model calls"), "unused")
        requests = extractor.requests(state, events)
        self.assertEqual(len(requests), 2)
        self.assertEqual({json.loads(r[3][len("INPUT\n"):])["scope"]["campaignId"] for r in requests}, {"campaign-a", "campaign-b"})
        batch = requests[0][2]
        observations = learning_model.parse_candidates({"candidates": [{"ruleKey": "hashtags.use", "polarity": "avoid", "statement": "No hashtags.",
            "confidence": "high", "evidencePairIds": [p["id"] for p in batch]}]}, batch, "LinkedIn", "en", NOW)
        self.assertEqual({o["scope"]["campaignId"] for o in observations}, {batch[0]["scope"]["campaignId"]})
        self.assertEqual({o["scope"]["contentTypeId"] for o in observations}, {"promotion"})


class GrantExpiryP0(unittest.TestCase):
    def test_route_grants_expire_at_deadline_and_invalid_expiry_fails_closed(self):
        for expiry in ("2000-01-01T00:00:00Z", "not-a-date", "2099-01-01"):
            source = {"useGrants": [{"purpose": "generation", "route": "local-cli", "expiresAt": expiry}]}
            self.assertFalse(voice_sources.route_granted(source, "generation", "local-cli"))
        self.assertFalse(voice_sources.unexpired({"expiresAt": "2026-01-01T00:00:00Z"}, datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_grant_action_preserves_expiry_instead_of_silently_making_it_permanent(self):
        state = workspace()
        source_id = voice_sources.apply_action(state, "voice_samples_import", {"format": "pasted", "text": "A short sample."}, "owner", NOW)["imported"][0]
        granted = voice_sources.apply_action(state, "voice_sample_grant", {"sourceId": source_id, "confirmed": True,
            "grants": [{"purpose": "generation", "route": "local-cli", "expiresAt": "2099-01-01T00:00:00Z"}]}, "owner", NOW)
        self.assertEqual(granted["grants"][0]["expiresAt"], "2099-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
