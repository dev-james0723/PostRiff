"""The founder console's Rafii tools (Founder Admin v2, CONTRACTS §4; PRD §6.3).

Thirteen tools registered with the agent runtime's `tool_adapter.register`, every one `ToolSpec(tenant='founder')`, so the
gate runs them only inside a founder turn (`ctx.extra['founder']`, set by founder_agent after Boundary.authorize) and
never a workspace tool beside them. Each executor reads the data mode from that scope and answers from the control
services it carries — `QueryService` (receipts), `WorkspaceService` (bounded reads and the Demo dataset) and, when the
metrics slice has installed them, `live_metrics` / `demo_metrics` / `founder_incidents` (imports are guarded and their
call shapes checked, so a missing adapter is an honest `unavailable`, never a crash or a guessed number).

Boundaries kept here:
- READ tools read; the three preparing tools (draft, reminder, report) return text or a draft that waits for the founder's
  confirmation in the panel and store nothing; `founder_incident_ack` is the only mutation and only through the incidents
  module. No refund, ban, delete, deploy, shell, SQL, email, push or call exists here.
- Numbers come from receipts and the Demo dataset's own projections; a tool never invents a total where the source has none
  (missing data is `unavailable`, not zero), and every number travels with the receipt id that backs it.
- Customer records are projected through a field allowlist: no messages, descriptions, emails or card digits reach a model.
- Demo is a data mode, never a fallback: a Live read that cannot be served says so.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import contracts
from postriff_phase2.agent_runtime_v2.context import RafiiRunContext
from postriff_phase2.agent_runtime_v2.tool_adapter import FOUNDER_TENANT, founder_scope, register, wants_to_go

from . import demo_dataset
from .auth import ControlError
from .founder_prompts import PERIODS, REPORT_TIME_ZONE, SECTIONS

FOUNDER_TOOL_NAMES = ("founder_metric_query", "founder_chart_explain", "founder_entity_lookup", "founder_entity_search", "founder_attention_list",
                      "founder_cost_breakdown", "founder_incident_read", "founder_source_health", "founder_draft_message", "founder_reminder_prepare",
                      "founder_report_prepare", "founder_incident_ack", "founder_navigate")
FOUNDER_SCOPE = frozenset(FOUNDER_TOOL_NAMES)
COLLECTIONS = ("customers", "workspaces", "subscriptions", "payments", "invoices", "usage", "tickets", "incidents")
LIVE_COLLECTIONS = ("customers", "workspaces", "subscriptions", "payments", "usage", "tickets")
COST_DIMENSIONS = ("feature", "model", "plan", "workspace", "provider")
SEARCH_VIEWS = ("all", "quota_80", "past_due", "open")
DRAFT_KINDS = ("payment_reminder", "quota_warning", "incident_notice", "custom")
SEVERITIES = ("critical", "warning", "info")
PAGE = demo_dataset.PAGE_SIZE
MAX_ROWS = 50
# Fields of a customer, workspace, subscription, payment, invoice, usage or request record a model may see (PRD §8: safe
# metadata). Emails, descriptions, line items, card digits and provider references are never projected.
SAFE_FIELDS = frozenset({"id", "name", "company", "plan", "planId", "billingCycle", "status", "workspaceIds", "workspaceId", "customerId", "subscriptionId",
                         "invoiceId", "paymentId", "memberCount", "creditsQuota", "creditsUsed", "creditsRemaining", "amountMinor", "currency", "period",
                         "kind", "title", "priority", "at", "createdAt", "renewsAt", "periodStartsAt", "dueAt", "paidAt", "issuedAt", "number", "dimension",
                         "quantity", "unit", "costState", "estimatedUsdMicro", "actualUsdMicro", "dataState", "country", "subscription_status", "terms_version",
                         "member_count", "created_at", "last_seen_at", "workspace_count", "user_id", "deleted", "workspace_id", "renameAllowed", "fictional"})
INCIDENT_FIELDS = ("id", "title", "severity", "state", "classification", "affectedCount", "affectedWorkspaceIds", "affectedSourceIds", "observedAt",
                   "lastGoodAsOf", "known", "unknown", "episodeId", "timeline", "acknowledged", "acknowledgement", "notificationState", "version")
_QUERY_VALUE = re.compile(r"^[A-Za-z0-9:_.-]{1,120}$")
_ID = r"^[A-Za-z0-9:_.-]{1,80}$"
_CONTROL_CODES = {"VALIDATION_FAILED": ("tool_input", 400), "SCOPE_DENIED": ("tool_forbidden", 403), "FOUNDER_REQUIRED": ("tool_forbidden", 403),
                  "STEP_UP_REQUIRED": ("tool_forbidden", 403), "AUTH_REQUIRED": ("tool_forbidden", 403), "BUDGET_EXCEEDED": ("budget", 400),
                  "STALE_PREVIEW": ("stale", 409), "SOURCE_UNAVAILABLE": ("source_unavailable", 503), "RATE_LIMITED": ("rate_limited", 429)}


# --- the founder scope -------------------------------------------------------------------------------------------------
def scope_of(ctx: RafiiRunContext) -> dict:
    """The founder scope of this turn (the gate already refused the tool without one; this is the executor's own check)."""
    founder = founder_scope(ctx)
    if founder is None:
        raise AlphaError("Founder scope unavailable.", 403, code="tool_forbidden")
    return founder


def control_failure(error: ControlError) -> AlphaError:
    """A control-service refusal as the typed failure the gate reports (the code, never the service's internals)."""
    code, status = _CONTROL_CODES.get(error.code, (str(error.code).lower()[:40], error.status))
    return AlphaError(f"Control refused this read ({error.code}).", status, code=code)


def principal_of(founder: dict) -> dict:
    return founder["principal"]


def mode_of(founder: dict) -> str:
    return "demo" if founder.get("mode") == "demo" else "live"


def note_receipt(ctx: RafiiRunContext, founder: dict, receipt_id, *, source: str, label: str, data_state, tool: str) -> None:
    """Record a receipt this turn used: the founder section lists it, and the answer policy then accepts its id."""
    if not isinstance(receipt_id, str) or not receipt_id:
        return
    receipts = founder.setdefault("receipts", [])
    if not any(r["receiptId"] == receipt_id for r in receipts):
        receipts.append({"receiptId": receipt_id, "source": source, "label": label[:80], "dataState": data_state, "tool": tool})
    ctx.ledger.reference("receipt", receipt_id, label)


def note_link(ctx: RafiiRunContext, founder: dict, kind: str, ident, href: str, title: str | None = None) -> dict:
    link = {"type": kind, "id": str(ident), "href": href}
    links = founder.setdefault("links", [])
    if link not in links:
        links.append(link)
    ctx.ledger.reference(kind, str(ident), title)
    return link


def console_href(section: str, **query) -> str:
    """A `/founder/...` link; only allowlisted sections and plain query values (never free text)."""
    if section not in SECTIONS:
        raise AlphaError("Unknown founder section.", 400, code="tool_input")
    path = "/founder" if section == "overview" else f"/founder/{section}"
    kept = {key: str(value) for key, value in query.items() if value not in (None, "") and _QUERY_VALUE.match(str(value))}
    return path + ("?" + urlencode(kept) if kept else "")


def entity_section(collection: str) -> str:
    return {"customers": "customers", "workspaces": "customers", "subscriptions": "revenue", "payments": "revenue", "invoices": "revenue", "usage": "ai-cost",
            "tickets": "support", "incidents": "operations"}.get(collection, "overview")


# How each page opens one record: the URL parameters it reads (customers: `record`, its workspaces tab: `q`; operations:
# `incident`). Collections a page cannot select by id open the tab that lists them.
_ENTITY_QUERY = {
    "customers": lambda ident: {"record": ident},
    "workspaces": lambda ident: {"tab": "workspaces", "q": ident},
    "subscriptions": lambda ident: {"tab": "subscriptions"},
    "payments": lambda ident: {"tab": "payments"},
    "invoices": lambda ident: {"tab": "payments"},
    "usage": lambda ident: {"tab": "reconcile"},
    "tickets": lambda ident: {"tab": "inbox"},
    "incidents": lambda ident: {"tab": "incidents", "incident": ident},
}


def entity_query(collection: str, ident) -> dict:
    return _ENTITY_QUERY.get(collection, lambda _ident: {})(str(ident))


def entity_href(collection: str, ident, mode: str | None = None) -> str:
    """The founder page link that opens one record (or the tab listing it), in Demo when the answer came from Demo."""
    return console_href(entity_section(collection), **entity_query(collection, ident), **({"mode": "demo"} if mode == "demo" else {}))


def adapter(module_name: str, function: str, arity: int):
    """A function of an optional sibling module (live_metrics, demo_metrics, founder_incidents) when it exists and accepts
    `arity` positional arguments; None otherwise, so a missing or differently shaped adapter is reported, never guessed at."""
    try:
        module = importlib.import_module(f"rafii_control.{module_name}")
    except ImportError:
        return None
    fn = getattr(module, function, None)
    if not callable(fn):
        return None
    try:
        parameters = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None
    positional = [p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    required = [p for p in positional if p.default is p.empty]
    if len(required) > arity or (len(positional) < arity and not any(p.kind == p.VAR_POSITIONAL for p in parameters)):
        return None
    return fn


def safe_record(row: dict) -> dict:
    return {key: row[key] for key in row if key in SAFE_FIELDS}


def safe_incident(row: dict) -> dict:
    return {key: row[key] for key in INCIDENT_FIELDS if key in row}


# --- time ------------------------------------------------------------------------------------------------------------------
def _zone(name) -> tuple[ZoneInfo, str]:
    try:
        return ZoneInfo(name), name
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return ZoneInfo(REPORT_TIME_ZONE), REPORT_TIME_ZONE


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def interval_for(ctx: RafiiRunContext, period: str, zone=None) -> dict:
    """A half-open interval [start, end) for a named period in the report time zone (local day boundaries; `today` ends at
    the start of tomorrow, so a day in progress is partial by construction)."""
    if period not in PERIODS:
        raise AlphaError("Unknown period.", 400, code="tool_input")
    tz, zone_name = _zone(zone or REPORT_TIME_ZONE)
    today = datetime.fromtimestamp(ctx.now(), tz).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    first = today.replace(day=1)
    if period == "today":
        start, end = today, tomorrow
    elif period in ("7d", "30d", "90d"):
        start, end = today - timedelta(days=int(period[:-1]) - 1), tomorrow
    elif period == "mtd":
        start, end = first, tomorrow
    else:
        start, end = (first - timedelta(days=1)).replace(day=1), first
    return {"start": _iso(start), "end": _iso(end), "timeZone": zone_name, "label": period}


def previous_interval(interval: dict) -> dict:
    """The equally long interval that ends where this one starts (the comparison period; the tool returns both, never a delta)."""
    start = datetime.fromisoformat(interval["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))
    return {"start": _iso(start - (end - start)), "end": _iso(start), "timeZone": interval["timeZone"], "label": "previous_" + interval["label"]}


def _within(stamp, interval: dict) -> bool:
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.fromisoformat(interval["start"].replace("Z", "+00:00")) <= at < datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))


# --- the Demo dataset --------------------------------------------------------------------------------------------------------
def demo_data(founder: dict) -> dict:
    """The founder's own Demo dataset (full records), read once per turn through WorkspaceService (RLS, revision, receipt)."""
    cache = founder.setdefault("cache", {})
    if "demo" not in cache:
        workspace = founder.get("workspace")
        if workspace is None:
            raise AlphaError("The Demo workspace is not available in this turn.", 503, code="demo_unavailable")
        try:
            cache["demo"] = workspace.demo(principal_of(founder))
        except ControlError as error:
            raise control_failure(error) from None
    return cache["demo"]


def demo_receipt(ctx: RafiiRunContext, founder: dict, data: dict, tool: str) -> dict:
    receipt = demo_dataset.receipt(data)
    note_receipt(ctx, founder, receipt["id"], source="demo", label=f"Demo dataset revision {data.get('revision')} ({receipt.get('scenario', 'normal')})",
                 data_state=receipt.get("dataState"), tool=tool)
    return receipt


def demo_incidents(data: dict) -> list[dict]:
    return [safe_incident(row) for row in data.get("incidents", [])[:20] if isinstance(row, dict) and row.get("id")]


def _demo_rows_for(data: dict, metric_id: str, group_by: list[str], interval: dict) -> list[dict] | None:
    """Rows for one metric id from the Demo dataset's own projections (`analytics`, `summary`, incidents); None when the
    Demo dataset has no definition for it (unavailable, not zero)."""
    analytics, summary = data.get("analytics", {}), data.get("summary", {})
    state = demo_dataset.receipt(data).get("dataState")
    base = {"metricId": metric_id, "definitionVersion": "demo-v1", "dataState": state, "fixture": True, "sourceWatermark": data.get("asOf")}
    if metric_id in ("paid_workspaces", "paid_customers", "subscriptions_by_plan_status"):
        return [{**base, "dimensions": {"plan": row["plan"], "status": "active"}, "value": row["subscribers"], "unit": "count"} for row in analytics.get("planDistribution", [])]
    if metric_id == "mrr":
        return [{**base, "dimensions": {"plan": row["plan"], "currency": row["currency"]}, "value": row["mrrMinor"], "unit": "currency_minor", "currency": row["currency"]}
                for row in analytics.get("planDistribution", [])]
    if metric_id in ("cash_collected", "collections"):
        return [{**base, "dimensions": {"window": row["period"], "currency": row["currency"]}, "value": row["cashMinor"], "unit": "currency_minor", "currency": row["currency"]}
                for row in analytics.get("revenueTrend", [])]
    if metric_id == "payment_failures":
        return [{**base, "dimensions": {}, "value": summary.get("failedPayments"), "unit": "count"}]
    if metric_id in ("open_tickets", "csat"):
        return [{**base, "definitionVersion": "v1", "dimensions": {}, "value": None, "unit": "count" if metric_id == "open_tickets" else "ratio", "dataState": "unavailable", "reason": "demo_not_simulated"}]
    if metric_id == "active_workspaces":
        return [{**base, "dimensions": {}, "value": summary.get("activeSubscriptions"), "unit": "count"}]
    if metric_id in ("ai_cost_actual", "ai_actual_cost"):
        return [{**base, "dimensions": {}, "value": None, "unit": "usd_micro", "dataState": "unavailable", "reason": "demo_usage_has_no_actual_cost"}]
    if metric_id in ("publish_outcomes", "publish_verified", "publish_failed"):
        return _demo_publish_rows(data, base, group_by, interval)
    return None


def _demo_publish_rows(data: dict, base: dict, group_by: list[str], interval: dict) -> list[dict]:
    outages = [row for row in data.get("incidents", []) if row.get("detectorFamily") == "demo_publishing_outage" and row.get("state") != "resolved"
               and _within(row.get("observedAt"), interval)]
    if not outages:
        return [{**base, "dimensions": {"status": "failed"}, "value": 0, "unit": "count", "reason": "no_simulated_outage_in_this_scenario"}]
    if "workspace" in group_by:
        return [{**base, "dimensions": {"workspace": wid, "status": "failed", "incident": row["id"]}, "value": 1, "unit": "count"}
                for row in outages for wid in row.get("affectedWorkspaceIds", [])][:MAX_ROWS]
    return [{**base, "dimensions": {"status": "failed", "incident": row["id"]}, "value": row.get("affectedCount"), "unit": "count"} for row in outages]


# --- the Live services ------------------------------------------------------------------------------------------------------
def live_queries(founder: dict):
    queries = founder.get("queries")
    if queries is None:
        raise AlphaError("The metrics service is not available in this turn.", 503, code="metrics_unavailable")
    return queries


def live_workspace(founder: dict):
    workspace = founder.get("workspace")
    if workspace is None:
        raise AlphaError("The workspace reads are not available in this turn.", 503, code="workspace_unavailable")
    return workspace


def founder_store(founder: dict):
    """The founder record store (incidents, follow-ups, schedules; founder_cron.PostgresFounderStore over the control
    store), built once per turn; None when that slice or the control store is not available."""
    cache = founder.setdefault("cache", {})
    if "fstore" not in cache:
        store = getattr(founder.get("queries"), "store", None)
        try:
            module = importlib.import_module("rafii_control.founder_cron")
        except ImportError:
            module = None
        cls = getattr(module, "PostgresFounderStore", None)
        cache["fstore"] = cls(store, founder.get("environment")) if callable(cls) and store is not None else None
    return cache["fstore"]


def _metric_query(ctx: RafiiRunContext, founder: dict, metric_ids: list[str], interval: dict, group_by: list[str], filters: list[dict], comparison: str, tool: str) -> dict:
    """One receipt-backed metric query through QueryService.metric_query in the turn's data mode (the catalog validates
    ids, dimensions and budget; Live reads the restricted projections, Demo computes the same definitions over the
    founder's Demo dataset) — one receipt per query, stored by the control store. Without a QueryService (unit tests)
    the Demo dataset's own projections answer with the Demo receipt, and Live says metrics are unavailable."""
    mode = mode_of(founder)
    query = {"metricIds": list(metric_ids), "interval": {k: interval[k] for k in ("start", "end", "timeZone")}, "groupBy": list(group_by), "filters": list(filters),
             "comparison": comparison, "limit": 200}
    queries = founder.get("queries")
    data = demo_data(founder) if mode == "demo" else None
    if queries is not None:
        query["groupBy"] = _with_currency(queries, metric_ids, query["groupBy"])
        try:
            result = queries.metric_query(query, principal_of(founder), founder["request_id"], mode=mode, demo_data=data)
        except ControlError as error:
            raise control_failure(error) from None
        note_receipt(ctx, founder, result.get("queryReceiptId"), source=mode, label="Metric query " + ", ".join(metric_ids), data_state=result.get("dataState"), tool=tool)
        return {"receiptId": result.get("queryReceiptId"), "dataState": result.get("dataState"), "rows": (result.get("rows") or [])[:MAX_ROWS], "coverage": result.get("coverage"),
                "executionState": result.get("executionState"), "warnings": result.get("warnings") or [], "interval": interval, "source": mode}
    if mode == "live":
        raise AlphaError("The metrics service is not available in this turn.", 503, code="metrics_unavailable")
    receipt = demo_receipt(ctx, founder, data, tool)
    rows, unsupported = [], []
    for metric_id in metric_ids:
        found = _demo_rows_for(data, metric_id, group_by, interval)
        if found is None:
            unsupported.append(metric_id)
            found = [{"metricId": metric_id, "definitionVersion": None, "dimensions": {}, "value": None, "unit": None, "dataState": "unavailable",
                      "reason": "definition_not_activated_in_demo", "fixture": True}]
        rows.extend(found)
    states = {row.get("dataState") for row in rows}
    return {"receiptId": receipt["id"], "dataState": next(iter(states)) if len(states) == 1 else "partial", "rows": rows[:MAX_ROWS],
            "coverage": {"complete": not unsupported, "returnedRows": min(len(rows), MAX_ROWS), "populationTotal": None, "unsupported": unsupported},
            "executionState": "demo_projection", "warnings": ["Demo dataset: fictional records; not the business."], "interval": interval, "source": "demo"}


def _with_currency(queries, metric_ids: list[str], group_by: list[str]) -> list[str]:
    """Native-currency metrics must be grouped by currency (the catalog refuses cross-currency totals); add it rather than fail."""
    catalog = getattr(queries, "catalog", None)
    metrics = getattr(catalog, "metrics", None) or {}
    needs = any((metrics.get(m) or {}).get("currency_policy") == "native_currency_separate" for m in metric_ids)
    return group_by if not needs or "currency" in group_by or len(group_by) >= 3 else group_by + ["currency"]


# --- tools -------------------------------------------------------------------------------------------------------------------
_PERIOD = {"type": "string", "enum": list(PERIODS), "description": "today | 7d | 30d | mtd | last_month | 90d (half-open, report time zone)."}
_RECEIPT_NOTE = "Every number in the result is backed by receiptId; cite it."


@register(contracts.ToolSpec("founder_metric_query", contracts.READ, "read", "Query catalog metrics by id for a period, grouped by dimensions, with the receipt. "
                             "Returns rows {metricId, dimensions, value, unit, dataState} and coverage; a value of null is unavailable, never zero. " + _RECEIPT_NOTE,
                             tenant=FOUNDER_TENANT),
          {"metricIds": {"type": "array", "maxItems": 3, "required": True, "items": {"type": "string"}},
           "period": {**_PERIOD, "required": True},
           "groupBy": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
           "filters": {"type": "array", "maxItems": 5, "items": {"type": "object"}},
           "comparison": {"type": "string", "enum": ["none", "previous_equal_elapsed", "previous_complete", "cohort_age_aligned"]}},
          "Queried metrics")
def founder_metric_query(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    metric_ids = [m for m in args["metricIds"] if isinstance(m, str) and re.match(r"^[a-z][a-z0-9_]{1,63}$", m)]
    if not metric_ids:
        raise AlphaError("Name at least one metric id.", 400, code="tool_input")
    group_by = [g for g in (args.get("groupBy") or []) if isinstance(g, str) and re.match(r"^[a-z][a-z0-9_]{1,40}$", g)]
    filters = [f for f in (args.get("filters") or []) if isinstance(f, dict) and {"dimension", "operator", "values"} <= set(f)]
    interval = interval_for(ctx, args["period"])
    found = _metric_query(ctx, founder, metric_ids, interval, group_by, filters, args.get("comparison") or "none", "founder_metric_query")
    for row in found["rows"]:
        workspace = (row.get("dimensions") or {}).get("workspace")
        if workspace:
            note_link(ctx, founder, "workspace", workspace, entity_href("workspaces", workspace))
    return {"ok": True, "verified": True, "source": "application", "mode": mode_of(founder), **found,
            "note": "Values are as the receipt reports them; a null value is unavailable, not zero."}


@register(contracts.ToolSpec("founder_chart_explain", contracts.READ, "read", "What the chart on the founder's screen (or chartId) really shows: the rows behind it, "
                             "its definition, denominator and cohort size where the receipt reports them, and its limits. Reads the page context's chart receipt.",
                             tenant=FOUNDER_TENANT),
          {"chartId": {"type": "string", "maxLength": 80}}, "Explained a chart")
def founder_chart_explain(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    chart = (founder.get("context") or {}).get("chart") or {}
    chart_id = args.get("chartId") or chart.get("chartId")
    if not chart_id:
        return {"ok": False, "code": "no_chart", "error": "No chart is selected on the page and none was named."}
    if mode_of(founder) == "demo":
        return _demo_chart(ctx, founder, chart_id, chart)
    queries = live_queries(founder)
    receipt_id = chart.get("queryReceiptId")
    if not receipt_id:
        return {"ok": False, "code": "no_receipt", "error": "The page context carries no receipt for this chart; open the chart's View data first."}
    try:
        receipt = queries.authorized_receipt(receipt_id, principal_of(founder))
    except ControlError as error:
        raise control_failure(error) from None
    rows = (receipt.get("result_rows") or [])[:MAX_ROWS]
    coverage = receipt.get("coverage") or {}
    note_receipt(ctx, founder, receipt.get("id") or receipt_id, source="live", label=f"Chart {chart_id} receipt", data_state=receipt.get("data_state"), tool="founder_chart_explain")
    return {"ok": True, "verified": True, "source": "application", "mode": "live", "chartId": chart_id, "receiptId": receipt.get("id") or receipt_id,
            "dataState": receipt.get("data_state"), "calculatedAt": receipt.get("calculated_at"), "rows": rows, "coverage": coverage,
            "maturedDenominator": coverage.get("denominator"), "cohortSize": coverage.get("denominator"), "knownShare": coverage.get("known"),
            "definitions": receipt.get("metric_versions"), "limits": _receipt_limits(receipt, rows)}


def _receipt_limits(receipt: dict, rows: list[dict]) -> list[str]:
    limits = []
    states = {row.get("dataState") for row in rows}
    if states - {"measured"}:
        limits.append("Some rows are " + ", ".join(sorted(s for s in states if s and s != "measured")) + ": they cannot support a current conclusion.")
    if not (receipt.get("coverage") or {}).get("complete", True):
        limits.append("Coverage is incomplete: the receipt says which population is missing.")
    if (receipt.get("coverage") or {}).get("denominator") in (None, 0):
        limits.append("The receipt reports no matured denominator; a ratio without one is not a retention rate.")
    return limits


def _demo_chart(ctx: RafiiRunContext, founder: dict, chart_id: str, chart: dict) -> dict:
    from .founder_intelligence import CHARTS
    data = demo_data(founder)
    receipt = demo_receipt(ctx, founder, data, "founder_chart_explain")
    historical = bool(chart.get("queryReceiptId")) and chart.get("queryReceiptId") != receipt["id"]
    analytics = data.get("analytics", {})
    key = CHARTS.get(chart_id)
    if key is None:
        return {"ok": True, "verified": True, "source": "application", "mode": "demo", "chartId": chart_id, "receiptId": receipt["id"], "dataState": "not_applicable",
                "rows": [], "maturedDenominator": None, "cohortSize": None, "historical": historical,
                "limits": [f"Chart {chart_id} is not instrumented in the Demo dataset: it has no cohort, denominator or retention records.",
                           "Nothing here measures the business; Demo is fictional."],
                "unknowns": [f"A {chart_id} chart needs a matured cohort denominator and cohort sizes from a receipt; the Demo dataset has none."]}
    rows = analytics.get(key, [])[:MAX_ROWS]
    definitions = {name: analytics[name] for name in ("revenueDefinition", "cashDefinition") if name in analytics}
    return {"ok": True, "verified": True, "source": "application", "mode": "demo", "chartId": chart_id, "receiptId": receipt["id"], "dataState": receipt.get("dataState"),
            "rows": rows, "definitions": definitions, "maturedDenominator": None, "cohortSize": None, "historical": historical,
            "limits": ["Demo dataset: fictional, monthly billing only, simulated cash timing; values use the Demo receipt."]
                      + (["The page's receipt is older than the current Demo revision; these rows are the current ones."] if historical else [])}


@register(contracts.ToolSpec("founder_entity_lookup", contracts.READ, "read", "One customer, workspace, subscription, payment, invoice, usage row, request or incident "
                             "by its id: safe metadata, linked records and console links. Never messages or private content.", tenant=FOUNDER_TENANT),
          {"collection": {"type": "string", "enum": list(COLLECTIONS), "required": True}, "id": {"type": "string", "pattern": _ID, "required": True}},
          "Looked up a record")
def founder_entity_lookup(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    collection, ident = args["collection"], args["id"]
    if collection == "incidents":
        return _incident(ctx, founder, ident)
    mode = mode_of(founder)
    if mode == "live" and collection not in LIVE_COLLECTIONS:
        return {"ok": False, "code": "collection_unavailable", "error": f"Live reads have no {collection} projection yet."}
    body = {"collection": collection, "search": "", "status": "all", "page": 1, "recordId": ident}
    try:
        found = live_workspace(founder).query(principal_of(founder), body, mode)
    except ControlError as error:
        raise control_failure(error) from None
    rows = found.get("rows") or []
    if not rows:
        return {"ok": False, "code": "not_found", "error": "No such record in this data mode."}
    record = safe_record(rows[0])
    href = entity_href(collection, ident, mode)
    note_link(ctx, founder, collection[:-1] if collection.endswith("s") else collection, ident, href, record.get("name") or record.get("title"))
    receipt_id = (found.get("receipt") or {}).get("id")
    if receipt_id:
        note_receipt(ctx, founder, receipt_id, source="demo", label="Demo dataset", data_state=found.get("_dataState"), tool="founder_entity_lookup")
    linked = {name: [safe_record(r) for r in rows_[:10]] for name, rows_ in (found.get("linkedRecords") or {}).items() if name != collection}
    return {"ok": True, "verified": True, "source": "application", "mode": mode, "collection": collection, "record": record, "linked": linked,
            "workspaces": [safe_record(w) for w in (found.get("workspaces") or [])[:10]], "href": href, "receiptId": receipt_id}


def _incident(ctx: RafiiRunContext, founder: dict, ident: str) -> dict:
    mode = mode_of(founder)
    if mode == "demo":
        data = demo_data(founder)
        receipt = demo_receipt(ctx, founder, data, "founder_incident_read")
        incident = next((row for row in demo_incidents(data) if row["id"] == ident), None)
        if incident is None:
            return {"ok": False, "code": "not_found", "error": "No such incident in the Demo scenario."}
        notifications = [{k: e.get(k) for k in ("id", "kind", "channel", "state", "createdAt", "acknowledged")} for e in data.get("notificationEvents", []) if e.get("incidentId") == ident][:10]
        href = console_href("operations", incident=ident, mode="demo")
        note_link(ctx, founder, "incident", ident, href, incident.get("title"))
        _link_affected(ctx, founder, incident.get("affectedWorkspaceIds"), mode="demo")
        return {"ok": True, "verified": True, "source": "application", "mode": "demo", "incident": incident, "notifications": notifications, "href": href, "receiptId": receipt["id"]}
    read, fstore = adapter("founder_incidents", "read_incident", 3), founder_store(founder)
    if read is None or fstore is None:
        return {"ok": False, "code": "incidents_unavailable", "error": "Live incidents are not available in this deployment yet."}
    try:
        found = read(fstore, principal_of(founder), ident)
    except ControlError as error:
        if error.status == 404:
            return {"ok": False, "code": "not_found", "error": "No such incident."}
        raise control_failure(error) from None
    incident = (found or {}).get("incident") if isinstance(found, dict) else None
    if not isinstance(incident, dict):
        return {"ok": False, "code": "not_found", "error": "No such incident."}
    href = incident.get("href") or console_href("operations", incident=ident)
    note_link(ctx, founder, "incident", ident, href, incident.get("detector"))
    evidence = incident.get("evidence") or {}
    _link_affected(ctx, founder, evidence.get("workspaceIds") or evidence.get("affectedWorkspaceIds"), mode="live")
    return {"ok": True, "verified": True, "source": "application", "mode": "live", "incident": incident, "href": href}


def _link_affected(ctx: RafiiRunContext, founder: dict, workspace_ids, *, mode: str) -> None:
    for workspace in (workspace_ids or [])[:20]:
        if isinstance(workspace, str) and _QUERY_VALUE.match(workspace):
            note_link(ctx, founder, "workspace", workspace, entity_href("workspaces", workspace, mode))


@register(contracts.ToolSpec("founder_entity_search", contracts.READ, "read", "Bounded search over customers, workspaces, subscriptions, payments, usage or requests "
                             "(at most 50 rows). view=quota_80 lists workspaces at 80% or more of their credit quota; past_due lists overdue subscriptions; "
                             "open lists open requests.", tenant=FOUNDER_TENANT),
          {"collection": {"type": "string", "enum": list(LIVE_COLLECTIONS), "required": True}, "search": {"type": "string", "maxLength": 160},
           "view": {"type": "string", "enum": list(SEARCH_VIEWS)}, "status": {"type": "string", "maxLength": 40}, "page": {"type": "integer"}},
          "Searched records")
def founder_entity_search(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    mode, view = mode_of(founder), args.get("view") or "all"
    page = args.get("page") if isinstance(args.get("page"), int) and 1 <= args.get("page") <= 1000 else 1
    if view == "quota_80":
        return _quota_view(ctx, founder) if mode == "demo" else {"ok": False, "code": "view_not_instrumented", "verified": False,
                                                                 "error": "Live quota usage per workspace is not instrumented yet (it needs a credit quota projection beside business_usage_v2)."}
    collection = {"past_due": "subscriptions", "open": "tickets"}.get(view, args["collection"])
    status = {"past_due": "past_due", "open": "open" if mode == "demo" else "requested"}.get(view, args.get("status") or "all")
    body = {"collection": collection, "search": args.get("search") or "", "status": status, "page": page, "recordId": ""}
    try:
        found = live_workspace(founder).query(principal_of(founder), body, mode)
    except ControlError as error:
        raise control_failure(error) from None
    rows = [safe_record(r) for r in (found.get("rows") or [])[:MAX_ROWS]]
    for row in rows:
        if row.get("id"):
            note_link(ctx, founder, collection[:-1], row["id"], entity_href(collection, row["id"], mode),
                      row.get("name") or row.get("title"))
    receipt_id = (found.get("receipt") or {}).get("id")
    if receipt_id:
        note_receipt(ctx, founder, receipt_id, source="demo", label="Demo dataset", data_state=found.get("_dataState"), tool="founder_entity_search")
    return {"ok": True, "verified": True, "source": "application", "mode": mode, "collection": collection, "view": view, "rows": rows, "total": found.get("total"),
            "page": page, "pageSize": found.get("pageSize"), "statuses": found.get("statuses"), "receiptId": receipt_id}


def _quota_view(ctx: RafiiRunContext, founder: dict) -> dict:
    data = demo_data(founder)
    receipt = demo_receipt(ctx, founder, data, "founder_entity_search")
    near = []
    for row in data.get("workspaces", []):
        quota, used = row.get("creditsQuota") or 0, row.get("creditsUsed") or 0
        if quota > 0 and used * 5 >= quota * 4:
            near.append({**safe_record(row), "quotaUsedPercent": used * 100 // quota})
    near.sort(key=lambda r: (-r["quotaUsedPercent"], r["id"]))
    rows = near[:MAX_ROWS]
    for row in rows:
        note_link(ctx, founder, "workspace", row["id"], entity_href("workspaces", row["id"], "demo"), row.get("name"))
    return {"ok": True, "verified": True, "source": "application", "mode": "demo", "collection": "workspaces", "view": "quota_80", "rows": rows, "total": len(near),
            "page": 1, "pageSize": MAX_ROWS, "receiptId": receipt["id"], "definition": "creditsUsed / creditsQuota >= 0.8 in the Demo dataset's usage settlement."}


@register(contracts.ToolSpec("founder_attention_list", contracts.READ, "read", "What needs the founder now: open incidents, payment and quota exceptions, stale sources and "
                             "open requests, by severity, with evidence and links. limit caps the list (3 for 'the three things').", tenant=FOUNDER_TENANT),
          {"limit": {"type": "integer"}, "severity": {"type": "string", "enum": list(SEVERITIES)}}, "Listed what needs attention")
def founder_attention_list(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    limit = args.get("limit") if isinstance(args.get("limit"), int) and 1 <= args.get("limit") <= 10 else 5
    mode = mode_of(founder)
    overview, queries = adapter("live_metrics", "overview", 4), founder.get("queries")
    if overview is not None and queries is not None:
        try:
            found = overview(principal_of(founder), mode, "30d", queries, request_id=founder["request_id"])
        except ControlError as error:
            raise control_failure(error) from None
        items = [i for i in (found.get("attention") or []) if isinstance(i, dict)]
        for receipt_id in (found.get("_receiptIds") or (found.get("brief") or {}).get("receiptIds") or [])[:20]:
            note_receipt(ctx, founder, receipt_id, source=mode, label="Overview brief", data_state=None, tool="founder_attention_list")
        source = "live_metrics.overview"
    elif mode == "demo":
        items, source = _demo_attention(ctx, founder), "demo_dataset"
    else:
        return {"ok": False, "code": "attention_unavailable", "error": "Live attention items need the overview adapter (live_metrics), which is not installed yet."}
    if args.get("severity"):
        items = [i for i in items if i.get("severity") == args["severity"]]
    rank = {name: index for index, name in enumerate(SEVERITIES)}
    items.sort(key=lambda i: rank.get(i.get("severity"), len(SEVERITIES)))
    kept = items[:limit]
    for item in kept:
        if item.get("href") and item.get("id"):
            note_link(ctx, founder, "attention", item["id"], item["href"], item.get("title"))
    return {"ok": True, "verified": True, "source": "application", "mode": mode, "items": kept, "total": len(items), "listedBy": source,
            "receiptIds": [r["receiptId"] for r in founder.get("receipts", [])]}


def _demo_attention(ctx: RafiiRunContext, founder: dict) -> list[dict]:
    data = demo_data(founder)
    receipt = demo_receipt(ctx, founder, data, "founder_attention_list")
    summary, items = data.get("summary", {}), []
    for incident in demo_incidents(data):
        if incident.get("state") in ("resolved",):
            continue
        items.append({"id": incident["id"], "severity": "critical" if incident.get("severity") == "critical" else "warning", "title": incident.get("title"), "scope": "operations",
                      "count": incident.get("affectedCount"), "since": incident.get("observedAt"), "state": incident.get("state"), "receiptId": receipt["id"],
                      "href": console_href("operations", incident=incident["id"], mode="demo"),
                      # Same {id,label,kind,href} shape as the Live overview; Demo incidents carry no ack (no version is
                      # ever acknowledged from Demo, CONTRACTS §3), so only explain/open are offered.
                      "actions": [{"id": "explain", "label": "Explain", "kind": "explain", "href": None},
                                  {"id": "open", "label": "Open", "kind": "open", "href": console_href("operations", incident=incident["id"], mode="demo")}]})
    if receipt.get("dataState") == "stale":
        items.append({"id": "demo-stale-source", "severity": "critical", "title": "Source data is stale", "scope": "data", "count": None, "since": receipt.get("lastGoodAsOf"),
                      "receiptId": receipt["id"], "href": console_href("advanced", mode="demo"), "actions": []})
    for key, title, scope, severity in (("billingReviews", "Subscriptions past due or in grace", "revenue", "warning"), ("failedPayments", "Failed payments", "revenue", "warning"),
                                        ("openRequests", "Open customer requests", "support", "info")):
        count = summary.get(key)
        if isinstance(count, int) and count > 0:
            items.append({"id": f"demo-{key}", "severity": severity, "title": title, "scope": scope, "count": count, "since": data.get("asOf"), "receiptId": receipt["id"],
                          "href": console_href("revenue" if scope == "revenue" else "support", mode="demo"), "actions": []})
    near = sum(1 for w in data.get("workspaces", []) if (w.get("creditsQuota") or 0) > 0 and (w.get("creditsUsed") or 0) * 10 >= (w.get("creditsQuota") or 0) * 9)
    if near:
        items.append({"id": "demo-quota-90", "severity": "warning", "title": "Workspaces at 90% or more of their credit quota", "scope": "customers", "count": near,
                      "since": data.get("asOf"), "receiptId": receipt["id"], "href": console_href("customers", mode="demo"), "actions": []})
    return items


@register(contracts.ToolSpec("founder_cost_breakdown", contracts.READ, "read", "AI cost for a period by feature, model, plan, workspace or provider, with coverage and the "
                             "receipt; compare: true also returns the previous period's rows (both are returned; no delta is computed for you). " + _RECEIPT_NOTE,
                             tenant=FOUNDER_TENANT),
          {"dimension": {"type": "string", "enum": list(COST_DIMENSIONS), "required": True}, "period": {**_PERIOD, "required": True}, "compare": {"type": "boolean"}},
          "Broke down AI cost")
def founder_cost_breakdown(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    interval = interval_for(ctx, args["period"])
    if args["dimension"] == "workspace" and founder.get("queries") is not None:
        return {"ok": False, "code": "dimension_not_instrumented", "error": "AI cost by workspace is not a catalog dimension (feature, model, plan, provider are); "
                                                                           "ask for a plan or feature breakdown, or look up one workspace."}
    if mode_of(founder) == "demo" and founder.get("queries") is None:
        current = _demo_cost(ctx, founder, args["dimension"], interval)
        previous = {"dataState": "unavailable", "reason": "demo_single_period", "rows": []} if args.get("compare") else None
    else:
        metric = "ai_cost_by_feature" if args["dimension"] == "feature" else "ai_cost_actual"
        current = _metric_query(ctx, founder, [metric], interval, [args["dimension"]], [], "none", "founder_cost_breakdown")
        previous = _metric_query(ctx, founder, [metric], previous_interval(interval), [args["dimension"]], [], "none", "founder_cost_breakdown") if args.get("compare") else None
    for row in current.get("rows", []):
        workspace = (row.get("dimensions") or {}).get("workspace")
        if workspace:
            note_link(ctx, founder, "workspace", workspace, entity_href("workspaces", workspace))
    return {"ok": True, "verified": True, "source": "application", "mode": mode_of(founder), "dimension": args["dimension"], "current": current, "previous": previous,
            "note": "Costs are native USD micro-units per row; never add rows across currencies or periods yourself. A null value is unavailable."}


def _demo_cost(ctx: RafiiRunContext, founder: dict, dimension: str, interval: dict) -> dict:
    data = demo_data(founder)
    receipt = demo_receipt(ctx, founder, data, "founder_cost_breakdown")
    if dimension in ("model", "provider"):
        return {"receiptId": receipt["id"], "dataState": "unavailable", "rows": [], "reason": f"demo_usage_has_no_{dimension}", "interval": interval, "source": "demo"}
    groups: dict[str, dict] = {}
    for row in data.get("usage", []):
        key = {"plan": row.get("plan"), "workspace": row.get("workspaceId"), "feature": row.get("dimension")}[dimension]
        group = groups.setdefault(str(key), {"dimensions": {dimension: key}, "estimatedUsdMicro": 0, "creditsUsed": 0, "rows": 0, "actualUsdMicro": None})
        group["estimatedUsdMicro"] += int(row.get("estimatedUsdMicro") or 0)
        group["creditsUsed"] += int(row.get("creditsUsed") or 0)
        group["rows"] += 1
    rows = sorted(groups.values(), key=lambda g: (-g["estimatedUsdMicro"], str(g["dimensions"])))[:10]
    for row in rows:
        row.update(unit="usd_micro", currency="USD", costState="simulated", dataState=receipt.get("dataState"), fixture=True)
    return {"receiptId": receipt["id"], "dataState": receipt.get("dataState"), "rows": rows, "coverage": {"complete": True, "returnedRows": len(rows), "groups": len(groups)},
            "interval": interval, "source": "demo", "warnings": ["Demo usage carries estimated cost only (actual cost is unavailable)."]}


@register(contracts.ToolSpec("founder_incident_read", contracts.READ, "read", "An incident with its affected records, known/unknown facts, timeline and notifications.",
                             tenant=FOUNDER_TENANT),
          {"incidentId": {"type": "string", "pattern": _ID, "required": True}}, "Read an incident")
def founder_incident_read(ctx: RafiiRunContext, args: dict) -> dict:
    return _incident(ctx, scope_of(ctx), args["incidentId"])


@register(contracts.ToolSpec("founder_source_health", contracts.READ, "read", "The data health strip: each source's state (measured, stale, unavailable), last good "
                             "time and reason code.", tenant=FOUNDER_TENANT),
          {}, "Checked source health")
def founder_source_health(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    mode = mode_of(founder)
    if founder.get("queries") is not None:
        found = _metric_query(ctx, founder, ["source_health"], interval_for(ctx, "today"), ["source", "state", "reason"], [], "none", "founder_source_health")
        sources = [{"sourceId": (row.get("dimensions") or {}).get("source"), "state": (row.get("dimensions") or {}).get("state") or row.get("dataState"),
                    "lastGoodAt": row.get("sourceWatermark"), "reasonCode": (row.get("dimensions") or {}).get("reason") or row.get("reason"), "dataState": row.get("dataState")}
                   for row in found["rows"]]
        return {"ok": True, "verified": True, "source": "application", "mode": mode, "sources": sources, "receiptId": found["receiptId"], "dataState": found["dataState"]}
    if mode == "demo":
        data = demo_data(founder)
        receipt = demo_receipt(ctx, founder, data, "founder_source_health")
        stale = receipt.get("dataState") == "stale"
        sources = [{"sourceId": c.get("id"), "state": "stale" if stale else "measured", "lastGoodAt": receipt.get("lastGoodAsOf") or data.get("asOf"),
                    "reasonCode": "simulated_stale_source" if stale else None, "label": c.get("label")} for c in data.get("connections", [])]
        return {"ok": True, "verified": True, "source": "application", "mode": "demo", "sources": sources, "receiptId": receipt["id"]}
    try:
        rows = live_queries(founder).source_health()
    except ControlError as error:
        raise control_failure(error) from None
    sources = [{"sourceId": r.get("source_id"), "state": r.get("state"), "lastGoodAt": r.get("watermark"), "reasonCode": r.get("reason_code") or r.get("reason"),
                "qualified": r.get("qualified")} for r in rows[:MAX_ROWS]]
    return {"ok": True, "verified": True, "source": "application", "mode": "live", "sources": sources}


@register(contracts.ToolSpec("founder_draft_message", contracts.CREATE_DRAFT, "edit", "Draft a payment reminder, quota warning or customer notice as TEXT for the founder "
                             "to read. Nothing is sent, stored or addressed: the result names the recipient class and any placeholder the data could not fill.",
                             tenant=FOUNDER_TENANT, idempotent=True),
          {"kind": {"type": "string", "enum": list(DRAFT_KINDS), "required": True}, "customerId": {"type": "string", "pattern": _ID}, "workspaceId": {"type": "string", "pattern": _ID},
           "language": {"type": "string", "enum": ["en", "zh-Hant", "zh-Hans"]}, "notes": {"type": "string", "maxLength": 400}},
          "Drafted a message (not sent)")
def founder_draft_message(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    facts = _recipient_facts(ctx, founder, args.get("customerId"), args.get("workspaceId"))
    language = args.get("language") or ("zh-Hant" if re.search(r"[一-鿿]", ctx.request_text or "") else "en")
    subject, body, placeholders = _draft_text(args["kind"], facts, language, args.get("notes"))
    draft_id = "draft-" + hashlib.sha256(json.dumps([args["kind"], facts.get("customerId"), body], sort_keys=True).encode()).hexdigest()[:12]
    draft = {"draftId": draft_id, "kind": args["kind"], "recipientClass": "customer owner", "recipient": {k: facts.get(k) for k in ("customerId", "workspaceId", "name")},
             "subject": subject, "body": body, "placeholders": placeholders, "language": language, "delivery": "none", "persisted": False, "mode": mode_of(founder),
             "receiptId": facts.get("receiptId")}
    founder.setdefault("drafts", []).append({"type": "message", **draft})
    ctx.ledger.facts.append({"text": "A message draft was returned as text only; nothing was sent or stored.", "kind": "derived", "rule": "founder_draft_message"})
    return {"ok": True, "verified": False, "stored": False, "source": "application", **draft,
            "note": "Text only. The founder console has no sending path; say 'here is the draft', never that it was sent or prepared for sending."}


def _recipient_facts(ctx: RafiiRunContext, founder: dict, customer_id, workspace_id) -> dict:
    """Who the draft is for and what the data says about their account, from the data mode's records (never guessed)."""
    mode = mode_of(founder)
    if mode == "demo":
        data = demo_data(founder)
        receipt = demo_receipt(ctx, founder, data, "founder_draft_message")
        customer = _demo_customer(data, customer_id, workspace_id)
        if customer is None:
            return {"receiptId": receipt["id"], "mode": "demo"}
        subscription = next((s for s in data.get("subscriptions", []) if s.get("customerId") == customer["id"]), None) or {}
        invoice = next((i for i in data.get("invoices", []) if i.get("id") == subscription.get("currentInvoiceId")), None) or {}
        workspace = next((w for w in data.get("workspaces", []) if w.get("customerId") == customer["id"]), None) or {}
        note_link(ctx, founder, "customer", customer["id"], entity_href("customers", customer["id"], "demo"), customer.get("name"))
        return {"receiptId": receipt["id"], "mode": "demo", "customerId": customer["id"], "name": customer.get("name"), "company": customer.get("company"), "plan": customer.get("plan"),
                "workspaceId": workspace.get("id"), "subscriptionStatus": subscription.get("status"), "invoiceNumber": invoice.get("number"), "invoiceStatus": invoice.get("status"),
                "amountMinor": invoice.get("amountMinor"), "currency": invoice.get("currency"), "dueAt": invoice.get("dueAt"),
                "creditsUsed": workspace.get("creditsUsed"), "creditsQuota": workspace.get("creditsQuota")}
    if not customer_id and not workspace_id:
        return {"mode": "live"}
    collection, ident = ("customers", customer_id) if customer_id else ("workspaces", workspace_id)
    try:
        found = live_workspace(founder).query(principal_of(founder), {"collection": collection, "search": "", "status": "all", "page": 1, "recordId": ident}, "live")
    except ControlError as error:
        raise control_failure(error) from None
    rows = found.get("rows") or []
    if not rows:
        return {"mode": "live"}
    record = safe_record(rows[0])
    note_link(ctx, founder, collection[:-1], ident, entity_href(collection, ident), record.get("name"))
    return {"mode": "live", "customerId": record.get("id") if collection == "customers" else None, "workspaceId": record.get("id") if collection == "workspaces" else None,
            "name": record.get("name"), "plan": record.get("plan"), "subscriptionStatus": record.get("status")}


def _demo_customer(data: dict, customer_id, workspace_id):
    customers = data.get("customers", [])
    if customer_id:
        return next((c for c in customers if c.get("id") == customer_id), None)
    if workspace_id:
        workspace = next((w for w in data.get("workspaces", []) if w.get("id") == workspace_id), None)
        return next((c for c in customers if workspace and c.get("id") == workspace.get("customerId")), None)
    overdue = next((s for s in data.get("subscriptions", []) if s.get("status") in ("past_due", "grace")), None)
    return next((c for c in customers if overdue and c.get("id") == overdue.get("customerId")), None)


def _draft_text(kind: str, facts: dict, language: str, notes) -> tuple[str, str, list[str]]:
    """Deterministic draft text; every value the data did not supply is a visible placeholder, never an invented one."""
    placeholders = []

    def value(key, label):
        if facts.get(key) in (None, ""):
            placeholders.append(label)
            return f"[{label}]"
        return str(facts[key])

    name = value("name", "customer name")
    amount = (f"{facts['amountMinor'] / 100:.2f} {facts.get('currency') or ''}".strip() if isinstance(facts.get("amountMinor"), int) and facts.get("currency")
              else "[invoice amount]")
    if amount.startswith("["):
        placeholders.append("invoice amount")
    invoice, due = value("invoiceNumber", "invoice number"), value("dueAt", "due date")
    quota = (f"{facts['creditsUsed']} of {facts['creditsQuota']}" if isinstance(facts.get("creditsUsed"), int) and isinstance(facts.get("creditsQuota"), int) else "[credits used of quota]")
    if quota.startswith("["):
        placeholders.append("credits used of quota")
    extra = (" " + str(notes).strip()) if isinstance(notes, str) and notes.strip() else ""
    zh = language.startswith("zh")
    if kind == "payment_reminder":
        subject = f"付款提醒：發票 {invoice}" if zh else f"Payment reminder: invoice {invoice}"
        body = (f"{name} 你好，\n\n發票 {invoice}（{amount}）的付款仍未完成，到期日為 {due}。請更新付款方式或完成付款，以免服務中斷。{extra}\n\nRafii 團隊" if zh else
                f"Hi {name},\n\nInvoice {invoice} for {amount} is still unpaid; it was due on {due}. Please update your payment method or complete the payment so your "
                f"workspace stays active.{extra}\n\nThe Rafii team")
    elif kind == "quota_warning":
        subject = "額度提醒" if zh else "Your credit quota is almost used up"
        body = (f"{name} 你好，\n\n你的工作區本月已使用 {quota} 點數。{extra}\n\nRafii 團隊" if zh else
                f"Hi {name},\n\nYour workspace has used {quota} credits this month.{extra}\n\nThe Rafii team")
    elif kind == "incident_notice":
        subject = "服務狀況通知" if zh else "Service notice"
        body = (f"{name} 你好，\n\n我們正在處理一個影響你工作區的問題。{extra}\n\nRafii 團隊" if zh else
                f"Hi {name},\n\nWe are working on an issue that affected your workspace.{extra}\n\nThe Rafii team")
    else:
        subject = "來自 Rafii 的通知" if zh else "A note from Rafii"
        body = (f"{name} 你好，\n\n{extra.strip() or '[message]'}\n\nRafii 團隊" if zh else f"Hi {name},\n\n{extra.strip() or '[message]'}\n\nThe Rafii team")
    return subject, body, list(dict.fromkeys(placeholders))


def _confirmation(founder: dict, kind: str) -> dict:
    if mode_of(founder) == "demo":
        return {"where": "panel", "how": "Demo sandbox action " + ("founder_report_schedule" if kind == "report" else "founder_reminder") + " with confirmed: true", "external": False}
    return {"where": "panel", "how": "POST /api/control/v2/" + ("briefing-schedules" if kind == "report" else "follow-ups"), "external": False}


@register(contracts.ToolSpec("founder_reminder_prepare", contracts.PREPARE_EXTERNAL, "edit", "Prepare a follow-up reminder (title, due local time, time zone, what it is "
                             "about) as a draft that waits for the founder's confirmation in the panel. Nothing is scheduled until they confirm.",
                             tenant=FOUNDER_TENANT, approval=True, idempotent=False),
          {"title": {"type": "string", "maxLength": 200, "required": True}, "dueLocal": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?$"},
           "timeZone": {"type": "string", "maxLength": 80}, "sourceType": {"type": "string", "enum": ["conversation", "incident", "customer", "workspace", "report"]},
           "sourceId": {"type": "string", "pattern": _ID}},
          "Prepared a reminder draft (needs confirmation)")
def founder_reminder_prepare(ctx: RafiiRunContext, args: dict) -> dict:
    from .founder_intelligence import resolve_local_time
    founder = scope_of(ctx)
    zone = args.get("timeZone") or REPORT_TIME_ZONE
    due_local = (args["dueLocal"] + (":00" if len(args["dueLocal"]) == 16 else "")) if args.get("dueLocal") else None
    due_at = None
    if due_local:
        try:
            due_at = resolve_local_time(due_local, zone)
        except ControlError:
            raise AlphaError("The due time or time zone is not valid.", 400, code="tool_input") from None
    draft = {"type": "reminder", "state": "draft", "title": args["title"].strip(), "dueLocal": due_local, "timeZone": zone, "dueAt": due_at,
             "sourceType": args.get("sourceType") or "conversation", "sourceId": args.get("sourceId") or ctx.conversation_id, "mode": mode_of(founder),
             "environment": founder.get("environment"), "receiptIds": [r["receiptId"] for r in founder.get("receipts", [])], "confirm": _confirmation(founder, "reminder")}
    founder.setdefault("drafts", []).append(draft)
    ctx.ledger.warn("founder_confirmation_required", "A reminder draft is ready in the panel; nothing is scheduled until you confirm it." if due_at else
                    "A reminder draft is ready in the panel; pick its due time and confirm it, or nothing is scheduled.")
    return {"ok": True, "verified": False, "needsUser": True, "source": "application", "draft": draft,
            "note": "Draft only: it waits for the founder's confirmation in the panel. Say that; never say it is scheduled or set."}


@register(contracts.ToolSpec("founder_report_prepare", contracts.PREPARE_EXTERNAL, "edit", "Prepare a daily or weekly briefing schedule, or a one-off report now, as a "
                             "draft built from this turn's receipts that waits for the founder's confirmation in the panel. Nothing is generated or delivered until then.",
                             tenant=FOUNDER_TENANT, approval=True, idempotent=False),
          {"kind": {"type": "string", "enum": ["daily", "weekly", "now"], "required": True}, "title": {"type": "string", "maxLength": 200},
           "localTime": {"type": "string", "pattern": r"^\d{2}:\d{2}$"}, "timeZone": {"type": "string", "maxLength": 80}},
          "Prepared a report draft (needs confirmation)")
def founder_report_prepare(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    zone = args.get("timeZone") or REPORT_TIME_ZONE
    _zone(zone)
    receipts = [r["receiptId"] for r in founder.get("receipts", [])]
    draft = {"type": "report", "state": "draft", "kind": args["kind"], "title": (args.get("title") or f"{args['kind']} briefing").strip()[:200], "localTime": args.get("localTime"),
             "timeZone": zone, "sections": [{"title": "Receipts this turn", "receiptIds": receipts}, {"title": "Facts", "text": None}, {"title": "Attention", "text": None}],
             "mode": mode_of(founder), "environment": founder.get("environment"), "receiptIds": receipts, "confirm": _confirmation(founder, "report")}
    founder.setdefault("drafts", []).append(draft)
    ctx.ledger.warn("founder_confirmation_required", "A report draft is ready in the panel; nothing is generated or scheduled until you confirm it.")
    return {"ok": True, "verified": False, "needsUser": True, "source": "application", "draft": draft,
            "note": "Draft only: the briefing is composed from receipts after the founder confirms. Never say it is scheduled or sent."}


@register(contracts.ToolSpec("founder_incident_ack", contracts.MUTATE_REVERSIBLE, "edit", "Acknowledge one incident at its exact version: escalation stops; the incident "
                             "is NOT resolved. Demo incidents are acknowledged from the Operations page, not here.", tenant=FOUNDER_TENANT, idempotent=False, audit="incidents.ack"),
          {"incidentId": {"type": "string", "pattern": _ID, "required": True}, "version": {"type": "integer", "required": True}}, "Acknowledged an incident")
def founder_incident_ack(ctx: RafiiRunContext, args: dict) -> dict:
    founder = scope_of(ctx)
    if mode_of(founder) == "demo":
        return {"ok": False, "code": "demo_read_only", "error": "The agent only reads the Demo scenario; acknowledge a Demo incident from the Operations page."}
    acknowledge, fstore = adapter("founder_incidents", "acknowledge", 4), founder_store(founder)
    if acknowledge is None or fstore is None:
        return {"ok": False, "code": "incidents_unavailable", "error": "Live incidents are not available in this deployment yet."}
    try:
        outcome = acknowledge(fstore, args["incidentId"], args["version"], founder["operatorId"], now=ctx.now(), channel="web")
    except ControlError as error:
        if error.status == 404:
            return {"ok": False, "code": "not_found", "error": "No such incident."}
        if error.code == "STALE_PREVIEW":
            return {"ok": False, "code": "stale_version", "error": "That incident has moved on since this version; read it again before acknowledging."}
        raise control_failure(error) from None
    incident = (outcome or {}).get("incident") if isinstance(outcome, dict) else None
    if not isinstance(incident, dict):
        return {"ok": False, "code": "ack_unverified", "error": "The acknowledgement returned no incident to re-read."}
    verified = incident.get("acknowledgedAt") is not None
    ctx.ledger.changed.append({"type": "incident", "id": args["incidentId"], "change": "acknowledged", "verified": verified, "expected": "acknowledged",
                               "actual": incident.get("state")})
    note_link(ctx, founder, "incident", args["incidentId"], incident.get("href") or entity_href("incidents", args["incidentId"]))
    return {"ok": True, "verified": verified, "source": "application", "incident": incident, "replayed": bool(outcome.get("replayed")),
            "cancelledAttempts": outcome.get("cancelledAttempts"), "note": "Acknowledged is not resolved: the incident stays open until its detector sees recovery."}


@register(contracts.ToolSpec("founder_navigate", contracts.READ, "read", "Put a link to one founder console section in the answer (optionally focused on an entity "
                             "or incident). auto: true ONLY when the founder explicitly asked to open or go to it.", tenant=FOUNDER_TENANT),
          {"section": {"type": "string", "enum": list(SECTIONS), "required": True}, "entityCollection": {"type": "string", "enum": list(COLLECTIONS)},
           "entityId": {"type": "string", "pattern": _ID}, "incidentId": {"type": "string", "pattern": _ID}, "auto": {"type": "boolean"}},
          "Linked a console page")
def founder_navigate(ctx: RafiiRunContext, args: dict) -> dict:
    from postriff_phase2.site_agent import contracts as site_contracts
    founder = scope_of(ctx)
    # An incident or entity opens on its own page with the parameters that page reads; otherwise the section itself.
    section, query = args["section"], {}
    if args.get("incidentId"):
        section, query = "operations", entity_query("incidents", args["incidentId"])
    elif args.get("entityCollection") and args.get("entityId"):
        section, query = entity_section(args["entityCollection"]), entity_query(args["entityCollection"], args["entityId"])
    href = console_href(section, **query, **({"mode": "demo"} if mode_of(founder) == "demo" else {}))
    title = {"overview": "Overview", "ai-cost": "AI cost"}.get(section, section.capitalize())
    auto = args.get("auto") is True and wants_to_go(ctx.request_text)
    ctx.ledger.navigation.append(site_contracts.navigation(f"Open {title}", href, "founder_" + section.replace("-", "_"), auto=auto))
    note_link(ctx, founder, "section", section, href, title)
    return {"ok": True, "verified": True, "source": "application", "href": href, "title": title, "opensNow": auto, "canOpen": True}


def register_all() -> None:
    """Importing this module registers the tools; this is the explicit hook for callers that want to say so."""
    return None
