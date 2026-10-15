-- RAPv2 RAP-088 (owner decision 2026-10-15, option A+B): account deletion removes the person's session inventory and
-- keeps their person-level sign-in history with the identifying fields erased. Candidate only: not applied anywhere.
BEGIN;
CREATE OR REPLACE FUNCTION public.pr_erase_session_history(uid uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $erasure$
DECLARE affected integer;
BEGIN
  IF uid IS NULL THEN RETURN 0; END IF;
  -- A: the inventory (browser label, first/last seen) goes. pr_session_revocations stays: it holds no label, and the
  -- account tombstone already refuses every token of this person.
  DELETE FROM public.pr_sessions WHERE user_id=uid;
  -- B: the append-only history keeps that something happened and when, never which session or which browser.
  UPDATE public.pr_audit_events SET subject='', meta=(meta-ARRAY['client','device']) || jsonb_build_object('privacyErased',true)
    WHERE actor=uid AND workspace_id IS NULL AND kind LIKE 'session.%'
      AND (subject<>'' OR meta ?| ARRAY['client','device']);
  GET DIAGNOSTICS affected=ROW_COUNT;
  RETURN affected;
END $erasure$;
REVOKE ALL ON FUNCTION public.pr_erase_session_history(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.pr_erase_session_history(uuid) TO service_role;
-- Deliberately do not grant UPDATE/DELETE on the append-only audit table.
COMMIT;
