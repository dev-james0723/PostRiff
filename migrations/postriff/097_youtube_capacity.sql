-- Reviewed candidate: quota reservations and fair worker selection. No provider calls.
BEGIN;
ALTER TABLE public.pr_youtube_usage ADD COLUMN IF NOT EXISTS project_key text NOT NULL DEFAULT 'legacy-unattributed';
ALTER TABLE public.pr_youtube_usage ADD COLUMN IF NOT EXISTS admitted boolean NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS pr_youtube_usage_project_time_idx ON public.pr_youtube_usage(project_key,bucket,attempted_at);

CREATE TABLE IF NOT EXISTS public.pr_youtube_quota_daily (
  project_key text NOT NULL,
  quota_date date NOT NULL,
  bucket text NOT NULL,
  scope_key text NOT NULL,
  workspace_id uuid REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  used_units bigint NOT NULL DEFAULT 0 CHECK(used_units>=0),
  admitted_requests bigint NOT NULL DEFAULT 0 CHECK(admitted_requests>=0),
  denied_requests bigint NOT NULL DEFAULT 0 CHECK(denied_requests>=0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(project_key,quota_date,bucket,scope_key),
  CHECK((workspace_id IS NULL AND scope_key='project') OR (workspace_id IS NOT NULL AND scope_key=workspace_id::text))
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_rate_windows (
  project_key text NOT NULL,
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  window_start timestamptz NOT NULL,
  requests integer NOT NULL DEFAULT 0 CHECK(requests>=0),
  PRIMARY KEY(project_key,workspace_id,window_start)
);
CREATE TABLE IF NOT EXISTS public.pr_worker_tenants (
  workspace_id uuid PRIMARY KEY REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  last_claimed_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS pr_worker_tenants_dispatch_idx ON public.pr_worker_tenants(last_claimed_at,workspace_id);

DO $policy$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['pr_youtube_quota_daily','pr_youtube_rate_windows','pr_worker_tenants'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM public,anon,authenticated',t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
    IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=t AND policyname=t||'_runtime') THEN
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO service_role USING(true) WITH CHECK(true)',t||'_runtime',t);
    END IF;
  END LOOP;
END $policy$;
COMMIT;
