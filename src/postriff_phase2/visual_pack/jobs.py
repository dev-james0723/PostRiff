"""Bounded background step for Visual Packs: deletion propagation (PRD R-NFR-02).

A rendered slide embeds the pixels of the Library image it used. When that image is deleted, every render that embeds
it is removed from private storage and its revision marked `purged` (rows, manifests and facts stay as the record).
Reading a pack does the same for that pack; this step covers packs nobody opens. It runs whether or not the feature
flag is on (removing derivatives is not new work), is bounded by `deadline` and a per-tick budget, and never raises.
Register `postriff_phase2.visual_pack.jobs` in `growth_v2_routes.CRON` to run it from the existing cron worker.
"""
from __future__ import annotations

import json
import time

WORKSPACES_PER_TICK = 10


def tick(hosted, deadline) -> dict:
    storage = getattr(getattr(hosted, "assets", None), "storage", None)
    if storage is None:
        return {"status": "skipped", "reason": "storage_unconfigured"}
    purged = workspaces = 0
    with hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pr_visual_pack_revisions') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {"status": "skipped", "reason": "not_migrated"}
        # Only workspaces where a rendered revision names an image that is no longer a live Library image, so a
        # workspace whose renders are all current is never re-read and can't starve the others.
        cur.execute("SELECT DISTINCT r.workspace_id::text FROM public.pr_visual_pack_revisions r JOIN public.pr_workspaces w ON w.id=r.workspace_id "
                    "WHERE r.render_manifest IS NOT NULL AND r.purged_at IS NULL AND EXISTS ("
                    " SELECT 1 FROM jsonb_array_elements_text(r.render_manifest->'lineage'->'imageAssetIds') image(id) WHERE NOT EXISTS ("
                    "  SELECT 1 FROM jsonb_array_elements(coalesce(w.state->'phase2'->'assets','[]'::jsonb)) a WHERE a->>'id'=image.id"
                    "  AND coalesce(a->>'deleted','false')='false' AND coalesce(a->>'deletionPending','false')='false'"
                    "  AND a->>'processing'='decoded' AND coalesce(nullif(a->>'mime',''),'image/') LIKE 'image/%%')) LIMIT %s", (WORKSPACES_PER_TICK,))
        candidates = [row[0] for row in cur.fetchall()]
    failed = 0
    for workspace_id in candidates:
        if time.monotonic() >= deadline:
            break
        try:
            purged += _sweep(hosted, storage, workspace_id)
            workspaces += 1
        except Exception:  # noqa: BLE001 - one workspace's storage error must not stop the others; it is retried next tick
            failed += 1
    return {"status": "ok", "workspaces": workspaces, "purged": purged, **({"failed": failed} if failed else {})}


def _sweep(hosted, storage, workspace_id) -> int:
    from .service import VisualPackService
    with hosted.connection_factory() as db, db.cursor() as cur:
        cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
        row = cur.fetchone()
        state = (json.loads(row[0]) if isinstance(row[0], str) else row[0]) if row else {}
        stale = VisualPackService._stale_renders(cur, workspace_id, state)
    for item in stale:
        for name in item["objects"]:   # files first: a revision is marked purged only once its files are gone
            storage.delete(workspace_id, "visual-pack", name)
        with hosted.connection_factory() as db, db.cursor() as cur:
            cur.execute("UPDATE public.pr_visual_pack_revisions SET purged_at=now(),purge_reason='source_image_deleted' "
                        "WHERE workspace_id=%s AND pack_id=%s AND revision_no=%s AND purged_at IS NULL", (workspace_id, item["packId"], item["revision"]))
            VisualPackService._fact(cur, workspace_id, item["packId"], item["revision"], "purged", None,
                                    {"reason": "source_image_deleted", "files": len(item["objects"])})
    return len(stale)
