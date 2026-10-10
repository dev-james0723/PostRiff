-- Durable fleet rotation hints; successful dispatch and customer authority remain unchanged.
-- Apply only through the reviewed migration workflow. No provider call is made.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
-- Runtime claims lock a workspace before its derived operations row. Acquire
-- the same relation order before operations DDL, including SELECT FOR UPDATE
-- callers (RowShare), so the backfill cannot invert their lock order.
LOCK TABLE public.pr_workspaces IN EXCLUSIVE MODE;
-- Previously deployed selectors may still open operations first. Refuse
-- contention immediately instead of waiting while holding workspace exclusion.
LOCK TABLE public.pr_youtube_operations IN ACCESS EXCLUSIVE MODE NOWAIT;

ALTER TABLE public.pr_youtube_operations
  ADD COLUMN IF NOT EXISTS last_planner_claim double precision NOT NULL DEFAULT 0;
COMMENT ON COLUMN public.pr_youtube_operations.last_planner_claim IS
  'Derived last fleet claim cursor, including deferred attempts. Never publication authority or evidence of successful dispatch.';
CREATE INDEX IF NOT EXISTS pr_youtube_operations_planner_claim_idx
  ON public.pr_youtube_operations(last_planner_claim,workspace_id);

CREATE OR REPLACE FUNCTION public.pr_youtube_planner_claim_clock(source_state jsonb)
RETURNS double precision LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $clock$
DECLARE value jsonb; cursor_at numeric;
BEGIN
  FOR value IN SELECT candidate FROM (VALUES
      (source_state#>'{youtubeAgent,lastPlannerClaimAt}'),
      (source_state#>'{youtubeAgent,lastDispatchAt}')) clocks(candidate) LOOP
    IF jsonb_typeof(value) IS DISTINCT FROM 'number' THEN CONTINUE; END IF;
    cursor_at:=(value#>>'{}')::numeric;
    IF cursor_at>=0 AND cursor_at<253402300799 THEN
      -- Operational epoch clocks need no sub-microsecond historical ordering.
      -- Clamp before the float cast so numeric underflow cannot abort a trigger.
      IF cursor_at<0.000001 THEN RETURN 0; END IF;
      RETURN cursor_at::double precision;
    END IF;
  END LOOP;
  RETURN 0;
END $clock$;

CREATE OR REPLACE FUNCTION public.pr_youtube_workspace_rotation_trigger()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $rotation$
BEGIN
  IF TG_OP='UPDATE' AND NEW.state IS NOT DISTINCT FROM OLD.state THEN RETURN NEW; END IF;
  UPDATE public.pr_youtube_operations
    SET last_planner_claim=public.pr_youtube_planner_claim_clock(NEW.state)
    WHERE workspace_id=NEW.id;
  RETURN NEW;
END $rotation$;
-- PostgreSQL runs same-kind triggers alphabetically. Rotation follows the
-- existing projection trigger, which creates the derived row on INSERT.
DROP TRIGGER IF EXISTS pr_youtube_workspace_rotation_trg ON public.pr_workspaces;
CREATE TRIGGER pr_youtube_workspace_rotation_trg AFTER INSERT OR UPDATE OF state ON public.pr_workspaces
  FOR EACH ROW EXECUTE FUNCTION public.pr_youtube_workspace_rotation_trigger();
REVOKE ALL ON FUNCTION public.pr_youtube_planner_claim_clock(jsonb),
  public.pr_youtube_workspace_rotation_trigger() FROM PUBLIC,anon,authenticated,service_role;

-- Backfill derived data only. Source row and relation locks remain until COMMIT;
-- LIMIT 100 bounds fetch memory, not the total held locks. Local timeouts bound
-- the maintenance wait/work and a failure rolls back the whole migration.
-- No state/revision, successful-dispatch clock, approval, policy, journal or
-- retention clock changes.
DO $backfill$
DECLARE source_row record; last_workspace uuid; batch_count integer;
BEGIN
  LOOP
    batch_count:=0;
    FOR source_row IN SELECT id,state FROM public.pr_workspaces
      WHERE last_workspace IS NULL OR id>last_workspace ORDER BY id LIMIT 100 FOR UPDATE LOOP
      UPDATE public.pr_youtube_operations
        SET last_planner_claim=public.pr_youtube_planner_claim_clock(source_row.state)
        WHERE workspace_id=source_row.id;
      last_workspace:=source_row.id;
      batch_count:=batch_count+1;
    END LOOP;
    EXIT WHEN batch_count=0;
  END LOOP;
END $backfill$;
COMMIT;
