"""SYNTHETIC FIXTURES ONLY: every row below is generated for tests and is not a creator label."""
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from postriff_phase2.growth import compare as C
from postriff_phase2.growth import golden as G
from postriff_phase2.growth import jev as J
from postriff_phase2.growth import questions as Q
from postriff_phase2.growth.judgments import Judgment, validate_answers

QS = Q.get("postdoctor")
TEMPLATE = Path(__file__).resolve().parents[1] / "docs/design/growth-phase0/golden-template.csv"
HEADER = list(G.REQUIRED) + ["better_than", "notes"]
POSITIVE = {n for n in QS.names if not n.startswith("risk_")}
INVERTED = {i["q"] for d in QS.dimensions.values() for i in d["items"] if i.get("invert")}


def write_csv(rows, header=HEADER):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    handle.close()
    return handle.name


def synthetic_row(i, level, lang):
    row = {"id": f"syn{i}", "platform": "threads", "lang": lang, "kind": "post",
           "text": f"synthetic fixture {i}", "notes": "SYNTHETIC FIXTURE"}
    row.update({d: str(level + 1) for d in G.DIMENSIONS})
    return row


def judgment_for(level, latency=10, cost=0.00001):
    p = (0.2, 0.47, 0.67, 0.9)[level]     # score lands in the level's default band
    raw = {}
    for n in QS.names:
        value = 0.05 if n.startswith("risk_") else (1 - p if n in INVERTED else p)
        raw[n] = {"type": "boolean", "probability": value}
    answers, invalid = validate_answers(QS, raw)
    return Judgment(QS.key, QS.digest, "typesafe-ai/jev", "primary", True, answers, invalid, cost, "gateway", None,
                    latency, "k")


class Parse(unittest.TestCase):
    def test_template_is_structurally_valid_but_warned(self):
        out = io.StringIO()
        self.assertEqual(G.main(["validate", str(TEMPLATE)], out=out), 0)
        self.assertIn("the plan needs about 200", out.getvalue())
        self.assertIn("no en rows", out.getvalue())

    def test_problems_carry_line_numbers(self):
        rows = [synthetic_row(1, 2, "en"), synthetic_row(1, 2, "en"), synthetic_row(3, 2, "zh-HK"),
                synthetic_row(4, 2, "en"), synthetic_row(5, 1, "en")]
        rows[2]["hook"] = "5"
        rows[3]["text"] = ""
        rows[4]["better_than"] = "nope"
        path = write_csv(rows)
        self.addCleanup(os.unlink, path)
        loaded, problems, _ = G.parse(path)
        lines = {line: msg for line, msg in problems}
        self.assertIn("duplicate id", lines[3])
        self.assertIn("hook must be 1-4", lines[4])
        self.assertIn("text is empty", lines[5])
        self.assertIn("better_than", lines[6])
        self.assertEqual([r.id for r in loaded], ["syn1"])
        self.assertEqual(loaded[0].labels["hook"], 2)   # CSV 3 -> level 2
        out = io.StringIO()
        self.assertEqual(G.main(["validate", path], out=out), 1)
        with self.assertRaises(ValueError):
            G.load(path)

    def test_missing_column_and_blank_labels(self):
        path = write_csv([{"id": "a"}], header=["id", "text"])
        self.addCleanup(os.unlink, path)
        self.assertIn("missing columns", G.parse(path)[1][0][1])
        row = synthetic_row(1, 0, "en")
        row["hook"] = ""
        path = write_csv([row])
        self.addCleanup(os.unlink, path)
        self.assertIsNone(G.load(path)[0].labels["hook"])

    def test_lang_groups(self):
        self.assertEqual([G.lang_group(t) for t in ("zh-HK", "zh-TW", "zh-Hant-HK", "en-GB", "ja")],
                         ["zh-Hant", "zh-Hant", "zh-Hant", "en", "ja"])


class Evaluate(unittest.TestCase):
    def setUp(self):
        raw = [synthetic_row(i, i % 4, "zh-HK" if i % 2 else "en") for i in range(80)]
        path = write_csv(raw)
        self.addCleanup(os.unlink, path)
        self.rows = G.load(path)
        self.judgments = {r.id: judgment_for(r.labels["hook"], latency=10 + i) for i, r in enumerate(self.rows)}

    def test_perfect_agreement_per_language(self):
        report = G.evaluate(self.rows, self.judgments, QS)
        hook = report["dimensions"]["hook"]
        self.assertAlmostEqual(hook["kappa"], 1.0)
        self.assertEqual(set(hook["by_lang"]), {"zh-Hant", "en"})
        fit = hook["by_lang"]["en"]["fit"]
        self.assertEqual(len(fit["thresholds"]), 3)
        self.assertAlmostEqual(fit["kappa_cv"], 1.0)
        self.assertEqual(report["latency_ms"], {"p50": 49, "p95": 85})
        self.assertEqual(report["cost_usd"], {"known": 0.0008, "unknown_calls": 0})
        # Level-1 fixtures use p=0.47, inside the abstain band: those 20 rows abstain on all 24 rubric questions
        # (risk answers at 0.05 stay usable), so they are reported as abstained, never scored as "no".
        self.assertEqual((hook["scored"], hook["abstained"]), (60, 20))
        self.assertEqual(report["question_abstain_rate"], round(20 * 24 / (80 * 28), 4))

    def test_missing_and_too_few(self):
        report = G.evaluate(self.rows[:6], {self.rows[0].id: self.judgments[self.rows[0].id]}, QS)
        hook = report["dimensions"]["hook"]
        self.assertEqual((hook["scored"], hook["missing_judgment"]), (1, 5))
        self.assertEqual(next(iter(hook["by_lang"].values()))["fit"]["reason"], "too_few")


class FakeJev:
    def __init__(self, calls):
        self.calls = calls

    def evaluate(self, state, questions, *, timeout_s):
        self.calls.append("jev")
        answers = {n: {"type": "boolean", "probability": 0.9} for n in questions}
        return J.RawEvaluation("typesafe-ai/jev", answers, 10, 10, 0.004, "gateway", "g", "typesafe-ai", 5)


class Compare(unittest.TestCase):
    def setUp(self):
        path = write_csv([synthetic_row(i, i % 4, "zh-HK" if i % 2 else "en") for i in range(10)])
        self.addCleanup(os.unlink, path)
        self.labels = path
        self.calls = []

        def chat(messages, model, max_tokens, timeout_s=None):
            self.calls.append(model)
            answers = {n: {"type": "boolean", "probability": 0.8} for n in QS.names}
            return json.dumps({"answers": answers}), {"gatewayCost": 0.003}
        self.factories = (lambda: FakeJev(self.calls), chat)

    def args(self, *extra):
        return ["--labels", self.labels, "--models", "jev,claude-haiku-4.5", "--price", "jev=1,5", *extra]

    def test_dry_run_makes_no_calls(self):
        out = io.StringIO()
        code = C.main(self.args("--max-usd", "20"), env={"AI_GATEWAY_API_KEY": "sk-secret"}, out=out,
                      factories=self.factories)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertIn("dry run", out.getvalue())
        self.assertNotIn("sk-secret", out.getvalue())

    def test_unknown_price_is_refused(self):
        out = io.StringIO()
        code = C.main(["--labels", self.labels, "--models", "jev", "--max-usd", "20"], env={}, out=out)
        self.assertEqual(code, 2)
        self.assertIn("no price for typesafe-ai/jev", out.getvalue())

    def test_estimate_over_cap_aborts_before_first_call(self):
        out = io.StringIO()
        code = C.main(self.args("--max-usd", "0.000001", "--confirm-live", "--out", "x.json"), env={}, out=out,
                      factories=self.factories)
        self.assertEqual(code, 3)
        self.assertEqual(self.calls, [])

    def test_live_run_with_fakes_stops_at_recorded_cap(self):
        rows, qs = G.load(self.labels), QS
        models = ["typesafe-ai/jev", "anthropic/claude-haiku-4.5"]
        costs = C.estimate(rows, qs, models, {"typesafe-ai/jev": (1, 5), "anthropic/claude-haiku-4.5": (1, 5)})
        report = C.run(rows, qs, models, jev_factory=self.factories[0], chat=self.factories[1], max_usd=0.05,
                       costs=costs)
        self.assertLessEqual(report["spend"]["known_usd"], 0.05)
        self.assertEqual(report["stopped_at_cap"]["model"], "anthropic/claude-haiku-4.5")
        self.assertEqual(self.calls.count("jev"), 10)
        self.assertIn("anthropic/claude-haiku-4.5", report["results"])

    def test_live_run_writes_report(self):
        out, target = io.StringIO(), tempfile.mktemp(suffix=".json")
        self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))
        code = C.main(self.args("--max-usd", "20", "--confirm-live", "--out", target), env={}, out=out,
                      factories=self.factories)
        self.assertEqual(code, 0)
        with open(target, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(set(report["results"]), {"typesafe-ai/jev", "anthropic/claude-haiku-4.5"})
        self.assertIsNone(report["stopped_at_cap"])
        self.assertAlmostEqual(report["spend"]["known_usd"], 0.07)


if __name__ == "__main__":
    unittest.main()
