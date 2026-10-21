-- Additive candidate only. Not applied to any hosted database in this task.
BEGIN;
ALTER TABLE public.pr_discord_request_admissions DROP CONSTRAINT pr_discord_request_admissions_credential_kind_check;
ALTER TABLE public.pr_discord_request_admissions ADD CONSTRAINT pr_discord_request_admissions_credential_kind_check CHECK (credential_kind IN ('bot','user','oauth','webhook'));
CREATE TABLE public.pr_discord_interaction_replays (
    application_id text NOT NULL CHECK (application_id ~ '^[0-9]{5,25}$'),
    interaction_id text NOT NULL CHECK (interaction_id ~ '^[0-9]{5,25}$'),
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (application_id,interaction_id)
);
-- No body, token, command arguments, draft content or user data in replay rows.
-- IDs retained: expiry of timestamp window alone cannot replay a re-signed ID.
CREATE TABLE public.pr_discord_interaction_links (
    workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
    member_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    application_id text NOT NULL CHECK (application_id ~ '^[0-9]{5,25}$'),
    discord_user_id text NOT NULL CHECK (discord_user_id ~ '^[0-9]{5,25}$'),
    identity_connection_id text NOT NULL,
    identity_generation uuid NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (workspace_id,member_id,application_id,discord_user_id),
    FOREIGN KEY (workspace_id,identity_connection_id) REFERENCES public.pr_encrypted_credentials(workspace_id,connection_id) ON DELETE CASCADE
);
CREATE INDEX pr_discord_interaction_subject ON public.pr_discord_interaction_links(application_id,discord_user_id) WHERE revoked_at IS NULL;
ALTER TABLE public.pr_discord_interaction_replays ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_interaction_replays FORCE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_interaction_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_interaction_links FORCE ROW LEVEL SECURITY;
-- Remove inherited Supabase defaults before granting the exact runtime rights.
REVOKE ALL ON public.pr_discord_interaction_replays, public.pr_discord_interaction_links FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT,INSERT ON public.pr_discord_interaction_replays TO service_role;
GRANT SELECT,INSERT,UPDATE ON public.pr_discord_interaction_links TO service_role;
CREATE POLICY pr_discord_interaction_replay_service ON public.pr_discord_interaction_replays FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY pr_discord_interaction_link_service ON public.pr_discord_interaction_links FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMIT;
