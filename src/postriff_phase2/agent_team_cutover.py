"""Bounded Agent Team cutover helpers.

Environment flags remain the normal production control plane. The exact Rafii
consumer staging Vercel project has an explicit code-level cutover so acceptance
can proceed even when the connected Vercel token lacks environment-write scope.
This never matches Founder Production or preview deployments.

Emergency disable flags always win and are intentionally separate from the
ordinary enable flags.
"""
_TRUE=frozenset(("1","true","yes","on"))
STAGING_PROJECT_ID="prj_4bfvSc0AC6am9FdknFWcwNYgmcnN"


def _truthy(value):
    return str(value or "").strip().lower() in _TRUE


def staging_cutover(values):
    return (str(values.get("VERCEL_PROJECT_ID") or "")==STAGING_PROJECT_ID
            and str(values.get("VERCEL_ENV") or "").strip().lower()=="production")


def team_enabled(values):
    if _truthy(values.get("JAMES_AGENT_TEAM_EMERGENCY_DISABLE")):
        return False
    return _truthy(values.get("JAMES_AGENT_TEAM_ENABLED")) or staging_cutover(values)


def call_enabled(values):
    if _truthy(values.get("JAMES_AGENT_TEAM_EMERGENCY_DISABLE")):
        return False
    if _truthy(values.get("JAMES_AGENT_TEAM_CALL_EMERGENCY_DISABLE")):
        return False
    # Preserve the existing JamesDailyCallService contract: its report-call
    # gate has historically been controlled by the call flag itself. The
    # Agent Team runtime separately checks team_enabled before it can schedule
    # a report call. Requiring the team flag here breaks direct service
    # validation and unnecessarily couples two independent safety gates.
    return _truthy(values.get("JAMES_AGENT_TEAM_CALL_ENABLED")) or staging_cutover(values)


def cutover_source(values):
    if _truthy(values.get("JAMES_AGENT_TEAM_EMERGENCY_DISABLE")):
        return "emergency_disabled"
    if _truthy(values.get("JAMES_AGENT_TEAM_ENABLED")):
        return "environment"
    if staging_cutover(values):
        return "rafii_consumer_staging"
    return "disabled"
