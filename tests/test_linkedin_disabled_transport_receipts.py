"""Offline acceptance-preservation tests; no real posts or grants are exercised."""
import copy
import unittest
from postriff_phase2.contracts import digest
from postriff_phase2.hosted_worker import DisabledHostedSocial
from postriff_phase2.outcomes import normalize_result


class DisabledLinkedInReceiptTests(unittest.TestCase):
    def setUp(self):
        self.adapter = DisabledHostedSocial()
        self.manifest = {'workspaceId': 'synthetic-workspace', 'channelId': 'synthetic-connection',
                         'platform': 'LinkedIn', 'providerAccountId': 'urn:li:person:synthetic',
                         'actor': 'synthetic-actor', 'idempotencyKey': 'synthetic-key',
                         'expiresAt': 1, 'payload': {'text': 'Offline fixture only'}}
        self.job = {'id': 'synthetic-job', 'manifest': copy.deepcopy(self.manifest),
                    'approvalDigest': digest(self.manifest), 'approvedBy': 'synthetic-actor',
                    'resultSchema': 'postriff.result.v1', 'state': 'provider_accepted',
                    'providerReference': 'urn:li:share:123',
                    'url': 'https://www.linkedin.com/feed/update/urn:li:share:123/',
                    'attempts': [{'number': 1, 'startedAt': 1, 'endedAt': 2}]}

    def reconcile(self):
        return self.adapter.reconcile(self.manifest, self.job)

    def test_known_acceptance_survives_disabled_transport_without_claiming_readback(self):
        before = copy.deepcopy(self.job)
        result = self.reconcile()
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(result['reference'], self.job['providerReference'])
        self.assertEqual(result['url'], self.job['url'])
        self.assertNotIn('verification', result)
        self.assertIn('unavailable', result['confirmed'])
        self.assertIn('do not resubmit', result['confirmed'])
        self.assertEqual(self.job, before, 'Read-only fallback must not rewrite durable job state')

    def test_existing_acceptance_is_not_reauthorized_to_create_again(self):
        self.job['cancelRequested'] = True
        result = normalize_result(self.reconcile(), self.job, reconciliation=True)
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertNotIn('retryAfterSeconds', result)
        self.assertNotIn('verification', result)
        self.assertEqual(result['reference'], 'urn:li:share:123')
        self.assertEqual(self.adapter.submit(self.manifest)['state'], 'held')
        self.assertEqual(len(self.job['attempts']), 1)

    def test_expired_approval_does_not_erase_historical_acknowledgment(self):
        self.assertEqual(self.manifest['expiresAt'], 1)
        self.assertEqual(self.reconcile()['state'], 'provider_accepted')

    def test_ugcpost_receipt_is_supported(self):
        self.job.update(providerReference='urn:li:ugcPost:456', url=None)
        result = self.reconcile()
        self.assertEqual(result['state'], 'provider_accepted')
        self.assertEqual(result['url'], 'https://www.linkedin.com/feed/update/urn:li:ugcPost:456/')

    def test_reference_alone_does_not_restore_ambiguous_or_failed_jobs(self):
        for state in ('uncertain', 'submitting', 'scheduled', 'held', 'failed', 'canceled', 'verified', None):
            with self.subTest(state=state):
                self.job['state'] = state
                self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_legacy_event_is_not_enough_to_repair_real_uncertain_job(self):
        self.job.update(state='uncertain', events=[{'state': 'provider_accepted', 'at': 1}])
        self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_mutated_approval_digest_is_not_accepted(self):
        self.job['approvalDigest'] = '0' * 64
        self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_manifest_binding_mismatch_is_not_accepted(self):
        for name in ('workspaceId', 'channelId', 'providerAccountId', 'actor', 'idempotencyKey'):
            with self.subTest(name=name):
                self.job['manifest'][name] = 'other'
                self.assertEqual(self.reconcile()['state'], 'uncertain')
                self.job['manifest'] = copy.deepcopy(self.manifest)

    def test_approver_mismatch_is_not_accepted(self):
        self.job['approvedBy'] = 'another-actor'
        self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_missing_manifest_identity_is_not_accepted(self):
        for name in ('workspaceId', 'channelId', 'actor', 'providerAccountId', 'idempotencyKey'):
            manifest = copy.deepcopy(self.manifest)
            del manifest[name]
            self.job['manifest'] = manifest
            self.job['approvalDigest'] = digest(manifest)
            with self.subTest(name=name):
                self.assertEqual(self.adapter.reconcile(manifest, self.job)['state'], 'uncertain')

    def test_missing_or_unknown_result_schema_is_not_accepted(self):
        for schema in (None, '', 'anything'):
            self.job['resultSchema'] = schema
            self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_bad_provider_reference_is_not_accepted(self):
        for reference in (None, 123, '', '123', 'urn:li:person:123', 'urn:li:share:123\n', 'urn:li:share:../private'):
            with self.subTest(reference=reference):
                self.job['providerReference'] = reference
                self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_other_providers_remain_fail_closed(self):
        for platform in ('X', 'Discord', 'YouTube', 'Facebook'):
            self.manifest['platform'] = platform
            self.job['manifest'] = copy.deepcopy(self.manifest)
            self.job['approvalDigest'] = digest(self.manifest)
            self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_conflicting_or_untrusted_receipt_url_is_not_accepted(self):
        for url in ('https://example.invalid/private', 'https://www.linkedin.com/feed/update/urn:li:share:999/'):
            self.job['url'] = url
            self.assertEqual(self.reconcile()['state'], 'uncertain')

    def test_partial_or_malformed_jobs_fail_closed_without_throwing(self):
        for manifest, job in (({}, {}), ({'platform': 'LinkedIn'}, {}), (self.manifest, {'state':'provider_accepted'})):
            with self.subTest(job=job):
                self.assertEqual(self.adapter.reconcile(manifest, job)['state'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
