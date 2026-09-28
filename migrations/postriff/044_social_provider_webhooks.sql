-- Signature-verified social-provider webhook idempotency. Payloads and credentials are never stored here.
begin;

create table public.pr_social_provider_events (
  provider text not null check (provider in ('xiaohongshu')),
  event_id text not null check (length(event_id) between 1 and 128),
  event_type text not null check (length(event_type) between 1 and 80),
  payload_digest text not null check (length(payload_digest)=64),
  outcome text,
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  primary key (provider,event_id)
);

alter table public.pr_social_provider_events enable row level security;
alter table public.pr_social_provider_events force row level security;
revoke all on public.pr_social_provider_events from public, anon, authenticated;
grant all on public.pr_social_provider_events to service_role;
create policy service_only on public.pr_social_provider_events for all to service_role using (true) with check (true);

commit;
