-- Service-only bounded health leases; no post bodies or access tokens.
begin;
create table if not exists public.pr_mastodon_health (
  workspace_id uuid not null,
  connection_id text not null,
  next_at timestamptz not null default now(),
  checked_at timestamptz,
  state text not null default 'pending',
  failures integer not null default 0 check (failures between 0 and 10),
  lease_id uuid,
  lease_until timestamptz,
  primary key(workspace_id, connection_id),
  foreign key(workspace_id, connection_id) references public.pr_encrypted_credentials(workspace_id, connection_id) on delete cascade
);
create index if not exists pr_mastodon_health_due on public.pr_mastodon_health(next_at, workspace_id, connection_id);
alter table public.pr_mastodon_health enable row level security;
alter table public.pr_mastodon_health force row level security;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_mastodon_health' and policyname='service_only') then
    create policy service_only on public.pr_mastodon_health for all to service_role using(true) with check(true);
  end if;
end $$;
revoke all on public.pr_mastodon_health from public, anon, authenticated;
grant select, insert, update, delete on public.pr_mastodon_health to service_role;
commit;
