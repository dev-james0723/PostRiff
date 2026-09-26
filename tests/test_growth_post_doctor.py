import unittest

from postriff_phase2.growth import jev as J
from postriff_phase2.growth import post_doctor as P
from postriff_phase2.growth import questions as Q
from postriff_phase2.growth import router as R
from postriff_phase2.growth.judgments import Judgment, JudgmentService, validate_answers

QS = Q.get("postdoctor")
ON = {P.FLAG: "1"}


def judgment(probs, *, calibrated=True, status="ok"):
    raw = {n: {"type": "boolean", "probability": p} for n, p in probs.items()}
    answers, invalid = validate_answers(QS, raw, names=list(probs))
    return Judgment(QS.key, QS.digest, "typesafe-ai/jev", "primary", calibrated, answers, invalid, None, "unknown",
                    None, 1, "k", status=status)


def all_answers(p=0.9, **overrides):
    probs = {n: p for n in QS.names}
    probs.update({n: 0.05 for n in QS.names if n.startswith("risk_")})
    probs.update(overrides)
    return probs


class Levels(unittest.TestCase):
    def test_invert_items_and_levels(self):
        # Every normal item 0.9 and every inverted item 0.9 → inverted contributes 0.1.
        dims = {d.id: d for d in P.levels_from_judgment(QS, judgment(all_answers()))}
        hook = dims["hook"]
        expected = (1.0 * 0.9 + 0.8 * 0.9 + 0.8 * 0.9 + 1.0 * 0.1 + 0.8 * 0.9) / 4.4
        self.assertAlmostEqual(hook.score, round(expected, 4))
        self.assertEqual(hook.level, 2)          # 0.736 → strong with [0.35, 0.55, 0.75]
        self.assertEqual(dims["novelty"].level, 3)
        self.assertEqual(hook.fixes, ("Replace the generic opener with the most specific line of the post.",))

    def test_abstained_answers_are_not_no_and_low_weight_gives_none(self):
        probs = all_answers(nov_firsthand=0.5, nov_challenges_belief=0.9)  # 0.5 abstains; 0.8/1.8 < 0.5 of weight
        dims = {d.id: d for d in P.levels_from_judgment(QS, judgment(probs))}
        self.assertIsNone(dims["novelty"].level)
        self.assertAlmostEqual(dims["novelty"].answered_weight, round(0.8 / 1.8, 4))
        probs = all_answers(nov_firsthand=0.9, nov_challenges_belief=0.5)
        dims = {d.id: d for d in P.levels_from_judgment(QS, judgment(probs))}
        self.assertEqual(dims["novelty"].level, 3)   # remaining answered weight 1.0/1.8 is enough

    def test_localised_fixes_max_two_and_thresholds_override(self):
        probs = all_answers(hook_specific_promise=0.1, hook_concrete_detail=0.2, hook_curiosity=0.1)
        hook = P.levels_from_judgment(QS, judgment(probs), lang="zh-Hant")[0]
        self.assertEqual(len(hook.fixes), 2)
        self.assertEqual(hook.fixes[0], "第一句講明讀者會得到乜。")
        low = P.levels_from_judgment(QS, judgment(all_answers()), thresholds=[0.9, 0.95, 0.99])[0]
        self.assertEqual(low.level, 0)

    def test_risks(self):
        self.assertEqual(P.risks_from_judgment(QS, judgment(all_answers(risk_bait=0.7))), ("risk_bait",))


class Computed(unittest.TestCase):
    def test_similarity_is_cjk_safe(self):
        self.assertEqual(P.similarity_recent("今日練琴三個鐘", ["今日練琴三個鐘"]), 1.0)
        self.assertEqual(P.similarity_recent("今日練琴", ["明天休息"]), 0.0)
        self.assertEqual(P.similarity_recent("Hello  World", ["hello world"]), 1.0)
        self.assertIsNone(P.similarity_recent("x", []))
        self.assertIsNone(P.similarity_recent("   ", ["x"]))

    def test_length_fit_uses_platform_count(self):
        fit = P.length_fit("X", "字" * 141)
        self.assertEqual((fit["unit"], fit["used"]), ("x-weighted", 282))
        self.assertEqual((fit["limit"], fit["status"], fit["over_by"]), (280, "over", 2))
        self.assertEqual(P.length_fit("NoSuchPlatform", "abc")["status"], "unknown")


class Confidence(unittest.TestCase):
    def test_steps(self):
        good = judgment(all_answers())
        self.assertEqual(P.confidence(QS, good, calibrated=False, posts_with_metrics=50)[0], "low")
        self.assertEqual(P.confidence(QS, good, calibrated=True, posts_with_metrics=9), ("medium", ("few_measured_posts",)))
        self.assertEqual(P.confidence(QS, good, calibrated=True, posts_with_metrics=10), ("high", ()))
        fallback = judgment(all_answers(), calibrated=False)
        self.assertEqual(P.confidence(QS, fallback, calibrated=True, posts_with_metrics=10), ("low", ("fallback_model",)))

    def test_drops_a_step_when_over_a_third_abstain(self):
        names = QS.names
        probs = {n: (0.5 if i < len(names) // 3 + 1 else 0.9) for i, n in enumerate(names)}
        level, reasons = P.confidence(QS, judgment(probs), calibrated=True, posts_with_metrics=10)
        self.assertEqual((level, reasons[-1]), ("medium", "many_abstained"))


class FakeJev:
    def __init__(self, outcome):
        self.outcome, self.states = outcome, []

    def evaluate(self, state, questions, *, timeout_s):
        self.states.append(state)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        answers = {n: {"type": "boolean", "probability": p} for n, p in all_answers().items()}
        return J.RawEvaluation("typesafe-ai/jev", answers, 1, 1, 0.00001, "gateway", "g", "typesafe-ai", 5)


def profile(groups, *, accepted=True, model="typesafe-ai/jev", thresholds=(0.95, 0.97, 0.99), dims=None):
    """A SYNTHETIC calibration profile shaped like golden.calibration_profile output."""
    dims = list(QS.dimensions) if dims is None else dims
    entry = {"thresholds": list(thresholds), "isotonic": {"x": [0.2, 0.9], "y": [0.1, 0.8]}, "n": 50, "kappa_cv": 0.7,
             "ece_cv": 0.05, "accepted": accepted, "reasons": []}
    return {"version": P.PROFILE_VERSION, "question_set": QS.key, "digest": QS.digest, "model": model,
            "languages": {g: {d: dict(entry) for d in dims} for g in groups}}


def service(outcome, env=ON, profile=None):
    jev = FakeJev(outcome)
    router = R.AIModelRouter(jev=jev, sleep=lambda s: None)
    return P.PostDoctorService(JudgmentService(router.evaluator(P.TASK)), env=env, profile=profile), jev


class Service(unittest.TestCase):
    def test_flag_defaults_off(self):
        svc, jev = service(None, env={})
        with self.assertRaises(P.PostDoctorDisabled):
            svc.check(workspace_id="ws1", draft_text="hi", platform="X", lang="en")
        self.assertEqual(jev.states, [])
        self.assertFalse(P.enabled({P.FLAG: "true"}))

    def test_check_end_to_end_and_private_cache(self):
        svc, jev = service(None, profile=profile(["en"], thresholds=(0.35, 0.55, 0.75)))
        creator = {"niche": "piano", "secret": {"nested": 1}, "flag": True}
        result = svc.check(workspace_id="ws1", draft_text="I practised three hours today.", platform="X", lang="en",
                           creator=creator, recent_texts=["I practised three hours today!"], posts_with_metrics=3)
        self.assertEqual(len(result.dimensions), 9)
        self.assertTrue(all(d.calibrated for d in result.dimensions))
        hook = result.dimensions[0]
        self.assertAlmostEqual(hook.p_strong, round(0.1 + 0.7 * (hook.score - 0.2) / 0.7, 4))   # the shipped calibrator
        self.assertEqual(result.confidence, "medium")
        self.assertGreater(result.computed["similarity_recent"], 0.8)
        self.assertIsNone(result.computed["fit_winners"])
        self.assertEqual(jev.states[0]["creator"], {"niche": "piano"})
        self.assertTrue(result.judgment.cache_key.startswith("personal:ws1|"))
        again = svc.check(workspace_id="ws1", draft_text="I practised three hours today.", platform="X", lang="en",
                          creator=creator)
        self.assertTrue(again.judgment.cached)
        self.assertEqual(len(jev.states), 1)

    def test_without_profile_confidence_stays_low(self):
        svc, _ = service(None)
        result = svc.check(workspace_id="ws1", draft_text="draft", platform="X", lang="en", posts_with_metrics=50)
        self.assertEqual((result.confidence, result.confidence_reasons), ("low", ("uncalibrated_language",)))
        self.assertFalse(any(d.calibrated for d in result.dimensions))

    def test_timeout_keeps_scoring_available_with_abstention(self):
        svc, _ = service(J.JevTimeout("slow"), profile=profile(["en"]))
        result = svc.check(workspace_id="ws1", draft_text="draft", platform="X", lang="en", posts_with_metrics=50)
        self.assertTrue(all(d.level is None and not d.calibrated for d in result.dimensions))
        self.assertEqual(result.risks, ())
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.confidence_reasons, ("judge_timeout", "uncalibrated_language", "many_abstained"))
        self.assertIsNotNone(result.computed["length_fit"])

    def test_language_groups_share_a_fit_but_languages_never_borrow(self):
        svc, _ = service(None, profile=profile(["zh-Hant"]))
        hk = svc.check(workspace_id="ws1", draft_text="今日練琴", platform="X", lang="zh-HK")
        tw = svc.check(workspace_id="ws1", draft_text="今天練琴", platform="X", lang="zh-TW")
        en = svc.check(workspace_id="ws1", draft_text="today", platform="X", lang="en")
        self.assertEqual((hk.dimensions[2].level, hk.dimensions[2].calibrated), (0, True))   # zh-Hant fit applies to zh-HK
        self.assertEqual(tw.dimensions[2].level, 0)
        self.assertEqual((en.dimensions[2].level, en.dimensions[2].calibrated, en.confidence), (3, False, "low"))

    def test_only_accepted_dimensions_and_the_profiled_model(self):
        partial = profile(["en"], dims=["hook"])
        svc, _ = service(None, profile=partial)
        result = svc.check(workspace_id="ws1", draft_text="x", platform="X", lang="en", posts_with_metrics=50)
        self.assertEqual([d.id for d in result.dimensions if d.calibrated], ["hook"])
        self.assertEqual(result.confidence, "low")
        self.assertIn("partly_calibrated", result.confidence_reasons)
        rejected, _ = service(None, profile=profile(["en"], accepted=False))
        self.assertFalse(any(d.calibrated for d in rejected.check(workspace_id="ws1", draft_text="y", platform="X", lang="en").dimensions))
        other, _ = service(None, profile=profile(["en"], model="google/gemini-2.5-flash-lite"))
        self.assertFalse(any(d.calibrated for d in other.check(workspace_id="ws1", draft_text="z", platform="X", lang="en").dimensions))

    def test_profile_for_another_rubric_or_malformed_is_refused(self):
        stale = profile(["en"])
        stale["digest"] = "0" * 64
        with self.assertRaises(ValueError):
            service(None, profile=stale)
        for breakage in ({"isotonic": None}, {"isotonic": {"x": [0.9, 0.2], "y": [0.1, 0.8]}}, {"thresholds": [0.9, 0.5, 0.7]},
                         {"isotonic": [0.1, 0.2]}, {"isotonic": "abc"}, {"thresholds": [None, None, None]}, {"thresholds": ["a", "b", "c"]},
                         {"isotonic": {"x": [0.1, 0.2], "y": ["a", "b"]}}, {"isotonic": {"x": [0.1, float("nan")], "y": [0.1, 0.2]}},
                         {"isotonic": {"x": [0.1, 0.2], "y": [0.1, 1.5]}}, {"thresholds": [0.1, 0.2]}):
            bad = profile(["en"])
            bad["languages"]["en"]["hook"].update(breakage)
            with self.subTest(breakage=breakage), self.assertRaises(ValueError):
                service(None, profile=bad)
        for shape in ({"languages": {"en": []}}, {"languages": {"en": {"hook": "x"}}}, {"languages": []}):
            broken = dict(profile(["en"]), **shape)
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                service(None, profile=broken)
        rejected = profile(["en"], accepted=False)
        rejected["languages"]["en"]["hook"]["isotonic"] = None   # an unaccepted fit may lack a calibrator
        service(None, profile=rejected)
        old = dict(profile(["en"]), version=1)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            service(None, profile=old)

    def test_only_a_literal_true_accepts_a_fit(self):
        truthy = profile(["en"])
        for d in truthy["languages"]["en"].values():
            d.update(accepted=1, thresholds="abc", isotonic=None)   # skipped by validation, so it must not be applied
        svc, _ = service(None, profile=truthy)
        result = svc.check(workspace_id="ws1", draft_text="x", platform="X", lang="en")
        self.assertFalse(any(d.calibrated for d in result.dimensions))


if __name__ == "__main__":
    unittest.main()
