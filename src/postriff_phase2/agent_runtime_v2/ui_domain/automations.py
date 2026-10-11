"""J08 — Automations and workspace recovery: every live automation with status, schedule text, time zone and next run; one
automation's plan and next occurrences with exact instants; its run history (paged, newest first); connection status and
capability levels with the notification-center attention items when that feature is on (explicitly `unavailable` when it
is off, never empty); and the allowlisted recovery guides with deep links.

The only action is preparing an automation change through the original `automation_change_propose` (a digest-bound
proposal on a new assistant message; applied only natively). Activating recurrence, approving runs, cancelling,
watching, OAuth, verify and disconnect stay on their own pages.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

ID = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:-]{1,120}$"}
INVALIDATES = ["automations_list", "automation_detail", "open_proposals"]
RECOVERY_GUIDES = ("connect_account", "create_automation", "schedule_draft", "approve_post", "check_plan", "turn_on_web_search", "set_up_voice", "choose_model")


def _tasks(state):
    from ... import automation_edit
    return automation_edit.live_tasks(state)


def _task(state, automation_id):
    task = next((t for t in _tasks(state) if t.get("id") == automation_id), None)
    if task is None:
        raise AlphaError("That automation is not in this workspace.", 404, code="not_found")
    return task


def _zone_of(task):
    zone = (task.get("schedule") or {}).get("timeZone")
    return zone if isinstance(zone, str) and zone else "UTC"


def _next(task):
    nxt = task.get("nextOccurrence") or {}
    at = nxt.get("scheduledFor")
    return {"atUtc": common.iso(at), "local": nxt.get("local"), "offset": nxt.get("offset"), "timeZone": _zone_of(task)} if at else None


def _row(task):
    from ... import automation_plan
    return {"automationId": task["id"], "ref": common.ref("automation", task["id"]), "name": task.get("name") or "Automation", "status": task.get("status"),
            "schedule": automation_plan.describe(task["schedule"]) if task.get("schedule") else None, "timeZone": _zone_of(task),
            "policy": (task.get("workflow") or {}).get("policy") or ("drafts" if not task.get("workflow") else None),
            "platforms": list(dict.fromkeys(d.get("platform") for d in task.get("destinations") or [] if isinstance(d, dict))), "nextRun": _next(task),
            "nextPublish": task.get("nextPublish"), "campaignId": task.get("campaignId"), "pausedReason": task.get("pauseReason"), "version": task.get("version"),
            "href": f"/app/automations?edit={task['id']}"}


def automations_list(dctx, inputs, cursor):
    tasks = _tasks(dctx.state)
    if inputs.get("status"):
        tasks = [t for t in tasks if t.get("status") == inputs["status"]]
    tasks.sort(key=lambda t: ((t.get("nextOccurrence") or {}).get("scheduledFor") or float("inf"), t.get("id")))
    page, next_cursor, start = common.paginate("automations_list", inputs, cursor, tasks, default=50)
    rows = [_row(t) for t in page]
    counts = {}
    for t in _tasks(dctx.state):
        counts[t.get("status")] = counts.get(t.get("status"), 0) + 1
    return ui_contracts.query_result("available" if tasks else "empty", {"automations": rows, "offset": start, "statusCounts": counts}, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(tasks), total=len(tasks))


def automation_detail(dctx, inputs, _cursor):
    from ... import campaigns
    from ...site_agent import tools
    task = _task(dctx.state, inputs["automationId"])
    view = tools.automation_get(dctx.site_context(), task["id"])["data"]
    upcoming = []
    if task.get("status") == "active" and isinstance(task.get("schedule"), dict):
        try:
            upcoming = campaigns.upcoming(task["schedule"], dctx.now, 5)
        except (AlphaError, ValueError, KeyError, TypeError):
            upcoming = []
    data = {**{k: view.get(k) for k in ("taskId", "name", "status", "scheduleText", "policy", "plan", "platforms", "needs", "contentLabel", "voiceMode")},
            "ref": common.ref("automation", task["id"]), "timeZone": _zone_of(task), "nextRun": _next(task), "nextPublish": view.get("nextPublish"),
            "upcoming": [{"atUtc": common.iso(o["scheduledFor"]), "local": o.get("local"), "offset": o.get("offset")} for o in upcoming],
            "version": task.get("version"), "campaignId": task.get("campaignId"), "pausedReason": task.get("pauseReason"),
            "history": sum(1 for o in campaigns._root(dctx.state).get("occurrences") or [] if o.get("taskId") == task["id"]), "href": f"/app/automations?edit={task['id']}"}
    return ui_contracts.query_result("available", data, as_of=common.iso(dctx.now), source_refs=[common.ref("automation", task["id"])], revision=str(task.get("version")),
                                     known=1, total=1, note=None if upcoming or task.get("status") != "active" else "No upcoming run could be computed from this schedule.")


def automation_history(dctx, inputs, cursor):
    from ... import campaigns, lifecycle
    task = _task(dctx.state, inputs["automationId"])
    zone = _zone_of(task)
    runs = [o for o in campaigns._root(dctx.state).get("occurrences") or [] if o.get("taskId") == task["id"]]
    runs.sort(key=lambda o: (-(o.get("scheduledFor") or o.get("createdAt") or 0), str(o.get("id"))))
    page, next_cursor, start = common.paginate("automation_history", inputs, cursor, runs, default=20)
    rows = []
    for o in page:
        at = o.get("scheduledFor") or o.get("anchorAt") or o.get("createdAt")
        cost = o.get("costUsdMicro")
        rows.append({"runId": o.get("id"), "ref": common.ref("automation_run", o.get("id")), "status": lifecycle.status(o), "attention": bool(lifecycle.attention(o)),
                     "scheduledUtc": common.iso(at), "scheduledLocal": common.local(at, zone) if isinstance(at, (int, float)) else None, "timeZone": zone,
                     "completedUtc": common.iso(o.get("completedAt")), "seen": bool(o.get("seenAt")),
                     "cost": {"usdMicro": cost, "state": "known" if isinstance(cost, int) else "unknown"},
                     "items": [{"platform": i.get("platform"), "state": i.get("state"), "reason": str(i.get("reason") or "")[:200] or None} for i in o.get("items") or []][:8]})
    return ui_contracts.query_result("available" if runs else "empty", {"automationId": task["id"], "runs": rows, "offset": start}, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(task.get("version")), next_cursor=next_cursor, known=len(runs), total=len(runs))


def connections_status(dctx, _inputs, _cursor):
    from ...site_agent import tools
    accounts = tools.channels_capabilities(dctx.site_context())["data"]
    attention = {"state": "unavailable", "reason": "feature_disabled", "items": []}
    try:
        from ...coworker.service import attention_enabled
        on = bool(attention_enabled())
    except Exception:  # noqa: BLE001 — the coworker package is optional
        on = False
    if on:
        try:
            from ...coworker import attention as coworker_attention
            cur = dctx.cur
            cur.execute("SAVEPOINT ui_attention")
            try:
                built = coworker_attention.build(cur, dctx.workspace_id, dctx.principal, dctx.member, dctx.state, dctx.now)
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT ui_attention")
            items = built.get("items") if isinstance(built, dict) else built
            items = [i for i in items or [] if isinstance(i, dict)]
            attention = {"state": "available" if items else "empty", "reason": None,
                         "items": [{k: i.get(k) for k in ("kind", "severity", "title", "href", "audience", "subject")} for i in items if isinstance(i, dict)][:20]}
        except Exception:  # noqa: BLE001 — a missing reader is unavailable, never empty
            attention = {"state": "unavailable", "reason": "reader_unavailable", "items": []}
    from ...channels import ATTENTION_STATES   # the computed connection states, as the Channels page reads them
    rows = [{**a, "ref": common.ref("connection", a.get("connectionId")), "needsReconnect": a.get("connectionState") in ATTENTION_STATES
             or bool(a.get("revoked"))} for a in accounts.get("accounts") or []]
    data = {"accounts": rows, "publishingLive": accounts.get("publishingLive"), "attention": attention,
            "recovery": {"guideId": "connect_account", "href": "/app/channels"}, "rule": "levels come from each account's verified capability record"}
    return ui_contracts.query_result("available" if rows else "empty", data, as_of=common.iso(dctx.now), source_refs=[r["ref"] for r in rows], known=len(rows), total=len(rows),
                                     note=None if attention["state"] != "unavailable" else "Attention items aren't available on this deployment; account states are shown.")


def recovery_guides(dctx, _inputs, _cursor):
    from ...site_agent import guides, tools
    rows = []
    for guide_id in RECOVERY_GUIDES:
        if guides.find(guide_id) is None:
            continue
        try:
            data = tools.ui_guide(dctx.site_context(), guide_id)["data"]
        except AlphaError:
            continue
        rows.append({k: data.get(k) for k in ("guideId", "title", "summary", "href", "page", "canOpen", "reason")})
    return ui_contracts.query_result("available" if rows else "empty", {"guides": rows, "pages": [{"label": "Automations", "href": "/app/automations"},
                                                                                             {"label": "Accounts", "href": "/app/channels"}]},
                                     as_of=common.iso(dctx.now), known=len(rows), total=len(rows))


# --- prepare an automation change --------------------------------------------------------------------------------------
def change_confirm(dctx, inputs):
    if inputs.get("automationId"):
        _task(dctx.state, inputs["automationId"])
    return {"title": "Prepare automation change", "summary": [f"Prepare a proposal: “{inputs['request'][:200]}”.",
                                                              "Nothing changes until you apply it on its card; pausing or resuming needs an owner."],
            "target": "Automation", "timeZone": None, "cost": "No AI cost"}


def change_execute(dctx, inputs, _key):
    from .calendar import persist_proposal, run_tool
    change_confirm(dctx, inputs)
    args = {"request": inputs["request"], **({"automationId": inputs["automationId"]} if inputs.get("automationId") else {})}
    result, ctx = run_tool(dctx, "automation_change_propose", args)
    if not result.get("ok") or not ctx.ledger.proposals:
        reason = result.get("question") or result.get("error") or "Rafii couldn't prepare that change."
        return Receipt(outcome="rejected", message=str(reason)[:300], next_context={"code": str(result.get("code") or "not_possible")[:60],
                                                                                      "candidates": [str(c)[:120] for c in result.get("candidates") or []][:5]})
    proposal = ctx.ledger.proposals[-1]
    stored = persist_proposal(dctx, proposal, ctx.ledger.references, "Prepared for your review: " + "; ".join(proposal.get("summary") or [])[:600])
    return Receipt(outcome="prepared", receipt_ref=f"message:{stored['messageId']}", proposal_ref=proposal["id"], changed_refs=[common.ref("proposal", proposal["id"])],
                   invalidation_keys=INVALIDATES, next_context={"proposal": {"proposalId": proposal["id"], "messageId": stored["messageId"],
                                                                             "conversationId": dctx.artifact["conversation_id"], "digest": proposal.get("digest"),
                                                                             "expiresAt": common.iso(proposal.get("expiresAt")), "type": proposal.get("type"),
                                                                             "requiredPermission": proposal.get("requiredPermission")},
                                                                "references": [{"type": "automation", "id": proposal.get("taskId")}]},
                   message="Prepared. Nothing changes until you apply the proposal on its card.")


query("automations_list", "J08", "Every live automation: status, schedule in words, time zone, policy, platforms and next run (exact instant and local time).",
      {"status": {"type": "string", "enum": ["draft", "active", "paused"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, automations_list, page=50,
      refresh=60, tool="automation.list", also=("J05",))
query("automation_detail", "J08", "One automation: plan, policy, platforms, what it still needs, and its next occurrences with exact instants in its own time zone.",
      {"automationId": ID}, automation_detail, required=("automationId",), refresh=60, tool="automation.get", also=("J05",))
query("automation_history", "J08", "An automation's runs, newest first (paged): status, when (its time zone), per-platform outcome and cost state (unknown stays unknown).",
      {"automationId": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, automation_history, required=("automationId",), page=20, refresh=60)
query("connections_status", "J08", "Connected accounts with connection state, verified capability levels and whether posts can publish; attention items when the feature is on.",
      {}, connections_status, refresh=60, tool="channels.capabilities")
query("recovery_guides", "J08", "The in-app step-by-step guides that fix common problems (connect an account, set up voice, check the plan…) and whether you can open each.",
      {}, recovery_guides, refresh=None)
action("automation_change_prepare", "J08", "Prepare change", "Prepares a proposal to change an automation (day, time, platforms, sources, approval policy, pause/resume). "
       "Nothing changes until you apply it.", "MUTATE_REVERSIBLE", "edit", {"automationId": ID, "request": {"type": "string", "minLength": 3, "maxLength": 400}},
       change_confirm, change_execute, required=("request",), tool="automation_change_propose", prepare_only=True, dedupe="intent", also=("J05",))
