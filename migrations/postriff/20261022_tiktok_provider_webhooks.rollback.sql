-- Separately reviewed rollback only. Refuses to drop TikTok from the CHECK while TikTok webhook rows exist.
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $$
DECLARE existing text; allowed text[]; validated boolean;
BEGIN
  SELECT pg_get_expr(conbin,conrelid),convalidated INTO existing,validated FROM pg_constraint
   WHERE conrelid=to_regclass('public.pr_social_provider_events') AND conname='pr_social_provider_events_provider_check' AND contype='c';
  IF existing IS NULL OR validated IS NOT TRUE THEN RAISE EXCEPTION 'Expected provider-webhook CHECK is missing; review source drift'; END IF;
  SELECT array_agg(m[1] ORDER BY m[1]) INTO allowed FROM regexp_matches(existing, $rx$'([^']+)'$rx$, 'g') m;
  IF allowed=ARRAY['xiaohongshu'] THEN RETURN; END IF;
  IF allowed IS DISTINCT FROM ARRAY['tiktok','xiaohongshu'] THEN RAISE EXCEPTION 'Unexpected provider-webhook CHECK; review source drift'; END IF;
  IF EXISTS (SELECT 1 FROM public.pr_social_provider_events WHERE provider='tiktok') THEN
    RAISE EXCEPTION 'TikTok webhook rows exist; export and remove them in a reviewed step first';
  END IF;
  ALTER TABLE public.pr_social_provider_events DROP CONSTRAINT pr_social_provider_events_provider_check;
  ALTER TABLE public.pr_social_provider_events ADD CONSTRAINT pr_social_provider_events_provider_check CHECK(provider IN ('xiaohongshu')) NOT VALID;
  ALTER TABLE public.pr_social_provider_events VALIDATE CONSTRAINT pr_social_provider_events_provider_check;
END $$;
COMMIT;
