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


class DisabledHostedSocial:
    """Fail closed until an exact provider transport and token vault are configured."""
    def submit(self, _manifest):
        return {"state": "held", "confirmed": "Live provider transport is not configured; nothing was submitted"}

    def reconcile(self, _manifest, _job):
        return {"state": "uncertain", "confirmed": "Provider reconciliation is unavailable; do not resubmit"}


class PostgresWorker:
    def __init__(self, connection_factory, social=None, clock=time.time, worker_id=None):
        self.connection_factory = connection_factory
        self.social = social or DisabledHostedSocial()
        self.clock = clock
        self.worker_id = worker_id or "worker-" + uuid.uuid4().hex
        self.commands = HostedPhase2Commands(clock)

    def _event(self, job, state, message):
        job["state"] = state
        job.setdefault("events", []).append({"at": self.clock(), "state": state, "message": message, "execution": "hosted-worker"})

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
                        if job.get("cancelRequested") and job.get("state") not in IN_FLIGHT:
                            self._event(job, "canceled", "Canceled before provider submission")
                            continue
                        if job.get("state") == "submitting":
                            self._event(job, "uncertain", "Worker lease expired after submission started; reconcile before retry")
                        reconciliation = job.get("state") in IN_FLIGHT
                        if not reconciliation:
                            cur.execute("SELECT m.role FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR SHARE OF m,p", (workspace_id, job['approvedBy']))
                            member = cur.fetchone()
                            if (not member or member[0] not in ('owner', 'editor')
                                    or job['approvalDigest'] != digest(job['manifest'])
                                    or job['approvedBy'] != job['manifest']['actor']):
                                self._event(job, 'held', 'Approval authority changed; a new review is required')
                                continue
                        if not reconciliation and len(job.get("attempts", [])) >= 3:
                            self._event(job, "failed", "Bounded retry limit reached")
                            continue
                        job["leaseOwner"] = self.worker_id
                        job["leaseUntil"] = now + 45
                        job["leaseId"] = uuid.uuid4().hex
                        if reconciliation:
                            job["checks"] = job.get("checks", 0) + 1
                        else:
                            self._event(job, "claimed", "Hosted worker acquired the fenced lease")
                            job.setdefault("attempts", []).append({"number": len(job.get("attempts", [])) + 1, "startedAt": now, "idempotencyKey": job["manifest"]["idempotencyKey"]})
                            self._event(job, "submitting", "Hosted worker began the approved provider operation")
                        selected = {"workspaceId": workspace_id, "job": copy.deepcopy(job), "reconciliation": reconciliation}
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
                if job.get("leaseOwner") != self.worker_id or job.get("leaseId") != claimed["job"].get("leaseId"):
                    return False
                result = normalize_result(result, job, claimed['reconciliation'])
                self._event(job, result["state"], result["confirmed"])
                if result.get("reference"):
                    job["providerReference"] = result["reference"]
                job["providerConfirmed"] = result["confirmed"]
                job["verification"] = {"method": result.get("verification"), "at": self.clock()} if result["state"] == "verified" else None
                if job.get("attempts") and not claimed["reconciliation"]:
                    job["attempts"][-1]["endedAt"] = self.clock()
                job["leaseOwner"], job["leaseUntil"] = None, 0
                job["nextAt"] = self.clock() + (60 if result["state"] == "scheduled" else 5)
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
                    job["nextAction"] = "Await provider reconciliation"
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb,revision=revision+1 WHERE id=%s AND revision=%s", (json.dumps(state), claimed["workspaceId"], revision))
                return cur.rowcount == 1

    def step(self, crash=None):
        claimed = self.claim()
        if not claimed or crash == "after_claim":
            return bool(claimed)
        try:
            if claimed["reconciliation"]:
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
