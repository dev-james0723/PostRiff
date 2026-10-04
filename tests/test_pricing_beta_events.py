"""Task11 synthetic unit evidence. No network, payment, provider or PostgreSQL I/O."""
import importlib
import json
import unittest
from unittest.mock import patch

from postriff_phase2.billing import Billing, Ledger
from postriff_phase2.credit_wallet import CreditBook
from postriff_phase2.billing_stripe import StripePaymentProvider

try:
    events = importlib.import_module('postriff_phase2.pricing_events')
except ModuleNotFoundError:
    events = None

W = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


class Cursor:
    def __init__(self, schema=True):
        self.schema, self.result, self.events, self.calls = schema, None, {}, []
        self.first_value_audit = False

    def execute(self, sql, args=()):
        self.calls.append((sql, args))
        if 'to_regclass' in sql:
            self.result = (self.schema,)
        elif "kind='pricing.first_value_completed'" in sql:
            self.result = (1,) if self.first_value_audit else None
        elif 'INSERT INTO public.pr_audit_events' in sql:
            self.first_value_audit = True
        elif 'INSERT INTO public.pr_product_events' in sql:
            workspace, event, properties, key, occurred = args
            self.events.setdefault((event, key), (workspace, json.loads(properties), occurred))
        else:
            self.result = None

    def fetchone(self):
        return self.result


class BetaEvents(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(events, 'Task11 private event helper is missing')
        self.cur = Cursor()

    def emit(self, **properties):
        return events.emit(self.cur, W, 'credits.held', 'usage_ledger', 'private payment ID', properties)

    def test_actual_source_workspace_global_dedupe_and_no_raw_source(self):
        for wid in (W, W.upper(), OTHER):
            events.emit(self.cur, wid, 'credits.held', 'usage_ledger', 'same source', {'heldMilliCredits': 9000})
        self.assertEqual(len(self.cur.events), 2)
        self.assertNotIn('same source', repr(self.cur.events))
        self.assertEqual({v[0] for v in self.cur.events.values()}, {W, OTHER})

    def test_distinct_immutable_sources_do_not_collapse(self):
        for source in ('a', 'b'):
            events.emit(self.cur, W, 'credits.held', 'usage_ledger', source, {'heldMilliCredits': 9000})
        self.assertEqual(len(self.cur.events), 2)

    def test_privacy_unknown_properties_fail_closed(self):
        for key in ('prompt', 'draft', 'url', 'priceId', 'customerId', 'paymentIntentId', 'reason', 'secret'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.emit(**{key: 'sensitive'})
        self.assertFalse(self.cur.events)

    def test_numeric_and_categorical_bounds(self):
        for value in (True, -1, 2**63, '9000', float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.emit(heldMilliCredits=value)
        with self.assertRaises(ValueError):
            events.emit(self.cur, W, 'subscription.cancelled', 'billing_event', 'e', {'cancellationReason': 'my private complaint'})
        with self.assertRaises(ValueError):
            events.emit(self.cur, W, 'invented.event', 'billing_event', 'e', {})

    def test_older_schema_is_noop_without_losing_original_transaction(self):
        cur = Cursor(False)
        events.emit(cur, W, 'credits.held', 'usage_ledger', 'r', {'heldMilliCredits': 9000})
        self.assertFalse(cur.events)
        self.assertEqual(len(cur.calls), 1)

    def test_signed_invoice_actual_variant_revenue_not_catalog_or_current_assignment(self):
        for variant, paid in (('49', 4700), ('59', 5900), ('79', 7900)):
            event = {'id': 'evt_secret', 'workspaceId': W, 'stripeType': 'invoice.paid',
                     'invoiceId': 'in_secret_' + variant, 'invoicePaid': True, 'amountPaid': paid,
                     'currency': 'usd', 'billingReason': 'subscription_cycle', 'planTermsId': 'creator-v1',
                     'priceVariantId': 'creator-' + variant + '-v1', 'createdAt': 100,
                     'customerId': 'cus_secret', 'paymentIntentId': 'pi_secret'}
            events.signed_billing(self.cur, event, 'stripe')
            events.signed_billing(self.cur, {**event, 'id': 'different delivery'}, 'stripe')
        rows = [v[1] for (event, _), v in self.cur.events.items() if event == 'renewal.paid']
        self.assertEqual(len(rows), 3)
        self.assertEqual({(v['priceVariant'], v['revenueCents']) for v in rows},
                         {('creator-49-v1', 4700), ('creator-59-v1', 5900), ('creator-79-v1', 7900)})
        self.assertNotIn('secret', repr(self.cur.events))
        self.assertTrue(all(v['cohort'] == 'paid_invoice' for v in rows))

    def test_unpaid_or_missing_invoice_facts_never_fabricate_revenue(self):
        base = {'workspaceId': W, 'stripeType': 'invoice.paid', 'id': 'e', 'createdAt': 100,
                'invoiceId': 'i', 'invoicePaid': True, 'amountPaid': 4900, 'currency': 'usd',
                'billingReason': 'subscription_create', 'planTermsId': 'creator-v1', 'priceVariantId': 'creator-49-v1'}
        for field in ('invoiceId', 'invoicePaid', 'amountPaid', 'currency'):
            events.signed_billing(self.cur, {**base, field: None}, 'stripe')
        self.assertFalse(self.cur.events)

    def test_legacy_retains_labelled_paid_cohort_and_no_fake_variant(self):
        events.signed_billing(self.cur, {'workspaceId': W, 'id': 'e', 'stripeType': 'invoice.paid',
            'invoiceId': 'i', 'invoicePaid': True, 'amountPaid': 1900, 'currency': 'usd',
            'billingReason': 'subscription_cycle', 'planTermsId': 'studio-v1', 'createdAt': 100}, 'stripe')
        props = next(v[1] for (name, _), v in self.cur.events.items() if name == 'renewal.paid')
        self.assertEqual((props['package'], props['priceVariant'], props['cohort']), ('legacy', None, 'legacy_paid_invoice'))

    def test_cancellation_category_is_signed_and_free_text_absent(self):
        obj = {'id': 'sub', 'status': 'canceled', 'cancellation_details':
               {'reason': 'cancellation_requested', 'feedback': 'too_expensive', 'comment': 'PRIVATE'}}
        mapped = StripePaymentProvider.map_event('evt', 'customer.subscription.deleted', 100, obj)
        self.assertEqual(mapped.get('cancellationReason'), 'too_expensive')
        self.assertNotIn('PRIVATE', repr(mapped))
        for details in ({}, {'feedback': 'PRIVATE', 'reason': 'PRIVATE'}, {'comment': 'PRIVATE'}):
            mapped = StripePaymentProvider.map_event('evt', 'customer.subscription.deleted', 100,
                                                     {**obj, 'cancellation_details': details})
            self.assertNotIn('cancellationReason', mapped)

    def test_unknown_stays_unknown_without_zero_cost_or_terminal_charge(self):
        events.settled(self.cur, W, 'r', 'unknown', None, {'maximum': 9000, 'policy': 'credits-v2-2026-09-28'}, None, {})
        props = next(v[1] for v in self.cur.events.values())
        self.assertEqual((props['state'], props['actualUsdMicro'], props['heldMilliCredits']), ('unknown', None, 9000))
        self.assertNotIn('credits.settled', {name for name, _ in self.cur.events})

    def test_failure_customer_zero_platform_actual_and_overmax_separate(self):
        events.settled(self.cur, W, 'failed', 'failed', 5000,
                       {'maximum': 9000, 'policy': 'credits-v2-2026-09-28'}, {'used': 0, 'released': 9000, 'absorbed': 0}, {})
        events.settled(self.cur, W, 'over', 'completed', 40000,
                       {'maximum': 9000, 'policy': 'credits-v2-2026-09-28'}, {'used': 9000, 'released': 0, 'absorbed': 3000}, {})
        props = {name: v[1] for (name, _), v in self.cur.events.items()}
        self.assertEqual(props['platform.cost']['actualUsdMicro'], 5000)
        self.assertEqual(props['platform.absorbed']['absorbedMilliCredits'], 3000)
        self.assertEqual(props['platform.absorbed']['actualUsdMicro'], 10000)

    def test_expiry_observes_source_lot_without_ledger_debit_and_keeps_held(self):
        rows = [{'id': 'lot', 'reservationId': None, 'credits': {'op': 'grant', 'milli': 10000,
                 'expiresAt': 100, 'policy': 'credits-v2-2026-09-28', 'source': 'verified-stripe-invoice'}},
                {'id': 'reserve', 'reservationId': 'reserve', 'credits': {'op': 'reserve',
                 'allocations': [{'grantId': 'lot', 'milli': 9000}]}}]
        events.observe_expiry(self.cur, W, rows, 99)
        self.assertFalse(self.cur.events)
        events.observe_expiry(self.cur, W, rows, 101)
        events.observe_expiry(self.cur, W, rows, 102)
        self.assertEqual(len(self.cur.events), 1)
        props = next(v[1] for v in self.cur.events.values())
        self.assertEqual((props['expiredMilliCredits'], props['heldMilliCredits']), (1000, 9000))
        self.assertFalse(any('INSERT INTO public.pr_usage_ledger' in sql for sql, _ in self.cur.calls))

    def test_first_value_ttl_does_not_turn_later_adoption_into_another_first(self):
        events.first_value(self.cur, W, 'run-first', 1)
        self.assertEqual(len(self.cur.events), 1)
        self.cur.events.clear()  # migration025 TTL retention, not a real user deletion
        events.first_value(self.cur, W, 'run-later', 1)
        self.assertFalse(self.cur.events, 'durable audit must preserve first-value identity after product TTL')


class Hooks(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(events, 'Task11 helper missing')

    def test_persisted_assignment_observed_without_rerandomizing(self):
        from postriff_phase2.plan_pricing import PlanPricing
        cur = Cursor()
        replies = iter([(W,), None, ('creator-49-v1',)])
        cur.execute = lambda *args: None
        cur.fetchone = lambda: next(replies)
        variant = {'planTermsId': 'creator-v1', 'priceVariantId': 'creator-49-v1'}
        with patch.object(PlanPricing, 'variant', return_value=variant), patch.object(events, 'assigned') as assigned:
            self.assertEqual(PlanPricing().assign(cur, W), variant)
            self.assertTrue(assigned.called, 'persisted assignment must be observed from the stored variant')

    def test_default_offer_is_available_without_assignment_or_exposure(self):
        from postriff_phase2.plan_pricing import PlanPricing
        for enabled, cohort in ((False, (W,)), (True, (OTHER,))):
            cur = Cursor()
            replies = iter([(W,), None, None])
            cur.execute = lambda sql, args=(): cur.calls.append((sql, args))
            cur.fetchone = lambda: next(replies)
            variant = {'planTermsId': 'creator-v1', 'priceVariantId': 'creator-59-v1'}
            with patch.object(PlanPricing, 'variant', return_value=variant), patch.object(events, 'assigned') as assigned:
                self.assertEqual(PlanPricing(enabled, cohort).assign(cur, W), variant)
                assigned.assert_not_called()
                self.assertFalse(any('INSERT' in sql for sql, _ in cur.calls))

    def test_successful_checkout_is_observed_using_actual_returned_session(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from postriff_phase2.hosted import HostedWorkspaceService
        cur = Cursor()
        @contextmanager
        def transaction(*args):
            yield cur, {}, 'owner'
        provider_calls, new_offers = [], []
        def create(**kw):
            provider_calls.append(kw)
            return {'sessionId': 'cs_PRIVATE', 'url': 'https://PRIVATE'}
        provider = SimpleNamespace(id='stripe', create_checkout_session=create)
        service = object.__new__(HostedWorkspaceService)
        service._live_provider = lambda: provider
        service._app_url = lambda *args: 'https://example.test'
        service._email_for = lambda *args: 'private@example.test'
        service.clock = lambda: 100
        service.repository = SimpleNamespace(transaction=transaction)
        service.billing = SimpleNamespace(pricing_v2_enabled=True, lifecycle=lambda *args: None,
            pricing=SimpleNamespace(freeze_offer=lambda *args: new_offers.append(args), checkout=lambda *args: {'priceVariantId': 'creator-49-v1', 'priceId': 'price_PRIVATE'}))
        with patch('postriff_phase2.hosted.require'), patch('postriff_phase2.hosted._membership'), patch('postriff_phase2.hosted.throttle'), patch('postriff_phase2.hosted.audit'):
            service.billing_checkout(W, 'fixture', 'creator-v1')
            self.assertFalse(new_offers, 'Task11 must not add default offer persistence before or after provider I/O')
            self.assertEqual(len(provider_calls), 1)
            with patch.object(events, 'emit', side_effect=RuntimeError('synthetic telemetry failure')), patch('builtins.print'):
                result = service.billing_checkout(W, 'fixture', 'creator-v1')
                self.assertEqual(result['sessionId'], 'cs_PRIVATE', 'valid provider success must survive analytics failure without provider retry')
            self.assertEqual(len(provider_calls), 2)
            with patch.object(provider, 'create_checkout_session', side_effect=RuntimeError('synthetic provider failure')) as failed:
                with self.assertRaises(RuntimeError):
                    service.billing_checkout(W, 'fixture', 'creator-v1')
                self.assertEqual(failed.call_count, 1, 'Task11 cannot retry a provider failure')
        self.assertEqual({name for name, _ in cur.events}, {'checkout.started'})
        self.assertNotIn('PRIVATE', repr(cur.events))

    def test_first_value_only_after_actual_saved_ideas_command(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from postriff_phase2.ideas import IdeasService
        cur = Cursor()
        execute = cur.execute
        artifact = {'variants': [{'text': 'PRIVATE DRAFT', 'sourceIds': [], 'unknowns': [],
                                  'platform': 'Threads', 'language': 'English'}]}
        def sql(statement, args=()):
            execute(statement, args)
            if statement.startswith('SELECT status,artifact'):
                cur.result = ('completed', artifact, 'hash', 1, 'context', 'fixture')
            elif statement.startswith('SELECT 1 FROM public.pr_product_events'):
                cur.result = (1,) if any(name == 'first_value.completed' for name, _ in cur.events) else None
        cur.execute = sql
        state = {'variants': [], 'speaker': {}, 'brief': {'revision': 1}, 'phase2': {}}
        @contextmanager
        def transaction(*args):
            yield cur, {}, 'owner'
        def command(wid, token, revision, fn, after=None):
            fn(state, 'owner')
            after(cur, state, 'owner')
            return {'revision': 2}
        service = object.__new__(IdeasService)
        service.repository = SimpleNamespace(transaction=transaction, command=command)
        service._member = lambda *args: {}
        service.clock = lambda: 100
        with patch('postriff_phase2.ideas.require'), patch('postriff_phase2.ideas.stamp'), \
                patch('postriff_phase2.ideas.project_context', return_value={'policyEpoch': 1, 'sources': [], 'excluded': []}), \
                patch('postriff_phase2.ideas.voice_sources.validate_bindings'), patch('postriff_phase2.ideas.learning.revision', return_value=1):
            result = service.apply(W, 'fixture', 1, 'run', 'hash')
            self.assertEqual(result['status'], 'applied')
            self.assertEqual(len(state['variants']), 1)
            self.assertEqual({name for name, _ in cur.events}, {'first_value.completed'}, 'saved Ideas result must be first value')
            service.apply(W, 'fixture', 2, 'later-run', 'hash')
        self.assertEqual(len(cur.events), 1, 'later saves are not additional first values')
        self.assertNotIn('PRIVATE', repr(cur.events))


    def test_credit_claim_observes_actual_hold(self):
        cur = Cursor()
        cur.execute = lambda *args: None
        cur.result = ('quote',)
        with patch.object(events, 'emit') as emit:
            CreditBook().claim(cur, W, 'reservation', {'maximum': 9000, 'quoteId': 'quote', 'policy': 'credits-v2-2026-09-28'})
            self.assertTrue(emit.called, 'an actual credit claim needs a held observation')

    def test_wallet_read_observes_expiry_even_without_current_paid_terms(self):
        with patch.object(CreditBook, 'rows', return_value=[]), patch.object(events, 'observe_expiry') as observe:
            CreditBook(clock=lambda: 100).view(Cursor(False), W)
            self.assertTrue(observe.called, 'wallet projection must observe expired immutable lots')

    def test_actual_ledger_unknown_hooks_pending_without_releasing(self):
        cur = Cursor()
        def execute(sql, args=()):
            if sql.startswith('SELECT meta FROM'):
                cur.result = ({'credits': {'maximum': 9000, 'policy': 'credits-v2-2026-09-28'}, 'budgetScopes': []},)
            elif sql.startswith('SELECT dimension,estimated'):
                cur.result = ('tool', 10000, False, 'fixture', 'fixture', None, None, None)
            else:
                cur.result = None
        cur.execute = execute
        with patch.object(events, 'settled') as settled:
            result = Ledger(credits_enabled=True).settle(cur, W, 'reservation', 'unknown', None)
            self.assertEqual(result['state'], 'estimated_unknown')
            self.assertTrue(settled.called, 'unknown immutable settlement needs analytics')

    def test_platform_failure_without_verified_cost_retains_unknown_hold(self):
        cur = Cursor()
        def execute(sql, args=()):
            if sql.startswith('SELECT meta FROM'):
                cur.result = ({'platformPreview': {'synthetic': True}, 'budgetScopes': []},)
            elif sql.startswith('SELECT dimension,estimated'):
                cur.result = ('tool', 10000, False, 'fixture', 'fixture', None, None, None)
            elif 'to_regclass' in sql:
                cur.result = (False,)
            else:
                cur.result = None
        cur.execute = execute
        result = Ledger().settle(cur, W, 'reservation', 'failed', None)
        self.assertEqual(result['state'], 'estimated_unknown', 'unknown platform usage cannot become a measured zero/release')

    def test_actual_growth_sink_records_late_physical_usage(self):
        from postriff_phase2.growth.usage import PostgresUsageSink, UsageEvent
        cur = Cursor()
        cur.execute = lambda *args: None
        cur.result = ('row-id',)
        event = UsageEvent('postdoctor.judge', 'fixture', 'primary', 'ok', 1,
                           workspace_id=W, cost_usd=.013, cost_source='gateway', input_tokens=100000)
        with patch.object(events, 'growth_usage') as usage:
            PostgresUsageSink(cur).record(event)
            self.assertTrue(usage.called, 'the durable sink must emit actual usage independently of content consent')
            self.assertEqual(usage.call_args.args[2], 'row-id')

    def test_unscoped_growth_compatibility_does_not_read_or_emit_private_identity(self):
        from postriff_phase2.growth.usage import PostgresUsageSink, UsageEvent
        for workspace in (None, '', 'legacy-synthetic-workspace'):
            cur = Cursor()
            cur.result = ('compatibility-row',)
            event = UsageEvent('postdoctor.judge', 'fixture', 'primary', 'ok', 1,
                               workspace_id=workspace, cost_usd=.013, cost_source='gateway')
            with patch.object(events, 'growth_usage') as usage, patch.object(cur, 'fetchone') as fetched:
                PostgresUsageSink(cur).record(event)
                self.assertFalse(usage.called, 'unscoped usage is retained only in the original sink')
                self.assertFalse(fetched.called, 'compatibility sink has no returned UUID identity')
                self.assertEqual(len(cur.calls), 1)
                self.assertNotIn('RETURNING', cur.calls[0][0])

    def test_actual_weekly_accept_is_adoption_not_rejection(self):
        from postriff_phase2.coworker.service import CoworkerService
        week = {'id': 'week', 'state': 'ready_for_review', 'slots': [
            {'id': 'slot-a', 'status': 'ready', 'variantId': 'draft'},
            {'id': 'slot-b', 'status': 'ready', 'variantId': 'draft2'}]}
        state = {'coworker': {'weekly': {'weeks': [week], 'revision': 0}}}
        service = object.__new__(CoworkerService)
        service.clock = lambda: 100
        service._require = lambda *args: None
        service._state = lambda *args: state
        cur = Cursor()
        def command(wid, token, fn, requirement, audit, subject, meta, after=None):
            fn(state, 'actor')
            if after:
                after(cur, state, 'actor')
        service._command = command
        service.weekly_slot(W, 'fixture', 'week', 'slot-a', 'reject', {'reason': 'PRIVATE'})
        self.assertFalse(cur.events)
        service.weekly_slot(W, 'fixture', 'week', 'slot-b', 'accept')
        self.assertEqual({name for name, _ in cur.events}, {'weekly_pack.adopted'}, 'only successful stored acceptance is adoption')
        self.assertNotIn('PRIVATE', repr(cur.events))

    def test_grant_adjust_emits_from_returned_immutable_entry(self):
        cur = Cursor()
        def execute(sql, args=()):
            cur.result = ('entry',) if 'INSERT INTO public.pr_usage_ledger' in sql else None
        cur.execute = execute
        with patch('postriff_phase2.credit_wallet.CreditBook.policy', return_value='credits-v2-2026-09-28'):
            if events is None:
                self.fail('credit grant analytics missing')
            with patch.object(events, 'emit') as emit:
                CreditBook().grant(cur, W, None, 'invoice', 3500000, source='verified-stripe-invoice')
                self.assertTrue(emit.called, 'CreditBook must record actual appended grant')
                self.assertEqual(emit.call_args.args[4], 'entry')


class PortableFixture(unittest.TestCase):
    def test_port_range_and_fixed_loopback_without_connecting(self):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).parent / 'phase2/postgres_pricing_beta_events.py'
        spec = importlib.util.spec_from_file_location('task11_pg_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for value in ('1024', '55439', '65535'):
            self.assertEqual(module.test_port(value), int(value))
        for value in ('1023', '65536', '-1', ' 55439', '55439 host=example.test', '５５４３９', '', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.test_port(value)
        self.assertTrue(module.DSN.startswith('host=127.0.0.1 '))


class AcceptedBilling(unittest.TestCase):
    def process(self, *, stale=False, valid=True, duplicate=False, ignored=False):
        from types import SimpleNamespace
        event = {'id': 'signed-delivery', 'type': 'unsupported' if ignored else 'subscription.updated',
                 'stripeType': 'invoice.paid', 'workspaceId': W, 'createdAt': 100,
                 'invoiceId': 'immutable-invoice', 'invoicePaid': True, 'amountPaid': 4700,
                 'currency': 'usd', 'billingReason': 'subscription_cycle'}
        cur = Cursor()
        execute = cur.execute
        def sql(statement, args=()):
            execute(statement, args)
            if statement.startswith('SELECT outcome FROM public.pr_billing_events'):
                cur.result = ('applied',) if duplicate else None
            elif statement.startswith('SELECT extract(epoch from last_event_at)'):
                cur.result = (101,) if stale else None
            elif statement.startswith('SELECT entitlements FROM public.pr_plan_terms'):
                cur.result = ({},)
        cur.execute = sql
        provider = SimpleNamespace(id='stripe', parse_webhook=lambda *args: dict(event))
        billing = Billing(provider=provider)
        def resolve(cursor, mapped):
            mapped.update(planTermsId='creator-v1', priceVariantId='creator-49-v1')
            return valid
        with patch.object(billing.pricing, 'resolve_event', side_effect=resolve), \
                patch.object(billing.pricing, 'assign', side_effect=AssertionError('invoice attribution must not consult current assignment')), \
                patch.object(billing, '_reconcile_entitlement'), patch.object(billing, '_grant_period_credits') as grant:
            result = billing.process_webhook(cur, 'synthetic signature boundary', b'synthetic body')
        return result, cur, grant

    def test_accepted_and_stale_invoices_observe_resolved_signed_money(self):
        for stale in (False, True):
            result, cur, grant = self.process(stale=stale)
            self.assertEqual(result['outcome'], 'stale' if stale else 'applied')
            grant.assert_called_once()
            self.assertEqual({name for name, _ in cur.events}, {'subscription.paid', 'renewal.paid'})
            for _, props, occurred in cur.events.values():
                self.assertEqual((props['priceVariant'], props['revenueCents'], occurred), ('creator-49-v1', 4700, 100))

    def test_rejected_ignored_and_duplicate_deliveries_emit_nothing(self):
        for options, outcome in (({'valid': False}, 'rejected'), ({'ignored': True}, 'ignored'), ({'duplicate': True}, 'duplicate')):
            result, cur, grant = self.process(**options)
            self.assertEqual(result['outcome'], outcome)
            self.assertFalse(cur.events)
            grant.assert_not_called()

    def test_signed_checkout_identity_is_session_and_ignores_private_response_fields(self):
        mapped = StripePaymentProvider.map_event('delivery', 'checkout.session.completed', 100,
            {'id': 'immutable-session', 'mode': 'subscription', 'url': 'PRIVATE URL',
             'metadata': {'workspace_id': W, 'plan_terms_id': 'creator-v1', 'price_variant_id': 'creator-79-v1'},
             'customer_details': {'email': 'PRIVATE EMAIL'}})
        cur = Cursor()
        self.assertEqual(mapped['checkoutSessionId'], 'immutable-session')
        events.signed_billing(cur, mapped, 'stripe')
        events.signed_billing(cur, {**mapped, 'id': 'another-delivery'}, 'stripe')
        self.assertEqual(len(cur.events), 1)
        self.assertNotIn('PRIVATE', repr(cur.events))
        self.assertNotIn('immutable-session', repr(cur.events))


if __name__ == '__main__':
    unittest.main(verbosity=2)
