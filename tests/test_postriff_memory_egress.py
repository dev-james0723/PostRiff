"""Memory files and cloud models: consent, privacy filtering, the owner-only action, and the Memory page summary."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import memory  # noqa: E402
from postriff_phase2.permissions import classify  # noqa: E402
from postriff_phase2.privacy import notice  # noqa: E402


def workspace():
    return {
        "speaker": {"label": "Kiln & Quiet", "activeRevision": 2, "revisions": [{"revision": 2, "approvedAt": "2026-09-01T00:00:00Z", "reason": "approved", "profile": {"tone": "plain, dry", "observations": ["Short sentences."]}}]},
        "brandHub": {"subject": "Ceramics"},
        "profile": {"fields": [
            {"section": "boundaries", "key": "students", "label": "Students", "value": "Never name a student", "privacy": "workspace_only"},
            {"section": "boundaries", "key": "public", "label": "Pricing", "value": "No prices in posts", "privacy": "public"},
            {"section": "boundaries", "key": "health", "label": "Health", "value": "SECRET-HEALTH-DETAIL", "privacy": "local_only"},
            {"section": "boundaries", "key": "family", "label": "Family", "value": "SECRET-FAMILY-DETAIL", "privacy": "private"},
            {"section": "boundaries", "key": "unlabelled", "label": "Past job", "value": "SECRET-UNLABELLED"},
        ]},
    }


class Projection(unittest.TestCase):
    def test_voice_file_reports_when_no_profile_exists(self):
        state = workspace()
        state['speaker']['activeRevision'] = None
        voice = next(file for file in memory.render_files(state) if file['name'] == 'VOICE.md')
        self.assertEqual(voice['source'], 'No active voice profile yet')
        self.assertIn('No active voice profile yet', voice['body'])

    def test_local_routes_read_every_prompt_file_unchanged(self):
        state = workspace()
        shared = memory.projection(state, "local")
        self.assertEqual(shared["files"], memory.prompt_fragments(state))
        self.assertTrue(shared["shared"])
        self.assertIn("SECRET-HEALTH-DETAIL", str(shared["files"]), "a local route keeps today's behaviour")

    def test_a_cloud_route_reads_nothing_until_the_workspace_allows_it(self):
        shared = memory.projection(workspace(), "cloud")
        # `learned` records what the run was given from learned preferences: nothing, and nothing to omit, here.
        self.assertEqual(shared, {"files": [], "shared": False, "withheldBoundaries": 0, "learned": {"styleRevision": 0, "used": [], "statements": [], "omitted": []}})

    def test_with_consent_private_local_only_and_unlabelled_boundaries_never_leave(self):
        state = workspace()
        memory.apply_memory_action(state, memory.EGRESS_ACTION, {"cloud": True, "confirmed": True}, "owner-1", 1789600000.0)
        shared = memory.projection(state, "cloud")
        self.assertTrue(shared["shared"])
        self.assertEqual([f["name"] for f in shared["files"]], list(memory.PROMPT_FILES))
        text = str(shared["files"])
        for secret in ("SECRET-HEALTH-DETAIL", "SECRET-FAMILY-DETAIL", "SECRET-UNLABELLED"):
            self.assertNotIn(secret, text)
        self.assertIn("Never name a student", text)
        self.assertIn("No prices in posts", text)
        self.assertEqual(shared["withheldBoundaries"], 3)
        self.assertIn("3 more boundaries are private or local-only", text)
        self.assertIn("Tone: plain, dry", text)

    def test_withdrawing_consent_stops_sharing(self):
        state = workspace()
        memory.apply_memory_action(state, memory.EGRESS_ACTION, {"cloud": True, "confirmed": True}, "owner-1", 1.0)
        memory.apply_memory_action(state, memory.EGRESS_ACTION, {"cloud": False, "confirmed": True}, "owner-1", 2.0)
        self.assertEqual(memory.projection(state, "cloud")["files"], [])


class Action(unittest.TestCase):
    def test_requires_an_explicit_boolean_and_confirmation(self):
        for payload in ({"cloud": True}, {"cloud": "yes", "confirmed": True}, {"confirmed": True}):
            with self.assertRaises(AlphaError):
                memory.apply_memory_action(workspace(), memory.EGRESS_ACTION, payload, "owner-1", 1.0)

    def test_other_actions_pass_through_and_only_owners_may_decide(self):
        self.assertFalse(memory.apply_memory_action(workspace(), "source_policy", {}, "owner-1", 1.0))
        self.assertEqual(classify(memory.EGRESS_ACTION), "owner")

    def test_decision_is_recorded_for_the_memory_page(self):
        state = workspace()
        self.assertEqual(memory.egress_summary(state)["cloud"], False)
        memory.apply_memory_action(state, memory.EGRESS_ACTION, {"cloud": True, "confirmed": True}, "owner-1", 5.0)
        summary = memory.egress_summary(state)
        self.assertEqual((summary["cloud"], summary["decidedBy"], summary["decidedAt"], summary["withheldBoundaries"]), (True, "owner-1", 5.0, 3))
        self.assertEqual(summary["shareablePrivacy"], ["public", "workspace_only"])


class Disclosure(unittest.TestCase):
    def test_agent_rules_and_privacy_notice_state_the_consent(self):
        agent = next(f["body"] for f in memory.render_files(workspace()) if f["name"] == "AGENT.md")
        self.assertIn("only if you allow it", agent)
        self.assertIn("only if a workspace owner allows it", notice()["aiProcessing"])


if __name__ == "__main__":
    unittest.main()
