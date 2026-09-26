-- Chat attachments: pending direct-to-storage video uploads and cached media notes (chat-context SPEC §7.3, §8.2).
-- Forward-only and idempotent. Rollback = RAFII_VIDEO_UPLOADS_ENABLED / RAFII_MEDIA_NOTES_ENABLED off; the tables stay empty.
begin;
create table if not exists public.pr_media_uploads (
  id uuid primary key,                                   -- the asset id the upload will become
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  created_by uuid not null,
  bucket text not null check (bucket ~ '^[a-z0-9-]{3,63}$'),
  object_name text not null check (object_name ~ '^[0-9a-f]{32}\.(mp4|mov)$'),
  mime text not null check (mime in ('video/mp4','video/quicktime')),
  declared_bytes bigint not null check (declared_bytes > 0),
  status text not null check (status in ('pending','committed','aborted','deleting')),
  token_expires_at timestamptz not null,
  delete_attempts integer not null default 0,
  last_error text check (last_error is null or length(last_error) <= 300),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists pr_media_uploads_sweep on public.pr_media_uploads (status, token_expires_at);
create index if not exists pr_media_uploads_owner on public.pr_media_uploads (workspace_id, created_by, status);
create table if not exists public.pr_media_notes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  asset_id text not null check (asset_id ~ '^[0-9a-f]{32}$'),
  asset_hash text not null check (length(asset_hash) <= 128),
  reader_version text not null check (length(reader_version) <= 40),
  processor jsonb not null check (jsonb_typeof(processor) = 'object'),
  status text not null check (status in ('reading','ready','failed')),
  kind text not null check (kind in ('photo','video_frames')),
  frames integer not null default 1 check (frames between 0 and 4),
  text text check (text is null or length(text) <= 1200),
  model text check (model is null or length(model) <= 120),
  reservation_id uuid,
  attempts integer not null default 0,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, asset_id, asset_hash, reader_version)
);
do $$
declare t text;
begin
  foreach t in array array['pr_media_uploads','pr_media_notes'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = 'service_only') then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;
commit;
