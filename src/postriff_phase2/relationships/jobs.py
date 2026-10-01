"""Background step for follow-ups (``growth_v2_routes.CRON``): a bounded scan for reminders that became due since the
last tick, emitted through the existing notification outbox so they reach people on time instead of at the hourly
detector rescan. Recipients, quiet hours, time zones, digests and preferences all come from the existing planner; the
event's dedupe key is the reminder identity, so the detector and this step never notify twice. Reminders never contact
the lead. Flag-gated, bounded by rows and the cron deadline, and it never raises.
"""
from __future__ import annotations

import time

from . import service as relationships

BATCH = 50


def tick(hosted, deadline):
    try:
        if not relationships.enabled():
            return {"status": "disabled"}
        notifications = getattr(hosted, "notifications", None)
        if notifications is None or not notifications.enabled():
            return {"status": "ok", "emitted": 0, "notifications": "disabled"}
        clock = getattr(hosted, "clock", None) or time.time
        now = clock()
        scanned = emitted = 0
        with hosted.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute(f"SELECT r.workspace_id::text,r.id::text,{relationships.REMINDER_TOKEN_SQL},"
                        "(SELECT rt.thread_id::text FROM public.pr_relationship_threads rt JOIN public.pr_audience_threads t ON t.workspace_id=rt.workspace_id AND t.id=rt.thread_id "
                        " WHERE rt.workspace_id=r.workspace_id AND rt.relationship_id=r.id ORDER BY coalesce(t.created_at_provider,t.ingested_at) DESC,t.id DESC LIMIT 1) "
                        "FROM public.pr_relationships r JOIN public.pr_workspaces w ON w.id=r.workspace_id "
                        f"WHERE {relationships.DUE_NOW_SQL} AND r.notified_key IS DISTINCT FROM {relationships.REMINDER_TOKEN_SQL} "
                        "AND NOT w.state ? 'accountDeletion' AND (w.state->'workspace'->'sample') IS DISTINCT FROM 'true'::jsonb "
                        "ORDER BY r.due_at,r.id FOR UPDATE OF r SKIP LOCKED LIMIT %s", (now, now, BATCH))
            rows = cur.fetchall()
            for workspace_id, relationship_id, token, thread_id in rows:
                if time.monotonic() >= deadline:
                    break
                scanned += 1
                event = relationships.followup_event({"id": relationship_id, "threadId": thread_id,
                                                      "dedupeKey": relationships.dedupe_key(relationship_id, token)})
                cur.execute("SAVEPOINT relationship_reminder")
                try:
                    result = notifications.emit(cur, workspace_id=workspace_id, **event)
                    cur.execute("UPDATE public.pr_relationships SET notified_key=%s WHERE workspace_id=%s AND id=%s", (token, workspace_id, relationship_id))
                    cur.execute("RELEASE SAVEPOINT relationship_reminder")
                    emitted += 1 if result.get("created") else 0
                except Exception:  # noqa: BLE001 - one reminder failing never stops the others; it is retried next tick
                    cur.execute("ROLLBACK TO SAVEPOINT relationship_reminder")
            db.commit()
        return {"status": "ok", "scanned": scanned, "emitted": emitted}
    except Exception as error:  # noqa: BLE001 - a background step must never fail the cron response
        return {"status": "unavailable", "reason": type(error).__name__}
