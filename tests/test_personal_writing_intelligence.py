"""PWI integration regressions; all samples are synthetic, no provider quality claim."""
import json
import os
import tempfile
import unittest
from unittest import mock

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from postriff_phase2 import creation_capabilities as capabilities, memory, skills, suggestions
from postriff_phase2.coworker import flags
from postriff_phase2.learning_chat import instruction_to_proposal

NOW = 1_900_000_000.0
ALL = {"RAFII_CREATION_PROJECTION_ENABLED": "", "RAFII_CREATION_ALL_PLATFORMS_ENABLED": "1"}
OFF = {"RAFII_CREATION_PROJECTION_ENABLED": "", "RAFII_CREATION_ALL_PLATFORMS_ENABLED": ""}


def workspace():
    return {
        "workspace": {"id": "synthetic-pwi"},
        "speaker": {"label": "Synthetic studio", "activeRevision": 1,
                    "revisions": [{"revision": 1, "profile": {"tone": "plain", "observations": ["Use specific wording."]}}]},
        "brandHub": {"audience": "Local readers"}, "sources": [], "preferences": [],
        "brief": {"revision": 3, "idea": "A community workshop"},
        "variants": [{"id": "existing", "channelId": "covered", "briefRevision": 3}],
        "phase2": {"channels": [], "jobs": [], "assets": []},
    }


def channel(platform):
    return {"id": "channel-" + skills.CHANNEL_SKILLS[platform], "platform": platform,
            "account": "Synthetic account", "identityVerified": True, "capabilityVerified": True,
            "revoked": False, "expiresAt": NOW + 86400}


class PlatformSuggestionIntegration(unittest.TestCase):
    def setUp(self):
        self.previous_flags = flags._values
        flags.attach(None)
        capabilities._CACHE.clear()
        self.state = workspace()
        self.state["phase2"]["channels"] = [channel(p) for p in skills.CHANNEL_SKILLS]

    def tearDown(self):
        flags.attach(self.previous_flags)
        capabilities._CACHE.clear()

    def active(self):
        return [item for item in suggestions.refresh(self.state, NOW)
                if item["kind"] == "missing_variant" and item["status"] == "open"]

    def test_all_33_supported_platforms_get_actionable_suggestions(self):
        with mock.patch.dict(os.environ, ALL):
            items = self.active()
            expected = {c["id"] for c in self.state["phase2"]["channels"]}
            self.assertEqual({i["evidence"][0]["id"] for i in items}, expected)
            self.assertEqual(len(items), 33)
            for item in items:
                result = suggestions.apply_action(self.state, "raffi_suggestion_accept",
                    {"suggestionId": item["id"]}, "synthetic-owner", NOW)
                self.assertEqual(result["actionRef"]["targetId"], item["evidence"][0]["id"])
                self.assertEqual(result["actionRef"]["type"], "draft_intent")
                self.assertEqual(result["actionRef"]["authority"], "open_for_review")
            self.assertEqual(self.state["phase2"]["jobs"], [])

    def test_rollout_and_missing_skill_limit_suggestions_to_available_drafting(self):
        with mock.patch.dict(os.environ, OFF):
            expected = {channel(p)["id"] for p in capabilities.ORIGINAL_PLATFORMS}
            self.assertEqual({i["evidence"][0]["id"] for i in self.active()}, expected)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {**ALL, "POSTRIFF_SKILLS_DIR": tmp}):
            capabilities._CACHE.clear()
            self.assertEqual(self.active(), [], "missing skills cannot be advertised as available personal writing")

    def test_disabled_platform_stales_then_reopens_without_duplicate_and_cannot_accept_stale(self):
        target = channel("Facebook")["id"]
        with mock.patch.dict(os.environ, ALL):
            item = next(i for i in self.active() if i["evidence"][0]["id"] == target)
            original_id = item["id"]
        with mock.patch.dict(os.environ, OFF):
            self.active()
            self.assertEqual(item["status"], "stale")
            with self.assertRaises(AlphaError):
                suggestions.apply_action(self.state, "raffi_suggestion_accept", {"suggestionId": original_id}, "owner", NOW)
        with mock.patch.dict(os.environ, ALL):
            restored = [i for i in self.active() if i["evidence"][0]["id"] == target]
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0]["id"], original_id)
            self.assertNotIn("staleAt", restored[0])

    def test_rejected_draft_does_not_suppress_a_missing_variant(self):
        target = channel("LinkedIn")["id"]
        self.state["variants"].append({"id": "rejected", "channelId": target, "briefRevision": 3, "rejected": True})
        with mock.patch.dict(os.environ, OFF):
            self.assertIn(target, {i["evidence"][0]["id"] for i in self.active()})

    def test_dismissal_stays_dismissed_after_capability_changes(self):
        with mock.patch.dict(os.environ, ALL):
            item = next(i for i in self.active() if i["evidence"][0]["id"] == channel("Facebook")["id"])
            suggestions.apply_action(self.state, "raffi_suggestion_dismiss", {"suggestionId": item["id"]}, "owner", NOW)
        with mock.patch.dict(os.environ, OFF):
            self.active()
        with mock.patch.dict(os.environ, ALL):
            self.assertNotIn(item["id"], {i["id"] for i in self.active()})
            self.assertEqual(item["status"], "dismissed")


class ScopedLearningIntegration(unittest.TestCase):
    def test_contextual_x_preference_is_scoped_and_reused_after_state_reload(self):
        for sentence in ("Remember: no hashtags on X", "以後喺 X 唔好用 hashtags", "Remember: no hashtags on Twitter", "Remember: no hashtags on x", "以後喺 x 唔好用 hashtags"):
            with self.subTest(sentence=sentence):
                state = workspace()
                proposal = instruction_to_proposal(sentence)
                self.assertEqual(proposal["scope"]["platform"], "X")
                accepted = learning.remember(state, proposal, actor="synthetic-owner", now=NOW)
                reloaded = json.loads(json.dumps(state))
                current, receipt = memory.prepare_writer(reloaded, "local", "local-cli", destinations=[{"platform": "X", "language": "en"}])
                self.assertEqual(current["learned"]["used"], [accepted["id"]])
                self.assertIn("No hashtags.", str(current["files"]))
                unrelated, _ = memory.prepare_writer(reloaded, "local", "local-cli", destinations=[{"platform": "LinkedIn", "language": "en"}])
                self.assertNotIn("No hashtags.", str(unrelated["files"]))
                self.assertEqual(unrelated["learned"]["used"], [])
                neutral, _ = memory.prepare_writer(reloaded, "local", "local-cli", destinations=[{"platform": "X", "language": "en"}], voice_mode="neutral")
                self.assertNotIn("No hashtags.", str(neutral["files"]))
                learning.retire(reloaded, accepted["id"], NOW + 1)
                with self.assertRaises(AlphaError):
                    memory.validate_receipt(reloaded, receipt)
                after, _ = memory.prepare_writer(reloaded, "local", "local-cli", destinations=[{"platform": "X", "language": "en"}])
                self.assertEqual(after["learned"]["used"], [])

    def test_ordinary_x_words_do_not_invent_platform_scope(self):
        for phrase in ("X-ray", "SpaceX", "Series X", "Malcolm X", "10x", "solving for x", "x + y", "a variable x"):
            with self.subTest(phrase=phrase):
                proposal = instruction_to_proposal(f"Remember no emoji when describing {phrase}")
                self.assertIsNone(proposal["scope"]["platform"])

    def test_multiple_platforms_never_silently_choose_one_or_all(self):
        for sentence in ("Remember no hashtags on X and LinkedIn", "以後 Instagram 同 Threads 唔好用 emoji", "Remember no hashtags on x and LinkedIn"):
            with self.subTest(sentence=sentence), self.assertRaisesRegex(ValueError, "one platform"):
                instruction_to_proposal(sentence)

    def test_specific_chinese_script_scope_is_not_broadened(self):
        for phrase, expected in (("Traditional Chinese", "zh-Hant"), ("繁體中文", "zh-Hant"), ("Simplified Chinese", "zh-Hans"), ("简体中文", "zh-Hans"), ("Chinese", "zh")):
            with self.subTest(phrase=phrase):
                self.assertEqual(instruction_to_proposal(f"Remember no hashtags in {phrase} posts")["scope"]["language"], expected)

    def test_nonquestion_opening_instruction_keeps_its_meaning(self):
        for sentence in ("Remember: don't use a promotional opening", "Remember: don’t use a promotional opening", "以後唔好用宣傳式開頭"):
            with self.subTest(sentence=sentence):
                proposal = instruction_to_proposal(sentence)
                self.assertEqual(proposal["statement"], sentence)
                self.assertEqual(proposal["polarity"], "avoid")
                self.assertEqual(proposal["ruleKey"], "opening.style")
                self.assertEqual(proposal["params"], {})

    def test_pending_candidate_is_not_a_durable_preference(self):
        state = workspace()
        pending = learning.propose(state, instruction_to_proposal("Remember no emoji on X"), NOW)
        self.assertEqual(pending["status"], "proposed")
        reloaded = json.loads(json.dumps(state))
        shared, _ = memory.prepare_writer(reloaded, "local", "local-cli", destinations=[{"platform": "X", "language": "en"}])
        self.assertEqual(shared["learned"]["used"], [])
        self.assertNotIn("No emoji.", str(shared["files"]))


if __name__ == "__main__":
    unittest.main()
