-- Additive lifecycle/organization schema. Roll back code, retain private rows and objects.
begin;
-- Reconcile the earlier staging candidate's over-escaped filename constraint.
alter table public.pr_library_assets drop constraint if exists pr_library_assets_object_name_check;
alter table public.pr_library_assets add constraint pr_library_assets_object_name_check check (object_name ~ '^[0-9a-f]{32}\.[a-z0-9]{1,12}$');
alter table public.pr_library_assets drop constraint if exists pr_library_assets_kind_check;
alter table public.pr_library_assets add constraint pr_library_assets_kind_check check (kind in ('document','file','audio'));
alter table public.pr_library_assets drop constraint if exists pr_library_assets_processing_status_check;
alter table public.pr_library_assets add constraint pr_library_assets_processing_status_check check (processing_status in ('pending','queued','processing','ready','failed','unsupported','duplicate','deleting'));
alter table public.pr_library_assets add column if not exists attempts integer not null default 0 check (attempts between 0 and 20);
alter table public.pr_library_assets add column if not exists lease_token uuid;
alter table public.pr_library_assets add column if not exists lease_expires_at timestamptz;
alter table public.pr_library_assets add column if not exists next_attempt_at timestamptz not null default now();
alter table public.pr_library_assets add column if not exists duplicate_of uuid references public.pr_library_assets(id) on delete set null;
alter table public.pr_library_assets add column if not exists transcription_status text not null default 'not_applicable' check (transcription_status in ('not_applicable','unavailable','ready'));
alter table public.pr_library_assets add column if not exists source_id text;
create index if not exists pr_library_assets_jobs on public.pr_library_assets(next_attempt_at,lease_expires_at) where processing_status in ('queued','processing');
create index if not exists pr_library_assets_dedup on public.pr_library_assets(workspace_id,sha256) where processing_status in ('ready','unsupported');
-- Bind chunks to the same asset workspace, including for privileged server access.
create unique index if not exists pr_library_assets_identity on public.pr_library_assets(workspace_id,id);
do $$ begin
 if not exists(select 1 from pg_constraint where conname='pr_library_chunks_workspace_asset_fk') then
  alter table public.pr_library_chunks add constraint pr_library_chunks_workspace_asset_fk foreign key (workspace_id,asset_id) references public.pr_library_assets(workspace_id,id) on delete cascade;
 end if;
end $$;
create table if not exists public.pr_library_labels (
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
 display_title text check (length(display_title) between 1 and 160),
 tags text[] not null default '{}' check (cardinality(tags)<=30),
 updated_at timestamptz not null default now(),
 primary key(workspace_id,asset_key)
);
create table if not exists public.pr_library_collections (
 id uuid primary key, workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 name text not null check (length(name) between 1 and 80), created_by uuid not null,
 created_at timestamptz not null default now(), unique(workspace_id,id), unique(workspace_id,name)
);
create table if not exists public.pr_library_collection_items (
 workspace_id uuid not null, collection_id uuid not null, asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
 primary key(workspace_id,collection_id,asset_key),
 foreign key(workspace_id,collection_id) references public.pr_library_collections(workspace_id,id) on delete cascade
);
create index if not exists pr_library_collection_asset on public.pr_library_collection_items(workspace_id,asset_key);
do $$ declare t text; begin
 foreach t in array array['pr_library_labels','pr_library_collections','pr_library_collection_items'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',t);
  end if;
 end loop;
end $$;
commit;
