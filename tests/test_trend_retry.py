"""Adversarial retry certainty and quarantine contracts; no live I/O."""
from unittest.mock import patch, Mock
import unittest
import copy
import uuid

from test_trend_contracts import OfflineTest, NOW, SCOPE
from test_trend_planner import FakeStore, PostgresFixture, PG_DSN, CAP
from postriff_phase2.growth.trends.retry import decide, retry_after, fail_attempt
from postriff_phase2.growth.trends import quarantine
from postriff_phase2.growth.trends.contracts import digest


class RetryTests(OfflineTest):
    def decision(self, **kwargs):
        inputs = dict(now=NOW, attempt=1, max_attempts=3, dispatched=True, proven_unbilled=True)
        inputs.update(kwargs)
        return decide(**inputs)

    def test_auth_access_budget_are_terminal_pauses(self):
        for code in (401, 402, 403):
            with self.subTest(code=code):
                value = self.decision(status=code)
                self.assertTrue(value.pause)
                self.assertIsNone(value.delay_seconds)

    def test_pause_does_not_release_unknown_paid_exposure(self):
        for code in (401, 402, 403, 429, 500, 503, None):
            value = self.decision(status=code, proven_unbilled=False)
            self.assertTrue(value.outcome_unknown)
            self.assertIsNone(value.delay_seconds)

    def test_client_schema_errors_do_not_retry(self):
        for code in (400, 404, 405, 409, 422):
            value = self.decision(status=code)
            self.assertEqual(value.code, 'provider_request_terminal')
            self.assertIsNone(value.delay_seconds)

    def test_transient_retries_have_exponential_bounded_jitter(self):
        for code in (429, 500, 502, 503, 599, None):
            for attempt in (1, 2):
                low = self.decision(status=code, attempt=attempt, jitter=0)
                high = self.decision(status=code, attempt=attempt, jitter=1)
                self.assertLessEqual(low.delay_seconds, high.delay_seconds)
                self.assertEqual(high.delay_seconds, 5 * 2 ** (attempt - 1))

    def test_attempt_ceiling_is_terminal(self):
        value = self.decision(status=503, attempt=3)
        self.assertEqual(value.code, 'provider_attempts_exhausted')
        self.assertIsNone(value.delay_seconds)

    def test_predispatch_failure_is_retryable_without_billing_claim(self):
        value = self.decision(status=None, dispatched=False, proven_unbilled=False)
        self.assertFalse(value.outcome_unknown)
        self.assertIsNotNone(value.delay_seconds)

    def test_retry_after_delta_and_http_date_are_minimums(self):
        for headers in ({'Retry-After': '120'}, {'retry-after': 'Sun, 27 Sep 2026 12:02:00 GMT'}):
            self.assertEqual(self.decision(status=429, headers=headers).delay_seconds, 120)

    def test_retry_after_past_and_malformed_headers(self):
        self.assertEqual(retry_after({'Retry-After': 'Sun, 27 Sep 2026 11:00:00 GMT'}, now=NOW), 0)
        for headers in (None, {}, {'Retry-After': '-1'}, {'Retry-After': 'NaN'},
                        {'Retry-After': '1.5'}, {'Retry-After': 10}, {'Retry-After': 'x' * 129},
                        {'Retry-After': '1', 'retry-after': '2'}, {str(n): 'x' for n in range(65)}):
            self.assertIsNone(retry_after(headers, now=NOW))

    def test_provider_wait_beyond_horizon_stops_instead_of_retrying_early(self):
        value = self.decision(status=429, headers={'Retry-After': '99999999999999'})
        self.assertEqual(value.code, 'retry_horizon_exceeded')
        self.assertIsNone(value.delay_seconds)
        self.assertIsNone(self.decision(status=429, headers={'Retry-After': '99999999999999'},
                                       ceiling_seconds=86400).delay_seconds)

    def test_absolute_deadline_is_exclusive(self):
        value = self.decision(status=503, jitter=1, deadline='2026-09-27T12:00:05Z')
        self.assertIsNone(value.delay_seconds)

    def test_nan_boolean_and_unbounded_retry_inputs_rejected(self):
        for kwargs in ({'jitter': float('nan')}, {'jitter': True}, {'attempt': True},
                       {'max_attempts': 4}, {'status': True}, {'status': 600},
                       {'dispatched': 'yes'}, {'proven_unbilled': 1}, {'ceiling_seconds': 86401}):
            self.reject(self.decision, **kwargs)

    def test_durable_failure_and_pause_share_transaction_and_no_raw_headers(self):
        store = FakeStore()
        claim = dict(scope_key=SCOPE, provider_id='fixture', attempts=1, max_attempts=3)
        with patch('postriff_phase2.growth.trends.retry.TrendJobs') as jobs, \
             patch('postriff_phase2.growth.trends.retry.source_health.record') as health:
            jobs.return_value.fail.return_value = {'state': 'outcome_unknown'}
            result = fail_attempt(store, claim, status=403, headers={'x-private': 'secret'}, dispatched=True, now=NOW)
            self.assertEqual(result['job']['state'], 'outcome_unknown')
            kwargs = jobs.return_value.fail.call_args.kwargs
            self.assertFalse(kwargs['proven_unbilled'])
            self.assertIsNone(kwargs['retry_after_seconds'])
            self.assertIs(kwargs['cursor'], health.call_args.kwargs['cursor'])
            self.assertEqual(health.call_args.kwargs['status'], 'revoked')
            self.assertNotIn('secret', str(health.call_args))

    def test_pre_dispatch_failure_releases_reservation(self):
        with patch('postriff_phase2.growth.trends.retry.TrendJobs') as jobs, \
             patch('postriff_phase2.growth.trends.retry.source_health.record'):
            fail_attempt(FakeStore(), dict(scope_key=SCOPE, provider_id='fixture', attempts=1, max_attempts=3),
                         dispatched=False, now=NOW)
            self.assertTrue(jobs.return_value.fail.call_args.kwargs['proven_unbilled'])

    def test_transient_failure_cannot_clear_prior_permanent_pause(self):
        store = FakeStore(); store.health = {'status': 'revoked'}
        with patch('postriff_phase2.growth.trends.retry.TrendJobs'), \
             patch('postriff_phase2.growth.trends.retry.source_health.record') as health:
            fail_attempt(store, dict(scope_key=SCOPE, provider_id='fixture', attempts=1, max_attempts=3),
                         dispatched=False, status=503, now=NOW)
            health.assert_not_called()


def receipt(**changes):
    value = dict(schema_version=quarantine.SCHEMA, job_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        lease_generation=1, partition_key=digest('synthetic-partition'), generation=1,
        accepted_count=0, quarantined_count=1, entries=[{'index': 0, 'reason_code': 'jetstream_invalid_frame'}],
        completeness='gap')
    value.update(changes)
    return value


class QuarantineTests(OfflineTest):
    def test_thousand_longest_codes_split_without_loss_under_jsonb_limit(self):
        import json
        entries = [{'index': n + 9000, 'reason_code': 'mastodon_canonical_identity_required'} for n in range(1000)]
        claim = dict(job_id=receipt()['job_id'], scope_key=SCOPE, lease_generation=2**63 - 1)
        cur = object()
        with patch.object(quarantine, 'TrendJobs') as jobs, patch.object(quarantine, 'TrendOutbox') as outbox:
            jobs.return_value._fence.return_value = {'state': 'running', 'kind': 'trend.ingest'}
            outbox.return_value.enqueue.side_effect = [{'event_id': 'primary'}, {'event_id': 'second'}]
            result = quarantine.record_batch(FakeStore(), claim, partition_key=receipt()['partition_key'],
                expected_generation=2**63 - 2, accepted_count=1000, quarantined=entries, cursor=cur)
            calls = outbox.return_value.enqueue.call_args_list
        self.assertEqual(result, {'event_id': 'primary'})
        self.assertEqual(len(calls), 2)
        saved = []
        for call in calls:
            self.assertIs(call.kwargs['cursor'], cur)
            payload = quarantine.sanitize_receipt(call.args[3])
            self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 64 * 1024)
            self.assertEqual(payload['quarantined_count'], len(payload['entries']))
            saved.extend(payload['entries'])
        self.assertEqual(saved, entries)
        self.assertNotEqual(calls[0].args[1], calls[1].args[1])

    def test_receipt_is_exact_content_free_shape(self):
        value = receipt()
        self.assertEqual(quarantine.sanitize_receipt(value), value)

    def test_unknown_arbitrary_reason_never_persists_source_text(self):
        value = quarantine.sanitize_receipt(receipt(entries=[{'index': 0, 'reason_code': 'private_source_text_123'}]))
        self.assertEqual(value['entries'][0]['reason_code'], 'invalid_record')
        self.assertNotIn('private_source_text', str(value))

    def test_raw_fields_cannot_hide_at_top_or_nested_level(self):
        self.reject(quarantine.sanitize_receipt, receipt(raw_response='private'))
        self.reject(quarantine.sanitize_receipt, receipt(entries=[{'index': 0, 'reason_code': 'invalid_record', 'text': 'private'}]))

    def test_index_count_generation_identity_and_gap_strict(self):
        for value in (receipt(generation=True), receipt(lease_generation=0), receipt(job_id='source-text'),
                      receipt(partition_key='source identity'), receipt(accepted_count=1001),
                      receipt(quarantined_count=2), receipt(completeness='complete'),
                      receipt(entries=[{'index': -1, 'reason_code': 'invalid_record'}]),
                      receipt(entries=[{'index': True, 'reason_code': 'invalid_record'}])):
            self.reject(quarantine.sanitize_receipt, value)

    def test_duplicate_indexes_and_unbounded_arrays_rejected(self):
        self.reject(quarantine.sanitize_receipt, receipt(quarantined_count=2,
            entries=[{'index': 0, 'reason_code': 'invalid_record'}] * 2))
        self.reject(quarantine.sanitize_receipt, receipt(quarantined_count=1001,
            entries=[{'index': n, 'reason_code': 'invalid_record'} for n in range(1001)]))

    def test_record_requires_batch_transaction_and_running_fence(self):
        claim = dict(job_id=receipt()['job_id'], scope_key=SCOPE, lease_generation=1)
        args = dict(partition_key=receipt()['partition_key'], expected_generation=0,
                    accepted_count=0, quarantined=receipt()['entries'])
        self.reject(quarantine.record_batch, FakeStore(), claim, **args, cursor=None)
        with patch.object(quarantine, 'TrendJobs') as jobs, patch.object(quarantine, 'TrendOutbox') as outbox:
            jobs.return_value._fence.return_value = {'state': 'leased', 'kind': 'trend.ingest'}
            self.reject(quarantine.record_batch, FakeStore(), claim, **args, cursor=object())
            outbox.return_value.enqueue.assert_not_called()

    def test_record_stable_receipt_link_and_target_generation(self):
        claim = dict(job_id=receipt()['job_id'], scope_key=SCOPE, lease_generation=1)
        cur = object()
        with patch.object(quarantine, 'TrendJobs') as jobs, patch.object(quarantine, 'TrendOutbox') as outbox:
            jobs.return_value._fence.return_value = {'state': 'running', 'kind': 'trend.ingest'}
            quarantine.record_batch(FakeStore(), claim, partition_key=receipt()['partition_key'], expected_generation=3,
                                    accepted_count=2, quarantined=receipt()['entries'], cursor=cur)
            args = outbox.return_value.enqueue.call_args
            self.assertEqual(args.args[2], 'trend.quarantined')
            self.assertEqual(args.args[3]['generation'], 4)
            self.assertEqual(args.args[3]['accepted_count'], 2)
            self.assertIs(args.kwargs['cursor'], cur)


@unittest.skipUnless(PG_DSN, 'Explicit isolated local PostgreSQL DSN not configured')
class RetryQuarantinePostgresTests(PostgresFixture):
    def test_thousand_poison_receipts_fit_jsonb_are_atomic_and_share_one_replay(self):
        claim = self.start()
        entries = [{'index': n, 'reason_code': 'mastodon_canonical_identity_required'} for n in range(1000)]
        # The frozen DB constraint really rejects the unsplit receipt.
        from psycopg.types.json import Jsonb
        large = receipt(job_id=claim['job_id'], quarantined_count=1000, entries=entries)
        self.assertGreater(self.fetch('SELECT octet_length(%s::jsonb::text)', (Jsonb(large),))[0], 64 * 1024)
        with self.assertRaisesRegex(RuntimeError, 'chunk rollback'):
            with self.store.transaction() as cur:
                quarantine.record_batch(self.store, claim, partition_key=self.partition, expected_generation=0,
                                        accepted_count=0, quarantined=entries, cursor=cur)
                raise RuntimeError('chunk rollback')
        self.assertEqual(self.fetch('SELECT count(*) FROM pr_trend_outbox WHERE scope_key=%s', (self.scope,))[0], 0)
        with self.store.transaction() as cur:
            primary = quarantine.record_batch(self.store, claim, partition_key=self.partition, expected_generation=0,
                                               accepted_count=0, quarantined=entries, cursor=cur)
            again = quarantine.record_batch(self.store, claim, partition_key=self.partition, expected_generation=0,
                                             accepted_count=0, quarantined=entries, cursor=cur)
            self.assertEqual(primary['event_id'], again['event_id'])
            self.jobs.complete_batch(claim, partition_key=self.partition, expected_generation=0,
                batch_key=digest([claim['job_id'], claim['lease_generation']]), observations=[],
                cursor_value={}, coverage_state='gap', actual_micro_usd=0, cursor=cur)
        with self.connect() as db:
            stored = db.execute("SELECT event_id::text,payload,octet_length(payload::text) FROM pr_trend_outbox WHERE scope_key=%s AND event_type='trend.quarantined' ORDER BY event_key", (self.scope,)).fetchall()
        self.assertEqual(len(stored), 2)
        self.assertTrue(all(item[2] < 64 * 1024 for item in stored))
        self.assertEqual([entry for item in stored for entry in item[1]['entries']], entries)
        # Start with the secondary: it must canonicalize to the primary even
        # before any replay exists, then all chunk IDs resolve the same job.
        second = quarantine.replay(self.store, self.planner, self.scope, stored[-1][0])
        first = quarantine.replay(self.store, self.planner, self.scope, primary['event_id'])
        self.assertEqual(second['job_id'], first['job_id'])
        self.assertEqual(first['payload']['quarantine_event_id'], primary['event_id'])
        replayed = self.start(first)
        next_event = self.commit_quarantine(replayed)
        self.reject(quarantine.replay, self.store, self.planner, self.scope, next_event['event_id'])

    def commit_quarantine(self, claim=None, *, actual=0):
        claim = claim or self.start()
        checkpoint = self.jobs.get_cursor(self.scope, 'fixture', self.partition)
        with self.store.transaction() as cur:
            event = quarantine.record_batch(self.store, claim, partition_key=self.partition,
                expected_generation=checkpoint['generation'], accepted_count=0,
                quarantined=[{'index': 0, 'reason_code': 'private_source_text'}], cursor=cur)
            self.jobs.complete_batch(claim, partition_key=self.partition, expected_generation=checkpoint['generation'],
                batch_key=digest([claim['job_id'], claim['lease_generation']]), observations=[],
                cursor_value=checkpoint['cursor_value'], coverage_state='gap', actual_micro_usd=actual, cursor=cur)
        return event

    def test_unknown_dispatched_retry_preserves_exposure_and_no_new_attempt(self):
        claim = self.start()
        result = fail_attempt(self.store, claim, status=503, dispatched=True, now=NOW)
        self.assertEqual(result['job']['state'], 'outcome_unknown')
        self.assertEqual(self.fetch('SELECT unknown_micro_usd,reserved_micro_usd FROM public.pr_trend_budget_limits WHERE budget_key=%s',
                                   (self.keys[0],)), (25, 0))
        self.assertIsNone(self.jobs.claim('again', job_id=claim['job_id'], scope_key=self.scope,
                                         budget_keys=self.keys, amount_micro_usd=25))

    def test_proven_unbilled_429_persists_retry_after_and_releases_reservation(self):
        claim = self.start()
        result = fail_attempt(self.store, claim, status=429, headers={'Retry-After': '90'},
                              dispatched=True, proven_unbilled=True, now=NOW)
        self.assertEqual(result['job']['state'], 'retry_wait')
        remaining = self.fetch('SELECT extract(epoch FROM due_at-clock_timestamp()) FROM public.pr_trend_jobs WHERE scope_key=%s AND job_id=%s',
                               (self.scope, claim['job_id']))[0]
        self.assertGreater(remaining, 80); self.assertLessEqual(remaining, 90)
        self.assertEqual(self.fetch('SELECT state FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s',
                                   (self.scope, claim['reservation_id']))[0], 'released')

    def test_402_pauses_other_jobs_and_keeps_unknown_cost(self):
        claim = self.start()
        fail_attempt(self.store, claim, status=402, dispatched=True, now=NOW)
        self.assertEqual(self.fetch('SELECT status FROM public.pr_trend_source_health WHERE scope_key=%s', (self.scope,))[0], 'revoked')
        self.reject(self.plan)
        self.assertEqual(self.fetch('SELECT state FROM public.pr_trend_budget_reservations WHERE scope_key=%s AND reservation_id=%s',
                                   (self.scope, claim['reservation_id']))[0], 'unknown')

    def test_receipt_and_batch_are_atomic_rollback_releases_no_cursor(self):
        claim = self.start()
        with self.assertRaisesRegex(RuntimeError, 'synthetic crash'):
            with self.store.transaction() as cur:
                quarantine.record_batch(self.store, claim, partition_key=self.partition, expected_generation=0,
                    accepted_count=0, quarantined=[{'index': 0, 'reason_code': 'invalid_record'}], cursor=cur)
                raise RuntimeError('synthetic crash')
        self.assertEqual(self.fetch('SELECT count(*) FROM public.pr_trend_outbox WHERE scope_key=%s', (self.scope,))[0], 0)
        self.assertEqual(self.jobs.get_cursor(self.scope, 'fixture', self.partition)['generation'], 0)

    def test_real_quarantine_is_safe_idempotent_replay_and_chain_bound(self):
        event = self.commit_quarantine()
        value = self.fetch('SELECT payload FROM public.pr_trend_outbox WHERE scope_key=%s AND event_id=%s',
                           (self.scope, event['event_id']))[0]
        self.assertNotIn('private_source_text', str(value))
        self.assertEqual(value['entries'][0]['reason_code'], 'invalid_record')
        self.assertEqual(value['completeness'], 'gap')
        first = quarantine.replay(self.store, self.planner, self.scope, event['event_id'])
        second = quarantine.replay(self.store, self.planner, self.scope, event['event_id'])
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertEqual(first['payload']['reservation_microusd'], 25)
        self.assertEqual(first['payload']['quarantine_event_id'], event['event_id'])
        replayed = self.start(first)
        next_event = self.commit_quarantine(replayed)
        self.reject(quarantine.replay, self.store, self.planner, self.scope, next_event['event_id'])
        self.assertEqual(self.jobs.get_cursor(self.scope, 'fixture', self.partition)['coverage_state'], 'gap')

    def test_unknown_cost_committed_batch_cannot_trigger_additional_paid_replay(self):
        event = self.commit_quarantine(actual=None)
        with self.assertRaisesRegex(ValueError, 'quarantine_unknown_exposure'):
            quarantine.replay(self.store, self.planner, self.scope, event['event_id'])

    def test_changed_cursor_and_foreign_scope_cannot_recover(self):
        event = self.commit_quarantine()
        with self.connect() as db:
            db.execute('UPDATE public.pr_trend_provider_cursors SET generation=generation+1 WHERE scope_key=%s', (self.scope,))
        self.reject(quarantine.replay, self.store, self.planner, self.scope, event['event_id'])
        self.reject(quarantine.replay, self.store, self.planner, 'workspace:' + str(uuid.uuid4()), event['event_id'])

    def test_revocation_blocks_recovery_but_preserves_content_free_audit(self):
        event = self.commit_quarantine()
        with self.connect() as db:
            db.execute('UPDATE public.pr_trend_source_policies SET revoked_at=clock_timestamp() WHERE scope_key=%s', (self.scope,))
        self.reject(quarantine.replay, self.store, self.planner, self.scope, event['event_id'])
        self.assertEqual(self.fetch('SELECT count(*) FROM public.pr_trend_outbox WHERE scope_key=%s', (self.scope,))[0], 1)


if __name__ == '__main__':
    unittest.main()
