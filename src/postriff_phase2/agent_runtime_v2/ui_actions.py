"""Lane D — the one guarded action dispatcher (spec §6.3; G06-G09).

Frozen entry points:
- activate_ui_action(cur, auth, artifact, manifest, request) -> dict UiActivationV1 (60 s, single use, input-digest bound, native
  confirmation copy from the server)
- execute_ui_action(cur, auth, artifact, manifest, request) -> dict UiActionResultV1 (activation + durable idempotency in
  pr_ui_actions in the same transaction as the original domain command; re-read; verified only from executor + re-read)
- activate_http(runtime, workspace_id, token, request) -> dict ; execute_http(runtime, workspace_id, token, request) -> dict
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def activate_ui_action(cur, auth, artifact, manifest, request):  # lane D
    _not_ready('activate_ui_action')


def execute_ui_action(cur, auth, artifact, manifest, request):  # lane D
    _not_ready('execute_ui_action')


def activate_http(runtime, workspace_id, token, request):  # lane D
    _not_ready('activate_http')


def execute_http(runtime, workspace_id, token, request):  # lane D
    _not_ready('execute_http')
