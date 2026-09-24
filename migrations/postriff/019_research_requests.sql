-- Durable at-most-once research dispatch. A pending row is never automatically retried.
begin;
create table if not exists public.pr_research_requests (
  workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
  idempotency_key text not null,
  request_digest text not null,
  status text not null check(status in ('pending','completed')),
  result jsonb,
  created_at timestamptz not null default now(),
  primary key(workspace_id,idempotency_key)
);
alter table public.pr_research_requests enable row level security;
alter table public.pr_research_requests force row level security;
revoke all on public.pr_research_requests from public,anon,authenticated;
grant all on public.pr_research_requests to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_research_requests' and policyname='trusted_write') then
    create policy trusted_write on public.pr_research_requests for all to service_role using(true) with check(true);
  end if;
end $$;
commit;
