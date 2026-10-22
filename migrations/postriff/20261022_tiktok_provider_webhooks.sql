-- Candidate only: separately approved production SQL required. Lets TikTok authorization.removed events use the
-- existing provider-webhook ledger (migration 044). No grants, customer content or existing rows change.
BEGIN;
SET LOCAL lock_timeout = '5s';
DO $$
DECLARE existing text; allowed text[]; validated boolean;
BEGIN
  SELECT pg_get_expr(conbin,conrelid),convalidated INTO existing,validated FROM pg_constraint
   WHERE conrelid=to_regclass('public.pr_social_provider_events') AND conname='pr_social_provider_events_provider_check' AND contype='c';
  IF existing IS NULL OR validated IS NOT TRUE THEN RAISE EXCEPTION 'Expected migration044 provider CHECK is missing'; END IF;
  SELECT array_agg(m[1] ORDER BY m[1]) INTO allowed FROM regexp_matches(existing, $rx$'([^']+)'$rx$, 'g') m;
  IF allowed=ARRAY['tiktok','xiaohongshu'] THEN RETURN; END IF;
  IF allowed IS DISTINCT FROM ARRAY['xiaohongshu'] THEN RAISE EXCEPTION 'Unexpected provider-webhook CHECK; review source drift'; END IF;
  ALTER TABLE public.pr_social_provider_events DROP CONSTRAINT pr_social_provider_events_provider_check;
  ALTER TABLE public.pr_social_provider_events ADD CONSTRAINT pr_social_provider_events_provider_check CHECK(provider IN ('xiaohongshu','tiktok')) NOT VALID;
  ALTER TABLE public.pr_social_provider_events VALIDATE CONSTRAINT pr_social_provider_events_provider_check;
END $$;
COMMIT;
