-- Disabled-by-default purchase scaffolding. No prices, packs or grants are activated.
begin;
create table public.pr_credit_packs (
 id text primary key, label text not null, policy_id text not null,
 price_id text not null, amount_cents bigint not null check(amount_cents>0),
 currency text not null check(currency ~ '^[a-z]{3}$'),
 millicredits bigint not null check(millicredits>0 and millicredits<=1000000000000),
 livemode boolean not null, active boolean not null default false
);
create table public.pr_credit_orders (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 actor uuid not null, pack_id text not null references public.pr_credit_packs(id),
 request_id text not null, policy_id text not null, price_id text not null,
 amount_cents bigint not null check(amount_cents>0), currency text not null,
 millicredits bigint not null check(millicredits>0), livemode boolean not null,
 status text not null default 'pending' check(status in ('pending','funded')),
 session_id text unique, payment_intent_id text unique, checkout_url text,
 grant_id uuid references public.pr_usage_ledger(id),
 reversed_millicredits bigint not null default 0 check(reversed_millicredits>=0 and reversed_millicredits<=millicredits),
 created_at timestamptz not null default now(), unique(workspace_id,request_id)
);
create table public.pr_credit_refunds (
 refund_id text primary key, payment_intent_id text not null,
 amount_cents bigint not null check(amount_cents>0), currency text not null,
 status text not null check(status in ('pending','requires_action','succeeded','failed','canceled')),
 event_created bigint not null
);
create index on public.pr_credit_refunds(payment_intent_id);
alter table public.pr_credit_packs enable row level security;
alter table public.pr_credit_packs force row level security;
alter table public.pr_credit_orders enable row level security;
alter table public.pr_credit_orders force row level security;
alter table public.pr_credit_refunds enable row level security;
alter table public.pr_credit_refunds force row level security;
revoke all on public.pr_credit_packs,public.pr_credit_orders,public.pr_credit_refunds from anon,authenticated;
grant select,insert,update,delete on public.pr_credit_packs,public.pr_credit_orders,public.pr_credit_refunds to service_role;
commit;
