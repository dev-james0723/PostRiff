-- Account security: users who finished TOTP enrolment are recorded here, and the API then rejects
-- any session below AAL2 for them (hosted_app.supabase_verifier). Enrolment itself lives in Supabase
-- Auth; this table is only the server-side "must present a second factor" decision.
-- Service-role only: the browser never reads or writes it.
create table if not exists public.pr_mfa_enforcement (
  user_id uuid primary key,
  enforced_at timestamptz not null default now()
);

alter table public.pr_mfa_enforcement enable row level security;
alter table public.pr_mfa_enforcement force row level security;
revoke all on public.pr_mfa_enforcement from public, anon, authenticated;
grant all on public.pr_mfa_enforcement to service_role;
create policy mfa_service_only on public.pr_mfa_enforcement for all to service_role using (true) with check (true);
