"""Scenario tests consume the coordinator's exact canonical Demo seed, never a copy."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

from rafii_control.auth import ControlError

# Integration imports the canonical package normally. During isolated worker
# checks only, an explicit path selects that same coordinator-owned source file.
if os.environ.get('RAFII_FOUNDER_DEMO_MODULE'):
    module_path = Path(os.environ['RAFII_FOUNDER_DEMO_MODULE']).resolve(strict=True)
    if module_path.name != 'demo_dataset.py':
        raise RuntimeError('RAFII_FOUNDER_DEMO_MODULE must identify the actual Demo module')
    spec = importlib.util.spec_from_file_location('rafii_control.demo_dataset', module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from rafii_control.demo_dataset import bounded_snapshot, sample_data
from rafii_control.founder_preview_scenarios import apply_scenario

NOW = '2026-10-01T14:00:00Z'
LATER = '2026-10-01T15:00:00Z'


class FounderPreviewScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = sample_data()

    def setUp(self):
        self.data = copy.deepcopy(self.canonical)
        # A network tripwire covers every scenario in every test.
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('real egress is forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def scenario(self, name, now=NOW):
        return apply_scenario(self.data, name, now=now)

    def fails(self, data, scenario, code, now=NOW):
        before = copy.deepcopy(data)
        with self.assertRaises(ControlError) as caught:
            apply_scenario(data, scenario, now=now)
        self.assertEqual(caught.exception.code, 'PREVIEW_SCENARIO_' + code)
        self.assertEqual(data, before)

    def test_exact_canonical_10000_baseline_not_second_seed(self):
        collection_ids = {name: id(self.data[name]) for name in ('customers', 'workspaces', 'subscriptions', 'invoices', 'payments')}
        result = self.scenario('normal')
        self.assertEqual(self.data['summary']['currentPaidSubscriptions'], 10000)
        self.assertEqual(self.data['summary']['activeSubscriptions'], 10000)
        self.assertEqual({row['plan']: row['subscribers'] for row in self.data['analytics']['planDistribution']},
                         {'Starter': 4500, 'Creator': 4000, 'Studio': 1500})
        self.assertEqual(self.data['receipt']['seed'], self.canonical['manifest']['seed'])
        self.assertEqual(collection_ids, {name: id(self.data[name]) for name in collection_ids})
        self.assertTrue(result['simulation'])
        self.assertFalse(result['externalDelivery'])

    def test_payment_failure_links_named_source_and_derives_money_from_records(self):
        result = self.scenario('payment_failure')
        sources = result['paymentSourceIds']
        source_rows = {collection: next(row for row in self.data[collection] if row['id'] == source_id)
                       for collection, source_id in sources.items()}
        self.assertEqual(source_rows['customers']['name'], 'Leo Martins')
        subscription = source_rows['subscriptions']
        self.assertEqual(source_rows['workspaces']['id'], subscription['workspaceId'])
        self.assertNotEqual(subscription['id'], subscription['workspaceId'])
        self.assertEqual(source_rows['invoices']['subscriptionId'], subscription['id'])
        self.assertEqual(source_rows['payments']['invoiceId'], source_rows['invoices']['id'])
        summary = self.data['summary']
        self.assertEqual(summary['currentPaidSubscriptions'], 10000)
        self.assertEqual(summary['activeSubscriptions'], 9999)
        self.assertEqual(summary['billingReviews'], 1)
        self.assertEqual(summary['failedPayments'], 1)
        self.assertEqual(summary['mrrMinor'], self.canonical['summary']['mrrMinor'] - subscription['amountMinor'])
        self.assertEqual(summary['cashThisMonthMinor'], self.canonical['summary']['cashThisMonthMinor'] - subscription['amountMinor'])
        creator = next(row for row in self.data['analytics']['planDistribution'] if row['plan'] == 'Creator')
        self.assertEqual(creator['subscribers'], 4000)
        self.assertEqual(creator['activeSubscriptions'], 3999)
        october = next(row for row in self.data['analytics']['revenueTrend'] if row['period'] == '2026-10')
        self.assertEqual(october['cashMinor'], summary['cashThisMonthMinor'])
        self.assertEqual(len(self.data['invoices']), 30000)
        self.assertEqual(len(self.data['payments']), 30000)

    def test_payment_exception_persists_same_linked_account_evidence_and_safe_notice(self):
        result = self.scenario('payment_failure')
        incident = self.data['incidents'][0]
        self.assertEqual(incident['id'], result['incidentId'])
        self.assertEqual(incident['detectorFamily'], 'demo_payment_exception')
        self.assertEqual(incident['classification'], 'simulated_payment_exception')
        self.assertEqual(incident['severity'], 'warning')
        self.assertEqual(incident['affectedCount'], 1)
        self.assertEqual(incident['affectedRecords'][0]['name'], 'Leo Martins')
        self.assertEqual(incident['affectedRecords'][0]['workspaceName'], 'Northline Stories')
        self.assertEqual(incident['affectedRecords'][0]['amountMinor'], 5900)
        self.assertEqual(incident['affectedRecords'][0]['currency'], 'USD')
        for collection, source_id in result['paymentSourceIds'].items():
            self.assertEqual(incident['affectedSourceIds'][collection], [source_id])
            self.assertTrue(any(row['id'] == source_id for row in self.data[collection]))
        self.assertIn('unverified', incident['unknown'][0])
        notice = self.data['notificationEvents'][0]
        self.assertEqual(notice['incidentId'], incident['id'])
        self.assertEqual(notice['kind'], 'incident')
        self.assertEqual(notice['state'], 'queued')
        for identifier in (incident['id'], incident['episodeId'], notice['id']):
            self.assertRegex(identifier, r'\A[A-Za-z0-9-]{1,80}\Z')
        self.assertFalse(notice['externalDelivery'])
        self.assertIsNone(notice['providerRef'])
        safe_body = json.dumps([incident, notice])
        for private in ('@', 'cardLast4', 'recipient'):
            self.assertNotIn(private, safe_body)
        before = copy.deepcopy(self.data)
        self.assertTrue(self.scenario('payment_failure', LATER)['replayed'])
        self.assertEqual(self.data, before)

    def test_payment_notification_failure_and_recovery_keep_episode_and_derive_restoration(self):
        opened = self.scenario('payment_failure')
        original_failure = copy.deepcopy(self.data['summary'])
        incident = self.data['incidents'][0]
        first_event = copy.deepcopy(incident['timeline'][0])
        failed = self.scenario('notification_failure', LATER)
        self.assertEqual(failed['incidentId'], opened['incidentId'])
        self.assertEqual(failed['paymentSourceIds'], opened['paymentSourceIds'])
        self.assertEqual(self.data['summary'], original_failure)
        self.assertEqual(incident['notificationState'], 'failed')
        self.assertEqual(self.data['notificationEvents'][0]['state'], 'failed')
        self.assertEqual(incident['timeline'][0], first_event)
        self.assertEqual(len(self.data['incidents']), 1)
        recovered = self.scenario('recovery', '2026-10-01T16:00:00Z')
        self.assertEqual(recovered['incidentId'], opened['incidentId'])
        self.assertEqual(incident['state'], 'resolved')
        self.assertFalse(incident['acknowledged'])
        self.assertEqual([row['type'] for row in incident['timeline']], ['opened', 'notification_failed', 'resolved'])
        self.assertEqual(self.data['summary'], self.canonical['summary'])
        self.assertEqual(self.data['invoices'], self.canonical['invoices'])
        self.assertEqual(self.data['payments'], self.canonical['payments'])
        self.assertEqual(len([row for row in self.data['notificationEvents'] if row['kind'] == 'recovery']), 1)
        before = copy.deepcopy(self.data['notificationEvents'])
        self.scenario('recovery', '2026-10-01T17:00:00Z')
        self.assertEqual(self.data['notificationEvents'], before)

    def test_payment_and_outage_have_distinct_detector_episodes_preserving_history(self):
        self.scenario('payment_failure')
        payment_incident = copy.deepcopy(self.data['incidents'][0])
        outage = self.scenario('outage', LATER)
        self.assertEqual(len(self.data['incidents']), 2)
        self.assertEqual(self.data['incidents'][0], payment_incident)
        self.assertNotEqual(outage['incidentId'], payment_incident['id'])
        self.assertEqual(self.data['incidents'][1]['detectorFamily'], 'demo_publishing_outage')
        self.assertEqual(self.data['incidents'][1]['affectedCount'], 3)
        self.assertEqual(self.data['summary'], self.canonical['summary'])

    def test_payment_normal_restores_original_fields_and_preserves_unrelated_work(self):
        result = self.scenario('payment_failure')
        affected_workspace = next(row for row in self.data['workspaces'] if row['id'] == result['paymentSourceIds']['workspaces'])
        affected_workspace['name'] = 'Founder renamed Demo workspace'
        self.data['customers'][50]['company'] = 'Unrelated edit'
        founder_state = dict(conversations=[dict(id='already-saved')], followUps=[dict(id='reminder-1')])
        self.data['founderIntelligence'] = founder_state
        self.scenario('normal', LATER)
        self.assertEqual(affected_workspace['name'], 'Founder renamed Demo workspace')
        self.assertEqual(affected_workspace['status'], 'active')
        self.assertEqual(self.data['customers'][50]['company'], 'Unrelated edit')
        self.assertIs(self.data['founderIntelligence'], founder_state)
        self.assertEqual(self.data['summary'], self.canonical['summary'])
        self.assertEqual(self.data['invoices'], self.canonical['invoices'])
        self.assertEqual(self.data['payments'], self.canonical['payments'])
        self.assertEqual(self.data['_founderPreviewScenarios']['patches'], [])

    def test_later_independent_edit_of_owned_status_wins_restoration(self):
        result = self.scenario('payment_failure')
        workspace = next(row for row in self.data['workspaces'] if row['id'] == result['paymentSourceIds']['workspaces'])
        workspace['status'] = 'archived'
        self.scenario('normal', LATER)
        self.assertEqual(workspace['status'], 'archived')

    def test_outage_has_linked_named_fictional_impact_unknown_cause_and_no_financial_fault(self):
        result = self.scenario('outage')
        incident = self.data['incidents'][0]
        self.assertEqual(result['affectedCount'], 3)
        self.assertEqual([row['name'] for row in incident['affectedRecords']], ['Maya Chen', 'Leo Martins', 'Aisha Patel'])
        self.assertEqual(len(set(incident['affectedWorkspaceIds'])), 3)
        for record in incident['affectedRecords']:
            member = next(row for row in self.data['members'] if row['id'] == record['memberId'])
            self.assertEqual(member['workspaceId'], record['workspaceId'])
            self.assertEqual(member['customerId'], record['customerId'])
        self.assertEqual(incident['state'], 'open')
        self.assertEqual(incident['severity'], 'warning')
        self.assertRegex(incident['id'], r'\A[A-Za-z0-9-]{1,80}\Z')
        self.assertRegex(self.data['notificationEvents'][0]['id'], r'\A[A-Za-z0-9-]{1,80}\Z')
        self.assertRegex(incident['timeline'][0]['id'], r'\A[A-Za-z0-9-]{1,80}\Z')
        self.assertFalse(incident['acknowledged'])
        self.assertIn('unverified', incident['unknown'][0])
        self.assertEqual(incident['sourceTrust'], 'server_owned_demo_scenario')
        self.assertEqual(self.data['summary'], self.canonical['summary'])
        self.assertEqual(self.data['invoices'], self.canonical['invoices'])
        self.assertEqual(self.data['payments'], self.canonical['payments'])
        self.assertEqual(len(self.data['notificationEvents']), 1)
        serialized = json.dumps(self.data['notificationEvents'])
        self.assertNotIn('@', serialized)
        self.assertNotIn('Maya', serialized)
        self.assertIsNone(self.data['notificationEvents'][0]['providerRef'])

    def test_failure_recovery_same_episode_append_only_no_duplicate_notices(self):
        opened = self.scenario('outage')
        first_timeline = copy.deepcopy(self.data['incidents'][0]['timeline'])
        self.assertTrue(self.scenario('outage', LATER)['replayed'])
        failed = self.scenario('notification_failure', LATER)
        incident = self.data['incidents'][0]
        self.assertEqual(failed['incidentId'], opened['incidentId'])
        self.assertEqual(incident['notificationState'], 'failed')
        self.assertEqual(self.data['notificationEvents'][0]['state'], 'failed')
        self.assertEqual(incident['timeline'][:1], first_timeline)
        self.scenario('notification_failure', LATER)
        self.assertEqual(len(incident['timeline']), 2)
        # Acknowledging a simulated contact/incident is never recovery.
        incident.update(acknowledged=True, acknowledgement='acknowledged')
        self.assertEqual(incident['state'], 'open')
        recovered = self.scenario('recovery', '2026-10-01T16:00:00Z')
        self.assertEqual(recovered['incidentId'], opened['incidentId'])
        self.assertEqual(incident['state'], 'resolved')
        self.assertTrue(incident['acknowledged'])
        self.assertEqual([row['type'] for row in incident['timeline']], ['opened', 'notification_failed', 'resolved'])
        self.assertEqual(len([row for row in self.data['notificationEvents'] if row['kind'] == 'recovery']), 1)
        before = copy.deepcopy(self.data)
        self.scenario('recovery', '2026-10-01T17:00:00Z')
        self.assertEqual(self.data, before)
        self.scenario('normal', '2026-10-01T17:00:00Z')
        self.scenario('recovery', '2026-10-01T18:00:00Z')
        self.assertEqual(len(self.data['notificationEvents']), 2)
        self.assertEqual(self.data['summary'], self.canonical['summary'])

    def test_new_outage_after_recovery_gets_new_episode_without_rewriting_history(self):
        self.scenario('outage')
        self.scenario('recovery', LATER)
        first = copy.deepcopy(self.data['incidents'][0])
        self.scenario('outage', '2026-10-02T14:00:00Z')
        self.assertEqual(len(self.data['incidents']), 2)
        self.assertEqual(self.data['incidents'][0], first)
        self.assertNotEqual(self.data['incidents'][0]['episodeId'], self.data['incidents'][1]['episodeId'])

    def test_stale_keeps_last_good_actual_asof_values_and_normal_restores_source_state(self):
        original = copy.deepcopy(self.data)
        self.scenario('stale_data')
        self.assertEqual(self.data['asOf'], original['asOf'])
        self.assertEqual(self.data['lastGoodAsOf'], original['asOf'])
        self.assertEqual(self.data['sourceState'], 'stale')
        self.assertEqual(self.data['summary']['dataState'], 'stale')
        self.assertEqual(self.data['summary']['mrrMinor'], original['summary']['mrrMinor'])
        financial_keys = ('period', 'currency', 'revenueMinor', 'cashMinor')
        self.assertEqual([{key: row[key] for key in financial_keys} for row in self.data['analytics']['revenueTrend']],
                         [{key: row[key] for key in financial_keys} for row in original['analytics']['revenueTrend']])
        for row in self.data['analytics']['revenueTrend']:
            self.assertEqual(row['dataState'], 'stale')
            self.assertEqual(row['asOf'], original['asOf'])
            self.assertEqual(row['lastGoodAsOf'], original['asOf'])
        self.assertEqual(self.data['connections'][0]['state'], 'stale')
        self.scenario('normal', LATER)
        for key in ('asOf', 'summary', 'analytics', 'connections'):
            self.assertEqual(self.data[key], original[key])
        for key in ('dataState', 'lastGoodAsOf', 'sourceState', 'staleSince'):
            self.assertNotIn(key, self.data)

    def test_demo_isolation_full_source_and_atomic_invalid_input(self):
        self.fails({'mode': 'live'}, 'outage', 'DEMO_REQUIRED')
        self.fails(self.data, 'unsupported', 'INVALID')
        self.fails(self.data, 'normal', 'INVALID', now='2026-10-01T14:00:00')
        self.fails(bounded_snapshot(self.data), 'payment_failure', 'FULL_SOURCE_REQUIRED')
        leo = next(row for row in self.data['customers'] if row['name'] == 'Leo Martins')
        leo['subscriptionId'] = 'workspace-2'
        self.fails(self.data, 'payment_failure', 'SOURCE_LINK_INVALID')

    def test_no_provider_transport_model_or_ledger_dependency(self):
        import rafii_control.founder_preview_scenarios as service
        source = Path(service.__file__).read_text()
        for forbidden in ('requests', 'urllib', 'httpx', 'smtplib', 'subprocess', 'phone.contracts',
                          'Ledger', 'actualUsdMicro', 'provider_accepted'):
            self.assertNotIn(forbidden, source)
        for scenario in ('payment_failure', 'outage', 'stale_data', 'notification_failure', 'recovery', 'normal'):
            result = self.scenario(scenario)
            self.assertFalse(result['externalDelivery'])
        self.assertNotIn('contactAttempts', self.data)


if __name__ == '__main__':
    unittest.main()
