-- Founder contact policy, incidents, briefing schedules, reports and contact attempts (Founder Admin v2 P0, CONTRACTS §5).
-- Additive and idempotent (apply twice). Follows 053: forced RLS, environment GUC policies, no consumer table modified.
-- Nothing here enables a real call: live_delivery_enabled defaults to false and every attempt row is written by code
-- that ends 'suppressed' with a reason while the policy, the RAFII_FOUNDER_CALLS_ENABLED flag or the provider is off.
begin;

create table if not exists rafii_control.founder_contact_policy (
 operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 revision integer not null default 1 check(revision>0),
 live_delivery_enabled boolean not null default false,
 channels jsonb not null default '[]'::jsonb check(jsonb_typeof(channels)='array'),
 -- Opaque reference to the operator's own public.pr_phone_numbers row ('pr_phone_numbers:<user_id>'); never a number.
 destination_ref text check(destination_ref is null or length(destination_ref) between 1 and 120),
 quiet_start smallint not null default 1320 check(quiet_start between 0 and 1439),
 quiet_end smallint not null default 480 check(quiet_end between 0 and 1439),
 time_zone text not null default 'America/Indiana/Indianapolis' check(length(time_zone) between 1 and 64),
 daily_cap smallint not null default 2 check(daily_cap between 0 and 2),
 concurrent_cap smallint not null default 1 check(concurrent_cap between 0 and 1),
 event_allowlist text[] not null default '{}',
 budget_usd_micro_daily bigint not null default 0 check(budget_usd_micro_daily between 0 and 50000000),
 updated_at timestamptz not null default now(),
 primary key(operator_id,environment),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);

create table if not exists rafii_control.founder_briefing_schedules (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,
 environment text not null check(environment in ('local','staging','production')),
 kind text not null check(kind in ('daily','weekly')),
 local_time text not null check(local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
 weekdays smallint[] not null default '{}',
 time_zone text not null check(length(time_zone) between 1 and 64),
 enabled boolean not null default true,next_at timestamptz not null,
 revision integer not null default 1 check(revision>0),created_at timestamptz not null default now(),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);
create index if not exists rc_founder_schedules_due on rafii_control.founder_briefing_schedules(environment,next_at) where enabled;

create table if not exists rafii_control.founder_reports (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,
 environment text not null check(environment in ('local','staging','production')),
 kind text not null check(kind in ('daily','weekly','incident','test')),
 version integer not null check(version>0),generated_at timestamptz not null default now(),
 receipt_ids uuid[] not null default '{}',sections jsonb not null default '[]'::jsonb check(jsonb_typeof(sections)='array'),
 coverage jsonb not null default '{}'::jsonb check(jsonb_typeof(coverage)='object'),
 text text not null check(length(text) between 1 and 12000),
 unique(operator_id,environment,kind,version)
);

create table if not exists rafii_control.founder_briefing_occurrences (
 id uuid primary key default gen_random_uuid(),schedule_id uuid not null references rafii_control.founder_briefing_schedules(id) on delete cascade,
 environment text not null check(environment in ('local','staging','production')),
 local_date date not null,slot smallint not null check(slot between 0 and 1439),scheduled_at timestamptz not null,
 state text not null check(state in ('planned','claimed','delivered','missed','coalesced','failed')),
 lease_owner text check(lease_owner is null or length(lease_owner)<=120),lease_until timestamptz,
 report_id uuid references rafii_control.founder_reports(id),attempt_id uuid,
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 unique(schedule_id,local_date,slot)
);

create table if not exists rafii_control.founder_incidents (
 id uuid primary key default gen_random_uuid(),environment text not null check(environment in ('local','staging','production')),
 detector text not null check(detector in ('publish_failure_rate','source_silence','cost_anomaly','payment_failure_spike')),
 scope text not null check(length(scope) between 1 and 120),episode_key text not null check(length(episode_key) between 1 and 200),
 severity text not null check(severity in ('warning','critical')),
 state text not null check(state in ('open','acknowledged','investigating','mitigated','resolved')),
 opened_at timestamptz not null default now(),acknowledged_at timestamptz,resolved_at timestamptz,
 evidence jsonb not null default '{}'::jsonb check(jsonb_typeof(evidence)='object'),
 affected_count integer not null default 0 check(affected_count>=0),version integer not null default 1 check(version>0),
 unique(environment,detector,scope,episode_key)
);
create index if not exists rc_founder_incidents_open on rafii_control.founder_incidents(environment,opened_at desc) where state<>'resolved';

create table if not exists rafii_control.founder_incident_events (
 id uuid primary key default gen_random_uuid(),incident_id uuid not null references rafii_control.founder_incidents(id) on delete cascade,
 environment text not null check(environment in ('local','staging','production')),
 kind text not null check(kind in ('opened','updated','escalated','acknowledged','contact_planned','contact_suppressed','contact_dispatched','contact_cancelled','resolved','notified')),
 at timestamptz not null default now(),body jsonb not null default '{}'::jsonb check(jsonb_typeof(body)='object')
);
create index if not exists rc_founder_incident_events_incident on rafii_control.founder_incident_events(incident_id,at);

create table if not exists rafii_control.founder_incident_acks (
 incident_id uuid not null references rafii_control.founder_incidents(id) on delete cascade,version integer not null check(version>0),
 environment text not null check(environment in ('local','staging','production')),
 operator_id uuid not null,at timestamptz not null default now(),channel text not null check(channel in ('web','phone','agent')),
 primary key(incident_id,version)
);

create table if not exists rafii_control.founder_contact_attempts (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,
 environment text not null check(environment in ('local','staging','production')),
 purpose text not null check(purpose in ('incident','briefing','test')),source_id text not null check(length(source_id) between 1 and 80),
 idempotency_key text not null unique check(idempotency_key ~ '^founder:(incident|briefing|test):[A-Za-z0-9_-]{1,80}$'),
 -- phone.contracts.STATES vocabulary plus the founder planning states.
 state text not null check(state in ('planned','eligible','reserved','suppressed','requested','dialing','ringing','answered','live','ending','completed','busy','declined','no_answer','voicemail','failed','ambiguous','cancelled')),
 provider text check(provider is null or provider in ('fake','twilio','telnyx','dial')),provider_call_ref text check(provider_call_ref is null or length(provider_call_ref)<=100),
 phone_call_id uuid,reserved_usd_micro bigint not null default 0 check(reserved_usd_micro>=0),
 outcome jsonb not null default '{}'::jsonb check(jsonb_typeof(outcome)='object'),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
create index if not exists rc_founder_attempts_open on rafii_control.founder_contact_attempts(environment,created_at desc) where state in ('reserved','requested','dialing','ringing','answered','live','ending','ambiguous');
create index if not exists rc_founder_attempts_source on rafii_control.founder_contact_attempts(environment,purpose,source_id);

-- Forced RLS with the environment GUC, like 053 workspace_actions. The cron writer acts for every founder operator of
-- one environment, so rows are environment-scoped and the service layer binds operator_id to the verified principal.
do $$ declare n text; begin
 foreach n in array array['founder_contact_policy','founder_briefing_schedules','founder_reports','founder_briefing_occurrences',
                          'founder_incidents','founder_incident_events','founder_incident_acks','founder_contact_attempts'] loop
  execute format('alter table rafii_control.%I enable row level security',n);
  execute format('alter table rafii_control.%I force row level security',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role,rafii_control_reader',n);
  execute format('grant select,insert,update on rafii_control.%I to rafii_control_session',n);
  if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=n and policyname='founder_environment_all') then
   execute format('create policy founder_environment_all on rafii_control.%I for all to rafii_control_session using(environment=current_setting(''rafii_control.environment'',true)) with check(environment=current_setting(''rafii_control.environment'',true))',n);
  end if;
 end loop;
end $$;
grant delete on rafii_control.founder_briefing_schedules to rafii_control_session;
-- Phone playback (phone/session.founder_playback_prompt) reads the immutable report text, or the incident the call is
-- about, through the reader role only; attempts, acks, schedules and the policy stay session-only.
grant select on rafii_control.founder_reports,rafii_control.founder_incidents to rafii_control_reader;
do $$ declare n text; begin
 foreach n in array array['founder_reports','founder_incidents'] loop
  if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=n and policyname='control_reader') then
   execute format('create policy control_reader on rafii_control.%I for select to rafii_control_reader using(environment=current_setting(''rafii_control.environment'',true))',n);
  end if;
 end loop;
end $$;

-- founder_cron.probe writes source_health (049). 054 grants the same; both are idempotent.
grant insert,update on rafii_control.source_health to rafii_control_session;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='source_health' and policyname='founder_cron_source_health_write') then
  create policy founder_cron_source_health_write on rafii_control.source_health for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;

-- NUMBER_UNVERIFIED is decided from the operator's own verified phone row: verification state and last four digits only,
-- never the ciphertext, hash or key id. The session role may read any row of this projection, so the service layer
-- always filters by the verified operator id.
do $$ begin
 if not exists(select 1 from pg_roles where rolname='rafii_control_business_projection') then
  create role rafii_control_business_projection nologin nosuperuser bypassrls;
 end if;
end $$;
grant usage on schema public,rafii_control to rafii_control_business_projection;
grant select(user_id,verified_at,last_four) on public.pr_phone_numbers to rafii_control_business_projection;
create or replace view rafii_control.founder_phone_destinations with(security_barrier=true) as
 select n.user_id::text as "operatorId",n.verified_at is not null as verified,n.last_four as "lastFour" from public.pr_phone_numbers n;
alter view rafii_control.founder_phone_destinations owner to rafii_control_business_projection;
revoke all on rafii_control.founder_phone_destinations from public,anon,authenticated,service_role,rafii_control_reader;
grant select on rafii_control.founder_phone_destinations to rafii_control_session;

commit;
