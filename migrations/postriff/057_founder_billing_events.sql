-- Founder Admin v2 P1 (CONTRACTS §8.A, PRD §8.5): billing instrumentation, public schema only.
-- Additive and idempotent; reapplication must be safe. Nothing here references the rafii_control schema, so this file can
-- be applied to production before the Control schema exists and the billing webhook starts recording at once; the founder
-- projections over these tables are 063_founder_revenue_views.sql. No role-membership grant is made to any migration runner.
--
-- Contents: ids, enums, counts, amounts in native minor units and timestamps only. No provider payload, name, email,
-- address, card or tax detail is stored. Financial facts outlive an account (PRD §8.5, decision D4): workspace references
-- are set null on deletion and the row stays. retain_until stays null until D4 fixes a retention period; a purge may only
-- ever delete rows whose retain_until has passed.
begin;

-- One row per verified billing event that asserts a subscription state (Billing.process_webhook, written before the
-- subscription upsert, in the webhook's own transaction). applied=false marks an event that did not change
-- pr_subscriptions (stale/out-of-order or informational such as trial_will_end); it still records the state the provider
-- reported at event_at, so history can be replayed in event order. Pricing columns are null when the event carried no
-- subscription object (checkout, invoice events); discount_minor null with a price means "discount present but unknown".
create table if not exists public.pr_subscription_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (provider ~ '^[a-z][a-z0-9_]{0,39}$'),
  event_id text not null check (length(event_id) between 1 and 200),
  event_type text not null check (event_type ~ '^[a-z][a-z0-9_.]{0,79}$'),
  workspace_id uuid references public.pr_workspaces(id) on delete set null,
  provider_subscription_id text check (provider_subscription_id is null or length(provider_subscription_id) between 1 and 200),
  event_at timestamptz not null,
  applied boolean not null default false,
  prior_status text check (prior_status is null or prior_status in ('trial','active','past_due','grace','cancelled','expired')),
  new_status text check (new_status is null or new_status in ('trial','active','past_due','grace','cancelled','expired')),
  prior_terms text check (prior_terms is null or length(prior_terms) between 1 and 120),
  new_terms text check (new_terms is null or length(new_terms) between 1 and 120),
  "interval" text check ("interval" is null or "interval" in ('day','week','month','year')),
  interval_count integer check (interval_count is null or interval_count between 1 and 1000),
  unit_amount_minor bigint check (unit_amount_minor is null or unit_amount_minor between 0 and 100000000000),
  quantity integer check (quantity is null or quantity between 0 and 1000000),
  usage_type text check (usage_type is null or usage_type in ('licensed','metered')),
  currency text check (currency is null or currency ~ '^[a-z]{3}$'),
  discount_minor bigint check (discount_minor is null or discount_minor between 0 and 100000000000),
  discount_end timestamptz,
  cancel_at timestamptz,
  trial_end timestamptz,
  recorded_at timestamptz not null default now(),
  retain_until timestamptz,
  unique (provider, event_id)
);
create index if not exists pr_subscription_events_subscription_idx on public.pr_subscription_events(provider_subscription_id, event_at);
create index if not exists pr_subscription_events_workspace_idx on public.pr_subscription_events(workspace_id, event_at);
create index if not exists pr_subscription_events_event_at_idx on public.pr_subscription_events(event_at);

-- One row per invoice, every plan (credit-policy and legacy), written for every invoice.* event before the credit-grant
-- early return. The latest state wins by event time, and a paid invoice never moves back to open (billing.py upsert).
create table if not exists public.pr_invoices (
  invoice_id text primary key check (length(invoice_id) between 1 and 200),
  provider text not null check (provider ~ '^[a-z][a-z0-9_]{0,39}$'),
  workspace_id uuid references public.pr_workspaces(id) on delete set null,
  subscription_id text check (subscription_id is null or length(subscription_id) between 1 and 200),
  billing_reason text check (billing_reason is null or billing_reason ~ '^[a-z][a-z0-9_]{0,39}$'),
  period_start timestamptz,
  period_end timestamptz,
  amount_due bigint check (amount_due is null or amount_due between 0 and 100000000000),
  amount_paid bigint check (amount_paid is null or amount_paid between 0 and 100000000000),
  currency text check (currency is null or currency ~ '^[a-z]{3}$'),
  status text not null check (status in ('draft','open','paid','uncollectible','void')),
  payment_intent_id text check (payment_intent_id is null or length(payment_intent_id) between 1 and 200),
  livemode boolean not null default false,
  event_id text not null check (length(event_id) between 1 and 200),
  event_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  retain_until timestamptz
);
create index if not exists pr_invoices_workspace_idx on public.pr_invoices(workspace_id, event_at);
create index if not exists pr_invoices_status_idx on public.pr_invoices(status, event_at);
create index if not exists pr_invoices_payment_intent_idx on public.pr_invoices(payment_intent_id) where payment_intent_id is not null;

do $$ declare t text; begin
  foreach t in array array['pr_subscription_events','pr_invoices'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from public,anon,authenticated', t);
    execute format('grant select,insert,update,delete on public.%I to service_role', t);
    if not exists (select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
      execute format('create policy service_only on public.%I for all to service_role using(true) with check(true)', t);
    end if;
  end loop;
end $$;

-- Credit ledger rows (meta.credits, written only while POSTRIFF_CREDITS_ENABLED) are read by time for the founder credit
-- metrics; a partial index keeps those reads off the rest of the usage ledger.
create index if not exists pr_usage_ledger_credits_at_idx on public.pr_usage_ledger(at) where meta ? 'credits';

-- The daily snapshot (054, founder_cron.subscription_snapshot) also records the workspace's normalized MRR from its latest
-- billing events: null when unknown (no priced event), never the list price. The table exists only once 054 is applied;
-- 063 repeats these guards so either order works.
alter table if exists public.pr_subscription_snapshots add column if not exists mrr_minor bigint check (mrr_minor is null or mrr_minor >= 0);
alter table if exists public.pr_subscription_snapshots add column if not exists currency text check (currency is null or currency ~ '^[a-z]{3}$');
alter table if exists public.pr_subscription_snapshots add column if not exists "interval" text check ("interval" is null or "interval" in ('day','week','month','year'));
alter table if exists public.pr_subscription_snapshots add column if not exists interval_count integer check (interval_count is null or interval_count between 1 and 1000);
commit;
