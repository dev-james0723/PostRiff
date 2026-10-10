-- Personal template-bound workflows. Existing Task Engine and CF2 remain execution and policy authority.
-- Candidate only; no production activation or migration application is implied.
begin;
create unique index if not exists pr_agent_autopilot_policy_identity on public.pr_agent_autopilot_policies(id,workspace_id,user_id);
create table if not exists public.pr_workflow_recipes (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 created_by uuid not null,
 version integer not null default 1 check(version>0),
 status text not null default 'draft' check(status in ('draft','active','paused','revoked')),
 config jsonb not null check(jsonb_typeof(config)='object' and octet_length(config::text)<=12000),
 policy_id uuid references public.pr_agent_autopilot_policies(id),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 event_cursor timestamptz,
 consecutive_failures integer not null default 0 check(consecutive_failures between 0 and 100),
 next_attempt_at timestamptz,
 unique(id,workspace_id,created_by),
 foreign key(workspace_id,created_by) references public.pr_memberships(workspace_id,user_id) on delete cascade,
 foreign key(policy_id,workspace_id,created_by) references public.pr_agent_autopilot_policies(id,workspace_id,user_id),
 check(status<>'active' or policy_id is not null)
);
create index if not exists pr_workflow_recipes_due on public.pr_workflow_recipes(workspace_id,updated_at,id) where status='active';
create index if not exists pr_workflow_recipes_owner on public.pr_workflow_recipes(workspace_id,created_by,updated_at desc);
create table if not exists public.pr_workflow_recipe_runs (
 id uuid primary key default gen_random_uuid(),
 recipe_id uuid not null,
 workspace_id uuid not null,
 created_by uuid not null,
 recipe_version integer not null check(recipe_version>0),
 occurrence_key text not null check(length(occurrence_key) between 1 and 160),
 task_id uuid not null references public.pr_agent_tasks(id) on delete cascade,
 policy_id uuid not null references public.pr_agent_autopilot_policies(id),
 inputs jsonb not null check(jsonb_typeof(inputs)='object' and octet_length(inputs::text)<=16000),
 report jsonb check(report is null or (jsonb_typeof(report)='object' and octet_length(report::text)<=100000)),
 created_at timestamptz not null default now(),
 completed_at timestamptz,
 settled boolean not null default false,
 foreign key(recipe_id,workspace_id,created_by) references public.pr_workflow_recipes(id,workspace_id,created_by) on delete cascade,
 unique(recipe_id,recipe_version,occurrence_key),
 unique(task_id),
 foreign key(task_id,workspace_id) references public.pr_agent_tasks(id,workspace_id) on delete cascade,
 foreign key(policy_id,workspace_id,created_by) references public.pr_agent_autopilot_policies(id,workspace_id,user_id)
);
create index if not exists pr_workflow_recipe_runs_owner on public.pr_workflow_recipe_runs(workspace_id,created_by,created_at desc,id desc);
create or replace function postriff_private.guard_workflow_recipe_run() returns trigger language plpgsql as $$
begin
 if (to_jsonb(new)-array['report','completed_at','settled']) is distinct from (to_jsonb(old)-array['report','completed_at','settled'])
   or (old.report is not null and new.report is distinct from old.report)
   or (old.completed_at is not null and new.completed_at is distinct from old.completed_at)
   or (old.settled and not new.settled)
   or (new.report is null) is distinct from (new.completed_at is null) then
  raise exception 'Recipe run identity and stored reports are immutable' using errcode='23514';
 end if;
 return new;
end $$;
revoke all on function postriff_private.guard_workflow_recipe_run() from public,anon,authenticated;
drop trigger if exists pr_workflow_recipe_run_guard on public.pr_workflow_recipe_runs;
create trigger pr_workflow_recipe_run_guard before update on public.pr_workflow_recipe_runs for each row execute function postriff_private.guard_workflow_recipe_run();
do $$ declare t text; begin
 foreach t in array array['pr_workflow_recipes','pr_workflow_recipe_runs'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('alter table public.%I force row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated',t);
  execute format('grant all on public.%I to service_role',t);
  if not exists(select 1 from pg_policies where schemaname='public' and tablename=t and policyname='service_only') then
   execute format('create policy service_only on public.%I for all to service_role using (true) with check (true)',t);
  end if;
 end loop;
end $$;
commit;
