"""Generate docs/design/site-agent/agent-runtime/verification-matrix.md from machine-readable evidence. Do not hand-edit it.

Evidence read (all under docs/design/site-agent/agent-runtime/evidence/ unless noted):
  unit.json                    per-test outcomes of tests/test_agent_runtime.py (scripts/agent_runtime_matrix.py --unit writes it)
  pg-scenarios.json            tests/phase2/postgres_agent_runtime.py
  browser-chromium/agent-runtime-browser.json, browser-webkit/agent-runtime-browser.json
  live-checks.json             scripts/agent_runtime_live.py --out
  ../evidence/scenarios.json   the site agent's scenario suite (for the capability gaps)

Status rules: a missing or failing deterministic reference → FAIL; deterministic evidence passed but the required live check
is not PASS → PARTIAL with its blocker; otherwise PASS. WebKit is reported beside Chromium, never instead of it.

    PYTHONPATH=src:tests python scripts/agent_runtime_matrix.py [--unit]
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
EVIDENCE = ROOT / "docs/design/site-agent/agent-runtime/evidence"
OUT = ROOT / "docs/design/site-agent/agent-runtime/verification-matrix.md"


def run_unit() -> dict:
    """Run tests/test_agent_runtime.py and record each test's outcome."""
    import os
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
    suite = unittest.defaultTestLoader.loadTestsFromName("test_agent_runtime")
    outcomes = {}

    class Recorder(unittest.TextTestResult):
        def addSuccess(self, test):
            super().addSuccess(test)
            outcomes[test.id().split(".", 1)[1]] = "PASS"

        def addFailure(self, test, err):
            super().addFailure(test, err)
            outcomes[test.id().split(".", 1)[1]] = "FAIL"

        def addError(self, test, err):
            super().addError(test, err)
            outcomes[test.id().split(".", 1)[1]] = "FAIL"

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            outcomes[test.id().split(".", 1)[1]] = "SKIPPED"

    result = unittest.TextTestRunner(resultclass=Recorder, verbosity=0).run(suite)
    data = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "tests": outcomes}
    (EVIDENCE / "unit.json").write_text(json.dumps(data, indent=1))
    return data


def load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def main(argv) -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    unit = run_unit() if "--unit" in argv else load(EVIDENCE / "unit.json")
    pg = load(EVIDENCE / "pg-scenarios.json") or {"scenarios": []}
    site = load(ROOT / "docs/design/site-agent/evidence/scenarios.json") or {"scenarios": []}
    chromium = load(EVIDENCE / "browser-chromium/agent-runtime-browser.json")
    webkit = load(EVIDENCE / "browser-webkit/agent-runtime-browser.json")
    live = load(EVIDENCE / "live-checks.json") or {"checks": []}
    from postriff_phase2.agent_runtime_v2.evals import catalog

    pg_by = {s["id"]: s for s in pg["scenarios"]}
    site_by = {s["id"]: s for s in site["scenarios"]}
    live_by = {c["check"]: c for c in live.get("checks") or []}

    def browser_status(results, ref):
        if not results:
            return "MISSING", "no browser run recorded"
        hits = [r for r in results["results"] if r["name"].startswith(ref) or ref in r["name"].split(":")[0].split("/")]
        if not hits:
            return "MISSING", f"no browser check named {ref!r}"
        return ("PASS", None) if all(r["ok"] for r in hits) else ("FAIL", "; ".join(r["name"] for r in hits if not r["ok"]))

    def resolve(ref):
        kind, _, key = ref.partition(":")
        if kind == "unit":
            outcome = ((unit or {}).get("tests") or {}).get(key)
            return (outcome or "MISSING"), (None if outcome == "PASS" else f"unit {key}: {outcome or 'not run'}")
        if kind == "pg":
            item = pg_by.get(key)
            if not item:
                return "MISSING", f"pg {key}: not run"
            return ("PASS", None) if item["result"] == "PASS" else ("FAIL", f"pg {key}: {item['result']} {item.get('error', '')[:120]}")
        if kind == "site":
            item = site_by.get(key)
            if not item:
                return "MISSING", f"site {key}: not in the site agent's evidence"
            verdict = str(item.get("verdict") or "").split(" ")[0]
            return ("PASS", None) if verdict == "PASS" else ("FAIL", f"site {key}: {item.get('verdict')}")
        if kind == "browser":
            return browser_status(chromium, key)
        return "MISSING", f"unknown evidence kind {ref}"

    def status(evidence, live_need):
        states = [resolve(ref) for ref in evidence]
        problems = [why for state, why in states if state != "PASS"]
        if problems:
            return "FAIL", "; ".join(problems)
        if live_need:
            check = live_by.get(live_need.replace("-", "_")) or live_by.get(live_need)
            if not check or check.get("result") != "PASS":
                reason = (check or {}).get("reason") or (check or {}).get("error") or "live check not run"
                return "PARTIAL", f"deterministic evidence passed; live {live_need}: {(check or {}).get('result', 'NOT RUN')} — {reason}"
        return "PASS", None

    rows, counts = [], {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for section, items in (("Voice (spec §32)", catalog.SCENARIOS[:20]), ("Multimodal (spec §33)", catalog.SCENARIOS[20:]), ("Capability gaps", catalog.GAPS),
                           ("Definition of done (spec §42)", catalog.DONE)):
        rows.append((section, []))
        for sid, title, evidence, live_need in items:
            state, why = status(evidence, live_need)
            counts[state] += 1
            rows[-1][1].append((sid, title, evidence, live_need, state, why))

    lines = ["# Rafii Agent Runtime — verification matrix", "",
             f"Generated by `python scripts/agent_runtime_matrix.py` from the evidence files ({catalog.VERSION}). Do not edit by hand.", "",
             f"**Rows: {sum(counts.values())} — {counts['PASS']} PASS, {counts['PARTIAL']} PARTIAL, {counts['FAIL']} FAIL.** PARTIAL means every deterministic check "
             "passed and the row also needs a live external service that could not be exercised (the reason is in the row); a failed or missing check is FAIL.", ""]
    lines.append(f"Evidence: unit {((unit or {}).get('ran'))} tests ({(unit or {}).get('failures', '?')} failures, {(unit or {}).get('errors', '?')} errors); "
                 f"PostgreSQL scenarios {pg.get('summary')}; Chromium {'%d/%d' % (sum(r['ok'] for r in chromium['results']), len(chromium['results'])) if chromium else 'not run'}; "
                 f"WebKit {'%d/%d' % (sum(r['ok'] for r in webkit['results']), len(webkit['results'])) if webkit else 'not run'}; "
                 f"live checks {[(c['check'], c['result']) for c in live.get('checks') or []]}.")
    lines.append("")
    for section, items in rows:
        lines += [f"## {section}", "", "| ID | Requirement | Evidence | Live | Result |", "|---|---|---|---|---|"]
        for sid, title, evidence, live_need, state, why in items:
            lines.append(f"| {sid} | {title} | {', '.join(f'`{e}`' for e in evidence)} | {live_need or '—'} | **{state}**{(' — ' + why.replace('|', '/')) if why else ''} |")
        lines.append("")
    lines += ["## Eval categories (spec §31)", "", "| Category | Evidence | Result |", "|---|---|---|"]
    for name, evidence in catalog.CATEGORIES.items():
        state, why = status(evidence, None)
        lines.append(f"| {name} | {', '.join(f'`{e}`' for e in evidence)} | **{state}**{(' — ' + why.replace('|', '/')) if why else ''} |")
    lines.append("")
    if chromium or webkit:
        lines += ["## Browser QA", "", "| Check | chromium | webkit |", "|---|---|---|"]
        names = list(dict.fromkeys([r["name"] for r in (chromium or {"results": []})["results"]] + [r["name"] for r in (webkit or {"results": []})["results"]]))
        for name in names:
            def cell(run):
                hit = next((r for r in (run or {"results": []})["results"] if r["name"] == name), None)
                return "—" if hit is None else ("PASS" if hit["ok"] else "FAIL")
            lines.append(f"| {name} | {cell(chromium)} | {cell(webkit)} |")
        lines.append("")
    OUT.write_text("\n".join(lines))
    print(json.dumps(counts))
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
