"""Rafii Agent tools for Substack editorial work; no provider write tools."""
import json
from postriff_alpha.domain import AlphaError
from . import contracts
from .tool_adapter import register

MANAGER_SCOPE = ("substack_workspace", "substack_draft_get", "substack_draft_save")
MANAGER_INSTRUCTIONS = """Substack: call substack_workspace to see the actual methods, publications and capability reasons.
A public feed is not an authenticated account or verified ownership. You may save a Rafii-only draft with substack_draft_save;
first read the current workspace revision and resolve the exact publication. Re-read an existing draft before editing it.
Only a human reviewer can approve and prepare a manual handoff on Connections. A target handoff time is not an automatic
Substack publishing schedule. There are no Substack publish, Notes send, subscriber, payment or OAuth tools in this release.
Report available, approval-required and unavailable capabilities as returned. Never invent analytics or claim a provider accepted a draft."""


def enabled_for(ctx):
    return bool(getattr(getattr(getattr(ctx, "service", None), "substack", None), "enabled", False))


def _service(ctx):
    if not enabled_for(ctx):
        raise AlphaError("Substack integration is not enabled.", 404, code="feature_disabled")
    # Rebind membership and principal through the existing agent context seam.
    with ctx.workspace():
        pass
    return ctx.service.substack


def _metadata(draft):
    result = {key: draft.get(key) for key in ("id", "connectionId", "contentType", "audience", "status", "contentHash", "approvedHash", "scheduledFor", "updatedAt")}
    title = draft.get("title", "")
    result.update(title=title[:120], titleTruncated=len(title) > 120)
    return result


@register(contracts.ToolSpec("substack_workspace", contracts.READ, "read", "Read Substack public-feed connections, draft metadata, manual queue and actual capability restrictions in this workspace.",
    voice=False, category="read_analyze", risk="R0", data_grants=("connections", "content"), since=3),
    {"draftOffset": {"type": "integer", "minimum": 0, "maximum": 200}, "connectionOffset": {"type": "integer", "minimum": 0, "maximum": 50}}, "Read Substack workspace")
def workspace(ctx, args):
    for name, maximum in (("draftOffset", 200), ("connectionOffset", 50)):
        if name in args and (type(args[name]) is not int or not 0 <= args[name] <= maximum):
            raise AlphaError("Choose a valid Substack page offset.", 400, code="tool_input")
    result = _service(ctx).workspace(ctx.workspace_id, ctx.token)
    start, connection_start = args.get("draftOffset", 0), args.get("connectionOffset", 0)
    important = ("public_feed_read", "account_connect", "publication_analytics", "draft_create", "draft_approval", "manual_handoff", "post_publish", "post_schedule", "notes_create")
    capabilities = {name: {"status": result["capabilities"][name]["status"], "reason": result["capabilities"][name]["reason"][:180]} for name in important}
    connections = [{key: value.get(key) for key in ("id", "mode", "publicationUrl", "status", "ownershipVerified", "accountAuthenticated", "analyticsConnected", "publishingAuthorized")}
                   for value in result["connections"][connection_start:connection_start + 10]]
    output = {"ok": True, "verified": True, "revision": result["revision"], "connections": connections,
            "drafts": [_metadata(value) for value in result["drafts"][start:start + 10]], "capabilities": capabilities,
            "counts": {"connections": len(result["connections"]), "drafts": len(result["drafts"]),
                       "pendingManualHandoffs": sum(value["status"] == "pending_manual" for value in result["queue"]),
                       "dueManualHandoffs": sum(value.get("due") is True for value in result["queue"])},
            "nextDraftOffset": start + 10 if start + 10 < len(result["drafts"]) else None,
            "nextConnectionOffset": connection_start + 10 if connection_start + 10 < len(result["connections"]) else None,
            "autoPublishingAvailable": False}
    # Bound encoded output too: a short visible title can contain multibyte
    # characters or JSON escapes. Continuation offsets follow retained rows.
    while len(json.dumps(output, ensure_ascii=False).encode()) > 12000:
        key = "drafts" if len(output["drafts"]) >= len(output["connections"]) else "connections"
        if not output[key]:
            raise AlphaError("The Substack overview is too large to show here. Open Connections.", 409, code="substack_overview_too_large")
        output[key].pop()
    following_draft = start + len(output["drafts"])
    following_connection = connection_start + len(output["connections"])
    output["nextDraftOffset"] = following_draft if following_draft < len(result["drafts"]) else None
    output["nextConnectionOffset"] = following_connection if following_connection < len(result["connections"]) else None
    return output


@register(contracts.ToolSpec("substack_draft_get", contracts.READ, "read", "Read one complete Rafii Substack draft by its ID before editing. No Substack private API call.",
    voice=False, category="read_analyze", risk="R0", data_grants=("content", "connections"), since=3),
    {"draftId": {"type": "string", "maxLength": 40, "required": True}}, "Read Substack draft")
def draft_get(ctx, args):
    result = _service(ctx).workspace(ctx.workspace_id, ctx.token)
    draft = next((value for value in result["drafts"] if value["id"] == args["draftId"]), None)
    if draft is None:
        raise AlphaError("Substack draft unavailable.", 404, code="substack_item_unavailable")
    output = {"ok": True, "verified": True, "revision": result["revision"], "draft": draft}
    if len(draft["body"].encode()) > 8000 or len(json.dumps(output, ensure_ascii=False).encode()) > 12000:
        # The tool adapter has a bounded model-output envelope. Never let a
        # model unknowingly edit a truncated long article.
        return {"ok": False, "verified": False, "code": "substack_draft_too_large_for_agent", "error": "Review and edit this long draft in Connections.", "draft": _metadata(draft)}
    return output


@register(contracts.ToolSpec("substack_draft_save", contracts.CREATE_DRAFT, "edit", "Save supplied text as a Rafii-only Substack draft for an existing public-feed destination. Does not approve, schedule with Substack or publish. Use the current revision from substack_workspace; edits invalidate prior human approval.",
    voice=False, category="create_edit", risk="R1", data_grants=("content", "connections"), idempotency="native_key", retry_class="manual", audit="substack.draft_saved", since=3),
    {"expectedRevision": {"type": "integer", "minimum": 0, "required": True},
     "draftId": {"type": "string", "maxLength": 40}, "connectionId": {"type": "string", "maxLength": 40, "required": True},
     "title": {"type": "string", "maxLength": 300, "required": True}, "body": {"type": "string", "maxLength": 8000, "required": True},
     "contentType": {"type": "string", "enum": ["article", "note", "podcast", "video"]},
     "audience": {"type": "string", "enum": ["everyone", "free", "paid"]}}, "Saved a Substack draft in Rafii")
def draft_save(ctx, args):
    service = _service(ctx)
    ctx.check_cancelled()
    before = service.workspace(ctx.workspace_id, ctx.token)
    current = next((value for value in before["drafts"] if value["id"] == args.get("draftId")), None)
    if current is not None and (len(current["body"].encode()) > 8000 or len(json.dumps(current, ensure_ascii=False).encode()) > 11500):
        raise AlphaError("Review and edit this long draft in Connections.", 409, code="substack_draft_too_large_for_agent")
    payload = {key: value for key, value in args.items() if key != "draftId"}
    saved = service.save_draft(ctx.workspace_id, ctx.token, payload, draft_id=args.get("draftId"))
    if args.get("draftId"):
        changed_id = args["draftId"]
    else:
        old_ids = {value["id"] for value in before["drafts"]}
        created = [value for value in saved["drafts"] if value["id"] not in old_ids]
        if len(created) != 1:
            return {"ok": False, "verified": False, "code": "substack_save_unverified", "error": "The draft result could not be verified. Reload Connections before retrying."}
        changed_id = created[0]["id"]
    expected = next(value for value in saved["drafts"] if value["id"] == changed_id)
    reread = service.workspace(ctx.workspace_id, ctx.token)
    actual = next((value for value in reread["drafts"] if value["id"] == changed_id), None)
    verified = actual is not None and actual["contentHash"] == expected["contentHash"]
    if not verified:
        return {"ok": False, "verified": False, "code": "substack_save_unverified", "error": "The draft changed before verification. Reload Connections."}
    return {"ok": True, "verified": True, "revision": reread["revision"], "draft": _metadata(actual), "autoPublished": False, "nextAction": "Review in Connections"}
