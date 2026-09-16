-- Additive consumer-web tenancy: five roles, separate action permissions, invitations,
-- audit events, session inventory, and auth throttling. Apply after 001 and 002.
-- Never grants browser writes; tokens and throttle buckets are service_role only.
begin;

-- Roles: owner/admin/editor/approver/viewer. Existing rows are unchanged.
alter table public.pr_memberships drop constraint if exists pr_memberships_role_check;
alter table public.pr_memberships add constraint pr_memberships_role_check
  check (role in ('owner','admin','editor','approver','viewer'));
alter table public.pr_memberships
  add column if not exists can_publish boolean not null default false,
  add column if not exists can_reply boolean not null default false,
  add column if not exists can_moderate boolean not null default false,
  add column if not exists can_manage_connections boolean not null default false,
  add column if not exists invited_by uuid,
  add column if not exists updated_at timestamptz not null default now();
-- Owners hold every action permission by definition.
update public.pr_memberships set can_publish=true, can_reply=true, can_moderate=true, can_manage_connections=true where role='owner';

-- Members may see their teammates (user ids and roles only; profiles stay self-only).
create policy team_membership on public.pr_memberships for select to authenticated using (postriff_private.member(workspace_id));

create table public.pr_invitations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  email text not null check (email = lower(email) and length(email) between 3 and 254 and position('@' in email) > 1),
  role text not null check (role in ('admin','editor','approver','viewer')),
  permissions jsonb not null default '{}' check (jsonb_typeof(permissions)='object'),
  token_hash text not null unique check (length(token_hash)=64),
  created_by uuid not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  accepted_by uuid,
  accepted_at timestamptz,
  revoked_at timestamptz,
  check (expires_at > created_at)
);
create index on public.pr_invitations (workspace_id);
alter table public.pr_invitations enable row level security;
alter table public.pr_invitations force row level security;
revoke all on public.pr_invitations from public, anon, authenticated;
grant all on public.pr_invitations to service_role;
create policy invitations_service_only on public.pr_invitations for all to service_role using (true) with check (true);

-- Append-only, content-free audit trail. Members can read their workspace's rows.
create table public.pr_audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.pr_workspaces(id) on delete cascade,
  actor uuid,
  kind text not null check (length(kind) between 3 and 80),
  subject text not null default '' check (length(subject) <= 200),
  at timestamptz not null default now(),
  meta jsonb not null default '{}' check (jsonb_typeof(meta)='object')
);
create index on public.pr_audit_events (workspace_id, at desc);
alter table public.pr_audit_events enable row level security;
alter table public.pr_audit_events force row level security;
revoke all on public.pr_audit_events from public, anon, authenticated;
grant select on public.pr_audit_events to authenticated;
grant insert, select on public.pr_audit_events to service_role;
create policy audit_tenant_read on public.pr_audit_events for select to authenticated using (workspace_id is not null and postriff_private.member(workspace_id));
create policy audit_service_write on public.pr_audit_events for all to service_role using (true) with check (true);
-- No update/delete grant exists for any role: rows are immutable.

-- Session inventory for the device list. Revocation uses pr_session_revocations.
create table public.pr_sessions (
  user_id uuid not null,
  session_id text not null check (length(session_id) between 16 and 160),
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  client_label text not null default '' check (length(client_label) <= 40),
  primary key (user_id, session_id)
);
alter table public.pr_sessions enable row level security;
alter table public.pr_sessions force row level security;
revoke all on public.pr_sessions from public, anon, authenticated;
grant all on public.pr_sessions to service_role;
create policy sessions_service_only on public.pr_sessions for all to service_role using (true) with check (true);

-- Fixed-window throttle buckets keyed by a hashed scope; never stores raw addresses.
create table public.pr_auth_throttle (
  bucket text primary key check (length(bucket)=64),
  window_start timestamptz not null default now(),
  count integer not null default 0 check (count >= 0)
);
alter table public.pr_auth_throttle enable row level security;
alter table public.pr_auth_throttle force row level security;
revoke all on public.pr_auth_throttle from public, anon, authenticated;
grant all on public.pr_auth_throttle to service_role;
create policy throttle_service_only on public.pr_auth_throttle for all to service_role using (true) with check (true);

-- Bootstrap now grants the owner every action permission explicitly.
create or replace function public.pr_bootstrap(p_user uuid, p_plan text) returns uuid language plpgsql security definer set search_path='' as $$
declare wid uuid;
begin
  if p_plan not in ('studio','assist') then raise exception 'unavailable plan'; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user::text,0));
  if not exists(select 1 from auth.users where id=p_user) then raise exception 'verified user required'; end if;
  if exists(select 1 from public.pr_account_tombstones where user_id=p_user) then raise exception 'deleted account'; end if;
  if exists(select 1 from public.pr_profiles where user_id=p_user and deleted_at is not null) then raise exception 'deleted account'; end if;
  select workspace_id into wid from public.pr_memberships where user_id=p_user and status='active' limit 1;
  if wid is not null then return wid; end if;
  if exists(select 1 from public.pr_trials where user_id=p_user) then raise exception 'trial already granted'; end if;
  insert into public.pr_profiles(user_id) values(p_user) on conflict do nothing;
  insert into public.pr_workspaces default values returning id into wid;
  insert into public.pr_memberships(workspace_id,user_id,role,status,can_publish,can_reply,can_moderate,can_manage_connections)
    values(wid,p_user,'owner','active',true,true,true,true);
  insert into public.pr_trials(user_id,workspace_id,plan) values(p_user,wid,p_plan);
  return wid;
end $$;
revoke all on function public.pr_bootstrap(uuid,text) from public,anon,authenticated;
grant execute on function public.pr_bootstrap(uuid,text) to service_role;

commit;
