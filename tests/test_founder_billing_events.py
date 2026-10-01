"""Founder billing instrumentation (migration 057; CONTRACTS §8.A): Stripe fixture webhooks → pr_subscription_events and
pr_invoices, written in the webhook's own transaction inside a savepoint, with a fake connection. No network, no database.

Proves: the Stripe field extraction (interval/count, unit amount, quantity, currency, recurring discounts, trial end), the
event row before the subscription upsert, one invoice row per invoice.* event before the credit-grant early return, the
recorded-only event types, and that a missing table (057 not applied yet) never fails the webhook or its own writes."""
import contextlib
import hashlib
import hmac
import io
import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2 import billing as billing_module
from postriff_phase2.billing import Billing, Ledger, record_invoice, record_subscription_event
from postriff_phase2.billing_stripe import EVENT_TYPES, StripePaymentProvider, _subscription_fields

try:
    from psycopg.errors import CheckViolation, UndefinedTable
except ImportError:  # the consumer runtime without psycopg: same sqlstates
    class UndefinedTable(Exception): sqlstate = "42P01"
    class CheckViolation(Exception): sqlstate = "23514"

NOW = 1_800_000_000.0
SECRET = "whsec_fixture"
WORKSPACE = "11111111-2222-4333-8444-555555555555"
EVENTS_INSERT = "INSERT INTO public.pr_subscription_events"
INVOICES_INSERT = "INSERT INTO public.pr_invoices"


def provider():
    return StripePaymentProvider("sk_test_fixture", SECRET, clock=lambda: NOW)


def signed(kind, obj, event_id="evt_1", created=int(NOW) - 60):
    body = json.dumps({"id": event_id, "type": kind, "created": created, "livemode": False, "data": {"object": obj}}).encode()
    signature = hmac.new(SECRET.encode(), f"{int(NOW)}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={int(NOW)},v1={signature}", body


def subscription(status="active", price=None, **extra):
    price = price or {"id": "price_creator", "unit_amount": 5900, "currency": "usd", "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}}
    return {"id": "sub_1", "customer": "cus_1", "status": status, "metadata": {"workspace_id": WORKSPACE, "plan_terms_id": "studio-v1"},
            "items": {"data": [{"price": price, "quantity": 1, "current_period_end": int(NOW) + 86400 * 30}]}, "cancel_at_period_end": False, **extra}


def invoice(status="paid", amount_paid=5900, invoice_id="in_1", reason="subscription_cycle"):
    return {"id": invoice_id, "customer": "cus_1", "subscription": "sub_1", "status": status, "paid": status == "paid", "amount_due": 5900, "amount_paid": amount_paid,
            "currency": "usd", "billing_reason": reason, "payment_intent": "pi_1", "subscription_details": {"metadata": {"workspace_id": WORKSPACE, "plan_terms_id": "studio-v1"}},
            "lines": {"data": [{"period": {"start": int(NOW) - 86400 * 30, "end": int(NOW)}}]}}


class FakeTransaction:
    """A cursor over one transaction with PostgreSQL's savepoint rules: a failed statement aborts the transaction until
    ROLLBACK TO SAVEPOINT; commit() keeps the statements that survived. Answers SELECTs by SQL substring."""

    def __init__(self, answers=None, fail=()):
        self.answers, self.fail = dict(answers or {}), list(fail)
        self.log, self.executed, self.savepoints, self.aborted, self.committed, self._pending = [], [], {}, False, None, None

    def execute(self, sql, params=None):
        text = sql.strip()
        self.executed.append((sql, params))
        self._pending = None
        if text.startswith("ROLLBACK TO SAVEPOINT"):
            del self.log[self.savepoints[text.split()[-1]]:]
            self.aborted = False
            return
        if self.aborted:
            raise RuntimeError("current transaction is aborted, commands ignored until end of transaction block")
        if text.startswith("SAVEPOINT"):
            self.savepoints[text.split()[-1]] = len(self.log)
            return
        if text.startswith("RELEASE SAVEPOINT"):
            self.savepoints.pop(text.split()[-1], None)
            return
        for needle, error in self.fail:
            if needle in sql:
                self.aborted = True
                raise error
        self.log.append((sql, params))
        for needle, rows in self.answers.items():
            if needle in sql:
                self._pending = list(rows)
                break

    def fetchone(self):
        return self._pending.pop(0) if self._pending else None

    def fetchall(self):
        rows, self._pending = self._pending or [], None
        return rows

    def commit(self):
        if self.aborted:
            raise RuntimeError("transaction aborted")
        self.committed = list(self.log)

    def written(self, needle):
        return [params for sql, params in (self.committed if self.committed is not None else self.log) if needle in sql]


ENTITLEMENTS = {"members": 1, "connectedAccounts": 3, "writingBatches": 0, "mediaCredits": 0, "storageMb": 1000}


def billing():
    return Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW)


def answers(prior=("active", "studio-v1"), last_event_at=None):
    found = {"SELECT entitlements FROM public.pr_plan_terms WHERE id=%s": [(ENTITLEMENTS,)], "SELECT status,plan_terms_id FROM public.pr_subscriptions": [prior] if prior else []}
    if last_event_at is not None:
        found["SELECT extract(epoch from last_event_at)"] = [(last_event_at,)]
    return found


def event_row(params):
    """pr_subscription_events INSERT params by column name."""
    names = ("provider", "event_id", "event_type", "workspace_id", "provider_subscription_id", "event_at", "applied", "prior_status", "new_status", "prior_terms", "new_terms",
             "interval", "interval_count", "unit_amount_minor", "quantity", "usage_type", "currency", "discount_minor", "discount_end", "cancel_at", "trial_end")
    return dict(zip(names, params))


def invoice_row(params):
    names = ("invoice_id", "provider", "workspace_id", "subscription_id", "billing_reason", "period_start", "period_end", "amount_due", "amount_paid", "currency", "status",
             "payment_intent_id", "livemode", "event_id", "event_at")
    return dict(zip(names, params))


class StripeFieldExtraction(unittest.TestCase):
    def test_event_types_record_refunds_and_trial_notices_without_transitions(self):
        self.assertEqual(EVENT_TYPES["charge.refunded"], "charge.refunded")
        self.assertEqual(EVENT_TYPES["customer.subscription.trial_will_end"], "subscription.trial_will_end")
        self.assertEqual(EVENT_TYPES["invoice.payment_failed"], "invoice.payment_failed")
        for kind in ("charge.refunded", "subscription.trial_will_end"):
            self.assertNotIn(kind, Billing.TRANSITIONS, "recorded only: no new side effect")

    def test_price_interval_quantity_currency_and_trial(self):
        fields = _subscription_fields(subscription(price={"id": "p", "unit_amount": 34800, "currency": "USD", "recurring": {"interval": "year", "interval_count": 1, "usage_type": "licensed"}},
                                                   trial_end=int(NOW) + 3600, cancel_at=int(NOW) + 7200))
        self.assertEqual((fields["interval"], fields["intervalCount"], fields["unitAmount"], fields["quantity"], fields["usageType"], fields["currency"]),
                         ("year", 1, 34800, 1, "licensed", "usd"))
        self.assertEqual((fields["discountMinor"], fields["discountEnd"], fields["trialEnd"], fields["cancelAt"]), (0, None, NOW + 3600, NOW + 7200))

    def test_recurring_discounts_are_valued_one_time_ignored_and_unknown_never_guessed(self):
        forever = _subscription_fields(subscription(discount={"id": "di_1", "coupon": {"duration": "forever", "percent_off": 10}}))
        self.assertEqual((forever["discountMinor"], forever["discountEnd"]), (590, None))
        repeating = _subscription_fields(subscription(discounts=[{"id": "di_2", "end": int(NOW) + 86400 * 90, "source": {"coupon": {"duration": "repeating", "amount_off": 1000, "currency": "usd"}}}]))
        self.assertEqual((repeating["discountMinor"], repeating["discountEnd"]), (1000, NOW + 86400 * 90))
        once = _subscription_fields(subscription(discount={"id": "di_3", "coupon": {"duration": "once", "percent_off": 50}}))
        self.assertEqual(once["discountMinor"], 0, "a one-time discount does not change recurring revenue")
        same = _subscription_fields(subscription(discount={"id": "di_1", "coupon": {"duration": "forever", "amount_off": 500, "currency": "usd"}}, discounts=["di_1"]))
        self.assertEqual(same["discountMinor"], 500, "the expanded legacy discount and its id in discounts are one discount")
        for unknown in (subscription(discounts=["di_unexpanded"]), subscription(discount={"id": "d", "coupon": {"duration": "forever", "amount_off": 500, "currency": "eur"}}),
                        subscription(discount={"id": "d", "coupon": "coupon_id_only"}),
                        subscription(discounts=[{"id": "a", "coupon": {"duration": "forever", "percent_off": 5}}, {"id": "b", "end": int(NOW), "coupon": {"duration": "repeating", "percent_off": 5}}])):
            self.assertIsNone(_subscription_fields(unknown)["discountMinor"])

    def test_prices_that_cannot_be_valued_leave_the_amount_unknown(self):
        multi = subscription()
        multi["items"]["data"].append({"price": {"id": "p2", "unit_amount": 100, "currency": "usd", "recurring": {"interval": "month"}}, "quantity": 1})
        inclusive = subscription(price={"id": "p", "unit_amount": 5900, "currency": "usd", "tax_behavior": "inclusive", "recurring": {"interval": "month"}})
        tiered = subscription(price={"id": "p", "unit_amount": None, "billing_scheme": "tiered", "currency": "usd", "recurring": {"interval": "month"}})
        for obj in (multi, inclusive, tiered):
            self.assertIsNone(_subscription_fields(obj)["unitAmount"])
        metered = _subscription_fields(subscription(price={"id": "p", "unit_amount": 2, "currency": "usd", "recurring": {"interval": "month", "usage_type": "metered"}}))
        self.assertEqual(metered["usageType"], "metered")
        self.assertEqual(_subscription_fields(subscription(price={"id": "p", "unit_amount": 2900, "currency": "usd", "recurring": {"interval": "month"}}))["intervalCount"], 1)


class WebhookRecording(unittest.TestCase):
    def setUp(self):
        billing_module._RECORDING["off_until"].clear()
        billing_module._RECORDING["logged"].clear()

    def process(self, kind, obj, cur, **kw):
        sig, body = signed(kind, obj, **kw)
        return billing().process_webhook(cur, sig, body)

    def test_subscription_event_row_precedes_the_subscription_upsert_inside_a_savepoint(self):
        cur = FakeTransaction(answers(prior=("trial", "trial-v1")))
        result = self.process("customer.subscription.created", subscription(trial_end=int(NOW) + 86400, discount={"id": "d", "coupon": {"duration": "forever", "percent_off": 10}}), cur)
        cur.commit()
        self.assertEqual((result["outcome"], result["status"]), ("applied", "active"))
        sqls = [sql for sql, _ in cur.executed]
        event_at = next(i for i, sql in enumerate(sqls) if EVENTS_INSERT in sql)
        upsert_at = next(i for i, sql in enumerate(sqls) if "INSERT INTO public.pr_subscriptions" in sql)
        self.assertLess(event_at, upsert_at, "written before the subscription upsert")
        self.assertEqual(sqls[event_at - 2:event_at + 2][0], "SAVEPOINT founder_billing_record")
        self.assertEqual(sqls[event_at + 1], "RELEASE SAVEPOINT founder_billing_record")
        self.assertIn("ON CONFLICT (provider,event_id) DO NOTHING", sqls[event_at])
        row = event_row(cur.written(EVENTS_INSERT)[0])
        self.assertEqual((row["provider"], row["event_id"], row["event_type"], row["workspace_id"], row["provider_subscription_id"], row["applied"]),
                         ("stripe", "evt_1", "customer.subscription.created", WORKSPACE, "sub_1", True))
        self.assertEqual((row["prior_status"], row["new_status"], row["prior_terms"], row["new_terms"]), ("trial", "active", "trial-v1", "studio-v1"))
        self.assertEqual((row["interval"], row["interval_count"], row["unit_amount_minor"], row["quantity"], row["usage_type"], row["currency"], row["discount_minor"]),
                         ("month", 1, 5900, 1, "licensed", "usd", 590))
        self.assertEqual((row["trial_end"], row["event_at"]), (NOW + 86400, NOW - 60))
        self.assertEqual(len(cur.written("INSERT INTO public.pr_billing_events")), 1)

    def test_every_invoice_event_records_one_invoice_row_before_the_credit_grant(self):
        cur = FakeTransaction({**answers(), "to_regclass('public.pr_credit_subscription_grants')": [(False,)]})
        result = self.process("invoice.paid", invoice(), cur, event_id="evt_paid")
        cur.commit()
        self.assertEqual(result["outcome"], "applied")
        sqls = [sql for sql, _ in cur.executed]
        invoice_at = next(i for i, sql in enumerate(sqls) if INVOICES_INSERT in sql)
        grant_at = next(i for i, sql in enumerate(sqls) if "pr_credit_subscription_grants" in sql)
        self.assertLess(invoice_at, grant_at, "recorded before the credit-grant early return")
        row = invoice_row(cur.written(INVOICES_INSERT)[0])
        self.assertEqual((row["invoice_id"], row["provider"], row["workspace_id"], row["subscription_id"], row["billing_reason"], row["status"]),
                         ("in_1", "stripe", WORKSPACE, "sub_1", "subscription_cycle", "paid"))
        self.assertEqual((row["amount_due"], row["amount_paid"], row["currency"], row["payment_intent_id"], row["livemode"], row["event_id"]),
                         (5900, 5900, "usd", "pi_1", False, "evt_paid"))
        self.assertEqual((row["period_start"], row["period_end"]), (NOW - 86400 * 30, NOW))
        self.assertIn("WHERE public.pr_invoices.status NOT IN ('paid','void')", next(sql for sql in sqls if INVOICES_INSERT in sql), "a paid invoice never moves back")
        status_row = event_row(cur.written(EVENTS_INSERT)[0])
        self.assertEqual((status_row["event_type"], status_row["new_status"], status_row["unit_amount_minor"], status_row["currency"]), ("invoice.paid", "active", None, "usd"))

    def test_failed_invoice_records_open_invoice_and_past_due_event(self):
        cur = FakeTransaction(answers())
        result = self.process("invoice.payment_failed", invoice(status="open", amount_paid=0), cur, event_id="evt_fail")
        self.assertEqual((result["outcome"], result["status"]), ("applied", "past_due"))
        self.assertEqual(invoice_row(cur.written(INVOICES_INSERT)[0])["status"], "open")
        self.assertEqual(invoice_row(cur.written(INVOICES_INSERT)[0])["amount_paid"], 0)
        self.assertEqual(event_row(cur.written(EVENTS_INSERT)[0])["new_status"], "past_due")

    def test_orphan_invoice_without_workspace_is_still_recorded(self):
        cur = FakeTransaction(answers())
        orphan = invoice()
        orphan["subscription_details"] = {}
        result = self.process("invoice.paid", orphan, cur, event_id="evt_orphan")
        self.assertEqual(result["outcome"], "ignored")
        self.assertIsNone(invoice_row(cur.written(INVOICES_INSERT)[0])["workspace_id"])
        self.assertEqual(cur.written(EVENTS_INSERT), [], "no workspace: no subscription state row")

    def test_stale_event_keeps_its_own_state_without_a_prior(self):
        cur = FakeTransaction(answers(last_event_at=NOW + 100))
        result = self.process("customer.subscription.updated", subscription(status="past_due"), cur, event_id="evt_old")
        self.assertEqual(result["outcome"], "stale")
        row = event_row(cur.written(EVENTS_INSERT)[0])
        self.assertEqual((row["applied"], row["prior_status"], row["new_status"], row["unit_amount_minor"]), (False, None, "past_due", 5900))
        self.assertEqual(cur.written("INSERT INTO public.pr_subscriptions"), [])

    def test_trial_notice_is_recorded_only_and_refunds_change_nothing(self):
        applied = []
        cur = FakeTransaction(answers(prior=("active", "studio-v1")))
        sig, body = signed("customer.subscription.trial_will_end", subscription(status="trialing", trial_end=int(NOW) + 3 * 86400), event_id="evt_trial")
        result = Billing(provider=provider(), ledger=Ledger(), clock=lambda: NOW, on_applied=lambda e, s: applied.append(e)).process_webhook(cur, sig, body)
        self.assertEqual((result["outcome"], result["type"]), ("ignored", "subscription.trial_will_end"))
        row = event_row(cur.written(EVENTS_INSERT)[0])
        self.assertEqual((row["applied"], row["prior_status"], row["new_status"], row["trial_end"]), (False, "active", "active", NOW + 3 * 86400))
        self.assertEqual(cur.written("INSERT INTO public.pr_subscriptions"), [])
        self.assertEqual(applied, [], "no notification side effect")
        refund = FakeTransaction(answers())
        result = self.process("charge.refunded", {"id": "ch_1", "invoice": "in_1", "payment_intent": "pi_1", "amount_refunded": 5900, "currency": "usd"}, refund, event_id="evt_refund")
        self.assertEqual((result["outcome"], result["type"]), ("ignored", "charge.refunded"))
        self.assertEqual((refund.written(EVENTS_INSERT), refund.written(INVOICES_INSERT)), ([], []), "a one-time refund never changes MRR or the invoice record")
        self.assertEqual(refund.written("INSERT INTO public.pr_billing_events")[0][2], "charge.refunded")

    def test_duplicate_event_writes_nothing_more(self):
        cur = FakeTransaction({"SELECT outcome FROM public.pr_billing_events": [("applied",)]})
        self.assertEqual(self.process("invoice.paid", invoice(), cur)["outcome"], "duplicate")
        self.assertEqual((cur.written(EVENTS_INSERT), cur.written(INVOICES_INSERT)), ([], []))

    def test_missing_table_never_fails_the_webhook_or_its_own_writes(self):
        """057 not applied yet: the INSERT fails inside the savepoint, the transaction recovers, the subscription upsert and
        the billing event are committed, the failure is logged once by class, and the table is skipped for 10 minutes."""
        missing = UndefinedTable("relation \"public.pr_subscription_events\" does not exist")
        cur = FakeTransaction({**answers(), "to_regclass('public.pr_credit_subscription_grants')": [(False,)]},
                              fail=[(EVENTS_INSERT, missing), (INVOICES_INSERT, UndefinedTable("relation \"public.pr_invoices\" does not exist"))])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.process("invoice.paid", invoice(), cur, event_id="evt_missing")
            cur.commit()
        self.assertEqual((result["outcome"], result["status"]), ("applied", "active"))
        self.assertEqual(len(cur.written("INSERT INTO public.pr_subscriptions")), 1, "the customer's subscription upsert is committed")
        self.assertEqual(len(cur.written("INSERT INTO public.pr_billing_events")), 1)
        self.assertEqual((cur.written(EVENTS_INSERT), cur.written(INVOICES_INSERT)), ([], []))
        self.assertIn("ROLLBACK TO SAVEPOINT founder_billing_record", [sql for sql, _ in cur.executed])
        logged = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual({(entry["table"], entry["reason"], entry["error"]) for entry in logged},
                         {("pr_subscription_events", "not_installed", "UndefinedTable"), ("pr_invoices", "not_installed", "UndefinedTable")})
        self.assertNotIn("does not exist", output.getvalue(), "exception class only, never its message")
        again = FakeTransaction(answers(), fail=[(EVENTS_INSERT, missing)])
        with contextlib.redirect_stdout(io.StringIO()) as quiet:
            self.assertEqual(self.process("customer.subscription.updated", subscription(), again, event_id="evt_skip")["outcome"], "applied")
        self.assertFalse(any(EVENTS_INSERT in sql for sql, _ in again.executed), "skipped for 10 minutes after a missing table")
        self.assertEqual(quiet.getvalue(), "")
        clock = [0.0]
        billing_module._RECORDING["off_until"]["pr_subscription_events"] = 5.0
        self.assertFalse(billing_module._founder_record(FakeTransaction(), "pr_subscription_events", lambda: None, clock=lambda: clock[0]))
        clock[0] = 6.0
        self.assertTrue(billing_module._founder_record(FakeTransaction(), "pr_subscription_events", lambda: None, clock=lambda: clock[0]), "retried after the pause")

    def test_other_failures_roll_back_the_founder_write_only(self):
        cur = FakeTransaction(answers(), fail=[(EVENTS_INSERT, CheckViolation("new row violates check constraint"))])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.process("customer.subscription.updated", subscription(), cur, event_id="evt_check")["outcome"], "applied")
            cur.commit()
        self.assertEqual(len(cur.written("INSERT INTO public.pr_subscriptions")), 1)
        self.assertEqual(json.loads(output.getvalue())["reason"], "write_failed")
        self.assertNotIn("pr_subscription_events", billing_module._RECORDING["off_until"], "only a missing installation pauses recording")

    def test_an_autocommit_cursor_records_nothing_and_changes_nothing(self):
        class Autocommit(FakeTransaction):
            def execute(self, sql, params=None):
                if sql.startswith("SAVEPOINT"):
                    raise RuntimeError("SAVEPOINT can only be used in transaction blocks")
                super().execute(sql, params)
        cur = Autocommit(answers())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.process("customer.subscription.updated", subscription(), cur, event_id="evt_auto")["outcome"], "applied")
        self.assertEqual(cur.written(EVENTS_INSERT), [])
        self.assertEqual(len(cur.written("INSERT INTO public.pr_subscriptions")), 1)
        self.assertEqual(json.loads(output.getvalue())["reason"], "no_transaction")

    def test_unattributable_events_write_no_row(self):
        cur = FakeTransaction()
        bad = {"id": "evt_x", "type": "subscription.activated", "createdAt": NOW, "workspaceId": "not-a-uuid"}
        self.assertFalse(record_subscription_event(cur, provider(), bad, "active", applied=True))
        self.assertFalse(record_invoice(cur, provider(), {"id": "evt_y", "type": "invoice.paid", "createdAt": NOW}))
        self.assertEqual(cur.executed, [])
        fixture = {"id": "evt_z", "type": "invoice.payment_failed", "createdAt": NOW, "workspaceId": str(uuid.uuid4()), "invoiceId": "in_fixture", "invoicePaid": False}
        self.assertTrue(record_invoice(cur, type("Fixture", (), {"id": "fixture"})(), fixture))
        self.assertEqual(invoice_row(cur.written(INVOICES_INSERT)[0])["status"], "open")


if __name__ == "__main__":
    unittest.main()
