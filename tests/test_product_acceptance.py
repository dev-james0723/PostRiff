"""Acceptance receipts cannot silently shrink scope or turn fixture checks into real activation."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('product_acceptance', ROOT / 'scripts/rafii_product_acceptance.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.requirements = json.loads((ROOT / 'docs/design/studio-customer-growth/requirements.json').read_text())
        self.matrix = {'functions': [{'id': r['id'], 'code': {'status': 'NOT_RUN', 'evidence': []},
                                     'production': {'status': 'PENDING', 'evidence': []},
                                     'data': {'status': 'PENDING', 'evidence': []}} for r in self.requirements['functions']]}

    def test_complete_inventory_and_unqualified_pending_are_valid(self):
        self.assertEqual(139, len(self.requirements['functions']))
        self.assertEqual([], module.validate(self.requirements, self.matrix))

    def test_hidden_row_duplicate_and_undefined_dependency_are_rejected(self):
        for change in ('missing', 'duplicate', 'dependency'):
            with self.subTest(change=change):
                req, matrix = copy.deepcopy(self.requirements), copy.deepcopy(self.matrix)
                if change == 'missing': matrix['functions'].pop()
                if change == 'duplicate': matrix['functions'][-1]['id'] = matrix['functions'][0]['id']
                if change == 'dependency': req['functions'][0]['dependencies'].append('stage-three-must-finish')
                self.assertTrue(module.validate(req, matrix))

    def test_unit_tests_ready_and_founder_cannot_be_real_pass(self):
        row = self.matrix['functions'][0]
        row['production'] = {'status': 'PASS', 'evidence': ['deployment READY', 'unit tests PASS']}
        self.assertTrue(module.validate(self.requirements, self.matrix))
        row['production']['qualification'] = {'environment': 'production', 'ordinaryPaid': True,
            'founder': True, 'providerAppRole': False, 'liveBillingEvidence': 'invoice',
            'principalId': 'person', 'workspaceId': 'workspace', 'sourceSha': 'a' * 40,
            'execution': 'real', 'flowEvidence': 'browser-api-receipt'}
        self.assertTrue(module.validate(self.requirements, self.matrix))
        row['production']['qualification']['founder'] = False
        self.assertEqual([], module.validate(self.requirements, self.matrix))
        row['production']['qualification']['providerAppRole'] = True
        self.assertTrue(module.validate(self.requirements, self.matrix))

    def test_horizon_requires_real_anchor_and_observation_not_reconstruction(self):
        row = next(r for r in self.matrix['functions'] if r['id'] == 'G12')
        row['data'] = {'status': 'PASS', 'evidence': ['native-read'], 'qualification': {
            'execution': 'real', 'provenance': 'official', 'anchorAt': 1000,
            'observedAt': 1000 + 604800, 'horizon': '7d', 'reconstructed': False,
            'providerReadId': 'read', 'providerPostId': 'post', 'connectionId': 'connection'}}
        self.assertEqual([], module.validate(self.requirements, self.matrix))
        row['data']['qualification']['observedAt'] = 1001
        self.assertTrue(module.validate(self.requirements, self.matrix))
        row['data']['qualification']['observedAt'] = 605800
        row['data']['qualification']['reconstructed'] = True
        self.assertTrue(module.validate(self.requirements, self.matrix))

    def test_earliest_time_is_unknown_until_real_verified_anchor(self):
        self.assertIsNone(module.earliest_time('G12', self.requirements, None))
        self.assertEqual(605800, module.earliest_time('G12', self.requirements, 1000))

    def test_axis_dependencies_cannot_name_an_undefined_gate(self):
        for axis in ('productionDependencies', 'dataDependencies', 'uiStateDependencies'):
            with self.subTest(axis=axis):
                req=copy.deepcopy(self.requirements)
                req['functions'][0][axis]=['invented-gate']
                self.assertTrue(module.validate(req,self.matrix))

    def test_native_horizon_has_the_same_inclusive_ten_minute_deadline_as_runtime(self):
        row = next(r for r in self.matrix['functions'] if r['id'] == 'G12')
        row['data'] = {'status': 'PASS', 'evidence': ['native-read'], 'qualification': {
            'execution': 'real', 'provenance': 'official', 'anchorAt': 1000,
            'observedAt': 1000 + 604800 + 600, 'horizon': '7d', 'reconstructed': False,
            'providerReadId': 'read', 'providerPostId': 'post', 'connectionId': 'connection'}}
        self.assertEqual([], module.validate(self.requirements, self.matrix))
        for observed in (1000 + 604800 + 601, 1000 + 8 * 86400):
            row['data']['qualification']['observedAt'] = observed
            self.assertTrue(module.validate(self.requirements, self.matrix), 'Late current counters cannot prove a 7d observation')


if __name__ == '__main__': unittest.main()
