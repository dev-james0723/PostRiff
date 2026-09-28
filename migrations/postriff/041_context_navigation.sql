-- Rafii Context Navigation. Apply after 036; additive indexes and workspace-scoped moments.
-- Trigram search keeps substring matches useful for Traditional Chinese and partial titles.
create extension if not exists pg_trgm;

-- Keep the checked-in migration compatible with the repository transaction runner. Production may prebuild these indexes with a reviewed one-off runner before the application release.
create index if not exists pr_conversations_navigation
  on public.pr_conversations (workspace_id, updated_at desc, id desc);
create index if not exists pr_conversations_title_search
  on public.pr_conversations using gin (title gin_trgm_ops);
create index if not exists pr_messages_text_search
  on public.pr_messages using gin ((body->>'text') gin_trgm_ops);

begin;
create table if not exists public.pr_media_moments (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  conversation_id uuid not null references public.pr_conversations(id) on delete cascade,
  created_by uuid not null,
  after_seq integer not null check (after_seq >= 0),
  source text not null check (source = 'rafii_asset'),
  title text not null check (length(title) between 1 and 200),
  asset_id uuid not null,
  seconds double precision not null check (seconds >= 0 and seconds < 86400 and seconds != 'Infinity'::float8),
  timestamp_label text not null check (length(timestamp_label) <= 12),
  created_at timestamptz not null default now()
);
create index if not exists pr_media_moments_thread
  on public.pr_media_moments (workspace_id, conversation_id, after_seq, created_at);
alter table public.pr_media_moments enable row level security;
alter table public.pr_media_moments force row level security;
revoke all on public.pr_media_moments from public, anon, authenticated;
grant select on public.pr_media_moments to authenticated;
grant all on public.pr_media_moments to service_role;
create policy tenant_read on public.pr_media_moments for select to authenticated
  using (postriff_private.member(workspace_id));
create policy trusted_write on public.pr_media_moments for all to service_role
  using (true) with check (true);

commit;
