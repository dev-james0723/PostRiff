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

    def test_chips_are_part_of_the_approved_request(self):
        # Chat-context S21: the same body goes to estimate, quote and turn, so every chip detail is bound.
        chips={'text':'hello','model':'a','references':[{'kind':'post','id':'p1','label':'Spring','role':'rework'}],
               'attachments':[{'assetId':'a'*32,'role':'post','slot':'A'}]}
        changed=[('references',[]),('attachments',[]),
                 ('references',[{'kind':'post','id':'p1','label':'Autumn','role':'rework'}]),
                 ('references',[{'kind':'post','id':'p1','label':'Spring','role':'inspire'}]),
                 ('attachments',[{'assetId':'a'*32,'role':'post','slot':'B'}]),
                 ('attachments',[{'assetId':'a'*32,'role':'reference','slot':'A'}])]
        for field,value in changed:
            with self.subTest(field=field,value=value): self.assertNotEqual(self.digest(chips,'c'),self.digest({**chips,field:value},'c'))

    def test_media_notes_binds_one_asset_only(self):
        one=credit_wallet.request_digest('media-notes',{'assetId':'a'*32})
        self.assertEqual(one,credit_wallet.request_digest('media-notes',{'assetId':'a'*32,'creditQuoteId':'q','expectedRevision':4}))
        self.assertNotEqual(one,credit_wallet.request_digest('media-notes',{'assetId':'b'*32}))
        self.assertNotEqual(one,credit_wallet.request_digest('quick-start',{'assetId':'a'*32}))
        for bad in ({},{'assetId':'a'*32,'model':'x'},{'assetId':7}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): credit_wallet.request_digest('media-notes',bad)
        with self.assertRaises(ValueError): credit_wallet.request_digest('media-notes',{'assetId':'a'*32},'conversation')
        with self.assertRaises(ValueError): credit_wallet.request_digest('media-notes',{'_credit_authority':{}})
