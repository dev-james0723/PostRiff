-- Rafii Account Protection v2, H-1: direct browser reads must obey the same session rules as the hosted API.
--
-- The hosted API refuses a revoked session, a deleted account and an AAL1 session of an account that enforces
-- two-factor sign-in (hosted_app.supabase_verifier). The `authenticated` role can still read many public tables and
-- the private Storage bucket straight through the Supabase Data API with its JWT, and those policies only check
-- workspace membership. This adds one RESTRICTIVE select policy to every such table (and to storage.objects): it is
-- ANDed with the existing permissive policies, so tenant isolation is unchanged and the session rules now hold too.
--
-- Additive and reversible: drop the policies and the function to roll back. No grants, rows or existing policies
-- change. The service role bypasses RLS, so server code is unaffected.
begin;

create or replace function postriff_private.browser_session_ok() returns boolean
language sql stable security definer set search_path = '' as $$
  with claims as (
    select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb) as j
  ), session as (
    select (select auth.uid()) as uid,
           coalesce(c.j->>'session_id', nullif(current_setting('request.jwt.claim.session_id', true), '')) as sid,
           coalesce(c.j->>'aal', nullif(current_setting('request.jwt.claim.aal', true), '')) as aal
    from claims c
  )
  select s.uid is not null
     -- Every Supabase user JWT carries its session; a token without one is not a browser session.
     and s.sid is not null
     and not exists (select 1 from public.pr_session_revocations r where r.user_id = s.uid and r.session_id = s.sid)
     and not exists (select 1 from public.pr_account_tombstones t where t.user_id = s.uid)
     and (s.aal = 'aal2' or not exists (select 1 from public.pr_mfa_enforcement e where e.user_id = s.uid))
  from session s
$$;
revoke all on function postriff_private.browser_session_ok() from public, anon;
grant execute on function postriff_private.browser_session_ok() to authenticated;

-- Every RLS-protected public table the browser role may read, as of this migration. A later migration that grants
-- authenticated SELECT on a new table must add the same policy (tests/test_rafii_browser_session_guard.py checks).
do $$
declare t text;
begin
  for t in
    select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relrowsecurity
      and has_table_privilege('authenticated', c.oid, 'SELECT')
      and not exists (select 1 from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname and p.policyname = 'rapv2_browser_session')
  loop
    execute format('create policy rapv2_browser_session on public.%I as restrictive for select to authenticated using ((select postriff_private.browser_session_ok()))', t);
  end loop;
  if not exists (select 1 from pg_policies where schemaname = 'storage' and tablename = 'objects' and policyname = 'rapv2_browser_session') then
    create policy rapv2_browser_session on storage.objects as restrictive for select to authenticated using ((select postriff_private.browser_session_ok()));
  end if;
end $$;

-- A browser-readable table without row level security would not be covered by any policy: refuse to finish.
do $$ begin
  if exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity
      and has_table_privilege('authenticated', c.oid, 'SELECT')
  ) then raise exception 'A public table readable by authenticated has no row level security'; end if;
end $$;

commit;
