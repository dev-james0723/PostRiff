"""Stripe payment provider for the billing layer (architecture §17; decisions D3, D13).

Real: Stripe REST over HTTPS (Checkout Sessions, Billing Portal sessions) through the injected
transport, and Stripe-Signature verification — header `t=<ts>,v1=<hex>[,v1=<hex>...]`, where each
v1 is HMAC-SHA256 of `<t>.<raw body>` keyed with the endpoint secret; any matching v1 is accepted,
compared in constant time, and the timestamp must sit within `tolerance` seconds of the clock.
Not here: no local persistence and no SDK. Subscription state is written only by
`Billing.process_webhook` after this module maps a Stripe event to the internal event shape;
Stripe events this deployment does not handle keep their raw type with workspaceId '' so the
webhook records them as ignored and answers 200 (Stripe must never be told 4xx for those).
Secrets never appear in responses, logs or errors; Stripe error bodies are reduced to a code.
"""
import hashlib
import hmac
import json
import re
import time
from postriff_alpha.domain import AlphaError
from .providers import http_transport

API = "https://api.stripe.com/v1"
_SAFE_CODE = re.compile(r"^[a-z0-9_]{1,48}$")

# Stripe event type → internal event type. None means "derive from the subscription object's status".
EVENT_TYPES = {
    "checkout.session.completed": "subscription.activated",  # only when mode=subscription
    "customer.subscription.created": None,
    "customer.subscription.updated": None,
    "customer.subscription.deleted": "subscription.cancelled",
    "invoice.payment_failed": "invoice.payment_failed",
    "invoice.paid": "subscription.updated",
}
# Stripe subscription status → internal event type (customer.subscription.created|updated).
SUBSCRIPTION_STATUS_EVENTS = {
    "active": "subscription.activated", "trialing": "subscription.activated",
    "past_due": "invoice.payment_failed", "unpaid": "subscription.expired",
    "canceled": "subscription.cancelled", "incomplete_expired": "subscription.cancelled",
}


def _ref(value):
    """Stripe returns related objects either as an id string or an expanded dict."""
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) and value else None


def _metadata(obj, *paths):
    """First metadata dict found along the given key paths (each path a tuple of keys)."""
    for path in paths:
        node = obj
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, dict):
            return node
    return {}


def _epoch(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _first_item(obj):
    items = (obj.get("items") or {}).get("data") if isinstance(obj.get("items"), dict) else None
    return items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}


def _subscription_fields(obj):
    item = _first_item(obj)
    meta = _metadata(obj, ("metadata",))
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    return {
        "workspaceId": meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None, "priceId": _ref(price),
        "customerId": _ref(obj.get("customer")), "subscriptionId": _ref(obj.get("id")),
        # Stripe API 2025-03-31 moved current_period_end onto subscription items; accept both shapes.
        "currentPeriodEnd": _epoch(obj.get("current_period_end")) if obj.get("current_period_end") is not None else _epoch(item.get("current_period_end")),
        "cancelAtPeriodEnd": bool(obj.get("cancel_at_period_end")),
    }


def _invoice_fields(obj):
    # 2025+ invoices carry parent.subscription_details; older ones subscription_details at the top level.
    details = obj.get("subscription_details") if isinstance(obj.get("subscription_details"), dict) else (obj.get("parent") or {}).get("subscription_details") if isinstance(obj.get("parent"), dict) else None
    details = details if isinstance(details, dict) else {}
    meta = _metadata(details, ("metadata",))
    lines = (obj.get("lines") or {}).get("data") if isinstance(obj.get("lines"), dict) else None
    line = lines[0] if isinstance(lines, list) and lines and isinstance(lines[0], dict) else {}
    period = line.get("period") if isinstance(line.get("period"), dict) else {}
    payments = (obj.get("payments") or {}).get("data") if isinstance(obj.get("payments"), dict) else None
    first_payment = payments[0].get("payment") if isinstance(payments, list) and payments and isinstance(payments[0], dict) and isinstance(payments[0].get("payment"), dict) else {}
    amount_paid = obj.get("amount_paid")
    return {
        "workspaceId": meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None,
        "customerId": _ref(obj.get("customer")), "subscriptionId": _ref(obj.get("subscription")) or _ref(details.get("subscription")),
        "currentPeriodEnd": _epoch(period.get("end")), "periodStart": _epoch(period.get("start")),
        # Monthly credits (FINAL-07) bind to the invoice itself, never to the event that delivered it.
        "invoiceId": _ref(obj.get("id")), "billingReason": obj.get("billing_reason") if isinstance(obj.get("billing_reason"), str) else None,
        "invoicePaid": obj.get("status") == "paid" or obj.get("paid") is True,
        "amountPaid": amount_paid if type(amount_paid) is int and amount_paid >= 0 else None,
        "currency": obj.get("currency") if isinstance(obj.get("currency"), str) else None,
        # Older API versions carry payment_intent on the invoice; 2025+ versions list invoice payments.
        "paymentIntentId": _ref(obj.get("payment_intent")) or _ref(first_payment.get("payment_intent")),
    }


def _checkout_fields(obj):
    meta = _metadata(obj, ("metadata",))
    return {
        "workspaceId": obj.get("client_reference_id") or meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None,
        "customerId": _ref(obj.get("customer")), "subscriptionId": _ref(obj.get("subscription")),
    }


CREDIT_CHECKOUT_TTL_SECONDS = 3600
KEY_MODES = (("sk_live_", True), ("rk_live_", True), ("sk_test_", False), ("rk_test_", False))


def key_mode(secret_key):
    """True for live keys, False for test keys (standard or restricted); any other format is refused."""
    for prefix, live in KEY_MODES:
        if secret_key.startswith(prefix):
            return live
    raise AlphaError("The Stripe secret key is not a recognised live or test key.", 503)


class StripePaymentProvider:
    """Live provider. `parse_webhook` verifies and maps; `create_*` call Stripe through `transport`."""
    id = "stripe"

    def __init__(self, secret_key, webhook_secret, transport=None, clock=time.time, tolerance=300):
        if not secret_key or not webhook_secret:
            raise AlphaError("Stripe credentials are required.", 503)
        self.secret_key, self.webhook_secret = secret_key, webhook_secret.encode()
        self.live = key_mode(secret_key)
        self.transport, self.clock, self.tolerance = transport or http_transport, clock, int(tolerance)

    # --- webhooks ------------------------------------------------------------------------
    def verify_signature(self, signature_header, body):
        if not isinstance(body, (bytes, bytearray)) or not isinstance(signature_header, str) or not signature_header:
            raise AlphaError("Webhook signature rejected.", 401)
        timestamp, candidates = None, []
        for part in signature_header.split(","):
            key, _, value = part.strip().partition("=")
            if key == "t" and value.isdigit():
                timestamp = int(value)
            elif key == "v1" and value:
                candidates.append(value)
        if timestamp is None or not candidates or abs(self.clock() - timestamp) > self.tolerance:
            raise AlphaError("Webhook signature rejected.", 401)
        expected = hmac.new(self.webhook_secret, f"{timestamp}.".encode() + bytes(body), hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
            raise AlphaError("Webhook signature rejected.", 401)

    def parse_webhook(self, signature_header, body):
        """Verified Stripe event → internal event (see module docstring for the unhandled-event rule)."""
        self.verify_signature(signature_header, body)
        try:
            raw = json.loads(body)
        except ValueError as error:
            raise AlphaError("Webhook body invalid.", 400) from error
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("type"), str):
            raise AlphaError("Webhook event incomplete.", 400)
        if raw.get("livemode") is not self.live:
            raise AlphaError("Payment environment mismatch.", 400)
        obj = (raw.get("data") or {}).get("object") if isinstance(raw.get("data"), dict) else None
        obj = obj if isinstance(obj, dict) else {}
        return self.map_event(raw["id"], raw["type"], _epoch(raw.get("created")) or self.clock(), obj)

    @staticmethod
    def map_event(event_id, stripe_type, created_at, obj):
        event = {"id": event_id, "type": stripe_type, "createdAt": created_at, "workspaceId": ""}
        if stripe_type not in EVENT_TYPES:
            return event
        internal = EVENT_TYPES[stripe_type]
        if stripe_type == "checkout.session.completed":
            if obj.get("mode") != "subscription":
                return event
            fields = _checkout_fields(obj)
        elif stripe_type.startswith("customer.subscription."):
            fields = _subscription_fields(obj)
            if internal is None:
                internal = SUBSCRIPTION_STATUS_EVENTS.get(obj.get("status"))
                if internal is None:
                    return event  # incomplete/paused etc.: recorded as ignored
        else:
            fields = _invoice_fields(obj)
        event.update({k: v for k, v in fields.items() if v is not None})
        event["type"] = internal
        event["stripeType"] = stripe_type
        return event

    # --- sessions ----------------------------------------------------------------------------
    def _post(self, path, form, idempotency_key=None, failure="Stripe did not complete this request."):
        headers = {"Authorization": "Bearer " + self.secret_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.transport("POST", API + path, headers=headers, form=form)
        body = response.get("body")
        if response.get("status") != 200 or not isinstance(body, dict):
            raise AlphaError(failure + self._summary(body), 502)
        return body

    @staticmethod
    def _summary(body):
        """Short, safe hint: Stripe's error code/type only — never its message, never request data."""
        error = body.get("error") if isinstance(body, dict) else None
        code = (error or {}).get("code") or (error or {}).get("type") if isinstance(error, dict) else None
        return f" (stripe: {code})" if isinstance(code, str) and _SAFE_CODE.match(code) else ""

    def create_checkout_session(self, *, workspace_id, plan_terms_id, price_id, success_url, cancel_url, customer_id=None, customer_email=None, idempotency_key):
        for name, value in (("workspace_id", workspace_id), ("plan_terms_id", plan_terms_id), ("price_id", price_id), ("success_url", success_url), ("cancel_url", cancel_url), ("idempotency_key", idempotency_key)):
            if not isinstance(value, str) or not value:
                raise AlphaError(f"Checkout needs {name}.", 400)
        if not customer_id and not customer_email:
            raise AlphaError("Checkout needs a customer id or email.", 400)
        form = {
            "mode": "subscription", "line_items[0][price]": price_id, "line_items[0][quantity]": "1",
            "client_reference_id": workspace_id,
            "subscription_data[metadata][workspace_id]": workspace_id, "subscription_data[metadata][plan_terms_id]": plan_terms_id,
            "metadata[workspace_id]": workspace_id, "metadata[plan_terms_id]": plan_terms_id,
            "success_url": success_url, "cancel_url": cancel_url, "allow_promotion_codes": "true",
        }
        if customer_id:
            form["customer"] = customer_id
        else:
            form["customer_email"] = customer_email
        body = self._post("/checkout/sessions", form, idempotency_key, "Checkout could not be started.")
        if not isinstance(body.get("url"), str) or not isinstance(body.get("id"), str):
            raise AlphaError("Checkout could not be started.", 502)
        return {"url": body["url"], "sessionId": body["id"]}

    def create_credit_checkout_session(self, *, order_id, workspace_id, price_id, customer_email, success_url, cancel_url):
        """Prepare one-time Checkout through the injected transport; no credit is granted here."""
        for value in (order_id, workspace_id, price_id, customer_email, success_url, cancel_url):
            if not isinstance(value, str) or not value:
                raise AlphaError("Credit checkout is missing a required field.", 400)
        form = {"mode": "payment", "line_items[0][price]": price_id, "line_items[0][quantity]": "1",
                # An unpaid session ends on its own; checkout.session.expired then closes the order.
                "expires_at": str(int(self.clock()) + CREDIT_CHECKOUT_TTL_SECONDS),
                "client_reference_id": workspace_id, "customer_email": customer_email,
                "metadata[credit_order_id]": order_id, "payment_intent_data[metadata][credit_order_id]": order_id,
                "success_url": success_url, "cancel_url": cancel_url}
        body = self._post("/checkout/sessions", form, "credit-order:" + order_id, "Credit checkout could not be started.")
        from urllib.parse import urlparse
        url = body.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or parsed.netloc != "checkout.stripe.com" or not isinstance(body.get("id"), str):
            raise AlphaError("Stripe did not return a valid checkout session.", 502)
        return {"sessionId": body["id"], "url": url}

    def create_portal_session(self, *, customer_id, return_url):
        if not isinstance(customer_id, str) or not customer_id or not isinstance(return_url, str) or not return_url:
            raise AlphaError("Portal needs a customer id and return URL.", 400)
        body = self._post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}, None, "The billing portal could not be opened.")
        if not isinstance(body.get("url"), str):
            raise AlphaError("The billing portal could not be opened.", 502)
        return {"url": body["url"]}
