"""Agent capability registry (rafii-agent-authz/1, CF-1): one authority for every tool and GenUI action.

Every capability an agent can reach is declared here once, with a stable id and version, what it reads and writes, its
risk class (R0-R3), its policy confirmation floor, cost, provider grants, limits, timeout/retry policy, evidence, and
verification and compensation behaviour:

- every `tool_adapter.REGISTRY` tool (the Manager's, the specialists', the coworker / trends / YouTube extensions', the
  adapted site-agent read and client tools, and the founder console's tools) -> `tool.<name>`;
- the grounded site agent's own catalog (`site_agent.tools.CATALOG`): each id maps to the adapted tool's capability, and
  the one proposal tool that has no runtime twin is `site.automation_patch_propose`;
- every GenUI action and query binding (`ui_domain.ACTIONS`/`QUERIES`): a binding that wraps an existing tool IS that
  tool's capability; otherwise `ui.action.<id>` / `ui.query.<name>`;
- the APP_STATE context sections (`context.*`) and the R3 actions Rafii may only navigate to (`NATIVE_ONLY`).

What each SURFACE asks today (correction 6) is not a property of the capability: the same `draft_edit` runs without a
dialog as a Manager tool and behind a native confirmation as a GenUI action. `SurfaceBinding.legacy_confirmation` holds it
per (surface, binding), and INV-10 makes every later decision `max(legacy_confirmation, decision)`.

Nothing here enforces anything, and nothing on a request path calls it in this release: the registry is read-only
metadata built lazily from the live registries. CF-2's gate (lane B1) and CF-3's engine (lane A2) consume it; the
permissions UI reads `public_catalogue()`. With their flags off, every surface keeps exactly today's behaviour, which the
golden test (`tests/test_agent_capability_registry.py`) pins capability by capability.

The classification of today's tools (CF-1 §7) lives in `TOOL_POLICY`, keyed by tool name, rather than as keyword
arguments at each registration site: the registering modules stay byte-identical (no conflict with the lanes editing
them), and `lint()` refuses a tool that is declared in neither place, or in both with different values.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import contracts
from .contracts import (CAPABILITY_KINDS, CONFIRMATIONS, DEFAULT_TIMEOUT_SECONDS, READ, R3_REAUTH_SECONDS, SURFACES, Limits, ProviderScope,
                        max_confirmation)

CONTRACT = "rafii-agent-authz/1"
REGISTRY_VERSION = 1
FOUNDER_TENANT = "founder"
AUTH_STATES = ("workspace_member", "founder_principal", "fresh_sign_in")
RESOURCE_SCOPES = ("workspace", "conversation", "person", "founder_console")
REGISTRY_ONLY_FIELDS = ("resource_scope", "feature_flag")     # TOOL_POLICY keys that are not ToolSpec fields

# --- CF-1 §7: classification of today's tools ---------------------------------------------------------------------------
_YT_READ = "https://www.googleapis.com/auth/youtube.readonly"            # = youtube.model.READ (asserted by the tests)
_YT_ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"  # = youtube.model.ANALYTICS
_WEEKLY, _BROKER = "RAFII_WEEKLY_OPERATOR_ENABLED", "RAFII_RESEARCH_BROKER_ENABLED"
_ENGAGE, _YOUTUBE = "RAFII_ENGAGEMENT_COPILOT_ENABLED", "POSTRIFF_YOUTUBE_CREATOR_ENABLED"


def _read(*grants, **extra) -> dict:
    return {"category": "read_analyze", "risk": "R0", "data_grants": tuple(grants), **extra}


def _nav(*grants, **extra) -> dict:
    return {"category": "navigate_interact", "risk": "R0", "data_grants": tuple(grants), **extra}


def _write(*grants, idempotency, retry_class, **extra) -> dict:
    return {"category": "create_edit", "risk": "R1", "data_grants": tuple(grants), "idempotency": idempotency, "retry_class": retry_class, **extra}


def _prepare(*grants, **extra) -> dict:
    return {"category": "execute_automations", "risk": "R2", "confirmation": "proposal", "data_grants": tuple(grants),
            "idempotency": "native_key", "retry_class": "manual", **extra}


_TREND_READS = ("trend_search", "trend_detail", "trend_receipt", "trend_examples", "trend_snapshots", "trend_methodology", "trend_calibration",
                "trend_language_patterns", "trend_genome", "trend_graph", "trend_saturation", "trend_whitespace", "trend_forecast",
                "trend_opportunities", "trend_opportunity", "trend_watches", "trend_lab_get")
_FOUNDER_READS = ("founder_metric_query", "founder_chart_explain", "founder_entity_lookup", "founder_entity_search", "founder_attention_list",
                  "founder_cost_breakdown", "founder_incident_read", "founder_source_health", "founder_navigate")

TOOL_POLICY: dict[str, dict] = {
    # help and navigation: public product content
    **{name: _read("public", background_eligible=True) for name in ("help_search", "help_get", "route_describe", "skills_list")},
    "ui_navigate": _nav("public"),
    "ui_show_help": _nav("public"),
    "ui_guide": _nav("public", client_requirement="guide"),
    # ui_voice is MUTATE_REVERSIBLE (tool_adapter._client_tool_overrides): it saves this person's own talking style
    "ui_voice": {"category": "navigate_interact", "risk": "R1", "data_grants": ("account",), "client_requirement": "voice",
                 "idempotency": "none", "retry_class": "never", "resource_scope": "person"},
    # the turn's own task plan and proposals
    **{name: _read("agent_activity", resource_scope="conversation") for name in ("task_plan", "task_update", "pending_approvals")},
    "proposal_apply": _prepare("content", "automations", resource_scope="conversation"),
    "schedule_propose": _prepare("content", "connections", autopilot_eligible=True),
    "automation_change_propose": _prepare("automations"),        # MUTATE_REVERSIBLE + approval => R2
    # drafting through the writing pipeline: its own 'text_model' reservation (ideas.py run reservation), writing-run key
    "draft_create": _write("content", "memory_brand", cost="text_credits", idempotency="native_key", retry_class="manual"),
    "draft_rewrite": _write("content", "memory_brand", cost="text_credits", idempotency="native_key", retry_class="manual"),
    # CF-3 now commits its receipt with the revisioned edit and restores through the same domain command.
    "draft_edit": _write("content", capability_version=2, idempotency="receipt_tx", retry_class="auto", compensation="inverse", inverse="tool.draft_edit"),
    "campaign_link": _write("campaigns", "content", idempotency="receipt_tx", retry_class="auto", compensation="inverse", inverse="tool.campaign_unlink"),
    "campaign_unlink": _write("campaigns", "content", idempotency="receipt_tx", retry_class="auto", compensation="inverse", inverse="tool.campaign_link"),
    # images: their own 'image_generation' reservation (creative.py); a duplicate reservation key returns the first call.
    # media_cloud is declared only where the executor refuses before any provider call (_consent_blocked): edit and
    # variant always send the parent image; generate sends one only with reference images, so it declares none.
    "image_generate": _write("content", cost="media_credits", idempotency="native_key", retry_class="manual"),
    "image_edit": _write("content", cost="media_credits", idempotency="native_key", retry_class="manual", consents=("media_cloud",)),
    "image_variant": _write("content", cost="media_credits", idempotency="native_key", retry_class="manual", consents=("media_cloud",)),
    "image_analyze": _read("content", consents=("media_cloud",)),
    "image_list": _read("content", resource_scope="conversation"),
    # memory: these executors FILTER private layers when cloud memory is off (memory_layers.cloud_allowed, overlays); they
    # never refuse, so no consent is declared (a declared consent would deny where today they answer). R0/#158 also
    # filters brand_summary/voice_profile through site_agent.reads._memory_allowed; filtering is not a consent refusal.
    **{name: _read("memory_brand") for name in ("memory_context", "memory_summary", "voice_check", "brand_summary", "voice_profile")},
    "overlay_context": _read("memory_brand", feature_flag="RAFII_ADAPTIVE_SKILLS_ENABLED"),
    # the web: web_research refuses unless research.allowed(state); the broker tools also have providers (MCP connector,
    # local desktop) whose readiness is not research.allowed, so they declare none
    "web_research": _read("web", consents=("research_web",)),
    "research_search": _read("web", feature_flag=_BROKER),
    "research_fetch": _read("web", feature_flag=_BROKER),
    "source_normalize": _read("web", feature_flag=_WEEKLY),
    "weather_now": _read("web"),
    # library: per-source cloud consent stays in the executor (site_agent/library_reads.py)
    "library_search": _read("library"),
    "library_read": _read("library"),
    "channels_capabilities": _read("connections"),
    **{name: _read("content") for name in ("queue_summary", "job_get", "draft_get", "calendar_range", "reviews_list", "publishing_summary",
                                           "content_search", "entity_status", "workspace_summary", "workspace_search", "attention_summary",
                                           "attention_summary_v2")},
    **{name: _read("automations") for name in ("automation_list", "automation_get", "automation_explain")},
    **{name: _read("campaigns", "content") for name in ("campaign_list", "campaign_get", "campaign_items", "campaign_membership", "relationships",
                                                        "record_attribution")},
    "member_activity": _read("members"),
    "notification_list": _read("notifications", resource_scope="person"),
    "entitlements_summary": _read("usage_billing"),
    "privacy_egress_state": _read("account"),
    "models_summary": _read("account"),
    # coworker extension
    "weekly_plan_get": _read("content", feature_flag=_WEEKLY),
    "strategy_context": _read("content", feature_flag="RAFII_PERFORMANCE_LEARNING_ENABLED"),
    "creative_plan": _read("content", feature_flag="RAFII_CREATIVE_AGENT_ENABLED"),
    "engagement_triage": _read("content", "connections", feature_flag=_ENGAGE),
    # writer runs started by the coworker service: ideas.turn in coworker/service.py (weekly slots, source campaigns) and
    # reply_writer's own 'text_model' reservation, so each is text_credits (CF-1 §7 listed the last two as free; the
    # §7 rule "confirmed by locating a ledger.reserve( call" decides)
    "weekly_plan_prepare": _write("content", cost="text_credits", idempotency="none", retry_class="never", feature_flag=_WEEKLY),
    "engagement_draft_create": _write("content", cost="text_credits", idempotency="none", retry_class="never", feature_flag=_ENGAGE),
    # content-addressed record: the same source and brief answer with the existing campaign
    "source_campaign_create": _write("content", "campaigns", cost="text_credits", idempotency="native_key", retry_class="manual"),
    # growth: stored trend receipts only
    **{name: _read("growth_trends") for name in _TREND_READS},
    "trend_opportunity_accept": _write("growth_trends", idempotency="native_key", retry_class="auto"),
    "trend_lab_check": _write("growth_trends", idempotency="native_key", retry_class="auto"),
    "trend_watch_create": _write("growth_trends", idempotency="native_key", retry_class="auto", compensation="inverse", inverse="tool.trend_watch_disable"),
    "trend_watch_disable": _write("growth_trends", idempotency="native_key", retry_class="auto", compensation="inverse", inverse="tool.trend_watch_create"),
    # YouTube: only the current human message can ask for these (the executors refuse otherwise, youtube/agent_tools.py)
    "youtube_plan_context": _read("content", "connections", explicit_request=True, feature_flag=_YOUTUBE),
    "youtube_recommendations": _read("content", "connections", explicit_request=True, feature_flag=_YOUTUBE),
    "youtube_plan_prepare": _write("content", "connections", idempotency="none", retry_class="never", explicit_request=True, feature_flag=_YOUTUBE),
    "youtube_analytics_summary": _read("analytics", "connections", explicit_request=True, feature_flag=_YOUTUBE,
                                       provider_scopes=(ProviderScope("YouTube", (_YT_READ, _YT_ANALYTICS), lane="agentic", capability="analytics"),)),
    # founder console (tenant 'founder'): consumer grants never apply (INV-7); rafii_control Boundary.authorize decides
    **{name: {"data_grants": (), "resource_scope": "founder_console"} for name in _FOUNDER_READS},
    "founder_draft_message": {"data_grants": (), "idempotency": "none", "retry_class": "never", "resource_scope": "founder_console"},
    "founder_reminder_prepare": {"data_grants": (), "idempotency": "native_key", "retry_class": "manual", "resource_scope": "founder_console"},
    "founder_report_prepare": {"data_grants": (), "idempotency": "native_key", "retry_class": "manual", "resource_scope": "founder_console"},
    "founder_incident_ack": {"data_grants": (), "idempotency": "none", "retry_class": "never", "resource_scope": "founder_console"},
}

# Executors that refuse BEFORE any work when the consent is off (the only places `consents` may be declared; correction 22).
VERIFIED_CONSENT_PRECHECKS = {
    "tool.image_analyze": ("media_cloud",),      # creative.py image_analyze -> _consent_blocked(..., "vision", ...)
    "tool.image_edit": ("media_cloud",),         # creative.py _generate -> parent image -> _consent_blocked(..., "image", ...)
    "tool.image_variant": ("media_cloud",),      # same path as image_edit
    "tool.web_research": ("research_web",),      # specialists.py web_research -> research.allowed(state) else research_off
}

# --- the grounded site agent's own catalog --------------------------------------------------------------------------------
# automation.patch_propose has no runtime twin (the runtime uses automation_change_propose); CF-2 E3 names it.
SITE_ONLY = {
    "automation.patch_propose": {"capability_id": "site.automation_patch_propose", "category": "execute_automations", "risk": "R2",
                                 "confirmation": "proposal", "data_grants": ("automations",), "idempotency": "native_key", "retry_class": "manual",
                                 "effect": contracts.MUTATE_REVERSIBLE, "approval": True},
}
# The grounded agent's own proposal flows (site_agent/service.py, compound.py) that are not catalog tools.
SITE_PROPOSALS = {"proposals.build_schedule": "tool.schedule_propose", "proposals.build": "tool.automation_change_propose"}

# --- GenUI bindings (CF-1 §8). A binding that wraps a tool is that tool's capability; these are the others. -------------
GENUI_ACTION_POLICY = {
    "campaign_create": {"category": "create_edit", "risk": "R1", "data_grants": ("campaigns",)},
    "campaign_update": {"category": "create_edit", "risk": "R1", "data_grants": ("campaigns",)},
    "library_use_as_source": {"category": "create_edit", "risk": "R1", "data_grants": ("library",)},
    "research_save_sources": {"category": "create_edit", "risk": "R1", "data_grants": ("web",)},
    "voice_samples_import": {"category": "create_edit", "risk": "R1", "data_grants": ("memory_brand",)},
    "voice_profile_analyze_local": {"category": "create_edit", "risk": "R1", "data_grants": ("memory_brand",)},
    "voice_sample_select": {"category": "create_edit", "risk": "R1", "data_grants": ("memory_brand",)},
    "voice_sample_exclude": {"category": "create_edit", "risk": "R1", "data_grants": ("memory_brand",)},
    # consent-type owner decisions stay R2 with a native confirmation (DP-5, decided)
    "voice_sample_grant": {"category": "manage_settings", "risk": "R2", "confirmation": "native", "data_grants": ("memory_brand",)},
    "voice_profile_approve": {"category": "manage_settings", "risk": "R2", "confirmation": "native", "data_grants": ("memory_brand",)},
    "preference_decide": {"category": "manage_settings", "risk": "R2", "confirmation": "native", "data_grants": ("memory_brand",)},
    "voice_profile_analyze_ai": {"category": "create_edit", "risk": "R1", "cost": "text_credits", "data_grants": ("memory_brand",)},
}
# How the GenUI action path makes a replay safe today (ui_domain.DEDUPE): `intent` returns the first stored pr_ui_actions
# receipt, `natural` commands are idempotent in the domain, `cas` refuses a second effect through the revision guard.
_DEDUPE_IDEMPOTENCY = {"intent": "receipt_tx", "natural": "native_key", "cas": "none"}
JOURNEY_DOMAINS = {"J01": ("content",), "J02": ("content",), "J03": ("library",), "J04": ("memory_brand",), "J05": ("campaigns",),
                   "J06": ("analytics",), "J07": ("web",), "J08": ("automations", "connections"), "J09": ()}

# --- CF-1 §10: APP_STATE context sections and R3 native-only actions -----------------------------------------------------
CONTEXT_CAPABILITIES = {
    "context.page_summary": ("public",),
    "context.screen_outline": ("screen",),
    "context.memory_layers": ("memory_brand",),
    "context.attention": ("content",),
    "context.connections": ("connections",),
}
# id: (route_id, permission, category, effect, data_grants)
NATIVE_ONLY = {
    "connections.connect": ("channels", "manage_connections", "manage_connected_services", "EXTERNAL_EFFECT", ("connections",)),
    "connections.disconnect": ("channels", "manage_connections", "manage_connected_services", "DESTRUCTIVE", ("connections",)),
    "consent.memory_egress": ("memory", "owner", "manage_settings", "MUTATE_REVERSIBLE", ("memory_brand",)),
    "consent.media_egress": ("memory", "owner", "manage_settings", "MUTATE_REVERSIBLE", ("library",)),
    "consent.research_egress": ("privacy", "owner", "manage_settings", "MUTATE_REVERSIBLE", ("web",)),
    "consent.connector_egress": ("api", "owner", "manage_settings", "MUTATE_REVERSIBLE", ("connections",)),
    "billing.checkout": ("billing", "owner", "manage_settings", "EXTERNAL_EFFECT", ("usage_billing",)),
    "members.manage": ("members", "manage_members", "manage_settings", "DESTRUCTIVE", ("members",)),
    "security.sessions_mfa": ("profile", "read", "manage_settings", "SECRET", ("account",)),
    "security.api_tokens": ("api", "manage_connections", "manage_settings", "SECRET", ("account",)),
    "account.delete": ("privacy", "read", "manage_settings", "DESTRUCTIVE", ("account",)),
    "publish.approve": ("queue", "approve", "execute_automations", "EXTERNAL_EFFECT", ("content", "connections")),
    "automations.auto_publish_authority": ("automations", "owner", "execute_automations", "EXTERNAL_EFFECT", ("automations",)),
    "library.delete": ("library", "edit", "create_edit", "DESTRUCTIVE", ("library",)),
}

# CF-1 §13 (correction 5): what only an explicit Recommended / Full / Custom choice adds to the Manager. draft_edit is
# already in manager.MANAGER_TOOLS at de4e5907, so in effect the expansion adds the campaign link pair.
MANAGER_EXPANSION_V1 = frozenset({"tool.campaign_link", "tool.campaign_unlink", "tool.draft_edit"})
EXPANSION_PRESETS = ("recommended", "full", "custom")

# The result every tool returns through tool_adapter.execute (the per-tool `data` is the tool's own and untrusted).
TOOL_RESULT_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "verified": {"type": "boolean"}, "code": {"type": "string"},
                                                       "error": {"type": "string"}, "needsUser": {"type": "boolean"}, "data": {}},
                      "note": "tool_adapter.execute result envelope; tool output reaches models as untrusted TOOL_RESULT data"}
UI_RECEIPT_SCHEMA = {"type": "object", "properties": {k: {} for k in ("outcome", "verified", "receiptRef", "proposalRef", "changedRefs",
                                                                     "invalidationKeys", "nextContext", "message")},
                     "note": "ui_domain.Receipt, stored in pr_ui_actions; verified comes from the executor's own re-read"}
_COPY_PATH = Path(__file__).with_name("capability_copy.json")
_ROUTES_PATH = Path(__file__).resolve().parent.parent / "site_agent" / "route_manifest.json"
_PERMISSION_WRITERS = ("apply_decision", "revoke", "remind", "bump_workspace", "on_membership_ended", "erase_workspace", "consent_effect")


@dataclass(frozen=True)
class CapabilitySpec:
    """One capability, as decide() (CF-2) and the engine (CF-3) read it. `confirmation` is the POLICY floor; what a
    surface asks today is SurfaceBinding.legacy_confirmation."""
    capability_id: str
    version: int
    kind: str                       # CAPABILITY_KINDS
    name: str                       # tool name | actionId | query name | context key | native id
    label: str
    category: str
    risk: str
    confirmation: str
    permission: str                 # permissions.CLASSES requirement, re-checked by the surface at execution
    tenant: str                     # 'workspace' | 'founder'
    effect: str
    approval: bool
    cost: str
    paid: bool
    data_grants: tuple | None       # None = undeclared (lint)
    consents: tuple
    provider_scopes: tuple
    limits: Limits
    timeout_seconds: float
    idempotency: str
    retry_class: str
    max_attempts: int
    background_eligible: bool
    evidence: str
    verification: str
    compensation: str
    inverse: str | None
    autopilot_eligible: bool
    explicit_request: bool
    client_requirement: str | None
    since: int
    route_id: str | None
    feature_flag: str | None
    reauth_seconds: int | None
    # --- what the task asks the registry to carry besides decide()'s inputs -------------------------------------------
    description: str = ""           # developer/model-facing text; never in public_catalogue
    auth_state: str = "workspace_member"      # AUTH_STATES: what must be true of the caller before the surface runs it
    resource_scope: str = "workspace"         # RESOURCE_SCOPES: the narrowest boundary its executor works inside
    input_schema: dict | None = None
    output_schema: dict | None = None
    audit: str | None = None
    voice: bool = True
    idempotent: bool = True
    declared: tuple = ()            # which policy fields were declared (TOOL_POLICY / inline / binding), not derived

    def __post_init__(self):
        name = self.capability_id
        if self.kind not in CAPABILITY_KINDS or self.auth_state not in AUTH_STATES or self.resource_scope not in RESOURCE_SCOPES:
            raise ValueError(f"{name}: bad kind/auth_state/resource_scope")
        if self.effect not in contracts.EFFECTS or (self.kind != "native_only" and self.effect in contracts.FORBIDDEN_EFFECTS):
            raise ValueError(f"{name}: an executable capability never has a forbidden effect (INV-5)")
        contracts.check_policy_values(name, {k: getattr(self, k) for k in ("category", "risk", "confirmation", "cost", "idempotency", "retry_class",
                                                                           "evidence", "verification", "compensation", "data_grants", "consents",
                                                                           "provider_scopes", "limits", "timeout_seconds", "max_attempts")}
                                      | {"capability_version": self.version, "since": self.since})
        if self.kind == "native_only":
            if self.risk != "R3" or self.confirmation != "approval_step_up" or self.reauth_seconds != R3_REAUTH_SECONDS or not self.route_id:
                raise ValueError(f"{name}: native-only capabilities are R3, step-up, re-auth {R3_REAUTH_SECONDS}s, with a route")
            return
        contracts.check_policy_combination(name, {k: getattr(self, k) for k in ("risk", "confirmation", "inverse", "autopilot_eligible",
                                                                                "background_eligible", "idempotency", "retry_class", "compensation")},
                                           self.effect)
        if self.paid != (self.cost != "free"):
            raise ValueError(f"{name}: paid is derived from cost")


@dataclass(frozen=True)
class SurfaceBinding:
    """How one surface reaches one capability today (correction 6). `legacy_confirmation` is the ONLY source of what that
    surface asks today; INV-10: required = max(legacy_confirmation, decision.required). The limits and timeout are the
    ones the surface itself applies today (no per-capability limit exists yet)."""
    surface: str                                 # SURFACES
    capability_id: str
    legacy_confirmation: str                     # CONFIRMATIONS
    binding_ref: str                             # tool name, site tool id, actionId, query name or context key
    legacy_limits: Limits = Limits()
    legacy_timeout_seconds: float | None = None  # a timeout the surface enforces per call today, or None

    def __post_init__(self):
        if self.surface not in SURFACES or self.legacy_confirmation not in CONFIRMATIONS:
            raise ValueError(f"bad surface binding {self.surface}:{self.binding_ref}")

    def required(self, decided: str = "none") -> str:
        """INV-10 at an enforcement point: never below what this surface asks today."""
        return max_confirmation(self.legacy_confirmation, decided)


@dataclass(frozen=True)
class _Built:
    caps: dict
    bindings: dict                               # (surface, binding_ref) -> SurfaceBinding
    problems: tuple                              # build-time lint findings
    baseline: frozenset


_CACHE: dict = {"key": None, "built": None}


# --- building ----------------------------------------------------------------------------------------------------------
def from_tool(spec, tool=None) -> CapabilitySpec:
    """A ToolSpec (and, when given, its registered Tool) as a CapabilitySpec: CF-1 §4 defaults, TOOL_POLICY[name], then the
    spec's own inline fields. Pure; never reads the cached registry."""
    table = dict(TOOL_POLICY.get(spec.name) or {})
    extra = {k: table.pop(k) for k in REGISTRY_ONLY_FIELDS if k in table}
    policy = contracts.derive_policy(spec, table)
    founder = spec.tenant == FOUNDER_TENANT
    return CapabilitySpec(
        capability_id=policy["capability_id"], version=policy["capability_version"], kind="tool", name=spec.name,
        label=(tool.label if tool is not None else spec.name), category=policy["category"], risk=policy["risk"], confirmation=policy["confirmation"],
        permission=spec.permission, tenant=spec.tenant, effect=spec.effect, approval=bool(spec.approval), cost=policy["cost"], paid=policy["paid"],
        data_grants=policy["data_grants"], consents=tuple(policy["consents"]), provider_scopes=tuple(policy["provider_scopes"]), limits=policy["limits"],
        timeout_seconds=float(policy["timeout_seconds"]), idempotency=policy["idempotency"], retry_class=policy["retry_class"],
        max_attempts=policy["max_attempts"], background_eligible=bool(policy["background_eligible"]), evidence=policy["evidence"],
        verification=policy["verification"], compensation=policy["compensation"], inverse=policy["inverse"],
        autopilot_eligible=bool(policy["autopilot_eligible"]), explicit_request=bool(policy["explicit_request"]),
        client_requirement=policy["client_requirement"], since=policy["since"], route_id=None, feature_flag=extra.get("feature_flag"),
        reauth_seconds=None, description=spec.description, auth_state="founder_principal" if founder else "workspace_member",
        resource_scope=extra.get("resource_scope") or ("founder_console" if founder else "workspace"),
        input_schema=(tool.schema if tool is not None else None), output_schema=TOOL_RESULT_SCHEMA, audit=spec.audit, voice=bool(spec.voice),
        idempotent=bool(spec.idempotent), declared=policy["declared"])


def _site_only(tool_id: str, definition: dict, label: str) -> CapabilitySpec:
    from ..site_agent import tools as site_tools
    entry = dict(SITE_ONLY[tool_id])
    effect, approval = entry.pop("effect"), entry.pop("approval")
    probe = contracts.ToolSpec(name=tool_id.replace(".", "_"), effect=effect, permission=site_tools.REQUIREMENT.get(tool_id, "read"),
                               description=definition["purpose"], approval=approval, idempotent=False)
    policy = contracts.derive_policy(probe, entry)
    return CapabilitySpec(
        capability_id=policy["capability_id"], version=1, kind="tool", name=tool_id, label=label, category=policy["category"], risk=policy["risk"],
        confirmation=policy["confirmation"], permission=probe.permission, tenant="workspace", effect=effect, approval=approval, cost=policy["cost"],
        paid=policy["paid"], data_grants=policy["data_grants"], consents=(), provider_scopes=(), limits=Limits(), timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        idempotency=policy["idempotency"], retry_class=policy["retry_class"], max_attempts=policy["max_attempts"], background_eligible=False,
        evidence=policy["evidence"], verification=policy["verification"], compensation=policy["compensation"], inverse=None, autopilot_eligible=False,
        explicit_request=False, client_requirement=None, since=1, route_id=None, feature_flag=None, reauth_seconds=None,
        description=definition["purpose"], input_schema=definition["input"], output_schema=TOOL_RESULT_SCHEMA, idempotent=False,
        declared=policy["declared"])


def _ui_cap(kind: str, binding, policy: dict) -> CapabilitySpec:
    """A GenUI binding with no tool of its own. Effect, requirement and confirmation come from the binding as registered."""
    action = kind == "ui_action"
    name = binding.action_id if action else binding.name
    effect = binding.effect if action else READ
    probe = contracts.ToolSpec(name=name, effect=effect, permission=binding.requirement, description=(binding.summary if action else binding.description),
                               approval=False)
    table = dict(policy)
    if action:
        table.setdefault("idempotency", _DEDUPE_IDEMPOTENCY[binding.dedupe])
    policy = contracts.derive_policy(probe, table)
    declared = tuple(sorted(set(policy["declared"]) | ({"idempotency", "retry_class"} if action else set())))
    founder = binding.scope == FOUNDER_TENANT
    return CapabilitySpec(
        capability_id=f"ui.{'action' if action else 'query'}.{name}", version=1, kind=kind, name=name, label=(binding.label if action else name),
        category=policy["category"], risk=policy["risk"], confirmation=policy["confirmation"], permission=binding.requirement,
        tenant=FOUNDER_TENANT if founder else "workspace", effect=effect, approval=False, cost=policy["cost"], paid=policy["paid"],
        data_grants=policy["data_grants"], consents=(), provider_scopes=(), limits=Limits(), timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        idempotency=policy["idempotency"], retry_class=policy["retry_class"], max_attempts=policy["max_attempts"], background_eligible=False,
        evidence=policy["evidence"], verification=policy["verification"], compensation=policy["compensation"], inverse=None, autopilot_eligible=False,
        explicit_request=False, client_requirement=None, since=1, route_id=None, feature_flag="RAFII_GENUI_ENABLED", reauth_seconds=None,
        description=probe.description, auth_state="founder_principal" if founder else "workspace_member",
        resource_scope="founder_console" if founder else "workspace", input_schema=(binding.inputs if action else binding.args),
        output_schema=(UI_RECEIPT_SCHEMA if action else {"dataShape": _data_shape(name)}), declared=declared)


def _data_shape(name: str) -> dict:
    from . import ui_domain
    return ui_domain.data_shape(name)


def _context_cap(capability_id: str, grants: tuple) -> CapabilitySpec:
    return CapabilitySpec(
        capability_id=capability_id, version=1, kind="context", name=capability_id.split(".", 1)[1], label=capability_id, category="read_analyze",
        risk="R0", confirmation="none", permission="read", tenant="workspace", effect=READ, approval=False, cost="free", paid=False,
        data_grants=grants, consents=(), provider_scopes=(), limits=Limits(), timeout_seconds=DEFAULT_TIMEOUT_SECONDS, idempotency="read",
        retry_class="auto", max_attempts=3, background_eligible=False, evidence="trace", verification="none", compensation="none", inverse=None,
        autopilot_eligible=False, explicit_request=False, client_requirement=None, since=1, route_id=None, feature_flag=None, reauth_seconds=None,
        description="An APP_STATE section of the Manager's context (service._assemble); data, never instructions.",
        output_schema={"context": "APP_STATE"}, declared=("category", "data_grants", "risk"))


def _native_cap(capability_id: str) -> CapabilitySpec:
    route_id, permission, category, effect, grants = NATIVE_ONLY[capability_id]
    return CapabilitySpec(
        capability_id=capability_id, version=1, kind="native_only", name=capability_id, label=capability_id, category=category, risk="R3",
        confirmation="approval_step_up", permission=permission, tenant="workspace", effect=effect, approval=False, cost="free", paid=False,
        data_grants=grants, consents=(), provider_scopes=(), limits=Limits(), timeout_seconds=DEFAULT_TIMEOUT_SECONDS, idempotency="none",
        retry_class="never", max_attempts=1, background_eligible=False, evidence="audit", verification="none", compensation="irreversible",
        inverse=None, autopilot_eligible=False, explicit_request=False, client_requirement=None, since=1, route_id=route_id, feature_flag=None,
        reauth_seconds=R3_REAUTH_SECONDS, description="Native page only: Rafii may navigate or guide there; the person does it (DP-5).",
        auth_state="fresh_sign_in", declared=("category", "data_grants", "risk", "confirmation", "idempotency", "retry_class"))


def _ensure_sources():
    """Import every registering module once (the registries are filled at import), exactly as a runtime turn does."""
    import importlib

    from . import domain_tools, ui_domain  # noqa: F401 — ui_domain.load() registers the GenUI bindings
    domain_tools.ensure_registered()
    try:
        importlib.import_module("rafii_control.founder_tools")   # as ui_domain/founder.py does on first use; tenant 'founder'
    except ImportError:
        pass


def _cache_key():
    from ..site_agent import tools as site_tools
    from . import manager, specialists, tool_adapter, ui_domain
    return (tuple((name, id(tool)) for name, tool in tool_adapter.REGISTRY.items()),
            tuple((name, id(b)) for name, b in ui_domain.ACTIONS.items()), tuple((name, id(b)) for name, b in ui_domain.QUERIES.items()),
            tuple((name, id(value)) for name, value in site_tools.CATALOG.items()), tuple(manager.MANAGER_TOOLS),
            tuple((k, tuple(v["tools"])) for k, v in specialists.SPECIALISTS.items()),
            tuple((k, tuple(v)) for k, v in specialists.EXTRA_SCOPES.items()))


def _tool_cap_id(tool_name: str | None) -> str | None:
    """The capability of a binding's `tool`: an agent tool name or a site tool id (adapted to its runtime name). A tool's
    id is `tool.<name>` unless its ToolSpec or TOOL_POLICY entry declares another `capability_id`."""
    from . import tool_adapter
    if not tool_name:
        return None
    if "." in tool_name:
        if tool_name in SITE_ONLY:
            return SITE_ONLY[tool_name]["capability_id"]
        tool_name = tool_adapter.site_tool_name(tool_name)
        if not tool_name:
            return None
    tool = tool_adapter.REGISTRY.get(tool_name)
    declared = (tool.spec.capability_id if tool is not None else None) or (TOOL_POLICY.get(tool_name) or {}).get("capability_id")
    return declared or f"tool.{tool_name}"


def site_capability(tool_id: str) -> str:
    """CF-1 §5.1 frozen site id rule; unknown catalogue ids fail closed. Pure metadata, never dispatches a tool.

    An adapted catalogue entry shares tool.<dotted_id_with_underscores>; an unadapted entry uses site.<...>. Lint checks
    that each adapter is the exact _site_executor(id), rather than accepting a coincidentally named tool as equivalent.
    """
    from ..site_agent import tools as site_tools
    from . import tool_adapter
    if tool_id not in site_tools.CATALOG:
        raise LookupError(f"unknown site tool {tool_id!r}")
    name = tool_id.replace(".", "_")
    adapted = tool_adapter.site_tool_name(tool_id)
    return f"tool.{name}" if adapted == name and name in tool_adapter.REGISTRY else f"site.{name}"


def _commands_direct() -> list[str]:
    """Tools commands.direct dispatches without a model (read from its source, so a new direct command cannot hide)."""
    from . import commands
    return sorted(set(re.findall(r'REGISTRY\["([a-z][a-z0-9_]*)"\]', inspect.getsource(commands))))


def _build() -> _Built:
    from ..site_agent import tools as site_tools
    from . import manager, specialists, tool_adapter, ui_actions, ui_domain, ui_queries
    caps: dict[str, CapabilitySpec] = {}
    problems: list[str] = []

    def add(cap):
        if cap.capability_id in caps and caps[cap.capability_id] != cap:
            problems.append(f"{cap.capability_id}: declared twice with different policies")
            return
        caps[cap.capability_id] = cap

    for name, tool in tool_adapter.REGISTRY.items():
        try:
            add(from_tool(tool.spec, tool))
        except ValueError as error:
            problems.append(f"tool.{name}: {error}")
    for tool_id, definition in site_tools.CATALOG.items():
        if tool_id in SITE_ONLY:
            add(_site_only(tool_id, definition, site_tools.LABELS.get(tool_id, tool_id)))
    for action_id, binding in ui_domain.ACTIONS.items():
        if binding.tool:
            continue
        if action_id not in GENUI_ACTION_POLICY:
            problems.append(f"ui.action.{action_id}: no declaration in GENUI_ACTION_POLICY")
            continue
        add(_ui_cap("ui_action", binding, GENUI_ACTION_POLICY[action_id]))
    for name, binding in ui_domain.QUERIES.items():
        if binding.tool:
            continue
        add(_ui_cap("ui_query", binding, {"category": "read_analyze", "risk": "R0", "data_grants": JOURNEY_DOMAINS[binding.journey]}))
    for capability_id, grants in CONTEXT_CAPABILITIES.items():
        add(_context_cap(capability_id, grants))
    for capability_id in NATIVE_ONLY:
        add(_native_cap(capability_id))

    bindings: dict[tuple, SurfaceBinding] = {}

    def bind(surface, binding_ref, capability_id, legacy, limits=Limits(), timeout=None):
        if capability_id not in caps:
            problems.append(f"{surface}:{binding_ref}: reaches {capability_id}, which has no registry entry")
            return
        bindings[(surface, binding_ref)] = SurfaceBinding(surface, capability_id, legacy, binding_ref, limits, timeout)

    def tool_legacy(name):
        return "proposal" if tool_adapter.REGISTRY[name].spec.approval else "none"

    # Model tool calls through tool_adapter.execute: the FunctionTool timeout, and a proposal for approval tools.
    from .task_engine.tools import ENGINE_TOOLS
    for name in sorted(ENGINE_TOOLS):
        bind('task_engine', name, _tool_cap_id(name), 'none', timeout=tool_adapter.REGISTRY[name].spec.timeout_seconds)
    for name in specialists.available(manager.MANAGER_TOOLS + specialists.EXTRA_SCOPES.get("rafii_manager", [])):
        bind("manager", name, _tool_cap_id(name), tool_legacy(name), timeout=tool_adapter.REGISTRY[name].spec.timeout_seconds)
    # PR152's opt-in metadata tool is reachable only through the Manager's per-workspace flag.
    # Its since-2 declaration prevents it joining the immutable legacy grant baseline.
    if "library_browse" in tool_adapter.REGISTRY:
        bind("manager", "library_browse", "tool.library_browse", "none", timeout=tool_adapter.REGISTRY["library_browse"].spec.timeout_seconds)
    for key, spec in specialists.SPECIALISTS.items():
        for name in specialists.available(list(spec["tools"]) + specialists.EXTRA_SCOPES.get(key, [])):
            bind("specialist", name, _tool_cap_id(name), tool_legacy(name), timeout=tool_adapter.REGISTRY[name].spec.timeout_seconds)
    for name in _commands_direct():
        if name in tool_adapter.REGISTRY:
            bind("commands_direct", name, _tool_cap_id(name), tool_legacy(name))
    # The grounded site agent: its catalog (at most MAX_TOOLS_PER_TURN tools per turn) and its own proposal flows.
    site_turn = Limits(per_turn=site_tools.MAX_TOOLS_PER_TURN)
    for tool_id, definition in site_tools.CATALOG.items():
        capability_id = site_capability(tool_id)
        bind("site_agent", tool_id, capability_id, "proposal" if definition["effect"] == "workspace_mutation" else "none", site_turn)
    for ref, capability_id in SITE_PROPOSALS.items():
        bind("site_agent", ref, capability_id, "proposal")
    # GenUI: native confirmation when the binding asks for it, a proposal when it only prepares; per-artifact throttles.
    for action_id, binding in ui_domain.ACTIONS.items():
        legacy = "proposal" if binding.prepare_only else ("native" if binding.requires_confirmation else "none")
        bind("genui_action", action_id, _tool_cap_id(binding.tool) or f"ui.action.{action_id}", legacy,
             Limits(per_minute=ui_actions.ACTIVATIONS_PER_MINUTE))
    for name, binding in ui_domain.QUERIES.items():
        bind("genui_query", name, _tool_cap_id(binding.tool) or f"ui.query.{name}", "none", Limits(per_minute=ui_queries.QUERY_LIMIT_PER_MINUTE))
    for capability_id in CONTEXT_CAPABILITIES:
        bind("context", capability_id, capability_id, "none")

    # The freeze covers every consumer capability of every executable/context kind, not merely a reachability subset.
    # Founder capabilities bypass consumer grants; native-only navigation is decided before the legacy baseline check.
    baseline = frozenset(c for c, cap in caps.items() if cap.tenant != FOUNDER_TENANT and cap.since == 1 and cap.kind != "native_only")
    return _Built(caps, bindings, tuple(problems), baseline)


def ensure() -> dict[str, CapabilitySpec]:
    """Every capability, built lazily from the live registries and cached by what is registered (tests reset them)."""
    return _built().caps


def _built() -> _Built:
    """Cached by what is registered. The registering imports run again only when that changed (or on first use), so a
    hot-path lookup costs one pass over the registry names."""
    if _CACHE["built"] is not None and _CACHE["key"] == _cache_key():
        return _CACHE["built"]
    _ensure_sources()
    key = _cache_key()
    _CACHE["built"] = _build()
    _CACHE["key"] = key
    return _CACHE["built"]


# --- lookups (fail closed: an unknown id is never a capability; INV-2) ------------------------------------------------
def get(capability_id: str) -> CapabilitySpec | None:
    return ensure().get(capability_id)


def _require(capability_id: str | None) -> CapabilitySpec:
    cap = get(capability_id) if capability_id else None
    if cap is None:
        raise LookupError(f"unknown capability {capability_id!r}")
    return cap


def for_tool(name: str) -> CapabilitySpec:
    """By runtime tool name, or by site tool id (`help.search`, `automation.patch_propose`)."""
    return _require(_tool_cap_id(name))


def for_action(binding) -> CapabilitySpec:
    """The capability of a GenUI action binding (an ActionBinding or its actionId)."""
    from . import ui_domain
    binding = ui_domain.ACTIONS.get(binding) if isinstance(binding, str) else binding
    if binding is None:
        raise LookupError("unknown action")
    return _require(_tool_cap_id(binding.tool) or f"ui.action.{binding.action_id}")


def for_query(binding) -> CapabilitySpec:
    from . import ui_domain
    binding = ui_domain.QUERIES.get(binding) if isinstance(binding, str) else binding
    if binding is None:
        raise LookupError("unknown query")
    return _require(_tool_cap_id(binding.tool) or f"ui.query.{binding.name}")


def surface(surface_name: str, binding_ref: str) -> SurfaceBinding:
    """The only source of a surface's legacy confirmation. Unknown (surface, binding) fails closed."""
    found = _built().bindings.get((surface_name, binding_ref))
    if found is None:
        raise LookupError(f"no {surface_name} binding {binding_ref!r}")
    return found


def bindings(capability_id: str | None = None) -> list[SurfaceBinding]:
    items = _built().bindings.values()
    return sorted((b for b in items if capability_id is None or b.capability_id == capability_id), key=lambda b: (b.surface, b.binding_ref))


def legacy_baseline_v1() -> frozenset:
    """Every consumer since-1 capability except native-only, checked against the frozen baseline fixture in CI.
    Founder bypass is separate. A post-freeze capability must declare since > 1 and can never enter this set."""
    return _built().baseline


def reach(surface_name: str, grants=None) -> frozenset:
    """Capability ids an agent scope may see (CF-1 §13). Legacy (no grants, or source 'legacy') is exactly today's set.
    The Manager gains MANAGER_EXPANSION_V1 only after an explicit Recommended/Full/Custom choice that is not the
    materialized legacy equivalent (baseline 'legacy_v1'). Filtering by decide() != deny is CF-2's (E10)."""
    if surface_name not in SURFACES:
        raise LookupError(f"unknown surface {surface_name!r}")
    built = _built()
    today = frozenset(b.capability_id for (s, _), b in built.bindings.items() if s == surface_name)
    if surface_name == "manager" and grants is not None and getattr(grants, "source", "legacy") == "explicit" \
            and getattr(grants, "baseline", "legacy_v1") is None and getattr(grants, "preset", None) in EXPANSION_PRESETS:
        return today | frozenset(c for c in MANAGER_EXPANSION_V1 if c in built.caps)
    return today


# --- the permissions UI's view (CF-1 §11) ---------------------------------------------------------------------------------
def copy_table() -> dict:
    return json.loads(_COPY_PATH.read_text(encoding="utf-8"))


def _provider_key(scope: ProviderScope) -> str:
    return f"{scope.provider}:{scope.capability or ''}"


def public_catalogue() -> list[dict]:
    """One entry per consumer-tenant capability, sorted by id: no schemas, executors, descriptions (model prompts), agent
    scope names or provider OAuth scope strings. Titles are server-authored en + zh-Hant (capability_copy.json)."""
    built = _built()
    copy = copy_table()
    titles, providers = copy.get("capabilities") or {}, copy.get("providers") or {}
    surfaces: dict[str, dict] = {}
    for b in built.bindings.values():
        per = surfaces.setdefault(b.capability_id, {})
        per[b.surface] = max_confirmation(per.get(b.surface, "none"), b.legacy_confirmation)
    out = []
    for capability_id in sorted(built.caps):
        cap = built.caps[capability_id]
        if cap.tenant == FOUNDER_TENANT:
            continue
        out.append({"capabilityId": capability_id, "version": cap.version, "kind": cap.kind, "category": cap.category, "risk": cap.risk,
                    "confirmation": cap.confirmation, "cost": cap.cost, "dataGrants": list(cap.data_grants or ()), "consents": list(cap.consents),
                    "providerScopes": [{"provider": s.provider, "title": providers.get(_provider_key(s))} for s in cap.provider_scopes],
                    "requirement": cap.permission, "surfaces": sorted(surfaces.get(capability_id, {})),
                    # what each surface asks today (correction 6); an enforcement point asks max(this, decision) (INV-10)
                    "legacyConfirmation": dict(sorted(surfaces.get(capability_id, {}).items())), "nativeOnly": cap.kind == "native_only",
                    "routeId": cap.route_id, "reauthSeconds": cap.reauth_seconds, "baseline": capability_id in built.baseline, "since": cap.since,
                    "explicitRequest": cap.explicit_request, "titleKey": f"capabilities.{capability_id}", "title": titles.get(capability_id)})
    return out


def catalogue_digest() -> str:
    canonical = json.dumps(public_catalogue(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- CI lint (CF-1 §14; remote CI runs it through the tests) -------------------------------------------------------------
def lint() -> list[str]:
    from ..site_agent import tools as site_tools
    from . import tool_adapter, ui_capabilities, ui_domain
    built = _built()
    caps = built.caps
    problems = list(built.problems)
    for name, tool in tool_adapter.REGISTRY.items():
        cap = caps.get(_tool_cap_id(name))
        inline = contracts.inline_policy(tool.spec)
        table = TOOL_POLICY.get(name)
        if table is None and not inline:
            problems.append(f"tool.{name}: dispatchable but undeclared (add it to TOOL_POLICY or declare it on its ToolSpec)")
        for key in set(inline) & set(table or {}):
            if inline[key] != table[key]:
                problems.append(f"tool.{name}: {key} declared inline and in TOOL_POLICY with different values")
        if cap is not None and cap.tenant != FOUNDER_TENANT and cap.data_grants is None:
            problems.append(f"tool.{name}: workspace tool without data_grants")
    for name, entry in TOOL_POLICY.items():
        unknown = set(entry) - set(contracts.POLICY_FIELDS) - set(REGISTRY_ONLY_FIELDS)
        if unknown:
            problems.append(f"TOOL_POLICY[{name}]: unknown keys {sorted(unknown)}")
        if name not in tool_adapter.REGISTRY:
            problems.append(f"TOOL_POLICY[{name}]: no such registered tool")
    for tool_id in site_tools.CATALOG:
        capability_id = site_capability(tool_id)
        if capability_id not in caps:
            problems.append(f"site_agent:{tool_id}: no capability {capability_id}")
        elif site_tools.REQUIREMENT.get(tool_id, "read") != caps[capability_id].permission:
            problems.append(f"site_agent:{tool_id}: requirement differs from its capability's permission")
        if _tool_cap_id(tool_id) != capability_id:
            problems.append(f"site_agent:{tool_id}: adapter mapping differs from the frozen site id rule")
        adapted = tool_adapter.site_tool_name(tool_id)
        if adapted and adapted in tool_adapter.REGISTRY:
            executor = tool_adapter.REGISTRY[adapted].executor
            expected = tool_adapter._site_executor(tool_id)
            try:
                same_executor = (getattr(executor, "__code__", None) is expected.__code__
                                 and inspect.getclosurevars(executor).nonlocals.get("tool_id") == tool_id)
            except (TypeError, ValueError):
                same_executor = False
            if not same_executor:
                problems.append(f"site_agent:{tool_id}: adapter does not run _site_executor({tool_id!r})")
    for kind, table in (("action", ui_domain.ACTIONS), ("query", ui_domain.QUERIES)):
        for ref, binding in table.items():
            capability_id = _tool_cap_id(binding.tool) or f"ui.{kind}.{ref}"
            cap = caps.get(capability_id)
            if cap is None:
                problems.append(f"genui_{kind}:{ref}: no capability {capability_id}")
                continue
            effect = binding.effect if kind == "action" else READ
            if binding.tool:
                # registration agreement, as ui_capabilities.tool_ok checks it for the manifest
                if not ui_capabilities.tool_ok(binding.tool, scope=binding.scope, effect=effect):
                    problems.append(f"genui_{kind}:{ref}: binding and tool {binding.tool} disagree (tool_ok)")
                tenant = FOUNDER_TENANT if binding.scope == FOUNDER_TENANT else "workspace"
                if cap.effect != effect or cap.tenant != tenant or cap.permission != binding.requirement:
                    problems.append(f"genui_{kind}:{ref}: effect/tenant/requirement differ from {capability_id}")
    for capability_id, cap in caps.items():
        if cap.kind in ("tool", "ui_action") and cap.effect != READ and not {"idempotency", "retry_class"} <= set(cap.declared):
            problems.append(f"{capability_id}: non-READ capability must declare idempotency and retry_class")
        if cap.inverse:
            other = caps.get(cap.inverse)
            if other is None or other.inverse != capability_id:
                problems.append(f"{capability_id}: inverse {cap.inverse} missing or not mutual")
        if cap.consents and set(cap.consents) - set(VERIFIED_CONSENT_PRECHECKS.get(capability_id, ())):
            problems.append(f"{capability_id}: consents {list(cap.consents)} not at a verified executor pre-check")
        if cap.since > 1 and capability_id in built.baseline:
            problems.append(f"{capability_id}: since > 1 can never be in LEGACY_BASELINE_V1")
        if cap.kind == "tool" and cap.name in tool_adapter.REGISTRY:
            problems.extend(_writes_permissions(capability_id, tool_adapter.REGISTRY[cap.name].executor))
    for action_id, binding in ui_domain.ACTIONS.items():
        problems.extend(_writes_permissions(f"genui_action:{action_id}", binding.execute))
    routes = {r["id"] for r in json.loads(_ROUTES_PATH.read_text(encoding="utf-8"))["routes"]}
    for capability_id, cap in caps.items():
        if cap.kind == "native_only" and cap.route_id not in routes:
            problems.append(f"{capability_id}: route {cap.route_id} is not in the route manifest")
    copy = copy_table()
    for capability_id, cap in caps.items():
        if cap.tenant == FOUNDER_TENANT:
            continue
        title = (copy.get("capabilities") or {}).get(capability_id) or {}
        if not all(isinstance(title.get(lang), str) and title[lang].strip() for lang in ("en", "zh-Hant")):
            problems.append(f"{capability_id}: needs an en and a zh-Hant title in capability_copy.json")
        for scope in cap.provider_scopes:
            if not (copy.get("providers") or {}).get(_provider_key(scope)):
                problems.append(f"{capability_id}: provider grant {scope.provider} needs a title")
    stale = set(copy.get("capabilities") or {}) - {c for c, cap in caps.items() if cap.tenant != FOUNDER_TENANT}
    problems.extend(f"capability_copy.json: {c} is not a consumer capability" for c in sorted(stale))
    return problems


def _writes_permissions(label: str, fn) -> list[str]:
    """PI-3: no executor may write the agent permission store (grants have no tool path, INV-4)."""
    try:
        source = inspect.getsource(inspect.getmodule(fn))
    except (TypeError, OSError):
        return []
    if "agent_permissions" in source and any(re.search(rf"\b{w}\s*\(", source) for w in _PERMISSION_WRITERS):
        return [f"{label}: its module calls an agent_permissions write function (PI-3)"]
    return []
