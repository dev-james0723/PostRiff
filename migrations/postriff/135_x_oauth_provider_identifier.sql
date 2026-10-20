-- Candidate migration only; production application requires release authorization.
-- Preserve the existing provider-name rule, adding only the official X adapter ID.
BEGIN;
ALTER TABLE public.pr_oauth_transactions
    DROP CONSTRAINT IF EXISTS pr_oauth_transactions_provider_check;
ALTER TABLE public.pr_oauth_transactions
    ADD CONSTRAINT pr_oauth_transactions_provider_check
    CHECK (provider = 'x' OR length(provider) BETWEEN 2 AND 40);
COMMIT;
