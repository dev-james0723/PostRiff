-- Additive, service-only Mastodon application custody and exact-action journal.
begin;
create table if not exists public.pr_mastodon_applications (
  instance text not null,
  binding_digest text not null check (binding_digest ~ '^[0-9a-f]{64}$'),
  credentials_ciphertext text not null,
  key_id text not null,
  updated_at timestamptz not null default now(),
  primary key(instance, binding_digest)
);
create table if not exists public.pr_mastodon_actions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  connection_id text not null,
  actor_id uuid not null,
  action text not null,
  preview jsonb not null,
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  status text not null default 'preview' check (status in ('preview','running','verified','accepted','rejected','uncertain','cancelled')),
  receipt jsonb,
  expires_at timestamptz not null default now() + interval '10 minutes',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists pr_mastodon_actions_connection on public.pr_mastodon_actions(workspace_id, connection_id, created_at desc);
alter table public.pr_mastodon_applications enable row level security;
alter table public.pr_mastodon_actions enable row level security;
alter table public.pr_mastodon_applications force row level security;
alter table public.pr_mastodon_actions force row level security;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_mastodon_applications' and policyname='service_only') then
    create policy service_only on public.pr_mastodon_applications for all to service_role using (true) with check (true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_mastodon_actions' and policyname='service_only') then
    create policy service_only on public.pr_mastodon_actions for all to service_role using (true) with check (true);
  end if;
end $$;
revoke all on public.pr_mastodon_applications, public.pr_mastodon_actions from public, anon, authenticated;
grant select, insert, update, delete on public.pr_mastodon_applications, public.pr_mastodon_actions to service_role;
commit;
