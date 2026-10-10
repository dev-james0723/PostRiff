"""Rafii agent authorization (rafii-agent-authz/1, CF-2 §8): one pure decision, three modes, one gate per tool call.

    allowed = user rights ∩ workspace/resource rights ∩ current agent consent ∩ provider grants ∩ capability policy   (INV-1)

No term ever widens another, and anything missing denies (INV-2): an unknown capability, a missing membership, a consent
reader that does not exist, an explicit-request capability without a matcher, an approval that is replayed or expired.

Modes (`RuntimeConfig.permissions_for(workspace)`, from RAFII_AGENT_PERMISSIONS_MODE narrowed by the fail-closed
RAFII_AGENT_PERMISSIONS_WORKSPACES allowlist):
- ``off``: nothing is evaluated. `tool_gate` returns before reading anything, so every tool call is exactly today's.
- ``shadow``: the decision is computed in its own short read and a would-deny line is logged (`agent.authz.shadow`).
  The tool call, its result, the ledger and the context are untouched: shadow can never change behaviour.
- ``enforce``: the decision is applied. A deny is a typed `agent_permission_denied` tool result, a confirmation is
  `needs_confirmation`, an R3 handoff is `native_only`.

People with no choice on record (existing members, anyone who chose "Not now") resolve to `LEGACY_BASELINE_V1` with
each surface's legacy confirmation: exactly what Rafii does today (DP-3/DP-4). Nothing here grants a permission: grant
rows are written only by session-authenticated HTTP handlers (agent_permissions, PI-3), never from a tool context.

`decide()` is pure over database-derived state and server constants. No model output, tool argument, page text,
document, message or provider string feeds it (PI-1, PI-6); untrusted content is data, never authority.

The capability registry (CF-1, lane A.1) owns capability metadata. Until it lands, `capability_for` derives the same
fields from the existing ToolSpec with CF-1 §4's default derivation and §7's classification; once a ToolSpec has
`policy()`, the registry's answer is used instead.
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import hmac
import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from postriff_alpha.domain import AlphaError

from . import agent_error_codes, contracts

log = logging.getLogger("postriff.agent_runtime")

# --- vocabulary (CF-1 §3; read through contracts.py once lane A.1 adds it there) ---------------------------------------
CATEGORIES = getattr(contracts, "CATEGORIES", ("read_analyze", "navigate_interact", "create_edit", "manage_settings",
                                               "manage_connected_services", "execute_automations"))
RISKS = getattr(contracts, "RISKS", ("R0", "R1", "R2", "R3"))
CONFIRMATIONS = getattr(contracts, "CONFIRMATIONS", ("none", "native", "proposal", "approval_step_up"))   # ordered: stricter later
COSTS = getattr(contracts, "COSTS", ("free", "text_credits", "media_credits"))
DATA_DOMAINS = getattr(contracts, "DATA_DOMAINS", ("public", "web", "account", "screen", "content", "campaigns", "library",
                                                   "memory_brand", "connections", "analytics", "growth_trends", "notifications",
                                                   "usage_billing", "members", "agent_activity", "automations"))
CONSENT_KEYS = getattr(contracts, "CONSENT_KEYS", ("memory_cloud", "research_web", "media_cloud", "connector_cloud", "growth", "radar",
                                                   "voice_sample_route", "library_purpose"))
AUTONOMY = getattr(contracts, "AUTONOMY", ("ask", "assist"))
CATALOGUE_GENERATION = getattr(contracts, "CATALOGUE_GENERATION", 1)
R3_REAUTH_SECONDS = getattr(contracts, "R3_REAUTH_SECONDS", 300)
SURFACES = getattr(contracts, "SURFACES", ("manager", "specialist", "site_agent", "commands_direct", "genui_action", "genui_query", "context"))
ALL_DOMAINS = tuple(d for d in DATA_DOMAINS if d != "public")   # 'public' is always allowed
SETTINGS_HREF = "/app/account/agent"
MODES = ("off", "shadow", "enforce")
OUTCOMES = ("allow", "confirm", "approve", "step_up", "deny")
ACTOR_KINDS = ("agent", "human_ui", "approval", "autopilot", "recipe")

REASON_CODES = ("allowed", "founder_tenant", "role", "workspace_consent", "workspace_ceiling", "feature_off", "not_in_baseline",
                "category_off", "capability_off", "domain_off", "provider_not_connected", "provider_reauth_required",
                "provider_scope_missing", "provider_lane_mismatch", "provider_capability_unsupported", "explicit_request_required",
                "needs_confirmation", "needs_approval", "needs_step_up", "native_only", "autopilot_not_covered", "autopilot_limit",
                "rate_limited", "cost_limit", "membership_missing", "permissions_changed")
# R0 and R1 floors by autonomy (CF-2 §8.1); R2 keeps the capability's own confirmation, R3 is approval_step_up.
FLOOR = {"R0": {"ask": "none", "assist": "none"}, "R1": {"ask": "native", "assist": "none"}}
SPEND = {"none": (), "media": ("media_credits",), "all": ("text_credits", "media_credits")}


def stricter(a: str, b: str) -> str:
    """The stricter of two confirmations in CONFIRMATIONS order (INV-10's max)."""
    return a if CONFIRMATIONS.index(a) >= CONFIRMATIONS.index(b) else b


@dataclass(frozen=True)
class ProviderScope:
    provider: str                        # platform key as stored on the channel ('YouTube', 'Instagram', ...)
    scopes: tuple = ()                   # every one must be granted on the connection
    lane: str | None = None              # 'agentic' | 'standard' | None (YouTube authorizationLane)
    capability: str | None = None        # a channel capability that must not be 'Unsupported'


@dataclass(frozen=True)
class Capability:
    """The fields of CF-1's CapabilitySpec that `decide()` reads."""
    capability_id: str
    version: int
    kind: str                            # 'tool' | 'ui_action' | 'ui_query' | 'context' | 'native_only'
    name: str
    category: str
    risk: str
    confirmation: str                    # the POLICY floor; a surface's legacy confirmation lives on its Surface
    permission: str
    tenant: str = "workspace"
    effect: str = contracts.READ
    approval: bool = False
    cost: str = "free"
    data_grants: tuple | None = None     # None: undeclared — requires every domain (fail closed for Custom)
    consents: tuple = ()
    provider_scopes: tuple = ()
    explicit_request: bool = False
    autopilot_eligible: bool = False
    since: int = 1
    route_id: str | None = None
    label: str = ""

    def required_domains(self) -> tuple:
        if self.data_grants is None:
            return ALL_DOMAINS
        return tuple(d for d in self.data_grants if d != "public")


@dataclass(frozen=True)
class Surface:
    """Where a capability is reached and what that surface asks today (CF-1 §6, correction 6)."""
    name: str
    binding_ref: str
    legacy_confirmation: str


# --- capability metadata until the registry lands (CF-1 §4 derivation, §7 classification) -----------------------------
_GROUPS = {
    ("navigate_interact", ("public",)): ("ui_navigate", "ui_show_help", "ui_guide"),
    ("navigate_interact", ("account",)): ("ui_voice",),
    ("read_analyze", ("public",)): ("help_search", "help_get", "route_describe", "skills_list"),
    ("read_analyze", ("agent_activity",)): ("task_plan", "task_update", "pending_approvals"),
    ("read_analyze", ("account",)): ("privacy_egress_state", "models_summary"),
    ("read_analyze", ("automations",)): ("automation_list", "automation_get", "automation_explain"),
    ("read_analyze", ("campaigns", "content")): ("campaign_list", "campaign_get", "campaign_items", "campaign_membership", "relationships",
                                                 "record_attribution"),
    ("read_analyze", ("memory_brand",)): ("memory_context", "memory_summary", "voice_check", "overlay_context", "brand_summary", "voice_profile"),
    ("read_analyze", ("web",)): ("web_research", "research_search", "research_fetch", "source_normalize", "weather_now"),
    ("read_analyze", ("library",)): ("library_search", "library_read", "library_browse"),
    ("read_analyze", ("connections",)): ("channels_capabilities",),
    ("read_analyze", ("members",)): ("member_activity",),
    ("read_analyze", ("notifications",)): ("notification_list",),
    ("read_analyze", ("usage_billing",)): ("entitlements_summary",),
    ("read_analyze", ("content", "connections")): ("engagement_triage", "youtube_plan_context", "youtube_recommendations"),
    ("read_analyze", ("analytics", "connections")): ("youtube_analytics_summary",),
    ("read_analyze", ("content",)): ("queue_summary", "job_get", "draft_get", "calendar_range", "reviews_list", "publishing_summary",
                                     "content_search", "entity_status", "workspace_search", "workspace_summary", "attention_summary",
                                     "attention_summary_v2", "weekly_plan_get", "strategy_context", "creative_plan", "image_analyze",
                                     "image_list"),
    ("create_edit", ("content", "memory_brand")): ("draft_create", "draft_rewrite"),
    ("create_edit", ("content",)): ("draft_edit", "weekly_plan_prepare", "engagement_draft_create", "source_campaign_create",
                                    "image_generate", "image_edit", "image_variant"),
    ("create_edit", ("campaigns", "content")): ("campaign_link", "campaign_unlink"),
    ("create_edit", ("content", "connections")): ("youtube_plan_prepare",),
    ("execute_automations", ("content", "automations")): ("proposal_apply",),
    ("execute_automations", ("content", "connections")): ("schedule_propose",),
    ("execute_automations", ("automations",)): ("automation_change_propose",),
}
CLASSIFICATION = {name: (category, grants) for (category, grants), names in _GROUPS.items() for name in names}
COST = {"draft_create": "text_credits", "draft_rewrite": "text_credits", "weekly_plan_prepare": "text_credits",
        "image_generate": "media_credits", "image_edit": "media_credits", "image_variant": "media_credits"}
SINCE = {"library_browse": 2}   # LIB-D5b: added after the freeze, so never part of LEGACY_BASELINE_V1


def _derived(spec) -> Capability:
    effect, approval = spec.effect, bool(spec.approval)
    if approval or effect == contracts.PREPARE_EXTERNAL:
        category, risk, confirmation = "execute_automations", "R2", "proposal"
    elif effect == contracts.READ:
        category, risk, confirmation = "read_analyze", "R0", "none"
    else:
        category, risk, confirmation = "create_edit", "R1", "none"
    grants = None
    if spec.name in CLASSIFICATION:
        category, grants = CLASSIFICATION[spec.name]
    if spec.name.startswith("trend_"):
        grants = ("growth_trends",)
    if spec.tenant == "founder":
        grants = ()
    return Capability(capability_id=f"tool.{spec.name}", version=1, kind="tool", name=spec.name, category=category, risk=risk,
                      confirmation=confirmation, permission=spec.permission, tenant=spec.tenant, effect=effect, approval=approval,
                      cost=COST.get(spec.name, "free"), data_grants=grants, since=SINCE.get(spec.name, 1))


def _registry_capability(policy) -> Capability:
    """One strict adapter for the registry's capability schema; missing fields fail closed."""
    values = {name: getattr(policy, name) for name in Capability.__dataclass_fields__}
    return Capability(**values)


def capability_for(spec) -> Capability:
    from . import capability_registry
    return _registry_capability(capability_registry.from_tool(spec))


def tool_surface(spec, agent: str | None = None) -> Surface:
    from . import capability_registry
    name = "manager" if agent in (None, "rafii_manager") else "specialist"
    try:
        binding = capability_registry.surface(name, spec.name)
    except LookupError:
        if name != "manager" or f"tool.{spec.name}" not in capability_registry.MANAGER_EXPANSION_V1:
            raise
        binding = capability_registry.surface("specialist", spec.name)
    return Surface(name, spec.name, binding.legacy_confirmation)


# --- LEGACY_BASELINE_V1 (CF-1 §12) ---------------------------------------------------------------------------------------
BASELINE_FILE = Path(__file__).with_name("legacy_baseline_v1.json")


def _baseline() -> frozenset:
    data = json.loads(BASELINE_FILE.read_text())
    return frozenset(data["capabilities"])


LEGACY_BASELINE_V1 = _baseline()


def compute_baseline() -> list[str]:
    from . import capability_registry
    return sorted(capability_registry.legacy_baseline_v1())


# --- the decision -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Actor:
    kind: str                            # ACTOR_KINDS
    principal: str
    request_text: str = ""               # ONLY the current human message of this request; "" for cron, resume, retry (correction 9)
    evidence: dict | None = None         # {'activationId', 'capabilityId'} | {'approval': {...}, 'digest'} | {'creditQuote': {...}, 'requestDigest'} | {'stepUp': {'at'}}


@dataclass(frozen=True)
class Decision:
    outcome: str                         # OUTCOMES
    reason: str                          # REASON_CODES
    capability_id: str
    capability_version: int
    category: str
    risk: str
    required: str                        # effective confirmation after INV-10
    detail: str | None = None
    policy_id: str | None = None
    token: str = ""

    def public(self) -> dict:
        return {"outcome": self.outcome, "reason": self.reason, "required": self.required, **({"detail": self.detail} if self.detail else {})}


def _consent(module_name: str, reader: Callable[[Any, dict], bool]) -> Callable[[dict, Any], bool]:
    def read(state, _target):
        import importlib
        return bool(reader(importlib.import_module(f"postriff_phase2.{module_name}"), state or {}))
    return read


CONSENT_READERS: dict[str, Callable[[dict, Any], bool]] = {   # IMPLEMENTED readers only; an absent key denies
    "memory_cloud": _consent("memory", lambda m, s: m.egress(s).get("cloud") is True),
    "research_web": _consent("research", lambda m, s: m.allowed(s)),
    "media_cloud": _consent("media_consent", lambda m, s: m.decision(s).get("cloud") is True),
    "connector_cloud": _consent("productivity_connectors", lambda m, s: m.egress_decision(s).get("cloud") is True),
    "growth": lambda s, t: bool((s or {}).get("growthConsent")),
    "radar": lambda s, t: bool(((s or {}).get("radarConsent") or {}).get("sources")),
    "voice_sample_route": lambda s, t: True,   # enforced per sample by voice_sources; declared for the UI only
    "library_purpose": lambda s, t: True,      # delegates to the Library's own per-purpose recheck once that lands
}
# capability_id -> matcher over the CURRENT human message only. A capability marked explicit_request with no matcher denies.
def _youtube_requested(text: str, *, analytics=False) -> bool:
    # Share the existing provider boundary's unquoted human-prose rules. No tool
    # argument, stored approval text or earlier turn supplies fresh authority.
    from ..youtube import agent_tools as youtube
    text = youtube._human_prose(str(text or ""))
    explicit_read = any(youtube._YOUTUBE.search(clause) and youtube._ANALYTICS.search(clause)
                        and youtube._OWNED_READ.search(clause) and not youtube._EDUCATIONAL.search(clause)
                        for clause in re.split(r"[.!?;\n，,。！？；]+", text))
    return bool(youtube._YOUTUBE.search(text) and not youtube._NEGATIVE.search(text)
                and (not analytics or (not youtube._NO_ACCESS.search(text) and explicit_read)))


EXPLICIT_REQUEST: dict[str, Callable[[str], bool]] = {
    "tool.youtube_plan_context": _youtube_requested,
    "tool.youtube_plan_prepare": _youtube_requested,
    "tool.youtube_recommendations": _youtube_requested,
    "tool.youtube_analytics_summary": functools.partial(_youtube_requested, analytics=True),
}


def _d(cap: Capability, outcome: str, reason: str, *, required: str | None = None, detail=None, policy_id=None, token="") -> Decision:
    return Decision(outcome, reason, cap.capability_id, cap.version, cap.category, cap.risk, required or cap.confirmation, detail=detail,
                    policy_id=policy_id, token=token)


def decide(cap: Capability, *, surface: Surface, member, grants, state: dict | None, actor: Actor, provider_view=None,
           target: dict | None = None, now: float) -> Decision:
    """One capability on one surface for one actor (CF-2 §8.1). Pure: no I/O, no model input."""
    token = grants.token() if grants is not None else ""

    def out(outcome, reason, **kw):
        kw.setdefault("required", surface.legacy_confirmation)
        return _d(cap, outcome, reason, token=token, **kw)

    legacy = surface.legacy_confirmation
    # (a) capability policy (static)
    if cap.kind == "native_only":
        return out("step_up", "native_only", required="approval_step_up")
    if cap.tenant == "founder":
        return out("allow", "founder_tenant", required=legacy)
    # (b) user rights (authoritative, unchanged)
    if member is None:
        return out("deny", "membership_missing")
    if not member.allows(cap.permission):
        return out("deny", "role")
    if grants is None:
        return out("deny", "permissions_changed")
    # (c) workspace / resource rights
    for key in cap.consents:
        reader = CONSENT_READERS.get(key)
        try:
            granted = reader is not None and reader(state, target)
        except Exception:  # noqa: BLE001 — a reader that cannot answer is not consent
            granted = False
        if not granted:
            return out("deny", "workspace_consent", detail=key)
    ceiling = grants.ceiling or {}
    if ceiling.get(cap.category) == "off":
        return out("deny", "workspace_ceiling")
    # (d) agent consent
    spend_only = False
    mode = None
    if grants.source == "legacy":
        if cap.capability_id not in LEGACY_BASELINE_V1:
            return out("deny", "not_in_baseline")
        required = legacy
    else:
        if grants.baseline == "legacy_v1" and cap.capability_id not in LEGACY_BASELINE_V1:
            return out("deny", "not_in_baseline")
        override = grants.capabilities.get(cap.capability_id)
        if override == "off":
            return out("deny", "capability_off")
        mode = override or grants.categories.get(cap.category)
        if ceiling.get(cap.category) == "ask":
            mode = "ask" if mode else None
        if mode is None:
            if cap.risk == "R0" and cap.data_grants == ("public",):
                mode = "assist"
            else:
                return out("deny", "category_off")
        missing = [d for d in cap.required_domains() if d not in grants.domains]
        if missing:
            return out("deny", "domain_off", detail=missing[0])
        if cap.risk in FLOOR:
            floor = FLOOR[cap.risk][mode]
        elif cap.risk == "R3":
            floor = "approval_step_up"
        else:
            floor = cap.confirmation
        if cap.cost in SPEND.get(grants.spend_confirmation, SPEND["all"]):
            spend_only = floor == "none" and cap.confirmation == "none" and legacy == "none"
            floor = stricter(floor, "native")
        if cap.since > grants.catalogue_generation and cap.risk != "R0":
            floor = stricter(floor, "native")
            spend_only = False
        required = stricter(legacy, stricter(cap.confirmation, floor))   # INV-10: never below the surface's legacy confirmation
    # (e) provider grants (read-only; never decrypts, never refreshes)
    for scope in cap.provider_scopes:
        reason = provider_check(provider_view, scope, target, now=now)
        if reason:
            return out("deny", reason, required=required)
    # (f) explicit request: only the current human message counts
    if cap.explicit_request:
        matcher = EXPLICIT_REQUEST.get(cap.capability_id)
        if actor.kind != "agent" or matcher is None or not matcher(actor.request_text or ""):
            return out("deny", "explicit_request_required", required=required)
    # (g) autonomy and confirmation
    if actor.kind == "autopilot":
        return _autopilot(cap, grants, mode, required, actor, target, now, out)
    if required == "none":
        return out("allow", "allowed", required=required)
    if required == "native":
        if _evidence_ok(actor, cap, now, spend_only=spend_only):
            return out("allow", "allowed", required=required)
        return out("confirm", "needs_confirmation", required=required)
    if required == "proposal":
        if cap.approval or (actor.kind == "approval" and _evidence_ok(actor, cap, now)):
            return out("allow", "allowed", required=required)
        return out("approve", "needs_approval", required=required)
    if _step_up_ok(actor, now, window=R3_REAUTH_SECONDS):
        return out("allow", "allowed", required=required)
    return out("step_up", "needs_step_up", required=required)


def _autopilot(cap, grants, mode, required, actor, target, now, out) -> Decision:
    """Bounded autopilot (CF-2 §1, P2 runner only): R0/R1 inside an explicit, unexpired policy whose category is already
    Assist; R2 never without a per-action approval; R3 never."""
    if cap.risk == "R3":
        return out("deny", "autopilot_not_covered", required=required)
    if cap.risk == "R2":
        if _evidence_ok(Actor("approval", actor.principal, "", actor.evidence), cap, now):
            return out("allow", "allowed", required=required)
        return out("approve", "needs_approval", required=required)
    if grants.source != "explicit" or mode != "assist" or (cap.risk == "R1" and not cap.autopilot_eligible):
        return out("deny", "autopilot_not_covered", required=required)
    policy = next((p for p in grants.autopilot if cap.capability_id in p.capability_ids and p.expires_at > now and _within(p, target)), None)
    if policy is None:
        return out("deny", "autopilot_not_covered", required=required)
    limits, usage = policy.limits or {}, policy.usage or {}
    for limit_key, usage_key in (("actionsPerDay", "actionsToday"), ("actionsTotal", "actionsTotal")):
        if isinstance(limits.get(limit_key), int) and int(usage.get(usage_key) or 0) >= limits[limit_key]:
            return out("deny", "autopilot_limit", required=required, policy_id=policy.id)
    return out("allow", "allowed", required=required, policy_id=policy.id)


def _within(policy, target) -> bool:
    """A policy's constraints narrow it to named connections, campaigns or platforms; an unnamed target is outside."""
    constraints = policy.constraints or {}
    for key, field_name in (("connectionIds", "connectionId"), ("campaignIds", "campaignId"), ("platforms", "platform")):
        allowed = constraints.get(key)
        if allowed:
            if not isinstance(target, dict) or target.get(field_name) not in allowed:
                return False
    return True


def approval_evidence_ok(record: Mapping | None, *, capability_id: str, digest: str | None, principal: str, now: float) -> bool:
    """A stored approval authorizes exactly one execution of exactly what was approved, by the person it was asked of,
    before it expires. Replayed (consumed), expired, rejected, revoked, foreign or drifted approvals never count."""
    if not isinstance(record, Mapping) or not isinstance(digest, str) or not digest:
        return False
    stored = record.get("digest")
    expires = record.get("expiresAt")
    return (record.get("state") == "approved" and not record.get("consumedAt")
            and record.get("capabilityId") == capability_id
            and isinstance(stored, str) and hmac.compare_digest(stored, digest)
            and str(record.get("requestedFor") or "") == str(principal)
            and isinstance(expires, (int, float)) and expires > now)


def _evidence_ok(actor: Actor, cap: Capability, now: float, *, spend_only: bool = False) -> bool:
    evidence = actor.evidence or {}
    if actor.kind == "human_ui":
        return bool(evidence.get("activationId")) and evidence.get("capabilityId") == cap.capability_id
    if actor.kind == "approval":
        return approval_evidence_ok(evidence.get("approval"), capability_id=cap.capability_id, digest=evidence.get("digest"),
                                    principal=actor.principal, now=now)
    if spend_only:
        quote = evidence.get("creditQuote") or {}
        wanted = evidence.get("requestDigest")
        return (isinstance(quote, Mapping) and isinstance(wanted, str) and isinstance(quote.get("requestDigest"), str)
                and hmac.compare_digest(quote["requestDigest"], wanted) and isinstance(quote.get("expiresAt"), (int, float))
                and quote["expiresAt"] > now and not quote.get("used"))
    return False


def _step_up_ok(actor: Actor, now: float, *, window: int) -> bool:
    at = ((actor.evidence or {}).get("stepUp") or {}).get("at")
    return isinstance(at, (int, float)) and 0 <= now - at <= window


# --- provider grants (CF-2 §11.1): read-only views of the same truth the Channels page shows ---------------------------
REAUTH_STATES = ("disconnected", "identity_known", "token_expired", "reauthorization_required", "client_binding_missing")


@dataclass(frozen=True)
class ProviderView:
    channels: tuple = ()                 # channels.customer_view(...) dicts: platform, connectionState, scopes, capabilities, lane


def provider_view(state: dict | None, now: float, youtube_status: Mapping | None = None) -> ProviderView:
    from .. import channels as channel_rules
    views = []
    for channel in ((state or {}).get("phase2") or {}).get("channels") or []:
        if not isinstance(channel, dict) or not channel.get("id"):
            continue
        if youtube_status is not None and channel.get("platform") == "YouTube":
            channel = channel_rules.with_youtube_credential_status(channel, youtube_status.get(channel["id"]))
        views.append({"id": channel["id"], "platform": channel.get("platform"), "connectionState": channel_rules.connection_state(channel, now),
                      "scopes": list(channel.get("scopes") or []), "capabilities": dict(channel.get("capabilities") or {}),
                      "authorizationLane": channel.get("authorizationLane", "standard") if channel.get("platform") == "YouTube" else None})
    return ProviderView(tuple(views))


def provider_view_current(cur, state, workspace_id, now):
    from ..channels import youtube_credential_status
    status = youtube_credential_status(cur, [workspace_id])
    return provider_view(state, now, {cid: value for (wid, cid), value in status.items() if str(wid) == str(workspace_id)})



def load_provider_view(cur, state, workspace_id, now, *, mode):
    """Shadow diagnostics must not leave the caller's PostgreSQL transaction aborted."""
    if mode != "shadow":
        return provider_view_current(cur, state, workspace_id, now)
    cur.execute("SAVEPOINT agent_provider_shadow_read")
    try:
        return provider_view_current(cur, state, workspace_id, now)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT agent_provider_shadow_read")
        cur.execute("RELEASE SAVEPOINT agent_provider_shadow_read")


def provider_check(view: ProviderView | None, scope: ProviderScope, target: Mapping | None = None, *, now: float) -> str | None:
    """Why this provider grant is missing (a REASON_CODES value), or None when it is there."""
    channels = [c for c in (view.channels if view else ()) if str(c.get("platform") or "").lower() == scope.provider.lower()]
    wanted = ((target or {}).get("channelId") or (target or {}).get("connectionId")) if isinstance(target, Mapping) else None
    if wanted:
        channels = [c for c in channels if c.get("id") == wanted]
    if not channels:
        return "provider_not_connected"
    reasons = []
    for channel in channels:
        if channel.get("connectionState") in REAUTH_STATES:
            reasons.append("provider_reauth_required")
        elif not set(scope.scopes) <= set(channel.get("scopes") or ()):
            reasons.append("provider_scope_missing")
        elif scope.lane and channel.get("authorizationLane") != scope.lane:
            reasons.append("provider_lane_mismatch")
        elif scope.capability and ((channel.get("capabilities") or {}).get(scope.capability) or {}).get("level", "Unsupported") == "Unsupported":
            reasons.append("provider_capability_unsupported")
        else:
            return None
    return reasons[0]


# --- the public catalogue the permissions UI reads (CF-1 §11) ------------------------------------------------------------
def catalogue() -> list[Capability]:
    from . import capability_registry
    return [_registry_capability(policy) for _, policy in sorted(capability_registry.ensure().items()) if policy.tenant != "founder"]


def capability_by_id(capability_id: str) -> Capability | None:
    from . import capability_registry
    policy = capability_registry.get(capability_id)
    return _registry_capability(policy) if policy is not None else None


def capability_surfaces(cap: Capability) -> list[Surface]:
    from . import capability_registry
    return [Surface(b.surface, b.binding_ref, b.legacy_confirmation) for b in capability_registry.bindings(cap.capability_id)]


def public_catalogue() -> list[dict]:
    from . import capability_registry
    return capability_registry.public_catalogue()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def catalogue_digest() -> str:
    from . import capability_registry
    return capability_registry.catalogue_digest()


# --- modes and the E1 gate ----------------------------------------------------------------------------------------------
IN_TOOL: contextvars.ContextVar[bool] = contextvars.ContextVar("rafii_authz_in_tool", default=False)
ACTIVE_CONTEXT: contextvars.ContextVar = contextvars.ContextVar("rafii_authz_active_context", default=None)
# Set by the task engine (CF-3 §10.1): fn(ctx, capability, args, decision) -> {approvalId, summary, expiresAt} | None.
APPROVAL_REQUESTER: list[Callable] = []


def register_approval_requester(fn: Callable) -> None:
    APPROVAL_REQUESTER[:] = [fn]


# Startup adapters declare actual installed enforcement points. The partial store/E1/E11
# recovery must never make enforce selectable while E2–E10 are still unwired.
REQUIRED_ENFORCEMENT_POINTS = frozenset(f"E{i}" for i in range(1, 13))
# E8 is registered by the integrated task-engine approval adapter only after validation.
ENFORCEMENT_POINTS: set[str] = {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E9", "E10", "E11", "E12"}


def enforcement_ready() -> bool:
    return REQUIRED_ENFORCEMENT_POINTS <= ENFORCEMENT_POINTS


def runtime_config_for(service=None):
    """Trusted application configuration; never a request/body-supplied mode."""
    configured = getattr(service, "agent_permissions_config", None)
    if configured is not None:
        return configured
    runtime = getattr(service, "agent_runtime", None)
    cfg = getattr(runtime, "cfg", None)
    if cfg is not None:
        return cfg
    from .config import RuntimeConfig
    return RuntimeConfig.from_environment()


def gate(ctx, cap, args=None, surface=None, *, actor=None) -> Decision:
    """E3–E6/E10: one loaded transaction snapshot, with byte-identical shadow output."""
    from . import capability_registry
    cap = _registry_capability(cap) if not isinstance(cap, Capability) else cap
    if surface is None:
        raise ValueError("a registered surface is required")
    if not isinstance(surface, Surface):
        surface = Surface(surface.surface, surface.binding_ref, surface.legacy_confirmation)
    legacy = _d(cap, "allow", "allowed", required=surface.legacy_confirmation)
    mode = getattr(ctx, "authz_mode", None) or mode_for(getattr(ctx, "config", None), getattr(ctx, "workspace_id", None))
    if mode == "off" or cap.tenant == "founder":
        return legacy
    try:
        now = getattr(ctx, "now", None) or time.time
        now = now() if callable(now) else now
        state = getattr(ctx, "authz_state", None) or getattr(ctx, "state", {})
        member = getattr(ctx, "member", None) or getattr(ctx, "membership", None)
        grants = getattr(ctx, "grants", None)
        actor = actor or Actor("agent", ctx.principal, getattr(ctx, "request_text", ""), getattr(ctx, "authz_evidence", None))
        result = decide(cap, surface=surface, member=member, grants=grants, state=state, actor=actor,
                        provider_view=getattr(ctx, "authz_provider_view", None) if cap.provider_scopes else None, target=args, now=now)
        if mode == "shadow":
            log.info(json.dumps({"event": "agent.authz.shadow", "capabilityId": cap.capability_id,
                                 "wouldOutcome": result.outcome, "wouldRequired": result.required, "wouldReason": result.reason}))
            return legacy
        return result
    except Exception as error:
        log.error(json.dumps({"event": "agent.authz.error", "mode": mode, "errorClass": type(error).__name__}))
        return legacy if mode == "shadow" else _d(cap, "deny", "feature_off", required=surface.legacy_confirmation)


def load_grants(cur, workspace_id, principal, *, now, mode):
    from . import agent_permissions
    if mode != "shadow":
        return agent_permissions.load(cur, workspace_id, principal, now=now)
    cur.execute("SAVEPOINT agent_permission_shadow_read")
    try:
        return agent_permissions.load(cur, workspace_id, principal, now=now)
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT agent_permission_shadow_read")
        cur.execute("RELEASE SAVEPOINT agent_permission_shadow_read")


def bind_context(ctx, *, cur=None, state=None, member=None):
    """E12: resolve grants for the verified turn principal, only outside off mode."""
    from . import agent_permissions
    ctx.authz_mode = mode_for(getattr(ctx, "config", None), ctx.workspace_id)
    if ctx.authz_mode == "off":
        return
    if cur is None:
        with ctx.service.repository.transaction(ctx.token, ctx.workspace_id) as (cur, row, principal):
            if principal != ctx.principal:
                raise AlphaError("Workspace unavailable.", 403)
            return bind_context(ctx, cur=cur, state=ctx.service.ideas._state(row), member=ctx.service.ideas._member(row))
    ctx.authz_state = state or {}
    if member is not None:
        ctx.membership = member
    try:
        now = ctx.now() if callable(ctx.now) else ctx.now
        ctx.grants = load_grants(cur, ctx.workspace_id, ctx.principal, now=now, mode=ctx.authz_mode)
        ctx.authz_provider_view = load_provider_view(cur, state or {}, ctx.workspace_id, now, mode=ctx.authz_mode)
        filter_context(ctx)
    except Exception as error:
        log.error(json.dumps({"event": "agent.authz.load_error", "mode": ctx.authz_mode, "errorClass": type(error).__name__}))
        ctx.grants = None
        if ctx.authz_mode == "enforce":
            raise AuthzError("Rafii's permission settings could not be checked.", "agent_permission_revoked") from error


@contextmanager
def active_tool(ctx, spec, args, agent=None):
    """Scope E2's capability to this executor only, including nested tool calls."""
    names = ("active_capability", "authz_actor", "authz_args", "authz_surface")
    before = {name: getattr(ctx, name, None) for name in names}
    marker = ACTIVE_CONTEXT.set(ctx)
    try:
        if mode_for(getattr(ctx, "config", None), ctx.workspace_id) != "off" and spec.tenant != "founder":
            try:
                ctx.active_capability = capability_for(spec)
                ctx.authz_actor = getattr(ctx, "authz_actor", None) or Actor("agent", ctx.principal, ctx.request_text or "", getattr(ctx, "authz_evidence", None))
                ctx.authz_args = args
                ctx.authz_surface = tool_surface(spec, agent)
            except Exception:
                ctx.active_capability = None
                if mode_for(ctx.config, ctx.workspace_id) == "enforce":
                    raise AuthzError("Rafii cannot verify this capability.", "agent_permission_denied")
        yield
    finally:
        ACTIVE_CONTEXT.reset(marker)
        for name, value in before.items():
            setattr(ctx, name, value)


def recheck_transaction(cur, workspace_id, principal, row):
    """Cover repository.command and bound GenUI transactions as well as ctx.workspace."""
    ctx = ACTIVE_CONTEXT.get()
    if ctx is None or mode_for(getattr(ctx, "config", None), workspace_id) == "off":
        return
    if str(ctx.workspace_id) != str(workspace_id) or str(ctx.principal) != str(principal):
        raise AuthzError("Workspace unavailable.", "agent_permission_revoked")
    from ..permissions import Membership
    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    recheck(cur, ctx, state=state, member=Membership.from_row(*row[2:7]))


def recheck(cur, ctx, *, state, member):
    """E2: re-read grants inside the executor's lock immediately before effects."""
    if getattr(ctx, "active_capability", None) is None or mode_for(getattr(ctx, "config", None), ctx.workspace_id) == "off":
        return
    bind_context(ctx, cur=cur, state=state, member=member)
    decision = gate(ctx, ctx.active_capability, getattr(ctx, "authz_args", None), getattr(ctx, "authz_surface", None), actor=ctx.authz_actor)
    if decision.outcome != "allow":
        raise AuthzError("Rafii's permissions changed before this action. Confirm again.", "agent_permission_revoked")


def gate_site(ctx, capability_id: str, tool_id: str, args=None):
    from . import capability_registry
    policy = capability_registry.get(capability_id)
    if policy is None:
        raise AuthzError("Rafii cannot use this capability.", "agent_permission_denied")
    return gate(ctx, policy, args, capability_registry.surface("site_agent", tool_id))


def gate_proposal(cur, workspace_id, state, proposal, *, config, now):
    """E7: the proposal creator's grants, in the apply transaction; decider rights stay independent."""
    from types import SimpleNamespace
    from . import capability_registry
    mode = mode_for(config, workspace_id)
    if mode == "off":
        return
    kinds = {"schedule_draft": "tool.schedule_propose", "reschedule_post": "tool.schedule_propose", "automation_change": "tool.automation_change_propose"}
    capability_id = kinds.get(proposal.get("type"))
    creator = proposal.get("createdBy")
    try:
        cap = capability_registry.get(capability_id or "")
        if cap is None or not creator:
            raise LookupError("proposal creator/capability unavailable")
        member = _step_member(cur, workspace_id, creator)
        grants = load_grants(cur, workspace_id, creator, now=now, mode=mode)
        ctx = SimpleNamespace(workspace_id=workspace_id, principal=creator, member=member, grants=grants,
                              config=config, authz_mode=mode, state=state, now=now)
        surfaces = capability_registry.bindings(capability_id)
        surface = next(b for b in surfaces if b.surface in ("manager", "specialist"))
        result = gate(ctx, cap, proposal, surface, actor=Actor("approval", creator, "", {"proposalId": proposal.get("id"), "digest": proposal.get("digest")}))
        if result.outcome == "deny":
            raise AuthzError("The creator's permission for this proposal was revoked.", "agent_permission_revoked")
    except Exception as error:
        if mode == "shadow":
            log.error(json.dumps({"event": "agent.authz.shadow_proposal_error", "errorClass": type(error).__name__}))
            return
        if isinstance(error, AuthzError):
            raise
        raise AuthzError("The creator's permissions could not be verified.", "agent_permission_revoked") from error


def recheck_principal(cur, *, workspace_id, principal, member, state, capability, config=None, now=None):
    """E9: agent-created background work only. Human-configured jobs pass no capability."""
    if capability is None:
        return
    from types import SimpleNamespace
    from . import capability_registry
    config = config or runtime_config_for()
    mode = mode_for(config, workspace_id)
    if mode == "off":
        return
    try:
        cap = capability_registry.get(capability) if isinstance(capability, str) else capability
        if cap is None:
            raise LookupError("unknown background capability")
        at = time.time() if now is None else now
        grants = load_grants(cur, workspace_id, principal, now=at, mode=mode)
        bindings = capability_registry.bindings(cap.capability_id)
        surface = next(b for b in bindings if b.surface in ("manager", "specialist"))
        ctx = SimpleNamespace(workspace_id=workspace_id, principal=principal, member=member, state=state, now=at,
                              grants=grants, config=config, authz_mode=mode)
        result = gate(ctx, cap, surface=surface, actor=Actor("autopilot", principal))
        if result.outcome != "allow":
            raise AuthzError("Rafii's permission for this work changed.", "agent_permission_revoked")
    except Exception as error:
        if mode != "shadow":
            if isinstance(error, AuthzError):
                raise
            raise AuthzError("Rafii's permissions could not be checked.", "agent_permission_revoked") from error
        log.error(json.dumps({"event": "agent.authz.shadow_background_error", "errorClass": type(error).__name__}))


def filter_tools(ctx, names, *, agent=None):
    """E10: preserve exact lists in off/shadow; enforce reach before model exposure."""
    from . import capability_registry, tool_adapter
    mode = mode_for(getattr(ctx, "config", None), ctx.workspace_id)
    if mode == "off":
        return list(names)
    surface_name = "manager" if agent in (None, "rafii_manager") else "specialist"
    candidates = list(names)
    if mode == "enforce" and surface_name == "manager":
        reach = capability_registry.reach("manager", getattr(ctx, "grants", None))
        candidates += [c.name for cid in sorted(reach) if (c := capability_registry.get(cid)) and c.kind == "tool" and c.name in tool_adapter.REGISTRY and c.name not in candidates]
    kept = []
    for name in candidates:
        tool = tool_adapter.REGISTRY.get(name)
        if tool is None:
            continue
        try:
            decision = gate(ctx, capability_for(tool.spec), surface=tool_surface(tool.spec, agent))
        except Exception:
            if mode == "shadow":
                kept.append(name)
            continue
        if mode == "shadow" or decision.outcome != "deny":
            kept.append(name)
    return candidates if mode == "shadow" else kept




def filter_context(ctx):
    """Keep private context fields out of system instructions and tool fallback context too."""
    if mode_for(getattr(ctx, "config", None), ctx.workspace_id) != "enforce":
        return
    from . import capability_registry
    def allowed(ident):
        decision = gate(ctx, capability_registry.get(ident), surface=capability_registry.surface("context", ident))
        return decision.outcome == "allow"
    if not allowed("context.memory_layers"):
        if hasattr(ctx, "style"):
            ctx.style = None
    elif getattr(ctx, "style", None):
        ctx.authz_used_capabilities = set(getattr(ctx, "authz_used_capabilities", ())) | {"context.memory_layers"}
    if not allowed("context.page_summary"):
        for key, empty in (("page", {}), ("page_raw", None), ("focus", None), ("ui_selection", None), ("chip_refs", [])):
            if hasattr(ctx, key):
                setattr(ctx, key, empty)
    elif not allowed("context.screen_outline"):
        for key in ("page", "page_raw"):
            value = getattr(ctx, key, None)
            if isinstance(value, dict):
                setattr(ctx, key, {k: v for k, v in value.items() if k not in ("outline", "screen", "screenOutline", "visibleState")})
    if not allowed("context.attention"):
        for key, empty in (("focus", None), ("ui_selection", None), ("chip_refs", []), ("conversation_assets", []), ("attachments", [])):
            if hasattr(ctx, key):
                setattr(ctx, key, empty)


def filter_app_state(ctx, app_state):
    """E11 applies even when Context Lens UI is disabled; shadow remains byte-identical."""
    mode = mode_for(getattr(ctx, "config", None), ctx.workspace_id)
    if mode == "off":
        return app_state
    from . import capability_registry
    fields = {
        "context.page_summary": ("page", "resolvedReferences", "chips", "selectedEntity"),
        "context.screen_outline": ("screen", "screenOutline", "visibleState"),
        "context.memory_layers": ("memory", "memoryLayers", "style", "brand"),
        "context.attention": ("activeTask", "lastTask", "pendingApprovals", "attention", "conversationImages", "attachedThisTurn", "viewSelection"),
        "context.connections": ("connections", "connectionHealth"),
    }
    out = dict(app_state)
    used = set(getattr(ctx, "authz_used_capabilities", set()))
    for ident, keys in fields.items():
        decision = gate(ctx, capability_registry.get(ident), surface=capability_registry.surface("context", ident))
        if mode == "enforce" and decision.outcome != "allow":
            for key in keys:
                if key in out:
                    out[key] = [] if isinstance(out[key], list) else None
        elif mode == "enforce" and any(out.get(key) for key in keys):
            used.add(ident)
    if mode == "enforce":
        ctx.authz_used_capabilities = used
    return out if mode == "enforce" else app_state


def history_eligible(cur, ctx, role, body):
    """Exclude earlier derived prose after current consent narrows; never rewrite history."""
    if role != "assistant" or mode_for(getattr(ctx, "config", None), ctx.workspace_id) != "enforce":
        return True
    run_id = body.get("runId") or (body.get("siteAgent") or {}).get("runId")
    if not run_id:
        return getattr(getattr(ctx, "grants", None), "source", None) == "legacy"
    cur.execute("SELECT artifact->'trace'->'authz' FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text=%s", (ctx.workspace_id, run_id))
    row = cur.fetchone()
    provenance = row[0] if row else None
    if not isinstance(provenance, dict):
        return getattr(getattr(ctx, "grants", None), "source", None) == "legacy"
    from . import capability_registry
    for ident in provenance.get("capabilities") or []:
        cap = capability_registry.get(ident)
        surfaces = capability_registry.bindings(ident) if cap else ()
        if not cap or not surfaces or gate(ctx, cap, surface=surfaces[0]).outcome != "allow":
            return False
    return True


def trace_for(ctx):
    """Server-only provenance for the next request's revocation filter."""
    if mode_for(getattr(ctx, "config", None), ctx.workspace_id) != "enforce":
        return None
    from . import capability_registry
    used = set(getattr(ctx, "authz_used_capabilities", set()))
    for item in getattr(getattr(ctx, "ledger", None), "tool_activity", []):
        if item.get("status") == "verified" and capability_registry.get("tool." + str(item.get("tool", ""))):
            used.add("tool." + item["tool"])
    grants = getattr(ctx, "grants", None)
    return {"capabilities": sorted(used), "token": grants.token() if grants else "unavailable"}


def context_gate(capability_id: str, *, cur, state: dict, workspace_id: str,
                 principal: str, member, config, now: float) -> str:
    """CF-2 E11. Existing transaction only; diagnostics cannot change shadow output."""
    mode = mode_for(config, workspace_id)
    if mode == "off":
        return "allow"
    try:
        from . import agent_permissions, capability_registry
        policy = capability_registry.get(capability_id)
        binding = capability_registry.surface("context", capability_id)
        if policy is None or policy.kind != "context" or binding is None or cur is None:
            raise ValueError("context permission metadata unavailable")
        cap = _registry_capability(policy)
        grants = load_grants(cur, workspace_id, principal, now=now, mode=mode)
        decision = decide(cap, surface=Surface("context", capability_id, binding.legacy_confirmation),
                          member=member, grants=grants, state=state, actor=Actor("agent", principal, request_text=""), now=now)
        log.info(json.dumps({"event": "agent.authz.context", "mode": mode, "capabilityId": capability_id,
                             "wouldOutcome": decision.outcome, "wouldReason": decision.reason}))
        return "allow" if mode == "shadow" or decision.outcome == "allow" else "deny"
    except Exception as error:  # shadow is observational even when evaluation is unavailable
        log.info(json.dumps({"event": "agent.authz.context_error", "mode": mode, "capabilityId": capability_id,
                             "errorClass": type(error).__name__}))
        return "allow" if mode == "shadow" else "deny"


def mode_for(config, workspace_id) -> str:
    reader = getattr(config, "permissions_for", None)
    if not callable(reader):
        return "off"
    mode = reader(workspace_id)
    return mode if mode in MODES else "off"


@contextmanager
def in_tool():
    """Marks a tool executor's run: grant writes refuse inside it (PI-3)."""
    marker = IN_TOOL.set(True)
    try:
        yield
    finally:
        IN_TOOL.reset(marker)


def _log(event: str, decision: Decision, mode: str, ctx) -> None:
    log.info(json.dumps({"event": event, "outcome": decision.outcome, "wouldOutcome": decision.outcome if mode == "shadow" else None,
                         "reason": decision.reason, "capabilityId": decision.capability_id, "risk": decision.risk, "mode": mode,
                         "traceId": getattr(ctx, "trace_id", None), "runId": getattr(ctx, "run_id", None)}))


def evaluate_tool(ctx, spec, args: dict | None = None, *, agent: str | None = None) -> Decision:
    """The decision for one model tool call, read in its own short transaction (never the turn's)."""
    from . import agent_permissions
    cap = capability_for(spec)
    surface = tool_surface(spec, agent)
    now = ctx.now() if callable(getattr(ctx, "now", None)) else time.time()
    actor = getattr(ctx, "authz_actor", None) or Actor("agent", ctx.principal, request_text=ctx.request_text or "", evidence=getattr(ctx, "authz_evidence", None))
    service = ctx.service
    with service.repository.transaction(ctx.token, ctx.workspace_id) as (cur, row, principal):
        if principal != ctx.principal:
            return _d(cap, "deny", "membership_missing")
        member = service.ideas._member(row)
        state = service.ideas._state(row)
        grants = load_grants(cur, ctx.workspace_id, principal, now=now, mode=mode_for(ctx.config, ctx.workspace_id))
        view = provider_view_current(cur, state, ctx.workspace_id, now) if cap.provider_scopes else None
        return decide(cap, surface=surface, member=member, grants=grants, state=state, actor=actor, provider_view=view, target=args, now=now)


def tool_gate(ctx, tool, args, *, started: float, agent: str | None = None) -> dict | None:
    """CF-2 E1: the one permission hook in `tool_adapter.execute`, after the role check. None means "go on" — always in
    off and shadow mode. In enforce mode a refusal is the typed tool result the model must report."""
    spec = tool.spec
    if spec.tenant == "founder":
        return None                      # INV-7: founder capabilities keep rafii_control's own boundary
    mode = mode_for(getattr(ctx, "config", None), getattr(ctx, "workspace_id", None))
    if mode == "off":
        return None
    try:
        if mode == "enforce" and ctx.membership is None:
            decision = _d(capability_for(spec), "deny", "membership_missing")
        else:
            decision = evaluate_tool(ctx, spec, args, agent=agent)
    except AlphaError as error:
        if mode == "shadow":
            log.info(json.dumps({"event": "agent.authz.shadow_error", "status": error.status, "capabilityId": f"tool.{spec.name}",
                                 "traceId": getattr(ctx, "trace_id", None)}))
            return None
        decision = _d(capability_for(spec), "deny", "membership_missing" if error.status in (401, 403) else "feature_off")
    except Exception as error:  # noqa: BLE001 — shadow never changes behaviour; enforce fails closed
        log.error(json.dumps({"event": "agent.authz.error", "mode": mode, "errorClass": type(error).__name__, "capabilityId": f"tool.{spec.name}",
                              "traceId": getattr(ctx, "trace_id", None)}))
        if mode == "shadow":
            return None
        decision = _d(capability_for(spec), "deny", "feature_off")
    if decision.outcome != "allow" or decision.risk != "R0":
        _log("agent.authz.shadow" if mode == "shadow" else "agent.authz", decision, mode, ctx)
    if mode == "shadow" or decision.outcome == "allow":
        return None
    return _refusal(ctx, tool, args, decision, started)


DENY_MESSAGE = "Rafii isn't allowed to do this with your current permissions. You can change them in Settings → Rafii Agent."
CONFIRM_MESSAGE = "This needs your confirmation on screen before Rafii does it."
NATIVE_MESSAGE = "Rafii can only take you to the page where you do this yourself."


def _refusal(ctx, tool, args, decision: Decision, started: float) -> dict:
    spec = tool.spec
    if decision.outcome == "deny":
        result = {"ok": False, "code": "agent_permission_denied", "reason": decision.reason, "category": decision.category,
                  "settingsHref": SETTINGS_HREF, "error": DENY_MESSAGE}
        status = "blocked"
    elif decision.outcome == "step_up":
        result = {"ok": False, "needsUser": True, "code": "native_only", "href": SETTINGS_HREF, "reauth": {"maxAgeSeconds": R3_REAUTH_SECONDS},
                  "error": NATIVE_MESSAGE}
        status = "blocked"
    else:
        approval = None
        if APPROVAL_REQUESTER:
            approval = APPROVAL_REQUESTER[0](ctx, capability_for(spec), args, decision)
        result = {"ok": False, "needsUser": True, "code": "needs_confirmation", "approvalId": (approval or {}).get("approvalId"),
                  "summary": (approval or {}).get("summary") or tool.label, "expiresAt": (approval or {}).get("expiresAt"), "error": CONFIRM_MESSAGE}
        status = "blocked"
    ctx.activity(spec.name, tool.label, spec.effect, status, started, code=result["code"])
    return result


# --- the step seam for the task engine (CF-2 §8.4, X3) ---------------------------------------------------------------------
@dataclass(frozen=True)
class StepVerdict:
    verdict: str                         # 'allow' | 'approve' | 'step_up' | 'deny'
    approval_kind: str | None
    reason_code: str | None
    authz_reason: str
    token: str
    required_permission: str
    approver_policy: str
    requires_step_up: bool


_STEP_DENY = {"permissions_changed": "permission_revoked", "membership_missing": "member_inactive",
              "provider_not_connected": "provider_disconnected", "provider_reauth_required": "provider_disconnected",
              "provider_scope_missing": "provider_grant_missing", "provider_lane_mismatch": "provider_grant_missing",
              "provider_capability_unsupported": "provider_grant_missing", "explicit_request_required": "needs_input",
              "feature_off": "feature_unavailable", "cost_limit": "budget", "autopilot_limit": "budget", "native_only": "needs_input"}


def step_verdict(decision: Decision, *, earlier_token: str | None = None, spend_only: bool = False) -> StepVerdict:
    """CF-2 §8.4's frozen mapping. `earlier_token` is the authz_token the step was last allowed under; tokens are compared
    for equality only (`!=`), never ordered (correction 3)."""
    permission = "owner" if decision.risk == "R3" else "approve" if decision.required == "proposal" else "edit"
    common = dict(authz_reason=decision.reason, token=decision.token, required_permission=permission,
                  approver_policy="role_approve" if decision.required == "proposal" else "task_owner", requires_step_up=False)
    if decision.outcome == "allow":
        return StepVerdict("allow", None, None, **common)
    if decision.outcome == "confirm":
        return StepVerdict("approve", "spend" if spend_only else "agent_action", None, **common)
    if decision.outcome == "approve":
        return StepVerdict("approve", "proposal", None, **common)
    if decision.outcome == "step_up" and decision.reason == "needs_step_up":
        return StepVerdict("step_up", "step_up_action", None, **{**common, "requires_step_up": True})
    reason = _STEP_DENY.get(decision.reason)
    if reason is None:
        reason = "permission_revoked" if earlier_token and earlier_token != decision.token else "permission_missing"
    return StepVerdict("deny", None, reason, **common)


def _step_member(cur, workspace_id: str, principal: str):
    from ..permissions import Membership
    cur.execute("SELECT m.role,m.can_publish,m.can_reply,m.can_moderate,m.can_manage_connections FROM public.pr_memberships m "
                "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s "
                "AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, principal))
    row = cur.fetchone()
    return Membership.from_row(*row) if row else None


def _legacy_step_token(member) -> str:
    summary = member.summary() if member is not None else {"role": None}
    material = "legacy_v1|" + "|".join(f"{key}={summary[key]}" for key in sorted(summary))
    return hashlib.sha256(material.encode()).hexdigest()


def decide_for_step(cur, task: dict, step: dict, *, actor: Actor, now: float, config=None) -> StepVerdict:
    """CF-2/CF-3 claim seam. Use the existing transaction and trusted runtime config.

    The task creator's current grants apply, even when another person approves.
    Off/shadow preserve the legacy membership/role verdict and token byte for byte.
    Non-tool lifecycle rows retain their own engine checks; they grant no authority
    to a later tool or provider dispatch. No provider request occurs here.
    """
    from . import agent_permissions, capability_registry
    workspace_id, creator = task["workspaceId"], task["createdBy"]
    member = _step_member(cur, workspace_id, creator)
    legacy_token = _legacy_step_token(member)
    common = dict(token=legacy_token, required_permission="read", approver_policy="task_owner", requires_step_up=False)
    observer = (actor.kind == "cron" and step.get("kind") == "delegate" and step.get("observesExternal") is True
                and step.get("delegateType") in ("publish_job", "automation_item")
                and (task.get("cancelRequestedAt") is not None or member is None))
    if observer:
        return StepVerdict("observe", None, None, "allowed", **common)
    if member is None:
        return StepVerdict("deny", None, "member_inactive", "membership_missing", **common)
    mode = mode_for(config, workspace_id)
    if step.get("kind") != "tool":
        if step.get("kind") not in ("delegate", "wait", "approval", "model", "continuation"):
            return StepVerdict("deny", None, "feature_unavailable", "feature_off", **common)
        return StepVerdict("allow" if member.allows("read") else "deny", None,
                           None if member.allows("read") else "permission_missing", "allowed" if member.allows("read") else "role", **common)
    try:
        policy = capability_registry.get(step.get("capabilityId") or "")
        if policy is None:
            policy = capability_registry.for_tool(step.get("capabilityId") or "")
        if policy is None or policy.kind != "tool" or policy.tenant != "workspace":
            raise LookupError("step capability is not a workspace tool")
        cap = _registry_capability(policy)
        common["required_permission"] = cap.permission
        common["approver_policy"] = "role_approve" if cap.approval else "task_owner"
        legacy_result = StepVerdict("allow" if member.allows(cap.permission) else "deny", None,
                                   None if member.allows(cap.permission) else "permission_missing",
                                   "allowed" if member.allows(cap.permission) else "role", **common)
        if mode == "off":
            return legacy_result
        # A recorded surface must resolve exactly. Older steps use an existing tool
        # binding; no invented lower confirmation is substituted for a missing one.
        recorded = step.get("surface")
        if recorded:
            binding = capability_registry.surface(recorded, step.get("bindingRef") or cap.name)
        else:
            bindings = [b for b in capability_registry.bindings(cap.capability_id) if b.surface in ("manager", "specialist", "tool")]
            if not bindings:
                raise LookupError("step tool has no registered surface")
            binding = max(bindings, key=lambda b: CONFIRMATIONS.index(b.legacy_confirmation))
        cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
        row = cur.fetchone()
        if not row or not isinstance(row[0], dict):
            raise LookupError("workspace state unavailable")
        state = row[0]
        grants = load_grants(cur, workspace_id, creator, now=now, mode=mode)
        target = step.get("inputs") if isinstance(step.get("inputs"), dict) else None
        decision = decide(cap, surface=Surface(binding.surface, binding.binding_ref, binding.legacy_confirmation), member=member,
                          grants=grants, state=state, actor=Actor(actor.kind, creator, actor.request_text, actor.evidence),
                          provider_view=provider_view_current(cur, state, workspace_id, now) if cap.provider_scopes else None, target=target, now=now)
        result = step_verdict(decision, earlier_token=step.get("authzToken") or task.get("authzToken"),
                              spend_only=decision.outcome == "confirm" and cap.cost in SPEND.get(grants.spend_confirmation, ())
                              and cap.confirmation == "none" and binding.legacy_confirmation == "none")
        if mode == "shadow":
            log.info(json.dumps({"event": "agent.authz.shadow", "wouldOutcome": decision.outcome,
                                 "wouldRequired": decision.required, "wouldReason": decision.reason, "capabilityId": cap.capability_id}))
            return legacy_result
        return result
    except Exception as error:  # same legacy result in shadow; no contents or credentials in diagnostics
        log.error(json.dumps({"event": "agent.authz.step_error", "mode": mode, "errorClass": type(error).__name__}))
        if mode == "shadow" and "legacy_result" in locals():
            return legacy_result
        return StepVerdict("deny", None, "feature_unavailable", "feature_off", **common)


def token_changed(before: str | None, after: str | None) -> bool:
    """Whether the authorization basis moved. Equality only: a token is a digest, never a counter."""
    return (before or "") != (after or "")


# --- HTTP-facing errors, step-up and the human-only rule (CF-2 §10, §13, PI-3) -----------------------------------------------
class AuthzError(AlphaError):
    """An AlphaError whose body carries more than {error, code} (for example `current` or `stepUp`)."""

    def __init__(self, message, code, *, extra: dict | None = None):
        super().__init__(message, agent_error_codes.status(code), code=code)
        self.extra = dict(extra or {})

    def body(self) -> dict:
        return {"error": str(self), "code": self.code, **self.extra}


def step_up_required(reason: str, window: int = R3_REAUTH_SECONDS) -> AuthzError:
    return AuthzError("Sign in again to confirm this change.", "step_up_required",
                      extra={"stepUp": {"required": True, "reason": reason, "maxAgeSeconds": window}})


def human_only(token: str) -> None:
    """Grant writes come only from a person's own signed-in session: never inside a tool, never from an API token."""
    from ..api_tokens import is_api_token
    if IN_TOOL.get() or is_api_token(token):
        raise AuthzError("Only you can change Rafii's permissions, from your own signed-in session.", "agent_permissions_human_only")


def require_step_up(repository, token: str, principal: str, *, now: float, window: int = R3_REAUTH_SECONDS, reason: str = "agent_permissions") -> dict:
    """A sign-in verified within `window` seconds (CF-2 §10). The newest signed `amr` method time counts; a refreshed
    token's `iat` alone never does. Returns the proof stored on the receipt: {method, at, aal} — never a credential."""
    from ..api_tokens import is_api_token
    if is_api_token(token):
        raise step_up_required(reason, window)
    try:
        repository.assert_fresh(token, principal)
    except AlphaError as error:
        raise step_up_required(reason, window) from error
    verify = getattr(repository, "verify_session", None)
    reader = getattr(verify, "method_time", None)
    method, at = reader(token, principal) if callable(reader) else (None, 0)
    if not isinstance(at, (int, float)) or at <= 0 or now - at > window or at > now:
        raise step_up_required(reason, window)
    aal_reader = getattr(verify, "aal", None)
    aal = aal_reader(token, principal) if callable(aal_reader) else "aal1"
    return {"method": str(method or "unknown")[:40], "at": float(at), "aal": "aal2" if aal == "aal2" else "aal1"}
