"""Live-billing path on disposable PostgreSQL: plan availability gate (D3), Stripe checkout/portal through a
recording transport, Stripe-signed webhooks (activation, payment failure, replay, orphan), the usage 'billing'
block, owner notifications, invitation email with the accept link, and reminder dedupe in pr_notifications.
No network: Stripe and Resend are replaced by in-memory doubles; the service, ledger and SQL are real.
"""
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.email import Mailer, NullTransport
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"
clock = [time.time() + 3600]  # ahead of any synthetic event timestamps left by earlier scripts on the shared cluster
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


verify.session_id = lambda t, p: "session-one-0123456789abcdef"
verify.auth_time = lambda t, p: clock[0]


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


class Transport:
    """Records every Stripe call; answers checkout and portal creation."""
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, form=None, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body})
        if url.endswith("/checkout/sessions"):
            return {"status": 200, "headers": {}, "body": {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}}
        if url.endswith("/billing_portal/sessions"):
            return {"status": 200, "headers": {}, "body": {"id": "bps_1", "url": "https://billing.stripe.com/p/session/1"}}
        return {"status": 404, "headers": {}, "body": {}}


class Identity:
    def email_for(self, user_id):
        return "owner@example.com" if user_id == ONE else None


def signed(event_type, obj, event_id, created=None):
    body = json.dumps({"id": event_id, "type": event_type, "created": int(created or clock[0]), "data": {"object": obj}}).encode()
    ts = int(clock[0])
    sig = hmac.new(b"whsec_test", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}", body


transport = Transport()
provider = StripePaymentProvider("sk_test_x", "whsec_test", transport=transport, clock=lambda: clock[0])
mail = NullTransport()
mailer = Mailer(mail, "PostRiff <hello@postriff.test>", "https://app.postriff.test")

with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
    # Earlier scripts share this workspace; start from a clean billing slate (ledger rows are append-only and left alone).
    for table in ("pr_notifications", "pr_subscriptions", "pr_entitlements"):
        db.execute(f"DELETE FROM public.{table} WHERE workspace_id=%s", (wid,))
    db.execute("DELETE FROM public.pr_billing_events")
    db.execute("UPDATE public.pr_plan_terms SET status='proposed', provider_price_id=NULL")

service = HostedWorkspaceService(connection, verify, clock=lambda: clock[0], identity=Identity(), public_base_url="https://app.postriff.test/", billing_provider=provider, mailer=mailer)
service.bootstrap("one", "studio")
assert any(m["subject"] == "Welcome to PostRiff" and m["to"] == "owner@example.com" for m in mail.sent), [m["subject"] for m in mail.sent]
service.bootstrap("one", "studio")
assert sum(1 for m in mail.sent if m["subject"] == "Welcome to PostRiff") == 1
checks.append("first bootstrap sends one welcome email; later sign-ins do not")

# 1. Proposed plan terms are not purchasable; usage reports the live provider with no checkout yet.
denied(lambda: service.billing_checkout(wid, "one", "studio-v1"), 409)
view = service.usage(wid, "one")
assert view["billing"] == {"provider": "stripe", "checkoutAvailable": False, "portalAvailable": False}, view["billing"]
checks.append("proposed plan terms refuse checkout (D3); usage shows no purchasable plan")

# 2. Activating terms with a provider price opens checkout; client paths must be relative.
with connection() as db:
    db.execute("UPDATE public.pr_plan_terms SET status='active', provider_price_id='price_studio' WHERE id='studio-v1'")
denied(lambda: service.billing_checkout(wid, "one", "studio-v1", "https://evil.example/x"), 400)
denied(lambda: service.billing_checkout(wid, "one", "studio-v1", "//evil.example"), 400)
session = service.billing_checkout(wid, "one", "studio-v1", "/app/account/billing?ok=1")
assert session["url"].startswith("https://checkout.stripe.com/") and session["sessionId"] == "cs_test_1", session
call = transport.calls[-1]
form = call["form"]
assert form["mode"] == "subscription" and form["line_items[0][price]"] == "price_studio" and form["client_reference_id"] == wid, form
assert form["subscription_data[metadata][workspace_id]"] == wid and form["subscription_data[metadata][plan_terms_id]"] == "studio-v1"
assert form["success_url"] == "https://app.postriff.test/app/account/billing?ok=1" and form["cancel_url"].startswith("https://app.postriff.test/app/account/billing")
assert form["customer_email"] == "owner@example.com" and call["headers"].get("Idempotency-Key") and call["headers"]["Authorization"] == "Bearer sk_test_x"
assert service.usage(wid, "one")["billing"]["checkoutAvailable"] is True
denied(lambda: service.billing_portal(wid, "one"), 409)
checks.append("active terms + price open checkout with workspace metadata and idempotency; absolute return URLs refused; portal needs a customer")

# 3. Stripe-signed checkout completion activates the subscription, reconciles entitlement, notifies the owner once.
sig, body = signed("checkout.session.completed", {"mode": "subscription", "client_reference_id": wid, "customer": "cus_1", "subscription": "sub_1", "metadata": {"workspace_id": wid, "plan_terms_id": "studio-v1"}}, "evt_1")
result = service.billing_webhook(sig, body)
assert result["outcome"] == "applied" and result["status"] == "active" and result["notification"]["sent"] is True, result
assert any(m["subject"] == "Your Studio plan is active" for m in mail.sent)
dup = service.billing_webhook(sig, body)
assert dup["outcome"] == "duplicate" and "notification" not in dup, dup
denied(lambda: service.billing_webhook("t=1,v1=bad", body), 401)
view = service.usage(wid, "one")
assert view["subscription"]["status"] == "active" and view["subscription"]["live"] is True and view["entitlement"]["source"] == "subscription", view["subscription"]
assert view["billing"]["portalAvailable"] is True
checks.append("signed checkout.session.completed → active subscription, entitlement from terms, one activation email; replay is duplicate; bad signature 401")

# 4. Portal works once a customer exists; a second checkout while active is refused.
portal = service.billing_portal(wid, "one", "/app/account/billing")
assert portal["url"].startswith("https://billing.stripe.com/") and transport.calls[-1]["form"]["customer"] == "cus_1", portal
denied(lambda: service.billing_checkout(wid, "one", "studio-v1"), 409)
checks.append("portal opens for the Stripe customer; active workspaces cannot start a second checkout")

# 5. Payment failure → past_due with grace and a payment_failed email; an orphan event is ignored with 200 semantics.
clock[0] += 5
sig, body = signed("invoice.payment_failed", {"customer": "cus_1", "subscription": "sub_1", "subscription_details": {"metadata": {"workspace_id": wid}}}, "evt_2")
result = service.billing_webhook(sig, body)
assert result["status"] == "past_due" and result["notification"]["sent"] is True, result
assert any(m["subject"] == "Action needed: payment failed" for m in mail.sent)
sig, body = signed("invoice.payment_failed", {"customer": "cus_zzz"}, "evt_3")
assert service.billing_webhook(sig, body)["outcome"] == "ignored"
checks.append("payment failure → past_due + grace + email; events without a PostRiff workspace are recorded as ignored")

# 6. A plan change arrives as subscription.updated with only the price id: resolved against active terms.
with connection() as db:
    db.execute("UPDATE public.pr_plan_terms SET status='active', provider_price_id='price_assist' WHERE id='assist-v1'")
clock[0] += 5
sig, body = signed("customer.subscription.updated", {"id": "sub_1", "status": "active", "customer": "cus_1", "metadata": {"workspace_id": wid}, "items": {"data": [{"price": {"id": "price_assist"}, "current_period_end": int(clock[0]) + 30 * 86400}]}}, "evt_4")
assert service.billing_webhook(sig, body)["outcome"] == "applied"
view = service.usage(wid, "one")
assert view["subscription"]["plan"] == "assist" and view["entitlement"]["writingBatchesRemaining"] == 100, (view["subscription"], view["entitlement"])
checks.append("price-only subscription.updated resolves plan terms by provider_price_id and reconciles entitlement")

# 7. Invitations email the accept link carrying the one-time raw token.
# The fixture grants an extra seat explicitly; production plan terms stay unchanged.
with connection() as db:
    db.execute("UPDATE public.pr_entitlements SET members=(SELECT count(*)+1 FROM public.pr_memberships WHERE workspace_id=%s AND status='active') WHERE workspace_id=%s", (wid, wid))
inv = service.invite(wid, "one", "Friend@Example.com", "editor", {})
assert inv["emailSent"] is True, inv
msg = [m for m in mail.sent if m["to"] == "friend@example.com"][-1]
assert f"https://app.postriff.test/invite/{inv['token']}" in msg["text"] and "owner@example.com" in msg["text"]
checks.append("invite sends the accept link with the raw token to the invitee")

# 8. Trial reminders: one send per window per workspace, deduped across runs.
with connection() as db:
    db.execute("UPDATE public.pr_trials SET expires_at=to_timestamp(%s) WHERE workspace_id=%s", (clock[0] + 2.5 * 86400, wid))
first, second = service.run_reminders(), service.run_reminders()
assert first == {"sent": 1, "skipped": 0} and second == {"sent": 0, "skipped": 1}, (first, second)
assert any(m["subject"].startswith("Your PostRiff trial ends in") for m in mail.sent)
with connection() as db:
    rows = db.execute("SELECT kind,sent FROM public.pr_notifications WHERE workspace_id=%s ORDER BY created_at", (wid,)).fetchall()
assert [r[0] for r in rows] == ["subscription_activated", "payment_failed", "subscription_activated", "trial_ending"] and all(r[1] for r in rows), rows
checks.append("reminder sweep sends once and dedupes; every notification is recorded with sent=true")

print(json.dumps({"status": "pass", "checks": checks}, ensure_ascii=False))
