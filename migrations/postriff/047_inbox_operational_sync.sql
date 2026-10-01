-- Inbox v1: durable bounded refresh and a crash-visible reply dispatch fence.
create table if not exists public.pr_audience_sync (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  provider text not null,
  last_synced_at timestamptz,
  last_attempt_at timestamptz,
  cursor_state jsonb not null default '{}'::jsonb,
  last_result jsonb not null default '{}'::jsonb,
  last_error_code text,
  lease_id uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (workspace_id, connection_id),
  constraint pr_audience_sync_cursor_object check (jsonb_typeof(cursor_state) = 'object')
);
create index if not exists pr_audience_sync_due_idx
  on public.pr_audience_sync (last_attempt_at, workspace_id, connection_id);

alter table public.pr_audience_sync enable row level security;
alter table public.pr_audience_sync force row level security;
revoke all on public.pr_audience_sync from public, anon, authenticated;
grant select on public.pr_audience_sync to authenticated;
grant all on public.pr_audience_sync to service_role;
drop policy if exists tenant_read on public.pr_audience_sync;
create policy tenant_read on public.pr_audience_sync for select to authenticated
  using (postriff_private.member(workspace_id));
drop policy if exists trusted_write on public.pr_audience_sync;
create policy trusted_write on public.pr_audience_sync for all to service_role
  using (true) with check (true);

alter table public.pr_audience_threads add column if not exists permalink text;
alter table public.pr_reply_drafts add column if not exists dispatch_started_at timestamptz;
alter table public.pr_reply_drafts add column if not exists dispatch_id uuid;
alter table public.pr_reply_drafts drop constraint if exists pr_reply_drafts_status_check;
alter table public.pr_reply_drafts add constraint pr_reply_drafts_status_check
  check (status in ('draft','approved','submitting','submitted','verified','failed','uncertain','held','cancelled'));
create index if not exists pr_reply_drafts_claim_idx
  on public.pr_reply_drafts (status, created_at, id) where status in ('approved','submitting','submitted');
