"""Trend switches use the existing coworker flag registry and preview isolation."""
from __future__ import annotations

from ...coworker import flags
from .contracts import uuid

NAMES = ("INTELLIGENCE", "TRUST_RECEIPTS", "CALIBRATION", "RADAR", "STAGE_CLAIMS", "MODEL_ENRICHMENT",
         "NOTIFICATIONS", "PROVIDER_OPERATIONS", "GRAPH_GENOME", "SATURATION", "WHITESPACE", "OPPORTUNITY_LAB",
         "MULTIMODAL", "FORECASTS")
FLAG_NAMES = tuple("RAFII_TREND_" + name + "_ENABLED" for name in NAMES)
EGRESS_FLAGS = tuple("RAFII_TREND_" + name + "_ENABLED" for name in
                     ("PROVIDER_OPERATIONS", "MODEL_ENRICHMENT", "NOTIFICATIONS", "MULTIMODAL"))


def enabled(name: str, values=None) -> bool:
    if name not in NAMES:
        raise KeyError(name)
    return flags.enabled("RAFII_TREND_" + name + "_ENABLED", values)


def workspace_allowed(workspace_id: str, values=None) -> bool:
    """Empty allowlist is nobody. No implicit wildcard production rollout."""
    try:
        workspace_id = uuid(workspace_id)
        source = flags._source(values)
        allowed = {uuid(part.strip()) for part in str(source.get("RAFII_TREND_WORKSPACE_ALLOWLIST", "")).split(",") if part.strip()}
        return enabled("INTELLIGENCE", source) and workspace_id in allowed
    except ValueError:
        return False


def dispatch_allowed(provider_id: str, operation: str, values=None) -> bool:
    source = flags._source(values)
    operations = set(str(source.get("RAFII_TREND_ALLOWED_OPERATIONS", "")).split(","))
    return (all(enabled(name, source) for name in ("INTELLIGENCE", "RADAR", "PROVIDER_OPERATIONS"))
            and f"{provider_id}:{operation}" in operations)


def stage_allowed(*, verification_state: str, cohort_qualified: bool, method_state: str, values=None) -> bool:
    return (all(enabled(name, values) for name in ("INTELLIGENCE", "TRUST_RECEIPTS", "STAGE_CLAIMS"))
            and verification_state == "verified" and cohort_qualified is True and method_state == "production")
