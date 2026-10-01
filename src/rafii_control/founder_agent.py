"""Founder Rafii: the agent runtime run for the founder on the ops workspace (Founder Admin v2, CONTRACTS §4; PRD §6).

One founder turn is an ordinary `AgentRuntimeService` turn — the same runs, messages, reservations, cancellation, answer
policy and stored result — on the founder's ops workspace (`RAFII_FOUNDER_OPS_WORKSPACE_ID`), with three founder-only
layers on top:

1. the principal: the verified control principal from `Boundary.authorize` (founder role, AAL2, `copilot.use`) becomes
   the ops-workspace member the turn runs as, through `automation_runs.principal_repository` (a private capability, never
   an HTTP credential, re-checked at every transaction) — the same pattern as `phone/service.scoped_runtime`;
2. the scope: the Manager is built with the founder tools only (`founder_tools.FOUNDER_TOOL_NAMES`) and the founder
   instructions (`founder_prompts`); the gate refuses every workspace tool inside the turn and every founder tool outside it;
3. the namespace: idempotency keys carry `founder:<mode>:<environment>:` and conversations are created in, and checked
   against, a `[founder:<mode>:<environment>]` namespace, so Demo and Live never share a thread.

What never happens here: a fall back to the customer site agent (a founder turn that cannot run says so), a Live answer
served from Demo, a number the tools did not return (the founder section keeps only facts whose receipt this turn produced),
or any effect beyond the founder tools' own (drafts wait for the founder's confirmation in the panel). Cost reservations are
tagged `costCenter='founder_ops'` on the ops workspace's own ledger.

With `RAFII_AGENT_HARNESS=1` (local QA only; refused on Vercel by the runtime's harness guard) the founder Manager is an
Agents SDK `ScriptedModel` whose steps are computed from the request and the tool outputs already in the run, so browser
and unit tests prove the tool plan for the PRD's example questions without a paid call.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import uuid

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import approvals, contracts, style as agent_style
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService, TURN_BUDGET_SECONDS
from postriff_phase2.agent_runtime_v2.tool_adapter import founder_scope

from . import founder_prompts, founder_tools  # noqa: F401 — importing founder_tools registers the founder tools with the gate
from .auth import ControlError
from .founder_prompts import AGENT_NAME, MODES, REPORT_TIME_ZONE, SECTIONS
from .founder_tools import COLLECTIONS, FOUNDER_TOOL_NAMES

OPS_WORKSPACE_ENV = "RAFII_FOUNDER_OPS_WORKSPACE_ID"
KEY_PREFIX = "founder:"                 # inside the runtime's own "agent:" prefix: agent:founder:<mode>:<environment>:<key>
RUN_KEY_PREFIX = "agent:" + KEY_PREFIX
MAX_MESSAGE = 4000
RUNTIME_VERSION = "founder-agent-1"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")      # the panel's Idempotency-Key header (http.py accepts up to 200)
_RUN_KEY_LIMIT = 100                                   # the runtime's own idempotency key limit (service.turn)
_ID = re.compile(r"^[A-Za-z0-9:_.-]{1,80}$")
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


class FounderError(ControlError):
    """A control error that also names the blocker (a fixed code, never free text from a request or a record)."""

    def __init__(self, code, status=403, *, blocker=None, detail=None):
        super().__init__(code, status)
        self.blocker, self.detail = blocker, detail


class PolicyDisabled(FounderError):
    def __init__(self, blocker):
        super().__init__("POLICY_DISABLED", 409, blocker=blocker)


# --- configuration and principal ---------------------------------------------------------------------------------------------
def ops_workspace_id(values=None) -> str:
    """The founder's ops workspace id, or `409 POLICY_DISABLED` (blocker ops_workspace_not_configured) when it is not set."""
    import os
    raw = (values if values is not None else os.environ).get(OPS_WORKSPACE_ENV)
    if not isinstance(raw, str) or not _UUID.match(raw.strip()):
        raise PolicyDisabled("ops_workspace_not_configured")
    return str(uuid.UUID(raw.strip()))


def require_founder(principal) -> dict:
    """The control principal a founder turn runs for: an active founder, AAL2, with copilot.use, control.read and
    metrics.query, on a live session of this environment. Anything else — including a customer bearer, which never has a
    control principal at all — is refused before any workspace is touched."""
    from .intelligence import QueryService
    if not isinstance(principal, dict) or not isinstance(principal.get("operator"), dict) or not isinstance(principal.get("session"), dict):
        raise ControlError("AUTH_REQUIRED", 401)
    for capability in ("copilot.use", "control.read", "metrics.query"):
        QueryService.require(principal, capability)
    operator, session = principal["operator"], principal["session"]
    if operator.get("role") != "founder" or operator.get("status") != "active":
        raise ControlError("FOUNDER_REQUIRED")
    if session.get("assurance") != "aal2":
        raise ControlError("STEP_UP_REQUIRED")
    user = operator.get("user_id")
    if not isinstance(user, str) or not _UUID.match(user):
        raise ControlError("VALIDATION_FAILED", 400)
    if (session.get("revoked_at") is not None or float(session.get("expires_at") or 0) <= time.time()
            or session.get("environment") != operator.get("environment") or session.get("auth_epoch") != operator.get("auth_epoch")):
        raise ControlError("AUTH_REQUIRED", 401)
    return principal


def request_identifier(value) -> str:
    return str(uuid.UUID(value)) if isinstance(value, str) and _UUID.match(value) else str(uuid.uuid4())


def conversation_namespace(mode: str, environment: str) -> str:
    return f"{KEY_PREFIX}{mode}:{environment}"


def runtime_key(mode: str, environment: str, key: str) -> str:
    """The runtime idempotency key: `founder:<mode>:<environment>:<key>`, the key digested when the whole would exceed the
    runtime's limit (the same panel key always maps to the same run)."""
    import hashlib
    full = f"{conversation_namespace(mode, environment)}:{key}"
    return full if len(full) <= _RUN_KEY_LIMIT else f"{conversation_namespace(mode, environment)}:h{hashlib.sha256(key.encode()).hexdigest()[:40]}"


def envelope_state(section: dict) -> str:
    """`_dataState` for the control envelope: Demo data is synthetic; Live is as measured as its receipts say."""
    if section.get("mode") == "demo":
        return "synthetic"
    states = {r.get("dataState") for r in section.get("receipts") or [] if r.get("dataState")}
    if not states:
        return "not_applicable"
    return "measured" if states == {"measured"} else "partial"


def conversation_title(namespace: str, text: str) -> str:
    first = " ".join((text or "").splitlines()[0].split())[:80] if text else ""
    return f"[{namespace}] " + (first or "Founder question")


def namespace_of_title(title) -> str | None:
    match = re.match(r"^\[(founder:(?:demo|live):[a-z]+)\]", title or "")
    return match.group(1) if match else None


# --- the turn body ----------------------------------------------------------------------------------------------------------
def _text(value, limit) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ControlError("VALIDATION_FAILED", 400)
    return value.strip()


def _identifier(value) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ControlError("VALIDATION_FAILED", 400)
    return value


def founder_context(raw) -> dict:
    """The founder page context, re-validated field by field (CONTRACTS §6: section, selectedEntity, chart, period, filters,
    incidentId, outline). Unknown keys and free text are refused; the outline goes through the site agent's own re-validation."""
    from postriff_phase2.site_agent import contracts as site_contracts
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {"section", "route", "selectedEntity", "chart", "period", "filters", "incidentId", "outline"}:
        raise ControlError("VALIDATION_FAILED", 400)
    out = {}
    if "section" in raw:
        if raw["section"] not in SECTIONS:
            raise ControlError("VALIDATION_FAILED", 400)
        out["section"] = raw["section"]
    if "route" in raw:
        route = _text(raw["route"], 200)
        if not route.startswith("/founder"):
            raise ControlError("VALIDATION_FAILED", 400)
        out["route"] = route
    if raw.get("selectedEntity") is not None:
        entity = raw["selectedEntity"]
        if not isinstance(entity, dict) or set(entity) != {"collection", "id"} or entity["collection"] not in COLLECTIONS:
            raise ControlError("VALIDATION_FAILED", 400)
        out["selectedEntity"] = {"collection": entity["collection"], "id": _identifier(entity["id"])}
    if raw.get("chart") is not None:
        chart = raw["chart"]
        if not isinstance(chart, dict) or not {"chartId", "viewVersion", "queryReceiptId"} <= set(chart) or set(chart) - {"chartId", "viewVersion", "queryReceiptId", "selection"}:
            raise ControlError("VALIDATION_FAILED", 400)
        if type(chart["viewVersion"]) is not int or not isinstance(chart["queryReceiptId"], str) or not 1 <= len(chart["queryReceiptId"]) <= 120:
            raise ControlError("VALIDATION_FAILED", 400)
        selection = chart.get("selection", [])
        if not isinstance(selection, list) or len(selection) > 10 or any(not isinstance(s, str) or len(s) > 80 for s in selection):
            raise ControlError("VALIDATION_FAILED", 400)
        out["chart"] = {"chartId": _identifier(chart["chartId"]), "viewVersion": chart["viewVersion"], "queryReceiptId": chart["queryReceiptId"], "selection": selection}
    if "period" in raw:
        out["period"] = _text(raw["period"], 40)
    if raw.get("filters") is not None:
        filters = raw["filters"]
        if not isinstance(filters, dict) or len(filters) > 10 or any(not isinstance(k, str) or not _FIELD.match(k) or not isinstance(v, str) or len(v) > 80 for k, v in filters.items()):
            raise ControlError("VALIDATION_FAILED", 400)
        out["filters"] = dict(filters)
    if "incidentId" in raw:
        out["incidentId"] = _identifier(raw["incidentId"])
    if "outline" in raw:
        out["outline"] = site_contracts.outline(raw["outline"])
    return out


def validate_turn(body) -> dict:
    """The founder turn body: message and mode, then the optional conversation, idempotency key, modality, time zone,
    locale and page context. Strict keys, bounded values, no free text anywhere but the message itself."""
    required, optional = {"message", "mode"}, {"conversationId", "idempotencyKey", "modality", "timeZone", "locale", "pageContext"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - required - optional:
        raise ControlError("VALIDATION_FAILED", 400)
    if body["mode"] not in MODES:
        raise ControlError("VALIDATION_FAILED", 400)
    out = {"message": _text(body["message"], MAX_MESSAGE), "mode": body["mode"], "modality": "text", "pageContext": founder_context(body.get("pageContext"))}
    conversation = body.get("conversationId")
    if conversation is not None:
        if not isinstance(conversation, str) or not _UUID.match(conversation):
            raise ControlError("VALIDATION_FAILED", 400)
        out["conversationId"] = str(uuid.UUID(conversation))
    key = body.get("idempotencyKey")
    if key is not None and (not isinstance(key, str) or not _KEY.match(key)):
        raise ControlError("VALIDATION_FAILED", 400)
    out["idempotencyKey"] = key or uuid.uuid4().hex
    if body.get("modality") is not None:
        if body["modality"] not in ("text", "voice"):
            raise ControlError("VALIDATION_FAILED", 400)
        out["modality"] = body["modality"]
    for name, limit in (("timeZone", 80), ("locale", 20)):
        if body.get(name) is not None:
            out[name] = _text(body[name], limit)
    return out


# --- errors across the boundary -------------------------------------------------------------------------------------------------
_POLICY_CODES = {"runtime_off", "no_model_route", "founder_budget", "founder_unavailable", "price_unknown"}


def control_error(error: AlphaError) -> ControlError:
    """A runtime refusal as a control error: the status and a fixed code, the runtime's own user-facing sentence as detail."""
    code = getattr(error, "code", None)
    if code in _POLICY_CODES:
        return FounderError("POLICY_DISABLED", 409, blocker=code, detail=str(error))
    mapped = {400: "VALIDATION_FAILED", 401: "AUTH_REQUIRED", 402: "BUDGET_EXCEEDED", 403: "SCOPE_DENIED", 404: "SOURCE_UNAVAILABLE", 409: "STALE_PREVIEW",
              429: "RATE_LIMITED"}.get(error.status, "SOURCE_UNAVAILABLE")
    return FounderError(mapped, error.status if error.status in (400, 401, 402, 403, 404, 409, 429) else 503, blocker=code, detail=str(error))


# --- the scoped runtime ---------------------------------------------------------------------------------------------------------
def founder_reservation_approval(cur, workspace_id, principal, revision, cost, route, run_id):
    """Founder turns are paid from the ops workspace's own credit policy (no model may supply authority); the reservation is
    tagged so finance reads it as founder operations, never as customer AI usage."""
    return None, {"costCenter": "founder_ops"}


def scoped_service(service, ops_workspace_id: str, operator_id: str):
    """A private copy of the hosted service that acts as the founder on the ops workspace only (`principal_repository`:
    the capability object is the token; every transaction re-checks the founder's membership)."""
    from postriff_phase2.automation_runs import principal_repository
    repository, capability = principal_repository(service, ops_workspace_id, operator_id, "edit")
    scoped = copy.copy(service)
    scoped.repository, scoped.verify_session = repository, repository.verify_session
    scoped.ideas = copy.copy(service.ideas)
    scoped.ideas.repository = repository
    if hasattr(scoped.ideas, "service_ref"):
        scoped.ideas.service_ref = scoped
    return scoped, capability


def founder_runtime(service, ops_workspace_id: str, operator_id: str, founder: dict, *, base=None, model_factory=None):
    """(FounderAgentRuntime, capability) for one founder request. `base` is the hosted service's configured runtime (the
    QA harness when enabled); a scripted `model_factory` is for tests."""
    if base is None:
        from postriff_phase2.agent_runtime_v2.http import runtime_for
        base = runtime_for(service)
    scoped, capability = scoped_service(service, ops_workspace_id, operator_id)
    factory = model_factory if model_factory is not None else (founder_model_factory(base.model_factory) if base.model_factory is not None else None)
    runtime = FounderAgentRuntime(scoped, base.cfg, founder, model_factory=factory, live_transport=getattr(base, "live_transport", None), clock=base.clock)
    return runtime, capability


class ControlServices:
    """The two control services a founder turn reads through: `queries` (QueryService: receipts, metric queries in
    either data mode) and `workspace` (WorkspaceService: bounded reads and the founder's Demo dataset)."""

    def __init__(self, queries, workspace):
        self.queries, self.workspace = queries, workspace


_CONTROL_CACHE: dict = {}


def control_services(values=None) -> ControlServices:
    """The control services for a turn the mount did not hand them to (http.py passes only the consumer service): built
    once per process and environment from the restricted RAFII_CONTROL_* logins exactly as rafii_control.hosted.create_app
    builds them — never from a consumer credential. 503 SOURCE_UNAVAILABLE when Control is not configured here."""
    import hashlib
    import os
    from .auth import Config
    from .hosted import admit_databases
    from .intelligence import QueryService
    from .store import PostgresStore, connection_factory
    from .workspace import WorkspaceService
    values = values if values is not None else os.environ
    try:
        config = Config.from_environment(values)
    except ValueError:
        raise ControlError("SOURCE_UNAVAILABLE", 503) from None
    session_dsn, reader_dsn = values.get("RAFII_CONTROL_SESSION_DSN"), values.get("RAFII_CONTROL_READER_DSN")
    if not config.enabled or not session_dsn or not reader_dsn or session_dsn == reader_dsn:
        raise ControlError("SOURCE_UNAVAILABLE", 503)
    key = (config.environment, hashlib.sha256((session_dsn + "\n" + reader_dsn).encode()).hexdigest())
    if key not in _CONTROL_CACHE:
        try:
            admit_databases(session_dsn, reader_dsn, values, config)
        except ValueError:
            raise ControlError("SOURCE_UNAVAILABLE", 503) from None
        store = PostgresStore(connection_factory(session_dsn, "rafii_control_session", config.environment),
                              connection_factory(reader_dsn, "rafii_control_reader", config.environment), config.environment)
        _CONTROL_CACHE[key] = ControlServices(QueryService(store), WorkspaceService(store))
    return _CONTROL_CACHE[key]


def founder_scope_for(principal: dict, mode: str, control, context: dict, request_id: str) -> dict:
    """What every founder tool reads from `ctx.extra['founder']`: the verified principal, the data mode, the control
    services (an object with `.queries` and `.workspace`: ControlServices or the ControlApplication) and the page context."""
    environment = principal["session"]["environment"]
    queries = getattr(control, "queries", None) if control is not None else None
    workspace = getattr(control, "workspace", None) if control is not None else None
    if workspace is None and queries is not None and getattr(queries, "store", None) is not None:
        from .workspace import WorkspaceService
        workspace = WorkspaceService(queries.store)
    return {"principal": principal, "operatorId": principal["operator"]["user_id"], "mode": mode, "environment": environment,
            "namespace": conversation_namespace(mode, environment), "queries": queries, "workspace": workspace, "context": context, "request_id": request_id,
            "receipts": [], "drafts": [], "links": [], "cache": {}}


class FounderAgentRuntime(AgentRuntimeService):
    """One founder turn's runtime: the base service with the founder Manager, no site-agent fallback, namespaced
    conversations, founder-tagged reservations and the `founder` result section. One instance serves one request."""

    def __init__(self, scoped, cfg, founder: dict, *, model_factory=None, live_transport=None, clock=None):
        super().__init__(scoped, cfg, model_factory=model_factory, live_transport=live_transport, clock=clock)
        self.founder = founder
        self.reservation_approval = founder_reservation_approval
        self.followup_transport = None
        self._founder_ctx: RafiiRunContext | None = None
        self._founder_reply = None

    # --- front door: the founder never reaches the customer site agent ---------------------------------------------------------
    def _front_door(self, cur, state, workspace_id, conversation_id, member, text, page, modality) -> dict:
        if conversation_id and approvals.is_cancel_request(text) and member.allows("edit"):
            return {"mode": "cancel"}
        if self.model_factory is None and not self.cfg.enabled("RAFII_AGENT_V2_ENABLED"):
            raise AlphaError("Rafii's agent runtime is not enabled on this deployment.", 409, code="runtime_off")
        if not member.allows("edit"):
            raise AlphaError("The founder's ops workspace membership can't run Rafii.", 403, code="role_grounded")
        if self.model_factory is None and not self.cfg.route("standard_reasoning", reason="founder turn").available:
            raise AlphaError("No reasoning model route is configured for the founder console.", 409, code="no_model_route")
        return {"mode": "manager"}

    def _fallback(self, workspace_id, token, payload, text, modality, trace_id, *, reason=None) -> dict:
        """There is no fallback for a founder turn: the site agent answers customer workspaces, never the founder."""
        if reason == "budget":
            raise AlphaError("Rafii can't start this founder turn: the ops workspace refused the cost reservation (budget, allowance or price).", 409, code="founder_budget")
        raise AlphaError("Rafii's founder agent can't answer this turn here.", 503, code="founder_unavailable")

    # --- conversations: one namespace per data mode and environment ----------------------------------------------------------------
    def _new_conversation(self, workspace_id, token, text) -> str:
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,%s) RETURNING id::text",
                        (workspace_id, principal, conversation_title(self.founder["namespace"], text)))
            return cur.fetchone()[0]

    def conversation_namespace_of(self, workspace_id, token, conversation_id) -> str:
        """The namespace a founder conversation was created in; a conversation that is not a founder one (or missing) is
        the same 404 as a missing one."""
        with self.service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
            cur.execute("SELECT title FROM public.pr_conversations WHERE id::text=%s AND workspace_id=%s", (conversation_id, workspace_id))
            row = cur.fetchone()
        found = namespace_of_title(row[0]) if row else None
        if not found:
            raise AlphaError("Conversation unavailable.", 404)
        return found

    def check_conversation(self, workspace_id, token, conversation_id) -> None:
        """A conversation the panel names must belong to this turn's namespace (Demo and Live threads never mix); a
        mismatch is the same 404 as a missing one."""
        if self.conversation_namespace_of(workspace_id, token, conversation_id) != self.founder["namespace"]:
            raise AlphaError("Conversation unavailable.", 404)

    # --- the Manager ---------------------------------------------------------------------------------------------------------------------
    def _run_manager(self, workspace_id, token, conversation_id, text, modality, trace_id, page, zone, payload, attachments, run_id, reservation,
                     workload, why, superseded, holder) -> dict:
        from agents import RunConfig, Runner
        from agents.exceptions import InputGuardrailTripwireTriggered, MaxTurnsExceeded, OutputGuardrailTripwireTriggered

        from postriff_phase2.agent_runtime_v2 import manager as manager_mod

        with self.service.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = self.service.ideas._member(row)
            history = self._history(cur, workspace_id, conversation_id)
            style = agent_style.load(cur, principal)
        ctx = RafiiRunContext(service=self.service, workspace_id=workspace_id, token=token, principal=principal, membership=member, conversation_id=conversation_id,
                              trace_id=trace_id, modality=modality, page=page, zone=zone, locale=payload.get("locale") if isinstance(payload.get("locale"), str) else None,
                              run_id=run_id, now=self.clock, config=self.cfg, request_text=text, style=style)
        ctx.extra = {"founder": {**self.founder, "receipts": [], "drafts": [], "links": [], "cache": {}}}
        ctx.cancelled = lambda: self._is_cancelled(workspace_id, token, run_id)
        ctx.deadline = time.monotonic() + TURN_BUDGET_SECONDS
        holder["ctx"] = ctx
        self._founder_ctx = ctx
        items = assemble(ctx, text, history)
        manager, routes = build_manager(ctx, model_factory=self.model_factory, workload=workload)
        collector = manager_mod.collector(self.cfg)
        run_config = RunConfig(workflow_name="rafii.founder.turn", trace_id=trace_id, group_id=conversation_id, trace_include_sensitive_data=False,
                               trace_metadata={"modality": modality, "runtime": RUNTIME_VERSION, "namespace": self.founder["namespace"]})
        reply, note, fallback_reason = None, None, None
        started = time.monotonic()
        try:
            result = asyncio.run(manager_mod.drive(ctx, Runner.run(manager, items, context=ctx, max_turns=12, run_config=run_config), TURN_BUDGET_SECONDS))
            reply = result.final_output
        except OutputGuardrailTripwireTriggered:
            fallback_reason = "guardrail_output"
        except InputGuardrailTripwireTriggered:
            fallback_reason = "guardrail_input"
            note = "I can't do that from the founder console's chat. Refunds, bans, deletions, deployments, commands and sending stay on their own pages, if they exist at all."
        except MaxTurnsExceeded:
            fallback_reason = "max_turns"
            note = "This took more steps than I allow in one turn, so I stopped. Here is exactly where things stand."
        except asyncio.TimeoutError:
            fallback_reason = "timeout"
            note = "This took longer than one turn allows, so I stopped. Here is exactly where things stand."
        except AlphaError as error:
            fallback_reason = error.code or "error"
            note = "You cancelled this, so I stopped. Here is what had already finished." if error.code == "run_cancelled" else f"I stopped: {error}"
        except Exception as error:  # noqa: BLE001 — a model or provider failure never becomes a success claim
            import logging
            logging.getLogger("postriff.agent_runtime").error(json.dumps({"event": "founder_turn.failed", "errorClass": type(error).__name__, "traceId": trace_id}))
            fallback_reason = "model_error"
            note = "Rafii's reasoning model didn't answer, so nothing more was done. Here is exactly where things stand."
        self._founder_reply = reply
        elapsed = round((time.monotonic() - started) * 1000)
        return self._finalize(ctx, run_id, reservation, reply=reply, note=note, fallback_reason=fallback_reason, interruptions=[], state_json=None, routes=routes,
                              workload=workload, why=why, spans=collector.take(trace_id), elapsed_ms=elapsed, superseded=superseded)

    def _manager_follow_ups(self, ctx, run_id, reservation, answer, language, default_model) -> dict:
        """No light-model follow-up chips for founder turns: the Manager's own follow_ups are enough, and no second paid call."""
        return {"followUps": [], "span": None, "skipped": "founder"}

    def _persist(self, cur, workspace_id, conversation_id, run_id, result, blocks, proposals, refs, *, trace, status, usage, pending=None, language=None,
                 follow_ups=(), site_extra=None):
        """The stored result carries the `founder` section (receipts, facts, hypotheses, recommendations, unknowns, links,
        drafts) and the panel gets the receipt and draft blocks; everything else is the base runtime's own persistence."""
        section = founder_section(self._founder_ctx, self._founder_reply, self.founder)
        result["founder"] = section
        blocks.extend(founder_blocks(section))
        trace = {**trace, "founder": {"mode": section["mode"], "environment": section["environment"], "namespace": section["namespace"], "runtime": RUNTIME_VERSION,
                                      "receipts": len(section["receiptIds"]), "factsKept": len(section["facts"]), "factsDropped": section.get("factsDropped", 0)}}
        return super()._persist(cur, workspace_id, conversation_id, run_id, result, blocks, proposals, refs, trace=trace, status=status, usage=usage, pending=pending,
                                language=language, follow_ups=follow_ups, site_extra=site_extra)


# --- building the founder Manager -----------------------------------------------------------------------------------------------------
def input_guardrail():
    """Defense in depth: a request for an effect the founder console never carries out from a chat (refund, ban, delete,
    deploy, shell/SQL, send) trips before any model call. No founder tool can do these anyway."""
    from agents import GuardrailFunctionOutput, input_guardrail as decorate

    @decorate(name="rafii_founder_forbidden_effects", run_in_parallel=False)
    async def forbidden(context, _agent, raw_input):
        ctx = context.context
        request = ctx.request_text or (raw_input if isinstance(raw_input, str) else "")
        category = founder_prompts.forbidden_effect(request)
        if category:
            ctx.ledger.guardrail_trips.append({"guardrail": "rafii_founder_forbidden_effects", "reason": category})
        return GuardrailFunctionOutput(output_info={"category": category}, tripwire_triggered=bool(category))

    return forbidden


def build_manager(ctx: RafiiRunContext, *, model_factory=None, workload: str = "standard_reasoning"):
    """(founder Manager Agent, routes used): the founder tools only, the founder instructions, the base answer-policy output
    guardrail and the founder input guardrail. Provider clients are recorded on `ctx.clients` and closed by `manager.drive`."""
    from postriff_phase2.agent_runtime_v2 import manager as manager_mod
    token = manager_mod._CLIENTS.set(ctx.clients)   # the base runtime's own client sink, so founder turns close clients the same way
    try:
        return _build(ctx, model_factory=model_factory, workload=workload)
    except Exception:
        if ctx.clients:
            try:
                asyncio.run(manager_mod.close_clients(ctx.clients))
            except RuntimeError:
                pass
        raise
    finally:
        manager_mod._CLIENTS.reset(token)


def _build(ctx: RafiiRunContext, *, model_factory, workload):
    from agents import Agent

    from postriff_phase2.agent_runtime_v2 import answer_policy, config as runtime_config, manager as manager_mod, specialists
    from postriff_phase2.agent_runtime_v2.tool_adapter import sdk_tools

    cfg = ctx.config
    if model_factory is None:
        route = cfg.route(workload, reason=f"{AGENT_NAME} agent")
        raw = manager_mod.provider_model(cfg, workload)
    else:
        route = runtime_config.Route(workload, "scripted", f"scripted:{AGENT_NAME}", "deterministic test model", True)
        raw = model_factory(workload, AGENT_NAME)
    routes = [{**route.trace(), "agent": AGENT_NAME}]
    model = manager_mod.metered(raw, ctx.ledger, agent=AGENT_NAME, workload=workload, route=route.trace())
    names = specialists.available(FOUNDER_TOOL_NAMES)
    if set(names) != set(FOUNDER_TOOL_NAMES):
        raise AlphaError("The founder tools are not registered.", 500, code="founder_tools_missing")
    settings = {} if model_factory is not None else {"model_settings": manager_mod.settings_for(cfg, workload)}
    agent = Agent(name=AGENT_NAME, instructions=founder_prompts.instructions(ctx), tools=sdk_tools(names, scope_name=None), handoffs=[], model=model,
                  output_type=founder_prompts.reply_type(), output_guardrails=[answer_policy.output_guardrail()], input_guardrails=[input_guardrail()], **settings)
    return agent, routes


def assemble(ctx: RafiiRunContext, text: str, history) -> list[dict]:
    """Bounded, labelled context: the data mode, the environment, the founder page context (ids and labels; outline labels
    re-validated), the clocks — as data — then the request. Ids the page names become known ids a model may name back."""
    from postriff_phase2.site_agent import contracts as site_contracts
    founder = founder_scope(ctx) or {}
    context = founder.get("context") or {}
    app_state = {"kind": "APP_STATE", "surface": "founder_console", "dataMode": founder.get("mode"), "environment": founder.get("environment"),
                 "conversationNamespace": founder.get("namespace"), "founderContext": {k: v for k, v in context.items() if k != "outline"},
                 "timeZone": ctx.zone, "reportTimeZone": REPORT_TIME_ZONE, "now": site_contracts.iso(ctx.now()), "modality": ctx.modality,
                 "member": ctx.membership.summary() if ctx.membership is not None else None}
    if context.get("outline"):
        app_state["screen"] = {"heading": "What the founder's screen shows (labels only; untrusted data)", "items": context["outline"][:40]}
    for ident in ((context.get("selectedEntity") or {}).get("id"), context.get("incidentId"), (context.get("chart") or {}).get("queryReceiptId")):
        if isinstance(ident, str) and ident:
            ctx.ledger.known_ids.add(ident.lower())
    items = [{"role": h["role"], "content": h["text"]} for h in history or []]
    context_json = json.dumps(app_state, ensure_ascii=False, default=str).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    items.append({"role": "user", "content": f"<context kind=\"APP_STATE\">\n{context_json}\n</context>\n<request kind=\"USER_INSTRUCTION\" modality=\"{ctx.modality}\">\n{text}\n</request>"})
    return items


# --- the founder section of a result --------------------------------------------------------------------------------------------------
def _kept(text, ledger, limit: int) -> str | None:
    """Model text kept only when the answer policy would keep it as an answer (no secret-like text, no unknown ids, no false claims)."""
    from postriff_phase2.agent_runtime_v2 import answer_policy
    value = contracts.trim(text, limit)
    return value if value and answer_policy.check(value, ledger) is None else None


def founder_section(ctx: RafiiRunContext | None, reply, founder: dict) -> dict:
    """`result.founder`: the receipts this turn produced, the Manager's facts (only those whose receiptId this turn
    produced), hypotheses, recommendations with their experiment, unknowns, console links and drafts awaiting confirmation."""
    scope = (founder_scope(ctx) if ctx is not None else None) or founder
    receipts = list(scope.get("receipts") or [])
    known = {r["receiptId"] for r in receipts}
    ledger = ctx.ledger if ctx is not None else None
    facts, dropped = [], 0
    for fact in (getattr(reply, "facts", None) or []):
        text = _kept(getattr(fact, "text", None), ledger, 500) if ledger is not None else None
        receipt_id = getattr(fact, "receiptId", None)
        if text is None or receipt_id not in known:
            dropped += 1
            continue
        facts.append({"text": text, "receiptId": receipt_id, "kind": "stored"})
    hypotheses = [t for t in (_kept(h, ledger, 400) for h in (getattr(reply, "hypotheses", None) or []) if ledger is not None) if t][:8]
    recommendations = []
    for item in (getattr(reply, "recommendations", None) or [])[:6]:
        text = _kept(getattr(item, "text", None), ledger, 400) if ledger is not None else None
        if text:
            recommendations.append({"text": text, "metric": contracts.trim(getattr(item, "metric", None), 80) or None, "period": contracts.trim(getattr(item, "period", None), 40) or None,
                                    "success": contracts.trim(getattr(item, "success", None), 200) or None})
    unknowns = [t for t in (_kept(u, ledger, 400) for u in (getattr(reply, "unknowns", None) or []) if ledger is not None) if t][:8]
    if dropped:
        unknowns.append(f"{dropped} statement(s) offered as facts had no receipt from this turn and were left out.")
    return {"version": 1, "mode": scope.get("mode"), "environment": scope.get("environment"), "namespace": scope.get("namespace"), "composedBy": "manager" if reply is not None else "deterministic",
            "receiptIds": [r["receiptId"] for r in receipts], "receipts": receipts[:20], "facts": facts[:20], "hypotheses": hypotheses, "recommendations": recommendations,
            "unknowns": unknowns, "links": list(scope.get("links") or [])[:20], "drafts": list(scope.get("drafts") or [])[:6], "factsDropped": dropped}


def founder_blocks(section: dict) -> list[dict]:
    """Panel blocks for the receipts (chips the EvidenceDrawer opens) and the drafts waiting for confirmation."""
    from postriff_phase2.site_agent.compose_reads import result_list
    blocks = []
    if section.get("receipts"):
        blocks.append(result_list("Receipts", [{"kind": "receipt", "title": r.get("label") or r["receiptId"], "excerpt": r["receiptId"], "meta": r.get("dataState") or r.get("source"),
                                                "href": None} for r in section["receipts"]]))
    if section.get("drafts"):
        blocks.append(result_list("Waiting for your confirmation", [{"kind": d.get("type"), "title": d.get("title") or d.get("subject") or d.get("kind"),
                                                                     "excerpt": "Draft only; nothing is scheduled, saved or sent until you confirm it in the panel.",
                                                                     "meta": d.get("state") or d.get("delivery"), "href": None} for d in section["drafts"]]))
    return blocks


# --- the public operations (CONTRACTS §3: POST /agent/turns, GET /agent/runs/{id}, GET /agent/conversations/{id}/state, POST /agent/runs/{id}/cancel) ---
def _prepare(service, control_principal, *, mode, control, context, request_id, values, base=None, model_factory=None):
    principal = require_founder(control_principal)
    ops = ops_workspace_id(values)
    founder = founder_scope_for(principal, mode, control, context, request_identifier(request_id))
    runtime, capability = founder_runtime(service, ops, principal["operator"]["user_id"], founder, base=base, model_factory=model_factory)
    return principal, ops, founder, runtime, capability


def _audit_turn(control, principal, request_id, result, error_code=None):
    """One content-free `founder.agent.turn` row in admin_audit_log through the control store (CONTRACTS §3): request id,
    operator, session, environment and outcome. A control object without a store (unit fakes) records nothing; an
    unavailable audit store is logged, since the runtime's own run row already holds the turn."""
    store = getattr(getattr(control, "queries", None), "store", None)
    audit = getattr(store, "audit", None)
    if audit is None:
        return
    try:
        audit(request_id=request_id, actor=principal["operator"]["user_id"], session=(principal.get("session") or {}).get("id"),
              environment=principal["session"]["environment"], action="founder.agent.turn", result=result, error_code=error_code)
    except Exception as error:  # noqa: BLE001 - the audit trail never changes the turn's outcome
        import logging
        logging.getLogger("rafii_control.founder_agent").warning(json.dumps({"event": "founder_agent.audit_unavailable", "result": result, "error": type(error).__name__}))


def _envelope(out: dict, mode: str, environment: str) -> dict:
    """The control envelope's `_receiptIds` and `_dataState` from the stored result's founder section."""
    section = ((out.get("result") or {}).get("founder") or {}) if isinstance(out.get("result"), dict) else {}
    return {**out, "mode": mode, "environment": environment, "namespace": conversation_namespace(mode, environment),
            "_receiptIds": list(section.get("receiptIds") or []), "_dataState": envelope_state(section or {"mode": mode})}


def turn(service, control_principal, body, request_id, *, control=None, values=None, base=None, model_factory=None) -> dict:
    """One founder turn (POST /agent/turns). `service` is the consumer hosted workspace service (the ops workspace lives
    in its database); `control` carries the control services (`.queries`, `.workspace`) and is built from the restricted
    control logins when the caller passes none; `values` is the environment (defaults to os.environ). Returns the
    runtime's stored turn (conversationId, runId, status, messageId, result with `result.founder`, traceId) plus mode,
    environment, namespace and the control envelope fields. 409 POLICY_DISABLED when the ops workspace is not configured."""
    payload = validate_turn(body)
    control = control if control is not None else control_services(values)
    principal, ops, founder, runtime, capability = _prepare(service, control_principal, mode=payload["mode"], control=control, context=payload["pageContext"],
                                                           request_id=request_id, values=values, base=base, model_factory=model_factory)
    environment = principal["session"]["environment"]
    runtime_payload = {"message": payload["message"], "idempotencyKey": runtime_key(payload["mode"], environment, payload["idempotencyKey"]),
                       "modality": payload["modality"], **{k: payload[k] for k in ("timeZone", "locale") if payload.get(k)}}
    try:
        if payload.get("conversationId"):
            runtime.check_conversation(ops, capability, payload["conversationId"])
            runtime_payload["conversationId"] = payload["conversationId"]
        out = runtime.turn(ops, capability, runtime_payload)
    except AlphaError as error:
        _audit_turn(control, principal, founder["request_id"], "denied", error_code=str(getattr(error, "code", None) or "turn_refused")[:64])
        raise control_error(error) from None
    _audit_turn(control, principal, founder["request_id"], "succeeded")
    return {**_envelope(out, payload["mode"], environment), "requestId": founder["request_id"]}


def _founder_run(cur, workspace_id, run_id, operator_id):
    """(mode, environment) of a founder run the operator asked for; None for any other run (the same 404 as a missing one)."""
    cur.execute("SELECT idempotency_key,actor::text FROM public.pr_agent_runs WHERE id::text=%s AND workspace_id=%s", (run_id, workspace_id))
    row = cur.fetchone()
    if not row or not str(row[0]).startswith(RUN_KEY_PREFIX) or row[1] != operator_id:
        return None
    parts = str(row[0])[len(RUN_KEY_PREFIX):].split(":", 2)
    return (parts[0], parts[1]) if len(parts) == 3 and parts[0] in MODES else None


def run(service, control_principal, run_id, request_id=None, *, values=None, base=None) -> dict:
    """The stored result of one founder run (GET /agent/runs/{id}): this founder's own founder runs only; any other run
    is the same 404 as a missing one."""
    if not isinstance(run_id, str) or not _UUID.match(run_id):
        raise ControlError("VALIDATION_FAILED", 400)
    principal, ops, _founder, runtime, capability = _prepare(service, control_principal, mode="live", control=None, context={}, request_id=request_id, values=values, base=base)
    try:
        with runtime.service.repository.transaction(capability, ops) as (cur, _row, _principal):
            found = _founder_run(cur, ops, run_id, principal["operator"]["user_id"])
            if found is None:
                raise AlphaError("Run unavailable.", 404)
            out = runtime._stored(cur, ops, run_id)
    except AlphaError as error:
        raise control_error(error) from None
    return _envelope(out, *found)


stored = run   # the contract's name for the same read


def cancel(service, control_principal, run_id, request_id=None, *, values=None, base=None) -> dict:
    """Stop a running founder turn before its next change (POST /agent/runs/{id}/cancel); the runtime's own cancel path."""
    if not isinstance(run_id, str) or not _UUID.match(run_id):
        raise ControlError("VALIDATION_FAILED", 400)
    principal, ops, _founder, runtime, capability = _prepare(service, control_principal, mode="live", control=None, context={}, request_id=request_id, values=values, base=base)
    try:
        with runtime.service.repository.transaction(capability, ops) as (cur, _row, _principal):
            found = _founder_run(cur, ops, run_id, principal["operator"]["user_id"])
            if found is None:
                raise AlphaError("Run unavailable.", 404)
        out = runtime.cancel(ops, capability, run_id)
    except AlphaError as error:
        raise control_error(error) from None
    return {**out, "mode": found[0], "environment": found[1], "namespace": conversation_namespace(*found), "_dataState": "not_applicable"}


def conversation_state(service, control_principal, conversation_id, request_id=None, *, mode=None, values=None, base=None) -> dict:
    """The conversation's state for the panel (GET /agent/conversations/{id}/state): the active task, images and pending
    approvals of one founder conversation, with the namespace (mode, environment) the conversation was created in. When the
    caller names a `mode`, the conversation must belong to it; otherwise the namespace is read from the conversation."""
    from postriff_phase2.agent_runtime_v2 import service as runtime_service
    if not isinstance(conversation_id, str) or not _UUID.match(conversation_id) or (mode is not None and mode not in MODES):
        raise ControlError("VALIDATION_FAILED", 400)
    principal, ops, founder, runtime, capability = _prepare(service, control_principal, mode=mode or "live", control=None, context={}, request_id=request_id, values=values, base=base)
    try:
        found = runtime.conversation_namespace_of(ops, capability, conversation_id)
        if mode is not None and found != founder["namespace"]:
            raise AlphaError("Conversation unavailable.", 404)
        out = runtime_service.conversation_task(runtime, ops, capability, conversation_id)
    except AlphaError as error:
        raise control_error(error) from None
    mode = found.split(":")[1]
    return {**out, "conversationId": conversation_id, "mode": mode, "environment": principal["session"]["environment"], "namespace": found, "_dataState": "not_applicable"}


# --- LOCAL QA HARNESS: deterministic founder reasoning (RAFII_AGENT_HARNESS=1; tests) --------------------------------------------------
def _publish_incident(outputs) -> str | None:
    """The id of the open publishing incident in this run's attention list output (the harness's 'who was affected' step)."""
    for name, text in outputs:
        if name != "founder_attention_list":
            continue
        try:
            items = (json.loads(text).get("data") or {}).get("items") or []
        except (ValueError, AttributeError):
            continue
        for item in items:
            words = " ".join(str(item.get(k) or "") for k in ("id", "title", "detector", "scope")).lower()
            if item.get("id") and ("publish" in words or "outage" in words):
                return str(item["id"])
    return None


def founder_plan(request: str, context: dict) -> dict:
    """The tool plan for a request, computed from its words (PRD §6.4's seven example questions and their English forms):
    `calls` in order, then the answer text. Deterministic; labelled "harness" wherever it answers."""
    lower = request.lower()
    entity = context.get("selectedEntity") or {}
    chart = context.get("chart") or {}
    if any(w in lower for w in ("三件事", "三件", "three things", "most need", "最需要", "需要我處理", "需要我处理")):
        return {"calls": [("founder_attention_list", {"limit": 3}), ("founder_source_health", {})], "answer": "Here are the three things that most need you today, with their evidence (harness)."}
    if "plan" in lower and any(w in lower for w in ("成本", "cost", "最高", "expensive")):
        return {"calls": [("founder_cost_breakdown", {"dimension": "plan", "period": "mtd"}), ("founder_metric_query", {"metricIds": ["mrr"], "period": "mtd", "groupBy": ["plan"]})],
                "answer": "AI cost by plan and MRR by plan, each as its receipt reports it; no ratio was computed (harness)."}
    if any(w in lower for w in ("成本", "cost", "spend")) and any(w in lower for w in ("上升", "升", "為甚麼", "为什么", "點解", "why", "rise", "up")):
        return {"calls": [("founder_cost_breakdown", {"dimension": "feature", "period": "mtd", "compare": True}), ("founder_attention_list", {"limit": 5})],
                "answer": "AI cost this month by feature beside last month, and the open attention items (harness)."}
    if any(w in lower for w in ("額度", "额度", "quota", "用完", "run out", "credits")):
        return {"calls": [("founder_entity_search", {"collection": "workspaces", "search": "", "view": "quota_80"})], "answer": "Workspaces at 80% or more of their credit quota (harness)."}
    if any(w in lower for w in ("發布", "發佈", "发布", "publish")) and any(w in lower for w in ("失敗", "失败", "fail")):
        return {"calls": [("founder_metric_query", {"metricIds": ["publish_outcomes"], "period": "today", "groupBy": ["status"]}), ("founder_attention_list", {"limit": 5}),
                          ("founder_incident_read", "publish_incident")],
                "answer": "Today's publish outcomes by status, and the open publishing incident with the workspaces it affected (harness)."}
    if any(w in lower for w in ("retention", "留存", "圖", "图", "chart")):
        return {"calls": [("founder_chart_explain", {"chartId": chart.get("chartId") or "retention"})], "answer": "What this chart shows, its denominator and its limits (harness)."}
    if any(w in lower for w in ("付款提醒", "payment reminder", "草擬", "草拟", "draft", "提醒信")):
        args = {"kind": "payment_reminder", **({"customerId": entity["id"]} if entity.get("collection") == "customers" else {})}
        return {"calls": [("founder_draft_message", args)], "answer": "Here is the payment reminder draft for you to read; nothing was sent (harness)."}
    return {"calls": [("founder_source_health", {})], "answer": "The data health strip (harness)."}


def founder_step(call):
    """One ScriptedModel step: the next planned tool not yet called, else the structured reply citing every receipt the
    tools returned (facts with receiptId, a labelled hypothesis, a measurable recommendation, the unknowns)."""
    from agents.testing import assistant_message

    from postriff_phase2.agent_runtime_v2 import harness
    request, app = harness._request(call)
    done = harness._outputs(call)
    called = [name for name, _ in done]
    blob = " ".join(out for _, out in done)
    plan = founder_plan(request, app.get("founderContext") or {})
    for name, args in plan["calls"]:
        if args == "publish_incident":
            incident = _publish_incident(done)
            if incident is None or name in called:
                continue
            return harness._call(name, {"incidentId": incident})
        if name not in called:
            return harness._call(name, args)
    receipts = harness._ids(blob, "receiptId")
    mode = "Demo" if app.get("dataMode") == "demo" else "Live"
    answer = f"{mode} data. " + plan["answer"] + (" Every number is in the tool results below with its receipt." if receipts else " No receipt was returned, so there is no number to report.")
    reply = {"answer": answer, "speakable": contracts.speakable(answer), "language": "en", "follow_ups": [],
             "facts": [{"text": f"The {mode} receipt backing this answer is in the evidence list (harness fact {index + 1}).", "receiptId": receipt} for index, receipt in enumerate(receipts[:5])],
             "hypotheses": ["Hypothesis (harness): a change near the period could explain a movement; the tools showed no mechanism."],
             "recommendations": [{"text": "Watch the metric for two weeks before acting (harness).", "metric": "ai_cost_actual", "period": "14d", "success": "No further rise against the receipt's baseline."}],
             "unknowns": ["Anything the tools reported as unavailable stays unknown (harness)."]}
    return [assistant_message(json.dumps(reply, ensure_ascii=False))]


def founder_model_factory(base_factory=None):
    """model_factory(workload, agent_name) for FounderAgentRuntime: the founder Manager is scripted by `founder_step`; any
    other agent goes to the hosted harness's factory (or an empty script when there is none)."""
    from agents.testing import ModelStep, ScriptedModel

    def factory(workload, name):
        if name == AGENT_NAME:
            return ScriptedModel([ModelStep.respond(founder_step) for _ in range(10)])
        if base_factory is not None:
            return base_factory(workload, name)
        return ScriptedModel([])
    return factory
