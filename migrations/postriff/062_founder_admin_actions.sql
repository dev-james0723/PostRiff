-- Founder account blocks (Founder Admin P1/P2, CONTRACTS §8.F; PRD §7.5 封鎖／解封). Public schema only: nothing here
-- references rafii_control, so this file can be applied to production before the Control schema exists. The Control side
-- (founder_action_requests, the reader projection) is 068_founder_actions_views.sql. Additive and idempotent (apply twice).
--
-- A block is a reversible fence a founder places only through a preview -> confirm with a fresh second factor in Control
-- (rafii_control.founder_actions). While a row is active (lifted_at is null) the consumer answers 403 ACCOUNT_BLOCKED to the
-- blocked user's sessions and API tokens, and freezes the workspaces in frozen_workspace_ids through their
-- state.accountBlock marker (postriff_phase2.operator_actions). Lifting sets lifted_at/by; nothing is cancelled or deleted.
-- Until this file is applied the consumer skips every block check (probe, never an error), so the code may ship first.
--
-- 045 pattern: forced RLS, one service_only policy, grants to service_role only. Ids, enums and timestamps only: no reason
-- text, message, email or address (approval_ref is a short reference such as a ticket id). Retention: an active block is
-- kept while active; a lifted block until retain_until (lift + 400 days), then the founder cron stage
-- account_block_retention deletes it. Rows go with the person or the workspace when either is deleted.
begin;

create table if not exists public.pr_account_blocks (
 id uuid primary key default gen_random_uuid(),
 user_id uuid references public.pr_profiles(user_id) on delete cascade,
 workspace_id uuid references public.pr_workspaces(id) on delete cascade,
 reason_code text not null check(reason_code in ('abuse','fraud','spam','security','payment','legal','other')),
 approval_ref text not null check(approval_ref ~ '^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,119}$'),
 frozen_workspace_ids uuid[] not null default '{}' check(cardinality(frozen_workspace_ids)<=100),
 blocked_at timestamptz not null default now(),
 blocked_by uuid not null,
 block_action_id uuid not null unique,
 lift_reason_code text check(lift_reason_code in ('resolved','mistake','appeal_granted','other')),
 lifted_at timestamptz,
 lifted_by uuid,
 lift_action_id uuid unique,
 retain_until timestamptz,
 check((user_id is null)<>(workspace_id is null)),
 check((lifted_at is null)=(lifted_by is null) and (lifted_at is null)=(lift_action_id is null)
       and (lifted_at is null)=(lift_reason_code is null) and (lifted_at is null)=(retain_until is null)),
 check(lifted_at is null or lifted_at>=blocked_at)
);
-- At most one active block per user and per workspace; the lookups the consumer runs on every session use these.
create unique index if not exists pr_account_blocks_active_user on public.pr_account_blocks(user_id) where lifted_at is null and user_id is not null;
create unique index if not exists pr_account_blocks_active_workspace on public.pr_account_blocks(workspace_id) where lifted_at is null and workspace_id is not null;
create index if not exists pr_account_blocks_retention on public.pr_account_blocks(retain_until) where retain_until is not null;

alter table public.pr_account_blocks enable row level security;
alter table public.pr_account_blocks force row level security;
revoke all on public.pr_account_blocks from public,anon,authenticated;
grant select,insert,update,delete on public.pr_account_blocks to service_role;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_account_blocks' and policyname='service_only') then
  create policy service_only on public.pr_account_blocks for all to service_role using(true) with check(true);
 end if;
end $$;

commit;
