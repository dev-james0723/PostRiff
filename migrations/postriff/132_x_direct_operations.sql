-- Candidate only: durable, approval-bound X operations. No provider request or production application.
BEGIN;
CREATE TABLE IF NOT EXISTS public.pr_x_direct_operations (
    workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    connection_id text NOT NULL,
    provider_account_id text NOT NULL CHECK(provider_account_id ~ '^[0-9]{1,25}$'),
    authorization_generation text NOT NULL,
    operation_id text NOT NULL,
    request_key text NOT NULL,
    request jsonb NOT NULL,
    digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    preview_expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'needs_approval' CHECK(state IN
      ('needs_approval','queued','dispatching','accepted','verified','uncertain','failed','held','canceled')),
    approved_by uuid,
    approved_at timestamptz,
    approval_expires_at timestamptz,
    next_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0 AND attempts<=3),
    checks integer NOT NULL DEFAULT 0 CHECK(checks>=0 AND checks<=3),
    lease_id uuid,
    lease_until timestamptz,
    cancel_requested boolean NOT NULL DEFAULT false,
    progress jsonb NOT NULL DEFAULT '{}'::jsonb,
    receipts jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(receipts)='array'),
    reason_code text,
    reason text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,id),
    UNIQUE(workspace_id,connection_id,request_key),
    FOREIGN KEY(workspace_id,connection_id)
      REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE,
    CHECK((approved_by IS NULL AND approved_at IS NULL AND approval_expires_at IS NULL)
      OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND approval_expires_at IS NOT NULL)),
    CHECK((lease_id IS NULL AND lease_until IS NULL) OR (lease_id IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS pr_x_direct_due_idx ON public.pr_x_direct_operations(next_at,workspace_id)
    WHERE state IN ('queued','dispatching','accepted');
CREATE INDEX IF NOT EXISTS pr_x_direct_account_idx
    ON public.pr_x_direct_operations(workspace_id,connection_id,created_at DESC);
ALTER TABLE public.pr_x_direct_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_x_direct_operations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_x_direct_operations FROM public,anon,authenticated;
-- Explicit minimum Data API rights for the hosted X operation journal.
-- Revoke inherited grants too (existing projects may still auto-grant DELETE/TRUNCATE).
REVOKE ALL ON public.pr_x_direct_operations FROM service_role;
GRANT SELECT, INSERT, UPDATE ON public.pr_x_direct_operations TO service_role;
DO $policy$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public'
        AND tablename='pr_x_direct_operations' AND policyname='pr_x_direct_operations_runtime') THEN
        CREATE POLICY pr_x_direct_operations_runtime ON public.pr_x_direct_operations
            FOR ALL TO service_role USING(true) WITH CHECK(true);
    END IF;
END $policy$;
COMMIT;
