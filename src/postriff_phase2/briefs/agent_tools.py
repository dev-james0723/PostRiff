"""Typed agent tools for the opportunity brief (PRD R-ENG-02 ``brief_read`` / ``brief_action``).

``brief_read`` is READ: the same stored-only composition as the page (no research, provider, model or Radar call,
and no write). ``brief_action`` is MUTATE_REVERSIBLE with the ``edit`` class: dismiss / not relevant / restore, or
the item's one supported action (save an idea, accept a trend opportunity), each through BriefService, which
re-checks the member, the edition version and the idempotency key. Voice and text are identical. The coordinator
wires ``register`` into ``skill_registry.registered_tools()``.
"""
from __future__ import annotations

import hashlib

from . import FLAG, enabled

TOOL_SCOPES = {"brief_read": ["rafii_manager", "content", "research"], "brief_action": ["rafii_manager", "content"]}


def _disabled():
    return {"ok": False, "verified": False, "code": "feature_disabled", "message": f"{FLAG} is off, so this tool is unavailable."}


def _error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _key(ctx, *parts):
    seed = ":".join(str(p) for p in (ctx.run_id or ctx.trace_id, ctx.workspace_id, *parts))
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
                "note": "Stored results only; nothing here is today's research or a prediction of results."}

    @tool_adapter.register(contracts.ToolSpec("brief_action", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Act on one opportunity-brief item: dismiss or mark not relevant (with a reason), restore it, save it as an idea, "
                                              "or accept a trend opportunity with an angle and account. Nothing is drafted, scheduled or published.",
                                              voice=True),
                           {"itemId": {"type": "string", "required": True}, "action": {"type": "string", "required": True},
                            "reasonCode": {"type": "string"}, "editionId": {"type": "string"}, "materialDigest": {"type": "string"},
                            "angleId": {"type": "string"}, "channelId": {"type": "string"}, "goal": {"type": "string"}}, "Acted on a brief item")
    def brief_action(ctx, args):
        if not enabled():
            return _disabled()
        from .http import ensure
        payload = {k: args[k] for k in ("action", "reasonCode", "editionId", "materialDigest", "angleId", "channelId", "goal") if args.get(k) is not None}
        payload["idempotencyKey"] = _key(ctx, "brief_action", args.get("itemId"), args.get("action"), args.get("editionId") or args.get("materialDigest"))
        try:
            result = ensure(ctx.service).action(ctx.workspace_id, ctx.token, str(args.get("itemId") or ""), payload)
        except AlphaError as error:
            return _error(error)
        if not result.get("replayed"):
            ctx.ledger.changed.append({"type": "brief_item", "id": result["action"]["itemId"], "change": f"brief item: {result['action']['action']}",
                                       "expected": result["action"]["action"], "actual": result["action"]["action"], "verified": bool(result["verified"])})
        if result.get("outcome"):
            ctx.ledger.reference("source", result["outcome"]["sourceId"], "Saved idea")
        return {"ok": True, "verified": bool(result["verified"]), "action": result["action"], "outcome": result.get("outcome"), "replayed": result.get("replayed", False)}
