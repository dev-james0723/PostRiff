-- Official OIDC identity linking is separate from Telegram Bot API grants.
begin;
create table public.pr_telegram_identity_owners (
  bot_id text not null, subject text not null, member_id uuid not null,
  primary key(bot_id,subject)
);
create table public.pr_telegram_identities (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null, bot_id text not null, subject text not null,
  telegram_user_id bigint not null, identity jsonb not null,
  linked_at timestamptz not null default now(), revoked_at timestamptz,
  unique(workspace_id,member_id,bot_id,subject)
);
create table public.pr_telegram_automation_controls (
  workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
  paused boolean not null default true,
  approval_policy text not null default 'always' check(approval_policy in ('always','scoped_auto')),
  allowed_connections text[] not null default '{}',
  allowed_actions text[] not null default '{}',
  retention_days integer not null default 7 check(retention_days between 1 and 90),
  revision bigint not null default 1,
  updated_by uuid not null, updated_at timestamptz not null default now()
);
create table public.pr_telegram_managed_requests (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  member_id uuid not null, manager_bot_id bigint not null, owner_user_id bigint not null,
  username text not null, name text not null, expires_at timestamptz not null, completed_at timestamptz,
  primary key(manager_bot_id,owner_user_id,username)
);
create table public.pr_telegram_managed_bots (
  manager_bot_id bigint not null, bot_id bigint not null, owner_user_id bigint not null,
  username text not null, last_update_id bigint not null,
  primary key(manager_bot_id,bot_id)
);
do $$ declare t text; begin
  foreach t in array array['pr_telegram_identity_owners','pr_telegram_identities','pr_telegram_automation_controls','pr_telegram_managed_requests','pr_telegram_managed_bots'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('revoke all on public.%I from public, anon, authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',t);
  end loop;
end $$;
commit;
