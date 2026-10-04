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


def _server_founder(cur, member_id):
    """Recognize the control-plane Founder from its server-created internal tenant marker."""
    try:
        actor = str(UUID(str(member_id)))
    except (ValueError, TypeError, AttributeError):
        return False
    cur.execute(
        "SELECT w.id::text FROM public.pr_workspaces w "
        "JOIN public.pr_memberships m ON m.workspace_id=w.id "
        "WHERE m.user_id=%s AND m.role='owner' AND m.status='active' "
        "AND w.state->'workspace'->>'name' LIKE 'Rafii Ops (founder)%%' "
        "AND w.state->'founderOps'->>'operatorId'=%s "
        "AND w.state->'founderOps'->>'version'='1' "
        "AND w.state->'founderOps'->>'environment' IN ('local','staging','production') LIMIT 2",
        (actor, actor),
    )
    return len(cur.fetchall()) == 1


def workspace_plan_exempt(cur, workspace_id):
    """A verified Founder-owned workspace is outside customer commercial plan ceilings.

    Authority comes from the optional immutable UUID allowlist or Rafii's server-created Founder
    Ops marker. Email/profile fields and request flags never confer Founder status.
    """
    allowed = _allowlist(FOUNDER_ALLOWLIST)
    cur.execute(
        "SELECT user_id::text FROM public.pr_memberships "
        "WHERE workspace_id=%s AND role='owner' AND status='active'",
        (workspace_id,),
    )
    owners = cur.fetchall()
    for row in owners:
        try:
            owner = UUID(str(row[0]))
        except (ValueError, TypeError, AttributeError, IndexError):
            continue
        if owner in allowed or _server_founder(cur, owner):
            return True
    return False
