"""Relevant Opportunity Brief (PRD R-BRF-01/02): a small weekly decision brief from stored evidence only.

Behind ``RAFII_OPPORTUNITY_BRIEF_ENABLED`` (default off: every route answers 404 ``feature_disabled`` and the cron
step does nothing). The flag is read like every coworker flag: the hosted app's isolated environment, true only for
1/true/yes/on.
"""
from __future__ import annotations

FLAG = "RAFII_OPPORTUNITY_BRIEF_ENABLED"


def enabled(values=None):
    from ..coworker import flags
    return flags._truthy(flags._source(values).get(FLAG, ""))


def require(values=None):
    if not enabled(values):
        from postriff_alpha.domain import AlphaError
        raise AlphaError("This Rafii feature isn’t turned on yet.", 404, code="feature_disabled")
