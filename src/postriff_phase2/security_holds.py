"""Rafii Account Protection v2, P1 item 3: account holds and fences.

A security hold (pr_security_account_controls, migration 121) stops everything that acts *as* a person without them
present: scheduled campaign runs, automation drafting and publishing, Agent task steps and API tokens. It is checked
at claim and again immediately before the external publish or call, inside the same transaction as the write that
follows. A job that captured `hold_epoch` at claim also refuses when the epoch moved since (a hold was placed, even if
already released). And work authorized before the latest hold was placed (a campaign activation, a post or job
approval, an Agent task) is refused even after the hold is released: it needs a fresh approval, so a hold that is
placed and lifted between two worker ticks still voids every earlier approval.

Fail closed, unlike operator_actions._lookup: if the controls cannot be read (missing table, privilege drift, any
database error) the action is refused with 503 `security_state_unavailable`. That is why this is behind its own flag,
RAFII_SECURITY_INCIDENT_HOLD (default off): turning it on before migration 121 is applied would stop all automation.

With the flag off a hold that is already active is still enforced: the flag is the rollback lever for the incident
route and the epoch fences, never a way to reopen a held account. That core check fails open as the app did before
holds existed (no control table, no privilege on it, or no row means clear) and its availability is probed without
an error, so it can never abort the caller's transaction. The epoch and authorization-time fences run only with the
flag on.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError

_ON = ("1", "on", "true")
# assert_clear(authorized_at=_SKIP): this caller has no authorization time to compare (a per-request credential check).
_SKIP = object()


def enabled(values=None):
    from .coworker import flags
    return str(flags._source(values).get("RAFII_SECURITY_INCIDENT_HOLD", "")).strip().lower() in _ON


class AccountHeld(AlphaError):
    def __init__(self, message="This account is on a security hold. Nothing runs for it until the hold is lifted from Account → Security.", *, code="security_account_hold"):
        super().__init__(message, 403, code=code)


def unavailable():
    return AlphaError("This action is paused while account security can't be checked. It will be retried.", 503, code="security_state_unavailable")


def read(cur, user_id):
    """(hold_active, hold_epoch, last placement as epoch seconds or None) for a person; (False, 0, None) when they never
    had a control row. Raises 503 on any failure."""
    try:
        cur.execute("SELECT hold_active,hold_epoch,extract(epoch from placed_at) FROM public.pr_security_account_controls WHERE user_id=%s", (str(user_id),))
        row = cur.fetchone()
    except Exception as error:
        raise unavailable() from error
    return (bool(row[0]), int(row[1]), float(row[2]) if row[2] is not None else None) if row else (False, 0, None)


def snapshot(cur, user_id, authorized_at=_SKIP):
    """The epoch to capture at claim, after checking there is no active hold (and that the work was authorized after the
    latest hold, when `authorized_at` is given); None with the flag off."""
    return assert_clear(cur, user_id, authorized_at=authorized_at)


def assert_clear(cur, user_id, expected_epoch=None, authorized_at=_SKIP):
    """Raise unless `user_id` has no active hold, the epoch is still `expected_epoch` (when given), and the work was
    authorized after the latest hold placement (when `authorized_at` is given; None means unknown and counts as before).
    Returns the current epoch; None with the flag off, where only an active hold refuses (core_hold)."""
    if not enabled():
        core_hold(cur, user_id)
        return None
    if not user_id:
        raise unavailable()
    active, epoch, placed = read(cur, user_id)
    if active:
        raise AccountHeld()
    if expected_epoch is not None and epoch != expected_epoch:
        raise AccountHeld("A security hold changed this account after the job started, so it was not run. Approve it again to continue.", code="security_hold_changed")
    if authorized_at is not _SKIP and placed is not None and (type(authorized_at) not in (int, float) or float(authorized_at) < placed):
        raise AccountHeld("This was approved before a security hold on the account, so it was not run. Approve it again to continue.", code="security_hold_changed")
    return epoch


_PROBE = "SELECT CASE WHEN to_regclass('public.pr_security_account_controls') IS NULL THEN false ELSE has_table_privilege(to_regclass('public.pr_security_account_controls'), 'SELECT') END"
# Whether the control table is readable here: (readable, checked at). Re-probed every _PROBE_SECONDS while it is not.
_INSTALLED = {"readable": False, "checked": float("-inf")}
_PROBE_SECONDS = 300


def core_hold(cur, user_id):
    """Flag off: raise AccountHeld when `user_id` has an active hold; otherwise (including when it can't be known) pass."""
    import time
    if not user_id:
        return
    if not _INSTALLED["readable"]:
        if time.monotonic() - _INSTALLED["checked"] < _PROBE_SECONDS:
            return
        cur.execute(_PROBE)
        row = cur.fetchone()
        _INSTALLED.update(readable=bool(row and row[0]), checked=time.monotonic())
        if not _INSTALLED["readable"]:
            return
    cur.execute("SELECT hold_active FROM public.pr_security_account_controls WHERE user_id=%s", (str(user_id),))
    row = cur.fetchone()
    if row and row[0]:
        raise AccountHeld()


def fenced_repository(repository, principal, hold_epoch):
    """A copy of `repository` whose every transaction first re-checks `principal`'s hold against the epoch captured at
    claim: for work that runs with the person's own session (inline Agent task steps)."""
    import copy
    from contextlib import contextmanager
    fenced = copy.copy(repository)
    base = repository.transaction

    @contextmanager
    def transaction(token, workspace_id, **kwargs):
        with base(token, workspace_id, **kwargs) as opened:
            assert_clear(opened[0], principal, hold_epoch)
            yield opened
    fenced.transaction = transaction
    return fenced


def place(cur, user_id, reason):
    """Place a hold; returns the new epoch. Used by the "This wasn't me" flow (item 4)."""
    cur.execute("SELECT public.pr_security_set_hold(%s,true,%s)", (str(user_id), reason))
    return int(cur.fetchone()[0])


def release(cur, user_id, reason):
    cur.execute("SELECT public.pr_security_set_hold(%s,false,%s)", (str(user_id), reason))
    return int(cur.fetchone()[0])
