-- Founder ops workspace setting (CONTRACTS §8.H). rafii_control only; additive and idempotent (apply twice).
-- One row per founder operator and environment naming the internal workspace Founder Rafii runs in. Created from Settings
-- (control.settings with a fresh second factor); RAFII_FOUNDER_OPS_WORKSPACE_ID, when set, still wins.
begin;
create table if not exists rafii_control.founder_settings (
 operator_id uuid not null,environment text not null check(environment in ('local','staging','production')),
 ops_workspace_id uuid,
 updated_at timestamptz not null default now(),
 primary key(operator_id,environment),
 foreign key(operator_id,environment) references rafii_control.platform_operators(user_id,environment)
);
alter table rafii_control.founder_settings enable row level security;
alter table rafii_control.founder_settings force row level security;
revoke all on rafii_control.founder_settings from public,anon,authenticated,service_role,rafii_control_reader;
grant select,insert,update on rafii_control.founder_settings to rafii_control_session;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='founder_settings' and policyname='founder_environment_all') then
  create policy founder_environment_all on rafii_control.founder_settings for all to rafii_control_session
   using(environment=current_setting('rafii_control.environment',true)) with check(environment=current_setting('rafii_control.environment',true));
 end if;
end $$;
commit;
