-- RAFII Product Growth G2-REL (PRD R-REL-01/02): a light relationship layer over the existing Inbox.
-- Additive and idempotent. Relationship records are workspace-owned, reference only threads the same workspace already
-- ingested (composite foreign keys), and keep an append-only, content-free history of every change. Nothing here can
-- contact anyone: replies stay on the existing exact-approval Inbox path.
begin;

-- Composite (workspace_id, id) key on the referenced Inbox thread table, so a link can never point at another
-- workspace's thread. Skipped when an equivalent unique index already exists.
do $$
begin
  if not exists (
    select 1 from pg_index i
    where i.indrelid = 'public.pr_audience_threads'::regclass and i.indisunique and i.indpred is null and i.indexprs is null and i.indnatts = 2
      and (select array_agg(a.attname::text order by a.attname) from pg_attribute a
           where a.attrelid = i.indrelid and a.attnum = any(i.indkey::int2[])) = array['id','workspace_id']::text[]
  ) then
    alter table public.pr_audience_threads add constraint pr_audience_threads_workspace_id_id_key unique (workspace_id, id);
  end if;
end $$;

create table if not exists public.pr_relationships (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 1 and 120),
  -- Optional opaque reference, scoped to one provider (+ the connected account it was seen through). Never matched
  -- across providers and never used for profiling.
  contact_provider text check (contact_provider is null or contact_provider ~ '^[a-z][a-z0-9_]{0,39}$'),
  contact_account text check (contact_account is null or char_length(contact_account) between 1 and 200),
  contact_ref text check (contact_ref is null or char_length(contact_ref) between 1 and 200),
  interest text check (interest is null or char_length(interest) <= 300),
  state text not null default 'new' check (state in ('new','replied','waiting','follow_up_due','won','closed')),
  previous_state text check (previous_state is null or previous_state in ('new','replied','waiting','follow_up_due')),  -- restored by reopen
  state_changed_at timestamptz not null default now(),
  owner_id uuid,
  next_action text check (next_action is null or char_length(next_action) <= 200),
  due_at timestamptz,
  due_time_zone text check (due_time_zone is null or (char_length(due_time_zone) <= 64 and due_time_zone ~ '^[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}$')),
  due_fold smallint not null default 0 check (due_fold in (0, 1)),
  due_revision integer not null default 0 check (due_revision >= 0),
  snoozed_until timestamptz,
  followup_dismissed_key text check (followup_dismissed_key is null or char_length(followup_dismissed_key) <= 80),
  notified_key text check (notified_key is null or char_length(notified_key) <= 80),
  suggestion_dismissed_key text check (suggestion_dismissed_key is null or char_length(suggestion_dismissed_key) <= 200),
  notes jsonb not null default '[]'::jsonb check (case when jsonb_typeof(notes) = 'array' then jsonb_array_length(notes) <= 20 else false end),
  won_result_id uuid,
  won_provenance text check (won_provenance is null or won_provenance in ('provider_native','first_party_reported','user_declared')),
  revision integer not null default 1 check (revision >= 1),
  idempotency_key text check (idempotency_key is null or char_length(idempotency_key) between 8 and 80),
  request_digest text check (request_digest is null or char_length(request_digest) = 64),
  last_request_key text check (last_request_key is null or char_length(last_request_key) between 8 and 80),
  last_request_digest text check (last_request_digest is null or char_length(last_request_digest) = 64),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint pr_relationships_workspace_id_id_key unique (workspace_id, id),
  constraint pr_relationships_idempotency_key unique (workspace_id, idempotency_key),
  constraint pr_relationships_contact_scope check (contact_ref is null or contact_provider is not null),
  constraint pr_relationships_due_zone check ((due_at is null) = (due_time_zone is null)),
  constraint pr_relationships_won_result check ((state = 'won') = (won_result_id is not null))
);
create index if not exists pr_relationships_list_idx on public.pr_relationships (workspace_id, due_at, created_at desc, id desc);
create index if not exists pr_relationships_owner_idx on public.pr_relationships (workspace_id, owner_id);
create index if not exists pr_relationships_due_idx on public.pr_relationships (due_at, workspace_id)
  where due_at is not null and state not in ('won','closed');

create table if not exists public.pr_relationship_threads (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  relationship_id uuid not null,
  thread_id uuid not null,
  linked_by uuid,
  linked_at timestamptz not null default now(),
  primary key (workspace_id, relationship_id, thread_id),
  constraint pr_relationship_threads_relationship_fk foreign key (workspace_id, relationship_id)
    references public.pr_relationships(workspace_id, id) on delete cascade,
  constraint pr_relationship_threads_thread_fk foreign key (workspace_id, thread_id)
    references public.pr_audience_threads(workspace_id, id) on delete cascade
);
create index if not exists pr_relationship_threads_thread_idx on public.pr_relationship_threads (workspace_id, thread_id);

-- Append-only and content-free: ids, enums and instants only (never names, notes, interests or message text).
create table if not exists public.pr_relationship_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  relationship_id uuid not null,
  kind text not null check (kind in ('created','updated','state','snoozed','unsnoozed','closed','reopened','assigned',
                                     'thread_linked','thread_unlinked','note_added','note_removed','due_changed',
                                     'followup_dismissed','followup_restored','suggestion_dismissed')),
  from_state text check (from_state is null or from_state in ('new','replied','waiting','follow_up_due','won','closed')),
  to_state text check (to_state is null or to_state in ('new','replied','waiting','follow_up_due','won','closed')),
  actor uuid,   -- null: a system/worker actor, never a forged person
  meta jsonb not null default '{}'::jsonb check (jsonb_typeof(meta) = 'object'),
  occurred_at timestamptz not null default now(),
  constraint pr_relationship_events_relationship_fk foreign key (workspace_id, relationship_id)
    references public.pr_relationships(workspace_id, id) on delete cascade
);
create index if not exists pr_relationship_events_workspace_idx on public.pr_relationship_events (workspace_id, occurred_at, id);
create index if not exists pr_relationship_events_relationship_idx
  on public.pr_relationship_events (workspace_id, relationship_id, occurred_at desc, id desc);

-- History is immutable for every role, the table owner included (grants alone don't bind the owner): no row is ever
-- updated, deleted on its own or truncated. Deleting the follow-up or the workspace it belongs to still removes its
-- history through the foreign-key cascade: by the time the cascade reaches a row, its parent is already gone.
create or replace function postriff_private.pr_relationship_events_immutable() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    if not exists (select 1 from public.pr_relationships r where r.workspace_id = old.workspace_id and r.id = old.relationship_id)
       or not exists (select 1 from public.pr_workspaces w where w.id = old.workspace_id) then
      return old;
    end if;
  end if;
  raise exception 'pr_relationship_events is append-only history' using errcode = '42501';
end $$;
revoke all on function postriff_private.pr_relationship_events_immutable() from public, anon, authenticated;
create or replace trigger pr_relationship_events_immutable before update or delete on public.pr_relationship_events
  for each row execute function postriff_private.pr_relationship_events_immutable();
create or replace trigger pr_relationship_events_no_truncate before truncate on public.pr_relationship_events
  for each statement execute function postriff_private.pr_relationship_events_immutable();

do $$
declare t text;
begin
  foreach t in array array['pr_relationships','pr_relationship_threads'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    execute format('drop policy if exists tenant_read on public.%I', t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))', t);
    execute format('drop policy if exists trusted_write on public.%I', t);
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)', t);
  end loop;
  alter table public.pr_relationship_events enable row level security;
  alter table public.pr_relationship_events force row level security;
  revoke all on public.pr_relationship_events from public, anon, authenticated, service_role;
  grant select on public.pr_relationship_events to authenticated;
  -- No update/delete grant exists for any role, and the trigger above refuses them even for the owner: history rows are
  -- immutable (deleting the follow-up or the workspace cascades).
  grant select, insert on public.pr_relationship_events to service_role;
  drop policy if exists tenant_read on public.pr_relationship_events;
  create policy tenant_read on public.pr_relationship_events for select to authenticated using (postriff_private.member(workspace_id));
  drop policy if exists service_insert on public.pr_relationship_events;
  create policy service_insert on public.pr_relationship_events for insert to service_role with check (true);
  drop policy if exists service_read on public.pr_relationship_events;
  create policy service_read on public.pr_relationship_events for select to service_role using (true);
end $$;

-- "Won" points at a declared business result (migration 080, results slice) in the same workspace. Added only when that
-- table exists with uuid keys; re-applying this file after 080 adds it. Until then the service refuses "won".
do $$
declare results regclass := to_regclass('public.pr_result_events');
begin
  if results is null then
    return;
  end if;
  if (select count(*) from pg_attribute where attrelid = results and attname in ('id', 'workspace_id') and atttypid = 'uuid'::regtype and not attisdropped) <> 2 then
    return;
  end if;
  if not exists (
    select 1 from pg_index i
    where i.indrelid = results and i.indisunique and i.indpred is null and i.indexprs is null and i.indnatts = 2
      and (select array_agg(a.attname::text order by a.attname) from pg_attribute a
           where a.attrelid = i.indrelid and a.attnum = any(i.indkey::int2[])) = array['id','workspace_id']::text[]
  ) then
    alter table public.pr_result_events add constraint pr_result_events_workspace_id_id_key unique (workspace_id, id);
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.pr_relationships'::regclass and conname = 'pr_relationships_won_result_fk') then
    alter table public.pr_relationships add constraint pr_relationships_won_result_fk foreign key (workspace_id, won_result_id)
      references public.pr_result_events(workspace_id, id);
  end if;
end $$;

commit;
