"""Bounded fact-expiry sweep (growth_v2_routes.CRON): when a claim behind a linked draft passes its review-by day, or a
watched source is withdrawn, deleted or re-approved, the draft gets Queue's blockers within a cron minute — not only
at the next series edit. It reads and writes only workspaces with such a series (row-locked, SKIP LOCKED), changes
nothing else, and reports counts. It runs whether or not RAFII_SERIES_ENABLED is on: turning the flag off stops new
series work (D-012), never the protection of drafts already linked to a series. It starts no work of its own (no
model, no draft, no notification). Never raises (growth_v2_routes isolates failures)."""
from __future__ import annotations

import json
import time

from . import model as m

MAX_WORKSPACES = 10
_DUE = """
SELECT w.id::text, w.state FROM public.pr_workspaces w
WHERE NOT w.state ? 'accountDeletion'
  AND coalesce(w.state#>'{raffi,campaignPlanning,campaigns}','[]'::jsonb) @> '[{"kind":"series"}]'::jsonb
  AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(w.state#>'{raffi,campaignPlanning,campaigns}') c
    WHERE c->>'kind' = 'series' AND (
      (c#>>'{series,nextGateAt}')::double precision <= %s
      OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(coalesce(c#>'{series,watch}','[]'::jsonb)) wv
        WHERE NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(coalesce(w.state->'sources','[]'::jsonb)) s
          WHERE s->>'id' = wv->>'id' AND s->>'active' = 'true' AND coalesce(s->>'reviewedAt','') = coalesce(wv->>'reviewedAt','')))))
ORDER BY w.id LIMIT %s FOR UPDATE SKIP LOCKED
"""


def _due(campaign, state, now):
    series = campaign["series"]
    if (series.get("nextGateAt") or float("inf")) <= now:
        return True
    sources = {s.get("id"): s for s in state.get("sources") or [] if isinstance(s, dict)}
    return any(not (sources.get(item.get("id")) or {}).get("active") or (sources.get(item.get("id")) or {}).get("reviewedAt") != item.get("reviewedAt")
               for item in series.get("watch") or [])


def tick(hosted, deadline):
    from ..hosted import audit
    from ..planning_store import sync
    clock = getattr(hosted, "clock", None) or time.time
    now, workspaces, refreshed_total, gated = clock(), 0, 0, 0
    engine = getattr(getattr(hosted, "commands", None), "engine", None)
    with hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute(_DUE, (now, MAX_WORKSPACES))
        for workspace_id, raw in cur.fetchall():
            if time.monotonic() >= deadline:
                break
            state = raw if isinstance(raw, dict) else json.loads(raw)
            refreshed, drafts = 0, 0
            for campaign in m.all_series(state):
                if _due(campaign, state, now):
                    drafts += m.refresh(state, campaign, now)   # also moves nextGateAt/watch on, so it is not picked again
                    refreshed += 1
            if not refreshed:
                continue
            if drafts and engine is not None and isinstance(state.get("phase2"), dict) and "reviews" in state["phase2"]:
                engine.invalidate(state)   # an approved post of a gated draft is held, as after any command
            cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            sync(cur, workspace_id, {}, state, None)
            audit(cur, workspace_id, None, "series.fact_review_swept", "", {"series": refreshed, "gatedDrafts": drafts})
            workspaces += 1
            refreshed_total += refreshed
            gated += drafts
    return {"status": "ok", "workspaces": workspaces, "series": refreshed_total, "gatedDrafts": gated}
