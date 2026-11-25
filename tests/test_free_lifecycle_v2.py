"""Task4 truthful hosted Free state; legacy local fixtures keep their trial."""
import copy
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.auth import initial_phase2_state
from postriff_phase2.billing import Billing
from postriff_phase2.hosted import HostedPhase2Commands, workspace_summary


class FreeState(unittest.TestCase):
    def free(self):
        try:
            return initial_phase2_state('w', 'u', 'Member', 'free', 100, execution='hosted-candidate')
        except AlphaError as error:
            self.fail('Hosted Free must have a truthful non-trial state: ' + str(error))

    def test_free_has_no_fake_trial_grant_and_present_is_usable(self):
        state = self.free()
        self.assertNotIn('trial', state['phase2'])
        shown = HostedPhase2Commands(clock=lambda: 101).present(state, 2)
        self.assertEqual(shown['revision'], 2)
        self.assertNotIn('trial', shown['state']['phase2'])
        self.assertEqual(shown['state']['phase2']['acquisitionPlan'], 'free')
        self.assertNotIn('trial', state['phase2'])

    def test_free_manual_draft_edit_and_privacy_remain_available(self):
        state = self.free()
        commands = HostedPhase2Commands(clock=lambda: 101)
        # The ordinary manual draft command is allowed without writing grants.
        result = commands(state, 'u', 'idea', {'idea': 'My own words'})
        self.assertEqual(result['brief']['idea'], 'My own words')
        self.assertNotIn('trial', result['phase2'])

    def test_free_legacy_generate_and_adapt_refuse_cleanly(self):
        state = self.free()
        for action in ('generate', 'adapt'):
            with self.subTest(action=action), self.assertRaises(AlphaError) as caught:
                HostedPhase2Commands(clock=lambda: 101)(copy.deepcopy(state), 'u', action, {})
            self.assertEqual(caught.exception.status, 402)

    def test_free_legacy_plan_selector_refuses_without_keyerror(self):
        try:
            HostedPhase2Commands(clock=lambda: 101)(self.free(), 'u', 'p2_plan', {'plan': 'assist'})
        except AlphaError as error:
            self.assertEqual(error.status, 409)
        except KeyError:
            self.fail('Free cannot crash the legacy trial plan selector')
        else:
            self.fail('A local trial selector cannot change hosted Free billing')

    def test_local_fixture_free_still_refused(self):
        with self.assertRaises(AlphaError):
            initial_phase2_state('w', 'u', 'Member', 'free', 100)

    def test_billing_owned_ledger_uses_the_same_flag_and_clock(self):
        clock = lambda: 100
        billing = Billing(clock=clock, pricing_v2_enabled=True)
        self.assertTrue(billing.ledger.pricing_v2_enabled)
        self.assertIs(billing.ledger.clock, clock)

    def test_old_local_trial_unchanged(self):
        state = initial_phase2_state('w', 'u', 'Member', 'studio', 100)
        self.assertEqual(state['phase2']['trial']['expiresAt'], 100 + 14 * 86400)
        self.assertEqual(state['phase2']['trial']['writingGrant'], 10)
        self.assertFalse(state['phase2']['trial']['autoConvert'])

    def test_summaries_do_not_mislabel_free_or_creator_as_trial(self):
        for plan in ('free', 'creator', 'starter'):
            with self.subTest(plan=plan):
                self.assertEqual(workspace_summary('W', plan, None, 'u', 'M', {})['plan'], plan)
        self.assertEqual(workspace_summary('W', None, 'assist', 'u', 'M', {})['plan'], 'trial')


if __name__ == '__main__':
    unittest.main()
