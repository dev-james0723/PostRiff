"""Task2: real disposable PostgreSQL accounting; synthetic local funding only."""
from local_pg_target import selected_target
import contextlib
import json
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import psycopg
from consumer_fixtures import approve_budgets
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import Ledger
from postriff_phase2.credit_meter import POLICY_VERSION
from postriff_phase2.credit_wallet import AUTO_LIMIT_ENV
from postriff_phase2.hosted import HostedWorkspaceService

ROOT = Path(__file__).resolve().parents[2]
DSN = selected_target().dsn()
V2 = 'credits-v2-2026-09-28'
NOW = int(time.time())
BASE = {'writingBatches': 10, 'mediaCredits': 1, 'members': 1, 'connectedAccounts': 3, 'storageMb': 200}


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class CreditPolicyV2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection() as db:
            assert db.info.host == '127.0.0.1' and db.info.port == selected_target().port
            # The shared RLS fixture omits these; apply only this missing ordered chain.
            for name in ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql'):
                db.execute((ROOT / 'migrations/postriff' / name).read_text())
            for version, policy in enumerate((POLICY_VERSION, V2), 980):
                db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) VALUES(%s,'studio',%s,'Synthetic Task2',0,'active',%s::jsonb)",
                           ('task2-' + policy, version, json.dumps({**BASE, 'creditPolicy': policy, 'monthlyCredits': 3500})))

    def setUp(self):
        self.clock = [float(NOW)]
        self.actor = str(uuid.uuid4())
        with connection() as db:
            db.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.actor,))
        def verify(token):
            if token != 'fixture':
                raise AlphaError('Denied', 403)
            return self.actor
        verify.session_id = lambda token, principal: 'task2-' + self.actor
        verify.auth_time = lambda token, principal: self.clock[0]
        self.service = HostedWorkspaceService(connection, verify, clock=lambda: self.clock[0], credits_enabled=True)
        snap = self.service.bootstrap('fixture', 'studio')
        self.wid, self.revision = snap['workspaceId'], snap['revision']
        self.ledger = self.service.ledger
        self.terms = 'task2-' + V2
        with connection() as db:
            self.ledger.ensure_entitlement(db.cursor(), self.wid, None)
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', (self.terms, self.wid))
            db.execute("UPDATE pr_subscriptions SET plan_terms_id=%s,status='active',provider='stripe',provider_subscription_id='sub_task2',current_period_end=to_timestamp(%s) WHERE workspace_id=%s", (self.terms, NOW + 60, self.wid))
        approve_budgets(connection, self.wid)

    def grant(self, key='funding', milli=30_000, expiry=None, source='local-test-only'):
        with connection() as db:
            try:
                return self.ledger.credits.grant(db.cursor(), self.wid, self.actor, key, milli, expiry, source=source)
            except AlphaError as error:
                self.fail('V2 synthetic grant must be supported: ' + str(error))

    def reserve(self, key, maximum=9_000, estimate=10_000):
        with connection() as db:
            cur = db.cursor()
            q = self.ledger.credits.issue(cur, self.wid, self.actor, self.revision, 'a' * 64, 'fixture-model', 'fixture-provider', maximum)
            authority = self.ledger.credits.authorize(cur, self.wid, self.actor, self.revision, 'a' * 64, q['quoteId'])
            return self.ledger.reserve(cur, self.wid, self.actor, 'text_model', estimate, key, charge_batch=True,
                                       provider='fixture-provider', model='fixture-model', credit_authority=authority)

    def view(self):
        with connection() as db:
            return self.ledger.credits.view(db.cursor(), self.wid)

    def settle(self, reservation, outcome, cost=None, key=None):
        with connection() as db:
            return self.ledger.settle(db.cursor(), self.wid, reservation['reservationId'], outcome, cost, idempotency_key=key)

    def invoice_evidence(self, invoice_id='in_task2', *, grant_id=None, start=NOW - 60, end=NOW + 60, milli=30_000, reversed_milli=0, terms=None, subscription='sub_task2', reason='subscription_cycle'):
        with connection() as db:
            db.execute("INSERT INTO pr_credit_subscription_grants(invoice_id,workspace_id,subscription_id,plan_terms_id,billing_reason,period_start,period_end,amount_cents,currency,millicredits,grant_id,reversed_millicredits,livemode) VALUES(%s,%s,%s,%s,%s,%s,%s,1000,'usd',%s,%s,%s,false)",
                       (invoice_id + self.wid, self.wid, subscription, terms or self.terms, reason, start, end, milli, grant_id, reversed_milli))

    def assert_period(self, view, total=None, expiry=None):
        self.assertIn('currentPeriodGrantMilliCredits', view)
        self.assertIn('currentPeriodExpiresAt', view)
        self.assertEqual(view['currentPeriodGrantMilliCredits'], total)
        self.assertEqual(view['currentPeriodExpiresAt'], expiry)

    def test_both_supported_policies_preserve_their_ledger_identifiers(self):
        for policy in (POLICY_VERSION, V2):
            with self.subTest(policy=policy), connection() as db:
                db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', ('task2-' + policy, self.wid))
                try:
                    grant = self.ledger.credits.grant(db.cursor(), self.wid, self.actor, 'grant-' + policy, 10_000)
                except AlphaError as error:
                    self.fail('Supported policy refused: ' + str(error))
                stored = db.execute("SELECT meta->'credits'->>'policy' FROM pr_usage_ledger WHERE id=%s", (grant['entryId'],)).fetchone()[0]
                self.assertEqual(stored, policy)
                quote = self.ledger.credits.issue(db.cursor(), self.wid, self.actor, self.revision, 'a' * 64, 'fixture-model', 'fixture-provider', 1_000)
                self.assertEqual(quote['policy'], policy)
        self.assertEqual(self.view()['availableMilliCredits'], 20_000)

    def test_actual_cost_and_task_rounding(self):
        self.grant(milli=600_000)
        for key, cost, expected in (('usd', 1_000_000, 300_000), ('fraction', sum([100, 12_900]), 3_900)):
            run = self.reserve(key, maximum=300_000, estimate=cost)
            self.settle(run, 'completed', cost)
            with connection() as db:
                credit = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE reservation_id=%s AND kind='settle'", (run['reservationId'],)).fetchone()[0]
                self.assertEqual(credit['used'], expected)
                self.assertEqual(credit['policy'], V2)
        self.assertEqual((self.view()['availableMilliCredits'], self.view()['usedMilliCredits']), (296_100, 303_900))

    def test_failed_run_releases_all_credits(self):
        self.grant()
        run = self.reserve('failed')
        self.settle(run, 'failed', 5_000)
        view = self.view()
        self.assertEqual((view['availableMilliCredits'], view['heldMilliCredits'], view['usedMilliCredits']), (30_000, 0, 0))

    def test_unknown_usage_stays_held_until_reconciled(self):
        self.grant()
        run = self.reserve('unknown')
        for outcome in ('unknown', 'completed'):
            self.settle(run, outcome, None, key='unknown-' + outcome)
            view = self.view()
            self.assertEqual((view['availableMilliCredits'], view['heldMilliCredits'], view['usedMilliCredits']), (21_000, 9_000, 0))
        self.settle(run, 'completed', 13_000)
        self.assertEqual((self.view()['heldMilliCredits'], self.view()['usedMilliCredits']), (0, 3_900))

    def test_over_max_is_absorbed_and_settlement_is_idempotent(self):
        self.grant()
        run = self.reserve('over-max', maximum=3_000)
        self.settle(run, 'completed', 50_000)
        self.assertTrue(self.settle(run, 'completed', 50_000)['duplicate'])
        self.assertTrue(self.settle(run, 'failed', 0, key='changed-terminal')['duplicate'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.settle(run, 'completed', 50_000, key='repeat-' + str(i)), range(4)))
        self.assertTrue(all(r['duplicate'] for r in results))
        with connection() as db:
            credits = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE reservation_id=%s AND meta->'credits'->>'op'='settle'", (run['reservationId'],)).fetchall()
        self.assertEqual(len(credits), 1)
        self.assertEqual((credits[0][0]['used'], credits[0][0]['absorbed'], credits[0][0]['released']), (3_000, 12_000, 0))
        self.assertEqual((self.view()['availableMilliCredits'], self.view()['usedMilliCredits']), (27_000, 3_000))

    def test_parallel_holds_cannot_overspend(self):
        self.grant()
        def compete(index):
            try:
                return self.reserve('race-' + str(index), maximum=20_000)
            except AlphaError as error:
                self.assertEqual(error.status, 402)
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(compete, range(2)))
        self.assertEqual(sum(r is not None for r in runs), 1)
        self.assertEqual((self.view()['availableMilliCredits'], self.view()['heldMilliCredits']), (10_000, 20_000))

    def test_quote_binding_and_unknown_or_inactive_policy_fail_closed(self):
        self.grant()
        with connection() as db:
            cur = db.cursor()
            quote = self.ledger.credits.issue(cur, self.wid, self.actor, self.revision, 'a' * 64, 'fixture-model', 'fixture-provider', 9_000)
            with self.assertRaises(AlphaError) as changed:
                self.ledger.credits.authorize(cur, self.wid, self.actor, self.revision, 'b' * 64, quote['quoteId'])
            self.assertEqual(changed.exception.status, 409)
            db.execute("UPDATE pr_plan_terms SET entitlements=jsonb_set(entitlements,'{creditPolicy}','\"unknown-task2\"') WHERE id=%s", (self.terms,))
            with self.assertRaises(AlphaError) as unknown:
                self.ledger.credits.policy(cur, self.wid)
            self.assertEqual(unknown.exception.status, 409)
            db.execute("UPDATE pr_plan_terms SET entitlements=%s::jsonb,status='proposed' WHERE id=%s", (json.dumps({**BASE, 'creditPolicy': V2}), self.terms))
            with self.assertRaises(AlphaError):
                self.ledger.credits.policy(cur, self.wid)
            db.rollback()

    def test_no_grant_or_unlinked_invoice_never_advertises_monthly_total(self):
        # Exercise projection under historical supported terms too: absence is unknown, not plan marketing.
        with connection() as db:
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', ('task2-' + POLICY_VERSION, self.wid))
        self.assert_period(self.view())
        self.invoice_evidence()
        self.assert_period(self.view())

    def test_current_period_uses_linked_grants_and_preserves_wallet_semantics(self):
        early = self.grant('period', expiry=NOW + 60, source='verified-stripe-invoice')
        self.grant('topup', milli=10_000)
        self.invoice_evidence(grant_id=early['entryId'])
        run = self.reserve('monthly-first', maximum=20_000)
        self.settle(run, 'completed', 50_000)
        with connection() as db:
            credit = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE id=%s", (run['reservationId'],)).fetchone()[0]
            self.assertEqual(credit['allocations'][0], {'grantId': early['entryId'], 'milli': 20_000})
            self.ledger.credits.reverse(db.cursor(), self.wid, self.actor, 'refund-period', early['entryId'], 30_000)
            db.execute('UPDATE pr_credit_subscription_grants SET reversed_millicredits=30000 WHERE grant_id=%s', (early['entryId'],))
        view = self.view()
        self.assert_period(view, 30_000, NOW + 60)
        self.assertEqual((view['availableMilliCredits'], view['heldMilliCredits'], view['usedMilliCredits'], view['debtMilliCredits']), (0, 0, 15_000, 5_000))
        self.grant('debt-repayment', milli=6_000)
        self.assertEqual((self.view()['availableMilliCredits'], self.view()['debtMilliCredits']), (1_000, 0))
        projected = self.service.usage(self.wid, 'fixture')['credits']
        self.assert_period(projected, 30_000, NOW + 60)
        self.assertNotIn('lots', projected)
        self.clock[0] = NOW + 60
        self.assert_period(self.view())
        self.assertEqual(self.view()['usedMilliCredits'], 15_000)  # Lifetime use, not this period's use.

    def test_purchased_expired_incomplete_and_foreign_evidence_is_excluded(self):
        topup = self.grant('topup')
        self.invoice_evidence('in_topup', grant_id=topup['entryId'])
        old = self.grant('expired', expiry=NOW - 1, source='verified-stripe-invoice')
        self.invoice_evidence('in_old', grant_id=old['entryId'], start=NOW - 120, end=NOW - 1)
        actual = self.grant('actual', expiry=NOW + 60, source='verified-stripe-invoice')
        self.invoice_evidence('in_missing_start', grant_id=actual['entryId'], start=None)
        self.invoice_evidence('in_missing_end', grant_id=actual['entryId'], end=None)
        self.invoice_evidence('in_other_sub', grant_id=actual['entryId'], subscription='sub_other')
        self.invoice_evidence('in_other_terms', grant_id=actual['entryId'], terms='task2-' + POLICY_VERSION)
        self.invoice_evidence('in_future', grant_id=actual['entryId'], start=NOW + 1)
        self.invoice_evidence('in_proration', grant_id=actual['entryId'], reason='subscription_update')
        self.invoice_evidence('in_wrong_amount', grant_id=actual['entryId'], milli=60_000)
        no_expiry = self.grant('no-expiry', source='verified-stripe-invoice')
        self.invoice_evidence('in_no_expiry', grant_id=no_expiry['entryId'])
        self.assert_period(self.view())
        # The grant relation cannot claim another workspace's actual ledger lot.
        other = CreditPolicyV2PostgresTests('test_failed_run_releases_all_credits')
        other.setUp()
        foreign = other.grant('foreign', expiry=NOW + 60, source='verified-stripe-invoice')
        self.invoice_evidence('in_foreign', grant_id=foreign['entryId'])
        self.assert_period(self.view())
        self.invoice_evidence('in_active', grant_id=actual['entryId'])
        self.assert_period(self.view(), 30_000, NOW + 60)
        with connection() as db:
            db.execute("UPDATE pr_plan_terms SET status='proposed' WHERE id=%s", (self.terms,))
            self.assert_period(self.ledger.credits.view(db.cursor(), self.wid))
            db.rollback()

    def test_period_total_sums_actual_lots_without_counting_the_same_grant_twice(self):
        first = self.grant('first-period', expiry=NOW + 60, source='verified-stripe-invoice')
        second = self.grant('second-period', milli=60_000, expiry=NOW + 60, source='verified-stripe-invoice')
        self.invoice_evidence('in_first', grant_id=first['entryId'])
        self.invoice_evidence('in_second', grant_id=second['entryId'], milli=60_000)
        self.invoice_evidence('in_duplicate_link', grant_id=first['entryId'])
        self.assert_period(self.view(), 90_000, NOW + 60)

    def test_v2_incomplete_paid_period_does_not_grant_perpetual_credits(self):
        for index, (start, end) in enumerate(((None, NOW + 60), (NOW, None), (NOW + 60, NOW))):
            with self.subTest(start=start, end=end), connection() as db:
                event = {'workspaceId': self.wid, 'planTermsId': self.terms, 'invoiceId': 'in_incomplete_' + self.wid + str(index),
                         'invoicePaid': True, 'amountPaid': 1000, 'currency': 'usd', 'billingReason': 'subscription_cycle',
                         'subscriptionId': 'sub_task2', 'periodStart': start, 'currentPeriodEnd': end}
                self.service.billing._grant_period_credits(db.cursor(), event)
                view = self.ledger.credits.view(db.cursor(), self.wid)
                self.assertEqual(view['availableMilliCredits'], 0)
                grants = db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (self.wid,)).fetchone()[0]
                self.assertEqual(grants, 0)

    def verified_grant(self, cur, key, policy, source='verified-stripe-invoice'):
        try:
            return self.ledger.credits.grant(cur, self.wid, self.actor, key, 10_000, NOW + 60,
                                             source=source, policy_version=policy)
        except TypeError as error:
            self.fail('Verified funding policy binding API unavailable: ' + str(error))

    def test_verified_funding_policy_replays_without_changing_history(self):
        with connection() as db:
            cur = db.cursor()
            first = self.verified_grant(cur, 'verified-policy-replay', POLICY_VERSION)
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', ('task2-' + POLICY_VERSION, self.wid))
            replay = self.verified_grant(cur, 'verified-policy-replay', POLICY_VERSION)
            self.assertTrue(replay['duplicate'])
            self.assertEqual(replay['entryId'], first['entryId'])
            with self.assertRaises(AlphaError) as conflict:
                self.verified_grant(cur, 'verified-policy-replay', V2)
            self.assertEqual(conflict.exception.status, 409)
            policy = db.execute("SELECT meta->'credits'->>'policy' FROM pr_usage_ledger WHERE id=%s", (first['entryId'],)).fetchone()[0]
            self.assertEqual(policy, POLICY_VERSION)
            db.rollback()

    def test_policy_override_rejects_unsupported_unverified_and_noncredit_funding(self):
        with connection() as db:
            cur = db.cursor()
            for policy in ('unknown-policy', ['credits-v2-2026-09-28'], True):
                with self.subTest(policy=policy):
                    with self.assertRaises(AlphaError) as error:
                        self.verified_grant(cur, 'unsupported-policy', policy)
                    self.assertEqual(error.exception.status, 409)
            with self.assertRaises(AlphaError) as unverified:
                self.verified_grant(cur, 'unverified-policy', POLICY_VERSION, source='client-request')
            self.assertEqual(unverified.exception.status, 409)
            db.execute("UPDATE pr_entitlements SET plan_terms_id='trial-v1' WHERE workspace_id=%s", (self.wid,))
            with self.assertRaises(AlphaError) as allowance:
                self.verified_grant(cur, 'noncredit-policy', V2)
            self.assertEqual(allowance.exception.status, 409)
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', (self.terms, self.wid))
            db.execute("UPDATE pr_plan_terms SET status='proposed' WHERE id=%s", (self.terms,))
            with self.assertRaises(AlphaError) as inactive:
                self.verified_grant(cur, 'inactive-policy', POLICY_VERSION)
            self.assertEqual(inactive.exception.status, 409)
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND meta->'credits'->>'op'='grant'", (self.wid,)).fetchone()[0], 0)
            db.rollback()

    def test_missing_monthly_evidence_table_keeps_legacy_wallet_readable(self):
        with connection() as db:
            db.execute('UPDATE pr_entitlements SET plan_terms_id=%s WHERE workspace_id=%s', ('task2-' + POLICY_VERSION, self.wid))
            self.ledger.credits.grant(db.cursor(), self.wid, self.actor, 'legacy', 10_000)
            db.execute('ALTER TABLE pr_credit_subscription_grants RENAME TO task2_hidden_monthly_evidence')
            view = self.ledger.credits.view(db.cursor(), self.wid)
            self.assertEqual(view['availableMilliCredits'], 10_000)
            self.assert_period(view)
            db.rollback()


    # --- Automatic per-request limit (POSTRIFF_CREDIT_AUTO_LIMIT_CREDITS) -----------------------------------------
    # Only request boundaries that know a signed-in person is asking (credit_requests.authorize with creditApproval,
    # the Rafii turn's reservation approval) issue an automatic quote; the ledger itself never approves anything.
    def automatic(self, key, estimate=10_000, limit='10', committed=0):
        """What such a boundary does: approve this one request automatically, then hold it with that authority."""
        from postriff_phase2.contracts import digest
        from postriff_phase2.credit_meter import millicredits
        with (patch.dict(os.environ, {AUTO_LIMIT_ENV: limit}) if limit is not None else contextlib.nullcontext()), connection() as db:
            cur = db.cursor()
            authority = self.ledger.credits.automatic_quote(cur, self.wid, self.actor, self.revision, digest({'request': key}),
                                                            'fixture-model', 'fixture-provider', millicredits(estimate), committed=committed)
            return self.ledger.reserve(cur, self.wid, self.actor, 'text_model', estimate, key, charge_batch=False,
                                       provider='fixture-provider', model='fixture-model', credit_authority=authority)

    def written(self):
        with connection() as db:
            return (db.execute('SELECT count(*) FROM pr_credit_quotes WHERE workspace_id=%s', (self.wid,)).fetchone()[0],
                    db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s AND kind='reserve'", (self.wid,)).fetchone()[0])

    def test_ledger_never_approves_by_itself_even_with_the_automatic_limit_on(self):
        # API tokens, automations and other server-started work reach the ledger with no authority: still refused.
        self.grant()
        with patch.dict(os.environ, {AUTO_LIMIT_ENV: '100'}), self.assertRaises(AlphaError) as raised, connection() as db:
            self.ledger.reserve(db.cursor(), self.wid, self.actor, 'text_model', 10_000, 'no-authority', charge_batch=False,
                                provider='fixture-provider', model='fixture-model')
        self.assertEqual(raised.exception.status, 402)
        self.assertIn('Confirm this task credit limit', str(raised.exception))
        self.assertEqual(self.written(), (0, 0))

    def test_automatic_limit_off_or_malformed_issues_nothing(self):
        self.grant()
        for raw in ('', '0', 'unlimited'):
            with self.subTest(raw=raw), self.assertRaises(AlphaError) as raised:
                self.automatic('off-' + (raw or 'unset'), limit=raw)
            self.assertEqual((raised.exception.status, raised.exception.code), (402, 'credit_limit_required'))
        self.assertEqual(self.written(), (0, 0))

    def test_automatic_quote_holds_exactly_one_request_and_charges_actual_cost(self):
        self.grant()
        reservation = self.automatic('auto-1')
        with connection() as db:
            credit = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE id=%s", (reservation['reservationId'],)).fetchone()[0]
            quote = db.execute('SELECT actor::text,max_millicredits,reservation_id::text,model,provider FROM pr_credit_quotes WHERE id::text=%s',
                               (credit['quoteId'],)).fetchone()
        self.assertIs(credit['automatic'], True)
        self.assertEqual(credit['maximum'], 3_000)  # USD 0.01 at 300 credits per USD: exactly this request's maximum
        self.assertEqual(quote, (self.actor, 3_000, reservation['reservationId'], 'fixture-model', 'fixture-provider'))
        self.assertEqual(self.view()['heldMilliCredits'], 3_000)
        self.settle(reservation, 'completed', 5_000)
        view = self.view()
        self.assertEqual((view['usedMilliCredits'], view['heldMilliCredits'], view['availableMilliCredits']), (1_500, 0, 28_500))
        self.assertEqual(self.written(), (1, 1))

    def test_automatic_quote_refuses_larger_requests_and_short_balances_before_writing(self):
        self.grant(milli=4_000)
        for estimate, committed in ((40_000, 0), (10_000, 8_000)):  # 12 credits; or 3 more on top of 8 already held by the request
            with self.subTest(estimate=estimate, committed=committed), self.assertRaises(AlphaError) as raised:
                self.automatic(f'auto-large-{committed}', estimate=estimate, committed=committed)
            self.assertEqual((raised.exception.status, raised.exception.code), (402, 'credit_auto_limit'))
            self.assertIn('Nothing was sent or charged', str(raised.exception))
        self.automatic('auto-fits')  # 3 of the 4 available credits are now held
        with self.assertRaises(AlphaError) as raised:
            self.automatic('auto-short')
        self.assertEqual((raised.exception.status, raised.exception.code), (402, 'credit_balance'))
        self.assertEqual(self.written(), (1, 1))

    def test_explicit_limits_are_unchanged_with_the_automatic_limit_on(self):
        self.grant()
        with patch.dict(os.environ, {AUTO_LIMIT_ENV: '10'}):
            explicit = self.reserve('explicit-with-automatic-on')
        with connection() as db:
            credit = db.execute("SELECT meta->'credits' FROM pr_usage_ledger WHERE id=%s", (explicit['reservationId'],)).fetchone()[0]
        self.assertNotIn('automatic', credit)
        self.assertEqual(credit['maximum'], 9_000)

    def test_parallel_automatic_requests_cannot_overspend(self):
        self.grant(milli=6_000)  # room for two 3-credit holds
        def attempt(index):
            try:
                self.automatic(f'auto-parallel-{index}', limit=None)
                return 'held'
            except AlphaError as error:
                return error.code
        with patch.dict(os.environ, {AUTO_LIMIT_ENV: '10'}), ThreadPoolExecutor(max_workers=4) as pool:  # patch.dict is not thread-safe
            outcomes = sorted(pool.map(attempt, range(4)))
        self.assertEqual(outcomes, ['credit_balance', 'credit_balance', 'held', 'held'])
        self.assertEqual(self.view()['heldMilliCredits'], 6_000)

    def test_usage_shows_the_automatic_limit(self):
        self.grant()
        for raw, expected in (('100', 100_000), ('', None)):
            with self.subTest(raw=raw), patch.dict(os.environ, {AUTO_LIMIT_ENV: raw}):
                self.assertEqual(self.service.usage(self.wid, 'fixture')['credits']['automaticLimitMilliCredits'], expected)

    def test_rafii_turn_is_approved_as_a_whole_within_the_automatic_limit(self):
        from postriff_phase2.agent_runtime_v2 import config
        from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
        from postriff_phase2.credit_automatic import run_approval
        self.grant(milli=100_000)
        cfg = config.RuntimeConfig.from_environment({'OPENAI_API_KEY': 'sk-synthetic-task2-not-a-key', 'RAFII_AGENT_V2_ENABLED': '1'})
        runtime = AgentRuntimeService(self.service, cfg, clock=lambda: self.clock[0])  # no model factory: real admission
        cid = self.service.ideas.create_conversation(self.wid, 'fixture', 'assistant credits')['conversationId']
        route = cfg.route('standard_reasoning', reason='test')
        def open_run(key):
            return runtime._open_run(self.wid, 'fixture', cid, 'What should I post this week?', 'text', key, 'trace-' + key, [],
                                     model=route.model, reserve_for='standard_reasoning')
        with patch.dict(os.environ, {AUTO_LIMIT_ENV: ''}), self.assertRaises(AlphaError) as raised:
            open_run('assistant-automatic-off')
        self.assertIn('Confirm this task credit limit', str(raised.exception))
        with patch.dict(os.environ, {AUTO_LIMIT_ENV: '30'}):
            run_id, reservation = open_run('assistant-automatic-on')
            with connection() as db:
                credit, meta_approval, via = db.execute("SELECT meta->'credits',meta->>'creditApproval',meta->>'via' FROM pr_usage_ledger WHERE id=%s",
                                                        (reservation['reservationId'],)).fetchone()
                self.assertEqual((via, meta_approval), ('rafii_agent', 'automatic'))
                self.assertIs(credit['automatic'], True)
                # A later hold on the same run (a resumed step, its generated view) counts the turn's open hold in full.
                room = 30_000 - credit['maximum']
                with self.assertRaises(AlphaError) as raised:
                    run_approval(self.ledger, db.cursor(), self.wid, self.actor, self.revision, (room + 1_000) * 10 // 3, route, run_id)
                self.assertEqual(raised.exception.code, 'credit_auto_limit')
                db.rollback()
        self.assertEqual(self.view()['heldMilliCredits'], credit['maximum'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
