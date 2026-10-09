"""Bounded PostgreSQL worker for browser-independent Phase 2 schedules."""
import copy
import json
import os
import time
import uuid

from postriff_alpha.domain import AlphaError
from .store import IN_FLIGHT, TERMINAL, find
from .hosted import HostedPhase2Commands
from .contracts import digest
from .outcomes import normalize_result, unknown
from .permissions import Membership
from .learning_service import record_published
from .youtube.agent import assert_job_authority


def configured_worker_limits(values=None):
    """Server-only tuning; existing cron defaults and safe per-invocation bounds."""
    values = os.environ if values is None else values
    try:
        jobs = int(values.get('POSTRIFF_WORKER_MAX_JOBS', 10))
        seconds = float(values.get('POSTRIFF_WORKER_MAX_SECONDS', 20))
    except (ValueError, TypeError, OverflowError):
        raise AlphaError('Worker budgets require one to 25 jobs and one to 45 seconds.', 503,
                         code='worker_budget_configuration') from None
    if not 1 <= jobs <= 25 or not 1 <= seconds <= 45:
        raise AlphaError('Worker budgets require one to 25 jobs and one to 45 seconds.', 503,
                         code='worker_budget_configuration')
    return jobs, seconds


def due_workspaces_sql(capacity_ready=True, *, youtube_only=False, exclude_youtube=False, operations_ready=True):
    """The actual bounded selection, shared with disposable query-plan acceptance."""
    dispatch_join = 'LEFT JOIN public.pr_worker_tenants dispatch ON dispatch.workspace_id=w.id' if capacity_ready else ''
    dispatch_order = 'dispatch.last_claimed_at NULLS FIRST,w.id' if capacity_ready else 'w.id'
    if youtube_only and exclude_youtube:
        raise AlphaError('Worker platform filters conflict.', 503, code='worker_platform_filter')
    if youtube_only and capacity_ready and operations_ready:
        from .youtube.operations import WORKER_SQL
        return WORKER_SQL
    platform_filter = (" AND j#>>'{manifest,platform}'='YouTube'" if youtube_only else
                       " AND coalesce(j#>>'{manifest,platform}','')<>'YouTube'" if exclude_youtube else '')
    return """SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces w
        """ + dispatch_join + """
        WHERE w.state ? 'phase2' AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
            WHERE coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')
              AND coalesce((j->>'leaseUntil')::double precision,0)<=%s
              AND coalesce((j->>'nextAt')::double precision,0)<=%s""" + platform_filter + """)
        ORDER BY """ + dispatch_order + """ LIMIT 100 FOR UPDATE OF w SKIP LOCKED"""


class DisabledHostedSocial:
    """Fail closed until an exact provider transport and token vault are configured."""
    def submit(self, _manifest):
        return {"state": "held", "confirmed": "Live provider transport is not configured; nothing was submitted"}

    def reconcile(self, _manifest, _job):
        return {"state": "uncertain", "confirmed": "Provider reconciliation is unavailable; do not resubmit"}


class PostgresWorker:
    def __init__(self, connection_factory, social=None, clock=time.time, worker_id=None, on_verified=None, youtube_maintenance=None):
        self.connection_factory = connection_factory
        self.social = social or DisabledHostedSocial()
        self.clock = clock
        self.worker_id = worker_id or "worker-" + uuid.uuid4().hex
        self.commands = HostedPhase2Commands(clock)
        # Optional server-side hook (e.g. native insights ingestion) run in the same transaction once verified.
        self.on_verified = on_verified
        self.youtube_maintenance = youtube_maintenance
        self.capacity_intervention = None

    def _event(self, job, state, message):
        job["state"] = state
        job.setdefault("events", []).append({"at": self.clock(), "state": state, "message": message, "execution": "hosted-worker"})

    def _approved(self, cur, workspace_id, state, job):
        from .billing import require_publishing
        try:
            if job.get('privacyErased') or job.get('youtubeProviderDataRemoved') or job.get('manifest', {}).get('privacyErased'):
                return False
            if state.get('accountDeletion') or state.get('accountBlock'): return False
            require_publishing(cur, workspace_id, self.clock())
            assert_job_authority(state, job, self.clock())
            manifest = job['manifest']
            channel = find(state['phase2']['channels'], manifest['channelId'])
            cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
            member = cur.fetchone()
            expires = manifest['expiresAt']
            recovery = job.get('youtubeRecoveryApproval') or {}
            if (manifest.get('platform') == 'YouTube' and recovery.get('digest') == job.get('approvalDigest')
                    and recovery.get('approvedBy') == job.get('approvedBy')
                    and type(recovery.get('approvedAt')) in (int, float)
                    and type(recovery.get('expiresAt')) in (int, float)
                    and recovery['approvedAt'] <= self.clock()
                    and recovery['approvedAt'] < recovery['expiresAt'] <= recovery['approvedAt'] + 36 * 3600):
                expires = max(expires, recovery['expiresAt'])
            return bool(member and Membership.from_row(member[0], can_publish=member[1]).allows('approve')
                        and (not job.get('youtubeAgent') or member[0] == 'owner')
                        and job['approvalDigest'] == digest(manifest) and job['approvedBy'] == manifest['actor']
                        and self.commands.engine.current(state, manifest)
                        and self.commands.engine.channel_state(channel) == 'Ready for posting'
                        and expires >= self.clock())
        except (AlphaError, KeyError, TypeError):
            return False

    def claim(self, *, youtube_only=False, exclude_youtube=False):
        if youtube_only and exclude_youtube:
            raise AlphaError('Worker platform filters conflict.', 503, code='worker_platform_filter')
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('postriff-worker-v1',0))")
                if not cur.fetchone()[0]:
                    return None
                cur.execute("SELECT to_regclass('public.pr_worker_tenants')")
                capacity_ready = cur.fetchone()[0] is not None
                self.capacity_intervention = None if capacity_ready else {
                    'code': 'youtube_capacity_schema', 'youtubeDispatch': 'paused',
                    'message': 'YouTube dispatch requires reviewed migration 097. No YouTube provider request is sent; other platforms continue.',
                    'nextAction': 'Review and apply migration 097, then verify admission and worker execution.'}
                # A founder account block freezes the workspace like a pending deletion; lifting it resumes the same jobs.
                # Select only tenants with due work, oldest dispatch first. The
                # durable cursor survives cron/worker restarts; a busy tenant
                # cannot monopolize every chunk lease by sorting before others.
                from .youtube.operations import schema_ready
                indexed = youtube_only and capacity_ready and schema_ready(cur)
                cur.execute(due_workspaces_sql(capacity_ready, youtube_only=youtube_only, exclude_youtube=exclude_youtube,
                                              operations_ready=indexed), (self.clock(), self.clock()))
                for candidate in cur.fetchall():
                    if indexed:
                        workspace_id, revision = candidate
                        # The selector owns the row lock. Fetch only the state
                        # considered for this claim, rather than 100 histories.
                        cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s', (workspace_id,))
                        row = cur.fetchone()
                        if not row:
                            continue
                        raw_state = row[0]
                    else:
                        workspace_id, revision, raw_state = candidate
                    state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                    # Projections are selection hints, never account authority.
                    if not state.get('phase2') or 'accountDeletion' in state or 'accountBlock' in state:
                        continue
                    original = json.dumps(state, sort_keys=True)
                    if youtube_only or exclude_youtube:
                        # Invalidation can hold jobs too; the isolated lane must
                        # not change another platform's review or queued job.
                        data = state['phase2']
                        jobs, reviews = data['jobs'], data['reviews']
                        def selected_platform(item):
                            match = item.get('manifest', {}).get('platform') == 'YouTube'
                            return match if youtube_only else not match
                        data['jobs'] = [job for job in jobs if selected_platform(job)]
                        data['reviews'] = [review for review in reviews if selected_platform(review)]
                        try:
                            self.commands.engine.invalidate(state)
                        finally:
                            data['jobs'], data['reviews'] = jobs, reviews
                    else:
                        self.commands.engine.invalidate(state)
                    selected = None
                    for job in sorted(state["phase2"]["jobs"], key=lambda item: item.get('lastDispatchedAt', 0)):
                        is_youtube = job.get('manifest', {}).get('platform') == 'YouTube'
                        if (youtube_only and not is_youtube) or (exclude_youtube and is_youtube):
                            continue
                        now = self.clock()
                        if job.get("leaseUntil", 0) > now or job.get("nextAt", 0) > now or job.get("state") in (*TERMINAL, "held"):
                            continue
                        stage = job.get('progress', {}).get('stage')
                        instagram = job['manifest']['platform'] == 'Instagram' and hasattr(self.social, 'advance_instagram')
                        if instagram and job.get('container') and not stage:
                            self._event(job, 'uncertain', 'Legacy container has no durable stage; reconcile without creating or publishing again')
                        forward = instagram and stage in ('container_created', 'container_ready') and job['state'] == 'processing'
                        youtube_forward = (job['manifest']['platform'] == 'YouTube' and bool(getattr(self.social, 'youtube', None))
                                           and (stage not in ('native_scheduled', 'native_schedule_reconciling') or job.get('cancelRequested')))
                        if job.get("cancelRequested") and (job.get("state") not in IN_FLIGHT or forward):
                            self._event(job, "canceled", "Canceled before provider submission")
                            continue
                        if job['manifest']['platform'] == 'YouTube' and not capacity_ready:
                            # Preserve the operation, approval and journal. Once
                            # the schema exists this same due job can resume;
                            # no lease, provider attempt or replacement is made.
                            if not job.get('capacityIntervention'):
                                self._event(job, job['state'], self.capacity_intervention['message'])
                            job['capacityIntervention'] = dict(self.capacity_intervention)
                            job['nextAction'] = self.capacity_intervention['nextAction']
                            job['nextAt'] = now + 60
                            continue
                        job.pop('capacityIntervention', None)
                        if job.get("state") == "submitting":
                            self._event(job, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                        reconciliation = job.get("state") in IN_FLIGHT and not forward
                        # YouTube forward authority is checked after the fenced claim,
                        # following exact-connection revalidation outside database locks.
                        # Accepted native schedules only read back.
                        if forward and not self._approved(cur, workspace_id, state, job):
                            self._event(job, 'held', 'Approval, account, media, timing or permission changed; a new review is required')
                            continue
                        if not reconciliation:
                            from .billing import require_publishing
                            try:
                                require_publishing(cur, workspace_id, now)
                                assert_job_authority(state, job, now)
                            except AlphaError as error:
                                self._event(job, "held", str(error))
                                continue
                            cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
                            member = cur.fetchone()
                            # Re-authorize at claim time: the approver must still hold approve authority.
                            if (not member or not Membership.from_row(member[0], can_publish=member[1]).allows("approve")
                                    or (job.get('youtubeAgent') and member[0] != 'owner')
                                    or job['approvalDigest'] != digest(job['manifest'])
                                    or job['approvedBy'] != job['manifest']['actor']):
                                self._event(job, 'held', 'Approval authority changed; a new review is required')
                                continue
                        if not reconciliation and not forward and len(job.get("attempts", [])) >= 3:
                            self._event(job, "failed", "Bounded retry limit reached")
                            from . import product_events
                            product_events.publish_outcome(cur, workspace_id, job, "failed")
                            continue
                        youtube_generation = None
                        if is_youtube:
                            from .youtube import workspace_provider_data as youtube_data
                            cur.execute("SELECT authorization_generation::text FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s AND provider='youtube' AND revoked_at IS NULL FOR NO KEY UPDATE",
                                        (workspace_id, job['manifest'].get('channelId')))
                            credential = cur.fetchone()
                            youtube_generation = credential[0] if credential else None
                            prior_source = job.get(youtube_data.KEY) if isinstance(job.get(youtube_data.KEY), dict) else {}
                            if (not youtube_generation or job.get(youtube_data.REMOVED)
                                    or (prior_source and prior_source.get('authorizationGeneration') != youtube_generation)):
                                youtube_data.scrub_job(job, 'youtube_authorization_data_removed', now)
                                continue
                        previous_state = job['state']
                        job["leaseOwner"] = self.worker_id
                        job["leaseUntil"] = now + 45
                        job["leaseId"] = uuid.uuid4().hex
                        job['lastDispatchedAt'] = now
                        if reconciliation:
                            job["checks"] = job.get("checks", 0) + 1
                        elif not forward:
                            self._event(job, "claimed", "Hosted worker acquired the fenced lease")
                            if not youtube_forward:
                                job.setdefault("attempts", []).append({"number": len(job.get("attempts", [])) + 1, "startedAt": now, "idempotencyKey": job["manifest"]["idempotencyKey"]})
                                self._event(job, "submitting", "Hosted worker began the approved provider operation")
                        selected = {"workspaceId": workspace_id, "job": copy.deepcopy(job), "reconciliation": reconciliation}
                        if is_youtube:
                            selected['youtubeAuthorizationGeneration'] = youtube_generation
                        if youtube_forward:
                            selected.update(youtubeForward=True, previousState=previous_state)
                        if instagram and not reconciliation:
                            action = 'status' if stage == 'container_created' else 'publish' if stage == 'container_ready' else 'create'
                            if action != 'status':
                                job['progress'] = {'version': 1, 'stage': action + '_attempted'}
                                self._event(job, 'submitting', 'Durable Instagram ' + action + ' intent recorded')
                            selected.update(job=copy.deepcopy(job), instagramAction=action)
                        break
                    if selected or json.dumps(state, sort_keys=True) != original:
                        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), workspace_id, revision))
                        if cur.rowcount != 1:
                            raise AlphaError("Worker claim lost its workspace revision.", 409)
                    if selected:
                        if capacity_ready:
                            cur.execute('''INSERT INTO public.pr_worker_tenants(workspace_id,last_claimed_at) VALUES(%s,to_timestamp(%s))
                                ON CONFLICT(workspace_id) DO UPDATE SET last_claimed_at=excluded.last_claimed_at''', (workspace_id, now))
                        return selected
        return None

    def complete(self, claimed, result):
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (claimed["workspaceId"],))
                row = cur.fetchone()
                if not row:
                    return False
                revision, raw_state = row
                state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                job = find(state["phase2"]["jobs"], claimed["job"]["id"])
                if (job.get("leaseOwner") != self.worker_id or job.get("leaseId") != claimed["job"].get("leaseId")
                        or job.get('leaseUntil', 0) <= self.clock()):
                    return False
                youtube_source = None
                if job.get('manifest', {}).get('platform') == 'YouTube':
                    from .youtube import workspace_provider_data as youtube_data
                    try:
                        generation = youtube_data.assert_completion(cur, claimed['workspaceId'], job, claimed, self.clock())
                        youtube_source = youtube_data.source(claimed['workspaceId'], job, generation, self.clock())
                        if youtube_source['expiresAt'] <= self.clock():
                            raise AlphaError('The previous YouTube runtime output expired.', 409, code='youtube_stale_completion')
                    except AlphaError:
                        youtube_data.scrub_job(job, 'youtube_stale_result_removed', self.clock())
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s',
                                    (json.dumps(state), claimed['workspaceId'], revision))
                        return False
                result = normalize_result(result, job, claimed['reconciliation'])
                self._event(job, result["state"], result["confirmed"])
                if result.get("reference"):
                    job["providerReference"] = result["reference"]
                job["providerConfirmed"] = result["confirmed"]
                job["verification"] = {"method": result.get("verification"), "at": self.clock()} if result["state"] == "verified" else None
                if result.get("container"):
                    job["container"] = result["container"]
                if result.get("url"):
                    job["url"] = result["url"]
                job['resultSchema'] = result.get('schema')
                if result.get('progress'):
                    job['progress'] = result['progress']
                if youtube_source is not None:
                    job[youtube_data.KEY] = youtube_source
                published = result['state'] == 'verified' and (job['manifest']['platform'] != 'YouTube' or (result.get('progress') or {}).get('stage') == 'published')
                if published and self.on_verified:
                    try:
                        self.on_verified(cur, claimed["workspaceId"], job)
                    except Exception:
                        job["insights"] = {"availability": "unavailable", "note": "Insights ingestion failed; publication verification is unaffected."}
                if published:
                    # Learning signal (ids and numbers only); a failure to record never affects the publication.
                    record_published(cur, claimed["workspaceId"], job, self.clock())
                if result["state"] in ("verified", "failed"):
                    from . import product_events
                    # Product taxonomy (PRD §8.6): publish.verified|failed behind its own savepoint; never affects the job.
                    product_events.publish_outcome(cur, claimed["workspaceId"], job, result["state"])
                if job.get("attempts") and not claimed["reconciliation"]:
                    job["attempts"][-1]["endedAt"] = self.clock()
                job["leaseOwner"], job["leaseUntil"] = None, 0
                job["nextAt"] = self.clock() + (60 if result["state"] in ('scheduled', 'processing') else 5)
                youtube_progress = job['manifest']['platform'] == 'YouTube' and (result.get('progress') or {}).get('version') == 2
                if youtube_progress:
                    progress = result['progress']
                    retry_at = progress.get('retryAt')
                    job['nextAt'] = max(self.clock() + 1, retry_at) if isinstance(retry_at, (int, float)) else self.clock() + 60
                    if progress.get('stage') == 'native_scheduled':
                        job['nextAt'] = self.clock() + 300
                    job['nextAction'] = 'Reconcile the existing YouTube session or immutable Video ID; never re-upload this operation'
                if result['state'] == 'processing':
                    job['processingChecks'] = job.get('processingChecks', 0) + 1
                    if job['processingChecks'] >= 6 and job.get('progress', {}).get('stage') == 'container_created':
                        self._event(job, 'held', 'Container processing did not finish within bounded checks; review before continuing')
                if job.get("checks", 0) >= 5 and job["state"] in IN_FLIGHT and not youtube_progress:
                    job["nextAt"] = self.clock() + 86400
                    job["nextAction"] = "Manual provider review required; do not resubmit"
                elif job["state"] == "held":
                    job["nextAction"] = "Review provider permission and configuration"
                elif job["state"] == "failed":
                    job["nextAction"] = "Correct the cause and create a new exact approval"
                elif job["state"] in TERMINAL:
                    job["nextAction"] = "Inspect receipt"
                else:
                    job["nextAction"] = "Await container processing; not published" if job['state'] == 'processing' else "Await provider reconciliation; do not resubmit"
                if youtube_progress and progress.get('stage') == 'quota_delayed':
                    job['nextAction'] = 'Publishing delayed by capacity controls; the same approved upload resumes after retryAt. Review the time if approval or publication time expires.'
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), claimed["workspaceId"], revision))
                return cur.rowcount == 1

    def authorize_dispatch(self, claimed, *, youtube_verified=False):
        """Re-read cancellation, exact approval and fence immediately before forward work."""
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
                row = cur.fetchone()
                if not row:
                    return False
                state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                job = find(state['phase2']['jobs'], claimed['job']['id'])
                if (job.get('leaseOwner') != self.worker_id or job.get('leaseId') != claimed['job'].get('leaseId')
                        or job.get('leaseUntil', 0) <= self.clock()):
                    return False
                if job.get('state') in (*TERMINAL, 'held'):
                    # Disconnect/cancellation may have ended a claimed operation
                    # while verification was in flight. A later reconnect never
                    # makes that same stale worker's lease a fresh approval.
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                if job.get('manifest', {}).get('platform') == 'YouTube':
                    from .youtube import workspace_provider_data as youtube_data
                    try:
                        youtube_data.assert_completion(cur, claimed['workspaceId'], job, claimed, self.clock())
                    except AlphaError:
                        youtube_data.scrub_job(job, 'youtube_stale_result_removed', self.clock())
                        cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                        return False
                youtube_cancel = (claimed.get('youtubeForward') and claimed['reconciliation']
                                  and claimed['job'].get('cancelRequested') is True)
                if (claimed.get('youtubeForward') and claimed['reconciliation']
                        and job.get('cancelRequested') and not youtube_cancel):
                    # The claimed copy would continue uploading. Release this fence
                    # so the next reconciliation observes the pending cancellation.
                    self._event(job, job['state'], 'Cancellation changed during verification; reconcile a fresh fenced snapshot')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    job['nextAt'] = self.clock() + 1
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                if ((job.get('cancelRequested') and not youtube_cancel)
                        or (claimed.get('youtubeForward') and not youtube_verified)
                        or not self._approved(cur, claimed['workspaceId'], state, job)):
                    # No call has been made by this fenced dispatch. Preserve any prior container.
                    stopped = 'canceled' if job.get('cancelRequested') and not claimed['reconciliation'] else 'held'
                    self._event(job, stopped, 'Stopped before provider dispatch; cancellation or approval changed')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                if claimed.get('youtubeForward') and not claimed['reconciliation']:
                    job.setdefault('attempts', []).append({'number': len(job.get('attempts', [])) + 1,
                        'startedAt': self.clock(), 'idempotencyKey': job['manifest']['idempotencyKey']})
                    self._event(job, 'submitting', 'Hosted worker began the approved provider operation')
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                return True

    def defer_youtube_dispatch(self, claimed):
        """Release an unsent fenced operation after unavailable grant verification."""
        with self.connection_factory() as db, db.cursor() as cur:
            cur.execute('SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE', (claimed['workspaceId'],))
            row = cur.fetchone()
            if not row:
                return False
            state = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            job = find(state['phase2']['jobs'], claimed['job']['id'])
            if (job.get('leaseOwner') != self.worker_id or job.get('leaseId') != claimed['job'].get('leaseId')
                    or job.get('leaseUntil', 0) <= self.clock()):
                return False
            if job['state'] == 'claimed':
                self._event(job, claimed['previousState'], 'YouTube verification unavailable; no provider operation was sent')
            job['leaseOwner'], job['leaseUntil'] = None, 0
            job['nextAt'] = self.clock() + 60
            cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
            return True

    def step(self, crash=None, *, youtube_only=False, exclude_youtube=False):
        claimed = (self.claim(youtube_only=youtube_only, exclude_youtube=exclude_youtube)
                   if youtube_only or exclude_youtube else self.claim())
        if not claimed or crash == "after_claim":
            return bool(claimed)
        if claimed.get('youtubeForward'):
            try:
                verification = self.social.youtube.oauth.reverify_for_worker(claimed['workspaceId'], claimed['job']['manifest']['channelId'])
            except AlphaError as error:
                verification = {'state': 'reauthorization_required' if error.status == 404 or error.code == 'youtube_revoked_oauth' else 'verification_unavailable'}
            if verification.get('state') == 'verification_unavailable':
                self.defer_youtube_dispatch(claimed)
                return True
            verified = verification.get('state') == 'read_verified' and verification.get('ready') is True
            if not self.authorize_dispatch(claimed, youtube_verified=verified):
                return True
        elif not claimed['reconciliation'] and not self.authorize_dispatch(claimed):
            return True
        try:
            if claimed.get('instagramAction'):
                result = self.social.advance_instagram(claimed['job']['manifest'], claimed['job'], claimed['instagramAction'])
            elif claimed["reconciliation"]:
                result = self.social.reconcile(claimed["job"]["manifest"], claimed["job"])
            else:
                result = self.social.submit(claimed["job"]["manifest"])
        except Exception:
            result = unknown()
        if crash == "after_provider":
            return True
        self.complete(claimed, result)
        return True

    def tick(self, max_jobs=None, max_seconds=None):
        from .youtube.fleet import enabled
        fleet_owns_youtube = enabled()
        return self._tick(max_jobs, max_seconds, exclude_youtube=fleet_owns_youtube)

    def tick_youtube(self, max_jobs, max_seconds):
        """Dedicated lane: no other platform or maintenance dispatch can run."""
        return self._tick(max_jobs, max_seconds, youtube_only=True)

    def _tick(self, max_jobs=None, max_seconds=None, *, youtube_only=False, exclude_youtube=False):
        if max_jobs is None or max_seconds is None:
            configured_jobs, configured_seconds = configured_worker_limits()
            max_jobs = configured_jobs if max_jobs is None else max_jobs
            max_seconds = configured_seconds if max_seconds is None else max_seconds
        if type(max_jobs) is not int or not 1 <= max_jobs <= 25 or type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 45:
            raise AlphaError("Use bounded worker limits.")
        started, processed = time.monotonic(), 0
        youtube = getattr(self.social, 'youtube', None) or getattr(self, 'youtube_maintenance', None)
        maintenance = ({'enabled': False, 'scheduler': 'isolated_upload_lane'} if youtube_only else
                       youtube.maintenance(dispatch=False) if youtube and exclude_youtube else
                       youtube.maintenance() if youtube else {'enabled': False})
        def step():
            return (self.step(youtube_only=youtube_only, exclude_youtube=exclude_youtube)
                    if youtube_only or exclude_youtube else self.step())
        while processed < max_jobs and time.monotonic() - started < max_seconds and step():
            processed += 1
        return {"processed": processed, "execution": "hosted-worker", "externalExecution": not isinstance(self.social, DisabledHostedSocial),
                "youtubeMaintenance": maintenance, "capacityIntervention": getattr(self, 'capacity_intervention', None),
                "budget": {"maxJobs": max_jobs, "maxSeconds": max_seconds}}
