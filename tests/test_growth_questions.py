import copy
import json
import tempfile
import unittest
from pathlib import Path

from postriff_phase2.growth import questions as Q

GOOD = {"id": "demo", "version": 1, "questions": {
    "flag": {"type": "boolean", "instructions": "Is it true?"},
    "pick": {"type": "choice", "instructions": "Pick one.", "criteria": {"a": "A", "unsure": "cannot tell"}},
    "rate": {"type": "score", "instructions": "Rate it.", "criteria": ["low", "high"]}},
    "dimensions": {"d": {"items": [{"q": "flag", "weight": 1.0}, {"q": "rate", "weight": 0.5, "invert": True}]}},
    "risks": {"flag": {"en": "x"}},
    "levels": {"thresholds": [0.4, 0.7], "names": {"en": ["Low", "Mid", "High"]}}}


class Parse(unittest.TestCase):
    def test_good_set_and_payload(self):
        qs = Q.parse(GOOD)
        self.assertEqual(qs.key, "demo.v1")
        self.assertEqual(qs.names, ("flag", "pick", "rate"))
        self.assertEqual(qs.payload_questions(["pick"]), {"pick": {"type": "choice", "instructions": "Pick one.", "criteria": {"a": "A", "unsure": "cannot tell"}}})
        self.assertEqual(qs.question("rate").options(), ("0", "1"))
        self.assertEqual(qs.abstain["boolean_band"], [0.35, 0.65])
        with self.assertRaises(KeyError):
            qs.payload_questions(["missing"])

    def test_digest_changes_with_content(self):
        other = copy.deepcopy(GOOD)
        other["questions"]["flag"]["instructions"] = "Is it really true?"
        self.assertNotEqual(Q.parse(GOOD).digest, Q.parse(other).digest)

    def test_rejections(self):
        cases = []
        def mutate(fn):
            raw = copy.deepcopy(GOOD); fn(raw); cases.append(raw)
        mutate(lambda r: r["questions"]["pick"]["criteria"].pop("unsure"))
        mutate(lambda r: r["questions"]["rate"].__setitem__("criteria", ["only"]))
        mutate(lambda r: r["questions"]["flag"].__setitem__("type", "text"))
        mutate(lambda r: r["questions"]["flag"].__setitem__("extra", 1))
        mutate(lambda r: r.__setitem__("version", 0))
        mutate(lambda r: r["dimensions"]["d"]["items"].append({"q": "pick", "weight": 1}))
        mutate(lambda r: r["dimensions"]["d"]["items"][0].__setitem__("weight", 0))
        mutate(lambda r: r["levels"].__setitem__("thresholds", [0.7, 0.4]))
        mutate(lambda r: r["levels"]["names"].__setitem__("en", ["a", "b"]))
        mutate(lambda r: r.__setitem__("abstain", {"boolean_band": [0.7, 0.3]}))
        mutate(lambda r: r["risks"].__setitem__("pick", {}))
        for raw in cases:
            with self.assertRaises(ValueError):
                Q.parse(raw)

    def test_file_name_must_match(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "demo.v1.json").write_text(json.dumps(GOOD))
            self.assertEqual(Q.get("demo", directory=d).version, 1)
            (Path(d) / "demo.v2.json").write_text(json.dumps(GOOD))
            with self.assertRaises(ValueError):
                Q.registry(d)


class Shipped(unittest.TestCase):
    def test_postdoctor_v1_loads(self):
        qs = Q.get("postdoctor", 1)
        self.assertEqual(len(qs.questions), 28)
        self.assertEqual(set(qs.dimensions), {"hook", "audience", "novelty", "specificity", "shareability", "conversation", "clarity", "emotion", "evidence"})
        self.assertTrue(all(q.type == "boolean" for q in qs.questions))

    def test_estimate_tokens(self):
        self.assertEqual(Q.estimate_tokens("abcd"), 1)
        self.assertEqual(Q.estimate_tokens("琴琴"), 2)
        payload = Q.get("postdoctor", 1).payload_questions()
        self.assertGreater(Q.estimate_tokens(payload), 500)


if __name__ == "__main__":
    unittest.main()
