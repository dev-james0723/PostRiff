-- Protocol compatibility fence for the EXISTING hosted worker and job store.
-- Canonical: postriff-phase2-private / buoyhkbodnhzngaotoel.
-- Older callers must fail their claim transaction BEFORE any provider I/O.
-- This is not an authorization substitute; all application checks still apply.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='30s';

CREATE FUNCTION public.pr_discord_lease_protocol_guard()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $guard$
DECLARE jobs jsonb; old_jobs jsonb; job jsonb; previous jsonb;
BEGIN
    IF TG_OP='UPDATE' AND NEW.state#>'{phase2,jobs}' IS NOT DISTINCT FROM OLD.state#>'{phase2,jobs}' THEN
        RETURN NEW;
    END IF;
    jobs=CASE WHEN jsonb_typeof(NEW.state#>'{phase2,jobs}')='array'
        THEN NEW.state#>'{phase2,jobs}' ELSE '[]'::jsonb END;
    old_jobs=CASE WHEN TG_OP='UPDATE' AND jsonb_typeof(OLD.state#>'{phase2,jobs}')='array'
        THEN OLD.state#>'{phase2,jobs}' ELSE '[]'::jsonb END;
    FOR job IN SELECT value FROM jsonb_array_elements(jobs) LOOP
        IF job#>>'{manifest,platform}' IS DISTINCT FROM 'Discord' OR job->>'leaseOwner' IS NULL THEN
            CONTINUE;
        END IF;
        SELECT value INTO previous FROM jsonb_array_elements(old_jobs)
            WHERE value->>'id'=job->>'id' LIMIT 1;
        -- A renewal or result on an unchanged lease does not acquire a lease.
        -- Each real old/new worker claim rotates leaseId, including recovery.
        IF previous IS NOT NULL
           AND previous->'leaseOwner' IS NOT DISTINCT FROM job->'leaseOwner'
           AND previous->'leaseId' IS NOT DISTINCT FROM job->'leaseId' THEN
            CONTINUE;
        END IF;
        IF coalesce(job->>'id','')=''
           OR coalesce(job->>'leaseId','')=''
           OR coalesce(job->>'leaseOwner','')=''
           OR coalesce(job->>'approvalDigest','') !~ '^[a-f0-9]{64}$'
           OR job#>'{discordWorker,version}' IS DISTINCT FROM '1'::jsonb
           OR job#>>'{discordWorker,leaseId}' IS DISTINCT FROM job->>'leaseId'
           OR job#>>'{discordWorker,publicationId}' IS DISTINCT FROM job->>'id'
           OR job#>>'{discordWorker,approvalDigest}' IS DISTINCT FROM job->>'approvalDigest'
           OR job#>>'{manifest,workspaceId}' IS DISTINCT FROM NEW.id::text
           OR job#>>'{manifest,discord,schema}' IS DISTINCT FROM 'rafii.discord.publish.v2'
           OR job#>>'{manifest,discord,publicationId}' IS DISTINCT FROM job->>'id'
           OR job#>>'{discordAuthorization,schema}' IS DISTINCT FROM 'rafii.discord.publish.v2'
           OR job#>>'{discordAuthorization,publicationId}' IS DISTINCT FROM job->>'id'
           OR job#>>'{discordAuthorization,target,workspaceId}' IS DISTINCT FROM NEW.id::text
           OR job#>>'{discordAuthorization,manifestDigest}' IS DISTINCT FROM job->>'approvalDigest'
           OR coalesce(job->>'approvedBy','')=''
           OR job#>>'{manifest,actor}' IS DISTINCT FROM job->>'approvedBy'
           OR job#>>'{discordAuthorization,approvedBy}' IS DISTINCT FROM job->>'approvedBy' THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='Discord requires the current fenced worker protocol before dispatch.';
        END IF;
    END LOOP;
    RETURN NEW;
END $guard$;
COMMENT ON FUNCTION public.pr_discord_lease_protocol_guard() IS
    'Rejects legacy Discord lease acquisition before provider I/O; preserves existing application authorization, tenant RLS and dispatch admission checks.';
REVOKE ALL ON FUNCTION public.pr_discord_lease_protocol_guard()
    FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER pr_discord_lease_protocol_trg BEFORE INSERT OR UPDATE OF state ON public.pr_workspaces
    FOR EACH ROW EXECUTE FUNCTION public.pr_discord_lease_protocol_guard();
COMMIT;
