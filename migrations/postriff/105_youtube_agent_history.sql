-- Reviewed candidate only: immutable private history, no automatic compaction/provider calls.
-- Archive insertion and workspace JSON compaction share the caller's transaction.
BEGIN;
CREATE TABLE IF NOT EXISTS public.pr_youtube_agent_history (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  connection_id text NOT NULL,
  record_kind text NOT NULL CHECK(record_kind IN ('draft','policy')),
  record_id text NOT NULL CHECK(record_id ~ '^[A-Za-z0-9_-]{1,128}$'),
  record jsonb NOT NULL CHECK(jsonb_typeof(record)='object'),
  record_sha256 text NOT NULL CHECK(record_sha256 ~ '^[a-f0-9]{64}$'),
  archived_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,connection_id,record_kind,record_id),
  CONSTRAINT pr_youtube_agent_history_record_scope CHECK(
    record ? 'id' AND record ? 'connectionId' AND
    jsonb_typeof(record->'id')='string' AND jsonb_typeof(record->'connectionId')='string' AND
    record->>'id'=record_id AND record->>'connectionId'=connection_id),
  CONSTRAINT pr_youtube_agent_history_credential_fk FOREIGN KEY(workspace_id,connection_id)
    REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS pr_youtube_agent_history_page_idx ON public.pr_youtube_agent_history
  (workspace_id,connection_id,record_kind,archived_at DESC,record_id DESC);

ALTER TABLE public.pr_youtube_agent_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_youtube_agent_history FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_youtube_agent_history FROM public,anon,authenticated,service_role;
-- UPDATE is intentionally absent; DELETE is only authorized account/disconnect cleanup.
GRANT SELECT,INSERT,DELETE ON public.pr_youtube_agent_history TO service_role;
DO $policy$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public'
      AND tablename='pr_youtube_agent_history' AND policyname='pr_youtube_agent_history_runtime') THEN
    CREATE POLICY pr_youtube_agent_history_runtime ON public.pr_youtube_agent_history
      FOR ALL TO service_role USING(true) WITH CHECK(true);
  END IF;
END $policy$;

-- Protect original records and ordering even from accidental server-side UPDATE.
CREATE OR REPLACE FUNCTION postriff_private.youtube_agent_history_immutable()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $body$
BEGIN
  RAISE EXCEPTION 'YouTube history records are immutable' USING ERRCODE='55000';
END $body$;
REVOKE ALL ON FUNCTION postriff_private.youtube_agent_history_immutable() FROM public,anon,authenticated;
GRANT EXECUTE ON FUNCTION postriff_private.youtube_agent_history_immutable() TO service_role;
DROP TRIGGER IF EXISTS pr_youtube_agent_history_immutable ON public.pr_youtube_agent_history;
CREATE TRIGGER pr_youtube_agent_history_immutable BEFORE UPDATE ON public.pr_youtube_agent_history
  FOR EACH ROW EXECUTE FUNCTION postriff_private.youtube_agent_history_immutable();

-- The credential PK is (workspace_id,connection_id), not provider. Bind to
-- YouTube without duplicating the entire credential index. A SHARE lock fences
-- concurrent provider reassignment; the second trigger preserves the invariant
-- on later provider changes. Normal token rotation/revocation updates are untouched.
CREATE OR REPLACE FUNCTION postriff_private.youtube_agent_history_provider()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $body$
DECLARE bound_provider text;
BEGIN
  SELECT provider INTO bound_provider FROM public.pr_encrypted_credentials
    WHERE workspace_id=NEW.workspace_id AND connection_id=NEW.connection_id FOR SHARE;
  IF bound_provider IS DISTINCT FROM 'youtube' THEN
    RAISE EXCEPTION 'YouTube history requires the exact YouTube credential' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $body$;
CREATE OR REPLACE FUNCTION postriff_private.youtube_agent_history_provider_change()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $body$
BEGIN
  IF NEW.provider<>'youtube' AND EXISTS(SELECT 1 FROM public.pr_youtube_agent_history
      WHERE workspace_id=OLD.workspace_id AND connection_id=OLD.connection_id) THEN
    RAISE EXCEPTION 'A credential with YouTube history cannot change provider' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $body$;
REVOKE ALL ON FUNCTION postriff_private.youtube_agent_history_provider(),
  postriff_private.youtube_agent_history_provider_change() FROM public,anon,authenticated;
GRANT EXECUTE ON FUNCTION postriff_private.youtube_agent_history_provider(),
  postriff_private.youtube_agent_history_provider_change() TO service_role;
DROP TRIGGER IF EXISTS pr_youtube_agent_history_provider ON public.pr_youtube_agent_history;
CREATE TRIGGER pr_youtube_agent_history_provider BEFORE INSERT ON public.pr_youtube_agent_history
  FOR EACH ROW EXECUTE FUNCTION postriff_private.youtube_agent_history_provider();
DROP TRIGGER IF EXISTS pr_youtube_agent_history_provider_change ON public.pr_encrypted_credentials;
CREATE TRIGGER pr_youtube_agent_history_provider_change BEFORE UPDATE OF provider ON public.pr_encrypted_credentials
  FOR EACH ROW WHEN(OLD.provider IS DISTINCT FROM NEW.provider)
  EXECUTE FUNCTION postriff_private.youtube_agent_history_provider_change();
COMMIT;
