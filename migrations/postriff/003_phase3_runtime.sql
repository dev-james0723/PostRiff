-- Additive Phase 3 candidate. Apply only to explicitly authorized environments.
begin;
create table public.pr_runtime (
 workspace_id uuid primary key references public.pr_workspaces(id) on delete cascade,
 state jsonb not null check(jsonb_typeof(state)='object'),
 updated_at timestamptz not null default now()
);
alter table public.pr_runtime enable row level security;
alter table public.pr_runtime force row level security;
-- Includes device credential hashes. Never grant direct browser reads, even to owners.
revoke all on public.pr_runtime from public,anon,authenticated;
grant select,insert,update,delete on public.pr_runtime to service_role;
create policy runtime_service_only on public.pr_runtime for all to service_role using(true) with check(true);
commit;
