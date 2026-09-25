"""FINAL-06: live/test mode comes from the Stripe key, including restricted keys, and every webhook
must match it (a test event on a live endpoint, or the reverse, fails closed)."""
import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2 import billing_stripe
from postriff_phase2.billing_stripe import StripePaymentProvider
from postriff_phase2.credit_purchases import CreditPurchases

SECRET = 'whsec_mode_test'
NOW = time.time()


def signed(provider_secret, body):
    stamp = int(NOW)
    return f"t={stamp},v1={hmac.new(provider_secret.encode(), f'{stamp}.'.encode() + body, hashlib.sha256).hexdigest()}"


class StripeMode(unittest.TestCase):
    def provider(self, key):
        return StripePaymentProvider(key, SECRET, transport=lambda *a, **k: None, clock=lambda: NOW)

    def test_restricted_live_keys_are_live_and_unknown_formats_are_refused(self):
        self.assertTrue(self.provider('rk_live_' + 'a' * 20).live)
        self.assertTrue(self.provider('sk_live_' + 'a' * 20).live)
        self.assertFalse(self.provider('rk_test_' + 'a' * 20).live)
        self.assertFalse(self.provider('sk_test_' + 'a' * 20).live)
        with self.assertRaises(AlphaError) as refused:
            self.provider('pk_live_' + 'a' * 20)
        self.assertEqual(refused.exception.status, 503)

    def test_credit_purchases_follow_the_provider_mode(self):
        self.assertTrue(CreditPurchases(None, self.provider('rk_live_' + 'b' * 20)).live)
        self.assertFalse(CreditPurchases(None, self.provider('sk_test_' + 'b' * 20)).live)

    def test_every_webhook_must_match_the_key_mode(self):
        live = self.provider('rk_live_' + 'c' * 20)
        for livemode, expected in ((True, None), (False, 400), (None, 400)):
            raw = {'id': 'evt_mode', 'type': 'invoice.paid', 'created': int(NOW), 'data': {'object': {}}}
            if livemode is not None:
                raw['livemode'] = livemode
            body = json.dumps(raw).encode()
            if expected is None:
                self.assertEqual(live.parse_webhook(signed(SECRET, body), body)['id'], 'evt_mode')
            else:
                with self.assertRaises(AlphaError) as refused:
                    live.parse_webhook(signed(SECRET, body), body)
                self.assertEqual(refused.exception.status, expected)


if __name__ == '__main__':
    unittest.main()
