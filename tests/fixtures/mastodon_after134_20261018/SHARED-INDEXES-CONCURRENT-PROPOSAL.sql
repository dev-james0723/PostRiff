-- FUTURE ONLY. Not runnable through an atomic migration wrapper.
-- Requires separate explicit approval, current core-ledger/hash and index-state readback.
-- Use a trusted autocommit admin connection bound to exact approved target, one statement at a time.
-- Do NOT use IF NOT EXISTS: an invalid leftover index must be reconciled, never silently accepted.
-- If outcome is uncertain, read pg_class/pg_index (indisready,indisvalid,indexdef) before any retry.
-- Do not DROP an invalid index without a separate exact destructive approval.
DO $indexes_preflight$
BEGIN
  IF (SELECT sha256 FROM postriff_private.schema_migrations WHERE name='20261018160404_mastodon_management_after_connect_134.sql')
       IS DISTINCT FROM '66afc61f47add5747fd819dab89d98a2d84f357f0f4e250df8974eda69b1b3ea' THEN
    RAISE EXCEPTION 'BLOCKED: exact approved management core ledger missing';
  END IF;
  IF to_regclass('public.pr_mastodon_actions') IS NULL OR to_regclass('public.pr_mastodon_health') IS NULL THEN
    RAISE EXCEPTION 'BLOCKED: management core tables missing';
  END IF;
  IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
      AND c.relname IN ('pr_mastodon_metrics_retention','pr_mastodon_reads_retention')) THEN
    RAISE EXCEPTION 'BLOCKED: retention index name exists; reconcile ready/valid/definition before retry';
  END IF;
END; $indexes_preflight$;
CREATE INDEX CONCURRENTLY pr_mastodon_metrics_retention
  ON public.pr_metric_observations(observed_at,id) WHERE provider='mastodon';
CREATE INDEX CONCURRENTLY pr_mastodon_reads_retention
  ON public.pr_metric_reads(updated_at,id) WHERE provider='mastodon' AND status IN ('done','cancelled','dead','unavailable');
