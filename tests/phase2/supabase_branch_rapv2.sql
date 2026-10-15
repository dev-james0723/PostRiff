-- RAPv2 acceptance on a disposable Supabase development branch (never staging main, never production).
-- Run each block as a separate request; evidence: docs/rapv2/supabase-branch-evidence-2026-10-15.json.
-- 0. Apply migrations/postriff/119_rapv2_browser_session_guard.sql to the branch if its replay did not reach it.

-- 1. Synthetic fixtures.
insert into auth.users(id, instance_id, aud, role, email, email_confirmed_at)
values ('0a0a0a0a-0000-4000-8000-00000000000a','00000000-0000-0000-0000-000000000000','authenticated','authenticated','owner-a@example.invalid', now());
select public.pr_bootstrap('0a0a0a0a-0000-4000-8000-00000000000a','studio');  -- :workspace
insert into public.pr_sessions(user_id,session_id,client_label) values
  ('0a0a0a0a-0000-4000-8000-00000000000a','branch-live-session-000000001','Safari on iPhone'),
  ('0a0a0a0a-0000-4000-8000-00000000000a','branch-revoked-session-000001','Chrome on Mac');
insert into public.pr_session_revocations(user_id,session_id) values ('0a0a0a0a-0000-4000-8000-00000000000a','branch-revoked-session-000001');
insert into storage.objects(bucket_id,name,owner) values ('postriff-private', :'workspace' || '/synthetic/object.bin','0a0a0a0a-0000-4000-8000-00000000000a');

-- 2. A browser read, as PostgREST performs it. Repeat with session_id branch-revoked-session-000001, without
--    session_id, after inserting pr_mfa_enforcement (aal1, then aal2) and after inserting pr_account_tombstones.
begin;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"0a0a0a0a-0000-4000-8000-00000000000a","role":"authenticated","aal":"aal1","session_id":"branch-live-session-000000001"}', true);
select (select count(*) from public.pr_workspaces) as workspaces,
       (select count(*) from storage.objects where bucket_id='postriff-private') as private_objects,
       (select count(*) from public.pr_audit_events where kind like 'session.%') as person_session_events;
rollback;

-- 3. Guard coverage.
select (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p') and c.relrowsecurity and has_table_privilege('authenticated', c.oid, 'SELECT')) as browser_readable_tables,
       (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p') and c.relrowsecurity and has_table_privilege('authenticated', c.oid, 'SELECT')
          and not exists (select 1 from pg_policies p where p.schemaname='public' and p.tablename=c.relname and p.policyname='rapv2_browser_session' and p.permissive='RESTRICTIVE')) as unguarded,
       (select count(*) from pg_policies where schemaname='storage' and tablename='objects' and policyname='rapv2_browser_session' and permissive='RESTRICTIVE') as storage_guard,
       has_function_privilege('anon','postriff_private.browser_session_ok()','EXECUTE') as anon_can_call_guard;

-- 4. Privileges and forced RLS on the session-security tables.
select c.relname, c.relrowsecurity, c.relforcerowsecurity,
       has_table_privilege('anon', c.oid, 'SELECT') as anon_select, has_table_privilege('anon', c.oid, 'INSERT') as anon_insert,
       has_table_privilege('authenticated', c.oid, 'SELECT') as auth_select, has_table_privilege('authenticated', c.oid, 'INSERT') as auth_insert,
       has_table_privilege('authenticated', c.oid, 'UPDATE') as auth_update, has_table_privilege('authenticated', c.oid, 'DELETE') as auth_delete,
       has_table_privilege('service_role', c.oid, 'UPDATE') as service_update, has_table_privilege('service_role', c.oid, 'DELETE') as service_delete
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('pr_sessions','pr_session_revocations','pr_audit_events','pr_mfa_enforcement','pr_account_tombstones') order by 1;

-- 5. The browser role cannot write a session row (expect ERROR 42501).
begin;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"0a0a0a0a-0000-4000-8000-00000000000a","role":"authenticated","aal":"aal2","session_id":"branch-live-session-000000001"}', true);
insert into public.pr_sessions(user_id,session_id,client_label) values ('0a0a0a0a-0000-4000-8000-00000000000a','forged-by-browser-000000001','trusted');
rollback;
