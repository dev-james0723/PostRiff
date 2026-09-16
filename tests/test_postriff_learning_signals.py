"""Learning signals (preference-learning design §3, §5.1): text features, a CJK-aware edit distance,
and the events one command implies from the state before and after it, without any draft text."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import learning_signals as signals  # noqa: E402

NOW = "2026-09-16T10:00:00+00:00"
ENGLISH = "Is it worth showing the messy middle?\n\nThis week I rebuilt the glaze schedule. It broke twice.\n\nComment below if you want the full list! #ceramics #studio 🔥"
CHINESE = "今日練完琴，記低一件事。\n\n慢練唔係為咗慢，係為咗聽清楚。\n\n你哋平時點練？留言告訴我 #練琴"


def variant(vid="v1", text=ENGLISH, revision=1, origin="ideas-candidate", **extra):
    base = {"id": vid, "platform": "LinkedIn", "language": "English", "contentTypeId": "pack.creator:personal_reflection", "formatId": "post", "text": text, "revision": revision,
            "revisions": [{"revision": 1, "text": text, "origin": origin}], "runId": "run-1", "styleRevision": 0, "feedback": []}
    base.update(extra)
    return base


def state(variants=None, jobs=None, preferences=None, learning=None):
    return {"speaker": {"activeRevision": 1}, "learning": learning or {"enabled": True, "revision": 0}, "variants": variants or [], "preferences": preferences or [], "phase2": {"jobs": jobs or []}}


class Features(unittest.TestCase):
    def test_english_form_counts(self):
        f = signals.features(ENGLISH)
        self.assertEqual((f["paragraphs"], f["hashtags"], f["emoji"], f["exclamations"], f["firstLineQuestion"], f["closingCta"]), (3, 2, 1, 1, True, True))
        self.assertEqual(f["firstLineTokens"], 7)
        self.assertEqual(f["cjkRatio"], 0.0)

    def test_chinese_form_counts(self):
        f = signals.features(CHINESE)
        self.assertEqual((f["paragraphs"], f["hashtags"], f["closingCta"], f["firstLineQuestion"]), (3, 1, True, False))
        self.assertGreater(f["cjkRatio"], 0.9)
        self.assertEqual(f["fullwidthPunctuation"], 5)
        self.assertEqual(f["listLines"], 0)
        self.assertEqual(signals.features("- one\n- two\n3. three")["listLines"], 3)

    def test_edit_distance_is_token_based_for_both_scripts(self):
        self.assertEqual(signals.edit_distance("Same text.", "Same text."), 0.0)
        self.assertEqual(signals.edit_distance("", ""), 0.0)
        self.assertGreater(signals.edit_distance("今日練完琴，記低一件事。", "今日練完琴。"), 0.3)
        self.assertLess(signals.edit_distance("A shorter opening.\n\nA useful question to explore.", "A shorter opening.\n\nA useful question to explore now."), 0.2)
        self.assertEqual(signals.edit_distance("abc", "xyz"), 1.0)

    def test_redaction_keeps_shape_and_drops_identifiers(self):
        out = signals.redact("Email me at kiln@studio.hk or @kilnandquiet, 3 spots left, see https://x.y/z on 12/10.")
        self.assertNotIn("kiln@studio.hk", out)
        self.assertNotIn("kilnandquiet", out)
        self.assertNotIn("https://", out)
        self.assertEqual(out.count("<num>"), 2)
        self.assertIn("spots left", out)


class DerivedEvents(unittest.TestCase):
    def test_an_authored_edit_yields_one_event_with_features_and_no_text(self):
        before = state([variant()])
        after = copy.deepcopy(before)
        v = after["variants"][0]
        v.update({"text": "This week I rebuilt the glaze schedule.\n\nIt broke twice.", "revision": 2})
        v["revisions"].append({"revision": 2, "text": v["text"], "origin": "author-edit"})
        events = signals.derive_events(before, after, "owner-1", NOW, "variant_edit", {"variantId": "v1"})
        self.assertEqual([e["kind"] for e in events], ["draft.edited"])
        event = events[0]
        self.assertEqual(event["subject"], {"variantId": "v1", "fromRevision": 1, "toRevision": 2, "origin": "author-edit", "runId": "run-1"})
        self.assertEqual(event["scope"], {"platform": "LinkedIn", "language": "English", "contentTypeId": "pack.creator:personal_reflection", "formatId": "post"})
        self.assertEqual((event["features"]["before"]["hashtags"], event["features"]["after"]["hashtags"], event["features"]["after"]["closingCta"]), (2, 0, False))
        self.assertGreater(event["features"]["editDistance"], 0.3)
        self.assertEqual((event["voiceRevision"], event["styleRevision"], event["actor"], event["at"]), (1, 0, "owner-1", NOW))
        self.assertFalse(signals.contains_text(event, "glaze schedule"))
        self.assertFalse(signals.contains_text(event, ENGLISH))

    def test_accepted_candidate_feedback_and_decided_proposal(self):
        before = state([variant(), variant("v2", CHINESE, platform="Instagram", language="繁體中文")], preferences=[{"id": "p1", "status": "proposed", "scopeKey": "k", "ruleKey": "hashtags.use", "source": "chat", "scope": {"platform": "Instagram", "language": "繁體中文", "contentTypeId": None}}])
        after = copy.deepcopy(before)
        v1, v2 = after["variants"]
        v1.update({"text": "Rewritten by the model.", "revision": 2})
        v1["revisions"].append({"revision": 2, "text": v1["text"], "origin": "accepted-fixture-replacement"})
        v2["feedback"].append({"id": "f1", "reasons": ["not_my_voice", "too_long"], "note": "SECRET NOTE", "revision": 1})
        after["preferences"][0]["status"] = "remembered"
        events = signals.derive_events(before, after, "owner-1", NOW)
        self.assertEqual([e["kind"] for e in events], ["draft.update_accepted", "draft.rejected", "proposal.decided"])
        rejected = events[1]
        self.assertEqual((rejected["subject"]["variantId"], rejected["features"]["reasons"], rejected["scope"]["platform"]), ("v2", ["not_my_voice", "too_long"], "Instagram"))
        self.assertFalse(signals.contains_text(rejected, "SECRET NOTE"), "the note stays on the draft, for the person only")
        self.assertEqual(events[2]["subject"], {"proposalId": "p1", "decision": "remembered", "scopeKey": "k", "ruleKey": "hashtags.use", "source": "chat"})

    def test_approval_measures_edits_against_the_model_text_and_cancel_is_recorded(self):
        edited = "This week I rebuilt the glaze schedule.\n\nIt broke twice, and I kept going."
        v = variant()
        v.update({"text": edited, "revision": 2})
        v["revisions"].append({"revision": 2, "text": edited, "origin": "author-edit"})
        manifest = {"variantId": "v1", "contentRevision": 2, "platform": "LinkedIn", "payload": {"text": edited, "language": "English"}, "contentType": {"id": "pack.creator:personal_reflection", "formatId": "post"}, "voiceRevision": 1, "styleRevision": 3, "channelId": "c1"}
        job = {"id": "job-1", "state": "scheduled", "manifest": manifest, "scheduleId": "s1", "cancelRequested": False}
        before = state([v])
        after = state([v], jobs=[job])
        events = signals.derive_events(before, after, "owner-1", NOW, "p2_approve")
        self.assertEqual([e["kind"] for e in events], ["draft.approved"])
        approved = events[0]
        self.assertEqual(approved["subject"], {"jobId": "job-1", "variantId": "v1", "contentRevision": 2, "scheduleId": "s1", "channelId": "c1"})
        self.assertEqual(approved["features"]["editCount"], 1)
        self.assertGreater(approved["features"]["editDistance"], 0.3)
        self.assertEqual(approved["features"]["approved"]["paragraphs"], 2)
        self.assertEqual((approved["voiceRevision"], approved["styleRevision"]), (1, 3))
        self.assertFalse(signals.contains_text(approved, "glaze"))
        cancelled = copy.deepcopy(after)
        cancelled["phase2"]["jobs"][0].update({"cancelRequested": True, "state": "canceled"})
        events = signals.derive_events(after, cancelled, "owner-1", NOW, "p2_cancel")
        self.assertEqual([(e["kind"], e["subject"]["jobId"], e["scope"]["platform"]) for e in events], [("job.cancelled", "job-1", "LinkedIn")])

    def test_no_events_when_learning_is_off_or_nothing_changed(self):
        before = state([variant()])
        after = copy.deepcopy(before)
        self.assertEqual(signals.derive_events(before, after, "owner-1", NOW), [])
        after["variants"][0].update({"text": "changed", "revision": 2})
        after["variants"][0]["revisions"].append({"revision": 2, "text": "changed", "origin": "author-edit"})
        after["learning"]["enabled"] = False
        self.assertEqual(signals.derive_events(before, after, "owner-1", NOW), [])

    def test_published_event_carries_ids_and_features_only(self):
        job = {"id": "job-1", "providerReference": "post-9", "manifest": {"variantId": "v1", "contentRevision": 2, "platform": "Threads", "payload": {"text": CHINESE, "language": "繁體中文"}, "contentType": {"id": "x", "formatId": "post"}, "voiceRevision": 1, "styleRevision": 2}}
        event = signals.published_event(job, None, NOW)
        self.assertEqual(event["kind"], "post.published")
        self.assertEqual(event["subject"]["providerReference"], "post-9")
        self.assertEqual(event["features"]["published"]["hashtags"], 1)
        self.assertNotIn("練琴", json.dumps(event, ensure_ascii=False))
        self.assertIn(event["kind"], signals.EVENT_KINDS)


if __name__ == "__main__":
    unittest.main()
