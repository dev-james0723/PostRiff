"""Official reports.query requires YouTube read access alongside Analytics grants."""
import unittest
from types import SimpleNamespace

from postriff_phase2.youtube.model import ANALYTICS, MANAGE, MONEY, READ, capability_matrix


class YouTubeAnalyticsGrantTests(unittest.TestCase):
    def test_reports_require_read_access_and_keep_sensitive_authorization_separate(self):
        provider = SimpleNamespace(creator_enabled=True, execution_enabled=True)
        identity = {'id': 'UC' + 'a' * 22, 'eligibility': {'monetary': True}}
        for granted, permitted in (([ANALYTICS], False), ([READ, ANALYTICS], True), ([MANAGE, ANALYTICS], True)):
            with self.subTest(granted=granted):
                caps = capability_matrix(provider, granted, identity)
                for key in ('analytics', 'shorts_analytics'):
                    self.assertEqual(caps[key]['canExecute'], permitted)
                    self.assertNotEqual(caps[key]['state'], 'READY')
        caps = capability_matrix(provider, [MONEY], identity, authorizations={'monetary': True})
        self.assertFalse(caps['monetary_analytics']['canExecute'])
        caps = capability_matrix(provider, [READ, MONEY], identity, authorizations={'monetary': True})
        self.assertTrue(caps['monetary_analytics']['canExecute'])
        self.assertTrue(caps['analytics']['canExecute'])
        caps = capability_matrix(provider, [READ, MONEY], identity)
        self.assertEqual(caps['monetary_analytics']['state'], 'NOT AUTHORIZED')


if __name__ == '__main__':
    unittest.main()
