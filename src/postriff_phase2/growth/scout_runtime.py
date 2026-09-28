"""Listening's opt-in Scout runner: claim → commit → HTTP → fenced completion.

The claim reserves work units before egress and serializes workspace runs.
No row lock spans provider/model/media calls. Expired claims cannot complete.
"""
from __future__ import annotations

import copy
import json
import time
import uuid

from ..coworker import flags, listening
from .. import research
from . import scout, scout_outcomes
from .jev import JevService
from .router import AIModelRouter
from .usage import MemoryUsageSink, PostgresUsageSink
from .scout_evidence import enrich


def fingerprint(state, watchlist):
    return scout.key("fence_", watchlist, state.get("brandHub"), (state.get("phase2") or {}).get("channels"),
                     (state.get("variants") or [])[-30:])


def reserve(state, now, token):
    scout.prune_media(state, now)
    root = listening.root(state)
    lease = root.get("scoutLease") or {}
    if state.get("accountDeletion") or not research.allowed(state) or lease.get("until", 0) > now:
        return None
    due = next((w for w in root["watchlists"] if listening._due(w, now) and w.get("primaryObjective") in scout.OBJECTIVES), None)
    if due is None:
        return None
    day = int(now // scout.DAY)
    budget = root.setdefault("scoutBudget", {})
    if budget.get("day") != day:
        budget.clear()
        budget.update(day=day, retrieval=0, judgments=0)
    # Failure/abandoned runs remain charged to the work cap; never retry unbounded.
    if budget["retrieval"] >= 10 or budget["judgments"] + 8 > 32:
        return None
    budget["retrieval"] += 1
    budget["judgments"] += 8
    media_budget = root.setdefault("mediaBudget", {})
    if media_budget.get("day") != day:
        media_budget.clear()
        media_budget.update(day=day, used={})
    # Reserve worst-case per-stage units before HTTP. Abandoned leases do not refund.
    media_reserved = flags.enabled("RAFII_MULTIMODAL_ENRICHMENT_ENABLED") and all(media_budget["used"].get(k, 0) <= 2 for k in ("acquisition", "frames", "transcription", "multimodal"))
    if media_reserved:
        for stage in ("acquisition", "frames", "transcription", "multimodal"):
            media_budget["used"][stage] = media_budget["used"].get(stage, 0) + 2
    root["scoutLease"] = {"token": token, "until": now + 90, "watchlistId": due["id"], "fingerprint": fingerprint(state, due), "mediaReserved": media_reserved}
    return copy.deepcopy(due)


def complete(state, token, prepared, now):
    root = listening.root(state)
    lease = root.get("scoutLease") or {}
    if lease.get("token") != token or lease.get("until", 0) <= now or state.get("accountDeletion") or not research.allowed(state):
        return None
    watchlist = next((w for w in root["watchlists"] if w["id"] == lease["watchlistId"]), None)
    if watchlist is None or not listening._due(watchlist, now) or fingerprint(state, watchlist) != lease["fingerprint"]:
        root.pop("scoutLease", None)
        return None
    new = scout.store(state, watchlist, prepared, now) if prepared.get("status", "ok") == "ok" else []
    watchlist["lastRunAt"] = now
    if "mediaCache" in prepared:
        root["mediaCache"] = prepared["mediaCache"]
    scout.prune_media(state, now)
    root.pop("scoutLease", None)
    root["scoutReceipt"] = {"at": now, "status": prepared.get("status", "ok"), "reason": prepared.get("reason"),
                            "judgments": prepared.get("judgments", 0), "signals": len(prepared["signals"]), "costSource": "see_model_usage_ledger"}
    return new


def run_workspace(service, workspace_id, deadline, *, broker=None, judge=None):
    from .trends.config import workspace_allowed
    if workspace_allowed(workspace_id, getattr(service, "values", None)):
        # The canonical durable trend worker owns collection for migrated workspaces.
        # Legacy search/Scout must not create a second collection/model loop.
        return {"workspaceId": workspace_id, "status": "stored_trend_mode", "reason": "durable_trend_worker"}
    now = service.clock()
    # Search timeout includes its existing retry; JEV max 8 x 2s + bounded completion.
    if deadline - time.monotonic() < research.TOTAL_BUDGET_SECONDS + 20:
        return {"workspaceId": workspace_id, "status": "deferred", "reason": "deadline"}
    token = uuid.uuid4().hex
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '1s'")
        cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        row = cur.fetchone()
        state = row[0] if row else {}
        watchlist = reserve(state, now, token) if row else None
        if watchlist is None:
            return {"workspaceId": workspace_id, "status": "not_due_or_budgeted"}
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
        db.commit()
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("""SELECT id::text,statement,cohort,evidence_ids,counter_evidence_ids,extract(epoch from expires_at)
                       FROM public.pr_strategy_hypotheses WHERE workspace_id=%s AND status='supported' AND causal=false
                         AND left(dimension,6)='scout_' AND experiment->'planningAccepted'='true'::jsonb AND expires_at>to_timestamp(%s) LIMIT 20""", (workspace_id, now))
        state["_scoutPlanningPreferences"] = [{"id": r[0], "statement": r[1], "cohort": r[2], "evidenceIds": r[3], "counterEvidenceIds": r[4], "expiresAt": float(r[5])} for r in cur.fetchall()]
    sink = MemoryUsageSink()
    if judge is None and flags.enabled("RAFII_JEV_SCOUT_ENABLED") and service.values.get("AI_GATEWAY_API_KEY"):
        judge = scout.ScoutJudge(AIModelRouter(jev=JevService(service.values["AI_GATEWAY_API_KEY"]), usage=sink))
    try:
        outcome = (broker or service._broker(state)).search_items(watchlist["query"], {"limit": 6})
        if outcome["status"] != "ok":
            raise RuntimeError("retrieval_unavailable")
        root = listening.root(state)
        media_cache = [e for e in root.get("mediaCache", []) if e["expiresAt"] > now]
        media_ledger = {"day": int(now // scout.DAY), "used": {}}
        adapter = getattr(service.hosted, "scout_media_adapter", None)
        if adapter and adapter.capabilities().get("localOnly") and (research.hosted() or not flags.enabled("RAFII_WATCH_IT_LOCAL_ADAPTER_ENABLED")):
            adapter = None
        def enrich_one(signal):
            return enrich(signal, workspace_id=workspace_id, adapter=adapter, ledger=media_ledger, cache=media_cache,
                          now=now, deadline=min(deadline - 2, time.monotonic() + 5), relevant=True, useful=True,
                          enabled=bool(root["scoutLease"].get("mediaReserved")))
        remaining = deadline - time.monotonic() - 12  # reserve media passes and DB completion
        call_cap = min(8, max(0, int(remaining // 2)))
        prepared = scout.prepare(state, watchlist, outcome["items"], workspace_id, now, judge=judge, max_judgments=call_cap, enrich=enrich_one)
        prepared["mediaCache"] = media_cache
    except Exception as error:
        prepared = {"signals": [], "trends": [], "opportunities": [], "judgments": len(sink.events), "status": "unavailable", "reason": type(error).__name__}
    with service.hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '1s'")
        cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
        row = cur.fetchone()
        if row is None or row[0].get("accountDeletion"):
            return {"workspaceId": workspace_id, "status": "deleted"}
        state = row[0]
        ledger = PostgresUsageSink(cur)
        for event in sink.events:
            ledger.record(event)
        new = complete(state, token, prepared, service.clock())
        if new is None:
            db.commit()  # record actual attempts even if content completion lost its fence
            return {"workspaceId": workspace_id, "status": "superseded"}
        scout_outcomes.refresh(cur, workspace_id, state, service.clock())
        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
        notifications = getattr(service.hosted, "notifications", None)
        if notifications:
            for op in new:
                notifications.emit(cur, workspace_id=workspace_id, event_type="opportunity.detected", dedupe_key=f"opportunity:{op['id']}",
                                   entity_type="opportunity", entity_id=op["id"], payload={"title": op["title"][:120], "why": op["why"][:160], "confidence": op["confidence"], "href": "/app/weekly?tab=opportunities"})
        db.commit()
    return {"workspaceId": workspace_id, "status": prepared.get("status", "ok"), "new": len(new)}
