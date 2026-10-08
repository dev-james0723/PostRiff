"""Lane F — artifact storage, CAS revisions, leases, private replay events and UI state (02-CONTRACTS §3, §5; migration 102).

Frozen entry points:
- create_or_resume_artifact(cur, auth, parent_run_id, slot, idempotency_key, *, surface, manifest, projection, kind='generate',
  retry_of=None, lease_owner) -> dict ArtifactLease {artifact, attempt, created, replay_cursor}. Same key -> same attempt; one live
  producer per (artifact, target revision) via the partial unique index; also records body.agent.uiArtifacts on the message.
- append_event(conn_or_cur, artifact_id, attempt_id, revision, kind, payload) -> dict (allocates monotonic seq)
- checkpoint(conn_or_cur, attempt_id, source, *, lease_owner) -> None   (outside the workspace lock; lease-owner checked)
- commit_ui_revision(cur, auth, patch, validation) -> dict UiArtifactV1 (atomic CAS on baseRevision/baseSourceHash)
- finish_attempt(cur, attempt_id, state, reason=None, usage=None) -> None
- persist_ui_state(cur, auth, artifact_id, expected_state_revision, patch) -> dict (declared persistable fields only)
- snapshot_http(runtime, workspace_id, token, artifact_id) -> dict {artifact, manifest(public), revisions?}
- by_message_http(runtime, workspace_id, token, message_id) -> dict {artifacts: [...]}
- persist_state_http(runtime, workspace_id, token, artifact_id, request) -> dict
- events_after(cur, auth, artifact_id, after, limit) -> list[dict]
- selection_context(cur, auth, ui_context) -> dict | None  (stable selection/order for follow-up turns)
- reap_expired(cur, workspace_id, now) -> int  (interrupted leases; unknown usage stays held)
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError


def _not_ready(name):
    raise AlphaError("Interactive views are still being prepared here.", 503, code="ui_not_ready")


def create_or_resume_artifact(cur, auth, parent_run_id, slot, idempotency_key, *, surface, manifest, projection, kind='generate', retry_of=None, lease_owner):  # lane F
    _not_ready('create_or_resume_artifact')


def append_event(conn_or_cur, artifact_id, attempt_id, revision, kind, payload):  # lane F
    _not_ready('append_event')


def checkpoint(conn_or_cur, attempt_id, source, *, lease_owner):  # lane F
    _not_ready('checkpoint')


def commit_ui_revision(cur, auth, patch, validation):  # lane F
    _not_ready('commit_ui_revision')


def finish_attempt(cur, attempt_id, state, reason=None, usage=None):  # lane F
    _not_ready('finish_attempt')


def persist_ui_state(cur, auth, artifact_id, expected_state_revision, patch):  # lane F
    _not_ready('persist_ui_state')


def snapshot_http(runtime, workspace_id, token, artifact_id):  # lane F
    _not_ready('snapshot_http')


def by_message_http(runtime, workspace_id, token, message_id):  # lane F
    _not_ready('by_message_http')


def persist_state_http(runtime, workspace_id, token, artifact_id, request):  # lane F
    _not_ready('persist_state_http')


def events_after(cur, auth, artifact_id, after, limit):  # lane F
    _not_ready('events_after')


def selection_context(cur, auth, ui_context):  # lane F
    _not_ready('selection_context')


def reap_expired(cur, workspace_id, now):  # lane F
    _not_ready('reap_expired')
