"""Domain tools of the Rafii Agent Runtime: tasks, proposals, campaign relations, drafting, memory, relationships.

Every mutation follows one path (spec §3.2, §23):
    intent → typed tool → permission (re-read) → [proposal + person's decision] → domain command →
    authoritative re-read → comparison with the intended result → verified outcome.
A tool never reports success from the command's return value alone; it re-reads the workspace and compares.

What executes directly, for a member whose role allows it, because the person asked for it in this turn:
- CREATE_DRAFT: drafting through the writing pipeline (drafts are reviewable, never scheduled or published);
- MUTATE_REVERSIBLE: linking drafts/posts to a campaign (organisation only; unlink reverses it; audited).
What only ever becomes a proposal a person applies (digest-bound, stored on the answer like the panel's own):
- PREPARE_EXTERNAL: scheduling a draft or moving a waiting post (it still needs a separate approval to publish);
- automation changes.
Nothing here publishes, approves, replies, deletes, disconnects, buys or reads secrets.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time

from postriff_alpha.domain import AlphaError

from . import contracts, task_state
from .context import RafiiRunContext
from .tool_adapter import harvest, register

_ID = r"^[A-Za-z0-9_.:-]{1,120}$"
STEP = {"type": "string", "pattern": r"^s[0-9]{1,2}$", "description": "The task step this call works on (from task_plan), if any."}
PLATFORMS = ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu")


# --- tasks (§16) -----------------------------------------------------------------------------------------------------------
def _plan(ctx: RafiiRunContext):
    if ctx.task is None:
        raise AlphaError("There is no task plan yet. Call task_plan first.", 400, code="no_task")
    return ctx.task


def persist_task(ctx: RafiiRunContext) -> None:
    """Save the plan now (short transaction) so the panel and Voice Mode see progress while the turn continues."""
    if ctx.task is None or not ctx.task.changes:
        return
    with ctx.workspace() as (cur, _row, _principal, _member, _state):
        task_state.save(cur, ctx.service.ideas, ctx.workspace_id, ctx.task, trace_id=ctx.trace_id)


@register(contracts.ToolSpec("task_plan", contracts.READ, "read", "Create (or extend) the plan for a request with more than one meaningful action. "
                             "One step per requested action, in order; name dependencies by earlier step ids. Nothing runs by planning."),
          {"title": {"type": "string", "maxLength": 140, "required": True},
           "steps": {"type": "array", "maxItems": task_state.MAX_STEPS, "required": True,
                     "items": {"type": "object", "properties": {"label": {"type": "string", "maxLength": 140}, "kind": {"type": "string", "maxLength": 40},
                                                                "dependsOn": {"type": "array", "items": {"type": "string"}}}, "required": ["label"]}}},
          "Planned the steps")
def task_plan(ctx: RafiiRunContext, args: dict) -> dict:
    now = ctx.now()
    if ctx.task is None or ctx.task.status != "running":
        with ctx.workspace() as (cur, _row, principal, _member, _state):
            ctx.task = task_state.create(cur, ctx.service.ideas, ctx.workspace_id, ctx.conversation_id, principal, args["title"], ctx.trace_id)
    added = []
    for raw in args["steps"]:
        if not isinstance(raw, dict):
            raise AlphaError("Each step needs a label.", 400, code="tool_input")
        step = ctx.task.add(raw.get("label"), kind=raw.get("kind"), depends_on=[d for d in raw.get("dependsOn") or [] if isinstance(d, str)], now=now)
        added.append({"stepId": step.id, "label": step.label, "dependsOn": step.depends_on})
    persist_task(ctx)
    return {"ok": True, "verified": True, "taskId": ctx.task.task_id, "steps": added}


@register(contracts.ToolSpec("task_update", contracts.READ, "read", "Say that a step is running, blocked, needs the person, or was cancelled, with the reason. "
                             "Only the tool that does a step's work can mark it done or failed."),
          {"stepId": {**STEP, "required": True}, "state": {"type": "string", "enum": list(task_state.MODEL_SETTABLE), "required": True},
           "reason": {"type": "string", "maxLength": 300}},
          "Updated a step")
def task_update(ctx: RafiiRunContext, args: dict) -> dict:
    step = _plan(ctx).model_set(args["stepId"], args["state"], args.get("reason"), ctx.now())
    persist_task(ctx)
    return {"ok": True, "verified": True, "step": step.view()}


def _step_start(ctx, args):
    if args.get("stepId") and ctx.task is not None:
        ctx.task.start(args["stepId"], ctx.now())
        persist_task(ctx)


def _step_done(ctx, args, *, verified, outputs=(), entities=()):
    if args.get("stepId") and ctx.task is not None:
        ctx.task.complete(args["stepId"], ctx.now(), outputs=list(outputs), entities=list(entities), verified=verified)
        persist_task(ctx)


def _step_failed(ctx, args, reason):
    if args.get("stepId") and ctx.task is not None:
        step = ctx.task.step(args["stepId"])
        if step.state not in contracts.TERMINAL_STEP_STATES:
            ctx.task.fail(args["stepId"], reason, ctx.now())
            persist_task(ctx)


def _step_waits(ctx, args, reason, approvals=()):
    if args.get("stepId") and ctx.task is not None:
        ctx.task.wait_for_person(args["stepId"], reason, ctx.now(), approvals=approvals)
        persist_task(ctx)


def guarded(fn):
    """A step-bound tool marks its step failed when it fails, with the real reason (never silently dropped)."""
    def run(ctx: RafiiRunContext, args: dict) -> dict:
        _step_start(ctx, args)
        try:
            result = fn(ctx, args)
        except AlphaError as error:
            _step_failed(ctx, args, str(error))
            raise
        if not result.get("ok", True) and not result.get("needsUser"):
            _step_failed(ctx, args, result.get("error") or "It could not be done.")
        return result
    run.__name__ = fn.__name__
    return run


# --- scheduling and automation proposals (§13) --------------------------------------------------------------------------
_ISO_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def resolve_when(text: str, now: float, zone: str) -> tuple[str | None, str | None]:
    """(local "YYYY-MM-DDTHH:MM", None) or (None, question). Deterministic date parsing; a model never computes dates."""
    from .. import workflow_parse
    from ..site_agent import timeframe
    text = (text or "").strip()
    if _ISO_LOCAL.match(text):
        return text, None
    frame = timeframe.parse(text, now, zone)
    clock = workflow_parse._time_in(text)
    if frame is None or frame["end"] - frame["start"] > 25 * 3600:
        return None, "Which day? For example “Thursday at 18:00”."
    if clock is None:
        return None, f"What time on {frame['label']}? For example “{frame['label']} at 18:00”."
    return f"{frame['startDate']}T{clock}", None


def _variant(state, draft_id):
    variant = next((v for v in state.get("variants", []) if isinstance(v, dict) and v.get("id") == draft_id), None)
    if variant is None:
        raise AlphaError("That draft is not in this workspace.", 404, code="not_found")
    return variant


def _proposal_record(ctx: RafiiRunContext, proposal: dict) -> dict:
    """Keep the proposal for the answer message; the person applies it from the panel or by a bound spoken 'yes'."""
    from ..site_agent import proposals as site_proposals
    ctx.ledger.proposals.append(proposal)
    ctx.ledger.known_ids.add(proposal["id"].lower())
    return {"proposalId": proposal["id"], "type": proposal["type"], "summary": proposal.get("summary") or [], "status": "proposed",
            "requiredPermission": proposal.get("requiredPermission"), "expiresAt": proposal.get("expiresAt"),
            "view": site_proposals.view(proposal, ctx.now())}


@register(contracts.ToolSpec("schedule_propose", contracts.PREPARE_EXTERNAL, "approve", "Propose preparing a draft for approval at a day and time "
                             "(or moving a waiting post). Nothing changes until the person applies the proposal, and the post then still needs its own approval "
                             "before it can publish. `when` is the person's words (\"Thursday 18:00\") or YYYY-MM-DDTHH:MM in their time zone.",
                             approval=True, idempotent=False, audit="post.review_prepared_by_proposal"),
          {"draftId": {"type": "string", "pattern": _ID}, "jobId": {"type": "string", "pattern": _ID}, "when": {"type": "string", "maxLength": 120, "required": True},
           "assetId": {"type": "string", "pattern": _ID, "description": "An image in this workspace to publish with the post (Instagram needs one)."},
           "alt": {"type": "string", "maxLength": 300}, "stepId": STEP},
          "Prepared a scheduling proposal")
@guarded
def schedule_propose(ctx: RafiiRunContext, args: dict) -> dict:
    from ..site_agent import proposals as site_proposals
    import inspect
    if not args.get("draftId") and not args.get("jobId"):
        raise AlphaError("Name the draft (or the waiting post) to schedule.", 400, code="tool_input")
    local_time, question = resolve_when(args["when"], ctx.now(), ctx.zone)
    if question:
        _step_waits(ctx, args, question)
        return {"ok": False, "needsUser": True, "code": "needs_time", "question": question}
    with ctx.workspace() as (_cur, _row, principal, member, state):
        if not member.allows("approve"):
            raise AlphaError("Preparing a post for approval needs the approve permission.", 403, code="tool_forbidden")
        p2 = state.get("phase2") or {}
        job = None
        if args.get("jobId"):
            job = next((j for j in p2.get("jobs", []) if j.get("id") == args["jobId"]), None)
            if job is None:
                raise AlphaError("That post is not in this workspace's queue.", 404, code="not_found")
            variant = _variant(state, (job.get("manifest") or {}).get("variantId"))
        else:
            variant = _variant(state, args["draftId"])
        channels = [c for c in p2.get("channels", []) if isinstance(c, dict) and not c.get("revoked")]
        channel = next((c for c in channels if c.get("id") == (variant.get("channelId") or ((job or {}).get("manifest") or {}).get("channelId"))), None)
        if channel is None:
            same = [c for c in channels if c.get("platform") == variant.get("platform")]
            channel = same[0] if len(same) == 1 else None
        if channel is None:
            reason = f"This {variant.get('platform')} draft has no account, and I won't pick one for you. Choose it in the schedule dialog."
            _step_waits(ctx, args, reason)
            return {"ok": False, "needsUser": True, "code": "needs_account", "error": reason}
        media = None
        if args.get("assetId"):
            asset = next((a for a in p2.get("assets", []) if a.get("id") == args["assetId"] and not a.get("deleted")), None)
            if asset is None:
                raise AlphaError("That image is not in this workspace.", 404, code="not_found")
            alt = " ".join(str(args.get("alt") or asset.get("alt") or "").split())[:300]
            if not alt:
                raise AlphaError("Describe the image in a few words (alt text) before it can be attached.", 400, code="needs_alt")
            media = {"assetId": asset["id"], "alt": alt, "rightsConfirmed": True}
        kwargs = dict(variant=variant, channel=channel, local_time=local_time, zone=ctx.zone, actor=principal, now=ctx.now(), commands=ctx.service.commands, job=job)
        if media is not None:
            if "media" not in inspect.signature(site_proposals.build_schedule).parameters:
                reason = "Attaching an image to a scheduled post isn't available from Rafii yet; schedule it from Queue → Drafts with the image."
                _step_waits(ctx, args, reason)
                return {"ok": False, "needsUser": True, "code": "media_unsupported", "error": reason}
            kwargs["media"] = media
        built = site_proposals.build_schedule(state, **kwargs)
    if "refuse" in built:
        # The app's own reason (review first, Instagram needs an image, the account can't post…), not a guess.
        _step_failed(ctx, args, built["refuse"])
        return {"ok": False, "code": built.get("code") or "not_possible", "error": built["refuse"]}
    record = _proposal_record(ctx, built["proposal"])
    ctx.ledger.reference("draft", variant["id"], f"{variant.get('platform')} draft")
    _step_waits(ctx, args, "Waiting for you to apply the proposal.", approvals=[record["proposalId"]])
    return {"ok": True, "verified": True, "needsUser": True, "proposal": record,
            "note": "A proposal only. Nothing is scheduled until the person applies it, and publishing still needs approval of that exact post."}


@register(contracts.ToolSpec("automation_change_propose", contracts.MUTATE_REVERSIBLE, "edit", "Propose a change to an automation in the person's words "
                             "(day, time, platforms, sources, approval policy, pause/resume). Nothing changes until the person applies it; pausing and "
                             "resuming need an owner; deleting stays on the Automations page.", approval=True, idempotent=False, audit="automation.changed_by_proposal"),
          {"request": {"type": "string", "maxLength": 400, "required": True}, "automationId": {"type": "string", "pattern": _ID}, "stepId": STEP},
          "Prepared an automation proposal")
@guarded
def automation_change_propose(ctx: RafiiRunContext, args: dict) -> dict:
    from .. import automation_edit
    from ..site_agent import proposals as site_proposals
    with ctx.workspace() as (_cur, _row, principal, member, state):
        target, _ = automation_edit.resolve(state, None, args.get("automationId"), args["request"])
        paid = False
        if target is not None and target.get("route"):
            try:
                paid = ctx.service.ideas._select_runtime(target["route"]).cost_class == "paid"
            except AlphaError:
                paid = True
        providers = getattr(getattr(ctx.service, "oauth", None), "providers", None) or {}
        built = site_proposals.build(state, args["request"], actor=principal, now=ctx.now(), owner=member.allows("owner"), paid=paid, zone=ctx.zone,
                                     conversation_task_id=args.get("automationId") or (target or {}).get("id"), providers=providers,
                                     live=bool(getattr(ctx.service, "publishing_live", False)))
    if "ask" in built:
        _step_waits(ctx, args, built["ask"])
        return {"ok": False, "needsUser": True, "code": "needs_detail", "question": built["ask"], "candidates": built.get("candidates") or []}
    if "refuse" in built:
        _step_failed(ctx, args, built["refuse"])
        return {"ok": False, "code": built.get("code") or "not_possible", "error": built["refuse"]}
    record = _proposal_record(ctx, built["proposal"])
    ctx.ledger.reference("automation", built["proposal"]["taskId"], built["proposal"].get("name"))
    _step_waits(ctx, args, "Waiting for you to apply the proposal.", approvals=[record["proposalId"]])
    return {"ok": True, "verified": True, "needsUser": True, "proposal": record}


# --- campaign relations (K05/X03, §25) --------------------------------------------------------------------------------------
def _campaign(state, campaign_id):
    from .. import campaigns
    campaign = next((c for c in campaigns._root(state)["campaigns"] if c.get("id") == campaign_id), None)
    if campaign is None:
        raise AlphaError("That campaign is not in this workspace.", 404, code="not_found")
    return campaign


def _link_command(ctx: RafiiRunContext, action: str, args: dict) -> dict:
    """Run the campaign's own link/unlink action through the workspace command path, audited, then re-read."""
    from .. import campaigns
    payload = {"campaignId": args["campaignId"], "draftIds": list(dict.fromkeys(args.get("draftIds") or [])), "jobIds": list(dict.fromkeys(args.get("jobIds") or []))}
    if args.get("assetIds"):
        if "asset" not in getattr(campaigns, "LINK_KEYS", {}):
            # The campaign relation has no asset kind yet: say so instead of storing the link somewhere else.
            raise AlphaError("Adding an image to a campaign isn't supported by the campaign record yet; the image stays in your library and on the post.", 409,
                             code="asset_link_unsupported")
        payload["assetIds"] = list(dict.fromkeys(args["assetIds"]))
    if not payload["draftIds"] and not payload["jobIds"] and not payload.get("assetIds"):
        raise AlphaError("Name the drafts, posts or images.", 400, code="tool_input")
    kind = "campaign.items_linked" if action == "raffi_campaign_link" else "campaign.items_unlinked"
    repo = ctx.service.repository
    for attempt in range(2):
        revision = repo.get(ctx.workspace_id, ctx.token)["revision"]
        try:
            repo.command(ctx.workspace_id, ctx.token, revision, lambda state, actor: ctx.service.commands(state, actor, action, payload), requirement="edit",
                         audit_event=lambda _s: (kind, payload["campaignId"], {"drafts": len(payload["draftIds"]), "posts": len(payload["jobIds"]), "assets": len(payload.get("assetIds") or []),
                                                                              "via": "rafii_agent", "traceId": ctx.trace_id}))
            break
        except AlphaError as error:
            if error.code != "workspace_revision_conflict" or attempt:
                raise
    return payload


def _verify_links(ctx: RafiiRunContext, payload: dict, *, linked: bool) -> tuple[bool, list[dict]]:
    from .. import campaigns
    state = ctx.snapshot()["state"]
    checks = []
    for kind, key in (("draft", "draftIds"), ("post", "jobIds"), ("asset", "assetIds")):
        for ident in payload.get(key) or []:
            present = any(item["campaign"].get("id") == payload["campaignId"] for item in campaigns.linked_campaigns(state, kind, ident))
            checks.append({"type": kind, "id": ident, "expected": "linked" if linked else "not linked", "actual": "linked" if present else "not linked",
                           "verified": present == linked})
    return all(c["verified"] for c in checks), checks


@register(contracts.ToolSpec("campaign_link", contracts.MUTATE_REVERSIBLE, "edit", "Add drafts and/or posts to a campaign (organisation only: nothing is "
                             "drafted, scheduled or published; campaign_unlink reverses it). The result is re-read from the workspace.",
                             idempotent=True, audit="campaign.items_linked"),
          {"campaignId": {"type": "string", "pattern": _ID, "required": True}, "draftIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
           "jobIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20}, "assetIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20}, "stepId": STEP},
          "Linked items to the campaign")
@guarded
def campaign_link(ctx: RafiiRunContext, args: dict) -> dict:
    with ctx.workspace() as (_cur, _row, _principal, _member, state):
        campaign = _campaign(state, args["campaignId"])
        if campaign.get("status") == "cancelled":
            raise AlphaError("This campaign is cancelled.", 409, code="campaign_cancelled")
    payload = _link_command(ctx, "raffi_campaign_link", args)
    verified, checks = _verify_links(ctx, payload, linked=True)
    for check in checks:
        ctx.ledger.changed.append({"type": check["type"], "id": check["id"], "change": f"linked to campaign {payload['campaignId']}", **check})
        ctx.ledger.reference({"draft": "draft", "post": "job", "asset": "asset"}[check["type"]], check["id"])
    ctx.ledger.reference("campaign", payload["campaignId"], (campaign.get("goal") or "")[:80])
    _step_done(ctx, args, verified=verified, outputs=[{"type": "campaign", "id": payload["campaignId"]}], entities=[{"type": c["type"], "id": c["id"]} for c in checks])
    return {"ok": verified, "verified": verified, "campaignId": payload["campaignId"], "checks": checks,
            **({} if verified else {"error": "The link could not be confirmed by re-reading the campaign."})}


@register(contracts.ToolSpec("campaign_unlink", contracts.MUTATE_REVERSIBLE, "edit", "Remove drafts and/or posts from a campaign (organisation only). "
                             "The result is re-read from the workspace.", idempotent=True, audit="campaign.items_unlinked"),
          {"campaignId": {"type": "string", "pattern": _ID, "required": True}, "draftIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
           "jobIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20}, "assetIds": {"type": "array", "items": {"type": "string"}, "maxItems": 20}, "stepId": STEP},
          "Removed items from the campaign")
@guarded
def campaign_unlink(ctx: RafiiRunContext, args: dict) -> dict:
    with ctx.workspace() as (_cur, _row, _principal, _member, state):
        _campaign(state, args["campaignId"])
    payload = _link_command(ctx, "raffi_campaign_unlink", args)
    verified, checks = _verify_links(ctx, payload, linked=False)
    for check in checks:
        ctx.ledger.changed.append({"type": check["type"], "id": check["id"], "change": f"removed from campaign {payload['campaignId']}", **check})
    _step_done(ctx, args, verified=verified, outputs=[{"type": "campaign", "id": payload["campaignId"]}])
    return {"ok": verified, "verified": verified, "campaignId": payload["campaignId"], "checks": checks}


@register(contracts.ToolSpec("campaign_items", contracts.READ, "read", "The drafts and posts a person linked to a campaign (with who and when), and the "
                             "campaigns a given draft or post belongs to."),
          {"campaignId": {"type": "string", "pattern": _ID}, "draftId": {"type": "string", "pattern": _ID}, "jobId": {"type": "string", "pattern": _ID}},
          "Read the campaign's items")
def campaign_items(ctx: RafiiRunContext, args: dict) -> dict:
    from .. import campaigns
    with ctx.workspace() as (_cur, _row, _principal, _member, state):
        if args.get("campaignId"):
            campaign = _campaign(state, args["campaignId"])
            variants = {v.get("id"): v for v in state.get("variants", []) if isinstance(v, dict)}
            items = []
            for item in campaign.get("items") or []:
                if item.get("kind") == "draft":
                    v = variants.get(item.get("variantId")) or {}
                    items.append({"kind": "draft", "draftId": item.get("variantId"), "platform": v.get("platform"), "exists": bool(v), "addedAt": item.get("addedAt"),
                                  "excerpt": " ".join((v.get("text") or "").split())[:100] or None})
                elif item.get("kind") == "post":
                    items.append({"kind": "post", "jobId": item.get("jobId"), "addedAt": item.get("addedAt")})
            data = {"campaignId": campaign["id"], "goal": campaign.get("goal"), "items": items[:50]}
        else:
            kind, ident = ("draft", args.get("draftId")) if args.get("draftId") else ("post", args.get("jobId"))
            if not ident:
                raise AlphaError("Name a campaign, a draft or a post.", 400, code="tool_input")
            found = campaigns.linked_campaigns(state, kind, ident)
            data = {"item": {"kind": kind, "id": ident}, "campaigns": [{"campaignId": f["campaign"]["id"], "goal": f["campaign"].get("goal"), "addedAt": f["item"].get("addedAt")} for f in found]}
    harvest(ctx, data)
    return {"ok": True, "verified": True, "data": data}


# --- drafting through the writing pipeline (CREATE_DRAFT; D04) ---------------------------------------------------------------
def _writing_run(ctx: RafiiRunContext, request: dict, *, separate: bool) -> tuple[str, dict]:
    """Run the writing pipeline in this conversation and save its candidates, as the panel's Save does."""
    ideas = ctx.service.ideas
    ctx.check_cancelled()
    if ctx.writer_model:
        request["model"] = ctx.writer_model
    result = ideas.turn(ctx.workspace_id, ctx.token, ctx.conversation_id, request)
    run_id = result.get("runId")
    if not run_id:
        raise AlphaError("The writer did not start.", 502, code="writer_unavailable")
    events = ideas.events(ctx.workspace_id, ctx.token, run_id) if hasattr(ideas, "events") else result
    status = events.get("status") or result.get("status")
    artifact_hash = events.get("artifactHash") or result.get("artifactHash")
    if status == "running":
        raise AlphaError("The writer is still working on this draft; it will appear in this conversation.", 202, code="writer_pending")
    if status not in ("completed", "applied") or not artifact_hash:
        raise AlphaError("The writer didn't produce a draft this time. Nothing was saved.", 502, code="writer_failed")
    ctx.check_cancelled()
    for attempt in range(2):
        revision = ctx.service.repository.get(ctx.workspace_id, ctx.token)["revision"]
        try:
            ideas.apply(ctx.workspace_id, ctx.token, revision, run_id, artifact_hash, separate=separate)
            break
        except AlphaError as error:
            if error.status != 409 or attempt:
                raise
    return run_id, ctx.snapshot()["state"]


def _draft_view(ctx, state, variant, *, proposed=False):
    channel = next((c for c in (state.get("phase2") or {}).get("channels", []) if c.get("id") == variant.get("channelId")), {})
    text = ((variant.get("proposedUpdate") or {}).get("text") if proposed else None) or variant.get("text") or ""
    return {"draftId": variant["id"], "platform": variant.get("platform"), "language": variant.get("language"), "account": channel.get("account"),
            "characters": len(text), "excerpt": " ".join(text.split())[:160], "proposedUpdate": proposed}


@register(contracts.ToolSpec("draft_create", contracts.CREATE_DRAFT, "edit", "Write new drafts through Rafii's writing pipeline (the writer the person "
                             "chose, their Brand Brain and voice) and save them as reviewable drafts. Nothing is scheduled or published. Optionally from a "
                             "campaign's brief. Returns the saved draft ids, re-read from the workspace.", idempotent=False),
          {"brief": {"type": "string", "maxLength": 1500, "required": True},
           "platforms": {"type": "array", "items": {"type": "string", "enum": list(PLATFORMS)}, "maxItems": 5, "required": True},
           "language": {"type": "string", "maxLength": 20}, "campaignId": {"type": "string", "pattern": _ID}, "stepId": STEP},
          "Wrote and saved drafts")
@guarded
def draft_create(ctx: RafiiRunContext, args: dict) -> dict:
    platforms = [p for p in dict.fromkeys(args["platforms"]) if p in PLATFORMS]
    if not platforms:
        raise AlphaError("Choose at least one platform.", 400, code="tool_input")
    with ctx.workspace() as (_cur, _row, _principal, member, state):
        if not member.allows("edit"):
            raise AlphaError("Your role can't create drafts.", 403, code="tool_forbidden")
        material = args["brief"]
        material_ref = None
        if args.get("campaignId"):
            campaign = _campaign(state, args["campaignId"])
            facts = "; ".join(f"{k}: {v}" for k, v in (campaign.get("facts") or {}).items())
            material = f"Campaign goal: {campaign.get('goal')}\nAudience: {campaign.get('audience')}" + (f"\nFacts: {facts}" if facts else "") + f"\nRequest: {args['brief']}"
            material_ref = {"type": "campaign", "id": campaign["id"], "title": (campaign.get("goal") or "")[:80]}
        channels = [c for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and not c.get("revoked") and c.get("configured", True)]
        destinations = []
        for platform in platforms:
            same = [c for c in channels if c.get("platform") == platform]
            destinations.append({"platform": platform, "language": args.get("language") or "en", **({"channelId": same[0]["id"]} if len(same) == 1 else {})})
    key = "agent-draft:" + hashlib.sha256(f"{ctx.trace_id}|{args['brief']}|{platforms}|{args.get('campaignId')}".encode()).hexdigest()[:40]
    # Empty `text`: the pipeline appends no user message (the person did not type this brief); the brief is the idea and
    # the material is data, never parsed for channels, days or instructions (ideas.turn "reworking").
    request = {"text": "", "intentText": args["brief"], "idea": args["brief"], "material": material, "destinations": destinations, "idempotencyKey": key,
               "timeZone": ctx.zone, **({"materialRef": material_ref} if material_ref else {})}
    run_id, state = _writing_run(ctx, request, separate=True)
    saved = [v for v in state.get("variants", []) if isinstance(v, dict) and (v.get("provenance") or {}).get("runId") == run_id]
    verified = bool(saved) and all(v.get("platform") in platforms for v in saved)
    views = [_draft_view(ctx, state, v) for v in saved]
    for view in views:
        ctx.ledger.reference("draft", view["draftId"], f"{view['platform']} draft")
        ctx.ledger.changed.append({"type": "draft", "id": view["draftId"], "change": "created", "expected": "saved draft", "actual": "saved draft", "verified": True})
    _step_done(ctx, args, verified=verified, outputs=[{"type": "draft", "id": v["draftId"]} for v in views])
    return {"ok": verified, "verified": verified, "runId": run_id, "drafts": views,
            **({} if verified else {"error": "The writer ran, but no saved draft was found when I re-read the workspace."})}


@register(contracts.ToolSpec("draft_rewrite", contracts.CREATE_DRAFT, "edit", "Rewrite, shorten or adapt one draft through the writing pipeline. The result "
                             "is a proposed update on that same draft (its current text stays until the person accepts it), or a new draft for another "
                             "platform. Re-read from the workspace.", idempotent=False),
          {"draftId": {"type": "string", "pattern": _ID, "required": True}, "instruction": {"type": "string", "maxLength": 600, "required": True},
           "platform": {"type": "string", "enum": list(PLATFORMS)}, "stepId": STEP},
          "Rewrote the draft")
@guarded
def draft_rewrite(ctx: RafiiRunContext, args: dict) -> dict:
    with ctx.workspace() as (_cur, _row, _principal, member, state):
        if not member.allows("edit"):
            raise AlphaError("Your role can't change drafts.", 403, code="tool_forbidden")
        variant = _variant(state, args["draftId"])
        before_text = variant.get("text") or ""
        platform = args.get("platform") or variant.get("platform")
        destination = {"platform": platform, "language": variant.get("language") or "en"}
        if platform == variant.get("platform") and variant.get("channelId"):
            destination["channelId"] = variant["channelId"]
    key = "agent-rewrite:" + hashlib.sha256(f"{ctx.trace_id}|{args['draftId']}|{args['instruction']}|{platform}".encode()).hexdigest()[:40]
    request = {"text": "", "intentText": args["instruction"], "idea": args["instruction"], "material": before_text, "idempotencyKey": key, "timeZone": ctx.zone,
               "materialRef": {"type": "draft", "id": args["draftId"], "title": f"{variant.get('platform')} draft"}, "destinations": [destination]}
    run_id, state = _writing_run(ctx, request, separate=False)
    updated = next((v for v in state.get("variants", []) if v.get("id") == args["draftId"]), None)
    derived = [v for v in state.get("variants", []) if (v.get("provenance") or {}).get("runId") == run_id and v.get("id") != args["draftId"]]
    if updated is not None and (updated.get("proposedUpdate") or {}).get("runId") == run_id:
        view = _draft_view(ctx, state, updated, proposed=True)
        unchanged = (updated.get("text") or "") == before_text
        ctx.ledger.changed.append({"type": "draft", "id": updated["id"], "change": "proposed update (current text unchanged until accepted)",
                                   "expected": "proposed update", "actual": "proposed update", "verified": unchanged})
        result = {"ok": unchanged, "verified": unchanged, "runId": run_id, "draft": view, "outcome": "proposed_update",
                  "shorter": view["characters"] < len(before_text), "beforeCharacters": len(before_text)}
    elif derived:
        views = [_draft_view(ctx, state, v) for v in derived]
        for view in views:
            ctx.ledger.changed.append({"type": "draft", "id": view["draftId"], "change": f"new draft derived from {args['draftId']}", "expected": "new draft", "actual": "new draft", "verified": True})
        result = {"ok": True, "verified": True, "runId": run_id, "drafts": views, "outcome": "new_draft"}
    else:
        result = {"ok": False, "verified": False, "runId": run_id, "error": "The rewrite ran, but I couldn't find its result on the draft when I re-read the workspace."}
    ctx.ledger.reference("draft", args["draftId"], f"{variant.get('platform')} draft")
    _step_done(ctx, args, verified=result["verified"], outputs=[{"type": "draft", "id": args["draftId"]}])
    return result


# --- layered memory (§14) -------------------------------------------------------------------------------------------------
@register(contracts.ToolSpec("memory_context", contracts.READ, "read", "Rafii's layered memory for this workspace, each item with where it came from: account "
                             "and locale, workspace facts, Brand Brain, voice profile, learned preferences (explicit vs inferred, with support/confidence and "
                             "status), active campaigns and the current task. Private boundaries are withheld unless the owner allowed cloud memory."),
          {"layers": {"type": "array", "items": {"type": "string", "enum": ["identity", "workspace", "brand", "voice", "preferences", "campaigns", "task"]}, "maxItems": 7}},
          "Read Rafii's memory")
def memory_context(ctx: RafiiRunContext, args: dict) -> dict:
    from . import memory_layers
    with ctx.workspace() as (cur, _row, _principal, member, state):
        data = memory_layers.read(state, member=member, cur=cur, workspace_id=ctx.workspace_id, zone=ctx.zone, locale=ctx.locale, task=ctx.task,
                                  layers=args.get("layers") or None)
    return {"ok": True, "verified": True, "data": data}


# --- relationships (§17) ---------------------------------------------------------------------------------------------------
@register(contracts.ToolSpec("relationships", contracts.READ, "read", "How an item relates to others, derived from stored records: a draft's campaign, source, "
                             "reviews, scheduled and published posts and automation; a campaign's automations, drafts and posts; an image's lineage."),
          {"type": {"type": "string", "enum": ["draft", "campaign", "job", "review", "asset", "automation", "source"], "required": True},
           "id": {"type": "string", "pattern": _ID, "required": True}},
          "Read how items relate")
def relationships(ctx: RafiiRunContext, args: dict) -> dict:
    from . import graph
    with ctx.workspace() as (_cur, _row, _principal, _member, state):
        data = graph.neighbours(state, args["type"], args["id"])
    harvest(ctx, data)
    return {"ok": data.get("found", False), "verified": data.get("found", False), "data": data,
            **({} if data.get("found") else {"error": "That item is not in this workspace."})}


# --- approvals (§13) --------------------------------------------------------------------------------------------------------
@register(contracts.ToolSpec("pending_approvals", contracts.READ, "read", "Proposals in this conversation that still wait for the person (open, not expired), newest first."),
          {}, "Checked what waits for approval")
def pending_approvals(ctx: RafiiRunContext, args: dict) -> dict:
    from . import approvals
    with ctx.workspace() as (cur, _row, _principal, _member, _state):
        items = approvals.open_proposals(cur, ctx.workspace_id, ctx.conversation_id, ctx.now())
    for item in items:
        ctx.ledger.known_ids.add(item["proposalId"].lower())
    return {"ok": True, "verified": True, "data": {"pending": [{k: v for k, v in item.items() if k != "proposal"} for item in items]}}


@register(contracts.ToolSpec("proposal_apply", contracts.PREPARE_EXTERNAL, "read", "Ask to apply one open proposal. This always pauses for the person's "
                             "explicit decision; the application then re-checks the digest and their permission, applies it, and re-reads the result.",
                             approval=True, idempotent=True),
          {"proposalId": {"type": "string", "pattern": _ID, "required": True}},
          "Applied a proposal the person approved")
def proposal_apply(ctx: RafiiRunContext, args: dict) -> dict:
    """Runs only after the person approved (SDK interruption resumed by the approval endpoint, which already applied the
    proposal through the site agent's apply path). This call verifies; it never applies a second time."""
    from . import approvals
    with ctx.workspace() as (cur, _row, _principal, _member, _state):
        found = approvals.find(cur, ctx.workspace_id, ctx.conversation_id, args["proposalId"])
    if found is None:
        raise AlphaError("That proposal is not in this conversation.", 404, code="not_found")
    proposal = found["proposal"]
    if proposal.get("status") != "applied":
        return {"ok": False, "verified": False, "code": "not_applied", "status": proposal.get("status"),
                "error": f"The proposal is {proposal.get('status')}; nothing was applied."}
    verified, checks = approvals.verify_applied(ctx.snapshot()["state"], proposal)
    return {"ok": verified, "verified": verified, "proposalId": proposal["id"], "result": proposal.get("result"), "checks": checks}


def ensure_registered() -> None:
    """Import side effects in one place (the registry is filled at import)."""
    from . import creative, specialists  # noqa: F401 — both register tools at import (image_*, web_research)
    from .tool_adapter import register_site_tools
    register_site_tools()


_ = (copy, time)  # kept for callers that patch clocks in tests
