"""Tool adapter and policy bridge (spec §12, WP02).

Every tool the Manager or a specialist can call is a `Tool`: a `ToolSpec` (stable name, effect class, permission,
approval, voice, idempotency, audit) plus an executor. The existing site-agent read tools are adapted, not rewritten:
each one runs `site_agent.tools.run` on a fresh snapshot inside its own short transaction, so its schema validation,
role check, redaction and release pinning stay exactly as verified.

`execute` is the single gate between a model's tool call and the application:
1. the tool must be in the calling agent's scope (a specialist never gains a tool because the app has an endpoint);
2. voice never gains more than text (`spec.voice`);
3. the member's permission is re-checked against the stored role, not the one the turn started with;
4. a cancelled turn stops before any non-read effect;
5. failures become typed results (`ok: false`, `code`) the model must report, never exceptions it can paper over.

Tool output reaches models as data (`context.untrusted`), bounded in size; it is never an instruction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from postriff_alpha.domain import AlphaError

from . import contracts
from .context import RafiiRunContext, untrusted

MAX_TOOL_OUTPUT = 14_000
log = logging.getLogger("postriff.agent_runtime")


@dataclass(frozen=True)
class Tool:
    spec: contracts.ToolSpec
    schema: dict
    executor: Callable[[RafiiRunContext, dict], dict]
    label: str

    @property
    def name(self) -> str:
        return self.spec.name


REGISTRY: dict[str, Tool] = {}


def register(spec: contracts.ToolSpec, schema: dict, label: str):
    def decorate(fn):
        if spec.name in REGISTRY:
            raise ValueError(f"duplicate tool {spec.name}")
        if not re.match(r"^[a-z][a-z0-9_]{1,63}$", spec.name):
            raise ValueError(f"tool names are snake_case identifiers: {spec.name}")
        REGISTRY[spec.name] = Tool(spec, _object(schema), fn, label)
        return fn
    return decorate


def _object(properties_or_schema: dict) -> dict:
    if properties_or_schema.get("type") == "object":
        return properties_or_schema
    required = [k for k, v in properties_or_schema.items() if isinstance(v, dict) and v.pop("required", False)]
    return {"type": "object", "properties": properties_or_schema, "required": required, "additionalProperties": False}


# --- the gate ----------------------------------------------------------------------------------------------------------
def execute(ctx: RafiiRunContext, tool: Tool, args: Any, *, scope: frozenset | None = None, agent: str | None = None) -> dict:
    started = time.monotonic()
    spec = tool.spec
    ctx = ctx.for_agent(agent)
    if not isinstance(args, dict):
        return _blocked(ctx, tool, started, "tool_input", "Tool input must be an object.")
    if scope is not None and spec.name not in scope:
        return _blocked(ctx, tool, started, "tool_out_of_scope", "This agent can't use that tool.")
    if ctx.modality == "voice" and not spec.voice:
        return _blocked(ctx, tool, started, "voice_not_allowed", "That can't be done from a voice request; use the panel.")
    if ctx.membership is not None and not ctx.membership.allows(spec.permission):
        return _blocked(ctx, tool, started, "tool_forbidden", "Your role in this workspace can't do this.")
    try:
        if spec.effect != contracts.READ:
            ctx.check_cancelled()
        _check_schema(tool.schema, args)
        result = tool.executor(ctx, args)
    except AlphaError as error:
        code = error.code or ("not_found" if error.status == 404 else "forbidden" if error.status == 403 else "conflict" if error.status == 409 else "failed")
        status = "blocked" if code in ("tool_input", "tool_forbidden", "forbidden", "run_cancelled") else "failed"
        ctx.activity(spec.name, tool.label, spec.effect, status, started, code=code)
        if status == "failed":
            ctx.ledger.error(code, str(error)[:300])
        return {"ok": False, "code": code, "error": str(error)}
    except Exception as error:  # noqa: BLE001 — a broken tool is a failed step, never a crashed turn
        log.error(json.dumps({"event": "agent_tool.failed", "tool": spec.name, "errorClass": type(error).__name__, "traceId": ctx.trace_id}))
        ctx.activity(spec.name, tool.label, spec.effect, "failed", started, code="tool_error")
        return {"ok": False, "code": "tool_error", "error": "The tool failed. Nothing was reported as done."}
    status = "verified" if result.get("verified", result.get("ok", True)) else ("unverified" if result.get("ok", True) else "failed")
    # A refusal keeps its code in the trace (why a step did not happen), never its free text.
    ctx.activity(spec.name, tool.label, spec.effect, status, started, **({"code": str(result["code"])[:60]} if result.get("code") else {}))
    if not result.get("ok", True) and not result.get("needsUser") and result.get("error"):
        # The app's own reason (a user-facing message) is what the answer reports when the Manager's words can't be used.
        ctx.ledger.error(str(result.get("code") or "failed")[:60], str(result["error"])[:300])
    return result


def _blocked(ctx, tool, started, code, message):
    ctx.activity(tool.spec.name, tool.label, tool.spec.effect, "blocked", started, code=code)
    return {"ok": False, "code": code, "error": message}


def _check_schema(schema: dict, args: dict) -> None:
    props = schema.get("properties") or {}
    extra = set(args) - set(props)
    if extra and schema.get("additionalProperties") is False:
        raise AlphaError("Unexpected tool input.", 400, code="tool_input")
    for key in schema.get("required") or []:
        if key not in args or args[key] in (None, ""):
            raise AlphaError(f"Missing tool input: {key}.", 400, code="tool_input")
    for key, value in args.items():
        spec = props.get(key) or {}
        kind = spec.get("type")
        if value is None:
            continue
        if kind == "string" and (not isinstance(value, str) or len(value) > spec.get("maxLength", 4000) or ("enum" in spec and value not in spec["enum"])
                                 or ("pattern" in spec and not re.match(spec["pattern"], value))):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")
        if kind == "array" and (not isinstance(value, list) or len(value) > spec.get("maxItems", 20)):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 10**11):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")
        if kind == "boolean" and not isinstance(value, bool):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")
        if kind == "object" and not isinstance(value, dict):
            raise AlphaError(f"Invalid tool input: {key}.", 400, code="tool_input")


def model_output(result: dict) -> str:
    """What a model sees: the result as delimited data, bounded."""
    text = json.dumps(untrusted("TOOL_RESULT", result), ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    trimmed = dict(result)
    trimmed["data"] = "(truncated: the result was too large; ask a narrower question)"
    trimmed["truncated"] = True
    return json.dumps(untrusted("TOOL_RESULT", trimmed), ensure_ascii=False, default=str)


# --- Agents SDK binding --------------------------------------------------------------------------------------------------
def sdk_tools(names, *, scope_name: str | None = None) -> list:
    """FunctionTools for `names`, each bound to the gate with this agent's scope."""
    from agents import FunctionTool

    scope = frozenset(names)
    tools = []
    for name in names:
        tool = REGISTRY[name]

        def make(tool=tool):
            async def invoke(tool_context, raw: str):
                ctx: RafiiRunContext = tool_context.context
                try:
                    args = json.loads(raw) if raw else {}
                except ValueError:
                    args = None
                left = ctx.remaining() if hasattr(ctx, "remaining") else None
                if left is not None and left < 8:
                    # Too little of the turn is left to finish a tool (its thread couldn't be stopped at the deadline).
                    ctx.ledger.error("turn_time", f"There wasn't time left in this turn for another step ({tool.name}); it was not started.")
                    return model_output({"ok": False, "code": "turn_time", "message": "No time left in this turn; say what is still to do instead of calling more tools."})
                # Tools do blocking database and provider I/O; keep the event loop free for concurrent tool calls.
                result = await asyncio.to_thread(execute, ctx, tool, args, scope=scope, agent=scope_name)
                return model_output(result)

            needs = _approval_gate(tool) if tool.spec.approval and tool.spec.name == "proposal_apply" else False
            return FunctionTool(name=tool.name, description=tool.spec.description, params_json_schema=tool.schema, on_invoke_tool=invoke,
                                strict_json_schema=False, needs_approval=needs, timeout_seconds=150.0)
        tools.append(make())
    return tools


def _approval_gate(tool: Tool):
    """Human in the loop (§13): applying a proposal always pauses the run for the person. The SDK interruption is only
    the pause; the application's own apply path (digest, permission re-check, audit) decides and executes."""
    async def needs_approval(_context, _args, _call_id):
        return True
    return needs_approval


# --- site-agent read tools, adapted ---------------------------------------------------------------------------------------
_SITE_NAMES = {
    "help.search": "help_search", "help.get": "help_get", "route.describe": "route_describe", "workspace.summary": "workspace_summary",
    "channels.capabilities": "channels_capabilities", "queue.summary": "queue_summary", "job.get": "job_get", "draft.get": "draft_get",
    "automation.list": "automation_list", "automation.get": "automation_get", "automation.explain": "automation_explain",
    "memory.summary": "memory_summary", "privacy.egress_state": "privacy_egress_state", "entitlements.summary": "entitlements_summary",
    "models.summary": "models_summary", "ui.navigate": "ui_navigate", "ui.show_help": "ui_show_help", "brand.summary": "brand_summary",
    "voice.profile": "voice_profile", "content.search": "content_search", "calendar.range": "calendar_range", "campaign.list": "campaign_list",
    "campaign.get": "campaign_get", "reviews.list": "reviews_list", "publishing.summary": "publishing_summary", "attention.summary": "attention_summary",
    "entity.status": "entity_status",
    # Registered by the site agent's gap work (voice fit, member activity); adapted when present.
    "voice.check": "voice_check", "member.activity": "member_activity", "record.attribution": "record_attribution", "campaign.membership": "campaign_membership",
}
_ID_TYPES = {"draftId": "draft", "variantId": "draft", "campaignId": "campaign", "jobId": "job", "reviewId": "review", "automationId": "automation",
             "taskId": "automation", "assetId": "asset", "connectionId": "connection", "documentId": "help_document"}
_TITLE_KEYS = ("name", "goal", "title", "label", "platform")


def site_tool_name(tool_id: str) -> str | None:
    return _SITE_NAMES.get(tool_id)


def _json_schema(site_schema: dict) -> dict:
    props = {}
    for key, spec in (site_schema.get("properties") or {}).items():
        spec = dict(spec)
        if spec.get("type") == "array" and "items" not in spec:
            spec["items"] = {"type": "string"}
        if spec.get("type") == "object":
            spec.setdefault("additionalProperties", True)
        props[key] = spec
    return {"type": "object", "properties": props, "required": list(site_schema.get("required") or []), "additionalProperties": False}


def harvest(ctx: RafiiRunContext, data: Any, limit: int = 40) -> None:
    """References and known ids from a tool's data, in order of appearance (for "the second one" and id checks)."""
    seen = [0]

    def walk(value, depth=0):
        if depth > 5 or seen[0] > limit:
            return
        if isinstance(value, dict):
            title = next((str(value[k]) for k in _TITLE_KEYS if isinstance(value.get(k), str) and value.get(k)), None)
            for key, kind in _ID_TYPES.items():
                ident = value.get(key)
                if isinstance(ident, str) and ident:
                    seen[0] += 1
                    ctx.ledger.reference(kind, ident, title)
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:25]:
                walk(item, depth + 1)
    walk(data)


def _site_executor(tool_id: str):
    def run(ctx: RafiiRunContext, args: dict) -> dict:
        from ..site_agent import tools as site_tools
        with ctx.workspace() as (cur, _row, _principal, member, state):
            sctx = ctx.site_context(cur, member, state)
            record, result = site_tools.run(tool_id, args, sctx)
        if record.get("status") == "blocked":
            raise AlphaError(result["warnings"][0] if result.get("warnings") else "That tool is not available.", 403 if record.get("code") == "tool_forbidden" else 400,
                             code=record.get("code") or "tool_input")
        data = result.get("data")
        if result.get("ok"):
            ctx.ledger.site_results[tool_id] = result
        harvest(ctx, data)
        if tool_id == "ui.navigate" and result.get("ok") and isinstance(data, dict) and data.get("canOpen"):
            from ..site_agent import contracts as site_contracts
            ctx.ledger.navigation.append(site_contracts.navigation(f"Open {data['title']}", data["href"], data["routeId"]))
        if tool_id == "help.search" and result.get("ok") and isinstance(data, dict):
            _citations(ctx, data.get("passages") or [])
        return {"ok": result["ok"], "verified": result["verified"], "observedAt": result.get("observedAt"), "source": "application",
                "warnings": result.get("warnings") or [], "data": data}
    return run


def _citations(ctx: RafiiRunContext, passages: list[dict]) -> None:
    from ..site_agent import compose as site_compose, contracts as site_contracts
    fresh = [p for p in passages[:3] if not any(c.get("documentId") == p.get("documentId") and c.get("section") == p.get("section") for c in ctx.ledger.citations)]
    if fresh:
        ctx.ledger.citations.extend(site_compose.citation_objects(fresh, site_contracts.iso(ctx.now()), used={p["ref"] for p in fresh if p.get("ref")}))


def register_site_tools() -> None:
    """Adapt every released site-agent read and client tool. The proposal tool is replaced by the typed proposal
    tools in domain_tools (they store proposals the same way the panel does)."""
    from ..site_agent import tools as site_tools
    for tool_id, definition in site_tools.CATALOG.items():
        name = _SITE_NAMES.get(tool_id)
        if name is None or name in REGISTRY or definition["effect"] not in ("read", "client_action"):
            continue
        spec = contracts.ToolSpec(name=name, effect=contracts.READ, permission=site_tools.REQUIREMENT.get(tool_id, "read"),
                                  description=f"{definition['purpose']} (Rafii site tool {tool_id} v{definition['version']}; read only.)")
        REGISTRY[name] = Tool(spec, _json_schema(definition["input"]), _site_executor(tool_id), site_tools.LABELS.get(tool_id, tool_id))


def catalogue() -> list[dict]:
    return [{**tool.spec.public(), "label": tool.label} for tool in REGISTRY.values()]
