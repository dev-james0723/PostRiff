"""Social listening → opportunities (adaptive coworker spec §12; architecture lock L1).

Watchlists run only through lawful, available sources: the Research Broker (public web search with the owner's
research consent), and nothing else unless a connector exists. An opportunity carries its evidence, source,
freshness, relevance, novelty, confidence, expiry and one proposed action; notification requires deterministic
thresholds (high confidence, fresh, not a repeat) and never manufactures urgency. Coverage is only what the
connected sources show, and the view says so.
"""
from __future__ import annotations

import hashlib
import re
import time

from postriff_alpha.domain import AlphaError

MAX_WATCHLISTS = 10
MAX_OPPORTUNITIES = 50
FRESH_DAYS = 7
EXPIRY_DAYS = 10


def root(state):
    coworker = state.setdefault("coworker", {})
    listening = coworker.setdefault("listening", {})
    listening.setdefault("watchlists", [])
    listening.setdefault("opportunities", [])
    return listening


def _view(state):
    return ((state.get("coworker") or {}).get("listening") or {"watchlists": [], "opportunities": []})


def save_watchlist(state, payload, actor, now, watchlist_id=None):
    listening = root(state)
    query = " ".join(str(payload.get("query") or "").split())[:200]
    goal = " ".join(str(payload.get("goal") or "").split())[:200]
    if len(query) < 3:
        raise AlphaError("Say what to watch (a topic, product or question).", 400)
    if watchlist_id:
        item = next((w for w in listening["watchlists"] if w["id"] == watchlist_id), None)
        if item is None:
            raise AlphaError("Watchlist unavailable.", 404)
        item.update({"query": query, "goal": goal, "active": payload.get("active", True) is not False, "updatedAt": now})
        return item
    if len(listening["watchlists"]) >= MAX_WATCHLISTS:
        raise AlphaError(f"A workspace follows at most {MAX_WATCHLISTS} watchlists.", 409)
    item = {"id": "wl_" + hashlib.sha256(f"{query}:{now}".encode()).hexdigest()[:10], "query": query, "goal": goal, "sources": ["public_web"], "active": True,
            "createdBy": actor, "createdAt": now, "updatedAt": now, "lastRunAt": None}
    listening["watchlists"].append(item)
    return item


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower())} | set(re.findall(r"[一-鿿]{2}", text or ""))


def score(item, watchlist, state, now):
    """Relevance to the watchlist and the workspace's goals, novelty against recent drafts, freshness from the
    source's own publication time. All deterministic."""
    text = f"{item.get('title', '')} {item.get('snippet', '')}"
    goal_words = _tokens(watchlist.get("goal") or "") | _tokens(watchlist["query"]) | _tokens((state.get("brandHub") or {}).get("subject") or "")
    overlap = len(_tokens(text) & goal_words)
    relevance = min(1.0, overlap / max(3, len(_tokens(watchlist["query"]))))
    recent = " ".join(v.get("text") or "" for v in (state.get("variants") or [])[-30:])
    novelty = 1.0 - min(1.0, len(_tokens(text) & _tokens(recent)) / max(1, len(_tokens(text))))
    age = (item.get("provenance") or {}).get("freshnessDays")
    freshness = 1.0 if age is None else max(0.0, 1.0 - age / FRESH_DAYS)
    value = round(0.5 * relevance + 0.3 * novelty + 0.2 * freshness, 3)
    confidence = "high" if value >= 0.7 and age is not None and age <= 3 else "moderate" if value >= 0.5 else "low"
    return {"relevance": round(relevance, 3), "novelty": round(novelty, 3), "freshness": round(freshness, 3), "score": value, "confidence": confidence, "ageDays": age}


def ingest(state, watchlist, items, now):
    """Add scored opportunities (deduplicated by URL), expire old ones. Returns the new high-confidence ones."""
    listening = root(state)
    known = {o["url"] for o in listening["opportunities"]}
    fresh = []
    for item in items:
        if not item.get("url") or item["url"] in known:
            continue
        scored = score(item, watchlist, state, now)
        # Relevance is required: something fresh and new but unrelated to the watchlist is not an opportunity.
        if scored["relevance"] < 0.2 or scored["score"] < 0.35:
            continue
        opportunity = {"id": "op_" + hashlib.sha256(item["url"].encode()).hexdigest()[:12], "watchlistId": watchlist["id"], "title": (item.get("title") or "")[:200],
                       "url": item["url"], "evidence": [{"url": item["url"], "provenance": item.get("provenance"), "snippet": (item.get("snippet") or "")[:300]}],
                       **scored, "status": "open", "createdAt": now, "expiresAt": now + EXPIRY_DAYS * 86400,
                       "why": f"Matches “{watchlist['query']}”" + (f" and your goal “{watchlist['goal']}”" if watchlist.get("goal") else "") + ".",
                       "proposedAction": "Draft a post that responds to it" if scored["confidence"] != "low" else "Keep an eye on it",
                       "note": "A search result is a lead; read the source before relying on it."}
        listening["opportunities"].append(opportunity)
        known.add(item["url"])
        if scored["confidence"] == "high":
            fresh.append(opportunity)
    for opportunity in listening["opportunities"]:
        if opportunity["status"] == "open" and opportunity["expiresAt"] < now:
            opportunity["status"] = "expired"
    listening["opportunities"] = sorted(listening["opportunities"], key=lambda o: (o["status"] != "open", -o["score"]))[:MAX_OPPORTUNITIES]
    watchlist["lastRunAt"] = now
    return fresh


def decide(state, opportunity_id, decision, actor, now):
    if decision not in ("act", "dismiss"):
        raise AlphaError("Choose act or dismiss.", 400)
    opportunity = next((o for o in root(state)["opportunities"] if o["id"] == opportunity_id), None)
    if opportunity is None:
        raise AlphaError("Opportunity unavailable.", 404)
    opportunity.update({"status": "acted" if decision == "act" else "dismissed", "decidedBy": actor, "decidedAt": now})
    return opportunity


def view(state, now):
    listening = _view(state)
    return {"watchlists": listening["watchlists"], "opportunities": [o for o in listening["opportunities"] if o["status"] in ("open", "acted", "dismissed")],
            "coverage": "Public web search results through the Research Broker, with the owner's research consent. Social platforms are covered only through a connected, permitted integration.",
            "now": now}


def cron(service, max_workspaces=20, max_seconds=30):
    """Run due watchlists (once a day each) for workspaces whose owner allowed web research."""
    from .. import research
    from .research_broker import ResearchBroker
    started, out = time.monotonic(), []
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("""SELECT id::text FROM public.pr_workspaces WHERE jsonb_array_length(coalesce(state->'coworker'->'listening'->'watchlists','[]'::jsonb)) > 0
                       AND NOT state ? 'accountDeletion' LIMIT %s""", (max_workspaces,))
        workspaces = [r[0] for r in cur.fetchall()]
    for workspace_id in workspaces:
        if time.monotonic() - started > max_seconds:
            break
        with service.hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT state, revision FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED", (workspace_id,))
            row = cur.fetchone()
            if row is None:
                continue
            state, revision = row
            if not research.allowed(state):
                out.append({"workspaceId": workspace_id, "skipped": "research_not_allowed"})
                continue
            now = service.clock()
            broker = ResearchBroker(state=state)
            new_high = []
            for watchlist in root(state)["watchlists"]:
                if not watchlist.get("active") or (watchlist.get("lastRunAt") or 0) > now - 86400:
                    continue
                outcome = broker.search_items(watchlist["query"], {"limit": 6})
                if outcome["status"] != "ok":
                    watchlist["lastError"] = "; ".join(e["error"] for e in outcome["errors"])[:200]
                    watchlist["lastRunAt"] = now
                    continue
                new_high += ingest(state, watchlist, outcome["items"], now)
            import json as _json
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s AND revision=%s", (_json.dumps(state), workspace_id, revision))
            if cur.rowcount == 1:
                notifications = getattr(service.hosted, "notifications", None)
                for opportunity in new_high[:3]:
                    if notifications is not None:
                        notifications.emit(cur, workspace_id=workspace_id, event_type="opportunity.detected", dedupe_key=f"opportunity:{opportunity['id']}",
                                           entity_type="opportunity", entity_id=opportunity["id"],
                                           payload={"title": opportunity["title"][:120], "why": opportunity["why"][:160], "confidence": opportunity["confidence"], "href": "/app/weekly?tab=opportunities"})
                db.commit()
                out.append({"workspaceId": workspace_id, "new": len(new_high)})
            else:
                db.rollback()
                out.append({"workspaceId": workspace_id, "skipped": "revision_changed"})
    return {"workspaces": out}
