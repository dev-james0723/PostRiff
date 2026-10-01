-- Approved LOCAL milestone only. Hosted apply needs its own reviewed authorization.
begin;
alter table rafii_control.query_receipts add column if not exists normalized_query jsonb not null default '{}';
alter table rafii_control.query_receipts add column if not exists calculated_at timestamptz;
alter table rafii_control.query_receipts add column if not exists source_versions jsonb not null default '{}';
alter table rafii_control.query_receipts add column if not exists coverage jsonb not null default '{"complete":false,"reason":"legacy_receipt"}';
do $$ declare c record; begin
 for c in select conname from pg_constraint where conrelid='rafii_control.query_receipts'::regclass
   and contype='c' and pg_get_constraintdef(oid) like '%execution_state%' loop
  execute format('alter table rafii_control.query_receipts drop constraint %I',c.conname);
 end loop;
 for c in select conname from pg_constraint where conrelid='rafii_control.admin_audit_log'::regclass
   and contype='c' and pg_get_constraintdef(oid) like '%result%' loop
  execute format('alter table rafii_control.admin_audit_log drop constraint %I',c.conname);
 end loop;
end $$;
alter table rafii_control.query_receipts add constraint rc_receipt_execution
 check(execution_state in ('policy_unavailable','local_synthetic','provider_observed_test','admitted_operational'));
alter table rafii_control.admin_audit_log add constraint rc_audit_outcome
 check(result in ('allowed','denied','succeeded','failed'));
create table if not exists rafii_control.github_check_snapshots (
 id uuid primary key,
 environment text not null check(environment='local'),
 source_request_id uuid not null,
 exact_sha text not null check(exact_sha ~ '^[0-9a-f]{40}$'),
 provenance text not null check(provenance in ('synthetic','provider_observed_test','admitted_operational')),
 observed_at timestamptz not null,
 payload_digest text not null check(payload_digest ~ '^[0-9a-f]{64}$'),
 payload jsonb not null check(octet_length(payload::text)<=131072),
 created_at timestamptz not null default now()
);
create index if not exists rc_github_snapshots_latest on rafii_control.github_check_snapshots(environment,observed_at desc,id);
alter table rafii_control.github_check_snapshots enable row level security;
alter table rafii_control.github_check_snapshots force row level security;
revoke all on rafii_control.github_check_snapshots from public,anon,authenticated,service_role,rafii_control_session;
grant select on rafii_control.github_check_snapshots to rafii_control_reader,rafii_control_ingest;
grant insert on rafii_control.github_check_snapshots to rafii_control_ingest;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='github_check_snapshots' and policyname='rc_github_read') then
  create policy rc_github_read on rafii_control.github_check_snapshots for select to rafii_control_reader,rafii_control_ingest
   using(environment=current_setting('rafii_control.environment',true));
 end if;
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='github_check_snapshots' and policyname='rc_github_insert') then
  create policy rc_github_insert on rafii_control.github_check_snapshots for insert to rafii_control_ingest
   with check(environment=current_setting('rafii_control.environment',true) and environment='local');
 end if;
end $$;
commit;
