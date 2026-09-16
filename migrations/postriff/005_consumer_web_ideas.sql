-- Additive Ideas/agent persistence: conversations, messages, attachments, runs, safe events,
-- and global skill/tool release catalogs. Apply after 004. Service_role writes only.
begin;

create table public.pr_conversations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  created_by uuid not null,
  title text not null default '' check (length(title) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);
create index on public.pr_conversations (workspace_id, updated_at desc);

create table public.pr_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  seq integer not null check (seq >= 1),
  role text not null check (role in ('user','assistant','system')),
  body jsonb not null check (jsonb_typeof(body)='object'),
  run_id uuid,
  created_at timestamptz not null default now(),
  unique (conversation_id, seq)
);
create index on public.pr_messages (workspace_id, conversation_id, seq);

create table public.pr_attachments (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  kind text not null check (kind in ('source','asset','link')),
  ref jsonb not null check (jsonb_typeof(ref)='object'),
  created_by uuid not null,
  created_at timestamptz not null default now()
);
create index on public.pr_attachments (workspace_id, conversation_id);

create table public.pr_agent_runs (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  actor uuid not null,
  status text not null check (status in ('running','completed','failed','cancelled','applied')),
  model text not null,
  reasoning text not null check (reasoning in ('quick','standard','deep')),
  context_digest text not null check (length(context_digest)=64),
  policy_epoch text not null check (length(policy_epoch)=64),
  idempotency_key text not null,
  artifact jsonb,
  artifact_hash text,
  usage jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);
create index on public.pr_agent_runs (workspace_id, conversation_id, created_at desc);

create table public.pr_agent_events (
  run_id uuid not null references public.pr_agent_runs(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  seq integer not null check (seq >= 1),
  kind text not null check (kind in ('run.started','progress.updated','source.added','artifact.created','message.delta','message.completed','warning.created','action.proposed','run.completed','run.failed','run.cancelled')),
  body jsonb not null default '{}' check (jsonb_typeof(body)='object'),
  at timestamptz not null default now(),
  primary key (run_id, seq)
);

-- Global, reviewed catalogs: no customer content, readable by any signed-in member.
create table public.pr_skill_releases (
  id text not null, version text not null, sha256 text not null check (length(sha256)=64),
  state text not null check (state in ('released','deprecated')), released_at timestamptz not null default now(),
  primary key (id, version)
);
create table public.pr_tool_releases (
  id text not null, version text not null, sha256 text not null check (length(sha256)=64),
  effect_class text not null check (effect_class in ('read','creative_write','workspace_mutation','paid_generation')),
  cost_class text not null check (cost_class in ('none','metered','paid')),
  state text not null check (state in ('released','deprecated')), released_at timestamptz not null default now(),
  primary key (id, version)
);

do $$
declare t text;
begin
  foreach t in array array['pr_conversations','pr_messages','pr_attachments','pr_agent_runs','pr_agent_events'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  foreach t in array array['pr_skill_releases','pr_tool_releases'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('create policy catalog_read on public.%I for select to authenticated using (true)', t);
    execute format('create policy catalog_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
end $$;

commit;
