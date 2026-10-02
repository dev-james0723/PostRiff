"""Typed business-result tools for Agent Runtime v2 (plan G2-OUT, PRD R-ENG-01, AC28).

Registered into the runtime's single registry, so every call passes its gate (scope, voice parity, permission re-check,
cancellation, schema). Each executor goes through ResultsService, which re-checks the person's workspace permission in
its own transaction, exactly as the web routes do; voice and text have the same authority. Nothing here sends,
publishes, charges or calls a paid service: a declaration and a tracking link are reversible workspace records
(reverse / turn off). Each tool answers ``feature_disabled`` while RAFII_RESULTS_ENABLED is off.

``register()`` is idempotent; the coordinator wires it into ``skill_registry.registered_tools()`` and adds the names
to specialists' scopes (TOOL_SCOPES is the proposal).
"""
from __future__ import annotations

import hashlib
import json

TOOL_SCOPES = {
    "results_summary": ["rafii_manager", "analytics"],
    "result_declare": ["rafii_manager", "analytics"],
    "tracking_link_create": ["content", "analytics"],
}
LABELS = {"provider_native": "Platform-reported", "first_party_reported": "Reported by your connected tool", "user_declared": "You reported"}
_REGISTERED = False


def _disabled():
    return {"ok": False, "code": "feature_disabled", "message": "RAFII_RESULTS_ENABLED is off, so this tool is unavailable.", "verified": False}


def _app_error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _results(ctx):
    from .http import ensure
    return ensure(ctx.service)


def _key(ctx, tool, args):
    """One intent per run: a retried identical call replays instead of recording a second result."""
    run = getattr(ctx, "run_id", None) or getattr(ctx, "trace_id", None) or getattr(ctx, "conversation_id", None)
    seed = json.dumps({"run": run, "tool": tool, "args": args}, sort_keys=True, default=str)
    return "agent-" + hashlib.sha256(seed.encode()).hexdigest()[:40]


def register():
    global _REGISTERED
    if _REGISTERED:
        return
    from ..agent_runtime_v2 import contracts, tool_adapter
    if "results_summary" in tool_adapter.REGISTRY:
        _REGISTERED = True
        return
    from postriff_alpha.domain import AlphaError
    from . import service

    @tool_adapter.register(contracts.ToolSpec(
        "results_summary", contracts.READ, "read",
        "The workspace's own business results (leads, bookings, sign-ups, sales) for a period, kept apart by source: results the person "
        "reported, results their connected form or booking tool reported, and platform metrics (not connected in this release). Counts and "
        "per-currency amounts only; never one blended number, never a claim that Rafii caused them. Tracking-link clicks are clicks, not people.",
        voice=True), {"days": {"type": "integer"}}, "Read business results")
    def results_summary(ctx, args):
        if not service.enabled():
            return _disabled()
        days = args.get("days") or 30
        if not 1 <= days <= 365:
            return {"ok": False, "verified": False, "code": "tool_input", "message": "Choose 1–365 days."}
        results = _results(ctx)
        now = results.clock()
        try:
            data = results.summary(ctx.workspace_id, ctx.token, start=now - days * 86400, end=now)
        except AlphaError as error:
            return _app_error(error)
        classes = {name: ({"label": LABELS[name], **value} if value else {"label": LABELS[name], "available": False}) for name, value in data["classes"].items()}
        return {"ok": True, "verified": True, "data": {"days": days, "dataState": data["dataState"], "periodOpen": data["period"]["open"],
                                                         "classes": classes, "clicks": data["clicks"], "testEvents": data["testEvents"],
                                                         "quarantined": data["quarantined"], "coverage": data["coverage"],
                                                         "rules": ["Never add the classes together or convert currencies.",
                                                                   "A class marked unavailable has no data; it is not zero.",
                                                                   "Associated means the result carried this workspace's own link; it is not proof of cause."]}}

    @tool_adapter.register(contracts.ToolSpec(
        "result_declare", contracts.MUTATE_REVERSIBLE, "edit",
        "Record a business result the person tells you about (a lead, booking, newsletter sign-up or sale), labelled as reported by them. "
        "Only what they said: never infer an amount from a lead, never guess the date or the link. Reversible from Analytics.",
        voice=True),
        {"type": {"type": "string", "enum": ["lead", "booking", "newsletter_signup", "sale"], "required": True},
         "occurredAt": {"type": "string", "maxLength": 40, "required": True},
         "amountMinor": {"type": "integer"}, "currency": {"type": "string", "pattern": "^[A-Za-z]{3}$", "maxLength": 3},
         "quantity": {"type": "integer"}, "note": {"type": "string", "maxLength": 500},
         "linkId": {"type": "string", "maxLength": 64}, "campaignRef": {"type": "string", "maxLength": 80}},
        "Recorded a result you reported")
    def result_declare(ctx, args):
        if not service.enabled():
            return _disabled()
        if (args.get("amountMinor") is None) != (args.get("currency") is None):
            return {"ok": False, "verified": False, "code": "tool_input", "message": "An amount needs both the number (in cents) and its currency."}
        payload = {"type": args["type"], "occurredAt": args["occurredAt"], "quantity": 1 if args.get("quantity") is None else args["quantity"], "note": args.get("note"),
                   "linkId": args.get("linkId"), "campaignRef": args.get("campaignRef") or None,
                   "amount": {"minor": args["amountMinor"], "currency": args["currency"]} if args.get("amountMinor") is not None else None}
        payload["idempotencyKey"] = _key(ctx, "result_declare", payload)
        try:
            saved = _results(ctx).declare(ctx.workspace_id, ctx.token, payload)
        except AlphaError as error:
            return _app_error(error)
        result = saved["result"]
        ctx.ledger.reference("result", result["id"], f"{result['type'].replace('_', ' ')} you reported")
        if not saved["replayed"]:
            ctx.ledger.changed.append({"type": "result", "id": result["id"], "change": "recorded a result you reported", "expected": "saved result",
                                       "actual": "saved result", "verified": True})
        return {"ok": True, "verified": True, "replayed": saved["replayed"], "result": result, "label": LABELS["user_declared"]}

    @tool_adapter.register(contracts.ToolSpec(
        "tracking_link_create", contracts.MUTATE_REVERSIBLE, "edit",
        "Create a Rafii tracking link for one public https:// page the person names, optionally with a campaign label. Results that come back "
        "carrying the link can be associated with it; clicks are counted as clicks, not people. Can be turned off from Analytics.",
        voice=True),
        {"destination": {"type": "string", "maxLength": 2048, "required": True}, "campaignRef": {"type": "string", "maxLength": 80},
         "label": {"type": "string", "maxLength": 80}},
        "Created a tracking link")
    def tracking_link_create(ctx, args):
        if not service.enabled():
            return _disabled()
        payload = {"destination": args["destination"], "campaignRef": args.get("campaignRef") or None, "label": args.get("label") or None}
        payload["idempotencyKey"] = _key(ctx, "tracking_link_create", payload)
        try:
            saved = _results(ctx).create_link(ctx.workspace_id, ctx.token, payload)
        except AlphaError as error:
            return _app_error(error)
        link = saved["link"]
        ctx.ledger.reference("tracking_link", link["id"], link["label"])
        if not saved["replayed"]:
            ctx.ledger.changed.append({"type": "tracking_link", "id": link["id"], "change": "created a tracking link", "expected": "active link",
                                       "actual": f"{link['status']} link", "verified": link["status"] == "active"})
        return {"ok": True, "verified": link["status"] == "active", "replayed": saved["replayed"],
                "link": {k: link[k] for k in ("id", "label", "url", "path", "destination", "campaignRef", "status", "windowDays")}}

    _REGISTERED = True
