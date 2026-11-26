"""An approved voice built from imported posts reaches the next personalized writing request (brand intelligence WF-2).

The chain pinned here, without a database: imported posts → measured form → Brand Brain proposal → approved active
revision (stored the way `_voice` stores it) → `memory.prepare_writer` for a personalized request. The approved profile
needs no voice-sample grant (it cites no workspace sources), so a personalized request is not sent back to neutral; its
traits reach VOICE.md and no post wording does. Neutral mode still keeps VOICE.md out.
"""
import copy
import unittest

from postriff_phase2 import memory, voice_corpus
from postriff_phase2.auth import initial_phase2_state

POSTS = [
    {"id": f"p{i}", "provider": "threads", "account_key": "acct-1", "published_at": f"2026-11-{10 + i:02d}T09:00:00+00:00",
     "body": body, "language": "en", "content_type": "post", "voice_scope": "brand", "permalink": f"https://example.test/p{i}"}
    for i, body in enumerate([
        "Saturday open studio is back. Bring a friend and stay for tea after the session.",
        "Small habit that works: end every practice with one piece you already love playing.",
        "New practice room, same old metronome that never lets anyone rush.",
        "A quiet reminder that the studio is closed on public holidays. Lessons move to the following week.",
        "Yes, the Tuesday group still has places. Send us a message and we will hold one for you.",
        "We moved the beginners' class to 4 pm so families can come after school. Same room, same teacher.",
    ])
]


def approved_state():
    state = initial_phase2_state("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "Owner", "studio", 1.0)
    group = {"key": "brand", "label": "This brand", "accounts": [{"provider": "threads", "accountKey": "acct-1"}], "eligible": len(POSTS)}
    proposal = voice_corpus.build_proposal(state, group, voice_corpus.measure(POSTS), [], {"eligible": len(POSTS), "analysed": len(POSTS)})
    profile = copy.deepcopy(proposal)
    profile["status"] = "approved"
    state["speaker"]["revisions"].append({"revision": 1, "profile": profile, "approvedAt": "2026-11-25T12:00:00+00:00", "reason": "test"})
    state["speaker"]["activeRevision"] = 1
    return state, profile


class ImportedVoiceReachesTheWriter(unittest.TestCase):
    def test_the_approved_import_profile_needs_no_sample_grant(self):
        state, profile = approved_state()
        self.assertEqual(profile.get("analysisMethod"), "voice_import")
        self.assertEqual(profile.get("evidenceSourceIds"), [])
        self.assertTrue(memory.manual_profile_available(state, "local"))

    def test_a_personalized_request_receives_its_traits_and_no_post_wording(self):
        state, _ = approved_state()
        shared, receipt = memory.prepare_writer(state, "local", "local-cli", destinations=[{"platform": "Threads", "language": "en"}], voice_mode="personalized")
        files = {item["name"]: item["body"] for item in shared["files"]} if isinstance(shared["files"], list) else shared["files"]
        voice = files.get("VOICE.md", "")
        self.assertTrue(voice.strip(), "VOICE.md reached the writer")
        self.assertEqual(receipt["requestedVoiceMode"], "personalized")
        self.assertTrue(receipt.get("traitsIncluded"), "the receipt names the traits that reached the writer")
        for post in POSTS:
            for start in range(0, len(post["body"]) - 30, 15):
                self.assertNotIn(post["body"][start:start + 30], voice, "no run of post wording reaches VOICE.md")

    def test_neutral_mode_keeps_the_imported_voice_out(self):
        state, _ = approved_state()
        shared, receipt = memory.prepare_writer(state, "local", "local-cli", destinations=[{"platform": "Threads", "language": "en"}], voice_mode="neutral")
        files = {item["name"]: item["body"] for item in shared["files"]} if isinstance(shared["files"], list) else shared["files"]
        self.assertNotIn("VOICE.md", files)
        self.assertEqual(receipt["effectiveVoiceMode"], "neutral")


if __name__ == "__main__":
    unittest.main()
