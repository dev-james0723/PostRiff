-- Candidate only: add X to the known legacy rule, never replace an unknown policy.
-- An already-effective validated rule is a catalog-only no-op (no table DDL lock).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $migration$
DECLARE
    wanted CONSTANT text := '((provider = ''x''::text) OR ((length(provider) >= 2) AND (length(provider) <= 40)))';
    legacy CONSTANT text := '((length(provider) >= 2) AND (length(provider) <= 40))';
    existing text;
    validated boolean;
    no_inherit boolean;
BEGIN
    SELECT pg_get_expr(conbin, conrelid), convalidated, connoinherit
      INTO existing, validated, no_inherit
      FROM pg_constraint
     WHERE conrelid = 'public.pr_oauth_transactions'::regclass
       AND conname = 'pr_oauth_transactions_provider_check' AND contype = 'c';
    IF existing = wanted AND validated AND NOT no_inherit THEN
        RETURN;
    END IF;
    IF existing IS DISTINCT FROM legacy OR validated IS DISTINCT FROM true
       OR no_inherit IS DISTINCT FROM false THEN
        RAISE EXCEPTION 'X migration 135: unexpected OAuth provider constraint; review before changing it';
    END IF;
    -- Recheck under the lock so a concurrent administrator's policy is not lost.
    LOCK TABLE public.pr_oauth_transactions IN ACCESS EXCLUSIVE MODE;
    SELECT pg_get_expr(conbin, conrelid), convalidated, connoinherit
      INTO existing, validated, no_inherit
      FROM pg_constraint
     WHERE conrelid = 'public.pr_oauth_transactions'::regclass
       AND conname = 'pr_oauth_transactions_provider_check' AND contype = 'c';
    IF existing = wanted AND validated AND NOT no_inherit THEN
        RETURN;
    END IF;
    IF existing IS DISTINCT FROM legacy OR validated IS DISTINCT FROM true
       OR no_inherit IS DISTINCT FROM false THEN
        RAISE EXCEPTION 'X migration 135: OAuth provider policy changed concurrently; no override performed';
    END IF;
    ALTER TABLE public.pr_oauth_transactions DROP CONSTRAINT pr_oauth_transactions_provider_check;
    ALTER TABLE public.pr_oauth_transactions ADD CONSTRAINT pr_oauth_transactions_provider_check
        CHECK (provider = 'x' OR length(provider) BETWEEN 2 AND 40);
END
$migration$;
COMMIT;
