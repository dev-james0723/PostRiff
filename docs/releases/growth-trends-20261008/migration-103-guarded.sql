-- Guarded production apply: 103_feature_enrollments (additive).
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM postriff_private.schema_migrations WHERE name='103_feature_enrollments.sql') THEN
    RAISE EXCEPTION '103 already recorded in the ledger';
  END IF;
  IF to_regclass('public.pr_feature_enrollments') IS NOT NULL THEN
    RAISE EXCEPTION 'pr_feature_enrollments already exists without a ledger row; refusing';
  END IF;
END
$guard$;
-- ===== 103_feature_enrollments.sql sha256 b3b8b681bf78100202ec15f0a37e05417d304663d19623e4930a2b02f67cd40c
-- Owner-initiated self-serve enrollment for Trends and Growth measurement.
-- Additive only: one new service-role table with forced RLS. No provider policy,
-- ingestion, budget or consent is created by an enrollment row.
CREATE TABLE IF NOT EXISTS public.pr_feature_enrollments (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  feature text NOT NULL CHECK (feature IN ('trend_radar','growth_measurement')),
  status text NOT NULL CHECK (status IN ('active','revoked')),
  policy_version text NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 64),
  enrolled_by uuid NOT NULL,
  enrolled_at timestamptz NOT NULL DEFAULT now(),
  revoked_by uuid,
  revoked_at timestamptz,
  revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
  PRIMARY KEY (workspace_id, feature),
  CHECK ((status='active' AND revoked_at IS NULL AND revoked_by IS NULL)
      OR (status='revoked' AND revoked_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS pr_feature_enrollments_active_idx
  ON public.pr_feature_enrollments(feature, workspace_id) WHERE status='active';

ALTER TABLE public.pr_feature_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_feature_enrollments FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_feature_enrollments FROM public, anon, authenticated;
GRANT ALL ON public.pr_feature_enrollments TO service_role;
DO $policy$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='pr_feature_enrollments'
                 AND policyname='pr_feature_enrollments_runtime') THEN
    CREATE POLICY pr_feature_enrollments_runtime ON public.pr_feature_enrollments
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $policy$;
INSERT INTO postriff_private.schema_migrations(name, sha256) VALUES ('103_feature_enrollments.sql', 'b3b8b681bf78100202ec15f0a37e05417d304663d19623e4930a2b02f67cd40c');
