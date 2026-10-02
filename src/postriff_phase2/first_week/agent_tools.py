"""First-week typed tools: read the journey, start it from the person's own words, plan the week. Accepting a draft,
committing a scope and spending credits stay explicit person actions in the app; no tool here does them."""
from __future__ import annotations

import hashlib

TOOL_SCOPES = {
    "first_week_get": ["rafii_manager", "content"],
    "first_week_start": ["content"],
    "first_week_plan": ["content"],
}
_REGISTERED = False


def _service(ctx):
    from .http import ensure
    return ensure(ctx.service)


def _error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def register():
    global _REGISTERED
    from ..agent_runtime_v2 import contracts, tool_adapter
    if _REGISTERED or "first_week_get" in tool_adapter.REGISTRY:
        _REGISTERED = True
        return
    from postriff_alpha.domain import AlphaError

    @tool_adapter.register(contracts.ToolSpec("first_week_get", contracts.READ, "read",
                                              "Read the person's first-week journey: draft, missing context, planned posts, what each still needs and the next action. Never drafts or spends.",
                                              voice=True), {}, "Read your first week")
    def first_week_get(ctx, args):
        try:
            return {"ok": True, "verified": True, "data": _service(ctx).view(ctx.workspace_id, ctx.token)}
        except AlphaError as error:
            return _error(error)

    @tool_adapter.register(contracts.ToolSpec("first_week_start", contracts.CREATE_DRAFT, "edit",
                                              "Save the person's own words (pasted in this conversation) as their first draft and source. Nothing is generated or charged; the person still accepts the draft themselves.",
                                              idempotent=True, voice=True),
                           {"text": {"type": "string", "required": True}, "platform": {"type": "string", "required": True}, "language": {"type": "string"}},
                           "Saved your draft")
    def first_week_start(ctx, args):
        text = str(args.get("text") or "")
        key = "agent-" + hashlib.sha256(f"{ctx.workspace_id}:{args.get('platform')}:{text}".encode()).hexdigest()[:40]
        try:
            result = _service(ctx).start_from_text(ctx.workspace_id, ctx.token, {"idempotencyKey": key, "consent": True, "text": text,
                                                                               "platform": args.get("platform"), "language": args.get("language")})
        except AlphaError as error:
            return _error(error)
        ctx.ledger.reference("draft", result["draftVariantId"], "Your first draft")
        ctx.ledger.changed.append({"type": "draft", "id": result["draftVariantId"], "change": "saved from your words", "expected": "saved draft",
                                   "actual": "saved draft", "verified": True})
        return {"ok": True, "verified": True, "draftVariantId": result["draftVariantId"], "replayed": result["replayed"],
                "next": "Review the draft and accept it in Weekly before planning the week."}

    @tool_adapter.register(contracts.ToolSpec("first_week_plan", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Plan (or re-plan) the first week after the person accepted a draft: up to three posts on one platform. Planning never drafts, spends or schedules.",
                                              idempotent=True, voice=True),
                           {"platform": {"type": "string"}, "channelId": {"type": "string"}, "postsPerWeek": {"type": "integer"}, "timeZone": {"type": "string"}},
                           "Planned your first week")
    def first_week_plan(ctx, args):
        service = _service(ctx)
        try:
            revision = service.view(ctx.workspace_id, ctx.token)["revision"]
            view = service.plan(ctx.workspace_id, ctx.token, {**{k: args[k] for k in ("platform", "channelId", "postsPerWeek", "timeZone") if k in args},
                                                              "expectedRevision": revision})
        except AlphaError as error:
            return _error(error)
        if view.get("week"):
            ctx.ledger.reference("week_plan", view["week"]["id"], f"Week of {view['week']['weekOf']}")
        return {"ok": True, "verified": bool(view.get("week")), "week": view.get("week"),
                "slots": [{k: s.get(k) for k in ("id", "platform", "status", "publishBlocker", "nextAction")} for s in view.get("slots") or []]}

    _REGISTERED = True
