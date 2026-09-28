-- Supabase hosted Auth currently supports passkey sign-in, but rejects WebAuthn MFA enrollment.
-- Preserve historical MFA approvals while allowing a fresh, separate passkey session to prove a
-- returning caller's account identity.  One passkey session may authorize at most one action.
alter table public.pr_phone_auth_challenges
  drop constraint if exists pr_phone_auth_challenges_approved_factor_kind_check;

alter table public.pr_phone_auth_challenges
  add constraint pr_phone_auth_challenges_approved_factor_kind_check
  check(approved_factor_kind is null or approved_factor_kind in ('webauthn','passkey'));

create unique index pr_phone_auth_passkey_session_once
  on public.pr_phone_auth_challenges(approved_session_id)
  where approved_factor_kind='passkey';

-- A passkey-created session is an ephemeral proof, not a reusable capability.  This private ledger
-- makes the one-action rule apply across call approval and trusted-caller revocation alike.
create table public.pr_phone_passkey_proof_uses (
  session_id text primary key check(session_id ~ '^[A-Za-z0-9_-]{16,160}$'),
  user_id uuid not null references public.pr_profiles(user_id) on delete cascade,
  purpose text not null check(purpose in ('call_approve','trusted_caller_revoke')),
  subject_id uuid not null,
  used_at timestamptz not null
);
create index pr_phone_passkey_proof_user_time on public.pr_phone_passkey_proof_uses(user_id,used_at desc);
alter table public.pr_phone_passkey_proof_uses enable row level security;
alter table public.pr_phone_passkey_proof_uses force row level security;
revoke all on public.pr_phone_passkey_proof_uses from public,anon,authenticated;
grant all on public.pr_phone_passkey_proof_uses to service_role;
create policy service_only on public.pr_phone_passkey_proof_uses
  for all to service_role using(true) with check(true);
