-- Opt-in credits: quotes only; balances and changes remain in pr_usage_ledger.
-- Does not activate prices, credit plans, payments or production spending.
begin;
create table public.pr_credit_quotes (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 actor uuid not null,
 policy_id text not null,
 request_digest text not null check(length(request_digest)=64),
 workspace_revision bigint not null,
 model text not null,
 provider text not null,
 max_millicredits bigint not null check(max_millicredits between 0 and 100000000),
 expires_at timestamptz not null,
 reservation_id uuid references public.pr_usage_ledger(id),
 created_at timestamptz not null default now()
);
alter table public.pr_credit_quotes enable row level security;
alter table public.pr_credit_quotes force row level security;
revoke all on public.pr_credit_quotes from anon,authenticated;
grant select,insert,update,delete on public.pr_credit_quotes to service_role;
create index on public.pr_credit_quotes(workspace_id,expires_at);
create index pr_usage_credit_projection on public.pr_usage_ledger(workspace_id,at) where meta ? 'credits';
commit;
