"""Faithful in-memory fakes for lane B's stream/presenter/accounting tests (no tests in this module).

- FakeDB + FakeCursor: answers exactly the tagged SQL that ui_stream / ui_metering issue (`/* rafii-ui:<name> */`), so an
  unexpected statement fails the test instead of silently passing. The same SQL runs on real PostgreSQL in
  tests/phase2/postgres_agent_ui_stream.py.
- FakeLedger: the Ledger semantics that matter for G13 (same key = same row, completed without actual = unknown, terminal
  settlements win, unknown recorded once and the hold kept).
- FakeStore: lane F's frozen ui_store contract (D-A32..D-A36) with the same constraints as migration 102: one attempt per
  idempotency key, one live producer per (artifact, target revision), CAS commit on base revision/hash, state machine.
- ScriptTransport: a provider stream scripted step by step (deltas, sleeps, final usage, errors, hangs); never a network call.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import config, ui_contracts as contracts

WS = "11111111-2222-4333-8444-555555555555"
OTHER_WS = "99999999-2222-4333-8444-555555555555"
ME = "aaaaaaaa-1111-4222-8333-944455556666"
OTHER = "bbbbbbbb-1111-4222-8333-944455556666"
TOKEN = "token-me-" + "x" * 30
OTHER_TOKEN = "token-other-" + "x" * 30
LIVE = ("queued", "streaming", "validating")
_TAG = re.compile(r"/\* rafii-ui:([a-z_]+) \*/")
PRIVATE_CONTEXT_TEXT = "PRIVATE-DRAFT-BODY-should-never-reach-a-frame"


def uid() -> str:
    return str(uuid.uuid4())


# --- database --------------------------------------------------------------------------------------------------------------
class FakeDB:
    def __init__(self):
        self.lock = threading.RLock()
        self.runs: dict = {}
        self.ledger: list = []
        self.artifacts: dict = {}
        self.attempts: dict = {}
        self.events: list = []
        self.revisions: dict = {}
        self.call_events: list = []
        self.settle_calls: list = []
        self.reserve_calls: list = []
        self.reserve_error = None
        self.members = {(WS, ME): "owner", (WS, OTHER): "editor", (OTHER_WS, OTHER): "owner"}
        self.tokens = {TOKEN: ME, OTHER_TOKEN: OTHER}
        self.version = 0
        self.statements: list = []

    # snapshots for transaction rollback
    def snapshot(self):
        return copy.deepcopy({k: getattr(self, k) for k in ("runs", "ledger", "artifacts", "attempts", "events", "revisions", "call_events")}), self.version

    def restore(self, snap):
        state, version = snap
        if version != self.version:
            raise AssertionError("fake: a rollback would discard another connection's commit")
        for key, value in state.items():
            setattr(self, key, value)

    # helpers used by tests
    def add_parent(self, *, eligible=True, status="completed", composed="manager", billing="metered", age=5.0, actor=ME, ceiling=88_000, spent=30_000,
                   spent_state="actual", journeys=("J01",), workspace=WS, run_key=None):
        run_id, conversation = uid(), uid()
        result = {"composedBy": composed, "usage": {"billing": billing}, "ui": {"eligible": eligible, "journeyIds": list(journeys)},
                  "answerText": "Here are your drafts.", "references": [{"type": "draft", "id": "d1", "title": PRIVATE_CONTEXT_TEXT}]}
        self.runs[run_id] = {"runId": run_id, "workspaceId": workspace, "conversationId": conversation, "status": status, "runKey": run_key or "agent:" + uid(),
                             "actor": actor, "result": result, "age": age}
        if ceiling is not None:
            rid = uid()
            self.ledger.append({"id": rid, "kind": "reserve", "key": f"agent:{run_id}", "estimate": ceiling, "actual": None, "costState": "estimated",
                                "reservationId": rid, "meta": {}, "runId": run_id, "workspaceId": workspace})
            if spent_state == "actual":
                self.ledger.append({"id": uid(), "kind": "settle", "key": f"settle:{rid}", "estimate": ceiling, "actual": spent, "costState": "actual",
                                    "reservationId": rid, "meta": {}, "runId": run_id, "workspaceId": workspace})
            elif spent_state == "unknown":
                self.ledger.append({"id": uid(), "kind": "settle", "key": f"settle:{rid}:unknown", "estimate": ceiling, "actual": None,
                                    "costState": "estimated_unknown", "reservationId": rid, "meta": {}, "runId": run_id, "workspaceId": workspace})
        return run_id

    def ui_reservations(self):
        return [r for r in self.ledger if r["kind"] == "reserve" and ":ui:" in r["key"]]

    def settlements_for(self, reservation_id):
        return [r for r in self.ledger if r["kind"] in ("settle", "release") and r["reservationId"] == reservation_id]

    def kinds(self, artifact_id=None):
        return [e["kind"] for e in self.events if artifact_id is None or e["artifactId"] == artifact_id]

    # --- tagged SQL ---------------------------------------------------------------------------------------------------------
    def execute(self, sql, params):
        match = _TAG.search(sql)
        if not match:
            raise AssertionError(f"fake: untagged SQL {sql[:80]!r}")
        name = match.group(1)
        self.statements.append(name)
        handler = getattr(self, "sql_" + name, None)
        if handler is None:
            raise AssertionError(f"fake: no handler for {name}")
        return handler(*params)

    def sql_parent_run(self, run_id, workspace_id):
        run = self.runs.get(run_id)
        if not run or run["workspaceId"] != workspace_id:
            return []
        return [(run["runId"], run["conversationId"], run["status"], run["runKey"], run["actor"], copy.deepcopy(run["result"]), run["age"])]

    def sql_attempt_by_key(self, workspace_id, key):
        return [(a["attemptId"],) for a in self.attempts.values() if a["workspaceId"] == workspace_id and a["idempotencyKey"] == key]

    def sql_artifact_head(self, artifact_id, workspace_id):
        art = self.artifacts.get(artifact_id)
        if not art or art["workspaceId"] != workspace_id:
            return []
        run = self.runs[art["runId"]]
        return [(art["runId"], art["slot"], art["actor"], art["scope"], art["scopeKey"], art["surface"], list(art["journeyIds"]), art["revision"],
                 art["sourceHash"], copy.deepcopy(art["manifest"]), art["currentAttemptId"], run["runKey"])]

    def sql_revision_source(self, artifact_id, workspace_id, revision):
        source = self.revisions.get((artifact_id, revision))
        return [(source,)] if source is not None else []

    def sql_current_attempt(self, artifact_id, workspace_id):
        art = self.artifacts.get(artifact_id)
        if not art or art["workspaceId"] != workspace_id or not art["currentAttemptId"]:
            return []
        t = self.attempts[art["currentAttemptId"]]
        return [(t["attemptId"], t["state"], t["targetRevision"], t["reservationId"], t["leaseExpired"])]

    def sql_attempt_state(self, attempt_id, workspace_id):
        t = self.attempts.get(attempt_id)
        return [(t["state"],)] if t and t["workspaceId"] == workspace_id else []

    def sql_workspace_lock(self, workspace_id):
        return [(workspace_id,)]

    def _terminal(self, rid):
        for r in self.ledger:
            if r["kind"] in ("settle", "release") and r["reservationId"] == rid and r["costState"] in ("actual", "released"):
                return r
        return None

    def sql_usage_rows(self, workspace_id, parent_key, pattern):
        prefix = pattern[:-1]
        rows = []
        for r in self.ledger:
            if r["kind"] != "reserve" or r["workspaceId"] != workspace_id:
                continue
            if r["key"] == parent_key or r["key"].startswith(prefix):
                terminal = self._terminal(r["id"])
                unknown = any(x["reservationId"] == r["id"] and x["costState"] == "estimated_unknown" for x in self.ledger)
                rows.append((r["key"], r["estimate"], terminal["actual"] if terminal else None, unknown, (r["meta"] or {}).get("chain") or ""))
        return rows

    def sql_attempt_reserved(self, reservation_id, attempt_id, workspace_id):
        t = self.attempts[attempt_id]
        t["reservationId"], t["providerAttempts"] = reservation_id, 1
        return []

    def sql_attempt_accounting(self, attempt_id, workspace_id):
        t = self.attempts.get(attempt_id)
        if not t or t["workspaceId"] != workspace_id:
            return []
        art = self.artifacts[t["artifactId"]]
        return [(t["reservationId"], t["kind"], art["runId"], art["actor"])]

    def sql_attempt_usage(self, usage_json, cost, cost_state, attempt_id, workspace_id):
        t = self.attempts[attempt_id]
        t["usage"], t["costUsdMicro"], t["costState"] = json.loads(usage_json), cost, cost_state
        return []

    def sql_orphan_holds(self, workspace_id, grace):
        out = []
        for t in self.attempts.values():
            if (t["workspaceId"] == workspace_id and t["reservationId"] and t["state"] not in LIVE and t.get("finishedLongAgo")
                    and not self.settlements_for(t["reservationId"])):
                out.append((t["attemptId"], t["reservationId"]))
        return out

    def sql_orphan_workspaces(self, grace, limit):
        found = {t["workspaceId"] for t in self.attempts.values() if t["reservationId"] and t["state"] not in LIVE and t.get("finishedLongAgo")
                 and not self.settlements_for(t["reservationId"])}
        return [(w,) for w in sorted(found)][:limit]

    def sql_workspace_lock_skip(self, workspace_id):
        return [] if workspace_id in getattr(self, "busy_workspaces", ()) else [(workspace_id,)]

    def sql_attempt_usage_state(self, attempt_id, workspace_id):
        self.attempts[attempt_id]["costState"] = "unknown"
        return []


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db, self._rows, self.rowcount = db, [], 0

    def execute(self, sql, params=()):
        with self.db.lock:
            self._rows = list(self.db.execute(sql, params) or [])
            self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db, self.closed = db, False
        self._snap = db.snapshot()

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        with self.db.lock:
            self.db.version += 1
            self._snap = self.db.snapshot()

    def rollback(self):
        with self.db.lock:
            if self._snap[1] == self.db.version:
                self.db.restore(self._snap)

    def close(self):
        self.closed = True


class FakeRepository:
    def __init__(self, db: FakeDB):
        self.db = db
        self.transactions = 0

    @contextmanager
    def transaction(self, token, workspace_id):
        principal = self.db.tokens.get(token)
        if principal is None:
            raise AlphaError("Sign in again.", 401)
        role = self.db.members.get((workspace_id, principal))
        if role is None:
            raise AlphaError("Workspace unavailable.", 403)
        self.transactions += 1
        with self.db.lock:
            snap = self.db.snapshot()
        try:
            yield FakeCursor(self.db), (7, {}, role, False, False, False, False), principal
        except BaseException:
            with self.db.lock:
                self.db.restore(snap)
            raise
        with self.db.lock:
            self.db.version += 1

    def connection_factory(self):
        return FakeConn(self.db)


class FakeIdeas:
    @staticmethod
    def _member(row):
        from postriff_phase2.permissions import Membership
        return Membership.from_row(*row[2:7])


class FakeLedger:
    def __init__(self, db: FakeDB):
        self.db = db

    def reserve(self, cur, workspace_id, member_id, dimension, estimated_usd_micro, idempotency_key, *, charge_batch, provider="", model="", run_id=None,
                job_id=None, meta=None, credit_authority=None):
        with self.db.lock:
            self.db.reserve_calls.append({"key": idempotency_key, "estimate": estimated_usd_micro, "runId": run_id, "meta": dict(meta or {}), "provider": provider,
                                          "model": model, "member": member_id, "authority": credit_authority})
            if self.db.reserve_error is not None:
                raise self.db.reserve_error
            for r in self.db.ledger:
                if r["kind"] == "reserve" and r["key"] == idempotency_key and r["workspaceId"] == workspace_id:
                    return {"reservationId": r["id"], "duplicate": True}
            rid = uid()
            self.db.ledger.append({"id": rid, "kind": "reserve", "key": idempotency_key, "estimate": estimated_usd_micro, "actual": None, "costState": "estimated",
                                   "reservationId": rid, "meta": dict(meta or {}), "runId": run_id, "workspaceId": workspace_id})
            return {"reservationId": rid, "duplicate": False, "warnings": []}

    def settle(self, cur, workspace_id, reservation_id, outcome, actual_usd_micro=None, idempotency_key=None):
        with self.db.lock:
            self.db.settle_calls.append((reservation_id, outcome, actual_usd_micro))
            if outcome == "completed" and actual_usd_micro is None:
                outcome = "unknown"
            terminal = self.db._terminal(reservation_id)
            if terminal:
                return {"reservationId": reservation_id, "duplicate": True, "state": terminal["costState"]}
            reserve = next(r for r in self.db.ledger if r["id"] == reservation_id and r["kind"] == "reserve")
            if outcome == "unknown":
                if any(r["reservationId"] == reservation_id and r["costState"] == "estimated_unknown" for r in self.db.ledger):
                    return {"reservationId": reservation_id, "duplicate": True, "state": "estimated_unknown"}
                self.db.ledger.append({**reserve, "id": uid(), "kind": "settle", "actual": None, "costState": "estimated_unknown"})
                return {"reservationId": reservation_id, "state": "estimated_unknown"}
            kind = "settle" if outcome == "completed" else "release"
            self.db.ledger.append({**reserve, "id": uid(), "kind": kind, "actual": int(actual_usd_micro or 0), "costState": "actual" if kind == "settle" else "released"})
            return {"reservationId": reservation_id, "state": "actual" if kind == "settle" else "released"}


class FakeRuntime:
    def __init__(self, db: FakeDB, cfg, transport, assets_dir):
        self.service = SimpleNamespace(repository=FakeRepository(db), ideas=FakeIdeas, ledger=FakeLedger(db))
        self.cfg, self.ui_transport, self.ui_assets_dir = cfg, transport, assets_dir
        self.approvals = []

    def _reservation_approval(self, cur, workspace_id, principal, revision, cost, route, run_id):
        self.approvals.append((principal, cost, run_id))
        return None, {}


# --- lane F's store (faithful fake) ----------------------------------------------------------------------------------------
class FakeStore:
    def __init__(self, db: FakeDB):
        self.db = db
        self.creates = []

    def _art(self, artifact_id, auth=None):
        art = self.db.artifacts.get(artifact_id)
        if not art or (auth is not None and art["workspaceId"] != auth.workspace_id):
            raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
        return art

    def _lease(self, art, attempt, created, cursor):
        return {"artifact": copy.deepcopy(art), "attempt": copy.deepcopy(attempt) if attempt else None, "created": created, "producer": created,
                "replay_cursor": cursor}

    def _cursor_for(self, art, attempt):
        if attempt:
            seqs = [e["seq"] for e in self.db.events if e["artifactId"] == art["artifactId"] and e["attemptId"] == attempt["attemptId"]]
            if seqs:
                return min(seqs) - 1
        return max(0, art["nextSeq"] - 1)

    def create_or_resume_artifact(self, cur, auth, parent_run_id, slot, idempotency_key, *, surface, manifest, projection, kind="generate", retry_of=None,
                                  lease_owner, base=None, library=None):
        with self.db.lock:
            self.creates.append({"kind": kind, "key": idempotency_key, "base": base, "library": library, "retryOf": retry_of})
            existing = next((a for a in self.db.attempts.values() if a["workspaceId"] == auth.workspace_id and a["idempotencyKey"] == idempotency_key), None)
            if existing:
                art = self._art(existing["artifactId"], auth)
                return self._lease(art, existing, False, self._cursor_for(art, existing))
            run = self.db.runs.get(parent_run_id)
            if not run or run["workspaceId"] != auth.workspace_id:
                raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
            if run["status"] != "completed" or not run["result"]["ui"]["eligible"]:
                raise AlphaError("not eligible", 409, code="not_eligible")
            art = next((a for a in self.db.artifacts.values() if a["runId"] == parent_run_id and a["slot"] == slot), None)
            if art is None:
                art = {"artifactId": uid(), "workspaceId": auth.workspace_id, "runId": parent_run_id, "conversationId": run["conversationId"], "slot": slot,
                       "actor": str(auth.principal), "surface": surface, "journeyIds": list((projection or {}).get("journey_ids") or []), "revision": 0,
                       "sourceHash": None, "manifest": copy.deepcopy(manifest or {}), "nextSeq": 1, "generationState": "queued", "validationState": "pending",
                       "currentAttemptId": None, "scope": "workspace", "scopeKey": "", "library": library}
                self.db.artifacts[art["artifactId"]] = art
            current = self.db.attempts.get(art["currentAttemptId"]) if art["currentAttemptId"] else None
            if current and current["state"] in LIVE:
                return self._lease(art, current, False, self._cursor_for(art, current))
            base_revision = base_hash = None
            instruction = None
            if kind == "generate":
                if current is not None or art["revision"] >= 1:
                    return self._lease(art, current, False, self._cursor_for(art, current))
            elif kind == "retry":
                prior = self.db.attempts.get(retry_of)
                if not prior or prior["artifactId"] != art["artifactId"] or prior["state"] not in ("failed", "canceled", "interrupted"):
                    raise AlphaError("Only a stopped view can be tried again.", 409, code="ui_retry")
            elif kind == "repair":
                prior = self.db.attempts.get(retry_of)
                if not prior or prior["state"] != "failed" or prior["kind"] == "repair":
                    raise AlphaError("A repair follows exactly one failed attempt.", 409, code="ui_retry")
                if any(a["retryOf"] == retry_of and a["kind"] == "repair" for a in self.db.attempts.values()):
                    raise AlphaError("already repaired", 409, code="repair_exhausted")
                base_revision, base_hash, instruction = prior["baseRevision"], prior["baseSourceHash"], prior["instruction"]
            else:  # edit
                base = base or {}
                if art["revision"] < 1 or base.get("revision") != art["revision"] or base.get("sourceHash") != art["sourceHash"]:
                    raise AlphaError("changed", 409, code="ui_revision_conflict")
                base_revision, base_hash, instruction = art["revision"], art["sourceHash"], base.get("instruction")
            target = art["revision"] + 1
            if any(a["artifactId"] == art["artifactId"] and a["targetRevision"] == target and a["state"] in LIVE for a in self.db.attempts.values()):
                live = next(a for a in self.db.attempts.values() if a["artifactId"] == art["artifactId"] and a["state"] in LIVE)
                return self._lease(art, live, False, self._cursor_for(art, live))
            attempt = {"attemptId": uid(), "artifactId": art["artifactId"], "workspaceId": auth.workspace_id, "kind": kind, "targetRevision": target,
                       "baseRevision": base_revision, "baseSourceHash": base_hash, "state": "queued", "reason": None, "idempotencyKey": idempotency_key,
                       "retryOf": retry_of, "instruction": instruction, "leaseOwner": lease_owner, "leaseExpired": False, "reservationId": None,
                       "providerAttempts": 0, "usage": {}, "costUsdMicro": None, "costState": "none", "checkpointSource": ""}
            self.db.attempts[attempt["attemptId"]] = attempt
            art["currentAttemptId"] = attempt["attemptId"]
            if art["revision"] < 1:
                art["generationState"], art["validationState"] = "queued", "pending"
            return self._lease(art, attempt, True, max(0, art["nextSeq"] - 1))

    def append_event(self, conn_or_cur, artifact_id, attempt_id, revision, kind, payload):
        with self.db.lock:
            if kind not in contracts.EVENT_KINDS:
                raise ValueError(kind)
            if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 40000:
                raise AlphaError("too large", 413, code="ui_event_too_large")
            art = self._art(artifact_id)
            seq = art["nextSeq"]
            art["nextSeq"] += 1
            event = contracts.make_event(artifact_id, attempt_id, int(revision or 0), seq, kind, copy.deepcopy(payload))
            self.db.events.append(event)
            return copy.deepcopy(event)

    def checkpoint(self, conn_or_cur, attempt_id, source, *, lease_owner):
        with self.db.lock:
            t = self.db.attempts[attempt_id]
            if t["state"] not in LIVE:
                raise AlphaError("stopped", 409, code="ui_attempt_closed")
            if t["leaseOwner"] != lease_owner or t["leaseExpired"]:
                raise AlphaError("lost", 409, code="ui_lease_lost")
            if len(source.encode("utf-8")) > contracts.BOUNDS["sourceBytes"]:
                raise AlphaError("too large", 413, code="source_too_large")
            t["checkpointSource"] = source
            if t["state"] == "queued":
                t["state"] = "streaming"
                self._mirror(t)

    def _mirror(self, t):
        art = self.db.artifacts[t["artifactId"]]
        if art["revision"] == 0 and art["currentAttemptId"] == t["attemptId"]:
            art["generationState"] = t["state"]

    def commit_ui_revision(self, cur, auth, patch, validation):
        with self.db.lock:
            art = self._art(patch["artifactId"], auth)
            t = self.db.attempts[patch["attemptId"]]
            if t["state"] not in LIVE:
                raise AlphaError("stopped", 409, code="ui_attempt_closed")
            if patch["baseRevision"] != art["revision"] or t["targetRevision"] != art["revision"] + 1:
                raise AlphaError("changed", 409, code="ui_revision_conflict")
            if art["revision"] >= 1 and patch.get("baseSourceHash") != art["sourceHash"]:
                raise AlphaError("changed", 409, code="ui_revision_conflict")
            if not validation.get("accepted"):
                raise AlphaError("rejected", 422, code="parse_rejected")
            canonical = validation["canonicalSource"]
            art["revision"] += 1
            art["sourceHash"] = contracts.sha256_text(canonical)
            art["generationState"], art["validationState"] = "ready", "accepted"
            self.db.revisions[(art["artifactId"], art["revision"])] = canonical
            t["state"] = "ready"
            self.db.events = [e for e in self.db.events if not (e["attemptId"] == t["attemptId"] and e["kind"] == "ui.delta")]   # F compacts deltas
            return {"artifactId": art["artifactId"], "revision": art["revision"], "sourceHash": art["sourceHash"], "generationState": "ready",
                    "validationState": "accepted", "canonicalSource": canonical}

    def finish_attempt(self, cur, attempt_id, state, reason=None, usage=None):
        with self.db.lock:
            t = self.db.attempts[attempt_id]
            if state != t["state"]:
                contracts.require_transition(t["state"], state)
            t["state"] = state
            t["reason"] = reason or t["reason"]
            self._mirror(t)
            return copy.deepcopy(t)

    def events_after(self, cur, auth, artifact_id, after, limit):
        with self.db.lock:
            self._art(artifact_id, auth)
            out = [copy.deepcopy(e) for e in self.db.events if e["artifactId"] == artifact_id and e["seq"] > after]
            return sorted(out, key=lambda e: e["seq"])[:limit]

    def reap_expired(self, cur, workspace_id, now, *, ledger=None, limit=50):
        with self.db.lock:
            count = 0
            for t in list(self.db.attempts.values()):
                if t["workspaceId"] == workspace_id and t["state"] in LIVE and t["leaseExpired"]:
                    if t["reservationId"] and ledger is not None:
                        ledger.settle(cur, workspace_id, t["reservationId"], "unknown")
                    t["state"], t["reason"] = "interrupted", "lease_expired"
                    self._mirror(t)
                    self.append_event(cur, t["artifactId"], t["attemptId"], 0, "ui.interrupted", {"reason": "lease_expired", "fallback": "native"})
                    count += 1
            return count


# --- lane D and C fakes ------------------------------------------------------------------------------------------------------
def fake_projection(cur, auth, verified_result, surface, selection_state, *, flags=None):
    return {"manifest_id": "m-1", "journey_ids": list((verified_result.get("ui") or {}).get("journeyIds") or ["J01"]), "component_group_ids": ["layout", "data"],
            "data_bindings": [{"name": "drafts_list"}], "action_bindings": [{"actionId": "draft_edit"}],
            "allowed_context": {"counts": {"drafts": 3}, "toolStates": {"drafts_list": "available"}, "refs": [{"type": "draft", "id": "d1"}],
                                "language": "en", "body": PRIVATE_CONTEXT_TEXT, "thumbnailUrl": "https://storage.example/x?token=secret"},
            "fallback_text": "Here are your drafts.", "egress_decision": {"allowed": True, "provider": "openai", "reason": None}}


def fake_manifest(cur, auth, projection, *, scope="workspace", flags=None):
    return {"manifestId": "m-1", "bindingVersion": 1, "journeyIds": list(projection["journey_ids"]), "componentGroups": ["layout", "data"],
            "library": "consumer", "queries": [{"name": "drafts_list", "description": "Drafts in this workspace", "argsSchema": {"type": "object"},
                                                "refreshMinSeconds": 30, "pageSize": 50}],
            "actions": [{"actionId": "draft_edit", "label": "Save the edit", "effect": "MUTATE_REVERSIBLE", "requiresConfirmation": True,
                         "inputSchema": {"type": "object"}, "summary": "Saves a reversible edit"}],
            "principal": ME, "workspaceId": WS, "approvedRefs": ["draft:d1"], "actionTargets": {"draft_edit": "secret-target"}}


def fake_current(cur, auth, manifest):
    return manifest


class FakeValidator:
    """Accepts a program whose first statement is `root = RafiiRoot(` and that has no `BAD`; patch mode appends to the base."""

    def __init__(self, verdicts=None):
        self.calls = []
        self.verdicts = list(verdicts or [])

    def __call__(self, base_source, candidate_source, library_hash, mode, *, policy, scope, **_):
        self.calls.append({"base": base_source, "candidate": candidate_source, "libraryHash": library_hash, "mode": mode, "policy": copy.deepcopy(policy),
                           "scope": dict(scope)})
        verdict = self.verdicts.pop(0) if self.verdicts else None
        if verdict == "unavailable":
            return {"accepted": False, "errors": ["validation_unavailable"]}
        if isinstance(verdict, str) and verdict.startswith("errors:"):
            return {"accepted": False, "errors": verdict[len("errors:"):].split(",")}
        merged = (base_source + "\n" + candidate_source) if mode == "patch" else candidate_source
        ok = verdict == "accept" or (verdict is None and merged.lstrip().startswith("root = RafiiRoot(") and "BAD" not in candidate_source)
        if not ok:
            return {"accepted": False, "errors": ["component_denied:Bogus", "unresolved_ref"]}
        canonical = merged.strip()
        return {"accepted": True, "canonicalSource": canonical, "sourceHash": contracts.sha256_text(canonical), "statementCount": canonical.count("\n") + 1,
                "queryNames": ["drafts_list"], "actionIds": [], "componentNames": ["RafiiRoot"], "errors": [], "libraryHash": library_hash, "libraryVersion": "rafii-1"}


# --- provider -----------------------------------------------------------------------------------------------------------------
GOOD_PROGRAM = 'root = RafiiRoot([title, table])\ntitle = Text("Drafts 粵語 🎹")\ntable = ToolBoundTable("drafts_list", {})\n'


def usage_final(inp=1200, out=300, status="ok"):
    return {"status": status, "known": True, "inputTokens": inp, "outputTokens": out, "requestId": "resp_test"}


class ScriptTransport:
    """Provider stream replaying `script` steps per call: ("delta", text) | ("sleep", s) | ("final", usage) | ("raise", exc) | ("hang",)."""

    def __init__(self, *scripts):
        self.scripts = [list(s) for s in scripts]
        self.calls = []
        self.cancelled = 0
        self.closed = 0

    async def stream(self, plan, *, timeout):
        self.calls.append({"plan": plan, "timeout": timeout})
        script = self.scripts.pop(0) if self.scripts else [("delta", GOOD_PROGRAM), ("final", usage_final())]
        try:
            for step in script:
                if step[0] == "delta":
                    yield ("delta", step[1])
                elif step[0] == "sleep":
                    await asyncio.sleep(step[1])
                elif step[0] == "final":
                    yield ("final", dict(step[1]))
                elif step[0] == "raise":
                    raise step[1]
                elif step[0] == "hang":
                    await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.closed += 1


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def program_in_pieces(program=GOOD_PROGRAM, size=7):
    return [("delta", program[i:i + size]) for i in range(0, len(program), size)]


# --- assets -------------------------------------------------------------------------------------------------------------------
LIBRARY_HASH = "c" * 64


def make_assets(root=None, *, tamper=False) -> str:
    root = root or tempfile.mkdtemp(prefix="rafii-ui-assets-")
    os.makedirs(os.path.join(root, "prompts"), exist_ok=True)
    prompts = {}
    for key, name, text in (("consumer:J01:generate", "consumer-J01-generate.txt", "You write openui-lang for Rafii drafts.\n## Component Signatures\nRafiiRoot(children)"),
                            ("consumer:all:generate", "consumer-all-generate.txt", "You write openui-lang for Rafii.\n## Component Signatures\nRafiiRoot(children)"),
                            ("consumer:J01:patch", "consumer-J01-patch.txt", "You edit openui-lang for Rafii.\n## Edit Mode\nsame name = replace"),
                            ("consumer:all:patch", "consumer-all-patch.txt", "You edit openui-lang for Rafii.\n## Edit Mode\nsame name = replace")):
        with open(os.path.join(root, "prompts", name), "w", encoding="utf-8") as handle:
            handle.write(text)
        prompts[key] = {"file": "prompts/" + name, "promptHash": contracts.sha256_text(text + ("x" if tamper else ""))}
    assets = {"contractVersion": contracts.CONTRACT_VERSION, "languageVersion": "0.3.2", "libraryVersion": "rafii-1",
              "libraries": {"consumer": {"libraryHash": LIBRARY_HASH, "root": "RafiiRoot",
                                         "components": ["RafiiRoot", "Stack", "Card", "Text", "ToolBoundTable", "EmptyState", "ActionButton", "ToolBoundChart"],
                                         "groups": {"layout": ["Stack", "Card", "Text", "EmptyState"], "data": ["ToolBoundTable", "ActionButton"],
                                                    "charts": ["ToolBoundChart"]},
                                         "schemaFile": "consumer.schema.json"}},
              "journeys": {"J01": {"library": "consumer", "groups": ["layout", "data"]}, "J06": {"library": "consumer", "groups": ["layout", "charts"]}},
              "prompts": prompts}
    with open(os.path.join(root, "openui-assets.json"), "w", encoding="utf-8") as handle:
        json.dump(assets, handle)
    return root


def make_cfg(**extra):
    values = {"OPENAI_API_KEY": "sk-test-not-a-real-key", "RAFII_AGENT_V2_ENABLED": "1", "RAFII_GENUI_ENABLED": "1", "RAFII_GENUI_EDITS_ENABLED": "1",
              "RAFII_GENUI_ACTIONS_ENABLED": "1", "RAFII_GENUI_FOUNDER_ENABLED": "1"}
    values.update(extra)
    return config.RuntimeConfig.from_environment(values={k: v for k, v in values.items() if v is not None})


# --- WSGI helpers ---------------------------------------------------------------------------------------------------------------
class Started:
    def __init__(self):
        self.status, self.headers = None, None

    def __call__(self, status, headers):
        self.status, self.headers = status, headers


def parse(data: bytes) -> list[dict]:
    text = data.decode("utf-8")
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def frame_ids(data: bytes) -> list[str]:
    return [line[4:] for line in data.decode("utf-8").split("\n") if line.startswith("id: ")]
