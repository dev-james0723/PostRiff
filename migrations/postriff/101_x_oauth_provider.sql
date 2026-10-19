-- X uses the canonical provider ID 'x'. The legacy two-character minimum
-- rejected its OAuth start transaction before any provider request was made.
-- Keep the existing bound for every other provider and preserve rows/policies.
begin;
set local lock_timeout = '5s';

alter table public.pr_oauth_transactions
  drop constraint pr_oauth_transactions_provider_check;
alter table public.pr_oauth_transactions
  add constraint pr_oauth_transactions_provider_check
  check (provider = 'x' or length(provider) between 2 and 40);

commit;
