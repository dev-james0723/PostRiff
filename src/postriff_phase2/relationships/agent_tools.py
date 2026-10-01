"""Typed relationship tools for Agent Runtime v2 (PRD R-ENG-02 ``relationship_upsert`` / ``followup_transition``).

They call the same service as the HTTP routes, under the runtime's gate (scope, voice parity, permission re-check,
cancellation, schema), so text and voice have exactly the person's authority. Reading is ``READ``; creating, editing and
moving a follow-up are reversible edits (``MUTATE_REVERSIBLE``, permission ``edit``). None of them replies to, messages
or notifies a lead: replying stays the Inbox's exact-approval path. ``won`` needs a declared result id; a tool can't
invent one. ``register()`` is idempotent; the coordinator wires it into ``skill_registry.registered_tools()``.
"""
from __future__ import annotations

from . import service as relationships

# Which runtime agent should see each tool (applied through specialists.extend_scope, the runtime owner's API).
TOOL_SCOPES = {"relationship_list": ["rafii_manager"], "relationship_upsert": ["rafii_manager"], "followup_transition": ["rafii_manager"]}
NAMES = tuple(TOOL_SCOPES)
_REGISTERED = False
BRIEF = ("id", "revision", "displayName", "state", "interest", "nextAction", "due", "followUp", "owner", "threadIds", "won")


def _disabled():
    return {"ok": False, "code": "feature_disabled", "message": f"{relationships.FLAG} is off, so this tool is unavailable.", "verified": False}


def _app_error(error):
    return {"ok": False, "verified": False, "code": getattr(error, "code", None) or "tool_failed", "message": str(error)[:300]}


def _service(ctx):
    from .http import ensure
    return ensure(ctx.service)


def _brief(relationship):
    return {key: relationship.get(key) for key in BRIEF}


def register():
    """Register the three tools once; re-bind scopes on every call (idempotent)."""
    global _REGISTERED
    from ..agent_runtime_v2 import contracts, tool_adapter
    if not _REGISTERED and "relationship_list" not in tool_adapter.REGISTRY:
        _register(contracts, tool_adapter)
    _REGISTERED = True
    _bind_runtime()


def _register(contracts, tool_adapter):
    from postriff_alpha.domain import AlphaError
    from ..agent_runtime_v2.context import untrusted
    from ..contracts import digest

    @tool_adapter.register(contracts.ToolSpec("relationship_list", contracts.READ, "read",
                                              "List the workspace's relationships and follow-ups, due first: state, owner, next action, due time and "
                                              "whether a follow-up is due now. Reads only.", voice=True),
                           {"state": {"type": "string", "enum": ["open", "all", *relationships.STATES]},
                            "due": {"type": "string", "enum": ["due_now", "overdue", "upcoming", "any", "none"]},
                            "owner": {"type": "string", "maxLength": 40}, "threadId": {"type": "string", "maxLength": 40},
                            "cursor": {"type": "string", "maxLength": 300}, "limit": {"type": "integer"}}, "Checked follow-ups")
    def relationship_list(ctx, args):
        if not relationships.enabled():
            return _disabled()
        try:
            data = _service(ctx).list(ctx.workspace_id, ctx.token, {"state": args.get("state"), "due": args.get("due"), "owner": args.get("owner"),
                                                                    "thread": args.get("threadId"), "cursor": args.get("cursor"),
                                                                    "limit": args.get("limit")})
        except AlphaError as error:
            return _app_error(error)
        for item in data["relationships"]:
            ctx.ledger.reference("relationship", item["id"], item["displayName"])
        return {"ok": True, "verified": True, "counts": data["counts"], "nextCursor": data["nextCursor"],
                "relationships": untrusted("APP_STATE", [_brief(item) for item in data["relationships"]])}

    @tool_adapter.register(contracts.ToolSpec("relationship_upsert", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Create a follow-up (optionally from one Inbox conversation) or edit one: name, interest, next action, due "
                                              "time in an IANA zone, owner. Edits need the revision last read. Never sends or replies to anyone.",
                                              idempotent=True, voice=True),
                           {"relationshipId": {"type": "string", "maxLength": 40}, "expectedRevision": {"type": "integer"},
                            "idempotencyKey": {"type": "string", "maxLength": 80}, "displayName": {"type": "string", "maxLength": 120},
                            "interest": {"type": "string", "maxLength": 300}, "nextAction": {"type": "string", "maxLength": 200},
                            "due": {"type": "object"}, "clearDue": {"type": "boolean"}, "threadId": {"type": "string", "maxLength": 40},
                            "ownerId": {"type": "string", "maxLength": 40}}, "Saved a follow-up")
    def relationship_upsert(ctx, args):
        if not relationships.enabled():
            return _disabled()
        service = _service(ctx)
        fields = {key: args[key] for key in ("displayName", "interest", "nextAction") if args.get(key) is not None}
        if args.get("due") is not None:
            fields["due"] = args["due"]
        elif args.get("clearDue"):
            fields["due"] = None
        try:
            if args.get("relationshipId"):
                rid = args["relationshipId"]
                result = service.update(ctx.workspace_id, ctx.token, rid, {**fields, "expectedRevision": args.get("expectedRevision"),
                                                                            **({"idempotencyKey": args["idempotencyKey"]} if args.get("idempotencyKey") else {})})
                if args.get("ownerId") is not None:
                    result = service.assign(ctx.workspace_id, ctx.token, rid, {"ownerId": args["ownerId"], "expectedRevision": result["relationship"]["revision"]})
                if args.get("threadId") is not None:
                    result = service.link_thread(ctx.workspace_id, ctx.token, rid, {"threadId": args["threadId"], "expectedRevision": result["relationship"]["revision"]})
                change = "follow-up updated"
            else:
                # One run retrying the same call creates one record.
                key = args.get("idempotencyKey") or f"agent-{digest({'run': ctx.run_id or ctx.trace_id, 'args': args})[:40]}"
                result = service.create(ctx.workspace_id, ctx.token, {**fields, "idempotencyKey": key,
                                                                      **({"threadId": args["threadId"]} if args.get("threadId") else {}),
                                                                      **({"ownerId": args["ownerId"]} if args.get("ownerId") else {})})
                change = "follow-up created" if not result.get("replayed") else "follow-up already existed"
        except AlphaError as error:
            return _app_error(error)
        relationship = result["relationship"]
        ctx.ledger.reference("relationship", relationship["id"], relationship["displayName"])
        ctx.ledger.changed.append({"type": "relationship", "id": relationship["id"], "change": change, "expected": "saved", "actual": relationship["state"],
                                   "verified": True})
        return {"ok": True, "verified": True, "replayed": bool(result.get("replayed")), "relationship": untrusted("APP_STATE", _brief(relationship))}

    @tool_adapter.register(contracts.ToolSpec("followup_transition", contracts.MUTATE_REVERSIBLE, "edit",
                                              "Move a follow-up: set its state (won needs a declared result id), snooze or unsnooze it, reopen it, or "
                                              "dismiss / restore a due reminder. Reversible and recorded. Never contacts anyone.", idempotent=False, voice=True),
                           {"relationshipId": {"type": "string", "maxLength": 40, "required": True}, "expectedRevision": {"type": "integer", "required": True},
                            "action": {"type": "string", "enum": ["set_state", "snooze", "unsnooze", "reopen", "dismiss", "restore"], "required": True},
                            "state": {"type": "string", "enum": list(relationships.STATES)}, "wonResultId": {"type": "string", "maxLength": 40},
                            "until": {"type": "string", "maxLength": 40}}, "Moved a follow-up")
    def followup_transition(ctx, args):
        if not relationships.enabled():
            return _disabled()
        service = _service(ctx)
        rid, base = args["relationshipId"], {"expectedRevision": args["expectedRevision"]}
        action = args["action"]
        try:
            if action == "set_state":
                if not args.get("state"):
                    return {"ok": False, "verified": False, "code": "tool_input", "message": "Say which state to set."}
                result = service.transition(ctx.workspace_id, ctx.token, rid, {**base, "to": args["state"],
                                                                                 **({"wonResultId": args["wonResultId"]} if args.get("wonResultId") else {})})
            elif action == "snooze":
                result = service.snooze(ctx.workspace_id, ctx.token, rid, {**base, "until": args.get("until")})
            else:
                method = {"unsnooze": service.unsnooze, "reopen": service.reopen, "dismiss": service.dismiss_followup, "restore": service.restore_followup}[action]
                result = method(ctx.workspace_id, ctx.token, rid, base)
        except AlphaError as error:
            return _app_error(error)
        relationship = result["relationship"]
        ctx.ledger.reference("relationship", relationship["id"], relationship["displayName"])
        if result.get("changed"):
            ctx.ledger.changed.append({"type": "relationship", "id": relationship["id"], "change": f"follow-up {action.replace('_', ' ')}",
                                       "expected": args.get("state") or action, "actual": relationship["state"], "verified": True})
        return {"ok": True, "verified": True, "changed": bool(result.get("changed")), "relationship": untrusted("APP_STATE", _brief(relationship))}


def _bind_runtime():
    try:
        from ..agent_runtime_v2 import specialists
    except ImportError:
        return
    for name, agents in TOOL_SCOPES.items():
        for agent_key in agents:
            try:
                specialists.extend_scope(agent_key, [name])
            except (ValueError, AttributeError):
                continue
