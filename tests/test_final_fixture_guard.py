"""FINAL-10: the labelled fixture payment provider (published test secret) can never accept a webhook on a
hosted deployment, even if some future entrypoint forgets to pass the real provider. Local tests keep it."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2.billing import FixturePaymentProvider

BODY = json.dumps({'id': 'evt_1', 'type': 'payment.succeeded', 'createdAt': 1, 'workspaceId': 'w'}).encode()


class FixtureGuard(unittest.TestCase):
    def test_fixture_webhooks_work_locally(self):
        provider = FixturePaymentProvider()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VERCEL', None)
            self.assertEqual(provider.parse_webhook(provider.sign(BODY), BODY)['id'], 'evt_1')

    def test_fixture_webhooks_are_refused_on_a_hosted_deployment(self):
        provider = FixturePaymentProvider()
        with mock.patch.dict(os.environ, {'VERCEL': '1'}):
            with self.assertRaises(AlphaError) as caught:
                provider.parse_webhook(provider.sign(BODY), BODY)
        self.assertEqual(caught.exception.status, 503)


if __name__ == '__main__':
    unittest.main()
