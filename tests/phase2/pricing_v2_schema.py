"""LOCAL TEST ONLY: add the credit and Pricing v2 tables the shared RLS fixture omits.

The fixture (rls.sql) stops short of 020-022 and 136-139. Scripts that need them call
ensure(db) on their own disposable cluster, so they run under any runner unchanged.
"""
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations/postriff'
CHAIN = ('020_credit_quotes.sql', '021_credit_purchases.sql', '022_credit_payment_lifecycle.sql',
         '136_pricing_credit_catalog_v2.sql', '137_free_lifecycle_bootstrap.sql',
         '138_pricing_public_four_plans.sql', '139_fixed_plan_checkout_approval.sql')


def ensure(db):
    if db.execute("SELECT to_regclass('public.pr_plan_price_variants')").fetchone()[0]:
        return
    for name in CHAIN:
        db.execute((MIGRATIONS / name).read_text(), prepare=False)
    db.commit()
