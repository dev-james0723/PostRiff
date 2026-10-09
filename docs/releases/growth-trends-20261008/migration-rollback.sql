-- Rollback (only if the release is abandoned; the tables are new and must be empty first).
BEGIN;
DO $c$ DECLARE t text; n bigint; BEGIN
  FOREACH t IN ARRAY ARRAY['pr_creator_calibrations','pr_audience_clusters','pr_comment_judgments','pr_postmortems',
    'pr_growth_budgets','pr_public_checks','pr_share_cards','pr_predictions','pr_post_doctor_runs','pr_genome_versions','pr_post_history','pr_feature_enrollments'] LOOP
    IF to_regclass('public.'||t) IS NOT NULL THEN EXECUTE format('SELECT count(*) FROM public.%I',t) INTO n;
      IF n>0 THEN RAISE EXCEPTION 'refusing rollback: % has % rows', t, n; END IF; END IF;
  END LOOP; END $c$;
DROP TABLE IF EXISTS public.pr_creator_calibrations, public.pr_audience_clusters, public.pr_comment_judgments, public.pr_postmortems,
  public.pr_growth_budgets, public.pr_public_checks, public.pr_share_cards, public.pr_predictions, public.pr_post_doctor_runs,
  public.pr_genome_versions, public.pr_post_history, public.pr_feature_enrollments;
DELETE FROM postriff_private.schema_migrations WHERE name IN ('037_growth_phase1.sql','038_growth_closed_loop.sql','103_feature_enrollments.sql');
COMMIT;
