\set ON_ERROR_STOP on
-- Parent-owned disposable PG17 only, fresh fixture database. No server lifecycle.
-- If the parent's rls.sql base is already loaded, do not replay this setup.
\ir rls.sql
\ir ../../migrations/postriff/020_credit_quotes.sql
\ir ../../migrations/postriff/021_credit_purchases.sql
\ir ../../migrations/postriff/022_credit_payment_lifecycle.sql
\ir ../../migrations/postriff/089_pricing_credit_catalog_v2.sql
\ir ../../migrations/postriff/090_free_lifecycle_bootstrap.sql
\ir ../../migrations/postriff/091_pricing_public_four_plans.sql
\ir ../../migrations/postriff/092_fixed_plan_checkout_approval.sql
