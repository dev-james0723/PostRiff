"""Durable leased jobs and retention for raw-file intake (PRD R-FWR-04, R-NFR-02, R-NFR-04).

`tick(hosted, deadline)` is the cron step (`growth_v2_routes.CRON`); `run_one` is also used by the bounded "process
now" route, so both take the same lease. Each step is bounded and never raises:

1. recover: a lease that expired before any provider I/O goes back to the queue (or fails once attempts run out);
   one that expired after a transcription was sent is `failed/outcome_unknown` with its cost kept pending — never
   retried automatically;
2. work (only while RAFII_SOURCE_UPLOADS_ENABLED is on): claim at most a few queued jobs whose time budget fits;
3. retention (always): expired signed uploads, text never used, files past their 30 days, sources retracted;
4. purges (always): delete queued objects; a failure is counted, kept with its error and retried with backoff.

Locks are taken workspace row first, then job row — the same order as the API's repository transaction. Every write
of an outcome re-checks the lease fence, so a cancelled or recovered job can never publish a late result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from postriff_alpha.domain import AlphaError

from . import limits, pdf_text, store, transcribe
from .store import NOW, Later

LEASE_SECONDS = 120
MARGIN = 3.0
BATCH = 4
STEP_ROWS = 20
PURGE_ROWS = 25
BACKOFF = (30, 120, 600)
NEGATIVE = ("failed", "unsupported", "cancelled")
log = logging.getLogger("postriff.source_uploads")


class Retry(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _lock(cur, workspace_id):
    cur.execute("SELECT 1 FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
    return cur.fetchone() is not None


def _needed(svc, kind):
    """Seconds one attempt of this kind may take; a job is only claimed when that much time is left."""
    if kind == "pdf_text":
        return svc.policy.pdf_seconds + 5
    if kind == "transcription":
        route, _ = svc.route()
        return (float(route.timeout_seconds) if route else 0) + 10
    return 5


def claim(svc, *, workspace_id=None, job_id=None, deadline=None):
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("SELECT workspace_id::text, id::text, kind FROM public.pr_source_upload_jobs WHERE state='queued' AND due_at<=now() AND NOT cancel_requested "
                    "AND attempts<max_attempts AND (%s::uuid IS NULL OR workspace_id=%s::uuid) AND (%s::uuid IS NULL OR id=%s::uuid) ORDER BY due_at, id LIMIT 8",
                    (workspace_id, workspace_id, job_id, job_id))
        candidates = cur.fetchall()
    for wid, jid, kind in candidates:
        if deadline is not None and deadline - time.monotonic() < _needed(svc, kind):
            continue
        owner = f"intake:{uuid.uuid4().hex[:16]}"
        with svc.connect() as db, db.cursor() as cur:
            if not _lock(cur, wid):
                continue
            cur.execute("UPDATE public.pr_source_upload_jobs SET state='running', lease_owner=%s, lease_until=now()+make_interval(secs=>%s), "
                        "lease_generation=lease_generation+1, attempts=attempts+1, updated_at=now() WHERE workspace_id=%s AND id=%s AND state='queued' "
                        "AND NOT cancel_requested AND attempts<max_attempts AND due_at<=now() RETURNING id", (owner, LEASE_SECONDS, wid, jid))
            if cur.fetchone() is None:
                continue
            return store.job(cur, wid, jid)
    return None


def _fenced(cur, claimed):
    _lock(cur, claimed["workspaceId"])
    current = store.job(cur, claimed["workspaceId"], claimed["id"], lock=True)
    ok = (current is not None and current["state"] == "running" and not current["cancelRequested"]
          and current["leaseOwner"] == claimed["leaseOwner"] and current["leaseGeneration"] == claimed["leaseGeneration"])
    return current, ok


def _settle(svc, cur, job, outcome, actual):
    """Settle the job's reservation once; returns the job's new quote_state. A completed call with no reported cost
    stays unknown (pending reconciliation), never zero."""
    if outcome == "completed" and actual is None:
        outcome = "unknown"
    found = svc.hosted.ledger.settle(cur, job["workspaceId"], job["reservationId"], outcome, actual)
    return {"actual": "settled", "released": "released", "estimated_unknown": "unknown"}.get(found.get("state"), {"completed": "settled", "failed": "released"}.get(outcome, "unknown"))


def _apply(svc, cur, current, state, reason, *, result=None, progress=None, settle=None, due=None, unbilled=False):
    """Write an outcome for a job whose row (and workspace) the caller holds locked."""
    wid, jid = current["workspaceId"], current["id"]
    fields = {"state": state, "reasonCode": reason, "leaseOwner": None, "leaseUntil": None,
              "progress": {**(current["progress"] or {}), **(progress or {})}}
    if unbilled:
        fields["dispatchedAt"] = None
    if settle is None and state in NEGATIVE and current["quoteState"] == "reserved" and current["reservationId"]:
        settle = ("unknown", None) if current["dispatchedAt"] and not unbilled else ("failed", 0)
    if settle and current["reservationId"] and current["quoteState"] == "reserved":
        fields["quoteState"] = _settle(svc, cur, current, *settle)
    if result is not None:
        fields.update(resultId=store.insert_result(cur, wid, jid, result), currentRevision=0, reviewedRevision=None)
    if state == "needs_review":
        fields["reviewExpiresAt"] = Later(limits.REVIEW_DAYS * 86400)
    if state in store.TERMINAL:
        fields["completedAt"] = NOW
    if state == "queued":
        fields["dueAt"] = Later(due) if due else NOW
    store.update_job(cur, wid, jid, **fields)
    if state in NEGATIVE:
        upload = store.upload(cur, wid, current["uploadId"], lock=True)
        if upload:
            store.delete_derived(cur, wid, jid)
            store.queue_purge(cur, upload, reason or state)
            if state == "cancelled" and upload["state"] in ("pending", "committed"):
                store.update_upload(cur, wid, upload["id"], state="cancelled", reasonCode=reason)
    svc._audit(cur, wid, None, f"source_upload.job_{state}", jid, {"kind": current["kind"], **({"reason": reason} if reason else {})})
    return state


def _finish(svc, claimed, state, reason, **kwargs):
    """Fenced write of an attempt's outcome; 'discarded' when the job was cancelled or recovered meanwhile."""
    with svc.connect() as db, db.cursor() as cur:
        current, ok = _fenced(cur, claimed)
        if ok:
            return _apply(svc, cur, current, state, reason, **kwargs)
        settle = kwargs.get("settle")
        if settle and current and current["reservationId"] and current["quoteState"] == "reserved":
            # Cancelled while the provider worked: nothing reaches the person, so their credits are released; the
            # provider's real cost is still booked (or kept unknown).
            outcome = "failed" if settle[0] == "completed" and settle[1] is not None else "unknown"
            store.update_job(cur, current["workspaceId"], current["id"], quoteState=_settle(svc, cur, current, outcome, settle[1]), leaseOwner=None, leaseUntil=None)
        return "discarded"


def _release(svc, claimed, code, *, unbilled=False):
    """A failure that is safe to retry (nothing billable happened): back to the queue with backoff, or failed once
    the attempts are used up. A failure after a transcription was sent is an unknown outcome instead."""
    with svc.connect() as db, db.cursor() as cur:
        current, ok = _fenced(cur, claimed)
        if not ok:
            if unbilled and current and current["reservationId"] and current["quoteState"] == "reserved" and current["state"] == "cancelled":
                # Cancelled while a refused (unbilled) call was out: release the reservation instead of leaving it held.
                store.update_job(cur, current["workspaceId"], current["id"], quoteState=_settle(svc, cur, current, "failed", 0),
                                 dispatchedAt=None, leaseOwner=None, leaseUntil=None)
            return "discarded"
        if current["dispatchedAt"] and not unbilled:
            return _apply(svc, cur, current, "failed", "outcome_unknown")
        if current["attempts"] >= current["maxAttempts"]:
            return _apply(svc, cur, current, "failed", code, unbilled=unbilled)
        return _apply(svc, cur, current, "queued", code, due=BACKOFF[min(current["attempts"], len(BACKOFF)) - 1], unbilled=unbilled)


def _renew(svc, claimed, progress, *, seconds=LEASE_SECONDS, dispatch=False):
    with svc.connect() as db, db.cursor() as cur:
        current, ok = _fenced(cur, claimed)
        if not ok:
            return False
        store.update_job(cur, current["workspaceId"], current["id"], leaseUntil=Later(seconds), progress={**(current["progress"] or {}), **progress},
                         **({"dispatchedAt": NOW} if dispatch else {}))
        return True


def _preconditions(svc, claimed):
    """(reason to stop, upload): the uploader must still be an active editor, the workspace not being deleted and the
    verified object still present."""
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("SELECT w.state ? 'accountDeletion', m.role, m.status, p.deleted_at IS NULL FROM public.pr_workspaces w "
                    "LEFT JOIN public.pr_memberships m ON m.workspace_id=w.id AND m.user_id=%s LEFT JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s",
                    (claimed["createdBy"], claimed["workspaceId"]))
        row = cur.fetchone()
        upload = store.upload(cur, claimed["workspaceId"], claimed["uploadId"])
    if row is None:
        return "workspace_unavailable", upload
    deleting, role, status, profile = row
    if deleting:
        return "account_deletion", upload
    if status != "active" or not profile or role not in ("owner", "admin", "editor"):
        return "membership_revoked", upload
    if upload is None or upload["state"] != "committed" or upload["objectState"] != "present":
        return "upload_missing", upload
    return None, upload


def _bytes(svc, claimed, upload):
    try:
        data = svc._read(claimed["workspaceId"], upload["objectName"], int(upload["bytes"]))
    except AlphaError as error:
        if error.code == "upload_incomplete":
            return None, "object_missing"
        raise Retry("storage_unavailable") from None
    if hashlib.sha256(data).hexdigest() != upload["sha256"]:
        return None, "object_changed"
    return data, None


def _pdf(svc, claimed, deadline):
    from ..coworker.research_broker import injection_flags
    reason, upload = _preconditions(svc, claimed)
    if reason:
        return _finish(svc, claimed, "cancelled", reason)
    if not pdf_text.available():
        return _finish(svc, claimed, "unsupported", "pdf_parser_unavailable")
    data, problem = _bytes(svc, claimed, upload)
    if problem:
        return _finish(svc, claimed, "failed", problem)
    if not _renew(svc, claimed, {"stage": "extracting"}):
        return "discarded"
    seconds = max(1.0, min(float(svc.policy.pdf_seconds), deadline - time.monotonic() - MARGIN))
    pages = (claimed["pagesFrom"], claimed["pagesTo"]) if claimed["pagesFrom"] else None
    out = pdf_text.extract(data, max_bytes=int(upload["limits"].get("maxBytes") or svc.policy.pdf_max_bytes), max_pages=svc.policy.pdf_max_pages,
                           max_chars=svc.policy.text_max_chars, seconds=seconds, pages=pages)
    status, selection = out["status"], out.get("selection") or [None, None]
    facts = {"pageCount": out.get("pageCount"), "selection": out.get("selection")}
    if status == "ok":
        text = out["text"]
        return _finish(svc, claimed, "needs_review", "text_review",
                       result={"kind": "pdf_text", "text": text, "pageCount": out["pageCount"], "pagesFrom": selection[0], "pagesTo": selection[1],
                               "pages": out["pages"][:100], "injectionFlags": injection_flags(text)[:12]},
                       progress={**facts, "stage": "review", "emptyPages": [p["page"] for p in out["pages"] if not p["chars"]][:100], "failedPages": out.get("failedPages") or []})
    if status in ("too_many_pages", "over_limit"):
        return _finish(svc, claimed, "needs_review", "page_selection_required",
                       progress={**facts, "stage": "select_pages", "totalChars": out.get("totalChars"), "maxChars": svc.policy.text_max_chars,
                                 "maxPages": svc.policy.pdf_max_pages, "pages": (out.get("pages") or [])[:100]})
    if status == "timeout":
        raise Retry("extraction_timeout")
    reason = {"encrypted": "encrypted", "no_text_layer": "no_text_layer", "parser_unavailable": "pdf_parser_unavailable"}.get(status, "pdf_unreadable")
    return _finish(svc, claimed, "unsupported", reason, progress={**facts, "stage": "done"})


def _audio(svc, claimed, deadline):
    from ..coworker.research_broker import injection_flags
    from .service import clean_text
    reason, upload = _preconditions(svc, claimed)
    if reason:
        return _finish(svc, claimed, "cancelled", reason)
    if claimed["quoteState"] != "reserved" or not claimed["reservationId"]:
        return _finish(svc, claimed, "failed", "quote_missing")
    route, why = svc.route()
    if route is None:
        return _finish(svc, claimed, "unsupported", why or "transcription_route_not_enabled")
    seconds = float(upload["durationSeconds"] or 0)
    if seconds > route.max_seconds or int(upload["bytes"]) > route.max_bytes:
        return _finish(svc, claimed, "unsupported", "provider_limit")
    data, problem = _bytes(svc, claimed, upload)
    if problem:
        return _finish(svc, claimed, "failed", problem)
    # From here on a lost answer is an unknown outcome: its cost stays pending and it is never resent automatically.
    if not _renew(svc, claimed, {"stage": "transcribing"}, seconds=float(route.timeout_seconds) + 60, dispatch=True):
        return "discarded"
    try:
        out = route.transcribe(data, upload["mime"], seconds, timeout=float(route.timeout_seconds))
    except transcribe.TranscriptionFailed as error:
        return _release(svc, claimed, error.code, unbilled=True)
    except Exception as error:  # noqa: BLE001 - any other failure after dispatch is an unknown outcome
        log.warning(json.dumps({"event": "source_upload.transcription_unknown", "error": type(error).__name__}))
        return _finish(svc, claimed, "failed", "outcome_unknown")
    actual = out.get("actualUsdMicro") if isinstance(out, dict) else None
    actual = actual if type(actual) is int and actual >= 0 else None
    settle = ("completed", actual)
    text = clean_text((out or {}).get("text") or "") if isinstance(out, dict) else ""
    if not text:
        return _finish(svc, claimed, "failed", "transcript_empty", settle=settle)
    if len(text) > svc.policy.text_max_chars:
        return _finish(svc, claimed, "failed", "over_limit", settle=settle, progress={"totalChars": len(text)})
    return _finish(svc, claimed, "needs_review", "text_review", settle=settle, progress={"stage": "review"},
                   result={"kind": "transcript", "text": text, "durationSeconds": seconds, "injectionFlags": injection_flags(text)[:12],
                           "synthetic": bool(route.synthetic), "provider": route.provider, "model": route.model})


def run_one(svc, deadline, *, workspace_id=None, job_id=None):
    """Claim and run one queued job (optionally a specific one). None when nothing was claimable in time."""
    claimed = claim(svc, workspace_id=workspace_id, job_id=job_id, deadline=deadline)
    if claimed is None:
        return None
    try:
        handler = {"pdf_text": _pdf, "transcription": _audio}.get(claimed["kind"])
        if handler is None:
            return _finish(svc, claimed, "failed", "unsupported_job")
        return handler(svc, claimed, deadline)
    except Retry as retry:
        return _release(svc, claimed, retry.code)
    except Exception as error:  # noqa: BLE001 - one job's defect never stops the worker; its state stays truthful
        log.warning(json.dumps({"event": "source_upload.job_error", "kind": claimed["kind"], "error": type(error).__name__}))
        return _release(svc, claimed, "worker_error")


def work(svc, deadline):
    if not svc.policy.enabled:
        return {"status": "paused"}
    outcomes = {}
    for _ in range(BATCH):
        if deadline - time.monotonic() < 5:
            break
        outcome = run_one(svc, deadline)
        if outcome is None:
            break
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {"status": "ok", "outcomes": outcomes}


def recover(svc):
    """Expired leases. A cancelled transcription that was already sent is settled as unknown here too."""
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("SELECT workspace_id::text, id::text FROM public.pr_source_upload_jobs WHERE lease_until < now() AND (state='running' "
                    "OR (state='cancelled' AND quote_state='reserved' AND dispatched_at IS NOT NULL)) ORDER BY lease_until LIMIT %s", (STEP_ROWS,))
        expired = cur.fetchall()
    counts = {}
    for wid, jid in expired:
        with svc.connect() as db, db.cursor() as cur:
            _lock(cur, wid)
            current = store.job(cur, wid, jid, lock=True)
            cur.execute("SELECT coalesce(lease_until < now(), false) FROM public.pr_source_upload_jobs WHERE workspace_id=%s AND id=%s", (wid, jid))
            still = cur.fetchone()
            if current is None or not still or not still[0]:
                continue   # renewed or finished since it was listed
            if current["state"] == "cancelled":
                quote_state = _settle(svc, cur, current, "unknown", None) if current["reservationId"] else current["quoteState"]
                store.update_job(cur, wid, jid, quoteState=quote_state, leaseOwner=None, leaseUntil=None)
                outcome = "cancelled_unknown"
            elif current["state"] != "running":
                continue
            elif current["dispatchedAt"]:
                outcome = _apply(svc, cur, current, "failed", "outcome_unknown")
            elif current["attempts"] >= current["maxAttempts"]:
                outcome = _apply(svc, cur, current, "failed", "attempts_exhausted")
            else:
                outcome = _apply(svc, cur, current, "queued", "lease_expired", due=BACKOFF[0])
            counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _locked(cur, wid, upload_id):
    _lock(cur, wid)
    upload = store.upload(cur, wid, upload_id, lock=True)
    return upload, (store.job(cur, wid, upload_id=upload_id, lock=True) if upload else None)


def sweep(svc):
    """Retention (privacy.RETENTION_CLASSES['raw_source_uploads']). Bounded per step; each row in its own transaction."""
    steps = {
        # a signed URL that was never finished (it can't write any more an hour after expiry)
        "uploadExpired": ("SELECT workspace_id::text, id::text FROM public.pr_source_uploads WHERE state='pending' AND token_expires_at < now() - interval '1 hour' "
                          "ORDER BY token_expires_at LIMIT %s", "upload_expired", False),
        # text that was never used (or a job left queued) for the review window
        "reviewExpired": ("SELECT j.workspace_id::text, j.upload_id::text FROM public.pr_source_upload_jobs j WHERE j.state IN ('queued','needs_review') "
                          "AND j.review_expires_at < now() ORDER BY j.review_expires_at LIMIT %s", "review_expired", False),
        # the file's days after a source was made from it (or any committed upload past its retention) are over
        "retentionElapsed": ("SELECT workspace_id::text, id::text FROM public.pr_source_uploads WHERE state='committed' AND retain_until < now() "
                             "ORDER BY retain_until LIMIT %s", "retention_elapsed", True),
        # the source made from it was retracted (or is gone): its file and text go with it
        "sourceRetracted": ("SELECT j.workspace_id::text, j.upload_id::text FROM public.pr_source_upload_jobs j JOIN public.pr_workspaces w ON w.id=j.workspace_id "
                            "JOIN public.pr_source_uploads u ON u.workspace_id=j.workspace_id AND u.id=j.upload_id WHERE j.state='completed' AND j.source_id IS NOT NULL "
                            "AND u.state='committed' AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.state->'sources')='array' "
                            "THEN w.state->'sources' ELSE '[]'::jsonb END) s WHERE s->>'id'=j.source_id AND s->>'active'='true') LIMIT %s", "source_retracted", True),
    }
    counts = {}
    for name, (query, reason, delete) in steps.items():
        with svc.connect() as db, db.cursor() as cur:
            cur.execute(query, (STEP_ROWS,))
            due = cur.fetchall()
        done = 0
        for wid, upload_id in due:
            with svc.connect() as db, db.cursor() as cur:
                upload, job = _locked(cur, wid, upload_id)
                if upload is None or upload["state"] not in ("pending", "committed"):
                    continue
                svc.stop(cur, upload, job, reason, delete=delete)
                done += 1
        counts[name] = done
    # A finished job whose object is somehow still present: queue it (belt and braces for the at-once deletions).
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("SELECT u.workspace_id::text, u.id::text FROM public.pr_source_uploads u JOIN public.pr_source_upload_jobs j ON j.workspace_id=u.workspace_id "
                    "AND j.upload_id=u.id WHERE u.object_state='present' AND j.state IN ('failed','unsupported','cancelled') LIMIT %s", (STEP_ROWS,))
        stale = cur.fetchall()
    for wid, upload_id in stale:
        with svc.connect() as db, db.cursor() as cur:
            upload, job = _locked(cur, wid, upload_id)
            if upload and upload["objectState"] == "present":
                store.queue_purge(cur, upload, f"job_{job['state']}" if job else "job_finished")
    counts["finishedObjects"] = len(stale)
    # Settled tombstones (cancelled, rejected, deleted) go entirely after the review window, file names included; never
    # while an object deletion is still queued or a transcription reservation is still held.
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("DELETE FROM public.pr_source_uploads WHERE id IN (SELECT u.id FROM public.pr_source_uploads u WHERE u.state IN ('rejected','cancelled','deleted') "
                    "AND u.object_state IN ('none','deleted') AND u.updated_at < now() - make_interval(days => %s) AND NOT EXISTS (SELECT 1 FROM public.pr_source_upload_jobs j "
                    "WHERE j.workspace_id=u.workspace_id AND j.upload_id=u.id AND j.quote_state='reserved') ORDER BY u.updated_at LIMIT %s)", (limits.REVIEW_DAYS, STEP_ROWS))
        counts["tombstonesRemoved"] = cur.rowcount
    return counts


def drain(svc, *, upload_id=None, limit=PURGE_ROWS):
    """Delete queued objects. Storage treats a missing object as deleted, so a retry is always safe."""
    storage = svc.storage
    with svc.connect() as db, db.cursor() as cur:
        if storage is None:
            cur.execute("SELECT count(*) FROM public.pr_source_upload_purges")
            return {"status": "storage_unavailable", "pending": int(cur.fetchone()[0])}
        cur.execute("UPDATE public.pr_source_upload_purges SET attempts=attempts+1, not_before=now()+interval '5 minutes' WHERE id IN "
                    "(SELECT id FROM public.pr_source_upload_purges WHERE not_before<=now() AND (%s::uuid IS NULL OR upload_id=%s::uuid) "
                    "ORDER BY not_before, id LIMIT %s FOR UPDATE SKIP LOCKED) RETURNING id::text, workspace_id::text, upload_id::text, bucket, object_name, attempts",
                    (upload_id, upload_id, limit))
        claimed = cur.fetchall()
    removed = failed = 0
    for purge_id, wid, uid, bucket, name, attempts in claimed:
        try:
            if bucket != getattr(storage, "source_bucket", bucket):
                raise AlphaError("The object is in a bucket this deployment doesn't manage.", 409)
            storage.delete(wid, "source", name)
        except Exception as error:  # noqa: BLE001 - kept with its reason and retried later
            with svc.connect() as db, db.cursor() as cur:
                cur.execute("UPDATE public.pr_source_upload_purges SET last_error=%s, not_before=now()+make_interval(secs=>%s) WHERE id=%s",
                            (f"{type(error).__name__}: {error}"[:200], min(3600, 60 * 2 ** min(int(attempts), 6)), purge_id))
            failed += 1
            continue
        with svc.connect() as db, db.cursor() as cur:
            cur.execute("DELETE FROM public.pr_source_upload_purges WHERE id=%s", (purge_id,))
            cur.execute("UPDATE public.pr_source_uploads SET object_state='deleted', updated_at=now() WHERE workspace_id=%s AND id=%s AND object_state='deleting'", (wid, uid))
        removed += 1
    with svc.connect() as db, db.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE attempts > 0) FROM public.pr_source_upload_purges")
        pending, retrying = cur.fetchone()
    return {"removed": removed, "failed": failed, "pending": int(pending), "retrying": int(retrying)}


def tick(hosted, deadline):
    """The cron step: counts and status codes only (no ids, names or text)."""
    from .service import ensure
    svc = ensure(hosted)
    try:
        with svc.connect() as db, db.cursor() as cur:
            if not store.installed(cur):
                return {"status": "not_installed"}
    except Exception as error:  # noqa: BLE001
        return {"status": "unavailable", "reason": type(error).__name__}
    summary = {"status": "ok"}
    for name, step in (("recovered", lambda: recover(svc)), ("jobs", lambda: work(svc, deadline)),
                       ("retention", lambda: sweep(svc)), ("purges", lambda: drain(svc))):
        if time.monotonic() >= deadline - 1:
            summary[name] = {"status": "deferred"}
            continue
        try:
            summary[name] = step()
        except Exception as error:  # noqa: BLE001 - one step's failure never hides the others
            log.warning(json.dumps({"event": "source_upload.step_failed", "step": name, "error": type(error).__name__}))
            summary[name] = {"status": "unavailable", "reason": type(error).__name__}
    return summary
