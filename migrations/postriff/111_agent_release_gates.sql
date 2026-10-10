-- CF2 live release evidence. Additive candidate; no flag activation and no production application by this file.
-- Writes only through the trusted release coordinator after independent browser and physical-attempt verification.
-- No user text, prompts, sources or credentials: digests, IDs and outcome provenance only. Browser/API roles get no access.
BEGIN;
CREATE TABLE IF NOT EXISTS public.pr_agent_release_gates (
 run_id uuid PRIMARY KEY,
 workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
 release_sha text NOT NULL CHECK (release_sha ~ '^[0-9a-f]{40}$'),
 profile text NOT NULL CHECK (profile IN ('full','recommended_narrowed')),
 receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
 receipt jsonb NOT NULL CHECK (jsonb_typeof(receipt)='object' AND octet_length(receipt::text)<=131072),
 verified_at timestamptz NOT NULL,
 revoked_at timestamptz,
 CHECK (coalesce(receipt->>'contract'='rafii-live-permission-gate/1',false)),
 CHECK (coalesce(receipt->>'execution'='live-browser+database',false)),
 CHECK (coalesce((receipt->>'runId')::uuid=run_id AND (receipt->>'workspaceId')::uuid=workspace_id,false)),
 CHECK (coalesce(receipt->>'releaseSha'=release_sha AND receipt->>'profile'=profile,false))
);
CREATE INDEX IF NOT EXISTS pr_agent_release_gates_current ON public.pr_agent_release_gates(workspace_id,release_sha,verified_at DESC) WHERE revoked_at IS NULL;
ALTER TABLE public.pr_agent_release_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_agent_release_gates FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_agent_release_gates FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT ON public.pr_agent_release_gates TO service_role;
GRANT UPDATE(revoked_at) ON public.pr_agent_release_gates TO service_role;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='pr_agent_release_gates' AND policyname='service_only') THEN
  CREATE POLICY service_only ON public.pr_agent_release_gates FOR ALL TO service_role USING(true) WITH CHECK(true);
 END IF;
END $$;
-- The evidence envelope is immutable, and a revocation cannot be reversed or rewritten.
CREATE OR REPLACE FUNCTION postriff_private.pr_agent_release_gate_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at')
    OR OLD.revoked_at IS NOT NULL
    OR NEW.revoked_at IS NULL
    OR NEW.revoked_at < OLD.verified_at THEN
  RAISE EXCEPTION 'Release gate evidence is immutable; revocation is final' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS pr_agent_release_gate_guard ON public.pr_agent_release_gates;
CREATE TRIGGER pr_agent_release_gate_guard BEFORE UPDATE ON public.pr_agent_release_gates
 FOR EACH ROW EXECUTE FUNCTION postriff_private.pr_agent_release_gate_guard();
COMMIT;
