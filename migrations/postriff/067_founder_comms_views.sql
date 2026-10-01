-- Founder notices and notice preferences (Founder Admin P1/P2, CONTRACTS §8.E slice-comms). The slice's rafii_control
-- objects (CONTRACTS §8.0 "two migration files per slice"); the slice needs no public-schema object, so 061 is unused.
-- Additive and idempotent (apply twice). Follows 055: forced RLS, the environment GUC policy, grants to
-- rafii_control_session only; no consumer table is modified and no role membership is granted to anyone.
-- Content is fixed vocabulary only: titles built from detector/scope/report kind, ids, enums, counts and timestamps; no
-- customer text, addresses, message bodies or provider payloads. The founder_digest cron stage purges notices after 400 days.
begin;

-- One row per founder operator and environment: which founder notices may use email/push (the contact policy and the
-- RAFII_FOUNDER_EMAIL_ENABLED / RAFII_FOUNDER_PUSH_ENABLED flags still gate both), the daily digest and the quiet window.
create table if not exists rafii_control.founder_notification_preferences (
 operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 revision integer not null default 1 check(revision>0),
 events jsonb not null default '{}'::jsonb check(jsonb_typeof(events)='object'),
 digest_enabled boolean not null default true,
 digest_email boolean not null default true,
 digest_hour smallint not null default 9 check(digest_hour between 0 and 23),
 quiet_start smallint not null default 1320 check(quiet_start between 0 and 1439),
 quiet_end smallint not null default 480 check(quiet_end between 0 and 1439),
 time_zone text not null default 'America/Indiana/Indianapolis' check(length(time_zone) between 1 and 64),
 updated_at timestamptz not null default now(),
 primary key(operator_id,environment),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);

-- The founder's in-app centre: every founder notice for every active founder operator, whatever the consumer notification
-- flags say. `channels` records the deterministic plan per channel (mode, reason, failing gates); `digest_state` marks the
-- notices the next daily digest summarises (`digest_id` = that digest notice).
create table if not exists rafii_control.founder_notices (
 id uuid primary key default gen_random_uuid(),operator_id uuid not null,
 environment text not null check(environment in ('local','staging','production')),
 event_type text not null check(event_type in ('founder.incident_opened','founder.incident_recovered','founder.briefing_ready',
                                                'founder.source_unavailable','founder.digest_ready','founder.test_notice')),
 severity text not null check(severity in ('info','warning','critical','security')),
 subject_type text not null check(subject_type in ('founder_incident','founder_report','founder_digest','founder_test')),
 subject_id text not null check(subject_id ~ '^[A-Za-z0-9_-]{1,80}$'),
 dedupe_key text not null check(length(dedupe_key) between 1 and 200),
 title text not null check(length(title) between 1 and 200),
 href text not null check(length(href) between 1 and 200 and href like '/founder%'),
 channels jsonb not null default '{}'::jsonb check(jsonb_typeof(channels)='object'),
 facts jsonb not null default '{}'::jsonb check(jsonb_typeof(facts)='object'),
 digest_state text not null default 'none' check(digest_state in ('none','pending','included')),
 digest_id uuid,
 created_at timestamptz not null default now(),read_at timestamptz,
 unique(operator_id,environment,dedupe_key),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);
create index if not exists rc_founder_notices_recent on rafii_control.founder_notices(operator_id,environment,created_at desc);
create index if not exists rc_founder_notices_digest on rafii_control.founder_notices(operator_id,environment,created_at) where digest_state='pending';
create index if not exists rc_founder_notices_retention on rafii_control.founder_notices(environment,created_at);

do $$ declare n text; begin
 foreach n in array array['founder_notification_preferences','founder_notices'] loop
  execute format('alter table rafii_control.%I enable row level security',n);
  execute format('alter table rafii_control.%I force row level security',n);
  execute format('revoke all on rafii_control.%I from public,anon,authenticated,service_role,rafii_control_reader',n);
  execute format('grant select,insert,update on rafii_control.%I to rafii_control_session',n);
  if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename=n and policyname='founder_environment_all') then
   execute format('create policy founder_environment_all on rafii_control.%I for all to rafii_control_session using(environment=current_setting(''rafii_control.environment'',true)) with check(environment=current_setting(''rafii_control.environment'',true))',n);
  end if;
 end loop;
end $$;
-- Retention: only the founder_digest stage deletes, and only notices older than 400 days.
grant delete on rafii_control.founder_notices to rafii_control_session;

commit;
