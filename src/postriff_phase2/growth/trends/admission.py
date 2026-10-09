"""Trends read admission versus provider egress.

Two different questions, deliberately answered by two functions:

- ``admitted``: may this workspace open Trends and read what it is entitled to?
  Legacy env allowlist OR an active owner enrollment while self-serve is open.
- ``egress_allowed``: may Rafii dispatch provider/model work on behalf of this
  workspace's private scope? Only the explicit, reviewed env allowlist. Enrolling
  never creates ingestion, model spend or a source policy.

Neither function grants data: reads still pass TrendStore.authorized_scopes,
entitlements and the trend_node_valid rights chain.
"""
from __future__ import annotations

from ... import feature_enrollment
from . import config

FEATURE = "trend_radar"


def egress_allowed(workspace_id, values=None) -> bool:
    return config.workspace_allowed(workspace_id, values)


def admitted(cur, workspace_id, values=None) -> bool:
    if not config.enabled("INTELLIGENCE", values):
        return False
    if config.workspace_allowed(workspace_id, values):
        return True
    return feature_enrollment.admitted(cur, workspace_id, FEATURE, values)


def admission_source(cur, workspace_id, values=None):
    """'reviewed_cohort', 'self_serve' or None — for readiness reason codes only."""
    if not config.enabled("INTELLIGENCE", values):
        return None
    if config.workspace_allowed(workspace_id, values):
        return "reviewed_cohort"
    if feature_enrollment.admitted(cur, workspace_id, FEATURE, values):
        return "self_serve"
    return None
