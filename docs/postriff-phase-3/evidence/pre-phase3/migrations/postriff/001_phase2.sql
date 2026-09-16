-- Additive Supabase candidate. Apply only to a new approved project.
-- Local tests bootstrap auth/storage schemas separately; never against founder data.
begin;
create schema if not exists postriff_private;
revoke all on schema postriff_private from public, anon, authenticated;
create table public.pr_profiles (
  user_id uuid primary key references auth.users(id), display_name text not null default '', deleted_at timestamptz
);
create table public.pr_workspaces (
  id uuid primary key default gen_random_uuid(), revision bigint not null default 1,
  state jsonb not null default '{}', created_at timestamptz not null default now()
);
create table public.pr_memberships (
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  user_id uuid references public.pr_profiles(user_id), role text not null check(role in ('owner','editor','viewer')),
  status text not null check(status in ('active','revoked')), primary key(workspace_id,user_id)
);
create table public.pr_trials (
  user_id uuid primary key references public.pr_profiles(user_id), workspace_id uuid references public.pr_workspaces(id) on delete set null,
  plan text not null check(plan in ('studio','assist')), started_at timestamptz not null default now(),
  expires_at timestamptz not null default now()+interval '14 days', writing_grant integer not null default 10 check(writing_grant=10),
  writing_used integer not null default 0 check(writing_used between 0 and 10), artwork_grant integer not null default 1,
  auto_convert boolean not null default false check(not auto_convert)
);
create function postriff_private.member(wid uuid) returns boolean language sql stable security definer set search_path='' as $$
  select exists(select 1 from public.pr_memberships m join public.pr_profiles p on p.user_id=m.user_id where m.workspace_id=wid and m.user_id=(select auth.uid()) and m.status='active' and p.deleted_at is null)
$$;
grant usage on schema postriff_private to authenticated;
grant execute on function postriff_private.member(uuid) to authenticated;
revoke all on function postriff_private.member(uuid) from public, anon;

-- Explicit object tables retain tenant keys and private versions; mutation is API-only.
do $$
declare t text;
begin
  foreach t in array array['pr_voice_profiles','pr_skills','pr_sources','pr_assets','pr_devices','pr_channels','pr_approvals','pr_jobs','pr_receipts'] loop
    execute format('create table public.%I (id uuid primary key default gen_random_uuid(), workspace_id uuid not null references public.pr_workspaces(id) on delete cascade, revision bigint not null default 1, body jsonb not null, created_at timestamptz not null default now())',t);
    execute format('alter table public.%I enable row level security',t);
    execute format('alter table public.%I force row level security',t);
    execute format('create policy tenant_read on public.%I for select to authenticated using (postriff_private.member(workspace_id))',t);
    -- Defense in depth if write grants are mistakenly added: CHECK prevents forged tenant IDs.
    execute format('create policy trusted_write on public.%I for all to service_role using (true) with check (true)',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select on public.%I to authenticated',t);
    execute format('grant all on public.%I to service_role',t);
    execute format('create index on public.%I (workspace_id)',t);
  end loop;
end $$;
alter table public.pr_profiles enable row level security;
alter table public.pr_profiles force row level security;
alter table public.pr_workspaces enable row level security;
alter table public.pr_workspaces force row level security;
alter table public.pr_memberships enable row level security;
alter table public.pr_memberships force row level security;
alter table public.pr_trials enable row level security;
alter table public.pr_trials force row level security;
create policy self_profile on public.pr_profiles for select to authenticated using(user_id=(select auth.uid()) and deleted_at is null);
create policy own_workspace on public.pr_workspaces for select to authenticated using(postriff_private.member(id));
create policy own_membership on public.pr_memberships for select to authenticated using(user_id=(select auth.uid()) and postriff_private.member(workspace_id));
create policy own_trial on public.pr_trials for select to authenticated using(user_id=(select auth.uid()) and postriff_private.member(workspace_id));
revoke all on public.pr_profiles,public.pr_workspaces,public.pr_memberships,public.pr_trials from public,anon,authenticated;
grant select on public.pr_profiles,public.pr_workspaces,public.pr_memberships,public.pr_trials to authenticated;
grant all on public.pr_profiles,public.pr_workspaces,public.pr_memberships,public.pr_trials to service_role;

-- Service role alone may bootstrap. p_user comes from a server-verified auth.users principal.
create function public.pr_bootstrap(p_user uuid, p_plan text) returns uuid language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  if p_plan not in ('studio','assist') then raise exception 'unavailable plan'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select workspace_id into wid from public.pr_memberships where user_id=p_user and status='active' limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships values(wid,p_user,'owner','active');
  insert into public.pr_trials(user_id,workspace_id,plan) values(p_user,wid,p_plan);
  return wid;
end $$;
revoke all on function public.pr_bootstrap(uuid,text) from public,anon,authenticated;
grant execute on function public.pr_bootstrap(uuid,text) to service_role;

create unique index pr_approval_idempotency on public.pr_approvals(workspace_id,(body->>'idempotencyKey'));
create unique index pr_job_idempotency on public.pr_jobs(workspace_id,(body->>'idempotencyKey'));
create index pr_job_due on public.pr_jobs((body->>'state'),(body->>'nextAt'));
insert into storage.buckets(id,name,public) values('postriff-private','postriff-private',false);
create policy postriff_private_read on storage.objects for select to authenticated using (
  bucket_id='postriff-private' and exists(select 1 from public.pr_workspaces w where w.id::text=split_part(name,'/',1) and postriff_private.member(w.id))
);
-- Browser writes are intentionally absent. Trusted API decodes assets and verifies membership
-- before service upload; no client may overwrite an immutable source or rendition.
commit;
