"""Bounded PostgreSQL worker for browser-independent Phase 2 schedules."""
import copy
import json
import time
import uuid

from postriff_alpha.domain import AlphaError
from .store import IN_FLIGHT, TERMINAL, find
from .hosted import HostedPhase2Commands
from .contracts import digest
from .outcomes import normalize_result, unknown
from .permissions import Membership
from .learning_service import record_published


class DisabledHostedSocial:
    """Fail closed until an exact provider transport and token vault are configured."""
    def submit(self, _manifest):
        return {"state": "held", "confirmed": "Live provider transport is not configured; nothing was submitted"}

    def reconcile(self, _manifest, _job):
        return {"state": "uncertain", "confirmed": "Provider reconciliation is unavailable; do not resubmit"}


class PostgresWorker:
    def __init__(self, connection_factory, social=None, clock=time.time, worker_id=None, on_verified=None):
        self.connection_factory = connection_factory
        self.social = social or DisabledHostedSocial()
        self.clock = clock
        self.worker_id = worker_id or "worker-" + uuid.uuid4().hex
        self.commands = HostedPhase2Commands(clock)
        # Optional server-side hook (e.g. native insights ingestion) run in the same transaction once verified.
        self.on_verified = on_verified

    def _event(self, job, state, message):
        job["state"] = state
        job.setdefault("events", []).append({"at": self.clock(), "state": state, "message": message, "execution": "hosted-worker"})

    def _approved(self, cur, workspace_id, state, job):
        from .billing import require_publishing
        try:
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

    def claim(self):
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('postriff-worker-v1',0))")
                if not cur.fetchone()[0]:
                    return None
                cur.execute("SELECT id::text,revision,state FROM public.pr_workspaces WHERE state ? 'phase2' ORDER BY id FOR UPDATE SKIP LOCKED")
                for workspace_id, revision, raw_state in cur.fetchall():
                    state = json.loads(raw_state) if isinstance(raw_state, str) else raw_state
                    original = json.dumps(state, sort_keys=True)
                    self.commands.engine.invalidate(state)
                    selected = None
                    for job in state["phase2"]["jobs"]:
                        now = self.clock()
                        if job.get("leaseUntil", 0) > now or job.get("nextAt", 0) > now or job.get("state") in (*TERMINAL, "held"):
                            continue
                        stage = job.get('progress', {}).get('stage')
                        instagram = job['manifest']['platform'] == 'Instagram' and hasattr(self.social, 'advance_instagram')
                        if instagram and job.get('container') and not stage:
                            self._event(job, 'uncertain', 'Legacy container has no durable stage; reconcile without creating or publishing again')
                        forward = instagram and stage in ('container_created', 'container_ready') and job['state'] == 'processing'
                        if job.get("cancelRequested") and (job.get("state") not in IN_FLIGHT or forward):
                            self._event(job, "canceled", "Canceled before provider submission")
                            continue
                        if job.get("state") == "submitting":
                            self._event(job, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                        reconciliation = job.get("state") in IN_FLIGHT and not forward
                        if forward and not self._approved(cur, workspace_id, state, job):
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
                            continue
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
                if job.get("attempts") and not claimed["reconciliation"]:
                    job["attempts"][-1]["endedAt"] = self.clock()
                job["leaseOwner"], job["leaseUntil"] = None, 0
                job["nextAt"] = self.clock() + (60 if result["state"] in ('scheduled', 'processing') else 5)
                if result['state'] == 'processing':
                    job['processingChecks'] = job.get('processingChecks', 0) + 1
                    if job['processingChecks'] >= 6 and job.get('progress', {}).get('stage') == 'container_created':
                        self._event(job, 'held', 'Container processing did not finish within bounded checks; review before continuing')
                if job.get("checks", 0) >= 5 and job["state"] in IN_FLIGHT:
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
                if job.get('cancelRequested') or not self._approved(cur, claimed['workspaceId'], state, job):
                    # No call has been made by this fenced dispatch. Preserve any prior container.
                    self._event(job, 'canceled' if job.get('cancelRequested') else 'held', 'Stopped before provider dispatch; cancellation or approval changed')
                    job['leaseOwner'], job['leaseUntil'] = None, 0
                    cur.execute('UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s', (json.dumps(state), claimed['workspaceId']))
                    return False
                return True

    def step(self, crash=None):
        claimed = self.claim()
        if not claimed or crash == "after_claim":
            return bool(claimed)
        if not claimed['reconciliation'] and not self.authorize_dispatch(claimed):
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

    def tick(self, max_jobs=10, max_seconds=20):
        if type(max_jobs) is not int or not 1 <= max_jobs <= 25 or type(max_seconds) not in (int, float) or not 1 <= max_seconds <= 45:
            raise AlphaError("Use bounded worker limits.")
        started, processed = time.monotonic(), 0
        while processed < max_jobs and time.monotonic() - started < max_seconds and self.step():
            processed += 1
        return {"processed": processed, "execution": "hosted-worker", "externalExecution": not isinstance(self.social, DisabledHostedSocial)}
