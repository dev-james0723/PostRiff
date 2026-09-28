"""Network-specific licensed import boundary; aggregates never fabricate post records."""
from __future__ import annotations

from ..contracts import ContractError, canonical, validate_observation
from ..policy import admit
from .base import Batch


def import_batch(rows, *, capability, policy, at, enabled, entitlement_current, reservation_microusd,
                 provider_revision, terminal_page=False):
    admit(capability, policy, at=at, requested_scope=policy.scope_key, enabled=enabled,
          item_limit=max(1, len(rows)), byte_limit=len(canonical(rows).encode("utf-8")),
          reservation_microusd=reservation_microusd, entitlement_current=entitlement_current,
          billable=capability.billable_unit != "authorized_offline_export")
    observations = []
    for row in rows:
        parsed = validate_observation(row)
        if (parsed["scope_key"] != policy.scope_key or parsed["provider_id"] != capability.provider_id
                or parsed["provider_contract_version"] != capability.version
                or parsed["source_policy_version"] != policy.version or parsed["kind"] not in capability.evidence_kinds):
            raise ContractError("licensed_domain_or_capability_mismatch")
        observations.append(parsed)
    return Batch(tuple(observations), {"provider_revision": provider_revision},
                 "complete_within_scope" if terminal_page else "partial", terminal_page=terminal_page,
                 cost_microusd=None)
