-- Candidate only: separately approved production SQL required. No grants, customer content or existing rows change; four native metric definitions are additive.
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $$
DECLARE existing text; allowed text[]; validated boolean;
BEGIN
  SELECT pg_get_expr(conbin,conrelid),convalidated INTO existing,validated FROM pg_constraint
   WHERE conrelid=to_regclass('public.pr_metric_reads') AND conname='pr_metric_reads_provider_check' AND contype='c';
  IF existing IS NULL OR validated IS NOT TRUE OR position('provider = ANY' in existing)=0 THEN RAISE EXCEPTION 'Expected migration035 metric provider CHECK is missing'; END IF;
  SELECT array_agg(m[1] ORDER BY m[1]) INTO allowed FROM regexp_matches(existing, $rx$'([^']+)'$rx$, 'g') m;
  IF allowed=ARRAY['instagram','pinterest','threads'] THEN RETURN; END IF;
  IF allowed IS DISTINCT FROM ARRAY['instagram','threads'] THEN RAISE EXCEPTION 'Unexpected metric provider CHECK; review source drift'; END IF;
  ALTER TABLE public.pr_metric_reads DROP CONSTRAINT pr_metric_reads_provider_check;
  ALTER TABLE public.pr_metric_reads ADD CONSTRAINT pr_metric_reads_provider_check CHECK(provider IN ('threads','instagram','pinterest')) NOT VALID;
  ALTER TABLE public.pr_metric_reads VALIDATE CONSTRAINT pr_metric_reads_provider_check;
END $$;
INSERT INTO public.pr_metric_definitions(provider,metric,native_name,definition_version,unit,scope,definition_url) VALUES
 ('pinterest','impressions','IMPRESSION','pinterest-pin-utc-window-v1','count','post','https://github.com/pinterest/api-description/blob/main/v5/openapi.json'),
 ('pinterest','saves','SAVE','pinterest-pin-utc-window-v1','count','post','https://github.com/pinterest/api-description/blob/main/v5/openapi.json'),
 ('pinterest','pin_clicks','PIN_CLICK','pinterest-pin-utc-window-v1','count','post','https://github.com/pinterest/api-description/blob/main/v5/openapi.json'),
 ('pinterest','outbound_clicks','OUTBOUND_CLICK','pinterest-pin-utc-window-v1','count','post','https://github.com/pinterest/api-description/blob/main/v5/openapi.json')
ON CONFLICT(provider,metric,definition_version) DO NOTHING;
COMMIT;
