-- Full-activation candidate. 088 was free in current source/open PRs on 2026-10-02.
-- Recheck the staging/production ledger before application. No old migration is replayed.
begin;

alter table rafii_control.founder_settings add column if not exists policy_revision integer not null default 0;
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_daily_cap_check;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_daily_cap_check check(daily_cap between 0 and 100);
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_concurrent_cap_check;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_concurrent_cap_check check(concurrent_cap between 0 and 10);
alter table rafii_control.founder_contact_policy drop constraint if exists founder_contact_policy_budget_usd_micro_daily_check;
alter table rafii_control.founder_contact_policy alter column budget_usd_micro_daily drop not null;
alter table rafii_control.founder_contact_policy add constraint founder_contact_policy_budget_usd_micro_daily_check check(budget_usd_micro_daily between 0 and 10000000000);

-- Legacy observations are unknown. Do not fabricate their availability time.
alter table public.pr_product_events add column if not exists recorded_at timestamptz;
alter table public.pr_product_events alter column recorded_at set default now();
grant select(recorded_at) on public.pr_product_events to rafii_control_business_projection;
create or replace view rafii_control.business_product_observations with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",event,occurred_at as "occurredAt",recorded_at as "recordedAt"
 from public.pr_product_events;

-- Only fixed counts/error classes are exposed. Recoverable rows remain in the
-- original tenant's audit, inaccessible to Control logins or Founder agents.
grant select(meta,subject) on public.pr_audit_events to rafii_control_business_projection;
create or replace view rafii_control.business_telemetry_health with(security_barrier=true) as
 select a.at as "observedAt",a.workspace_id::text as "workspaceId",
 case when a.kind='telemetry.product_events' then 'product_events' else 'ai_call_events' end as writer,
 case when a.meta->>'state' in ('recorded','failed','suspended') then a.meta->>'state' else 'unknown' end as state,
 case when a.meta->>'attempted' ~ '^[0-9]{1,3}$' then (a.meta->>'attempted')::integer else 0 end as attempted,
 case when a.meta->>'recorded' ~ '^[0-9]{1,3}$' then (a.meta->>'recorded')::integer else 0 end as recorded,
 case when a.meta->>'errorClass' ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$' then a.meta->>'errorClass' end as "errorClass",
 a.meta->>'recoverable'='true' as recoverable,
 exists(select 1 from public.pr_audit_events r where r.kind='telemetry.recovered' and r.subject=a.id::text) as recovered
 from public.pr_audit_events a where a.kind in ('telemetry.product_events','telemetry.ai_call_events');

-- Configuration is a durable, explicit approval record. Empty means no new
-- real email dispatch. Founder/customer scopes never share approval or quota.
create table if not exists public.pr_delivery_cutovers (
 audience text not null check(audience in ('founder','customer')),
 channel text not null check(channel in ('email','push')),
 revision integer not null check(revision>0),
 mode text not null check(mode in ('canary_only','new_events_only','disabled')),
 not_before timestamptz not null,
 approved_at timestamptz not null,
 operator_id uuid not null,
 recipient_user_ids uuid[] not null default '{}',
 max_messages integer not null check(max_messages between 0 and 10000),
 template_version text not null check(length(template_version) between 1 and 80),
 approval_ref text not null check(approval_ref ~ '^[A-Za-z0-9_-]{1,40}$'),
 primary key(audience,channel,revision),
 check(mode!='canary_only' or cardinality(recipient_user_ids)>0)
);
alter table public.pr_delivery_cutovers enable row level security;
alter table public.pr_delivery_cutovers force row level security;
revoke all on public.pr_delivery_cutovers from public,anon,authenticated;
grant select,insert on public.pr_delivery_cutovers to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_delivery_cutovers' and policyname='service_only') then
  create policy service_only on public.pr_delivery_cutovers for all to service_role using(true) with check(true);
 end if;
end $$;

do $$ declare n text; begin
 foreach n in array array['business_product_observations','business_telemetry_health'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
end $$;

-- Original-tenant support. Reader roles receive fixed metadata only.
create table if not exists public.pr_support_tickets (
 id uuid primary key,workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 created_by uuid not null,category text not null check(category in ('technical','billing','account','other')),
 status text not null default 'open' check(status in ('open','waiting_customer','resolved')),
 revision integer not null default 1 check(revision>0),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 first_response_at timestamptz,resolved_at timestamptz
);
create table if not exists public.pr_support_messages (
 id uuid primary key default gen_random_uuid(),workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 ticket_id uuid not null references public.pr_support_tickets(id) on delete cascade,
 actor_id uuid not null,actor_role text not null check(actor_role in ('customer','founder')),
 body text not null check(length(body) between 1 and 8000),request_id uuid not null,fingerprint text not null,
 created_at timestamptz not null default now(),unique(workspace_id,request_id)
);
create index if not exists pr_support_tenant_recent on public.pr_support_tickets(workspace_id,updated_at desc);
alter table public.pr_support_tickets enable row level security;
alter table public.pr_support_tickets force row level security;
alter table public.pr_support_messages enable row level security;
alter table public.pr_support_messages force row level security;
revoke all on public.pr_support_tickets,public.pr_support_messages from public,anon,authenticated;
grant select,insert,update on public.pr_support_tickets to service_role;
grant select,insert on public.pr_support_messages to service_role;
do $$ declare n text; begin
 foreach n in array array['pr_support_tickets','pr_support_messages'] loop
  if not exists(select 1 from pg_policies where schemaname='public' and tablename=n and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)',n);
  end if;
 end loop;
end $$;
grant select(id,workspace_id,created_by,category,status,revision,created_at,updated_at,first_response_at,resolved_at)
 on public.pr_support_tickets to rafii_control_business_projection;
grant select(workspace_id,kind) on rafii_control.workspace_classifications to rafii_control_business_projection;
create or replace view rafii_control.business_support_tickets with(security_barrier=true) as
 select t.id::text,t.workspace_id::text as "workspaceId",t.category as title,t.category,t.status,t.revision,
 t.created_at as at,t.created_at as "createdAt",t.updated_at as "updatedAt",t.first_response_at as "firstResponseAt",t.resolved_at as "resolvedAt",
 'masked'::text as "identityVisibility"
 from public.pr_support_tickets t
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=t.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_tickets owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_tickets from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_tickets to rafii_control_reader;

-- Never hard-delete financial dispatch history. Workspace deletion cannot
-- cascade through a pending or completed financial action. The historical
-- tenant identifier has no cascading FK, so customer content can be removed
-- while the confirmed financial action stays recoverable.
create table if not exists public.pr_founder_refund_dispatches (
 action_id uuid primary key,workspace_id uuid not null,
 payment_intent_id text not null,amount_minor bigint not null check(amount_minor>0),currency text not null,
 operator_id uuid not null,created_at timestamptz not null default now(),
 state text not null check(state in ('prepared','uncertain','pending','requires_action','succeeded','failed','canceled')),
 refund_id text,result jsonb
);
alter table public.pr_founder_refund_dispatches enable row level security;
alter table public.pr_founder_refund_dispatches force row level security;
revoke all on public.pr_founder_refund_dispatches from public,anon,authenticated;
grant select,insert,update on public.pr_founder_refund_dispatches to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_founder_refund_dispatches' and policyname='service_only') then
  create policy service_only on public.pr_founder_refund_dispatches for all to service_role using(true) with check(true);
 end if;
end $$;

-- Immutable original-tenant financial history survives customer content
-- deletion. Current billing projections may change; every observed version and
-- deletion tombstone remains here, with its original timestamps in record.
-- The initial snapshot is explicitly observed-existing, never synthetic past
-- change history. No Founder reader role can read these raw financial rows.
create table if not exists public.pr_financial_history (
 id uuid primary key default gen_random_uuid(),workspace_id uuid,
 source_table text not null,operation text not null check(operation in ('observed_existing','INSERT','UPDATE','DELETE')),
 observed_at timestamptz not null default clock_timestamp(),record jsonb not null,
 fingerprint text not null,unique(source_table,operation,fingerprint)
);
alter table public.pr_financial_history enable row level security;
alter table public.pr_financial_history force row level security;
revoke all on public.pr_financial_history from public,anon,authenticated,service_role;
grant select,insert on public.pr_financial_history to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_financial_history' and policyname='service_only') then
  create policy service_only on public.pr_financial_history for all to service_role using(true) with check(true);
 end if;
end $$;
create or replace function public.pr_financial_history_immutable() returns trigger language plpgsql set search_path=pg_catalog as $$
begin raise exception 'Financial history is immutable' using errcode='42501'; end $$;
drop trigger if exists immutable_history on public.pr_financial_history;
create trigger immutable_history before update or delete on public.pr_financial_history for each row execute function public.pr_financial_history_immutable();
drop trigger if exists immutable_history_truncate on public.pr_financial_history;
create trigger immutable_history_truncate before truncate on public.pr_financial_history for each statement execute function public.pr_financial_history_immutable();
create or replace function public.pr_financial_history_capture() returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare value jsonb; begin
 value=case when TG_OP='DELETE' then to_jsonb(OLD) else to_jsonb(NEW) end;
 insert into public.pr_financial_history(workspace_id,source_table,operation,record,fingerprint)
 values((value->>'workspace_id')::uuid,TG_TABLE_NAME,TG_OP,value,encode(sha256(convert_to(value::text,'UTF8')),'hex')) on conflict do nothing;
 return case when TG_OP='DELETE' then OLD else NEW end;
end $$;
revoke all on function public.pr_financial_history_capture(),public.pr_financial_history_immutable() from public,anon,authenticated,service_role;
do $$ declare n text; begin
 foreach n in array array['pr_usage_ledger','pr_subscription_events','pr_subscription_snapshots','pr_invoices','pr_credit_orders','pr_credit_subscription_grants','pr_credit_refunds','pr_credit_disputes','pr_founder_refund_dispatches'] loop
  if to_regclass('public.'||n) is not null then
   execute format('insert into public.pr_financial_history(workspace_id,source_table,operation,record,fingerprint) select (to_jsonb(r)->>''workspace_id'')::uuid,%L,''observed_existing'',to_jsonb(r),encode(sha256(convert_to(to_jsonb(r)::text,''UTF8'')),''hex'') from public.%I r on conflict do nothing',n,n);
   execute format('drop trigger if exists financial_history_capture on public.%I',n);
   execute format('create trigger financial_history_capture after insert or update or delete on public.%I for each row execute function public.pr_financial_history_capture()',n);
  end if;
 end loop;
end $$;
-- The three direct account templates without V2 equivalents use an encrypted
-- original-tenant outbox. No raw mail body or destination reaches Control.
create table if not exists public.pr_transactional_mail (
 id uuid primary key,workspace_id uuid references public.pr_workspaces(id) on delete cascade,
 user_id uuid references public.pr_profiles(user_id) on delete cascade,kind text not null check(kind in ('invitation','welcome','trial_ended')),
 semantic_key text not null unique check(semantic_key ~ '^[a-f0-9]{64}$'),
 recipient_hash text not null check(recipient_hash ~ '^[a-f0-9]{64}$'),
 payload_cipher text not null,key_id text not null,
 occurred_at timestamptz not null,expires_at timestamptz not null,
 status text not null default 'queued' check(status in ('queued','dispatching','provider_accepted','delivered','uncertain','suppressed','cancelled','failed','bounced','complained')),
 lease_until timestamptz,provider_ref text,failure_code text,delivered_at timestamptz,
 created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
alter table public.pr_transactional_mail enable row level security;
alter table public.pr_transactional_mail force row level security;
revoke all on public.pr_transactional_mail from public,anon,authenticated;
grant select,insert,update,delete on public.pr_transactional_mail to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_transactional_mail' and policyname='service_only') then
  create policy service_only on public.pr_transactional_mail for all to service_role using(true) with check(true);
 end if;
end $$;
commit;
