-- Universal Library normalized assets and extracted text.
-- Server-only tables: workspace membership is enforced by HostedWorkspaceService before SQL access.
begin;

create table if not exists public.pr_library_assets (
  id uuid primary key,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  created_by uuid not null,
  original_filename text not null check (length(original_filename) between 1 and 255),
  display_title text check (display_title is null or length(display_title) <= 160),
  title_source text not null default 'filename' check (title_source in ('filename','generated','user')),
  summary text check (summary is null or length(summary) <= 1200),
  tags text[] not null default '{}',
  kind text not null check (kind in ('document','file')),
  mime text not null check (length(mime) between 3 and 160),
  extension text not null check (extension ~ '^[a-z0-9]{1,12}$'),
  bytes bigint not null check (bytes > 0 and bytes <= 52428800),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  bucket text not null check (bucket ~ '^[a-z0-9-]{3,63}$'),
  object_name text not null check (object_name ~ '^[0-9a-f]{32}\.[a-z0-9]{1,12}$'),
  etag text check (etag is null or length(etag) <= 200),
  processing_status text not null default 'pending' check (processing_status in ('pending','ready','failed','unsupported','deleting')),
  analysis_status text not null default 'pending' check (analysis_status in ('pending','ready','failed','not_applicable')),
  indexing_status text not null default 'pending' check (indexing_status in ('pending','ready','failed','not_applicable')),
  extraction_error text check (extraction_error is null or length(extraction_error) <= 300),
  provenance jsonb not null default '{}'::jsonb check (jsonb_typeof(provenance) = 'object'),
  token_expires_at timestamptz,
  delete_attempts integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, object_name)
);

create table if not exists public.pr_library_chunks (
  asset_id uuid not null references public.pr_library_assets(id) on delete cascade,
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  ordinal integer not null check (ordinal >= 0 and ordinal < 10000),
  text text not null check (length(text) between 1 and 12000),
  search_vector tsvector generated always as (to_tsvector('simple', text)) stored,
  primary key (asset_id, ordinal)
);

create index if not exists pr_library_assets_workspace_created on public.pr_library_assets(workspace_id, created_at desc);
create index if not exists pr_library_assets_workspace_status on public.pr_library_assets(workspace_id, processing_status, indexing_status);
create index if not exists pr_library_assets_sweep on public.pr_library_assets(processing_status, token_expires_at) where processing_status in ('pending','deleting');
create index if not exists pr_library_chunks_workspace on public.pr_library_chunks(workspace_id, asset_id, ordinal);
create index if not exists pr_library_chunks_search on public.pr_library_chunks using gin(search_vector);
create index if not exists pr_library_assets_metadata_search on public.pr_library_assets using gin(
  to_tsvector('simple',
    coalesce(display_title,'') || ' ' ||
    coalesce(original_filename,'') || ' ' ||
    coalesce(summary,'')
  )
);

do $$
declare t text;
begin
  foreach t in array array['pr_library_assets','pr_library_chunks'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
    if not exists (
      select 1 from pg_policies
      where schemaname='public' and tablename=t and policyname='service_only'
    ) then
      execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)', t);
    end if;
  end loop;
end $$;

commit;
