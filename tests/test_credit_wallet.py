import unittest
from postriff_phase2 import billing

class CreditWalletTests(unittest.TestCase):
    def project(self, rows, now=100):
        self.assertTrue(hasattr(billing, 'project_credit_wallet'), 'wallet projection must exist')
        return billing.project_credit_wallet(rows, now)

    def grant(self, amount=10000, expiry=None):
        return {'id':'g','reservationId':None,'credits':{'op':'grant','milli':amount,'expiresAt':expiry}}

    def reserve(self):
        return {'id':'r','reservationId':'r','credits':{'op':'reserve','allocations':[{'grantId':'g','milli':6000}]}}

    def test_reservation_is_not_a_completed_charge(self):
        result=self.project([self.grant(),self.reserve()])
        self.assertEqual((result['availableMilliCredits'],result['heldMilliCredits'],result['usedMilliCredits']), (4000,6000,0))

    def test_settlement_releases_difference_once(self):
        settle={'id':'s','reservationId':'r','credits':{'op':'settle','allocations':[{'grantId':'g','milli':2000}]}}
        result=self.project([self.grant(),self.reserve(),settle])
        self.assertEqual((result['availableMilliCredits'],result['heldMilliCredits'],result['usedMilliCredits']), (8000,0,2000))

    def test_expiry_does_not_erase_outstanding_holds(self):
        result=self.project([self.grant(expiry=90),self.reserve()])
        self.assertEqual((result['availableMilliCredits'],result['heldMilliCredits']), (0,6000))

    def test_failed_operation_returns_all_held_credits(self):
        release={'id':'s','reservationId':'r','credits':{'op':'settle','allocations':[]}}
        result=self.project([self.grant(),self.reserve(),release])
        self.assertEqual((result['availableMilliCredits'],result['heldMilliCredits']), (10000,0))

    def test_reversal_of_consumed_grant_creates_visible_debt(self):
        settle={'id':'s','reservationId':'r','credits':{'op':'settle','allocations':[{'grantId':'g','milli':6000}]}}
        reverse={'id':'v','reservationId':None,'credits':{'op':'reverse','grantId':'g','milli':10000}}
        result=self.project([self.grant(),self.reserve(),settle,reverse])
        self.assertEqual((result['availableMilliCredits'],result['debtMilliCredits']), (0,6000))

    def test_allocation_uses_earliest_expiring_grants_first(self):
        other={'id':'late','reservationId':None,'credits':{'op':'grant','milli':2000,'expiresAt':500}}
        result=self.project([other,self.grant(expiry=200)])
        self.assertEqual(result['lots'][0]['grantId'],'g')

    def test_negative_or_foreign_allocation_fails_closed(self):
        row=self.reserve();row['credits']['allocations'][0]['grantId']='foreign'
        with self.assertRaises(ValueError): self.project([self.grant(),row])
