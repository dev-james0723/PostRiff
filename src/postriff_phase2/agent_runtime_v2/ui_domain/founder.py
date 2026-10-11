"""J09 — Founder agent, read-only: receipt-backed revenue/cost/reliability/support summaries and drill-down through the
founder console's own tools (`founder_metric_query`, `founder_cost_breakdown`, `founder_attention_list`, `founder_source_health`,
`founder_incident_read`, `founder_entity_search`, `founder_entity_lookup`), run through the single tool gate with the
verified control principal's founder scope.

These bindings exist only in the `founder` scope: the consumer manifest can never carry them (registry and manifest both
refuse), and they run only when the founder route supplies the scope (`DomainContext.founder`, set by the founder route
after `Boundary.authorize` at AAL2). Absent metrics stay `unavailable` (the catalog's own `definition_not_activated`), never
zero; every number travels with its receipt id. No founder action exists in this release.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import common, query

PERIODS = ("today", "7d", "30d", "mtd", "last_month", "90d")
METRIC_ID = {"type": "string", "maxLength": 64, "pattern": r"^[a-z][a-z0-9_]{1,63}$"}
DIMENSION = {"type": "string", "maxLength": 40, "pattern": r"^[a-z][a-z0-9_]{1,40}$"}
PERIOD = {"type": "string", "enum": list(PERIODS)}
COLLECTIONS = ("customers", "workspaces", "subscriptions", "payments", "invoices", "usage", "tickets", "incidents")
SEARCHABLE = ("customers", "workspaces", "subscriptions", "payments", "usage", "tickets")
_DATA_STATES = {"measured": "available", "available": "available", "partial": "partial", "unavailable": "unavailable", "stale": "stale", "empty": "empty"}


def _run(dctx, tool_name: str, args: dict) -> dict:
    """One founder tool through the gate (scope, tenant=founder, role, schema) with this request's founder scope."""
    if not dctx.founder:
        return {"ok": False, "code": "founder_scope_missing", "error": "The founder console scope is not present on this request."}
    from .. import contracts, tool_adapter
    from ..context import RafiiRunContext
    import importlib
    importlib.import_module("rafii_control.founder_tools")   # registers the founder tools (tenant='founder') on first use
    tool = tool_adapter.REGISTRY.get(tool_name)
    if tool is None or tool.spec.tenant != tool_adapter.FOUNDER_TENANT or tool.spec.effect != contracts.READ:
        return {"ok": False, "code": "tool_unavailable", "error": "That founder read isn't available."}
    ctx = RafiiRunContext(service=dctx.service, workspace_id=dctx.workspace_id, token=None, principal=dctx.principal, membership=dctx.member,
                          conversation_id=dctx.artifact["conversation_id"], trace_id=contracts.new_trace_id(), modality="text", zone=dctx.zone,
                          run_id=dctx.artifact.get("parent_run_id"), now=lambda: dctx.now, config=getattr(dctx.runtime, "cfg", None), request_text="")
    ctx.extra = {"founder": {**dctx.founder, "receipts": [], "drafts": [], "links": [], "cache": {}}}
    return tool_adapter.execute(ctx, tool, args, scope=frozenset({tool_name}))


def _result(dctx, out: dict, data_key: str = "rows", *, note=None):
    if not out.get("ok"):
        code = str(out.get("code") or "unavailable")[:60]
        state = "denied" if code in ("tool_forbidden", "forbidden", "tool_tenant") else "unavailable"
        return ui_contracts.query_result(state, as_of=common.iso(dctx.now), note=str(out.get("error") or "This founder data isn't available.")[:240], warnings=[code])
    raw = out.get("dataState")
    state = _DATA_STATES.get(str(raw), "available") if raw else "available"
    items = out.get(data_key)
    count = len(items) if isinstance(items, list) else None
    if state == "available" and count == 0:
        state = "empty"
    coverage = out.get("coverage") if isinstance(out.get("coverage"), dict) else {}
    data = {k: v for k, v in out.items() if k not in ("ok", "verified", "source")}
    receipt = out.get("receiptId")
    return ui_contracts.query_result(state, data, as_of=out.get("calculatedAt") or common.iso(dctx.now), source_refs=[f"receipt:{receipt}"] if receipt else [],
                                     revision=receipt, known=coverage.get("returnedRows") if isinstance(coverage.get("returnedRows"), int) else count,
                                     total=coverage.get("populationTotal") if isinstance(coverage.get("populationTotal"), int) else None,
                                     note=note or "A null value is unavailable, never zero; every number is backed by its receipt.",
                                     warnings=[str(w)[:240] for w in out.get("warnings") or []][:10])


def founder_metrics(dctx, inputs, _cursor):
    args = {"metricIds": list(inputs["metricIds"]), "period": inputs["period"]}
    if inputs.get("groupBy"):
        args["groupBy"] = list(inputs["groupBy"])
    if inputs.get("comparison"):
        args["comparison"] = inputs["comparison"]
    return _result(dctx, _run(dctx, "founder_metric_query", args))


def founder_costs(dctx, inputs, _cursor):
    """founder_cost_breakdown answers {dimension, current: {receiptId, dataState, rows, coverage, …}, previous}: the state, rows and
    coverage of THIS period come from `current` (an unavailable breakdown is never reported available)."""
    out = _run(dctx, "founder_cost_breakdown", {"dimension": inputs["dimension"], "period": inputs["period"], **({"compare": True} if inputs.get("compare") else {})})
    if not out.get("ok"):
        return _result(dctx, out)
    current = out.get("current") if isinstance(out.get("current"), dict) else {}
    flat = {"ok": True, "mode": out.get("mode"), "dimension": out.get("dimension"), "receiptId": current.get("receiptId"), "dataState": current.get("dataState") or "unavailable",
            "rows": current.get("rows") if isinstance(current.get("rows"), list) else [], "coverage": current.get("coverage"), "interval": current.get("interval"),
            "reason": current.get("reason"), "previous": out.get("previous"), "warnings": current.get("warnings") or [], "note": out.get("note")}
    return _result(dctx, flat, note="AI cost by the chosen dimension; an uninstrumented dimension says so instead of estimating.")


def founder_attention(dctx, inputs, _cursor):
    out = _run(dctx, "founder_attention_list", {"limit": inputs.get("limit") or 5, **({"severity": inputs["severity"]} if inputs.get("severity") else {})})
    return _result(dctx, out, "items")


def founder_sources(dctx, _inputs, _cursor):
    return _result(dctx, _run(dctx, "founder_source_health", {}), "sources", note="Each source's own state and last good time; stale is shown as stale.")


def founder_incident(dctx, inputs, _cursor):
    return _result(dctx, _run(dctx, "founder_incident_read", {"incidentId": inputs["incidentId"]}), "timeline")


def founder_search(dctx, inputs, _cursor):
    args = {"collection": inputs["collection"], **{k: inputs[k] for k in ("search", "view", "status", "page") if inputs.get(k) is not None}}
    return _result(dctx, _run(dctx, "founder_entity_search", args), "rows", note="Safe metadata only: no messages, emails or card details.")


def founder_entity(dctx, inputs, _cursor):
    return _result(dctx, _run(dctx, "founder_entity_lookup", {"collection": inputs["collection"], "id": inputs["id"]}), "links",
                   note="Safe metadata and console links only.")


F = {"scope": "founder"}
query("founder_metrics", "J09", "Receipt-backed catalog metrics (revenue such as mrr/cash_collected, AI cost/calls, reliability such as api_error_rate/queue_health, support "
      "such as support_aging, product funnels) for a period, grouped by up to 3 dimensions. Rows carry value or null (unavailable), unit and data state.",
      {"metricIds": {"type": "array", "minItems": 1, "maxItems": 3, "items": METRIC_ID, "uniqueItems": True}, "period": PERIOD,
       "groupBy": {"type": "array", "maxItems": 3, "items": DIMENSION, "uniqueItems": True},
       "comparison": {"type": "string", "enum": ["none", "previous_equal_elapsed", "previous_complete", "cohort_age_aligned"]}},
      founder_metrics, required=("metricIds", "period"), refresh=60, tool="founder_metric_query", **F)
query("founder_costs", "J09", "AI cost for a period by feature, model, plan, workspace or provider, with coverage and receipt.",
      {"dimension": {"type": "string", "enum": ["feature", "model", "plan", "workspace", "provider"]}, "period": PERIOD, "compare": {"type": "boolean"}},
      founder_costs, required=("dimension", "period"), refresh=60, tool="founder_cost_breakdown", **F)
query("founder_attention", "J09", "What needs the founder now (incidents, payment and quota exceptions, stale sources, open requests) by severity, with evidence and links.",
      {"limit": {"type": "integer", "minimum": 1, "maximum": 10}, "severity": {"type": "string", "enum": ["critical", "warning", "info"]}},
      founder_attention, refresh=60, tool="founder_attention_list", **F)
query("founder_sources", "J09", "Data-source health: each source's state (measured, stale, unavailable), last good time and reason.", {}, founder_sources, refresh=60,
      tool="founder_source_health", **F)
query("founder_incident", "J09", "One incident: affected records, known/unknown facts, timeline and notifications.",
      {"incidentId": {"type": "string", "maxLength": 80, "pattern": r"^[A-Za-z0-9:_.-]{1,80}$"}}, founder_incident, required=("incidentId",), refresh=60,
      tool="founder_incident_read", **F)
query("founder_search", "J09", "Bounded search (≤50 rows) over customers, workspaces, subscriptions, payments, usage or support requests; safe metadata only.",
      {"collection": {"type": "string", "enum": list(SEARCHABLE)}, "search": {"type": "string", "maxLength": 160},
       "view": {"type": "string", "enum": ["all", "quota_80", "past_due", "open"]}, "status": {"type": "string", "maxLength": 40},
       "page": {"type": "integer", "minimum": 1, "maximum": 50}}, founder_search, required=("collection",), refresh=60, search=True, tool="founder_entity_search", **F)
query("founder_entity", "J09", "One record by id (customer, workspace, subscription, payment, invoice, usage, request or incident) with linked records and console links.",
      {"collection": {"type": "string", "enum": list(COLLECTIONS)}, "id": {"type": "string", "maxLength": 80, "pattern": r"^[A-Za-z0-9:_.-]{1,80}$"}},
      founder_entity, required=("collection", "id"), refresh=None, tool="founder_entity_lookup", **F)
_ = AlphaError
