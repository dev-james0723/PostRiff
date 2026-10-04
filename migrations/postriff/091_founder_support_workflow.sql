-- Original-tenant support workflow and masked metadata projections.
-- Original-tenant metadata and immutable workflow history. No message or PII projection.
alter table public.pr_support_tickets
 add column if not exists priority text not null default 'normal' check(priority in ('low','normal','high','urgent')),
 add column if not exists assignee_id uuid,
 add column if not exists duplicate_of uuid;

do $$ begin
 if not exists(select 1 from pg_constraint where conrelid='public.pr_support_tickets'::regclass and conname='pr_support_ticket_tenant_identity') then
  alter table public.pr_support_tickets add constraint pr_support_ticket_tenant_identity unique(workspace_id,id);
 end if;
 if not exists(select 1 from pg_constraint where conrelid='public.pr_support_tickets'::regclass and conname='pr_support_duplicate_tenant') then
  alter table public.pr_support_tickets add constraint pr_support_duplicate_tenant
   foreign key(workspace_id,duplicate_of) references public.pr_support_tickets(workspace_id,id) deferrable initially deferred;
 end if;
end $$;
alter table public.pr_support_tickets drop constraint if exists pr_support_tickets_status_check;
alter table public.pr_support_tickets add constraint pr_support_tickets_status_check
 check(status in ('open','waiting_customer','resolved','closed','spam','duplicate'));
do $$ begin
 if not exists(select 1 from pg_constraint where conrelid='public.pr_support_tickets'::regclass and conname='pr_support_duplicate_state') then
  alter table public.pr_support_tickets add constraint pr_support_duplicate_state
   check((status='duplicate' and duplicate_of is not null and duplicate_of<>id) or (status<>'duplicate' and duplicate_of is null));
 end if;
end $$;

create table if not exists public.pr_support_workflow_events (
 id uuid primary key default gen_random_uuid(),
 workspace_id uuid not null references public.pr_workspaces(id) on delete cascade,
 ticket_id uuid not null,request_id uuid not null,actor_id uuid not null,
 actor_role text not null check(actor_role in ('customer','founder')),
 kind text not null check(kind in ('created','message','status','triage','duplicate_link','duplicate_unlink','verified_recurrence')),
 fingerprint text not null,
 result_revision integer not null check(result_revision>0),
 from_status text,to_status text,from_priority text,to_priority text,
 from_assignee_id uuid,to_assignee_id uuid,related_ticket_id uuid,message_id uuid,
 occurred_at timestamptz not null default now(),observed_at timestamptz not null default now(),
 unique(workspace_id,request_id),
 foreign key(workspace_id,ticket_id) references public.pr_support_tickets(workspace_id,id) on delete cascade,
 foreign key(workspace_id,related_ticket_id) references public.pr_support_tickets(workspace_id,id) on delete cascade
);
create index if not exists pr_support_workflow_recent on public.pr_support_workflow_events(workspace_id,ticket_id,occurred_at,id);
alter table public.pr_support_workflow_events enable row level security;
alter table public.pr_support_workflow_events force row level security;
revoke all on public.pr_support_workflow_events from public,anon,authenticated,service_role;
grant select,insert on public.pr_support_workflow_events to service_role;
drop policy if exists service_only on public.pr_support_workflow_events;
create policy service_only on public.pr_support_workflow_events for all to service_role using(true) with check(true);
create or replace function public.pr_support_workflow_immutable() returns trigger language plpgsql set search_path=pg_catalog as $$
begin
 if TG_OP='DELETE' and not exists(select 1 from public.pr_workspaces where id=OLD.workspace_id) then return OLD; end if;
 raise exception 'Support workflow history is immutable within a retained tenant' using errcode='42501';
end $$;
drop trigger if exists support_workflow_immutable on public.pr_support_workflow_events;
create trigger support_workflow_immutable before update or delete on public.pr_support_workflow_events
 for each row execute function public.pr_support_workflow_immutable();
drop trigger if exists support_workflow_no_truncate on public.pr_support_workflow_events;
create trigger support_workflow_no_truncate before truncate on public.pr_support_workflow_events
 for each statement execute function public.pr_support_workflow_immutable();
revoke all on function public.pr_support_workflow_immutable() from public,anon,authenticated,service_role;

grant select(priority,assignee_id,duplicate_of) on public.pr_support_tickets to rafii_control_business_projection;
grant select(id,workspace_id,ticket_id,actor_role,kind,result_revision,from_status,to_status,from_priority,to_priority,
 from_assignee_id,to_assignee_id,related_ticket_id,message_id,occurred_at,observed_at)
 on public.pr_support_workflow_events to rafii_control_business_projection;

create or replace view rafii_control.business_support_tickets with(security_barrier=true) as
 select t.id::text,t.workspace_id::text as "workspaceId",t.category as title,t.category,t.status,t.revision,
 t.created_at as at,t.created_at as "createdAt",t.updated_at as "updatedAt",t.first_response_at as "firstResponseAt",t.resolved_at as "resolvedAt",
 'masked'::text as "identityVisibility",t.priority,t.assignee_id::text as "assigneeId",t.duplicate_of::text as "duplicateOfTicketId"
 from public.pr_support_tickets t
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=t.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_tickets owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_tickets from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_tickets to rafii_control_reader;

create or replace view rafii_control.business_support_workflow_events with(security_barrier=true) as
 select e.id::text,e.workspace_id::text as "workspaceId",e.ticket_id::text as "ticketId",e.actor_role as "actorRole",
 e.kind,e.result_revision as revision,e.from_status as "fromStatus",e.to_status as "toStatus",
 e.from_priority as "fromPriority",e.to_priority as "toPriority",e.from_assignee_id::text as "fromAssigneeId",e.to_assignee_id::text as "toAssigneeId",
 e.related_ticket_id::text as "relatedTicketId",e.message_id::text as "messageId",e.occurred_at as "occurredAt",e.observed_at as "observedAt"
 from public.pr_support_workflow_events e
 where not exists(select 1 from rafii_control.workspace_classifications c where c.workspace_id=e.workspace_id and c.kind in ('internal','test','demo'));
alter view rafii_control.business_support_workflow_events owner to rafii_control_business_projection;
revoke all on rafii_control.business_support_workflow_events from public,anon,authenticated,service_role;
grant select on rafii_control.business_support_workflow_events to rafii_control_reader;

-- Existing timestamps remain elapsed-time source facts. No historical workflow
-- events, business calendars, SLA numbers, survey answers or recurrence are invented.
