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


class LengthReminder(unittest.TestCase):
    """A remembered length is measured after drafting: a writer's own note that it complied is not evidence."""

    def test_words_over_an_exclusive_limit_get_a_measured_reminder(self):
        text = " ".join(["word"] * 86)
        note = signals.length_reminder("Remember: keep LinkedIn posts under 80 words", text)
        self.assertIn("86 words", note)
        self.assertIn("under 80", note)
        self.assertIsNone(signals.length_reminder("Remember: keep LinkedIn posts under 80 words", " ".join(["word"] * 79)))
        self.assertIsNotNone(signals.length_reminder("Keep posts under 80 words", " ".join(["word"] * 80)))

    def test_inclusive_limits(self):
        self.assertIsNone(signals.length_reminder("At most 80 words on X", " ".join(["word"] * 80)))
        self.assertIn("81 words", signals.length_reminder("No more than 80 words", " ".join(["word"] * 81)))
        self.assertIn("81 words", signals.length_reminder("80 words or fewer", " ".join(["word"] * 81)))

    def test_chinese_counts_characters_as_words(self):
        self.assertIn("12", signals.length_reminder("以後 Threads 帖文 10 字以內", "今日練完琴記低一件事情呀"))
        self.assertIsNone(signals.length_reminder("唔好超過 20 字", "今日練完琴，記低一件事。"))

    def test_statements_without_an_explicit_whole_post_maximum_are_never_measured(self):
        long_text = " ".join(["word"] * 2000)
        for statement in ("Keep posts short", "Write shorter openings", "Use 3 short paragraphs", "Posts of about 80 words read best", "",
                          # a minimum, however it is phrased, is not a maximum
                          "Never go below 100 words", "Don't write fewer than 100 words", "not less than 150 words", "不少於 100 字", "At least 80 words",
                          "每篇至少 80 字內容", "Write a minimum of 50 words",
                          # a limit on part of a post is not a limit on the post
                          "Keep sentences under 20 words", "Keep titles under 10 words", "First line under 8 words", "Paragraphs of at most 40 words",
                          # numbers that are not lengths, and units this check does not measure
                          "Use up to 3 hashtags", "Reply within 2 days", "Keep clips under 18s", "Mention at most 2 characters per post",
                          "Keep posts under 120 characters.", "climax 5 words"):
            self.assertIsNone(signals.length_limit(statement), statement)
            self.assertIsNone(signals.length_reminder(statement, long_text), statement)
        self.assertIsNone(signals.length_reminder("under 80 words", None))

    def test_thousands_are_read_whole(self):
        self.assertEqual(signals.length_limit("1,000 words or fewer")["max"], 1000)
        self.assertEqual(signals.length_limit("Keep essays under 1,500 words")["max"], 1499)
        self.assertIsNone(signals.length_limit("under 0 words"))

    def test_bullets_and_links_do_not_inflate_the_count(self):
        text = "Three things I checked:\n- the oven\n- the flour\n- the door\nMore at https://example.com/a-long/path-with-many-parts?x=1 today"
        self.assertEqual(signals.word_count(text), 14)
        self.assertEqual(signals.word_count("今日練琴 well-known piece"), 6)


class RememberedLengthOnARun(unittest.TestCase):
    """Only a preference the run was given is measured, and only on the destinations its scope covers."""

    def setUp(self):
        from postriff_phase2 import ideas
        self.ideas = ideas
        self.item = {"id": "pref-1", "status": "active", "ruleKey": "length.target", "statement": "Remember: keep LinkedIn posts under 80 words",
                     "scope": {"platform": "LinkedIn", "language": None, "contentTypeId": None}}
        self.state = {"learning": {"active": [self.item, {"id": "pref-2", "status": "active", "ruleKey": "hashtags.use", "statement": "No hashtags.", "scope": {}}]}}
        self.long = " ".join(["word"] * 86)

    def variants(self):
        return [{"platform": "LinkedIn", "language": "en", "text": self.long, "warnings": ["Kept under 80 words per the saved LinkedIn preference."]},
                {"platform": "Instagram", "language": "en", "text": self.long, "warnings": []}]

    def test_bound_preference_is_measured_on_its_own_platform_only(self):
        variants = self.variants()
        self.ideas.remembered_length_reminders(self.state, ["pref-1", "pref-2"], variants)
        self.assertTrue(any("86 words" in note and "under 80" in note for note in variants[0]["warnings"]))
        self.assertEqual(variants[0]["text"], self.long)
        self.assertEqual(variants[1]["warnings"], [])

    def test_unbound_paused_or_short_enough_adds_nothing(self):
        variants = self.variants()
        self.ideas.remembered_length_reminders(self.state, [], variants)
        self.ideas.remembered_length_reminders(self.state, None, variants)
        self.item["status"] = "paused"
        self.ideas.remembered_length_reminders(self.state, ["pref-1"], variants)
        self.item["status"] = "active"
        short = [{"platform": "LinkedIn", "language": "en", "text": "A short post.", "warnings": []}]
        self.ideas.remembered_length_reminders(self.state, ["pref-1"], short)
        self.assertEqual(len(variants[0]["warnings"]), 1)
        self.assertEqual(short[0]["warnings"], [])

    def test_reminder_is_added_once(self):
        variants = self.variants()
        for _ in range(2):
            self.ideas.remembered_length_reminders(self.state, ["pref-1"], variants)
        self.assertEqual(sum("86 words" in note for note in variants[0]["warnings"]), 1)

    def test_narrower_scope_decides_and_the_reminder_agrees_with_the_writer_limit(self):
        items = [{"id": "g", "status": "active", "ruleKey": "length.target", "statement": "Keep posts under 50 words", "scope": {}},
                 {"id": "l", "status": "active", "ruleKey": "length.target", "statement": "Up to 300 words on LinkedIn", "scope": {"platform": "LinkedIn"}}]
        state = {"learning": {"active": items}}
        text = " ".join(["word"] * 200)
        variants = [{"platform": "LinkedIn", "language": "en", "text": text, "warnings": []}, {"platform": "Threads", "language": "en", "text": text, "warnings": []}]
        self.assertEqual(self.ideas.remembered_length_limits(state, ["g", "l"], variants),
                         [{"platform": "LinkedIn", "language": "en", "words": 300}, {"platform": "Threads", "language": "en", "words": 49}])
        self.ideas.remembered_length_reminders(state, ["g", "l"], variants)
        self.assertEqual(variants[0]["warnings"], [])
        self.assertTrue(any("200 words" in note and "under 50" in note for note in variants[1]["warnings"]))


class RememberedLengthReachesTheWriter(unittest.TestCase):
    """A stated limit travels to the writer as a number on the destination, not only as a sentence in VOICE.md
    (a real writer met "under 80 words" 2 times in 5 from the sentence alone, 5 in 5 with the number)."""

    def test_stated_limit_is_parsed_as_an_inclusive_maximum(self):
        self.assertEqual(signals.length_limit("Remember: keep LinkedIn posts under 80 words"), {"max": 79, "stated": 80, "exclusive": True})
        self.assertEqual(signals.length_limit("At most 80 words"), {"max": 80, "stated": 80, "exclusive": False})
        self.assertEqual(signals.length_limit("最多 200 字")["max"], 200)
        self.assertEqual(signals.length_limit("帖文 100 字內。")["max"], 100)

    def test_only_bound_preferences_on_covered_destinations_set_a_limit(self):
        from postriff_phase2 import ideas
        items = [{"id": "a", "status": "active", "ruleKey": "length.target", "statement": "Keep LinkedIn posts under 80 words", "scope": {"platform": "LinkedIn"}},
                 {"id": "b", "status": "active", "ruleKey": "length.target", "statement": "At most 60 words", "scope": {}},
                 {"id": "c", "status": "active", "ruleKey": "length.target", "statement": "Under 20 words", "scope": {"platform": "X"}},
                 {"id": "d", "status": "active", "ruleKey": "other", "statement": "Mention 5 words of thanks", "scope": {}},
                 {"id": "e", "status": "active", "ruleKey": "length.target", "statement": "At most 70 words on LinkedIn", "scope": {"platform": "LinkedIn"}}]
        state = {"learning": {"active": items}}
        destinations = [{"platform": "LinkedIn", "language": "en"}, {"platform": "Instagram", "language": "en"}]
        self.assertEqual(ideas.remembered_length_limits(state, ["a", "d"], destinations), [{"platform": "LinkedIn", "language": "en", "words": 79}])
        self.assertEqual(ideas.remembered_length_limits(state, ["a", "b", "c"], destinations),
                         [{"platform": "LinkedIn", "language": "en", "words": 79}, {"platform": "Instagram", "language": "en", "words": 60}])
        self.assertEqual(ideas.remembered_length_limits(state, ["a", "e"], destinations), [{"platform": "LinkedIn", "language": "en", "words": 70}])
        self.assertEqual(ideas.remembered_length_limits(state, [], destinations), [])

    def test_only_a_matching_destination_carries_the_word_limit(self):
        request = {"lengthLimits": [{"platform": "LinkedIn", "language": "en", "words": 79}]}
        self.assertEqual(signals.word_limit_field(request, {"platform": "LinkedIn", "language": "en"}), {"wordLimit": 79})
        self.assertEqual(signals.word_limit_field(request, {"platform": "Threads", "language": "en"}), {})
        self.assertEqual(signals.word_limit_field({}, {"platform": "LinkedIn", "language": "en"}), {})
        self.assertTrue(signals.has_word_limit(request))
        self.assertFalse(signals.has_word_limit({"lengthLimits": [{"platform": "X", "words": "79"}]}))


if __name__ == "__main__":
    unittest.main()
