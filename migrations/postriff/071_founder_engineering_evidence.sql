-- Founder Admin › Engineering: attested CI evidence in hosted environments. Apply after 049-053. Additive and idempotent;
-- reapplication must be safe. Hosted application is a separate owner-approved step. No login and no role membership is
-- created here.
--
-- 052 kept the required-check manifest (github_check_snapshots) LOCAL-only, and 049/051 gave rafii_control_ingest no
-- write on engineering_evidence, so a hosted Engineering tab could only ever read 'suspected'. This lets the CI ingest
-- (src/rafii_control/ci_evidence.py, run by .github/workflows/founder-engineering-evidence.yml through a dedicated login
-- that can only SET ROLE rafii_control_ingest) record, in its session environment only:
--   1. github_check_snapshots manifests with provenance 'ci_attested' and the CI adapter's payload (schemaVersion 2, the
--      row's own exact SHA). Staging/production rows can only ever be 'ci_attested'; synthetic and manual captures stay
--      local. Rows stay insert-only (052 grants no UPDATE or DELETE).
--   2. engineering_evidence rows of kind 'check' from provider github or vercel, and later update only their verdict
--      columns (state, conclusion, failure_class, attested, observed_at); never the id, environment, kind, provider,
--      external id, exact SHA or required flag, and never a delete. A 'checks_passed' check row must be an attested
--      success (049 already requires attested + exact SHA; this adds the conclusion, NOT VALID so no old row is rescanned).
-- Forced RLS, the rafii_control.environment GUC scoping and the session/reader/ingest split are unchanged; the reader and
-- session roles gain nothing.
--
-- Deployment step (not this file), on PostgreSQL 15-17:
--   create role rafii_engineering_ingest login noinherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication
--     in role rafii_control_ingest;
-- then give it a generated credential (never in this repository) and store its DSN as the repository secret
-- RAFII_ENGINEERING_INGEST_DSN. ci_evidence.write refuses a privileged login and a login that inherits the role.
begin;

-- 1. github_check_snapshots: any environment, hosted rows CI-attested only. 052's unnamed environment/provenance checks are
--    found by expression (never a guessed name) and replaced by named ones.
do $$ declare c record; begin
 for c in select conname from pg_constraint where conrelid='rafii_control.github_check_snapshots'::regclass and contype='c'
   and conname not like 'rc\_github\_%'
   and (pg_get_constraintdef(oid) like '%environment%' or pg_get_constraintdef(oid) like '%provenance%') loop
  execute format('alter table rafii_control.github_check_snapshots drop constraint %I',c.conname);
 end loop;
end $$;
alter table rafii_control.github_check_snapshots drop constraint if exists rc_github_environment;
alter table rafii_control.github_check_snapshots add constraint rc_github_environment
 check(environment in ('local','staging','production'));
alter table rafii_control.github_check_snapshots drop constraint if exists rc_github_provenance;
alter table rafii_control.github_check_snapshots add constraint rc_github_provenance
 check(provenance in ('synthetic','provider_observed_test','admitted_operational','ci_attested'));
alter table rafii_control.github_check_snapshots drop constraint if exists rc_github_ci_attested;
alter table rafii_control.github_check_snapshots add constraint rc_github_ci_attested
 check((environment='local' or provenance='ci_attested')
   and (provenance<>'ci_attested' or coalesce(payload->>'schemaVersion'='2' and payload->>'adapterVersion'='github-ci-evidence/1'
     and payload->>'provenance'='ci_attested' and payload->>'exactSha'=exact_sha, false)));
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='github_check_snapshots' and policyname='rc_github_ci_insert') then
  create policy rc_github_ci_insert on rafii_control.github_check_snapshots for insert to rafii_control_ingest
   with check(environment=current_setting('rafii_control.environment',true) and provenance='ci_attested');
 end if;
end $$;

-- 2. engineering_evidence: check rows from github/vercel, verdict columns only.
grant insert on rafii_control.engineering_evidence to rafii_control_ingest;
grant update(state,conclusion,failure_class,attested,observed_at) on rafii_control.engineering_evidence to rafii_control_ingest;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='engineering_evidence' and policyname='control_ingest_insert') then
  create policy control_ingest_insert on rafii_control.engineering_evidence for insert to rafii_control_ingest
   with check(environment=current_setting('rafii_control.environment',true) and kind='check' and provider in ('github','vercel'));
 end if;
 if not exists(select 1 from pg_policies where schemaname='rafii_control' and tablename='engineering_evidence' and policyname='control_ingest_update') then
  create policy control_ingest_update on rafii_control.engineering_evidence for update to rafii_control_ingest
   using(environment=current_setting('rafii_control.environment',true) and kind='check' and provider in ('github','vercel'))
   with check(environment=current_setting('rafii_control.environment',true) and kind='check' and provider in ('github','vercel'));
 end if;
end $$;
alter table rafii_control.engineering_evidence drop constraint if exists rc_evidence_check_green;
alter table rafii_control.engineering_evidence add constraint rc_evidence_check_green
 check(kind<>'check' or state<>'checks_passed' or conclusion is not distinct from 'success') not valid;

commit;
