"""Typed agent tools for the opportunity brief (PRD R-ENG-02 ``brief_read`` / ``brief_action``).

``brief_read`` is READ: the same stored-only composition as the page (no research, provider, model or Radar call,
and no write). ``brief_action`` is MUTATE_REVERSIBLE with the ``edit`` class: dismiss / not relevant / restore, or
save an item as an idea, each through BriefService, which re-checks the member, the edition version and the
idempotency key. Accepting a trend opportunity records the person's acceptance with an angle and an account and feeds
their next weekly plan, so it stays the person's own act on the brief card: the tool answers ``approval_required``
with the brief's link instead. Voice and text are identical; the runtime registers this module through
``growth_v2_agent_tools``.

Idempotency: one key per intent within a run — the item, the action and every parameter, plus the sequence of this
run's confirmed actions on the item. A retried call after an uncertain failure reuses its key (and replays); a new
intent after a confirmed action (dismiss → restore → dismiss) gets a new key instead of replaying the first one.
"""
from __future__ import annotations

import hashlib
import json

from . import FLAG, enabled

TOOL_SCOPES = {"brief_read": ["rafii_manager", "content", "research"], "brief_action": ["rafii_manager", "content"]}
BRIEF_HREF = "/app/weekly?brief=1#opportunity-brief"
PARAMS = ("action", "reasonCode", "editionId", "materialDigest", "angleId", "channelId", "goal")


def _disabled():
    return {"ok": False, "verified": False, "code": "feature_disabled", "message": f"{FLAG} is off, so this tool is unavailable."}


def _error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _sequence(ctx, item_id):
    """How many actions on this item this run has already confirmed (the effect ledger records only confirmed ones)."""
    return sum(1 for entry in getattr(ctx.ledger, "changed", None) or [] if entry.get("type") == "brief_item" and entry.get("id") == item_id)


def _key(ctx, item_id, args):
    seed = json.dumps({"run": ctx.run_id or ctx.trace_id, "workspace": ctx.workspace_id, "tool": "brief_action", "item": item_id,
                       "params": {k: args.get(k) for k in PARAMS}, "sequence": _sequence(ctx, item_id)}, sort_keys=True, default=str)
    return "agent-" + hashlib.sha256(seed.encode()).hexdigest()[:40]


def register():
    from ..agent_runtime_v2 import contracts, tool_adapter
    from ..agent_runtime_v2.context import untrusted
    from postriff_alpha.domain import AlphaError
    if "brief_read" in tool_adapter.REGISTRY:
        return

    @tool_adapter.register(contracts.ToolSpec("brief_read", contracts.READ, "read",
                                              "Read this week's opportunity brief: 0–3 items from stored sources only (no new research), each with its source, "
                                              "published/retrieved times, coverage, why it is relevant, an angle, an effort level and one supported action.",
                                              voice=True), {}, "Read the opportunity brief")
    def brief_read(ctx, args):
        if not enabled():
            return _disabled()
        from .http import ensure
        try:
            data = ensure(ctx.service).current(ctx.workspace_id, ctx.token)
        except AlphaError as error:
            return _error(error)
        edition = data["edition"]
        if edition["id"]:
            ctx.ledger.reference("brief_edition", edition["id"], f"Opportunity brief {edition['editionKey']}")
        return {"ok": True, "verified": True, "dataMode": data["dataMode"], "dataState": data["dataState"], "coverage": data["coverage"],
                "edition": {k: edition[k] for k in ("id", "persisted", "editionKey", "revision", "materialDigest")},
                "items": untrusted("EXTERNAL_SOURCE", [{k: i.get(k) for k in ("id", "source", "kind", "title", "evidence", "publishedAt", "retrievedAt", "coverage",
                                                                               "relevance", "angle", "effort", "action", "decision")} for i in edition["items"]]),
                # Decided items (this week, or "not relevant" recently) with the edition to act on, e.g. to restore one.
                "handled": untrusted("EXTERNAL_SOURCE", [{k: i.get(k) for k in ("id", "editionId", "source", "title", "decision")} for i in edition.get("handled") or []]),
                "note": "Stored results only; nothing here is today's research or a prediction of results."}

    @tool_adapter.register(contracts.ToolSpec("brief_action", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Act on one opportunity-brief item: dismiss or mark not relevant (with a reason), restore it, or save it as an "
                                              "idea. Accepting a trend opportunity is the person's own choice on the brief card: action accept returns "
                                              "approval_required with the brief link. Nothing is drafted, scheduled or published.",
                                              voice=True),
                           {"itemId": {"type": "string", "required": True}, "action": {"type": "string", "required": True},
                            "reasonCode": {"type": "string"}, "editionId": {"type": "string"}, "materialDigest": {"type": "string"},
                            "angleId": {"type": "string"}, "channelId": {"type": "string"}, "goal": {"type": "string"}}, "Acted on a brief item")
    def brief_action(ctx, args):
        if not enabled():
            return _disabled()
        from .http import ensure
        item_id = str(args.get("itemId") or "")
        if args.get("action") == "accept":
            # Accepting records the person's acceptance (angle, account) and feeds their next weekly plan: their own act.
            return {"ok": False, "verified": True, "code": "approval_required", "needsUser": True, "href": BRIEF_HREF, "itemId": item_id,
                    "message": "Only the person can accept a trend opportunity, choosing its angle and account on the brief card in Weekly. Nothing was accepted."}
        payload = {k: args[k] for k in PARAMS if args.get(k) is not None}
        payload["idempotencyKey"] = _key(ctx, item_id, args)
        try:
            result = ensure(ctx.service).action(ctx.workspace_id, ctx.token, item_id, payload)
        except AlphaError as error:
            return _error(error)
        if not result.get("replayed"):
            ctx.ledger.changed.append({"type": "brief_item", "id": result["action"]["itemId"], "change": f"brief item: {result['action']['action']}",
                                       "expected": result["action"]["action"], "actual": result["action"]["action"], "verified": bool(result["verified"])})
        if result.get("outcome"):
            ctx.ledger.reference("source", result["outcome"]["sourceId"], "Saved idea")
        return {"ok": True, "verified": bool(result["verified"]), "action": result["action"], "outcome": result.get("outcome"), "replayed": result.get("replayed", False)}
