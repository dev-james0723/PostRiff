#!/usr/bin/env python3
"""Acceptance ledger for the Rafii Intelligent Library package (80 cases, A001–A080).

Usage:
  library-intelligence-acceptance.py init                 # copy the catalogue into evidence/acceptance-status.json (all UNVERIFIED)
  library-intelligence-acceptance.py set A025 VERIFIED --sha <sha> --env "<env>" --command "<cmd>" --evidence <ref> [--note ...]
  library-intelligence-acceptance.py check [--sha <sha>]  # validate the evidence protocol; non-zero exit when violated
  library-intelligence-acceptance.py summary              # counts per status and per requirement

Rules enforced (05-ACCEPTANCE-MATRIX evidence protocol): statuses are VERIFIED/FAILED/UNVERIFIED/BLOCKED; VERIFIED needs a
candidate SHA, command or manual procedure, environment and at least one evidence locator; a check against --sha fails if any
VERIFIED row names another SHA. Mock/fixture evidence is flagged in the note and cannot verify a real-provider case.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/design/rafii-intelligent-library-2026-10-08"
CATALOGUE = PACKAGE / "acceptance-cases.json"
LEDGER = PACKAGE / "evidence/acceptance-status.json"
STATUSES = ("VERIFIED", "FAILED", "UNVERIFIED", "BLOCKED")
REAL_PROVIDER_CASES = {"A017", "A018", "A022", "A023", "A026", "A032"}
DEVICE_CASES = {"A066"}


def load():
    return json.loads(LEDGER.read_text())


def save(data):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def init(_args):
    if LEDGER.exists():
        print("ledger exists; refusing to reset it", file=sys.stderr)
        return 1
    data = json.loads(CATALOGUE.read_text())
    for case in data["cases"]:
        case.update(status="UNVERIFIED", candidate_sha=None, environment=None, command=None, evidence=[], note=None)
    save(data)
    print(f"initialised {len(data['cases'])} cases")
    return 0


def set_case(args):
    data = load()
    case = next((c for c in data["cases"] if c["id"] == args.id), None)
    if case is None:
        print("unknown case", file=sys.stderr)
        return 2
    if args.status not in STATUSES:
        print("unknown status", file=sys.stderr)
        return 2
    if args.status == "VERIFIED" and not (args.sha and args.command and args.env and args.evidence):
        print("VERIFIED needs --sha, --command, --env and --evidence", file=sys.stderr)
        return 2
    if args.status == "VERIFIED" and args.id in REAL_PROVIDER_CASES and "real-provider" not in (args.note or ""):
        print(f"{args.id} needs real-provider evidence; say so in --note", file=sys.stderr)
        return 2
    if args.status == "VERIFIED" and args.id in DEVICE_CASES and "real-device" not in (args.note or ""):
        print(f"{args.id} needs a real device; say so in --note", file=sys.stderr)
        return 2
    case.update(status=args.status, candidate_sha=args.sha, environment=args.env, command=args.command,
                evidence=list(args.evidence or []), note=args.note)
    save(data)
    print(f"{args.id} -> {args.status}")
    return 0


def check(args):
    data = load()
    problems = []
    for case in data["cases"]:
        if case["status"] not in STATUSES:
            problems.append(f"{case['id']}: invalid status {case['status']}")
        if case["status"] == "VERIFIED":
            for key in ("candidate_sha", "environment", "command"):
                if not case.get(key):
                    problems.append(f"{case['id']}: VERIFIED without {key}")
            if not case.get("evidence"):
                problems.append(f"{case['id']}: VERIFIED without evidence")
            if args.sha and case.get("candidate_sha") != args.sha:
                problems.append(f"{case['id']}: VERIFIED on {case.get('candidate_sha')} not candidate {args.sha}")
    if len(data["cases"]) != 80:
        problems.append(f"expected 80 cases, found {len(data['cases'])}")
    for p in problems:
        print("PROBLEM", p)
    print(json.dumps(summary_counts(data)))
    return 1 if problems else 0


def summary_counts(data):
    counts = {s: 0 for s in STATUSES}
    for case in data["cases"]:
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    return counts


def summary(_args):
    data = load()
    print(json.dumps(summary_counts(data)))
    by_req = {}
    for case in data["cases"]:
        for req in case["requirements"]:
            by_req.setdefault(req, []).append(f"{case['id']}={case['status']}")
    for req in sorted(by_req):
        print(req, " ".join(by_req[req]))
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init").set_defaults(fn=init)
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("status")
    s.add_argument("--sha")
    s.add_argument("--env")
    s.add_argument("--command")
    s.add_argument("--evidence", action="append")
    s.add_argument("--note")
    s.set_defaults(fn=set_case)
    c = sub.add_parser("check")
    c.add_argument("--sha")
    c.set_defaults(fn=check)
    sub.add_parser("summary").set_defaults(fn=summary)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
