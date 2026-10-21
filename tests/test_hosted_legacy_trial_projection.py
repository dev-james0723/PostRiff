"""Legacy hosted workspaces can have no embedded trial grant."""
import copy
import unittest

from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands


class HostedLegacyTrialProjectionTests(unittest.TestCase):
    def test_snapshot_without_embedded_trial_preserves_saved_state_and_grants(self):
        now = 1_800_000_000
        commands = HostedPhase2Commands(clock=lambda: now)
        for trial_kind in ('absent', 'null', 'active', 'expired'):
            with self.subTest(trial_kind=trial_kind):
                state = initial_phase2_state('synthetic-workspace', 'synthetic-owner',
                    'Member', 'studio', now, execution='hosted-candidate')
                if trial_kind == 'absent':
                    del state['phase2']['trial']
                elif trial_kind == 'null':
                    state['phase2']['trial'] = None
                elif trial_kind == 'expired':
                    state['phase2']['trial']['expiresAt'] = now
                before = copy.deepcopy(state)
                result = commands.present(state, 104)
                self.assertEqual(result['revision'], 104)
                self.assertEqual(result['state']['workspace']['id'], 'synthetic-workspace')
                self.assertEqual(result['state']['phase2']['assets'], before['phase2']['assets'])
                self.assertEqual(result['state']['phase2']['channels'], before['phase2']['channels'])
                if trial_kind == 'absent':
                    self.assertNotIn('trial', result['state']['phase2'])
                elif trial_kind == 'null':
                    self.assertIsNone(result['state']['phase2']['trial'])
                else:
                    expected = {**before['phase2']['trial'], 'status': trial_kind}
                    self.assertEqual(result['state']['phase2']['trial'], expected)
                self.assertEqual(state['phase2'], before['phase2'],
                    'Presentation cannot persist invented entitlements or change channels/assets.')


if __name__ == '__main__':
    unittest.main()
