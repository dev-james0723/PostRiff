-- Candidate only. Pause private Trial first. Prepared/known outcomes are retained, never silently erased.
begin;
set local lock_timeout = '5s';
do $$
begin
  if to_regclass('public.pr_pinterest_trial_intents') is not null then
    lock table public.pr_pinterest_trial_intents in access exclusive mode;
    if exists (select 1 from public.pr_pinterest_trial_intents) then
      raise exception 'Pinterest Trial journal contains prepared or known outcomes; preserve it for reconciliation';
    end if;
  end if;
end;
$$;
drop table if exists public.pr_pinterest_trial_intents;
drop function if exists public.pr_pinterest_trial_intent_immutable();
-- Existing rate-budget reservations remain intact; restoring the table never grants extra attempts.
commit;
