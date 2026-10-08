"""Durable, leased Library intelligence jobs (engineering spec §4 IntelligenceJob, §6 revocation, §7 pipeline, §12 costs; T02).

One job = one capability of one immutable content version, processed by one processor version. Lifecycle:

    enqueue (idempotent, permission-checked)  ->  claim (FOR UPDATE SKIP LOCKED, leased, attempts+1, committed alone)
    ->  prepare (re-authorize, reserve budget before any cloud call, committed)  ->  run the processor OUTSIDE any
    database transaction (bytes read from private storage with a hash/identity check)  ->  finalize in a new transaction
    (lease check, grant recheck, derivatives written through the owning workstream's writers, cost settled once).

Retries are bounded (3 attempts by default) with exponential backoff, jitter and provider Retry-After. Only retryable
errors retry; permission, corrupt and unsupported input become terminal states. A stale lease (crashed worker) is
recovered by the next tick; a job at its ceiling with an expired lease fails honestly instead of looping. A revocation or
cancellation that lands while a processor runs means nothing is written. Nothing here sends content to telemetry.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from typing import Any, Callable

from postriff_alpha.domain import AlphaError

from ..contracts import digest
from . import capabilities, policy, providers, versions
from . import contracts as c

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
BACKOFF_BASE, BACKOFF_CAP, JITTER, RETRY_AFTER_CAP = 30, 900, 0.25, 3600
ORPHAN_MINUTES = 15
MAX_ITEMS = 5000
MAX_MEDIA_JSON = 64 * 1024
MAX_RAW_BYTES = 100_000_000
REQUEST_KEY = re.compile(r"^[A-Za-z0-9_.:\-]{16,120}$")
ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
SYSTEM_ACTOR = "00000000-0000-0000-0000-000000000000"
OUTCOME_STATES = ("ready", "partial", "unsupported", "failed", "blocked_permission", "blocked_budget")
JOB_STATUS = {"ready": "completed", "partial": "partial", "unsupported": "completed", "failed": "failed",
              "blocked_permission": "blocked", "blocked_budget": "blocked", "cancelled": "cancelled"}
# error codes whose failure means no provider charge happened (the reservation is released, not left unknown)
UNCHARGED = {"library_provider_unavailable", "library_provider_rate_limited", "library_provider_failed", "library_source_changed",
             "library_source_unavailable", "library_storage_not_configured", "library_media_too_large", "library_capability_unavailable",
             "library_processor_contract", "library_corrupt", "library_unsupported"}

JOB_COLS = ("id::text,workspace_id::text,asset_key,capability,processor_version,consent_revision,idempotency_key,status,attempts,max_attempts,"
            "lease_token::text,extract(epoch from lease_expires_at),extract(epoch from next_attempt_at),reservation,cost,error_category,error_code,"
            "requested_by::text,extract(epoch from created_at),extract(epoch from finished_at)")
LOCK = "/*lij:job.lock*/ SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
ACTIVE = (f"/*lij:job.active*/ SELECT {JOB_COLS} FROM public.pr_library_jobs WHERE workspace_id=%s AND asset_key=%s AND capability=%s "
          "AND processor_version=%s AND status IN ('queued','processing') ORDER BY created_at DESC LIMIT 1")
INSERT = ("/*lij:job.insert*/ INSERT INTO public.pr_library_jobs(id,workspace_id,asset_key,capability,processor_version,consent_revision,idempotency_key,"
          f"status,max_attempts,requested_by) VALUES(%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s) ON CONFLICT(workspace_id,idempotency_key) DO NOTHING RETURNING {JOB_COLS}")
BY_KEY = f"/*lij:job.by_key*/ SELECT {JOB_COLS} FROM public.pr_library_jobs WHERE workspace_id=%s AND idempotency_key=%s"
REVIVE = ("/*lij:job.revive*/ UPDATE public.pr_library_jobs SET status='queued',attempts=0,next_attempt_at=now(),lease_token=null,lease_expires_at=null,"
          "error_category=null,error_code=null,finished_at=null,requested_by=coalesce(%s,requested_by),updated_at=now() "
          f"WHERE workspace_id=%s AND id=%s AND status IN ('failed','cancelled','blocked') RETURNING {JOB_COLS}")
GET = f"/*lij:job.get*/ SELECT {JOB_COLS} FROM public.pr_library_jobs WHERE workspace_id=%s AND id=%s FOR UPDATE"
CLAIM = ("/*lij:job.claim*/ UPDATE public.pr_library_jobs j SET status='processing',lease_token=%s,lease_expires_at=now()+make_interval(secs=>%s),"
         "heartbeat_at=now(),attempts=j.attempts+1,updated_at=now() WHERE j.id=(SELECT d.id FROM public.pr_library_jobs d "
         "WHERE ((d.status='queued' AND d.next_attempt_at<=now()) OR (d.status='processing' AND d.lease_expires_at<now())) AND d.attempts<d.max_attempts "
         "AND EXISTS(SELECT 1 FROM public.pr_workspaces w WHERE w.id=d.workspace_id AND NOT (w.state ? 'accountBlock') AND NOT (w.state ? 'accountDeletion')) "
         f"ORDER BY d.next_attempt_at,d.created_at LIMIT 1 FOR UPDATE OF d SKIP LOCKED) RETURNING {JOB_COLS}")
RESERVE = "/*lij:job.reserve*/ UPDATE public.pr_library_jobs SET reservation=%s::jsonb,updated_at=now() WHERE id=%s AND lease_token=%s"
HEARTBEAT = ("/*lij:job.heartbeat*/ UPDATE public.pr_library_jobs SET heartbeat_at=now(),lease_expires_at=now()+make_interval(secs=>%s),updated_at=now() "
             "WHERE id=%s AND lease_token=%s AND status='processing' RETURNING 1")
FINISH = ("/*lij:job.finish*/ UPDATE public.pr_library_jobs SET status=%s,error_category=%s,error_code=%s,cost=%s::jsonb,reservation=%s::jsonb,cleanup=%s,"
          "timings=timings||%s::jsonb,lease_token=null,lease_expires_at=null,finished_at=now(),updated_at=now() WHERE id=%s")
REQUEUE = ("/*lij:job.requeue*/ UPDATE public.pr_library_jobs SET status='queued',error_category=%s,error_code=%s,reservation=%s::jsonb,"
           "timings=timings||%s::jsonb,lease_token=null,lease_expires_at=null,next_attempt_at=now()+make_interval(secs=>%s),updated_at=now() WHERE id=%s")
SETTLED = "/*lij:job.settled*/ UPDATE public.pr_library_jobs SET reservation=%s::jsonb,updated_at=now() WHERE id=%s AND reservation->>'reservationId'=%s"
CANCEL = ("/*lij:job.cancel*/ UPDATE public.pr_library_jobs SET status='cancelled',error_category='cancelled',error_code='library_cancelled',lease_token=null,"
          "lease_expires_at=null,finished_at=now(),updated_at=now() WHERE workspace_id=%s AND asset_key=%s AND status IN ('queued','processing') "
          "AND capability=ANY(%s) RETURNING id::text,capability")
RECOVER = ("/*lij:job.recover*/ UPDATE public.pr_library_jobs j SET status='failed',error_category='timeout',error_code='library_job_timeout',lease_token=null,"
           "lease_expires_at=null,finished_at=now(),updated_at=now() WHERE j.id IN (SELECT d.id FROM public.pr_library_jobs d WHERE d.status='processing' "
           f"AND d.lease_expires_at<now() AND d.attempts>=d.max_attempts LIMIT 50 FOR UPDATE OF d SKIP LOCKED) RETURNING {JOB_COLS}")
ORPHANS = (f"/*lij:job.orphans*/ SELECT {JOB_COLS} FROM public.pr_library_jobs WHERE status IN ('cancelled','failed','blocked','completed','partial') "
           "AND reservation IS NOT NULL AND reservation->>'status'='reserved' AND NOT coalesce((reservation->>'settled')::boolean,false) "
           "AND updated_at<now()-make_interval(mins=>%s) ORDER BY updated_at LIMIT 20 FOR UPDATE SKIP LOCKED")
WS_STATE = "/*lij:ws.state*/ SELECT state FROM public.pr_workspaces WHERE id=%s"
OBJECT = "/*lij:asset.object*/ SELECT object_name,bytes,mime,etag,sha256 FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s"
MEDIA = "/*lij:asset.media*/ UPDATE public.pr_library_assets SET media=media||%s::jsonb,updated_at=now() WHERE workspace_id=%s AND id=%s"
RECEIPT_GET = ("/*lij:receipt.get*/ SELECT actor::text,action_type,request_hash,result FROM public.pr_library_action_receipts "
               "WHERE workspace_id=%s AND idempotency_key=%s")
RECEIPT_PUT = ("/*lij:receipt.put*/ INSERT INTO public.pr_library_action_receipts(workspace_id,idempotency_key,actor,action_type,request_hash,status,result) "
               "VALUES(%s,%s,%s,%s,%s,'applied',%s::jsonb) ON CONFLICT DO NOTHING")


class RetryableError(AlphaError):
    """Raised by processors for a transient failure. `retry_after` (seconds or an HTTP-date) honours provider Retry-After."""

    def __init__(self, message="A temporary problem interrupted processing.", *, code="library_retryable", retry_after=None, status=503):
        super().__init__(message, status, code=code)
        self.retry_after = retry_after


class _WriterUnavailable(Exception):
    pass


class _System:
    """Membership for background work: it may read the workspace it was enqueued in, nothing else."""
    role = "system"

    def allows(self, requirement):
        return requirement == "read"


@dataclass
class JobContext:
    """What a processor's run(job) and estimate(job) receive (OWNER-MAP section A)."""
    job_id: str
    workspace_id: str
    actor: str
    version: dict
    providers: Any
    now: float
    processor: dict
    consent_revision: int
    attempt: int
    _reader: Callable[[], bytes] | None = None
    _heartbeat: Callable[[], bool] | None = None
    _progress: Callable[[int, int, str], bool] | None = None
    _raw: bytes | None = field(default=None, repr=False)

    def raw(self) -> bytes:
        """The original bytes from private storage, verified against the version's hash or storage identity. Read once."""
        if self._raw is None:
            if self._reader is None:
                raise AlphaError("Private storage is not configured.", 503, code="library_storage_not_configured")
            self._raw = self._reader()
        return self._raw

    def heartbeat(self) -> bool:
        """Extend the lease. False means the job was cancelled, revoked or taken over: stop and return."""
        return bool(self._heartbeat()) if self._heartbeat else True

    def progress(self, done: int, total: int, unit: str = "items") -> bool:
        """Report measurable progress (also a heartbeat). Never a guessed percentage."""
        return bool(self._progress(done, total, unit)) if self._progress else True


# --- helpers ------------------------------------------------------------------------------------------------------------
def idempotency_key(workspace_id, version_key, capability, processor_version, consent_revision) -> str:
    raw = json.dumps([str(workspace_id), version_key, capability, processor_version, int(consent_revision)], separators=(",", ":"))
    return "lij:" + hashlib.sha256(raw.encode()).hexdigest()


def _f(value):
    return float(value) if value is not None else None


def _job(r) -> dict:
    return {"id": str(r[0]).replace("-", ""), "workspaceId": str(r[1]), "assetKey": r[2], "capability": r[3], "processorVersion": r[4],
            "consentRevision": int(r[5]), "idempotencyKey": r[6], "status": r[7], "attempts": int(r[8]), "maxAttempts": int(r[9]),
            "leaseToken": r[10], "leaseExpiresAt": _f(r[11]), "nextAttemptAt": _f(r[12]), "reservation": r[13] if isinstance(r[13], dict) else None,
            "cost": r[14] if isinstance(r[14], dict) else None, "errorCategory": r[15], "errorCode": r[16], "requestedBy": r[17],
            "createdAt": _f(r[18]), "finishedAt": _f(r[19])}


def public_job(job: dict | None) -> dict | None:
    if job is None:
        return None
    return {"jobId": job["id"], "capability": job["capability"], "processorVersion": job["processorVersion"], "status": job["status"],
            "attempts": job["attempts"], "maxAttempts": job["maxAttempts"], "errorCode": job["errorCode"]}


def _cap_state(job: dict) -> str:
    return {"queued": "queued", "processing": "processing", "completed": "ready", "partial": "partial", "failed": "failed",
            "cancelled": "cancelled", "blocked": "blocked_permission" if job.get("errorCategory") == "permission" else "blocked_budget"}[job["status"]]


def retry_after_seconds(value) -> int | None:
    """Provider Retry-After: delta seconds or an HTTP-date, bounded to RETRY_AFTER_CAP. Unparseable -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d{1,10}(\.\d+)?", text):
            seconds = float(text)
        else:
            try:
                when = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
            if when is None:
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return int(min(RETRY_AFTER_CAP, max(0, math.ceil(seconds))))


def backoff(attempt: int, retry_after=None, rand=random.random) -> int:
    base = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** max(0, int(attempt) - 1))
    delay = base * (1 + JITTER * rand())
    hint = retry_after_seconds(retry_after)
    if hint is not None:
        delay = max(delay, hint)
    return int(math.ceil(delay))


def _code(value, fallback):
    return value if isinstance(value, str) and ERROR_CODE.fullmatch(value) else fallback


def classify(error: BaseException) -> dict:
    """Turn a processor exception into an Outcome. Messages are the AlphaError's user-facing text, never internals."""
    code = getattr(error, "code", None)
    status = error.status if isinstance(error, AlphaError) else 500
    detail = str(error)[:300] if isinstance(error, AlphaError) else "Processing stopped unexpectedly."
    out = {"state": "failed", "errorCode": _code(code, "library_processing_failed"), "detail": detail, "retryable": False, "charged": None}
    retry_after = getattr(error, "retry_after", None)
    if isinstance(error, RetryableError):
        out.update(retryable=True, errorCategory="retryable", retryAfterSeconds=retry_after_seconds(retry_after))
    elif code == "library_provider_unavailable":
        out.update(errorCategory="permanent", charged=False)
    elif code == "library_provider_rate_limited" or status == 429:
        out.update(retryable=True, errorCategory="retryable", charged=False, retryAfterSeconds=retry_after_seconds(retry_after))
    elif code == "library_provider_timeout" or isinstance(error, TimeoutError):
        out.update(retryable=True, errorCategory="timeout", errorCode=_code(code, "library_provider_timeout"))
    elif status in (401, 403):
        out.update(state="blocked_permission", errorCategory="permission", charged=False)
    elif status == 402:
        out.update(state="blocked_budget", errorCategory="budget", charged=False)
    elif isinstance(code, str) and "unsupported" in code:
        out.update(state="unsupported", errorCategory="unsupported", charged=False)
    elif status in (400, 409, 413, 415, 422):
        out.update(errorCategory="corrupt", charged=False)
    elif status == 404:
        out.update(errorCategory="permanent", charged=False)
    elif code == "library_storage_not_configured":
        out.update(errorCategory="permanent", charged=False)
    else:
        out.update(retryable=True, errorCategory="retryable", charged=False if code == "library_provider_failed" else None)
    return out


def _outcome(result) -> dict:
    """Validate a processor Outcome; a malformed one is a failed state, never a silent success."""
    bad = {"state": "failed", "errorCode": "library_processor_contract", "detail": "The processor returned an unexpected result.",
           "retryable": False, "errorCategory": "permanent", "charged": None}
    if not isinstance(result, dict) or result.get("state") not in OUTCOME_STATES:
        return bad
    out = dict(result)
    for name in ("segments", "annotations", "embeddings"):
        items = out.get(name) or []
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            return bad
        out[name] = items
    media = out.get("media")
    if media is not None and (not isinstance(media, dict) or len(json.dumps(media, default=str)) > MAX_MEDIA_JSON):
        return bad
    if out.get("provider") is not None and not isinstance(out["provider"], dict):
        return bad
    out["errorCode"] = _code(out.get("errorCode"), None)
    out["detail"] = str(out["detail"])[:300] if out.get("detail") else None
    out["retryable"] = out.get("retryable") is True
    out.setdefault("errorCategory", {"unsupported": "unsupported", "blocked_permission": "permission", "blocked_budget": "budget"}.get(out["state"]))
    return out


def _uuid(key) -> uuid.UUID:
    return uuid.UUID(hex=c.asset_key(key))


def system_context(cur, workspace_id, actor=None) -> c.LibraryContext | None:
    """A non-locking context for background work. None when the workspace is gone, blocked or being deleted."""
    cur.execute(WS_STATE, (str(workspace_id),))
    row = cur.fetchone()
    if not row:
        return None
    state = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    if state.get("accountBlock") or state.get("accountDeletion"):
        return None
    return c.LibraryContext(workspace_id=str(workspace_id), actor=str(actor or SYSTEM_ACTOR), membership=_System(), state=state, cur=cur, now=time.time())


# --- enqueue ------------------------------------------------------------------------------------------------------------
def enqueue_capability(ctx, ref, capability, processor_version, *, retry: bool = False, requested_by=None) -> dict:
    """Idempotent: the key binds workspace, version, capability, processor version and the current grant revision, so a
    duplicate event returns the same job. A denied processing permission records blocked_permission and creates no job."""
    if capability not in c.CAPABILITIES:
        c.fail("Choose a known processing capability.")
    version = versions.resolve(ctx, ref)
    proc = capabilities.processor(capability, processor_version)
    if proc is None:
        raise AlphaError("This Library capability is not available in this build.", 503, code="library_capability_unavailable")
    if not capabilities.applies(proc, version):
        raise AlphaError("This kind of processing does not apply to this item.", 422, code="library_capability_not_applicable")
    key = version["versionId"]
    revs = policy.revisions(ctx, fresh=True)
    decision = policy.authorize_processing(ctx, version, proc["location"], proc["category"])
    if not decision.allowed:
        capabilities.set_state(ctx.cur, ctx.workspace_id, key, capability, "blocked_permission", error_code="library_" + (decision.reason or "denied"),
                               detail=policy.message(decision.reason), processor_version=processor_version,
                               keep=("ready", "partial", "queued", "processing"))
        return {"job": None, "state": "blocked_permission", "reason": decision.reason, "duplicate": False}
    ctx.cur.execute(LOCK, (f"library-job:{ctx.workspace_id}:{key}:{capability}",))
    ctx.cur.execute(ACTIVE, (ctx.workspace_id, key, capability, processor_version))
    active = ctx.cur.fetchone()
    if active:
        job = _job(active)
        return {"job": public_job(job), "state": _cap_state(job), "duplicate": True}
    idem = idempotency_key(ctx.workspace_id, key, capability, processor_version, revs["grantRevision"])
    ctx.cur.execute(INSERT, (uuid.uuid4(), ctx.workspace_id, key, capability, processor_version, revs["grantRevision"], idem, MAX_ATTEMPTS,
                             requested_by))
    row = ctx.cur.fetchone()
    duplicate = row is None
    if duplicate:
        ctx.cur.execute(BY_KEY, (ctx.workspace_id, idem))
        row = ctx.cur.fetchone()
        job = _job(row)
        if retry and job["status"] in ("failed", "cancelled", "blocked"):
            ctx.cur.execute(REVIVE, (requested_by, ctx.workspace_id, _uuid(job["id"])))
            revived = ctx.cur.fetchone()
            if revived:
                row, duplicate = revived, False
    job = _job(row)
    if duplicate:
        return {"job": public_job(job), "state": _cap_state(job), "duplicate": True}
    capabilities.set_state(ctx.cur, ctx.workspace_id, key, capability, "queued", job_id=job["id"], processor_version=processor_version)
    return {"job": public_job(job), "state": "queued", "duplicate": False}


def on_asset_processed(connect, workspace_id, asset_key) -> dict:
    """Called by library_assets after an original finishes (ready/unsupported) and its transaction committed. Enqueues the
    private LOCAL default capabilities only, and only when enrichment is switched on. Never raises into the upload flow."""
    try:
        if not policy.enabled("enrichment"):
            return {"status": "disabled"}
        key = c.asset_key(asset_key)
        out = []
        with connect() as db, db.cursor() as cur:
            ctx = system_context(cur, workspace_id)
            if ctx is None:
                return {"status": "workspace_unavailable"}
            version = versions.get(ctx, key)
            chosen: dict[str, dict] = {}
            for proc in capabilities.processors_for(version):
                if capabilities.is_local(proc):
                    chosen[proc["capability"]] = proc  # the last registered local version wins
            for capability, proc in chosen.items():
                result = enqueue_capability(ctx, versions.ref(version), capability, proc["version"])
                out.append({"capability": capability, "state": result["state"], "duplicate": result["duplicate"]})
        return {"status": "enqueued", "capabilities": out}
    except Exception as error:  # the upload already succeeded; intelligence is additive
        print(json.dumps({"event": "library_intelligence.enqueue_failed", "error": type(error).__name__}), flush=True)
        return {"status": "error"}


# --- receipts (idempotent HTTP requests) -------------------------------------------------------------------------------
def receipt(ctx, key: str, action_type: str, request_hash: str) -> dict | None:
    """A prior result for this idempotency key, or None. A key reused for a different request is a 409."""
    ctx.cur.execute(RECEIPT_GET, (ctx.workspace_id, key))
    row = ctx.cur.fetchone()
    if not row:
        return None
    if str(row[0]) != str(ctx.actor) or row[1] != action_type or row[2] != request_hash:
        raise AlphaError("This request key was already used for a different request.", 409, code="library_idempotency_conflict")
    result = row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}")
    return {**result, "replayed": True}


def put_receipt(ctx, key: str, action_type: str, request_hash: str, result: dict):
    ctx.cur.execute(RECEIPT_PUT, (ctx.workspace_id, key, ctx.actor, action_type, request_hash, json.dumps(result)))


def request_key(value) -> str:
    if not isinstance(value, str) or not REQUEST_KEY.fullmatch(value):
        c.fail("Each request needs an idempotency key of 16 to 120 characters.")
    return value


def _capability_list(value, *, default=None) -> list[str]:
    if value is None and default is not None:
        return list(default)
    if not isinstance(value, list) or not 1 <= len(value) <= len(c.CAPABILITIES) or len(set(value)) != len(value) or not set(value) <= set(c.CAPABILITIES):
        c.fail("Choose the capabilities to process.")
    return [cap for cap in c.CAPABILITIES if cap in value]


def _choose(ctx, version, capability) -> dict | None:
    """Prefer an authorized cloud processor (richest allowed result), then a local one; an unauthorized cloud processor
    is still returned when it is the only option so the request records an honest blocked_permission."""
    candidates = [p for p in capabilities.processors_for(version) if p["capability"] == capability]
    if not candidates:
        return None
    cloud = [p for p in candidates if not capabilities.is_local(p)]
    local = [p for p in candidates if capabilities.is_local(p)]
    for proc in reversed(cloud):
        if policy.authorize_processing(ctx, version, proc["location"], proc["category"]).allowed:
            return proc
    return local[-1] if local else cloud[-1]


def _not_sample(ctx):
    if (ctx.state.get("workspace") or {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")


def request_http(ctx, request):
    """POST .../assets/{key}/process {capabilities:[...], idempotencyKey}. Explicit user request: a failed or cancelled job
    for the same key may run again (attempts reset); a ready one is returned as is."""
    ctx.require("edit")
    _not_sample(ctx)
    body = request.get("body") or {}
    if not set(body) <= {"capabilities", "idempotencyKey"}:
        c.fail("This processing request has unexpected fields.")
    wanted = _capability_list(body.get("capabilities"))
    key = request_key(body.get("idempotencyKey"))
    version = versions.get(ctx, request["params"]["key"])
    request_hash = digest({"asset": version["versionId"], "capabilities": wanted})
    prior = receipt(ctx, key, "capability.request", request_hash)
    if prior is not None:
        return {**prior, "capabilities": capabilities.states_for(ctx, version)}
    if not policy.enabled("enrichment"):
        raise AlphaError("Library processing is not switched on.", 503, code="library_enrichment_disabled")
    results = []
    for capability in wanted:
        proc = _choose(ctx, version, capability)
        if proc is None:
            results.append({"capability": capability, "state": "not_requested", "available": False, "reason": "library_capability_unavailable"})
            continue
        out = enqueue_capability(ctx, versions.ref(version), capability, proc["version"], retry=True, requested_by=ctx.actor)
        results.append({"capability": capability, "state": out["state"], "jobId": (out["job"] or {}).get("jobId"), "processorVersion": proc["version"],
                        "location": proc["location"], "duplicate": out["duplicate"], **({"reason": out["reason"]} if out.get("reason") else {})})
    result = {"assetRef": versions.ref(version), "results": results}
    put_receipt(ctx, key, "capability.request", request_hash, result)
    return {**result, "capabilities": capabilities.states_for(ctx, version), "_status": 202}


def cancel(ctx, version_key: str, wanted) -> int:
    """Cancel queued/running jobs. A running processor finishes its call, but its finalize sees the cancellation and
    writes no derivative."""
    ctx.cur.execute(CANCEL, (ctx.workspace_id, version_key, list(wanted)))
    rows = ctx.cur.fetchall()
    for job_id, capability in rows:
        capabilities.set_state(ctx.cur, ctx.workspace_id, version_key, capability, "cancelled", job_id=str(job_id).replace("-", ""),
                               error_code="library_cancelled", detail="Cancelled. The original is unchanged.", retryable=True,
                               job_guard=str(job_id).replace("-", ""))
    return len(rows)


def cancel_http(ctx, request):
    """POST .../assets/{key}/cancel {capabilities?:[...]}. Naturally idempotent."""
    ctx.require("edit")
    body = request.get("body") or {}
    if not set(body) <= {"capabilities", "idempotencyKey"}:
        c.fail("This cancel request has unexpected fields.")
    wanted = _capability_list(body.get("capabilities"), default=c.CAPABILITIES)
    version = versions.get(ctx, request["params"]["key"])
    count = cancel(ctx, version["versionId"], wanted)
    return {"assetRef": versions.ref(version), "cancelled": count, "capabilities": capabilities.states_for(ctx, version)}


# --- byte access --------------------------------------------------------------------------------------------------------
def _storage(intel):
    return getattr(getattr(getattr(intel, "service", None), "library", None), "storage", None)


def _reader(storage, workspace_id, version, obj, legacy):
    """Bounded private-storage read with an identity and hash check; raises AlphaError on any mismatch."""
    def changed():
        return AlphaError("The original changed or is unavailable; processing stopped.", 409, code="library_source_changed")

    def read():
        if storage is None:
            raise AlphaError("Private storage is not configured.", 503, code="library_storage_not_configured")
        if not version["legacy"]:
            if obj is None:
                raise AlphaError("The original is unavailable.", 404, code="library_source_unavailable")
            name, size, mime, etag, sha = obj
            info = storage.object_info(workspace_id, "file", name)
            if (info.get("bytes"), info.get("mime"), info.get("etag")) != (int(size), mime, etag):
                raise changed()
            raw = storage.get_bounded(workspace_id, "file", name, int(size))
            if len(raw) != int(size) or not sha or hashlib.sha256(raw).hexdigest() != sha or sha != version["sha256"]:
                raise changed()
            return raw
        if legacy is None or not legacy.get("objectName"):
            raise AlphaError("The original is unavailable.", 404, code="library_source_unavailable")
        if version["kind"] == "video":
            size = int(legacy.get("bytes") or 0)
            if not 0 < size <= MAX_RAW_BYTES:
                raise AlphaError("This video is too large to process here.", 422, code="library_media_too_large")
            return storage.get_verified_video(workspace_id, legacy["objectName"], expected_bytes=size, expected_mime=legacy.get("mime"),
                                              expected_etag=legacy.get("etag"))
        raw = storage.get(workspace_id, "media", legacy["objectName"])
        if not version["sha256"] or hashlib.sha256(raw).hexdigest() != version["sha256"]:
            raise changed()
        return raw
    return read


def _legacy_asset(state, key):
    return next((a for a in (state.get("phase2") or {}).get("assets", []) if isinstance(a, dict) and a.get("id") == key), None)


# --- claim / prepare / run / finalize -----------------------------------------------------------------------------------
def _settle(cur, workspace_id, reservation: dict | None, outcome: dict | None) -> dict | None:
    """Settle one attempt's reservation exactly once. Errors leave it unsettled for the orphan sweep, never block finalize."""
    if not reservation or reservation.get("status") != "reserved" or reservation.get("settled"):
        return reservation
    outcome = outcome or {}
    receipt_value = outcome.get("provider") if isinstance(outcome.get("provider"), dict) else None
    cur.execute("SAVEPOINT library_settle")
    try:
        if receipt_value is None and (outcome.get("charged") is False or outcome.get("errorCode") in UNCHARGED):
            providers.settle(cur, workspace_id, reservation, None, failed=True)
            settlement = "released"
        elif receipt_value is not None:
            providers.settle(cur, workspace_id, reservation, SimpleNamespace(cost=receipt_value.get("cost") or {"kind": "unknown"}))
            settlement = "receipt"
        else:
            providers.settle(cur, workspace_id, reservation, None)
            settlement = "unknown"
        cur.execute("RELEASE SAVEPOINT library_settle")
        return {**reservation, "settled": True, "settlement": settlement}
    except Exception as error:
        cur.execute("ROLLBACK TO SAVEPOINT library_settle")
        print(json.dumps({"event": "library_intelligence.settle_failed", "error": type(error).__name__}), flush=True)
        return reservation


def _settle_orphans(connect) -> int:
    count = 0
    with connect() as db, db.cursor() as cur:
        cur.execute(ORPHANS, (ORPHAN_MINUTES,))
        for row in cur.fetchall():
            job = _job(row)
            settled = _settle(cur, job["workspaceId"], job["reservation"], None)
            if settled and settled.get("settled"):
                cur.execute(SETTLED, (json.dumps(settled), _uuid(job["id"]), job["reservation"].get("reservationId")))
                count += 1
    return count


def _recover(connect) -> int:
    """Jobs whose worker died at their last attempt fail honestly (timeout) instead of looping or hanging."""
    with connect() as db, db.cursor() as cur:
        cur.execute(RECOVER)
        rows = [_job(r) for r in cur.fetchall()]
        for job in rows:
            settled = _settle(cur, job["workspaceId"], job["reservation"], None)
            if settled is not job["reservation"]:
                cur.execute(SETTLED, (json.dumps(settled), _uuid(job["id"]), (job["reservation"] or {}).get("reservationId")))
            capabilities.set_state(cur, job["workspaceId"], job["assetKey"], job["capability"], "failed", job_id=job["id"], job_guard=job["id"],
                                   error_code="library_job_timeout", detail="Processing timed out. You can try again.", retryable=True,
                                   processor_version=job["processorVersion"])
    return len(rows)


def claim_next(intel, connect) -> dict | None:
    """Claim one due job (its own committed transaction), then prepare it. Returns a prepared job, or None."""
    lease = uuid.uuid4()
    with connect() as db, db.cursor() as cur:
        cur.execute(CLAIM, (lease, LEASE_SECONDS))
        row = cur.fetchone()
    if not row:
        return None
    job = _job(row)
    prepared = {"job": job, "leaseToken": str(lease), "reservation": None, "processor": None, "grantRevision": job["consentRevision"],
                "context": None, "early": None}
    try:
        _prepare(intel, connect, prepared)
    except Exception as error:
        prepared["early"] = classify(error)
    return prepared


def _prepare(intel, connect, prepared):
    job = prepared["job"]
    with connect() as db, db.cursor() as cur:
        ctx = system_context(cur, job["workspaceId"], job["requestedBy"])
        if ctx is None:
            prepared["early"] = {"state": "cancelled", "errorCode": "library_workspace_unavailable", "cleanup": "workspace_unavailable"}
            return
        if job["reservation"] and job["reservation"].get("status") == "reserved" and not job["reservation"].get("settled"):
            # A previous attempt reserved and then died: its provider call may or may not have happened.
            settled = _settle(cur, job["workspaceId"], job["reservation"], None)
            cur.execute(SETTLED, (json.dumps(settled), _uuid(job["id"]), job["reservation"].get("reservationId")))
        version = versions.load(ctx, [job["assetKey"]]).get(job["assetKey"])
        if version is None or version["status"] in ("deleting", "duplicate", "missing"):
            prepared["early"] = {"state": "cancelled", "errorCode": "library_source_unavailable", "cleanup": "source_unavailable"}
            return
        proc = capabilities.processor(job["capability"], job["processorVersion"])
        prepared["processor"] = proc
        if proc is None:
            prepared["early"] = {"state": "failed", "errorCode": "library_capability_unavailable", "detail": "This processor is not available in this build.",
                                 "errorCategory": "permanent", "retryable": False, "userRetryable": True}
            return
        if not capabilities.applies(proc, version):
            prepared["early"] = {"state": "unsupported", "errorCode": "library_capability_not_applicable", "errorCategory": "unsupported"}
            return
        decision = policy.authorize_processing(ctx, version, proc["location"], proc["category"])
        prepared["grantRevision"] = decision.grant_revision
        if not decision.allowed:
            prepared["early"] = {"state": "blocked_permission", "errorCode": "library_" + (decision.reason or "denied"), "detail": policy.message(decision.reason),
                                 "errorCategory": "permission"}
            return
        obj = None
        if not version["legacy"]:
            cur.execute(OBJECT, (ctx.workspace_id, _uuid(version["versionId"])))
            obj = cur.fetchone()
        storage = _storage(intel)
        legacy = _legacy_asset(ctx.state, version["versionId"]) if version["legacy"] else None
        jid = job["id"]

        def heartbeat():
            with connect() as hb, hb.cursor() as hcur:
                hcur.execute(HEARTBEAT, (LEASE_SECONDS, _uuid(jid), prepared["leaseToken"]))
                return hcur.fetchone() is not None

        def progress(done, total, unit):
            with connect() as pg, pg.cursor() as pcur:
                pcur.execute(HEARTBEAT, (LEASE_SECONDS, _uuid(jid), prepared["leaseToken"]))
                if pcur.fetchone() is None:
                    return False
                capabilities.set_state(pcur, job["workspaceId"], version["versionId"], job["capability"], "processing", job_id=jid, job_guard=jid,
                                       progress={"done": done, "total": total, "unit": unit}, processor_version=proc["version"])
                return True
        jobctx = JobContext(job_id=jid, workspace_id=job["workspaceId"], actor=ctx.actor, version=version, providers=getattr(intel, "providers", None),
                            now=time.time(), processor=proc, consent_revision=decision.grant_revision, attempt=job["attempts"],
                            _reader=_reader(storage, job["workspaceId"], version, obj, legacy), _heartbeat=heartbeat, _progress=progress)
        prepared["context"] = jobctx
        if not capabilities.is_local(proc):
            estimate = proc["estimate"](jobctx) if proc.get("estimate") else None
            if type(estimate) is not int or estimate < 0:
                prepared["early"] = {"state": "blocked_budget", "errorCode": "library_estimate_unavailable",
                                     "detail": "The cost of this processing could not be estimated, so nothing was sent.", "errorCategory": "budget"}
                return
            provider_seam = getattr(intel, "providers", None)
            model = proc.get("model")
            if not model and proc["category"] in providers.DEFAULTS and callable(getattr(provider_seam, "model", None)):
                model = provider_seam.model(proc["category"])
            model = model or proc["category"]
            reservation = providers.reserve(cur, job["workspaceId"], job["requestedBy"], capability=proc["category"], estimate_usd_micro=estimate,
                                            key=f"job:{jid}:{job['attempts']}", model=str(model)[:120], job_id=jid)
            if reservation.get("status") != "reserved":
                prepared["early"] = {"state": "blocked_budget", "errorCode": "library_budget_blocked", "detail": str(reservation.get("reason") or "")[:300] or None,
                                     "errorCategory": "budget"}
                return
            reservation = {**reservation, "attempt": job["attempts"], "key": f"job:{jid}:{job['attempts']}", "settled": False}
            cur.execute(RESERVE, (json.dumps(reservation), _uuid(jid), prepared["leaseToken"]))
            prepared["reservation"] = reservation
        capabilities.set_state(cur, job["workspaceId"], version["versionId"], job["capability"], "processing", job_id=jid, processor_version=proc["version"])


def run_claimed(intel, connect, prepared) -> str:
    """Run a prepared job's processor outside any transaction, then finalize it in a new one."""
    job = prepared["job"]
    started = time.monotonic()
    result = prepared["early"]
    if result is None:
        try:
            result = prepared["processor"]["run"](prepared["context"])
        except Exception as error:
            result = classify(error)
    timings = {"runMs": round((time.monotonic() - started) * 1000), "attempt": job["attempts"]}
    with connect() as db, db.cursor() as cur:
        ctx = system_context(cur, job["workspaceId"], job["requestedBy"])
        if ctx is None:
            return "lost"
        return complete_capability(ctx, job["id"], result, prepared["grantRevision"], lease_token=prepared["leaseToken"],
                                   reservation=prepared["reservation"], processor=prepared["processor"], timings=timings)


def _writer(module_name, function_name):
    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
        return getattr(module, function_name)
    except (ImportError, AttributeError):
        raise _WriterUnavailable(module_name) from None


def _write(ctx, version, proc, outcome) -> dict:
    """Derivatives go through the owning workstream's writers (B: segments, understanding; C: index)."""
    written = {}
    revs = policy.revisions(ctx)
    receipt_value = outcome.get("provider") or {}
    if outcome["segments"]:
        written["segments"] = _writer("segments", "write_segments")(ctx.cur, ctx.workspace_id, version, outcome["segments"],
                                                                    extractor=proc.get("name") or proc["capability"], extractor_version=proc["version"])
    if outcome["embeddings"]:
        written["embeddings"] = _writer("index", "write_embeddings")(ctx.cur, ctx.workspace_id, version, outcome["embeddings"],
                                                                     consent_revision=revs["grantRevision"], index_generation=revs["indexGeneration"])
    if outcome["annotations"]:
        written["annotations"] = _writer("understanding", "write_annotations")(ctx.cur, ctx.workspace_id, version, outcome["annotations"],
                                                                               processor_version=proc["version"], model=receipt_value.get("model"))
    if outcome.get("media") and not version["legacy"]:
        ctx.cur.execute(MEDIA, (json.dumps(outcome["media"], default=str), ctx.workspace_id, _uuid(version["versionId"])))
        written["media"] = True
    return written


def complete_capability(ctx, job_id, result, expected_grant_revision, *, lease_token=None, reservation=None, processor=None, timings=None) -> str:
    """Finalize one job inside the caller's transaction. Order: lease -> source still present -> grant recheck (TOCTOU) ->
    derivatives -> state -> settlement. Returns the capability state written, 'retrying', or why nothing was written
    ('lost', 'cancelled', 'missing', or the job's existing terminal status)."""
    cur = ctx.cur
    cur.execute(GET, (ctx.workspace_id, _uuid(job_id)))
    row = cur.fetchone()
    if not row:
        return "missing"
    job = _job(row)
    outcome = _outcome(result) if not (isinstance(result, dict) and result.get("state") == "cancelled") else dict(result)
    held = reservation if reservation is not None else job["reservation"]
    if job["status"] != "processing" or (lease_token is not None and job["leaseToken"] != str(lease_token)):
        # Cancelled, revoked or taken over: write nothing. The provider may still have run, so settle what we hold.
        if reservation is not None:
            settled = _settle(cur, ctx.workspace_id, reservation, outcome)
            if settled is not reservation:
                cur.execute(SETTLED, (json.dumps(settled), _uuid(job["id"]), reservation.get("reservationId")))
        return "lost" if job["status"] == "processing" else job["status"]
    key = job["assetKey"]
    timings = dict(timings or {})
    proc = processor or capabilities.processor(job["capability"], job["processorVersion"])

    def finish(state, *, category=None, code=None, detail=None, retryable=False, cleanup=None, provider=None):
        settled = _settle(cur, ctx.workspace_id, held, outcome)
        cost = (provider or {}).get("cost") if isinstance(provider, dict) else None
        cur.execute(FINISH, (JOB_STATUS[state], category, code, json.dumps(cost) if cost else None, json.dumps(settled) if settled else None,
                             cleanup, json.dumps(timings), _uuid(job["id"])))
        if cleanup != "source_unavailable":
            capabilities.set_state(cur, ctx.workspace_id, key, job["capability"], state, job_id=job["id"], job_guard=job["id"], error_code=code,
                                   detail=detail, retryable=retryable, processor_version=job["processorVersion"], provider=provider)
        return state

    if outcome["state"] == "cancelled":
        return finish("cancelled", category="cancelled", code=outcome.get("errorCode"), cleanup=outcome.get("cleanup"))
    version = versions.load(ctx, [key]).get(key)
    if version is None or version["status"] in ("deleting", "duplicate", "missing"):
        return finish("cancelled", category="cancelled", code="library_source_unavailable", cleanup="source_unavailable")
    if proc is None:
        return finish("failed", category="permanent", code="library_capability_unavailable", detail="This processor is not available in this build.",
                      retryable=True)
    if outcome["state"] in ("ready", "partial") or outcome.get("provider"):
        decision = policy.Decision(True, "processing", key, grant_revision=int(expected_grant_revision), source_sha256=version.get("sha256") or "",
                                   processing={"location": proc["location"], "category": proc["category"]})
        fresh = policy.recheck(ctx, decision)
        if not fresh.allowed:
            return finish("blocked_permission", category="permission", code="library_" + (fresh.reason or "grant_revoked"),
                          detail=policy.message(fresh.reason), provider=outcome.get("provider"), cleanup="derivatives_discarded")
    state = outcome["state"]
    if state in ("ready", "partial"):
        cur.execute("SAVEPOINT library_finalize")
        try:
            _write(ctx, version, proc, outcome)
            cur.execute("RELEASE SAVEPOINT library_finalize")
        except _WriterUnavailable:
            cur.execute("ROLLBACK TO SAVEPOINT library_finalize")
            outcome.update(state="failed", errorCode="library_capability_unavailable", detail="This build cannot store these results yet.",
                           retryable=False, errorCategory="permanent", userRetryable=True)
        except AlphaError as error:
            cur.execute("ROLLBACK TO SAVEPOINT library_finalize")
            outcome.update(state="failed", errorCode=_code(error.code, "library_finalize_failed"), detail=str(error)[:300],
                           retryable=error.status >= 500, errorCategory="retryable" if error.status >= 500 else "corrupt")
        except Exception as error:
            cur.execute("ROLLBACK TO SAVEPOINT library_finalize")
            print(json.dumps({"event": "library_intelligence.finalize_failed", "error": type(error).__name__}), flush=True)
            outcome.update(state="failed", errorCode="library_finalize_failed", detail="Results could not be stored.", retryable=True,
                           errorCategory="retryable")
        state = outcome["state"]
    if state == "failed" and outcome.get("retryable") and job["attempts"] < job["maxAttempts"]:
        settled = _settle(cur, ctx.workspace_id, held, outcome)
        delay = backoff(job["attempts"], outcome.get("retryAfterSeconds"))
        cur.execute(REQUEUE, (outcome.get("errorCategory") or "retryable", outcome.get("errorCode"), json.dumps(settled) if settled else None,
                              json.dumps(timings), delay, _uuid(job["id"])))
        capabilities.set_state(cur, ctx.workspace_id, key, job["capability"], "queued", job_id=job["id"], job_guard=job["id"],
                               error_code=outcome.get("errorCode"), detail="Retrying after a temporary problem.", retryable=True,
                               processor_version=job["processorVersion"])
        return "retrying"
    retryable = bool(outcome.get("retryable") or outcome.get("userRetryable"))
    return finish(state, category=outcome.get("errorCategory") if state != "ready" else None, code=outcome.get("errorCode"), detail=outcome.get("detail"),
                  retryable=retryable if state not in ("ready", "partial") else False, provider=outcome.get("provider"), cleanup=outcome.get("cleanup"))


SUMMARY_KEYS = {"ready": "completed", "partial": "partial", "unsupported": "unsupported", "failed": "failed", "retrying": "retrying",
                "blocked_permission": "blocked", "blocked_budget": "blocked", "cancelled": "cancelled"}


def tick(intel, connect, *, max_jobs: int = 4, max_seconds: float = 20.0, clock=time.monotonic) -> dict:
    """Cron entry (LibraryIntelligence.tick): recover stale work, then claim and run up to max_jobs within max_seconds."""
    summary = {"claimed": 0, "recovered": 0, "orphansSettled": 0, "completed": 0, "partial": 0, "unsupported": 0, "failed": 0, "retrying": 0,
               "blocked": 0, "cancelled": 0, "lost": 0, "errors": 0}
    if not policy.enabled("enrichment"):
        return {"status": "disabled", **summary}
    started = clock()
    summary["recovered"] = _recover(connect)
    summary["orphansSettled"] = _settle_orphans(connect)
    while summary["claimed"] < max(0, int(max_jobs)) and clock() - started < max_seconds:
        prepared = claim_next(intel, connect)
        if prepared is None:
            break
        summary["claimed"] += 1
        try:
            outcome = run_claimed(intel, connect, prepared)
        except Exception as error:
            # The lease expires and the next tick retries or fails the job; nothing partial was committed.
            print(json.dumps({"event": "library_intelligence.job_error", "error": type(error).__name__}), flush=True)
            summary["errors"] += 1
            continue
        summary[SUMMARY_KEYS.get(outcome, "lost")] += 1
    return {"status": "ok", **summary}
