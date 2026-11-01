-- Candidate only. Requires separate exact canonical-production migration approval.
begin;
set local lock_timeout = '5s';
create table if not exists public.pr_pinterest_trial_intents (
  authority_hash text not null check (authority_hash ~ '^[0-9a-f]{64}$'),
  intent_hash text not null check (intent_hash ~ '^[0-9a-f]{64}$'),
  pin_id text check (pin_id is null or pin_id ~ '^[0-9]{5,30}$'),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  primary key (authority_hash, intent_hash),
  unique (authority_hash, pin_id),
  check (expires_at > created_at)
);
-- No workspace FK: the independent response transaction must not wait for the caller's workspace row lock.
alter table public.pr_pinterest_trial_intents enable row level security;
alter table public.pr_pinterest_trial_intents force row level security;
revoke all on public.pr_pinterest_trial_intents from public, anon, authenticated, service_role;
grant select, insert on public.pr_pinterest_trial_intents to service_role;
grant update (pin_id) on public.pr_pinterest_trial_intents to service_role;

create or replace function public.pr_pinterest_trial_intent_immutable()
returns trigger language plpgsql set search_path = pg_catalog as $$
begin
  if new.authority_hash is distinct from old.authority_hash
     or new.intent_hash is distinct from old.intent_hash
     or new.created_at is distinct from old.created_at
     or new.expires_at is distinct from old.expires_at
     or (old.pin_id is not null and new.pin_id is distinct from old.pin_id) then
    raise exception 'Pinterest Trial response journal is immutable' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function public.pr_pinterest_trial_intent_immutable() from public, anon, authenticated;
grant execute on function public.pr_pinterest_trial_intent_immutable() to service_role;
drop trigger if exists pr_pinterest_trial_intent_immutable on public.pr_pinterest_trial_intents;
create trigger pr_pinterest_trial_intent_immutable
before update on public.pr_pinterest_trial_intents
for each row execute function public.pr_pinterest_trial_intent_immutable();
comment on table public.pr_pinterest_trial_intents is
  'Server-only prepared Pinterest Trial intents and immutable response Pin IDs. App/environment/authority/intent hashes; no credentials, content or workspace FK. Expiry stops provider authority, never refunds attempts. Retention/deletion requires separately approved maintenance.';
commit;
