"""Email-provider webhooks and signed unsubscribe links (adaptive coworker spec §17, §21; architecture lock E1).

Resend signs webhooks with Svix: `svix-id`, `svix-timestamp`, `svix-signature` ("v1,<base64 HMAC-SHA256>" entries)
over "<id>.<timestamp>.<raw body>" with the base64 secret after "whsec_". Verification mirrors
`billing_stripe.verify_signature` (5-minute tolerance, constant-time compare, 401 on any failure), and replay
defence is the `(provider, event_id)` primary key of `pr_notification_provider_events`.

Unsubscribe links carry an HMAC-signed token (person, scope, category, expiry); one-click (RFC 8058) posts to the
same URL. No session is needed and nothing else can be changed through it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from postriff_alpha.domain import AlphaError

TOLERANCE = 300
EMAIL_EVENTS = {"email.sent": "sent", "email.delivered": "delivered", "email.delivery_delayed": None, "email.bounced": "bounced",
                "email.complained": "complained", "email.failed": "failed", "email.opened": "opened", "email.clicked": "clicked"}


def verify_svix(secret, headers, body, now=None, tolerance=TOLERANCE):
    """Return the parsed event, or raise AlphaError(401). `headers` keys are lower-case."""
    if not secret or not str(secret).startswith("whsec_"):
        raise AlphaError("Email webhooks are not configured.", 503)
    msg_id, stamp, signatures = headers.get("svix-id"), headers.get("svix-timestamp"), headers.get("svix-signature")
    if not msg_id or not stamp or not signatures:
        raise AlphaError("Webhook signature rejected.", 401)
    try:
        timestamp = int(stamp)
    except (TypeError, ValueError) as error:
        raise AlphaError("Webhook signature rejected.", 401) from error
    if abs((now or time.time()) - timestamp) > tolerance:
        raise AlphaError("Webhook signature rejected.", 401)
    try:
        key = base64.b64decode(str(secret)[len("whsec_"):])
    except ValueError as error:
        raise AlphaError("Email webhooks are not configured.", 503) from error
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    supplied = [part.split(",", 1)[1] for part in str(signatures).split() if part.startswith("v1,") and "," in part]
    # Compared as bytes: a header with non-ASCII characters is a rejected signature (401), never a server error.
    if not any(hmac.compare_digest(expected.encode(), candidate.encode("utf-8", "replace")) for candidate in supplied):
        raise AlphaError("Webhook signature rejected.", 401)
    try:
        event = json.loads(body)
    except ValueError as error:
        raise AlphaError("Webhook body is not JSON.", 400) from error
    if not isinstance(event, dict):
        raise AlphaError("Webhook body is not an event.", 400)
    return event


def sign_svix(secret, msg_id, stamp, body):
    """Test/dev helper: the header a real Svix sender would produce."""
    key = base64.b64decode(str(secret)[len("whsec_"):])
    signature = base64.b64encode(hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": str(stamp), "svix-signature": f"v1,{signature}"}


def ingest(cur, msg_id, event, raw_body, now=None):
    """Apply one verified provider event to its delivery. Idempotent: a replayed svix-id is a duplicate."""
    kind = str(event.get("type") or "")[:60]
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    digest = hashlib.sha256(raw_body).hexdigest()
    cur.execute("SELECT outcome FROM public.pr_notification_provider_events WHERE provider='resend' AND event_id=%s", (msg_id,))
    if cur.fetchone():
        return {"outcome": "duplicate"}
    tags = {}
    for tag in data.get("tags") or []:
        if isinstance(tag, dict) and tag.get("name"):
            tags[str(tag["name"])] = str(tag.get("value"))
    if isinstance(data.get("tags"), dict):
        tags.update({str(k): str(v) for k, v in data["tags"].items()})
    delivery_id = tags.get("delivery_id")
    provider_ref = data.get("email_id") or data.get("id")
    rows = []
    if delivery_id:
        cur.execute("SELECT id::text, user_id::text, status FROM public.pr_notification_deliveries WHERE id::text=%s AND channel='email'", (delivery_id,))
        rows = cur.fetchall()
    if not rows and provider_ref:
        # A digest is one email for several delivery rows that share its provider reference: the outcome applies to all.
        cur.execute("SELECT id::text, user_id::text, status FROM public.pr_notification_deliveries WHERE provider='resend' AND provider_ref=%s AND channel='email'", (str(provider_ref)[:200],))
        rows = cur.fetchall()
    row = rows[0] if rows else None
    targets = [r[0] for r in rows]
    mapped = EMAIL_EVENTS.get(kind, "unknown")
    outcome = "unmatched" if row is None else "ignored"
    if row is not None:
        delivery, user_id, status = row
        if mapped == "delivered" and status in ("sent", "claimed"):
            cur.execute("UPDATE public.pr_notification_deliveries SET status='delivered', delivered_at=now(), updated_at=now() WHERE id::text = ANY(%s) AND status IN ('sent','claimed')",
                        (targets,))
            outcome = "applied"
        elif mapped in ("bounced", "failed"):
            cur.execute("UPDATE public.pr_notification_deliveries SET status='failed', failure_class='permanent', failure_detail=%s, failed_at=now(), updated_at=now() WHERE id::text = ANY(%s)",
                        (f"provider reported {mapped}", targets))
            if mapped == "bounced":
                _suppress_email(cur, user_id, "bounced")
            outcome = "applied"
        elif mapped == "complained":
            _suppress_email(cur, user_id, "complained")
            outcome = "applied"
        elif mapped in ("opened", "clicked"):
            cur.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) SELECT workspace_id,user_id,%s,%s::jsonb,%s FROM public.pr_notification_deliveries WHERE id::text=%s ON CONFLICT DO NOTHING",
                        (f"notification.{mapped}", json.dumps({"channel": "email", "deliveryId": delivery}), f"{mapped}:{delivery}", delivery))
            if mapped == "clicked":
                cur.execute("UPDATE public.pr_notification_deliveries SET read_at=coalesce(read_at, now()), updated_at=now() WHERE id::text=%s", (delivery,))
            outcome = "applied"
    cur.execute("""INSERT INTO public.pr_notification_provider_events(provider,event_id,delivery_id,kind,event_at,payload_digest,outcome)
                   VALUES('resend',%s,%s,%s,to_timestamp(%s),%s,%s) ON CONFLICT (provider,event_id) DO NOTHING""",
                (msg_id, row[0] if row else None, kind or "unknown", now or time.time(), digest, outcome))
    return {"outcome": outcome, "kind": kind}


def _suppress_email(cur, user_id, reason):
    """A hard bounce or complaint stops non-transactional email for that person (they can re-enable it)."""
    cur.execute("""INSERT INTO public.pr_notification_preferences(user_id,scope_key,category,email_unsubscribed,updated_at) VALUES(%s,'*','*',true,now())
                   ON CONFLICT (user_id,scope_key,category) DO UPDATE SET email_unsubscribed=true, updated_at=now()""", (user_id,))
    cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(NULL,%s,'notification.email_suppressed',%s,%s::jsonb)",
                (user_id, reason, json.dumps({"reason": reason})))


# --- signed unsubscribe tokens ------------------------------------------------------------------------------------------
def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_key(values):
    explicit = values.get("POSTRIFF_NOTIFICATION_SIGNING_KEY")
    base = explicit or values.get("POSTRIFF_CREDENTIAL_KEY") or values.get("CRON_SECRET")
    if not base:
        return None
    return hmac.new(str(base).encode(), b"rafii-notification-unsubscribe-v1", hashlib.sha256).digest()


def unsubscribe_token(key, user_id, scope_key="*", category="*", now=None, ttl=180 * 86400):
    body = json.dumps({"u": user_id, "s": scope_key, "c": category, "e": int((now or time.time()) + ttl)}, separators=(",", ":")).encode()
    return _b64(body) + "." + _b64(hmac.new(key, body, hashlib.sha256).digest())


def read_unsubscribe_token(key, token, now=None):
    try:
        body_part, signature = str(token).split(".", 1)
        body = _unb64(body_part)
        if not hmac.compare_digest(_unb64(signature), hmac.new(key, body, hashlib.sha256).digest()):
            raise ValueError("signature")
        data = json.loads(body)
    except (ValueError, TypeError) as error:
        raise AlphaError("This unsubscribe link is not valid.", 400) from error
    if data.get("e", 0) < (now or time.time()):
        raise AlphaError("This unsubscribe link has expired. Change email settings in Rafii instead.", 400)
    return {"userId": data["u"], "scope": data.get("s", "*"), "category": data.get("c", "*")}


def apply_unsubscribe(cur, token_data):
    """A deleted account's links stop working, and a repeated click changes nothing and records nothing new."""
    cur.execute("SELECT 1 FROM public.pr_account_tombstones WHERE user_id=%s", (token_data["userId"],))
    if cur.fetchone():
        raise AlphaError("This unsubscribe link is not valid.", 400)
    cur.execute("SELECT email_unsubscribed FROM public.pr_notification_preferences WHERE user_id=%s AND scope_key=%s AND category=%s",
                (token_data["userId"], token_data["scope"], token_data["category"]))
    current = cur.fetchone()
    if current and current[0] is True:
        return {"unsubscribed": True}
    cur.execute("""INSERT INTO public.pr_notification_preferences(user_id,scope_key,category,email_unsubscribed,updated_at) VALUES(%s,%s,%s,true,now())
                   ON CONFLICT (user_id,scope_key,category) DO UPDATE SET email_unsubscribed=true, updated_at=now() RETURNING email_unsubscribed""",
                (token_data["userId"], token_data["scope"], token_data["category"]))
    stored = cur.fetchone()
    cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(NULL,%s,'notification.unsubscribed',%s,%s::jsonb)",
                (token_data["userId"], token_data["category"], json.dumps({"scope": "workspace" if token_data["scope"] != "*" else "all"})))
    return {"unsubscribed": bool(stored and stored[0])}
