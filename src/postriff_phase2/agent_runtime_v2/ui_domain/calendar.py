"""J02 — Calendar and publishing operations: an agenda/week read with exact instants and zones (complete status counts,
paged entries), the publishing queue, one job/review, a deterministic slot check for a proposed time (DST validity,
same-account posts within the app's own 2-hour rule), the open proposals of this conversation, and preparing a
schedule/reschedule PROPOSAL through the original `schedule_propose` path.

Preparing writes a new deterministic assistant message in the same conversation (`siteAgent.blocks=[proposal_diff]`,
`proposals`, `presents`) plus an `action.proposed` run event, so the original apply/dismiss (`POST agent/approvals/decide`
or the native proposal card) and a spoken "yes" find it exactly like a Manager-made proposal. Nothing here applies a
proposal, approves a review or publishes; prepared is never applied.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

ID = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:-]{1,120}$"}
DATE = {"type": "string", "format": "date", "maxLength": 10}
LOCAL = {"type": "string", "format": "local-date-time", "maxLength": 16}
ZONE = {"type": "string", "maxLength": 64, "pattern": r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$"}
PLATFORM = {"type": "string", "maxLength": 40}
INVALIDATES = ["calendar_agenda", "queue_status", "job_detail", "slot_check", "open_proposals"]
MAX_DAY_BUCKETS = 62


def _timing_index(state):
    """id → (manifest timing zone, channelId, fromAutomation) for jobs and reviews."""
    p2 = state.get("phase2") or {}
    out = {}
    for item in list(p2.get("jobs") or []) + list(p2.get("reviews") or []):
        if isinstance(item, dict) and item.get("id"):
            manifest = item.get("manifest") or {}
            out[item["id"]] = {"jobZone": (manifest.get("timing") or {}).get("timeZone"), "fold": (manifest.get("timing") or {}).get("fold"),
                               "fromAutomation": bool(item.get("automation"))}
    return out


def calendar_agenda(dctx, inputs, cursor):
    from ...site_agent import reads, tools
    zone = dctx.zone
    lo, hi = common.window(inputs, zone, dctx.now, default_days=7)
    sctx = dctx.site_context()
    entries = [e for e in reads._entries(sctx, lo, hi, zone) if (not inputs.get("platform") or e.get("platform") == inputs["platform"])
               and (not inputs.get("channelId") or e.get("channelId") == inputs["channelId"])]
    counts, unknown = tools.calendar_status_counts(entries)
    timing = _timing_index(dctx.state)
    page, next_cursor, start = common.paginate("calendar_agenda", inputs, cursor, entries, default=50)
    rows = []
    for e in page:
        meta = timing.get(e["id"]) or {}
        rows.append({"kind": e["kind"], "id": e["id"], "ref": common.ref("job" if e["kind"] == "job" else e["kind"], e["id"]), "state": e.get("state"),
                     "status": tools.calendar_status(e.get("kind"), e.get("state")), "title": e.get("title"), "platform": e.get("platform"), "account": e.get("account"),
                     "channelId": e.get("channelId"), "atUtc": common.iso(e.get("at")), "local": common.local(e.get("at"), zone), "offset": common.offset(e.get("at"), zone),
                     "timeZone": zone, "jobZone": meta.get("jobZone"), "jobLocal": common.local(e.get("at"), meta["jobZone"]) if meta.get("jobZone") else None,
                     "fromAutomation": meta.get("fromAutomation", e.get("kind") == "automation_item"), "excerpt": common.excerpt(e.get("text"), 140), "href": e.get("href")})
    # Derived observations, each with the rule that produced it (never a stored fact).
    close, by_account = [], {}
    for e in entries:
        by_account.setdefault(e.get("channelId") or f"{e.get('platform')}:{e.get('account')}", []).append(e)
    for items in by_account.values():
        for a, b in zip(items, items[1:]):
            if b["at"] - a["at"] < reads.CLOSE_SECONDS:
                close.append({"first": a["id"], "second": b["id"], "platform": a.get("platform"), "account": a.get("account"), "minutes": round((b["at"] - a["at"]) / 60)})
    import datetime as dt
    from zoneinfo import ZoneInfo
    days = []
    first = dt.datetime.fromtimestamp(lo, ZoneInfo(zone)).date()
    last = dt.datetime.fromtimestamp(hi - 1, ZoneInfo(zone)).date()
    if (last - first).days + 1 <= MAX_DAY_BUCKETS:
        cursor_day = first
        while cursor_day <= last:
            iso_day = cursor_day.isoformat()
            days.append({"date": iso_day, "weekday": cursor_day.strftime("%A"), "count": sum(1 for e in entries if common.local(e["at"], zone)[:10] == iso_day)})
            cursor_day += dt.timedelta(days=1)
    data = {"range": {"start": inputs.get("start") or first.isoformat(), "end": inputs.get("end") or last.isoformat(), "timeZone": zone, "startUtc": common.iso(lo),
                      "endUtc": common.iso(hi)},
            "entries": rows, "offset": start, "total": len(entries), "statusCounts": counts, "unknownStates": unknown, "days": days,
            "daysNote": None if days else f"Day buckets are shown for ranges up to {MAX_DAY_BUCKETS} days.",
            "derived": {"closeTogether": {"rule": f"two posts on the same account less than {reads.CLOSE_SECONDS // 3600} hours apart", "pairs": close[:20]},
                        "emptyDays": {"rule": "days from today in this range with nothing scheduled, waiting or planned",
                                      "days": [d["date"] for d in days if d["count"] == 0 and d["date"] >= common.local(dctx.now, zone)[:10]]}},
            "href": "/app/calendar?view=week"}
    return ui_contracts.query_result("available" if entries else "empty", data, as_of=common.iso(dctx.now), source_refs=[r["ref"] for r in rows],
                                     revision=str(dctx.revision), next_cursor=next_cursor, known=len(entries), total=len(entries),
                                     note="Unknown states are counted as unknown, never as scheduled." if unknown else None)


def queue_status(dctx, inputs, _cursor):
    from ...site_agent import tools
    sctx = dctx.site_context()
    summary = tools.queue_summary(sctx)["data"]
    p2 = dctx.state.get("phase2") or {}
    jobs = [j for j in p2.get("jobs") or [] if isinstance(j, dict)]
    limit = common.page_size(inputs, 50)
    waiting = sorted((j for j in jobs if j.get("state") in tools.WAITING), key=lambda j: ((j.get("manifest") or {}).get("timing") or {}).get("timestamp") or 0)
    attention = [j for j in jobs if j.get("state") in tools.ATTENTION]
    reviews = [r for r in p2.get("reviews") or [] if isinstance(r, dict) and r.get("status") == "needs_review"]
    data = {"statusCounts": summary.get("statusCounts"), "unknownStates": summary.get("unknownStates"), "draftsUnscheduled": summary.get("draftsUnscheduled"),
            "waitingApproval": [{"reviewId": r.get("id"), "ref": common.ref("review", r.get("id")), "platform": (r.get("manifest") or {}).get("platform"),
                                 "account": (r.get("manifest") or {}).get("account"), "local": ((r.get("manifest") or {}).get("timing") or {}).get("local"),
                                 "timeZone": ((r.get("manifest") or {}).get("timing") or {}).get("timeZone"), "atUtc": common.iso(((r.get("manifest") or {}).get("timing") or {}).get("timestamp")),
                                 "expired": tools._review_expired(r, dctx.now)} for r in reviews][:limit],
            "upcoming": [{**tools._job_view(sctx, j), "ref": common.ref("job", j.get("id")), "atUtc": common.iso(((j.get("manifest") or {}).get("timing") or {}).get("timestamp"))}
                         for j in waiting][:limit],
            "attention": [{**tools._job_view(sctx, j), "ref": common.ref("job", j.get("id"))} for j in attention][:limit],
            "totals": {"waitingApproval": len(reviews), "upcoming": len(waiting), "attention": len(attention)}, "href": "/app/queue"}
    shown = len(data["waitingApproval"]) + len(data["upcoming"]) + len(data["attention"])
    total = len(reviews) + len(waiting) + len(attention)
    return ui_contracts.query_result("available" if total else "empty", data, as_of=common.iso(dctx.now), revision=str(dctx.revision),
                                     source_refs=[x["ref"] for x in data["waitingApproval"] + data["upcoming"] + data["attention"]][:50], known=shown, total=total,
                                     note=None if shown == total else f"Showing {shown} of {total}; the Queue lists every item.")


def job_detail(dctx, inputs, _cursor):
    from ...site_agent import tools
    result = tools.job_get(dctx.site_context(), inputs["jobId"])
    data = result["data"]
    return ui_contracts.query_result("available", {**data, "ref": common.ref(data.get("kind") or "job", inputs["jobId"])}, as_of=result.get("observedAt"),
                                     source_refs=[common.ref(data.get("kind") or "job", inputs["jobId"])], revision=str(dctx.revision), known=1, total=1)


def _target(state, inputs):
    """(variant, job | None) for a slot or schedule request; foreign ids are the same 404."""
    p2 = state.get("phase2") or {}
    job = None
    if inputs.get("jobId"):
        job = next((j for j in p2.get("jobs") or [] if isinstance(j, dict) and j.get("id") == inputs["jobId"]), None)
        if job is None:
            raise AlphaError("That post is not in this workspace's queue.", 404, code="not_found")
        variant_id = (job.get("manifest") or {}).get("variantId")
    elif inputs.get("draftId"):
        variant_id = inputs["draftId"]
    else:
        raise AlphaError("Name the draft or the waiting post.", 400, code="ui_input")
    variant = next((v for v in state.get("variants") or [] if isinstance(v, dict) and v.get("id") == variant_id), None)
    if variant is None:
        raise AlphaError("That draft is not in this workspace.", 404, code="not_found")
    return variant, job


def _channel_for(state, variant, job, channel_id=None):
    channels = [c for c in (state.get("phase2") or {}).get("channels") or [] if isinstance(c, dict) and not c.get("revoked")]
    wanted = channel_id or variant.get("channelId") or ((job or {}).get("manifest") or {}).get("channelId")
    channel = next((c for c in channels if c.get("id") == wanted), None) if wanted else None
    if channel is None and not channel_id:
        same = [c for c in channels if c.get("platform") == variant.get("platform")]
        channel = same[0] if len(same) == 1 else None
    return channel


def _slot(dctx, inputs):
    from ... import contracts as app_contracts
    from ...site_agent import reads
    zone = common.zone(inputs.get("zone"), dctx.zone)
    variant, job = _target(dctx.state, inputs)
    channel = _channel_for(dctx.state, variant, job, inputs.get("channelId"))
    problems, timing = [], None
    try:
        timing = app_contracts.resolve_time(inputs["local"], zone, None, dctx.now)
    except AlphaError as error:
        problems.append({"code": "time", "message": str(error)})
    collisions = []
    if timing is not None and channel is not None:
        around = reads._entries(dctx.site_context(), timing["timestamp"] - reads.CLOSE_SECONDS, timing["timestamp"] + reads.CLOSE_SECONDS, zone)
        for e in around:
            if e.get("channelId") == channel["id"] and e.get("id") != (job or {}).get("id"):
                collisions.append({"kind": e["kind"], "id": e["id"], "ref": common.ref("job" if e["kind"] == "job" else e["kind"], e["id"]), "local": common.local(e["at"], zone),
                                   "minutesApart": round(abs(e["at"] - timing["timestamp"]) / 60), "status": e.get("state")})
    return variant, job, channel, zone, timing, problems, collisions


def slot_check(dctx, inputs, _cursor):
    if not inputs.get("local") or not (inputs.get("draftId") or inputs.get("jobId")):
        # A view whose time (or draft) is still unset must not error on mount.
        return ui_contracts.query_result("empty", {"draftId": inputs.get("draftId"), "jobId": inputs.get("jobId"), "platform": None, "account": None, "channelId": None,
                                                   "local": None, "timeZone": inputs.get("zone") or dctx.zone, "atUtc": None, "valid": False, "problems": [], "collisions": [],
                                                   "rule": "posts on the same account less than 2 hours apart (Rafii's calendar rule); an observation, not a block"},
                                         as_of=common.iso(dctx.now), known=0, total=0, note="Pick a time" if not inputs.get("local") else "Pick a draft")
    variant, job, channel, zone, timing, problems, collisions = _slot(dctx, inputs)
    if channel is None:
        problems.append({"code": "needs_account", "message": f"This {variant.get('platform')} draft has no account, and Rafii won't pick one for you."})
    data = {"draftId": variant["id"], "jobId": (job or {}).get("id"), "platform": variant.get("platform"), "account": (channel or {}).get("account"),
            "channelId": (channel or {}).get("id"), "local": inputs["local"], "timeZone": zone, "atUtc": (timing or {}).get("utc"), "valid": timing is not None and channel is not None,
            "problems": problems, "collisions": collisions,
            "rule": "posts on the same account less than 2 hours apart (Rafii's calendar rule); an observation, not a block"}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("draft", variant["id"])], revision=str(variant.get("revision")),
                                     known=len(collisions), total=len(collisions), warnings=[p["message"] for p in problems][:5])


def open_proposals(dctx, _inputs, _cursor):
    from .. import approvals
    from ...site_agent import proposals
    items = approvals.open_proposals(dctx.cur, dctx.workspace_id, dctx.artifact["conversation_id"], dctx.now)
    rows = [{"proposalId": i["proposalId"], "messageId": i["messageId"], "type": i.get("type"), "summary": i.get("summary") or [], "digest": i.get("digest"),
             "expiresAt": common.iso(i.get("expiresAt")), "requiredPermission": i.get("requiredPermission"), "status": "proposed",
             "view": proposals.view(i["proposal"], dctx.now)} for i in items][:50]
    return ui_contracts.query_result("available" if rows else "empty", {"proposals": rows, "conversationId": dctx.artifact["conversation_id"],
                                                                        "applyWith": "the native proposal card (agent/approvals/decide)"},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("proposal", r["proposalId"]) for r in rows], known=len(rows), total=len(rows),
                                     note="Prepared proposals are not applied until you apply them on their card.")


# --- prepare a schedule proposal --------------------------------------------------------------------------------------
def schedule_confirm(dctx, inputs):
    if not dctx.member.allows("approve"):
        raise AlphaError("Preparing a post for approval needs the approve permission.", 403, code="tool_forbidden")
    variant, job, channel, zone, timing, problems, collisions = _slot(dctx, inputs)
    if channel is None:
        raise AlphaError(f"This {variant.get('platform')} draft has no account, and Rafii won't pick one for you. Choose it in the schedule dialog.", 409, code="needs_account")
    if timing is None:
        raise AlphaError(problems[0]["message"] if problems else "Use a valid local date, time and time zone.", 400, code="ui_time")
    lines = [f"Prepare the exact {variant.get('platform')} post for {channel.get('account')} at {inputs['local'].replace('T', ' ')} ({zone}).",
             "This only prepares a proposal. You apply it on its card, and the post still needs its own approval before it can publish."]
    if job is not None:
        lines.insert(0, f"Move the waiting post (currently {(job.get('manifest') or {}).get('timing', {}).get('local', '').replace('T', ' ')}).")
    if collisions:
        lines.append(f"{len(collisions)} other post(s) on this account are less than 2 hours away (Rafii's calendar rule).")
    return {"title": "Prepare scheduling proposal", "summary": lines, "target": f"{variant.get('platform')} · {channel.get('account')}", "timeZone": zone,
            "cost": "No AI cost"}


def persist_proposal(dctx, proposal: dict, refs: list[dict], lead: str) -> dict:
    """A deterministic assistant message carrying one prepared proposal, in this artifact's conversation, plus the
    `action.proposed` event on the parent run. The original apply/dismiss and the spoken-"yes" binding read it as-is."""
    from ...agent_runtime import safe_event
    from ...site_agent import contracts as site_contracts
    from ...site_agent import proposals
    view = proposals.view(proposal, dctx.now)
    blocks = [site_contracts.text(lead), {"type": "proposal_diff", "proposal": view}]
    pending = [{"proposalId": proposal["id"], "messageId": None, "type": proposal.get("type"), "summary": proposal.get("summary"), "digest": proposal.get("digest"),
                "expiresAt": proposal.get("expiresAt"), "requiredPermission": proposal.get("requiredPermission")}]
    site = {"version": site_contracts.VERSION, "runId": None, "status": "completed", "intent": "agent", "language": None, "blocks": blocks, "citations": [],
            "grounding": {"required": False, "sufficient": True, "missing": []}, "proposals": [proposal],
            "context": {"route": None, "entity": None, "read": [], "withheld": ["passwords, tokens and keys", "other workspaces"], "stale": False},
            "model": {"id": None, "composedBy": "grounded"}, "followUps": [], "feedback": None, "refs": [r for r in refs if r.get("id")][:12],
            "presents": {"proposalIds": [proposal["id"]], "at": dctx.now}, "uiAction": {"artifactId": dctx.artifact["id"], "via": "rafii_genui"}}
    agent = {**_empty_agent(lead), "pendingApprovals": pending, "blocks": blocks, "references": refs[:20]}
    body = {"text": lead, "runId": None, "siteAgent": site, "agent": agent}
    ideas = dctx.service.ideas
    message = ideas._append_message(dctx.cur, dctx.workspace_id, dctx.artifact["conversation_id"], "assistant", body, None)
    pending[0]["messageId"] = message["messageId"]
    body["agent"]["pendingApprovals"] = pending
    import json
    dctx.cur.execute("UPDATE public.pr_messages SET body=%s::jsonb WHERE id::text=%s AND workspace_id=%s",
                     (json.dumps(body, ensure_ascii=False, default=str), message["messageId"], dctx.workspace_id))
    if dctx.artifact.get("parent_run_id"):
        ideas._insert_event(dctx.cur, dctx.workspace_id, dctx.artifact["parent_run_id"],
                            safe_event("action.proposed", action=proposal.get("type"), proposalId=proposal["id"], status="proposed"))
    return {"messageId": message["messageId"], "view": view}


def _empty_agent(text: str) -> dict:
    from .. import contracts
    result = contracts.empty_result(contracts.new_trace_id(), "text")
    result.update({"answerText": text, "speakableSummary": contracts.speakable(text), "composedBy": "grounded"})
    return result


def run_tool(dctx, name: str, args: dict, *, zone: str | None = None):
    """Run one existing agent tool through the single gate (scope, tenant, role re-check, schema), outside a Manager turn,
    on the request's bound service (commands.direct builds the same context). Returns (result, ctx)."""
    from .. import contracts, domain_tools, tool_adapter
    from ..context import RafiiRunContext
    domain_tools.ensure_registered()
    tool = tool_adapter.REGISTRY.get(name)
    if tool is None or tool.spec.tenant == tool_adapter.FOUNDER_TENANT:
        raise AlphaError("That action isn't available here.", 404, code="ui_action")
    ctx = RafiiRunContext(service=dctx.service, workspace_id=dctx.workspace_id, token=None, principal=dctx.principal, membership=dctx.member,
                          conversation_id=dctx.artifact["conversation_id"], trace_id=contracts.new_trace_id(), modality="text", zone=zone or dctx.zone,
                          run_id=dctx.artifact.get("parent_run_id"), now=lambda: dctx.now, config=getattr(dctx.runtime, "cfg", None), request_text="")
    from .. import authz
    authz.bind_context(ctx, cur=dctx.cur, state=dctx.state, member=dctx.member)
    if getattr(dctx.auth, "verified_activation", None) and getattr(dctx.auth, "authz_mode", "off") == "enforce":
        ctx.authz_actor = authz.Actor("human_ui", ctx.principal, evidence={"activationId": dctx.auth.verified_activation, "capabilityId": "tool." + name})
    return tool_adapter.execute(ctx, tool, args, scope=frozenset({name})), ctx


def schedule_execute(dctx, inputs, _key):
    schedule_confirm(dctx, inputs)   # same checks, same record, inside this transaction
    zone = common.zone(inputs.get("zone"), dctx.zone)
    args = {k: inputs[k] for k in ("draftId", "jobId", "assetId", "alt") if inputs.get(k)}
    args["when"] = inputs["local"]
    result, ctx = run_tool(dctx, "schedule_propose", args, zone=zone)
    if not result.get("ok") or not ctx.ledger.proposals:
        raise AlphaError(result.get("error") or result.get("question") or "Rafii couldn't prepare that proposal.", 409, code=str(result.get("code") or "not_possible")[:60])
    proposal = ctx.ledger.proposals[-1]
    stored = persist_proposal(dctx, proposal, ctx.ledger.references, "Prepared for your review: " + "; ".join(proposal.get("summary") or [])[:600])
    return Receipt(outcome="prepared", verified=False, receipt_ref=f"message:{stored['messageId']}", proposal_ref=proposal["id"],
                   changed_refs=[common.ref("proposal", proposal["id"])], invalidation_keys=INVALIDATES,
                   next_context={"proposal": {"proposalId": proposal["id"], "messageId": stored["messageId"], "conversationId": dctx.artifact["conversation_id"],
                                              "digest": proposal.get("digest"), "expiresAt": common.iso(proposal.get("expiresAt")), "type": proposal.get("type"),
                                              "localTime": proposal.get("localTime"), "timeZone": proposal.get("timeZone"), "requiredPermission": proposal.get("requiredPermission")},
                                 "references": [{"type": "draft", "id": proposal.get("variantId")}]},
                   message="Prepared. Nothing is scheduled until you apply the proposal, and the post still needs its own approval.")


query("calendar_agenda", "J02", "What is scheduled, waiting for approval or planned in a date range (inclusive YYYY-MM-DD dates in a time zone): each entry with its exact UTC "
      "instant, local time and the job's own zone, complete status counts (unknown stays unknown), day counts and rule-labelled observations.",
      {"start": DATE, "end": DATE, "zone": ZONE, "platform": PLATFORM, "channelId": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      calendar_agenda, page=50, refresh=60, tool="calendar.range", invalidated_by=("calendar_agenda",), also=("J05",))
query("queue_status", "J02", "The publishing queue now: reviews waiting for approval, approved posts waiting for their time, posts needing attention, complete counts.",
      {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, queue_status, refresh=60, tool="queue.summary", also=("J08",))
query("job_detail", "J02", "One publishing job or review: state in plain words, timeline, time zone and next safe step.", {"jobId": ID}, job_detail, required=("jobId",),
      refresh=60, tool="job.get")
query("slot_check", "J02", "Check a proposed local time for a draft or waiting post before preparing it: valid in that zone (DST), the account it would use and posts on "
      "the same account less than 2 hours away. Read only.", {"draftId": ID, "jobId": ID, "local": LOCAL, "zone": ZONE, "channelId": ID},
      slot_check, refresh=None)
query("open_proposals", "J02", "Proposals in this conversation still waiting for the person (open, not expired), with digest and expiry. Applied only on their native card.",
      {}, open_proposals, refresh=30, tool="pending_approvals", also=("J05", "J08"))
action("schedule_prepare", "J02", "Prepare schedule", "Prepares a proposal to schedule this draft (or move this waiting post) at the chosen local time. Nothing changes "
       "until you apply it, and the post still needs its own approval to publish.", "PREPARE_EXTERNAL", "approve",
       {"draftId": ID, "jobId": ID, "local": LOCAL, "zone": ZONE, "assetId": {"type": "string", "maxLength": 64, "pattern": r"^[0-9a-f]{32}$"},
        "alt": {"type": "string", "maxLength": 300}}, schedule_confirm, schedule_execute, required=("local", "zone"), tool="schedule_propose", prepare_only=True,
       dedupe="intent", also=("J05",))
