"""Offline, operation-scoped provider policy for revision 14."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_hash
from .contracts import validate_contract


@dataclass(frozen=True)
class CapabilityDecision:
    provider_id: str
    operation: str
    decision: str
    reason: str
    record_hash: str


class ProviderRegistry:
    def __init__(self, records: list[dict[str, object]], registry_version: str):
        self.registry_version = registry_version
        self._providers: dict[str, dict[str, object]] = {}
        for candidate in records:
            record = validate_contract("source_acquisition_provider", candidate)
            provider_id = str(record["provider_id"])
            if provider_id in self._providers:
                raise ValueError(f"duplicate_provider_id:{provider_id}")
            self._providers[provider_id] = record

    @classmethod
    def from_file(cls, path: Path) -> "ProviderRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
            raise ValueError("invalid_provider_registry")
        version = payload.get("registry_version")
        if not isinstance(version, str) or not version:
            raise ValueError("missing_registry_version")
        return cls(payload["providers"], version)

    def get(self, provider_id: str) -> dict[str, object]:
        return copy.deepcopy(self._providers[provider_id])

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def evaluate(
        self, provider_id: str, operation: str, mode: str = "dry_run"
    ) -> CapabilityDecision:
        if mode not in {"dry_run", "execute"}:
            return CapabilityDecision(provider_id, operation, "denied", "invalid_mode", "")
        record = self._providers.get(provider_id)
        if record is None:
            return CapabilityDecision(provider_id, operation, "denied", "unknown_provider", "")
        record_hash = canonical_hash(record)
        allowed = record["allowed_operations"]
        denied = record["denied_operations"]
        if operation in denied or operation not in allowed:  # type: ignore[operator]
            decision, reason = "denied", "operation_not_allowlisted"
        elif record["provider_state"] == "reference_only":
            decision, reason = "denied", "provider_reference_only"
        elif mode != "dry_run":
            decision = "phase0_execution_disabled"
            reason = "phase0_has_zero_provider_execution"
        else:
            decision, reason = "dry_run_only", "fixture_simulation_permitted"
        return CapabilityDecision(provider_id, operation, decision, reason, record_hash)
