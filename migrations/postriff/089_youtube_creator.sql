-- Candidate migration: apply only through the authorized release workflow. No external migration in this task.
BEGIN;

-- Google code exchange is claimed durably before calling the provider.
ALTER TABLE public.pr_oauth_transactions DROP CONSTRAINT IF EXISTS pr_oauth_transactions_outcome_check;
ALTER TABLE public.pr_oauth_transactions ADD CONSTRAINT pr_oauth_transactions_outcome_check CHECK (outcome IN ('exchange_started','exchanged','denied','expired','mismatch'));

CREATE TABLE IF NOT EXISTS public.pr_youtube_uploads (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  operation_key text NOT NULL,
  state jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, connection_id, operation_key)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  actor uuid NOT NULL,
  operation_key text NOT NULL,
  manifest jsonb NOT NULL,
  manifest_digest text NOT NULL,
  status text NOT NULL CHECK (status IN ('prepared','started','accepted','verified','failed','outcome_unknown')),
  receipt jsonb,
  secret_ciphertext text,
  secret_key_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, connection_id, operation_key)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_usage (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  method text NOT NULL,
  bucket text NOT NULL,
  estimated_units integer,
  attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pr_youtube_usage_time_idx ON public.pr_youtube_usage(workspace_id,attempted_at);
CREATE TABLE IF NOT EXISTS public.pr_youtube_settings (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  monetary_authorized boolean NOT NULL DEFAULT false,
  memberships_authorized boolean NOT NULL DEFAULT false,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, connection_id)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_cache (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  cache_key text NOT NULL,
  source text NOT NULL,
  data jsonb NOT NULL,
  refreshed_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (workspace_id,connection_id,cache_key)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_chat_cursor (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  live_chat_id text NOT NULL,
  next_page_token text,
  next_read_at timestamptz,
  seen_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,connection_id,live_chat_id)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_reporting_coverage (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  job_id text NOT NULL,
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  report_id text NOT NULL,
  report_created_at timestamptz NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT now(),
  dataset jsonb NOT NULL,
  PRIMARY KEY (workspace_id,connection_id,job_id,start_time,end_time)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_push (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  channel_id text NOT NULL,
  callback text NOT NULL,
  topic text NOT NULL,
  status text NOT NULL CHECK(status IN ('prepared','requested','awaiting_verification','active','inactive','failed','outcome_unknown')),
  automatic_renewal boolean NOT NULL DEFAULT false,
  lease_expires_at timestamptz,
  secret_ciphertext text NOT NULL,
  secret_key_id text NOT NULL,
  pending_secret_ciphertext text,
  pending_secret_key_id text,
  review jsonb NOT NULL,
  review_digest text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id,connection_id)
);

-- Preserve YouTube hierarchy in the shared approval-gated Inbox.
ALTER TABLE public.pr_audience_threads ADD COLUMN IF NOT EXISTS provider_thread_id text;
ALTER TABLE public.pr_audience_threads ADD COLUMN IF NOT EXISTS provider_parent_id text;
ALTER TABLE public.pr_audience_threads ADD COLUMN IF NOT EXISTS provider_channel_id text;
ALTER TABLE public.pr_audience_threads ADD COLUMN IF NOT EXISTS moderation_state text;

DO $policy$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['pr_youtube_uploads','pr_youtube_actions','pr_youtube_usage','pr_youtube_settings','pr_youtube_cache','pr_youtube_chat_cursor','pr_youtube_reporting_coverage','pr_youtube_push'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM public, anon, authenticated', t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid=('public.'||t)::regclass AND conname=t||'_credential_fk') THEN
      EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY(workspace_id,connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE',t,t||'_credential_fk');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=t AND policyname=t||'_runtime') THEN
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',t||'_runtime',t);
    END IF;
  END LOOP;
END $policy$;
GRANT USAGE, SELECT ON SEQUENCE public.pr_youtube_usage_id_seq TO service_role;
COMMIT;
