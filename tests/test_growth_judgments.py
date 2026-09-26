import unittest
from dataclasses import dataclass

from postriff_phase2.growth import judgments as JM
from postriff_phase2.growth import questions as Q

QS = Q.parse({"id": "demo", "version": 1, "questions": {
    "flag": {"type": "boolean", "instructions": "Is it true?"},
    "pick": {"type": "choice", "instructions": "Pick.", "criteria": {"a": "A", "b": "B", "unsure": "?"}},
    "rate": {"type": "score", "instructions": "Rate.", "criteria": ["low", "mid", "high"]}}})


@dataclass
class Eval:
    answers: dict
    route: str = "primary"
    model: str = "typesafe-ai/jev"
    calibrated: bool = True
    cost_usd: float | None = 0.0001
    cost_source: str = "gateway"
    generation_id: str | None = "gen_1"
    latency_ms: int = 300


GOOD = {"flag": {"type": "boolean", "probability": 0.9},
        "pick": {"type": "choice", "choice": "a", "probabilities": {"a": 0.8, "b": 0.15, "unsure": 0.05}},
        "rate": {"type": "score", "score": 1.8, "probabilities": {"0": 0.02, "1": 0.16, "2": 0.82}}}


class Validate(unittest.TestCase):
    def test_all_valid(self):
        valid, invalid = JM.validate_answers(QS, GOOD)
        self.assertEqual(invalid, ())
        self.assertAlmostEqual(valid["flag"].value, 0.9)
        self.assertFalse(any(a.abstained for a in valid.values()))

    def test_invalid_shapes(self):
        bad = {
            "flag": {"type": "boolean", "probability": 1.2},
            "pick": {"type": "choice", "choice": "b", "probabilities": {"a": 0.8, "b": 0.15, "unsure": 0.05}},
            "rate": {"type": "score", "score": 1.0, "probabilities": {"0": 0.5, "1": 0.5}},
        }
        valid, invalid = JM.validate_answers(QS, bad)
        self.assertEqual(valid, {})
        self.assertEqual(set(invalid), {"flag", "pick", "rate"})
        _, invalid = JM.validate_answers(QS, {"flag": {"type": "choice"}})
        self.assertEqual(set(invalid), {"flag", "pick", "rate"})
        _, invalid = JM.validate_answers(QS, {**GOOD, "pick": {"type": "choice", "choice": "a", "probabilities": {"a": 0.8, "b": 0.3, "unsure": 0.05}}})
        self.assertEqual(invalid, ("pick",))

    def test_abstain_rules(self):
        answers = {"flag": {"type": "boolean", "probability": 0.5},
                   "pick": {"type": "choice", "choice": "unsure", "probabilities": {"a": 0.2, "b": 0.2, "unsure": 0.6}},
                   "rate": {"type": "score", "score": 1.0, "probabilities": {"0": 0.3, "1": 0.4, "2": 0.3}}}
        valid, invalid = JM.validate_answers(QS, answers)
        self.assertEqual(invalid, ())
        self.assertTrue(all(a.abstained for a in valid.values()))


class Service(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def evaluate(qs, state, workspace_id=None, subject=None):
            self.calls.append(state)
            return Eval(dict(GOOD))
        self.svc = JM.JudgmentService(evaluate)
        self.subject = JM.subject_hash("draft text")

    def test_cache_hit_and_scope(self):
        first = self.svc.judge(QS, {"t": 1}, subject=self.subject, scope="personal:ws1", model="typesafe-ai/jev", workspace_id="ws1")
        second = self.svc.judge(QS, {"t": 1}, subject=self.subject, scope="personal:ws1", model="typesafe-ai/jev", workspace_id="ws1")
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(len(self.calls), 1)
        other = self.svc.judge(QS, {"t": 1}, subject=self.subject, scope="personal:ws2", model="typesafe-ai/jev", workspace_id="ws2")
        self.assertFalse(other.cached)
        self.assertEqual(first.probability("flag"), 0.9)

    def test_personal_scope_must_match_workspace(self):
        with self.assertRaises(ValueError):
            self.svc.judge(QS, {}, subject=self.subject, scope="personal:ws2", model="m", workspace_id="ws1")
        with self.assertRaises(ValueError):
            JM.cache_key("everyone", self.subject, QS, "m")
        with self.assertRaises(ValueError):
            JM.cache_key("shared", "not-a-hash", QS, "m")

    def test_invalid_not_cached_and_fallback_uncalibrated(self):
        def evaluate(qs, state, workspace_id=None, subject=None):
            return Eval({"flag": {"type": "boolean", "probability": 0.9}}, route="fallback", calibrated=True)
        svc = JM.JudgmentService(evaluate)
        j = svc.judge(QS, {}, subject=self.subject, scope="shared", model="m")
        self.assertEqual(set(j.invalid), {"pick", "rate"})
        self.assertFalse(j.calibrated)
        self.assertEqual(svc.cache.items, {})


if __name__ == "__main__":
    unittest.main()
