"""Durable notification events and deliveries (architecture lock N1, N2, N4).

`emit(cur, …)` runs inside the caller's domain transaction (a transactional outbox): the event row and every
planned delivery commit with the domain change or not at all, and a replay of the same event (same scope and
dedupe key) is a no-op. No network call ever happens here.
"""
from __future__ import annotations

import json
import time
import uuid

from ..permissions import Membership
from . import catalog, planner

PAYLOAD_KEYS = ("title", "detail", "entityTitle", "platform", "account", "count", "href", "reason", "weekOf", "metrics", "planName", "endsAt",
                "device", "location", "amount", "currency", "campaignName", "recipeName", "confidence", "why")
MAX_PAYLOAD_TEXT = 240


def _clean_payload(payload):
    """Only presentation fields, short strings and small numbers: no addresses, bodies, tokens or DMs."""
    out = {}
    for key in PAYLOAD_KEYS:
        value = (payload or {}).get(key)
        if value is None:
            continue
        if isinstance(value, str):
            if "@" in value and "." in value.split("@")[-1] and " " not in value.strip():
                continue  # looks like an address: never stored
            out[key] = value[:MAX_PAYLOAD_TEXT]
        elif isinstance(value, bool) or isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, list) and key == "metrics":
            out[key] = [{"label": str(m.get("label", ""))[:40], "value": str(m.get("value", ""))[:24]} for m in value[:4] if isinstance(m, dict)]
    return out


def members(cur, workspace_id):
    cur.execute("""SELECT m.user_id::text, m.role, m.can_publish, m.can_reply, m.can_moderate, m.can_manage_connections, m.status,
                          coalesce(p.time_zone,''), coalesce(p.locale,'')
                   FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id = m.user_id
                   WHERE m.workspace_id = %s AND m.status = 'active' AND p.deleted_at IS NULL""", (workspace_id,))
    return [{"userId": r[0], "membership": Membership.from_row(r[1], r[2], r[3], r[4], r[5]), "active": r[6] == "active",
             "time_zone": r[7] or None, "locale": r[8] or None} for r in cur.fetchall()]


def person(cur, user_id):
    cur.execute("SELECT coalesce(time_zone,''), coalesce(locale,'') FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL", (user_id,))
    row = cur.fetchone()
    return None if row is None else {"userId": user_id, "membership": Membership("owner"), "active": True, "time_zone": row[0] or None, "locale": row[1] or None}


def preference_rows(cur, user_id):
    cur.execute("""SELECT scope_key, category, in_app, email_mode, push_mode, digest_frequency, quiet_start, quiet_end, time_zone,
                          extract(epoch from muted_until), email_unsubscribed FROM public.pr_notification_preferences WHERE user_id=%s""", (user_id,))
    rows = {}
    for r in cur.fetchall():
        rows[(r[0], r[1])] = {"in_app": r[2], "email_mode": r[3], "push_mode": r[4], "digest_frequency": r[5], "quiet_start": r[6], "quiet_end": r[7],
                              "time_zone": r[8], "muted_until": float(r[9]) if r[9] is not None else None, "email_unsubscribed": r[10]}
    return rows


def push_available(cur, user_id):
    cur.execute("SELECT 1 FROM public.pr_push_subscriptions WHERE user_id=%s AND revoked_at IS NULL LIMIT 1", (user_id,))
    return cur.fetchone() is not None


def recent_counts(cur, user_id, now):
    cur.execute("""SELECT channel, count(*) FROM public.pr_notification_deliveries WHERE user_id=%s AND channel IN ('email','push')
                   AND mode='immediate' AND status IN ('pending','claimed','sent','delivered','read','acted') AND created_at > to_timestamp(%s)
                   GROUP BY channel""", (user_id, now - 3600))
    return {r[0]: r[1] for r in cur.fetchall()}


def emit(cur, *, workspace_id, event_type, dedupe_key, entity_type=None, entity_id=None, payload=None, actor=None, user_id=None,
         grouping_key=None, correlation_id=None, occurred_at=None, expires_at=None, now=None, email_available=True, push_enabled=False, baseline=False):
    """Insert one event and its planned deliveries in the caller's transaction. Returns {eventId, created, deliveries}.
    `user_id` scopes a person-level event (security) that has no workspace. `baseline` records a condition that
    already existed when notifications were first turned on for this scope: the event is kept (so its dedupe key is
    spent) but nobody is notified about the past."""
    spec = catalog.spec(event_type)
    now = now or time.time()
    scope_key = workspace_id or f"user:{user_id}"
    if not workspace_id and not user_id:
        raise ValueError("an event needs a workspace or a person")
    cur.execute("""INSERT INTO public.pr_notification_events(workspace_id,scope_key,event_type,category,entity_type,entity_id,severity,actor,payload,
                          dedupe_key,grouping_key,correlation_id,occurred_at,expires_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,to_timestamp(%s),%s)
                   ON CONFLICT (scope_key, dedupe_key) DO NOTHING RETURNING id::text""",
                (workspace_id, scope_key, event_type, spec["category"], entity_type, (str(entity_id)[:200] if entity_id else None), spec["severity"],
                 actor, json.dumps(_clean_payload(payload)), dedupe_key[:300], grouping_key, correlation_id, occurred_at or now,
                 None if expires_at is None else _ts(expires_at)))
    row = cur.fetchone()
    if row is None:
        return {"eventId": None, "created": False, "deliveries": []}
    event_id = row[0]
    if baseline:
        return {"eventId": event_id, "created": True, "deliveries": [], "baseline": True}
    event = {"event_type": event_type, "workspace_id": workspace_id, "severity": spec["severity"], "actor": actor or user_id}
    recipients = planner.audience(members(cur, workspace_id), event, actor or user_id) if workspace_id else [p for p in [person(cur, user_id)] if p]
    planned = []
    for recipient in recipients:
        rows = planner.plan(event, recipient, preference_rows(cur, recipient["userId"]), now, push_available=push_enabled and push_available(cur, recipient["userId"]),
                            email_available=email_available, recent=recent_counts(cur, recipient["userId"], now))
        for item in rows:
            key = f"ntf_{uuid.uuid5(uuid.NAMESPACE_URL, f'{event_id}:{recipient['userId']}:{item['channel']}').hex}"
            status = item["status"]
            cur.execute("""INSERT INTO public.pr_notification_deliveries(event_id,workspace_id,user_id,channel,mode,status,next_attempt_at,idempotency_key,
                                  max_attempts,failure_class,failure_detail,delivered_at)
                           VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,%s) ON CONFLICT (event_id,user_id,channel) DO NOTHING RETURNING id::text""",
                        (event_id, workspace_id, recipient["userId"], item["channel"], item["mode"], status, item["next_attempt_at"], key,
                         catalog.MAX_ATTEMPTS[item["channel"]], "preference" if status == "suppressed" else None, item.get("reason"),
                         _ts(now) if status == "delivered" else None))
            created = cur.fetchone()
            if created:
                planned.append({"deliveryId": created[0], "userId": recipient["userId"], **item})
    return {"eventId": event_id, "created": True, "deliveries": planned}


def _ts(value):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(float(value), timezone.utc)


# --- notification centre --------------------------------------------------------------------------------------------
def center(cur, user_id, workspace_id=None, limit=50, before=None, unread_only=False):
    """In-app notifications for one person (only rows they own, only workspaces they still belong to)."""
    params = [user_id]
    sql = """SELECT d.id::text, d.status, extract(epoch from d.created_at), e.event_type, e.category, e.severity, e.entity_type, e.entity_id, e.payload,
                    e.workspace_id::text, extract(epoch from d.read_at), extract(epoch from d.acted_at)
             FROM public.pr_notification_deliveries d JOIN public.pr_notification_events e ON e.id = d.event_id
             WHERE d.user_id = %s AND d.channel = 'in_app' AND d.status IN ('delivered','read','acted')
               AND (e.workspace_id IS NULL OR EXISTS (SELECT 1 FROM public.pr_memberships m WHERE m.workspace_id = e.workspace_id AND m.user_id = d.user_id AND m.status='active'))"""
    if workspace_id:
        sql += " AND (e.workspace_id = %s OR e.workspace_id IS NULL)"
        params.append(workspace_id)
    if unread_only:
        sql += " AND d.status = 'delivered'"
    if before:
        sql += " AND d.created_at < to_timestamp(%s)"
        params.append(before)
    sql += " ORDER BY d.created_at DESC LIMIT %s"
    params.append(max(1, min(int(limit), 100)))
    cur.execute(sql, params)
    items = []
    for r in cur.fetchall():
        spec = catalog.EVENTS.get(r[3], {})
        items.append({"id": r[0], "status": r[1], "createdAt": float(r[2]), "type": r[3], "category": r[4], "severity": r[5], "entity": {"type": r[6], "id": r[7]},
                      "payload": r[8] or {}, "workspaceId": r[9], "readAt": float(r[10]) if r[10] else None, "actedAt": float(r[11]) if r[11] else None,
                      "actionable": spec.get("severity") in ("action", "critical", "warning", "security")})
    cur.execute("SELECT count(*) FROM public.pr_notification_deliveries WHERE user_id=%s AND channel='in_app' AND status='delivered'" + (" AND (workspace_id=%s OR workspace_id IS NULL)" if workspace_id else ""),
                [user_id] + ([workspace_id] if workspace_id else []))
    return {"items": items, "unread": cur.fetchone()[0]}


def mark_all_read(cur, user_id, workspace_id):
    """Every unread in-app notification of one person in one workspace (plus account-wide ones) becomes read, in one
    statement, so the bell's count can reach 0 however many arrived. Re-counted so the caller can verify."""
    cur.execute("SELECT id FROM public.pr_notification_deliveries WHERE user_id=%s AND channel='in_app' AND status='delivered' "
                "AND (workspace_id=%s OR workspace_id IS NULL) FOR UPDATE", (user_id, workspace_id))
    ids = [row[0] for row in cur.fetchall()]
    if not ids:
        return {"changed": 0, "unread": 0, "verified": True}
    cur.execute("UPDATE public.pr_notification_deliveries SET status='read', read_at=coalesce(read_at, now()), updated_at=now() "
                "WHERE id = ANY(%s) AND status='delivered'", (ids,))
    changed = max(cur.rowcount or 0, 0)
    # Only the rows this call targeted: one that arrives meanwhile is simply still unread, not a failure.
    cur.execute("SELECT count(*) FROM public.pr_notification_deliveries WHERE id = ANY(%s) AND status='delivered'", (ids,))
    unread = cur.fetchone()[0]
    return {"changed": changed, "unread": unread, "verified": unread == 0}


def mark(cur, user_id, delivery_id, action):
    """read | acted | dismissed on one's own in-app notification. Re-read and returned so the caller can verify."""
    if action not in ("read", "acted", "dismissed"):
        raise ValueError(action)
    extra = {"read": "", "acted": ", acted_at=coalesce(acted_at, now())", "dismissed": ", dismissed_at=coalesce(dismissed_at, now())"}[action]
    cur.execute(f"""UPDATE public.pr_notification_deliveries SET status=%s, read_at=coalesce(read_at, now()){extra}, updated_at=now()
                    WHERE id::text=%s AND user_id=%s AND channel='in_app' AND status IN ('delivered','read','acted') RETURNING id""",
                (action, delivery_id, user_id))
    changed = cur.fetchone() is not None
    cur.execute("SELECT status FROM public.pr_notification_deliveries WHERE id::text=%s AND user_id=%s", (delivery_id, user_id))
    row = cur.fetchone()
    return {"changed": changed, "status": row[0] if row else None, "verified": bool(row and row[0] == action)}
