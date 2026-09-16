"""Learned preferences on the local Phase 2 store (preference-learning design, decision A1): remembering
one keeps scheduled jobs and pending reviews valid, the next draft reads it, "don't use this draft"
feedback blocks scheduling until the draft changes, and the old shape migrates on the first command."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_alpha import learning  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import memory  # noqa: E402
from postriff_phase2.store import Phase2Store  # noqa: E402
from test_postriff_phase2 import P2Journey  # noqa: E402


class LearningOnPhase2Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1_800_000_000.0
        self.store = Phase2Store(Path(self.tmp.name) / "p2.db", clock=lambda: self.now)
        self.j = P2Journey(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def channel(self, platform="LinkedIn", language="English"):
        self.j.act("p2_channel_add", platform=platform, language=language)
        c = self.j.state["phase2"]["channels"][-1]
        self.j.act("p2_channel_verify", channelId=c["id"], scenario="success")
        return self.j.state["phase2"]["channels"][-1]

    def reviewed(self, platform="LinkedIn", language="English"):
        self.j.act("generate", platform=platform, language=language)
        v = self.j.state["variants"][-1]
        self.j.act("p2_variant_review", variantId=v["id"], variantRevision=v["revision"], confirmed=True, excludedUnknowns=v["unknowns"])
        return self.j.state["variants"][-1]

    def review(self, channel, variant):
        local = datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat()
        self.j.act("p2_review", channelId=channel["id"], variantId=variant["id"], localTime=local, timeZone="UTC", acknowledgedWarnings=variant["warnings"])
        return self.j.state["phase2"]["reviews"][-1]

    def variant(self, platform):
        return next(v for v in self.j.state["variants"] if v["platform"] == platform)

    def review_status(self, review_id):
        return next(r for r in self.j.state["phase2"]["reviews"] if r["id"] == review_id)["status"]

    def rewrite_state(self, mutate):
        """Change the stored state the way an older build (or server code) would, then reload the snapshot."""
        with self.store.connect() as db:
            row = db.execute("SELECT revision, state FROM workspaces WHERE id=?", (self.j.id,)).fetchone()
            state = json.loads(row["state"])
            result = mutate(state)
            db.execute("UPDATE workspaces SET state=?, revision=? WHERE id=?", (json.dumps(state), row["revision"] + 1, self.j.id))
        self.j.refresh()
        return result

    def propose(self, **overrides):
        """Server code proposes and the client only decides; seed one the way a later phase's chat path will."""
        proposal = {"type": "writing_preference", "ruleKey": "opening.style", "polarity": "do", "scope": {"platform": "LinkedIn", "language": "English"},
                    "statement": "Use shorter openings.", "params": {"shortOpenings": True}, "source": "chat", **overrides}
        return self.rewrite_state(lambda state: learning.propose(state, proposal, self.now))

    def test_remembering_a_preference_keeps_scheduled_jobs_and_pending_reviews(self):
        self.j.setup()
        linkedin, threads = self.channel("LinkedIn"), self.channel("Threads")
        first = self.review(linkedin, self.reviewed("LinkedIn"))
        self.j.act("p2_approve", reviewId=first["id"], digest=first["digest"], confirmed=True)
        job = self.j.state["phase2"]["jobs"][-1]
        self.assertEqual((job["state"], job["manifest"]["styleRevision"], job["manifest"]["voiceRevision"]), ("scheduled", 0, 1))
        pending = self.review(threads, self.reviewed("Threads"))
        self.assertEqual(pending["status"], "needs_review")

        proposal = self.propose()
        self.j.act("preference", preferenceId=proposal["id"], decision="remember")
        state = self.j.state
        self.assertEqual((state["speaker"]["activeRevision"], state["learning"]["revision"]), (1, 1))
        self.assertEqual(state["phase2"]["jobs"][-1]["state"], "scheduled")
        self.assertEqual(self.review_status(pending["id"]), "needs_review")
        self.assertFalse(any(v["needsReview"] for v in state["variants"]), "no draft was forced back into review")
        self.assertEqual(next(p for p in state["preferences"] if p["id"] == proposal["id"])["status"], "remembered")

        # The worker claims and submits the job; nothing was held.
        self.now += 61
        self.assertTrue(self.store.worker_step())
        self.j.refresh()
        job = self.j.state["phase2"]["jobs"][-1]
        self.assertNotEqual(job["state"], "held")
        self.assertEqual(len(job["attempts"]), 1)

        # The next LinkedIn draft reads the preference and records the style revision; Threads does not.
        self.j.act("preview_update", variantId=self.variant("LinkedIn")["id"])
        proposed = self.variant("LinkedIn")["proposedUpdate"]
        self.assertTrue(proposed["text"].startswith("A small start."))
        self.assertEqual((proposed["styleRevision"], proposed["voiceRevision"]), (1, 1))
        self.j.act("preview_update", variantId=self.variant("Threads")["id"])
        self.assertFalse(self.variant("Threads")["proposedUpdate"]["text"].startswith("A small start."))
        voice = next(f["body"] for f in memory.render_files(self.j.state) if f["name"] == "VOICE.md")
        self.assertIn("- [LinkedIn · English] Use shorter openings. — you said so", voice)

        # Undo retires the item under a new style revision; the voice revision still does not move.
        self.j.act("preference", preferenceId=proposal["id"], decision="undo")
        self.assertEqual((self.j.state["speaker"]["activeRevision"], self.j.state["learning"]["revision"], learning.active_items(self.j.state)), (1, 2, []))
        self.assertEqual(self.j.state["phase2"]["jobs"][-1]["state"], job["state"])

    def test_dont_use_this_draft_blocks_scheduling_until_the_draft_changes(self):
        self.j.setup()
        v = self.reviewed()
        channel = self.channel()
        pending = self.review(channel, v)
        with self.assertRaises(AlphaError):
            self.j.act("p2_variant_feedback", variantId=v["id"], variantRevision=v["revision"], reasons=["nope"])
        with self.assertRaises(AlphaError):
            self.j.act("p2_variant_feedback", variantId=v["id"], variantRevision=v["revision"] + 1, reasons=["other"])
        self.j.act("p2_variant_feedback", variantId=v["id"], variantRevision=v["revision"], reasons=["not_my_voice", "too_long"], note="Reads like a brochure.")
        v = self.j.state["variants"][0]
        self.assertTrue(v["rejected"])
        self.assertEqual((v["feedback"][0]["reasons"], v["feedback"][0]["note"], v["feedback"][0]["revision"]), (["not_my_voice", "too_long"], "Reads like a brochure.", v["revision"]))
        self.assertEqual(self.review_status(pending["id"]), "stale")
        with self.assertRaises(AlphaError) as caught:
            self.review(channel, v)
        self.assertIn("don't want to use", str(caught.exception))

        self.j.act("variant_edit", variantId=v["id"], variantRevision=v["revision"], text="My own words instead.")
        v = self.j.state["variants"][0]
        self.assertNotIn("rejected", v)
        self.assertEqual(len(v["feedback"]), 1, "the feedback stays on the draft as a learning signal")
        self.j.act("p2_variant_review", variantId=v["id"], variantRevision=v["revision"], confirmed=True, excludedUnknowns=v["unknowns"])
        v = self.j.state["variants"][0]
        review = self.review(channel, v)
        self.j.act("p2_approve", reviewId=review["id"], digest=review["digest"], confirmed=True)
        with self.assertRaises(AlphaError) as caught:
            self.j.act("p2_variant_feedback", variantId=v["id"], variantRevision=v["revision"], reasons=["other"])
        self.assertEqual(caught.exception.status, 409)

    def test_edits_no_longer_create_hidden_proposals_and_an_old_workspace_migrates_once(self):
        self.j.setup()
        v = self.reviewed()
        self.j.act("variant_edit", variantId=v["id"], variantRevision=v["revision"], text="Edited by hand.")
        self.assertEqual(self.j.state["preferences"], [])
        self.assertNotIn("preferenceAsked", self.j.state["variants"][0])

        def older_build(state):
            state.pop("learning")
            state["preferences"].append({"id": "hidden-1", "variantId": v["id"], "platform": "LinkedIn", "language": "English", "key": "shortOpenings", "value": True, "label": "Use shorter openings?", "status": "proposed", "createdAt": "2026-09-10T00:00:00+00:00"})
            state["preferences"].append({"id": "kept-1", "variantId": v["id"], "platform": "Threads", "language": "English", "key": "shortOpenings", "value": True, "status": "remembered"})
            state["speaker"]["revisions"][0]["profile"]["preferences"] = [{"id": "kept-1", "platform": "Threads", "language": "English", "key": "shortOpenings", "value": True}]

        self.rewrite_state(older_build)
        self.j.act("p2_refresh")
        state = self.j.state
        statuses = {p["id"]: p["status"] for p in state["preferences"]}
        self.assertEqual(statuses, {"hidden-1": "expired", "kept-1": "remembered"})
        self.assertEqual([(i["id"], i["evidenceState"]) for i in learning.active_items(state)], [("kept-1", "user_confirmed")])
        self.assertEqual((state["speaker"]["activeRevision"], state["learning"]["revision"]), (1, 1))
        self.assertTrue(learning.flag(state, "shortOpenings", "Threads", "English"))
        self.assertTrue(state["learning"]["migratedAt"])


if __name__ == "__main__":
    unittest.main()
