"""Permitted corroboration through the existing ResearchBroker, never social counts."""
from __future__ import annotations

from ..contracts import ContractError, digest, permits
from ..policy import ProviderCapability, SourcePolicy, admit
from .base import Batch, observation, safe_url

VERSION = "existing-research-broker-v1"
CAPABILITY = ProviderCapability("web", "corroborate", VERSION, ("search_lead",), "existing:ResearchBroker.search_items",
                                "existing-provider-contract", "existing-account", (), 6, 400_000, 30, 1,
                                "existing_research_request", "source-retention/refresh/revocation")


def collect(*, broker, query: str, policy: SourcePolicy, enabled: bool, entitlement_current: bool,
            received_at: str, available_at: str, coverage_epoch: str, reservation_microusd: int,
            workspace_consent: bool, scope_context: dict, resolve_urls: bool = True) -> Batch:
    if not workspace_consent or not policy.scope_key.startswith("workspace:"):
        raise ContractError("workspace_research_consent_required")
    if not isinstance(scope_context, dict) or scope_context.get('workspace_id') != policy.scope_key[10:]:
        raise ContractError('workspace_scope_mismatch')
    if not isinstance(query, str) or not 1 <= len(query) <= 300 or any(ord(c) < 32 for c in query):
        raise ContractError("invalid_query")
    admit(CAPABILITY, policy, at=received_at, requested_scope=policy.scope_key, enabled=enabled,
          item_limit=6, byte_limit=400_000, reservation_microusd=reservation_microusd,
          entitlement_current=entitlement_current)
    # The existing broker remains the owner of consent, routing and usage behavior.
    result = broker.search_items(query, scope_context)
    if not isinstance(result, dict):
        raise ContractError('invalid_web_response')
    if result.get("status") not in ("ok", "partial"):
        return Batch(health="unavailable", completeness="gap", reason_code="web_corroboration_unavailable")
    items = result.get('items', [])
    if not isinstance(items, list) or len(items) > 6 or any(not isinstance(item, dict) for item in items):
        raise ContractError('invalid_web_items')
    observations, quarantine = [], []
    for index, item in enumerate(items):
        try:
            url = safe_url(item.get("url", ""), resolve=resolve_urls)
            prov = item.get("provenance") or {}
            payload = {"platform": "web", "canonical_url": url, "query_digest": digest(query),
                       "represented_scope": "search_index_leads", "title": str(item.get("title", ""))[:300]}
            if permits(policy.rights, "store_raw", policy.scope_key, available_at):
                payload["text"] = str(item.get("snippet", item.get("text", "")))[:800]
            rows = observation(policy=policy, source_identity=url, revision_identity=digest([received_at, payload]),
                               sequence=int(__import__('datetime').datetime.fromisoformat(received_at.replace('Z','+00:00')).timestamp()*1_000_000),
                               kind="search_lead", operation="create", payload=payload, event_at=None,
                               received_at=received_at, available_at=available_at, coverage_epoch=coverage_epoch,
                               contract_version=VERSION, access_method="existing_public_web_research")
            rows["provenance"]["injection_flags"] = [x.get("rule") for x in prov.get("injectionFlags", []) if isinstance(x, dict)]
            observations.append(rows)
        except ContractError as exc:
            quarantine.append({"index": index, "reason_code": exc.code})
    return Batch(tuple(observations), completeness="partial", reason_code="search_index_is_not_social_population",
                 cost_microusd=None, quarantined=tuple(quarantine))
