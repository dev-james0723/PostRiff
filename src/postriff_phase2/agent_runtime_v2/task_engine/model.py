"""Pure rules of the durable task engine (CF-3 §2, §4, §8.1, §9): states, the legacy view mapping, step defaults, task
derivation, dependencies, effect keys and digests. No I/O; the store and executor apply these rules inside transactions.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

# --- vocabulary (EX-1) -----------------------------------------------------------------------------------------------------
STATES = ("queued", "running", "awaiting_approval", "blocked", "completed", "failed", "cancelled")
OPEN_STATES = STATES[:4]
TERMINAL_STATES = STATES[4:]
KINDS = ("tool", "model", "approval", "delegate", "continuation", "wait")
RISKS = ("R0", "R1", "R2", "R3")
STEP_EFFECTS = ("READ", "CREATE_DRAFT", "MUTATE_REVERSIBLE", "PREPARE_EXTERNAL")
EFFECT_RISK = {"READ": "R0", "CREATE_DRAFT": "R1", "MUTATE_REVERSIBLE": "R1", "PREPARE_EXTERNAL": "R2"}
RETRY_CLASSES = ("auto", "manual", "never")
ORIGINS = ("chat", "voice", "genui", "task_center", "recipe", "opportunity", "adopted")
CHAT_ORIGINS = ("chat", "voice", "adopted")
DELEGATE_TYPES = ("proposal", "ui_action", "ui_attempt", "publish_job", "automation_item", "library_job", "weekly_slot", "agent_task")
EXTERNAL_DELEGATES = ("publish_job", "automation_item")      # observes_external (generated column in 108)
APPROVAL_KINDS = ("proposal", "agent_action", "spend", "step_up_action")
APPROVAL_STATES = ("pending", "approved", "consumed", "rejected", "expired", "superseded", "revoked")
LEGACY_PROPOSAL_TYPES = ("schedule_draft", "reschedule_post", "automation_change")   # the only ones a typed/spoken "yes" decides (DP-5)
MAX_STEPS = 12
MAX_GENERATION = 4
TASK_ATTEMPTS = 24
TTL_SECONDS = 72 * 3600
HARD_TTL_SECONDS = 14 * 24 * 3600
APPROVAL_TTL_SECONDS = 24 * 3600
STEP_UP_APPROVAL_TTL_SECONDS = 15 * 60
CHECKPOINT_CLAIM_SECONDS = 230
CHECKPOINT_MAX_BYTES = 1024 * 1024
UNDO_WINDOW_SECONDS = 24 * 3600                              # DP-13 default; the DDL ceiling is 7 days
DELEGATE_POLL_SECONDS = 60
CRON_LIVE_PER_WORKSPACE = 2
INLINE_RESERVE_SECONDS = 15                                  # an inline step's deadline is min(timeout, request deadline − 15 s)
_STEP_KEY = re.compile(r"^s([1-9]|1[0-2])$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")


def legacy_state(state: str, reason_code: str | None = None) -> str:
    """The TaskPlan v1 spelling of an engine state (§2 legacyState)."""
    if state == "blocked":
        return "needs_user" if reason_code == "needs_input" else "blocked"
    return {"queued": "planned", "running": "running", "awaiting_approval": "needs_user", "completed": "done", "failed": "failed",
            "cancelled": "canceled"}[state]


def from_legacy(state: str, *, has_approvals: bool) -> tuple[str, str | None]:
    """An engine state (and reason code) for a TaskPlan v1 step the Manager drives (a `model` step)."""
    if state == "needs_user":
        return ("awaiting_approval", None) if has_approvals else ("blocked", "needs_input")
    if state == "blocked":
        return "blocked", "needs_conversation"
    return {"planned": "queued", "running": "running", "done": "completed", "failed": "failed", "canceled": "cancelled"}.get(state, "queued"), None


# --- step defaults (§9.1; the registry may only lower timeout and attempts) -----------------------------------------------
@dataclass(frozen=True)
class StepDefaults:
    timeout_seconds: int
    retry_class: str
    max_attempts: int


PAID_CAPABILITIES = frozenset({"image_generate", "image_edit", "image_variant", "draft_create", "draft_rewrite", "engagement_draft_create",
                               "weekly_plan_prepare", "youtube_plan_prepare"})


def defaults(kind: str, risk: str, *, paid: bool = False, receipt_tx: bool = False) -> StepDefaults:
    if kind == "tool":
        if risk == "R0":
            return StepDefaults(20, "auto", 3)
        if paid:
            return StepDefaults(180, "manual", 1)
        if risk == "R1":
            # Automatic re-runs only for effects that commit their receipt in the domain transaction (CF-1 `idempotency`
            # receipt_tx/native_key). Until CF-1 declares that per capability, an R1 effect is never re-run by itself.
            return StepDefaults(30, "auto", 3) if receipt_tx else StepDefaults(30, "manual", 1)
        return StepDefaults(30, "manual", 1)          # R2 prepare
    if kind == "continuation":
        return StepDefaults(200, "manual", 1)
    if kind == "delegate":
        return StepDefaults(10, "auto", 5)
    if kind == "wait":
        return StepDefaults(10, "auto", 3)
    if kind == "approval":
        return StepDefaults(10, "never", 1)
    return StepDefaults(30, "never", 1)               # model steps follow the Manager's own turns


# --- task derivation (EX-6) ------------------------------------------------------------------------------------------------
@dataclass
class StepFacts:
    """What derive() and the dependency rules need to know about one step."""
    key: str
    state: str
    kind: str = "tool"
    depends_on: tuple = ()
    reason_code: str | None = None
    retry_class: str = "manual"
    generation: int = 1
    observes_external: bool = False
    extra: dict = field(default_factory=dict)


def retryable(step: StepFacts, task_attempts_left: int) -> bool:
    """A failed step a person can still retry (it keeps its task open as `blocked/step_failed`)."""
    return (step.state == "failed" and step.retry_class != "never" and step.generation < MAX_GENERATION and task_attempts_left > 0
            and step.reason_code not in ("dependency_failed", "approval_rejected", "approval_expired", "task_expired", "retry_budget_exhausted",
                                         "cancelled_by_person", "cancelled_by_revocation", "task_superseded"))


def derive(steps: list[StepFacts], *, cancel_requested: bool, attempts_left: int) -> tuple[str, str | None, bool]:
    """(state, reason_code, partial) of a task from its steps (CF-3 §4.2), with two refinements recorded in the PR:
    a cancel never closes a task while an external-effect observer is open (§4.4), and a queued step whose dependency is
    blocked or failed does not make the task `queued` (it waits on that dependency)."""
    by_key = {s.key: s for s in steps}
    running = [s for s in steps if s.state == "running"]
    external_open = [s for s in steps if s.observes_external and s.state in OPEN_STATES]
    if cancel_requested and not running and not external_open:
        return "cancelled", "cancelled_by_person", _partial(steps, "cancelled")
    if running:
        return "running", None, False
    if any(s.state == "awaiting_approval" for s in steps):
        return "awaiting_approval", None, False
    for s in steps:
        if s.state == "queued" and all((by_key.get(d) is None or by_key[d].state not in ("failed", "blocked", "cancelled")) for d in s.depends_on):
            return "queued", None, False
    blocked = [s for s in steps if s.state == "blocked"]
    if blocked:
        return "blocked", blocked[0].reason_code or "needs_input", False
    if any(retryable(s, attempts_left) for s in steps):
        return "blocked", "step_failed", False
    if any(s.state == "queued" for s in steps):
        # Queued behind something that can no longer finish: nothing more will happen without a person.
        return "blocked", "step_failed", False
    if not steps or all(s.state == "completed" for s in steps):
        return "completed", None, False
    if all(s.state == "cancelled" for s in steps):
        reason = next((s.reason_code for s in steps if s.reason_code), None)
        return "cancelled", reason, False
    reason = next((s.reason_code for s in steps if s.state == "failed" and s.reason_code), None)
    return "failed", reason, _partial(steps, "failed")


def _partial(steps: list[StepFacts], state: str) -> bool:
    return state != "completed" and any(s.state == "completed" for s in steps)


def dependents(steps: list[StepFacts], key: str) -> list[str]:
    """Every step that transitively depends on `key`, in plan order."""
    found: list[str] = []
    frontier = {key}
    changed = True
    while changed:
        changed = False
        for s in steps:
            if s.key not in found and s.key != key and frontier.intersection(s.depends_on):
                found.append(s.key)
                frontier.add(s.key)
                changed = True
    order = [s.key for s in steps]
    return sorted(found, key=order.index)


def waiting_on(step: StepFacts, steps: list[StepFacts]) -> list[str]:
    by_key = {s.key: s for s in steps}
    return [d for d in step.depends_on if (by_key.get(d) is not None and by_key[d].state != "completed")]


# --- keys and digests (EX-18, §8.3, §10.1) --------------------------------------------------------------------------------
def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256(value) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def effect_key(task_id: str, step_key: str, generation: int, *, capability_id: str | None = None, input_digest: str | None = None) -> str:
    """'tsk:' + task id (32 hex) + ':' + step key + ':g' + generation; a tool call inside a model step appends a short digest of
    the call. Stable across automatic reclaim (same generation); changes only with an explicit retry."""
    key = f"tsk:{str(task_id).replace('-', '').lower()}:{step_key}:g{int(generation)}"
    if capability_id:
        key += ":" + sha256(f"{capability_id}|{input_digest or ''}")[:16]
    return key


def input_digest(capability_id: str, inputs: dict) -> str:
    return sha256({"capability": capability_id, "inputs": inputs})


def request_digest(created_by: str, payload) -> str:
    """L1: the creator is part of the digest, so another member's reuse of a key never matches (CF-3 §8.3)."""
    return sha256({"createdBy": str(created_by), "payload": payload})


def approval_digest(capability_id: str, input_digest_value: str, targets: list, risk: str, generation: int) -> str:
    """sha256(capability_id, input_digest, sorted target {type,id,revision}, risk, generation) for agent_action/spend (§10.1)."""
    ordered = sorted(({"type": str(t.get("type")), "id": str(t.get("id")), "revision": t.get("revision")} for t in targets or [] if isinstance(t, dict)),
                     key=lambda t: (t["type"], t["id"]))
    return sha256([capability_id, input_digest_value, ordered, risk, int(generation)])


def valid_step_key(key) -> bool:
    return isinstance(key, str) and bool(_STEP_KEY.match(key))


def valid_capability(capability_id) -> bool:
    return isinstance(capability_id, str) and bool(_CAPABILITY.match(capability_id))


def clip(text, limit: int) -> str | None:
    if text is None:
        return None
    value = " ".join(str(text).split())[:limit]
    return value or None
