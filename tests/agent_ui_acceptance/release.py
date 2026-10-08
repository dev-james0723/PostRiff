"""`release` mode: the full-production completion check of 04-ACCEPTANCE (G25).

Every required gate in acceptance.json must have, for the exact candidate SHA:
  * matrix status `pass` (gate-level `candidate_sha`, or the matrix's top-level one, equal to the candidate), and
  * for each evidence-kind group of `corpus.GATES[gate]["kinds"]`, at least one evidence record with status `pass`, the same
    candidate SHA and an `environment.kind` from that group (a mock/fixture/emulation can never satisfy a group that asks for
    a live provider, a deployment or a physical device), and
  * no record with status `fail` or `blocked` for the candidate.

Anything else is reported per gate as `fail`, `blocked`, `stale` (evidence or matrix for another SHA), `absent` or
`unverified`, and the command exits non-zero. The candidate must be the code under test: HEAD may differ from it only by
commits that touch the engineering package's evidence/matrix files (evidence is committed after the run it describes).

    python -m agent_ui_acceptance.release --candidate <sha> [--acceptance PATH] [--records DIR_OR_FILE ...] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import corpus, redaction

ROOT = Path(__file__).resolve().parents[2]
PKG = "docs/design/openui-production-2026-10-08"
DEFAULT_ACCEPTANCE = ROOT / PKG / "acceptance.json"
DEFAULT_RECORDS = (ROOT / PKG / "evidence/g/results",)
EVIDENCE_ONLY_PREFIXES = (f"{PKG}/evidence/", f"{PKG}/acceptance.json", f"{PKG}/coordination.json")
GATE_STATES = ("pass", "fail", "blocked", "stale", "absent", "unverified")


def _sha_matches(value, candidate: str) -> bool:
    if not isinstance(value, str) or len(value) < 7 or not candidate:
        return False
    return candidate.startswith(value) or value.startswith(candidate)


def load_records(paths) -> list[dict]:
    """Gate-level evidence records (evidence.record shape) from files or directories; a file may hold one record, a list,
    or {"records": [...]}. Unreadable or malformed files are reported as records of their own so they can't be ignored."""
    out = []
    for raw in paths:
        path = Path(raw)
        files = sorted(path.rglob("*.json")) if path.is_dir() else [path] if path.exists() else []
        for file in files:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                out.append({"gate": None, "status": "fail", "source": str(file), "error": f"unreadable evidence: {type(error).__name__}"})
                continue
            items = data.get("records") if isinstance(data, dict) and isinstance(data.get("records"), list) else data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and "gate" in item:
                    out.append({**item, "source": str(file)})
    return out


def _inline(gate: dict, root: Path) -> list[dict]:
    out = []
    for entry in gate.get("evidence") or []:
        if isinstance(entry, dict) and entry.get("gate"):
            out.append({**entry, "source": "acceptance.json"})
        elif isinstance(entry, str) and entry.endswith(".json"):
            out.extend(r for r in load_records([root / entry]) if r.get("gate") == gate["id"])
    return out


def evaluate_gate(gate: dict, records: list[dict], candidate: str, matrix_sha) -> dict:
    gid = gate["id"]
    spec = corpus.GATES.get(gid)
    if spec is None:
        return {"gate": gid, "status": "fail", "why": ["gate is not in the lane-G corpus map"]}
    mine = [r for r in records if r.get("gate") == gid]
    current = [r for r in mine if _sha_matches(r.get("candidateSha"), candidate)]
    stale = [r for r in mine if r not in current]
    why = []
    failed = [r for r in current if r.get("status") == "fail"]
    blocked = [r for r in current if r.get("status") in ("blocked", "unverified")]
    passing = [r for r in current if r.get("status") == "pass"]
    missing = []
    for group in spec["kinds"]:
        if not any((r.get("environment") or {}).get("kind") in group for r in passing):
            missing.append(list(group))
    gate_sha = gate.get("candidate_sha") or matrix_sha
    matrix_status = gate.get("status")
    if failed:
        status = "fail"
        why.append(f"{len(failed)} failing record(s) for the candidate")
    elif blocked:
        status = "blocked"
        why.append(f"{len(blocked)} blocked/unverified record(s) for the candidate")
    elif matrix_status in ("fail", "blocked") and _sha_matches(gate_sha, candidate):
        status = matrix_status
        why.append(f"matrix says {matrix_status}")
    elif missing:
        status = "stale" if stale and not current else "absent"
        why.append("no passing evidence of kind " + " | ".join("/".join(g) for g in missing))
    elif not _sha_matches(gate_sha, candidate):
        status = "stale"
        why.append(f"matrix candidate_sha {gate_sha!r} is not the candidate")
    elif matrix_status != "pass":
        status = "unverified"
        why.append(f"matrix status is {matrix_status!r}, not pass")
    else:
        status = "pass"
    return {"gate": gid, "status": status, "required": bool(gate.get("required", True)), "why": why, "missingKinds": missing,
            "passing": len(passing), "stale": len(stale), "sources": sorted({str(r.get("source")) for r in current})[:20]}


def code_under_test(candidate: str, root: Path = ROOT) -> dict:
    """HEAD must be the candidate, or a descendant whose extra commits touch only evidence/matrix files."""
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        return {"ok": False, "why": "not a git checkout"}
    head_sha = head.stdout.strip()
    full = git("rev-parse", "--verify", f"{candidate}^{{commit}}")
    if full.returncode != 0:
        return {"ok": False, "head": head_sha, "why": f"candidate {candidate} is not a commit in this repository"}
    cand = full.stdout.strip()
    if cand == head_sha:
        return {"ok": True, "head": head_sha, "candidate": cand, "evidenceOnlyCommits": 0}
    if git("merge-base", "--is-ancestor", cand, head_sha).returncode != 0:
        return {"ok": False, "head": head_sha, "candidate": cand, "why": "candidate is not an ancestor of HEAD"}
    changed = [line for line in git("diff", "--name-only", cand, head_sha).stdout.splitlines() if line]
    code = [p for p in changed if not p.startswith(EVIDENCE_ONLY_PREFIXES)]
    if code:
        return {"ok": False, "head": head_sha, "candidate": cand, "why": "HEAD changes code after the candidate", "paths": code[:20]}
    return {"ok": True, "head": head_sha, "candidate": cand, "evidenceOnlyCommits": len(changed)}


def check(candidate: str, acceptance_path=DEFAULT_ACCEPTANCE, record_paths=DEFAULT_RECORDS, *, root: Path = ROOT, verify_git=True) -> dict:
    if not candidate or len(candidate) < 7:
        raise SystemExit("release mode needs --candidate <sha> (the exact code SHA under test)")
    matrix = json.loads(Path(acceptance_path).read_text(encoding="utf-8"))
    records = load_records(record_paths)
    for gate in matrix.get("gates") or []:
        records.extend(_inline(gate, root))
    broken = [r for r in records if r.get("gate") is None]
    leaks = []
    for r in records:
        found = redaction.scan({k: v for k, v in r.items() if k != "source"})
        if found:
            leaks.append({"source": r.get("source"), "findings": [f["kind"] for f in found][:5]})
    gates = [evaluate_gate(g, records, candidate, matrix.get("candidate_sha")) for g in matrix.get("gates") or []]
    known = {g["id"] for g in matrix.get("gates") or []}
    unmapped = sorted(set(corpus.GATES) - known)
    git_state = code_under_test(candidate, root) if verify_git else {"ok": True, "skipped": True}
    required = [g for g in gates if g["required"]]
    ok = (bool(required) and all(g["status"] == "pass" for g in required) and not broken and not leaks and not unmapped and git_state.get("ok"))
    counts = {s: sum(1 for g in required if g["status"] == s) for s in GATE_STATES}
    return {"mode": "release", "candidate": candidate, "ok": bool(ok), "counts": counts, "gates": gates, "unreadable": [r["source"] for r in broken],
            "redactionFindings": leaks, "gatesMissingFromMatrix": unmapped, "codeUnderTest": git_state}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--acceptance", type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument("--records", type=Path, nargs="*", default=list(DEFAULT_RECORDS))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-git", action="store_true", help="skip the code-under-test check (only for checking a copied matrix)")
    args = parser.parse_args(argv)
    report = check(args.candidate, args.acceptance, args.records, verify_git=not args.no_git)
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    for gate in report["gates"]:
        if gate["status"] != "pass":
            print(f"{gate['gate']}: {gate['status'].upper()} — {'; '.join(gate['why'])}", file=sys.stderr)
    if not report["codeUnderTest"].get("ok"):
        print(f"candidate: {report['codeUnderTest'].get('why')}", file=sys.stderr)
    print(json.dumps({"mode": "release", "candidate": args.candidate, "ok": report["ok"], "counts": report["counts"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
