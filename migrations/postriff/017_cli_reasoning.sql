-- Additive CLI effort values; retain legacy values for existing runs and managed routes.
begin;
alter table public.pr_agent_runs drop constraint pr_agent_runs_reasoning_check;
alter table public.pr_agent_runs add constraint pr_agent_runs_reasoning_check
  check (reasoning in ('quick','standard','deep','low','medium','high','xhigh','max'));
commit;
