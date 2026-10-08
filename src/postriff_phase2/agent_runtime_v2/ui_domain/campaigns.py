"""J05 — Campaign planning: paged campaigns, one campaign's brief/automations/derived gaps, its complete (paged) membership,
a zone-explicit timeline (upcoming automation runs, run history and linked posts in a window), and the conversation's
multi-step task progress. Calendar and open-proposal bindings are shared with J02.

Actions, all through the campaign's own workspace commands (audited, effects hooks, re-read):
- `campaign_create` (native confirmation; account and image ids checked against this workspace first; one campaign per
  artifact revision and inputs, so a double click or a second tab never makes two);
- `campaign_update` (native confirmation naming how many automations pause and items return to review; refused unless
  the campaign is still at the version the person saw — a compare-and-swap the bare command lacks);
- `campaign_link` / `campaign_unlink` (organisation only, naturally idempotent, re-read verified).
Activating recurrence, approving runs and paid drafting are not here (their own pages and approvals).
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

from .. import ui_contracts
from . import Receipt, action, common, query

ID = {"type": "string", "maxLength": 120, "pattern": r"^[A-Za-z0-9_.:-]{1,120}$"}
IDS = {"type": "array", "maxItems": 20, "items": ID, "uniqueItems": True}
DATE = {"type": "string", "format": "date", "maxLength": 10}
ZONE = {"type": "string", "maxLength": 64, "pattern": r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$"}
INVALIDATES = ["campaigns_list", "campaign_detail", "campaign_items", "campaign_timeline", "drafts_list"]


def _root(state):
    from ... import campaigns
    return campaigns._root(state)


def _campaign(state, campaign_id):
    campaign = next((c for c in _root(state)["campaigns"] if c.get("id") == campaign_id), None)
    if campaign is None:
        raise AlphaError("That campaign is not in this workspace.", 404, code="not_found")
    return campaign


def _progress(state, campaign):
    """Derived progress (no campaign state machine exists): linked items by state and automation runs by status. Labelled."""
    from ... import lifecycle
    root = _root(state)
    variants = {v.get("id"): v for v in state.get("variants") or [] if isinstance(v, dict)}
    jobs = {j.get("id"): j for j in (state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)}
    items = {"drafts": 0, "draftsNeedingReview": 0, "posts": 0, "postsVerified": 0, "postsWaiting": 0, "missing": 0}
    for item in campaign.get("items") or []:
        if item.get("kind") == "draft":
            v = variants.get(item.get("variantId"))
            if v is None:
                items["missing"] += 1
                continue
            items["drafts"] += 1
            items["draftsNeedingReview"] += 1 if (v.get("needsReview") or item.get("needsReview")) else 0
        elif item.get("kind") == "post":
            j = jobs.get(item.get("jobId"))
            if j is None:
                items["missing"] += 1
                continue
            items["posts"] += 1
            items["postsVerified"] += 1 if j.get("state") == "verified" else 0
            items["postsWaiting"] += 1 if j.get("state") in ("approved", "scheduled", "claimed") else 0
    task_ids = {t["id"] for t in root["recurringTasks"] if t.get("campaignId") == campaign["id"] and not t.get("deletedAt")}
    runs: dict[str, int] = {}
    for occurrence in root.get("occurrences") or []:
        if occurrence.get("taskId") in task_ids:
            status = lifecycle.status(occurrence)
            runs[status] = runs.get(status, 0) + 1
    return {"items": items, "runs": runs, "rule": "derived from linked items and automation runs; a campaign has no completion state of its own"}


def campaigns_list(dctx, inputs, cursor):
    from ...site_agent import reads
    sctx = dctx.site_context()
    live = [c for c in _root(dctx.state)["campaigns"] if c.get("status") != "cancelled"]
    if inputs.get("q"):
        words = [w for w in inputs["q"].casefold().split() if w]
        live = [c for c in live if all(w in " ".join([c.get("goal") or "", c.get("audience") or ""]).casefold() for w in words)]
    if inputs.get("status"):
        live = [c for c in live if c.get("status") == inputs["status"]]
    live.sort(key=lambda c: (-(c.get("updatedAt") or c.get("createdAt") or 0), c.get("id")))
    page, next_cursor, start = common.paginate("campaigns_list", inputs, cursor, live, default=50)
    rows = [{**reads._campaign_view(sctx, c), "ref": common.ref("campaign", c["id"]), "version": c.get("version"), "itemCount": len(c.get("items") or []),
             "createdAt": common.iso(c.get("createdAt")), "updatedAt": common.iso(c.get("updatedAt"))} for c in page]
    return ui_contracts.query_result("available" if live else "empty", {"campaigns": rows, "offset": start}, as_of=common.iso(dctx.now),
                                     source_refs=[r["ref"] for r in rows], revision=str(dctx.revision), next_cursor=next_cursor, known=len(live), total=len(live))


def campaign_detail(dctx, inputs, _cursor):
    from ...site_agent import reads
    result = reads.campaign_get(dctx.site_context(), inputs["campaignId"])
    campaign = _campaign(dctx.state, result["data"]["campaignId"])
    data = {**result["data"], "ref": common.ref("campaign", campaign["id"]), "version": campaign.get("version"), "accountIds": list(campaign.get("accountIds") or []),
            "itemCount": len(campaign.get("items") or []), "progress": _progress(dctx.state, campaign),
            "note": "Drafts and posts here are truncated; campaign_items lists every linked item."}
    return ui_contracts.query_result("available", data, as_of=result.get("observedAt"), source_refs=[common.ref("campaign", campaign["id"])],
                                     revision=str(campaign.get("version")), known=1, total=1)


def campaign_items(dctx, inputs, cursor):
    campaign = _campaign(dctx.state, inputs["campaignId"])
    variants = {v.get("id"): v for v in dctx.state.get("variants") or [] if isinstance(v, dict)}
    jobs = {j.get("id"): j for j in (dctx.state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)}
    assets = {a.get("id"): a for a in (dctx.state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict)}
    items = [i for i in campaign.get("items") or [] if isinstance(i, dict)]
    if inputs.get("kind"):
        items = [i for i in items if i.get("kind") == inputs["kind"]]
    page, next_cursor, start = common.paginate("campaign_items", inputs, cursor, items, default=50)
    rows, missing = [], 0
    for item in page:
        kind = item.get("kind")
        row = {"itemId": item.get("id"), "kind": kind, "addedAt": common.iso(item.get("addedAt")), "needsReview": bool(item.get("needsReview")),
               "addedByYou": item.get("addedBy") == dctx.principal}
        if kind == "draft":
            v = variants.get(item.get("variantId"))
            row.update({"draftId": item.get("variantId"), "ref": common.ref("draft", item.get("variantId")), "exists": v is not None,
                        "platform": (v or {}).get("platform"), "revision": (v or {}).get("revision"), "excerpt": common.excerpt((v or {}).get("text"), 120)})
        elif kind == "post":
            j = jobs.get(item.get("jobId"))
            timing = ((j or {}).get("manifest") or {}).get("timing") or {}
            row.update({"jobId": item.get("jobId"), "ref": common.ref("job", item.get("jobId")), "exists": j is not None, "state": (j or {}).get("state"),
                        "platform": ((j or {}).get("manifest") or {}).get("platform"), "local": timing.get("local"), "timeZone": timing.get("timeZone"),
                        "atUtc": common.iso(timing.get("timestamp"))})
        elif kind == "asset":
            a = assets.get(item.get("assetId"))
            row.update({"assetId": item.get("assetId"), "ref": common.ref("asset", item.get("assetId")), "exists": a is not None and not (a or {}).get("deleted")})
        missing += 0 if row.get("exists") else 1
        rows.append(row)
    return ui_contracts.query_result("available" if items else "empty", {"campaignId": campaign["id"], "version": campaign.get("version"), "items": rows, "offset": start,
                                                                         "max": 200},
                                     as_of=common.iso(dctx.now), source_refs=[r["ref"] for r in rows if r.get("ref")], revision=str(campaign.get("version")),
                                     next_cursor=next_cursor, known=len(items), total=len(items),
                                     warnings=["Some linked items are no longer in the workspace."] if missing else [])


def campaign_timeline(dctx, inputs, _cursor):
    from ... import campaigns, lifecycle
    campaign = _campaign(dctx.state, inputs["campaignId"])
    zone = dctx.zone
    lo, hi = common.window(inputs, zone, dctx.now, default_days=30)
    root = _root(dctx.state)
    tasks = [t for t in root["recurringTasks"] if t.get("campaignId") == campaign["id"] and not t.get("deletedAt")]
    events = []
    for task in tasks:
        if task.get("status") == "active" and isinstance(task.get("schedule"), dict):
            try:
                upcoming = campaigns.upcoming(task["schedule"], max(lo, dctx.now), 14)
            except (AlphaError, ValueError, KeyError, TypeError):
                upcoming = []
            for occurrence in upcoming:
                if occurrence["scheduledFor"] < hi:
                    events.append({"kind": "planned_run", "automationId": task["id"], "ref": common.ref("automation", task["id"]), "name": task.get("name"),
                                   "atUtc": common.iso(occurrence["scheduledFor"]), "local": common.local(occurrence["scheduledFor"], zone),
                                   "scheduleZone": (task.get("schedule") or {}).get("timeZone"), "scheduleLocal": occurrence.get("local"), "status": "planned",
                                   "at": occurrence["scheduledFor"]})
    task_ids = {t["id"] for t in tasks}
    for occurrence in root.get("occurrences") or []:
        at = occurrence.get("scheduledFor") or occurrence.get("anchorAt") or occurrence.get("createdAt")
        if occurrence.get("taskId") in task_ids and isinstance(at, (int, float)) and lo <= at < hi:
            events.append({"kind": "run", "runId": occurrence.get("id"), "automationId": occurrence.get("taskId"), "ref": common.ref("automation_run", occurrence.get("id")),
                           "atUtc": common.iso(at), "local": common.local(at, zone), "status": lifecycle.status(occurrence), "at": at,
                           "items": [{"platform": i.get("platform"), "state": i.get("state")} for i in occurrence.get("items") or []][:8]})
    jobs = {j.get("id"): j for j in (dctx.state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)}
    for item in campaign.get("items") or []:
        job = jobs.get(item.get("jobId")) if item.get("kind") == "post" else None
        timing = ((job or {}).get("manifest") or {}).get("timing") or {}
        at = timing.get("timestamp")
        if job and isinstance(at, (int, float)) and lo <= at < hi:
            events.append({"kind": "post", "jobId": job.get("id"), "ref": common.ref("job", job.get("id")), "atUtc": common.iso(at), "local": common.local(at, zone),
                           "jobZone": timing.get("timeZone"), "jobLocal": timing.get("local"), "status": job.get("state"), "at": at,
                           "platform": (job.get("manifest") or {}).get("platform")})
    events.sort(key=lambda e: (e["at"], e["kind"]))
    for e in events:
        e.pop("at", None)
    return ui_contracts.query_result("available" if events else "empty", {"campaignId": campaign["id"], "timeZone": zone, "startUtc": common.iso(lo), "endUtc": common.iso(hi),
                                                                          "events": events[:200], "truncated": len(events) > 200},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("campaign", campaign["id"])], revision=str(campaign.get("version")),
                                     known=min(len(events), 200), total=len(events),
                                     note="Planned runs come from the automation's schedule; dependencies between campaign items are not recorded by Rafii.")


def task_progress(dctx, inputs, _cursor):
    from .. import task_state
    plan = task_state.load(dctx.cur, dctx.workspace_id, inputs["taskId"]) if inputs.get("taskId") else task_state.latest(dctx.cur, dctx.workspace_id, dctx.artifact["conversation_id"])
    if plan is None:
        return ui_contracts.query_result("empty", {"task": None}, as_of=common.iso(dctx.now), known=0, total=0, note="No multi-step task in this conversation.")
    if inputs.get("taskId") and plan.conversation_id not in (None, dctx.artifact["conversation_id"]) if hasattr(plan, "conversation_id") else False:
        raise AlphaError("Task unavailable.", 404)
    view = plan.view()
    steps = view.get("steps") or []
    summary = plan.summary() if hasattr(plan, "summary") else {}
    return ui_contracts.query_result("available", {"task": view, "summary": summary, "rule": "only the tool that did a step's work marks it done"},
                                     as_of=common.iso(dctx.now), source_refs=[common.ref("task", view.get("taskId"))], known=sum(1 for s in steps if s.get("state") == "done"),
                                     total=len(steps))


# --- actions ------------------------------------------------------------------------------------------------------------
def _validate_targets(state, inputs):
    channels = {c.get("id") for c in (state.get("phase2") or {}).get("channels") or [] if isinstance(c, dict) and not c.get("revoked")}
    from ... import asset_kinds
    images = {a.get("id") for a in (state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict) and not a.get("deleted") and asset_kinds.kind_of(a) != "video"}
    bad_accounts = [a for a in inputs.get("accountIds") or [] if a not in channels]
    bad_assets = [a for a in inputs.get("assetIds") or [] if a not in images]
    if bad_accounts or bad_assets:
        raise AlphaError("Some accounts or images aren't in this workspace (or can't be used here).", 404, code="not_found")


def _facts(inputs):
    facts = {}
    for key, value in (inputs.get("facts") or {}).items() if isinstance(inputs.get("facts"), dict) else []:
        facts[key] = value
    return facts


def create_confirm(dctx, inputs):
    _validate_targets(dctx.state, inputs)
    from ... import campaigns
    facts = {k: inputs[k] for k in ("date", "venue") if inputs.get(k)}
    missing = campaigns.missing_facts(inputs["goal"], facts)
    lines = [f"Create a campaign brief: goal ({len(inputs['goal'])} characters) and audience ({len(inputs['audience'])} characters).",
             "Nothing is drafted, scheduled or published; automations are set up separately."]
    if inputs.get("accountIds"):
        lines.append(f"{len(inputs['accountIds'])} account(s) and {len(inputs.get('assetIds') or [])} image(s) attached to the brief.")
    if missing:
        lines.append("Still missing: " + ", ".join(missing) + " (the campaign stays 'needs input').")
    return {"title": "Create campaign", "summary": lines, "target": "New campaign", "timeZone": None, "cost": "No AI cost"}


def create_execute(dctx, inputs, _key):
    create_confirm(dctx, inputs)
    service = dctx.service
    payload = {"goal": inputs["goal"], "audience": inputs["audience"], "facts": {k: inputs[k] for k in ("date", "venue") if inputs.get(k)},
               "accountIds": list(inputs.get("accountIds") or []), "assetIds": list(inputs.get("assetIds") or [])}
    before = {c.get("id") for c in _root(dctx.state)["campaigns"]}
    service.repository.command(dctx.workspace_id, None, dctx.revision, lambda state, actor: service.commands(state, actor, "raffi_campaign_create", payload), requirement="edit",
                               audit_event=lambda _s: ("campaign.created_by_ui", "", {"via": "rafii_genui", "artifactId": dctx.artifact["id"]}))
    after = [c for c in _root(dctx.refresh_state())["campaigns"] if c.get("id") not in before]
    verified = len(after) == 1 and after[0].get("goal") == payload["goal"].strip() and after[0].get("audience") == payload["audience"].strip()
    campaign = after[0] if after else {}
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"campaign:{campaign.get('id')}@{campaign.get('version')}" if campaign else None,
                   changed_refs=[common.ref("campaign", campaign.get("id"))] if campaign else [], invalidation_keys=INVALIDATES,
                   next_context={"references": [{"type": "campaign", "id": campaign.get("id")}]} if campaign else {},
                   message=(f"Created. Status: {campaign.get('status')}." if verified else "The campaign was created but the re-read didn't match; reload."))


def _update_payload(inputs):
    payload = {"campaignId": inputs["campaignId"]}
    for key in ("goal", "audience"):
        if inputs.get(key) is not None:
            payload[key] = inputs[key]
    return payload


def update_confirm(dctx, inputs):
    campaign = _campaign(dctx.state, inputs["campaignId"])
    if campaign.get("version") != inputs["expectedVersion"]:
        raise AlphaError("This campaign changed since you opened it. Reload it before saving.", 409, code="campaign_version_conflict")
    if not inputs.get("goal") and not inputs.get("audience"):
        raise AlphaError("Change the goal or the audience.", 400, code="ui_input")
    root = _root(dctx.state)
    pausing = [t for t in root["recurringTasks"] if t.get("campaignId") == campaign["id"] and t.get("status") == "active"]
    review = [i for i in campaign.get("items") or [] if i.get("status") not in ("published", "scheduled")]
    lines = [f"Update this campaign's brief (version {campaign.get('version')} → {int(campaign.get('version') or 0) + 1})."]
    if pausing:
        lines.append(f"{len(pausing)} active automation(s) of this campaign will pause until you resume them.")
    if review:
        lines.append(f"{len(review)} linked item(s) not yet scheduled or published will be marked for review.")
    return {"title": "Update campaign brief", "summary": lines, "target": "Campaign", "timeZone": None, "cost": "No AI cost"}


def update_execute(dctx, inputs, _key):
    update_confirm(dctx, inputs)
    service = dctx.service
    payload = _update_payload(inputs)

    def change(state, actor):
        current = _campaign(state, inputs["campaignId"])
        if current.get("version") != inputs["expectedVersion"]:
            raise AlphaError("This campaign changed since you opened it. Reload it before saving.", 409, code="campaign_version_conflict")
        return service.commands(state, actor, "raffi_campaign_update", payload)

    service.repository.command(dctx.workspace_id, None, dctx.revision, change, requirement="edit",
                               audit_event=lambda _s: ("campaign.updated_by_ui", inputs["campaignId"], {"via": "rafii_genui", "artifactId": dctx.artifact["id"]}))
    saved = _campaign(dctx.refresh_state(), inputs["campaignId"])
    verified = saved.get("version") == inputs["expectedVersion"] + 1 and all(saved.get(k) == str(payload[k]).strip() for k in ("goal", "audience") if k in payload)
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"campaign:{saved['id']}@{saved.get('version')}", changed_refs=[common.ref("campaign", saved["id"])],
                   invalidation_keys=INVALIDATES + ["automations_list", "automation_detail"],
                   next_context={"references": [{"type": "campaign", "id": saved["id"]}], "campaign": {"version": saved.get("version"), "status": saved.get("status")}},
                   message="Saved. Active automations of this campaign are paused until you resume them." if verified else "Saved, but the re-read didn't match; reload.")


def _link(dctx, inputs, action_name, linked):
    from ... import campaigns
    service = dctx.service
    _campaign(dctx.state, inputs["campaignId"])
    payload = {"campaignId": inputs["campaignId"], "draftIds": list(inputs.get("draftIds") or []), "jobIds": list(inputs.get("jobIds") or [])}
    if not payload["draftIds"] and not payload["jobIds"]:
        raise AlphaError("Choose drafts or posts.", 400, code="ui_input")
    kind = "campaign.items_linked" if linked else "campaign.items_unlinked"
    service.repository.command(dctx.workspace_id, None, dctx.revision, lambda state, actor: service.commands(state, actor, action_name, payload), requirement="edit",
                               audit_event=lambda _s: (kind, payload["campaignId"], {"drafts": len(payload["draftIds"]), "posts": len(payload["jobIds"]), "via": "rafii_genui"}))
    state = dctx.refresh_state()
    checks = []
    for kind_name, key in (("draft", "draftIds"), ("post", "jobIds")):
        for ident in payload[key]:
            present = any(item["campaign"].get("id") == payload["campaignId"] for item in campaigns.linked_campaigns(state, kind_name, ident))
            checks.append({"type": kind_name, "id": ident, "verified": present == linked})
    verified = all(c["verified"] for c in checks)
    return Receipt(outcome="applied", verified=verified, receipt_ref=f"campaign:{payload['campaignId']}", changed_refs=[common.ref(c["type"], c["id"]) for c in checks],
                   invalidation_keys=INVALIDATES, next_context={"references": [{"type": "campaign", "id": payload["campaignId"]}],
                                                                "checks": checks[:40]},
                   message=("Linked." if linked else "Removed.") if verified else "The change couldn't be confirmed by re-reading the campaign.")


def link_confirm(dctx, inputs):
    _campaign(dctx.state, inputs["campaignId"])
    n = len(inputs.get("draftIds") or []) + len(inputs.get("jobIds") or [])
    return {"title": "Add to campaign", "summary": [f"Add {n} item(s) to this campaign. Organisation only; nothing is drafted, scheduled or published."],
            "target": "Campaign", "timeZone": None, "cost": None}


def unlink_confirm(dctx, inputs):
    _campaign(dctx.state, inputs["campaignId"])
    n = len(inputs.get("draftIds") or []) + len(inputs.get("jobIds") or [])
    return {"title": "Remove from campaign", "summary": [f"Remove {n} item(s) from this campaign. The drafts and posts themselves stay."],
            "target": "Campaign", "timeZone": None, "cost": None}


query("campaigns_list", "J05", "Campaign briefs (newest change first) with status, missing facts, automations and platforms; filter by words or status.",
      {"q": {"type": "string", "maxLength": 120}, "status": {"type": "string", "enum": ["needs_input", "draft", "active", "completed"]},
       "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, campaigns_list, page=50, refresh=60, search=True, tool="campaign.list")
query("campaign_detail", "J05", "One campaign: goal, audience, facts, automations with next run, platforms, recent runs, derived gaps (each with its rule) and derived progress.",
      {"campaignId": ID}, campaign_detail, required=("campaignId",), refresh=60, tool="campaign.get")
query("campaign_items", "J05", "Every draft, post and image linked to a campaign (paged), with current state.",
      {"campaignId": ID, "kind": {"type": "string", "enum": ["draft", "post", "asset"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
      campaign_items, required=("campaignId",), page=50, refresh=60, tool="campaign_items")
query("campaign_timeline", "J05", "A campaign's timeline in a date range and time zone: planned automation runs, past runs and linked posts, each with its exact instant.",
      {"campaignId": ID, "start": DATE, "end": DATE, "zone": ZONE}, campaign_timeline, required=("campaignId",), refresh=60)
query("task_progress", "J05", "The multi-step task of this conversation (or one task): each step's state, what it depends on, and what is still open.",
      {"taskId": {"type": "string", "maxLength": 40, "pattern": r"^[0-9a-fA-F-]{36}$"}}, task_progress, refresh=30, also=("J01", "J02", "J08"))
CAMPAIGN_INPUTS = {"goal": {"type": "string", "minLength": 1, "maxLength": 1200}, "audience": {"type": "string", "minLength": 1, "maxLength": 800},
                   "date": {"type": "string", "maxLength": 80}, "venue": {"type": "string", "maxLength": 160}, "accountIds": IDS,
                   "assetIds": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 32, "pattern": r"^[0-9a-f]{32}$"}, "uniqueItems": True}}
action("campaign_create", "J05", "Create campaign", "Creates a campaign brief. Nothing is drafted, scheduled or published.", "MUTATE_REVERSIBLE", "edit",
       CAMPAIGN_INPUTS, create_confirm, create_execute, required=("goal", "audience"), dedupe="intent")
action("campaign_update", "J05", "Save brief", "Updates the campaign's goal or audience. Its active automations pause until you resume them.", "MUTATE_REVERSIBLE", "edit",
       {"campaignId": ID, "expectedVersion": {"type": "integer", "minimum": 1, "maximum": 1_000_000}, "goal": CAMPAIGN_INPUTS["goal"], "audience": CAMPAIGN_INPUTS["audience"]},
       update_confirm, update_execute, required=("campaignId", "expectedVersion"))
action("campaign_link", "J05", "Add to campaign", "Adds drafts or posts to the campaign (organisation only).", "MUTATE_REVERSIBLE", "edit",
       {"campaignId": ID, "draftIds": IDS, "jobIds": IDS}, link_confirm, lambda d, i, k: _link(d, i, "raffi_campaign_link", True), required=("campaignId",),
       requires_confirmation=False, tool="campaign_link", dedupe="natural", also=("J01",))
action("campaign_unlink", "J05", "Remove from campaign", "Removes drafts or posts from the campaign; they stay in the workspace.", "MUTATE_REVERSIBLE", "edit",
       {"campaignId": ID, "draftIds": IDS, "jobIds": IDS}, unlink_confirm, lambda d, i, k: _link(d, i, "raffi_campaign_unlink", False), required=("campaignId",),
       requires_confirmation=False, tool="campaign_unlink", dedupe="natural")
