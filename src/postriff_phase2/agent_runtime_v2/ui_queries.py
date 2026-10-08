"""Lane D — authorized, bounded, read-only queries (spec §6.2; G05/G06/G18).

Frozen entry points:
- query_ui_binding(cur, auth, artifact, manifest, request) -> dict UiQueryResultV1 (re-authorized; read-only even if a write
  name is requested; unknown -> denied, never zero)
- query_http(runtime, workspace_id, token, request) -> dict
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def query_ui_binding(cur, auth, artifact, manifest, request):  # lane D
    _not_ready('query_ui_binding')


def query_http(runtime, workspace_id, token, request):  # lane D
    _not_ready('query_http')
