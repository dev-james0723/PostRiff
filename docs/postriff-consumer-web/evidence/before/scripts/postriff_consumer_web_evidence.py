"""Evidence helper for the consumer-web round (no Git in this tree).

Usage:
  python scripts/postriff_consumer_web_evidence.py backup <path> [<path> ...]
      Copy each file to docs/postriff-consumer-web/evidence/before/<path> (first time only)
      and record its SHA-256 in evidence/baseline.json.
  python scripts/postriff_consumer_web_evidence.py diff
      Write evidence/changed-files.json (before/after hashes, new files) and
      evidence/source-diff.patch (unified diff of every backed-up file vs current).

Never records file contents in JSON; only relative paths and hashes.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "postriff-consumer-web" / "evidence"
BEFORE = EVIDENCE / "before"
BASELINE = EVIDENCE / "baseline.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_baseline() -> dict:
    if BASELINE.exists():
        return json.loads(BASELINE.read_text())
    return {"schema": "postriff.consumer-web.baseline.v1", "files": {}}


def backup(paths: list[str]) -> None:
    base = load_baseline()
    for raw in paths:
        rel = Path(raw)
        src = (ROOT / rel).resolve()
        key = src.relative_to(ROOT).as_posix()
        if key in base["files"]:
            print(f"already recorded {key}")
            continue
        if src.exists():
            dest = BEFORE / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            base["files"][key] = {"sha256": sha256(src), "existed": True}
            print(f"backed up {key} {base['files'][key]['sha256'][:12]}")
        else:
            base["files"][key] = {"sha256": None, "existed": False}
            print(f"recorded new-file marker {key}")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")


def diff() -> None:
    base = load_baseline()
    changed = []
    patch: list[str] = []
    for key, meta in sorted(base["files"].items()):
        current = ROOT / key
        after = sha256(current) if current.exists() else None
        entry = {"path": key, "before": meta["sha256"], "after": after}
        if meta["sha256"] == after:
            entry["state"] = "unchanged"
        elif meta["sha256"] is None:
            entry["state"] = "added"
        elif after is None:
            entry["state"] = "deleted"
        else:
            entry["state"] = "modified"
        changed.append(entry)
        if entry["state"] == "unchanged":
            continue
        before_text = (BEFORE / key).read_text().splitlines(keepends=True) if meta["existed"] else []
        after_text = current.read_text().splitlines(keepends=True) if current.exists() else []
        patch.extend(difflib.unified_diff(before_text, after_text, f"a/{key}", f"b/{key}"))
    (EVIDENCE / "changed-files.json").write_text(json.dumps({"schema": "postriff.consumer-web.changes.v1", "files": changed}, indent=2) + "\n")
    (EVIDENCE / "source-diff.patch").write_text("".join(patch))
    summary = {e["state"] for e in changed}
    print(f"{len(changed)} tracked files; states: {sorted(summary)}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in {"backup", "diff"}:
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "backup":
        backup(sys.argv[2:])
    else:
        diff()
