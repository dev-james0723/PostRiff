BEGIN;
CREATE TABLE IF NOT EXISTS public.pr_x_resource_evidence(
 workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
 connection_id text NOT NULL CHECK(connection_id ~ '^[0-9a-f]{32}$'),
 credential_generation text NOT NULL CHECK(length(credential_generation) BETWEEN 1 AND 256),
 post_id text NOT NULL CHECK(post_id ~ '^[1-9][0-9]{0,18}$'),
 evidence_kind text NOT NULL CHECK(evidence_kind IN ('summoned_reply','post_edit')),
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 expires_at timestamptz NOT NULL CHECK(isfinite(expires_at)),
 PRIMARY KEY(workspace_id,connection_id,credential_generation,post_id,evidence_kind),
 FOREIGN KEY(workspace_id,connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS pr_x_resource_evidence_expiry_idx ON public.pr_x_resource_evidence(expires_at);
ALTER TABLE public.pr_x_resource_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_x_resource_evidence FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_x_resource_evidence FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.pr_x_resource_evidence TO service_role;
DROP POLICY IF EXISTS pr_x_resource_evidence_service_only ON public.pr_x_resource_evidence;
CREATE POLICY pr_x_resource_evidence_service_only ON public.pr_x_resource_evidence
 FOR ALL TO service_role USING(true) WITH CHECK(true);
COMMENT ON TABLE public.pr_x_resource_evidence IS 'Fresh internal X response metadata only; no provider content; exact tenant and credential generation.';
COMMIT;
