"""Evidence records in the 04-ACCEPTANCE shape (gate, candidate SHA, environment/origin, timestamp+timezone, command, actor,
redacted data scope, expected/actual, evidence paths). Every write passes redaction.assert_clean first (public repository).

`Recorder(name)` collects per-check records during a run and writes `$AGENT_UI_EVIDENCE_DIR/<name>.json`; `record(...)`
builds one gate-level record for docs/design/openui-production-2026-10-08/evidence/g/results/. The release checker reads both.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import corpus, redaction

ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("pass", "fail", "blocked", "unverified")


def head_sha() -> str:
    for name in ("AGENT_UI_CANDIDATE_SHA", "GITHUB_SHA"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def environment(kind: str, origin: str | None = None, **extra) -> dict:
    if kind not in corpus.EVIDENCE_KINDS:
        raise ValueError(f"unknown evidence kind {kind}")
    runner = os.environ.get("GITHUB_RUN_ID")
    return {"kind": kind, "origin": origin, "runner": "github-actions" if runner else os.environ.get("RUNNER_NAME") or "unknown",
            "runId": runner, "runUrl": (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{runner}"
                                        if runner and os.environ.get("GITHUB_REPOSITORY") else None), **extra}


def record(gate: str, status: str, *, kind: str, command: str, expected: str, actual: str, origin: str | None = None, actor: str = "G",
           data_scope: str = "synthetic disposable workspace", evidence_paths=(), checks=(), sha: str | None = None, **extra) -> dict:
    if gate not in corpus.GATES:
        raise ValueError(f"unknown gate {gate}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    out = {"gate": gate, "status": status, "candidateSha": sha or head_sha(), "environment": environment(kind, origin), "recordedAt": now_iso(),
           "timezone": "UTC", "command": command, "actor": actor, "dataScope": data_scope, "expected": expected, "actual": actual,
           "evidencePaths": list(evidence_paths), "checks": list(checks), **extra}
    redaction.assert_clean(out)
    return out


class Recorder:
    def __init__(self, name: str):
        self.name, self.items, self.started = name, [], time.time()

    def add(self, check: str, status: str, detail: str, **extra):
        if status not in STATUSES:
            raise ValueError(status)
        item = {"check": check, "status": status, "detail": redaction.scrub_text(str(detail))[:600], "at": now_iso(), **extra}
        redaction.assert_clean(item)
        self.items.append(item)
        return item

    def summary(self) -> dict:
        counts = {s: sum(1 for i in self.items if i["status"] == s) for s in STATUSES}
        return {"name": self.name, "candidateSha": head_sha(), "startedAt": datetime.fromtimestamp(self.started, timezone.utc).isoformat(timespec="seconds"),
                "finishedAt": now_iso(), "counts": counts, "items": self.items}

    def write(self, directory: str | None = None) -> Path | None:
        target = Path(directory or os.environ.get("AGENT_UI_EVIDENCE_DIR") or "")
        if not str(target) or str(target) == ".":
            return None
        target.mkdir(parents=True, exist_ok=True)
        payload = self.summary()
        redaction.assert_clean(payload)
        path = target / f"{self.name}.json"
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
        return path
