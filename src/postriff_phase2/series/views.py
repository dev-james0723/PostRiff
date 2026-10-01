"""Read projections of a series: what the person sees (coverage, freshness, gates, duplicates, decisions, the one next
action). Everything is recomputed from the workspace at read time, so a deleted source or an expired claim shows at
once even before the sweep gates a draft; nothing here writes."""
from __future__ import annotations

from . import model as m


def _published_jobs(state):
    out = {}
    for job in m._jobs(state):
        variant_id = (job.get("manifest") or {}).get("variantId")
        if variant_id:
            out.setdefault(variant_id, []).append(job)
    return out


def _draft(state, ref, jobs):
    variant = m._variant(state, ref.get("variantId"))
    if variant is None:
        return {"variantId": ref.get("variantId"), "missing": True, "platform": ref.get("platform"), "language": ref.get("language"), "warnings": ref.get("warnings") or []}
    linked_jobs = jobs.get(variant["id"]) or []
    published = next((j for j in linked_jobs if m.verified_at(j) is not None), None)
    series_unknown = any(isinstance(u, str) and u.startswith(m.UNKNOWN_PREFIX) for u in variant.get("unknowns") or [])
    return {"variantId": variant["id"], "missing": False, "platform": variant.get("platform"), "language": variant.get("language"),
            "revision": variant.get("revision"), "changedSinceLinked": variant.get("revision") != ref.get("revision"),
            "needsReview": bool(variant.get("needsReview")), "unknowns": len(variant.get("unknowns") or []), "factGate": series_unknown,
            "blocked": bool(variant.get("blockedByRetraction") or variant.get("policyBlocked") or variant.get("rejected")),
            "published": published is not None, "publishedJobId": published["id"] if published else None,
            "queued": next((j.get("state") for j in linked_jobs if j.get("state") in ("approved", "scheduled", "claimed", "held")), None),
            "excerpt": str(variant.get("text") or "")[:160], "warnings": ref.get("warnings") or []}


def _candidates(state, episode):
    """Drafts an automation run made for this episode and nobody linked yet (offered, never linked silently)."""
    occurrences = {item.get("occurrenceId") for item in episode.get("automation") or []}
    if not occurrences:
        return []
    runs = {o.get("runId") for o in m.planning(state).get("occurrences") or [] if o.get("id") in occurrences and o.get("runId")}
    out = []
    for variant in state.get("variants") or []:
        tagged = (variant.get("automation") or {}).get("occurrenceId") in occurrences or (variant.get("provenance") or {}).get("runId") in runs
        if tagged and not variant.get("rejected") and not m.linked_elsewhere(state, variant["id"]):
            out.append({"variantId": variant["id"], "platform": variant.get("platform"), "language": variant.get("language"), "excerpt": str(variant.get("text") or "")[:160]})
    return out[:m.MAX_DRAFTS]


def _claim(state, series, claim, today):
    found, detail = m.claim_state(state, claim, today)
    support = claim.get("support") or {}
    title = None
    if support.get("kind") == "source":
        title = (m._source(state, support.get("id")) or {}).get("title")
    elif support.get("kind") == "post":
        title = (series.get("origin") or {}).get("platform")
    return {"id": claim["id"], "text": claim["text"], "claimType": claim.get("claimType"), "reviewBy": claim.get("reviewBy"), "status": claim.get("status"),
            "freshness": {"state": found, "reason": m.REASON_CODES.get(found), "detail": detail},
            "support": {"kind": support.get("kind"), "id": support.get("id") if support.get("kind") != "user" else None, "factId": support.get("factId"),
                        "title": " ".join(str(title).split())[:120] if title else None, "available": found not in ("source_unavailable", "missing_support")}}


def episode_view(state, campaign, episode, today, jobs):
    series = campaign["series"]
    issues = m.episode_issues(state, series, episode, today)
    drafts = [_draft(state, ref, jobs) for ref in episode.get("draftRefs") or []]
    published = any(d.get("published") for d in drafts)
    blocked = None
    if episode.get("state") == "planned":
        waiting = next((e for e in series.get("episodes") or [] if e["id"] != episode["id"] and e.get("state") in ("approved", "drafting") and not e.get("draftRefs")), None)
        blocked = "needs_fact_review" if issues else ("episode_pending" if waiting else ("series_inactive" if series.get("status") != "active" else None))
    return {"id": episode["id"], "index": episode.get("index"), "role": episode["role"], "question": episode.get("question"), "angle": episode["angle"],
            "state": "published" if published else episode.get("state"), "workflowState": episode.get("state"), "angleDecision": episode.get("angleDecision"),
            "factState": "needs_fact_review" if issues else "ok", "factReasons": sorted({m.REASON_CODES[found] for _, found, _ in issues}),
            "claimIds": list(episode.get("claimIds") or []), "drafts": drafts, "candidateDrafts": _candidates(state, episode) if episode.get("state") == "drafting" else [],
            "assetIds": list(episode.get("assetIds") or []), "lineage": episode.get("lineage"), "basis": episode.get("basis"),
            "automation": list(episode.get("automation") or []), "covered": bool(drafts), "published": published,
            "canApprove": episode.get("state") == "planned" and blocked is None, "blockedReason": blocked,
            "approvedAt": episode.get("approvedAt"), "createdAt": episode.get("createdAt"), "updatedAt": episode.get("updatedAt")}


def next_action(series, episodes):
    live = [e for e in episodes if e["workflowState"] != "skipped"]
    if any(e["factState"] == "needs_fact_review" and (e["drafts"] or e["workflowState"] in ("approved", "drafting")) for e in live):
        return {"kind": "review_facts"}
    if series.get("status") != "active":
        return {"kind": "resume" if series.get("status") == "paused" else "none"}
    waiting = next((e for e in live if e["workflowState"] in ("approved", "drafting") and not e["drafts"]), None)
    if waiting:
        return {"kind": "add_draft", "episodeId": waiting["id"]}
    ready = next((e for e in live if e["canApprove"]), None)
    if ready:
        return {"kind": "approve_next", "episodeId": ready["id"]}
    if any(e["workflowState"] == "planned" for e in live):
        return {"kind": "review_facts"}
    return {"kind": "plan_more"}


def _decision(state, record, member_is_owner):
    active = m.decision_active(state, record)
    return {"id": record["id"], "decision": record["decision"], "level": record.get("level", "angle"), "role": record["role"], "angleText": record.get("angleText"),
            "episodeId": record.get("episodeId"), "storage": record.get("storage"), "reason": record.get("reason"),
            "status": "active" if active else ("revoked" if record.get("status") == "revoked" else "inactive"),
            "createdAt": record.get("createdAt"), "revokedAt": record.get("revokedAt"),
            "canRevoke": active and (record.get("storage") != "overlay" or member_is_owner)}


def detail(state, campaign, now, member=None):
    series = campaign["series"]
    today = m._day(now)
    jobs = _published_jobs(state)
    episodes = [episode_view(state, campaign, e, today, jobs) for e in sorted(series.get("episodes") or [], key=lambda e: e.get("index", 0))]
    origin = series.get("origin") or {}
    text = m.origin_text(state, origin)
    claims = [_claim(state, series, c, today) for c in series.get("claims") or []]
    questions = [{"episodeId": e["id"], "index": e["index"], "role": e["role"], "question": e["question"], "state": e["state"], "covered": e["covered"]}
                 for e in episodes if e["workflowState"] != "skipped"]
    owner = bool(member and member.allows("owner"))
    tasks = {t.get("id"): t for t in m.planning(state).get("recurringTasks") or []}
    return {"id": campaign["id"], "revision": series.get("revision"), "title": series.get("title"), "audienceQuestion": series.get("audienceQuestion"),
            "goal": series.get("goal"), "language": series.get("language"), "owner": series.get("owner"), "status": series.get("status"),
            "createdAt": series.get("createdAt"), "updatedAt": series.get("updatedAt"),
            "origin": {"kind": origin.get("kind"), "id": origin.get("id"), "available": text is not None, "platform": origin.get("platform"),
                       "publishedAt": origin.get("publishedAt"), "title": origin.get("title"), "excerpt": (text or "")[:600], "contentDigest": origin.get("contentDigest")},
            "sources": [{"sourceId": s["sourceId"], "title": s.get("title"), "available": bool((m._source(state, s["sourceId"]) or {}).get("active")),
                         "versionCurrent": m.source_version(m._source(state, s["sourceId"])) == s.get("version") if m._source(state, s["sourceId"]) else False}
                        for s in series.get("sources") or []],
            "claims": claims, "episodes": episodes,
            "coverage": {"audienceQuestion": series.get("audienceQuestion"), "covered": any(q["covered"] for q in questions), "questions": questions,
                         "coveredCount": sum(1 for q in questions if q["covered"]), "publishedCount": sum(1 for e in episodes if e["published"]), "total": len(questions)},
            "decisions": [_decision(state, d, owner) for d in reversed(series.get("decisions") or [])],
            "followers": [{"taskId": task_id, "name": (tasks.get(task_id) or {}).get("name"), "status": (tasks.get(task_id) or {}).get("status")} for task_id in m.followers(state, campaign["id"])],
            "injectionFlags": series.get("injectionFlags", 0), "nextAction": next_action(series, episodes),
            "limits": {"maxPlan": m.MAX_PLAN, "maxEpisodes": m.MAX_EPISODES, "maxDrafts": m.MAX_DRAFTS, "reviewMaxDays": m.REVIEW_MAX_DAYS},
            "definitionVersion": m.SCHEMA, "asOf": now, "dataState": "available"}


def summary(state, campaign, now):
    view = detail(state, campaign, now)
    return {**{k: view[k] for k in ("id", "revision", "title", "audienceQuestion", "status", "language", "createdAt", "updatedAt", "nextAction")},
            "origin": {k: view["origin"][k] for k in ("kind", "available", "platform", "publishedAt", "title")},
            "episodes": len([e for e in view["episodes"] if e["workflowState"] != "skipped"]),
            "coveredCount": view["coverage"]["coveredCount"], "publishedCount": view["coverage"]["publishedCount"],
            "needsFactReview": sum(1 for e in view["episodes"] if e["factState"] == "needs_fact_review" and e["workflowState"] != "skipped"),
            "followers": len(view["followers"])}
