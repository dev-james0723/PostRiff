"""Commit an approved automation post to the publishing queue (orchestration §5).

An automation never writes a job itself. When an approved post is due, the worker runs the `raffi_run_commit`
command as the person whose approval it carries: the human who approved that exact draft, or, for auto-publish, the
owner who granted standing authority for this exact definition. The command runs the same Phase 2 steps a person
does in Queue (variant review, source use, review, approve) inside one workspace transaction, so every existing
gate still applies: permission class, revision check, `build_manifest` freshness, channel readiness, daily limits,
billing (the after-hook), and later the hosted worker's claim-time re-check of the approval.

Auto-publish is refused, never forged: a draft with unknown facts, an unfamiliar warning, a third-party source the
owner did not cover, an unverified quote or an over-long text is downgraded to "ready for review" with the reason.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import zoneinfo

from postriff_alpha.domain import AlphaError

from . import campaigns, lifecycle, source_policy
from .contracts import LIMITS, digest

COMMIT_LEAD = 30 * 60           # commit (review + approve) this long before the publish time
MIN_LEAD = 120                  # a manifest time is at least this far in the future
MAX_ATTEMPTS = 3
_RESEARCH_WARNING = re.compile(r"^Some facts came from web research \(.*\); check them against the pages before scheduling\.$")
_CANDIDATE_WARNING = "Rewritten-source candidate: approve public use before publishing."


class _NoDatabase:
    def execute(self, *_args, **_kwargs):
        raise AlphaError("This operation must use the hosted service.", 409)


def acknowledgeable(warning: str, source_use: bool) -> bool:
    """Warnings an owner's standing authority may acknowledge: the neutral-voice fallback always; the web research
    and rewritten-source notes only when the owner allowed Raffi to publish from sources it finds."""
    from .ideas import VOICE_FALLBACK_NOTE
    if warning == VOICE_FALLBACK_NOTE:
        return True
    return source_use and (warning == _CANDIDATE_WARNING or bool(_RESEARCH_WARNING.match(warning)))


def text_blockers(variant: dict, platform: str) -> list[str]:
    limit = (LIMITS.get(platform) or {}).get("characters")
    text = variant.get("text") or ""
    if not text.strip():
        return ["The draft is empty."]
    if limit and len(text) > limit:
        return [f"The draft is {len(text)} characters; {platform} allows {limit}."]
    return []


def auto_blockers(state: dict, task: dict, occurrence: dict, item: dict, variant: dict) -> list[str]:
    """Why this draft may not publish without a person looking at it (empty = eligible for auto-publish)."""
    authority = task.get("publishAuthority") or {}
    reasons = []
    if not authority or authority.get("definitionDigest") != task.get("definitionDigest"):
        reasons.append("Automatic publishing needs to be confirmed again after the automation changed.")
    if variant.get("unknowns"):
        reasons.append("Some details in the draft couldn't be backed by a source.")
    if variant.get("rejected") or variant.get("blockedByRetraction") or variant.get("policyBlocked"):
        reasons.append("The draft can't be published as it is.")
    unknown_warnings = [w for w in variant.get("warnings") or [] if not acknowledgeable(w, authority.get("sourceUse") is True)]
    if unknown_warnings:
        reasons.append(unknown_warnings[0])
    for source_id in variant.get("sourceIds", []):
        source = next((s for s in state.get("sources", []) if s.get("id") == source_id), None)
        if source is None or not source.get("active"):
            continue
        policy = source.get("sourcePolicy")
        if policy in (None, "internal_reference", "prohibited"):
            reasons.append("A source used in the draft isn't cleared for public use.")
        elif policy == "rewrite_approval" and not source_policy.use_approved(source) and authority.get("sourceUse") is not True:
            reasons.append("The draft uses an outside source you haven't cleared for automatic posts.")
    quote = (occurrence.get("research") or {}).get("quote")
    if quote and not quote.get("verified"):
        reasons.append("The quote's attribution couldn't be confirmed on two independent sites.")
    reasons += text_blockers(variant, item["platform"])
    if item["platform"] == "Instagram":
        reasons.append("Instagram posts need an image, and this automation writes text.")
    return list(dict.fromkeys(reasons))


def _manifest_time(publish_at: float, zone_name: str, now: float) -> dict:
    """The local minute the manifest schedules: the publish time, or two minutes from now if that is sooner."""
    at = max(publish_at, now + MIN_LEAD)
    at = math.ceil(at / 60) * 60
    zone = zoneinfo.ZoneInfo(zone_name)
    local = dt.datetime.fromtimestamp(at, dt.timezone.utc).astimezone(zone)
    return {"localTime": local.strftime("%Y-%m-%dT%H:%M"), "timeZone": zone_name, "fold": local.fold}


def expected_principal(task: dict, item: dict) -> str | None:
    if item.get("approvedVia") == "owner_preauthorization":
        return (task.get("publishAuthority") or {}).get("grantedBy")
    return (item.get("decision") or {}).get("by")


def commit(engine, state: dict, principal: str, payload: dict, now: float) -> dict:
    """`raffi_run_commit` (hosted command body): publish-queue one approved item as the approving principal."""
    root = campaigns._root(state)
    occurrence = next((o for o in root["occurrences"] if o.get("id") == payload.get("occurrenceId")), None)
    if occurrence is None:
        raise AlphaError("Run unavailable.", 404)
    task = next((t for t in root["recurringTasks"] if t.get("id") == occurrence["taskId"]), None)
    item = campaigns.item_of(occurrence, payload.get("itemKey"))
    if item.get("jobId"):
        return {"jobId": item["jobId"], "state": item["state"], "note": "Already queued."}
    if item.get("state") != "approved" or task is None:
        raise AlphaError("Only an approved post can be queued.", 409, code="lifecycle_transition")
    if task.get("status") != "active":
        raise AlphaError("This automation is not active.", 409, code="automation_inactive")
    if principal != expected_principal(task, item):
        raise AlphaError("Only the person who approved this post can queue it.", 403)
    if item.get("approvedVia") == "owner_preauthorization" and (task.get("publishAuthority") or {}).get("definitionDigest") != task.get("definitionDigest"):
        raise AlphaError("Automatic publishing needs to be confirmed again after the automation changed.", 409, code="publish_authority_required")
    if not item.get("channelId"):
        raise AlphaError("Choose the account to publish to.", 409, code="no_account")
    publish_at = item.get("publishAt")
    if publish_at is None or not publish_at - COMMIT_LEAD - 120 <= now < publish_at + 3600:
        raise AlphaError("This post can be queued only shortly before its publish time.", 409, code="not_due")
    variant = engine._variant(state, item["variantId"])
    decision = item.get("decision") or {}
    # Every approval, human or standing, is for this exact draft: an edit, a new candidate or new sources void it.
    if decision.get("variantRevision") != variant["revision"] or decision.get("textDigest") != digest(variant.get("text", "")) or variant.get("proposedUpdate"):
        raise AlphaError("The draft changed after it was approved. Approve the current version.", 409, code="draft_changed")
    if item.get("approvedVia") == "owner_preauthorization":
        blockers = auto_blockers(state, task, occurrence, item, variant)
        if blockers:
            raise AlphaError("Held for your approval: " + blockers[0], 409, code="auto_blocked")
    jobs = state["phase2"]["jobs"]
    # Never two posts for one draft on one account.
    live = next((j for j in jobs if j["manifest"].get("variantId") == variant["id"] and j["manifest"].get("channelId") == item["channelId"] and j.get("state") not in ("failed", "canceled")), None)
    if live is None:
        device = {"id": "automation", "user_id": principal}
        if variant.get("needsReview") or variant.get("unknowns"):
            excluded = decision.get("excludedUnknowns", []) if item.get("approvedVia") == "human" else []
            engine.apply_phase2(_NoDatabase(), state, "variant_review", {"variantId": variant["id"], "variantRevision": variant["revision"], "confirmed": True, "excludedUnknowns": excluded}, device)
            if item.get("approvedVia") == "owner_preauthorization":
                variant["uncertaintyReview"]["claim"] = "owner_standing_authorization_no_unknowns"
        standing = item.get("approvedVia") == "owner_preauthorization" and (task.get("publishAuthority") or {}).get("sourceUse") is True
        recorded = {entry["sourceId"]: entry["factsDigest"] for entry in decision.get("sourceUse") or []}
        for source_id in variant.get("sourceIds", []):
            source = next((s for s in state.get("sources", []) if s.get("id") == source_id), None)
            if source is None or not source.get("active") or source.get("sourcePolicy") != "rewrite_approval" or source_policy.use_approved(source):
                continue
            facts = recorded.get(source_id) or (source_policy.facts_digest(source) if standing else None)
            if facts is None:
                raise AlphaError("A source in this draft needs your approval for public use.", 409, code="source_use_required")
            if facts != source_policy.facts_digest(source):
                raise AlphaError("A source used in this draft changed after it was approved. Approve it again.", 409, code="draft_changed")
            source_policy.apply_policy_action(state, "source_use_approve", {"sourceId": source_id, "factsDigest": facts, "confirmed": True}, principal, now)
            source["useApprovals"][-1]["via"] = "automation_standing_authority" if standing else "automation_approval"
        warnings = variant.get("warnings") or []
        if item.get("approvedVia") == "human" and sorted(decision.get("acknowledgedWarnings") or []) != sorted(warnings):
            raise AlphaError("The draft's warnings changed after it was approved. Approve it again.", 409, code="draft_changed")
        timing = _manifest_time(item["publishAt"], task["schedule"]["timeZone"], now)
        engine.apply_phase2(_NoDatabase(), state, "review", {"variantId": variant["id"], "channelId": item["channelId"], "acknowledgedWarnings": list(warnings), **timing}, device)
        review = state["phase2"]["reviews"][-1]
        engine.apply_phase2(_NoDatabase(), state, "approve", {"reviewId": review["id"], "digest": review["digest"], "confirmed": True}, device)
        review = next(r for r in state["phase2"]["reviews"] if r["id"] == review["id"])
        live = next(j for j in jobs if j["id"] == review["jobId"])
        item["reviewId"] = review["id"]
    live["automation"] = {"taskId": task["id"], "occurrenceId": occurrence["id"], "itemKey": item["key"], "approvedVia": item.get("approvedVia")}
    item["jobId"] = live["id"]
    item["lastError"] = None
    lifecycle.move(item, "scheduled", at=now)
    campaigns._history(occurrence, now, "scheduled", f"{item['platform']} post queued to publish at {live['manifest']['timing']['local'].replace('T', ' ')}.", principal)
    return {"jobId": live["id"], "state": item["state"]}
