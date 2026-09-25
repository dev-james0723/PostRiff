"""Typed, surface-neutral contracts of the Rafii Agent Runtime (spec §8, §9, §12, §16).

One turn result drives the text panel, Voice Mode and any later client. The panel renders `blocks` (the same block
types the site agent already renders); GPT-Live speaks `speakableSummary`, never markdown; every other field is
structured so no client has to parse prose to know what happened.

Facts in a result come from the application, not from the model: created/changed entities, pending approvals,
generated assets and task steps are filled by the tools that did the work and re-read the state (`verification`).
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Any

# --- effect classes (§12) ---------------------------------------------------------------------------------------------
EFFECTS = ("READ", "CREATE_DRAFT", "MUTATE_REVERSIBLE", "PREPARE_EXTERNAL", "EXTERNAL_EFFECT", "DESTRUCTIVE", "SECRET")
READ, CREATE_DRAFT, MUTATE_REVERSIBLE, PREPARE_EXTERNAL, EXTERNAL_EFFECT, DESTRUCTIVE, SECRET = EFFECTS
# Effects no tool of this runtime may have. They stay on their own pages behind their own approvals (site agent §9).
FORBIDDEN_EFFECTS = (EXTERNAL_EFFECT, DESTRUCTIVE, SECRET)

# --- modalities, step states (§16) ------------------------------------------------------------------------------------
MODALITIES = ("text", "voice", "image")
STEP_STATES = ("planned", "running", "done", "needs_user", "blocked", "failed", "canceled")
TERMINAL_STEP_STATES = ("done", "failed", "canceled")
# Only a tool that did the work and re-read the state may set these (the model cannot mark its own work done).
TOOL_ONLY_STEP_STATES = ("done",)

# --- context kinds (§15) ----------------------------------------------------------------------------------------------
CONTEXT_KINDS = ("USER_INSTRUCTION", "APP_STATE", "MEMORY", "TOOL_RESULT", "HELP_CONTENT", "EXTERNAL_SOURCE", "MODEL_DERIVATION")

_TRACE = re.compile(r"^trace_[0-9a-f]{32}$")


def new_trace_id() -> str:
    """The correlation id shared by the browser event, Live delegation, Manager, specialists, tools, approval,
    mutation, verification and result (§30). The Agents SDK accepts this `trace_<32 hex>` form as its trace id."""
    return "trace_" + secrets.token_hex(16)


def valid_trace_id(value) -> bool:
    return isinstance(value, str) and bool(_TRACE.match(value))


@dataclass(frozen=True)
class ToolSpec:
    """What every Rafii tool declares (§12)."""
    name: str
    effect: str
    permission: str                 # permissions.CLASSES requirement, re-checked at execution
    description: str
    idempotent: bool = True
    approval: bool = False          # a proposal a person applies, never executed by the model
    voice: bool = True              # usable from a delegated voice turn (voice never gains more than text)
    audit: str | None = None        # audit kind recorded by the domain path, if any
    tenant: str = "workspace"       # every tool is scoped to the turn's single workspace

    def __post_init__(self):
        if self.effect not in EFFECTS:
            raise ValueError(f"{self.name}: unknown effect {self.effect}")
        if self.effect in FORBIDDEN_EFFECTS:
            raise ValueError(f"{self.name}: {self.effect} tools are not allowed in the agent runtime")
        if self.effect == PREPARE_EXTERNAL and not self.approval:
            raise ValueError(f"{self.name}: preparing an external effect is always a proposal")

    def public(self) -> dict:
        return {"name": self.name, "effect": self.effect, "permission": self.permission, "approval": self.approval, "voice": self.voice,
                "idempotent": self.idempotent, "audit": self.audit}


@dataclass
class Step:
    id: str
    label: str
    state: str = "planned"
    kind: str | None = None
    depends_on: list[str] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    reason: str | None = None
    verified: bool = False
    started_at: float | None = None
    updated_at: float | None = None

    def view(self) -> dict:
        return {"id": self.id, "label": self.label, "state": self.state, "kind": self.kind, "dependsOn": list(self.depends_on),
                "entities": list(self.entities), "outputs": list(self.outputs), "approvals": list(self.approvals), "reason": self.reason,
                "verified": self.verified, "startedAt": self.started_at, "updatedAt": self.updated_at}


def empty_result(trace_id: str, modality: str) -> dict:
    """The surface-neutral turn result (§9). Every key is always present so clients never guess."""
    return {
        "version": 1,
        "traceId": trace_id,
        "modality": modality,
        "answerText": "",
        "speakableSummary": "",
        "references": [],          # [{type, id, title}] items the answer names (for "that draft", "the second image")
        "citations": [],           # help citations, as the site agent returns them
        "facts": [],               # [{text, kind: "stored"|"derived", rule?}] — stored facts vs derived observations
        "toolActivity": [],        # [{tool, label, effect, status, latencyMs, specialist?}]
        "task": None,              # {taskId, title, steps: [Step.view()]}
        "changedEntities": [],     # [{type, id, change, verified, expected, actual}]
        "pendingApprovals": [],    # [{proposalId, messageId, type, summary, digest, expiresAt}]
        "generatedAssets": [],     # [{assetId, kind: "generated"|"edited"|"variant", model, parentAssetId, href}]
        "warnings": [],            # [{code, message}]
        "errors": [],              # recoverable errors [{code, message, step?}]
        "usage": {"modelRequests": 0, "costUsdMicro": None, "route": None, "billing": None},
        "routes": [],              # model routing decisions (§21)
        "blocks": [],              # panel blocks (site agent block types)
        "composedBy": "grounded",  # "manager" | "grounded" | "deterministic"
    }


SPEAKABLE_MAX = 600
_MARKDOWN = re.compile(r"[*_`#>\[\]]|\(\s*/app/[^)]*\)")


def trim(value, limit: int) -> str:
    """Text a model or provider produced, cut to size. `clean` refuses over-long input from a person (a 400); applied to
    output that already cost money, it would turn a paid result into an error, so output is cut instead."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return value.replace("\x00", "").strip()[:limit].strip()


def speakable(text: str, limit: int = SPEAKABLE_MAX) -> str:
    """Plain words for GPT-Live to say: no markdown, links, ids or tables; short."""
    if not isinstance(text, str):
        return ""
    plain = _MARKDOWN.sub("", text)
    plain = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{24,64}\b", "", plain, flags=re.I)
    plain = " ".join(plain.split())
    if len(plain) <= limit:
        return plain
    cut = plain[:limit]
    end = max(cut.rfind(". "), cut.rfind("。"), cut.rfind("? "), cut.rfind("! "))
    return (cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…").strip()


def as_json(value: Any):
    """Dataclasses and tuples to JSON-safe values (results are persisted as jsonb)."""
    if isinstance(value, Step):
        return value.view()
    if isinstance(value, dict):
        return {str(k): as_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [as_json(v) for v in value]
    return value
