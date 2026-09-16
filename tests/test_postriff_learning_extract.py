"""Phase C1, pure: observations from edit features and unedited approvals, then consolidation with a
threshold, distinct drafts, counter-evidence, decay, dismissal, promotion, conflicts and retirement."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha import learning  # noqa: E402
from postriff_phase2 import learning_extract as extract  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400


def features(**overrides):
    base = {"chars": 400, "tokens": 80, "lines": 5, "paragraphs": 3, "sentencesPerParagraph": 2.0, "firstLineTokens": 12, "firstLineQuestion": False,
            "hashtags": 0, "emoji": 0, "exclamations": 0, "questions": 0, "listLines": 0, "closingCta": False, "cjkRatio": 0.0, "fullwidthPunctuation": 0, "halfwidthPunctuation": 6}
    base.update(overrides)
    return base


def edited(variant, before, after, platform="LinkedIn", language="English", at=NOW, actor="owner", event_id=None):
    return {"id": event_id or f"e-{variant}-{platform}-{at}", "kind": "draft.edited", "actor": actor, "at": at, "subject": {"variantId": variant, "origin": "author-edit"},
            "scope": {"platform": platform, "language": language, "contentTypeId": None, "formatId": None}, "features": {"before": before, "after": after, "editDistance": 0.3}, "voiceRevision": 1, "styleRevision": 0}


def approved(variant, text_features, edit_count=0, platform="LinkedIn", language="English", at=NOW):
    return {"id": f"a-{variant}", "kind": "draft.approved", "actor": "owner", "at": at, "subject": {"variantId": variant, "jobId": f"j-{variant}"},
            "scope": {"platform": platform, "language": language, "contentTypeId": None, "formatId": None}, "features": {"editCount": edit_count, "editDistance": 0.0, "approved": text_features}, "voiceRevision": 1, "styleRevision": 0}


def state():
    return {"speaker": {"activeRevision": 1, "revisions": [{"revision": 1, "profile": {}}]}, "learning": learning.initial(migrated_at="x"), "variants": [], "preferences": []}


class Observations(unittest.TestCase):
    def test_edit_features_map_to_rules(self):
        support, counter = extract.observations([
            edited("v1", features(hashtags=3, emoji=2, exclamations=1, closingCta=True, listLines=4, firstLineQuestion=True, firstLineTokens=14, tokens=120),
                   features(hashtags=0, emoji=0, exclamations=0, closingCta=False, listLines=0, firstLineQuestion=False, firstLineTokens=6, tokens=70)),
        ])
        self.assertEqual({(o["ruleKey"], o["polarity"]) for o in support},
                         {("hashtags.use", "avoid"), ("emoji.use", "avoid"), ("exclamation.use", "avoid"), ("closing.cta", "avoid"), ("lists.use", "avoid"), ("opening.style", "avoid"), ("opening.style", "do"), ("length.target", "avoid")})
        self.assertEqual(next(o["value"] for o in support if o["ruleKey"] == "length.target"), 70)
        self.assertEqual(counter, [])
        self.assertTrue(all(o["scopeKey"].endswith("|LinkedIn|English|*") for o in support))

    def test_an_unedited_approval_counts_against_rules_that_would_have_changed_it(self):
        support, counter = extract.observations([approved("v1", features(hashtags=2, closingCta=True), edit_count=0), approved("v2", features(hashtags=2), edit_count=1)])
        self.assertEqual(support, [])
        self.assertEqual({(o["ruleKey"], o["polarity"]) for o in counter} & {("hashtags.use", "avoid"), ("closing.cta", "avoid"), ("emoji.use", "do")}, {("hashtags.use", "avoid"), ("closing.cta", "avoid"), ("emoji.use", "do")})
        self.assertTrue(all(o["variantId"] == "v1" for o in counter), "an edited approval is not counter-evidence")

    def test_rejected_as_too_long_supports_a_length_target(self):
        support, _ = extract.observations([{"id": "r1", "kind": "draft.rejected", "actor": "owner", "at": NOW, "subject": {"variantId": "v9"}, "scope": {"platform": "Threads", "language": "English"}, "features": {"reasons": ["too_long"], "text": features(tokens=140)}}])
        self.assertEqual([(o["ruleKey"], o["polarity"], o["value"]) for o in support], [("length.target", "avoid", 140)])


class Consolidation(unittest.TestCase):
    def removed_hashtags(self, variants, platform="LinkedIn", language="English", at=NOW):
        return [edited(v, features(hashtags=2), features(hashtags=0), platform, language, at) for v in variants]

    def test_three_edits_on_two_drafts_clear_the_bar_and_two_do_not(self):
        two = extract.consolidate(*extract.observations(self.removed_hashtags(["v1", "v2"])), state(), NOW)
        self.assertEqual(two, [])
        aged = extract.consolidate(*extract.observations(self.removed_hashtags(["v1", "v2", "v3"], at=NOW - 10 * DAY)), state(), NOW)
        self.assertEqual(len(aged), 1, "three edits from ten days ago still clear the bar")
        one_draft = extract.consolidate(*extract.observations(self.removed_hashtags(["v1", "v1", "v1"])), state(), NOW)
        self.assertEqual(one_draft, [], "three edits of the same draft are one draft")
        proposals = extract.consolidate(*extract.observations(self.removed_hashtags(["v1", "v2", "v3"])), state(), NOW)
        self.assertEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual((p["ruleKey"], p["polarity"], p["statement"], p["scope"], p["source"], p["replaces"]), ("hashtags.use", "avoid", "No hashtags.", {"platform": "LinkedIn", "language": "English", "contentTypeId": None}, "deterministic", None))
        self.assertEqual(len(p["evidence"]), 3)
        self.assertIn("3 of your drafts on LinkedIn · English", p["why"])
        self.assertEqual(learning.lint(p["statement"], p["ruleKey"]), p["statement"])

    def test_counter_evidence_decay_and_dismissal_hold_a_candidate_back(self):
        support, counter = extract.observations(self.removed_hashtags(["v1", "v2", "v3"]) + [approved("v4", features(hashtags=1), 0)])
        self.assertEqual(len(extract.consolidate(support, counter, state(), NOW)), 1, "one unedited approval with hashtags is 0.5 against 3.0: within the ratio")
        support, counter = extract.observations(self.removed_hashtags(["v1", "v2", "v3"]) + [approved("v4", features(hashtags=1), 0), approved("v5", features(hashtags=1), 0)])
        self.assertEqual(extract.consolidate(support, counter, state(), NOW), [], "two unedited approvals with hashtags are 1.0 against 3.0: over the ratio")
        support, _ = extract.observations(self.removed_hashtags(["v1", "v2", "v3"], at=NOW - 100 * DAY))
        self.assertEqual(extract.consolidate(support, [], state(), NOW), [], "hundred-day-old edits have decayed below the threshold")
        support, _ = extract.observations(self.removed_hashtags(["v1", "v2", "v3"]))
        key = learning.scope_key("writing_preference", "hashtags.use", "avoid", {"platform": "LinkedIn", "language": "English", "contentTypeId": None})
        self.assertEqual(extract.consolidate(support, [], state(), NOW, dismissed_keys={key}), [])
        self.assertEqual(extract.consolidate(support, [], state(), NOW, recent_decisions=["dismissed"] * 5), [], "a low accept rate doubles the threshold")
        self.assertEqual(len(extract.consolidate(support, [], state(), NOW, recent_decisions=["remembered", "dismissed", "remembered", "dismissed", "remembered"])), 1)

    def test_same_rule_on_two_platforms_is_one_language_level_proposal(self):
        events = self.removed_hashtags(["v1", "v2", "v3"], "LinkedIn") + self.removed_hashtags(["v4", "v5", "v6"], "Threads")
        proposals = extract.consolidate(*extract.observations(events), state(), NOW)
        self.assertEqual([(p["scope"], p["statement"]) for p in proposals], [({"platform": None, "language": "English", "contentTypeId": None}, "No hashtags.")])
        events += self.removed_hashtags(["v7", "v8", "v9"], "Instagram", "繁體中文") + self.removed_hashtags(["v10", "v11", "v12"], "Threads", "繁體中文")
        proposals = extract.consolidate(*extract.observations(events), state(), NOW)
        self.assertEqual([p["scope"] for p in proposals], [{"platform": None, "language": None, "contentTypeId": None}])

    def test_length_target_uses_the_median_and_the_scope_language(self):
        events = [edited(f"v{n}", features(tokens=160), features(tokens=t), "Instagram", "繁體中文") for n, t in enumerate((90, 110, 100))]
        proposals = extract.consolidate(*extract.observations(events), state(), NOW)
        self.assertEqual([p["statement"] for p in proposals], ["Keep posts under 100 characters."])

    def test_an_active_item_is_not_re_proposed_but_a_conflict_becomes_an_update_and_edits_against_it_a_retirement(self):
        s = state()
        current = learning.remember(s, {"ruleKey": "hashtags.use", "polarity": "avoid", "scope": {"platform": "LinkedIn", "language": "English"}, "statement": "No hashtags.", "source": "chat"}, now=NOW)
        self.assertEqual(extract.consolidate(*extract.observations(self.removed_hashtags(["v1", "v2", "v3"])), s, NOW), [], "already learned")
        added = [edited(v, features(hashtags=0), features(hashtags=2)) for v in ("v1", "v2", "v3")]
        proposals = extract.consolidate(*extract.observations(added), s, NOW)
        self.assertEqual([(p["polarity"], p["op"] if "op" in p else "add", p["replaces"]) for p in proposals], [("do", "add", current["id"])])
        self.assertEqual(proposals[0]["statement"], "Use hashtags.")
        # The same evidence, seen as "stop the old rule", is offered once as a retirement when nothing replaces it.
        s2 = state()
        old = learning.remember(s2, {"ruleKey": "closing.cta", "polarity": "avoid", "scope": {"platform": "LinkedIn", "language": "English"}, "statement": "Don't end with a call to action.", "source": "chat"}, now=NOW)
        going_back = [edited(v, features(closingCta=False), features(closingCta=True)) for v in ("v1", "v2", "v3")]
        proposals = extract.consolidate(*extract.observations(going_back), s2, NOW)
        self.assertEqual([(p.get("op", "add"), p["replaces"]) for p in proposals], [("add", old["id"])])
        self.assertEqual(proposals[0]["statement"], "End with a call to action.")

    def test_retirement_alone_when_the_opposite_has_no_statement(self):
        s = state()
        old = learning.remember(s, {"ruleKey": "exclamation.use", "polarity": "avoid", "scope": {"platform": "LinkedIn", "language": "English"}, "statement": "No exclamation marks.", "source": "chat"}, now=NOW)
        # Adding exclamation marks has no "do" statement, so the only proposal is to retire the old rule.
        support = [{"ruleKey": "exclamation.use", "polarity": "do", "scope": {"platform": "LinkedIn", "language": "English", "contentTypeId": None}, "scopeKey": learning.scope_key("writing_preference", "exclamation.use", "do", {"platform": "LinkedIn", "language": "English", "contentTypeId": None}), "weight": 1.0, "at": NOW, "eventId": f"e{n}", "variantId": f"v{n}", "value": None, "source": "deterministic"} for n in range(3)]
        proposals = extract.consolidate(support, [], s, NOW)
        self.assertEqual([(p["op"], p["replaces"], p["statement"]) for p in proposals], [("retire", old["id"], "No exclamation marks.")])


if __name__ == "__main__":
    unittest.main()
