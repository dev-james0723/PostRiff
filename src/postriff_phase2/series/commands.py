"""Series state transitions (pure). The service supplies authority, expected revision and idempotency; these
functions validate the request against the workspace state and change only the series body, the drafts it links
(lineage + Queue gates) and, for decisions a person may keep in workspace memory, one scoped overlay item."""
from __future__ import annotations

import datetime as dt

from postriff_alpha.domain import AlphaError, uid

from .. import locales
from ..contracts import digest
from . import model as m


def _text(value, message, limit):
    if not isinstance(value, str) or not value.strip():
        raise AlphaError(message, 400)
    value = " ".join(value.split())
    if len(value) > limit:
        raise AlphaError(f"Keep it within {limit} characters.", 400)
    return value


def bounded_int(value, default, low, high, message):
    value = default if value is None else value
    if type(value) is not int or not low <= value <= high:
        raise AlphaError(message, 400)
    return value


def _review_by(value, today, *, required, allow_past=False):
    if value is None and not required:
        return None
    day = m.parse_day(value)
    if day is None or day > today + dt.timedelta(days=m.REVIEW_MAX_DAYS) or (not allow_past and day <= today):
        raise AlphaError(f"Choose a review date after today and within {m.REVIEW_MAX_DAYS} days (YYYY-MM-DD).", 400)
    return day.isoformat()


# --- create / plan --------------------------------------------------------------------------------------------------
def create(state, payload, actor, now):
    """A series from one eligible old post (Evergreen eligibility) or one source with approved facts, with its claims,
    source references and an initial plan of 2–6 episodes."""
    origin_in = payload.get("origin")
    if not isinstance(origin_in, dict) or origin_in.get("kind") not in ("post", "source") or not isinstance(origin_in.get("id"), str) or not m._ID.match(origin_in["id"]):
        raise AlphaError("Choose the published post or source this series starts from.", 400)
    if len(m.all_series(state)) >= m.MAX_SERIES:
        raise AlphaError(f"A workspace keeps up to {m.MAX_SERIES} series.", 409)
    question = _text(payload.get("audienceQuestion"), "Write the audience question this series answers.", 300)
    goal = _text(payload.get("goal"), "Say what this series is for.", 600)
    title = _text(payload["title"], "Name this series.", 120) if payload.get("title") is not None else question[:120]
    count = bounded_int(payload.get("episodeCount"), m.DEFAULT_PLAN, m.MIN_PLAN, m.MAX_PLAN, f"Plan {m.MIN_PLAN} to {m.MAX_PLAN} episodes.")
    min_age = bounded_int(payload.get("minAgeDays"), m.DEFAULT_MIN_AGE, m.MIN_AGE_DAYS, m.MAX_AGE_DAYS, f"Reuse posts between {m.MIN_AGE_DAYS} and {m.MAX_AGE_DAYS} days old.")
    today = m._day(now)
    # An explicit date the person gives for the original's facts (a past one marks them for review at once).
    review_by = _review_by(payload.get("reviewBy"), today, required=False, allow_past=True)
    source_ids = payload.get("sourceIds") or []
    if not isinstance(source_ids, list) or len(source_ids) > m.MAX_SOURCES or not all(isinstance(i, str) and m._ID.match(i) for i in source_ids):
        raise AlphaError(f"Choose up to {m.MAX_SOURCES} sources from this workspace.", 400)
    if origin_in["kind"] == "post":
        job = m.eligible_post(state, origin_in["id"], now, min_age)
        text = m.job_text(job)
        manifest = job.get("manifest") or {}
        language = locales.canonical(payload.get("language")) or locales.canonical((manifest.get("payload") or {}).get("language")) or ("zh-Hant" if m.is_cjk(text) else "en")
        origin = {"kind": "post", "id": job["id"], "contentDigest": m.text_digest(text), "platform": manifest.get("platform"),
                  "publishedAt": m._day(m.verified_at(job)).isoformat(), "title": None, "capturedAt": now}
    else:
        source = m.usable_source(state, origin_in["id"])
        text = m.origin_text(state, {"kind": "source", "id": source["id"]})
        language = locales.canonical(payload.get("language")) or ("zh-Hant" if m.is_cjk(text) else "en")
        origin = {"kind": "source", "id": source["id"], "contentDigest": m.text_digest(text), "version": m.source_version(source), "platform": None,
                  "publishedAt": None, "title": " ".join(str(source.get("title") or "").split())[:120] or None, "capturedAt": now}
    for other in m.all_series(state):
        same = other["series"].get("origin") or {}
        if other["series"].get("status") != "archived" and (same.get("kind"), same.get("id")) == (origin["kind"], origin["id"]):
            raise AlphaError(f"This {'post' if origin['kind'] == 'post' else 'source'} already starts the series “{other['series']['title'][:60]}”. Plan more episodes there.", 409, code="duplicate_series")
    analysis, claims = m.origin_claims(state, origin, now, review_by)
    references = []
    for source_id in dict.fromkeys(source_ids):
        if source_id == origin["id"]:
            continue
        source = m.usable_source(state, source_id)
        references.append({"sourceId": source_id, "title": " ".join(str(source.get("title") or "").split())[:120], "version": m.source_version(source),
                           "fingerprint": source.get("fingerprint"), "addedAt": now})
        claims += m.source_claims(source, now, review_by)
    claims = list({c["id"]: c for c in claims}.values())[:m.MAX_CLAIMS]
    campaign = {"id": uid(), "version": 1, "kind": "series", "goal": goal, "audience": question, "facts": {}, "accountIds": [], "assetIds": [], "items": [],
                "status": "active", "missingFacts": [], "createdBy": actor, "createdAt": now, "updatedAt": now,
                "series": {"schema": m.SCHEMA, "revision": 1, "title": title, "audienceQuestion": question, "goal": goal, "language": language,
                           "owner": actor, "status": "active", "origin": origin, "sources": references, "claims": claims,
                           "questions": analysis["questions"], "signals": analysis["signals"], "injectionFlags": analysis["injectionFlags"],
                           "episodes": [], "decisions": [], "keys": [], "createdAt": now, "createdBy": actor, "updatedAt": now, "updatedBy": actor}}
    m.planning_root(state)["campaigns"].append(campaign)
    m.plan(state, campaign, count, now)
    return campaign


def replan(state, campaign, payload, now):
    """Fill the plan back up to `count` waiting episodes (1–6) with the decisions in force now."""
    if campaign["series"].get("status") in ("completed", "archived"):
        raise AlphaError("This series is finished. Reopen it before planning more episodes.", 409)
    count = bounded_int(payload.get("count"), m.DEFAULT_PLAN, 1, m.MAX_PLAN, f"Plan 1 to {m.MAX_PLAN} episodes.")
    added = m.plan(state, campaign, count, now)
    return {"added": [e["id"] for e in added]}


# --- decisions ------------------------------------------------------------------------------------------------------
def decide(state, campaign, episode_id, payload, actor, now, storage):
    """Accept, reject or never repeat an episode's angle (or, for do-not-repeat, its whole role). `storage` is
    {"kind": "overlay"} when the person may keep it in workspace memory, else {"kind": "series", "reason": …}."""
    series = campaign["series"]
    episode = m.episode_of(series, episode_id)
    decision, level = payload.get("decision"), payload.get("level") or "angle"
    if decision not in m.DECISIONS:
        raise AlphaError("Choose accept, reject or do not repeat.", 400)
    if level not in ("angle", "role") or (level == "role" and decision != "do_not_repeat"):
        raise AlphaError("Only ‘do not repeat’ can cover a whole role.", 400)
    if episode.get("state") == "skipped":
        raise AlphaError("This episode was already set aside.", 409, code="lifecycle_transition")
    if decision == "reject" and episode.get("draftRefs"):
        raise AlphaError("This episode already has a draft. Remove the draft first, or choose ‘do not repeat’ for future plans.", 409, code="lifecycle_transition")
    active = [d for d in series.get("decisions") or [] if m.decision_active(state, d)]
    target = episode["angle"]["key"] if level == "angle" else episode["role"]
    if any(d["decision"] == decision and d.get("level", "angle") == level and (d["angleKey"] if level == "angle" else d["role"]) == target for d in active):
        raise AlphaError("That decision is already in force.", 409, code="already_decided")
    record = {"id": "sd_" + uid()[:12], "seriesId": campaign["id"], "decision": decision, "level": level, "role": episode["role"],
              "angleKey": episode["angle"]["key"], "angleText": episode["angle"]["text"][:160] if level == "angle" else None,
              "episodeId": episode["id"], "storage": storage["kind"], "overlayId": None, "reason": storage.get("reason"),
              "status": "active", "createdAt": now, "createdBy": actor}
    decisions = list(series.get("decisions") or [])
    while len(decisions) >= m.MAX_DECISIONS:
        stale = next((d for d in decisions if not m.decision_active(state, d)), None)
        if stale is None:
            raise AlphaError(f"This series holds {m.MAX_DECISIONS} decisions in force. Revoke one first.", 409)
        decisions.remove(stale)
    if storage["kind"] == "overlay":
        from ..coworker import overlays
        item = {"id": "ov_" + uid()[:10], "memoryType": "strategy", "statement": m.decision_statement(campaign, decision, episode["role"], record["angleText"]),
                "scope": {"seriesId": campaign["id"]}, "status": "active", "revision": 1, "createdAt": now, "updatedAt": now, "createdBy": actor,
                "ruleKey": f"series_angle_{decision}", "target": {"angleKey": record["angleKey"], "role": episode["role"], "level": level}}
        overlays.add_item(state, item, actor, now)
        record["overlayId"] = item["id"]
    series["decisions"] = decisions + [record]
    if decision == "accept":
        episode["angleDecision"] = "accepted"
    else:
        episode["angleDecision"] = "rejected" if decision == "reject" else "do_not_repeat"
        affected = [episode] if level == "angle" else [e for e in series["episodes"] if e["role"] == episode["role"]]
        for item in affected:
            if item.get("state") in ("planned", "approved") and not item.get("draftRefs"):
                item["state"], item["updatedAt"] = "skipped", now
    episode["updatedAt"] = now
    return record


def revoke(state, campaign, decision_id, actor, now):
    """Stop a decision from shaping future plans. Episodes already set aside stay set aside; the next plan may offer
    that angle again. Brand Brain and voice are untouched either way."""
    record = next((d for d in campaign["series"].get("decisions") or [] if d.get("id") == decision_id), None)
    if record is None:
        raise AlphaError("That decision is not part of this series.", 404)
    if not m.decision_active(state, record):
        raise AlphaError("That decision is no longer in force.", 409, code="already_revoked")
    if record.get("storage") == "overlay":
        from ..coworker import overlays
        overlays.set_status(state, record["overlayId"], "retired", actor, now)
    record.update(status="revoked", revokedAt=now, revokedBy=actor)
    return record


# --- episodes -------------------------------------------------------------------------------------------------------
def _waiting(series, exclude=None):
    return next((e for e in series.get("episodes") or [] if e.get("id") != exclude and e.get("state") in ("approved", "drafting") and not e.get("draftRefs")), None)


def approve(state, campaign, episode_id, actor, now):
    """Approve one episode as the next to produce. One at a time: no queue of approved episodes."""
    series = campaign["series"]
    if series.get("status") != "active":
        raise AlphaError("This series is not active. Resume it before approving an episode.", 409)
    episode = m.episode_of(series, episode_id)
    if episode.get("state") != "planned":
        raise AlphaError("Only a planned episode can be approved as the next one.", 409, code="lifecycle_transition")
    waiting = _waiting(series, episode_id)
    if waiting:
        raise AlphaError(f"Episode {waiting.get('index')} is approved and waiting for its draft. Add its draft or set it aside first.", 409, code="episode_pending")
    issues = m.episode_issues(state, series, episode, m._day(now))
    if issues:
        raise AlphaError(m.gate_unknown(issues), 409, code="needs_fact_review")
    episode.update(state="approved", approvedAt=now, approvedBy=actor, updatedAt=now)
    return episode


def claim(state, campaign, claim_id, payload, actor, now):
    """Fix a fact before release: confirm it is still supported (new review date), update it (new text, optional new
    source fact, new review date) or remove it from every episode that used it."""
    series = campaign["series"]
    item = m.claim_of(series, claim_id)
    action = payload.get("action")
    if action not in m.CLAIM_ACTIONS:
        raise AlphaError("Choose reviewed, update or remove.", 400)
    today = m._day(now)
    if action == "remove":
        item.update(status="removed", removedAt=now, removedBy=actor)
        return item
    review_by = _review_by(payload.get("reviewBy"), today, required=True)
    if action == "reviewed":
        found, _ = m.claim_state(state, item, today)
        if found in ("source_unavailable", "missing_support"):
            raise AlphaError("The support for this fact is gone. Update it with another source or remove it.", 409, code="source_unavailable")
        item["support"] = _current_support(state, item["support"])
    else:
        text = _text(payload.get("text"), "Write the corrected fact.", 280)
        support = payload.get("support")
        if support is not None:
            if not isinstance(support, dict) or not isinstance(support.get("sourceId"), str):
                raise AlphaError("Choose a source fact from this workspace.", 400)
            source = m.usable_source(state, support["sourceId"])
            fact = next((f for f in m.approved_facts(source) if f.get("id") == support.get("factId")), None)
            if support.get("factId") is not None and fact is None:
                raise AlphaError("Choose an approved fact from that source.", 409, code="approval_required")
            item["support"] = {"kind": "source", "id": source["id"], "factId": support.get("factId"), "version": m.source_version(source)}
        else:
            # The person states the corrected fact themselves (first-party, attributed to them).
            item["support"] = {"kind": "user", "id": actor, "version": None}
        item["previousDigest"] = digest({"text": item["text"]})[:16]
        item["text"], item["claimType"] = text, m.claim_type(text)
    item.update(reviewBy=review_by, status="supported", reviewedAt=now, reviewedBy=actor)
    return item


def _current_support(state, support):
    if support.get("kind") == "post":
        return {**support, "version": m.text_digest(m.job_text(m._job(state, support["id"])))[:16]}
    if support.get("kind") == "source":
        return {**support, "version": m.source_version(m._source(state, support["id"]))}
    return support


def link_draft(state, campaign, episode_id, payload, actor, now):
    """Attach an existing draft (any platform or language version of this episode) after the duplicate checks; the
    draft gets lineage to the series and, while a fact needs review, Queue's own blockers."""
    series = campaign["series"]
    episode = m.episode_of(series, episode_id)
    if episode.get("state") not in ("approved", "drafting", "drafted"):
        raise AlphaError("Approve this episode as the next one before adding its draft.", 409, code="approval_required")
    if len(episode.get("draftRefs") or []) >= m.MAX_DRAFTS:
        raise AlphaError(f"An episode keeps up to {m.MAX_DRAFTS} drafts.", 409)
    variant_id = payload.get("variantId")
    if not isinstance(variant_id, str) or not m._ID.match(variant_id):
        raise AlphaError("Choose a draft from this workspace.", 400)
    checks = m.draft_checks(state, campaign, episode, variant_id)
    if checks["refusal"]:
        raise AlphaError(checks["refusal"]["message"], 409, code=checks["refusal"]["code"])
    acknowledged = payload.get("acknowledgedWarnings") or []
    if not isinstance(acknowledged, list) or sorted(str(a) for a in acknowledged) != sorted(w["id"] for w in checks["warnings"]):
        raise AlphaError("Review the similarity warnings for this draft, then confirm them.", 409, code="warnings_unacknowledged")
    variant = m._variant(state, variant_id)
    ref = {"variantId": variant_id, "revision": variant.get("revision"), "textDigest": m.text_digest(variant.get("text"))[:16],
           "platform": variant.get("platform"), "language": variant.get("language"), "linkedAt": now, "linkedBy": actor,
           "warnings": [{k: w[k] for k in ("id", "code", "similarity", "refId")} for w in checks["warnings"]]}
    episode.setdefault("draftRefs", []).append(ref)
    episode.update(state="drafted", updatedAt=now)
    origin = series.get("origin") or {}
    variant["seriesEpisode"] = {"seriesId": campaign["id"], "episodeId": episode["id"], "index": episode.get("index"), "role": episode["role"],
                                "originKind": origin.get("kind"), "originId": origin.get("id")}
    return ref


def unlink_draft(state, campaign, episode_id, variant_id, actor, now):
    series = campaign["series"]
    episode = m.episode_of(series, episode_id)
    refs = [r for r in episode.get("draftRefs") or [] if r.get("variantId") != variant_id]
    if len(refs) == len(episode.get("draftRefs") or []):
        raise AlphaError("That draft is not part of this episode.", 404)
    episode["draftRefs"] = refs
    variant = m._variant(state, variant_id)
    if variant is not None:
        m._strip_gate(variant)
        if (variant.get("seriesEpisode") or {}).get("episodeId") == episode_id:
            variant.pop("seriesEpisode", None)
    if not refs:
        # Back to waiting for a draft, unless another episode took that one place meanwhile.
        episode["state"] = "planned" if _waiting(series, episode_id) else "approved"
    episode["updatedAt"] = now
    return {"variantId": variant_id, "episodeState": episode["state"]}


def link_asset(state, campaign, episode_id, payload, actor, now):
    """Reference an existing Library image for an episode (images only, as campaign links; the image is not copied)."""
    from .. import asset_kinds
    episode = m.episode_of(campaign["series"], episode_id)
    if episode.get("state") not in ("approved", "drafting", "drafted"):
        raise AlphaError("Approve this episode as the next one before adding its image.", 409, code="approval_required")
    asset_id = payload.get("assetId")
    if not isinstance(asset_id, str) or not m._ID.match(asset_id):
        raise AlphaError("Choose an image from this workspace.", 400)
    asset = next((a for a in (state.get("phase2") or {}).get("assets") or [] if isinstance(a, dict) and a.get("id") == asset_id and not a.get("deleted")), None)
    if asset is None:
        raise AlphaError("That image is not in this workspace.", 404)
    if asset_kinds.kind_of(asset) == "video":
        raise AlphaError("A series episode takes images from Library, not videos.", 409, code="unsupported_input")
    if asset_id in (episode.get("assetIds") or []):
        raise AlphaError("This image is already part of this episode.", 409, code="already_linked")
    if len(episode.get("assetIds") or []) >= m.MAX_ASSETS:
        raise AlphaError(f"An episode keeps up to {m.MAX_ASSETS} images.", 409)
    episode.setdefault("assetIds", []).append(asset_id)
    episode["updatedAt"] = now
    return {"assetId": asset_id}


def unlink_asset(state, campaign, episode_id, asset_id, actor, now):
    episode = m.episode_of(campaign["series"], episode_id)
    if asset_id not in (episode.get("assetIds") or []):
        raise AlphaError("That image is not part of this episode.", 404)
    episode["assetIds"] = [a for a in episode["assetIds"] if a != asset_id]
    episode["updatedAt"] = now
    return {"assetId": asset_id}


def set_status(state, campaign, payload, actor, now):
    status = payload.get("status")
    if status not in m.STATUSES:
        raise AlphaError("Choose active, paused, completed or archived.", 400)
    series = campaign["series"]
    if series.get("status") == status:
        raise AlphaError(f"This series is already {status}.", 409, code="lifecycle_transition")
    series.update(status=status, statusChangedAt=now, statusChangedBy=actor)
    campaign["status"] = m.CAMPAIGN_STATUS[status]
    return {"status": status}
