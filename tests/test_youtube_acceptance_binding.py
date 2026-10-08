"""Synthetic reader contracts; never evidence of real creator acceptance."""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from postriff_phase2.youtube.model import READ, capability_matrix


class AcceptanceBindingTests(unittest.TestCase):
    def test_ready_requires_current_channel_client_and_project(self):
        channel = 'UC' + 'a' * 22
        provider = SimpleNamespace(creator_enabled=True, execution_enabled=True,
            client_id='current-client', project_evidence={'projectId': 'current-project'})
        proof = {'status': 'PASS', 'execution': 'real', 'channelId': channel,
            'clientId': provider.client_id, 'projectId': 'current-project',
            'reference': 'synthetic-unit-contract',
            'verifiedAt': datetime.now(timezone.utc).isoformat()}
        def state(candidate):
            return capability_matrix(provider, [READ], {'id': channel},
                {'identity': candidate})['identity']['state']
        self.assertEqual(state(proof), 'READY')
        for key, value in [('clientId', 'rotated-client'), ('projectId', 'other-project'),
                           ('channelId', 'UC' + 'b' * 22), ('execution', 'fixture')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(proof); changed[key] = value
                self.assertNotEqual(state(changed), 'READY')
        for missing in ('clientId', 'projectId'):
            with self.subTest(missing=missing):
                changed = copy.deepcopy(proof); changed.pop(missing)
                self.assertNotEqual(state(changed), 'READY')
        provider.project_evidence = {}
        self.assertNotEqual(state(proof), 'READY')
