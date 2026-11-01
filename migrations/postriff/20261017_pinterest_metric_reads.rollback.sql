-- Separately reviewed rollback only. Refuse data loss and schema drift; pause analytics first.
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $$
DECLARE existing text; allowed text[]; validated boolean;
BEGIN
  SELECT pg_get_expr(conbin,conrelid),convalidated INTO existing,validated FROM pg_constraint
   WHERE conrelid=to_regclass('public.pr_metric_reads') AND conname='pr_metric_reads_provider_check' AND contype='c';
  IF existing IS NULL OR validated IS NOT TRUE OR position('provider = ANY' in existing)=0 THEN
    RAISE EXCEPTION 'Expected validated metric provider CHECK is missing; review source drift';
  END IF;
  SELECT array_agg(m[1] ORDER BY m[1]) INTO allowed FROM regexp_matches(existing, $rx$'([^']+)'$rx$, 'g') m;
  IF allowed IS DISTINCT FROM ARRAY['instagram','pinterest','threads'] AND allowed IS DISTINCT FROM ARRAY['instagram','threads'] THEN
    RAISE EXCEPTION 'Unexpected metric provider CHECK; review source drift';
  END IF;
  IF EXISTS(SELECT 1 FROM public.pr_metric_reads WHERE provider='pinterest') THEN
    RAISE EXCEPTION 'Pinterest metric rows exist; preserve them and keep the expanded CHECK';
  END IF;
  IF allowed=ARRAY['instagram','threads'] THEN RETURN; END IF;
  ALTER TABLE public.pr_metric_reads DROP CONSTRAINT pr_metric_reads_provider_check;
  ALTER TABLE public.pr_metric_reads ADD CONSTRAINT pr_metric_reads_provider_check CHECK(provider IN ('threads','instagram')) NOT VALID;
  ALTER TABLE public.pr_metric_reads VALIDATE CONSTRAINT pr_metric_reads_provider_check;
END $$;
COMMIT;
