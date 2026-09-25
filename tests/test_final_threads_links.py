"""FINAL-09: Threads rejects posts with more than 5 links (official posts guide, dated note 2025-12-22).
A review for Threads is refused up front with the reason, instead of an approved post failing at publish
time. Five links, and other platforms, are unaffected."""
import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_alpha.domain import AlphaError
import test_postriff_phase2 as phase2

LINKS = ' '.join(f'https://example.com/{n}' for n in range(6))


class ThreadsLinks(unittest.TestCase):
    setUp, tearDown = phase2.Phase2Acceptance.setUp, phase2.Phase2Acceptance.tearDown
    channel, draft = phase2.Phase2Acceptance.channel, phase2.Phase2Acceptance.draft

    def manifest(self, platform, text, variant=None):
        variant = variant or self.draft()
        channel = self.channel(platform=platform)
        state = copy.deepcopy(self.j.state)
        state['variants'][0].update(platform=platform, text=text)
        payload = {'channelId': channel['id'], 'variantId': variant['id'], 'localTime': datetime.fromtimestamp(self.now + 60, timezone.utc).replace(tzinfo=None).isoformat(), 'timeZone': 'UTC', 'acknowledgedWarnings': variant['warnings']}
        return self.store.build_manifest(state, payload, 'actor')

    def test_more_than_five_links_is_refused_for_threads(self):
        with self.assertRaises(AlphaError) as refused:
            self.manifest('Threads', 'Recital links: ' + LINKS)
        self.assertEqual(refused.exception.status, 409)
        self.assertIn('5 links', str(refused.exception))

    def test_five_links_and_other_platforms_are_unaffected(self):
        five = ' '.join(f'https://example.com/{n}' for n in range(5))
        variant = self.draft()
        self.assertEqual(self.manifest('Threads', 'Recital links: ' + five, variant)['platform'], 'Threads')
        self.assertEqual(self.manifest('LinkedIn', 'Recital links: ' + LINKS, variant)['platform'], 'LinkedIn')


if __name__ == '__main__':
    unittest.main()
