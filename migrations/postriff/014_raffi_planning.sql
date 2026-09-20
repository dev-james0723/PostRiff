-- Raffi campaigns, recurring draft preparation and contextual suggestions.
-- Additive and tenant-scoped. Existing workspace JSON remains readable by older workers;
-- rollout can be disabled without destructive down-migration.
begin;

create table if not exists public.pr_campaigns (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  version bigint not null default 1 check (version > 0),
  status text not null check (status in ('needs_input','draft','active','completed','cancelled')),
  body jsonb not null,
  created_by uuid not null references public.pr_profiles(user_id),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (workspace_id, id)
);
create table if not exists public.pr_recurring_tasks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  campaign_id uuid not null,
  version bigint not null default 1 check (version > 0),
  status text not null check (status in ('draft','active','paused','cancelled')),
  body jsonb not null, next_at timestamptz,
  created_by uuid not null references public.pr_profiles(user_id),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  foreign key (workspace_id,campaign_id) references public.pr_campaigns(workspace_id,id),
  unique (workspace_id,id)
);
create table if not exists public.pr_recurring_occurrences (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  task_id uuid not null, task_version bigint not null, scheduled_for timestamptz not null,
  state text not null check (state in ('pending','running','completed','failed','held','missed','cancelled')),
  idempotency_key text not null check (idempotency_key ~ '^[0-9a-f]{64}$'), body jsonb not null default '{}',
  created_at timestamptz not null default now(),
  foreign key (workspace_id,task_id) references public.pr_recurring_tasks(workspace_id,id),
  unique(workspace_id,idempotency_key), unique(workspace_id,task_id,task_version,scheduled_for)
);
create table if not exists public.pr_suggestions (
  id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  identity text not null check (identity ~ '^[0-9a-f]{64}$'), status text not null check(status in ('open','snoozed','dismissed','accepted','stale')),
  body jsonb not null, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique(workspace_id,identity)
);

create index if not exists pr_recurring_due on public.pr_recurring_tasks(status,next_at) where status='active';
create index if not exists pr_suggestions_open on public.pr_suggestions(workspace_id,status);

do $$
declare table_name text;
begin
  foreach table_name in array array['pr_campaigns','pr_recurring_tasks','pr_recurring_occurrences','pr_suggestions'] loop
    execute format('alter table public.%I enable row level security',table_name);
    execute format('alter table public.%I force row level security',table_name);
    execute format('revoke all on public.%I from public,anon,authenticated',table_name);
    execute format('grant select on public.%I to authenticated',table_name);
    execute format('grant all on public.%I to service_role',table_name);
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=table_name and policyname='tenant_read') then
      execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))',table_name);
    end if;
    if not exists(select 1 from pg_policies where schemaname='public' and tablename=table_name and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)',table_name);
    end if;
  end loop;
end $$;
commit;
