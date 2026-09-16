-- Additive channel integration persistence: OAuth transactions, encrypted credential custody,
-- and per-capability level records. Apply after 005. Tokens are never browser-readable.
begin;

-- One row per OAuth start. State is stored hashed; PKCE verifier is encrypted at rest.
create table public.pr_oauth_transactions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null,
  provider text not null check (length(provider) between 2 and 40),
  capability text not null check (capability in ('identity','publish','schedule','analytics','comments_read','reply','moderate')),
  redirect_uri text not null check (redirect_uri like 'https://%'),
  scopes text[] not null,
  state_hash text not null unique check (length(state_hash)=64),
  verifier_ciphertext text not null,
  key_id text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  outcome text check (outcome in ('exchanged','denied','expired','mismatch')),
  check (expires_at > created_at)
);
create index on public.pr_oauth_transactions (workspace_id, created_at desc);

-- Encrypted provider tokens bound to a workspace + connection. Application-layer encryption;
-- the key lives in server secrets (POSTRIFF_CREDENTIAL_KEY), never in this table.
create table public.pr_encrypted_credentials (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (length(connection_id) between 8 and 80),
  provider text not null,
  provider_account_id text not null,
  access_ciphertext text not null,
  refresh_ciphertext text,
  key_id text not null,
  scopes text[] not null,
  access_expires_at timestamptz,
  refresh_supported boolean not null default false,
  revoked_at timestamptz,
  rotated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, connection_id)
);

-- Capability levels per connection: Direct / Assisted / Bridge / Unsupported, each with evidence.
create table public.pr_channel_capabilities (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  capability text not null check (capability in ('identity','publish','schedule','analytics','comments_read','reply','moderate','media_types','webhooks')),
  level text not null check (level in ('Direct','Assisted','Bridge','Unsupported')),
  evidence text not null default '' check (length(evidence) <= 400),
  capability_version integer not null default 0,
  verified_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, connection_id, capability)
);

do $$
declare t text;
begin
  foreach t in array array['pr_oauth_transactions','pr_encrypted_credentials'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  alter table public.pr_channel_capabilities enable row level security;
  alter table public.pr_channel_capabilities force row level security;
  revoke all on public.pr_channel_capabilities from public, anon, authenticated;
  grant select on public.pr_channel_capabilities to authenticated;
  grant all on public.pr_channel_capabilities to service_role;
  create policy tenant_read on public.pr_channel_capabilities for select to authenticated using (postriff_private.member(workspace_id));
  create policy trusted_write on public.pr_channel_capabilities for all to service_role using (true) with check (true);
end $$;

commit;
