-- Policy plumbing only. No document, approval, acceptance or public launch is seeded.
BEGIN;
CREATE TABLE IF NOT EXISTS public.pr_youtube_policy_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  privacy_revision text NOT NULL CHECK(length(privacy_revision) BETWEEN 1 AND 100),
  privacy_url text NOT NULL CHECK(privacy_url ~ '^https://'),
  privacy_sha256 text NOT NULL CHECK(privacy_sha256 ~ '^[0-9a-f]{64}$'),
  terms_revision text NOT NULL CHECK(length(terms_revision) BETWEEN 1 AND 100),
  terms_url text NOT NULL CHECK(terms_url ~ '^https://'),
  terms_sha256 text NOT NULL CHECK(terms_sha256 ~ '^[0-9a-f]{64}$'),
  approved_by text NOT NULL CHECK(length(trim(approved_by))>0),
  approval_reference text NOT NULL CHECK(length(trim(approval_reference))>0),
  approved_at timestamptz NOT NULL,
  published_at timestamptz NOT NULL CHECK(published_at>=approved_at),
  is_current boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS pr_youtube_policy_current_idx
  ON public.pr_youtube_policy_revisions(is_current) WHERE is_current;
CREATE OR REPLACE FUNCTION postriff_private.youtube_policy_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $immutable$
BEGIN
  IF (to_jsonb(NEW)-'is_current') IS DISTINCT FROM (to_jsonb(OLD)-'is_current') THEN
    RAISE EXCEPTION 'Published policy revisions are immutable; register a new revision';
  END IF;
  RETURN NEW;
END $immutable$;
DROP TRIGGER IF EXISTS pr_youtube_policy_immutable ON public.pr_youtube_policy_revisions;
CREATE TRIGGER pr_youtube_policy_immutable BEFORE UPDATE ON public.pr_youtube_policy_revisions
  FOR EACH ROW EXECUTE FUNCTION postriff_private.youtube_policy_immutable();

CREATE TABLE IF NOT EXISTS public.pr_youtube_policy_acceptances (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.pr_profiles(user_id) ON DELETE CASCADE,
  policy_id uuid NOT NULL REFERENCES public.pr_youtube_policy_revisions(id),
  accepted_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id,user_id,policy_id),
  UNIQUE(workspace_id,id)
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_policy_bindings (
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  authorization_generation uuid NOT NULL,
  receipt_id uuid NOT NULL,
  PRIMARY KEY(workspace_id,connection_id),
  FOREIGN KEY(workspace_id,connection_id)
    REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE,
  FOREIGN KEY(workspace_id,receipt_id)
    REFERENCES public.pr_youtube_policy_acceptances(workspace_id,id) ON DELETE CASCADE
);
DO $policy$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['pr_youtube_policy_revisions','pr_youtube_policy_acceptances','pr_youtube_policy_bindings'] LOOP
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
