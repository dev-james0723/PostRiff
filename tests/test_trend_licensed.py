"""Offline licensed aggregate import contracts; no vendor access or rights approval."""
from dataclasses import replace

from postriff_phase2.growth.trends import contracts as C
from postriff_phase2.growth.trends.policy import ProviderCapability
from postriff_phase2.growth.trends.providers.licensed import import_batch
import test_trend_contracts as F


class LicensedAggregateImport(F.OfflineTest):
    def setUp(self):
        super().setUp()
        self.capability = ProviderCapability(
            provider_id='fixture', operation='sample', version='fixture-v1',
            evidence_kinds=('aggregate_metric',), endpoint='offline:synthetic-export',
            protocol='authorized_export', credential_class='offline', required_scopes=('read',),
            max_items=2, max_response_bytes=32000, timeout_seconds=1, max_attempts=1,
            billable_unit='authorized_offline_export', deletion_mechanism='revision_tombstone')

    def load(self, rows, **overrides):
        args = dict(capability=self.capability, policy=F.policy(), at=F.NOW,
                    enabled=True, entitlement_current=True, reservation_microusd=0,
                    provider_revision='synthetic-export-1')
        args.update(overrides)
        return import_batch(rows, **args)

    def test_aggregate_only_import_preserves_zero_and_unknown_without_post_records(self):
        zero = F.row('aggregate_metric')
        missing = F.row('aggregate_metric', source_identity='missing')
        missing['payload'].update(value=None, null_reason='not_returned')
        missing['payload_digest'] = C.digest(missing['payload'])
        batch = self.load([zero, missing])
        self.assertEqual(batch.observations, (zero, missing))
        self.assertEqual(batch.observations[0]['payload']['value'], 0)
        self.assertIsNone(batch.observations[1]['payload']['value'])
        self.assertEqual(batch.completeness, 'partial')
        self.assertFalse(batch.terminal_page)
        self.assertIsNone(batch.cost_microusd)
        for item in batch.observations:
            self.assertEqual(item['kind'], 'aggregate_metric')
            self.assertNotIn('native_id', item['payload'])
            self.assertNotIn('representative_posts', item['payload'])

    def test_empty_terminal_export_does_not_invent_zero_measurement(self):
        batch = self.load([], terminal_page=True)
        self.assertEqual(batch.observations, ())
        self.assertTrue(batch.terminal_page)
        self.assertEqual(batch.completeness, 'complete_within_scope')

    def test_aggregate_capability_rejects_posts_and_cross_domain_or_revision_rows(self):
        self.reject(self.load, [F.row()])
        self.reject(self.load, [F.row('aggregate_metric', scope_key='workspace:' + F.OTHER)])
        for key in ('provider_id', 'provider_contract_version', 'source_policy_version'):
            with self.subTest(key=key):
                bad = F.row('aggregate_metric'); bad[key] = 'another'
                self.reject(self.load, [bad])

    def test_unknown_revoked_expired_or_unentitled_access_fails_closed(self):
        rows = [F.row('aggregate_metric')]
        for args in (
            {'enabled': False}, {'entitlement_current': False},
            {'policy': F.policy(rights=F.permissions(retrieve='unknown'))},
            {'policy': F.policy(revoked_at=F.NOW)}, {'at': F.AFTER},
            {'policy': F.policy(verified_scopes=())},
        ):
            with self.subTest(args=args):
                self.reject(self.load, rows, **args)

    def test_item_byte_and_paid_reservation_limits_apply_before_import(self):
        rows = [F.row('aggregate_metric')]
        self.reject(self.load, rows * 3)
        large = F.row('aggregate_metric'); large['payload']['population'] = 'a' * 2000
        large['payload_digest'] = C.digest(large['payload'])
        self.reject(self.load, [large], capability=replace(self.capability, max_response_bytes=1024))
        paid = replace(self.capability, billable_unit='request')
        self.reject(self.load, rows, capability=paid)
        self.reject(self.load, rows, capability=paid, reservation_microusd=101)
        batch = self.load(rows, capability=paid, reservation_microusd=100)
        self.assertIsNone(batch.cost_microusd, 'reservation is not observed provider cost')
