"""Bounded PostgreSQL worker for browser-independent Phase 2 schedules."""
import copy
import json
import math
import time
import uuid

from postriff_alpha.domain import AlphaError
from .store import IN_FLIGHT, TERMINAL, find
from .hosted import HostedPhase2Commands
from .contracts import digest
from .outcomes import normalize_result, unknown
from .permissions import Membership, require
from .learning_service import record_published

NO_SUBMISSION_CONFIRMED = 'Live provider transport is not configured; nothing was submitted'
PREVIEW_PENDING_MESSAGE = 'Approved preview post; choose Publish approved post when due.'


def _no_provider_effect(job):
    return not any(job.get(key) for key in ('providerReference', 'container', 'providerUpload',
                                            'providerAssets', 'providerThread', 'progress', 'url', 'verification'))


class DisabledHostedSocial:
    """Fail closed until an exact provider transport and token vault are configured."""
    def submit(self, _manifest):
        return {"state": "held", "confirmed": NO_SUBMISSION_CONFIRMED}

    def reconcile(self, _manifest, _job):
        return {"state": "uncertain", "confirmed": "Provider reconciliation is unavailable; do not resubmit"}


class PostgresWorker:
    def __init__(self, connection_factory, social=None, clock=time.time, worker_id=None, on_verified=None, worker_binding=None):
        self.connection_factory = connection_factory
        self.social = social or DisabledHostedSocial()
        self.clock = clock
        self.worker_id = worker_id or "worker-" + uuid.uuid4().hex
        self.commands = HostedPhase2Commands(clock, worker_binding=worker_binding)
        self.worker_binding = self.commands.engine.worker_binding
        # Optional server-side hook (e.g. native insights ingestion) run in the same transaction once verified.
        self.on_verified = on_verified

    def _event(self, job, state, message):
        job["state"] = state
        job.setdefault("events", []).append({"at": self.clock(), "state": state, "message": message, "execution": "hosted-worker"})

    def _binding_matches(self, job):
        manifest = job.get('manifest') or {}
        if 'workerBinding' in manifest and 'workerBinding' in job and manifest['workerBinding'] != job['workerBinding']:
            return False
        binding = job.get('workerBinding', manifest.get('workerBinding'))
        return binding == self.worker_binding

    def _may_adopt_legacy_hold(self, job):
        """One definitive disabled-transport result, never an unknown provider outcome."""
        attempts = job.get('attempts') or []
        event = (job.get('events') or [{}])[-1]
        return bool(self.worker_binding is not None and 'workerBinding' not in job
                    and 'workerBinding' not in (job.get('manifest') or {})
                    and job.get('state') == 'held' and not job.get('cancelRequested')
                    and job.get('resultSchema') == 'postriff.result.v1' and _no_provider_effect(job)
                    and job.get('providerConfirmed') == NO_SUBMISSION_CONFIRMED
                    and event.get('state') == 'held' and event.get('message') == NO_SUBMISSION_CONFIRMED
                    and len(attempts) == 1 and attempts[0].get('number') == 1
                    and type(attempts[0].get('startedAt')) in (int, float)
                    and type(attempts[0].get('endedAt')) in (int, float)
                    and math.isfinite(attempts[0]['startedAt']) and math.isfinite(attempts[0]['endedAt'])
                    and attempts[0]['endedAt'] >= attempts[0]['startedAt'])

    def _preview_hold(self, job):
        event = (job.get('events') or [{}])[-1]
        return bool(self.worker_binding is not None and self._binding_matches(job)
                    and job.get('manifest', {}).get('workerBinding') == self.worker_binding
                    and job.get('state') == 'held' and job.get('previewDispatchPending') is True
                    and not job.get('attempts') and _no_provider_effect(job)
                    and event.get('state') == 'held' and event.get('message') == PREVIEW_PENDING_MESSAGE)

    def _invalidate_owned(self, state):
        # A shared database may contain approvals from another deployment. Filter before
        # invalidation as well as before claim; neither reviews nor jobs may cross that boundary.
        data = state['phase2']
        view = {**state, 'phase2': {**data,
                'jobs': [job for job in data['jobs'] if self._binding_matches(job)],
                'reviews': [review for review in data['reviews'] if self._binding_matches({'manifest': review['manifest']})]}}
        self.commands.engine.invalidate(view)

    def _approved(self, cur, workspace_id, state, job):
        from .billing import require_publishing
        try:
            if state.get('accountDeletion') or state.get('accountBlock'): return False
            require_publishing(cur, workspace_id, self.clock())
            manifest = job['manifest']
            channel = find(state['phase2']['channels'], manifest['channelId'])
            cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
            member = cur.fetchone()
            return bool(member and Membership.from_row(member[0], can_publish=member[1]).allows('approve')
                        and job['approvalDigest'] == digest(manifest) and job['approvedBy'] == manifest['actor']
                        and self.commands.engine.current(state, manifest)
                        and self.commands.engine.channel_state(channel) == 'Ready for posting'
                        and manifest['expiresAt'] >= self.clock())
        except (AlphaError, KeyError, TypeError):
            return False

    @staticmethod
    def _requester_may_approve(cur, workspace_id, principal):
        cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, principal))
        member = cur.fetchone()
        return bool(member and Membership.from_row(member[0], can_publish=member[1]).allows('approve'))

    def execute_job(self, repository, workspace_id, token, job_id, approval_digest):
        """An authenticated nudge of one existing approval, never a new or forced submission."""
        if (not isinstance(approval_digest, str) or len(approval_digest) != 64
                or set(approval_digest) - set('0123456789abcdef')):
            raise AlphaError('Send the exact stored approval for this post.', 409)
        with repository.transaction(token, workspace_id) as (_, row, principal):
            require(Membership.from_row(*row[2:7]), 'approve')
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            if state.get('workspace', {}).get('sample'):
                raise AlphaError('Hosted sample workspaces are read-only.', 403)
            job = find(state.get('phase2', {}).get('jobs', []), job_id)
            if (job['manifest'].get('workspaceId') != workspace_id
                    or approval_digest != job.get('approvalDigest') or approval_digest != digest(job['manifest'])):
                raise AlphaError('This approval changed. Reload the post before continuing.', 409)
            if not self._binding_matches(job) and not self._may_adopt_legacy_hold(job):
                raise AlphaError('Open this approved post in the deployment where it was reviewed.', 409)
        processed = self.step(workspace_id=workspace_id, job_id=job_id, approval_digest=approval_digest,
                              dispatch_principal=principal)
        return {'processed': int(processed), 'execution': 'hosted-worker', 'jobId': job_id}

    def claim(self, *, workspace_id=None, job_id=None, approval_digest=None, dispatch_principal=None):
        scoped = any(value is not None for value in (workspace_id, job_id, approval_digest, dispatch_principal))
        if scoped and not all(isinstance(value, str) and value for value in (workspace_id, job_id, approval_digest, dispatch_principal)):
            raise AlphaError('Select one workspace, job and exact approval.', 409)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('postriff-worker-v1',0))")
                if not cur.fetchone()[0]:
                    return None
                # A founder account block freezes the workspace like a pending deletion; lifting it resumes the same jobs.
                query = "SELECT id::text,revision,state FROM public.pr_workspaces WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'"
                if scoped:
                    cur.execute(query + ' AND id=%s ORDER BY id FOR UPDATE SKIP LOCKED', (workspace_id,))
                else:
                    cur.execute(query + ' ORDER BY id FOR UPDATE SKIP LOCKED')
                for workspace_id, revision, raw_state in cur.fetchall():
                    state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                    original = json.dumps(state, sort_keys=True)
                    if scoped:
                        if not self._requester_may_approve(cur, workspace_id, dispatch_principal):
                            raise AlphaError("This action needs the 'approve' permission in this workspace.", 403)
                        target = find(state['phase2']['jobs'], job_id)
                        if (target['manifest'].get('workspaceId') != workspace_id
                                or approval_digest != target.get('approvalDigest') or approval_digest != digest(target['manifest'])):
                            raise AlphaError('This approval changed. Reload the post before continuing.', 409)
                    else:
                        self._invalidate_owned(state)
                    selected = None
                    for job in state["phase2"]["jobs"]:
                        if scoped and job.get('id') != job_id:
                            continue
                        adopt_legacy = scoped and self._may_adopt_legacy_hold(job)
                        if not self._binding_matches(job) and not adopt_legacy:
                            if scoped:
                                raise AlphaError('Open this approved post in the deployment where it was reviewed.', 409)
                            continue
                        now = self.clock()
                        if job.get("leaseUntil", 0) > now or job.get("nextAt", 0) > now or job.get("state") in TERMINAL:
                            continue
                        release_hold = scoped and (self._preview_hold(job) or adopt_legacy)
                        if job.get('state') == 'held' and not release_hold:
                            continue
                        if scoped and job.get('providerReference') and job.get('state') not in IN_FLIGHT:
                            self._event(job, 'uncertain', 'Known provider receipt retained; reconcile without creating another post')
                        stage = job.get('progress', {}).get('stage')
                        from .official_publishers import ASYNC_PLATFORMS, FORWARD_STAGES
                        official = (job['manifest']['platform'] in ASYNC_PLATFORMS and hasattr(self.social, 'official_enabled')
                                    and self.social.official_enabled(job['manifest']))
                        instagram = official or (job['manifest']['platform'] == 'Instagram' and hasattr(self.social, 'advance_instagram'))
                        if instagram and job.get('container') and not stage:
                            self._event(job, 'uncertain', 'Legacy container has no durable stage; reconcile without creating or publishing again')
                        forward = instagram and stage in FORWARD_STAGES and job['state'] == 'processing'
                        if job.get("cancelRequested") and (job.get("state") not in IN_FLIGHT or forward):
                            self._event(job, "held" if job.get('providerThread') else "canceled", "Further thread creation stopped; already-created provider posts remain" if job.get('providerThread') else "Canceled before provider submission")
                            continue
                        if job.get("state") == "submitting":
                            self._event(job, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                        reconciliation = job.get("state") in IN_FLIGHT and not forward
                        if (forward or (scoped and not reconciliation)) and not self._approved(cur, workspace_id, state, job):
                            self._event(job, 'held', 'Approval, account, media, timing or permission changed; a new review is required')
                            continue
                        if not reconciliation:
                            from .billing import require_publishing
                            try:
                                require_publishing(cur, workspace_id, now)
                            except AlphaError as error:
                                self._event(job, "held", str(error))
                                continue
                            cur.execute("SELECT m.role,m.can_publish FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
                            member = cur.fetchone()
                            # Re-authorize at claim time: the approver must still hold approve authority.
                            if (not member or not Membership.from_row(member[0], can_publish=member[1]).allows("approve")
                                    or job['approvalDigest'] != digest(job['manifest'])
                                    or job['approvedBy'] != job['manifest']['actor']):
                                self._event(job, 'held', 'Approval authority changed; a new review is required')
                                continue
                        if not reconciliation and not forward and len(job.get("attempts", [])) >= 3:
                            self._event(job, "failed", "Bounded retry limit reached")
                            from . import product_events
                            product_events.publish_outcome(cur, workspace_id, job, "failed")
                            continue
                        if release_hold:
                            if adopt_legacy:
                                # Retain the original exact manifest/digest and attempt history.
                                # The requester authorizes this server-owned deployment binding now.
                                job['workerBinding'] = copy.deepcopy(self.worker_binding)
                            job.pop('previewDispatchPending', None)
                            self._event(job, 'scheduled', 'Approved preview post released by the authenticated exact-job worker action')
                        job["leaseOwner"] = self.worker_id
                        job["leaseUntil"] = now + 45
                        job["leaseId"] = uuid.uuid4().hex
                        if reconciliation:
                            job["checks"] = job.get("checks", 0) + 1
                        elif not forward:
                            self._event(job, "claimed", "Hosted worker acquired the fenced lease")
                            job.setdefault("attempts", []).append({"number": len(job.get("attempts", [])) + 1, "startedAt": now, "idempotencyKey": job["manifest"]["idempotencyKey"]})
                            self._event(job, "submitting", "Hosted worker began the approved provider operation")
                        selected = {"workspaceId": workspace_id, "job": copy.deepcopy(job), "reconciliation": reconciliation}
                        if scoped:
                            selected['dispatchPrincipal'] = dispatch_principal
                        if official and reconciliation and job.get('cancelRequested') and job['manifest'].get('nativeScheduleAt') and job.get('providerReference'):
                            if job.get('progress', {}).get('stage') != 'cancel_attempted':
                                job['progress'] = {'version': 1, 'stage': 'cancel_attempted'}
                                selected.update(job=copy.deepcopy(job), nativeCancel=True)
                        if instagram and not reconciliation:
                            action = 'status' if stage in ('container_created', 'children_created', 'assets_uploaded') else 'parent' if stage == 'children_ready' else 'publish' if stage in ('container_ready', 'thread_ready') else 'upload' if stage == 'upload_session' else 'finalize' if stage == 'upload_finalizable' else 'metadata' if stage == 'metadata_pending' else 'create'
                            if action != 'status':
                                job['progress'] = {'version': 1, 'stage': action + '_attempted'}
                                self._event(job, 'submitting', 'Durable provider ' + action + ' intent recorded')
                            selected.update(job=copy.deepcopy(job), instagramAction=action, officialAction=official)
                        break
                    if selected or json.dumps(state, sort_keys=True) != original:
                        cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), workspace_id, revision))
                        if cur.rowcount != 1:
                            raise AlphaError("Worker claim lost its workspace revision.", 409)
                    if selected:
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
                result = normalize_result(result, job, claimed['reconciliation'])
                self._event(job, result["state"], result["confirmed"])
                if result.get("reference"):
                    job["providerReference"] = result["reference"]
                if "providerUpload" in result:
                    job["providerUpload"] = result["providerUpload"]
                if "providerAssets" in result:
                    job["providerAssets"] = result["providerAssets"]
                for key in ('providerThread', 'threadChecked'):
                    if key in result: job[key] = result[key]
                job["providerConfirmed"] = result["confirmed"]
                job["verification"] = {"method": result.get("verification"), "at": self.clock()} if result["state"] == "verified" else None
                if result.get("container"):
                    job["container"] = result["container"]
                if result.get("url"):
                    job["url"] = result["url"]
                job['resultSchema'] = result.get('schema')
                if result.get('progress'):
                    job['progress'] = result['progress']
                if result["state"] == "verified" and self.on_verified:
                    try:
                        self.on_verified(cur, claimed["workspaceId"], job)
                    except Exception:
                        job["insights"] = {"availability": "unavailable", "note": "Insights ingestion failed; publication verification is unaffected."}
                if result["state"] == "verified":
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
                if result['state'] == 'processing':
                    job['processingChecks'] = job.get('processingChecks', 0) + 1
                    if job['processingChecks'] >= (20 if getattr(self.social, 'official_enabled', lambda _: False)(job.get('manifest') or {}) else 6) and job.get('progress', {}).get('stage') in ('container_created', 'children_created', 'assets_uploaded'):
                        self._event(job, 'held', 'Container processing did not finish within bounded checks; review before continuing')
                if result['state'] == 'native_scheduled':
                    job['nextAt'] = max(self.clock()+60, job['manifest']['nativeScheduleAt'])
                if job.get("checks", 0) >= 5 and job["state"] in IN_FLIGHT and job['state'] != 'native_scheduled':
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
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), claimed["workspaceId"], revision))
                return cur.rowcount == 1

    def authorize_dispatch(self, claimed):
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
                requester_allowed = (not claimed.get('dispatchPrincipal')
                                     or self._requester_may_approve(cur, claimed['workspaceId'], claimed['dispatchPrincipal']))
                if (job.get('cancelRequested') or not requester_allowed or not self._binding_matches(job)
                        or not self._approved(cur, claimed['workspaceId'], state, job)):
                    # No call has been made by this fenced dispatch. Preserve any prior container.
                    self._event(job, 'canceled' if job.get('cancelRequested') and not job.get('providerThread') else 'held', 'Stopped before provider dispatch; prior provider posts, if any, remain')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                return True

    def step(self, crash=None, *, workspace_id=None, job_id=None, approval_digest=None, dispatch_principal=None):
        scope = (workspace_id, job_id, approval_digest, dispatch_principal)
        claimed = (self.claim(workspace_id=workspace_id, job_id=job_id, approval_digest=approval_digest,
                              dispatch_principal=dispatch_principal) if any(value is not None for value in scope) else self.claim())
        if not claimed or crash == "after_claim":
            return bool(claimed)
        if not claimed['reconciliation'] and not self.authorize_dispatch(claimed):
            return True
        try:
            if claimed.get('instagramAction'):
                advance = self.social.advance_official if claimed.get('officialAction') else self.social.advance_instagram
                result = advance(claimed['job']['manifest'], claimed['job'], claimed['instagramAction'])
            elif claimed.get("nativeCancel"):
                result = self.social.cancel_native(claimed["job"]["manifest"], claimed["job"])
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

    def tick(self, max_jobs=10, max_seconds=20):
        if type(max_jobs) is not int or not 1 <= max_jobs <= 25 or type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 45:
            raise AlphaError("Use bounded worker limits.")
        started, processed = time.monotonic(), 0
        while processed < max_jobs and time.monotonic() - started < max_seconds and self.step():
            processed += 1
        return {"processed": processed, "execution": "hosted-worker", "externalExecution": not isinstance(self.social, DisabledHostedSocial)}
