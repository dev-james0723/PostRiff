"""Shared contract of Rafii Generative UI (`rafii-genui/1`), Python side.

Frozen by the release coordinator (role A). The TypeScript mirror is `web/src/lib/agent-runtime/ui-contracts.ts`; both are
checked against `tests/fixtures/agent_ui/contracts/contract-manifest.json`, so a change on one side without the other fails
CI. Lanes import from here; only A edits it (docs/design/openui-production-2026-10-08/02-CONTRACTS.md).

What this module is: names, states, bounds, request validators, the input digest, SSE framing and the public projection of
an artifact. What it is not: storage (ui_store), streaming (ui_stream), queries/actions (ui_queries, ui_actions) or the
parser (the Node validator). Nothing here grants authority: every route still authenticates, re-checks membership and
re-reads the business record through the original domain service.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError

CONTRACT_VERSION = "rafii-genui/1"
LANGUAGE = "openui-lang"

# --- vocabulary (02-CONTRACTS §2) --------------------------------------------------------------------------------------
UI_SURFACES = ("chat", "panel", "expanded", "mobile", "browser_voice", "founder")
GENERATION_STATES = ("queued", "streaming", "validating", "ready", "failed", "canceled", "interrupted")
TERMINAL_GENERATION_STATES = ("ready", "failed", "canceled", "interrupted")
VALIDATION_STATES = ("pending", "accepted", "rejected")
DATA_STATES = ("loading", "available", "empty", "partial", "unavailable", "denied", "stale")
ACTION_OUTCOMES = ("prepared", "applied", "rejected", "conflict", "pending", "failed")
EVENT_KINDS = ("ui.started", "ui.delta", "ui.checkpoint", "ui.ready", "ui.failed", "ui.canceled", "ui.interrupted",
               "ui.state_changed", "ui.binding_changed", "ui.heartbeat")
TERMINAL_EVENT_KINDS = ("ui.ready", "ui.failed", "ui.canceled", "ui.interrupted")
ATTEMPT_KINDS = ("generate", "repair", "edit", "retry")
REVISION_KINDS = ("generate", "repair", "edit")
SCOPES = ("workspace", "founder")
SLOTS = ("main",)
JOURNEYS = ("J01", "J02", "J03", "J04", "J05", "J06", "J07", "J08", "J09")
CONSUMER_JOURNEYS = JOURNEYS[:8]
FOUNDER_JOURNEYS = ("J09",)

# Effect classes a UI action binding may carry (subset of contracts.EFFECTS). Queries are always READ. EXTERNAL_EFFECT,
# DESTRUCTIVE and SECRET never appear in a manifest: publishing, sending, buying, deleting, disconnecting and secrets stay
# on their own authenticated pages (spec §6.3).
UI_ACTION_EFFECTS = ("CREATE_DRAFT", "MUTATE_REVERSIBLE", "PREPARE_EXTERNAL")
UI_QUERY_EFFECT = "READ"

# Allowed state machine (02-CONTRACTS §5). A ready revision is immutable; an edit is a new attempt on a new target revision.
TRANSITIONS = {
    "queued": ("streaming", "failed", "canceled", "interrupted"),
    "streaming": ("validating", "failed", "canceled", "interrupted"),
    "validating": ("ready", "failed", "canceled", "interrupted"),
    "ready": (),
    "failed": (),
    "canceled": (),
    "interrupted": (),
}

# Stable reason codes for ui.failed / ui.canceled / ui.interrupted and for native fallbacks. Never free text from a model.
REASON_CODES = (
    "not_eligible", "disabled", "budget", "price_unknown", "no_model_route", "egress_denied", "provider_error", "provider_timeout",
    "parse_rejected", "validation_unavailable", "source_too_large", "repair_exhausted", "canceled_by_user", "client_gone",
    "lease_expired", "superseded", "library_unsupported", "revision_conflict", "internal_error",
)

# --- bounds (02-CONTRACTS §7). Tighten with evidence; never widen silently ---------------------------------------------
BOUNDS = {
    "sourceBytes": 128 * 1024,
    "patchBytes": 32 * 1024,
    "founderPatchBytes": 24 * 1024,      # the control dispatcher caps bodies at 32 768 bytes including JSON overhead
    "statements": 512,
    "treeDepth": 24,
    "queryPageDefault": 50,
    "queryPageMax": 100,
    "queryWindowDays": 366,
    "queryConcurrentPerArtifact": 4,
    "queryPerMinute": 60,
    "refreshMinSeconds": 30,
    "searchDebounceMs": 300,
    "stateBytes": 16 * 1024,
    "stateDebounceMs": 500,
    "providerAttempts": 2,               # 1 initial + at most 1 automatic UI-only repair
    "generationTimeoutSeconds": 60,
    "activationSeconds": 60,
    "requestBodyBytes": 160 * 1024,      # outer cap before any per-field check
    "inputBytes": 16 * 1024,             # query/action inputs
    "inputDepth": 8,
    "heartbeatSeconds": 10,
    "replayTailSeconds": 30,
    "replayPageEvents": 500,
    "checkpointBytes": 4 * 1024,
    "checkpointMs": 1000,
    "validatorTimeoutSeconds": 8,
}

FLAGS = ("RAFII_GENUI_ENABLED", "RAFII_GENUI_ACTIONS_ENABLED", "RAFII_GENUI_EDITS_ENABLED", "RAFII_GENUI_FOUNDER_ENABLED")
# Comma-separated workspace ids; empty means every eligible workspace once RAFII_GENUI_ENABLED is on (canary control).
CANARY_ENV = "RAFII_GENUI_WORKSPACES"

ROUTES = {
    "consumerBase": "/api/workspaces/{workspaceId}/agent/ui",
    "founderBase": "/api/control/v2/agent/ui",
    "presentations": "POST {base}/presentations",
    "snapshot": "GET {base}/presentations/{artifactId}",
    "events": "GET {base}/presentations/{artifactId}/events?after={seq}",
    "cancel": "POST {base}/presentations/{artifactId}/cancel",
    "edits": "POST {base}/presentations/{artifactId}/edits",
    "state": "POST {base}/presentations/{artifactId}/state",
    "queries": "POST {base}/queries",
    "activate": "POST {base}/actions/activate",
    "actions": "POST {base}/actions",
    "byMessage": "GET {base}/messages/{messageId}",
    "probe": "GET {base}/diagnostics/stream",
    "validator": "POST /internal/agent-ui/validate",
}

# --- identifiers -------------------------------------------------------------------------------------------------------
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_ACTIVATION = re.compile(r"^act_[A-Za-z0-9_-]{32,64}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")           # query binding names and action ids (lowercase: never a component)
_HASH = re.compile(r"^[0-9a-f]{64}$")


def valid_uuid(value) -> bool:
    return isinstance(value, str) and bool(_UUID.match(value))


def valid_idempotency_key(value) -> bool:
    return isinstance(value, str) and bool(_IDEMPOTENCY.match(value))


def valid_activation_id(value) -> bool:
    return isinstance(value, str) and bool(_ACTIVATION.match(value))


def valid_name(value) -> bool:
    return isinstance(value, str) and bool(_NAME.match(value))


def valid_hash(value) -> bool:
    return isinstance(value, str) and bool(_HASH.match(value))


def new_activation_id() -> str:
    return "act_" + secrets.token_urlsafe(32)


def new_attempt_seed() -> str:
    return secrets.token_hex(16)


def event_id(artifact_id: str, seq: int) -> str:
    return f"{artifact_id}:{seq}"


def parse_event_id(value) -> int | None:
    """`{artifactId}:{seq}` (Last-Event-ID) → seq; anything else → None."""
    if not isinstance(value, str) or ":" not in value:
        return None
    tail = value.rsplit(":", 1)[1]
    return int(tail) if tail.isdigit() and len(tail) <= 9 else None


# --- canonical JSON and digests ----------------------------------------------------------------------------------------
def _canon(value, depth=0, max_depth=BOUNDS["inputDepth"]):
    if max_depth is not None and depth > max_depth:
        raise AlphaError("These inputs are nested too deeply.", 400, code="ui_input_depth")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        if abs(value) > 2 ** 53:
            raise AlphaError("A number in these inputs is out of range.", 400, code="ui_input_number")
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise AlphaError("A number in these inputs is not finite.", 400, code="ui_input_number")
        return int(value) if value.is_integer() and abs(value) <= 2 ** 53 else value
    if isinstance(value, list):
        return [_canon(v, depth + 1, max_depth) for v in value]
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise AlphaError("Input keys must be text.", 400, code="ui_input_key")
        return {k: _canon(value[k], depth + 1, max_depth) for k in sorted(value)}
    raise AlphaError("These inputs contain a value Rafii can't accept.", 400, code="ui_input_type")


def canonical_json(value, *, max_depth: int | None = BOUNDS["inputDepth"]) -> str:
    """Sorted keys, no whitespace, UTF-8 text, integral floats as integers. The server is the only authority for digests.
    The default depth bound is for client-supplied inputs; server-built data (query results, manifests, schemas) passes
    `max_depth=None`."""
    return json.dumps(_canon(value, 0, max_depth), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_digest(action_id: str, inputs: dict) -> str:
    """The digest an activation is bound to: action id plus exact canonical inputs."""
    return sha256_text(canonical_json({"actionId": action_id, "inputs": inputs, "v": CONTRACT_VERSION}))


def args_hash(binding: str, inputs: dict) -> str:
    """Query dedupe key (binding + canonical arguments)."""
    return sha256_text(canonical_json({"binding": binding, "inputs": inputs}))


# --- request validators (unknown keys are refused; privilege-bearing keys never come from a client) -------------------
def _require_object(body, allowed: set, required: set, what: str) -> dict:
    if not isinstance(body, dict):
        raise AlphaError(f"{what} must be a JSON object.", 400, code="ui_body")
    extra = set(body) - allowed
    if extra:
        raise AlphaError(f"{what} has fields Rafii doesn't accept: {', '.join(sorted(extra))[:200]}.", 400, code="ui_unknown_field")
    missing = [k for k in sorted(required) if body.get(k) is None]
    if missing:
        raise AlphaError(f"{what} is missing {', '.join(missing)}.", 400, code="ui_missing_field")
    return body


def _bounded_inputs(inputs, what: str) -> dict:
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        raise AlphaError(f"{what} inputs must be an object.", 400, code="ui_input_type")
    text = canonical_json(inputs)
    if len(text.encode("utf-8")) > BOUNDS["inputBytes"]:
        raise AlphaError(f"{what} inputs are too large.", 413, code="ui_input_too_large")
    return json.loads(text)


def _revision(value, what="artifactRevision") -> int:
    if type(value) is not int or value < 0 or value > 1_000_000:
        raise AlphaError(f"{what} must be a whole number.", 400, code="ui_revision")
    return value


def validate_presentation_request(body) -> dict:
    """POST /presentations: create or resume one presentation of a completed parent run."""
    body = _require_object(body, {"parentRunId", "slot", "surface", "idempotencyKey", "retryOfAttemptId", "conversationId"},
                           {"parentRunId", "idempotencyKey"}, "This presentation request")
    if not valid_uuid(body["parentRunId"]):
        raise AlphaError("That run is unavailable.", 404, code="ui_parent_run")
    if not valid_idempotency_key(body["idempotencyKey"]):
        raise AlphaError("A valid idempotencyKey is required.", 400, code="ui_idempotency_key")
    slot = body.get("slot") or "main"
    if slot not in SLOTS:
        raise AlphaError("Unknown presentation slot.", 400, code="ui_slot")
    surface = body.get("surface") or "chat"
    if surface not in UI_SURFACES or surface == "founder":
        raise AlphaError("Unknown surface.", 400, code="ui_surface")
    retry = body.get("retryOfAttemptId")
    if retry is not None and not valid_uuid(retry):
        raise AlphaError("retryOfAttemptId is invalid.", 400, code="ui_retry")
    conversation = body.get("conversationId")
    if conversation is not None and not valid_uuid(conversation):
        raise AlphaError("That conversation is unavailable.", 404, code="ui_conversation")
    return {"parentRunId": body["parentRunId"], "slot": slot, "surface": surface, "idempotencyKey": body["idempotencyKey"],
            "retryOfAttemptId": retry, "conversationId": conversation}


def validate_query(body) -> dict:
    """UiQueryV1."""
    body = _require_object(body, {"artifactId", "artifactRevision", "bindingId", "inputs", "cursor"}, {"artifactId", "bindingId"}, "This query")
    if not valid_uuid(body["artifactId"]):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    if not valid_name(body["bindingId"]):
        raise AlphaError("Unknown data binding.", 404, code="ui_binding")
    cursor = body.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512):
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor")
    return {"artifactId": body["artifactId"], "artifactRevision": _revision(body.get("artifactRevision", 0)), "bindingId": body["bindingId"],
            "inputs": _bounded_inputs(body.get("inputs"), "Query"), "cursor": cursor}


def validate_activation(body) -> dict:
    """POST /actions/activate: the displayed control and its exact inputs."""
    body = _require_object(body, {"artifactId", "artifactRevision", "actionId", "inputs", "controlId"}, {"artifactId", "actionId"}, "This activation")
    if not valid_uuid(body["artifactId"]):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    if not valid_name(body["actionId"]):
        raise AlphaError("Unknown action.", 404, code="ui_action")
    control = body.get("controlId")
    if control is not None and (not isinstance(control, str) or len(control) > 80):
        raise AlphaError("Invalid control id.", 400, code="ui_control")
    return {"artifactId": body["artifactId"], "artifactRevision": _revision(body.get("artifactRevision", 0)), "actionId": body["actionId"],
            "inputs": _bounded_inputs(body.get("inputs"), "Action"), "controlId": control}


def validate_action(body) -> dict:
    """UiActionV1."""
    body = _require_object(body, {"artifactId", "artifactRevision", "actionId", "inputs", "idempotencyKey", "activationId"},
                           {"artifactId", "actionId", "idempotencyKey", "activationId"}, "This action")
    if not valid_uuid(body["artifactId"]):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    if not valid_name(body["actionId"]):
        raise AlphaError("Unknown action.", 404, code="ui_action")
    if not valid_idempotency_key(body["idempotencyKey"]):
        raise AlphaError("A valid idempotencyKey is required.", 400, code="ui_idempotency_key")
    if not valid_activation_id(body["activationId"]):
        raise AlphaError("This action needs a fresh confirmation.", 409, code="ui_activation")
    return {"artifactId": body["artifactId"], "artifactRevision": _revision(body.get("artifactRevision", 0)), "actionId": body["actionId"],
            "inputs": _bounded_inputs(body.get("inputs"), "Action"), "idempotencyKey": body["idempotencyKey"], "activationId": body["activationId"]}


def validate_patch(body, *, founder: bool = False) -> dict:
    """UiPatchV1 (explicit semantic edit). `instruction` is the person's words; `patchSource` is only accepted from the
    server-side presenter, never from a browser (a browser edit request carries an instruction, not DSL)."""
    body = _require_object(body, {"artifactId", "baseRevision", "baseSourceHash", "instruction", "idempotencyKey", "selection"},
                           {"baseRevision", "baseSourceHash", "instruction", "idempotencyKey"}, "This edit")
    if not valid_hash(body["baseSourceHash"]):
        raise AlphaError("baseSourceHash is invalid.", 400, code="ui_base_hash")
    if not valid_idempotency_key(body["idempotencyKey"]):
        raise AlphaError("A valid idempotencyKey is required.", 400, code="ui_idempotency_key")
    text = body["instruction"]
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise AlphaError("Say what to change in up to 2,000 characters.", 400, code="ui_instruction")
    selection = body.get("selection")
    if selection is not None:
        selection = _bounded_inputs(selection, "Selection")
    _ = founder
    return {"artifactId": body.get("artifactId"), "baseRevision": _revision(body["baseRevision"], "baseRevision"), "baseSourceHash": body["baseSourceHash"],
            "instruction": text.strip(), "idempotencyKey": body["idempotencyKey"], "selection": selection}


def validate_state_patch(body) -> dict:
    """POST /presentations/{id}/state: whitelisted UI state, compare-and-swap on stateRevision."""
    body = _require_object(body, {"expectedStateRevision", "patch"}, {"expectedStateRevision", "patch"}, "This state update")
    if not isinstance(body["patch"], dict):
        raise AlphaError("patch must be an object.", 400, code="ui_state_patch")
    text = canonical_json(body["patch"])
    if len(text.encode("utf-8")) > BOUNDS["stateBytes"]:
        raise AlphaError("This view's saved state is too large.", 413, code="ui_state_too_large")
    return {"expectedStateRevision": _revision(body["expectedStateRevision"], "expectedStateRevision"), "patch": json.loads(text)}


def validate_ui_context(value) -> dict | None:
    """The optional `uiContext` on an agent turn: which artifact/revision the person is looking at. The server re-resolves
    selections from persisted state; nothing here is trusted as a selection by itself."""
    if value is None:
        return None
    body = _require_object(value, {"artifactId", "artifactRevision", "stateRevision"}, {"artifactId"}, "uiContext")
    if not valid_uuid(body["artifactId"]):
        raise AlphaError("That view is unavailable.", 404, code="ui_artifact")
    return {"artifactId": body["artifactId"], "artifactRevision": _revision(body.get("artifactRevision", 0)),
            "stateRevision": _revision(body.get("stateRevision", 0), "stateRevision")}


# --- state machine -----------------------------------------------------------------------------------------------------
def can_transition(current: str, nxt: str) -> bool:
    return nxt in TRANSITIONS.get(current, ())


def require_transition(current: str, nxt: str) -> None:
    if not can_transition(current, nxt):
        raise AlphaError(f"A presentation can't move from {current} to {nxt}.", 409, code="ui_state_transition")


# --- events and SSE framing --------------------------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_event(artifact_id: str, attempt_id: str | None, revision: int, seq: int, kind: str, payload: dict | None = None, at: str | None = None) -> dict:
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown UI event kind {kind}")
    return {"contractVersion": CONTRACT_VERSION, "artifactId": artifact_id, "attemptId": attempt_id, "revision": revision, "seq": seq,
            "kind": kind, "at": at or now_iso(), "payload": payload or {}}


def sse_frame(event: dict, *, retry_ms: int | None = None) -> bytes:
    """One `text/event-stream` frame: `id: {artifactId}:{seq}`, `event: {kind}`, `data: {json}`. JSON escapes newlines, so
    a payload is always one data line."""
    lines = []
    if retry_ms is not None:
        lines.append(f"retry: {int(retry_ms)}")
    lines.append(f"id: {event_id(event['artifactId'], event['seq'])}")
    lines.append(f"event: {event['kind']}")
    lines.append("data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def sse_comment(text: str = "") -> bytes:
    return (": " + text.replace("\n", " ")[:80] + "\n\n").encode("utf-8")


SSE_HEADERS = [("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store, no-transform"), ("X-Accel-Buffering", "no"),
               ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer")]

# --- public artifact projection ----------------------------------------------------------------------------------------
PUBLIC_ARTIFACT_KEYS = ("contractVersion", "artifactId", "conversationId", "messageId", "runId", "revision", "generationAttemptId", "generationState",
                        "validationState", "language", "languageVersion", "libraryVersion", "libraryHash", "promptHash", "sourceHash", "canonicalSource",
                        "fallbackText", "manifestId", "bindingVersion", "safeState", "stateRevision", "createdAt", "updatedAt", "asOf")
# Server-only manifest metadata never leaves the server (principal, scope, permission revision, egress decision, approved data
# refs, query constraints, action targets, proposal digests, capability expiry).
SERVER_ONLY_MANIFEST_KEYS = ("principal", "scope", "workspaceId", "permissionRevision", "role", "egress", "approvedRefs", "queryConstraints",
                             "actionTargets", "proposalDigests", "expiresAt")


def public_artifact(record: dict) -> dict:
    """UiArtifactV1 from a store record: exactly the public keys, nothing server-only. `ready` is presentation state only."""
    out = {k: record.get(k) for k in PUBLIC_ARTIFACT_KEYS}
    out["contractVersion"] = CONTRACT_VERSION
    out["language"] = LANGUAGE
    if out.get("generationState") not in GENERATION_STATES:
        raise ValueError("artifact record has an unknown generation state")
    if out.get("validationState") not in VALIDATION_STATES:
        raise ValueError("artifact record has an unknown validation state")
    if out["generationState"] != "ready" or out["validationState"] != "accepted":
        # Untrusted or unfinished source is never handed out as canonical.
        out["canonicalSource"] = None if out["validationState"] != "accepted" else out.get("canonicalSource")
    out["safeState"] = out.get("safeState") or {}
    return out


def public_manifest(manifest: dict) -> dict:
    """What the browser may know about a manifest: bindings it can call and action controls it can show, never targets."""
    return {"manifestId": manifest.get("manifestId"), "bindingVersion": manifest.get("bindingVersion"), "journeyIds": list(manifest.get("journeyIds") or []),
            "componentGroups": list(manifest.get("componentGroups") or []),
            "queries": [{k: q.get(k) for k in ("name", "description", "argsSchema", "refreshMinSeconds", "pageSize")} for q in manifest.get("queries") or []],
            "actions": [{k: a.get(k) for k in ("actionId", "label", "effect", "requiresConfirmation", "inputSchema", "summary")} for a in manifest.get("actions") or []],
            "expiresAt": manifest.get("expiresAt")}


def query_result(state: str, data=None, *, as_of=None, source_refs=(), revision=None, next_cursor=None, known=None, total=None, note=None, warnings=()) -> dict:
    """UiQueryResultV1. `unavailable`/`denied` carry no data; unknown is never coerced to zero."""
    if state not in DATA_STATES:
        raise ValueError(f"unknown data state {state}")
    return {"state": state, "data": data if state in ("available", "partial", "stale", "empty") else None, "asOf": as_of,
            "sourceRefs": [str(r) for r in source_refs][:50], "revision": revision, "nextCursor": next_cursor,
            "coverage": {"known": known, "total": total, "note": note}, "warnings": [str(w)[:240] for w in warnings][:10]}


def action_result(action_id: str, idempotency_key: str, outcome: str, *, verified: bool = False, receipt_ref=None, proposal_ref=None, changed_refs=(),
                  invalidation_keys=(), next_context=None) -> dict:
    """UiActionResultV1. `verified` is True only when the original executor ran and the re-read matched (D sets it, never
    a client or model)."""
    if outcome not in ACTION_OUTCOMES:
        raise ValueError(f"unknown action outcome {outcome}")
    if verified and outcome != "applied":
        raise ValueError("only an applied action can be verified")
    return {"actionId": action_id, "idempotencyKey": idempotency_key, "outcome": outcome, "verified": bool(verified), "receiptRef": receipt_ref,
            "proposalRef": proposal_ref, "changedRefs": list(changed_refs)[:50], "invalidationKeys": list(invalidation_keys)[:50], "nextContext": next_context or {}}


# --- contract manifest (drift check) -----------------------------------------------------------------------------------
def contract_manifest() -> dict:
    """Everything both languages must agree on. Its canonical JSON hash is the contract hash."""
    return {"contractVersion": CONTRACT_VERSION, "language": LANGUAGE, "surfaces": list(UI_SURFACES), "generationStates": list(GENERATION_STATES),
            "terminalGenerationStates": list(TERMINAL_GENERATION_STATES), "validationStates": list(VALIDATION_STATES), "dataStates": list(DATA_STATES),
            "actionOutcomes": list(ACTION_OUTCOMES), "eventKinds": list(EVENT_KINDS), "terminalEventKinds": list(TERMINAL_EVENT_KINDS),
            "attemptKinds": list(ATTEMPT_KINDS), "revisionKinds": list(REVISION_KINDS), "scopes": list(SCOPES), "slots": list(SLOTS),
            "journeys": list(JOURNEYS), "uiActionEffects": list(UI_ACTION_EFFECTS), "transitions": {k: list(v) for k, v in TRANSITIONS.items()},
            "reasonCodes": list(REASON_CODES), "bounds": dict(BOUNDS), "flags": list(FLAGS), "canaryEnv": CANARY_ENV, "routes": dict(ROUTES),
            "publicArtifactKeys": list(PUBLIC_ARTIFACT_KEYS)}


def contract_hash() -> str:
    return sha256_text(canonical_json(contract_manifest()))
