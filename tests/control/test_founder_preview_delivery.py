"""Focused, network-forbidden tests of the Founder Demo delivery adapter."""
import copy
import json
import unittest
from unittest.mock import patch

from rafii_control.auth import ControlError
from rafii_control.founder_preview_delivery import delivery_action, email_preview


class FounderPreviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.state = {"mode": "demo", "timeZone": "America/Indiana/Indianapolis", "contactAttempts": []}
        self.counter = 0

    def action(self, operation="start", channel="call", source="report-1", attempt=None,
               outcome=None, at="2026-10-01T14:00:00Z", request=None):
        self.counter += 1
        payload = dict(operation=operation, channel=channel, sourceId=source)
        if attempt is not None:
            payload["attemptId"] = attempt["id"]
        if outcome is not None:
            payload["outcome"] = outcome
        return delivery_action(self.state, payload, request_id=request or f"req-{self.counter}", now=at)["attempt"]

    def fails(self, code, callable_action):
        before = copy.deepcopy(self.state)
        with self.assertRaises(ControlError) as caught:
            callable_action()
        self.assertEqual(caught.exception.code, "PREVIEW_DELIVERY_" + code)
        self.assertEqual(self.state, before, "rejected action must leave Demo state untouched")

    def test_call_progress_reuses_receipt_and_never_acknowledges_completion(self):
        first = self.action()
        live = self.action("advance", attempt=first, outcome="live", at="2026-10-01T14:00:30Z")
        self.assertEqual(live["state"], "live")
        completed = self.action("advance", attempt=live, outcome="completed", at="2026-10-01T14:01:00Z")
        self.assertEqual(completed["receipt"]["state"], "completed")
        self.assertIsNone(completed["receipt"]["call_ref"])
        self.assertFalse(completed["acknowledged"])
        self.assertIsNone(completed["acknowledgedAt"])
        acknowledged = self.action("acknowledge", attempt=completed, at="2026-10-01T14:02:00Z")
        self.assertTrue(acknowledged["acknowledged"])
        self.assertEqual(acknowledged["acknowledgement"], "acknowledged")

    def test_duplicate_request_cannot_repeat_or_change_effect(self):
        started = self.action(request="same-request")
        replay = self.action(request="same-request", at="2026-10-01T14:01:00Z")
        self.assertEqual(started, replay)
        self.assertEqual(len(self.state["contactAttempts"]), 1)
        self.fails("CONFLICT", lambda: self.action(source="other", request="same-request"))
        self.fails("CONFLICT", lambda: self.action("cancel", attempt=started, request="same-request"))

    def test_replay_capacity_cannot_prevent_terminal_call_cleanup(self):
        first=self.action()
        for i in range(255): self.action('advance',attempt=first,outcome='live')
        ended=self.action('advance',attempt=first,outcome='completed')
        self.assertEqual(ended['state'],'completed')
        self.assertFalse(ended['acknowledged'])
        acknowledged=self.action('acknowledge',attempt=ended)
        self.assertTrue(acknowledged['acknowledged'])

    def test_duplicate_start_cannot_bypass_explicit_retry(self):
        first = self.action()
        self.action("advance", attempt=first, outcome="failed")
        repeated = self.action(at="2026-10-02T14:00:00Z")
        self.assertEqual(repeated["id"], first["id"])
        self.assertEqual(repeated["state"], "failed")
        self.assertEqual(len(self.state["contactAttempts"]), 1)

    def test_out_of_order_and_terminal_callbacks_never_regress(self):
        first = self.action()
        self.action("advance", attempt=first, outcome="live", at="2026-10-01T14:01:00Z")
        self.fails("STALE_EVENT", lambda: self.action("advance", attempt=first, outcome="ringing"))
        stale = self.action("advance", attempt=first, outcome="ringing", at="2026-10-01T14:02:00Z")
        self.assertEqual(stale["state"], "live")
        completed = self.action("advance", attempt=first, outcome="completed", at="2026-10-01T14:03:00Z")
        for incoming in ("answered", "failed", "ambiguous"):
            result = self.action("advance", attempt=completed, outcome=incoming, at="2026-10-01T14:04:00Z")
            self.assertEqual(result["state"], "completed")

    def test_ambiguity_holds_active_slot_until_definitive_reconciliation(self):
        first = self.action()
        self.action("advance", attempt=first, outcome="live")
        ambiguous = self.action("advance", attempt=first, outcome="ambiguous")
        self.assertEqual(ambiguous["state"], "ambiguous")
        for operation, outcome in (("advance", "failed"), ("retry", None), ("cancel", None)):
            self.fails("AMBIGUOUS", lambda op=operation, out=outcome: self.action(op, attempt=first, outcome=out))
        self.fails("CALL_ACTIVE", lambda: self.action(source="incident-2"))
        self.fails("DEFINITIVE_OUTCOME_REQUIRED", lambda: self.action("reconcile", attempt=first, outcome="ringing"))
        settled = self.action("reconcile", attempt=first, outcome="failed")
        self.assertEqual(settled["reconciliation"], "explicit_simulated_evidence")
        retried = self.action("retry", attempt=first, at="2026-10-01T14:05:00Z")
        self.assertEqual(retried["attemptNumber"], 2)
        self.assertEqual(retried["retryOf"], first["id"])

    def test_retry_cooldown_starts_at_failure_and_total_attempts_are_two(self):
        first = self.action()
        self.action("advance", attempt=first, outcome="no_answer", at="2026-10-01T14:01:00Z")
        self.fails("COOLDOWN", lambda: self.action("retry", attempt=first, at="2026-10-01T14:05:59Z"))
        second = self.action("retry", attempt=first, at="2026-10-01T14:06:00Z", request="retry-request")
        replay = self.action("retry", attempt=first, at="2026-10-01T14:07:00Z", request="retry-request")
        self.assertEqual(second, replay)
        self.action("advance", attempt=second, outcome="failed", at="2026-10-01T14:08:00Z")
        self.fails("RETRY_LIMIT", lambda: self.action("retry", attempt=second, at="2026-10-02T14:00:00Z"))
        self.fails("RETRY_LIMIT", lambda: self.action("retry", attempt=first, at="2026-10-02T14:00:00Z"))

    def test_only_failed_or_no_answer_calls_are_retryable(self):
        for index, outcome in enumerate(("busy", "declined", "voicemail", "completed", "cancelled")):
            self.state["contactAttempts"] = []
            first = self.action(source=f"incident-{index}")
            self.action("advance", source=f"incident-{index}", attempt=first, outcome=outcome)
            self.fails("RETRY_NOT_ALLOWED", lambda: self.action("retry", source=f"incident-{index}", attempt=first, at="2026-10-02T14:00:00Z"))

    def test_one_active_call_and_daily_cap_span_all_sources(self):
        first = self.action()
        self.fails("CALL_ACTIVE", lambda: self.action(source="report-2"))
        self.action("advance", attempt=first, outcome="failed")
        second = self.action(source="report-2")
        self.action("advance", source="report-2", attempt=second, outcome="completed")
        self.fails("DAILY_LIMIT", lambda: self.action(source="report-3"))
        third = self.action(source="report-3", at="2026-10-02T14:00:00Z")
        self.assertEqual(third["state"], "requested")

    def test_daily_cap_uses_founder_local_day_not_utc_day(self):
        first = self.action(at="2026-10-01T23:00:00Z")
        self.action("advance", attempt=first, outcome="failed", at="2026-10-01T23:01:00Z")
        second = self.action(source="report-2", at="2026-10-02T03:59:00Z")
        self.action("advance", source="report-2", attempt=second, outcome="failed", at="2026-10-02T03:59:30Z")
        self.fails("DAILY_LIMIT", lambda: self.action(source="report-3", at="2026-10-02T03:59:59Z"))
        self.assertEqual(self.action(source="report-3", at="2026-10-02T04:00:00Z")["state"], "requested")

    def test_quiet_hours_gate_scheduled_calls_and_automatic_retry(self):
        self.state["reports"] = [{"id": "report-1", "deliveryMode": "scheduled"}]
        self.fails("QUIET_HOURS", lambda: self.action(at="2026-10-02T03:00:00Z"))
        first = self.action(at="2026-10-01T23:00:00Z")
        self.action("advance", attempt=first, outcome="failed", at="2026-10-01T23:01:00Z")
        self.fails("QUIET_HOURS", lambda: self.action("retry", attempt=first, at="2026-10-02T03:00:00Z"))
        self.assertEqual(self.action("retry", attempt=first, at="2026-10-02T12:00:00Z")["state"], "requested")

    def test_source_and_channel_bind_every_attempt_operation(self):
        first = self.action()
        for operation in ("advance", "reconcile", "retry", "acknowledge", "cancel"):
            outcome = "failed" if operation in ("advance", "reconcile") else None
            self.fails("NOT_FOUND", lambda op=operation, out=outcome: self.action(op, source="other-source", attempt=first, outcome=out))
        self.fails("NOT_FOUND", lambda: self.action("advance", channel="email", attempt=first, outcome="delivered"))

    def test_email_acceptance_delivery_and_acknowledgement_are_separate(self):
        first = self.action(channel="email")
        self.assertEqual(first["state"], "queued")
        accepted = self.action("advance", channel="email", attempt=first, outcome="provider_accepted")
        self.assertFalse(accepted["acknowledged"])
        self.fails("ACKNOWLEDGEMENT_NOT_ALLOWED", lambda: self.action("acknowledge", channel="email", attempt=first))
        self.fails("CANNOT_CANCEL", lambda: self.action("cancel", channel="email", attempt=first))
        self.assertEqual(self.action("advance", channel="email", attempt=first, outcome="queued")["state"], "provider_accepted")
        delivered = self.action("advance", channel="email", attempt=first, outcome="delivered")
        self.assertFalse(delivered["acknowledged"])
        self.assertEqual(self.action("advance", channel="email", attempt=first, outcome="failed")["state"], "delivered")
        self.assertTrue(self.action("acknowledge", channel="email", attempt=first)["acknowledged"])

    def test_email_failure_retry_and_suppression_never_dispatch(self):
        first = self.action(channel="email")
        self.action("advance", channel="email", attempt=first, outcome="failed")
        second = self.action("retry", channel="email", attempt=first, at="2026-10-01T14:05:00Z")
        self.assertEqual(second["state"], "retrying")
        suppressed = self.action("cancel", channel="email", attempt=second, at="2026-10-01T14:05:00Z")
        self.assertEqual(suppressed["state"], "suppressed")
        self.fails("RETRY_NOT_ALLOWED", lambda: self.action("retry", channel="email", attempt=second, at="2026-10-02T14:00:00Z"))
        self.assertEqual(suppressed["providerCalls"], 0)
        self.assertEqual(suppressed["operationsCost"], "not_applicable")

    def test_email_uncertainty_requires_definitive_reconcile(self):
        first = self.action(channel="email")
        self.action("advance", channel="email", attempt=first, outcome="ambiguous")
        self.fails("AMBIGUOUS", lambda: self.action("retry", channel="email", attempt=first))
        self.fails("DEFINITIVE_OUTCOME_REQUIRED", lambda: self.action("reconcile", channel="email", attempt=first, outcome="provider_accepted"))
        delivered = self.action("reconcile", channel="email", attempt=first, outcome="delivered")
        self.assertFalse(delivered["acknowledged"])
        self.assertEqual(delivered["state"], "delivered")

    def test_payload_rejects_egress_fields_untrusted_ids_and_live_mode(self):
        payload = dict(operation="start", channel="call", sourceId="report-1")
        for key, value in (("destination", "+14155550123"), ("url", "https://provider.test"), ("providerKey", "secret"),
                           ("recipient", "private@example.test"), ("body", "private content")):
            self.fails("INVALID", lambda k=key, v=value: delivery_action(self.state, {**payload, k: v}, request_id="invalid", now="2026-10-01T14:00:00Z"))
        self.fails("INVALID", lambda: delivery_action(self.state, {**payload, "sourceId": "https://other"}, request_id="invalid", now="2026-10-01T14:00:00Z"))
        self.fails("INVALID", lambda: delivery_action(self.state, payload, request_id="valid", now="2026-10-01T14:00:00"))
        self.state["mode"] = "live"
        self.fails("DEMO_REQUIRED", lambda: self.action())

    def test_adapter_and_preview_make_no_socket_calls(self):
        with patch("socket.socket", side_effect=AssertionError("real network forbidden")), patch("socket.create_connection", side_effect=AssertionError("real network forbidden")):
            first = self.action()
            self.action("advance", attempt=first, outcome="completed")
            email = self.action(channel="email")
            self.action("advance", channel="email", attempt=email, outcome="delivered")
            result = email_preview({"id": "incident-1", "title": "Demo outage", "affectedCount": 500})
        self.assertFalse(result["externalDelivery"])
        self.assertEqual(result["providerCalls"], 0)

    def test_corrupt_attempt_state_cannot_release_active_call_guard(self):
        first = self.action()
        self.state["contactAttempts"][0]["state"] = "unrecognized"
        self.fails("STATE_INVALID", lambda: self.action(source="other"))
        self.state["contactAttempts"][0]["state"] = first["state"]
        self.state["contactAttempts"][0]["updatedAt"] = "not-a-timestamp"
        self.fails("STATE_INVALID", lambda: self.action(source="other"))
        self.state["contactAttempts"] = []
        self.action(channel="email")
        self.state["contactAttempts"][0]["state"] = ["queued"]
        self.fails("STATE_INVALID", lambda: self.action(source="other"))


class FounderEmailPreviewTests(unittest.TestCase):
    def test_original_payment_evidence_preserves_minor_units_without_private_fields(self):
        original = dict(invoiceId="invoice-demo-9", subscriptionId="subscription-demo-2", paymentId="payment-demo-7",
                        amountMinor=1234, currency="JPY")
        incident = dict(id="incident-payment", title="Simulated payment exception", affectedCount=1,
                        affectedRecords=[{**original, "name": "PRIVATE-NAME", "workspaceName": "PRIVATE-WORKSPACE",
                                          "body": "PRIVATE-BODY", "recipient": "PRIVATE-RECIPIENT", "url": "https://PRIVATE-URL.test"}],
                        known=["PRIVATE-INSTRUCTION"], logs=["PRIVATE-LOG"])
        preview = email_preview(incident)
        self.assertEqual(preview["paymentEvidence"], [original])
        self.assertIn("Original simulated evidence", preview["text"])
        self.assertIn("Invoice: invoice-demo-9", preview["text"])
        self.assertIn("Subscription: subscription-demo-2", preview["text"])
        self.assertIn("Payment: payment-demo-7", preview["text"])
        self.assertIn("Amount (minor units): 1234 JPY", preview["text"])
        self.assertNotIn("12.34", json.dumps(preview))
        self.assertNotIn("PRIVATE-", json.dumps(preview))
        self.assertFalse(preview["externalDelivery"])
        self.assertEqual(preview["providerCalls"], 0)

    def test_payment_evidence_is_bounded_and_invalid_references_fail_closed(self):
        original = dict(invoiceId="invoice-demo-9", subscriptionId="subscription-demo-2", paymentId="payment-demo-7",
                        amountMinor=3900, currency="USD")
        preview = email_preview(dict(id="incident-payment", affectedRecords=[original, {**original, "invoiceId": "invoice-extra"}]))
        self.assertEqual(preview["paymentEvidence"], [original])
        self.assertNotIn("invoice-extra", json.dumps(preview))
        self.assertIn("1 record shown", preview["text"])
        for change in ({"invoiceId": "https://private.test"}, {"subscriptionId": "owner@example.test"},
                       {"paymentId": "bad/id"}, {"amountMinor": True}, {"amountMinor": -1},
                       {"amountMinor": 10**12 + 1}, {"currency": "US"}, {"currency": "<b>USD</b>"}):
            with self.subTest(change=change), self.assertRaises(ControlError):
                email_preview(dict(id="incident-payment", affectedRecords=[{**original, **change}]))

    def test_recovery_preview_subject_is_explicitly_recovered_and_unsent(self):
        recovered = email_preview(dict(id="incident-recovery", state="resolved", title="Simulated outage"))
        self.assertIn("[Recovered]", recovered["subject"])
        self.assertIn("DEMO — simulated, not sent", recovered["subject"])
        self.assertIn("State: resolved", recovered["text"])
        self.assertEqual(recovered["impact"]["state"], "resolved")

    def test_private_fields_are_dropped_and_impact_text_is_escaped(self):
        incident = {"id": "incident-1", "title": '<script>alert("demo")</script>', "severity": "critical",
                    "affectedCount": 720, "state": "recovering", "observedAt": "2026-10-01T14:00:00Z",
                    "body": "PRIVATE-CUSTOMER-MESSAGE", "recipients": ["PRIVATE-RECIPIENT"],
                    "url": "https://PRIVATE-URL.test", "providerSecret": "PRIVATE-PROVIDER-KEY"}
        preview = email_preview(incident)
        output = json.dumps(preview)
        self.assertNotIn("PRIVATE-", output)
        self.assertNotIn("<script>", preview["html"])
        self.assertIn("&lt;script&gt;", preview["html"])
        self.assertEqual(set(preview["impact"]), {"id", "title", "severity", "affectedCount", "state", "observedAt"})
        self.assertEqual(preview["actionPath"], "/control/advanced")
        self.assertEqual(preview["url"], "https://rafii.invalid/app")
        self.assertEqual(preview["headers"], {})
        self.assertIn("DEMO — simulated, not sent", preview["subject"])
        self.assertTrue(preview["text"].startswith("DEMO — simulated, not sent"))
        self.assertIn('data-execution="simulation"', preview["html"])
        self.assertIn("DEMO — simulated, not sent", preview["html"])
        self.assertNotIn("<img", preview["html"])
        self.assertNotIn('href="https://', preview["html"])
        self.assertEqual(preview["rendererLinks"], "disabled_preview_only")

    def test_contact_like_title_values_cannot_become_a_destination(self):
        preview = email_preview({"id": "incident-1", "title": "Outage https://private.test owner@example.test +14155550123"}, locale="zh-Hant-HK")
        self.assertEqual(preview["locale"], "zh-Hant-HK")
        for private in ("https://private.test", "owner@example.test", "+14155550123"):
            self.assertNotIn(private, json.dumps(preview))
        self.assertIn("[redacted]", preview["text"])

    def test_bad_impact_inputs_fail_closed(self):
        for patch_value in ({"id": "bad/id"}, {"affectedCount": True}, {"affectedCount": 10001},
                            {"severity": "<script>"}, {"state": "unknown"}, {"observedAt": "no-timestamp"},
                            {"title": {"body": "private nested content"}}):
            with self.assertRaises(ControlError):
                email_preview({"id": "incident-1", **patch_value})


if __name__ == "__main__":
    unittest.main()
