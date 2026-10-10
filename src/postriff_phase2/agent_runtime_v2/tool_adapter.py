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
5. failures become typed results (`ok: false`, `code`) the model must report, never exceptions it can paper over;
6. the tool's tenant must match the turn's: a `tenant='founder'` tool runs only inside a founder turn (`ctx.extra['founder']`,
   set by rafii_control.founder_agent from a verified control principal), and workspace tools never run in a founder turn.

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

from . import authz, contracts
from .context import RafiiRunContext, untrusted

MAX_TOOL_OUTPUT = 14_000
FOUNDER_TENANT = "founder"
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
def founder_scope(ctx) -> dict | None:
    """The founder turn's control scope, or None in a workspace (customer) turn.

    A founder turn carries `ctx.extra['founder']` (the verified control principal, the data mode, the control services
    and the founder page context), set only by rafii_control.founder_agent after Boundary.authorize. `RafiiRunContext`
    declares no `extra` field, so a context that was never given one is a workspace turn: nothing a model sends can
    create the scope, and a view of the context (`for_agent`) keeps it."""
    extra = getattr(ctx, "extra", None)
    scope = extra.get(FOUNDER_TENANT) if isinstance(extra, dict) else None
    return scope if isinstance(scope, dict) and scope else None


def tenant_mismatch(ctx, spec: contracts.ToolSpec) -> str | None:
    """Why this tool may not run in this turn's tenant: a founder tool outside a founder turn, or a workspace tool inside
    one. None when the tenants match."""
    founder = founder_scope(ctx) is not None
    if spec.tenant == FOUNDER_TENANT and not founder:
        return "That tool belongs to the founder console and can't run in a workspace request."
    if spec.tenant != FOUNDER_TENANT and founder:
        return "A founder request can't use workspace tools."
    return None


def execute(ctx: RafiiRunContext, tool: Tool, args: Any, *, scope: frozenset | None = None, agent: str | None = None) -> dict:
    started = time.monotonic()
    spec = tool.spec
    ctx = ctx.for_agent(agent)
    if not isinstance(args, dict):
        return _blocked(ctx, tool, started, "tool_input", "Tool input must be an object.")
    if scope is not None and spec.name not in scope:
        return _blocked(ctx, tool, started, "tool_out_of_scope", "This agent can't use that tool.")
    mismatch = tenant_mismatch(ctx, spec)
    if mismatch:
        return _blocked(ctx, tool, started, "tool_tenant", mismatch)
    if ctx.modality == "voice" and not spec.voice:
        return _blocked(ctx, tool, started, "voice_not_allowed", "That can't be done from a voice request; use the panel.")
    if ctx.membership is not None and not ctx.membership.allows(spec.permission):
        return _blocked(ctx, tool, started, "tool_forbidden", "Your role in this workspace can't do this.")
    if ctx.ledger.youtube_provider_context and spec.name not in ('youtube_analytics_summary', 'youtube_recommendations'):
        # Once native provider data reaches a model, freeform tool arguments can
        # be derivatives too. Keep this turn read-only instead of creating
        # untracked drafts, memories, task labels or other persistent copies.
        # Even READ tools can dispatch external queries or persist task prose.
        return _blocked(ctx, tool, started, 'youtube_analytics_read_only',
                        'This analytics turn is read-only. Start a separate request for workspace changes using your own instructions.')
    try:
        if spec.effect != contracts.READ:
            ctx.check_cancelled()
        _check_schema(tool.schema, args)
        from .task_engine.bridge import dispatch_bound
        dispatched = dispatch_bound(ctx, tool, args)
        if dispatched is not None:
            return dispatched
        # Rafii agent permissions (CF-2 E1): nothing is read in off mode, nothing changes in shadow mode; enforce refuses here.
        refused = authz.tool_gate(ctx, tool, args, started=started, agent=agent)
        if refused is not None:
            return refused
        from . import thinking_state
        op = thinking_state.tool_op(spec.name)
        if op:
            ctx.thinking(op, "tool", spec.name)
        with authz.in_tool(), authz.active_tool(ctx, spec, args, agent):
            result = tool.executor(ctx, args)
    except AlphaError as error:
        code = error.code or ("not_found" if error.status == 404 else "forbidden" if error.status == 403 else "conflict" if error.status == 409 else "failed")
        status = "blocked" if code in ("tool_input", "tool_forbidden", "forbidden", "run_cancelled") else "failed"
        ctx.activity(spec.name, tool.label, spec.effect, status, started, code=code)
        if status == "failed":
            ctx.ledger.error(code, str(error)[:300])
        result = {"ok": False, "code": code, "error": str(error)}
        if code == "budget_ceiling" and getattr(error, "required_budget_ceiling_usd_micro", None):
            result["requiredBudgetCeilingUsdMicro"] = error.required_budget_ceiling_usd_micro
        return result
    except Exception as error:  # noqa: BLE001 — a broken tool is a failed step, never a crashed turn
        log.error(json.dumps({"event": "agent_tool.failed", "tool": spec.name, "errorClass": type(error).__name__, "traceId": ctx.trace_id}))
        ctx.activity(spec.name, tool.label, spec.effect, "failed", started, code="tool_error")
        return {"ok": False, "code": "tool_error", "error": "The tool failed. Nothing was reported as done."}
    status = "verified" if result.get("verified", result.get("ok", True)) else ("unverified" if result.get("ok", True) else "failed")
    # A refusal keeps its code in the trace (why a step did not happen), never its free text.
    extra = {"code": str(result["code"])[:60]} if result.get("code") else {}
    runs = run_ids_read(spec.name, result) if status == "verified" else []
    if runs:
        extra["runIds"] = runs
    ctx.activity(spec.name, tool.label, spec.effect, status, started, **extra)
    if not result.get("ok", True) and not result.get("needsUser") and result.get("error"):
        # The app's own reason (a user-facing message) is what the answer reports when the Manager's words can't be used.
        ctx.ledger.error(str(result.get("code") or "failed")[:60], str(result["error"])[:300])
    return result


# D-A52: which automation runs a verified automation read covered (opaque occurrence ids only, never their text), so the
# presentation eligibility (ui_projection.eligibility) offers a run-history view on what was read, not on wording alone.
RUN_READS = {"automation_get": "runs", "automation_explain": "runId"}
MAX_RUN_IDS = 10
_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def run_ids_read(tool: str, result: Any) -> list[str]:
    data = result.get("data") if isinstance(result, dict) else None
    if tool not in RUN_READS or not isinstance(data, dict):
        return []
    if tool == "automation_get":
        found = [run.get("occurrenceId") for run in data.get("runs") if isinstance(run, dict)] if isinstance(data.get("runs"), list) else []
    else:
        found = [data.get("runId")]
    out: list[str] = []
    for ident in found:
        if isinstance(ident, str) and _RUN_ID.match(ident) and ident not in out:
            out.append(ident)
    return out[:MAX_RUN_IDS]


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
            # The timeout is the capability's declared one (CF-1 ToolSpec.timeout_seconds, default 150 s = what every tool had).
            return FunctionTool(name=tool.name, description=tool.spec.description, params_json_schema=tool.schema, on_invoke_tool=invoke,
                                strict_json_schema=False, needs_approval=needs, timeout_seconds=tool.spec.timeout_seconds)
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
    "library.search": "library_search", "library.read": "library_read",
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
    # Chat attachments (chat-context SPEC §5.9): the same search the picker uses.
    "workspace.search": "workspace_search",
    # Rafii live agent (Contract 2): client actions the panel and the voice session carry out.
    "ui.guide": "ui_guide", "ui.voice": "ui_voice",
}
# An `auto` card acts without a click, so it needs the person's own words to ask for it; a model's choice alone only
# leaves a card to click (Contract 2: auto navigation only when the person asked to go/open/be taken somewhere, an
# auto guide only when they asked to be shown or taught). English, Cantonese and Mandarin; code-switching included.
_WANTS_TO_GO = re.compile(r"\bopen(?:s|ing)?\b|\btake\s+me\b|\bbring\s+me\b|\bgo\s+(?:back\s+)?to\b|\bnavigate\b|\bswitch\s+to\b|\bjump\s+to\b|\bhead\s+to\b"
                          r"|\bshow\s+me\s+(?:the\s+|my\s+)?[a-z& ]{2,30}\s+(?:page|screen|tab)\b"
                          r"|帶我去|带我去|打開|打开|開啟|开启|跳去|跳到|轉去|转去|切換到|切换到|去(?:返)?[^，。？！,.?!\s]{0,8}(?:頁|页|版)|開(?:返)?(?:個)?[^，。？！,.?!\s]{0,6}(?:頁|页)", re.I)
_WANTS_TO_BE_SHOWN = re.compile(r"\bhow\s+(?:do|does|can|could|should|would|to)\b|\bshow\s+me\b|\bteach\s+me\b|\bwalk\s+me\b|\bguide\s+me\b|\bwalk\s*through\b"
                                r"|\bstep[\s-]+by[\s-]+step\b|\btutorial\b|\bhelp\s+me\s+(?:to\s+)?(?:set\s+up|connect|create|schedule|upload|add|turn\s+on|choose|write|approve)\b"
                                r"|點樣|点样|點做|点做|點整|点整|點用|点用|點設定|教我|教下我|教吓我|示範|示范|怎麼|怎么|怎樣|怎样|如何|帶我做|带我做|一步一步|手把手", re.I)


def wants_to_go(text: str) -> bool:
    return bool(_WANTS_TO_GO.search(text or ""))


def wants_to_be_shown(text: str) -> bool:
    return bool(_WANTS_TO_BE_SHOWN.search(text or ""))


_ID_TYPES = {"draftId": "draft", "variantId": "draft", "campaignId": "campaign", "jobId": "job", "reviewId": "review", "automationId": "automation",
             "taskId": "automation", "assetId": "asset", "connectionId": "connection", "documentId": "help_document",
             "sourceId": "source", "templateId": "template", "folderId": "folder"}
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
            auto = args.get("auto") is True and wants_to_go(ctx.request_text)
            ctx.ledger.navigation.append(site_contracts.navigation(f"Open {data['title']}", data["href"], data["routeId"], auto=auto))
            data = {**data, "opensNow": auto}
        if tool_id == "ui.guide" and result.get("ok") and isinstance(data, dict):
            data = _guide_card(ctx, args, data)
        if tool_id == "ui.voice" and result.get("ok") and isinstance(data, dict):
            data = _voice_command(ctx, data)
        if tool_id == "help.search" and result.get("ok") and isinstance(data, dict):
            _citations(ctx, data.get("passages") or [])
        return {"ok": result["ok"], "verified": result["verified"], "observedAt": result.get("observedAt"), "source": "application",
                "warnings": result.get("warnings") or [], "data": data}
    return run


def _capable(ctx: RafiiRunContext, capability: str) -> bool:
    """The page declared it can carry out this client action (`uiCapabilities`, re-validated by the page contract)."""
    return capability in ((ctx.page or {}).get("uiCapabilities") or [])


def _guide_card(ctx: RafiiRunContext, args: dict, data: dict) -> dict:
    """A guide card when the panel can run guides; otherwise a plain link to the guide's page (Contract 2)."""
    from ..site_agent import contracts as site_contracts
    if not data.get("canOpen"):
        return {**data, "shownAs": "nothing"}
    if _capable(ctx, "guide"):
        auto = args.get("auto") is True and wants_to_be_shown(ctx.request_text)
        ctx.ledger.guides.append(site_contracts.guide_card(data["guideId"], data["routeId"], data["href"], data["title"], data["summary"], auto=auto))
        return {**data, "shownAs": "guide", "startsNow": auto}
    ctx.ledger.navigation.append(site_contracts.navigation(f"Open {data['page']}", data["href"], data["routeId"], reason=data["title"]))
    return {**data, "shownAs": "link", "startsNow": False}


def _voice_command(ctx: RafiiRunContext, data: dict) -> dict:
    """The panel control for the voice session (Contract 2). A saved style change is a verified change of this person's
    own preference; the panel applies it either way when it can."""
    from ..site_agent import contracts as site_contracts
    command = data.get("command")
    if command == "style" and data.get("persisted"):
        ctx.ledger.changed.append({"type": "preference", "id": "agent_style", "change": "for how Rafii talks to you saved", "expected": "saved style",
                                   "actual": "saved style", "verified": True})
    if not _capable(ctx, "voice"):
        return {**data, "shownAs": "nothing", "note": "This panel can't carry out voice controls; say it in words instead."}
    ctx.ledger.voice_commands.append(site_contracts.voice_command(command, data.get("style") if command == "style" else None))
    return {**data, "shownAs": "panel"}


def _citations(ctx: RafiiRunContext, passages: list[dict]) -> None:
    from ..site_agent import compose as site_compose, contracts as site_contracts
    fresh = [p for p in passages[:3] if not any(c.get("documentId") == p.get("documentId") and c.get("section") == p.get("section") for c in ctx.ledger.citations)]
    if fresh:
        ctx.ledger.citations.extend(site_compose.citation_objects(fresh, site_contracts.iso(ctx.now()), used={p["ref"] for p in fresh if p.get("ref")}))


def _client_tool_overrides() -> dict:
    """Precise descriptions (and, for ui.voice, its effect and style schema) for the client actions the Manager uses."""
    from ..site_agent import guides
    from . import style as agent_style
    style_schema = {"type": "object", "additionalProperties": False,
                    "properties": {**{key: {"type": "string", "enum": list(values)} for key, values in agent_style.FIELDS.items()},
                                   "preset": {"type": "string", "enum": list(agent_style.PRESETS)}}}
    fields = "; ".join(f"{key} ({', '.join(values)})" for key, values in agent_style.FIELDS.items())
    return {
        "ui.navigate": {"description": "Put a link to one allowlisted Rafii page in the answer (routeId from the route manifest; params and query only where "
                                       "that page allows them). Set auto: true ONLY when the person explicitly asked to open, go to or be taken to a page: the panel "
                                       "then opens it at once. Returns whether this member may open it (canOpen, reason)."},
        "ui.guide": {"description": "Start a step-by-step guide on the person's screen: the panel opens the guide's page and a pointer walks through each "
                                    "step, stopping where the person must act themselves (a platform's sign-in). Prefer it to a plain link for 'how do I', "
                                    "'show me', 'teach me', '點樣', '教我'. Set auto: true when the person asked to be shown or taught; otherwise the answer "
                                    "carries a card to start it. shownAs says what the person gets (guide, or a plain link when this panel can't run guides). "
                                    "Guides: " + "; ".join(f"{g['id']} ({g['title']})" for g in guides.entries()) + "."},
        "ui.voice": {"effect": contracts.MUTATE_REVERSIBLE, "schema": {"style": style_schema},
                     "description": "Control the voice panel: end_call (after the person says goodbye or asks to hang up), mute (their microphone), "
                                    "stop_speaking, or style with a `style` change of " + fields + ", or preset (" + ", ".join(agent_style.PRESETS) + "). "
                                    "A style change is saved for this person (persisted: false means it applies to this panel only). The panel carries the "
                                    "command out after your answer: say what will happen, never that it already happened."},
    }


def register_site_tools() -> None:
    """Adapt every released site-agent read and client tool. The proposal tool is replaced by the typed proposal
    tools in domain_tools (they store proposals the same way the panel does)."""
    from ..site_agent import tools as site_tools
    overrides = _client_tool_overrides()
    for tool_id, definition in site_tools.CATALOG.items():
        name = _SITE_NAMES.get(tool_id)
        if name is None or name in REGISTRY or definition["effect"] not in ("read", "client_action"):
            continue
        extra = overrides.get(tool_id, {})
        description = extra.get("description") or definition["purpose"]
        effect = extra.get("effect", contracts.READ)
        spec = contracts.ToolSpec(name=name, effect=effect, permission=site_tools.REQUIREMENT.get(tool_id, "read"),
                                  description=f"{description} (Rafii site tool {tool_id} v{definition['version']}" + ("; read only.)" if effect == contracts.READ else ".)"))
        schema = _json_schema(definition["input"])
        schema["properties"].update(extra.get("schema") or {})
        REGISTRY[name] = Tool(spec, schema, _site_executor(tool_id), site_tools.LABELS.get(tool_id, tool_id))


def catalogue() -> list[dict]:
    return [{**tool.spec.public(), "label": tool.label} for tool in REGISTRY.values()]
