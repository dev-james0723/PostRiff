"""Lane B — real presentation streaming over the existing WSGI app (02-CONTRACTS §3-4; transport-deploy map §7.1).

Frozen entry points (called by ui_http; signatures fixed by A):
- create_presentation(runtime, environ, start_response, workspace_id, token, request) -> WSGI iterable (text/event-stream).
  One short ui_transaction claims/resumes the lease via ui_store.create_or_resume_artifact, reserves via ui_metering inside the
  combined turn budget and persists `queued`; then streams UiEventV1 frames (contracts.sse_frame) from ui_presenter in a worker
  thread; checkpoints through ui_store; finalizes (ui_validator.validate_and_merge_ui -> ui_store.commit_ui_revision -> settle)
  before `ui.ready`. A duplicate idempotency key attaches to the existing attempt (replay) and never dispatches again.
- replay(runtime, environ, start_response, workspace_id, token, artifact_id, after) -> WSGI iterable: authorized bounded replay
  + live tail of the existing attempt (heartbeats, <= BOUNDS.replayTailSeconds); never starts a provider call.
- cancel_http(runtime, workspace_id, token, artifact_id) -> dict: cancel presentation only, settle once, keep the business result.
- create_edit(runtime, environ, start_response, workspace_id, token, artifact_id, request) -> WSGI iterable: explicit semantic edit,
  a new bounded metered attempt on (baseRevision, baseSourceHash); stale base -> 409 conflict before any spend.
- probe(runtime, environ, start_response, workspace_id, token) -> WSGI iterable: authenticated, zero-model G04 probe (three frames
  ~1.5 s apart, one multi-byte UTF-8 character split across two writes, server monotonic timestamps).
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def create_presentation(runtime, environ, start_response, workspace_id, token, request):  # lane B
    _not_ready('create_presentation')


def replay(runtime, environ, start_response, workspace_id, token, artifact_id, after):  # lane B
    _not_ready('replay')


def cancel_http(runtime, workspace_id, token, artifact_id):  # lane B
    _not_ready('cancel_http')


def create_edit(runtime, environ, start_response, workspace_id, token, artifact_id, request):  # lane B
    _not_ready('create_edit')


def probe(runtime, environ, start_response, workspace_id, token):  # lane B
    _not_ready('probe')
