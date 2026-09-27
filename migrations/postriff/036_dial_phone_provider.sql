-- Add Dial to the existing private phone ledger. No new identity store or agent runtime.
alter table public.pr_phone_calls drop constraint if exists pr_phone_calls_provider_check;
alter table public.pr_phone_calls add constraint pr_phone_calls_provider_check
  check (provider in ('fake','twilio','telnyx','dial'));
