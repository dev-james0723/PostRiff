import unittest
from postriff_phase2 import credit_wallet

class CreditRequestTests(unittest.TestCase):
    def digest(self, body, conversation=None):
        self.assertTrue(hasattr(credit_wallet,'request_digest'))
        return credit_wallet.request_digest('turn' if conversation else 'quick-start',body,conversation)

    def test_quote_identifier_is_not_part_of_approved_request(self):
        original={'text':'hello','model':'a','destinations':[{'channelId':'one'}]}
        self.assertEqual(self.digest(original),self.digest({**original,'creditQuoteId':'q','expectedRevision':3}))

    def test_every_material_choice_changes_binding(self):
        original={'text':'hello','model':'a','ownContent':False,'research':False}
        for field,value in [('text','bye'),('model','b'),('ownContent',True),('research',True),('voiceSourceIds',['different'])]:
            with self.subTest(field=field): self.assertNotEqual(self.digest(original),self.digest({**original,field:value}))
        self.assertNotEqual(self.digest(original,'conversation-a'),self.digest(original,'conversation-b'))

    def test_private_authority_cannot_be_inserted_in_request(self):
        with self.assertRaises(ValueError): self.digest({'_credit_authority':{'maximum':1}})
