-- CANDIDATE ONLY. Connect application custody; no management/metrics/health schema.
-- Extracted from G7 131; distinct ledger name must never impersonate full 131.
create table public.pr_mastodon_applications (
  instance text not null,
  binding_digest text not null check (binding_digest ~ '^[0-9a-f]{64}$'),
  credentials_ciphertext text not null,
  key_id text not null,
  updated_at timestamptz not null default now(),
  primary key(instance, binding_digest)
);
alter table public.pr_mastodon_applications enable row level security;
alter table public.pr_mastodon_applications force row level security;
create policy service_only on public.pr_mastodon_applications
  for all to service_role using (true) with check (true);
revoke all on public.pr_mastodon_applications from public, anon, authenticated;
grant select, insert, update, delete on public.pr_mastodon_applications to service_role;
