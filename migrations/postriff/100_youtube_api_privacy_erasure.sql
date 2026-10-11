-- Candidate only: no legal-policy seed, provider calls or automatic data erasure.
BEGIN;
ALTER TABLE public.pr_encrypted_credentials ADD COLUMN IF NOT EXISTS youtube_identity_ingested_at timestamptz;
COMMENT ON COLUMN public.pr_encrypted_credentials.youtube_identity_ingested_at IS
  'Successful genuine YouTube identity ingestion only; legacy NULL uses created_at. Token rotation or generic verification never extends retention.';
CREATE INDEX IF NOT EXISTS pr_youtube_identity_privacy_expiry
  ON public.pr_encrypted_credentials((coalesce(youtube_identity_ingested_at,created_at)),workspace_id)
  WHERE provider='youtube' AND revoked_at IS NULL;
ALTER TABLE public.pr_youtube_actions ADD COLUMN IF NOT EXISTS user_inputs jsonb;
ALTER TABLE public.pr_youtube_actions ADD COLUMN IF NOT EXISTS privacy_erased_at timestamptz;
COMMENT ON COLUMN public.pr_youtube_actions.user_inputs IS
  'Exactly submitted inputs, separate from merged provider plans. Submission provenance does not prove independent authorship of identifiers.';
ALTER TABLE public.pr_youtube_actions DROP CONSTRAINT IF EXISTS pr_youtube_actions_status_check;
ALTER TABLE public.pr_youtube_actions ADD CONSTRAINT pr_youtube_actions_status_check
  CHECK(status IN ('prepared','started','accepted','verified','failed','outcome_unknown','privacy_erased'));
CREATE INDEX IF NOT EXISTS pr_youtube_actions_privacy_expiry
  ON public.pr_youtube_actions(created_at,workspace_id) WHERE privacy_erased_at IS NULL;

-- Fixed fields and event kinds only. Legacy application subjects must still
-- resolve to this exact connection. Ambiguous orphan/stream-ID subjects are
-- deliberately excluded; this is not a blanket deletion/compliance claim.
CREATE OR REPLACE FUNCTION public.pr_youtube_erase_audit_fields(wid uuid,cid text,cutoff_epoch double precision DEFAULT NULL)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $erasure$
DECLARE affected integer; application_subjects text[];
BEGIN
  IF wid IS NULL OR cid IS NULL OR cid='' THEN RETURN 0; END IF;
  -- Serialize against workspace mutation; callers use workspace->credential.
  PERFORM 1 FROM public.pr_workspaces WHERE id=wid FOR UPDATE;
  IF NOT FOUND THEN RETURN 0; END IF;
  SELECT coalesce(array_agg(subject),'{}'::text[]) INTO application_subjects FROM (
    SELECT id::text AS subject FROM public.pr_youtube_actions WHERE workspace_id=wid AND connection_id=cid
    UNION ALL
    SELECT r->>'id' FROM public.pr_workspaces w,
      LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.state#>'{phase2,jobs}')='array' THEN w.state#>'{phase2,jobs}' ELSE '[]'::jsonb END) r
      WHERE w.id=wid AND r#>>'{manifest,workspaceId}'=wid::text AND r#>>'{manifest,platform}'='YouTube' AND r#>>'{manifest,channelId}'=cid
    UNION ALL
    SELECT r->>'id' FROM public.pr_workspaces w,
      LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.state#>'{youtubeAgent,drafts}')='array' THEN w.state#>'{youtubeAgent,drafts}' ELSE '[]'::jsonb END) r
      WHERE w.id=wid AND r->>'connectionId'=cid
    UNION ALL
    SELECT r->>'id' FROM public.pr_workspaces w,
      LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(w.state#>'{youtubeAgent,policies}')='array' THEN w.state#>'{youtubeAgent,policies}' ELSE '[]'::jsonb END) r
      WHERE w.id=wid AND r->>'connectionId'=cid
  ) exact_subjects WHERE subject IS NOT NULL;
  UPDATE public.pr_audit_events SET meta=(meta-ARRAY['channelId','resourceId','videoId'])
      || jsonb_build_object('privacyErased',true)
    WHERE workspace_id=wid AND kind IN ('youtube.action_prepared','youtube.action_result','youtube.upload_resumed',
      'youtube.agent_prepared','youtube.agent_activated','youtube.agent_paused','youtube.agent_revoked',
      'youtube.agent_queued','youtube.agent_draft_created','youtube.agent_draft_prepared','youtube.agent_draft_approved',
      'youtube.agent_policy_prepared','youtube.agent_policy_activated',
      'youtube.agent_policy_paused','youtube.agent_policy_revoked','youtube.agent_dispatched')
      AND (meta->>'connectionId'=cid OR (NOT meta ? 'connectionId' AND (subject=cid OR subject=ANY(application_subjects))))
      AND (cutoff_epoch IS NULL OR at<=to_timestamp(cutoff_epoch))
      AND meta ?| ARRAY['channelId','resourceId','videoId'];
  GET DIAGNOSTICS affected=ROW_COUNT;
  RETURN affected;
END $erasure$;
REVOKE ALL ON FUNCTION public.pr_youtube_erase_audit_fields(uuid,text,double precision) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.pr_youtube_erase_audit_fields(uuid,text,double precision) TO service_role;
-- Deliberately do not grant UPDATE/DELETE on the append-only audit table.
COMMIT;
