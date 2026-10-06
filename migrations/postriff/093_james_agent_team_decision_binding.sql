-- Candidate only: immutable mission questions, one choice, positive attendance.
-- Existing duplicate legacy question tuples MUST be reconciled before applying;
-- the unique index deliberately fails instead of deleting or choosing a winner.
begin;
create table if not exists public.pr_agent_team_call_evidence (
  call_id uuid not null references public.pr_phone_calls(id) on delete restrict,
  evidence_kind text not null check(evidence_kind in ('human','media')),
  provider text not null check(provider in ('twilio','dial','telnyx')),
  source text not null,
  evidence_sha256 text not null check(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz not null,
  input_frames bigint, output_frames bigint,
  playback_ack_sha256 text check(playback_ack_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  primary key(call_id,evidence_kind),
  check((evidence_kind='human' and source='signed_provider_human_detection' and input_frames is null and output_frames is null and playback_ack_sha256 is null)
     or (evidence_kind='media' and source='authenticated_bidirectional_media' and input_frames is not null and output_frames is not null and input_frames>0 and output_frames>0 and playback_ack_sha256 is not null))
);
alter table public.pr_agent_team_call_evidence enable row level security;
alter table public.pr_agent_team_call_evidence force row level security;
revoke all on public.pr_agent_team_call_evidence from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_call_evidence to service_role;
do $$ begin
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_call_evidence' and policyname='service_evidence_read') then
    create policy service_evidence_read on public.pr_agent_team_call_evidence for select to service_role using(true);
  end if;
  if not exists(select 1 from pg_policies where schemaname='public' and tablename='pr_agent_team_call_evidence' and policyname='service_evidence_insert') then
    create policy service_evidence_insert on public.pr_agent_team_call_evidence for insert to service_role with check(true);
  end if;
end $$;

alter table public.pr_agent_team_decisions
  add column if not exists workspace_id uuid references public.pr_workspaces(id),
  add column if not exists question_sha256 text check(question_sha256 ~ '^[0-9a-f]{64}$'),
  add column if not exists authorization_sha256 text check(authorization_sha256 ~ '^[0-9a-f]{64}$'),
  add column if not exists registration_sha256 text check(registration_sha256 ~ '^[0-9a-f]{64}$'),
  add column if not exists execution_binding_sha256 text check(execution_binding_sha256 ~ '^[0-9a-f]{64}$'),
  add column if not exists completion_requirement_refs text[],
  add column if not exists attended_call_id uuid references public.pr_phone_calls(id),
  add column if not exists effect_key text check(effect_key ~ '^team-decision:[0-9a-f]{64}$');
create unique index if not exists pr_agent_team_one_question_choice
  on public.pr_agent_team_decisions(call_run_id,mission_id,scope_version,question_version);
create unique index if not exists pr_agent_team_decision_effect
  on public.pr_agent_team_decisions(effect_key) where effect_key is not null;
alter table public.pr_agent_team_decisions drop constraint if exists pr_agent_team_bound_decision;
alter table public.pr_agent_team_decisions add constraint pr_agent_team_bound_decision
  check((question_sha256 is null and workspace_id is null and authorization_sha256 is null and registration_sha256 is null
          and execution_binding_sha256 is null and completion_requirement_refs is null and attended_call_id is null and effect_key is null)
     or (question_sha256 is not null and workspace_id is not null and authorization_sha256 is not null and registration_sha256 is not null
          and execution_binding_sha256 is not null and completion_requirement_refs is not null and cardinality(completion_requirement_refs)>0
          and cardinality(completion_requirement_refs)<=100 and array_position(completion_requirement_refs,null) is null
          and array_to_string(completion_requirement_refs,',') ~ '^[0-9a-f]{64}(,[0-9a-f]{64})*$'
          and attended_call_id is not null and effect_key is not null and call_run_id is not null));

create or replace function postriff_private.agent_team_immutable_choice() returns trigger
language plpgsql set search_path=pg_catalog as $$ begin
  if (to_jsonb(new)-'execution_state') is distinct from (to_jsonb(old)-'execution_state') then
    raise exception 'Immutable mission decision';
  end if;
  return new;
end $$;
drop trigger if exists pr_agent_team_immutable_choice on public.pr_agent_team_decisions;
create trigger pr_agent_team_immutable_choice before update on public.pr_agent_team_decisions
  for each row execute function postriff_private.agent_team_immutable_choice();
create or replace function postriff_private.agent_team_immutable_question() returns trigger
language plpgsql set search_path=pg_catalog as $$ begin
  if (new.context->'agentTeamDecisionQuestion') is distinct from (old.context->'agentTeamDecisionQuestion') then
    raise exception 'Immutable mission question';
  end if;
  return new;
end $$;
drop trigger if exists pr_agent_team_immutable_question on public.pr_james_daily_call_runs;
create trigger pr_agent_team_immutable_question before update on public.pr_james_daily_call_runs
  for each row execute function postriff_private.agent_team_immutable_question();
revoke all on function postriff_private.agent_team_immutable_choice(),postriff_private.agent_team_immutable_question() from public,anon,authenticated;
grant execute on function postriff_private.agent_team_immutable_choice(),postriff_private.agent_team_immutable_question() to service_role;
alter table public.pr_agent_team_decisions enable row level security;
alter table public.pr_agent_team_decisions force row level security;
revoke all on public.pr_agent_team_decisions from public,anon,authenticated,service_role;
grant select,insert on public.pr_agent_team_decisions to service_role;
grant update(execution_state) on public.pr_agent_team_decisions to service_role;
do $$ declare t text; begin
  foreach t in array array['pr_agent_team_decisions','pr_agent_team_call_evidence'] loop
    if not exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
                  where n.nspname='public' and c.relname=t and c.relrowsecurity and c.relforcerowsecurity) then
      raise exception 'Agent Team evidence requires forced RLS';
    end if;
    if has_table_privilege('anon','public.'||t,'SELECT,INSERT,UPDATE,DELETE')
       or has_table_privilege('authenticated','public.'||t,'SELECT,INSERT,UPDATE,DELETE')
       or has_any_column_privilege('anon','public.'||t,'SELECT,INSERT,UPDATE')
       or has_any_column_privilege('authenticated','public.'||t,'SELECT,INSERT,UPDATE') then
      raise exception 'Agent Team evidence must remain service only';
    end if;
    if not has_table_privilege('service_role','public.'||t,'SELECT') or not has_table_privilege('service_role','public.'||t,'INSERT')
       or has_table_privilege('service_role','public.'||t,'DELETE') then
      raise exception 'Agent Team evidence grants are invalid';
    end if;
  end loop;
  if not exists(select 1 from pg_constraint c
                where c.conrelid='public.pr_agent_team_call_evidence'::regclass
                  and c.confrelid='public.pr_phone_calls'::regclass
                  and c.contype='f' and c.confdeltype in ('a','r')) then
    raise exception 'Attendance evidence must survive parent deletion attempts';
  end if;
  if has_any_column_privilege('service_role','public.pr_agent_team_call_evidence','UPDATE')
     or has_column_privilege('service_role','public.pr_agent_team_decisions','choice','UPDATE')
     or not has_column_privilege('service_role','public.pr_agent_team_decisions','execution_state','UPDATE') then
    raise exception 'Agent Team choice and evidence must remain immutable';
  end if;
end $$;
commit;
