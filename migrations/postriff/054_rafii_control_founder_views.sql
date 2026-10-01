-- Founder Admin v2 (P0). Additive only; apply after 053. Reapplication must be safe.
-- No operator gains a new capability here; enrollment stays a separate reviewed step.
-- Every view is a column-allowlisted, security_barrier projection owned by the non-login
-- business projection role. No payload bodies, drafts, addresses, keys or customer prose.
begin;
grant select(provider,cancel_at_period_end,updated_at) on public.pr_subscriptions to rafii_control_business_projection;
grant select(member_id,run_id,reservation_id,provider,model,estimated_usd_micro,idempotency_key,meta) on public.pr_usage_ledger to rafii_control_business_projection;
grant select(scope,window_kind,window_start,warn_usd_micro,stop_usd_micro,spent_usd_micro,reserved_usd_micro,status) on public.pr_budgets to rafii_control_business_projection;
grant select(id,workspace_id,kind,sent,created_at) on public.pr_notifications to rafii_control_business_projection;
grant select(id,workspace_id,event_type,severity,entity_type,entity_id,payload,occurred_at,resolved_at) on public.pr_notification_events to rafii_control_business_projection;
grant select(id,event_id,workspace_id,channel,status,attempts,failure_class,created_at,sent_at,delivered_at) on public.pr_notification_deliveries to rafii_control_business_projection;
grant select(id,workspace_id,kind,direction,provider,state,failure_class,requested_at,answered_at,ended_at,duration_seconds,telephony_cost_usd_micro,live_cost_usd_micro) on public.pr_phone_calls to rafii_control_business_projection;
grant select(id,workspace_id,actor,status,model,idempotency_key,created_at,updated_at) on public.pr_agent_runs to rafii_control_business_projection;
grant select(id,workspace_id,actor,kind,at) on public.pr_audit_events to rafii_control_business_projection;
grant select(workspace_id,task_kind,confidence,saved_seconds,occurred_at) on public.pr_time_savings_ledger to rafii_control_business_projection;
grant select(completed_at) on public.pr_data_requests to rafii_control_business_projection;

-- Subscriptions with the provider/cancel flags the activated metrics need; 053's business_subscriptions is unchanged.
create or replace view rafii_control.business_subscriptions_v2 with(security_barrier=true) as
 select s.workspace_id::text as "workspaceId",
 (select m.user_id::text from public.pr_memberships m join public.pr_profiles p on p.user_id=m.user_id and p.deleted_at is null
   where m.workspace_id=s.workspace_id and m.role='owner' and m.status='active' order by m.user_id limit 1) as "ownerId",
 s.plan_terms_id as "planTermsId",t.label as plan,s.status,s.provider,s.cancel_at_period_end as "cancelAtPeriodEnd",
 s.current_period_end as "currentPeriodEnd",case when t.status='active' then t.price_cents else null end as "amountMinor",t.currency,s.updated_at as "updatedAt"
 from public.pr_subscriptions s join public.pr_plan_terms t on t.id=s.plan_terms_id;
-- feature is a bounded label derived from the idempotency_key prefix; the raw key is never projected. reservationId lets the
-- metrics skip an estimated_unknown row once a later settle/release row reconciled the same reservation (billing.Ledger).
create index if not exists pr_usage_ledger_reservation_idx on public.pr_usage_ledger(workspace_id,reservation_id);
create or replace view rafii_control.business_usage_v2 with(security_barrier=true) as
 select u.id::text as id,u.workspace_id::text as "workspaceId",u.member_id::text as "memberId",u.run_id::text as "runId",u.reservation_id::text as "reservationId",u.kind,u.dimension,u.provider,u.model,
 u.quantity,u.unit,u.estimated_usd_micro as "estimatedUsdMicro",u.actual_usd_micro as "actualUsdMicro",u.cost_state as "costState",
 case when jsonb_typeof(u.meta->'aiUsageExempt')='boolean' then (u.meta->>'aiUsageExempt')::boolean else false end as "aiUsageExempt",
 -- Feature comes from the reservation: settle/reconcile/release rows carry generic keys (billing.Ledger: settle:<reservation>:<outcome>,
 -- reconcile:<reservation>), so read the first key of the same reservation (the reserve row itself, id = reservation_id, or a sibling)
 -- that still carries the caller prefix (run:, image:, voice:, ...). Rows without a reservation classify by their own key.
 case split_part(coalesce((select o.idempotency_key from public.pr_usage_ledger o
   where u.reservation_id is not null and o.workspace_id=u.workspace_id and (o.id=u.reservation_id or o.reservation_id=u.reservation_id)
     and split_part(o.idempotency_key,':',1) not in ('settle','reconcile','release') order by o.at,o.id limit 1), u.idempotency_key),':',1)
  when 'run' then 'writer' when 'image' then 'image' when 'agent-image' then 'image' when 'understanding' then 'understanding' when 'learning' then 'learning'
  when 'voice' then 'voice' when 'reply' then 'reply' when 'notes' then 'notes' when 'media' then 'notes' when 'research' then 'research'
  when 'agent' then 'agent' when 'agent-follow-ups' then 'agent' when 'agent-resume' then 'agent' when 'founder' then 'agent'
  when 'site-agent' then 'site_agent' when 'phone-live' then 'phone' when 'phone-tel' then 'phone' when 'radar' then 'radar'
  else 'other' end as feature,
 case when jsonb_typeof(u.meta->'credits'->'used')='number' then (u.meta->'credits'->>'used')::numeric::bigint else null end as "creditsUsedMilli",
 u.meta->>'costCenter' as "costCenter",u.at
 from public.pr_usage_ledger u;
create or replace view rafii_control.business_budgets with(security_barrier=true) as
 select scope,window_kind as "windowKind",window_start as "windowStart",warn_usd_micro as "warnUsdMicro",stop_usd_micro as "stopUsdMicro",
 spent_usd_micro as "spentUsdMicro",reserved_usd_micro as "reservedUsdMicro",status from public.pr_budgets;
create or replace view rafii_control.business_billing_notices with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",kind,created_at as "createdAt",sent from public.pr_notifications
 where kind in ('payment_failed','subscription_activated','trial_ending','trial_ended');
create or replace view rafii_control.business_notification_events with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",event_type as "eventType",severity,entity_type as "entityType",entity_id as "entityId",
 occurred_at as "occurredAt",resolved_at as "resolvedAt",payload->>'platform' as "payloadPlatform" from public.pr_notification_events;
create or replace view rafii_control.business_notification_deliveries with(security_barrier=true) as
 select id::text as id,event_id::text as "eventId",workspace_id::text as "workspaceId",channel,status,attempts,failure_class as "failureClass",
 created_at as "createdAt",sent_at as "sentAt",delivered_at as "deliveredAt" from public.pr_notification_deliveries;
create or replace view rafii_control.business_phone_calls with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",kind,direction,provider,state,failure_class as "failureClass",requested_at as "requestedAt",
 answered_at as "answeredAt",ended_at as "endedAt",duration_seconds as "durationSeconds",telephony_cost_usd_micro as "telephonyCostUsdMicro",live_cost_usd_micro as "liveCostUsdMicro"
 from public.pr_phone_calls;
create or replace view rafii_control.business_agent_runs with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",actor::text as actor,status,model,split_part(idempotency_key,':',1) as "idempotencyPrefix",
 created_at as "createdAt",updated_at as "updatedAt" from public.pr_agent_runs;
create or replace view rafii_control.business_audit_events with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",actor::text as actor,kind,at from public.pr_audit_events
 where kind in ('session.alerted','mfa.enabled','mfa.disabled','session.revoked_others','session.revoked','api_token.created','api_token.revoked');
create or replace view rafii_control.business_time_savings with(security_barrier=true) as
 select workspace_id::text as "workspaceId",task_kind as "taskKind",confidence,saved_seconds as "savedSeconds",occurred_at as "occurredAt" from public.pr_time_savings_ledger;
create or replace view rafii_control.business_data_requests_v2 with(security_barrier=true) as
 select id::text as id,workspace_id::text as "workspaceId",kind,status,requested_at as "requestedAt",completed_at as "completedAt" from public.pr_data_requests;

-- Daily subscription state, written by the consumer cron (founder_cron.subscription_snapshot over the consumer connection).
-- Metrics read it only through the view. This is a consumer `public` table, so like every other consumer table it keeps the
-- standard service_role grant/policy (CONTRACTS §2 "service_role writer"); the §0 rule that nothing is granted to
-- anon/authenticated/service_role applies to the rafii_control schema, whose objects below all revoke those roles.
create table if not exists public.pr_subscription_snapshots (
 day date not null,workspace_id uuid not null,plan_terms_id text not null,status text not null,provider text not null,
 primary key(day,workspace_id)
);
alter table public.pr_subscription_snapshots enable row level security;
alter table public.pr_subscription_snapshots force row level security;
revoke all on public.pr_subscription_snapshots from public,anon,authenticated;
grant select,insert,update on public.pr_subscription_snapshots to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_subscription_snapshots' and policyname='service_only') then
  create policy service_only on public.pr_subscription_snapshots for all to service_role using(true) with check(true);
 end if;
end $$;
grant select on public.pr_subscription_snapshots to rafii_control_business_projection;
create or replace view rafii_control.business_subscription_snapshots with(security_barrier=true) as
 select s.day,s.workspace_id::text as "workspaceId",s.plan_terms_id as "planTermsId",t.label as plan,s.status,s.provider
 from public.pr_subscription_snapshots s left join public.pr_plan_terms t on t.id=s.plan_terms_id;

do $$ declare n text; begin
 foreach n in array array['business_subscriptions_v2','business_usage_v2','business_budgets','business_billing_notices','business_notification_events',
  'business_notification_deliveries','business_phone_calls','business_agent_runs','business_audit_events','business_time_savings','business_data_requests_v2','business_subscription_snapshots'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
 -- Cash, refund and dispute projections exist only where the canonical purchase schema exists (053 pattern).
 if to_regclass('public.pr_credit_orders') is not null then
  grant select(livemode,payment_intent_id) on public.pr_credit_orders to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_payments_v2 with(security_barrier=true) as select id::text as id,workspace_id::text as "workspaceId",amount_cents as "amountMinor",upper(currency) as currency,status,livemode,payment_intent_id as "paymentIntentId",created_at as at from public.pr_credit_orders';
  alter view rafii_control.business_payments_v2 owner to rafii_control_business_projection;
  revoke all on rafii_control.business_payments_v2 from public,anon,authenticated,service_role;
  grant select on rafii_control.business_payments_v2 to rafii_control_reader;
 end if;
 if to_regclass('public.pr_credit_subscription_grants') is not null then
  grant select(invoice_id,workspace_id,subscription_id,plan_terms_id,billing_reason,period_start,period_end,amount_cents,currency,payment_intent_id,livemode,recorded_at) on public.pr_credit_subscription_grants to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_subscription_grants with(security_barrier=true) as select invoice_id as "invoiceId",workspace_id::text as "workspaceId",subscription_id as "subscriptionId",plan_terms_id as "planTermsId",billing_reason as "billingReason",to_timestamp(period_start) as "periodStart",to_timestamp(period_end) as "periodEnd",amount_cents as "amountMinor",upper(currency) as currency,livemode,recorded_at as "recordedAt" from public.pr_credit_subscription_grants';
  alter view rafii_control.business_subscription_grants owner to rafii_control_business_projection;
  revoke all on rafii_control.business_subscription_grants from public,anon,authenticated,service_role;
  grant select on rafii_control.business_subscription_grants to rafii_control_reader;
 end if;
 if to_regclass('public.pr_credit_refunds') is not null and to_regclass('public.pr_credit_orders') is not null and to_regclass('public.pr_credit_subscription_grants') is not null then
  grant select(refund_id,payment_intent_id,amount_cents,currency,status,event_created) on public.pr_credit_refunds to rafii_control_business_projection;
  -- Workspace attribution is nullable: legacy plan refunds have no payment-intent join path and stay "unattributed".
  execute 'create or replace view rafii_control.business_refunds with(security_barrier=true) as select r.refund_id as id,r.payment_intent_id as "paymentIntentId",r.amount_cents as "amountMinor",upper(r.currency) as currency,r.status,to_timestamp(r.event_created) as "eventCreated",coalesce(o.workspace_id,g.workspace_id)::text as "workspaceId" from public.pr_credit_refunds r left join public.pr_credit_orders o on o.payment_intent_id=r.payment_intent_id left join public.pr_credit_subscription_grants g on g.payment_intent_id=r.payment_intent_id';
  alter view rafii_control.business_refunds owner to rafii_control_business_projection;
  revoke all on rafii_control.business_refunds from public,anon,authenticated,service_role;
  grant select on rafii_control.business_refunds to rafii_control_reader;
 end if;
 if to_regclass('public.pr_credit_disputes') is not null and to_regclass('public.pr_credit_orders') is not null and to_regclass('public.pr_credit_subscription_grants') is not null then
  grant select(dispute_id,payment_intent_id,amount_cents,currency,status,withdrawn,event_created) on public.pr_credit_disputes to rafii_control_business_projection;
  execute 'create or replace view rafii_control.business_disputes with(security_barrier=true) as select d.dispute_id as id,d.payment_intent_id as "paymentIntentId",d.amount_cents as "amountMinor",upper(d.currency) as currency,d.status,d.withdrawn,to_timestamp(d.event_created) as "eventCreated",coalesce(o.workspace_id,g.workspace_id)::text as "workspaceId" from public.pr_credit_disputes d left join public.pr_credit_orders o on o.payment_intent_id=d.payment_intent_id left join public.pr_credit_subscription_grants g on g.payment_intent_id=d.payment_intent_id';
  alter view rafii_control.business_disputes owner to rafii_control_business_projection;
  revoke all on rafii_control.business_disputes from public,anon,authenticated,service_role;
  grant select on rafii_control.business_disputes to rafii_control_reader;
 end if;
end $$;

-- Workspace classification: customer metrics exclude internal/test/demo; founder_ops_cost includes only those.
create table if not exists rafii_control.workspace_classifications (
 workspace_id uuid primary key,kind text not null check(kind in ('customer','internal','test','demo')),
 reason text not null default '' check(length(reason)<=200),set_by uuid,
 environment text not null check(environment in ('local','staging','production')),set_at timestamptz not null default now()
);
create table if not exists rafii_control.founder_follow_ups (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 source_type text not null check(length(source_type) between 1 and 40),source_id text not null check(length(source_id) between 1 and 160),
 title text not null check(length(title) between 1 and 200),due_at timestamptz,time_zone text not null default 'America/Indiana/Indianapolis' check(length(time_zone)<=80),
 state text not null default 'draft' check(state in ('draft','scheduled','due','completed','cancelled','missed')),
 evidence jsonb not null default '{}' check(jsonb_typeof(evidence)='object'),revision integer not null default 1 check(revision>0),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 unique(operator_id,environment,source_type,source_id)
);
do $$ declare n text; begin
 foreach n in array array['workspace_classifications','founder_follow_ups'] loop
  execute format('alter table rafii_control.%I enable row level security',n);
  execute format('alter table rafii_control.%I force row level security',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role,rafii_control_reader',n);
  execute format('grant select,insert,update on rafii_control.%I to rafii_control_session',n);
 end loop;
 -- Classifications are environment-wide operator state (permissive policies OR together, so follow-ups get only the per-operator policy below).
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='workspace_classifications' and policyname='environment_rw') then
  create policy environment_rw on rafii_control.workspace_classifications for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;
-- The reader applies classifications inside fixed metric SQL; it never sees other environments.
grant select on rafii_control.workspace_classifications to rafii_control_reader;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='workspace_classifications' and policyname='control_reader') then
  create policy control_reader on rafii_control.workspace_classifications for select to rafii_control_reader using(environment=current_setting('rafii_control.environment',true));
 end if;
 -- Follow-up rows belong to one operator; a second founder in the same environment cannot read them.
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_follow_ups' and policyname='own_follow_ups') then
  create policy own_follow_ups on rafii_control.founder_follow_ups for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true))
   with check(environment=current_setting('rafii_control.environment',true) and operator_id::text=current_setting('rafii_control.operator',true));
 end if;
end $$;
-- The founder cron (session role) records source probes; the reader keeps its 049 read policy.
grant insert,update on rafii_control.source_health to rafii_control_session;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='source_health' and policyname='control_session_write') then
  create policy control_session_write on rafii_control.source_health for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;

-- Receipts for activated Live metrics are admitted operational reads; Demo receipts name the Demo dataset.
alter table rafii_control.query_receipts drop constraint if exists rc_receipt_execution;
alter table rafii_control.query_receipts add constraint rc_receipt_execution
 check(execution_state in ('policy_unavailable','local_synthetic','provider_observed_test','admitted_operational','demo_dataset'));
-- New capabilities are declared here; no operator row is changed.
alter table rafii_control.platform_operators drop constraint if exists platform_operators_capabilities_check;
alter table rafii_control.platform_operators add constraint platform_operators_capabilities_check
 check(capabilities <@ array['control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename',
  'incidents.ack','followups.write','control.settings','founder.agent.turn','founder.call.request']::text[]);
alter table rafii_control.admin_audit_log drop constraint if exists admin_audit_log_action_check;
alter table rafii_control.admin_audit_log add constraint admin_audit_log_action_check check(action in ('session.exchange','control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename',
 'incidents.ack','followups.write','control.settings','founder.agent.turn','founder.call.request','prohibited'));
commit;
