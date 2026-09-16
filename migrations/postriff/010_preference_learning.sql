-- Preference learning (docs/postriff-preference-learning.md §6): what the person did, what the agent
-- proposes, and what they accepted. Additive; apply after 009. Service-role writes only; members read
-- their own workspace's rows. Events carry ids and numeric features, never draft text.
create table if not exists public.pr_learning_events (
  id uuid primary key default gen_random_uuid(),
  seq bigint generated always as identity,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  actor uuid,
  kind text not null check (kind in ('draft.edited','draft.update_accepted','draft.rejected','draft.approved','job.cancelled','post.published','chat.instruction','proposal.decided')),
  subject jsonb not null default '{}' check (jsonb_typeof(subject)='object'),
  scope jsonb not null default '{}' check (jsonb_typeof(scope)='object'),
  features jsonb not null default '{}' check (jsonb_typeof(features)='object'),
  voice_revision integer,
  style_revision integer not null default 0,
  consumed_by uuid,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '180 days'
);
create index if not exists pr_learning_events_recent on public.pr_learning_events (workspace_id, seq);
create index if not exists pr_learning_events_unconsumed on public.pr_learning_events (workspace_id) where consumed_by is null;

-- A proposal is one suggested change to the learned preferences; only a person decides it.
create table if not exists public.pr_memory_proposals (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  scope_key text not null,
  op text not null check (op in ('add','update','retire')),
  source text not null check (source in ('chat','deterministic','model','performance','legacy')),
  body jsonb not null check (jsonb_typeof(body)='object'),
  status text not null check (status in ('pending','remembered','edited','post_only','dismissed','expired')),
  decided_by uuid,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '30 days'
);
create index if not exists pr_memory_proposals_open on public.pr_memory_proposals (workspace_id, status, created_at desc);

-- An accepted preference. One current version per scope key; retiring sets valid_to.
create table if not exists public.pr_memory_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  scope_key text not null,
  body jsonb not null check (jsonb_typeof(body)='object'),
  status text not null check (status in ('active','paused','retired')),
  proposal_id uuid references public.pr_memory_proposals(id) on delete set null,
  confirmed_by uuid,
  valid_from timestamptz not null default now(),
  valid_to timestamptz
);
create unique index if not exists pr_memory_versions_one_current on public.pr_memory_versions (workspace_id, scope_key) where valid_to is null;

do $$
declare t text;
begin
  foreach t in array array['pr_learning_events','pr_memory_proposals','pr_memory_versions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='tenant_read') then
      execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    end if;
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='trusted_write') then
      execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;
