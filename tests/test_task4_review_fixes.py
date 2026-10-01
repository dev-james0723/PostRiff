"""Task4 review: a no-trial workspace uses the dedicated managed writer surface."""
import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.hosted import HostedPhase2Commands


class LegacyNoTrialCommand(unittest.TestCase):
    def test_no_trial_rejection_does_not_claim_an_active_creator_is_free(self):
        state = initial_phase2_state('w', 'u', 'Owner', 'free', 100, execution='hosted-candidate')
        # Acquisition history stays Free after a verified paid upgrade; live SQL
        # entitlement has already been checked by the service, not inferred here.
        state['phase2']['acquisitionPlan'] = 'free'
        for action in ('generate', 'adapt'):
            with self.subTest(action=action), self.assertRaises(AlphaError) as caught:
                HostedPhase2Commands(clock=lambda: 101)(copy.deepcopy(state), 'u', action, {})
            self.assertEqual(caught.exception.status, 402)
            self.assertNotIn('Free', str(caught.exception))
            self.assertIn('dedicated', str(caught.exception).lower())
            self.assertIn('managed', str(caught.exception).lower())
        self.assertNotIn('trial', state['phase2'])


if __name__ == '__main__':
    unittest.main()
