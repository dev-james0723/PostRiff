-- Founder Admin v2 P1 (CONTRACTS §8.A): founder projections over the 057 billing instrumentation and the credit ledger.
-- Additive only; apply after 054 and 057. Reapplication must be safe. Every view is a column-allowlisted, security_barrier
-- projection owned by the non-login business projection role and readable only by rafii_control_reader (the 054 pattern).
-- No role-membership grant is made to any migration runner; hosted application is a separate owner-approved step.
begin;

-- 057 may have run before 054 created the snapshot table; make sure its columns exist before the view reads them.
alter table if exists public.pr_subscription_snapshots add column if not exists mrr_minor bigint check (mrr_minor is null or mrr_minor >= 0);
alter table if exists public.pr_subscription_snapshots add column if not exists currency text check (currency is null or currency ~ '^[a-z]{3}$');
alter table if exists public.pr_subscription_snapshots add column if not exists "interval" text check ("interval" is null or "interval" in ('day','week','month','year'));
alter table if exists public.pr_subscription_snapshots add column if not exists interval_count integer check (interval_count is null or interval_count between 1 and 1000);

grant select(id,provider,event_id,event_type,workspace_id,provider_subscription_id,event_at,applied,prior_status,new_status,prior_terms,new_terms,"interval",interval_count,
  unit_amount_minor,quantity,usage_type,currency,discount_minor,discount_end,cancel_at,trial_end,recorded_at) on public.pr_subscription_events to rafii_control_business_projection;
grant select(invoice_id,provider,workspace_id,subscription_id,billing_reason,period_start,period_end,amount_due,amount_paid,currency,status,payment_intent_id,livemode,
  event_at,recorded_at) on public.pr_invoices to rafii_control_business_projection;
grant select(day,workspace_id,plan_terms_id,status,provider,mrr_minor,currency,"interval",interval_count) on public.pr_subscription_snapshots to rafii_control_business_projection;

-- Subscription state as each billing event reported it. Plan labels come from the versioned terms; ids only, no payload.
create or replace view rafii_control.business_subscription_events with(security_barrier=true) as
 select e.id::text as id,e.provider,e.event_id as "eventId",e.event_type as "eventType",e.workspace_id::text as "workspaceId",
 e.provider_subscription_id as "providerSubscriptionId",e.event_at as "eventAt",e.applied,e.prior_status as "priorStatus",e.new_status as "newStatus",
 e.prior_terms as "priorTermsId",pt.label as "priorPlan",e.new_terms as "newTermsId",nt.label as "newPlan",e."interval",e.interval_count as "intervalCount",
 e.unit_amount_minor as "unitAmountMinor",e.quantity,e.usage_type as "usageType",upper(e.currency) as currency,e.discount_minor as "discountMinor",
 e.discount_end as "discountEnd",e.cancel_at as "cancelAt",e.trial_end as "trialEnd",e.recorded_at as "recordedAt"
 from public.pr_subscription_events e left join public.pr_plan_terms pt on pt.id=e.prior_terms left join public.pr_plan_terms nt on nt.id=e.new_terms;

create or replace view rafii_control.business_invoices with(security_barrier=true) as
 select i.invoice_id as "invoiceId",i.provider,i.workspace_id::text as "workspaceId",i.subscription_id as "subscriptionId",i.billing_reason as "billingReason",
 i.period_start as "periodStart",i.period_end as "periodEnd",i.amount_due as "amountDueMinor",i.amount_paid as "amountPaidMinor",upper(i.currency) as currency,
 i.status,i.payment_intent_id as "paymentIntentId",i.livemode,i.event_at as "eventAt",i.recorded_at as "recordedAt"
 from public.pr_invoices i;

-- The 054 snapshot view keeps its columns (054 must stay re-applicable); the MRR columns get their own projection.
create or replace view rafii_control.business_subscription_snapshots_v2 with(security_barrier=true) as
 select s.day,s.workspace_id::text as "workspaceId",s.plan_terms_id as "planTermsId",t.label as plan,s.status,s.provider,
 s.mrr_minor as "mrrMinor",upper(s.currency) as currency,s."interval",s.interval_count as "intervalCount"
 from public.pr_subscription_snapshots s left join public.pr_plan_terms t on t.id=s.plan_terms_id;

-- Credit ledger operations (credit_wallet.CreditBook): op, amounts, grant ids, expiry and allocation ids only. Present only
-- while credits are enabled; without POSTRIFF_CREDITS_ENABLED the ledger carries no credit rows and the metrics say so.
create or replace view rafii_control.business_credit_entries with(security_barrier=true) as
 select u.id::text as id,u.workspace_id::text as "workspaceId",u.reservation_id::text as "reservationId",u.kind,
 case when c->>'op' in ('grant','reverse','restore','reserve','settle') then c->>'op' else 'other' end as op,
 case when jsonb_typeof(c->'milli')='number' then (c->>'milli')::numeric::bigint end as milli,
 case when jsonb_typeof(c->'used')='number' then (c->>'used')::numeric::bigint end as "usedMilli",
 case when jsonb_typeof(c->'grantId')='string' then left(c->>'grantId',80) end as "grantId",
 case when jsonb_typeof(c->'expiresAt')='number' then (c->>'expiresAt')::double precision end as "expiresAtEpoch",
 case when coalesce(c->>'source','') ~ '^[a-z][a-z0-9-]{0,39}$' then c->>'source' else 'other' end as "grantSource",
 case when jsonb_typeof(c->'allocations')='array' then (select coalesce(jsonb_agg(jsonb_build_object('grantId',left(a->>'grantId',80),
   'milli',case when jsonb_typeof(a->'milli')='number' then (a->>'milli')::numeric::bigint end)),'[]'::jsonb) from jsonb_array_elements(c->'allocations') a) end as allocations,
 case when jsonb_typeof(u.meta->'aiUsageExempt')='boolean' then (u.meta->>'aiUsageExempt')::boolean else false end as "aiUsageExempt",
 u.at
 from public.pr_usage_ledger u cross join lateral (select u.meta->'credits' as c) x
 where u.meta ? 'credits' and jsonb_typeof(u.meta->'credits')='object';

do $$ declare n text; begin
 foreach n in array array['business_subscription_events','business_invoices','business_subscription_snapshots_v2','business_credit_entries'] loop
  execute format('alter view rafii_control.%I owner to rafii_control_business_projection',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role',n);
  execute format('grant select on rafii_control.%I to rafii_control_reader',n);
 end loop;
end $$;
commit;
