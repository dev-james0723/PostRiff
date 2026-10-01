-- 083 · Publish-ready Visual Pack (RAFII Product Growth v2, PRD R-VIS-01..03, plan G3-VIS).
-- One editable six-slide 1080×1350 carousel per pack. Revisions are append-only: an edit is a new revision, and the
-- revision it replaces becomes `superseded` (its acceptance and exports stop being valid); content, render manifest,
-- approval and export digests never change once written. Facts (export_ready, downloaded, user_confirmed_used, …)
-- are recorded once per revision in pr_visual_pack_events. Rendered PNGs live in private storage under
-- {workspace}/visual-pack/; the rows only reference them. Additive and idempotent; no data is rewritten.
begin;

create table if not exists public.pr_visual_packs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  format text not null default 'carousel_6_1080x1350' check (format = 'carousel_6_1080x1350'),
  source_variant_id text check (source_variant_id is null or source_variant_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  source_campaign_id text check (source_campaign_id is null or source_campaign_id ~ '^[A-Za-z0-9_-]{1,80}$'),
  status text not null default 'active' check (status in ('active','archived')),
  current_revision integer not null default 1 check (current_revision >= 1),
  settings jsonb not null default '{}'::jsonb check (jsonb_typeof(settings) = 'object'),
  language text not null default 'und' check (length(language) between 2 and 35),
  idempotency_key text not null check (length(idempotency_key) between 8 and 80),
  request_digest text not null check (request_digest ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, id),
  unique (workspace_id, idempotency_key)
);
create index if not exists pr_visual_packs_list_idx on public.pr_visual_packs (workspace_id, created_at desc, id desc);
create index if not exists pr_visual_packs_variant_idx on public.pr_visual_packs (workspace_id, source_variant_id) where source_variant_id is not null;

create table if not exists public.pr_visual_pack_revisions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  pack_id uuid not null,
  revision_no integer not null check (revision_no >= 1),
  slides jsonb not null check (jsonb_typeof(slides) = 'array' and jsonb_array_length(slides) = 6),
  caption text not null default '' check (length(caption) <= 5000),
  settings jsonb not null check (jsonb_typeof(settings) = 'object'),
  source jsonb not null default '{}'::jsonb check (jsonb_typeof(source) = 'object'),
  content_digest text not null check (content_digest ~ '^[0-9a-f]{64}$'),
  checks jsonb not null default '{}'::jsonb check (jsonb_typeof(checks) = 'object'),
  state text not null default 'draft'
    check (state in ('draft','rendered','accepted','export_ready','downloaded','user_confirmed_used','queued','superseded')),
  render_manifest jsonb check (render_manifest is null or jsonb_typeof(render_manifest) = 'object'),
  render_digest text check (render_digest is null or render_digest ~ '^[0-9a-f]{64}$'),
  rendered_at timestamptz,
  approval_digest text check (approval_digest is null or approval_digest ~ '^[0-9a-f]{64}$'),
  accepted_by uuid,
  accepted_at timestamptz,
  export_digest text check (export_digest is null or export_digest ~ '^[0-9a-f]{64}$'),
  export_sha256 text check (export_sha256 is null or export_sha256 ~ '^[0-9a-f]{64}$'),
  export_bytes integer check (export_bytes is null or export_bytes > 0),
  export_ready_at timestamptz,
  exported_by uuid,
  downloaded_at timestamptz,
  download_count integer not null default 0 check (download_count >= 0),
  confirmed_used_at timestamptz,
  confirmed_by uuid,
  queued_at timestamptz,
  superseded_at timestamptz,
  purged_at timestamptz,
  purge_reason text check (purge_reason is null or purge_reason in ('source_image_deleted','pack_deleted')),
  edit_key text check (edit_key is null or length(edit_key) between 8 and 80),
  edit_digest text check (edit_digest is null or edit_digest ~ '^[0-9a-f]{64}$'),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, id),
  unique (workspace_id, pack_id, revision_no),
  unique (workspace_id, pack_id, edit_key),
  foreign key (workspace_id, pack_id) references public.pr_visual_packs (workspace_id, id) on delete cascade,
  constraint pr_visual_pack_revisions_render_pair check ((render_manifest is null) = (render_digest is null)),
  constraint pr_visual_pack_revisions_render_before_accept check (approval_digest is null or render_digest is not null),
  constraint pr_visual_pack_revisions_accept_before_export check (export_digest is null or approval_digest is not null),
  constraint pr_visual_pack_revisions_export_before_download check (downloaded_at is null or export_digest is not null),
  constraint pr_visual_pack_revisions_download_before_used check (confirmed_used_at is null or downloaded_at is not null),
  constraint pr_visual_pack_revisions_state_facts check (
    (state = 'draft' and render_digest is null)
    or (state = 'rendered' and render_digest is not null and approval_digest is null)
    or (state = 'accepted' and approval_digest is not null and export_digest is null)
    or (state = 'export_ready' and export_digest is not null and downloaded_at is null)
    or (state = 'downloaded' and downloaded_at is not null and confirmed_used_at is null)
    or (state = 'user_confirmed_used' and confirmed_used_at is not null)
    or (state = 'queued' and queued_at is not null and approval_digest is not null)
    or (state = 'superseded' and superseded_at is not null))
);
create index if not exists pr_visual_pack_revisions_pack_idx on public.pr_visual_pack_revisions (workspace_id, pack_id, revision_no desc);

-- A pack's current revision always exists (checked at commit, so a pack and its first revision insert together).
do $$ begin
  if not exists (select 1 from pg_constraint where conrelid = 'public.pr_visual_packs'::regclass
                 and conname = 'pr_visual_packs_current_revision_fkey') then
    alter table public.pr_visual_packs add constraint pr_visual_packs_current_revision_fkey
      foreign key (workspace_id, id, current_revision)
      references public.pr_visual_pack_revisions (workspace_id, pack_id, revision_no)
      deferrable initially deferred;
  end if;
end $$;

-- Facts, once per revision and kind; repeated downloads only count on the revision.
create table if not exists public.pr_visual_pack_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  pack_id uuid not null,
  revision_no integer not null,
  kind text not null check (kind in ('prepared','edited','rendered','accepted','export_ready','downloaded','user_confirmed_used',
                                      'queued','verified_published','superseded','purged')),
  actor uuid,
  occurred_at timestamptz not null default now(),
  meta jsonb not null default '{}'::jsonb check (jsonb_typeof(meta) = 'object'),
  unique (workspace_id, pack_id, revision_no, kind),
  foreign key (workspace_id, pack_id, revision_no)
    references public.pr_visual_pack_revisions (workspace_id, pack_id, revision_no) on delete cascade
);
create index if not exists pr_visual_pack_events_period_idx on public.pr_visual_pack_events (workspace_id, occurred_at, id);

-- Append-only content: what a revision says, shows and was approved/exported as never changes after it is written.
create or replace function postriff_private.pr_visual_pack_revision_guard() returns trigger language plpgsql set search_path = '' as $$
begin
  if new.workspace_id is distinct from old.workspace_id or new.pack_id is distinct from old.pack_id
     or new.revision_no is distinct from old.revision_no or new.slides is distinct from old.slides
     or new.caption is distinct from old.caption or new.settings is distinct from old.settings
     or new.source is distinct from old.source or new.content_digest is distinct from old.content_digest
     or new.edit_key is distinct from old.edit_key or new.edit_digest is distinct from old.edit_digest
     or new.created_by is distinct from old.created_by or new.created_at is distinct from old.created_at
     or (old.render_manifest is not null and new.render_manifest is distinct from old.render_manifest)
     or (old.render_digest is not null and new.render_digest is distinct from old.render_digest)
     or (old.approval_digest is not null and new.approval_digest is distinct from old.approval_digest)
     or (old.export_digest is not null and new.export_digest is distinct from old.export_digest)
     or (old.export_sha256 is not null and new.export_sha256 is distinct from old.export_sha256)
     or (old.state = 'superseded' and new.state <> 'superseded')
     or new.download_count < old.download_count then
    raise exception 'visual pack revisions are append-only' using errcode = '42501';
  end if;
  return new;
end $$;
revoke all on function postriff_private.pr_visual_pack_revision_guard() from public, anon, authenticated;
create or replace trigger pr_visual_pack_revision_guard before update on public.pr_visual_pack_revisions
  for each row execute function postriff_private.pr_visual_pack_revision_guard();

create or replace function postriff_private.pr_visual_pack_event_immutable() returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'visual pack events are immutable' using errcode = '42501';
end $$;
revoke all on function postriff_private.pr_visual_pack_event_immutable() from public, anon, authenticated;
create or replace trigger pr_visual_pack_event_immutable before update on public.pr_visual_pack_events
  for each row execute function postriff_private.pr_visual_pack_event_immutable();

do $$ declare t text; begin
  foreach t in array array['pr_visual_packs','pr_visual_pack_revisions','pr_visual_pack_events'] loop
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
end $$;

commit;
