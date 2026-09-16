"""Phase D, pure: performance is a like-for-like note on a proposal (never a proposal by itself), and an
active rule whose drafts needed more editing since it took effect becomes a retire proposal."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha import learning  # noqa: E402
from postriff_phase2 import learning_extract as extract  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400


def approved(job, hashtags, platform="LinkedIn", language="English", distance=0.1, at=NOW):
    return {"id": f"a-{job}", "kind": "draft.approved", "actor": "owner", "at": at, "subject": {"variantId": f"v-{job}", "jobId": job},
            "scope": {"platform": platform, "language": language, "contentTypeId": None, "formatId": None},
            "features": {"editCount": 1, "editDistance": distance, "approved": {"hashtags": hashtags, "emoji": 0, "exclamations": 0, "closingCta": False, "listLines": 0}}}


def candidate(rule="hashtags.use", polarity="avoid", platform="LinkedIn"):
    return {"ruleKey": rule, "polarity": polarity, "scope": {"platform": platform, "language": "English", "contentTypeId": None}}


class PerformanceNote(unittest.TestCase):
    def test_note_compares_like_for_like_and_names_the_direction(self):
        events = [approved(f"with{n}", 2) for n in range(3)] + [approved(f"without{n}", 0) for n in range(3)]
        metrics = {**{f"with{n}": {"saved": 10.0, "likes": 30.0} for n in range(3)}, **{f"without{n}": {"saved": 20.0, "likes": 30.0} for n in range(3)}}
        note = extract.performance_note(candidate(), events, metrics)
        self.assertEqual((note["metric"], note["direction"], note["withFeature"], note["withoutFeature"]), ("saved", "supports", {"posts": 3, "mean": 10.0}, {"posts": 3, "mean": 20.0}))
        self.assertIn("not a cause", note["note"])
        self.assertEqual(extract.performance_note(candidate(polarity="do"), events, metrics)["direction"], "contradicts")
        neutral = {**{f"with{n}": {"saved": 19.0} for n in range(3)}, **{f"without{n}": {"saved": 20.0} for n in range(3)}}
        self.assertEqual(extract.performance_note(candidate(), events, neutral)["direction"], "neutral")

    def test_no_note_without_three_measured_posts_of_each_kind_a_known_feature_or_a_matching_scope(self):
        events = [approved(f"with{n}", 2) for n in range(3)] + [approved("without0", 0)]
        metrics = {f"with{n}": {"saved": 10.0} for n in range(3)} | {"without0": {"saved": 20.0}}
        self.assertIsNone(extract.performance_note(candidate(), events, metrics))
        self.assertIsNone(extract.performance_note(candidate("length.target"), events, metrics))
        events = [approved(f"with{n}", 2, platform="Threads") for n in range(3)] + [approved(f"without{n}", 0, platform="Threads") for n in range(3)]
        metrics = {**{f"with{n}": {"saved": 10.0} for n in range(3)}, **{f"without{n}": {"saved": 20.0} for n in range(3)}}
        self.assertIsNone(extract.performance_note(candidate(platform="LinkedIn"), events, metrics), "another platform is not like for like")
        self.assertIsNotNone(extract.performance_note(candidate(platform=None), events, metrics), "a language-wide candidate reads every platform")

    def test_like_for_like_means_one_content_type(self):
        def typed(job, hashtags, content_type):
            event = approved(job, hashtags)
            event["scope"]["contentTypeId"] = content_type
            return event
        metrics = {**{f"with{n}": {"saved": 10.0} for n in range(3)}, **{f"without{n}": {"saved": 20.0} for n in range(3)}}
        mixed = [typed(f"with{n}", 2, "reflection") for n in range(3)] + [typed(f"without{n}", 0, "howto") for n in range(3)]
        self.assertIsNone(extract.performance_note(candidate(), mixed, metrics), "posts of two kinds are not compared")
        same = [typed(f"with{n}", 2, "reflection") for n in range(3)] + [typed(f"without{n}", 0, "reflection") for n in range(3)]
        note = extract.performance_note(candidate(), same, metrics)
        self.assertEqual((note["contentTypeId"], note["direction"]), ("reflection", "supports"))

    def test_revision_stats_summarise_editing_per_style_revision(self):
        events = [approved(f"r0-{n}", 0, distance=0.3) for n in range(3)] + [approved(f"r1-{n}", 0, distance=0.1) for n in range(2)]
        for event in events[3:]:
            event["styleRevision"] = 1
        events[3]["features"]["editCount"] = 0
        stats = extract.revision_stats(events + [{"kind": "draft.edited", "features": {}}])
        self.assertEqual(stats, [{"styleRevision": 0, "approvals": 3, "meanEditDistance": 0.3, "uneditedShare": 0.0}, {"styleRevision": 1, "approvals": 2, "meanEditDistance": 0.1, "uneditedShare": 0.5}])

    def test_performance_alone_never_makes_a_proposal(self):
        state = {"learning": learning.initial(migrated_at="x"), "variants": [], "preferences": []}
        events = [approved(f"with{n}", 2, distance=0.0) for n in range(6)]
        support, counter = extract.observations(events)
        self.assertEqual(extract.consolidate(support, counter, state, NOW), [])


class KillSwitch(unittest.TestCase):
    def test_more_editing_since_a_rule_took_effect_proposes_its_retirement(self):
        state = {"learning": learning.initial(migrated_at="x"), "variants": [], "preferences": []}
        item = learning.remember(state, {"ruleKey": "hashtags.use", "polarity": "avoid", "scope": {"platform": "LinkedIn", "language": "English"}, "statement": "No hashtags.", "source": "chat"}, now=NOW - 20 * DAY)
        before = [approved(f"b{n}", 0, distance=0.10, at=NOW - 30 * DAY) for n in range(3)]
        after = [approved(f"a{n}", 0, distance=0.35, at=NOW - 10 * DAY + n) for n in range(5)]
        proposals = extract.regressions(state, before + after, NOW)
        self.assertEqual([(p["op"], p["replaces"], p["statement"]) for p in proposals], [("retire", item["id"], "No hashtags.")])
        self.assertIn("35% of the text changed before approval, against 10% before", proposals[0]["why"])
        self.assertEqual(len(proposals[0]["evidence"]), 5)
        self.assertEqual(extract.regressions(state, before + after[:4], NOW), [], "four approvals after are not enough")
        self.assertEqual(extract.regressions(state, before[:2] + after, NOW), [], "two before are not a baseline")
        steady = [approved(f"s{n}", 0, distance=0.12, at=NOW - 10 * DAY + n) for n in range(5)]
        self.assertEqual(extract.regressions(state, before + steady, NOW), [], "within the margin nothing is proposed")
        other = [approved(f"t{n}", 0, platform="Threads", distance=0.5, at=NOW - 10 * DAY + n) for n in range(5)]
        self.assertEqual(extract.regressions(state, before + other, NOW), [], "another platform is not this rule's scope")


if __name__ == "__main__":
    unittest.main()
