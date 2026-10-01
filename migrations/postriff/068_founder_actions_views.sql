-- Founder actions, Control side (Founder Admin P1/P2, CONTRACTS §8.F). Everything in rafii_control; apply after 056 and
-- 062. Additive and idempotent (apply twice). Hosted application is a separate, owner-approved step: no role membership
-- is granted to the migration runner here, no role is created, and no operator gains a capability (056 declares
-- usage.reconcile, credits.adjust, accounts.block and refunds.prepare; enrollment stays a reviewed step).
--
-- rafii_control.founder_action_requests: the preview -> confirm record of every founder action (055 pattern: forced RLS,
-- environment GUC policies, written only by the restricted session role). Reads are environment-wide (audit.read lists
-- recent requests); inserts and updates are bound to the operator GUC, so one founder can never claim another's preview.
-- Content-free: target ids, validated parameters (ids, enums, amounts and one bounded evidence reference), the preview the
-- founder saw (target, current value, effect as ids/enums/counts/amounts/timestamps), the result, fixed error/blocker
-- codes and the Control audit request ids. The revision digests the target's current value at preview time; a preview
-- expires after five minutes. After insert only the lifecycle columns can change (column-level UPDATE grant).
-- rafii_control.business_account_blocks: the reader projection of public.pr_account_blocks (054 pattern) for Customer 360
-- and GET /actions; no approval reference, no operator id.
begin;

create table if not exists rafii_control.founder_action_requests (
 id uuid primary key,
 operator_id uuid not null,
 environment text not null check(environment in ('local','staging','production')),
 kind text not null check(kind in ('reconcile','credits_adjust','account_block','account_unblock','refund_intent')),
 target_type text not null check(target_type in ('reservation','workspace','user','payment')),
 target_id text not null check(target_id ~ '^[A-Za-z0-9_-]{1,100}$'),
 workspace_id uuid,
 params jsonb not null default '{}'::jsonb check(jsonb_typeof(params)='object' and octet_length(params::text)<=2048),
 preview jsonb not null default '{}'::jsonb check(jsonb_typeof(preview)='object' and octet_length(preview::text)<=16384),
 revision text not null check(revision ~ '^[0-9a-f]{16}$'),
 state text not null default 'previewed' check(state in ('previewed','confirmed','executed','failed','expired')),
 request_id uuid not null unique,
 confirm_request_id uuid unique,
 preview_audit_id uuid not null,
 confirm_audit_id uuid,
 result jsonb not null default '{}'::jsonb check(jsonb_typeof(result)='object' and octet_length(result::text)<=8192),
 error_code text check(error_code ~ '^[A-Z][A-Z_]{1,39}$'),
 blocker text check(blocker ~ '^[a-z][a-z0-9_]{0,63}$'),
 created_at timestamptz not null,
 expires_at timestamptz not null,
 confirmed_at timestamptz,
 finished_at timestamptz,
 check(expires_at>created_at and expires_at<=created_at+interval '5 minutes'),
 check(state not in ('previewed','expired') or (confirm_request_id is null and confirmed_at is null)),
 check(state in ('previewed','expired') or (confirm_request_id is not null and confirmed_at is not null)),
 check(state not in ('executed','failed') or finished_at is not null),
 check(confirm_request_id is null or confirm_request_id<>request_id),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);
create index if not exists rc_founder_actions_recent on rafii_control.founder_action_requests(environment,created_at desc);
create index if not exists rc_founder_actions_open on rafii_control.founder_action_requests(environment,expires_at) where state='previewed';

alter table rafii_control.founder_action_requests enable row level security;
alter table rafii_control.founder_action_requests force row level security;
revoke all on rafii_control.founder_action_requests from public,anon,authenticated,service_role,rafii_control_reader;
grant select,insert on rafii_control.founder_action_requests to rafii_control_session;
grant update(state,confirm_request_id,confirm_audit_id,confirmed_at,finished_at,result,error_code,blocker)
 on rafii_control.founder_action_requests to rafii_control_session;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_action_requests' and policyname='founder_actions_read') then
  create policy founder_actions_read on rafii_control.founder_action_requests for select to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true));
 end if;
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_action_requests' and policyname='founder_actions_insert') then
  create policy founder_actions_insert on rafii_control.founder_action_requests for insert to rafii_control_session
   with check(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true));
 end if;
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_action_requests' and policyname='founder_actions_update') then
  create policy founder_actions_update on rafii_control.founder_action_requests for update to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true))
   with check(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true));
 end if;
end $$;

-- Account blocks for the reader (054 pattern): column grants to the business projection role, a security_barrier view it
-- owns, select for the reader only.
grant select(id,user_id,workspace_id,reason_code,blocked_at,lifted_at) on public.pr_account_blocks to rafii_control_business_projection;
create or replace view rafii_control.business_account_blocks with(security_barrier=true) as
 select id::text as id,user_id::text as "userId",workspace_id::text as "workspaceId",reason_code as "reasonCode",
 blocked_at as "blockedAt",lifted_at as "liftedAt",lifted_at is null as active
 from public.pr_account_blocks;
alter view rafii_control.business_account_blocks owner to rafii_control_business_projection;
revoke all on rafii_control.business_account_blocks from public,anon,authenticated,service_role;
grant select on rafii_control.business_account_blocks to rafii_control_reader;

commit;
