"""Humanizer quality stage (adaptive coworker spec §10; architecture lock H1).

Meaning preservation is proven on 32 locale fixtures (en, zh-Hans, zh-Hant, zh-Hant-HK, yue-Hant-HK, code-switched)
plus held-out cases written independently of them; the detector flags clusters, never single words, protects brand
terms and reports script mixing; the stage never rewrites text and records its version.
"""
import json
import re
import unittest
from pathlib import Path

from postriff_phase2.coworker import humanizer

REPO = Path(__file__).resolve().parents[1]
CASES = json.loads((REPO / "tests" / "fixtures" / "humanizer_meaning_cases.json").read_text())


class MeaningPreservationTest(unittest.TestCase):
    def test_fixtures_cover_every_violation_and_locale(self):
        codes = {v for c in CASES for v in c["violations"]}
        self.assertEqual(codes, set(humanizer.VIOLATIONS))
        self.assertTrue({"en", "zh-Hans", "zh-Hant", "zh-Hant-HK", "yue-Hant-HK", "mixed-en-zh"} <= {c["locale"] for c in CASES})
        self.assertGreaterEqual(len(CASES), 24)

    def test_good_rewrites_preserve_meaning(self):
        for case in CASES:
            with self.subTest(case["id"]):
                self.assertEqual(humanizer.meaning_diff(case["source"], case["good_rewrite"], case["brand_terms"]), [])

    def test_bad_rewrites_report_exactly_their_violations(self):
        for case in CASES:
            with self.subTest(case["id"]):
                found = sorted(v["code"] for v in humanizer.meaning_diff(case["source"], case["bad_rewrite"], case["brand_terms"]))
                self.assertEqual(found, sorted(case["violations"]))

    def test_held_out_cases(self):
        held = [
            ("Our cafe may open a second store in March 2027.", "Our cafe opened a second store in March 2027.", {"hedge_removed", "status_changed"}),
            ("Sales rose 12% in Q3, according to the company.", "Sales rose 12% in Q3.", {"attribution_lost"}),
            ("Sales rose 12% in Q3, according to the company.", "Sales rose 15% in Q3, according to the company.", {"number_changed"}),
            ("呢個活動唔收費，但要預先登記。", "呢個活動收費，要預先登記。", {"negation_lost"}),
            ("部分會員可以提前購票。", "所有會員都可以提前購票。", {"scope_changed"}),
            ("The new menu launches next week.", "The new menu launches next week.", set()),
            ("Our tasting menu is available on Fridays.", "Honestly, I felt so proud when our tasting menu became available on Fridays.", {"feeling_added"}),
        ]
        for source, candidate, want in held:
            with self.subTest(candidate[:30]):
                self.assertEqual({v["code"] for v in humanizer.meaning_diff(source, candidate)}, want)

    def test_brand_terms_are_protected(self):
        source = "Try the Harbour Kitchen Signature Box this weekend."
        self.assertEqual(humanizer.meaning_diff(source, source, ["Harbour Kitchen Signature Box"]), [])
        changed = humanizer.meaning_diff(source, "Try our signature box this weekend.", ["Harbour Kitchen Signature Box"])
        self.assertIn("brand_term_changed", {v["code"] for v in changed})


class DetectorTest(unittest.TestCase):
    def test_a_cluster_is_flagged(self):
        text = ("In today's fast-paced digital landscape, it's important to note that our groundbreaking platform serves as a testament "
                "to innovation. Let's dive in!")
        result = humanizer.detect(text, "en")
        self.assertEqual([f["code"] for f in result["findings"]][:1], ["synthetic_cluster"])
        self.assertGreaterEqual(len(result["families"]), 2)

    def test_plain_specific_copy_is_not_flagged(self):
        for text in ("We cut delivery times from five days to three by moving the warehouse closer to the port.",
                     "Our spring menu has three new dishes. The lamb is slow-cooked for six hours.",
                     "今日我哋推出咗新菜單，歡迎嚟試。"):
            self.assertEqual(humanizer.detect(text, "yue-Hant-HK" if "今日" in text else "en")["findings"], [], text)

    def test_one_ai_word_is_not_a_finding(self):
        self.assertEqual(humanizer.detect("We tested a new landscape layout for the menu board this week.", "en")["findings"], [])

    def test_brand_terms_are_never_counted(self):
        text = "Delve Studio opens a pop-up in Leeds on Saturday."
        self.assertNotIn("delve", humanizer.detect(text, "en", ["Delve Studio"])["vocabulary"])

    def test_script_mixing_is_reported_for_traditional_copy(self):
        result = humanizer.detect("我們今天推出新的会员计划，歡迎查看。", "zh-Hant")
        self.assertIn("script_mixed", [f["code"] for f in result["findings"]])
        self.assertEqual(humanizer.detect("我們今天推出新的會員計劃，歡迎查看。", "zh-Hant")["findings"], [])

    def test_cantonese_register_is_evidence_not_an_error(self):
        result = humanizer.detect("今日我哋推出咗新菜單，歡迎嚟試。", "yue-Hant-HK")
        self.assertFalse(result["register"]["written"])
        self.assertEqual(result["findings"], [])


class StageTest(unittest.TestCase):
    def test_evaluate_never_rewrites_and_records_versions(self):
        source = "The workshop may move to 12 October, according to the venue."
        candidate = "The workshop moves to 12 October."
        result = humanizer.evaluate(candidate, source=source, locale="en", platform="LinkedIn")
        self.assertFalse(result["rewritten"])
        self.assertEqual(result["version"], humanizer.VERSION)
        self.assertEqual(result["patternsVersion"], humanizer.patterns()["version"])
        self.assertIn("attribution_lost", result["blocking"])
        self.assertIn("hedge_removed", result["blocking"])
        self.assertFalse(result["ok"])

    def test_platform_limits_are_linted(self):
        result = humanizer.evaluate("x" * 600, locale="en", platform="X")
        self.assertTrue(any(f["code"] == "too_long" for f in result["stages"]["lint"]))

    def test_packs_are_bounded_generic_and_attributed(self):
        for pack in ("rafii-humanizer-en", "rafii-humanizer-zh"):
            skill = (REPO / "skills" / pack / "SKILL.md").read_text()
            self.assertLessEqual(len(skill), 12_000, pack)
            notice = (REPO / "skills" / pack / "LICENSE-NOTICE.md").read_text()
            self.assertIn("MIT", notice)
            self.assertNotRegex(skill, re.compile(r"never use (?:an )?em[- ]dash", re.I))
            self.assertNotRegex(skill, re.compile(r"have opinions|let some mess in", re.I))
        zh = (REPO / "skills" / "rafii-humanizer-zh" / "SKILL.md").read_text() + (REPO / "skills" / "rafii-humanizer-zh" / "references" / "register.md").read_text()
        for needle in ("zh-Hant-HK", "yue", "zh-Hans"):
            self.assertIn(needle, zh)


if __name__ == "__main__":
    unittest.main()
