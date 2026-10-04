"""Public OFF/rollback cannot restore old new-sale packages: synthetic cursors only."""
import unittest
from postriff_alpha.domain import AlphaError
from postriff_phase2.plan_pricing import public_catalog
from test_surviving_pricing_catalog import Cursor

class RollbackCatalog(unittest.TestCase):
    def test_post048_off_displays_free_creator_even_if_persisted_sale_is_enabled(self):
        shown=public_catalog(Cursor(True),False,credits_enabled=True)
        self.assertEqual(shown['pricing'],'v2')
        self.assertEqual([p['plan'] for p in shown['plans']],['free','starter','creator','studio'])
        self.assertEqual([(p['priceCents'],p['monthlyCredits']) for p in shown['plans']],[(0,0),(2900,1000),(5900,3500),(14900,8000)])
        self.assertEqual([p['checkout'] for p in shown['plans']],['not_applicable','not_yet_available','not_yet_available','not_yet_available'])
        self.assertFalse(shown['plans'][2]['checkoutAvailable'])
        self.assertFalse(shown['topUps']['available'])
    def test_pre048_public_off_is_unavailable_instead_of_old_new_sale(self):
        cur=Cursor(False)
        with self.assertRaises(AlphaError) as caught:public_catalog(cur,False,credits_enabled=False)
        self.assertEqual((caught.exception.status,caught.exception.code),(503,'catalog_unavailable'))
        self.assertEqual(len(cur.calls),1)
    def test_qualified_public_creator_projection_has_explicit_purchase_permission(self):
        shown=public_catalog(Cursor(True),True,credits_enabled=True)
        self.assertEqual(shown['plans'][2]['checkout'],'available')
        self.assertIs(shown['plans'][2].get('checkoutAvailable'),True)
        self.assertIs(shown['plans'][0].get('checkoutAvailable'),False)

if __name__=='__main__':unittest.main()
