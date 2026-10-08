"""The acceptance world: real actors on the running harness (serve.py), their workspace, a completed Manager turn and a
presentation, plus the BLOCKED rule and per-check evidence recording shared by the API corpus.

Actors are real dev identities (`Bearer dev:<uuid>`) created through `POST /api/auth/verify`; extra roles are memberships
in the owner's workspace (setup fixture rows on the disposable database — assertions only ever go through the API). The
seed is the same path the existing browser scenes use (LinkedIn consent stand-in, deterministic preview writer, a
confirmed draft), so drafts/calendar/campaign tools have real records to read.

BLOCKED: when a lane's route still answers 503 `ui_not_ready` (its stub), or a positive control cannot be established,
the check raises `Blocked` (a unittest skip) and is recorded `blocked` with the exact lane and route. A blocked check is
never counted as a pass; `release` mode refuses it and strict runs (PRs to consumer-saas, AGENT_UI_REQUIRE_COMPLETE=1)
fail on it.
"""
from __future__ import annotations

import functools
import json
import os
import threading
import time
import unittest
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .client import Api, new_key
from .db import Db
from .evidence import Recorder

ROUTE_OWNER = {"presentations": "B (ui_stream.create_presentation)", "events": "B (ui_stream.replay)", "cancel": "B (ui_stream.cancel_http)",
               "edits": "B (ui_stream.create_edit)", "probe": "B (ui_stream.probe)", "snapshot": "F (ui_store.snapshot_http)",
               "state": "F (ui_store.persist_state_http)", "messages": "F (ui_store.by_message_http)", "queries": "D (ui_queries.query_http)",
               "activate": "D (ui_actions.activate_http)", "actions": "D (ui_actions.execute_http)", "eligibility": "D (ui_projection.eligibility)"}
TERMINAL = ("ui.ready", "ui.failed", "ui.canceled", "ui.interrupted")
# Harness Manager prompts (agent_runtime_v2/harness.manager_step) that make it call a read tool, phrased with an explicit
# UI intent (table/compare/chart/timeline) so lane D's deterministic eligibility can choose a journey.
ELIGIBLE_PROMPTS = ("Chart what's missing in the campaign by status", "Compare my campaigns side by side in a table", "Show what's still left in a table I can filter")


def turn_view(body: dict) -> dict:
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    return {**result, **{k: body[k] for k in ("runId", "conversationId", "messageId", "status") if body.get(k) is not None}}


class Blocked(unittest.SkipTest):
    """A positive control that a lane has not delivered yet. Recorded `blocked`, never `pass`."""


def blocked_if_not_ready(response, route: str):
    status = getattr(response, "status", None)
    code = getattr(response, "code", None)
    if status == 503 and code == "ui_not_ready":
        raise Blocked(f"BLOCKED lane {ROUTE_OWNER.get(route, route)}: {route} answers 503 ui_not_ready")
    return response


@dataclass
class Actor:
    name: str
    principal: str
    workspace_id: str | None = None

    @property
    def token(self) -> str:
        return f"dev:{self.principal}"


@dataclass
class Presentation:
    status: int
    artifact_id: str | None
    attempt_id: str | None
    events: list = field(default_factory=list)
    terminal: dict | None = None
    body: dict | None = None
    stream: object = None

    def kinds(self):
        return [e.get("event") for e in self.events]

    def payload(self, kind):
        for event in self.events:
            if event.get("event") == kind and isinstance(event.get("data"), dict):
                return event["data"].get("payload") or {}
        return None


class World:
    """One per test process. Lazily builds actors, the seed and a ready artifact; everything is cached per run."""
    _lock = threading.Lock()
    _instance = None

    @classmethod
    def get(cls) -> "World":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        url = os.environ.get("AGENT_UI_API_URL")
        state_file = os.environ.get("AGENT_UI_STACK_STATE")
        if not url or not state_file:
            raise RuntimeError("run by scripts/agent_ui_acceptance.sh: AGENT_UI_API_URL and AGENT_UI_STACK_STATE are required")
        self.state = json.loads(Path(state_file).read_text(encoding="utf-8"))
        self.api = Api(url)
        self.db = Db(self.state["dsn"])
        provider = self.state.get("providerUrl")
        self.provider = Api(provider.rsplit("/v1", 1)[0]) if provider else None
        self.actors: dict[str, Actor] = {}
        self._seeded = None
        self._ready = None
        self._blocked: dict = {}          # positive controls already proven unavailable this run (deterministic harness)

    # --- provider boundary (fixture provider) -------------------------------------------------------------------------
    def provider_requests(self) -> int:
        """Every request that reached the provider boundary (agent, helper and presenter)."""
        if not self.provider:
            raise Blocked("BLOCKED harness: no fixture provider URL in the stack state")
        return int((self.provider.request("GET", "/__stats").json() or {}).get("requests") or 0)

    def presenter_requests(self) -> int:
        """Presenter requests only (no tools, free text): one per physical presentation attempt."""
        if not self.provider:
            raise Blocked("BLOCKED harness: no fixture provider URL in the stack state")
        return int((self.provider.request("GET", "/__stats").json() or {}).get("presenterRequests") or 0)

    def arm(self, fault: str | None, count: int = 1):
        self.provider.request("POST", "/__fault", body={"fault": fault, "count": count})

    def seen(self, markers, kinds=("presenter",)) -> dict:
        return (self.provider.request("POST", "/__seen", body={"markers": list(markers), "kinds": list(kinds)}).json() or {}).get("seen") or {}

    # --- actors ---------------------------------------------------------------------------------------------------------
    def actor(self, name: str) -> Actor:
        if name in self.actors:
            return self.actors[name]
        actor = Actor(name, str(uuid.uuid4()))
        boot = self.api.request("POST", "/api/auth/verify", actor.token, {})
        if boot.status not in (200, 201):
            raise AssertionError(f"auth/verify for {name} failed: {boot.status} {boot.text(200)}")
        actor.workspace_id = (boot.json() or {}).get("workspaceId")
        self.actors[name] = actor
        owner = self.actors.get("owner") if name != "owner" else None
        if name in ("editor", "viewer", "revocable", "expiring", "approver") and owner is None:
            owner = self.actor("owner")
        if name in ("editor", "viewer", "revocable", "expiring", "approver"):
            role = {"revocable": "editor", "expiring": "editor"}.get(name, name)
            self.db.add_member(owner.workspace_id, actor.principal, role)
            actor.workspace_id = owner.workspace_id
        return actor

    def base(self, actor: Actor, workspace_id: str | None = None) -> str:
        return f"/api/workspaces/{workspace_id or actor.workspace_id}/agent/ui"

    # --- seed (same path as the existing browser scenes) --------------------------------------------------------------
    def call(self, actor, method, path, body=None, ok=(200, 201)):
        answer = self.api.request(method, path, actor.token, body if body is not None or method == "GET" else {})
        if answer.status not in ok:
            raise AssertionError(f"{method} {path} → {answer.status} {answer.text(300)}")
        return answer.json()

    def seed(self) -> dict:
        if self._seeded:
            return self._seeded
        owner = self.actor("owner")
        w = owner.workspace_id
        out = {"workspaceId": w}
        try:
            start = self.call(owner, "POST", f"/api/workspaces/{w}/channels/linkedin/oauth/start", {"capability": "publish"})
            from urllib.parse import parse_qs, urlsplit
            state = parse_qs(urlsplit(start["authorizeUrl"]).query)["state"][0]
            self.call(owner, "POST", f"/api/workspaces/{w}/channels/linkedin/oauth/complete", {"state": state, "code": "good-code"})
            snap = self.call(owner, "GET", f"/api/workspaces/{w}")
            linkedin = next(c for c in snap["state"]["phase2"]["channels"] if c["platform"] == "LinkedIn")
            run = self.call(owner, "POST", f"/api/workspaces/{w}/ideas/quick-start", {
                "expectedRevision": snap["revision"], "text": "Slow practice builds fast fingers: three minutes, one bar, eyes closed.", "ownContent": True,
                "confirmUse": True, "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": linkedin["id"]}], "model": "deterministic-preview",
                "reasoning": "quick", "voiceMode": "neutral", "timeZone": "Asia/Hong_Kong"})
            snap = self.call(owner, "GET", f"/api/workspaces/{w}")
            self.call(owner, "POST", f"/api/workspaces/{w}/ideas/runs/{run['runId']}/apply", {"expectedRevision": snap["revision"], "artifactHash": run["artifactHash"]})
            snap = self.call(owner, "GET", f"/api/workspaces/{w}")
            draft = next((v for v in snap["state"].get("variants") or [] if (v.get("provenance") or {}).get("runId") == run["runId"]), None)
            out.update({"channelId": linkedin["id"], "draftId": draft and draft["id"]})
        except (AssertionError, KeyError, StopIteration) as error:
            out["seedError"] = str(error)[:300]
        self._seeded = out
        return out

    # --- turns and presentations ----------------------------------------------------------------------------------------
    def turn(self, actor: Actor, message: str, **extra) -> dict:
        """One real agent turn. Returns the stored result merged with the run identity (POST turns answers
        {conversationId, runId, status, messageId, result: {..., ui, usage, speakableSummary}})."""
        body = {"message": message, "idempotencyKey": new_key("turn"), "timeZone": "Asia/Hong_Kong", "modality": "text",
                **{k: v for k, v in extra.items() if v is not None}}
        answer = self.api.request("POST", f"/api/workspaces/{actor.workspace_id}/agent/turns", actor.token, body, timeout=180)
        if answer.status not in (200, 201):
            raise AssertionError(f"agent turn failed: {answer.status} {answer.text(300)}")
        return turn_view(answer.json() or {})

    def eligible_turn(self, actor: Actor) -> dict:
        if "eligible" in self._blocked:
            raise Blocked(self._blocked["eligible"])
        reasons = []
        for prompt in ELIGIBLE_PROMPTS:
            result = self.turn(actor, prompt)
            ui = result.get("ui") or {}
            if ui.get("eligible") and result.get("runId"):
                return result
            usage = result.get("usage") or {}
            reasons.append(f"{prompt!r} → ui={json.dumps(ui)[:120]} composedBy={result.get('composedBy')} billing={usage.get('billing')} "
                           f"tools={[a.get('tool') for a in (result.get('toolActivity') or [])][:6]}")
        self._blocked["eligible"] = ("BLOCKED lane D (ui_projection.eligibility) or the turn seam: no harness Manager turn was eligible; "
                                     + "; ".join(reasons)[:500])
        raise Blocked(self._blocked["eligible"])

    def present(self, actor: Actor, run_id: str, key: str | None = None, *, surface="chat", drain=True, max_seconds=120, until=None) -> Presentation:
        body = {"parentRunId": run_id, "slot": "main", "surface": surface, "idempotencyKey": key or new_key("present")}
        stream = self.api.stream("POST", self.base(actor) + "/presentations", actor.token, body, timeout=30)
        if stream.body_if_json is not None:
            from .client import Response
            resp = Response(stream.status, stream.headers, stream.body_if_json)
            blocked_if_not_ready(resp, "presentations")
            return Presentation(stream.status, None, None, body=resp.json())
        out = Presentation(stream.status, None, None, stream=stream)
        if drain:
            for event in stream.iter_events(max_seconds=max_seconds, until=until):
                self._note(out, event)
            out.events = list(stream.events)
            for event in out.events:
                self._note(out, event)
            if until is None:
                stream.close()
        return out

    @staticmethod
    def _note(out: Presentation, event: dict):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        out.artifact_id = out.artifact_id or data.get("artifactId")
        out.attempt_id = out.attempt_id or data.get("attemptId")
        if event.get("event") in TERMINAL:
            out.terminal = event

    def ready_artifact(self) -> dict:
        """One ready, accepted artifact of the owner's eligible turn (cached). Blocked if any lane can't produce it yet."""
        if self._ready:
            return self._ready
        if "ready" in self._blocked:
            raise Blocked(self._blocked["ready"])
        try:
            return self._make_ready()
        except Blocked as blocked:
            self._blocked["ready"] = str(blocked)
            raise

    def _make_ready(self) -> dict:
        self.seed()
        owner = self.actor("owner")
        result = self.eligible_turn(owner)
        before = self.provider_requests()
        key = new_key("ready")
        shown = self.present(owner, result["runId"], key)
        if shown.status != 200 or not shown.terminal:
            raise Blocked(f"BLOCKED lane B/F: presentation answered {shown.status} with no terminal event ({shown.kinds()[:8]})")
        if shown.terminal.get("event") != "ui.ready":
            reason = ((shown.terminal.get("data") or {}).get("payload") or {}).get("reason")
            raise Blocked(f"BLOCKED lanes B/C: the fixture presentation ended {shown.terminal.get('event')} ({reason}); a valid fixture source needs C's generated "
                          "schema and validator, B's stream, F's store")
        snap = self.api.request("GET", f"{self.base(owner)}/presentations/{shown.artifact_id}", owner.token)
        blocked_if_not_ready(snap, "snapshot")
        artifact = (snap.json() or {}).get("artifact") or {}
        self._ready = {"runId": result["runId"], "conversationId": result.get("conversationId"), "messageId": result.get("messageId") or artifact.get("messageId"),
                       "artifactId": shown.artifact_id, "attemptId": shown.attempt_id, "key": key, "artifact": artifact,
                       "manifest": (snap.json() or {}).get("manifest") or {}, "providerRequests": self.provider_requests() - before, "events": shown.kinds()}
        return self._ready

    def ui(self, actor: Actor, method: str, tail: str, body=None, *, workspace_id=None, route=None, headers=None, timeout=None):
        answer = self.api.request(method, self.base(actor, workspace_id) + tail, actor.token, body if body is not None or method == "GET" else {},
                                  headers=headers, timeout=timeout)
        if route:
            blocked_if_not_ready(answer, route)
        return answer

    def wait_attempt(self, artifact_id, predicate, seconds=90):
        deadline = time.monotonic() + seconds
        rows = []
        while time.monotonic() < deadline:
            rows = self.db.attempts(artifact_id)
            if predicate(rows):
                return rows
            time.sleep(0.5)
        return rows


def recorded(recorder: Recorder, prefix: str):
    """Decorator factory: record pass / fail / blocked for one check under `<prefix>.<Class>.<method>` (the names corpus.py
    maps to gates), then re-raise so unittest reports the same outcome."""
    def decorate(fn):
        @functools.wraps(fn)
        def run(self, *args, **kwargs):
            name = f"{prefix}.{type(self).__name__}.{fn.__name__}"
            try:
                detail = fn(self, *args, **kwargs)
            except unittest.SkipTest as skipped:
                recorder.add(name, "blocked", str(skipped))
                raise
            except AssertionError as error:
                recorder.add(name, "fail", str(error))
                raise
            except Exception as error:  # noqa: BLE001 — an unexpected error is a failing check, recorded and re-raised
                recorder.add(name, "fail", f"{type(error).__name__}: {error}")
                raise
            recorder.add(name, "pass", detail if isinstance(detail, str) else "ok")
            return None   # the detail lives in the evidence record; unittest wants None
        return run
    return decorate


RECORD = Recorder("api-corpus")
check = recorded(RECORD, "api_corpus")
