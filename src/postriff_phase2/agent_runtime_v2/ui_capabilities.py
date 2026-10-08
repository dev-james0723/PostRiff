"""Lane D — server-created capability manifest (spec §6.1). Built from explicit per-journey allowlists filtered by ToolSpec
tenant/effect; never by iterating the global tool registry.

Frozen entry points:
- build_manifest(cur, auth, projection, *, scope='workspace') -> dict (server record incl. SERVER_ONLY_MANIFEST_KEYS)
- query_binding(manifest, name) -> dict | None ; action_binding(manifest, action_id) -> dict | None
- current(cur, auth, manifest) -> dict  (re-check permission revision / expiry before every query, action, refresh, replay)
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def build_manifest(cur, auth, projection, *, scope='workspace'):  # lane D
    _not_ready('build_manifest')


def query_binding(manifest, name):  # lane D
    _not_ready('query_binding')


def action_binding(manifest, action_id):  # lane D
    _not_ready('action_binding')


def current(cur, auth, manifest):  # lane D
    _not_ready('current')
