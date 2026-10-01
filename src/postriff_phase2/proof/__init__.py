"""Growth Loop proof v2 and the next-week strategy loop (PRD R-PROOF-01/02).

Behind ``RAFII_PROOF_V2_ENABLED`` (default off: routes answer 404 ``feature_disabled``, the cron step does nothing,
and Weekly planning ignores strategy decisions exactly as before). The flag is read like every coworker flag: the
hosted app's isolated environment, true only for 1/true/yes/on.
"""
from __future__ import annotations

FLAG = "RAFII_PROOF_V2_ENABLED"


def enabled(values=None):
    from ..coworker import flags
    return flags._truthy(flags._source(values).get(FLAG, ""))


def require(values=None):
    if not enabled(values):
        from postriff_alpha.domain import AlphaError
        raise AlphaError("This Rafii feature isn’t turned on yet.", 404, code="feature_disabled")
