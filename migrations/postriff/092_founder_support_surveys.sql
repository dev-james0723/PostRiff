-- Forward-only in-app support survey collection. No backfill or outbound notice.
do $$ begin
 if not exists(select 1 from pg_constraint where conrelid='public.pr_support_tickets'::regclass and conname='pr_support_ticket_recipient_identity') then
  alter table public.pr_support_tickets add constraint pr_support_ticket_recipient_identity unique(workspace_id,id,created_by);
 end if;
 if not exists(select 1 from pg_constraint where conrelid='public.pr_support_workflow_events'::regclass and conname='pr_support_workflow_tenant_identity') then
  alter table public.pr_support_workflow_events add constraint pr_support_workflow_tenant_identity unique(workspace_id,id);
 end if;
end $$;
create table if not exists public.pr_support_survey_offers (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 ticket_id uuid not null,recipient_id uuid not null,
 resolution_event_id uuid not null,resolution_revision integer not null check(resolution_revision>0),
 resolved_at timestamptz not null,offered_at timestamptz not null default now(),
 source_version text not null check(source_version='in_app_support_csat_yes_no/v1'),
 unique(workspace_id,id),unique(workspace_id,id,recipient_id),unique(workspace_id,resolution_event_id),
 foreign key(workspace_id,ticket_id,recipient_id) references public.pr_support_tickets(workspace_id,id,created_by) on delete cascade,
 foreign key(workspace_id,resolution_event_id) references public.pr_support_workflow_events(workspace_id,id) on delete cascade
);
create table if not exists public.pr_support_survey_responses (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 survey_id uuid not null,actor_id uuid not null,request_id uuid not null,fingerprint text not null,
 helpful boolean not null,answered_at timestamptz not null default now(),
 source_version text not null check(source_version='in_app_support_csat_yes_no/v1'),
 unique(workspace_id,request_id),unique(workspace_id,survey_id),
 foreign key(workspace_id,survey_id,actor_id) references public.pr_support_survey_offers(workspace_id,id,recipient_id) on delete cascade
);
create index if not exists pr_support_survey_ticket on public.pr_support_survey_offers(workspace_id,ticket_id,offered_at,id);
alter table public.pr_support_survey_offers enable row level security;
alter table public.pr_support_survey_offers force row level security;
alter table public.pr_support_survey_responses enable row level security;
alter table public.pr_support_survey_responses force row level security;
revoke all on public.pr_support_survey_offers,public.pr_support_survey_responses from public,anon,authenticated,service_role;
grant select,insert on public.pr_support_survey_offers,public.pr_support_survey_responses to service_role;
drop policy if exists service_only on public.pr_support_survey_offers;
create policy service_only on public.pr_support_survey_offers for all to service_role using(true) with check(true);
drop policy if exists service_only on public.pr_support_survey_responses;
create policy service_only on public.pr_support_survey_responses for all to service_role using(true) with check(true);
drop trigger if exists support_survey_offer_immutable on public.pr_support_survey_offers;
create trigger support_survey_offer_immutable before update or delete on public.pr_support_survey_offers for each row execute function public.pr_support_workflow_immutable();
drop trigger if exists support_survey_response_immutable on public.pr_support_survey_responses;
create trigger support_survey_response_immutable before update or delete on public.pr_support_survey_responses for each row execute function public.pr_support_workflow_immutable();
drop trigger if exists support_survey_offer_no_truncate on public.pr_support_survey_offers;
create trigger support_survey_offer_no_truncate before truncate on public.pr_support_survey_offers for each statement execute function public.pr_support_workflow_immutable();
drop trigger if exists support_survey_response_no_truncate on public.pr_support_survey_responses;
create trigger support_survey_response_no_truncate before truncate on public.pr_support_survey_responses for each statement execute function public.pr_support_workflow_immutable();
grant select(id,workspace_id,ticket_id,resolution_event_id,resolution_revision,resolved_at,offered_at,source_version)
 on public.pr_support_survey_offers to rafii_control_business_projection;
grant select(id,workspace_id,survey_id,helpful,answered_at,source_version)
 on public.pr_support_survey_responses to rafii_control_business_projection;
create or replace view rafii_control.business_support_survey_offers with(security_barrier=true) as
 select o.id::text,o.workspace_id::text as "workspaceId",o.ticket_id::text as "ticketId",
 o.resolution_event_id::text as "resolutionEventId",o.resolution_revision as "resolutionRevision",
 o.resolved_at as "resolvedAt",o.offered_at as "offeredAt",o.source_version as "sourceVersion"
 from public.pr_support_survey_offers o
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=o.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_survey_offers owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_survey_offers from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_survey_offers to rafii_control_reader;
create or replace view rafii_control.business_support_survey_responses with(security_barrier=true) as
 select r.id::text,r.workspace_id::text as "workspaceId",r.survey_id::text as "surveyId",r.helpful,r.answered_at as "answeredAt",r.source_version as "sourceVersion"
 from public.pr_support_survey_responses r
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=r.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_survey_responses owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_survey_responses from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_survey_responses to rafii_control_reader;
