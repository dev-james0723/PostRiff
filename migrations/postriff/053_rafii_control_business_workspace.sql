-- Candidate only. No hosted apply, operator enrollment or test grant is implied.
-- 052 is reserved for concurrent Founder Home investigations.
begin;
do $$ begin
 if not exists(select 1 from pg_roles where rolname='rafii_control_business_projection') then
  create role rafii_control_business_projection nologin nosuperuser bypassrls;
 end if;
 if not exists(select 1 from pg_roles where rolname='rafii_control_test_writer') then
  create role rafii_control_test_writer nologin nosuperuser bypassrls;
 end if;
end $$;
grant usage on schema public,rafii_control to rafii_control_business_projection,rafii_control_test_writer;
grant select(user_id,display_name,deleted_at) on public.pr_profiles to rafii_control_business_projection;
grant select(id,state,revision,created_at) on public.pr_workspaces to rafii_control_business_projection;
grant select(user_id,workspace_id,role,status) on public.pr_memberships to rafii_control_business_projection;
grant select(workspace_id,plan_terms_id,status,current_period_end) on public.pr_subscriptions to rafii_control_business_projection;
grant select(id,label,status,price_cents,currency) on public.pr_plan_terms to rafii_control_business_projection;
grant select(id,workspace_id,kind,dimension,quantity,unit,cost_state,actual_usd_micro,at) on public.pr_usage_ledger to rafii_control_business_projection;
grant select(id,workspace_id,kind,status,requested_at) on public.pr_data_requests to rafii_control_business_projection;

create or replace view rafii_control.business_customers with(security_barrier=true) as
 select p.user_id::text as id,p.display_name as name,case when p.deleted_at is null then 'active' else 'deleted' end as status,
 coalesce((select jsonb_agg(m.workspace_id::text order by m.workspace_id) from public.pr_memberships m where m.user_id=p.user_id and m.status='active'),'[]'::jsonb) as "workspaceIds"
 from public.pr_profiles p;
create or replace view rafii_control.business_workspaces with(security_barrier=true) as
 select w.id::text as id,w.state->'workspace'->>'name' as name,w.revision,
 (select m.user_id::text from public.pr_memberships m where m.workspace_id=w.id and m.role='owner' and m.status='active' order by m.user_id limit 1) as "ownerId",
 (select count(*) from public.pr_memberships m where m.workspace_id=w.id and m.status='active') as "memberCount",
 t.label as plan,coalesce(s.status,'unconfigured') as status,w.created_at as "createdAt"
 from public.pr_workspaces w left join public.pr_subscriptions s on s.workspace_id=w.id left join public.pr_plan_terms t on t.id=s.plan_terms_id;
create or replace view rafii_control.business_subscriptions with(security_barrier=true) as
 select s.workspace_id::text as id,s.workspace_id::text as "workspaceId",t.label as plan,s.status,
 case when t.status='active' then t.price_cents else null end as "amountMinor",t.currency,t.status as "termsStatus",s.current_period_end as "renewsAt"
 from public.pr_subscriptions s join public.pr_plan_terms t on t.id=s.plan_terms_id;
create or replace view rafii_control.business_usage with(security_barrier=true) as
 select id::text,id as "sourceId",workspace_id::text as "workspaceId",kind,dimension,quantity,unit,cost_state as "costState",actual_usd_micro as "actualUsdMicro",at from public.pr_usage_ledger;
create or replace view rafii_control.business_requests with(security_barrier=true) as
 select id::text,workspace_id::text as "workspaceId",kind as title,kind,status,requested_at as at from public.pr_data_requests;
do $$ declare n text; begin
 foreach n in array array['business_customers','business_workspaces','business_subscriptions','business_usage','business_requests'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
 -- Payment metadata remains absent when the canonical purchase schema is absent.
 if to_regclass('public.pr_credit_orders') is not null then
  grant select(id,workspace_id,amount_cents,currency,status,created_at) on public.pr_credit_orders to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_payments with(security_barrier=true) as select id::text,workspace_id::text as "workspaceId",amount_cents as "amountMinor",upper(currency) as currency,status,created_at as at from public.pr_credit_orders';
  alter view rafii_control.business_payments owner to rafii_control_business_projection;
  revoke all on rafii_control.business_payments from public,anon,authenticated,service_role;
  grant select on rafii_control.business_payments to rafii_control_reader;
 end if;
end $$;

create table if not exists rafii_control.demo_workspaces (
 operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 payload jsonb not null check(payload->>'mode'='demo'),replays jsonb not null default '{}',
 primary key(operator_id,environment),foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);
alter table rafii_control.demo_workspaces enable row level security;
alter table rafii_control.demo_workspaces force row level security;
revoke all on rafii_control.demo_workspaces from public,anon,authenticated,service_role,rafii_control_reader;
grant select,insert,update on rafii_control.demo_workspaces to rafii_control_session;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='demo_workspaces' and policyname='own_demo') then
  create policy own_demo on rafii_control.demo_workspaces for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true))
   with check(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true));
 end if;
end $$;

create table if not exists rafii_control.workspace_actions (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,environment text not null,
 mode text not null check(mode in ('live','demo')),request_id uuid not null,action text not null,
 target_id text not null,request jsonb,result jsonb,at timestamptz not null default now(),
 unique(operator_id,environment,mode,request_id)
);
create table if not exists rafii_control.test_workspace_grants (
 operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 workspace_id uuid not null references public.pr_workspaces(id),approval_ref text not null check(length(approval_ref)>0),
 expires_at timestamptz not null,primary key(operator_id,environment,workspace_id)
);
do $$ declare n text; begin
 foreach n in array array['workspace_actions','test_workspace_grants'] loop
  execute format('alter table rafii_control.%I enable row level security',n);
  execute format('alter table rafii_control.%I force row level security',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role,rafii_control_reader',n);
  execute format('grant select on rafii_control.%I to rafii_control_session,rafii_control_test_writer',n);
  if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=n and policyname='environment_read') then
   execute format('create policy environment_read on rafii_control.%I for select to rafii_control_session using(environment=current_setting(''rafii_control.environment'',true))',n);
  end if;
 end loop;
end $$;
grant insert on rafii_control.workspace_actions to rafii_control_session,rafii_control_test_writer;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='workspace_actions' and policyname='demo_action_insert') then
  create policy demo_action_insert on rafii_control.workspace_actions for insert to rafii_control_session
   with check(mode='demo' and environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true));
 end if;
end $$;
-- Enrollment is deliberately separate; no active operator gains a write capability here.
alter table rafii_control.platform_operators drop constraint if exists platform_operators_capabilities_check;
alter table rafii_control.platform_operators add constraint platform_operators_capabilities_check
 check(capabilities <@ array['control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename']::text[]);
alter table rafii_control.admin_audit_log drop constraint if exists admin_audit_log_action_check;
alter table rafii_control.admin_audit_log add constraint admin_audit_log_action_check check(action in ('session.exchange','control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename','prohibited'));
grant select(user_id,environment,role,status,capabilities,auth_epoch) on rafii_control.platform_operators to rafii_control_test_writer;
grant select on rafii_control.founder_sessions to rafii_control_test_writer;
grant select(id,revision,state),update(state,revision) on public.pr_workspaces to rafii_control_test_writer;
create or replace function rafii_control.rename_test_workspace(p_actor uuid,p_session uuid,p_environment text,p_workspace uuid,p_name text,p_revision bigint,p_request uuid)
 returns jsonb language plpgsql security definer set search_path='' as $$
 declare old_revision bigint; source_state jsonb; response jsonb; previous record; intent jsonb;
 begin
  if p_environment is distinct from current_setting('rafii_control.environment',true) or p_revision is null or p_request is null or p_name is null or length(btrim(p_name)) not between 1 and 80 then raise exception 'SCOPE_DENIED'; end if;
  if not exists(select 1 from rafii_control.platform_operators o join rafii_control.founder_sessions s on s.user_id=o.user_id and s.environment=o.environment and s.auth_epoch=o.auth_epoch
   where o.user_id=p_actor and o.environment=p_environment and o.role='founder' and o.status='active' and 'workspaces.test.rename'=any(o.capabilities)
   and s.id=p_session and s.assurance='aal2' and s.revoked_at is null and s.expires_at>extract(epoch from now()) and s.last_seen_at>extract(epoch from now())-1800) then raise exception 'SCOPE_DENIED'; end if;
  if not exists(select 1 from rafii_control.founder_sessions where id=p_session and mfa_at between extract(epoch from now())-300 and extract(epoch from now())) then raise exception 'STEP_UP_REQUIRED'; end if;
  if not exists(select 1 from rafii_control.test_workspace_grants where operator_id=p_actor and environment=p_environment and workspace_id=p_workspace and expires_at>now()) then raise exception 'SCOPE_DENIED'; end if;
  intent=jsonb_build_object('workspaceId',p_workspace,'name',p_name,'revision',p_revision);
  -- Serialize both concurrent requests and uncertain-response retries on the canonical row.
  select revision,state into old_revision,source_state from public.pr_workspaces where id=p_workspace for update;
  if not found or source_state ? 'accountDeletion' then raise exception 'SCOPE_DENIED'; end if;
  select request,result into previous from rafii_control.workspace_actions where operator_id=p_actor and environment=p_environment and mode='live' and request_id=p_request;
  if found then
   if previous.request is distinct from intent then raise exception 'IDEMPOTENCY_CONFLICT'; end if;
   return previous.result;
  end if;
  if old_revision<>p_revision then raise exception 'STALE_PREVIEW'; end if;
  update public.pr_workspaces set state=jsonb_set(jsonb_set(state,'{workspace}',coalesce(state->'workspace','{}'::jsonb)),'{workspace,name}',to_jsonb(p_name)),revision=revision+1 where id=p_workspace;
  response=jsonb_build_object('workspaceId',p_workspace,'name',p_name,'revision',old_revision+1,'requestId',p_request);
  insert into rafii_control.workspace_actions(operator_id,environment,mode,request_id,action,target_id,request,result)
   values(p_actor,p_environment,'live',p_request,'test_workspace_renamed',p_workspace::text,intent,response);
  return response;
 end $$;
alter function rafii_control.rename_test_workspace(uuid,uuid,text,uuid,text,bigint,uuid) owner to rafii_control_test_writer;
revoke all on function rafii_control.rename_test_workspace(uuid,uuid,text,uuid,text,bigint,uuid) from public,anon,authenticated,service_role,rafii_control_reader;
grant execute on function rafii_control.rename_test_workspace(uuid,uuid,text,uuid,text,bigint,uuid) to rafii_control_session;
commit;
