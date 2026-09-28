"""Operator-only AI quota exemptions, bound to authenticated immutable user IDs.

Never use a handle, email, request flag or user-editable profile as authority.
An empty/invalid allowlist grants nothing. This changes quotas, not permissions.
"""
import os
from uuid import UUID


def ai_usage_exempt(member_id):
    try:
        actor = UUID(str(member_id))
        configured = os.environ.get("RAFII_AI_UNLIMITED_USER_IDS", "")
        allowed = {UUID(value.strip()) for value in configured.split(",") if value.strip()}
    except (ValueError, TypeError, AttributeError):
        return False
    return actor in allowed
