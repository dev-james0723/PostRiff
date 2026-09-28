"""Executable operation, audience and lifecycle admission. No optimistic defaults."""
from __future__ import annotations

from dataclasses import dataclass
from .contracts import ContractError, KINDS, READINESS, bounded_text, instant, permits, scope, validate_rights


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    operation: str
    version: str
    evidence_kinds: tuple[str, ...]
    endpoint: str
    protocol: str
    credential_class: str
    required_scopes: tuple[str, ...]
    max_items: int
    max_response_bytes: int
    timeout_seconds: int
    max_attempts: int
    billable_unit: str
    deletion_mechanism: str

    def __post_init__(self):
        if any(type(getattr(self, name)) is not int for name in
               ('max_items', 'max_response_bytes', 'timeout_seconds', 'max_attempts')):
            raise ContractError("invalid_capability_limit")
        for name in ("provider_id", "operation", "version", "endpoint", "protocol", "credential_class",
                     "billable_unit", "deletion_mechanism"):
            bounded_text(getattr(self, name), 2048 if name == "endpoint" else 256)
        if not self.evidence_kinds or not set(self.evidence_kinds) <= set(KINDS):
            raise ContractError("invalid_capability_evidence_kind")
        if not 1 <= self.max_items <= 1000 or not 1024 <= self.max_response_bytes <= 4_000_000:
            raise ContractError("invalid_capability_limit")
        if not 1 <= self.timeout_seconds <= 60 or not 1 <= self.max_attempts <= 3:
            raise ContractError("invalid_attempt_limit")


@dataclass(frozen=True)
class SourcePolicy:
    id: str
    version: str
    provider_id: str
    operation: str
    scope_key: str
    rights: dict
    reviewed_by: str
    review_ref: str
    effective_at: str
    expires_at: str
    retention_seconds: int
    readiness: str = "access_pending"
    revoked_at: str | None = None
    verified_scopes: tuple[str, ...] = ()
    price_ref: str | None = None
    approved_attempt_cap_microusd: int | None = None

    def __post_init__(self):
        for value in (self.id, self.version, self.provider_id, self.operation, self.reviewed_by, self.review_ref):
            bounded_text(value)
        scope(self.scope_key); validate_rights(self.rights)
        if self.readiness not in READINESS or instant(self.effective_at) >= instant(self.expires_at):
            raise ContractError("invalid_source_policy")
        if not isinstance(self.retention_seconds, int) or isinstance(self.retention_seconds, bool) or not 1 <= self.retention_seconds <= 366 * 86400:
            raise ContractError("invalid_retention")
        if self.revoked_at:
            instant(self.revoked_at)
        if self.approved_attempt_cap_microusd is not None and (type(self.approved_attempt_cap_microusd) is not int or self.approved_attempt_cap_microusd < 0):
            raise ContractError("invalid_cost_cap")

    def valid(self, at: str) -> bool:
        return (self.readiness == "ready" and self.revoked_at is None
                and instant(self.effective_at) <= instant(at) < instant(self.expires_at))

    def require(self, permission: str, at: str):
        if not self.valid(at) or not permits(self.rights, permission, self.scope_key, at):
            raise ContractError("source_right_not_permitted")


def admit(capability: ProviderCapability, policy: SourcePolicy, *, at: str, requested_scope: str,
          enabled: bool, item_limit: int, byte_limit: int, reservation_microusd: int,
          entitlement_current: bool, billable: bool = True) -> None:
    """Call again immediately before dispatch AND before committing fetched results."""
    if not enabled:
        raise ContractError("provider_operation_disabled")
    if not entitlement_current or requested_scope != policy.scope_key:
        raise ContractError("audience_not_entitled")
    if (capability.provider_id, capability.operation) != (policy.provider_id, policy.operation):
        raise ContractError("policy_operation_mismatch")
    if not set(capability.required_scopes) <= set(policy.verified_scopes):
        raise ContractError("provider_scope_unverified")
    if type(item_limit) is not int or not 1 <= item_limit <= capability.max_items:
        raise ContractError("item_limit_exceeded")
    if type(byte_limit) is not int or not 1 <= byte_limit <= capability.max_response_bytes:
        raise ContractError("byte_limit_exceeded")
    policy.require("retrieve", at)
    if requested_scope.startswith("shared:"):
        policy.require("share_across_workspaces", at)
    if type(reservation_microusd) is not int or reservation_microusd < 0:
        raise ContractError("reservation_required")
    if billable:
        cap = policy.approved_attempt_cap_microusd
        if not policy.price_ref or cap is None or cap <= 0 or not 0 < reservation_microusd <= cap:
            raise ContractError("funded_bounded_operation_required")


def evidence_projection(observation: dict, policy: SourcePolicy, *, at: str, entitled: bool) -> dict | None:
    """Display rights differ from storage/model rights; forbidden text never enters the API payload."""
    if (not entitled or observation["scope_key"] != policy.scope_key or not policy.valid(at)
            or observation["provider_id"] != policy.provider_id
            or observation["source_policy_version"] != policy.version
            or observation["operation"] == "delete" or instant(at) >= instant(observation["retention_until"])):
        return None
    payload = observation["payload"]
    out = {"observation_id": observation["observation_id"], "kind": observation["kind"],
           "provider_id": observation["provider_id"], "platform": payload.get("platform"),
           "event_at": observation["event_at"], "received_at": observation["received_at"],
           "language": payload.get("language", "und"), "display_state": "metadata_only"}
    rights = observation["rights"]
    for permission, source_key, output_key in (("display_excerpt", "text", "excerpt"), ("display_link", "canonical_url", "url")):
        if (permits(rights, permission, policy.scope_key, at)
                and permits(policy.rights, permission, policy.scope_key, at) and payload.get(source_key)):
            out[output_key] = payload[source_key][:800] if source_key == "text" else payload[source_key]
    if "excerpt" in out:
        out["display_state"] = "excerpt_permitted"
    return out
