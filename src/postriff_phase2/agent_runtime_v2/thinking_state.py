"""Application-owned semantic ThinkingOps for Rafii.

These events describe product activity only. They never carry prompts, user text, model reasoning,
tool arguments, URLs, paths, credentials or provider payloads.
"""
from __future__ import annotations

from typing import Iterable

OPS = frozenset({
    "working", "searching", "solving", "listening", "connecting",
    "weaving", "composing", "breathing", "shaping", "acting",
})
SOURCES = frozenset({"run", "model", "specialist", "tool", "voice", "client"})

SEARCH_TOOLS = frozenset({
    "web_research", "help_search", "help_get", "content_search", "workspace_search",
    "calendar_range", "queue_summary", "campaign_list", "campaign_get", "campaign_items",
    "attention_summary", "entity_status", "workspace_summary", "relationships", "memory_context",
    "image_list", "pending_approvals",
})
COMPOSE_TOOLS = frozenset({"draft_create", "draft_rewrite"})
SHAPE_TOOLS = frozenset({"image_analyze", "image_generate", "image_edit", "image_variant"})
ACT_TOOLS = frozenset({"draft_edit", "campaign_link", "campaign_unlink"})
SOLVE_TOOLS = frozenset({
    "task_plan", "task_update", "schedule_propose", "automation_change_propose",
    "proposal_apply", "route_describe", "skills_list", "weather_now",
})
CONNECT_TOOLS = frozenset()

SPECIALIST_OP = {
    "content": "composing",
    "research": "searching",
    "creative": "shaping",
    "brand_intelligence": "solving",
    "campaign": "solving",
    "publishing_ops": "solving",
    "analytics": "solving",
    "workspace_history": "solving",
}

REASON_CODES = frozenset(
    {"run_open", "manager", "manager_synthesis", "voice_connect", "voice_input", "voice_ready", "approval_apply"}
    | set(SEARCH_TOOLS)
    | set(COMPOSE_TOOLS)
    | set(SHAPE_TOOLS)
    | set(ACT_TOOLS)
    | set(SOLVE_TOOLS)
    | set(CONNECT_TOOLS)
    | set(SPECIALIST_OP)
)


def validate_op(value: str) -> str:
    if value not in OPS:
        raise ValueError("unknown ThinkingOp")
    return value


def event(op: str, source: str, reason_code: str) -> dict:
    """Build one safe event body from fixed enums only."""
    validate_op(op)
    if source not in SOURCES:
        raise ValueError("unknown ThinkingOp source")
    if reason_code not in REASON_CODES:
        raise ValueError("unknown ThinkingOp reason")
    from ..agent_runtime import safe_event
    return safe_event(
        "progress.updated",
        stage="agent_state",
        thinkingOp=op,
        thinkingSource=source,
        reasonCode=reason_code,
    )


def tool_op(tool_name: str) -> str | None:
    if tool_name in SEARCH_TOOLS:
        return "searching"
    if tool_name in COMPOSE_TOOLS:
        return "composing"
    if tool_name in SHAPE_TOOLS:
        return "shaping"
    if tool_name in ACT_TOOLS:
        return "acting"
    if tool_name in SOLVE_TOOLS:
        return "solving"
    if tool_name in CONNECT_TOOLS:
        return "connecting"
    return None


def specialist_op(agent: str | None) -> str:
    return SPECIALIST_OP.get(agent or "", "solving")


def evidence_channels(tool_activity: Iterable[dict]) -> set[str]:
    """Deterministic evidence families already observed in the shared ledger."""
    channels: set[str] = set()
    for item in tool_activity:
        if item.get("status") not in ("verified", "unverified"):
            continue
        specialist = item.get("agent") or item.get("specialist")
        if isinstance(specialist, str) and specialist:
            channels.add("specialist:" + specialist)
            continue
        tool = item.get("tool")
        if not isinstance(tool, str):
            continue
        op = tool_op(tool)
        if op:
            channels.add("tool:" + op)
    return channels


def model_op(agent: str, tool_activity: Iterable[dict]) -> tuple[str, str]:
    if agent != "rafii_manager":
        return specialist_op(agent), agent if agent in REASON_CODES else "manager"
    if len(evidence_channels(tool_activity)) >= 2:
        return "weaving", "manager_synthesis"
    return "solving", "manager"
