"""Proposals: a change Rafii prepares and a person applies (site agent §9.4, §10.4, §13.4).

From the side panel, a request to change an automation ("move the Friday one to Thursday", "pause it for two weeks")
becomes a proposal instead of an edit: the exact changes, the automation's version and definition digest before,
and a preview of the plan after, computed by running the same automation_edit code on a copy of the workspace. The
proposal is stored on Rafii's message. Applying it re-runs that code for real, in one workspace command, only when
the automation is unchanged since (same version, definition digest and status), the proposal is still open and not
expired, and the person applying it still holds the permission it needs. Deleting an automation is not proposed:
that stays on the Automations page.

Proposal states: proposed → applied | dismissed | expired | superseded | failed.
"""
from __future__ import annotations

import copy

from postriff_alpha.domain import AlphaError, uid

from .. import automation_edit, automation_plan, campaigns, workflow_parse
from ..contracts import digest

TTL_SECONDS = 24 * 3600
OWNER_OPS = ("pause", "resume")
STATES = ("proposed", "applied", "dismissed", "expired", "superseded", "failed")


def _plan_view(view: dict) -> dict:
    return {"status": view.get("status"), "scheduleText": view.get("scheduleText"), "policy": view.get("policy"),
            "plan": [{"step": p.get("step"), "when": p.get("when"), "text": p.get("text")} for p in (view.get("plan") or [])][:6],
            "platforms": [{"platform": p.get("platform"), "canPublish": p.get("canPublish")} for p in (view.get("platforms") or [])][:8],
            "needs": [n.get("text") for n in (view.get("needs") or []) if isinstance(n, dict)][:4], "nextPublish": view.get("nextPublish")}


def _before(task: dict) -> dict:
    return {"version": task.get("version"), "definitionDigest": campaigns.definition_digest(task), "status": task.get("status")}


SCHEDULE_TYPES = ("schedule_draft", "reschedule_post")
WAITING_JOBS = ("approved", "scheduled", "claimed")


def proposal_digest(proposal: dict) -> str:
    fields = {key: proposal.get(key) for key in ("type", "taskId", "changes", "before", "createdBy", "variantId", "variantRevision", "channelId", "localTime",
                                                 "timeZone", "jobId", "acknowledgedWarnings")}
    # Later steps join the digest only when present, so proposals stored before them still verify.
    for extra in ("acceptUpdate", "confirmReview", "media"):
        if proposal.get(extra):
            fields[extra] = proposal[extra]
    return digest(fields)


def build(state: dict, text: str, *, actor: str, now: float, owner: bool, paid: bool, zone: str, conversation_task_id: str | None,
          reading: dict | None = None, providers=None, live: bool = False) -> dict:
    """{"proposal"} or {"ask", "candidates"} or {"refuse", "code"}; never changes `state`."""
    edit = reading or workflow_parse.read_edit(text, now, zone)
    task, candidates = automation_edit.resolve(state, (edit.get("target") or {}).get("name"), conversation_task_id, text)
    if task is None:
        names = [item.get("name") or "Automation" for item in candidates]
        if not names:
            return {"refuse": "You don't have an automation to change yet.", "code": "no_automation"}
        return {"ask": "Which automation do you mean?", "candidates": names}
    changes = [dict(change) for change in edit.get("changes") or [] if isinstance(change, dict) and change.get("op")]
    if not changes:
        return {"ask": "What should change? For example the day or time, the platforms, the sources, whether it waits for approval, or pausing it.",
                "candidates": [], "taskId": task["id"]}
    if any(change["op"] == "delete" for change in changes):
        return {"refuse": "Deleting an automation is done on the Automations page, where you can see its run history first.", "code": "delete_on_page", "taskId": task["id"]}
    if any(change["op"] in OWNER_OPS for change in changes) and not owner:
        return {"refuse": "Only an owner of this workspace can pause or resume an automation.", "code": "owner_required", "taskId": task["id"]}
    trial = copy.deepcopy(state)
    try:
        result = automation_edit.apply(trial, actor, now, {"target": {"name": None}, "changes": changes}, conversation_task_id=task["id"],
                                       owner=owner, paid=paid, zone=zone)
    except AlphaError as error:
        return {"refuse": str(error), "code": error.code or "not_possible", "taskId": task["id"]}
    if "ask" in result:
        return {"ask": result["ask"], "candidates": result.get("candidates") or []}
    before_view = automation_plan.card(state, task["id"], [], [], providers=providers, live=live)
    after_view = automation_plan.card(trial, task["id"], (result.get("view") or {}).get("needs") or [], [], providers=providers, live=live)
    needs_owner = any(change["op"] in OWNER_OPS or (change["op"] == "policy" and change.get("policy") == "auto") for change in changes)
    proposal = {"id": uid(), "type": "automation_change", "status": "proposed", "taskId": task["id"], "name": task.get("name") or "Automation",
                "changes": changes, "summary": [str(item) for item in result.get("summary") or []][:6], "before": _before(task),
                "preview": {"before": _plan_view(before_view), "after": _plan_view(after_view)},
                "requiredPermission": "owner" if needs_owner else "edit", "createdBy": actor, "createdAt": now, "expiresAt": now + TTL_SECONDS}
    proposal["digest"] = proposal_digest(proposal)
    return {"proposal": proposal}


def _review_payload(proposal: dict) -> dict:
    payload = {"variantId": proposal["variantId"], "channelId": proposal["channelId"], "localTime": proposal["localTime"], "timeZone": proposal["timeZone"],
               "acknowledgedWarnings": list(proposal.get("acknowledgedWarnings") or [])}
    media = proposal.get("media")
    if media:
        payload.update(assetId=media.get("assetId"), alt=media.get("alt"), rightsConfirmed=media.get("rightsConfirmed") is True)
    return payload


def _variant(state: dict, variant_id: str) -> dict | None:
    return next((v for v in state.get("variants", []) if isinstance(v, dict) and v.get("id") == variant_id), None)


def _prepare(state: dict, proposal: dict, actor: str, commands) -> None:
    """The steps a scheduling proposal takes, in order, with the app's own commands (on a copy when building)."""
    if proposal.get("jobId"):
        commands(state, actor, "p2_cancel", {"jobId": proposal["jobId"]})
    if proposal.get("acceptUpdate"):
        commands(state, actor, "accept_update", {"variantId": proposal["variantId"]})
    if proposal.get("confirmReview"):
        variant = _variant(state, proposal["variantId"]) or {}
        commands(state, actor, "p2_variant_review", {"variantId": proposal["variantId"], "variantRevision": variant.get("revision"), "confirmed": True,
                                                     "excludedUnknowns": list(proposal["confirmReview"]["excludedUnknowns"])})
    commands(state, actor, "p2_review", _review_payload(proposal))


def _newest_review(state: dict, variant_id: str, local_time: str) -> dict | None:
    reviews = (state.get("phase2") or {}).get("reviews") or []
    return next((r for r in reversed(reviews) if (r.get("manifest") or {}).get("variantId") == variant_id and ((r.get("manifest") or {}).get("timing") or {}).get("local") == local_time), None)


def build_schedule(state: dict, *, variant: dict, channel: dict, local_time: str, zone: str, actor: str, now: float, commands, job: dict | None = None,
                   accept_update: bool = False, media: dict | None = None, picked: str | None = None) -> dict:
    """Propose preparing the exact review of a draft at a time on an account (and, for a move, cancelling the waiting
    job first). Checked by running the same commands on a copy; nothing changes until the proposal is applied, and
    even then the post waits for a separate approval of that exact review.

    Two earlier steps join when the draft needs them, each shown to the person before they apply: using the rewrite
    Rafii just wrote (`accept_update`, the draft's pending proposed update; the earlier text stays in its history), and
    confirming the draft review (the unknown details listed stay out of the post). A retracted or out-of-policy
    source still refuses, as it does in the Queue."""
    if job is not None and job.get("state") not in WAITING_JOBS:
        return {"refuse": "Only a post that is approved and waiting can be moved. A held or failed post is prepared again from its draft.", "code": "not_waiting"}
    proposal = {"type": "reschedule_post" if job else "schedule_draft", "variantId": variant["id"], "variantRevision": variant.get("revision"), "channelId": channel["id"],
                "localTime": local_time, "timeZone": zone, "jobId": (job or {}).get("id"), "acknowledgedWarnings": list(variant.get("warnings") or [])}
    update = variant.get("proposedUpdate") if accept_update else None
    if accept_update and not update:
        return {"refuse": "That draft has no rewrite waiting to be used.", "code": "no_update"}
    if update:
        proposal["acceptUpdate"] = {"runId": update.get("runId"), "textDigest": digest(update.get("text") or "")}
        # After the rewrite is accepted, its own warnings are the ones to acknowledge.
        proposal["acknowledgedWarnings"] = list(update.get("warnings") or [])
    if media:
        proposal["media"] = {"assetId": media.get("assetId"), "alt": str(media.get("alt") or "")[:1000], "rightsConfirmed": media.get("rightsConfirmed") is True}
    trial = copy.deepcopy(state)
    try:
        if job:
            commands(trial, actor, "p2_cancel", {"jobId": job["id"]})
        if update:
            commands(trial, actor, "accept_update", {"variantId": variant["id"]})
        drafted = _variant(trial, variant["id"]) or {}
        if drafted.get("needsReview") or drafted.get("unknowns"):
            proposal["confirmReview"] = {"excludedUnknowns": list(drafted.get("unknowns") or [])}
            commands(trial, actor, "p2_variant_review", {"variantId": variant["id"], "variantRevision": drafted.get("revision"), "confirmed": True,
                                                         "excludedUnknowns": list(drafted.get("unknowns") or [])})
        commands(trial, actor, "p2_review", _review_payload(proposal))
    except AlphaError as error:
        return {"refuse": str(error), "code": error.code or "not_possible"}
    review = _newest_review(trial, variant["id"], local_time) or {}
    manifest = review.get("manifest") or {}
    before_time = ((job or {}).get("manifest") or {}).get("timing", {}).get("local")
    warnings = proposal["acknowledgedWarnings"]
    summary = [f"prepare the exact {channel.get('platform')} post for {channel.get('account')} at {local_time.replace('T', ' ')} ({zone})"]
    if picked:
        summary.append(f"the time was picked by Rafii: {picked}")
    if job:
        summary.insert(0, f"cancel the waiting post at {(before_time or '').replace('T', ' ')}")
    if proposal.get("confirmReview"):
        unknowns = proposal["confirmReview"]["excludedUnknowns"]
        summary.insert(0, "confirm the draft review: " + ("these details stay out of the post: " + "; ".join(unknowns)[:300] if unknowns else "you've read this exact text"))
    if update:
        summary.insert(0, "use the rewrite Rafii wrote (it replaces the current text; the earlier version stays in the draft's history)")
    if proposal.get("media"):
        summary.append(f"attach the image “{proposal['media']['alt'][:60]}” (you confirm you hold the rights to use it)")
    if warnings:
        summary.append("acknowledge its warnings: " + "; ".join(warnings)[:300])
    proposal.update({"id": uid(), "status": "proposed", "name": f"{channel.get('platform')} · {channel.get('account')}", "summary": summary,
                     "preview": {"before": {"status": f"{job.get('state')} for {(before_time or '').replace('T', ' ')}" if job else "Not scheduled", "scheduleText": None, "plan": [], "platforms": [], "needs": []},
                                 "after": {"status": "Waiting for approval", "scheduleText": f"{local_time.replace('T', ' ')} ({zone})",
                                           "plan": [{"when": local_time.replace("T", " "), "text": "Publishes only after someone with the approve permission approves this exact post."}],
                                           "platforms": [{"platform": channel.get("platform"), "canPublish": None}], "needs": []}},
                     "before": {"variantRevision": variant.get("revision"), "jobState": (job or {}).get("state")},
                     "requiredPermission": "approve", "needsEdit": bool(update or proposal.get("confirmReview")), "createdBy": actor, "createdAt": now,
                     "expiresAt": now + TTL_SECONDS, "characters": len((manifest.get("payload") or {}).get("text") or variant.get("text") or ""),
                     "text": (manifest.get("payload") or {}).get("text") or ""})
    proposal["digest"] = proposal_digest(proposal)
    return {"proposal": proposal}


def check(proposal: dict, *, digest_value: str, now: float) -> None:
    """Raise when the stored proposal cannot be applied as it stands (state, expiry, digest)."""
    if proposal.get("status") != "proposed":
        raise AlphaError(f"This proposal was already {proposal.get('status')}.", 409, code="proposal_closed")
    if proposal.get("expiresAt", 0) <= now:
        raise AlphaError("This proposal expired. Ask Rafii again for a fresh one.", 409, code="proposal_expired")
    if digest_value != proposal.get("digest") or proposal_digest(proposal) != proposal.get("digest"):
        raise AlphaError("This proposal does not match what Rafii prepared.", 409, code="proposal_digest")


def apply(state: dict, proposal: dict, *, actor: str, now: float, owner: bool, paid: bool, zone: str, commands=None, can_approve: bool = False, can_edit: bool = False) -> dict:
    """Apply a checked proposal to `state` in place with the same code the app uses; stale targets are refused."""
    if proposal.get("type") in SCHEDULE_TYPES:
        if not can_approve:
            raise AlphaError("Preparing a post for approval needs the approve permission.", 403, code="approve_required")
        if proposal.get("needsEdit") and not can_edit:
            raise AlphaError("Using the rewrite or confirming the draft review needs the edit permission as well.", 403, code="edit_required")
        variant = _variant(state, proposal.get("variantId"))
        if variant is None or variant.get("revision") != proposal.get("variantRevision"):
            raise AlphaError("The draft changed since Rafii proposed this. Ask again for a fresh proposal.", 409, code="proposal_stale")
        accept = proposal.get("acceptUpdate")
        if accept:
            update = variant.get("proposedUpdate") or {}
            if update.get("runId") != accept.get("runId") or digest(update.get("text") or "") != accept.get("textDigest"):
                raise AlphaError("The rewrite changed since Rafii proposed this. Ask again for a fresh proposal.", 409, code="proposal_stale")
        if proposal.get("jobId"):
            job = next((j for j in (state.get("phase2") or {}).get("jobs", []) if j.get("id") == proposal["jobId"]), None)
            if job is None or job.get("state") not in WAITING_JOBS:
                raise AlphaError("That post is no longer waiting, so it can't be moved.", 409, code="proposal_stale")
        _prepare(state, proposal, actor, commands)
        review = _newest_review(state, proposal["variantId"], proposal["localTime"]) or {}
        return {"reviewId": review.get("id"), "status": review.get("status"), "localTime": proposal["localTime"], "timeZone": proposal["timeZone"],
                "cancelledJobId": proposal.get("jobId"), "summary": proposal.get("summary") or []}
    if proposal.get("requiredPermission") == "owner" and not owner:
        raise AlphaError("Only an owner of this workspace can apply this change.", 403, code="owner_required")
    task = next((t for t in automation_edit.live_tasks(state) if t.get("id") == proposal.get("taskId")), None)
    if task is None:
        raise AlphaError("That automation no longer exists.", 409, code="proposal_stale")
    if _before(task) != proposal.get("before"):
        raise AlphaError("The automation changed since Rafii proposed this. Ask again for a fresh proposal.", 409, code="proposal_stale")
    result = automation_edit.apply(state, actor, now, {"target": {"name": None}, "changes": proposal["changes"]}, conversation_task_id=task["id"],
                                   owner=owner, paid=paid, zone=zone)
    if "ask" in result:
        raise AlphaError(result["ask"], 409, code="proposal_stale")
    view = result.get("view") or {}
    return {"taskId": task["id"], "status": view.get("status"), "version": next((t.get("version") for t in automation_edit.live_tasks(state) if t.get("id") == task["id"]), None),
            "summary": [str(item) for item in result.get("summary") or []][:6], "needs": [n.get("text") for n in view.get("needs") or [] if isinstance(n, dict)][:4]}


def view(proposal: dict, now: float) -> dict:
    """What the browser receives: never `createdBy`; an open proposal past its time shows as expired."""
    status = proposal.get("status")
    if status == "proposed" and proposal.get("expiresAt", 0) <= now:
        status = "expired"
    keep = ("id", "type", "taskId", "name", "changes", "summary", "preview", "requiredPermission", "expiresAt", "digest", "result", "appliedAt", "closedReason",
            "variantId", "channelId", "localTime", "timeZone", "jobId", "media", "needsEdit", "text")
    return {**{k: proposal.get(k) for k in keep}, "status": status}
