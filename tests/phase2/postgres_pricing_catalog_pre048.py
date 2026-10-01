"""`GET /api/plans` on the schema before migration 048 (disposable PG17, base schema only; R-ENG-03).

Break caught: the legacy catalog read `pr_plan_terms.new_checkout_enabled`, a 048 column, so on any database without
048 (production before its approved migration, the staging-backed preview) the public plan endpoint answered 500.
Legacy pricing must keep working there; the v2 catalog must refuse cleanly instead of failing.
"""
import unittest

import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.plan_pricing import CATALOG_VERSION_LEGACY, public_catalog

DSN = 'host=127.0.0.1 port=55438 dbname=postgres'


def connection():
    return psycopg.connect(DSN, client_encoding='utf8')


class CatalogBefore048(unittest.TestCase):
    def setUp(self):
        with connection() as db:
            present = db.execute("SELECT to_regclass('public.pr_plan_price_variants') IS NOT NULL").fetchone()[0]
            column = db.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='pr_plan_terms' "
                                "AND column_name='new_checkout_enabled'").fetchone()[0]
        self.assertFalse(present or column, 'this group must run on the schema before 048')

    def test_legacy_catalog_is_served_without_048(self):
        with connection() as db, db.cursor() as cur:
            catalog = public_catalog(cur, False)
        self.assertEqual((catalog['catalogVersion'], catalog['pricing']), (CATALOG_VERSION_LEGACY, 'legacy'))
        self.assertTrue(catalog['plans'])

    def test_v2_catalog_refuses_cleanly_without_048(self):
        with connection() as db, db.cursor() as cur, self.assertRaises(AlphaError) as caught:
            public_catalog(cur, True)
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'catalog_unavailable'))


if __name__ == '__main__':
    unittest.main()
