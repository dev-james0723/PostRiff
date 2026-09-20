import unittest
from postriff_phase2.email import Mailer, NullTransport

class DeliveryReceipt(unittest.TestCase):
    def test_null_transport_never_claims_delivery(self):
        result = Mailer(NullTransport(), 'hello@example.test', 'https://app.example.test').welcome('user@example.test','https://app.example.test/app')
        self.assertFalse(result['sent'])
    def test_empty_transport_response_is_not_delivery(self):
        from types import SimpleNamespace
        result = Mailer(SimpleNamespace(send=lambda _: None), 'hello@example.test', 'https://app.example.test').welcome('user@example.test','https://app.example.test/app')
        self.assertFalse(result['sent'])
