"""Notification delivery worker (architecture lock N4).

Claim → commit → send → complete. A claim is `FOR UPDATE SKIP LOCKED` on due rows, sets a lease and counts the
attempt, and commits **before** any network call; completion is fenced on (id, lease owner) so a worker whose lease
expired cannot overwrite a newer outcome. A crash after the claim leaves the row claimed with an expired lease; the
next tick re-claims it and resends with the **same** idempotency key (Resend deduplicates it; push uses a Topic so
a repeat replaces the earlier notice on the device).

Outcomes: sent (provider accepted) → delivered (provider webhook) for email; sent for push. Transient failures and
lost responses retry with bounded exponential backoff (60 s · 2^attempt, at most 6 h, with deterministic jitter)
up to the channel's max attempts, then `dead`. Permanent failures are `failed`; an unconfigured transport is
`suppressed` with that reason (never "sent"); a person who left the workspace is `cancelled`. None of this touches
domain state.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from . import catalog, email_render, planner, push as push_module, store

LEASE_SECONDS = 120
MAX_BACKOFF = 6 * 3600


def backoff(delivery_id, attempts):
    jitter = int(hashlib.sha256(str(delivery_id).encode()).hexdigest()[:4], 16) % 30
    return min(60 * (2 ** max(0, attempts - 1)), MAX_BACKOFF) + jitter


class DeliveryWorker:
    def __init__(self, connection_factory, *, email_transport=None, from_address=None, push_transport=None, vault=None, base_url="https://rafii.invalid",
                 address_for=None, signing_key=None, clock=time.time, worker_id=None):
        self.connection_factory = connection_factory
        self.email_transport, self.from_address = email_transport, from_address
        self.push_transport, self.vault = push_transport, vault
        self.base_url, self.address_for, self.signing_key = base_url, address_for, signing_key
        self.clock = clock
        self.worker_id = worker_id or f"ntf-{uuid.uuid4().hex[:12]}"

    # --- claim / complete ----------------------------------------------------------------------------------------------
    def claim(self, limit=25, channel=None, mode="immediate"):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute(f"""UPDATE public.pr_notification_deliveries d SET status='claimed', lease_owner=%s, lease_until=now() + make_interval(secs => %s),
                                   attempts=attempts+1, updated_at=now()
                            WHERE d.id IN (SELECT id FROM public.pr_notification_deliveries
                                           WHERE channel IN ('email','push') AND mode=%s {"AND channel=%s" if channel else ""}
                                             AND ((status='pending' AND next_attempt_at <= now()) OR (status='claimed' AND lease_until < now()))
                                           ORDER BY next_attempt_at LIMIT %s FOR UPDATE SKIP LOCKED)
                            RETURNING d.id::text, d.event_id::text, d.workspace_id::text, d.user_id::text, d.channel, d.attempts, d.max_attempts, d.idempotency_key,
                                      extract(epoch from d.created_at)""",
                        [self.worker_id, LEASE_SECONDS, mode] + ([channel] if channel else []) + [limit])
            rows = cur.fetchall()
            db.commit()
        return [{"id": r[0], "eventId": r[1], "workspaceId": r[2], "userId": r[3], "channel": r[4], "attempts": r[5], "maxAttempts": r[6], "key": r[7],
                 "createdAt": float(r[8]) if r[8] is not None else None} for r in rows]

    def complete(self, row, outcome):
        """Fenced on the lease. Returns True when this worker's outcome was recorded."""
        state = outcome["state"]
        with self.connection_factory() as db, db.cursor() as cur:
            if state == "sent":
                sql, params = ("UPDATE public.pr_notification_deliveries SET status='sent', sent_at=now(), provider=%s, provider_ref=%s, template_version=%s, "
                               "lease_owner=NULL, lease_until=NULL, failure_class=NULL, failure_detail=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s AND status='claimed'",
                               (outcome.get("provider"), (outcome.get("providerRef") or "")[:200] or None, outcome.get("templateVersion"), row["id"], self.worker_id))
            elif state in ("transient", "uncertain") and row["attempts"] < row["maxAttempts"]:
                delay = outcome.get("retryAfter") or backoff(row["id"], row["attempts"])
                sql, params = ("UPDATE public.pr_notification_deliveries SET status='pending', next_attempt_at=now() + make_interval(secs => %s), failure_class=%s, "
                               "failure_detail=%s, lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s AND status='claimed'",
                               (delay, state, (outcome.get("detail") or "")[:300], row["id"], self.worker_id))
            else:
                final = {"transient": "dead", "uncertain": "dead", "permanent": "failed", "gone": "failed", "config": "suppressed", "membership": "cancelled",
                         "preference": "suppressed", "expired": "cancelled"}.get(state, "failed")
                failure = {"gone": "permanent"}.get(state, state if state in ("transient", "uncertain", "permanent", "config", "membership", "preference", "expired") else "permanent")
                sql, params = ("UPDATE public.pr_notification_deliveries SET status=%s, failure_class=%s, failure_detail=%s, failed_at=CASE WHEN %s IN ('dead','failed') THEN now() END, "
                               "lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s AND status='claimed'",
                               (final, failure, (outcome.get("detail") or "")[:300], final, row["id"], self.worker_id))
            cur.execute(sql, params)
            recorded = cur.rowcount == 1
            db.commit()
        return recorded

    # --- context -------------------------------------------------------------------------------------------------------------
    def _context(self, row, channel="email", mode="immediate"):
        """Re-read what the message needs, and re-check that the person still belongs to the workspace and still wants
        this message on this channel (their preferences may have changed since it was planned)."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT e.event_type, e.payload, e.severity, e.expires_at IS NOT NULL AND e.expires_at < now(), coalesce(p.locale,''),
                                  coalesce(w.state->'workspace'->>'name',''), e.grouping_key
                           FROM public.pr_notification_events e LEFT JOIN public.pr_profiles p ON p.user_id=%s LEFT JOIN public.pr_workspaces w ON w.id=e.workspace_id
                           WHERE e.id::text=%s""", (row["userId"], row["eventId"]))
            event = cur.fetchone()
            member = True
            if row["workspaceId"]:
                cur.execute("SELECT 1 FROM public.pr_memberships WHERE workspace_id=%s AND user_id=%s AND status='active'", (row["workspaceId"], row["userId"]))
                member = cur.fetchone() is not None
            opted_out = None
            if event is not None:
                prefs = planner.effective_preferences(store.preference_rows(cur, row["userId"]), row["workspaceId"], catalog.spec(event[0])["category"])
                opted_out = planner.opted_out(event[0], channel, mode, prefs, self.clock())
        if event is None:
            return None
        return {"type": event[0], "payload": event[1] or {}, "severity": event[2], "expired": bool(event[3]), "locale": event[4] or "en",
                "workspaceName": event[5] or None, "grouping": event[6], "member": member, "optedOut": opted_out}

    def _unsubscribe_url(self, row, category):
        if not self.signing_key:
            return None
        from .webhooks import unsubscribe_token
        # Based on when the delivery was created, not the send time: a retry renders the same body, so the provider's
        # Idempotency-Key sees the same payload (a different body under the same key is refused).
        token = unsubscribe_token(self.signing_key, row["userId"], row["workspaceId"] or "*", category, now=row.get("createdAt") or self.clock())
        return f"{self.base_url.rstrip('/')}/api/notifications/unsubscribe?token={token}"

    def render(self, row, ctx):
        spec = catalog.spec(ctx["type"])
        payload = ctx["payload"]
        values = {**payload, "workspace": ctx["workspaceName"], "recipe": payload.get("recipeName") or "Your automation",
                  "title": payload.get("title") or "", "reason": payload.get("reason") or "", "count": payload.get("count") or 1}
        return email_render.render(spec["template"], locale=ctx["locale"], values=values, base_url=self.base_url, href=payload.get("href"),
                                   workspace_name=ctx["workspaceName"], unsubscribe_url=self._unsubscribe_url(row, spec["category"]),
                                   transactional=catalog.transactional(ctx["type"]), metrics=payload.get("metrics"))

    # --- channels ------------------------------------------------------------------------------------------------------------
    def send_email(self, row, ctx):
        if self.email_transport is None or not self.from_address:
            return {"state": "config", "detail": "email is not configured on this deployment"}
        address = None
        try:
            address = self.address_for(row["userId"]) if self.address_for else None
        except Exception:  # noqa: BLE001 - an identity lookup failure is transient, the address is never logged
            return {"state": "transient", "detail": "the account address could not be looked up"}
        if not address:
            return {"state": "permanent", "detail": "the account has no email address"}
        message = self.render(row, ctx)
        receipt = None
        try:
            receipt = self.email_transport.send({"from": self.from_address, "to": address, "subject": message["subject"], "text": message["text"], "html": message["html"],
                                                 "headers": message["headers"], "idempotencyKey": row["key"],
                                                 "tags": [{"name": "kind", "value": ctx["type"].replace(".", "_")}, {"name": "delivery_id", "value": row["id"]}]})
        except Exception as error:  # noqa: BLE001 - classify without leaking provider text
            # ResendTransport raises 502 for any refused request and http_transport 503 for an unreachable service or
            # a timeout: both are retried (bounded). A 4xx the provider reported explicitly is permanent.
            status = getattr(error, "status", None)
            permanent = isinstance(status, int) and 400 <= status < 500 and status != 429
            return {"state": "permanent" if permanent else "transient", "detail": f"the email service did not accept the message ({status or 'error'})"}
        if not isinstance(receipt, dict) or not receipt.get("id") or receipt.get("delivered") is False:
            return {"state": "config", "detail": "the configured email transport does not deliver (not confirmed)"}
        return {"state": "sent", "provider": "resend", "providerRef": receipt["id"], "templateVersion": message["templateVersion"]}

    def _subscriptions(self, user_id):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT id::text, endpoint_ciphertext, p256dh_ciphertext, auth_ciphertext, key_id FROM public.pr_push_subscriptions WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            rows = cur.fetchall()
        out = []
        for sid, endpoint, p256dh, auth, key_id in rows:
            try:
                out.append({"id": sid, "endpoint": self.vault.decrypt(endpoint, key_id), "p256dh": self.vault.decrypt(p256dh, key_id), "auth": self.vault.decrypt(auth, key_id)})
            except Exception:  # noqa: BLE001 - a key rotation invalidates a subscription; it is revoked, not retried
                self._revoke(sid, "key_rotated")
        return out

    def _revoke(self, subscription_id, reason):
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("UPDATE public.pr_push_subscriptions SET revoked_at=now(), revoked_reason=%s WHERE id::text=%s AND revoked_at IS NULL", (reason, subscription_id))
            db.commit()

    def send_push(self, row, ctx):
        if self.push_transport is None or self.vault is None:
            return {"state": "config", "detail": "web push is not configured on this deployment"}
        subscriptions = self._subscriptions(row["userId"])
        if not subscriptions:
            return {"state": "preference", "detail": "no active push subscription"}
        spec = catalog.spec(ctx["type"])
        message = self.render(row, ctx)
        body = push_module.payload("Rafii", message["subject"], (ctx["payload"] or {}).get("href"), ctx.get("grouping") or ctx["type"], spec["category"])
        results = []
        for subscription in subscriptions:
            result = self.push_transport.send(subscription, body, ttl=86400 if spec["severity"] in ("critical", "security") else 43200,
                                              urgency=push_module.URGENCY.get(spec["severity"], "normal"), topic=(ctx.get("grouping") or row["eventId"])[:32])
            if result["state"] == "gone":
                self._revoke(subscription["id"], "gone")
            elif result["state"] == "sent":
                with self.connection_factory() as db, db.cursor() as cur:
                    cur.execute("UPDATE public.pr_push_subscriptions SET last_success_at=now(), failure_count=0 WHERE id::text=%s", (subscription["id"],))
                    db.commit()
            results.append(result)
        if any(r["state"] == "sent" for r in results):
            return {"state": "sent", "provider": getattr(self.push_transport, "name", "push"), "providerRef": next((r.get("providerRef") for r in results if r.get("providerRef")), None),
                    "templateVersion": message["templateVersion"]}
        for state in ("transient", "uncertain", "config"):
            hit = next((r for r in results if r["state"] == state), None)
            if hit:
                return hit
        return {"state": "permanent", "detail": "every push subscription was gone or rejected"}

    # --- ticks -----------------------------------------------------------------------------------------------------------------
    def tick(self, max_items=50, max_seconds=20):
        started, summary = time.monotonic(), {"claimed": 0, "sent": 0, "retry": 0, "failed": 0, "suppressed": 0, "cancelled": 0, "lostLease": 0}
        while summary["claimed"] < max_items and time.monotonic() - started < max_seconds:
            rows = self.claim(limit=min(25, max_items - summary["claimed"]))
            if not rows:
                break
            for row in rows:
                summary["claimed"] += 1
                ctx = self._context(row, row["channel"], "immediate")
                if ctx is None:
                    outcome = {"state": "permanent", "detail": "event missing"}
                elif not ctx["member"]:
                    outcome = {"state": "membership", "detail": "the person no longer belongs to this workspace"}
                elif ctx["expired"]:
                    outcome = {"state": "expired", "detail": "the event expired before delivery"}
                elif ctx["optedOut"]:
                    outcome = {"state": "preference", "detail": ctx["optedOut"]}
                elif row["channel"] == "email":
                    outcome = self.send_email(row, ctx)
                else:
                    outcome = self.send_push(row, ctx)
                if not self.complete(row, outcome):
                    summary["lostLease"] += 1
                    continue
                key = {"sent": "sent", "transient": "retry", "uncertain": "retry", "config": "suppressed", "preference": "suppressed", "membership": "cancelled",
                       "expired": "cancelled"}.get(outcome["state"], "failed")
                if key == "retry" and row["attempts"] >= row["maxAttempts"]:
                    key = "failed"
                summary[key] += 1
        return summary

    def digest_tick(self, max_people=50):
        """One email per person with everything their digest collected, sent once (idempotency key over the group).
        A group whose lease expired (a crash mid-send) is recovered first and on its own, so it is resent with the same
        key and body; rows the person no longer wants, or that no longer apply, are completed as such, never as sent."""
        sent = 0
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute("""SELECT DISTINCT user_id::text FROM public.pr_notification_deliveries WHERE channel='email' AND mode='digest'
                           AND ((status='pending' AND next_attempt_at <= now()) OR (status='claimed' AND lease_until < now())) LIMIT %s""", (max_people,))
            people = [r[0] for r in cur.fetchall()]
        for user_id in people:
            with self.connection_factory() as db, db.cursor() as cur:
                returning = "RETURNING id::text, event_id::text, workspace_id::text, attempts, max_attempts, extract(epoch from created_at)"
                cur.execute(f"""UPDATE public.pr_notification_deliveries SET lease_owner=%s, lease_until=now() + make_interval(secs => {LEASE_SECONDS}), attempts=attempts+1, updated_at=now()
                                WHERE id IN (SELECT id FROM public.pr_notification_deliveries WHERE user_id=%s AND channel='email' AND mode='digest'
                                             AND status='claimed' AND lease_until < now() FOR UPDATE SKIP LOCKED) {returning}""", (self.worker_id, user_id))
                rows = cur.fetchall()
                if not rows:
                    cur.execute(f"""UPDATE public.pr_notification_deliveries SET status='claimed', lease_owner=%s, lease_until=now() + make_interval(secs => {LEASE_SECONDS}),
                                           attempts=attempts+1, updated_at=now()
                                    WHERE id IN (SELECT id FROM public.pr_notification_deliveries WHERE user_id=%s AND channel='email' AND mode='digest'
                                                 AND status='pending' AND next_attempt_at <= now() FOR UPDATE SKIP LOCKED) {returning}""", (self.worker_id, user_id))
                    rows = cur.fetchall()
                db.commit()
            if not rows:
                continue
            items, included, excluded = [], [], []
            first_ctx = None
            for delivery_id, event_id, workspace_id, attempts, max_attempts, created in rows:
                ctx = self._context({"userId": user_id, "eventId": event_id, "workspaceId": workspace_id}, "email", "digest")
                if ctx is None:
                    excluded.append((delivery_id, "permanent", "failed", "event missing"))
                elif not ctx["member"]:
                    excluded.append((delivery_id, "membership", "cancelled", "the person no longer belongs to this workspace"))
                elif ctx["expired"]:
                    excluded.append((delivery_id, "expired", "cancelled", "the event expired before the digest"))
                elif ctx["optedOut"]:
                    excluded.append((delivery_id, "preference", "suppressed", ctx["optedOut"]))
                else:
                    first_ctx = first_ctx or ctx
                    included.append((delivery_id, attempts, max_attempts, created))
                    title = (ctx["payload"] or {}).get("title") or email_render.catalogue()["locales"][email_render.resolve_locale(ctx["locale"])]["templates"].get(
                        catalog.spec(ctx["type"])["template"], {}).get("headline", ctx["type"])
                    detail = (ctx["payload"] or {}).get("platform") or (ctx["payload"] or {}).get("recipeName") or ctx["workspaceName"] or ""
                    items.append({"title": email_render._fmt(title, {**(ctx["payload"] or {}), "recipe": (ctx["payload"] or {}).get("recipeName") or "", "platform": (ctx["payload"] or {}).get("platform") or ""}),
                                  "detail": detail})
            group_key = "dig_" + hashlib.sha256(",".join(sorted(r[0] for r in included)).encode()).hexdigest()[:40]
            outcome = {"state": "empty", "detail": "nothing left to send"}
            if items and first_ctx:
                base = min((c for *_, c in included if c is not None), default=None)
                message = email_render.render("digest", locale=first_ctx["locale"], values={"count": len(items)}, base_url=self.base_url, href="/app",
                                              workspace_name=None, unsubscribe_url=self._unsubscribe_url({"userId": user_id, "workspaceId": None, "createdAt": base}, "*"), items=items)
                if self.email_transport is None or not self.from_address:
                    outcome = {"state": "config", "detail": "email is not configured on this deployment"}
                else:
                    try:
                        address = self.address_for(user_id) if self.address_for else None
                        receipt = self.email_transport.send({"from": self.from_address, "to": address, "subject": message["subject"], "text": message["text"],
                                                             "html": message["html"], "headers": message["headers"], "idempotencyKey": group_key,
                                                             "tags": [{"name": "kind", "value": "digest"}, {"name": "digest_id", "value": group_key}]}) if address else None
                        outcome = ({"state": "sent", "providerRef": receipt["id"], "templateVersion": message["templateVersion"]}
                                   if isinstance(receipt, dict) and receipt.get("id") and receipt.get("delivered") is not False
                                   else {"state": "config" if address else "permanent", "detail": "not confirmed" if address else "no address"})
                    except Exception:  # noqa: BLE001
                        outcome = {"state": "transient", "detail": "the email service did not accept the digest"}
            digest_id = str(uuid.uuid5(uuid.NAMESPACE_URL, group_key))
            with self.connection_factory() as db, db.cursor() as cur:
                for delivery_id, failure, final, detail in excluded:
                    cur.execute("""UPDATE public.pr_notification_deliveries SET status=%s, failure_class=%s, failure_detail=%s, lease_owner=NULL, lease_until=NULL, updated_at=now()
                                   WHERE id::text=%s AND lease_owner=%s""", (final, failure, detail[:300], delivery_id, self.worker_id))
                for delivery_id, attempts, max_attempts, _created in included:
                    if outcome["state"] == "sent":
                        cur.execute("""UPDATE public.pr_notification_deliveries SET status='sent', sent_at=now(), provider='resend', provider_ref=%s, template_version=%s,
                                       digest_id=%s, lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s""",
                                    (outcome["providerRef"], outcome["templateVersion"], digest_id, delivery_id, self.worker_id))
                    elif outcome["state"] == "transient" and attempts < max_attempts:
                        cur.execute("""UPDATE public.pr_notification_deliveries SET status='pending', next_attempt_at=now() + make_interval(secs => %s), failure_class='transient',
                                       lease_owner=NULL, lease_until=NULL, updated_at=now() WHERE id::text=%s AND lease_owner=%s""", (backoff(delivery_id, attempts), delivery_id, self.worker_id))
                    else:
                        final = "suppressed" if outcome["state"] == "config" else "dead" if outcome["state"] == "transient" else "failed"
                        cur.execute("""UPDATE public.pr_notification_deliveries SET status=%s, failure_class=%s, failure_detail=%s, lease_owner=NULL, lease_until=NULL,
                                       updated_at=now() WHERE id::text=%s AND lease_owner=%s""", (final, outcome["state"], outcome.get("detail"), delivery_id, self.worker_id))
                db.commit()
            sent += 1 if outcome["state"] == "sent" else 0
        return {"people": len(people), "sent": sent}


def backlog(cur):
    """Operational health: pending/claimed backlog, oldest due, dead letters in the last day."""
    cur.execute("""SELECT count(*) FILTER (WHERE status IN ('pending','claimed') AND next_attempt_at <= now()),
                          extract(epoch from now() - min(next_attempt_at) FILTER (WHERE status IN ('pending','claimed') AND next_attempt_at <= now())),
                          count(*) FILTER (WHERE status='dead' AND updated_at > now() - interval '1 day'),
                          count(*) FILTER (WHERE status='claimed' AND lease_until < now())
                   FROM public.pr_notification_deliveries WHERE channel IN ('email','push')""")
    due, oldest, dead, expired = cur.fetchone()
    return {"due": due, "oldestDueSeconds": round(float(oldest), 1) if oldest else 0, "dead24h": dead, "expiredLeases": expired}


def json_safe(value):
    return json.loads(json.dumps(value, default=str))
