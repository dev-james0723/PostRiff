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

# --- capability vocabulary (rafii-agent-authz/1, CF-1 §3) ---------------------------------------------------------------
# Vocabulary and declarations only. Nothing in this runtime enforces them yet: CF-2's gate reads them in `shadow` or
# `enforce` mode, and with its flag off every surface keeps exactly today's behaviour (capability_registry.SurfaceBinding).
CATEGORIES = ("read_analyze", "navigate_interact", "create_edit", "manage_settings", "manage_connected_services", "execute_automations")
RISKS = ("R0", "R1", "R2", "R3")        # R0 read · R1 reversible internal · R2 externally visible / shared impact · R3 high-impact or irreversible
CONFIRMATIONS = ("none", "native", "proposal", "approval_step_up")      # ORDERED: max_confirmation() picks the stricter
COSTS = ("free", "text_credits", "media_credits")    # text_credits: its own 'text_model' writer reservation; media_credits: 'image_generation'/'tool'
IDEMPOTENCY = ("read", "native_key", "receipt_tx", "none")   # how a replay is made safe (CF-3 §8)
RETRY_CLASSES = ("auto", "manual", "never")
EVIDENCE = ("trace", "audit", "receipt")
VERIFICATIONS = ("none", "reread", "provider_receipt")
COMPENSATIONS = ("none", "inverse", "manual", "irreversible")
CAPABILITY_KINDS = ("tool", "ui_action", "ui_query", "context", "native_only")
SURFACES = ("manager", "specialist", "site_agent", "commands_direct", "genui_action", "genui_query", "context", "task_engine")
DATA_DOMAINS = ("public", "web", "account", "screen", "content", "campaigns", "library", "memory_brand", "connections",
                "analytics", "growth_trends", "notifications", "usage_billing", "members", "agent_activity", "automations")
CONSENT_KEYS = ("memory_cloud", "research_web", "media_cloud", "connector_cloud", "growth", "radar",
                "voice_sample_route", "library_purpose")
AUTONOMY = ("ask", "assist")             # autopilot is never a grant level; it is a bounded policy (CF-2 §2)
CATALOGUE_GENERATION = 2                 # Library metadata writes are post-freeze; old grants still ask.
R3_REAUTH_SECONDS = 300                  # DP-5: agent-originated R3 needs a sign-in verified within 5 minutes


def max_confirmation(*values: str) -> str:
    """INV-10: the stricter confirmation in the order of CONFIRMATIONS. An unknown value fails closed to the strictest."""
    rank = 0
    for value in values:
        rank = max(rank, CONFIRMATIONS.index(value) if value in CONFIRMATIONS else len(CONFIRMATIONS) - 1)
    return CONFIRMATIONS[rank]


@dataclass(frozen=True)
class ProviderScope:
    """A provider grant a capability needs (read-only metadata; CF-2's provider_grants checks it, never this module)."""
    provider: str                        # platform key as stored on the channel ('YouTube', 'Instagram', ...)
    scopes: tuple[str, ...]              # YouTube: youtube.model.has_scopes; others: subset check. Never shown to people.
    lane: str | None = None              # 'agentic' | 'standard' | None (YouTube authorizationLane)
    capability: str | None = None        # pr_channel_capabilities.capability that must not be 'Unsupported'

    def __post_init__(self):
        if not isinstance(self.provider, str) or not self.provider or not isinstance(self.scopes, tuple) \
                or not all(isinstance(s, str) and s for s in self.scopes) or self.lane not in (None, "agentic", "standard"):
            raise ValueError(f"invalid provider scope {self.provider!r}")


@dataclass(frozen=True)
class Limits:
    """Per-capability rate and cost limits. None means no limit of that kind is declared (today's tools declare none:
    the limits that exist today belong to a surface, see capability_registry.SurfaceBinding.legacy_limits)."""
    per_turn: int | None = None
    per_minute: int | None = None        # hosted.throttle(cur, key, limit, 60)
    per_day: int | None = None
    max_usd_micro: int | None = None     # refused before dispatch when the estimate exceeds it

    def __post_init__(self):
        for key in ("per_turn", "per_minute", "per_day", "max_usd_micro"):
            value = getattr(self, key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f"limit {key} must be a positive integer or None")

    def public(self) -> dict:
        return {"perTurn": self.per_turn, "perMinute": self.per_minute, "perDay": self.per_day, "maxUsdMicro": self.max_usd_micro}


# The policy fields a ToolSpec may declare inline (keyword arguments) or capability_registry.TOOL_POLICY may declare by name.
POLICY_FIELDS = ("capability_id", "capability_version", "category", "data_grants", "consents", "risk", "confirmation", "cost", "provider_scopes",
                 "limits", "timeout_seconds", "idempotency", "retry_class", "max_attempts", "background_eligible", "evidence", "verification",
                 "compensation", "inverse", "autopilot_eligible", "explicit_request", "client_requirement", "since")
_ENUMS = {"category": CATEGORIES, "risk": RISKS, "confirmation": CONFIRMATIONS, "cost": COSTS, "idempotency": IDEMPOTENCY,
          "retry_class": RETRY_CLASSES, "evidence": EVIDENCE, "verification": VERIFICATIONS, "compensation": COMPENSATIONS}
DEFAULT_TIMEOUT_SECONDS = 150.0          # = the FunctionTool timeout every agent tool has today (tool_adapter.sdk_tools)


def check_policy_values(name: str, values: dict) -> None:
    """Unknown enum values and malformed policy fields (shared by ToolSpec and capability_registry.CapabilitySpec)."""
    for key, allowed in _ENUMS.items():
        value = values.get(key)
        if value is not None and value not in allowed:
            raise ValueError(f"{name}: unknown {key} {value!r}")
    grants = values.get("data_grants")
    if grants is not None and (not isinstance(grants, tuple) or any(d not in DATA_DOMAINS for d in grants)):
        raise ValueError(f"{name}: data_grants must be a tuple of DATA_DOMAINS")
    consents = values.get("consents", ())
    if not isinstance(consents, tuple) or any(c not in CONSENT_KEYS for c in consents):
        raise ValueError(f"{name}: consents must be a tuple of CONSENT_KEYS")
    scopes = values.get("provider_scopes", ())
    if not isinstance(scopes, tuple) or any(not isinstance(s, ProviderScope) for s in scopes):
        raise ValueError(f"{name}: provider_scopes must be a tuple of ProviderScope")
    if not isinstance(values.get("limits", Limits()), Limits):
        raise ValueError(f"{name}: limits must be a Limits")
    timeout = values.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= DEFAULT_TIMEOUT_SECONDS:
        # CF-3 may lower a timeout per step; nothing may raise it above what the SDK binding gives a tool today.
        raise ValueError(f"{name}: timeout_seconds must be in (0, {DEFAULT_TIMEOUT_SECONDS}]")
    attempts = values.get("max_attempts")
    if attempts is not None and (isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5):
        raise ValueError(f"{name}: max_attempts must be 1..5")
    for key in ("capability_version", "since"):
        value = values.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name}: {key} must be a positive integer")


def check_policy_combination(name: str, policy: dict, effect: str) -> None:
    """CF-1 §4: the impossible combinations, checked on the EFFECTIVE policy (inline fields, table and defaults merged)."""
    if policy["risk"] == "R3":
        raise ValueError(f"{name}: R3 is native-only in P0 (INV-5); Rafii may only navigate or guide to it")
    if policy["risk"] == "R2" and policy["confirmation"] == "none":
        raise ValueError(f"{name}: an R2 capability always asks (native confirmation or proposal)")
    if policy.get("inverse") and policy["compensation"] != "inverse":
        raise ValueError(f"{name}: an inverse needs compensation='inverse'")
    if policy.get("autopilot_eligible") and policy["risk"] not in ("R1", "R2"):
        raise ValueError(f"{name}: autopilot may only cover R1/R2 capabilities")
    if policy.get("background_eligible") and (policy["risk"] != "R0" or effect != READ):
        raise ValueError(f"{name}: only R0 READ capabilities may run in the background (correction 9)")
    if policy["idempotency"] == "none" and policy["retry_class"] != "never":
        raise ValueError(f"{name}: a capability without a replay guard never retries")


def derive_policy(spec, overrides: dict | None = None) -> dict:
    """CF-1 §4 default derivation, frozen. `overrides` (a capability_registry.TOOL_POLICY entry) and then the spec's own
    inline keyword fields win over the defaults; the result is the effective policy of that tool.

    | Field | READ | CREATE_DRAFT / MUTATE_REVERSIBLE | PREPARE_EXTERNAL, or approval=True |
    | category | read_analyze | create_edit | execute_automations |
    | risk | R0 | R1 | R2 |
    | confirmation (policy floor) | none | none | proposal |
    | idempotency | read | none unless declared | native_key (the proposal digest) |
    | retry_class / max_attempts | auto/3 if idempotent, else never/1 | none → never/1; paid → manual/1; else auto/3 | manual/1 |
    | evidence / verification / compensation | trace / none / none | audit / reread / manual | audit / reread / manual |
    """
    external = spec.effect == PREPARE_EXTERNAL or bool(spec.approval)
    if external:
        out = {"category": "execute_automations", "risk": "R2", "confirmation": "proposal", "idempotency": "native_key",
               "evidence": "audit", "verification": "reread", "compensation": "manual"}
    elif spec.effect == READ:
        out = {"category": "read_analyze", "risk": "R0", "confirmation": "none", "idempotency": "read",
               "evidence": "trace", "verification": "none", "compensation": "none"}
    else:
        out = {"category": "create_edit", "risk": "R1", "confirmation": "none", "idempotency": "none",
               "evidence": "audit", "verification": "reread", "compensation": "manual"}
    out.update({"capability_id": f"tool.{spec.name}", "capability_version": 1, "data_grants": None, "consents": (), "cost": "free",
                "provider_scopes": (), "limits": Limits(), "timeout_seconds": DEFAULT_TIMEOUT_SECONDS, "retry_class": None, "max_attempts": None,
                "background_eligible": False, "inverse": None, "autopilot_eligible": False, "explicit_request": False, "client_requirement": None,
                "since": 1})
    declared = {}
    for source in (overrides or {}, inline_policy(spec)):
        for key, value in source.items():
            out[key] = value
            declared[key] = value
    if out["retry_class"] is None:
        if external:
            out["retry_class"] = "manual"
        elif out["idempotency"] == "read":
            out["retry_class"] = "auto" if spec.idempotent else "never"
        elif out["idempotency"] == "none":
            out["retry_class"] = "never"
        elif out["cost"] != "free":
            out["retry_class"] = "manual"
        else:
            out["retry_class"] = "auto"
    if out["max_attempts"] is None:
        out["max_attempts"] = 3 if out["retry_class"] == "auto" else 1
    out["paid"] = out["cost"] != "free"
    out["declared"] = tuple(sorted(declared))
    return out


def inline_policy(spec) -> dict:
    """The policy fields a ToolSpec declared itself (anything that differs from the field's default)."""
    defaults = _TOOLSPEC_POLICY_DEFAULTS
    return {key: getattr(spec, key) for key in POLICY_FIELDS if getattr(spec, key) != defaults[key]}


def input_digest(capability_id: str, inputs) -> str:
    """CF-3 §7.1: sha256(canonical(capability_id, inputs)), 64 hex. The one definition plan time and effect keys share."""
    import hashlib
    import json
    canonical = json.dumps({"capabilityId": capability_id, "inputs": inputs if inputs is not None else {}}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def effect_key(binding: dict | None, capability_id: str | None = None, inputs=None) -> str | None:
    """CF-3 §8.1 effect key, or None without a step binding (callers then keep today's trace-based keys).
    `tool` step: 'tsk:' + task_id_hex32 + ':' + step_key + ':g' + generation; a tool call inside a `model` step appends
    ':' + sha256(capability_id + '|' + input_digest)[:16]. Stable across automatic reclaim (same generation)."""
    import hashlib
    if not isinstance(binding, dict) or not binding:
        return None
    task_id = str(binding.get("taskId") or "").replace("-", "").lower()
    step_key = binding.get("stepKey")
    generation = binding.get("generation")
    if not re.fullmatch(r"[0-9a-f]{32}", task_id) or not isinstance(step_key, str) or not step_key \
            or isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("a step binding needs taskId (uuid), stepKey and an integer generation")
    key = f"tsk:{task_id}:{step_key}:g{generation}"
    if binding.get("kind") == "model":
        if not capability_id:
            raise ValueError("a tool call inside a model step needs its capability id")
        key += ":" + hashlib.sha256(f"{capability_id}|{input_digest(capability_id, inputs)}".encode("utf-8")).hexdigest()[:16]
    return key


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
    # --- rafii-agent-authz/1 (CF-1 §4). Keyword fields with defaults, appended after `tenant`, so every positional
    # construction keeps working. None means "derive" (derive_policy). None of them enters skill_registry.tool_digest (INV-9).
    capability_id: str | None = None             # default f"tool.{name}"
    capability_version: int = 1                  # bump on any semantic change
    category: str | None = None                  # CATEGORIES; default derived
    data_grants: tuple[str, ...] | None = None   # DATA_DOMAINS; None = undeclared (capability_registry.lint fails for tenant 'workspace')
    consents: tuple[str, ...] = ()               # CONSENT_KEYS the executor ALREADY pre-checks (correction 22)
    risk: str | None = None                      # RISKS; default derived; "R3" refused in P0
    confirmation: str | None = None              # CONFIRMATIONS; default derived (policy floor, never the surface's)
    cost: str = "free"                           # COSTS
    provider_scopes: tuple[ProviderScope, ...] = ()
    limits: Limits = field(default_factory=Limits)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS   # = FunctionTool timeout today; CF-3 may only lower it per step
    idempotency: str | None = None               # IDEMPOTENCY; default derived
    retry_class: str | None = None               # RETRY_CLASSES; default derived
    max_attempts: int | None = None              # 1..5; default derived
    background_eligible: bool = False            # may a cron claim run it (P0: R0 READ only, correction 9)
    evidence: str | None = None
    verification: str | None = None
    compensation: str | None = None
    inverse: str | None = None                   # capability id that undoes it; only with compensation="inverse"
    autopilot_eligible: bool = False             # bounded autopilot policy may cover it (P2 runner)
    explicit_request: bool = False               # only the CURRENT human message can authorize it
    client_requirement: str | None = None        # page uiCapabilities token needed to render (never authority)
    since: int = 1                               # CATALOGUE_GENERATION when added or widened

    def __post_init__(self):
        if self.effect not in EFFECTS:
            raise ValueError(f"{self.name}: unknown effect {self.effect}")
        if self.effect in FORBIDDEN_EFFECTS:
            raise ValueError(f"{self.name}: {self.effect} tools are not allowed in the agent runtime")
        if self.effect == PREPARE_EXTERNAL and not self.approval:
            raise ValueError(f"{self.name}: preparing an external effect is always a proposal")
        # CF-1 §4: only invalid values and impossible combinations are refused here. Completeness (data_grants declared) is
        # capability_registry.lint, never an import error: domain_tools.ensure_registered swallows extension errors, so a
        # refusal here would make a tool vanish silently.
        check_policy_values(self.name, {key: getattr(self, key) for key in POLICY_FIELDS})
        check_policy_combination(self.name, derive_policy(self), self.effect)

    def policy(self):
        """The registry's CapabilitySpec for this tool (capability_registry.from_tool): defaults, the registry's
        classification of the tool by name, and this spec's own inline fields."""
        from .capability_registry import from_tool
        return from_tool(self)

    def public(self) -> dict:
        cap = self.policy()
        return {"name": self.name, "effect": self.effect, "permission": self.permission, "approval": self.approval, "voice": self.voice,
                "idempotent": self.idempotent, "audit": self.audit,
                "capabilityId": cap.capability_id, "capabilityVersion": cap.version, "category": cap.category, "risk": cap.risk,
                "confirmation": cap.confirmation, "cost": cap.cost, "dataGrants": list(cap.data_grants) if cap.data_grants is not None else None}


_TOOLSPEC_POLICY_DEFAULTS = {"capability_id": None, "capability_version": 1, "category": None, "data_grants": None, "consents": (), "risk": None,
                             "confirmation": None, "cost": "free", "provider_scopes": (), "limits": Limits(), "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                             "idempotency": None, "retry_class": None, "max_attempts": None, "background_eligible": False, "evidence": None,
                             "verification": None, "compensation": None, "inverse": None, "autopilot_eligible": False, "explicit_request": False,
                             "client_requirement": None, "since": 1}


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
