"""Stage 2 policy and durable acquisition state; no provider traffic."""
from contextlib import contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from postriff_phase2.growth.trends import beta, activation
from postriff_phase2.growth.trends.activation import ALLOWED, candidate
from postriff_phase2.growth.trends.contracts import ContractError, PERMISSIONS
from postriff_phase2.growth.trends.providers import bluesky
from trend_provider_activation import compare, production_state

WID = '00000000-0000-4000-8000-000000000001'
NOW = '2026-09-28T12:00:00Z'
START = '2026-09-28T12:10:00Z'
END = '2026-09-28T16:10:00Z'


class ManifestTests(unittest.TestCase):
    def test_exact_workspace_rights_schedule_and_zero_cost(self):
        value = candidate(WID, START, END, now=NOW)
        p = value['policy']
        self.assertEqual((p['provider_id'], p['operation'], p['scope_key']),
                         ('bluesky', 'live_sample', 'workspace:' + WID))
        self.assertEqual({k for k, v in p['rights'].items() if v['state'] == 'allow'}, ALLOWED)
        self.assertEqual(set(p['rights']), set(PERMISSIONS))
        self.assertTrue(all(v['state'] == 'deny' for k, v in p['rights'].items() if k not in ALLOWED))
        self.assertEqual(p['retention_seconds'], 86400)
        self.assertEqual((p['schedule']['interval_seconds'], p['schedule']['max_samples'],
                          p['schedule']['max_items'], p['schedule']['seconds']), (120, 120, 100, 5))
        self.assertEqual(p['schedule']['reservation_microusd'], 0)
        self.assertEqual({b['dimension'] for b in value['budgets']}, {'system', 'provider', 'workspace'})
        self.assertTrue(all(b['cap_micro_usd'] == 0 for b in value['budgets']))
        self.assertEqual(value['contract']['version'], bluesky.PROTOCOL)

    def test_window_and_capability_change_fail_closed(self):
        for end in ('2026-09-28T16:10:01Z', '2026-09-28T12:09:59Z'):
            with self.subTest(end=end), self.assertRaises(ContractError):
                candidate(WID, START, end, now=NOW)
        with self.assertRaises(ContractError):
            candidate(WID, '2026-09-28T07:59:00Z', END, now=NOW)
        with patch.object(activation, 'REVIEWED_ENDPOINT', 'wss://changed.invalid'):
            with self.assertRaisesRegex(ContractError, 'capability_contract_changed'):
                candidate(WID, START, END, now=NOW)

    def test_immutable_conflict_and_idempotence(self):
        desired = candidate(WID, START, END, now=NOW)
        empty = {'contract': None, 'policy': None, 'budgets': {}}
        self.assertEqual(compare(empty, desired)['policy'], 'create')
        contract = {k: desired['contract'][k] for k in ('operations', 'valid_from', 'expires_at', 'manifest')}
        existing = {'contract': {**contract, 'revoked_at': None},
                    'policy': {'manifest': desired['policy'], 'provider_contract_version': desired['contract']['version'], 'revoked_at': None},
                    'budgets': {b['budget_key']: b for b in desired['budgets']}}
        self.assertEqual(compare(existing, desired)['policy'], 'match')
        existing['policy']['revoked_at'] = NOW
        self.assertEqual(compare(existing, desired)['policy'], 'conflict')


class FakeEvidence:
    def __init__(self, value):
        self.value = value
        self.result = None
        self.queries = []

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, query, args=None):
        self.queries.append(query)
        self.result = {'now': NOW} if 'SELECT clock_timestamp() AS now' in query else self.value

    def fetchone(self):
        return self.result


class EvidenceTests(unittest.TestCase):
    def flags(self):
        return {**{'RAFII_TREND_' + k + '_ENABLED': '1' for k in ('INTELLIGENCE', 'RADAR', 'TRUST_RECEIPTS', 'PROVIDER_OPERATIONS')},
                'RAFII_TREND_WORKSPACE_ALLOWLIST': WID,
                'RAFII_TREND_ALLOWED_OPERATIONS': 'bluesky:live_sample'}

    def test_flag_alone_never_proves_collection(self):
        self.assertEqual(beta.status(WID, self.flags(), metric_reads_enabled=False)['acquisition'], 'unverified')
        no_rows = FakeEvidence(None)
        self.assertEqual(beta.status(WID, self.flags(), metric_reads_enabled=False, store=no_rows)['acquisition'], 'unverified')
        self.assertEqual(beta.status(WID[:-1] + '2', self.flags(), metric_reads_enabled=False, store=no_rows)['acquisition'], 'none')
        self.assertFalse(any('payload' in q.lower() for q in no_rows.queries))

    def test_recent_batch_active_and_health_or_expiry_degraded(self):
        evidence = {'readiness': 'ready', 'revoked_at': None, 'expires_at': END,
                    'contract_revoked_at': None, 'contract_expires_at': END,
                    'health': 'partial', 'health_observed_at': NOW,
                    'next_allowed_at': None, 'collected_at': NOW}
        self.assertEqual(beta.acquisition_evidence(FakeEvidence(evidence), WID), 'active')
        for change in ({'health': 'gap'}, {'next_allowed_at': END}, {'revoked_at': NOW},
                       {'contract_revoked_at': NOW}, {'contract_expires_at': NOW},
                       {'readiness': 'rights_suspended'}, {'expires_at': NOW}):
            with self.subTest(change=change):
                self.assertEqual(beta.acquisition_evidence(FakeEvidence({**evidence, **change}), WID), 'degraded')
        self.assertEqual(beta.acquisition_evidence(FakeEvidence({**evidence, 'collected_at': None}), WID), 'unverified')
        self.assertEqual(beta.acquisition_evidence(FakeEvidence({**evidence, 'health_observed_at': None}), WID), 'unverified')


class ProductionGateTests(unittest.TestCase):
    def test_sha_mismatch_denied_before_env_access(self):
        deployed = {'id': 'dpl_fixture', 'target': 'production', 'readyState': 'READY',
                    'aliases': ['postriff-phase2-private.vercel.app']}
        detail = {'gitSource': {'sha': 'a' * 40, 'ref': 'consumer-saas'}}
        with patch('trend_provider_activation._run', side_effect=[json.dumps(deployed), json.dumps(detail)]) as run:
            with self.assertRaisesRegex(ContractError, 'production_sha_mismatch'):
                production_state('b' * 40, WID)
            self.assertEqual(run.call_count, 2)

    def test_exact_one_workspace_and_excluded_flags(self):
        deployed = {'id': 'dpl_fixture', 'target': 'production', 'readyState': 'READY',
                    'aliases': ['postriff-phase2-private.vercel.app']}
        detail = {'gitSource': {'sha': 'a' * 40, 'ref': 'consumer-saas'}}
        def fake_run(*args):
            if args[1] == 'inspect':
                return json.dumps(deployed)
            if args[1] == 'api':
                return json.dumps(detail)
            if args[1] == 'env':
                Path(args[3]).write_text('\n'.join([
                    'RAFII_TREND_WORKSPACE_ALLOWLIST=' + WID,
                    'RAFII_TREND_INTELLIGENCE_ENABLED=1',
                    'RAFII_TREND_RADAR_ENABLED=1',
                    'RAFII_TREND_TRUST_RECEIPTS_ENABLED=1',
                    'RAFII_TREND_ALLOWED_OPERATIONS=bluesky:live_sample'
                ]))
                return ''
            raise AssertionError(args)
        with patch('trend_provider_activation._run', side_effect=fake_run):
            self.assertEqual(production_state('a' * 40, WID)['allowed_operations'], 'bluesky:live_sample')
            with self.assertRaisesRegex(ContractError, 'workspace_allowlist_mismatch'):
                production_state('a' * 40, WID[:-1] + '2')


if __name__ == '__main__':
    unittest.main()
