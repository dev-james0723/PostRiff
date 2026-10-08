"""Rafii Intelligent Library: one permission-aware service for search, understanding, organization, voice, task
source packs and quiet suggestions (package docs/design/rafii-intelligent-library-2026-10-08).

UI routes, Agent tools, the OpenUI task adapter and background work all call these modules; none keeps its own SQL
or source-policy interpretation. Postgres stays the authority; the existing private object store keeps bytes.
"""
from __future__ import annotations


class LibraryIntelligence:
    """Mounted on HostedWorkspaceService as `library_intelligence`."""

    def __init__(self, service, providers=None):
        self.service = service
        self._providers = providers

    @property
    def providers(self):
        if self._providers is None:
            from .providers import Providers
            self._providers = Providers()
        return self._providers

    def route(self, method, workspace_id, rest, query, body_reader, token):
        from .http import dispatch
        return dispatch(self.service, method, workspace_id, rest, query, body_reader, token)

    def tick(self, connect, *, max_jobs: int = 4, max_seconds: float = 20.0) -> dict:
        """Cron entry: bounded capability jobs, collection reconciliation and suggestion evaluation."""
        from . import jobs
        result = {"jobs": jobs.tick(self, connect, max_jobs=max_jobs, max_seconds=max_seconds)}
        try:
            from . import collections
            result["collections"] = collections.reconcile_due(self, connect)
        except (ImportError, AttributeError):
            result["collections"] = {"status": "unavailable"}
        try:
            from . import suggestions
            result["suggestions"] = suggestions.evaluate_due(self, connect)
        except (ImportError, AttributeError):
            result["suggestions"] = {"status": "unavailable"}
        return result
