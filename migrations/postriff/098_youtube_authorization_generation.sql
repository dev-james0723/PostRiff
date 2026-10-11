-- Apply before deploying the YouTube revocation fence. No provider calls.
BEGIN;

-- A consent generation survives token refresh, but changes when the account
-- holder grants access again. In-flight uploads must not inherit a new grant.
ALTER TABLE public.pr_encrypted_credentials
  ADD COLUMN IF NOT EXISTS authorization_generation uuid NOT NULL DEFAULT gen_random_uuid();

COMMENT ON COLUMN public.pr_encrypted_credentials.authorization_generation IS
  'OAuth consent generation; refreshed tokens retain it, new YouTube consent replaces it.';

COMMIT;
