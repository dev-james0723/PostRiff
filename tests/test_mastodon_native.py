"""Approved native schedule synchronization, synthetic provider evidence only."""
import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from postriff_phase2.mastodon_native import same_instant, synchronize
from postriff_phase2.mastodon_management import MastodonManagement


class NativeSynchronizationTests(unittest.TestCase):
    def test_queue_native_time_is_canonical_frozen_and_checked_against_service_clock(self):
        from postriff_phase2.publish_options import normalize
        from postriff_alpha.domain import AlphaError
        now = 1_800_000_000
        at = datetime.fromtimestamp(now + 600, timezone.utc).isoformat().replace('+00:00', 'Z')
        options = {'scheduled_at': at, 'visibility': 'unlisted', 'spoiler_text': 'SYNTHETIC'}
        normalized = normalize('Mastodon', options, [], 'SYNTHETIC', now=now)
        self.assertEqual(normalized['scheduled_at'], at.replace('Z', '+00:00'))
        self.assertEqual(normalized['visibility'], 'unlisted'); self.assertEqual(options['scheduled_at'], at)
        with self.assertRaises(AlphaError): normalize('Mastodon', options, [], 'SYNTHETIC', now=now + 301)
        self.assertIsNone(normalize('Mastodon', None, [], 'SYNTHETIC', now=now))

    def setUp(self):
        self.manifest = {'platform': 'Mastodon', 'channelId': 'one', 'providerAccountId': '10@mastodon.social',
                         'payload': {'text': 'Unchanged'}, 'timing': {'nativePublicationAt': '2026-10-12T10:00:00Z'}}
        self.job = {'id': 'job', 'manifest': copy.deepcopy(self.manifest), 'state': 'processing', 'approvalDigest': 'original',
                    'progress': {'stage': 'native_scheduled', 'reference': '41', 'scheduledAt': '2026-10-12T10:00:00Z'},
                    'leaseOwner': 'old-worker', 'leaseId': 'old-fence', 'leaseUntil': 1000}
        self.state = {'phase2': {'jobs': [self.job]}}
        self.preview = {'action': 'native_reschedule', 'accountId': '10@mastodon.social',
                        'path': '/api/v1/scheduled_statuses/41', 'body': {'scheduled_at': '2026-10-13T11:00:00Z'}}
        self.receipt = {'state': 'verified', 'verification': 'native_schedule_lookup', 'reference': '41', 'scheduledAt': '2026-10-13T11:00:00+00:00'}

    def sync(self, preview=None, receipt=None, connection='one'):
        return synchronize(self.state, connection, preview or self.preview, receipt or self.receipt,
                           actor='owner', action_id='exact-action', fingerprint='exact-digest', now=900)

    def test_verified_amendment_preserves_manifest_and_fences_old_lookup(self):
        self.assertEqual(self.sync(), ['job'])
        self.assertEqual(self.job['manifest'], self.manifest); self.assertEqual(self.job['approvalDigest'], 'original')
        self.assertEqual(self.job['nativeScheduleChange']['approvalDigest'], 'exact-digest')
        self.assertEqual(self.job['progress']['scheduledAt'], self.receipt['scheduledAt'])
        self.assertEqual(self.job['state'], 'processing'); self.assertIsNone(self.job['leaseOwner']); self.assertIsNone(self.job['leaseId'])

    def test_acceptance_wrong_time_wrong_schedule_and_other_connection_never_update(self):
        before = copy.deepcopy(self.state)
        for update in ({'state': 'accepted'}, {'scheduledAt': '2026-10-13T12:00:00Z'}, {'reference': '42'}, {'verification': 'manual'}):
            self.assertEqual(self.sync(receipt={**self.receipt, **update}), [])
            self.assertEqual(self.state, before)
        self.assertEqual(self.sync(connection='other'), []); self.assertEqual(self.state, before)

    def test_exact_verified_cancellation_retains_posting_manifest_and_stops_lookup(self):
        preview = {**self.preview, 'action': 'native_cancel', 'body': {}}
        self.assertEqual(self.sync(preview, {'state': 'accepted'}), [])
        self.assertEqual(self.sync(preview, {'state': 'verified', 'verification': 'provider_lookup_absent'}), ['job'])
        self.assertTrue(self.job['cancelRequested']); self.assertEqual(self.job['state'], 'canceled')
        self.assertEqual(self.job['manifest'], self.manifest)

    def test_schedule_times_require_timezone_and_exact_instant(self):
        self.assertTrue(same_instant('2026-10-13T11:00:00Z', '2026-10-13T07:00:00-04:00'))
        for value in ('2026-10-13T11:00:00', None, 'invalid', '2026-10-13T11:00:01Z'):
            self.assertFalse(same_instant(value, '2026-10-13T11:00:00Z'))

    def test_provider_time_or_id_mismatch_never_verifies_native_reschedule(self):
        session = {'instance': 'mastodon.social'}
        response = {'status': 200, 'body': {'id': '41'}}
        provider = SimpleNamespace(api=lambda *_args, **_kw: {'status': 200, 'body': {'id': '41', 'scheduled_at': '2026-10-13T12:00:00Z'}})
        self.assertEqual(MastodonManagement._receipt(provider, session, self.preview, response)['state'], 'accepted')
        self.assertEqual(MastodonManagement._receipt(provider, session, self.preview, {'status': 200, 'body': {'id': '42'}})['state'], 'uncertain')
