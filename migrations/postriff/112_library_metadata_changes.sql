-- Native Library metadata previews and the one conditional inverse used by native/task callers.
-- Additive only. Rollback code independently; retain private receipts and monotonic versions.
begin;
create table if not exists public.pr_library_metadata_versions (
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 asset_key text not null check (asset_key ~ '^[0-9a-f]{32}$'),
 revision bigint not null default 1 check (revision > 0),
 primary key(workspace_id,asset_key)
);
create table if not exists public.pr_library_metadata_changes (
 id uuid primary key,
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 actor_id uuid not null,
 status text not null default 'prepared' check (status in ('prepared','applied','undone')),
 payload jsonb not null check (coalesce(jsonb_typeof(payload)='object' and payload->>'version'='1'
   and coalesce(jsonb_typeof(payload->'entries')='array' and jsonb_array_length(payload->'entries') between 1 and 20,false)
   and octet_length(payload::text)<=262144,false)),
 created_at timestamptz not null default now(),
 expires_at timestamptz not null,
 applied_at timestamptz,
 undo_expires_at timestamptz,
 undone_at timestamptz,
 check ((status='prepared' and applied_at is null and undo_expires_at is null and undone_at is null)
     or (status='applied' and applied_at is not null and undo_expires_at is not null and undone_at is null)
     or (status='undone' and applied_at is not null and undo_expires_at is not null and undone_at is not null))
);
create index if not exists pr_library_metadata_changes_owner on public.pr_library_metadata_changes(workspace_id,actor_id,created_at desc);

create or replace function public.pr_library_metadata_bump() returns trigger language plpgsql set search_path=pg_catalog,public as $$
declare w uuid; k text;
begin
 if tg_op='DELETE' then
  w:=old.workspace_id;
  if tg_table_name='pr_library_assets' then k:=replace(old.id::text,'-',''); else k:=old.asset_key; end if;
 else
  w:=new.workspace_id;
  if tg_table_name='pr_library_assets' then k:=replace(new.id::text,'-',''); else k:=new.asset_key; end if;
 end if;
 -- During workspace erasure the parent may already be gone. Never recreate its metadata.
 if exists(select 1 from public.pr_workspaces where id=w) then
  insert into public.pr_library_metadata_versions(workspace_id,asset_key) values(w,k)
   on conflict(workspace_id,asset_key) do update set revision=public.pr_library_metadata_versions.revision+1;
 end if;
 return null;
end $$;
revoke all on function public.pr_library_metadata_bump() from public,anon,authenticated;
grant execute on function public.pr_library_metadata_bump() to service_role;
drop trigger if exists pr_library_metadata_asset_version on public.pr_library_assets;
create trigger pr_library_metadata_asset_version after insert or delete or update of display_title,title_source,tags on public.pr_library_assets for each row execute function public.pr_library_metadata_bump();
drop trigger if exists pr_library_metadata_label_version on public.pr_library_labels;
create trigger pr_library_metadata_label_version after insert or delete or update of display_title,tags on public.pr_library_labels for each row execute function public.pr_library_metadata_bump();
drop trigger if exists pr_library_metadata_collection_version on public.pr_library_collection_items;
create trigger pr_library_metadata_collection_version after insert or delete or update on public.pr_library_collection_items for each row execute function public.pr_library_metadata_bump();

do $$ declare t text; begin
 foreach t in array array['pr_library_metadata_versions','pr_library_metadata_changes'] loop
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
