-- FINAL-06: one-time credit purchases beyond the happy path. Like 021, nothing here activates a
-- pack, price or grant. Adds: order end states, disputes, and a durable inbox for verified payment
-- events that could not be applied (kept for review instead of failing until the provider gives up).
-- The inbox stores the minimal parsed event (identifiers, amounts, status), never raw payloads,
-- customer details or card data.
begin;
alter table public.pr_credit_orders drop constraint if exists pr_credit_orders_status_check;
alter table public.pr_credit_orders add constraint pr_credit_orders_status_check check (status in ('pending','funded','expired','failed'));
alter table public.pr_credit_orders add column if not exists closed_at timestamptz;

create table if not exists public.pr_credit_disputes (
 dispute_id text primary key,
 payment_intent_id text not null,
 amount_cents bigint not null check (amount_cents > 0),
 currency text not null check (currency ~ '^[a-z]{3}$'),
 status text not null check (length(status) between 1 and 40),
 withdrawn boolean not null,
 event_created bigint not null
);
create index if not exists pr_credit_disputes_payment_idx on public.pr_credit_disputes(payment_intent_id);

create table if not exists public.pr_credit_payment_inbox (
 event_id text primary key,
 kind text not null check (length(kind) between 1 and 80),
 event_created bigint not null,
 livemode boolean not null,
 payload_digest text not null check (length(payload_digest) = 64),
 event jsonb not null default '{}' check (jsonb_typeof(event) = 'object'),
 status text not null check (status in ('needs_review','resolved')),
 reason text not null check (length(reason) between 1 and 200),
 received_at timestamptz not null default now(),
 resolved_at timestamptz,
 resolution jsonb
);

-- FINAL-07: monthly plan credits, one row per paid plan invoice (candidate policy; plans stay inactive).
create table if not exists public.pr_credit_subscription_grants (
 invoice_id text primary key,
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 subscription_id text,
 plan_terms_id text not null,
 billing_reason text not null default '',
 period_start bigint,
 period_end bigint,
 amount_cents bigint not null check (amount_cents >= 0),
 currency text not null check (currency ~ '^[a-z]{3}$'),
 payment_intent_id text,
 millicredits bigint not null check (millicredits >= 0),
 grant_id uuid references public.pr_usage_ledger(id),
 reversed_millicredits bigint not null default 0 check (reversed_millicredits >= 0 and reversed_millicredits <= millicredits),
 livemode boolean not null,
 note text not null default '' check (length(note) <= 200),
 recorded_at timestamptz not null default now()
);
create index if not exists pr_credit_subscription_grants_payment_idx on public.pr_credit_subscription_grants(payment_intent_id);

alter table public.pr_credit_subscription_grants enable row level security;
alter table public.pr_credit_subscription_grants force row level security;
alter table public.pr_credit_disputes enable row level security;
alter table public.pr_credit_disputes force row level security;
alter table public.pr_credit_payment_inbox enable row level security;
alter table public.pr_credit_payment_inbox force row level security;
revoke all on public.pr_credit_disputes, public.pr_credit_payment_inbox, public.pr_credit_subscription_grants from anon, authenticated;
grant select, insert, update on public.pr_credit_disputes, public.pr_credit_payment_inbox, public.pr_credit_subscription_grants to service_role;
commit;
