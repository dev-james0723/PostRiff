"""Trend screening reads the approved profile's topics and the owner's boundaries (brand intelligence WF-1).

The screening stays lexical and unqualified: it adds evidence-labelled reasons, never a score, and it never
repeats a boundary's wording in its output.
"""
import json
import unittest

from postriff_phase2.growth.trends import relevance


def state(topics=None, boundary=None, stale=False, active=1):
    profile = {"status": "stale" if stale else "active", "topics": topics or []}
    if boundary is not None:
        profile["fields"] = [{"id": "b1", "section": "boundaries", "key": "never", "value": boundary, "privacy": "private"}]
    return {"brandHub": {"subject": "", "audience": ""},
            "speaker": {"activeRevision": active, "revisions": [{"revision": 1, "profile": profile}]},
            "variants": [], "sources": []}


class TrendBrandFit(unittest.TestCase):
    def test_approved_topics_are_named_as_evidence_for_brand_fit(self):
        result = relevance.evaluate({"canonical_topic": "piano practice routines"}, state(topics=["piano teaching", "concert life"]))
        fit = result["dimensions"]["brand_fit"]
        self.assertEqual(fit["evidence_refs"], ["speaker.activeRevision.topics"])
        self.assertEqual(fit["assessment"], "unknown")   # lexical overlap never qualifies fit
        self.assertIn("unqualified", fit["reason"])
        self.assertFalse(result["qualified"])

    def test_no_overlap_leaves_brand_fit_not_evaluated(self):
        result = relevance.evaluate({"canonical_topic": "crypto markets"}, state(topics=["piano teaching"]))
        self.assertEqual(result["dimensions"]["brand_fit"]["reason"], "Not evaluated")

    def test_a_topic_that_touches_a_boundary_is_a_concern_and_the_boundary_text_is_not_repeated(self):
        result = relevance.evaluate({"canonical_topic": "election predictions"}, state(boundary="No election or party politics"))
        risk = result["dimensions"]["risk"]
        self.assertEqual(risk["assessment"], "concern")
        self.assertEqual(risk["evidence_refs"], ["BOUNDARIES.md"])
        self.assertNotIn("party politics", json.dumps(result))

    def test_chinese_topics_and_boundaries_match_too(self):
        result = relevance.evaluate({"canonical_topic": "鋼琴比賽"}, state(topics=["鋼琴教學"], boundary="不談政治"))
        self.assertEqual(result["dimensions"]["brand_fit"]["evidence_refs"], ["speaker.activeRevision.topics"])
        self.assertEqual(result["dimensions"]["risk"]["reason"], "Not evaluated")

    def test_a_stale_or_inactive_profile_contributes_no_topics(self):
        for value in (state(topics=["piano teaching"], stale=True), state(topics=["piano teaching"], active=None)):
            result = relevance.evaluate({"canonical_topic": "piano practice"}, value)
            self.assertEqual(result["dimensions"]["brand_fit"]["reason"], "Not evaluated")

    def test_a_profile_without_topics_screens_exactly_as_before(self):
        result = relevance.evaluate({"canonical_topic": "baking"}, state())
        self.assertEqual({name: d["reason"] for name, d in result["dimensions"].items()}, {name: "Not evaluated" for name in relevance.DIMENSIONS})
        self.assertEqual(result["method_version"], "workspace-screening.v2")


if __name__ == "__main__":
    unittest.main()
