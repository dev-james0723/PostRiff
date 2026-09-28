"""Bounded frontier generation. Private seeds never become shared query material."""
from __future__ import annotations

import re
from dataclasses import dataclass
from .contracts import ContractError, digest, instant, scope

ROUTES = ("watch", "keyword_independent_sample", "phrase_burst", "entity", "hashtag", "community",
          "platform_seed", "related_topic", "cross_platform", "corroboration", "refresh")


@dataclass(frozen=True)
class DiscoveryRequest:
    scope_key: str
    provider_id: str
    route: str
    query: str
    coverage_epoch: str
    policy_version: str
    window_start: str
    window_end: str
    language: str = "und"
    community: str | None = None
    depth: int = 0
    parent_id: str | None = None
    sampling_probability: float | None = None

    def __post_init__(self):
        scope(self.scope_key)
        if self.route not in ROUTES or not 0 <= self.depth <= 2:
            raise ContractError("invalid_discovery_route")
        if not isinstance(self.query, str) or len(self.query) > 300 or any(ord(c) < 32 for c in self.query):
            raise ContractError("invalid_discovery_query")
        if re.search(r"(?:https?://|[<>;`]|\b(?:password|authorization|cookie):)", self.query, re.I):
            raise ContractError("query_operator_not_allowed")
        if instant(self.window_start) >= instant(self.window_end):
            raise ContractError("invalid_discovery_window")
        if self.sampling_probability is not None and not 0 < self.sampling_probability <= 1:
            raise ContractError("invalid_sampling_probability")

    @property
    def id(self):
        return digest(self.__dict__)


def children(parent: DiscoveryRequest, candidates: list[str]) -> list[DiscoveryRequest]:
    if parent.depth >= 2:
        return []
    result, seen = [], set()
    for query in candidates:
        key = " ".join(query.split()) if isinstance(query, str) else ""
        if not key or key.casefold() in seen:
            continue
        seen.add(key.casefold())
        request = DiscoveryRequest(**{**parent.__dict__, "query": key, "route": "related_topic",
                                      "depth": parent.depth + 1, "parent_id": parent.id})
        result.append(request)
        if len(result) == 5:
            break
    return result


def exploration(*, scope_key: str, provider_id: str, policy_version: str, coverage_epoch: str,
                window_start: str, window_end: str) -> DiscoveryRequest:
    """Independent of every workspace watch keyword; permitted public sample discovers new conversations."""
    return DiscoveryRequest(scope_key, provider_id, "keyword_independent_sample", "", coverage_epoch,
                            policy_version, window_start, window_end)


def allocation(budget_units: int, *, deletion_units: int = 0, required_watch_units: int = 0) -> dict:
    if any(type(v) is not int or v < 0 for v in (budget_units, deletion_units, required_watch_units)):
        raise ContractError("invalid_frontier_budget")
    deletion = min(budget_units, deletion_units)
    remaining = budget_units - deletion
    watch = min(remaining, max(required_watch_units, remaining * 60 // 100))
    corroboration = min(remaining - watch, remaining * 15 // 100)
    explore = remaining - watch - corroboration
    return {"method": "frontier-allocation-candidate-1", "deletion": deletion, "watch": watch,
            "corroboration": corroboration, "exploration": explore,
            "coverage_reduced": watch < required_watch_units or explore == 0}
