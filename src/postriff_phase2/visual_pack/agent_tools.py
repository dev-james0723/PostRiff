"""Typed Visual Pack tools for Agent Runtime v2 (plan §1 agent tools; PRD R-ENG-01/02 · AC28).

`visual_pack_prepare` (CREATE_DRAFT): a six-slide 1080×1350 pack from one of this workspace's drafts.
`visual_pack_edit` (MUTATE_REVERSIBLE): slide text, alt text, images, order, palette, weight → a new revision; the
previous revision stays intact.
`visual_pack_export` (MUTATE_REVERSIBLE): render, then export files for the person to download once the person has
accepted this exact revision in the carousel editor. Accepting is the person's own act (it records them as the one who
accepted): no tool here accepts, so a rendered revision comes back as `approval_required` with the editor's link. It
never publishes and never hands anything to Queue.

All three need `edit`, go through VisualPackService (flag gate, membership re-check, revision and idempotency rules,
read-back) and behave identically by voice and text. `register()` is idempotent; the coordinator adds it to
`skill_registry.registered_tools()`.
"""
from __future__ import annotations

import hashlib

TOOL_SCOPES = {"visual_pack_prepare": ["creative", "content"], "visual_pack_edit": ["creative"], "visual_pack_export": ["creative"]}
PALETTES = ["rafii_light", "rafii_dark", "rafii_violet", "rafii_paper"]
HREF = "/app/library#visual-packs"   # Library's carousel section: the editor where the person accepts a revision
WEIGHTS = ["regular", "bold"]
_REGISTERED = False


def _key(ctx, name, args) -> str:
    """One key per tool call intent in this turn: a retried call replays instead of making a second pack or revision."""
    return f"agent-{name[12:16]}-" + hashlib.sha256(f"{ctx.trace_id}|{name}|{sorted(args.items())!r}".encode()).hexdigest()[:40]


def _error(error) -> dict:
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _summary(view: dict) -> dict:
    from ..agent_runtime_v2.context import untrusted
    revision = view["revision"]
    return {"packId": view["pack"]["id"], "revision": revision["revision"], "state": revision["state"], "receipt": view["receipt"],
            "sourceStatus": revision["sourceStatus"], "checksOk": revision["checks"]["ok"],
            "findings": [{"position": s["position"], "codes": [f["code"] for f in s["findings"] if f["severity"] == "blocking"]}
                         for s in revision["checks"]["slides"] if not s["ok"]],
            "slides": untrusted("APP_STATE", [{"position": s["position"], "key": s["key"], "text": s["text"], "imageAssetId": s["imageAssetId"]}
                                              for s in revision["slides"]]),
            "export": revision["export"], "queue": "unavailable: no connected account can publish a six-image carousel; export instead"}


def _record(ctx, view, change, replayed=False):
    pack = view["pack"]["id"]
    ctx.ledger.reference("visual_pack", pack, f"Carousel r{view['revision']['revision']}")
    if not replayed:
        ctx.ledger.changed.append({"type": "visual_pack", "id": pack, "change": change, "expected": change, "actual": view["revision"]["state"], "verified": True})


def register():
    """Register the three tools once and give the creative/content specialists their scope (idempotent)."""
    global _REGISTERED
    from ..agent_runtime_v2 import contracts, tool_adapter
    _bind_scopes()
    if _REGISTERED or "visual_pack_prepare" in tool_adapter.REGISTRY:
        _REGISTERED = True
        return
    from postriff_alpha.domain import AlphaError

    from .service import ensure

    @tool_adapter.register(contracts.ToolSpec("visual_pack_prepare", contracts.CREATE_DRAFT, "edit",
                                              "Make an editable six-slide 1080×1350 carousel from one of this workspace's drafts (hook, four points, close; "
                                              "the draft's own sentences, nothing invented). Returns the slides and their checks. Nothing is rendered, "
                                              "exported or published.", idempotent=True, voice=True),
                           {"variantId": {"type": "string", "maxLength": 80, "required": True}, "palette": {"type": "string", "enum": PALETTES},
                            "weight": {"type": "string", "enum": WEIGHTS}}, "Prepared a carousel")
    def visual_pack_prepare(ctx, args):
        settings = {k: args[k] for k in ("palette", "weight") if args.get(k)}
        try:
            view = ensure(ctx.service).prepare(ctx.workspace_id, ctx.token, {"idempotencyKey": _key(ctx, "visual_pack_prepare", args),
                                                                              "variantId": args["variantId"], "settings": settings})
        except AlphaError as error:
            return _error(error)
        _record(ctx, view, "carousel prepared from the draft", view.get("replayed"))
        return {"ok": True, "verified": True, **_summary(view)}

    @tool_adapter.register(contracts.ToolSpec("visual_pack_edit", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Edit a carousel: slide text or alt text (by position 1–6), an image from this workspace's Library "
                                              "(imageAssetId, or null to remove), the slide order (positions in their new order), palette or weight, or "
                                              "take the slides from the changed draft again (source: resplit) or keep them (source: keep). Each edit is a "
                                              "new revision; earlier ones stay and their acceptance and exports stop applying.", idempotent=True, voice=True),
                           {"packId": {"type": "string", "maxLength": 40, "required": True}, "expectedRevision": {"type": "integer"},
                            "slides": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
                                "position": {"type": "integer"}, "text": {"type": "string", "maxLength": 2000}, "altText": {"type": "string", "maxLength": 1000},
                                "imageAssetId": {"type": ["string", "null"], "maxLength": 80}}, "required": ["position"], "additionalProperties": False}},
                            "order": {"type": "array", "items": {"type": "integer"}, "minItems": 6, "maxItems": 6}, "caption": {"type": "string", "maxLength": 5000},
                            "palette": {"type": "string", "enum": PALETTES}, "weight": {"type": "string", "enum": WEIGHTS},
                            "source": {"type": "string", "enum": ["keep", "resplit"]}}, "Edited the carousel")
    def visual_pack_edit(ctx, args):
        service = ensure(ctx.service)
        try:
            current = service.get(ctx.workspace_id, ctx.token, args["packId"])
            slides = current["revision"]["slides"]
            keys = {s["position"]: s["key"] for s in slides}
            body = {"idempotencyKey": _key(ctx, "visual_pack_edit", args), "expectedRevision": args.get("expectedRevision") or current["revision"]["revision"]}
            patches = []
            for change in args.get("slides") or []:
                if change.get("position") not in keys:
                    return {"ok": False, "verified": False, "code": "unsupported_input", "message": "Slide positions are 1 to 6."}
                patches.append({"key": keys[change["position"]], **{k: change[k] for k in ("text", "altText", "imageAssetId") if k in change}})
            if patches:
                body["slides"] = patches
            if args.get("order"):
                if sorted(args["order"]) != list(range(1, 7)):
                    return {"ok": False, "verified": False, "code": "unsupported_input", "message": "A new order lists positions 1 to 6 once each."}
                body["order"] = [keys[p] for p in args["order"]]
            settings = {k: args[k] for k in ("palette", "weight") if args.get(k)}
            if settings:
                body["settings"] = settings
            for field in ("caption", "source"):
                if field in args:
                    body[field] = args[field]
            view = service.edit(ctx.workspace_id, ctx.token, args["packId"], body)
        except AlphaError as error:
            return _error(error)
        _record(ctx, view, "new carousel revision", view.get("replayed") or view.get("unchanged"))
        return {"ok": True, "verified": True, "unchanged": bool(view.get("unchanged")), **_summary(view)}

    @tool_adapter.register(contracts.ToolSpec("visual_pack_export", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Prepare a carousel's files for the person to download and post themselves: renders the six PNGs, then "
                                              "exports a zip (PNGs, caption, alt text, manifest) once the person has accepted that exact revision in the "
                                              "carousel editor. Rafii never accepts a revision for them; a rendered revision returns approval_required "
                                              "with the editor link. Never publishes and never queues anything.",
                                              idempotent=True, voice=True),
                           {"packId": {"type": "string", "maxLength": 40, "required": True}}, "Exported the carousel files")
    def visual_pack_export(ctx, args):
        service = ensure(ctx.service)
        try:
            view = service.get(ctx.workspace_id, ctx.token, args["packId"])
            number = view["revision"]["revision"]
            if view["revision"]["state"] == "draft":
                view = service.render(ctx.workspace_id, ctx.token, args["packId"], {"expectedRevision": number})
            if view["revision"]["state"] == "rendered":
                _record(ctx, view, "carousel rendered for review")
                return {"ok": False, "verified": True, "code": "approval_required", "needsUser": True, "href": HREF,
                        **_summary(view),
                        "message": ("The six slides are rendered. Only the person can accept this exact revision, in the carousel editor "
                                    "(Library); Rafii can export the files after that. Nothing was accepted, exported or published.")}
            if view["revision"]["state"] == "accepted":
                view = service.export(ctx.workspace_id, ctx.token, args["packId"], {"expectedRevision": number})
        except AlphaError as error:
            return _error(error)
        _record(ctx, view, "carousel files exported for download (not published)", view.get("replayed"))
        return {"ok": view["revision"]["export"] is not None, "verified": True, **_summary(view),
                "note": "Files are ready in the carousel editor. Rafii has not published them; posting them is the person's own step."}

    _REGISTERED = True


def _bind_scopes():
    try:
        from ..agent_runtime_v2 import specialists
    except ImportError:   # pragma: no cover - runtime absent in a reduced build
        return
    by_agent = {}
    for tool, agents in TOOL_SCOPES.items():
        for agent in agents:
            by_agent.setdefault(agent, []).append(tool)
    for agent, names in by_agent.items():
        try:
            specialists.extend_scope(agent, names)
        except (ValueError, AttributeError):
            continue
