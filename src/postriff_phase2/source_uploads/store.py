"""Rows for raw-file intake (migration 087). Every function runs on the caller's cursor; nothing here commits.

Lookups always name the workspace with the id, so another workspace's id reads as missing. Updates go through a
column allow-list; `NOW` and `Later(seconds)` become database time, so retention never depends on a client clock.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

NOW = object()


@dataclass(frozen=True)
class Later:
    seconds: float


def digest(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _epoch(column):
    return f"extract(epoch from {column})::float8"


UPLOAD = {"id": "id::text", "workspaceId": "workspace_id::text", "kind": "kind", "state": "state", "objectState": "object_state",
          "bucket": "bucket", "objectName": "object_name", "displayName": "display_name", "declaredMime": "declared_mime", "mime": "mime",
          "sniffedType": "sniffed_type", "declaredBytes": "declared_bytes", "bytes": "bytes", "sha256": "sha256", "etag": "etag",
          "durationSeconds": "duration_seconds::float8", "limits": "limits", "reasonCode": "reason_code", "beginKey": "begin_key",
          "beginDigest": "begin_digest", "createdBy": "created_by::text", "tokenExpiresAt": _epoch("token_expires_at"),
          "committedAt": _epoch("committed_at"), "retainUntil": _epoch("retain_until"), "deletedAt": _epoch("deleted_at"),
          "createdAt": _epoch("created_at"), "updatedAt": _epoch("updated_at")}
JOB = {"id": "id::text", "workspaceId": "workspace_id::text", "uploadId": "upload_id::text", "kind": "kind", "state": "state",
       "reasonCode": "reason_code", "attempts": "attempts", "maxAttempts": "max_attempts", "leaseOwner": "lease_owner",
       "leaseUntil": _epoch("lease_until"), "leaseGeneration": "lease_generation", "cancelRequested": "cancel_requested",
       "progress": "progress", "idempotencyKey": "idempotency_key", "pagesFrom": "pages_from", "pagesTo": "pages_to",
       "quoteState": "quote_state", "quote": "quote", "reservationId": "reservation_id::text", "dispatchedAt": _epoch("dispatched_at"),
       "resultId": "result_id::text", "currentRevision": "current_revision", "reviewedRevision": "reviewed_revision",
       "sourceId": "source_id", "sourceKey": "source_key", "createdBy": "created_by::text", "dueAt": _epoch("due_at"),
       "reviewExpiresAt": _epoch("review_expires_at"), "completedAt": _epoch("completed_at"), "createdAt": _epoch("created_at"),
       "updatedAt": _epoch("updated_at")}
RESULT = {"id": "id::text", "jobId": "job_id::text", "kind": "kind", "characters": "char_count", "digest": "digest", "pageCount": "page_count",
          "pagesFrom": "pages_from", "pagesTo": "pages_to", "pages": "pages", "durationSeconds": "duration_seconds::float8",
          "injectionFlags": "injection_flags", "synthetic": "synthetic", "provider": "provider", "model": "model", "createdAt": _epoch("created_at")}

UPLOAD_SET = {"state": "state", "objectState": "object_state", "displayName": "display_name", "bytes": "bytes", "sha256": "sha256",
              "etag": "etag", "sniffedType": "sniffed_type", "durationSeconds": "duration_seconds", "reasonCode": "reason_code",
              "committedAt": "committed_at", "retainUntil": "retain_until", "deletedAt": "deleted_at", "tokenExpiresAt": "token_expires_at"}
JOB_SET = {"state": "state", "reasonCode": "reason_code", "attempts": "attempts", "leaseOwner": "lease_owner", "leaseUntil": "lease_until",
           "cancelRequested": "cancel_requested", "progress": "progress", "pagesFrom": "pages_from", "pagesTo": "pages_to",
           "quoteState": "quote_state", "quote": "quote", "reservationId": "reservation_id", "dispatchedAt": "dispatched_at",
           "resultId": "result_id", "currentRevision": "current_revision", "reviewedRevision": "reviewed_revision", "sourceId": "source_id",
           "sourceKey": "source_key", "dueAt": "due_at", "reviewExpiresAt": "review_expires_at", "completedAt": "completed_at"}
JSON_COLUMNS = {"progress", "quote", "limits", "pages", "injection_flags"}
TERMINAL = ("completed", "failed", "cancelled", "unsupported")


def _select(columns):
    return ", ".join(columns.values())


def _row(columns, row):
    return dict(zip(columns, row)) if row else None


def _set(fields, allowed):
    parts, values = [], []
    for key, value in fields.items():
        column = allowed[key]
        if value is NOW:
            parts.append(f"{column}=now()")
        elif isinstance(value, Later):
            parts.append(f"{column}=now()+make_interval(secs=>%s)")
            values.append(float(value.seconds))
        elif column in JSON_COLUMNS:
            parts.append(f"{column}=%s::jsonb")
            values.append(json.dumps(value))
        else:
            parts.append(f"{column}=%s")
            values.append(value)
    parts.append("updated_at=now()")
    return ", ".join(parts), values


# --- uploads -------------------------------------------------------------------------------------------------------------
def upload(cur, workspace_id, upload_id, lock=False):
    cur.execute(f"SELECT {_select(UPLOAD)} FROM public.pr_source_uploads WHERE workspace_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""),
                (workspace_id, upload_id))
    return _row(UPLOAD, cur.fetchone())


def upload_by_key(cur, workspace_id, key, lock=True):
    cur.execute(f"SELECT {_select(UPLOAD)} FROM public.pr_source_uploads WHERE workspace_id=%s AND begin_key=%s" + (" FOR UPDATE" if lock else ""),
                (workspace_id, key))
    return _row(UPLOAD, cur.fetchone())


def insert_upload(cur, row):
    cur.execute("""INSERT INTO public.pr_source_uploads(id,workspace_id,kind,state,object_state,bucket,object_name,display_name,declared_mime,mime,
                   sniffed_type,declared_bytes,bytes,sha256,limits,reason_code,begin_key,begin_digest,created_by,token_expires_at,committed_at,retain_until)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,
                          CASE WHEN %s::float8 IS NULL THEN NULL ELSE now()+make_interval(secs=>%s::float8) END,
                          CASE WHEN %s THEN now() END, CASE WHEN %s::float8 IS NULL THEN NULL ELSE now()+make_interval(secs=>%s::float8) END)""",
                (row["id"], row["workspaceId"], row["kind"], row["state"], row["objectState"], row.get("bucket"), row.get("objectName"),
                 row.get("displayName"), row.get("declaredMime"), row.get("mime"), row.get("sniffedType"), row.get("declaredBytes"),
                 row.get("bytes"), row.get("sha256"), json.dumps(row.get("limits") or {}), row.get("reasonCode"), row.get("beginKey"),
                 row.get("beginDigest"), row["createdBy"], row.get("tokenSeconds"), row.get("tokenSeconds"), bool(row.get("committed")),
                 row.get("retainSeconds"), row.get("retainSeconds")))


def update_upload(cur, workspace_id, upload_id, **fields):
    clause, values = _set(fields, UPLOAD_SET)
    cur.execute(f"UPDATE public.pr_source_uploads SET {clause} WHERE workspace_id=%s AND id=%s", (*values, workspace_id, upload_id))


def counts(cur, workspace_id, member):
    """(pending by this member, pending in the workspace, unfinished jobs, bytes started in the last 24 h)."""
    cur.execute("SELECT count(*) FILTER (WHERE created_by=%s), count(*) FROM public.pr_source_uploads "
                "WHERE workspace_id=%s AND state='pending' AND token_expires_at > now()", (member, workspace_id))
    mine, pending = cur.fetchone()
    cur.execute("SELECT count(*) FROM public.pr_source_upload_jobs WHERE workspace_id=%s AND state IN ('queued','running','needs_review')", (workspace_id,))
    active = cur.fetchone()[0]
    cur.execute("SELECT coalesce(sum(coalesce(bytes,declared_bytes)),0) FROM public.pr_source_uploads WHERE workspace_id=%s "
                "AND kind<>'transcript' AND created_at > now() - interval '24 hours'", (workspace_id,))
    return int(mine), int(pending), int(active), int(cur.fetchone()[0])


def page(cur, workspace_id, before=None, limit=25):
    """Newest first; `before` = (created_at epoch, id) of the last row already shown."""
    if before:
        # The cursor's row gives the exact timestamp (an epoch float can't carry every microsecond); its epoch is the fallback.
        cur.execute(f"SELECT {_select(UPLOAD)} FROM public.pr_source_uploads WHERE workspace_id=%s AND (created_at, id) < "
                    "(coalesce((SELECT c.created_at FROM public.pr_source_uploads c WHERE c.workspace_id=%s AND c.id=%s::uuid), to_timestamp(%s)), %s::uuid) "
                    "ORDER BY created_at DESC, id DESC LIMIT %s", (workspace_id, workspace_id, before[1], before[0], before[1], limit + 1))
    else:
        cur.execute(f"SELECT {_select(UPLOAD)} FROM public.pr_source_uploads WHERE workspace_id=%s ORDER BY created_at DESC, id DESC LIMIT %s",
                    (workspace_id, limit + 1))
    return [_row(UPLOAD, r) for r in cur.fetchall()]


# --- jobs ----------------------------------------------------------------------------------------------------------------
def job(cur, workspace_id, job_id=None, *, upload_id=None, lock=False):
    column, value = ("id", job_id) if job_id else ("upload_id", upload_id)
    cur.execute(f"SELECT {_select(JOB)} FROM public.pr_source_upload_jobs WHERE workspace_id=%s AND {column}=%s" + (" FOR UPDATE" if lock else ""),
                (workspace_id, value))
    return _row(JOB, cur.fetchone())


def jobs_for(cur, workspace_id, upload_ids):
    if not upload_ids:
        return {}
    cur.execute(f"SELECT {_select(JOB)} FROM public.pr_source_upload_jobs WHERE workspace_id=%s AND upload_id = ANY(%s::uuid[])", (workspace_id, list(upload_ids)))
    return {r["uploadId"]: r for r in (_row(JOB, x) for x in cur.fetchall())}


def insert_job(cur, row):
    job_id = str(uuid.uuid4())
    cur.execute("""INSERT INTO public.pr_source_upload_jobs(id,workspace_id,upload_id,kind,state,reason_code,idempotency_key,quote_state,progress,
                   result_id,created_by,review_expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,now()+make_interval(secs=>%s))""",
                (job_id, row["workspaceId"], row["uploadId"], row["kind"], row["state"], row.get("reasonCode"), row["idempotencyKey"],
                 row.get("quoteState") or "not_required", json.dumps(row.get("progress") or {}), row.get("resultId"), row["createdBy"],
                 float(row["reviewSeconds"])))
    return job_id


def update_job(cur, workspace_id, job_id, **fields):
    clause, values = _set(fields, JOB_SET)
    cur.execute(f"UPDATE public.pr_source_upload_jobs SET {clause} WHERE workspace_id=%s AND id=%s", (*values, workspace_id, job_id))


# --- results and revisions -----------------------------------------------------------------------------------------------
def insert_result(cur, workspace_id, job_id, row):
    result_id = str(uuid.uuid4())
    text = row["text"]
    cur.execute("""INSERT INTO public.pr_source_upload_results(id,workspace_id,job_id,kind,text,char_count,digest,page_count,pages_from,pages_to,
                   pages,duration_seconds,injection_flags,synthetic,provider,model) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s)""",
                (result_id, workspace_id, job_id, row["kind"], text, len(text), digest(text), row.get("pageCount"), row.get("pagesFrom"),
                 row.get("pagesTo"), json.dumps(row.get("pages") or []), row.get("durationSeconds"), json.dumps(row.get("injectionFlags") or []),
                 bool(row.get("synthetic")), row.get("provider"), row.get("model")))
    return result_id


def result(cur, workspace_id, result_id):
    if not result_id:
        return None
    cur.execute(f"SELECT {_select(RESULT)} FROM public.pr_source_upload_results WHERE workspace_id=%s AND id=%s", (workspace_id, result_id))
    return _row(RESULT, cur.fetchone())


def current_text(cur, workspace_id, job_row):
    """(text, digest, revision) the person sees now: the latest correction, else the extraction itself."""
    if not job_row or not job_row.get("resultId"):
        return None
    if job_row["currentRevision"]:
        cur.execute("SELECT text, digest, revision FROM public.pr_source_upload_revisions WHERE workspace_id=%s AND result_id=%s AND revision=%s",
                    (workspace_id, job_row["resultId"], job_row["currentRevision"]))
    else:
        cur.execute("SELECT text, digest, 0 FROM public.pr_source_upload_results WHERE workspace_id=%s AND id=%s", (workspace_id, job_row["resultId"]))
    found = cur.fetchone()
    return {"text": found[0], "digest": found[1], "revision": found[2]} if found else None


def revision_by_key(cur, workspace_id, key):
    cur.execute("SELECT result_id::text, revision, digest FROM public.pr_source_upload_revisions WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
    found = cur.fetchone()
    return {"resultId": found[0], "revision": found[1], "digest": found[2]} if found else None


def insert_revision(cur, workspace_id, result_id, revision, text, key, actor):
    cur.execute("""INSERT INTO public.pr_source_upload_revisions(id,workspace_id,result_id,revision,text,char_count,digest,idempotency_key,created_by)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (str(uuid.uuid4()), workspace_id, result_id, revision, text, len(text), digest(text), key, actor))


def revisions(cur, workspace_id, result_id):
    cur.execute("SELECT revision, char_count, created_by::text, extract(epoch from created_at)::float8 FROM public.pr_source_upload_revisions "
                "WHERE workspace_id=%s AND result_id=%s ORDER BY revision DESC LIMIT 20", (workspace_id, result_id))
    return [{"revision": r[0], "characters": r[1], "createdBy": r[2], "createdAt": r[3]} for r in cur.fetchall()]


def delete_derived(cur, workspace_id, job_id):
    """Extraction text and every correction of it (revisions cascade). Returns how many results went."""
    cur.execute("DELETE FROM public.pr_source_upload_results WHERE workspace_id=%s AND job_id=%s", (workspace_id, job_id))
    return cur.rowcount


# --- storage deletion queue ------------------------------------------------------------------------------------------------
def queue_purge(cur, upload_row, reason, *, after_token=False):
    """Mark the object for deletion and queue it (twice for a still-valid signed URL: now, and once it has expired)."""
    if not upload_row.get("objectName") or upload_row.get("objectState") in ("none", "deleted"):
        return False
    cur.execute("INSERT INTO public.pr_source_upload_purges(workspace_id,upload_id,bucket,object_name,reason) VALUES(%s,%s,%s,%s,%s)",
                (upload_row["workspaceId"], upload_row["id"], upload_row["bucket"], upload_row["objectName"], reason))
    if after_token:
        cur.execute("INSERT INTO public.pr_source_upload_purges(workspace_id,upload_id,bucket,object_name,reason,not_before) "
                    "SELECT %s,%s,%s,%s,%s,token_expires_at+interval '1 hour' FROM public.pr_source_uploads "
                    "WHERE workspace_id=%s AND id=%s AND token_expires_at > now()",
                    (upload_row["workspaceId"], upload_row["id"], upload_row["bucket"], upload_row["objectName"], reason,
                     upload_row["workspaceId"], upload_row["id"]))
    update_upload(cur, upload_row["workspaceId"], upload_row["id"], objectState="deleting")
    return True


def installed(cur):
    cur.execute("SELECT to_regclass('public.pr_source_upload_jobs') IS NOT NULL AND to_regclass('public.pr_source_upload_purges') IS NOT NULL")
    return bool(cur.fetchone()[0])
