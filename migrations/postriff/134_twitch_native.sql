-- Candidate only. Never apply to Production without the reviewed release packet.
-- Twitch native actions share Rafii's credentials, membership locks and audit log.
BEGIN;

CREATE TABLE IF NOT EXISTS public.pr_twitch_actions (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  actor uuid NOT NULL,
  action text NOT NULL,
  generation text NOT NULL,
  payload jsonb NOT NULL,
  manifest jsonb NOT NULL,
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[a-f0-9]{64}$'),
  state text NOT NULL CHECK (state IN ('draft','approved','paused','cancelled','dispatching','succeeded','accepted','partial','failed','outcome_unknown','expired','revoked')),
  execute_at timestamptz NOT NULL,
  approval_deadline timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  approved_at timestamptz,
  approved_by uuid,
  agent_origin boolean NOT NULL DEFAULT false,
  permission_token text,
  lease_id uuid,
  dispatched_at timestamptz,
  completed_at timestamptz,
  result jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(workspace_id,connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE,
  CHECK (expires_at > execute_at),
  CHECK (approved_at IS NULL OR approved_by = actor),
  UNIQUE(id,workspace_id,connection_id,generation)
);
CREATE INDEX IF NOT EXISTS pr_twitch_actions_due ON public.pr_twitch_actions(execute_at,id) WHERE state='approved';
CREATE INDEX IF NOT EXISTS pr_twitch_actions_member ON public.pr_twitch_actions(workspace_id,connection_id,created_at DESC);

CREATE TABLE IF NOT EXISTS public.pr_twitch_subscriptions (
  id uuid PRIMARY KEY,
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  generation text NOT NULL,
  action_id uuid,
  provider_subscription_id text UNIQUE,
  type text NOT NULL,
  version text NOT NULL,
  condition jsonb NOT NULL,
  state text NOT NULL CHECK (state IN ('pending','enabled','revoked','inactive','outcome_unknown','cleanup_pending')),
  secret_ciphertext text NOT NULL,
  secret_key_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(workspace_id,connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE,
  FOREIGN KEY(action_id,workspace_id,connection_id,generation) REFERENCES public.pr_twitch_actions(id,workspace_id,connection_id,generation),
  UNIQUE(workspace_id,connection_id,generation,type,version),
  UNIQUE(id,workspace_id,connection_id,generation)
);

CREATE TABLE IF NOT EXISTS public.pr_twitch_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  subscription_id uuid NOT NULL,
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  generation text NOT NULL,
  message_id text NOT NULL,
  type text NOT NULL,
  message_kind text NOT NULL,
  payload_ciphertext text NOT NULL,
  payload_key_id text NOT NULL,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','processed','discarded')),
  received_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',
  processed_at timestamptz,
  UNIQUE(subscription_id,message_id),
  -- Trust comes from the registered subscription, including its tenant and
  -- generation. This avoids waiting on an OAuth credential lock during a signed
  -- challenge while Create Subscription is itself in flight.
  FOREIGN KEY(subscription_id,workspace_id,connection_id,generation)
    REFERENCES public.pr_twitch_subscriptions(id,workspace_id,connection_id,generation) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS pr_twitch_events_due ON public.pr_twitch_events(id) WHERE state='queued';
CREATE INDEX IF NOT EXISTS pr_twitch_events_inbox ON public.pr_twitch_events(workspace_id,connection_id,id DESC);

CREATE TABLE IF NOT EXISTS public.pr_twitch_context (
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  generation text NOT NULL,
  account_type text NOT NULL DEFAULT '',
  is_live boolean NOT NULL DEFAULT false,
  observed_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes',
  PRIMARY KEY(workspace_id,connection_id),
  FOREIGN KEY(workspace_id,connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.pr_twitch_maintenance (
  name text PRIMARY KEY CHECK(name='validation'),
  cursor jsonb,
  lease_id uuid,
  lease_until timestamptz,
  completed_at timestamptz
);

-- Browser/PostgREST clients have zero table access, including their own workspace.
-- Service-role queries must bind BOTH workspace and connection; HTTP authenticates
-- through PostgresWorkspaceRepository and dispatch rechecks current membership.
DO $policy$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['pr_twitch_actions','pr_twitch_subscriptions','pr_twitch_events','pr_twitch_context','pr_twitch_maintenance'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM public, anon, authenticated', t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=t AND policyname=t||'_runtime') THEN
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)', t||'_runtime',t);
    END IF;
  END LOOP;
END $policy$;
GRANT USAGE, SELECT ON SEQUENCE public.pr_twitch_events_id_seq TO service_role;
COMMIT;
