"""PRD §15.2 golden payment fixtures and R-MET-01 shared definitions (AC31–AC34), pure functions."""
import unittest

from postriff_phase2 import metric_definitions as m

DAY = 86400
T0 = 1_780_000_000          # first-payment day of the fixtures
NOW = T0 + 200 * DAY        # well past every checkpoint unless a test says otherwise


def pay(invoice, at, amount=5900, *, reason="subscription_create", period=30, live=True, status="paid", sub="sub_1", pi=None, provider="stripe"):
    return {"workspaceId": "w", "invoiceId": invoice, "status": status, "livemode": live, "amountPaid": amount, "subscriptionId": sub,
            "billingReason": reason, "paidAt": at, "paymentIntentId": pi or f"pi_{invoice}", "periodStart": at, "periodEnd": at + period * DAY,
            "provider": provider}


class FirstCashPaidTest(unittest.TestCase):
    def test_active_subscription_without_a_successful_payment_never_converts(self):
        self.assertIsNone(m.first_cash_paid([pay("inv_open", T0, status="open")]))
        self.assertIsNone(m.first_cash_paid([]))

    def test_zero_dollar_discounted_first_invoice_then_a_positive_one(self):
        first = m.first_cash_paid([pay("inv_free_month", T0, amount=0), pay("inv_second", T0 + 30 * DAY, reason="subscription_cycle")])
        self.assertEqual(first, {"invoiceId": "inv_second", "paidAt": T0 + 30 * DAY})

    def test_duplicate_paid_notification_counts_once_with_the_earliest_time(self):
        first = m.first_cash_paid([pay("inv_1", T0 + 60), pay("inv_1", T0)])
        self.assertEqual(first, {"invoiceId": "inv_1", "paidAt": T0})

    def test_non_cash_credit_top_up_test_mode_and_fixture_never_qualify(self):
        for p in (pay("inv_credit", T0, amount=0), pay("topup", T0, sub=None, reason="manual"), pay("inv_test", T0, live=False),
                  pay("inv_fixture", T0, provider="fixture"), pay("inv_manual", T0, reason="manual")):
            self.assertIsNone(m.first_cash_paid([p]), p["invoiceId"])

    def test_one_payment_across_invoices_is_not_double_counted(self):
        payments = [pay("inv_a", T0, amount=3000, pi="pi_shared"), pay("inv_b", T0 + 10, amount=2900, pi="pi_shared", reason="subscription_update")]
        self.assertEqual(m.first_cash_paid(payments)["invoiceId"], "inv_a")
        refunds = [{"paymentIntentId": "pi_shared", "amount": 5900, "status": "succeeded"}]
        self.assertEqual(m.refunded_intents(payments, refunds, []), {"pi_shared"})
        partial = [{"paymentIntentId": "pi_shared", "amount": 3000, "status": "succeeded"}]
        self.assertEqual(m.refunded_intents(payments, partial, []), set())


class RetentionTest(unittest.TestCase):
    def cohort(self, **workspaces):
        return {k: {"payments": v[0], "refunds": v[1] if len(v) > 1 else [], "disputes": v[2] if len(v) > 2 else []} for k, v in workspaces.items()}

    def test_cancellation_with_a_paid_period_still_covers_d30(self):
        # Paid annual-ish period through day 40, cancelled at period end: D30 is still paid coverage.
        cohort = self.cohort(a=([pay("inv_1", T0, period=40)],))
        out = m.retention(cohort, now=NOW, watermark=NOW, days=30)
        self.assertEqual((out["value"], out["coverage"]["numerator"], out["coverage"]["denominator"]), (1.0, 1, 1))

    def test_unpaid_grace_at_d60_is_not_paid_retention(self):
        cohort = self.cohort(a=([pay("inv_1", T0), pay("inv_2", T0 + 30 * DAY, reason="subscription_cycle"), pay("inv_3_unpaid", T0 + 60 * DAY, status="open")],))
        self.assertEqual(m.retention(cohort, now=NOW, watermark=NOW, days=60)["value"], 0.0)
        self.assertEqual(m.retention(cohort, now=NOW, watermark=NOW, days=30)["value"], 1.0)

    def test_refund_after_acquisition_keeps_origin_and_only_affects_refund_adjusted(self):
        payments = [pay("inv_1", T0, period=40)]
        cohort = self.cohort(a=(payments, [{"paymentIntentId": "pi_inv_1", "amount": 5900, "status": "succeeded"}]))
        self.assertEqual(m.first_cash_paid(payments)["paidAt"], T0)
        self.assertEqual(m.retention(cohort, now=NOW, watermark=NOW, days=30)["value"], 1.0)
        adjusted = m.retention(cohort, now=NOW, watermark=NOW, days=30, refund_adjusted=True)
        self.assertEqual((adjusted["metricId"], adjusted["value"]), ("cash_paid_retention_d30_refund_adjusted", 0.0))

    def test_misattributed_event_correction_is_a_restatement_not_a_silent_move(self):
        wrong = [pay("inv_wrong", T0 - 10 * DAY), pay("inv_right", T0)]
        before = m.first_cash_paid(wrong)
        corrected = [p for p in wrong if p["invoiceId"] != "inv_wrong"]   # the correction receipt removes the misattributed row
        after = m.first_cash_paid(corrected)
        self.assertNotEqual(before, after)
        self.assertEqual(after["invoiceId"], "inv_right")

    def test_late_renewal_after_the_displayed_checkpoint_keeps_it_provisional(self):
        cohort = self.cohort(a=([pay("inv_1", T0)],))
        early = m.retention(cohort, now=T0 + 31 * DAY, watermark=T0 + 29 * DAY, days=30)   # watermark not past day 30 yet
        self.assertEqual((early["dataState"], early["value"], early["measures"]["immatureExcluded"]), ("unavailable", None, 1))
        cohort["a"]["payments"].append(pay("inv_2_late", T0 + 30 * DAY, reason="subscription_cycle"))
        final = m.retention(cohort, now=T0 + 35 * DAY, watermark=T0 + 34 * DAY, days=30)
        self.assertEqual((final["dataState"], final["value"]), ("available", 1.0))

    def test_unknown_service_periods_are_unknown_not_lapsed(self):
        broken = pay("inv_1", T0)
        broken["periodEnd"] = None
        out = m.retention(self.cohort(a=([broken],)), now=NOW, watermark=NOW, days=30)
        self.assertEqual((out["dataState"], out["coverage"]["unknown"], out["value"]), ("unavailable", 1, None))

    def test_future_cohort_cells_stay_unavailable(self):
        out = m.retention(self.cohort(a=([pay("inv_1", NOW - 10 * DAY)],)), now=NOW, watermark=NOW, days=30)
        self.assertEqual((out["value"], out["dataState"]), (None, "unavailable"))


class WindowConversionTest(unittest.TestCase):
    def test_only_mature_windows_and_payments_inside_them_count(self):
        cohort = {"inside": {"startedAt": T0, "payments": [pay("i1", T0 + 5 * DAY)]},
                  "outside": {"startedAt": T0, "payments": [pay("i2", T0 + 31 * DAY)]},
                  "never": {"startedAt": T0, "payments": []},
                  "test_mode": {"startedAt": T0, "payments": [pay("i3", T0 + DAY, live=False)]},
                  "immature": {"startedAt": NOW - 5 * DAY, "payments": [pay("i4", NOW - DAY)]}}
        out = m.window_conversion("legacy_trial_to_paid", cohort, now=NOW, watermark=NOW)
        self.assertEqual((out["coverage"]["numerator"], out["coverage"]["denominator"], out["measures"]["immatureExcluded"]), (1, 4, 1))
        self.assertEqual(out["dataState"], "partial")


class DefinitionsTest(unittest.TestCase):
    def test_every_definition_is_a_proposal_with_a_unit(self):
        for metric_id, spec in m.DEFINITIONS.items():
            self.assertEqual(spec["status"], m.PROPOSED, metric_id)
            self.assertIn(spec["unit"], ("workspace", "recipient"), metric_id)
            self.assertTrue(spec["definition"])
        self.assertEqual(m.DEFINITIONS["source_paid_conversion"].get("owner"), "founder")

    def test_row_shape_matches_founder_control(self):
        out = m.row("first_cash_paid_conversion", None, data_state="unavailable", reason="legacy_plan_invoices_not_recorded")
        for key in ("metricId", "definitionVersion", "interval", "dimensions", "value", "unit", "dataState", "coverage", "sourceWatermark", "sampleCount", "reason", "fixture"):
            self.assertIn(key, out)
        self.assertEqual(set(out["coverage"]), {"known", "unknown", "numerator", "denominator"})


class WeekCompletionTest(unittest.TestCase):
    week = {"id": "wk_1", "slots": [{"id": "a", "status": "published"}, {"id": "b", "status": "ready"}, {"id": "c", "status": "rejected"}]}

    def test_assisted_and_verified_are_separate_and_scope_is_explicit(self):
        complete, parts = m.week_completion(self.week)
        self.assertEqual((complete, parts["basis"], parts["committed"]), (False, "non_rejected_slots", 2))
        first_week = {"scope": {"weekId": "wk_1", "slotIds": ["a", "b"]}, "handoffs": {"b": {"state": "user_confirmed_used"}}}
        complete, parts = m.week_completion(self.week, first_week)
        self.assertEqual((complete, parts), (True, {"basis": "frozen_scope", "committed": 2, "verified": 1, "assisted": 1}))

    def test_an_export_alone_never_completes_a_week(self):
        first_week = {"scope": {"weekId": "wk_1", "slotIds": ["a", "b"]}, "handoffs": {"b": {"state": "export_ready"}}}
        self.assertFalse(m.week_completion(self.week, first_week)[0])


if __name__ == "__main__":
    unittest.main()


class FounderContractTest(unittest.TestCase):
    """The Founder Control catalog rows are generated from these definitions and must never drift (AC31, D-025)."""

    # Vocabulary Founder Control's catalogs/metrics.json already uses (PR #88 at e787cd47); new values would be unreviewed.
    GRAINS = {"workspace interval", "workspace snapshot", "occurrence", "ledger settlement", "provider attempt", "subscription snapshot",
              "opening paid cohort", "payment event", "refund event", "funds movement", "period + currency", "signup cohort"}
    UNITS = {"ratio", "count", "currency_minor", "seconds_distribution", "millicredits", "usd_micro", "seconds"}
    DIMENSIONS = {"plan", "currency", "window", "cohort", "provider", "task_type", "model", "source", "status"}

    def contract(self):
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / "docs/design/rafii-product-growth/contracts/founder-metrics-growth.json"
        return path.read_text(encoding="utf-8"), json.loads(path.read_text(encoding="utf-8"))

    def test_contract_file_is_exactly_the_generated_rows(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location("growth_metric_contract", Path(__file__).resolve().parents[1] / "scripts/growth_metric_contract.py")
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        text, rows = self.contract()
        self.assertEqual(text, generator.render(), "run scripts/growth_metric_contract.py")
        self.assertEqual({r["id"] for r in rows}, {k for k, v in m.DEFINITIONS.items() if v.get("owner") != "founder"})

    def test_rows_use_only_founder_vocabulary_and_stay_proposed(self):
        _, rows = self.contract()
        for row in rows:
            self.assertEqual(row["definition"], m.DEFINITIONS[row["id"]]["definition"], row["id"])
            self.assertEqual(row["status"], m.PROPOSED, row["id"])
            self.assertIn(row["grain"], self.GRAINS, row["id"])
            self.assertIn(row["unit"], self.UNITS, row["id"])
            self.assertLessEqual(set(row["allowed_dimensions"]), self.DIMENSIONS, row["id"])
            self.assertIn(row["currency_policy"], {"not_applicable", "native_currency_separate"}, row["id"])
            self.assertIn(row["refresh_target"], {"hourly_or_source_cadence", "event_driven_or_15m"}, row["id"])
            self.assertNotIn("activation", row, row["id"])   # only activated rows carry it; activation stays with James
