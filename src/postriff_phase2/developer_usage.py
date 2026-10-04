"""Operator-only quota exemptions, bound to authenticated immutable user IDs.

Never use a handle, email, request flag or user-editable profile as authority.
An empty/invalid allowlist grants nothing. Founder unlimited access changes commercial
plan/quota enforcement only; it does not change permissions, MFA, provider approvals,
rate limits, pause switches, or explicit automation safety limits.
"""
import os
from uuid import UUID

AI_ALLOWLIST = "RAFII_AI_UNLIMITED_USER_IDS"
FOUNDER_ALLOWLIST = "RAFII_FOUNDER_UNLIMITED_USER_IDS"


def _allowlist(name):
    try:
        configured = os.environ.get(name, "")
        return {UUID(value.strip()) for value in configured.split(",") if value.strip()}
    except (ValueError, TypeError, AttributeError):
        return set()


def _allowed(member_id, *names):
    try:
        actor = UUID(str(member_id))
    except (ValueError, TypeError, AttributeError):
        return False
    return any(actor in _allowlist(name) for name in names)


def founder_plan_exempt(member_id):
    """True only for an authenticated immutable Founder UUID in the server allowlist."""
    return _allowed(member_id, FOUNDER_ALLOWLIST)


def ai_usage_exempt(member_id):
    """Founder unlimited implies AI quota exemption; the legacy AI-only allowlist remains valid."""
    return _allowed(member_id, FOUNDER_ALLOWLIST, AI_ALLOWLIST)


def workspace_plan_exempt(cur, workspace_id):
    """A workspace owned by an allowlisted Founder is outside customer plan ceilings.

    Ownership is read from server-side membership state. Email/profile fields never confer authority.
    """
    allowed = _allowlist(FOUNDER_ALLOWLIST)
    if not allowed:
        return False
    cur.execute(
        "SELECT user_id::text FROM public.pr_memberships "
        "WHERE workspace_id=%s AND role='owner' AND status='active'",
        (workspace_id,),
    )
    for row in cur.fetchall():
        try:
            if UUID(str(row[0])) in allowed:
                return True
        except (ValueError, TypeError, AttributeError, IndexError):
            continue
    return False
