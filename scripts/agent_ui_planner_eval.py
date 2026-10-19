#!/usr/bin/env python3
"""Offline comparison of the deterministic GenUI eligibility baseline and the Adaptive UI Planner (rafii-ui-plan/1).

No model, network or database. Reads a labelled case file (tests/fixtures/agent_ui/planner_cases_v1.json) and reports, for
the baseline and the planner:
- inappropriateWidgets: cases labelled text-only that would get a generated view (spend without value);
- missedWidgets: cases labelled as needing a view that would stay text;
- formAccuracy (planner only; the baseline has no notion of form);
- safetyVetoOverrides: planner views on turns the baseline vetoed for safety (must be 0).

  python3 scripts/agent_ui_planner_eval.py [cases.json] [--json]

The labels are an engineer's, not an owner-reviewed ground truth; the report says so. It measures selection logic only:
real interaction completion, latency, spend and fallback success need the live canary (see the closeout package).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "tests" / "fixtures" / "agent_ui" / "planner_cases_v1.json"
ON = {"enabled": True, "actions": True, "edits": True, "canary": False}


def _turn(case: dict) -> dict:
    out = {"composedBy": case.get("composed", "manager"), "usage": {"billing": case.get("billing", "metered")}, "answerText": "",
           "toolActivity": [{"tool": t, "status": s, **({"runIds": case["runIds"]} if case.get("runIds") else {})} for t, s in case.get("tools") or []],
           "references": [{"type": k, "id": i} for k, i in case.get("refs") or []],
           "pendingApprovals": [{"type": t, "proposalId": f"prop-{n}"} for n, t in enumerate(case.get("approvals") or [])],
           "changedEntities": [], "routes": [{"agent": "rafii_manager", "provider": "openai"}]}
    if case.get("founder"):
        out["founder"] = {"mode": "live"}
    if case.get("youtube"):
        out["agent"] = {"youtubeProviderContext": {}}
    return out


def evaluate(path=DEFAULT) -> dict:
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    from postriff_phase2.agent_runtime_v2 import ui_planner, ui_projection

    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    base = {"inappropriateWidgets": 0, "missedWidgets": 0}
    plan = {"inappropriateWidgets": 0, "missedWidgets": 0, "formCorrect": 0, "safetyVetoOverrides": 0}
    rows = []
    for case in corpus["cases"]:
        turn, text, modality, scope = _turn(case), case["text"], case.get("modality", "text"), case.get("scope", "workspace")
        want = case["expect"]
        b = ui_projection.eligibility(turn, text, modality, flags=ON, scope=scope)
        p = ui_planner.plan(turn, text, modality, flags=ON, scope=scope, context={"followsArtifact": bool(case.get("followsArtifact"))})
        for tally, got in ((base, b["eligible"]), (plan, p["eligible"])):
            tally["inappropriateWidgets"] += int(got and not want["eligible"])
            tally["missedWidgets"] += int(want["eligible"] and not got)
        plan["formCorrect"] += int(p["form"] == want["form"])
        plan["safetyVetoOverrides"] += int(p["eligible"] and b["reason"] in ui_planner.HARD_VETOES)
        rows.append({"id": case["id"], "want": f'{want["eligible"]}/{want["form"]}', "baseline": f'{b["eligible"]}/{b["reason"]}',
                     "planner": f'{p["eligible"]}/{p["form"]}/{p["reason"]}', "delta": p["delta"]})
    n = len(corpus["cases"])
    plan["formAccuracy"] = round(plan["formCorrect"] / n, 4) if n else None
    return {"corpus": corpus.get("corpus"), "cases": n, "labels": "engineer-authored, not owner-reviewed", "baseline": base, "planner": plan, "rows": rows}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    report = evaluate(args[0] if args else DEFAULT)
    if "--json" in argv:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0
    print(f'{report["corpus"]}: {report["cases"]} cases ({report["labels"]})')
    for name in ("baseline", "planner"):
        print(f"  {name:9} {json.dumps(report[name], ensure_ascii=False)}")
    for row in report["rows"]:
        print(f'  {row["id"]}  want={row["want"]:16} baseline={row["baseline"]:22} planner={row["planner"]:34} {row["delta"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
