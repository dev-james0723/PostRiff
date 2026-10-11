-- Derived selection indexes only. Approval/history state remains authoritative.
-- Apply through the reviewed release workflow; this migration invokes no provider.
BEGIN;

CREATE TABLE IF NOT EXISTS public.pr_youtube_operations (
  workspace_id uuid PRIMARY KEY REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  upload_due_at double precision,
  planner_lease_until double precision NOT NULL DEFAULT 0,
  last_planner_dispatch double precision NOT NULL DEFAULT 0,
  provider_expires_at double precision
);
CREATE TABLE IF NOT EXISTS public.pr_youtube_planner_candidates (
  workspace_id uuid NOT NULL REFERENCES public.pr_workspaces(id) ON DELETE CASCADE,
  policy_id text NOT NULL,
  draft_id text NOT NULL,
  candidate_at double precision NOT NULL,
  ends_at double precision NOT NULL,
  PRIMARY KEY(workspace_id,policy_id,draft_id)
);
COMMENT ON TABLE public.pr_youtube_operations IS
  'Thin transactional selection hints. Claims, approvals, tenant rights and erasure predicates must be revalidated against locked source state.';
COMMENT ON TABLE public.pr_youtube_planner_candidates IS
  'One derived policy/draft interval, never an authorization or a replacement for retained policy history.';

CREATE INDEX IF NOT EXISTS pr_youtube_operations_upload_due_idx
  ON public.pr_youtube_operations(upload_due_at,workspace_id) WHERE upload_due_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS pr_youtube_operations_provider_due_idx
  ON public.pr_youtube_operations(provider_expires_at,workspace_id) WHERE provider_expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS pr_youtube_operations_planner_dispatch_idx
  ON public.pr_youtube_operations(last_planner_dispatch,workspace_id);
CREATE INDEX IF NOT EXISTS pr_youtube_planner_candidates_due_idx
  ON public.pr_youtube_planner_candidates(workspace_id,candidate_at,ends_at);

ALTER TABLE public.pr_youtube_uploads ADD COLUMN IF NOT EXISTS youtube_api_expires_at double precision;
COMMENT ON COLUMN public.pr_youtube_uploads.youtube_api_expires_at IS
  'Derived retention selector only. Original journal state, removal marker and ingestion/updated clocks must be revalidated before erasure.';
CREATE INDEX IF NOT EXISTS pr_youtube_uploads_api_expiry_idx
  ON public.pr_youtube_uploads(youtube_api_expires_at,workspace_id) WHERE youtube_api_expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS pr_youtube_uploads_workspace_api_expiry_idx
  ON public.pr_youtube_uploads(workspace_id,youtube_api_expires_at) WHERE youtube_api_expires_at IS NOT NULL;

-- jsonpath retention predicates accept JSON numbers, not numeric strings or
-- booleans. An out-of-float-range JSON number keeps its ordering relative to a
-- finite epoch via signed infinity; readiness clocks separately reject it.
CREATE OR REPLACE FUNCTION public.pr_youtube_projection_number(value jsonb)
RETURNS double precision LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $number$
BEGIN
  IF jsonb_typeof(value) IS DISTINCT FROM 'number' THEN RETURN NULL; END IF;
  BEGIN
    RETURN (value#>>'{}')::double precision;
  EXCEPTION WHEN numeric_value_out_of_range THEN
    -- PostgreSQL reports float underflow through the same exception class.
    -- Tiny epoch numbers are near zero, never signed overflow/infinite time.
    IF abs((value#>>'{}')::numeric)<1 THEN RETURN 0; END IF;
    RETURN CASE WHEN (value#>>'{}')::numeric<0 THEN '-infinity'::double precision ELSE 'infinity'::double precision END;
  END;
END $number$;

CREATE OR REPLACE FUNCTION public.pr_youtube_projection_refresh(wid uuid,source_state jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $refresh$
DECLARE
  upload_due double precision;
  provider_due double precision;
  lease_until double precision;
  last_dispatch double precision;
BEGIN
  -- Missing/null dispatch clocks preserve the existing zero default. A bad
  -- non-null clock cannot turn into immediate upload/planner readiness.
  lease_until:=CASE WHEN source_state#>'{youtubeAgent,fleetLease,until}' IS NULL
      OR source_state#>'{youtubeAgent,fleetLease,until}'='null'::jsonb THEN 0
    ELSE coalesce(public.pr_youtube_projection_number(source_state#>'{youtubeAgent,fleetLease,until}'),'infinity'::double precision) END;
  last_dispatch:=CASE WHEN source_state#>'{youtubeAgent,lastDispatchAt}' IS NULL
      OR source_state#>'{youtubeAgent,lastDispatchAt}'='null'::jsonb THEN 0
    ELSE coalesce(public.pr_youtube_projection_number(source_state#>'{youtubeAgent,lastDispatchAt}'),'infinity'::double precision) END;
  IF lease_until NOT BETWEEN '-1.7976931348623157e308'::double precision AND '1.7976931348623157e308'::double precision
    THEN lease_until:='infinity'::double precision; END IF;
  IF last_dispatch NOT BETWEEN '-1.7976931348623157e308'::double precision AND '1.7976931348623157e308'::double precision
    THEN last_dispatch:='infinity'::double precision; END IF;

  IF source_state ? 'phase2' AND NOT source_state ? 'accountDeletion' AND NOT source_state ? 'accountBlock' THEN
    SELECT min(greatest(clocks.lease_until,clocks.next_at)) INTO upload_due FROM (
      SELECT
        CASE WHEN j->'leaseUntil' IS NULL OR j->'leaseUntil'='null'::jsonb THEN 0
          ELSE public.pr_youtube_projection_number(j->'leaseUntil') END AS lease_until,
        CASE WHEN j->'nextAt' IS NULL OR j->'nextAt'='null'::jsonb THEN 0
          ELSE public.pr_youtube_projection_number(j->'nextAt') END AS next_at
      FROM jsonb_array_elements(CASE WHEN jsonb_typeof(source_state#>'{phase2,jobs}')='array'
        THEN source_state#>'{phase2,jobs}' ELSE '[]'::jsonb END) j
      WHERE j#>>'{manifest,platform}'='YouTube' AND coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')
    ) clocks WHERE clocks.lease_until>'-infinity'::double precision AND clocks.lease_until<'infinity'::double precision
      AND clocks.next_at>'-infinity'::double precision AND clocks.next_at<'infinity'::double precision;
  END IF;

  -- Cleanup remains selectable while an account is blocked or being deleted.
  -- Marker key presence mirrors the original conservative SQL selection.
  SELECT min(outputs.expires_at) INTO provider_due FROM (
    SELECT CASE WHEN j ? 'youtubeProviderOutput'
        THEN coalesce(public.pr_youtube_projection_number(j#>'{youtubeProviderOutput,expiresAt}'),'-infinity'::double precision)
      ELSE coalesce(public.pr_youtube_projection_number(j->'approvedAt')+2592000,'-infinity'::double precision) END AS expires_at
    FROM jsonb_array_elements(CASE WHEN jsonb_typeof(source_state#>'{phase2,jobs}')='array'
      THEN source_state#>'{phase2,jobs}' ELSE '[]'::jsonb END) j
    WHERE j#>>'{manifest,platform}'='YouTube' AND NOT j ? 'youtubeProviderDataRemoved'
      AND j ?| ARRAY['providerReference','url','container','progress','providerConfirmed','verification','insights','comments']
    UNION ALL
    SELECT coalesce(public.pr_youtube_projection_number(c->'youtubeIdentityIngestedAt')+2592000,'-infinity'::double precision)
    FROM jsonb_array_elements(CASE WHEN jsonb_typeof(source_state#>'{phase2,channels}')='array'
      THEN source_state#>'{phase2,channels}' ELSE '[]'::jsonb END) c
    WHERE c->>'platform'='YouTube' AND c->>'evidenceSource'='live_provider' AND NOT c ? 'youtubeProviderDataRemoved'
  ) outputs;

  INSERT INTO public.pr_youtube_operations(workspace_id,upload_due_at,planner_lease_until,last_planner_dispatch,provider_expires_at)
    VALUES(wid,upload_due,lease_until,last_dispatch,provider_due)
    ON CONFLICT(workspace_id) DO UPDATE SET upload_due_at=EXCLUDED.upload_due_at,
      planner_lease_until=EXCLUDED.planner_lease_until,last_planner_dispatch=EXCLUDED.last_planner_dispatch,
      provider_expires_at=EXCLUDED.provider_expires_at;

  DELETE FROM public.pr_youtube_planner_candidates WHERE workspace_id=wid;
  IF source_state ? 'youtubeAgent' AND NOT source_state ? 'accountDeletion' AND NOT source_state ? 'accountBlock' THEN
    INSERT INTO public.pr_youtube_planner_candidates(workspace_id,policy_id,draft_id,candidate_at,ends_at)
      SELECT wid,eligible.policy_id,eligible.draft_id,eligible.candidate_at,eligible.ends_at FROM (
        SELECT p->>'id' AS policy_id,d->>'id' AS draft_id,
          CASE WHEN d->>'uploadWorkflow' IS NOT NULL AND d->>'uploadWorkflow'<>'upload_later'
            THEN public.pr_youtube_projection_number(p->'startsAt')
            ELSE greatest(public.pr_youtube_projection_number(p->'startsAt'),public.pr_youtube_projection_number(d->'uploadAt')-1800) END AS candidate_at,
          public.pr_youtube_projection_number(p->'endsAt') AS ends_at
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(source_state#>'{youtubeAgent,policies}')='array'
            THEN source_state#>'{youtubeAgent,policies}' ELSE '[]'::jsonb END) p
        JOIN jsonb_array_elements(CASE WHEN jsonb_typeof(source_state#>'{youtubeAgent,drafts}')='array'
            THEN source_state#>'{youtubeAgent,drafts}' ELSE '[]'::jsonb END) d
          ON d->>'connectionId'=p->>'connectionId'
        WHERE p->>'status'='active' AND d->>'status'='proposed' AND p->>'id' IS NOT NULL AND d->>'id' IS NOT NULL
          AND public.pr_youtube_projection_number(p->'startsAt')>'-infinity'::double precision
          AND public.pr_youtube_projection_number(p->'startsAt')<'infinity'::double precision
          AND public.pr_youtube_projection_number(p->'endsAt')>'-infinity'::double precision
          AND public.pr_youtube_projection_number(p->'endsAt')<'infinity'::double precision
          AND ((d->>'uploadWorkflow' IS NOT NULL AND d->>'uploadWorkflow'<>'upload_later')
            OR (public.pr_youtube_projection_number(d->'uploadAt')>'-infinity'::double precision
              AND public.pr_youtube_projection_number(d->'uploadAt')<'infinity'::double precision))
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p->'drafts')='array'
            THEN p->'drafts' ELSE '[]'::jsonb END) e WHERE e->>'id'=d->>'id')
      ) eligible
      ON CONFLICT(workspace_id,policy_id,draft_id) DO NOTHING;
  END IF;
END $refresh$;

CREATE OR REPLACE FUNCTION public.pr_youtube_workspace_projection_trigger()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $workspace_trigger$
BEGIN
  IF TG_OP='UPDATE' AND NEW.state IS NOT DISTINCT FROM OLD.state THEN RETURN NEW; END IF;
  PERFORM public.pr_youtube_projection_refresh(NEW.id,NEW.state);
  RETURN NEW;
END $workspace_trigger$;
DROP TRIGGER IF EXISTS pr_youtube_workspace_projection_trg ON public.pr_workspaces;
CREATE TRIGGER pr_youtube_workspace_projection_trg AFTER INSERT OR UPDATE OF state ON public.pr_workspaces
  FOR EACH ROW EXECUTE FUNCTION public.pr_youtube_workspace_projection_trigger();

CREATE OR REPLACE FUNCTION public.pr_youtube_upload_projection_trigger()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $upload_trigger$
DECLARE ingested double precision; created double precision;
BEGIN
  IF NEW.state ? 'youtubeProviderDataRemoved' THEN
    NEW.youtube_api_expires_at:=NULL;
  ELSE
    ingested:=public.pr_youtube_projection_number(NEW.state->'youtubeProviderDataIngestedAt');
    created:=public.pr_youtube_projection_number(NEW.state->'createdAt');
    NEW.youtube_api_expires_at:=CASE WHEN ingested IS NOT NULL THEN ingested+2592000
      ELSE least(created+2592000,extract(epoch FROM NEW.updated_at)::double precision+2592000) END;
  END IF;
  RETURN NEW;
END $upload_trigger$;
DROP TRIGGER IF EXISTS pr_youtube_upload_projection_trg ON public.pr_youtube_uploads;
CREATE TRIGGER pr_youtube_upload_projection_trg BEFORE INSERT OR UPDATE OF state,updated_at,youtube_api_expires_at ON public.pr_youtube_uploads
  FOR EACH ROW EXECUTE FUNCTION public.pr_youtube_upload_projection_trigger();

-- Only server SELECT is exposed. Trigger owners maintain the derived data;
-- neither browser roles nor service callers can mutate or directly refresh it.
DO $access$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['pr_youtube_operations','pr_youtube_planner_candidates'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',table_name);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',table_name);
    EXECUTE format('GRANT SELECT ON public.%I TO service_role',table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I',table_name||'_service_read',table_name);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO service_role USING(true)',table_name||'_service_read',table_name);
  END LOOP;
END $access$;
REVOKE ALL ON FUNCTION public.pr_youtube_projection_number(jsonb),public.pr_youtube_projection_refresh(uuid,jsonb),
  public.pr_youtube_workspace_projection_trigger(),public.pr_youtube_upload_projection_trigger()
  FROM PUBLIC,anon,authenticated,service_role;

-- Keyset batches keep backfill memory bounded; all maintenance and original
-- rows remain in this migration transaction. Source state/revision and journal
-- content/updated_at are never replaced, truncated, re-signed or refreshed.
DO $backfill$
DECLARE workspace_row record; journal_row record; last_workspace uuid; batch_count integer;
  last_journal_workspace uuid; last_connection text; last_operation text;
BEGIN
  LOOP
    batch_count:=0;
    FOR workspace_row IN SELECT id,state FROM public.pr_workspaces
      WHERE last_workspace IS NULL OR id>last_workspace ORDER BY id LIMIT 100 FOR UPDATE LOOP
      PERFORM public.pr_youtube_projection_refresh(workspace_row.id,workspace_row.state);
      last_workspace:=workspace_row.id;
      batch_count:=batch_count+1;
    END LOOP;
    EXIT WHEN batch_count=0;
  END LOOP;
  LOOP
    batch_count:=0;
    FOR journal_row IN SELECT workspace_id,connection_id,operation_key FROM public.pr_youtube_uploads
      WHERE last_journal_workspace IS NULL OR (workspace_id,connection_id,operation_key)>(last_journal_workspace,last_connection,last_operation)
      ORDER BY workspace_id,connection_id,operation_key LIMIT 500 FOR UPDATE LOOP
      UPDATE public.pr_youtube_uploads SET youtube_api_expires_at=youtube_api_expires_at
        WHERE workspace_id=journal_row.workspace_id AND connection_id=journal_row.connection_id AND operation_key=journal_row.operation_key;
      last_journal_workspace:=journal_row.workspace_id;
      last_connection:=journal_row.connection_id;
      last_operation:=journal_row.operation_key;
      batch_count:=batch_count+1;
    END LOOP;
    EXIT WHEN batch_count=0;
  END LOOP;
END $backfill$;
COMMIT;
