-- Connected accounts' profile pictures for post previews (src/postriff_phase2/account_pictures.py).
-- One small re-encoded JPEG per connection, read from the provider at connect and re-verify, deleted on
-- disconnect. Additive; apply after 011. Service-role writes only; members read their own workspace's rows.
create table if not exists public.pr_channel_pictures (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null check (connection_id ~ '^[0-9a-f]{32}$'),
  picture bytea not null check (octet_length(picture) between 1 and 262144),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  fetched_at timestamptz not null default now(),
  primary key (workspace_id, connection_id)
);

do $$
begin
  alter table public.pr_channel_pictures enable row level security;
  alter table public.pr_channel_pictures force row level security;
  revoke all on public.pr_channel_pictures from public, anon, authenticated;
  grant select on public.pr_channel_pictures to authenticated;
  grant all on public.pr_channel_pictures to service_role;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_channel_pictures' and policyname='tenant_read') then
    create policy tenant_read on public.pr_channel_pictures for select to authenticated using (postriff_private.member(workspace_id));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='pr_channel_pictures' and policyname='trusted_write') then
    create policy trusted_write on public.pr_channel_pictures for all to service_role using (true) with check (true);
  end if;
end $$;
