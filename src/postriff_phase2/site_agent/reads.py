"""Workspace reads for the questions people ask Rafii across the app: Brand Brain, the learned voice, search, the
calendar, campaigns, reviews, publishing results, what needs attention, and the status of the selected item.

Every function reads this member's snapshot of this workspace (tools.Context) and returns stored facts with ids and
links. Anything computed from them (a gap in the calendar, two posts close together, a platform with nothing
planned) is marked `derived` with the rule that produced it, so an answer can say "observation" instead of
presenting it as a stored fact. Suggestions are never produced here; the answer layer labels its own.
"""
from __future__ import annotations

import datetime as dt
import re

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError

from .. import automation_edit, automation_plan, campaigns, lifecycle, memory
from . import contracts, routes, timeframe
from .tools import IN_FLIGHT, JOB_STATES, WAITING, _account, _job_view, _review_expired, redact

PRIVATE = ("private", "local-only", "local_only", "excluded")
CLOSE_SECONDS = 2 * 3600
REPEAT_THRESHOLD = 0.6


def _zone(ctx):
    return getattr(ctx, "zone", None) or "UTC"


def _phase2(ctx):
    return ctx.state.get("phase2") or {}


def _variants(ctx):
    return [v for v in ctx.state.get("variants", []) if isinstance(v, dict)]


def _jobs(ctx):
    return [j for j in _phase2(ctx).get("jobs", []) if isinstance(j, dict)]


def _reviews(ctx):
    return [r for r in _phase2(ctx).get("reviews", []) if isinstance(r, dict)]


def _timestamp(item):
    return ((item.get("manifest") or {}).get("timing") or {}).get("timestamp")


def _draft_href(draft_id):
    return routes.href("queue", query={"view": "drafts", "draft": draft_id}) or routes.href("queue", query={"view": "drafts"})


def _excerpt(text, limit=140):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- Brand Brain and voice -----------------------------------------------------------------------------------------
def brand_summary(ctx):
    state = ctx.state
    hub = state.get("brandHub") or {}
    you = state.get("you") if isinstance(state.get("you"), dict) else {}
    revision = memory.active_profile(state)
    profile = (revision or {}).get("profile") or {}
    boundaries = []
    for field in memory.boundary_fields(state):
        private = (field.get("privacy") or "") in PRIVATE
        boundaries.append({"label": field.get("label") or field.get("key") or "Boundary", "value": None if private else redact(str(field.get("value") or ""), 200),
                           "privacy": field.get("privacy"), "private": private})
    learned = [{"statement": item.get("statement"), "scope": learning.scope_label(item.get("scope") or {}), "polarity": item.get("polarity"), "type": item.get("type")}
               for item in learning.active_items(state)][:20]
    identity = {key: hub.get(key) or None for key in ("purpose", "audience", "subject", "mode", "speaker")}
    identity["identitySentence"] = you.get("identitySentence") or None
    identity["layers"] = hub.get("layers") or []
    voice = None
    if revision and not (revision.get("stale") or profile.get("status") == "stale"):
        voice = {"revision": revision.get("revision"), "approvedAt": revision.get("approvedAt"), "tone": profile.get("tone") or None,
                 "observations": [str(o) for o in profile.get("observations") or []][:12], "writingExample": _excerpt(profile.get("writingExample") or "", 400) or None,
                 "unknowns": [str(u) for u in profile.get("unknowns") or []][:6]}
    stored = any(identity[k] for k in ("purpose", "audience", "subject", "mode", "speaker", "identitySentence")) or voice or boundaries or learned
    return contracts.result({"identity": identity, "voice": voice, "boundaries": boundaries, "learned": learned, "empty": not stored,
                             "href": routes.href("memory"), "brandHref": routes.href("brand")}, now=ctx.now)


def voice_profile(ctx, platform=None):
    brand = brand_summary(ctx)["data"]
    items = learning.active_items(ctx.state)
    by_scope: dict[str, list[str]] = {}
    for item in items:
        scope = item.get("scope") or {}
        if platform and scope.get("platform") not in (None, platform):
            continue
        by_scope.setdefault(learning.scope_label(scope), []).append(item.get("statement"))
    samples = sum(1 for s in ctx.state.get("sources", []) if isinstance(s, dict) and s.get("kind") == "voice_sample" and s.get("active"))
    speaker = ctx.state.get("speaker") or {}
    return contracts.result({"voice": brand["voice"], "learnedByScope": by_scope, "samples": samples, "provisional": bool(speaker.get("provisional")),
                             "platformSpecific": sorted({(i.get("scope") or {}).get("platform") for i in items if (i.get("scope") or {}).get("platform")}),
                             "href": routes.href("brand")}, now=ctx.now, verified=brand["voice"] is not None or bool(items))


# --- search ----------------------------------------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]{3,}|[㐀-鿿]{2,}")
_STOP = {"the", "and", "for", "with", "about", "that", "this", "post", "posts", "draft", "drafts", "find", "show", "everything", "related", "wrote", "write",
         "campaign", "campaigns", "content", "from", "last", "month", "week", "where", "did", "use", "used", "phrase", "before", "all", "across", "mentioning", "any", "have", "what"}


def _terms(query):
    words = [w for w in _WORD.findall((query or "").lower()) if w not in _STOP]
    quoted = re.findall(r"[\"“']([^\"”']{3,80})[\"”']", query or "")
    return words, [q.lower() for q in quoted]


def _match(text, words, phrases):
    lower = (text or "").lower()
    if phrases and not all(p in lower for p in phrases):
        return 0
    hits = sum(1 for w in words if w in lower)
    return hits + 2 * len(phrases)


def _run_times(ctx, run_ids):
    """When each writing run started: a draft's own time. Read in this workspace only, inside the turn's transaction."""
    ids = sorted({r for r in run_ids if isinstance(r, str) and routes.ID_VALUE.match(r)})
    if not ids or ctx.cur is None:
        return {}
    ctx.cur.execute("SELECT id::text, extract(epoch FROM created_at) FROM public.pr_agent_runs WHERE workspace_id=%s AND id::text = ANY(%s)", (ctx.workspace_id, ids))
    return {row[0]: float(row[1]) for row in ctx.cur.fetchall()}


def _epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def content_search(ctx, query, kinds=None, platform=None, since=None, until=None, label=None):
    """Words or a quoted phrase across drafts, sources, campaigns, automations and posts. Without a quoted phrase, what
    was made from a match (a draft from a matching source, a campaign's automation and drafts) is included and marked
    `via`; a quoted phrase lists only real uses of it. Dates apply to every kind: a draft's time is its writing run's,
    a post's is its publish time; an item with no time is left out of a dated search and counted in `undated`."""
    words, phrases = _terms(query)
    if not words and not phrases and list(kinds or []) == ["draft"]:
        # "My unfinished / recent drafts": the newest drafts first, with what each still needs.
        scheduled = {(j.get("manifest") or {}).get("variantId") for j in _jobs(ctx) if j.get("state") not in ("failed", "canceled")}
        items = []
        for index, v in reversed(list(enumerate(_variants(ctx)))):
            if v.get("rejected") or (platform and v.get("platform") != platform):
                continue
            needs = [r for r, on in (("unknown details", bool(v.get("unknowns"))), ("review after a change", v.get("needsReview")), ("not scheduled", v.get("id") not in scheduled)) if on]
            items.append({"kind": "draft", "id": v.get("id"), "title": f"{v.get('platform')} draft" + (f" · {_account(ctx, v.get('channelId'))}" if v.get("channelId") else ""),
                          "excerpt": _excerpt(v.get("text")), "href": _draft_href(v.get("id")), "needs": needs, "scheduled": v.get("id") in scheduled, "score": 1})
        return contracts.result({"query": "", "results": items[:10], "total": len(items), "searched": ["draft"], "listing": True}, now=ctx.now)
    if not words and not phrases:
        return contracts.result({"query": query, "results": [], "searched": []}, now=ctx.now, verified=False, warnings=["Name a topic, a phrase or a title to search for."])
    wanted = set(kinds or ("draft", "source", "campaign", "automation", "post"))
    results = []
    zone = _zone(ctx)
    needed = max(1, min(2, len(words) + len(phrases)))
    link = not phrases
    dated = since is not None or until is not None
    undated: dict[str, int] = {}

    def passes(score):
        return score >= needed or bool(score and len(words) + len(phrases) == 1)

    def in_dates(kind, at):
        if not dated:
            return True
        if at is None:
            undated[kind] = undated.get(kind, 0) + 1
            return False
        return (since is None or at >= since) and (until is None or at < until)

    def keep(kind, score, item, via=None, at=None):
        if passes(score) and in_dates(kind, at):
            results.append({**item, "kind": kind, "score": score, "via": via})

    # Sources and campaigns first: what was made from a match is related to it ("everything related to the launch").
    root = campaigns._root(ctx.state)
    source_hits, campaign_hits = {}, {}
    for s in ctx.state.get("sources", []):
        if not isinstance(s, dict) or not s.get("active") or s.get("kind") == "voice_sample":
            continue
        text = " ".join([s.get("title") or "", s.get("text") or ""] + [f.get("text", "") for f in s.get("facts") or [] if isinstance(f, dict)])
        score = _match(text, words, phrases)
        if passes(score):
            source_hits[s.get("id")] = score
        if "source" in wanted:
            keep("source", score, {"id": s.get("id"), "title": s.get("title") or "Source", "excerpt": _excerpt(s.get("text")), "href": routes.href("ideas")}, at=_epoch(s.get("createdAt")))
    for c in root["campaigns"]:
        if c.get("status") == "cancelled":
            continue
        score = _match(" ".join([c.get("goal") or "", c.get("audience") or "", " ".join(str(v) for v in (c.get("facts") or {}).values())]), words, phrases)
        if passes(score):
            campaign_hits[c.get("id")] = score
        if "campaign" in wanted:
            keep("campaign", score, {"id": c.get("id"), "title": _excerpt(c.get("goal"), 90), "excerpt": _excerpt(c.get("audience")), "href": routes.href("automations", query={"campaign": c["id"]})},
                 at=_epoch(c.get("createdAt")))
    task_campaign = {t.get("id"): t.get("campaignId") for t in root["recurringTasks"]}
    variants = [v for v in _variants(ctx) if not (platform and v.get("platform") != platform)]
    run_times = _run_times(ctx, [(v.get("provenance") or {}).get("runId") for v in variants]) if dated and "draft" in wanted else {}
    draft_hits = {}
    for index, v in enumerate(variants):
        score, via = _match(v.get("text"), words, phrases), None
        if not passes(score) and link:
            from_source = max((source_hits.get(i, 0) for i in v.get("sourceIds") or []), default=0)
            from_campaign = campaign_hits.get(task_campaign.get((v.get("automation") or {}).get("taskId")), 0)
            if from_source:
                score, via = from_source, "made from a matching source"
            elif from_campaign:
                score, via = from_campaign, "from a matching campaign's automation"
        if passes(score):
            draft_hits[v.get("id")] = score
        if "draft" in wanted:
            keep("draft", score, {"id": v.get("id"), "title": f"{v.get('platform')} draft" + (f" · {_account(ctx, v.get('channelId'))}" if v.get("channelId") else ""),
                                  "excerpt": _excerpt(v.get("text")), "href": _draft_href(v.get("id")), "order": index, "setAside": bool(v.get("rejected"))},
                 via, at=run_times.get((v.get("provenance") or {}).get("runId")))
    if "automation" in wanted:
        for t in automation_edit.live_tasks(ctx.state):
            score, via = _match(" ".join([t.get("name") or "", t.get("intent") or ""]), words, phrases), None
            if not passes(score) and link and campaign_hits.get(t.get("campaignId")):
                score, via = campaign_hits[t["campaignId"]], "belongs to a matching campaign"
            keep("automation", score, {"id": t.get("id"), "title": t.get("name") or "Automation", "excerpt": _excerpt(t.get("intent")), "href": routes.href("automations", query={"edit": t["id"]}),
                                       "status": t.get("status")}, via, at=_epoch(t.get("createdAt")))
    if "post" in wanted:
        for j in _jobs(ctx):
            manifest = j.get("manifest") or {}
            if platform and manifest.get("platform") != platform:
                continue
            at = _timestamp(j)
            score, via = _match((manifest.get("payload") or {}).get("text"), words, phrases), None
            if not passes(score) and link and draft_hits.get(manifest.get("variantId")):
                score, via = draft_hits[manifest["variantId"]], "a post of a matching draft"
            keep("post", score, {"id": j.get("id"), "title": f"{manifest.get('platform')} post · {manifest.get('account')}", "excerpt": _excerpt((manifest.get("payload") or {}).get("text")),
                                 "state": j.get("state"), "when": timeframe.local(at, zone), "href": routes.href("queue", query={"job": j["id"]})}, via, at=at)
    # Direct matches first, then what is linked to one.
    results.sort(key=lambda r: (r.get("via") is not None, -r["score"], -(r.get("order") or 0)))
    linked = sum(1 for r in results if r.get("via"))
    return contracts.result({"query": query, "terms": list(dict.fromkeys(phrases or words)), "results": results[:12], "total": len(results), "direct": len(results) - linked,
                             "linked": linked, "searched": sorted(wanted), "range": {"label": label or "in those dates"} if dated else None, "undated": undated}, now=ctx.now)


# --- calendar --------------------------------------------------------------------------------------------------------
def _entries(ctx, start, end, zone):
    entries = []
    for j in _jobs(ctx):
        at = _timestamp(j)
        if at is None or not start <= at < end or j.get("state") == "canceled":
            continue
        manifest = j.get("manifest") or {}
        entries.append({"kind": "job", "id": j["id"], "state": j.get("state"), "title": JOB_STATES.get(j.get("state"), (j.get("state"),))[0], "platform": manifest.get("platform"),
                        "account": manifest.get("account"), "channelId": manifest.get("channelId"), "at": at, "when": timeframe.local(at, zone),
                        "text": manifest.get("payload", {}).get("text") or "", "href": routes.href("queue", query={"job": j["id"]})})
    for r in _reviews(ctx):
        if r.get("status") != "needs_review":
            continue
        at = _timestamp(r)
        if at is None or not start <= at < end:
            continue
        manifest = r.get("manifest") or {}
        entries.append({"kind": "review", "id": r["id"], "state": "expired" if _review_expired(r, ctx.now) else "needs_review", "title": "Waiting for approval",
                        "platform": manifest.get("platform"), "account": manifest.get("account"), "channelId": manifest.get("channelId"), "at": at,
                        "when": timeframe.local(at, zone), "text": (manifest.get("payload") or {}).get("text") or "", "href": routes.href("queue")})
    root = campaigns._root(ctx.state)
    for occurrence in root.get("occurrences", []):
        for item in occurrence.get("items") or []:
            at = item.get("publishAt")
            if not isinstance(at, (int, float)) or not start <= at < end or item.get("jobId"):
                continue
            entries.append({"kind": "automation_item", "id": f"{occurrence.get('id')}:{item.get('key')}", "state": item.get("state"), "title": f"Automation post ({item.get('state', '').replace('_', ' ')})",
                            "platform": item.get("platform"), "account": item.get("account"), "channelId": item.get("channelId"), "at": at, "when": timeframe.local(at, zone),
                            "text": "", "href": routes.href("automations", query={"edit": occurrence.get("taskId")}) if occurrence.get("taskId") else routes.href("automations")})
    return sorted(entries, key=lambda e: e["at"])


def _similar(a, b):
    left, right = set(_WORD.findall((a or "").lower())), set(_WORD.findall((b or "").lower()))
    if len(left) < 5 or len(right) < 5:
        return 0.0
    return len(left & right) / len(left | right)


def calendar_range(ctx, start=None, end=None, label=None, platform=None):
    zone = _zone(ctx)
    if start is None or end is None:
        frame = timeframe.parse("this week", ctx.now, zone)
        start, end, label = frame["start"], frame["end"], frame["label"]
    entries = [e for e in _entries(ctx, start, end, zone) if not platform or e["platform"] == platform]
    days = []
    cursor = dt.datetime.fromtimestamp(start, timeframe._zone(zone)).date()
    last = dt.datetime.fromtimestamp(end - 1, timeframe._zone(zone)).date()
    while cursor <= last and len(days) < 62:
        iso = cursor.isoformat()
        days.append({"date": iso, "weekday": cursor.strftime("%A"), "count": sum(1 for e in entries if timeframe.date_of(e["at"], zone) == iso)})
        cursor += dt.timedelta(days=1)
    today = timeframe.date_of(ctx.now, zone)
    gaps = [d for d in days if d["count"] == 0 and d["date"] >= today]
    close = []
    by_account: dict[str, list[dict]] = {}
    for e in entries:
        by_account.setdefault(e.get("channelId") or f"{e['platform']}:{e.get('account')}", []).append(e)
    for items in by_account.values():
        for a, b in zip(items, items[1:]):
            if b["at"] - a["at"] < CLOSE_SECONDS:
                close.append({"first": a["when"], "second": b["when"], "platform": a["platform"], "account": a.get("account"), "minutes": round((b["at"] - a["at"]) / 60)})
    repeats = []
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if a["text"] and b["text"] and _similar(a["text"], b["text"]) >= REPEAT_THRESHOLD:
                repeats.append({"first": a["when"], "second": b["when"], "similarity": round(_similar(a["text"], b["text"]), 2)})
    platforms = {}
    for e in entries:
        platforms[e["platform"]] = platforms.get(e["platform"], 0) + 1
    shown = [{k: e[k] for k in ("kind", "id", "state", "title", "platform", "account", "when", "href")} for e in entries][:30]
    return contracts.result({"range": {"label": label, "start": contracts.iso(start), "end": contracts.iso(end), "timeZone": zone}, "entries": shown, "total": len(entries),
                             "perPlatform": platforms, "days": days,
                             "derived": {"emptyDays": {"rule": "days from today in this range with nothing scheduled, waiting or planned", "days": [f"{d['weekday']} {d['date']}" for d in gaps]},
                                         "closeTogether": {"rule": f"two posts on the same account less than {CLOSE_SECONDS // 3600} hours apart", "pairs": close[:6]},
                                         "similarText": {"rule": f"two posts sharing at least {int(REPEAT_THRESHOLD * 100)}% of their words", "pairs": repeats[:6]}},
                             "href": routes.href("calendar", query={"view": "week"})}, now=ctx.now)


# --- campaigns -------------------------------------------------------------------------------------------------------
def _campaign_view(ctx, campaign, detail=False):
    root = campaigns._root(ctx.state)
    zone = _zone(ctx)
    tasks = [t for t in root["recurringTasks"] if t.get("campaignId") == campaign["id"] and not t.get("deletedAt")]
    task_ids = {t["id"] for t in tasks}
    platforms = sorted({d.get("platform") for t in tasks for d in t.get("destinations") or []})
    view = {"campaignId": campaign["id"], "goal": campaign.get("goal"), "audience": campaign.get("audience"), "status": campaign.get("status"),
            "missingFacts": list(campaign.get("missingFacts") or []), "facts": {k: redact(str(v), 160) for k, v in (campaign.get("facts") or {}).items()},
            "automations": [{"automationId": t["id"], "name": t.get("name"), "status": t.get("status"), "schedule": automation_plan.describe(t["schedule"]) if t.get("schedule") else None,
                             "policy": (t.get("workflow") or {}).get("policy") or "drafts", "nextRun": timeframe.local((t.get("nextOccurrence") or {}).get("scheduledFor"), zone)} for t in tasks],
            "platforms": platforms, "href": routes.href("automations", query={"campaign": campaign["id"]})}
    if not detail:
        return view
    drafts = [v for v in _variants(ctx) if (v.get("automation") or {}).get("taskId") in task_ids]
    variant_ids = {v.get("id") for v in drafts}
    jobs = [j for j in _jobs(ctx) if (j.get("manifest") or {}).get("variantId") in variant_ids or (j.get("automation") or {}).get("taskId") in task_ids]
    week_ago = ctx.now - 7 * 86400
    runs = []
    for occurrence in root.get("occurrences", []):
        if occurrence.get("taskId") not in task_ids:
            continue
        at = occurrence.get("anchorAt") or occurrence.get("scheduledFor") or occurrence.get("createdAt")
        runs.append({"runId": occurrence.get("id"), "status": lifecycle.status(occurrence), "when": timeframe.local(at, zone), "at": at,
                     "items": [{"platform": i.get("platform"), "state": i.get("state"), "reason": i.get("reason")} for i in occurrence.get("items") or []][:6]})
    runs.sort(key=lambda r: -(r["at"] or 0))
    connected = sorted({c.get("platform") for c in _phase2(ctx).get("channels", []) if isinstance(c, dict) and not c.get("revoked")})
    upcoming = [r for r in runs if (r["at"] or 0) >= ctx.now]
    derived = {"platformsNotCovered": {"rule": "connected platforms none of this campaign's automations post to", "items": [p for p in connected if p not in platforms]},
               "noUpcomingRun": {"rule": "no active automation with a next run", "value": not any(a["status"] == "active" and a["nextRun"] for a in view["automations"])},
               "failedOrSkippedLastWeek": {"rule": "runs in the last 7 days that failed or were skipped", "items": [r for r in runs if (r["at"] or 0) >= week_ago and r["status"] in ("failed", "skipped", "source_unavailable")][:4]}}
    return {**view, "drafts": [{"draftId": v.get("id"), "platform": v.get("platform"), "account": _account(ctx, v.get("channelId")), "excerpt": _excerpt(v.get("text"), 100),
                                "href": _draft_href(v.get("id"))} for v in drafts][:10],
            "draftCount": len(drafts), "posts": [_job_view(ctx, j) for j in jobs][:6],
            "lastWeek": [r for r in runs if week_ago <= (r["at"] or 0) < ctx.now][:6], "upcomingRuns": upcoming[:3], "derived": derived}


# Words that describe the question about a campaign, never its name ("the objective of the Black Friday campaign").
_CAMPAIGN_QUESTION = {"objective", "objectives", "goal", "goals", "audience", "status", "missing", "covered", "platform", "platforms", "belong", "belongs",
                      "happened", "happen", "still", "planned", "plan", "gap", "gaps", "called", "named", "current", "which", "running", "tell", "about",
                      "summary", "summarize", "summarise", "explain", "doing", "going", "performance", "details", "detail", "info", "information", "week",
                      "discussing", "discussed", "talking", "mentioned", "earlier", "just", "were", "was"}


def campaign_list(ctx, query=None):
    """Campaign briefs. Words that name a campaign narrow the list (`matched`); words that name none keep every
    campaign as a candidate and say so, so "not found" is never claimed for a question that named nothing. A name
    that matches nothing never falls back to the only campaign: `detail` is read only for a match or an unnamed ask."""
    root = campaigns._root(ctx.state)
    live = [c for c in root["campaigns"] if c.get("status") != "cancelled"]
    words, phrases = _terms(query or "")
    words = [w for w in words if w not in _CAMPAIGN_QUESTION]
    matched = None
    if words or phrases:
        scored = [(_match(" ".join([c.get("goal") or "", c.get("audience") or ""] + [t.get("name") or "" for t in root["recurringTasks"] if t.get("campaignId") == c["id"]]), words, phrases), c) for c in live]
        hits = [c for score, c in sorted(scored, key=lambda x: -x[0]) if score > 0]
        matched = bool(hits)
        if hits:
            live = hits
    data = {"campaigns": [_campaign_view(ctx, c) for c in live][:10], "total": len(live), "query": query, "matched": matched}
    if len(live) == 1 and matched is not False:
        # One campaign: read it in full (still a read of the same snapshot).
        data["detail"] = _campaign_view(ctx, live[0], detail=True)
    return contracts.result(data, now=ctx.now)


def campaign_get(ctx, campaignId):
    root = campaigns._root(ctx.state)
    campaign = next((c for c in root["campaigns"] if c.get("id") == campaignId), None)
    if campaign is None:
        task = next((t for t in root["recurringTasks"] if t.get("id") == campaignId), None)
        campaign = next((c for c in root["campaigns"] if task and c.get("id") == task.get("campaignId")), None)
    if campaign is None:
        raise AlphaError("That campaign is not in this workspace.", 404, code="not_found")
    return contracts.result(_campaign_view(ctx, campaign, detail=True), now=ctx.now)


# --- reviews and publishing ------------------------------------------------------------------------------------------
def reviews_list(ctx):
    """What waits for a decision. A review links to the Queue, where it is listed under "Waiting for approval"
    (the Queue's `?job=` opens jobs only; a review id there would read as a missing job)."""
    zone = _zone(ctx)
    waiting = [{"reviewId": r["id"], "platform": (r.get("manifest") or {}).get("platform"), "account": (r.get("manifest") or {}).get("account"),
                "when": timeframe.local(_timestamp(r), zone), "expired": _review_expired(r, ctx.now), "href": routes.href("queue")}
               for r in _reviews(ctx) if r.get("status") == "needs_review"]
    root = campaigns._root(ctx.state)
    automation_items, returned = [], []
    for occurrence in root.get("occurrences", []):
        for item in occurrence.get("items") or []:
            base = {"automationId": occurrence.get("taskId"), "platform": item.get("platform"), "account": item.get("account"), "when": timeframe.local(item.get("publishAt"), zone),
                    "href": routes.href("automations", query={"edit": occurrence["taskId"]}) if occurrence.get("taskId") else routes.href("automations")}
            decision = item.get("decision") or {}
            if item.get("state") in ("ready_for_review", "needs_revision"):
                automation_items.append({**base, "state": item.get("state"), "reason": item.get("reason")})
            if decision.get("decision") in ("reject", "revise"):
                returned.append({**base, "decision": decision.get("decision"), "note": redact(decision.get("note") or "", 300) or None, "state": item.get("state")})
    feedback = []
    for v in _variants(ctx):
        for entry in v.get("feedback") or []:
            if isinstance(entry, dict) and (entry.get("note") or entry.get("text")):
                feedback.append({"draftId": v.get("id"), "platform": v.get("platform"), "note": redact(entry.get("note") or entry.get("text"), 300), "href": _draft_href(v.get("id"))})
    needs = [{"draftId": v.get("id"), "platform": v.get("platform"), "account": _account(ctx, v.get("channelId")), "reasons": [r for r, on in (("marked for review", v.get("needsReview")), ("unknown details", bool(v.get("unknowns"))), ("a retracted source", v.get("blockedByRetraction"))) if on],
              "href": _draft_href(v.get("id"))} for v in _variants(ctx) if not v.get("rejected") and (v.get("needsReview") or v.get("unknowns") or v.get("blockedByRetraction"))]
    rejected = [{"draftId": v.get("id"), "platform": v.get("platform"), "href": _draft_href(v.get("id"))} for v in _variants(ctx) if v.get("rejected")]
    return contracts.result({"waitingApproval": waiting[:10], "automationItems": automation_items[:10], "returned": returned[:10], "feedback": feedback[:10],
                             "draftsNeedingReview": needs[:10], "setAside": rejected[:10], "href": routes.href("queue")}, now=ctx.now)


def publishing_summary(ctx, start=None, end=None, label=None):
    zone = _zone(ctx)
    if start is None or end is None:
        frame = timeframe.parse("today", ctx.now, zone)
        start, end, label = frame["start"], frame["end"], frame["label"]
    jobs = _jobs(ctx)
    in_range = [j for j in jobs if _timestamp(j) is not None and start <= _timestamp(j) < end]

    def views(states, source):
        return [{**_job_view(ctx, j), "href": routes.href("queue", query={"job": j["id"]})} for j in source if j.get("state") in states][:8]

    return contracts.result({"range": {"label": label, "start": contracts.iso(start), "end": contracts.iso(end), "timeZone": zone},
                             "verified": views(("verified",), in_range), "publishedUnconfirmed": views(("published", "provider_accepted"), in_range),
                             "scheduled": views(WAITING, in_range), "inFlight": views(IN_FLIGHT, jobs), "failed": views(("failed",), jobs),
                             "uncertain": views(("uncertain",), jobs), "held": views(("held",), jobs),
                             "note": "Only 'verified' means the provider confirmed the post is live. Scheduled and in-flight posts have not been published yet."}, now=ctx.now)


# --- attention -------------------------------------------------------------------------------------------------------
def attention_summary(ctx):
    zone = _zone(ctx)
    facts, observations = [], []
    reviews = reviews_list(ctx)["data"]
    for r in reviews["waitingApproval"]:
        facts.append({"kind": "review_waiting", "text": f"A {r['platform']} post for {r['account']} at {r['when']} is waiting for approval" + (" (its review window closed)" if r["expired"] else ""), "href": r["href"]})
    for item in reviews["automationItems"]:
        facts.append({"kind": "automation_review", "text": f"An automation post for {item['platform']} ({item['when'] or 'no time'}) is {item['state'].replace('_', ' ')}", "href": item["href"]})
    for j in _jobs(ctx):
        if j.get("state") in ("held", "failed", "uncertain"):
            view = _job_view(ctx, j)
            facts.append({"kind": f"job_{j['state']}", "text": f"A {view['platform']} post for {view['account']} ({view['publishAt']}) is {j['state']}: {view['meaning']}", "href": routes.href("queue", query={"job": j["id"]})})
    for c in _phase2(ctx).get("channels", []):
        if isinstance(c, dict) and (c.get("revoked") or (c.get("expiresAt") or 0) <= ctx.now):
            facts.append({"kind": "account", "text": f"{c.get('platform')} · {c.get('account')} needs reconnecting.", "href": routes.href("channels")})
    for t in automation_edit.live_tasks(ctx.state):
        if t.get("status") == "draft":
            facts.append({"kind": "automation_off", "text": f"Automation “{t.get('name')}” is not turned on; an owner needs to activate it.", "href": routes.href("automations", query={"edit": t["id"]})})
    pending = 0
    if ctx.cur is not None:
        from ..learning_service import pending_proposals
        pending = len(pending_proposals(ctx.cur, ctx.workspace_id))
    if pending:
        facts.append({"kind": "memory", "text": f"{pending} learned preference(s) are waiting for an owner's decision.", "href": routes.href("memory")})
    week = timeframe.parse("next 7 days", ctx.now, zone)
    calendar = calendar_range(ctx, week["start"], week["end"], week["label"])["data"]
    if calendar["derived"]["emptyDays"]["days"]:
        observations.append({"kind": "gap", "rule": calendar["derived"]["emptyDays"]["rule"], "text": "Nothing is scheduled, waiting or planned on " + ", ".join(calendar["derived"]["emptyDays"]["days"][:7]) + ".",
                             "href": calendar["href"]})
    for pair in calendar["derived"]["closeTogether"]["pairs"]:
        observations.append({"kind": "close", "rule": calendar["derived"]["closeTogether"]["rule"], "text": f"Two {pair['platform']} posts for {pair['account']} are {pair['minutes']} minutes apart ({pair['first']}, {pair['second']}).",
                             "href": calendar["href"]})
    for pair in calendar["derived"]["similarText"]["pairs"]:
        observations.append({"kind": "repetitive", "rule": calendar["derived"]["similarText"]["rule"], "text": f"The posts at {pair['first']} and {pair['second']} share {int(pair['similarity'] * 100)}% of their words.",
                             "href": calendar["href"]})
    fortnight = ctx.now - 14 * 86400
    # "Waiting" is what the rule says: a review waiting for approval and a live automation post count, not only jobs.
    activity = [((j.get("manifest") or {}).get("platform"), _timestamp(j)) for j in _jobs(ctx) if j.get("state") != "canceled"]
    activity += [((r.get("manifest") or {}).get("platform"), _timestamp(r)) for r in _reviews(ctx) if r.get("status") == "needs_review"]
    activity += [(item.get("platform"), item.get("publishAt")) for o in campaigns._root(ctx.state).get("occurrences", []) for item in o.get("items") or []
                 if item.get("state") not in ("rejected", "skipped", "failed", "cancelled", "canceled")]
    for platform in sorted({c.get("platform") for c in _phase2(ctx).get("channels", []) if isinstance(c, dict) and not c.get("revoked")}):
        recent = [at for name, at in activity if name == platform and isinstance(at, (int, float)) and at >= fortnight]
        if not recent:
            observations.append({"kind": "neglected", "rule": "a connected platform with no post scheduled, waiting or published in the last 14 days or the days ahead",
                                 "text": f"{platform} has nothing scheduled or published in the last 14 days or ahead.", "href": routes.href("calendar")})
    return contracts.result({"facts": facts[:15], "observations": observations[:10]}, now=ctx.now)


# --- the selected item -----------------------------------------------------------------------------------------------
def entity_status(ctx, type, id):  # noqa: A002 — mirrors the page context's field names
    if type in ("job", "review"):
        from .tools import job_get
        data = job_get(ctx, id)["data"]
        still = list(data.get("steps") or [])
        return contracts.result({"kind": data.get("kind"), "summary": data, "stillNeeded": still, "platform": data.get("platform"), "account": data.get("account")}, now=ctx.now)
    if type == "draft":
        from .tools import draft_get
        data = draft_get(ctx, id)["data"]
        still = []
        if data["overLimit"]:
            still.append(f"Shorten it to {data['limit']} characters or fewer.")
        if data["unknowns"]:
            still.append("Confirm or remove the unknown details: " + "; ".join(data["unknowns"][:3]))
        if data["needsReview"]:
            still.append("Review it: it was marked for review after a change.")
        if data["blockedByRetraction"]:
            still.append("Draft it again: a source it used was retracted.")
        if not data["scheduled"]:
            still.append("Schedule it: choose the account and time, then approve the exact post.")
        campaign = None
        variant = next((v for v in _variants(ctx) if v.get("id") == id), {})
        task_id = (variant.get("automation") or {}).get("taskId")
        if task_id:
            task = next((t for t in campaigns._root(ctx.state)["recurringTasks"] if t.get("id") == task_id), None)
            if task:
                campaign = {"automationId": task_id, "name": task.get("name"), "campaignId": task.get("campaignId")}
        summary = {k: data[k] for k in ("draftId", "platform", "language", "account", "revision", "characters", "limit", "overLimit", "unknowns", "warnings", "needsReview", "scheduled", "setAside")}
        return contracts.result({"kind": "draft", "summary": summary, "stillNeeded": still, "platform": data["platform"], "account": data["account"], "campaign": campaign}, now=ctx.now)
    if type == "automation":
        from .tools import automation_get
        data = automation_get(ctx, id)["data"]
        still = [n.get("text") for n in data.get("needs") or [] if isinstance(n, dict)]
        return contracts.result({"kind": "automation", "summary": data, "stillNeeded": still, "platform": ", ".join(p.get("platform") for p in data.get("platforms") or [] if isinstance(p, dict))}, now=ctx.now)
    if type == "source":
        source = next((s for s in ctx.state.get("sources", []) if isinstance(s, dict) and s.get("id") == id), None)
        if source is None:
            raise AlphaError("That source is not in this workspace.", 404, code="not_found")
        approved = sum(1 for f in source.get("facts") or [] if isinstance(f, dict) and f.get("approved"))
        still = [] if approved else ["Approve at least one paragraph so drafts may use it."]
        return contracts.result({"kind": "source", "summary": {"title": source.get("title"), "policy": source.get("sourcePolicy"), "approvedFacts": approved, "active": source.get("active")},
                                 "stillNeeded": still}, now=ctx.now)
    raise AlphaError("Rafii can't describe that item yet.", 404, code="not_found")
