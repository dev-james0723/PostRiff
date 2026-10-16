"""The step seam to CF-2 (`decide_for_step`, CF-2 §8.4; CF-3 §6.2, §18).

The engine calls `decide_for_step` at every claim and every inline step start, whatever any epoch says. Lane B owns the real
decision (`agent_runtime_v2/authz.py`, migration 107). Until it is present this module answers with a fallback that is
exactly today's rule: the creator's current membership and role (re-read in the claiming transaction) against the
capability's ToolSpec permission. The fallback never asks for more than today and never grants more than today.

Resolution order: lane B's `authz.decide_for_step` when that module exists; else a decider registered with
`register_decider` (lane B may register instead of being imported); else the fallback. Whatever answers, the verdict is
normalised to `StepVerdict` and its reason mapped to a CF-3 step reason code (§8.4 table).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ...permissions import Membership

LEGACY_BASELINE = "legacy_v1"
VERDICTS = ("allow", "approve", "step_up", "deny", "observe")


@dataclass(frozen=True)
class Actor:
    kind: str                 # 'agent' | 'human_ui' | 'approval' | 'autopilot' | 'recipe' | 'cron' | 'retry' | 'continuation'
    principal: str
    request_text: str = ""    # ONLY the current human message of an inline agent tool call; "" everywhere else (correction 9)
    evidence: dict | None = None


@dataclass(frozen=True)
class StepVerdict:
    verdict: str                      # allow | approve | step_up | deny
    approval_kind: str | None         # agent_action | proposal | spend | step_up_action
    reason_code: str | None           # CF-3 step reason code, or None when allowed
    authz_reason: str                 # the CF-2 REASON_CODES value ('allowed', 'role', ...)
    token: str                        # Grants.token() used for this decision (64 hex)
    required_permission: str = "edit"
    approver_policy: str = "task_owner"
    requires_step_up: bool = False


# CF-2 §8.4: decide() reason -> step reason code (deny); revocation vs missing depends on whether the task was allowed before.
_DENY_REASON = {
    "membership_missing": "member_inactive",
    "provider_not_connected": "provider_disconnected", "provider_reauth_required": "provider_disconnected",
    "provider_scope_missing": "provider_grant_missing", "provider_lane_mismatch": "provider_grant_missing",
    "provider_capability_unsupported": "provider_grant_missing",
    "explicit_request_required": "needs_input", "native_only": "needs_input",
    "feature_off": "feature_unavailable",
    "cost_limit": "budget", "autopilot_limit": "budget",
    "permissions_changed": "permission_revoked",
}
_PERMISSION_REASONS = ("role", "not_in_baseline", "category_off", "capability_off", "domain_off", "workspace_consent", "workspace_ceiling",
                       "autopilot_not_covered", "founder_tenant")

_registered = None


def register_decider(fn) -> None:
    """Lane B (CF-2) may register its decide_for_step here instead of being imported. Passing None removes it."""
    global _registered
    _registered = fn


def legacy_token(member: Membership | None) -> str:
    """The fallback's Grants.token(): a digest of the legacy baseline and the member's current role and flags. A role change
    therefore changes the token (compared with <> by the engine); the epoch is never consulted."""
    summary = member.summary() if member is not None else {"role": None}
    material = LEGACY_BASELINE + "|" + "|".join(f"{k}={summary[k]}" for k in sorted(summary))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def membership(cur, workspace_id: str, principal: str) -> Membership | None:
    """The principal's active membership, re-read now (None when it ended, the profile is deleted, or the role is unknown)."""
    cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m "
                "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL",
                (workspace_id, principal))
    row = cur.fetchone()
    if not row:
        return None
    try:
        return Membership.from_row(*row)
    except Exception:  # noqa: BLE001 — an unknown role is no membership
        return None


def _cf2():
    try:
        from importlib import import_module
        authz = import_module("postriff_phase2.agent_runtime_v2.authz")
    except ModuleNotFoundError as error:
        if error.name != "postriff_phase2.agent_runtime_v2.authz":
            raise
        return None
    fn = getattr(authz, "decide_for_step", None)
    return fn if callable(fn) else None


def decide_for_step(cur, task: dict, step: dict, *, actor: Actor, now: float, allowed_before: bool = False, config=None) -> StepVerdict:
    fn = _cf2() or _registered
    if fn is not None:
        raw = fn(cur, task, step, actor=actor, now=now, config=config)
        return normalise(raw, allowed_before=allowed_before)
    return fallback(cur, task, step, actor=actor, allowed_before=allowed_before)


def normalise(raw, *, allowed_before: bool) -> StepVerdict:
    """Accept lane B's StepVerdict (or an equivalent object/dict) and fill the CF-3 reason code from the frozen table."""
    get = (lambda k, d=None: raw.get(k, d)) if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
    verdict = get("verdict")
    if verdict not in VERDICTS:
        verdict = "deny"
    authz_reason = str(get("authz_reason") or get("reason") or ("allowed" if verdict == "allow" else "role"))
    reason_code = get("reason_code")
    if verdict == "deny" and not reason_code:
        reason_code = map_reason(authz_reason, allowed_before=allowed_before)
    if verdict in ("allow", "observe"):
        reason_code = None
    token = str(get("token") or "")
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        token = hashlib.sha256(token.encode("utf-8")).hexdigest()
    kind = get("approval_kind")
    if verdict == "approve" and kind not in ("agent_action", "proposal", "spend"):
        kind = "agent_action"
    if verdict == "step_up":
        kind = "step_up_action"
    return StepVerdict(verdict, kind if verdict in ("approve", "step_up") else None, reason_code, authz_reason[:64], token,
                       str(get("required_permission") or "edit"), str(get("approver_policy") or "task_owner"), bool(get("requires_step_up") or verdict == "step_up"))


def map_reason(authz_reason: str, *, allowed_before: bool) -> str:
    if authz_reason in _DENY_REASON:
        return _DENY_REASON[authz_reason]
    if authz_reason in _PERMISSION_REASONS:
        return "permission_revoked" if allowed_before else "permission_missing"
    return "permission_revoked" if allowed_before else "permission_missing"


def fallback(cur, task: dict, step: dict, *, actor: Actor, allowed_before: bool) -> StepVerdict:
    """Today's rule, re-read in this transaction: the creator is still an active member and the role allows the capability."""
    from .. import domain_tools, tool_adapter

    member = membership(cur, task["workspaceId"], task["createdBy"])
    token = legacy_token(member)

    def deny(authz_reason):
        return StepVerdict("deny", None, map_reason(authz_reason, allowed_before=allowed_before), authz_reason, token)

    if (actor.kind == "cron" and step.get("kind") == "delegate" and step.get("observesExternal") is True
            and step.get("delegateType") in ("publish_job", "automation_item")
            and (task.get("cancelRequestedAt") is not None or member is None)):
        return StepVerdict("observe", None, None, "observer", token)
    if member is None:
        return deny("membership_missing")
    kind = step.get("kind")
    if kind == "tool":
        domain_tools.ensure_registered()
        tool = tool_adapter.REGISTRY.get(step.get("capabilityId") or "")
        if tool is None:
            return deny("feature_off")
        if tool.spec.tenant != "workspace":
            return deny("founder_tenant")
        if not member.allows(tool.spec.permission):
            return deny("role")
        return StepVerdict("allow", None, None, "allowed", token)
    if kind in ("delegate", "wait", "approval", "model", "continuation"):
        if not member.allows("read"):
            return deny("role")
        return StepVerdict("allow", None, None, "allowed", token)
    return deny("feature_off")
