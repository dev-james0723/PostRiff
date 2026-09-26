-- Per-user, read-only productivity connectors for explicit Agent Chat picks.
-- Rollback is both RAFII_NOTION_CONNECTOR_ENABLED / RAFII_GMAIL_CONNECTOR_ENABLED off.
-- Tokens and cached excerpts are server-only and cascade with the workspace.
begin;

create table if not exists public.pr_connector_oauth_transactions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  provider text not null check (provider in ('notion','gmail')),
  redirect_uri text not null check (redirect_uri like 'https://%'),
  scopes text[] not null default '{}',
  state_hash text not null unique check (length(state_hash)=64),
  verifier_ciphertext text not null,
  key_id text not null,
  expires_at timestamptz not null,
  consumed_at timestamptz,
  outcome text check (outcome in ('exchanged','denied','expired','mismatch')),
  created_at timestamptz not null default now()
);
create index if not exists pr_connector_oauth_member on public.pr_connector_oauth_transactions(workspace_id,member_id,created_at desc);

create table if not exists public.pr_connector_credentials (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (connection_id ~ '^pc_[0-9a-f]{32}$'),
  member_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  provider text not null check (provider in ('notion','gmail')),
  provider_account_id text not null,
  account_label text not null check (length(account_label)<=160),
  access_ciphertext text not null,
  refresh_ciphertext text,
  key_id text not null,
  scopes text[] not null default '{}',
  access_expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key(workspace_id,connection_id),
  unique(workspace_id,member_id,provider,provider_account_id)
);
create index if not exists pr_connector_credentials_member on public.pr_connector_credentials(workspace_id,member_id,provider) where revoked_at is null;

-- A short-lived opaque picker receipt. The turn always re-fetches remote content by item_id.
create table if not exists public.pr_connector_selections (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  reference_id text not null check (reference_id ~ '^ci_[0-9a-f]{32}$'),
  connection_id text not null,
  provider text not null check (provider in ('notion','gmail')),
  item_id text not null check (length(item_id) between 1 and 300),
  title text not null check (length(title)<=300),
  content_digest text check (content_digest is null or length(content_digest)=64),
  excerpt text check (excerpt is null or length(excerpt)<=12000),
  expires_at timestamptz not null,
  fetched_at timestamptz,
  created_at timestamptz not null default now(),
  primary key(workspace_id,member_id,reference_id),
  foreign key(workspace_id,connection_id) references public.pr_connector_credentials(workspace_id,connection_id) on delete cascade
);
create index if not exists pr_connector_selections_connection on public.pr_connector_selections(workspace_id,connection_id);

-- Metering/audit binds exact opaque item ids to the already request-bound turn digest.
create table if not exists public.pr_connector_fetches (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  request_digest text not null check (length(request_digest)=64),
  reference_ids text[] not null,
  providers text[] not null check (providers <@ array['notion','gmail']::text[]),
  fetched_count integer not null check (fetched_count between 0 and 12 and fetched_count<=cardinality(reference_ids)),
  created_at timestamptz not null default now()
);
create index if not exists pr_connector_fetches_member on public.pr_connector_fetches(workspace_id,member_id,created_at desc);

do $$ declare t text;
begin
  foreach t in array array['pr_connector_oauth_transactions','pr_connector_credentials','pr_connector_selections','pr_connector_fetches'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',t);
    end if;
  end loop;
end $$;
commit;
