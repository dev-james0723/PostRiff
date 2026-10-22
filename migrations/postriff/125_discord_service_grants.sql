-- Canonical Supabase default grants can give service_role DELETE/TRUNCATE.
-- Keep operational rate/admission evidence outside routine destructive grants.
BEGIN;
REVOKE ALL ON public.pr_discord_rate_state,public.pr_discord_route_buckets,public.pr_discord_request_admissions FROM service_role;
GRANT SELECT,INSERT,UPDATE ON public.pr_discord_rate_state,public.pr_discord_route_buckets,public.pr_discord_request_admissions TO service_role;
REVOKE ALL ON SEQUENCE public.pr_discord_request_admissions_request_seq_seq FROM service_role;
GRANT USAGE,SELECT ON SEQUENCE public.pr_discord_request_admissions_request_seq_seq TO service_role;
COMMIT;
