-- James Daily Call: covering indexes for FK maintenance and reconciliation lookups.
begin;

create index if not exists pr_james_daily_call_runs_user
  on public.pr_james_daily_call_runs(user_id,created_at desc);
create index if not exists pr_james_daily_call_runs_workspace
  on public.pr_james_daily_call_runs(workspace_id,created_at desc);
create index if not exists pr_james_daily_call_runs_conversation
  on public.pr_james_daily_call_runs(conversation_id) where conversation_id is not null;
create index if not exists pr_james_daily_call_runs_first_call
  on public.pr_james_daily_call_runs(first_call_id) where first_call_id is not null;
create index if not exists pr_james_daily_call_runs_retry_call
  on public.pr_james_daily_call_runs(retry_call_id) where retry_call_id is not null;

commit;
