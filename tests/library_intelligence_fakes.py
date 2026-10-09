"""Unit-test doubles for Library intelligence. A FakeCursor answers SQL by regex; it proves Python logic only.
Database behaviour (constraints, RLS, real queries) is covered by tests/phase2/postgres_library_intelligence.py."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2.permissions import Membership  # noqa: E402
from postriff_phase2.library_intelligence import contracts as c  # noqa: E402

WS = "11111111-1111-1111-1111-111111111111"
ACTOR = "00000000-0000-0000-0000-000000000001"


class FakeCursor:
    def __init__(self, rules=None):
        self.rules = list(rules or [])  # (pattern, rows | callable(sql, args) -> rows)
        self.executed = []
        self.rowcount = 0
        self._rows = []

    def on(self, pattern, rows):
        self.rules.insert(0, (pattern, rows))
        return self

    def execute(self, sql, args=()):
        self.executed.append((sql, args))
        self._rows, self.rowcount = [], 0
        for pattern, rows in self.rules:
            if re.search(pattern, sql, re.S):
                value = rows(sql, args) if callable(rows) else rows
                self._rows = list(value or [])
                self.rowcount = len(self._rows)
                break

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def sql(self, pattern):
        return [s for s, _ in self.executed if re.search(pattern, s, re.S)]


def ctx(cur=None, *, role="owner", state=None, grants=None, revision=0):
    context = c.LibraryContext(workspace_id=WS, actor=ACTOR, membership=Membership(role), state=state or {"sources": [], "phase2": {"assets": []}},
                               cur=cur or FakeCursor(), now=1_790_000_000.0)
    context.caches["policy"] = {"grantRevision": revision, "indexGeneration": 1, "organizationRevision": 0}
    context.caches["grants"] = list(grants or [])
    return context


def version(key="a" * 32, *, status="ready", sha="b" * 64, source_id=None, kind="document", asset=None):
    return {"assetId": asset or key, "versionId": key, "versionNo": 1, "sha256": sha, "filename": "notes.md", "title": "Notes",
            "titleSource": "filename", "summary": None, "tags": [], "kind": kind, "mime": "text/markdown", "extension": "md",
            "bytes": 10, "status": status, "analysisStatus": "not_applicable", "indexingStatus": "ready", "transcriptionStatus": "not_applicable",
            "sourceId": source_id, "sourceKind": "upload", "media": {}, "duplicateOf": None, "provenance": {}, "createdAt": 1.0, "legacy": False}


def grant(purpose=None, *, location=None, category=None, scope="workspace", key="*", members=(), gid="c" * 32, attestation=None):
    return {"id": gid, "grantType": "purpose" if purpose else "processing", "scopeKind": scope, "scopeKey": key, "memberKeys": list(members),
            "purpose": purpose, "location": location, "category": category, "attestation": attestation or {}, "grantedBy": ACTOR,
            "grantedRevision": 1, "grantedAt": 1.0}
