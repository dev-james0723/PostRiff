"""Turn per-check results (api-corpus.json, validator-corpus.json, e2e-<browser>.json in $AGENT_UI_EVIDENCE_DIR) into
gate-level evidence records (evidence.record shape) for the release checker.

A gate's record for one evidence kind is `fail` if any of its checks failed, `blocked` if any is blocked (and none failed),
`pass` only if every check that ran passed and at least one ran; a check that never ran is listed as missing (a gate with
missing checks is never `pass`). ci-harness records come from the API/validator corpora; ci-browser-emulation from the
browser scenes (both engines must agree). Output: <dir>/gate-records.json — A copies it into evidence/g/results/.

    python -m agent_ui_acceptance.summarize --dir $AGENT_UI_EVIDENCE_DIR [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import corpus, evidence

ORDER = {"fail": 3, "blocked": 2, "unverified": 1, "pass": 0}


def load(directory: Path) -> dict:
    """check name → list of (status, detail, source)."""
    results: dict = {}
    for name in ("contract-corpus.json", "api-corpus.json", "validator-corpus.json", "e2e-chromium.json", "e2e-webkit.json"):
        path = directory / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("items") or []:
            results.setdefault(item["check"], []).append((item["status"], item.get("detail", ""), name))
    return results


def gate_record(gate: str, kind: str, checks: list, results: dict, origin: str | None):
    if not checks:
        return None
    statuses, missing, details = [], [], []
    for check in checks:
        runs = results.get(check)
        if not runs:
            missing.append(check)
            continue
        worst = max(runs, key=lambda r: ORDER.get(r[0], 3))
        statuses.append(worst[0])
        if worst[0] != "pass":
            details.append(f"{check}: {worst[0]} — {worst[1][:160]}")
    if not statuses:
        status = "unverified"
    elif "fail" in statuses:
        status = "fail"
    elif "blocked" in statuses:
        status = "blocked"
    elif missing:
        status = "unverified"
    else:
        status = "pass"
    actual = f"{statuses.count('pass')}/{len(checks)} checks pass" + (f"; missing {len(missing)}" if missing else "") + (f"; {'; '.join(details)[:900]}" if details else "")
    return evidence.record(gate, status, kind=kind, origin=origin, command="scripts/agent_ui_acceptance.sh browser",
                           expected="every mapped lane-G check passes on this SHA", actual=actual, checks=checks, missingChecks=missing,
                           data_scope="synthetic disposable workspaces on the CI acceptance stack (harness Manager, fixture provider)")


REQUIRED_ELSEWHERE = {
    "G01": "A: git metadata, package probe, ownership register", "G03": "live: scripts/agent_ui_live.py ingest (fixed 60-case corpus, >=59/60 first pass; D-A53)",
    "G20": "A: agent_ui_validation.sh regression on the integrated SHA", "G22": "A: migration rehearsal + route smoke", "G23": "A/G: deployed kill-switch drill",
    "G24": "A: production release receipt", "G25": "release.py over the final matrix", **{f"J0{i}": "real-service journey (E/D/F) + live journey" for i in range(1, 10)},
}


def render_matrix(out: dict) -> str:
    """The 04-ACCEPTANCE evidence record as a Markdown matrix (one row per gate and evidence kind)."""
    lines = [f"# Lane G acceptance matrix — candidate `{out['candidateSha'][:12]}`", "",
             f"Generated {out['generatedAt']} (UTC) by `scripts/agent_ui_acceptance.sh browser`. CI harness and browser-emulation evidence only: "
             "rows marked *needs* list evidence no CI run can provide (live provider, deployment, physical device, release owner).", "",
             "| Gate | Kind | Status | Actual | Origin | Run |", "|---|---|---|---|---|---|"]
    by_gate: dict = {}
    for record in out["records"]:
        by_gate.setdefault(record["gate"], []).append(record)
    for gate in corpus.GATES:
        rows = by_gate.get(gate) or []
        for record in rows:
            env = record.get("environment") or {}
            run = f"[{env.get('runId')}]({env.get('runUrl')})" if env.get("runUrl") else (env.get("runId") or "")
            actual = str(record.get("actual") or "").replace("|", "/").replace("\n", " ")[:220]
            lines.append(f"| {gate} | {env.get('kind')} | **{record['status']}** | {actual} | {env.get('origin') or ''} | {run} |")
        needs = [g for g in corpus.GATES[gate]["kinds"] if not any((r.get("environment") or {}).get("kind") in g for r in rows)]
        if needs:
            lines.append(f"| {gate} | *needs* {' + '.join('/'.join(g) for g in needs)} | unverified | {REQUIRED_ELSEWHERE.get(gate, corpus.GATES[gate]['g'])} | | |")
    lines += ["", "Command, actor and data scope for every CI row: `scripts/agent_ui_acceptance.sh browser`, actor G, synthetic disposable workspaces on the "
              "CI acceptance stack (fixture provider, harness QA script for the Manager). Machine-readable records: `gate-records.json` (release mode input)."]
    return "\n".join(lines) + "\n"


def summarize(directory: Path) -> dict:
    results = load(directory)
    origin = os.environ.get("RAFII_WEB_URL") or os.environ.get("AGENT_UI_API_URL")
    records = []
    for gate in corpus.GATES:
        checks = corpus.gate_checks(gate)
        harness = [c for c in checks if not c.startswith("e2e:")]
        browser = [c for c in checks if c.startswith("e2e:")]
        for kind, subset in (("ci-harness", harness), ("ci-browser-emulation", browser)):
            record = gate_record(gate, kind, subset, results, origin)
            if record:
                records.append(record)
    counts = {s: sum(1 for r in records if r["status"] == s) for s in evidence.STATUSES}
    out = {"candidateSha": evidence.head_sha(), "generatedAt": evidence.now_iso(), "counts": counts, "records": records,
           "checks": {k: [r[0] for r in v] for k, v in sorted(results.items())}}
    (directory / "gate-records.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    (directory / "matrix.md").write_text(render_matrix(out))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=Path(os.environ.get("AGENT_UI_EVIDENCE_DIR") or "."))
    parser.add_argument("--strict", action="store_true", help="exit non-zero on blocked/unverified too (release candidates)")
    args = parser.parse_args(argv)
    out = summarize(args.dir)
    print(json.dumps({"gateRecords": out["counts"], "checks": len(out["checks"])}))
    bad = out["counts"].get("fail", 0) + (out["counts"].get("blocked", 0) + out["counts"].get("unverified", 0) if args.strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
