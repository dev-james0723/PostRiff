-- Server-only durable ceilings. No policy is enabled or spending authorized here.
-- Deliberately no workspace FK: OAuth already holds the workspace row lock.
CREATE TABLE IF NOT EXISTS public.pr_social_cost_reservations (
  id text PRIMARY KEY,
  workspace_id uuid NOT NULL,
  connection_id text NOT NULL,
  policy_hash text NOT NULL,
  endpoint text NOT NULL,
  ceiling_micros bigint NOT NULL CHECK (ceiling_micros > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pr_social_cost_reservations_policy ON public.pr_social_cost_reservations(policy_hash,workspace_id);
ALTER TABLE public.pr_social_cost_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_social_cost_reservations FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.pr_social_cost_reservations TO service_role;
