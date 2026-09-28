"""One trend capability registry. Publishing identity is never discovery entitlement."""
from __future__ import annotations

from dataclasses import asdict
from ..contracts import ContractError
from ..policy import ProviderCapability, SourcePolicy

# This catalogue documents admission gaps; it is not a list of active providers.
CATALOGUE = {
    "bluesky": {"operations": ["live_sample", "archive_replay"], "kinds": ["raw_post"],
                "blocker": "Operation-specific host/policy review; archive replay additionally needs metered access and cap."},
    "mastodon": {"operations": ["public_timeline"], "kinds": ["raw_post"],
                 "blocker": "An explicit instance, its rules, access and deletion/refresh policy must be admitted."},
    "web": {"operations": ["corroborate"], "kinds": ["search_lead"],
            "blocker": "Workspace consent, existing account capacity, excerpt rights and bounded budget required."},
    "x": {"operations": ["recent_search", "filtered_stream", "hydrate"], "kinds": ["raw_post", "aggregate_metric"],
          "blocker": "Official operation entitlement, current prices, funded cap and retention contract required."},
    "threads": {"operations": ["keyword_search", "owned_read"], "kinds": ["raw_post", "owned_post"],
                "blocker": "App review, verified scopes and actual returned fields/quotas required."},
    "youtube": {"operations": ["search_references", "display_metrics", "approved_derivatives"], "kinds": ["search_lead", "aggregate_metric"],
                "blocker": "Each operation needs policy mapping; proposed derivatives need applicable audited-use-case approval."},
    "reddit": {"operations": ["licensed_discovery"], "kinds": ["raw_post", "aggregate_metric"],
               "blocker": "Written commercial data permission or network-specific licensed contract required."},
    "tiktok": {"operations": ["licensed_discovery", "authorized_owned_read", "permitted_trend_seeds"],
               "kinds": ["aggregate_metric", "owned_post", "trend_seed"],
               "blocker": "Commercial/owned operation rights required; Research API is excluded from this product."},
    "instagram": {"operations": ["hashtag_discovery", "owned_read", "licensed_discovery"],
                  "kinds": ["raw_post", "owned_post", "aggregate_metric"],
                  "blocker": "Operation-specific Meta scopes/app review or licensed network rights required."},
    "linkedin": {"operations": ["owned_read", "licensed_discovery", "web_lead"],
                 "kinds": ["owned_post", "aggregate_metric", "search_lead"],
                 "blocker": "Owned/org scope does not grant general discovery; contract-specific storage and export rights required."},
    "google_trends": {"operations": ["permitted_trending_seed", "alpha_series"], "kinds": ["trend_seed", "aggregate_metric"],
                      "blocker": "Public seed permission or alpha entitlement and normalized-series comparability required."},
    "licensed": {"operations": ["contract_export"], "kinds": ["raw_post", "aggregate_metric"],
                 "blocker": "Contract must grant network/operation/customer/territory/processing/export rights independently."},
}


class ProviderRegistry:
    def __init__(self):
        self._entries = {}

    def register(self, capability: ProviderCapability, policy: SourcePolicy, adapter):
        if (capability.provider_id, capability.operation) != (policy.provider_id, policy.operation):
            raise ContractError("registry_policy_mismatch")
        key = (capability.provider_id, capability.operation, policy.scope_key, policy.version)
        if key in self._entries:
            raise ContractError("immutable_provider_registration")
        self._entries[key] = (capability, policy, adapter)

    def resolve(self, provider, operation, scope_key, policy_version, *, at):
        value = self._entries.get((provider, operation, scope_key, policy_version))
        if not value or not value[1].valid(at):
            raise ContractError("provider_operation_unavailable")
        return value

    def diagnostics(self, *, at, scope_key):
        result = []
        for provider, spec in CATALOGUE.items():
            for operation in spec["operations"]:
                entries = [v for k, v in self._entries.items() if k[:3] == (provider, operation, scope_key)]
                active = next((v for v in entries if v[1].valid(at)), None)
                result.append({"provider_id": provider, "operation": operation,
                               "readiness": active[1].readiness if active else "not_configured",
                               "evidence_kinds": list(active[0].evidence_kinds) if active else spec["kinds"],
                               "live_verification": "not_run", "limitations": [] if active else [spec["blocker"]]})
        return result
