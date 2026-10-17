-- Derived selector for Rafii's EXISTING jobs, never a queue or authorization.
-- Canonical target: postriff-phase2-private / buoyhkbodnhzngaotoel.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='30s';

CREATE TABLE public.pr_discord_worker_projection (
    workspace_id uuid PRIMARY KEY REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
    next_at double precision,
    last_claimed_at double precision NOT NULL DEFAULT 0,
    source_revision bigint NOT NULL,
    CHECK(next_at IS NULL OR next_at>=0 AND next_at<253402300799),
    CHECK(last_claimed_at>=0 AND last_claimed_at<253402300799)
);
COMMENT ON TABLE public.pr_discord_worker_projection IS
    'Private transactional due-work hints only. Claims, leases, grants and human approvals are revalidated in locked pr_workspaces.state.';
CREATE INDEX pr_discord_worker_projection_due ON public.pr_discord_worker_projection(next_at,workspace_id)
    WHERE next_at IS NOT NULL;
CREATE INDEX pr_discord_worker_projection_rotation ON public.pr_discord_worker_projection(last_claimed_at,workspace_id)
    WHERE next_at IS NOT NULL;

CREATE FUNCTION public.pr_discord_queue_number(value jsonb)
RETURNS double precision LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $number$
DECLARE n numeric;
BEGIN
    IF value IS NULL THEN RETURN 0; END IF;
    IF jsonb_typeof(value) IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
    n=(value#>>'{}')::numeric;
    IF n<0 OR n>=253402300799 THEN RETURN NULL; END IF;
    BEGIN
        RETURN n::double precision;
    EXCEPTION WHEN numeric_value_out_of_range THEN
        IF n<1 THEN RETURN 0; END IF;
        RETURN NULL;
    END;
END $number$;

CREATE FUNCTION public.pr_discord_projection_refresh(wid uuid,source_state jsonb,revision_value bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $refresh$
DECLARE jobs jsonb; due_at double precision; busy_until double precision; rotation double precision;
BEGIN
    jobs=CASE WHEN jsonb_typeof(source_state#>'{phase2,jobs}')='array'
        THEN source_state#>'{phase2,jobs}' ELSE '[]'::jsonb END;
    rotation=coalesce(public.pr_discord_queue_number(source_state#>'{phase2,discordWorkerCursor,lastClaimedAt}'),0);
    IF source_state ? 'phase2' AND NOT source_state ? 'accountDeletion' AND NOT source_state ? 'accountBlock'
       AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(jobs) j
            WHERE j#>>'{manifest,platform}'='Discord'
              AND (coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')
                   OR j->>'leaseOwner' IS NOT NULL)
              AND (public.pr_discord_queue_number(j->'leaseUntil') IS NULL
                   OR public.pr_discord_queue_number(j->'nextAt') IS NULL)) THEN
        SELECT coalesce(max(public.pr_discord_queue_number(j->'leaseUntil')),0) INTO busy_until
            FROM jsonb_array_elements(jobs) j
            WHERE j#>>'{manifest,platform}'='Discord' AND j->>'leaseOwner' IS NOT NULL;
        SELECT min(greatest(public.pr_discord_queue_number(j->'leaseUntil'),
                   public.pr_discord_queue_number(j->'nextAt'),busy_until)) INTO due_at
            FROM jsonb_array_elements(jobs) j
            WHERE j#>>'{manifest,platform}'='Discord'
              AND coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held');
    END IF;
    INSERT INTO public.pr_discord_worker_projection(workspace_id,next_at,last_claimed_at,source_revision)
        VALUES(wid,due_at,rotation,revision_value)
        ON CONFLICT(workspace_id) DO UPDATE SET next_at=excluded.next_at,
            last_claimed_at=excluded.last_claimed_at,source_revision=excluded.source_revision;
END $refresh$;

CREATE FUNCTION public.pr_discord_workspace_projection_trigger()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $trigger$
BEGIN
    PERFORM public.pr_discord_projection_refresh(NEW.id,NEW.state,NEW.revision);
    RETURN NEW;
END $trigger$;
CREATE TRIGGER pr_discord_workspace_projection_trg AFTER INSERT OR UPDATE OF state,revision ON public.pr_workspaces
    FOR EACH ROW EXECUTE FUNCTION public.pr_discord_workspace_projection_trigger();

ALTER TABLE public.pr_discord_worker_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pr_discord_worker_projection FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pr_discord_worker_projection FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.pr_discord_worker_projection TO service_role;
CREATE POLICY pr_discord_worker_projection_service_read ON public.pr_discord_worker_projection
    FOR SELECT TO service_role USING(true);
REVOKE ALL ON FUNCTION public.pr_discord_queue_number(jsonb),
    public.pr_discord_projection_refresh(uuid,jsonb,bigint),public.pr_discord_workspace_projection_trigger()
    FROM PUBLIC,anon,authenticated,service_role;

-- Backfill selection hints only; source JSON/revision, approvals and provider
-- evidence remain byte-identical. Trigger installation serializes source writes.
DO $backfill$
DECLARE item record; after_id uuid; batch_count integer;
BEGIN
    LOOP
        batch_count=0;
        FOR item IN SELECT id,revision,state FROM public.pr_workspaces
            WHERE after_id IS NULL OR id>after_id ORDER BY id LIMIT 200 LOOP
            PERFORM public.pr_discord_projection_refresh(item.id,item.state,item.revision);
            after_id=item.id; batch_count=batch_count+1;
        END LOOP;
        EXIT WHEN batch_count=0;
    END LOOP;
END $backfill$;
COMMIT;
