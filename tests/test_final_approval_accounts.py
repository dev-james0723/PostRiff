"""FINAL-02/09: an approval manifest keeps the account a draft was written for.

A draft generated for one account (variant.channelId) must never be reviewed, approved or
published through a different account on the same platform. A platform-level draft (no
channelId) still needs the person to name the account explicitly in the review.
"""
import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_alpha.domain import AlphaError
import test_postriff_phase2 as phase2


class ApprovalAccountBinding(unittest.TestCase):
    # Borrow the fixture helpers only, so the inherited phase-2 tests do not run twice.
    setUp, tearDown = phase2.Phase2Acceptance.setUp, phase2.Phase2Acceptance.tearDown
    channel, draft = phase2.Phase2Acceptance.channel, phase2.Phase2Acceptance.draft

    def payload(self, channel, variant):
        return {'channelId': channel['id'], 'variantId': variant['id'], 'localTime': datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat(), 'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']}

    def two_accounts(self):
        variant = self.draft()
        first = self.channel(platform='LinkedIn')
        second = self.channel(platform='LinkedIn')
        self.assertNotEqual(first['id'], second['id'])
        return variant, first, second

    def test_account_bound_draft_cannot_be_reviewed_for_another_account(self):
        variant, first, second = self.two_accounts()
        state = copy.deepcopy(self.j.state)
        state['variants'][0]['channelId'] = first['id']
        with self.assertRaises(AlphaError) as refused:
            self.store.build_manifest(state, self.payload(second, variant), 'actor')
        self.assertEqual(refused.exception.status, 409)
        manifest = self.store.build_manifest(state, self.payload(first, variant), 'actor')
        self.assertEqual(manifest['channelId'], first['id'])

    def test_platform_level_draft_uses_the_account_named_in_the_review(self):
        variant, _, second = self.two_accounts()
        self.assertIsNone(self.j.state['variants'][0].get('channelId'))
        manifest = self.store.build_manifest(copy.deepcopy(self.j.state), self.payload(second, variant), 'actor')
        self.assertEqual(manifest['channelId'], second['id'])


if __name__ == '__main__':
    unittest.main()
