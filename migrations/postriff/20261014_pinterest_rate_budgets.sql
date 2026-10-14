-- Candidate only. Apply to an approved isolated DB first, then production only with release approval.
begin;
create table if not exists public.pr_pinterest_rate_budgets (
  budget_key text not null,
  window_start bigint not null,
  used integer not null check (used > 0),
  primary key (budget_key, window_start)
);
alter table public.pr_pinterest_rate_budgets enable row level security;
revoke all on public.pr_pinterest_rate_budgets from public, anon, authenticated;
grant select, insert, update, delete on public.pr_pinterest_rate_budgets to service_role;
comment on table public.pr_pinterest_rate_budgets is 'Server-only Pinterest rate reservations. Hashed app/account keys, no credentials or content. Delete windows older than 48 hours via separately approved maintenance.';
commit;
-- Rollback after pausing Pinterest: drop table public.pr_pinterest_rate_budgets;
-- Without this table the candidate fails closed; no publishing fallback is permitted.
