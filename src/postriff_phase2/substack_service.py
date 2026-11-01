"""Workspace-owned Substack editorial workflow and public feeds.

State, consent decisions and the manual queue share the existing PostgreSQL
workspace transaction, revision and audit boundary. Nothing here is a provider
publish operation or an assertion of publication ownership. No provider secrets
are collected until an official, usable authorization contract is established.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

from postriff_alpha.domain import AlphaError
from .api_tokens import is_api_token
from .permissions import require
from .substack import build_manual_handoff, fetch_public_feed, get_substack_capabilities, validate_publication_url

MAX_CONNECTIONS = 50
MAX_DRAFTS = 200
MAX_TOTAL_BODY_BYTES = 2_000_000
CONTENT_TYPES = frozenset({"article", "note", "podcast", "video"})
AUDIENCES = frozenset({"everyone", "free", "paid"})
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HASH = re.compile(r"^[a-f0-9]{64}$")


def _iso(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")


def _state(state):
    section = state.setdefault("substack", {"version": 1, "connections": [], "drafts": [], "queue": []})
    if not isinstance(section, dict) or section.get("version") != 1:
        raise AlphaError("Substack workspace data needs an update.", 503, code="substack_state_unavailable")
    for key in ("connections", "drafts", "queue"):
        if not isinstance(section.get(key), list):
            raise AlphaError("Substack workspace data needs an update.", 503, code="substack_state_unavailable")
    return section


def _item(items, item_id, kind):
    if not isinstance(item_id, str):
        raise AlphaError(f"Substack {kind} unavailable.", 404, code="substack_item_unavailable")
    item = next((value for value in items if value.get("id") == item_id), None)
    if item is None:
        raise AlphaError(f"Substack {kind} unavailable.", 404, code="substack_item_unavailable")
    return item


def _connection(section, connection_id):
    connection = _item(section["connections"], connection_id, "publication")
    if connection.get("status") != "feed_added" or connection.get("mode") != "public_feed":
        raise AlphaError("Add or reconnect this public feed before using it.", 409, code="substack_connection_inactive")
    # Revalidate stored data before any egress or destination-sensitive action.
    validate_publication_url(connection.get("publicationUrl"))
    return connection


def _content_hash(draft, connection):
    bound = {key: draft.get(key) for key in ("connectionId", "title", "body", "format", "contentType", "audience", "scheduledFor")}
    bound.update(publicationUrl=connection["publicationUrl"], mode=connection["mode"])
    return hashlib.sha256(json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _checked_hash(payload, expected):
    value = payload.get("contentHash")
    if not isinstance(value, str) or not _HASH.fullmatch(value) or value != expected:
        raise AlphaError("The draft or destination changed. Review the current version.", 409, code="substack_approval_stale")


def _cancel_jobs(section, draft_id, now):
    for job in section["queue"]:
        if job.get("draftId") == draft_id and job.get("status") != "canceled":
            job.update(status="canceled", canceledAt=_iso(now))


def _schedule(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise AlphaError("Choose a target handoff time with a timezone.", code="invalid_substack_schedule")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone required")
        return _iso(dt.timestamp())
    except (ValueError, OverflowError, OSError) as error:
        raise AlphaError("Choose a target handoff time with a timezone.", code="invalid_substack_schedule") from error


class HostedSubstackService:
    def __init__(self, repository, *, enabled=False, clock=time.time, feed_fetcher=None):
        self.repository = repository
        self.enabled = enabled is True
        self.clock = clock
        self.feed_fetcher = feed_fetcher or fetch_public_feed

    def _enabled(self):
        if not self.enabled:
            raise AlphaError("Substack integration is not enabled.", 404, code="feature_disabled")

    def _authorize(self, workspace_id, token, scope=None):
        """Direct service callers get the same API-token floor as HTTP callers.

        The repository locks and revalidates the live token in the transaction;
        scopes are immutable after issuance. Agent transaction authz is inherited
        from PostgresWorkspaceRepository, including consent revocation checks.
        """
        self._enabled()
        if is_api_token(token):
            if scope is None:
                raise AlphaError("Use an interactive session for this Substack decision.", 403, code="token_scope_denied")
            grant = self.repository.api_tokens.resolve(token, workspace_id)
            if scope not in grant["scopes"]:
                raise AlphaError("This token does not have the required scope.", 403, code="token_scope_denied")

    def _projection(self, saved):
        section = _state(copy.deepcopy(saved["state"]))
        # Queue readiness is derived from the persisted target and current time.
        # No scheduler can turn these manual jobs into provider send jobs.
        queue = copy.deepcopy(section["queue"])
        for job in queue:
            if job.get("status") == "pending_manual":
                target = job.get("scheduledFor")
                job["due"] = target is None or datetime.fromisoformat(target.replace("Z", "+00:00")).timestamp() <= self.clock()
        return {"revision": saved["revision"], "connections": section["connections"], "drafts": section["drafts"],
                "queue": queue, "capabilities": get_substack_capabilities(), "enabled": self.enabled,
                "membership": saved.get("membership", {})}

    def workspace(self, workspace_id, token):
        self._authorize(workspace_id, token, "read")
        return self._projection(self.repository.get(workspace_id, token))

    def capabilities(self, workspace_id, token):
        return self.workspace(workspace_id, token)

    def _command(self, workspace_id, token, payload, command, *, permission, event, subject, meta=None, scope=None):
        self._authorize(workspace_id, token, scope)
        if not isinstance(payload, dict):
            raise AlphaError("Send a structured Substack action.")
        def guarded(state, principal):
            if state.get("workspace", {}).get("sample"):
                raise AlphaError("Choose your own workspace before changing Substack data.", 403, code="sample_workspace")
            return command(state, principal)
        saved = self.repository.command(
            workspace_id, token, payload.get("expectedRevision"), guarded, requirement=permission,
            audit_event=lambda state: (event, subject(state) if callable(subject) else subject, meta(state) if callable(meta) else (meta or {})),
        )
        return self._projection(saved)

    def connect(self, workspace_id, token, payload):
        def command(state, principal):
            mode = payload.get("mode", "public_feed")
            if mode != "public_feed":
                if mode not in ("official_mcp_analytics", "official_authorized", "official_partnership"):
                    raise AlphaError("Choose a supported Substack connection method.", code="invalid_substack_mode")
                raise AlphaError("Official authorization for this connection method is not enabled for Rafii.", 409, code="requires_official_approval")
            if payload.get("confirmed") is not True:
                raise AlphaError("Confirm you are adding a public feed, without account authentication or ownership verification.", 403, code="substack_consent_required")
            target = validate_publication_url(payload.get("publicationUrl"))
            section = _state(state)
            existing = next((value for value in section["connections"] if value["publicationUrl"] == target["publication_url"]), None)
            if existing is not None:
                existing.update(status="feed_added", reconnectedAt=_iso(self.clock()), feedConsentAt=_iso(self.clock()),
                                feedConsentVersion=1, health="not_checked", lastCheckedAt=None)
                return state
            if len(section["connections"]) >= MAX_CONNECTIONS:
                raise AlphaError("This workspace has reached its Substack feed limit.", 409, code="substack_capacity")
            section["connections"].append({
                "id": "sc_" + uuid.uuid4().hex, "mode": "public_feed", "publicationUrl": target["publication_url"],
                "feedUrl": target["feed_url"], "status": "feed_added", "ownershipVerified": False,
                "accountAuthenticated": False, "analyticsConnected": False, "publishingAuthorized": False,
                "createdAt": _iso(self.clock()), "feedConsentAt": _iso(self.clock()), "feedConsentVersion": 1,
                "lastCheckedAt": None, "health": "not_checked",
            })
            return state

        return self._command(workspace_id, token, payload, command, permission="manage_connections", event="substack.feed_added",
                             subject="public_feed", meta={"mode": "public_feed", "accountAuthenticated": False, "consentVersion": 1})

    def disconnect(self, workspace_id, token, connection_id, payload):
        def command(state, principal):
            section, now = _state(state), self.clock()
            connection = _item(section["connections"], connection_id, "publication")
            connection.update(status="disconnected", disconnectedAt=_iso(now), health="disconnected")
            for draft in section["drafts"]:
                if draft["connectionId"] == connection_id:
                    draft.update(approvedHash=None, approvedAt=None, updatedAt=_iso(now))
                    if draft["status"] != "canceled":
                        draft["status"] = "draft"
                    _cancel_jobs(section, draft["id"], now)
            return state

        return self._command(workspace_id, token, payload, command, permission="manage_connections", event="substack.feed_disconnected", subject=connection_id,
                             meta={"mode": "public_feed", "credentialsRevoked": False})

    def save_draft(self, workspace_id, token, payload, draft_id=None):
        saved_id = []

        def command(state, principal):
            section, now = _state(state), self.clock()
            current = _item(section["drafts"], draft_id, "draft") if draft_id is not None else None
            connection = _connection(section, payload.get("connectionId", current.get("connectionId") if current else None))
            fields = {}
            for name, default, limit in (("title", "", 300), ("body", "", 200000)):
                value = payload.get(name, current.get(name, default) if current else default)
                if not isinstance(value, str) or len(value) > limit or _CONTROL.search(value):
                    raise AlphaError(f"Substack draft {name} is invalid or too long.", code="invalid_substack_draft")
                if name == "title" and any(char in value for char in "\r\n\t"):
                    raise AlphaError("Keep the Substack draft title on one line.", code="invalid_substack_draft")
                try:
                    value.encode("utf-8", errors="strict")
                except UnicodeEncodeError as error:
                    raise AlphaError("The draft contains invalid text characters.", code="invalid_substack_draft") from error
                fields[name] = value.strip() if name == "title" else value
            if not fields["title"] and not fields["body"].strip():
                raise AlphaError("Add a title or draft text.", code="invalid_substack_draft")
            for name, default, choices in (("format", "markdown", {"markdown"}), ("contentType", "article", CONTENT_TYPES), ("audience", "everyone", AUDIENCES)):
                value = payload.get(name, current.get(name, default) if current else default)
                if not isinstance(value, str) or value not in choices:
                    raise AlphaError("Choose supported Substack draft options.", code="invalid_substack_draft")
                fields[name] = value
            fields["scheduledFor"] = _schedule(payload.get("scheduledFor", current.get("scheduledFor") if current else None))
            fields["connectionId"] = connection["id"]
            total = sum(len(value.get("body", "").encode()) for value in section["drafts"] if value.get("id") != draft_id)
            if total + len(fields["body"].encode()) > MAX_TOTAL_BODY_BYTES:
                raise AlphaError("Export or delete older Substack drafts before adding more content.", 409, code="substack_capacity")
            digest = _content_hash(fields, connection)
            if current is None:
                if len(section["drafts"]) >= MAX_DRAFTS:
                    raise AlphaError("This workspace has reached its Substack draft limit.", 409, code="substack_capacity")
                current = {"id": "sd_" + uuid.uuid4().hex, "createdAt": _iso(now), "approvedHash": None, "approvedAt": None, "status": "draft"}
                section["drafts"].append(current)
            elif digest != current.get("contentHash") or current.get("status") == "canceled":
                current.update(approvedHash=None, approvedAt=None, status="draft")
                _cancel_jobs(section, current["id"], now)
            current.update(fields, contentHash=digest, updatedAt=_iso(now))
            saved_id.append(current["id"])
            return state

        return self._command(workspace_id, token, payload, command, permission="edit", event="substack.draft_saved", subject=lambda state: saved_id[0],
                             meta=lambda state: {"contentHash": _item(_state(state)["drafts"], saved_id[0], "draft")["contentHash"]}, scope="draft")

    def approve(self, workspace_id, token, draft_id, payload):
        def command(state, principal):
            section, now = _state(state), self.clock()
            draft = _item(section["drafts"], draft_id, "draft")
            connection = _connection(section, draft["connectionId"])
            if payload.get("confirmed") is not True:
                raise AlphaError("Confirm this exact draft and destination for manual handoff.", 403, code="substack_consent_required")
            _checked_hash(payload, _content_hash(draft, connection))
            if draft["status"] == "canceled":
                raise AlphaError("Save this draft again before approving it.", 409, code="substack_draft_canceled")
            # Incomplete editorial drafts may be saved, but never enter the
            # approved queue until their exact payload can actually be exported.
            build_manual_handoff(connection["publicationUrl"], draft)
            draft.update(approvedHash=draft["contentHash"], approvedAt=_iso(now), updatedAt=_iso(now))
            if draft["status"] != "handoff_ready":
                draft["status"] = "approved"
            # One durable manual job per draft/content/destination; no provider jobs.
            key = hashlib.sha256((draft_id + ":" + draft["contentHash"]).encode()).hexdigest()
            job = next((value for value in section["queue"] if value["idempotencyKey"] == key), None)
            if job is None:
                # Keep only this draft's current job; history belongs in append-only audit.
                section["queue"] = [value for value in section["queue"] if value["draftId"] != draft_id]
                section["queue"].append({"id": "sq_" + uuid.uuid4().hex, "kind": "manual_handoff", "draftId": draft_id,
                    "connectionId": connection["id"], "contentHash": draft["contentHash"], "idempotencyKey": key,
                    "scheduledFor": draft["scheduledFor"], "status": "pending_manual", "createdAt": _iso(now), "autoPublished": False})
            elif job["status"] == "canceled":
                job.update(status="pending_manual", scheduledFor=draft["scheduledFor"], approvedAt=_iso(now))
                job.pop("canceledAt", None)
            return state

        return self._command(workspace_id, token, payload, command, permission="approve", event="substack.draft_approved", subject=draft_id,
                             meta=lambda state: {"contentHash": _item(_state(state)["drafts"], draft_id, "draft")["contentHash"], "purpose": "manual_handoff"})

    def handoff(self, workspace_id, token, draft_id, payload):
        receipt = []

        def command(state, principal):
            section, now = _state(state), self.clock()
            draft = _item(section["drafts"], draft_id, "draft")
            connection = _connection(section, draft["connectionId"])
            current_hash = _content_hash(draft, connection)
            _checked_hash(payload, current_hash)
            if draft.get("approvedHash") != current_hash or draft.get("status") not in ("approved", "handoff_ready"):
                raise AlphaError("An authorized reviewer must approve this draft and destination first.", 409, code="substack_approval_required")
            key = hashlib.sha256((draft_id + ":" + current_hash).encode()).hexdigest()
            job = next((value for value in section["queue"] if value["idempotencyKey"] == key and value["status"] != "canceled"), None)
            if job is None:
                raise AlphaError("The manual handoff approval is no longer active.", 409, code="substack_approval_required")
            ready = build_manual_handoff(connection["publicationUrl"], draft)
            ready.update(contentHash=current_hash, receiptId=job["id"], autoPublished=False)
            receipt.append(ready)
            draft.update(status="handoff_ready", updatedAt=_iso(now))
            job.update(status="handoff_prepared", handoffPreparedAt=job.get("handoffPreparedAt") or _iso(now), autoPublished=False)
            return state

        result = self._command(workspace_id, token, payload, command, permission="approve", event="substack.handoff_prepared", subject=draft_id,
                               meta=lambda state: {"contentHash": _item(_state(state)["drafts"], draft_id, "draft")["contentHash"], "autoPublished": False})
        return {**result, "handoff": receipt[0]}

    def cancel(self, workspace_id, token, draft_id, payload):
        def command(state, principal):
            section, now = _state(state), self.clock()
            draft = _item(section["drafts"], draft_id, "draft")
            _checked_hash(payload, draft["contentHash"])
            draft.update(status="canceled", approvedHash=None, approvedAt=None, updatedAt=_iso(now))
            _cancel_jobs(section, draft_id, now)
            return state

        return self._command(workspace_id, token, payload, command, permission="approve", event="substack.draft_canceled", subject=draft_id)

    def delete_draft(self, workspace_id, token, draft_id, payload):
        def command(state, principal):
            section = _state(state)
            draft = _item(section["drafts"], draft_id, "draft")
            if draft.get("status") not in ("draft", "canceled"):
                raise AlphaError("Cancel the approval before deleting this draft.", 409, code="substack_cancel_required")
            _checked_hash(payload, draft["contentHash"])
            section["drafts"] = [value for value in section["drafts"] if value["id"] != draft_id]
            section["queue"] = [value for value in section["queue"] if value["draftId"] != draft_id]
            return state

        return self._command(workspace_id, token, payload, command, permission="edit", event="substack.draft_deleted", subject=draft_id)

    def refresh(self, workspace_id, token, connection_id, payload):
        """Authenticate and rate limit before egress; fetch outside the DB lock.

        Public excerpts are returned to the requesting member, never persisted in
        the workspace. A disconnect, revision change or lost membership during
        the network call prevents delivery of the result and health mutation.
        """
        from .hosted import _membership, audit, throttle
        self._authorize(workspace_id, token)
        if not isinstance(payload, dict):
            raise AlphaError("Send a structured Substack action.")
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(_membership(row), "read")
            if type(payload.get("expectedRevision")) is not int or payload["expectedRevision"] != row[0]:
                raise AlphaError("Workspace changed; reload.", 409, code="workspace_revision_conflict")
            state = json.loads(row[1]) if isinstance(row[1], str) else copy.deepcopy(row[1])
            if state.get("workspace", {}).get("sample"):
                raise AlphaError("Choose your own workspace before refreshing Substack feeds.", 403, code="sample_workspace")
            connection = _connection(_state(state), connection_id)
            if connection.get("feedConsentVersion") != 1:
                raise AlphaError("Confirm this public feed again before refreshing it.", 403, code="substack_consent_required")
            target = connection["publicationUrl"]
            throttle(cur, "substack.feed_refresh:" + str(workspace_id), 10, 60)
            audit(cur, workspace_id, principal, "substack.feed_refresh_requested", connection_id, {"mode": "public_feed"})
        try:
            feed = self.feed_fetcher(target)
        except AlphaError as error:
            # Provider error text may contain untrusted content. Keep a stable,
            # content-free failure code; do not relay payloads or credential data.
            with self.repository.transaction(token, workspace_id) as (cur, _, principal):
                audit(cur, workspace_id, principal, "substack.feed_refresh_failed", connection_id, {"code": "public_feed_unavailable"})
            raise AlphaError("This public feed could not be refreshed. Try again later.", 503, code="substack_feed_unavailable") from error

        def command(state, principal):
            current = _connection(_state(state), connection_id)
            if current["publicationUrl"] != target:
                raise AlphaError("The publication changed. Reload before refreshing.", 409, code="workspace_revision_conflict")
            current.update(lastCheckedAt=_iso(self.clock()), health="public_feed_reachable")
            return state

        result = self._command(workspace_id, token, payload, command, permission="read", event="substack.feed_refreshed", subject=connection_id,
                               meta={"mode": "public_feed"})
        return {**result, "feed": {**feed, "connectionId": connection_id, "fetchedAt": _iso(self.clock())}}
