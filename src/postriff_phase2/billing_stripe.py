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
from decimal import ROUND_HALF_UP, Decimal
from postriff_alpha.domain import AlphaError
from .providers import http_transport

API = "https://api.stripe.com/v1"
_SAFE_CODE = re.compile(r"^[a-z0-9_]{1,48}$")

# Stripe event type → internal event type. None means "derive from the subscription object's status".
# The last two are recorded with their fields but change no subscription state (Billing.TRANSITIONS has no entry for
# them): a refund never changes MRR, and a trial notice only records the trial end (founder billing events, 057).
EVENT_TYPES = {
    "checkout.session.completed": "subscription.activated",  # only when mode=subscription
    "customer.subscription.created": None,
    "customer.subscription.updated": None,
    "customer.subscription.deleted": "subscription.cancelled",
    "invoice.payment_failed": "invoice.payment_failed",
    "invoice.paid": "subscription.updated",
    "charge.refunded": "charge.refunded",
    "customer.subscription.trial_will_end": "subscription.trial_will_end",
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


def _path(obj, *keys):
    for key in keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


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


def _item_count(obj):
    items = (obj.get("items") or {}).get("data") if isinstance(obj.get("items"), dict) else None
    return len(items) if isinstance(items, list) else 0


def _minor(value):
    """A non-negative integer amount in minor units, else None."""
    return value if type(value) is int and 0 <= value <= 100_000_000_000 else None


def _currency(value):
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{3}", value) else None


def _coupon_of(discount):
    """The coupon of one Stripe discount: `discount.coupon` (older API versions) or `discount.source.coupon` (newer)."""
    coupon = discount.get("coupon")
    if not isinstance(coupon, dict) and isinstance(discount.get("source"), dict):
        coupon = discount["source"].get("coupon")
    return coupon if isinstance(coupon, dict) else None


def _discount_value(discount, gross, currency):
    """(duration, amount per invoice, end) for one discount, or None when it cannot be valued from the payload."""
    coupon = _coupon_of(discount)
    if coupon is None:
        return None
    duration = coupon.get("duration")
    if duration == "once":
        return ("once", 0, None)  # a one-time discount does not change recurring revenue
    if duration not in ("forever", "repeating"):
        return None
    amount_off, percent_off = _minor(coupon.get("amount_off")), coupon.get("percent_off")
    if amount_off is not None:
        if _currency(coupon.get("currency")) != currency:
            return None
        value = min(amount_off, gross)
    elif isinstance(percent_off, (int, float)) and not isinstance(percent_off, bool) and 0 < percent_off <= 100:
        value = int((Decimal(gross) * Decimal(str(percent_off)) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    else:
        return None
    end = _epoch(discount.get("end")) if duration == "repeating" else None
    if duration == "repeating" and end is None:
        return None
    return (duration, value, end)


def _discount_fields(obj, item, gross, currency):
    """Recurring discount per invoice for MRR (PRD §7.1 M04: forever and repeating discounts are subtracted, one-time ones
    are not). Returns {discountMinor, discountEnd}: 0 when there is no discount; discountMinor None ("present but unknown")
    when a discount is only an unexpanded id, uses an unknown coupon shape or several repeating/forever discounts mix."""
    found, ids = [], set()
    candidates = [obj.get("discount")] + list(obj.get("discounts") if isinstance(obj.get("discounts"), list) else []) \
        + list(item.get("discounts") if isinstance(item.get("discounts"), list) else [])
    for entry in candidates:
        if entry is None:
            continue
        key = _ref(entry)
        if key and key in ids:
            continue
        if not isinstance(entry, dict):
            return {"discountMinor": None, "discountEnd": None}  # an id we cannot value from the payload
        if key:
            ids.add(key)
        found.append(entry)
    if not found:
        return {"discountMinor": 0, "discountEnd": None}
    if gross is None or currency is None:
        return {"discountMinor": None, "discountEnd": None}
    values = [_discount_value(entry, gross, currency) for entry in found]
    if any(value is None for value in values):
        return {"discountMinor": None, "discountEnd": None}
    forever = sum(value for duration, value, _ in values if duration == "forever")
    repeating = [(value, end) for duration, value, end in values if duration == "repeating"]
    if not repeating:
        return {"discountMinor": forever, "discountEnd": None}
    if forever == 0 and len(repeating) == 1:
        return {"discountMinor": repeating[0][0], "discountEnd": repeating[0][1]}
    return {"discountMinor": None, "discountEnd": None}


def _price_fields(obj, item, price):
    """Recurring price of the subscription for founder MRR (057 pr_subscription_events). Only a single-item, per-unit,
    tax-exclusive price is valued: several items, tiered prices or tax-inclusive amounts leave unitAmount unknown (None),
    which the founder metrics report as coverage.unknown, never as a list price."""
    recurring = price.get("recurring") if isinstance(price.get("recurring"), dict) else {}
    interval = recurring.get("interval") if recurring.get("interval") in ("day", "week", "month", "year") else None
    count = recurring.get("interval_count")
    usage = recurring.get("usage_type") if recurring.get("usage_type") in ("licensed", "metered") else None
    quantity = item.get("quantity") if type(item.get("quantity")) is int and 0 <= item.get("quantity") <= 1_000_000 else None
    currency = _currency(price.get("currency")) or _currency(obj.get("currency"))
    unit = _minor(price.get("unit_amount"))
    if _item_count(obj) != 1 or price.get("tax_behavior") == "inclusive" or price.get("billing_scheme") not in (None, "per_unit"):
        unit = None
    gross = unit * (quantity if quantity is not None else 1) if unit is not None else None
    return {
        "interval": interval, "intervalCount": count if type(count) is int and 1 <= count <= 1000 else (1 if interval else None),
        "usageType": usage, "unitAmount": unit, "quantity": quantity, "currency": currency,
        **_discount_fields(obj, item, gross, currency),
        "trialEnd": _epoch(obj.get("trial_end")), "cancelAt": _epoch(obj.get("cancel_at")),
    }


def _subscription_fields(obj):
    item = _first_item(obj)
    meta = _metadata(obj, ("metadata",))
    price = item.get("price") if isinstance(item.get("price"), dict) else {}   # expanded price, for the valued fields
    return {
        "workspaceId": meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None, "priceVariantId": meta.get("price_variant_id") or None, "priceId": _ref(item.get("price")),
        "customerId": _ref(obj.get("customer")), "subscriptionId": _ref(obj.get("id")),
        # Stripe API 2025-03-31 moved current_period_end onto subscription items; accept both shapes.
        "currentPeriodEnd": _epoch(obj.get("current_period_end")) if obj.get("current_period_end") is not None else _epoch(item.get("current_period_end")),
        "cancelAtPeriodEnd": bool(obj.get("cancel_at_period_end")),
        # items[0].price.recurring interval/count, unit amount, quantity, currency and recurring discounts (PRD §8.5).
        **_price_fields(obj, item, price),
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
        "workspaceId": meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None, "priceVariantId": meta.get("price_variant_id") or None,
        "priceId": _ref(line.get("price")) or _ref(_path(line, "pricing", "price_details", "price")),
        "customerId": _ref(obj.get("customer")), "subscriptionId": _ref(obj.get("subscription")) or _ref(details.get("subscription")),
        "currentPeriodEnd": _epoch(period.get("end")), "periodStart": _epoch(period.get("start")),
        # Monthly credits (FINAL-07) bind to the invoice itself, never to the event that delivered it.
        "invoiceId": _ref(obj.get("id")), "billingReason": obj.get("billing_reason") if isinstance(obj.get("billing_reason"), str) else None,
        "invoicePaid": obj.get("status") == "paid" or obj.get("paid") is True,
        "amountPaid": amount_paid if type(amount_paid) is int and amount_paid >= 0 else None,
        "currency": obj.get("currency") if isinstance(obj.get("currency"), str) else None,
        # Older API versions carry payment_intent on the invoice; 2025+ versions list invoice payments.
        "paymentIntentId": _ref(obj.get("payment_intent")) or _ref(first_payment.get("payment_intent")),
        # Founder invoice record (057 pr_invoices): amount due and the invoice's own status.
        "amountDue": _minor(obj.get("amount_due")),
        "invoiceStatus": obj.get("status") if obj.get("status") in ("draft", "open", "paid", "uncollectible", "void") else None,
    }


def _charge_fields(obj):
    """charge.refunded: ids and the refunded amount only. It is recorded and changes no subscription state."""
    meta = _metadata(obj, ("metadata",))
    return {
        "workspaceId": meta.get("workspace_id") or "", "customerId": _ref(obj.get("customer")), "chargeId": _ref(obj.get("id")),
        "invoiceId": _ref(obj.get("invoice")), "paymentIntentId": _ref(obj.get("payment_intent")),
        "amountRefunded": _minor(obj.get("amount_refunded")), "currency": _currency(obj.get("currency")),
    }



def _invoice_price_lines(obj):
    """Keep signed line facts together; only the server catalog can select the plan line."""
    lines = _path(obj, "lines", "data")
    result = []
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        parent_kind = _path(line, "parent", "type")
        kind = "unknown"
        if line.get("type") == "subscription" or parent_kind == "subscription_item_details":
            kind = "subscription"
        elif line.get("type") in ("invoiceitem", "invoice_item") or parent_kind == "invoice_item_details":
            kind = "addon"
        prices = {_ref(line.get("price")), _ref(_path(line, "pricing", "price_details", "price"))} - {None}
        subscriptions = {_ref(line.get("subscription")),
                         _ref(_path(line, "parent", "subscription_item_details", "subscription")),
                         _ref(_path(line, "parent", "invoice_item_details", "subscription"))} - {None}
        result.append({"priceIds": sorted(prices), "kind": kind,
                       "subscriptionId": next(iter(subscriptions)) if len(subscriptions) == 1 else None,
                       "subscriptionIds": sorted(subscriptions),
                       "periodStart": _epoch(_path(line, "period", "start")),
                       "periodEnd": _epoch(_path(line, "period", "end"))})
    return result


def _checkout_fields(obj):
    meta = _metadata(obj, ("metadata",))
    return {
        "workspaceId": obj.get("client_reference_id") or meta.get("workspace_id") or "", "planTermsId": meta.get("plan_terms_id") or None, "priceVariantId": meta.get("price_variant_id") or None,
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
        elif stripe_type.startswith("charge."):
            fields = _charge_fields(obj)
        else:
            fields = _invoice_fields(obj)
        event.update({k: v for k, v in fields.items() if v is not None})
        event["type"] = internal
        event["stripeType"] = stripe_type
        metadata = [obj.get("metadata")]
        if stripe_type.startswith("invoice."):
            event["invoicePriceLines"] = _invoice_price_lines(obj)
            if any(len(line["priceIds"]) > 1 for line in event["invoicePriceLines"]):
                event["metadataConflict"] = True
            metadata += [_path(obj, "subscription_details", "metadata"),
                         _path(obj, "parent", "subscription_details", "metadata")]
            subscriptions = {_ref(obj.get("subscription")), _ref(_path(obj, "subscription_details", "subscription")),
                             _ref(_path(obj, "parent", "subscription_details", "subscription"))} - {None}
            # Check every signed carrier before package/period selection, including addon lines.
            subscriptions.update(subscription_id for line in event["invoicePriceLines"]
                                 for subscription_id in line["subscriptionIds"])
            if len(subscriptions) > 1:
                event["metadataConflict"] = True
        for key, field in (("workspace_id", "workspaceId"), ("plan_terms_id", "planTermsId"), ("price_variant_id", "priceVariantId")):
            values = [m[key] for m in metadata if isinstance(m, dict) and key in m]
            if key == "workspace_id" and obj.get("client_reference_id"):
                values.append(obj["client_reference_id"])
            if any(not isinstance(v, str) or not v.strip() for v in values) or len(set(v for v in values if isinstance(v, str))) > 1:
                event["metadataConflict"] = True
            elif values:
                event[field] = values[0]
        collection = obj.get("lines") if stripe_type.startswith("invoice.") else obj.get("items")
        items = collection.get("data") if isinstance(collection, dict) else []
        prices = {_ref(value) for item in (items or []) if isinstance(item, dict)
                  for value in (item.get("price"), _path(item, "pricing", "price_details", "price"))} - {None}
        if len(prices) > 1:
            # Legacy invoices can include addons; v2 rejects ambiguous package pricing.
            event["priceConflict"] = True
        elif prices:
            event["priceId"] = next(iter(prices))
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

    def create_checkout_session(self, *, workspace_id, plan_terms_id, price_id, success_url, cancel_url, customer_id=None, customer_email=None, idempotency_key, price_variant_id=None):
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
        if price_variant_id is not None:
            if not isinstance(price_variant_id, str) or not price_variant_id.strip():
                raise AlphaError("Checkout needs a valid price variant.", 400)
            form["metadata[price_variant_id]"] = price_variant_id
            form["subscription_data[metadata][price_variant_id]"] = price_variant_id
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
