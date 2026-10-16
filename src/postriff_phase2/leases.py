"""Shared producer-lease semantics for durable background work (CF-3 §5.2, §9.2).

Extracted only from merged code: the Generative UI producer lease in `agent_runtime_v2/ui_store.py` (lease = timeout +
30 s; renewal is a guarded UPDATE on the lease owner and a live state; a closed attempt makes its producer stop; reaping
marks the attempt `interrupted` and keeps an unknown cost held, never zero), plus the backoff and failure classification
written out in CF-3 §9.2. `ui_store.py` keeps its own copy (it is frozen for the GenUI lanes); new executors use this one.

Nothing here performs I/O beyond the SQL it is handed a cursor for, and nothing here reads or writes content.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

LEASE_GRACE_SECONDS = 30          # lease = timeout + 30 s (ui_store.LEASE_SECONDS uses the same margin)
HEARTBEAT_EVERY_SECONDS = 20      # a long step renews at least this often (CF-3 §5.2)
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 900
RETRY_AFTER_CAP_SECONDS = 3600
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Internal error categories of an attempt (CF-3 §2). `lease_lost` is not one: a producer that lost its lease writes nothing.
CATEGORIES = ("retryable", "permanent", "permission", "budget", "cancelled", "corrupt", "timeout", "unsupported", "revoked",
              "outcome_unknown", "conflict")


def lease_seconds(timeout_seconds: int) -> int:
    return int(timeout_seconds) + LEASE_GRACE_SECONDS


def backoff_seconds(attempt: int, *, retry_after: float | None = None, rand=random.random) -> int:
    """delay = ceil(min(900, 30·2^(attempt−1)) · (1 + 0.25·rand)), then max(delay, Retry-After capped at 3600 s)."""
    attempt = max(1, int(attempt))
    base = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    delay = math.ceil(base * (1 + 0.25 * float(rand())))
    if retry_after is not None:
        try:
            delay = max(delay, int(min(float(retry_after), RETRY_AFTER_CAP_SECONDS)))
        except (TypeError, ValueError):
            pass
    return int(delay)


@dataclass(frozen=True)
class Outcome:
    """What a finished (or reaped) attempt does to its step."""
    state: str                       # queued | failed | blocked | cancelled
    reason_code: str | None = None
    delay_seconds: int = 0           # for queued: next_attempt_at = now + delay
    retry_now: bool = False          # a conflict's single immediate retry


def classify(category: str, *, retry_class: str, attempts: int, max_attempts: int, conflict_retried: bool = False,
             retry_after: float | None = None, rand=random.random) -> Outcome:
    """CF-3 §9.2: retryable/timeout → queued with backoff if `auto` and attempts remain, else failed; conflict → one immediate
    retry, then failed; permission/revoked → blocked; budget → blocked; permanent/corrupt/unsupported → failed; cancelled →
    cancelled; outcome_unknown (a lease lost with no receipt) → failed/outcome_unknown, never re-run automatically."""
    if category not in CATEGORIES:
        category = "permanent"
    if category in ("retryable", "timeout"):
        if retry_class == "auto" and attempts < max_attempts:
            return Outcome("queued", None, backoff_seconds(attempts, retry_after=retry_after, rand=rand))
        return Outcome("failed", "outcome_unknown" if category == "timeout" else None)
    if category == "conflict":
        # One immediate retry whatever the retry class (the effect did not happen), then failed.
        return Outcome("failed", None) if conflict_retried else Outcome("queued", None, 0, retry_now=True)
    if category == "revoked":
        return Outcome("blocked", "permission_revoked")
    if category == "permission":
        return Outcome("blocked", "permission_missing")
    if category == "budget":
        return Outcome("blocked", "budget")
    if category == "cancelled":
        return Outcome("cancelled", "cancelled_by_person")
    if category == "outcome_unknown":
        return Outcome("failed", "outcome_unknown")
    return Outcome("failed", None)


def reaped(*, receipt_done: bool, receipt_verified: bool | None, retry_class: str, attempts: int, max_attempts: int,
           task_attempts_left: int, rand=random.random) -> Outcome | str:
    """What recovery does with a step whose attempt lost its lease (CF-3 §5.3 phase 1): 'completed' when the effect's
    receipt is done and verified (the work happened; replay it), an automatic requeue for an `auto` step with attempts left,
    otherwise failed/outcome_unknown with a manual retry offered. Never an automatic re-run of a `manual` step."""
    if receipt_done:
        return "completed" if receipt_verified else Outcome("failed", "outcome_unknown")
    if retry_class == "auto" and attempts < max_attempts and task_attempts_left > 0:
        return Outcome("queued", None, backoff_seconds(attempts, rand=rand))
    return Outcome("failed", "outcome_unknown")


# --- the guarded SQL shapes (identifiers are validated; values are always parameters) ------------------------------------
def _ident(name: str) -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"not a SQL identifier: {name!r}")
    return name


def renew(cur, table: str, row_id: str, *, lease_owner: str, timeout_seconds: int, live_state: str = "running") -> bool:
    """Renew a live lease: only its owner, only while the row is still live and the lease has not already expired (a
    reaped or cancelled attempt makes its producer stop). True when renewed."""
    table = _ident(table)
    cur.execute(f"UPDATE public.{table} SET lease_expires_at=greatest(lease_expires_at, now()+make_interval(secs => %s)), heartbeat_at=now() "
                f"WHERE id::text=%s AND lease_owner=%s AND state=%s AND lease_expires_at > now() RETURNING 1",
                (lease_seconds(timeout_seconds), str(row_id), lease_owner, live_state))
    return cur.fetchone() is not None


def still_owned(cur, table: str, row_id: str, *, lease_owner: str, live_state: str = "running", lock: bool = True) -> bool:
    """The finish guard: the row is still live and still ours. On False the caller writes nothing (lease lost)."""
    table = _ident(table)
    cur.execute(f"SELECT state, lease_owner, lease_expires_at > now() FROM public.{table} WHERE id::text=%s" + (" FOR UPDATE" if lock else ""), (str(row_id),))
    row = cur.fetchone()
    return bool(row) and row[0] == live_state and row[1] == lease_owner and row[2] is True


def expired_candidates(cur, table: str, *, live_state: str = "running", limit: int = 50, workspace_id: str | None = None) -> list[str]:
    """Ids of live rows whose lease expired, oldest first. A candidate scan only: the caller locks and re-checks each one in
    the frozen lock order before touching it (the ui_store.reap_expired pattern)."""
    table = _ident(table)
    params: list = [live_state]
    where = "state=%s AND lease_expires_at < now()"
    if workspace_id:
        where += " AND workspace_id=%s"
        params.append(workspace_id)
    cur.execute(f"SELECT id::text FROM public.{table} WHERE {where} ORDER BY lease_expires_at LIMIT %s", (*params, int(limit)))
    return [r[0] for r in cur.fetchall()]
