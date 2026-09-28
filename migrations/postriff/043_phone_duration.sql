-- Fund calls incrementally; existing calls retain their original reservation and timeout.
alter table public.pr_phone_calls drop constraint if exists pr_phone_calls_max_seconds_check;
alter table public.pr_phone_calls add constraint pr_phone_calls_max_seconds_check check(max_seconds between 60 and 3600);
alter table public.pr_phone_calls add column if not exists funded_seconds integer check(funded_seconds between 60 and 3600);
alter table public.pr_phone_calls add column if not exists media_generation integer not null default 0;
alter table public.pr_phone_calls add column if not exists media_resume_until timestamptz;
alter table public.pr_phone_calls add column if not exists media_usage_seconds numeric not null default 0;
alter table public.pr_phone_inbound_codes add column if not exists use_available_credits boolean not null default false;
