"""Stripe provider unit tests (no network): signature scheme, event mapping, checkout/portal
requests through a recording transport, safe 502 errors, and Billing's priceId → planTermsId
resolution plus the on_applied callback over a stub cursor."""
import hashlib
import hmac
import json
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Billing, Ledger
from postriff_phase2.billing_stripe import EVENT_TYPES, SUBSCRIPTION_STATUS_EVENTS, StripePaymentProvider

NOW = 1_800_000_000.0
SECRET = "whsec_test"


def sign(body, ts=int(NOW), secret=SECRET):
    return hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def stripe_event(kind, obj, event_id="evt_1", created=int(NOW) - 5):
    return json.dumps({"id": event_id, "type": kind, "created": created, "livemode": False, "data": {"object": obj}}).encode()


class RecordingTransport:
    def __init__(self, status=200, body=None):
        self.calls, self.status, self.body = [], status, body if body is not None else {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}

    def __call__(self, method, url, headers=None, form=None, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "form": form, "body": body})
        return {"status": self.status, "headers": {}, "body": self.body}


def provider(transport=None, tolerance=300):
    return StripePaymentProvider("sk_test_x", SECRET, transport=transport, clock=lambda: NOW, tolerance=tolerance)


class Signatures(unittest.TestCase):
    body = stripe_event("invoice.paid", {"subscription_details": {"metadata": {"workspace_id": "w"}}})

    def test_valid_signature_is_accepted(self):
        event = provider().parse_webhook(f"t={int(NOW)},v1={sign(self.body)}", self.body)
        self.assertEqual((event["id"], event["type"], event["workspaceId"]), ("evt_1", "subscription.updated", "w"))

    def test_any_matching_v1_is_accepted(self):
        header = f"t={int(NOW)},v1={'0' * 64},v1={sign(self.body)},v0=ignored"
        self.assertEqual(provider().parse_webhook(header, self.body)["id"], "evt_1")

    def test_invalid_signature_wrong_secret_or_body_is_401(self):
        for header in ("", "nonsense", f"t={int(NOW)}", f"v1={sign(self.body)}", f"t={int(NOW)},v1={sign(self.body, secret='other')}", f"t={int(NOW)},v1={sign(b'{}')}"):
            with self.assertRaises(AlphaError) as ctx:
                provider().parse_webhook(header, self.body)
            self.assertEqual(ctx.exception.status, 401, header)
        with self.assertRaises(AlphaError):
            provider().parse_webhook(None, self.body)
        with self.assertRaises(AlphaError):
            provider().parse_webhook(f"t={int(NOW)},v1={sign(self.body)}", self.body.decode())

    def test_expired_timestamp_is_401_even_with_valid_hmac(self):
        old = int(NOW) - 301
        with self.assertRaises(AlphaError) as ctx:
            provider().parse_webhook(f"t={old},v1={sign(self.body, ts=old)}", self.body)
        self.assertEqual(ctx.exception.status, 401)
        future = int(NOW) + 301
        with self.assertRaises(AlphaError):
            provider().parse_webhook(f"t={future},v1={sign(self.body, ts=future)}", self.body)
        edge = int(NOW) - 300
        self.assertEqual(provider().parse_webhook(f"t={edge},v1={sign(self.body, ts=edge)}", self.body)["id"], "evt_1")

    def test_invalid_json_or_shape_is_400(self):
        for raw in (b"{not json", b"[]", b'{"id":"e"}'):
            with self.assertRaises(AlphaError) as ctx:
                provider().parse_webhook(f"t={int(NOW)},v1={sign(raw)}", raw)
            self.assertEqual(ctx.exception.status, 400)


class EventMapping(unittest.TestCase):
    def parse(self, kind, obj, **kw):
        body = stripe_event(kind, obj, **kw)
        return provider().parse_webhook(f"t={int(NOW)},v1={sign(body)}", body)

    def test_mapping_table_is_explicit(self):
        # charge.refunded and customer.subscription.trial_will_end are recorded for the founder billing events (057) and change no state.
        self.assertEqual(set(EVENT_TYPES), {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted", "invoice.payment_failed", "invoice.paid",
                                            "charge.refunded", "customer.subscription.trial_will_end"})
        self.assertEqual(set(SUBSCRIPTION_STATUS_EVENTS), {"active", "trialing", "past_due", "unpaid", "canceled", "incomplete_expired"})

    def test_checkout_session_completed(self):
        event = self.parse("checkout.session.completed", {"mode": "subscription", "client_reference_id": "ws-1", "customer": "cus_1", "subscription": {"id": "sub_1"}, "metadata": {"plan_terms_id": "studio-v1", "workspace_id": "ws-1"}})
        self.assertEqual(event["type"], "subscription.activated")
        self.assertEqual((event["workspaceId"], event["customerId"], event["subscriptionId"], event["planTermsId"]), ("ws-1", "cus_1", "sub_1", "studio-v1"))
        self.assertEqual(event["createdAt"], float(int(NOW) - 5))
        payment = self.parse("checkout.session.completed", {"mode": "payment", "client_reference_id": "ws-1"})
        self.assertEqual((payment["type"], payment["workspaceId"]), ("checkout.session.completed", ""))

    def test_subscription_created_and_updated_by_status(self):
        base = {"id": "sub_9", "customer": "cus_9", "metadata": {"workspace_id": "ws-9", "plan_terms_id": "assist-v1"}, "items": {"data": [{"price": {"id": "price_abc"}, "current_period_end": 1_800_100_000}]}, "cancel_at_period_end": True}
        expected = {"active": "subscription.activated", "trialing": "subscription.activated", "past_due": "invoice.payment_failed", "unpaid": "subscription.expired", "canceled": "subscription.cancelled", "incomplete_expired": "subscription.cancelled"}
        for kind in ("customer.subscription.created", "customer.subscription.updated"):
            for status, internal in expected.items():
                event = self.parse(kind, {**base, "status": status})
                self.assertEqual(event["type"], internal, (kind, status))
                self.assertEqual((event["workspaceId"], event["planTermsId"], event["priceId"], event["customerId"], event["subscriptionId"]), ("ws-9", "assist-v1", "price_abc", "cus_9", "sub_9"))
                self.assertEqual(event["currentPeriodEnd"], 1_800_100_000.0)
                self.assertTrue(event["cancelAtPeriodEnd"])
        legacy = self.parse("customer.subscription.updated", {**base, "status": "active", "current_period_end": 1_800_200_000, "items": {"data": [{"price": {"id": "price_abc"}}]}})
        self.assertEqual(legacy["currentPeriodEnd"], 1_800_200_000.0)
        incomplete = self.parse("customer.subscription.updated", {**base, "status": "incomplete"})
        self.assertEqual((incomplete["type"], incomplete["workspaceId"]), ("customer.subscription.updated", ""))
        without_terms = self.parse("customer.subscription.updated", {**base, "status": "active", "metadata": {"workspace_id": "ws-9"}})
        self.assertNotIn("planTermsId", without_terms)
        self.assertEqual(without_terms["priceId"], "price_abc")

    def test_subscription_deleted(self):
        event = self.parse("customer.subscription.deleted", {"id": "sub_2", "status": "canceled", "customer": {"id": "cus_2"}, "metadata": {"workspace_id": "ws-2"}})
        self.assertEqual((event["type"], event["workspaceId"], event["subscriptionId"], event["customerId"]), ("subscription.cancelled", "ws-2", "sub_2", "cus_2"))

    def test_invoice_payment_failed_both_shapes_and_missing_metadata(self):
        legacy = self.parse("invoice.payment_failed", {"customer": "cus_3", "subscription": "sub_3", "subscription_details": {"metadata": {"workspace_id": "ws-3"}}})
        self.assertEqual((legacy["type"], legacy["workspaceId"], legacy["customerId"], legacy["subscriptionId"]), ("invoice.payment_failed", "ws-3", "cus_3", "sub_3"))
        modern = self.parse("invoice.payment_failed", {"customer": "cus_4", "parent": {"type": "subscription_details", "subscription_details": {"subscription": "sub_4", "metadata": {"workspace_id": "ws-4", "plan_terms_id": "studio-v1"}}}})
        self.assertEqual((modern["workspaceId"], modern["subscriptionId"], modern["planTermsId"]), ("ws-4", "sub_4", "studio-v1"))
        orphan = self.parse("invoice.payment_failed", {"customer": "cus_5"})
        self.assertEqual((orphan["type"], orphan["workspaceId"]), ("invoice.payment_failed", ""))

    def test_invoice_paid_maps_to_updated_with_period_end(self):
        event = self.parse("invoice.paid", {"customer": "cus_6", "subscription": "sub_6", "subscription_details": {"metadata": {"workspace_id": "ws-6"}}, "lines": {"data": [{"period": {"start": 1, "end": 1_800_300_000}}]}})
        self.assertEqual((event["type"], event["workspaceId"], event["currentPeriodEnd"]), ("subscription.updated", "ws-6", 1_800_300_000.0))

    def test_unknown_event_keeps_raw_type_and_blank_workspace(self):
        event = self.parse("charge.succeeded", {"id": "ch_1", "metadata": {"workspace_id": "ws-7"}}, event_id="evt_x")
        self.assertEqual(event, {"id": "evt_x", "type": "charge.succeeded", "createdAt": float(int(NOW) - 5), "workspaceId": ""})
        self.assertIsNone(Billing.TRANSITIONS.get(event["type"]))

    def test_missing_created_falls_back_to_clock(self):
        body = json.dumps({"id": "evt_nc", "type": "invoice.paid", "livemode": False, "data": {"object": {}}}).encode()
        self.assertEqual(provider().parse_webhook(f"t={int(NOW)},v1={sign(body)}", body)["createdAt"], NOW)


class Sessions(unittest.TestCase):
    def test_checkout_form_headers_and_response(self):
        transport = RecordingTransport()
        result = provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://app/billing?ok=1", cancel_url="https://app/pricing", customer_email="o@example.com", idempotency_key="ws-1:studio-v1:1")
        self.assertEqual(result, {"url": "https://checkout.stripe.com/c/pay/cs_1", "sessionId": "cs_1"})
        call = transport.calls[0]
        self.assertEqual((call["method"], call["url"]), ("POST", "https://api.stripe.com/v1/checkout/sessions"))
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertEqual(call["headers"]["Idempotency-Key"], "ws-1:studio-v1:1")
        self.assertIsNone(call["body"])
        form = call["form"]
        for key, value in {"mode": "subscription", "line_items[0][price]": "price_1", "line_items[0][quantity]": "1", "client_reference_id": "ws-1", "subscription_data[metadata][workspace_id]": "ws-1", "subscription_data[metadata][plan_terms_id]": "studio-v1", "metadata[workspace_id]": "ws-1", "metadata[plan_terms_id]": "studio-v1", "success_url": "https://app/billing?ok=1", "cancel_url": "https://app/pricing", "customer_email": "o@example.com", "allow_promotion_codes": "true"}.items():
            self.assertEqual(form.get(key), value, key)
        self.assertNotIn("customer", form)

    def test_checkout_prefers_existing_customer(self):
        transport = RecordingTransport()
        provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://a", cancel_url="https://b", customer_id="cus_1", customer_email="o@example.com", idempotency_key="k")
        form = transport.calls[0]["form"]
        self.assertEqual(form["customer"], "cus_1")
        self.assertNotIn("customer_email", form)

    def test_checkout_validates_inputs_before_any_call(self):
        transport = RecordingTransport()
        with self.assertRaises(AlphaError) as ctx:
            provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="", price_id="price_1", success_url="https://a", cancel_url="https://b", customer_id="cus_1", idempotency_key="k")
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(AlphaError):
            provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://a", cancel_url="https://b", idempotency_key="k")
        self.assertEqual(transport.calls, [])

    def test_non_200_is_502_without_leaking_body(self):
        transport = RecordingTransport(400, {"error": {"type": "invalid_request_error", "code": "resource_missing", "message": "No such price: 'price_1' for sk_test_x SECRET"}})
        with self.assertRaises(AlphaError) as ctx:
            provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://a", cancel_url="https://b", customer_id="cus_1", idempotency_key="k")
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(str(ctx.exception), "Checkout could not be started. (stripe: resource_missing)")
        weird = RecordingTransport(500, {"error": {"message": "sk_test_x leaked", "code": "<script>"}})
        with self.assertRaises(AlphaError) as ctx:
            provider(weird).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://a", cancel_url="https://b", customer_id="cus_1", idempotency_key="k")
        self.assertEqual(str(ctx.exception), "Checkout could not be started.")
        missing_url = RecordingTransport(200, {"id": "cs_1"})
        with self.assertRaises(AlphaError) as ctx:
            provider(missing_url).create_checkout_session(workspace_id="ws-1", plan_terms_id="studio-v1", price_id="price_1", success_url="https://a", cancel_url="https://b", customer_id="cus_1", idempotency_key="k")
        self.assertEqual(ctx.exception.status, 502)

    def test_portal_session(self):
        transport = RecordingTransport(200, {"id": "bps_1", "url": "https://billing.stripe.com/p/session/x"})
        self.assertEqual(provider(transport).create_portal_session(customer_id="cus_1", return_url="https://app/billing"), {"url": "https://billing.stripe.com/p/session/x"})
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.stripe.com/v1/billing_portal/sessions")
        self.assertEqual(call["form"], {"customer": "cus_1", "return_url": "https://app/billing"})
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk_test_x")
        self.assertNotIn("Idempotency-Key", call["headers"])
        with self.assertRaises(AlphaError) as ctx:
            provider(RecordingTransport(404, {"error": {"code": "resource_missing"}})).create_portal_session(customer_id="cus_1", return_url="https://app/billing")
        self.assertEqual(ctx.exception.status, 502)
        with self.assertRaises(AlphaError) as ctx:
            provider(transport).create_portal_session(customer_id="", return_url="https://app/billing")
        self.assertEqual(ctx.exception.status, 400)

    def test_missing_credentials_refused(self):
        with self.assertRaises(AlphaError) as ctx:
            StripePaymentProvider("", SECRET)
        self.assertEqual(ctx.exception.status, 503)


class StubCursor:
    """Answers SELECTs by SQL substring; records every statement with its parameters."""

    def __init__(self, answers):
        self.answers, self.executed, self._pending = answers, [], None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._pending = None
        for needle, rows in self.answers.items():
            if needle in sql:
                self._pending = list(rows)
                break

    def fetchone(self):
        if not self._pending:
            return None
        return self._pending.pop(0)

    def fetchall(self):
        rows, self._pending = self._pending or [], None
        return rows


ENT = {"members": 1, "connectedAccounts": 3, "writingBatches": 100, "mediaCredits": 0, "storageMb": 1000}


class WebhookResolution(unittest.TestCase):
    def signed(self, kind, obj, event_id="evt_r1"):
        body = stripe_event(kind, obj, event_id=event_id)
        return f"t={int(NOW)},v1={sign(body)}", body

    def test_price_id_resolves_active_plan_terms_and_applies(self):
        applied = []
        cur = StubCursor({"WHERE provider_price_id=%s AND status='active'": [("assist-v1",)], "SELECT entitlements FROM public.pr_plan_terms WHERE id=%s": [(ENT,)]})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW, on_applied=lambda event, status: applied.append((event["planTermsId"], status)))
        sig, body = self.signed("customer.subscription.updated", {"id": "sub_1", "status": "active", "customer": "cus_1", "metadata": {"workspace_id": "ws-1"}, "items": {"data": [{"price": {"id": "price_live"}, "current_period_end": 1_800_100_000}]}})
        result = billing.process_webhook(cur, sig, body)
        self.assertEqual((result["outcome"], result["status"]), ("applied", "active"))
        self.assertEqual(applied, [("assist-v1", "active")])
        lookups = [p for s, p in cur.executed if "provider_price_id" in s]
        self.assertEqual(lookups, [("price_live",)])
        sub_insert = next(p for s, p in cur.executed if "INSERT INTO public.pr_subscriptions" in s)
        self.assertEqual((sub_insert[0], sub_insert[1], sub_insert[2], sub_insert[3], sub_insert[4], sub_insert[5]), ("ws-1", "assist-v1", "stripe", "cus_1", "sub_1", "active"))
        self.assertTrue(any("INSERT INTO public.pr_entitlements" in s for s, _ in cur.executed))
        events_insert = next(p for s, p in cur.executed if "INSERT INTO public.pr_billing_events" in s)
        self.assertEqual((events_insert[0], events_insert[1], events_insert[2], events_insert[5]), ("stripe", "evt_r1", "subscription.activated", "applied"))

    def test_unbound_or_proposed_price_falls_back_without_entitlement(self):
        cur = StubCursor({})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW)
        sig, body = self.signed("customer.subscription.updated", {"id": "sub_1", "status": "active", "metadata": {"workspace_id": "ws-1"}, "items": {"data": [{"price": {"id": "price_proposed"}}]}})
        result = billing.process_webhook(cur, sig, body)
        self.assertEqual(result["outcome"], "applied")
        sub_insert = next(p for s, p in cur.executed if "INSERT INTO public.pr_subscriptions" in s)
        self.assertEqual(sub_insert[1], "trial-v1")
        self.assertFalse(any("INSERT INTO public.pr_entitlements" in s for s, _ in cur.executed))

    def test_explicit_plan_terms_id_skips_price_lookup(self):
        cur = StubCursor({"SELECT entitlements FROM public.pr_plan_terms WHERE id=%s": [(ENT,)]})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW)
        sig, body = self.signed("customer.subscription.created", {"id": "sub_1", "status": "active", "metadata": {"workspace_id": "ws-1", "plan_terms_id": "studio-v1"}, "items": {"data": [{"price": {"id": "price_live"}}]}})
        self.assertEqual(billing.process_webhook(cur, sig, body)["outcome"], "applied")
        self.assertFalse(any("provider_price_id" in s for s, _ in cur.executed))

    def test_unhandled_stripe_event_is_ignored_and_callback_not_called(self):
        applied = []
        cur = StubCursor({})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW, on_applied=lambda e, s: applied.append(e))
        sig, body = self.signed("charge.refunded", {"id": "ch_1"})
        result = billing.process_webhook(cur, sig, body)
        self.assertEqual((result["outcome"], result["status"]), ("ignored", None))
        self.assertEqual(applied, [])
        self.assertFalse(any("pr_subscriptions" in s for s, _ in cur.executed))
        events_insert = next(p for s, p in cur.executed if "INSERT INTO public.pr_billing_events" in s)
        self.assertEqual((events_insert[2], events_insert[5]), ("charge.refunded", "ignored"))

    def test_failing_callback_never_breaks_the_webhook(self):
        def boom(event, status):
            raise RuntimeError("mailer down")
        cur = StubCursor({"SELECT entitlements FROM public.pr_plan_terms WHERE id=%s": [(ENT,)]})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW, on_applied=boom)
        sig, body = self.signed("checkout.session.completed", {"mode": "subscription", "client_reference_id": "ws-1", "customer": "cus_1", "subscription": "sub_1", "metadata": {"plan_terms_id": "studio-v1"}})
        self.assertEqual(billing.process_webhook(cur, sig, body)["outcome"], "applied")

    def test_stale_and_rejected_do_not_invoke_callback(self):
        applied = []
        stale = StubCursor({"SELECT extract(epoch from last_event_at)": [(NOW + 100,)]})
        billing = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW, on_applied=lambda e, s: applied.append(e))
        sig, body = self.signed("customer.subscription.deleted", {"id": "sub_1", "status": "canceled", "metadata": {"workspace_id": "ws-1"}})
        self.assertEqual(billing.process_webhook(stale, sig, body)["outcome"], "stale")
        rejected = StubCursor({})
        sig, body = self.signed("checkout.session.completed", {"mode": "subscription", "client_reference_id": "ws-1", "metadata": {"plan_terms_id": "not-a-plan"}})
        self.assertEqual(billing.process_webhook(rejected, sig, body)["outcome"], "rejected")
        self.assertEqual(applied, [])


class Availability(unittest.TestCase):
    def test_stripe_with_active_bound_terms_and_customer(self):
        cur = StubCursor({"coalesce(provider_price_id,'')<>''": [(1,)], "SELECT provider_customer_id FROM public.pr_subscriptions": [("cus_1",)]})
        block = Billing(provider=provider(), ledger=Ledger()).availability(cur, "ws-1")
        self.assertEqual(block, {"provider": "stripe", "checkoutAvailable": True, "portalAvailable": True})
        self.assertIn(("ws-1", "stripe"), [p for _, p in cur.executed])

    def test_stripe_without_active_terms_or_customer(self):
        cur = StubCursor({"SELECT provider_customer_id FROM public.pr_subscriptions": [(None,)]})
        block = Billing(provider=provider(), ledger=Ledger()).availability(cur, "ws-1")
        self.assertEqual(block, {"provider": "stripe", "checkoutAvailable": False, "portalAvailable": False})

    def test_fixture_provider_never_offers_checkout(self):
        cur = StubCursor({"coalesce(provider_price_id,'')<>''": [(1,)], "SELECT provider_customer_id FROM public.pr_subscriptions": [("cus_fixture",)]})
        block = Billing(ledger=Ledger()).availability(cur, "ws-1")
        self.assertEqual(block, {"provider": "fixture", "checkoutAvailable": False, "portalAvailable": False})



class VariantMetadata(unittest.TestCase):
    def test_creator_checkout_binds_variant_to_session_and_subscription(self):
        self.assertIn("price_variant_id", inspect.signature(StripePaymentProvider.create_checkout_session).parameters,
                      "missing trusted variant checkout binding")
        transport = RecordingTransport()
        provider(transport).create_checkout_session(workspace_id="ws-1", plan_terms_id="creator-v1",
            price_variant_id="creator-59-v1", price_id="price_synthetic_59", success_url="https://app/ok",
            cancel_url="https://app/cancel", customer_email="o@example.com", idempotency_key="variant-key")
        form = transport.calls[0]["form"]
        self.assertEqual(form["metadata[price_variant_id]"], "creator-59-v1")
        self.assertEqual(form["subscription_data[metadata][price_variant_id]"], "creator-59-v1")
        self.assertNotIn("payment_method_types", form)

    def test_signed_subscription_and_invoice_recover_variant_and_price(self):
        meta = {"workspace_id": "ws-1", "plan_terms_id": "creator-v1", "price_variant_id": "creator-49-v1"}
        objects = [
            ("customer.subscription.updated", {"id": "sub_1", "status": "active", "metadata": meta,
                "items": {"data": [{"price": "price_synthetic_49"}]}}),
            ("invoice.paid", {"id": "in_1", "status": "paid", "amount_paid": 4900, "currency": "usd",
                "parent": {"subscription_details": {"subscription": "sub_1", "metadata": meta}},
                "lines": {"data": [{"pricing": {"price_details": {"price": "price_synthetic_49"}},
                                     "period": {"start": 100, "end": 200}}]}}),
            ("checkout.session.completed", {"mode": "subscription", "client_reference_id": "ws-1", "metadata": meta})]
        for kind, obj in objects:
            with self.subTest(kind=kind):
                body = stripe_event(kind, obj)
                mapped = provider().parse_webhook(f"t={int(NOW)},v1={sign(body)}", body)
                self.assertEqual(mapped.get("priceVariantId"), "creator-49-v1")
                if kind != "checkout.session.completed":
                    self.assertEqual(mapped.get("priceId"), "price_synthetic_49")

    def test_conflicting_signed_checkout_workspace_is_marked_invalid(self):
        mapped = StripePaymentProvider.map_event("evt", "checkout.session.completed", NOW,
            {"mode": "subscription", "client_reference_id": "w2", "metadata": {"workspace_id": "w1"}})
        self.assertTrue(mapped.get("metadataConflict"), "must not silently prefer a conflicting workspace")

    def test_conflicting_invoice_metadata_or_multi_price_cannot_be_silently_selected(self):
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"metadata": {"price_variant_id": "creator-79-v1"},
             "subscription_details": {"metadata": {"price_variant_id": "creator-49-v1"}},
             "lines": {"data": [{"price": "price_a"}, {"price": "price_b"}]}})
        self.assertTrue(mapped.get("metadataConflict"))


    def test_invoice_subscription_references_cannot_disagree(self):
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"subscription": "sub_a", "parent": {"subscription_details": {"subscription": "sub_b"}}})
        self.assertTrue(mapped.get("metadataConflict"))

    def test_old_and_new_price_carriers_cannot_disagree(self):
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"lines": {"data": [{"price": "price_a", "pricing": {"price_details": {"price": "price_b"}}}]}})
        self.assertTrue(mapped.get("priceConflict"))


    def test_review_f3_invoice_keeps_each_price_period_and_subscription_line_kind(self):
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"subscription": "sub_1", "lines": {"data": [
                {"parent": {"type": "invoice_item_details"}, "pricing": {"price_details": {"price": "price_addon"}}, "period": {"start": 10, "end": 20}},
                {"type": "subscription", "subscription": "sub_1", "price": "price_plan", "period": {"start": 100, "end": 200}}]}})
        self.assertEqual(mapped.get("invoicePriceLines"), [
            {"priceIds": ["price_addon"], "kind": "addon", "subscriptionId": None, "subscriptionIds": [], "periodStart": 10.0, "periodEnd": 20.0},
            {"priceIds": ["price_plan"], "kind": "subscription", "subscriptionId": "sub_1", "subscriptionIds": ["sub_1"], "periodStart": 100.0, "periodEnd": 200.0}])


    def test_review_f4_modern_foreign_subscription_is_preserved_and_rejected(self):
        for parent_kind in ("subscription_item_details", "invoice_item_details"):
            for reference in ("sub_b", {"id": "sub_b"}):
                with self.subTest(parent_kind=parent_kind, reference=reference):
                    body = stripe_event("invoice.paid", {"subscription": "sub_a", "lines": {"data": [{
                        "parent": {"type": parent_kind, parent_kind: {"subscription": reference}},
                        "pricing": {"price_details": {"price": "price_plan"}}, "period": {"start": 100, "end": 200}}]}})
                    mapped = provider().parse_webhook(f"t={int(NOW)},v1={sign(body)}", body)
                    self.assertTrue(mapped.get("metadataConflict"), "modern line B cannot fund invoice A")
                    self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionId"), "sub_b")
                    self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionIds"), ["sub_b"])

    def test_review_f4_conflicting_old_nested_and_invoice_carriers_are_rejected(self):
        for parent_kind in ("subscription_item_details", "invoice_item_details"):
            for old, nested in (("sub_a", "sub_b"), ("sub_b", "sub_a")):
                with self.subTest(parent_kind=parent_kind, old=old, nested=nested):
                    mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
                        {"subscription": "sub_a", "lines": {"data": [{"subscription": old,
                         "parent": {"type": parent_kind, parent_kind: {"subscription": nested}}}]}})
                    self.assertTrue(mapped.get("metadataConflict"), "neither carrier may hide the other")
                    self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionIds"), ["sub_a", "sub_b"])
                    self.assertIsNone(mapped["invoicePriceLines"][0].get("subscriptionId"))
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"subscription": "sub_a", "lines": {"data": [{"parent": {"type": "subscription_item_details",
                "subscription_item_details": {"subscription": "sub_a"}, "invoice_item_details": {"subscription": "sub_b"}}}]}})
        self.assertTrue(mapped.get("metadataConflict"), "conflicting nested parent carriers cannot hide each other")
        self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionIds"), ["sub_a", "sub_b"])
        mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
            {"subscription": "sub_a", "parent": {"subscription_details": {"subscription": "sub_b"}},
             "lines": {"data": [{"parent": {"type": "subscription_item_details", "subscription_item_details": {"subscription": "sub_a"}}}]}})
        self.assertTrue(mapped.get("metadataConflict"), "matching line must not hide invoice carrier conflict")

    def test_review_f4_matching_old_modern_and_absent_carriers_stay_compatible(self):
        for parent_kind in ("subscription_item_details", "invoice_item_details"):
            for old, nested in ((None, "sub_a"), ("sub_a", None), ("sub_a", {"id": "sub_a"}), (None, None)):
                with self.subTest(parent_kind=parent_kind, old=old, nested=nested):
                    line = {"price": "price_plan", "period": {"start": 100, "end": 200}}
                    if old is not None:
                        line["subscription"] = old
                    if nested is not None:
                        line["parent"] = {"type": parent_kind, parent_kind: {"subscription": nested}}
                    mapped = StripePaymentProvider.map_event("evt", "invoice.paid", NOW,
                        {"subscription": "sub_a", "lines": {"data": [line]}})
                    self.assertFalse(mapped.get("metadataConflict", False))
                    self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionId"), "sub_a" if old or nested else None)
                    self.assertEqual(mapped["invoicePriceLines"][0].get("subscriptionIds"), ["sub_a"] if old or nested else [])
                    self.assertEqual(mapped["invoicePriceLines"][0]['kind'], ('subscription' if parent_kind == 'subscription_item_details' else 'addon') if nested else 'unknown')
                    self.assertEqual((mapped["periodStart"], mapped["currentPeriodEnd"]), (100, 200))

if __name__ == "__main__":
    unittest.main()
