"""Lane G — self-tests of the acceptance tooling (no DB, no Agents SDK; loopback only): release mode, the live runner's
guards and evidence rules, the fixture provider's wire format, the gate summary and the check recorder.

A harness that can pass vacuously is worse than none, so each rule that keeps evidence honest has a negative here: stale or
blocked or mock evidence never satisfies a gate, the live runner refuses credentials on argv and never writes one, unknown
cost is never zero, and the fixture provider's stream is a faithful Responses/Chat Completions stream with usage.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from agent_ui_acceptance import corpus, evidence, fake_provider, release, summarize
from agent_ui_acceptance.client import Api
from agent_ui_acceptance.sse import SseReader, parse_all
from agent_ui_acceptance.world import Blocked, recorded

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
OTHER_SHA = "b" * 40
UUID = "6c1f2f3e-1111-4222-8333-944455556666"


def _live():
    spec = importlib.util.spec_from_file_location("agent_ui_live", ROOT / "scripts/agent_ui_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIVE = _live()


def rec(gate, status, kind, sha=SHA):
    return {"gate": gate, "status": status, "candidateSha": sha, "environment": {"kind": kind}}


def passing_records(sha=SHA):
    out = []
    for gate, spec in corpus.GATES.items():
        for group in spec["kinds"]:
            out.append(rec(gate, "pass", group[0], sha))
    return out


def matrix(status="pass", sha=SHA, gates=None):
    return {"candidate_sha": sha, "gates": [{"id": g, "required": True, "status": status, "candidate_sha": sha, "evidence": []} for g in (gates or corpus.GATES)]}


def ingest_sample(plan):
    """A complete CI-fake browser collection + server rows for every normal case of the plan: each first pass ready."""
    browser = {"cases": {}, "marks": [], "resources": []}
    rows = []
    for index, case in enumerate(plan["normal"]):
        artifact = f"00000000-0000-4000-8000-{index:012d}"
        browser["cases"][case["caseId"]] = {"begunAt": index * 1000}
        browser["resources"].append({"caseId": case["caseId"], "route": "/api/workspaces/:id/agent/turns", "start": 0.0})
        browser["resources"].append({"caseId": case["caseId"], "route": "/api/workspaces/:id/agent/ui/presentations", "start": 100.0})
        browser["marks"] += [{"caseId": case["caseId"], "name": "rafii-genui:first-component", "at": 2100.0, "artifactId": artifact},
                             {"caseId": case["caseId"], "name": "rafii-genui:ready", "at": 9100.0, "artifactId": artifact, "revision": 1}]
        rows.append({"artifact_id": artifact, "kind": "generate", "state": "ready", "accepted": True, "provider_attempts": 1, "cost_usd_micro": 900,
                     "cost_state": "known", "admitted_at": "2026-10-09T10:00:00Z", "first_delta_at": "2026-10-09T10:00:01.5Z", "ready_at": "2026-10-09T10:00:08Z"})
    return browser, rows


# D-A53 (James, 2026-10-09): the G03 corpus is fixed before any measurement. Its first 30 cases, 9 edits and 3 faults are the
# v1 plan byte for byte (fixtures/g03-corpus-v1.json, printed by `agent_ui_live.py plan` at de4e5907); the hash below freezes all
# 60 normal cases. A changed, dropped, replaced or reordered case is a new corpus: it needs a new decision and a new id, and
# results measured on different corpora are never pooled.
G03_CORPUS_V1 = json.loads((Path(__file__).resolve().parent / "fixtures" / "g03-corpus-v1.json").read_text(encoding="utf-8"))
G03_CORPUS_SHA256 = "703b54cdb40eb8abb3b5f4d8b82a1d9ca46779a327ee72b88adc47ba34721ff0"
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
JOURNEYS = tuple(f"J0{i}" for i in range(1, 10))


class ReleaseMode(unittest.TestCase):
    def run_check(self, records, mtx=None, candidate=SHA):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "acceptance.json").write_text(json.dumps(mtx or matrix()))
            Path(tmp, "results").mkdir()
            Path(tmp, "results", "r.json").write_text(json.dumps({"records": records}))
            return release.check(candidate, Path(tmp, "acceptance.json"), [Path(tmp, "results")], verify_git=False)

    def status_of(self, report, gate):
        return next(g for g in report["gates"] if g["gate"] == gate)["status"]

    def test_complete_evidence_for_the_candidate_passes(self):
        report = self.run_check(passing_records())
        self.assertTrue(report["ok"], [g for g in report["gates"] if g["status"] != "pass"][:3])

    def test_stale_blocked_failed_absent_and_unverified_never_pass(self):
        records = [r for r in passing_records() if r["gate"] not in ("G03", "G04", "G05", "G06", "G07")]
        records += [rec("G03", "pass", "live-provider", OTHER_SHA), rec("G03", "pass", "production-canary", OTHER_SHA)]   # stale
        records += [rec("G04", "blocked", "production-canary")]                                                            # blocked
        records += [rec("G05", "fail", "ci-harness"), rec("G05", "pass", "production-canary")]                            # fail
        records += [rec("G06", "pass", "contract")]                                                                       # wrong kind → absent
        mtx = matrix()
        next(g for g in mtx["gates"] if g["id"] == "G07")["status"] = "unverified"
        records += [rec("G07", "pass", "ci-harness")]
        report = self.run_check(records, mtx)
        self.assertFalse(report["ok"])
        self.assertEqual(self.status_of(report, "G03"), "stale")
        self.assertEqual(self.status_of(report, "G04"), "blocked")
        self.assertEqual(self.status_of(report, "G05"), "fail")
        self.assertEqual(self.status_of(report, "G06"), "absent")
        self.assertEqual(self.status_of(report, "G07"), "unverified")

    def test_mock_or_emulation_never_satisfies_live_device_or_deployment_gates(self):
        for gate, kind in (("G03", "ci-harness"), ("G04", "ci-browser-emulation"), ("G15", "ci-browser-emulation"), ("G24", "preview-deployment")):
            records = [r for r in passing_records() if r["gate"] != gate] + [rec(gate, "pass", kind)]
            with self.subTest(gate=gate, kind=kind):
                report = self.run_check(records)
                self.assertNotEqual(self.status_of(report, gate), "pass")
                self.assertFalse(report["ok"])

    def test_matrix_for_another_sha_is_stale(self):
        report = self.run_check(passing_records(), matrix(sha=OTHER_SHA))
        self.assertFalse(report["ok"])
        self.assertTrue(all(g["status"] == "stale" for g in report["gates"]))

    def test_leaking_or_unreadable_evidence_fails_the_release(self):
        leaky = passing_records()
        leaky[0] = {**leaky[0], "note": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"}
        self.assertFalse(self.run_check(leaky)["ok"])
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "acceptance.json").write_text(json.dumps(matrix()))
            Path(tmp, "results").mkdir()
            Path(tmp, "results", "good.json").write_text(json.dumps(passing_records()))
            Path(tmp, "results", "bad.json").write_text("{not json")
            report = release.check(SHA, Path(tmp, "acceptance.json"), [Path(tmp, "results")], verify_git=False)
            self.assertFalse(report["ok"])
            self.assertTrue(report["unreadable"])

    def test_missing_gate_in_matrix_fails(self):
        report = self.run_check(passing_records(), matrix(gates=[g for g in corpus.GATES if g != "G25"]))
        self.assertIn("G25", report["gatesMissingFromMatrix"])
        self.assertFalse(report["ok"])

    def test_code_under_test(self):
        head = release.code_under_test("0" * 40)
        self.assertFalse(head["ok"], "an unknown candidate is never the code under test")
        import subprocess
        current = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if current:
            self.assertTrue(release.code_under_test(current)["ok"])

    def test_the_real_matrix_is_readable_and_currently_not_releasable(self):
        path = ROOT / "docs/design/openui-production-2026-10-08/acceptance.json"
        if not path.exists():
            self.skipTest("JCB snapshots exclude docs/**; GitHub Actions runs this")
        report = release.check(SHA, path, [ROOT / "docs/design/openui-production-2026-10-08/evidence/g/results"], verify_git=False)
        self.assertFalse(report["ok"], "the shipped matrix is unverified; release mode must refuse it")
        self.assertEqual(report["gatesMissingFromMatrix"], [])


class LiveRunnerGuards(unittest.TestCase):
    def args(self, **over):
        values = {"origin": "https://rafii.io", "workspace": UUID, "budget_usd": 2.0}
        values.update(over)
        return type("A", (), values)()

    def refused(self, fn):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            fn()
        self.assertEqual(caught.exception.code, 64)

    def test_plan_is_the_04_acceptance_sample(self):
        plan = LIVE.sample_plan()
        self.assertEqual(len(plan["normal"]), 60)
        self.assertEqual(sum(1 for c in plan["normal"] if c["journey"] == "composite"), 6)
        for j in corpus.GATES:
            if j.startswith("J"):
                self.assertEqual(sum(1 for c in plan["normal"] if c["journey"] == j), 6, j)
        self.assertEqual(sorted(c["journey"] for c in plan["edits"]), [f"J0{i}" for i in range(1, 10)])
        self.assertEqual(len({c["caseId"] for c in plan["normal"] + plan["edits"]}), 69)
        self.assertTrue(all(c["surface"] == "founder" for c in plan["normal"] if c["journey"] == "J09"))
        self.assertEqual(plan["denominators"]["G03"], {"firstPassValidAtLeast": 59, "of": 60, "functionalAfterOneRepair": 60})

    def test_refusals(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.refused(lambda: LIVE.guard_live(self.args(), needs_token=False))
        with mock.patch.dict(os.environ, {"RAFII_LIVE_CHECKS": "1"}, clear=True):
            for bad in ({"origin": None}, {"origin": "http://rafii.io"}, {"origin": "https://rafii.io/app"}, {"origin": "https://u:p@rafii.io"},
                        {"workspace": "not-a-uuid"}, {"workspace": None}, {"budget_usd": None}, {"budget_usd": 0}, {"budget_usd": 1000}):
                with self.subTest(bad=bad):
                    self.refused(lambda: LIVE.guard_live(self.args(**bad), needs_token=False))
            self.refused(lambda: LIVE.guard_live(self.args(), needs_token=True))
            self.assertIsNone(LIVE.guard_live(self.args(), needs_token=False))
            self.assertIsNone(LIVE.guard_live(self.args(origin="http://127.0.0.1:4538"), needs_token=False))
        with mock.patch.dict(os.environ, {"RAFII_LIVE_CHECKS": "1", LIVE.TOKEN_ENV: "x" * 40}, clear=True):
            self.assertEqual(LIVE.guard_live(self.args(), needs_token=True), "x" * 40)

    def test_credentials_on_argv_are_refused(self):
        for item in ("Bearer abcdefghijklmnopqrstuv", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIx", "sk-proj-abcdefghijkl", "dev:" + UUID, "--token=prt_abcdefghijkl"):
            with self.subTest(item=item[:12]):
                self.refused(lambda: LIVE.guard_argv(["run", "--origin", "https://rafii.io", item]))
        self.refused(lambda: LIVE.main(["run", "--origin", "https://rafii.io", "Bearer abcdefghijklmnopqrstuvwxyz"]))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            LIVE.main(["run", "--token", "abc"])     # there is no --token option at all

    def test_unknown_cost_is_never_zero_and_the_cap_stops_the_run(self):
        budget = LIVE.Budget(0.10, 0.06)
        self.assertTrue(budget.admit())
        budget.charge(None)
        self.assertAlmostEqual(budget.spent, 0.06)
        self.assertFalse(budget.admit(), "the next case would cross the cap")
        self.assertEqual(budget.report()["unknownCostCases"], 1)

    def test_evidence_is_redacted_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                LIVE.write_evidence({"note": "Bearer abcdefghijklmnopqrstuvwxyz0123"}, Path(tmp, "x.json"), SHA)
            with self.assertRaises(ValueError):
                LIVE.write_evidence({"canonicalSource": "root = RafiiRoot([])"}, Path(tmp, "y.json"), SHA)
            path = LIVE.write_evidence({"sourceHash": "a" * 64, "dataScope": LIVE.scope_hash(UUID)}, Path(tmp, "z.json"), SHA)
            self.assertTrue(path.exists())
            self.assertNotIn(UUID, path.read_text())

    def test_server_sql_exports_no_source_or_text(self):
        sql = LIVE.SERVER_SQL.lower()
        for column in ("checkpoint_source", "r.source,", "fallback_text", "canonical", "instruction", "safe_state", "manifest", "payload", "body"):
            self.assertNotIn(column, sql, column)
        for column in ("admitted_at", "first_delta_at", "ready_at", "provider_attempts", "cost_usd_micro", "cost_state", "source_hash"):
            self.assertIn(column, sql)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            LIVE.main(["server-sql", "--workspace", "x'; drop table y; --", "--since", "2026-10-09T00:00:00Z"])

    def test_browser_snippet_returns_timings_not_tokens(self):
        snippet = LIVE.BROWSER_SNIPPET
        for name in ("rafii-genui:first-component", "rafii-genui:ready", "collect()", "probe(workspaceId)", "TextDecoder", "stream: true"):
            self.assertIn(name, snippet)
        self.assertEqual(snippet.count("access_token"), 1, "the session is read once, inside the page, for the probe request only")
        self.assertNotIn("return token", snippet)
        self.assertNotIn("localStorage.setItem", snippet)

    def test_ingest_verdicts(self):
        plan = LIVE.sample_plan()
        browser, rows = ingest_sample(plan)
        rows[3] = {**rows[3], "state": "failed", "reason": "parse_rejected"}
        rows.append({**rows[3], "kind": "repair", "state": "ready", "reason": None})
        browser["probe"] = {"ok": True, "frames": [{"at": 10, "event": "ui.started", "multibyte": False}, {"at": 1510, "event": "ui.delta", "multibyte": True},
                                                   {"at": 3010, "event": "ui.ready", "multibyte": False}], "endedAt": 3020, "splitInsideCharacter": True}
        out = LIVE.ingest(browser, rows, plan)
        v = out["verdicts"]
        self.assertEqual(v["G03"]["status"], "pass", v["G03"])
        self.assertEqual(v["G03"]["firstPassValid"], 59)
        self.assertEqual(v["G17"]["status"], "pass")
        self.assertEqual(v["G17"]["firstUsefulComponentP95Ms"], 2000.0)
        self.assertEqual(v["G04"]["status"], "pass")
        self.assertEqual(v["G10-live"]["status"], "unverified")
        self.assertEqual(len(v["G10-live"]["missingCases"]), 9)
        self.assertEqual(v["G05"]["status"], "unverified", "no filter check was collected: never assumed")
        records = LIVE.gate_records(v, sha=SHA, origin="https://rafii.io", data_scope=LIVE.scope_hash(UUID), evidence_path="evidence/g/live-x.json")
        kinds = {(r["gate"], r["environment"]["kind"]): r["status"] for r in records}
        self.assertEqual(kinds[("G03", "live-provider")], "pass")
        self.assertEqual(kinds[("G03", "production-canary")], "pass")
        self.assertEqual(kinds[("G10", "live-provider")], "unverified")
        self.assertTrue(all(r["candidateSha"] == SHA for r in records))
        del browser["cases"]["J05-b"]
        short = LIVE.ingest(browser, rows, plan)["verdicts"]["G03"]
        self.assertEqual(short["status"], "unverified")
        self.assertEqual(short["missingCases"], ["J05-b"])

    def test_ingest_counts_the_fixed_corpus_only(self):
        plan = LIVE.sample_plan()
        browser, rows = ingest_sample(plan)
        out = LIVE.ingest(browser, rows, plan)
        g03 = out["verdicts"]["G03"]
        self.assertEqual((g03["status"], g03["firstPassValid"], g03["functional"], g03["required"]), ("pass", 60, 60, 60))
        self.assertEqual(g03["firstPassValidAtLeast"], 59)
        self.assertEqual(g03["corpus"], {"id": plan["corpus"]["id"], "sha256": plan["corpus"]["sha256"]})
        self.assertEqual(out["verdicts"]["G17"]["coldCase"], "J01-a", "the cold case is the first case run, not the first id alphabetically")
        self.assertEqual([c["caseId"] for c in out["cases"]][:4], ["J01-a", "J01-b", "J01-c", "J01-d"], "evidence lists cases in run order")

        one_miss = [dict(r) for r in rows]
        one_miss[3] = {**one_miss[3], "state": "failed", "reason": "parse_rejected"}
        one_miss.append({**one_miss[3], "kind": "repair", "state": "ready", "reason": None})
        self.assertEqual(LIVE.ingest(browser, one_miss, plan)["verdicts"]["G03"]["status"], "pass", "59/60 first pass, 60/60 functional")

        two_misses = [dict(r) for r in one_miss]
        two_misses[40] = {**two_misses[40], "state": "failed", "reason": "parse_rejected"}
        two_misses.append({**two_misses[40], "kind": "repair", "state": "ready", "reason": None})
        v = LIVE.ingest(browser, two_misses, plan)["verdicts"]["G03"]
        self.assertEqual((v["status"], v["firstPassValid"], v["functional"]), ("fail", 58, 60))

        unrepaired = [dict(r) for r in rows]
        unrepaired[7] = {**unrepaired[7], "state": "failed", "reason": "parse_rejected"}
        v = LIVE.ingest(browser, unrepaired, plan)["verdicts"]["G03"]
        self.assertEqual((v["status"], v["firstPassValid"], v["functional"]), ("fail", 59, 59), "every case must be functional after one repair")

        # A replacement case is never counted: the planned case stays missing (or failed) and the extra id is reported.
        replaced = json.loads(json.dumps(browser))
        del replaced["cases"]["J05-b"]
        replaced["cases"]["J05-b2"] = {"begunAt": 1}
        for item in replaced["marks"] + replaced["resources"]:
            if item["caseId"] == "J05-b":
                item["caseId"] = "J05-b2"
        v = LIVE.ingest(replaced, rows, plan)["verdicts"]["G03"]
        self.assertEqual((v["status"], v["missingCases"], v["unplannedCases"], v["normalCases"]), ("unverified", ["J05-b"], ["J05-b2"], 59))
        v = LIVE.ingest(replaced, unrepaired, plan)["verdicts"]["G03"]
        self.assertEqual(v["status"], "fail", "a known unrepaired failure fails the gate even while another case is missing")

        # A case re-run under the same id (two artifacts in one case) never counts as first-pass valid.
        rerun = json.loads(json.dumps(browser))
        rerun["marks"].append({"caseId": "J02-c", "name": "rafii-genui:ready", "at": 19100.0, "artifactId": "00000000-0000-4000-8000-999999999999", "revision": 1})
        v = LIVE.ingest(rerun, rows, plan)["verdicts"]["G03"]
        self.assertEqual((v["repeatedCases"], v["firstPassValid"], v["status"]), (["J02-c"], 59, "pass"))
        rerun["marks"].append({"caseId": "J06-e", "name": "rafii-genui:ready", "at": 19100.0, "artifactId": "00000000-0000-4000-8000-999999999998", "revision": 1})
        self.assertEqual(LIVE.ingest(rerun, rows, plan)["verdicts"]["G03"]["status"], "fail")

    def test_api_mode_runs_each_conversation_in_order_and_threads_its_id(self):
        plan = LIVE.sample_plan()
        calls = []

        def fake_case(api, token, workspace, case, budget, conversation_id=None):
            calls.append((case["caseId"], conversation_id))
            return {"caseId": case["caseId"], "status": "ready", "_conversationId": conversation_id or f"conv-{case['caseId']}"}
        cases, founder = LIVE.run_conversations(None, "t" * 30, UUID, plan, None, LIVE.Budget(5.0, 0.07), case_fn=fake_case)
        self.assertEqual(calls[:7], [("J01-a", None), ("J01-b", "conv-J01-a"), ("J01-c", "conv-J01-a"), ("J01-d", None), ("J01-e", "conv-J01-d"),
                                     ("J01-f", "conv-J01-d"), ("J02-a", None)])
        self.assertEqual(len(cases), 54)
        self.assertTrue(all("_conversationId" not in c for c in cases), "conversation ids never reach evidence")
        self.assertEqual(founder, [f"J09-{x}" for x in "abcdef"], "founder cases need the founder surface")
        calls.clear()
        cases, founder = LIVE.run_conversations(None, "t" * 30, UUID, plan, {"J03-e", "J09-a"}, LIVE.Budget(5.0, 0.07), case_fn=fake_case)
        self.assertEqual((calls, founder), ([("J03-e", None)], ["J09-a"]))

    def test_ingest_end_to_end_writes_evidence_and_records(self):
        plan = LIVE.sample_plan()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"RAFII_LIVE_CHECKS": "1"}):
            Path(tmp, "consumer.json").write_text(json.dumps({"cases": {"J01-a": {}}, "marks": [], "resources": [], "userAgent": "UA"}))
            Path(tmp, "founder.json").write_text(json.dumps({"cases": {"J09-a": {}}, "marks": [], "resources": []}))
            Path(tmp, "rows.json").write_text("[]")
            code = LIVE.main(["ingest", "--origin", "https://rafii.io", "--workspace", UUID, "--budget-usd", "1", "--sha", SHA, "--out", str(Path(tmp, "live.json")),
                              "--browser-results", str(Path(tmp, "consumer.json")), str(Path(tmp, "founder.json")), "--server-rows", str(Path(tmp, "rows.json"))])
            self.assertEqual(code, 1, "an incomplete sample never exits 0")
            written = json.loads(Path(tmp, "live.json").read_text())
            self.assertEqual({c["caseId"] for c in written["cases"]}, {"J01-a", "J09-a"})
            self.assertNotIn(UUID, json.dumps(written))
            records = json.loads(Path(tmp, "live.records.json").read_text())["records"]
            self.assertTrue(records and all(r["status"] != "pass" for r in records))
        self.assertEqual(plan["normal"][0]["caseId"], "J01-a")


class G03Corpus(unittest.TestCase):
    """D-A53: G03 is measured on a FIXED 60-case live corpus, ≥59/60 first pass and 60/60 functional after at most one repair."""

    @classmethod
    def setUpClass(cls):
        cls.plan = LIVE.sample_plan()
        cls.normal = cls.plan["normal"]
        cls.new = cls.normal[30:]

    def test_exactly_60_normal_cases_with_unique_ids_and_six_per_journey(self):
        self.assertEqual(len(self.normal), 60)
        self.assertEqual(len({c["caseId"] for c in self.normal}), 60)
        for j in JOURNEYS:
            self.assertEqual([c["caseId"] for c in self.normal if c["journey"] == j], [f"{j}-{x}" for x in "abcdef"], j)
        self.assertEqual([c["caseId"] for c in self.normal if c["journey"] == "composite"], [f"CMP-{x}" for x in "abcdef"])
        self.assertTrue(all(set(c) == {"caseId", "journey", "kind", "surface", "prompt"} and c["kind"] == "generate" and c["prompt"].strip()
                            for c in self.normal))
        self.assertEqual({c["surface"] for c in self.normal if c["journey"] == "J09"}, {"founder"})
        self.assertEqual({c["surface"] for c in self.normal if c["journey"] != "J09"}, {"chat"})

    def test_first_30_cases_edits_and_faults_are_byte_identical_to_v1(self):
        def dump(value):
            return json.dumps(value, indent=1, ensure_ascii=False)
        self.assertEqual(len(G03_CORPUS_V1["normal"]), 30)
        self.assertEqual(dump(self.normal[:30]), dump(G03_CORPUS_V1["normal"]))
        self.assertEqual(dump(self.plan["edits"]), dump(G03_CORPUS_V1["edits"]))
        self.assertEqual(dump(self.plan["faults"]), dump(G03_CORPUS_V1["faults"]))

    def test_the_new_cases_are_d_e_f_per_journey_plus_composite(self):
        self.assertEqual([c["caseId"] for c in self.new], [f"{j}-{x}" for j in JOURNEYS for x in "def"] + [f"CMP-{x}" for x in "def"])
        prompts = [c["prompt"] for c in self.normal]
        self.assertEqual(len(set(prompts)), 60, "no prompt is repeated")

    def test_at_least_a_third_of_the_new_cases_are_chinese_and_some_mix_english(self):
        chinese = [c["caseId"] for c in self.new if CJK.search(c["prompt"])]
        self.assertGreaterEqual(3 * len(chinese), len(self.new), chinese)
        mixed = [c["caseId"] for c in self.new if CJK.search(c["prompt"]) and len(re.findall(r"\b[A-Za-z]{2,}\b", c["prompt"])) >= 5]
        self.assertTrue(mixed, "at least one new case mixes English and Chinese")
        self.assertFalse([c["caseId"] for c in self.normal[:30] if CJK.search(c["prompt"])], "v1 had no Chinese cases (unchanged)")

    def test_every_journey_has_a_follow_up_that_runs_as_a_later_turn_of_its_conversation(self):
        follow = self.plan["corpus"]["followUps"]
        self.assertTrue(set(follow) <= {c["caseId"] for c in self.new}, "follow-ups are new cases; v1 cases are unchanged")
        for j in JOURNEYS + ("composite",):
            self.assertTrue(any(c["caseId"] in follow for c in self.new if c["journey"] == j), j)
        for group in self.plan["runOrder"]:
            for position, case_id in enumerate(group["cases"]):
                if case_id in follow:
                    self.assertEqual(group["start"], "new")
                    self.assertGreater(position, 0, f"{case_id} only makes sense after an earlier turn of {group['conversation']}")

    def test_the_corpus_is_frozen_by_hash_and_the_gate_is_59_of_60(self):
        self.assertEqual(self.plan["corpus"]["sha256"], LIVE.corpus_sha256(self.normal))
        self.assertEqual(self.plan["corpus"]["sha256"], G03_CORPUS_SHA256,
                         "the G03 corpus is frozen (D-A53): a changed, dropped, replaced or reordered case needs a new decision and corpus id")
        self.assertEqual(self.plan["corpus"]["normalCases"], 60)
        self.assertEqual(self.plan["corpus"]["decision"], "D-A53")
        self.assertEqual(self.plan["denominators"]["G03"], {"firstPassValidAtLeast": 59, "of": 60, "functionalAfterOneRepair": 60})
        self.assertEqual(LIVE.G03_FIRST_PASS_AT_LEAST, 59)

    def test_the_gate_reads_59_of_60_everywhere_it_is_defined(self):
        pkg = ROOT / "docs/design/openui-production-2026-10-08"
        if not (pkg / "acceptance.json").exists():
            self.skipTest("JCB snapshots exclude docs/**; GitHub Actions runs this")
        gate = next(g for g in json.loads((pkg / "acceptance.json").read_text(encoding="utf-8"))["gates"] if g["id"] == "G03")
        rows = [line for name in ("04-ACCEPTANCE.md", "evidence/g/live-runbook.md")
                for line in (pkg / name).read_text(encoding="utf-8").splitlines() if line.startswith("| G03 |")]
        self.assertEqual(len(rows), 2)
        for text in (gate["pass_criteria"], *rows):
            self.assertIn("59/60", text)
            self.assertIn("60", text.replace("59/60", ""), "every case functional after one repair")
            self.assertNotIn("29/30", text.replace("was 29/30", ""), "the old rule appears only as the amended value")
        self.assertIn(G03_CORPUS_SHA256, gate["required_evidence"])
        decisions = (pkg / "A-DECISIONS.md").read_text(encoding="utf-8")
        self.assertIn("- D-A53 (2026-10-09", decisions)
        self.assertIn(G03_CORPUS_SHA256, decisions)

    def test_run_order_is_deterministic_grouped_per_conversation_and_founder_last(self):
        self.assertEqual(json.dumps(LIVE.sample_plan(), ensure_ascii=False), json.dumps(self.plan, ensure_ascii=False))
        by_id = {c["caseId"]: c for c in self.normal + self.plan["edits"]}
        steps = [case_id for group in self.plan["runOrder"] for case_id in group["cases"]]
        self.assertEqual(sorted(steps), sorted(by_id), "every planned case and edit runs exactly once")
        self.assertEqual(len(steps), len(set(steps)))
        self.assertEqual(steps[0], "J01-a", "the first case run is the cold case")
        self.assertEqual(steps, LIVE.run_sequence(self.plan))
        group_of = {case_id: group for group in self.plan["runOrder"] for case_id in group["cases"]}
        started = []
        for group in self.plan["runOrder"]:
            self.assertEqual({by_id[c]["journey"] for c in group["cases"]}, {group["journey"]}, "one journey per conversation")
            self.assertEqual({by_id[c]["surface"] for c in group["cases"]}, {group["surface"]})
            if group["start"] == "new":
                self.assertNotIn(group["conversation"], started)
                started.append(group["conversation"])
                self.assertTrue(all(by_id[c]["kind"] == "generate" for c in group["cases"]))
            else:
                self.assertIn(group["conversation"], started, "an edit reopens a conversation that already ran")
        for edit in self.plan["edits"]:
            group = group_of[edit["caseId"]]
            self.assertEqual(group["start"], f"reopen {edit['baseCase']}")
            self.assertEqual(group["conversation"], group_of[edit["baseCase"]]["conversation"])
            self.assertGreater(steps.index(edit["caseId"]), steps.index(edit["baseCase"]))
        surfaces = [group["surface"] for group in self.plan["runOrder"]]
        self.assertEqual(surfaces, sorted(surfaces, key=lambda s: s == "founder"), "consumer chat first, then the founder panel once")
        self.assertEqual({c for g in self.plan["runOrder"] if g["surface"] == "founder" for c in g["cases"]},
                         {c["caseId"] for c in self.normal + self.plan["edits"] if c["journey"] == "J09"})


class FixtureProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url, cls.state = fake_provider.start(0, delay=0.01)
        cls.api = Api(cls.url.rsplit("/v1", 1)[0])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.api.request("POST", "/__reset", body={})

    def stream(self, path, body):
        s = self.api.stream("POST", path, None, {"model": "gpt-6-luna", "stream": True, **body}, timeout=10)
        events = s.drain(max_seconds=10)
        s.close()
        return events

    def test_responses_stream_reassembles_the_source_with_usage(self):
        events = self.stream("/v1/responses", {"input": [{"role": "user", "content": "projection only"}]})
        types = [e["data"]["type"] for e in events if isinstance(e["data"], dict)]
        self.assertEqual(types[0], "response.created")
        self.assertEqual(types[-1], "response.completed")
        text = "".join(e["data"]["delta"] for e in events if e["data"].get("type") == "response.output_text.delta")
        self.assertGreaterEqual(types.count("response.output_text.delta"), 3)
        self.assertTrue(text.startswith("root = "))
        done = events[-1]["data"]["response"]
        self.assertEqual(done["output"][0]["content"][0]["text"], text)
        self.assertGreater(done["usage"]["output_tokens"], 0)
        self.assertEqual(self.api.request("GET", "/__stats").json()["requests"], 1)

    def test_chat_completions_stream_ends_with_usage_and_done(self):
        s = self.api.stream("POST", "/v1/chat/completions", None, {"model": "m", "stream": True, "messages": [{"role": "user", "content": "x"}]}, timeout=10)
        raw = []
        while True:
            chunk = s.response.read1(4096)
            if not chunk:
                break
            raw.append(chunk)
        s.close()
        body = b"".join(raw).decode()
        self.assertIn('"usage": {"prompt_tokens"', body)
        self.assertTrue(body.rstrip().endswith("data: [DONE]"))

    def test_faults(self):
        self.api.request("POST", "/__fault", body={"fault": "no_usage", "count": 1})
        events = self.stream("/v1/responses", {"input": "x"})
        self.assertIsNone(events[-1]["data"]["response"]["usage"])
        self.api.request("POST", "/__fault", body={"fault": "error", "count": 1})
        self.assertEqual(self.api.request("POST", "/v1/responses", body={"stream": True, "input": "x"}).status, 500)
        self.api.request("POST", "/__fault", body={"fault": "truncated", "count": 1})
        types = [e["data"]["type"] for e in self.stream("/v1/responses", {"input": "x"})]
        self.assertNotIn("response.completed", types)
        self.api.request("POST", "/__fault", body={"fault": "malformed", "count": 1})
        text = "".join(e["data"].get("delta", "") for e in self.stream("/v1/responses", {"input": "x"}))
        self.assertIn("= )", text)
        self.assertEqual(self.api.request("POST", "/__fault", body={"fault": "rm -rf"}).status, 400)
        stats = self.api.request("GET", "/__stats").json()
        self.assertEqual(stats["faultsUsed"], ["no_usage", "error", "truncated", "malformed"])

    def test_patch_mode_redeclares_a_statement_and_markers_are_detectable(self):
        user = ('<context kind="UI_PROJECTION">\n{}\n</context>\n\n<source kind="CURRENT_UI" revision="1" hash="x">\nroot = RafiiRoot([t1, f1])\n'
                't1 = Text("old")\nf1 = TextField("g_note", "Note", $g_note)\n</source>\n\n<request kind="USER_EDIT">\nchange it G-MARK-1\n</request>')
        events = self.stream("/v1/responses", {"input": [{"role": "user", "content": [{"type": "input_text", "text": user}]}]})
        text = "".join(e["data"].get("delta", "") for e in events if isinstance(e["data"], dict))
        self.assertTrue(text.startswith("t1 = Text("), text)
        seen = self.api.request("POST", "/__seen", body={"markers": ["G-MARK-1", "absent-marker"]}).json()["seen"]
        self.assertEqual(seen, {"G-MARK-1": 1, "absent-marker": 0})

    def test_kinds_are_counted_separately(self):
        self.stream("/v1/responses", {"input": "projection"})
        structured = self.api.request("POST", "/v1/responses", body={"input": "x", "text": {"format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"followUps": {"type": "array"}, "tone": {"enum": ["a", "b"]}}, "required": ["followUps", "tone"]}}}})
        payload = structured.json()["output"][0]["content"][0]["text"]
        self.assertEqual(json.loads(payload), {"followUps": [], "tone": "a"})
        stats = self.api.request("GET", "/__stats").json()
        self.assertEqual((stats["presenterRequests"], stats["byKind"].get("structured")), (1, 1))

    def test_build_source_without_and_with_a_schema(self):
        with mock.patch.object(fake_provider, "_schema", return_value=({}, {})):
            self.assertEqual(fake_provider.build_source(), "root = RafiiRoot([])\n")
        defs = {"RafiiRoot": {"properties": {"children": {"type": "array"}, "title": {"type": "string"}}, "required": ["children"]},
                "Text": {"properties": {"content": {"type": "string"}, "variant": {"enum": ["body", "muted"]}}, "required": ["content"]},
                "TextField": {"properties": {"name": {"type": "string"}, "label": {"type": "string"}}, "required": ["name", "label"]}}
        with mock.patch.object(fake_provider, "_schema", return_value=({"root": "RafiiRoot"}, defs)):
            source = fake_provider.build_source(with_input=True)
            plain = fake_provider.build_source(allowed={"RafiiRoot", "Text"}, with_input=True)
            body = {"instructions": "x\n\n## Components for this view\nUse only these components: RafiiRoot, Text.", "input": '<source kind="REJECTED_UI">\nbad\n</source>'}
            repaired = fake_provider.presenter_source(body)
        lines = source.strip().split("\n")
        self.assertEqual(lines[0], "root = RafiiRoot([t1, t2, t3, f1])")
        self.assertIn('$g_note = ""', lines)
        self.assertEqual(lines[-1], 'f1 = TextField("g_note", "Fixture note", $g_note)')
        self.assertTrue(all(line.startswith(f"t{i} = Text(\"") for i, line in enumerate(lines[2:5], 1)))
        self.assertTrue(any(ord(ch) > 0xFFFF for ch in source), "the fixture carries 4-byte characters (emoji) for UTF-8 splits")
        self.assertNotIn("TextField", plain, "a component outside the view's allowed list is never used")
        self.assertNotIn("TextField", repaired, "a repair answers with the plain text view")
        self.assertEqual(fake_provider.allowed_components(body["instructions"]), {"RafiiRoot", "Text"})

    @unittest.skipUnless(importlib.util.find_spec("agents"), "the Agents SDK runs in cloud CI (requirements.txt); this Mac's venv lacks it")
    def test_agent_requests_are_answered_by_the_qa_script(self):
        body = {"model": "gpt-6-sol", "tools": [{"type": "function", "name": "ask_campaign"}, {"type": "function", "name": "pending_approvals"}],
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "<request>\nWhat's missing in the campaign?\n</request>"}]}]}
        answer = self.api.request("POST", "/v1/responses", body=body).json()
        self.assertEqual(answer["output"][0]["type"], "function_call")
        self.assertEqual(answer["output"][0]["name"], "ask_campaign")
        self.assertGreater(answer["usage"]["input_tokens"], 0)
        self.assertEqual(self.api.request("GET", "/__stats").json()["byKind"], {"agent": 1})


class Tooling(unittest.TestCase):
    def test_split_character_detection(self):
        raw = "data: 廣\n\n".encode()
        reader = parse_all(raw, split_at=[7])   # inside the 3-byte character
        self.assertTrue(reader.split_inside_character())
        self.assertFalse(parse_all(raw).split_inside_character())
        self.assertEqual(reader.events[0]["data"], "廣")

    def test_recorder_decorator_records_pass_fail_and_blocked(self):
        rec_ = evidence.Recorder("t")

        class T(unittest.TestCase):
            @recorded(rec_, "m")
            def test_ok(self):
                return "fine"

            @recorded(rec_, "m")
            def test_blocked(self):
                raise Blocked("BLOCKED lane X")

            @recorded(rec_, "m")
            def test_bad(self):
                self.assertEqual(1, 2)
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(T).run(result)
        statuses = {i["check"]: i["status"] for i in rec_.items}
        self.assertEqual(statuses, {"m.T.test_ok": "pass", "m.T.test_blocked": "blocked", "m.T.test_bad": "fail"})
        self.assertEqual(len(result.skipped), 1, "blocked is a skip in unittest, never a pass")

    def test_summary_never_passes_a_gate_with_missing_or_blocked_checks(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AGENT_UI_CANDIDATE_SHA": SHA}):
            items = [{"check": c, "status": "pass"} for c in corpus.gate_checks("G13") if not c.startswith("e2e:")]
            items[0]["status"] = "blocked"
            items += [{"check": c, "status": "pass"} for c in corpus.gate_checks("G09") if not c.startswith("e2e:")]
            Path(tmp, "api-corpus.json").write_text(json.dumps({"items": items}))
            out = summarize.summarize(Path(tmp))
            by = {(r["gate"], r["environment"]["kind"]): r["status"] for r in out["records"]}
            self.assertEqual(by[("G13", "ci-harness")], "blocked")
            self.assertEqual(by[("G09", "ci-harness")], "pass")
            self.assertEqual(by[("G16", "ci-browser-emulation")], "unverified", "no browser results: unverified, never pass")
            self.assertEqual(out["candidateSha"], SHA)
            matrix = Path(tmp, "matrix.md").read_text()
            self.assertIn("| G13 | ci-harness | **blocked** |", matrix)
            self.assertIn("| G03 | *needs* live-provider + production-canary/production | unverified |", matrix)

    def test_scenes_never_count_as_tests_in_unit_mode(self):
        scenes = list((ROOT / "web/tests/agent-ui-e2e").glob("*.test.*"))
        self.assertEqual(scenes, [], "a browser scene named *.test.* would run under unit mode without a browser")


if __name__ == "__main__":
    unittest.main()
