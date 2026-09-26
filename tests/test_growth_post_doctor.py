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


def service(outcome, env=ON):
    jev = FakeJev(outcome)
    router = R.AIModelRouter(jev=jev, sleep=lambda s: None)
    return P.PostDoctorService(JudgmentService(router.evaluator(P.TASK)), env=env), jev


class Service(unittest.TestCase):
    def test_flag_defaults_off(self):
        svc, jev = service(None, env={})
        with self.assertRaises(P.PostDoctorDisabled):
            svc.check(workspace_id="ws1", draft_text="hi", platform="X", lang="en")
        self.assertEqual(jev.states, [])
        self.assertFalse(P.enabled({P.FLAG: "true"}))

    def test_check_end_to_end_and_private_cache(self):
        svc, jev = service(None)
        creator = {"niche": "piano", "secret": {"nested": 1}, "flag": True}
        result = svc.check(workspace_id="ws1", draft_text="I practised three hours today.", platform="X", lang="en",
                           creator=creator, recent_texts=["I practised three hours today!"], posts_with_metrics=3,
                           calibrated=True)
        self.assertEqual(len(result.dimensions), 9)
        self.assertEqual(result.confidence, "medium")
        self.assertGreater(result.computed["similarity_recent"], 0.8)
        self.assertIsNone(result.computed["fit_winners"])
        self.assertEqual(jev.states[0]["creator"], {"niche": "piano"})
        self.assertTrue(result.judgment.cache_key.startswith("personal:ws1|"))
        again = svc.check(workspace_id="ws1", draft_text="I practised three hours today.", platform="X", lang="en",
                          creator=creator)
        self.assertTrue(again.judgment.cached)
        self.assertEqual(len(jev.states), 1)

    def test_timeout_keeps_scoring_available_with_abstention(self):
        svc, _ = service(J.JevTimeout("slow"))
        result = svc.check(workspace_id="ws1", draft_text="draft", platform="X", lang="en", calibrated=True,
                           posts_with_metrics=50)
        self.assertTrue(all(d.level is None for d in result.dimensions))
        self.assertEqual(result.risks, ())
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.confidence_reasons, ("judge_timeout", "many_abstained"))
        self.assertIsNotNone(result.computed["length_fit"])

    def test_per_language_thresholds_are_not_borrowed(self):
        svc, _ = service(None)
        svc.thresholds = {"en": [0.95, 0.97, 0.99]}
        zh = svc.check(workspace_id="ws1", draft_text="今日練琴", platform="X", lang="zh-HK", calibrated=True)
        en = svc.check(workspace_id="ws1", draft_text="today", platform="X", lang="en", calibrated=True)
        self.assertEqual(zh.dimensions[2].level, 3)
        self.assertEqual(en.dimensions[2].level, 0)


if __name__ == "__main__":
    unittest.main()
