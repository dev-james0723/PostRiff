"""Typed Signature Series tools for Agent Runtime v2 (PRD R-ENG-02 `series_prepare` / `episode_prepare`, AC28).

Registered once into the runtime's single registry; every call passes its gate (scope, voice parity, permission
re-check, cancellation, schema) and runs SeriesService with the person's own session, so text and voice have exactly
the authority of the Library page. `series_list` reads; `series_prepare` and `episode_prepare` save plan/draft
references only (CREATE_DRAFT): no model call, no cost, nothing scheduled or published. Approving the next episode
and acknowledging similarity warnings stay the person's decisions in Library. Series content reaches a model only as
data (`untrusted`). `register()` is idempotent; the coordinator adds it to `skill_registry.registered_tools()` and
the names in TOOL_SCOPES to the specialists' scopes.
"""
from __future__ import annotations

from ..contracts import digest
from . import model as m

TOOL_SCOPES = {"series_list": ["rafii_manager", "content"], "series_prepare": ["content"], "episode_prepare": ["content"]}
_REGISTERED = False
HREF = "/app/library?series={id}"


def _disabled():
    return {"ok": False, "verified": False, "code": "feature_disabled", "message": f"{m.FLAG} is off, so this tool is unavailable."}


def _error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _key(ctx, tool, args):
    """One key per run, tool and arguments: a retried call in the same run replays, a new run is a new request."""
    return f"agent:{digest({'run': ctx.run_id or ctx.trace_id, 'tool': tool, 'args': args})[:48]}"


def _episode_brief(view, episode):
    claims = {c["id"]: c for c in view["claims"]}
    return {"seriesId": view["id"], "seriesRevision": view["revision"], "episodeId": episode["id"], "index": episode["index"], "role": episode["role"],
            "question": episode["question"], "angle": episode["angle"]["text"], "state": episode["state"], "factState": episode["factState"],
            "factReasons": episode["factReasons"], "approvalRequired": episode["workflowState"] == "planned", "canApprove": episode["canApprove"],
            "blockedReason": episode["blockedReason"], "claims": [{k: claims[i][k] for k in ("id", "text", "reviewBy", "freshness")} for i in episode["claimIds"] if i in claims],
            "draftIds": [d["variantId"] for d in episode["drafts"]], "candidateDraftIds": [d["variantId"] for d in episode["candidateDrafts"]]}


def register():
    global _REGISTERED
    from ..agent_runtime_v2 import contracts, tool_adapter
    if _REGISTERED or "series_list" in tool_adapter.REGISTRY:
        _REGISTERED = True
        return
    from postriff_alpha.domain import AlphaError
    from ..agent_runtime_v2.context import untrusted
    from .service import ensure

    @tool_adapter.register(contracts.ToolSpec("series_list", contracts.READ, "read",
                                              "List this workspace's Signature Series: title, status, how many audience questions are covered, facts needing review and the next action. Reads only.",
                                              voice=True), {"limit": {"type": "integer"}}, "Read series")
    def series_list(ctx, args):
        if not m.enabled():
            return _disabled()
        try:
            data = ensure(ctx.service).list(ctx.workspace_id, ctx.token, limit=max(1, min(int(args.get("limit") or 10), 25)))
        except AlphaError as error:
            return _error(error)
        for item in data["items"]:
            ctx.ledger.reference("series", item["id"], item["title"])
        return {"ok": True, "verified": True, "series": untrusted("APP_STATE", data["items"]), "more": bool(data["nextCursor"])}

    @tool_adapter.register(contracts.ToolSpec("series_prepare", contracts.CREATE_DRAFT, "edit",
                                              "Start a Signature Series from one published post at least 14 days old or one source with approved facts: saves the series, its facts with review dates and a 2–6 episode plan (distinct roles and angles). Deterministic; writes no post, costs nothing, schedules nothing.",
                                              voice=True),
                           {"originKind": {"type": "string", "enum": ["post", "source"], "required": True},
                            "originId": {"type": "string", "maxLength": 80, "required": True},
                            "audienceQuestion": {"type": "string", "maxLength": 300, "required": True},
                            "goal": {"type": "string", "maxLength": 600, "required": True},
                            "title": {"type": "string", "maxLength": 120},
                            "episodeCount": {"type": "integer"},
                            "sourceIds": {"type": "array", "maxItems": m.MAX_SOURCES}}, "Planned a series")
    def series_prepare(ctx, args):
        if not m.enabled():
            return _disabled()
        payload = {"origin": {"kind": args["originKind"], "id": args["originId"]}, "audienceQuestion": args["audienceQuestion"], "goal": args["goal"],
                   **{k: args[k] for k in ("title", "episodeCount", "sourceIds") if args.get(k) is not None}}
        payload["idempotencyKey"] = _key(ctx, "series_prepare", payload)
        try:
            result = ensure(ctx.service).create(ctx.workspace_id, ctx.token, payload)
        except AlphaError as error:
            return _error(error)
        view = result["series"]
        ctx.ledger.reference("series", view["id"], view["title"])
        ctx.ledger.changed.append({"type": "series", "id": view["id"], "change": "series and episode plan saved (nothing written or scheduled)",
                                   "expected": "saved plan", "actual": "saved plan" if result["verified"] else "unconfirmed", "verified": bool(result["verified"])})
        return {"ok": True, "verified": bool(result["verified"]), "replayed": result["replayed"], "href": HREF.format(id=view["id"]),
                "series": untrusted("APP_STATE", {"id": view["id"], "title": view["title"], "revision": view["revision"], "nextAction": view["nextAction"],
                                                  "episodes": [_episode_brief(view, e) for e in view["episodes"] if e["workflowState"] != "skipped"]})}

    @tool_adapter.register(contracts.ToolSpec("episode_prepare", contracts.CREATE_DRAFT, "edit",
                                              "Prepare one Signature Series episode: its role, angle, question and facts with source, version and review date, whether it needs a fact review or the person's approval, and its drafts. Can plan more episodes (planMore) or attach existing drafts by id (variantIds) after the duplicate check; a near-duplicate is returned for the person to confirm in Library, never attached silently. Never approves, writes, schedules or publishes.",
                                              voice=True),
                           {"seriesId": {"type": "string", "maxLength": 80, "required": True}, "episodeId": {"type": "string", "maxLength": 80},
                            "variantIds": {"type": "array", "maxItems": m.MAX_DRAFTS}, "planMore": {"type": "boolean"}}, "Prepared an episode")
    def episode_prepare(ctx, args):
        if not m.enabled():
            return _disabled()
        service = ensure(ctx.service)
        changed, needs_user = [], []
        try:
            view = service.get(ctx.workspace_id, ctx.token, args["seriesId"])["series"]
            if args.get("planMore"):
                payload = {"count": m.DEFAULT_PLAN}
                payload["idempotencyKey"] = _key(ctx, "episode_prepare.plan", {"series": view["id"], "revision": view["revision"]})
                payload["expectedRevision"] = view["revision"]
                outcome = service.plan(ctx.workspace_id, ctx.token, view["id"], payload)
                view = outcome["series"]
                changed += [{"type": "series_episode", "id": i, "change": "episode planned"} for i in (outcome.get("result") or {}).get("added") or []]
            target = args.get("episodeId") or (view["nextAction"].get("episodeId"))
            episode = next((e for e in view["episodes"] if e["id"] == target), None) if target else None
            for variant_id in args.get("variantIds") or []:
                if episode is None:
                    return {"ok": False, "verified": False, "code": "episode_required", "message": "Name the episode the drafts belong to."}
                if not isinstance(variant_id, str):
                    continue
                check = service.draft_check(ctx.workspace_id, ctx.token, view["id"], episode["id"], variant_id)
                if check["refusal"]:
                    needs_user.append({"variantId": variant_id, "refusal": check["refusal"]["code"], "message": check["refusal"]["message"]})
                    continue
                if check["warnings"]:
                    needs_user.append({"variantId": variant_id, "warnings": [{k: w[k] for k in ("code", "similarity")} for w in check["warnings"]]})
                    continue
                payload = {"variantId": variant_id, "acknowledgedWarnings": [], "expectedRevision": view["revision"],
                           "idempotencyKey": _key(ctx, "episode_prepare.link", {"series": view["id"], "episode": episode["id"], "variant": variant_id})}
                outcome = service.link(ctx.workspace_id, ctx.token, view["id"], episode["id"], payload)
                view = outcome["series"]
                changed.append({"type": "draft", "id": variant_id, "change": f"attached to series episode {episode['index']}"})
                episode = next((e for e in view["episodes"] if e["id"] == episode["id"]), episode)
        except AlphaError as error:
            return _error(error)
        for item in changed:
            ctx.ledger.changed.append({**item, "expected": "saved", "actual": "saved", "verified": True})
        ctx.ledger.reference("series", view["id"], view["title"])
        return {"ok": True, "verified": True, "href": HREF.format(id=view["id"]), "needsUser": needs_user or None,
                "episode": untrusted("APP_STATE", _episode_brief(view, episode)) if episode else None, "nextAction": view["nextAction"]}

    _REGISTERED = True
