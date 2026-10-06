-- A spoken candidate is not an authenticated decision or native authorization.
begin;
create table if not exists public.pr_agent_team_spoken_choices (
  call_run_id uuid not null references public.pr_james_daily_call_runs(id) on delete restrict,
  question_sha256 text not null check(question_sha256 ~ '^[0-9a-f]{64}$'),
  call_id uuid not null references public.pr_phone_calls(id) on delete restrict,
  choice text not null check(choice in ('continue','wait','needs_human')),
  candidate_sha256 text not null check(candidate_sha256 ~ '^[0-9a-f]{64}$'),
  document jsonb not null check(jsonb_typeof(document)='object'),
  captured_at timestamptz not null,
  primary key(call_run_id,question_sha256),
  unique(candidate_sha256)
);
alter table public.pr_agent_team_spoken_choices enable row level security;
alter table public.pr_agent_team_spoken_choices force row level security;
revoke all on public.pr_agent_team_spoken_choices from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_spoken_choices to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_spoken_choices' and policyname='service_spoken_read') then
    create policy service_spoken_read on public.pr_agent_team_spoken_choices for select to service_role using(true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_spoken_choices' and policyname='service_spoken_insert') then
    create policy service_spoken_insert on public.pr_agent_team_spoken_choices for insert to service_role with check(true);
  end if;
end $$;
drop trigger if exists pr_agent_team_immutable_spoken_choice on public.pr_agent_team_spoken_choices;
create trigger pr_agent_team_immutable_spoken_choice before update or delete on public.pr_agent_team_spoken_choices
  for each row execute function postriff_private.agent_team_immutable_registry();
alter table public.pr_agent_team_decisions add column if not exists spoken_choice_sha256 text
  references public.pr_agent_team_spoken_choices(candidate_sha256) on delete restrict;
commit;
