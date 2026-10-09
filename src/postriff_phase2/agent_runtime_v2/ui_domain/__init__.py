"""Lane D — the static catalog of Generative UI data bindings and guarded actions (rafii-genui/1).

One explicit allowlist per journey (J01-J09). A binding is a name the presenter may reference in `Query("name", …)` and
a browser bridge may call through `POST …/agent/ui/queries`; an action is an id a registered Rafii control may activate
through `POST …/actions/activate` + `POST …/actions`. Nothing here is discovered from the global tool registry, from a
model's output or from an HTTP path: an id that is not in this module does not exist (fail closed, never `classify()`).

Each entry names:
- the journey and the scope it belongs to (`workspace` for the consumer app, `founder` for the founder console only);
- the permission class the *current* member must hold (re-checked on every request; never the manifest's snapshot);
- the effect class (queries are always READ; actions are one of ui_contracts.UI_ACTION_EFFECTS);
- the existing ToolSpec / site-agent tool it wraps, when there is one, so the manifest builder can check that spec's
  tenant and effect by explicit name;
- a JSON-schema subset for its inputs (unknown keys refused) and the handler that reads or runs the original domain
  service.

Handlers live in the per-journey modules (drafts J01, calendar J02, library J03, voice J04, campaigns J05, analytics J06,
research J07, automations J08, founder J09). Importing this package imports them, which registers their entries.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from postriff_alpha.domain import AlphaError

from .. import ui_contracts

SCOPES = ("workspace", "founder")
REQUIREMENTS = ("read", "edit", "approve", "manage_connections", "owner")
DEDUPE = ("intent", "cas", "natural")


@dataclass(frozen=True)
class QueryBinding:
    name: str
    journey: str
    description: str
    args: dict                                    # JSON-schema object (properties/required/additionalProperties=False)
    handler: Callable[..., dict]                  # handler(dctx, inputs, cursor) -> ui_contracts.query_result(...)
    refresh: int | None = 60                      # minimum refresh seconds (>= BOUNDS.refreshMinSeconds) or None: no polling
    page: int | None = None                       # default page size for paginated bindings
    scope: str = "workspace"
    requirement: str = "read"
    tool: str | None = None                       # underlying site-agent tool id or agent ToolSpec name (effect checked: READ)
    search: bool = False                          # text-search binding: the browser debounces 300 ms and aborts superseded calls
    invalidated_by: tuple = ()                    # invalidation keys (from action results) that make cached reads stale


@dataclass(frozen=True)
class ActionBinding:
    action_id: str
    journey: str
    label: str
    summary: str
    effect: str                                   # ui_contracts.UI_ACTION_EFFECTS
    requirement: str
    inputs: dict                                  # JSON-schema object
    confirm: Callable[..., dict]                  # confirm(dctx, inputs) -> native confirmation copy (server-built)
    execute: Callable[..., dict]                  # execute(dctx, inputs, receipt) -> outcome dict (see ui_actions)
    requires_confirmation: bool = True
    scope: str = "workspace"
    tool: str | None = None                       # the ToolSpec whose effect/tenant this action must match, when one exists
    prepare_only: bool = False                    # outcome is `prepared` (a proposal / selection), never `applied`
    two_phase: bool = False                       # the domain command manages its own transactions (paid/long): run outside the lock
    dedupe: str = "cas"                           # intent: the same artifact revision + input digest returns the first result (creates/prepares)
                                                  # cas: the domain revision guard refuses a second effect; natural: the command is idempotent


QUERIES: dict[str, QueryBinding] = {}
ACTIONS: dict[str, ActionBinding] = {}
JOURNEY_QUERIES: dict[str, list[str]] = {j: [] for j in ui_contracts.JOURNEYS}
JOURNEY_ACTIONS: dict[str, list[str]] = {j: [] for j in ui_contracts.JOURNEYS}


def _check_schema(schema: dict) -> dict:
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ValueError("binding schemas are JSON objects")
    schema.setdefault("required", [])
    schema["additionalProperties"] = False
    for key, spec in schema["properties"].items():
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9]{0,39}$", key):
            raise ValueError(f"input names are camelCase identifiers: {key}")
        kinds = spec.get("type") if isinstance(spec.get("type"), list) else [spec.get("type")]
        if not set(kinds) <= {"string", "integer", "number", "boolean", "array", "null"}:
            raise ValueError(f"unsupported input type for {key}")
        if "array" in kinds and not isinstance(spec.get("maxItems"), int):
            raise ValueError(f"arrays are bounded: {key}")
        if "string" in kinds and not (isinstance(spec.get("maxLength"), int) or spec.get("enum") or spec.get("format")):
            raise ValueError(f"strings are bounded: {key}")
    return schema


def schema(properties: dict, required=()) -> dict:
    return _check_schema({"type": "object", "properties": properties, "required": list(required), "additionalProperties": False})


def query(name, journey, description, properties, handler, *, required=(), refresh=60, page=None, scope="workspace", requirement="read", tool=None,
          search=False, invalidated_by=(), also=()):
    """Register a read binding. `also` lists other journeys whose manifests carry it too (open proposals in J05/J08, …)."""
    if not ui_contracts.valid_name(name) or name in QUERIES or name in ACTIONS:
        raise ValueError(f"bad or duplicate binding {name}")
    if journey not in ui_contracts.JOURNEYS or scope not in SCOPES or requirement not in REQUIREMENTS:
        raise ValueError(f"bad binding metadata {name}")
    if (journey in ui_contracts.FOUNDER_JOURNEYS) != (scope == "founder") or any(j not in ui_contracts.JOURNEYS or (j in ui_contracts.FOUNDER_JOURNEYS) != (scope == "founder")
                                                                                 for j in also):
        raise ValueError(f"founder bindings belong to J09 only: {name}")
    if refresh is not None and refresh < ui_contracts.BOUNDS["refreshMinSeconds"]:
        raise ValueError(f"refresh below the minimum: {name}")
    if page is not None and not 1 <= page <= ui_contracts.BOUNDS["queryPageMax"]:
        raise ValueError(f"page out of bounds: {name}")
    binding = QueryBinding(name, journey, description, schema(properties, required), handler, refresh, page, scope, requirement, tool, search, tuple(invalidated_by))
    QUERIES[name] = binding
    for j in dict.fromkeys((journey, *also)):
        JOURNEY_QUERIES[j].append(name)
    return binding


def action(action_id, journey, label, summary, effect, requirement, properties, confirm, execute, *, required=(), requires_confirmation=True, scope="workspace",
           tool=None, prepare_only=False, two_phase=False, dedupe="cas", also=()):
    if not ui_contracts.valid_name(action_id) or action_id in ACTIONS or action_id in QUERIES:
        raise ValueError(f"bad or duplicate action {action_id}")
    if effect not in ui_contracts.UI_ACTION_EFFECTS:
        raise ValueError(f"effect {effect} is not a UI action effect")
    if journey not in ui_contracts.JOURNEYS or scope != "workspace" or requirement not in REQUIREMENTS:
        # The founder manifest is read-only in this release (A-DECISIONS D-A22): no founder actions exist.
        raise ValueError(f"bad action metadata {action_id}")
    if effect == "PREPARE_EXTERNAL" and not prepare_only:
        raise ValueError(f"PREPARE_EXTERNAL actions only prepare: {action_id}")
    if (effect == "PREPARE_EXTERNAL" or prepare_only) and not requires_confirmation:
        raise ValueError(f"a prepared change is always confirmed natively: {action_id}")
    if dedupe not in DEDUPE or any(j not in ui_contracts.CONSUMER_JOURNEYS for j in also):
        raise ValueError(f"bad action metadata {action_id}")
    binding = ActionBinding(action_id, journey, label, summary, effect, requirement, schema(properties, required), confirm, execute, requires_confirmation,
                            scope, tool, prepare_only, two_phase, dedupe)
    ACTIONS[action_id] = binding
    for j in dict.fromkeys((journey, *also)):
        JOURNEY_ACTIONS[j].append(action_id)
    return binding


# --- input validation (server side; the browser's copy is a UX aid only) ------------------------------------------------
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def _bad(key: str) -> AlphaError:
    return AlphaError(f"The value for {key} isn't valid here.", 400, code="ui_input")


def _one(key: str, spec: dict, value: Any) -> Any:
    kinds = spec.get("type") if isinstance(spec.get("type"), list) else [spec.get("type")]
    if value is None:
        if "null" in kinds:
            return None
        raise _bad(key)
    if "string" in kinds and isinstance(value, str):
        if len(value) > spec.get("maxLength", 200) or len(value) < spec.get("minLength", 0) or "\x00" in value:
            raise _bad(key)
        if "enum" in spec and value not in spec["enum"]:
            raise _bad(key)
        if "pattern" in spec and not re.match(spec["pattern"], value):
            raise _bad(key)
        if spec.get("format") == "date" and not _DATE.match(value):
            raise _bad(key)
        if spec.get("format") == "local-date-time" and not _LOCAL.match(value):
            raise _bad(key)
        return value
    if "boolean" in kinds and isinstance(value, bool):
        return value
    if "integer" in kinds and type(value) is int:
        if value < spec.get("minimum", -(2 ** 53)) or value > spec.get("maximum", 2 ** 53):
            raise _bad(key)
        return value
    if "number" in kinds and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        if value < spec.get("minimum", -(2 ** 53)) or value > spec.get("maximum", 2 ** 53):
            raise _bad(key)
        return value
    if "array" in kinds and isinstance(value, list):
        if len(value) > spec["maxItems"] or len(value) < spec.get("minItems", 0):
            raise _bad(key)
        item = spec.get("items") or {"type": "string", "maxLength": 120}
        out = [_one(key, item, v) for v in value]
        return list(dict.fromkeys(out)) if spec.get("uniqueItems") and all(isinstance(v, (str, int)) for v in out) else out
    raise _bad(key)


def validate(schema_: dict, inputs: dict | None) -> dict:
    """Exact inputs for one binding: unknown keys refused, required keys present, every value within its bounds."""
    inputs = inputs or {}
    if not isinstance(inputs, dict):
        raise AlphaError("Inputs must be an object.", 400, code="ui_input")
    props = schema_["properties"]
    extra = set(inputs) - set(props)
    if extra:
        raise AlphaError("These inputs aren't accepted here: " + ", ".join(sorted(extra))[:160], 400, code="ui_input")
    out = {}
    for key in schema_.get("required") or []:
        if inputs.get(key) is None:
            raise AlphaError(f"{key} is required here.", 400, code="ui_input")
    for key, value in inputs.items():
        out[key] = _one(key, props[key], value)
    return out


def data_shape(name: str) -> dict:
    """Field names only (no values): what a row path and row fields look like, for the presenter and E's components."""
    from .shapes import OPEN_SHAPES, OPTIONAL, SHAPES
    shape = SHAPES.get(name) or {"keys": [], "lists": {}}
    optional = OPTIONAL.get(name) or {"keys": [], "lists": {}}
    return {"keys": list(shape["keys"]), "lists": {k: list(v) for k, v in shape["lists"].items()},
            "optional": {"keys": list(optional["keys"]), "lists": {k: list(v) for k, v in optional["lists"].items()}}, "open": name in OPEN_SHAPES}


def public_query(binding: QueryBinding) -> dict:
    return {"name": binding.name, "description": binding.description, "argsSchema": binding.args, "refreshMinSeconds": binding.refresh,
            "pageSize": binding.page, "dataShape": data_shape(binding.name)}


def public_action(binding: ActionBinding) -> dict:
    return {"actionId": binding.action_id, "label": binding.label, "effect": binding.effect, "requiresConfirmation": bool(binding.requires_confirmation),
            "inputSchema": binding.inputs, "summary": binding.summary}


def catalog() -> dict:
    """The machine-readable catalog lanes C/E/G build on: per journey the read bindings (name, argsSchema, dataShape) and the
    action controls (actionId, inputSchema, effect), plus flat maps with the server-side metadata."""
    shape = data_shape

    return {"contractVersion": ui_contracts.CONTRACT_VERSION,
            "journeys": {j: {"queries": [{"name": n, "argsSchema": QUERIES[n].args, "dataShape": shape(n)} for n in JOURNEY_QUERIES[j]],
                             "actions": [{"actionId": a, "inputSchema": ACTIONS[a].inputs, "effect": ACTIONS[a].effect} for a in JOURNEY_ACTIONS[j]]}
                         for j in ui_contracts.JOURNEYS},
            "queries": {name: {**public_query(b), "journey": b.journey, "scope": b.scope, "requirement": b.requirement, "search": b.search,
                               "invalidatedBy": list(b.invalidated_by), "dataShape": shape(name)} for name, b in sorted(QUERIES.items())},
            "actions": {aid: {**public_action(b), "journey": b.journey, "scope": b.scope, "requirement": b.requirement, "prepareOnly": b.prepare_only,
                              "dedupe": b.dedupe, "twoPhase": b.two_phase} for aid, b in sorted(ACTIONS.items())}}


@dataclass
class Receipt:
    """What an action's executor reports. `verified` is set by ui_actions from the executor's own re-read, never a client."""
    outcome: str
    verified: bool = False
    receipt_ref: str | None = None
    proposal_ref: str | None = None
    changed_refs: list = field(default_factory=list)
    invalidation_keys: list = field(default_factory=list)
    next_context: dict = field(default_factory=dict)
    message: str | None = None                    # sanitized, human-readable (native receipt line)


def load() -> None:
    """Import every journey module (registration side effects), once. The site agent's tools module goes first: it imports its
    `reads` module at its end, so importing `reads` first would be circular."""
    from ...site_agent import tools as _site_tools  # noqa: F401
    from . import analytics, automations, calendar, campaigns, drafts, founder, library, research, voice  # noqa: F401


load()
