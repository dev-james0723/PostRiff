"""Check, lock or report the Rafii capability registry (skills/rafii-registry.json).

    PYTHONPATH=src:tests python scripts/rafii_skill_registry.py --check [--json PATH]
    PYTHONPATH=src:tests python scripts/rafii_skill_registry.py --lock
    PYTHONPATH=src:tests python scripts/rafii_skill_registry.py --report

--check exits 1 on any registry error (CI). --lock records new hashes only for entries whose version changed and
refuses a content change without a version bump. Nothing here edits a skill file.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import skill_registry  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--lock", action="store_true")
    group.add_argument("--report", action="store_true")
    parser.add_argument("--json", help="write the machine-readable report here")
    args = parser.parse_args()
    if args.lock:
        result = skill_registry.lock()
        print(json.dumps(result, indent=2))
        if result["refused"]:
            print("Refused: content changed without a version bump for " + ", ".join(result["refused"]), file=sys.stderr)
            return 1
        return 0
    report = skill_registry.check()
    payload = report.as_dict()
    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if args.report or args.check:
        totals = payload["totals"]
        print(f"release {payload['release']} · registered {totals['registered']} · default {totals['default']} · private {totals['private']}")
        print("by kind: " + ", ".join(f"{k} {v}" for k, v in totals["byKind"].items()))
        print(f"orphans {payload['orphanCount']} · deprecated {totals['deprecated']} · dormant {totals['dormant']} · James-leak findings {payload['jamesLeakage']['findings']}")
        for item in payload["documentedExceptions"]:
            print(f"  exception {item['id']} ({item['state']}): {item['reason']}")
        for error in payload["errors"]:
            print("ERROR " + error)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
