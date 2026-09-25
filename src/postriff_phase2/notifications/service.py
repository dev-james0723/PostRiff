"""NotificationService: the one entry point feature code and the API use (architecture lock N1-N5, E1-E2).

- `emit(cur, …)` / `scan(cur, workspace_id, state)`: events inside the domain transaction (outbox), never a send;
- `effect(...)`: the `repository.effects` hook (the detector over the state a command just wrote);
- `cron(...)`: detector scan for worker-made changes + security events, then delivery and digest ticks, each
  isolated and bounded so one failing step never stops the others;
- person-facing API: notification centre, read/acted/dismissed, preferences, push subscribe/unsubscribe/list,
  one-click unsubscribe, provider webhook.
Every method is a no-op or `feature_disabled` while RAFII_NOTIFICATIONS_V2_ENABLED is off.
"""
from __future__ import annotations

import json
import logging
import re
import time

from postriff_alpha.domain import AlphaError

from ..coworker import flags
from . import catalog, delivery, detector, push as push_module, store, webhooks

log = logging.getLogger("postriff.notifications")
ZONE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}$")
MODES = {"email_mode": ("immediate", "digest", "off"), "push_mode": ("immediate", "off"), "digest_frequency": ("daily", "weekly", "off")}


RESCAN_SECONDS = 3600          # an unchanged workspace is re-checked hourly (billing, trials, token expiry)
NEW_WORKSPACE_SECONDS = 600    # a workspace created this recently has no past to baseline

class NotificationService:
    def __init__(self, hosted, values=None, *, email_transport=None, push_transport=None, clock=time.time):
        self.hosted, self.values, self.clock = hosted, dict(values or {}), clock
        mailer = getattr(hosted, "mailer", None)
        self.email_transport = email_transport if email_transport is not None else getattr(mailer, "transport", None)
        self.from_address = getattr(mailer, "from_address", None)
        self.base_url = str(getattr(hosted, "public_base_url", None) or self.values.get("POSTRIFF_PUBLIC_BASE_URL") or "https://rafii.invalid").rstrip("/")
        self.vapid = None
        try:
            self.vapid = push_module.vapid_from_environment(self.values)
        except ValueError as error:
            log.warning(json.dumps({"event": "notifications.vapid_invalid", "error": str(error)[:120]}))
        self.push_transport = push_transport if push_transport is not None else (push_module.WebPushTransport(self.vapid) if self.vapid else None)
        self.signing_key = webhooks.signing_key(self.values)

    # --- switches ---------------------------------------------------------------------------------------------------------
    def enabled(self):
        return flags.enabled("RAFII_NOTIFICATIONS_V2_ENABLED")

    def push_enabled(self):
        return self.enabled() and flags.enabled("RAFII_WEB_PUSH_ENABLED") and self.vapid is not None

    def email_available(self):
        return self.email_transport is not None and not type(self.email_transport).__name__.startswith("Null")

    def _require(self, push=False):
        if not self.enabled() or (push and not self.push_enabled()):
            raise AlphaError("This Rafii feature is not turned on for this deployment.", 404, code="feature_disabled")

    # --- events ----------------------------------------------------------------------------------------------------------------
    def emit(self, cur, **event):
        if not self.enabled():
            return {"eventId": None, "created": False, "deliveries": [], "disabled": True}
        return store.emit(cur, **event, now=self.clock(), email_available=self.email_available(), push_enabled=self.push_enabled())

    def scan(self, cur, workspace_id, state, include_database=True, baseline=False):
        """Emit every event the workspace's authoritative state implies (idempotent). With `baseline` (the first scan of
        a workspace that existed before notifications were turned on) the events are recorded without notifying anyone,
        so turning the feature on never mails people about months-old failures."""
        if not self.enabled() or not state or (state.get("workspace") or {}).get("sample"):
            return {"events": 0, "created": 0}
        events = detector.from_state(workspace_id, state, self.clock())
        if include_database:
            events += detector.from_database(cur, workspace_id, self.clock())
        created = 0
        for event in events:
            cur.execute("SAVEPOINT rafii_notification")
            try:
                result = self.emit(cur, workspace_id=workspace_id, **event, **({"baseline": True} if baseline else {}))
                cur.execute("RELEASE SAVEPOINT rafii_notification")
                created += 1 if result.get("created") and not result.get("baseline") else 0
            except Exception as error:  # noqa: BLE001 - a notification problem never fails the domain command
                cur.execute("ROLLBACK TO SAVEPOINT rafii_notification")
                log.warning(json.dumps({"event": "notifications.emit_failed", "type": event.get("event_type"), "error": type(error).__name__}))
        return {"events": len(events), "created": created, "baseline": bool(baseline)}

    def effect(self, cur, workspace_id, before, after, principal):
        """repository.effects hook: runs in the command's transaction, after the state write. Only conditions the
        command just created are emitted here (the diff of the detector over before/after); the cron scan catches up
        on anything else, and dedupe keys make any overlap a no-op."""
        if not self.enabled() or not after or (after.get("workspace") or {}).get("sample"):
            return
        now = self.clock()
        known = {e["dedupe_key"] for e in detector.from_state(workspace_id, before or {}, now)}
        for event in detector.from_state(workspace_id, after, now):
            if event["dedupe_key"] in known:
                continue
            cur.execute("SAVEPOINT rafii_notification")
            try:
                self.emit(cur, workspace_id=workspace_id, **event)
                cur.execute("RELEASE SAVEPOINT rafii_notification")
            except Exception as error:  # noqa: BLE001 - a notification problem never fails the domain command
                cur.execute("ROLLBACK TO SAVEPOINT rafii_notification")
                log.warning(json.dumps({"event": "notifications.emit_failed", "type": event.get("event_type"), "error": type(error).__name__}))

    def cron(self, max_workspaces=200, max_items=50, max_seconds=20):
        """Detector scan for changed workspaces, security events, then delivery and digests. Each step isolated."""
        result = {}
        if not self.enabled():
            return {"status": "disabled"}
        factory = self.hosted.repository.connection_factory
        started = time.monotonic()
        first_run = False
        try:
            scanned = created = baselined = 0
            with factory() as db, db.cursor() as cur:
                cur.execute("SELECT NOT EXISTS (SELECT 1 FROM public.pr_notification_scan)")
                first_run = bool(cur.fetchone()[0])
                # Changed workspaces first; then any not scanned for RESCAN_SECONDS, so billing, trial and token-expiry
                # conditions reach idle workspaces too. A workspace's first scan is a silent baseline unless it is new.
                cur.execute("""SELECT w.id::text, w.revision, (s.workspace_id IS NULL AND w.created_at < now() - make_interval(secs => %s))
                               FROM public.pr_workspaces w LEFT JOIN public.pr_notification_scan s ON s.workspace_id=w.id
                               WHERE (s.revision IS DISTINCT FROM w.revision OR s.scanned_at < now() - make_interval(secs => %s)) AND NOT w.state ? 'accountDeletion'
                               ORDER BY (s.revision IS DISTINCT FROM w.revision) DESC, s.scanned_at ASC NULLS FIRST, w.id LIMIT %s""",
                            (NEW_WORKSPACE_SECONDS, RESCAN_SECONDS, max_workspaces))
                changed = cur.fetchall()
            for workspace_id, revision, baseline in changed:
                if time.monotonic() - started > max_seconds:
                    break
                with factory() as db, db.cursor() as cur:
                    cur.execute("SELECT state, revision FROM public.pr_workspaces WHERE id=%s FOR UPDATE SKIP LOCKED", (workspace_id,))
                    row = cur.fetchone()
                    if row is None:
                        continue
                    outcome = self.scan(cur, workspace_id, row[0], baseline=bool(baseline))
                    cur.execute("""INSERT INTO public.pr_notification_scan(workspace_id,revision,scanned_at) VALUES(%s,%s,now())
                                   ON CONFLICT (workspace_id) DO UPDATE SET revision=excluded.revision, scanned_at=now()""", (workspace_id, row[1]))
                    db.commit()
                scanned += 1
                created += outcome["created"]
                baselined += 1 if outcome.get("baseline") else 0
            result["scan"] = {"workspaces": scanned, "created": created, "baselined": baselined}
        except Exception as error:  # noqa: BLE001
            result["scan"] = {"error": type(error).__name__}
        try:
            with factory() as db, db.cursor() as cur:
                made = 0
                for event in detector.security_events(cur):
                    cur.execute("SAVEPOINT rafii_security")
                    try:
                        # The very first run records the last day's security events as a baseline: those alerts were
                        # already sent by the legacy mailer.
                        made += 1 if self.emit(cur, workspace_id=None, **event, **({"baseline": True} if first_run else {})).get("created") and not first_run else 0
                        cur.execute("RELEASE SAVEPOINT rafii_security")
                    except Exception:  # noqa: BLE001
                        cur.execute("ROLLBACK TO SAVEPOINT rafii_security")
                db.commit()
            result["security"] = {"created": made}
        except Exception as error:  # noqa: BLE001
            result["security"] = {"error": type(error).__name__}
        worker = self.worker()
        try:
            result["delivery"] = worker.tick(max_items=max_items, max_seconds=max_seconds)
        except Exception as error:  # noqa: BLE001
            result["delivery"] = {"error": type(error).__name__}
        try:
            result["digest"] = worker.digest_tick()
        except Exception as error:  # noqa: BLE001
            result["digest"] = {"error": type(error).__name__}
        try:
            with factory() as db, db.cursor() as cur:
                result["backlog"] = delivery.backlog(cur)
        except Exception as error:  # noqa: BLE001
            result["backlog"] = {"error": type(error).__name__}
        return result

    def worker(self):
        return delivery.DeliveryWorker(self.hosted.repository.connection_factory, email_transport=self.email_transport if self.email_available() else None,
                                       from_address=self.from_address, push_transport=self.push_transport if self.push_enabled() else None,
                                       vault=getattr(getattr(self.hosted, "oauth", None), "vault", None), base_url=self.base_url,
                                       address_for=getattr(self.hosted, "_email_for", None), signing_key=self.signing_key, clock=self.clock)

    # --- person-facing API -----------------------------------------------------------------------------------------------------
    def _principal(self, token, workspace_id=None):
        if workspace_id:
            return self.hosted.repository.transaction(token, workspace_id)
        return None

    def center(self, workspace_id, token, before=None, unread_only=False):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            return {**store.center(cur, principal, workspace_id, before=before, unread_only=unread_only), "catalogVersion": catalog.CATALOG_VERSION}

    def mark(self, workspace_id, token, delivery_id, action):
        self._require()
        if action not in ("read", "acted", "dismissed"):
            raise AlphaError("Choose read, acted or dismissed.", 400)
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            result = store.mark(cur, principal, delivery_id, action)
            if not result["status"]:
                raise AlphaError("Notification unavailable.", 404)
            if result["changed"]:
                cur.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) VALUES(%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                            (workspace_id, principal, f"notification.{ 'opened' if action == 'read' else action}", json.dumps({"channel": "in_app", "deliveryId": delivery_id}), f"{action}:{delivery_id}"))
            return result

    def preferences(self, workspace_id, token):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            rows = store.preference_rows(cur, principal)
            cur.execute("SELECT count(*) FROM public.pr_push_subscriptions WHERE user_id=%s AND revoked_at IS NULL", (principal,))
            devices = cur.fetchone()[0]
        effective = {cat: store.planner.effective_preferences(rows, workspace_id, cat) for cat in catalog.CATEGORIES}
        return {"catalog": catalog.public(), "rows": [{"scope": k[0], "category": k[1], **v} for k, v in rows.items()], "effective": effective,
                "push": {"available": self.push_enabled(), "vapidPublicKey": self.vapid.public_key if self.push_enabled() else None, "devices": devices},
                "email": {"available": self.email_available()}}

    def set_preference(self, workspace_id, token, payload):
        """Upsert one preference row for the caller only. Scope: 'workspace' (this workspace) or 'all' (the person's
        defaults). Transactional categories (security, billing) keep their email regardless."""
        self._require()
        scope = payload.get("scope", "workspace")
        category = payload.get("category", "*")
        if scope not in ("workspace", "all") or (category != "*" and category not in catalog.CATEGORIES):
            raise AlphaError("Choose a scope (workspace or all) and a known category.", 400)
        fields = {}
        for key, allowed in MODES.items():
            if key in payload:
                if payload[key] is not None and payload[key] not in allowed:
                    raise AlphaError(f"{key} must be one of {', '.join(allowed)}.", 400)
                fields[key] = payload[key]
        if "in_app" in payload:
            if not isinstance(payload["in_app"], bool):
                raise AlphaError("in_app must be true or false.", 400)
            fields["in_app"] = payload["in_app"]
        for key in ("quiet_start", "quiet_end"):
            if key in payload:
                value = payload[key]
                if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1439):
                    raise AlphaError("Quiet hours are minutes after midnight (0–1439).", 400)
                fields[key] = value
        if "time_zone" in payload:
            value = payload["time_zone"]
            if value is not None:
                from zoneinfo import ZoneInfo
                try:
                    ZoneInfo(value)
                except Exception as error:  # noqa: BLE001
                    raise AlphaError("Unknown time zone.", 400) from error
                if not ZONE.match(value):
                    raise AlphaError("Unknown time zone.", 400)
            fields["time_zone"] = value
        if "mute_hours" in payload:
            hours = payload["mute_hours"]
            if hours is not None and (not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 < hours <= 24 * 30):
                raise AlphaError("Mute for between 1 hour and 30 days.", 400)
            fields["muted_until"] = None if hours is None else self.clock() + hours * 3600
        if "email_unsubscribed" in payload:
            if not isinstance(payload["email_unsubscribed"], bool):
                raise AlphaError("email_unsubscribed must be true or false.", 400)
            fields["email_unsubscribed"] = payload["email_unsubscribed"]
        if not fields:
            raise AlphaError("Nothing to change.", 400)
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            scope_key = workspace_id if scope == "workspace" else "*"
            columns = list(fields)
            values = [fields[c] if c != "muted_until" or fields[c] is None else store._ts(fields[c]) for c in columns]
            cur.execute(f"""INSERT INTO public.pr_notification_preferences(user_id,scope_key,category,{','.join(columns)},updated_at)
                            VALUES(%s,%s,%s,{','.join(['%s'] * len(columns))},now())
                            ON CONFLICT (user_id,scope_key,category) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in columns)}, updated_at=now()""",
                        [principal, scope_key, category] + values)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "notification.preferences_updated", category, {"scope": scope, "fields": sorted(columns)})
            stored = store.preference_rows(cur, principal).get((scope_key, category)) or {}
        verified = all((stored.get(c) == fields[c]) if c != "muted_until" else (fields[c] is None) == (stored.get(c) is None) for c in columns)
        return {"scope": scope, "category": category, "stored": stored, "verified": verified}

    def subscribe_push(self, workspace_id, token, payload, client_label=None):
        """Store one explicit opt-in subscription for the caller (endpoint and keys encrypted)."""
        self._require(push=True)
        endpoint, keys = payload.get("endpoint"), payload.get("keys") or {}
        if not isinstance(endpoint, str) or not push_module.endpoint_allowed(endpoint) or len(endpoint) > 2000:
            raise AlphaError("This push subscription is not from a supported push service.", 400)
        try:
            if len(push_module.unb64u(keys.get("p256dh"))) != 65 or len(push_module.unb64u(keys.get("auth"))) != 16:
                raise ValueError
        except (ValueError, TypeError) as error:
            raise AlphaError("The subscription keys are invalid.", 400) from error
        vault = getattr(getattr(self.hosted, "oauth", None), "vault", None)
        if vault is None or not getattr(vault, "fernet", None):
            raise AlphaError("Push subscriptions need server-side encryption, which is not configured.", 503)
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            sealed = [vault.encrypt(v)[0] for v in (endpoint, keys["p256dh"], keys["auth"])]
            expiration = payload.get("expirationTime")
            cur.execute("""INSERT INTO public.pr_push_subscriptions(user_id,endpoint_sha256,endpoint_ciphertext,p256dh_ciphertext,auth_ciphertext,key_id,client_label,expiration_time)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (endpoint_sha256) DO UPDATE SET user_id=excluded.user_id, endpoint_ciphertext=excluded.endpoint_ciphertext,
                             p256dh_ciphertext=excluded.p256dh_ciphertext, auth_ciphertext=excluded.auth_ciphertext, key_id=excluded.key_id,
                             client_label=excluded.client_label, expiration_time=excluded.expiration_time, revoked_at=NULL, revoked_reason=NULL, last_seen_at=now()
                           RETURNING id::text""",
                        (principal, push_module.endpoint_hash(endpoint), *sealed, vault.key_id, (client_label or "")[:60] or None,
                         store._ts(expiration / 1000) if isinstance(expiration, (int, float)) and expiration > 0 else None))
            subscription_id = cur.fetchone()[0]
            from ..hosted import audit
            audit(cur, workspace_id, principal, "push.subscribed", subscription_id, {"client": (client_label or "")[:40]})
            cur.execute("SELECT revoked_at IS NULL FROM public.pr_push_subscriptions WHERE id::text=%s AND user_id=%s", (subscription_id, principal))
            active = bool((cur.fetchone() or [False])[0])
        return {"subscriptionId": subscription_id, "active": active, "verified": active}

    def unsubscribe_push(self, workspace_id, token, subscription_id=None, endpoint=None):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            if endpoint:
                cur.execute("UPDATE public.pr_push_subscriptions SET revoked_at=now(), revoked_reason='user' WHERE user_id=%s AND endpoint_sha256=%s AND revoked_at IS NULL RETURNING id::text",
                            (principal, push_module.endpoint_hash(endpoint)))
            else:
                cur.execute("UPDATE public.pr_push_subscriptions SET revoked_at=now(), revoked_reason='user' WHERE user_id=%s AND id::text=%s AND revoked_at IS NULL RETURNING id::text",
                            (principal, subscription_id))
            revoked = [r[0] for r in cur.fetchall()]
            from ..hosted import audit
            for rid in revoked:
                audit(cur, workspace_id, principal, "push.revoked", rid, {})
            cur.execute("SELECT count(*) FROM public.pr_push_subscriptions WHERE user_id=%s AND revoked_at IS NULL AND id::text = ANY(%s)", (principal, revoked or [""]))
            still = cur.fetchone()[0]
        return {"revoked": len(revoked), "verified": still == 0}

    def push_devices(self, workspace_id, token):
        self._require()
        with self.hosted.repository.transaction(token, workspace_id) as (cur, _row, principal):
            cur.execute("""SELECT id::text, client_label, extract(epoch from created_at), extract(epoch from last_success_at) FROM public.pr_push_subscriptions
                           WHERE user_id=%s AND revoked_at IS NULL ORDER BY created_at DESC""", (principal,))
            return {"devices": [{"id": r[0], "label": r[1], "createdAt": float(r[2]), "lastSuccessAt": float(r[3]) if r[3] else None} for r in cur.fetchall()]}

    # --- public, token-authenticated -------------------------------------------------------------------------------------------
    def unsubscribe(self, token, apply=False):
        if self.signing_key is None:
            raise AlphaError("Unsubscribe links are not configured.", 503)
        data = webhooks.read_unsubscribe_token(self.signing_key, token, self.clock())
        if not apply:
            return {"valid": True, "category": data["category"]}
        with self.hosted.repository.connection_factory() as db, db.cursor() as cur:
            result = webhooks.apply_unsubscribe(cur, data)
            db.commit()
        return {"valid": True, **result}

    def provider_webhook(self, headers, raw_body):
        secret = self.values.get("RESEND_WEBHOOK_SECRET")
        event = webhooks.verify_svix(secret, headers, raw_body, self.clock())
        with self.hosted.repository.connection_factory() as db, db.cursor() as cur:
            outcome = webhooks.ingest(cur, headers["svix-id"], event, raw_body, self.clock())
            db.commit()
        return outcome

    def status(self):
        return {"enabled": self.enabled(), "push": self.push_enabled(), "email": self.email_available(), "catalogVersion": catalog.CATALOG_VERSION}
