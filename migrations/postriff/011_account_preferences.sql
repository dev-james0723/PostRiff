-- Person-level preferences and the account-history feed behind Account → Profile.
-- Preferences live on the profile row (one per verified user), never in workspace state, so
-- they follow the person across workspaces. Both empty by default: the browser's own settings
-- apply until the person chooses.
alter table public.pr_profiles
  add column if not exists time_zone text not null default '' check (length(time_zone) <= 64),
  add column if not exists locale text not null default '' check (length(locale) <= 16),
  add column if not exists alert_new_device boolean not null default false;

-- The profile's "recent security activity" reads the audit log by person (what they did, and what
-- was done to their memberships); the existing index only serves per-workspace reads.
create index if not exists pr_audit_events_actor_at on public.pr_audit_events (actor, at desc);
create index if not exists pr_audit_events_subject_member on public.pr_audit_events (subject, at desc)
  where kind in ('member.updated', 'member.removed');
