"""Approval-bound Xiaohongshu image publishing for the local Studio owner."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .studio import StudioError, _no_symlinks, _now


@dataclass(frozen=True)
class _Lease:
    asset_id: str
    expires_at: float
    remaining_reads: int


class XiaohongshuPublishing:
    """A deliberately narrow bridge for one immediate, public image note.

    The body supplied for review is immutable once its receipt is calculated.
    A duplicate idempotency key never resubmits after a transport attempt. Image
    bytes are exposed only through a random, loopback-only, short-lived lease so
    the driver need not receive the Studio browser's authenticated session.
    """

    _BASE_FIELDS = frozenset((
        "account", "rednoteId", "destination", "nativeFormat", "title", "content",
        "assetId", "altText", "tags", "visibility", "scheduledAt", "originality", "products",
    ))
    _SUBMIT_FIELDS = _BASE_FIELDS | frozenset((
        "approvalReceiptHash", "idempotencyKey", "publicationConsent",
    ))

    def __init__(self, store, broker, port: int):
        self.store = store
        self.broker = broker
        self.port = port
        self._leases: dict[str, _Lease] = {}
        self.db_path = self.store.data_dir / "xiaohongshu-publishing.sqlite3"
        with self._connection(write=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS studio_xiaohongshu_publish_attempts ("
                "idempotency_key TEXT PRIMARY KEY, approval_hash TEXT NOT NULL, "
                "state TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    @contextmanager
    def _connection(self, *, write=False):
        """Keep publishing receipts separate from Studio's schema-locked store."""
        _no_symlinks(self.store.data_dir)
        if self.db_path.exists() and self.db_path.is_symlink():
            raise StudioError("xiaohongshu_publish_store_invalid", "The Xiaohongshu publishing receipt store is invalid.", 500)
        descriptor = os.open(
            self.db_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise StudioError("xiaohongshu_publish_store_invalid", "The Xiaohongshu publishing receipt store is invalid.", 500)
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA journal_mode=WAL")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _canonical(value: dict) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _text(cls, value, field, maximum):
        if (not isinstance(value, str) or not value.strip() or len(value) > maximum
                or "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value)):
            raise StudioError("xiaohongshu_publish_manifest_invalid", f"The Xiaohongshu {field} is invalid.", 422)
        return value

    def _normalize(self, supplied: dict) -> dict:
        if not isinstance(supplied, dict) or set(supplied) != self._BASE_FIELDS:
            raise StudioError("xiaohongshu_publish_manifest_invalid", "Review the exact Xiaohongshu image note before publication.", 422)
        account = self._text(supplied["account"], "account", 80)
        rednote_id = self._text(supplied["rednoteId"], "RedNote ID", 20)
        if not rednote_id.isdecimal() or not 5 <= len(rednote_id) <= 20:
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu RedNote ID is invalid.", 422)
        if supplied["destination"] != "public_profile_feed" or supplied["nativeFormat"] != "xiaohongshu.note":
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu destination or native format is invalid.", 422)
        # The pinned RedNote driver rejects a title above 20 characters and a
        # note body above 1,000. Enforce those provider limits before a write.
        title = self._text(supplied["title"], "title", 20)
        content = self._text(supplied["content"], "content", 1_000)
        asset_id = self._text(supplied["assetId"], "asset", 64)
        alt_text = supplied["altText"]
        if not isinstance(alt_text, str) or len(alt_text) > 2_000 or "\x00" in alt_text:
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu image description is invalid.", 422)
        if (supplied["tags"] != [] or supplied["products"] != [] or supplied["scheduledAt"] is not None
                or supplied["visibility"] != "公开可见" or supplied["originality"] is not True):
            raise StudioError(
                "xiaohongshu_publish_manifest_invalid",
                "This bridge supports one immediate, public, original image note with no tags or products.",
                422,
            )
        data, mime = self.store.asset_content(asset_id)
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise StudioError("xiaohongshu_publish_manifest_invalid", "The Xiaohongshu cover must be a supported image.", 422)
        return {
            "account": account, "rednoteId": rednote_id,
            "destination": supplied["destination"], "nativeFormat": supplied["nativeFormat"],
            "title": title, "content": content, "assetId": asset_id,
            "assetSha256": hashlib.sha256(data).hexdigest(), "altText": alt_text,
            "tags": [], "visibility": "公开可见", "scheduledAt": None,
            "originality": True, "products": [],
        }

    @classmethod
    def _receipt(cls, manifest: dict) -> tuple[str, str]:
        approval_hash = "sha256:" + hashlib.sha256(cls._canonical(manifest).encode("utf-8")).hexdigest()
        idempotency_key = hashlib.sha256(("xiaohongshu.publish_image\0" + approval_hash).encode("utf-8")).hexdigest()
        return approval_hash, idempotency_key

    @staticmethod
    def _safe_record(record: dict) -> dict:
        return {
            "state": record["state"], "approvalReceiptHash": record["approvalReceiptHash"],
            "idempotencyKey": record["idempotencyKey"], "updatedAt": record["updatedAt"],
            "verification": record.get("verification", "not_attempted"),
        }

    def review(self, supplied: dict) -> dict:
        manifest = self._normalize(supplied)
        approval_hash, idempotency_key = self._receipt(manifest)
        return {
            "manifest": manifest, "approvalReceiptHash": approval_hash,
            "idempotencyKey": idempotency_key,
            "policy": "exact_publication_approval_required",
        }

    def _assert_connected_identity(self, manifest: dict):
        identity = self.broker.xiaohongshu_identity.status()
        if (identity.get("state") != "identity_connected"
                or identity.get("nickname") != manifest["account"]
                or identity.get("rednoteId") != manifest["rednoteId"]):
            raise StudioError("xiaohongshu_identity_required", "The approved Xiaohongshu identity is not connected.", 409)
        # Recheck the protected session immediately before the external write.
        self.broker.xiaohongshu_mcp.verify_identity(
            expected_rednote_id=manifest["rednoteId"], expected_nickname=manifest["account"],
        )

    def _lease(self, asset_id: str) -> str:
        self.store.asset_content(asset_id)
        now = time.monotonic()
        self._leases = {token: lease for token, lease in self._leases.items() if lease.expires_at > now and lease.remaining_reads > 0}
        token = secrets.token_urlsafe(32)
        self._leases[token] = _Lease(asset_id=asset_id, expires_at=now + 600, remaining_reads=5)
        return f"http://127.0.0.1:{self.port}/api/xiaohongshu-publishing/assets/{token}"

    def asset_content(self, token: str):
        now = time.monotonic()
        lease = self._leases.get(token)
        if lease is None or lease.expires_at <= now or lease.remaining_reads <= 0:
            self._leases.pop(token, None)
            raise StudioError("xiaohongshu_asset_lease_missing", "This temporary Xiaohongshu image lease has expired.", 404)
        remaining = lease.remaining_reads - 1
        if remaining:
            self._leases[token] = _Lease(lease.asset_id, lease.expires_at, remaining)
        else:
            self._leases.pop(token, None)
        return self.store.asset_content(lease.asset_id)

    def _load_attempt(self, idempotency_key: str):
        with self._connection() as db:
            row = db.execute(
                "SELECT approval_hash,state,data,updated_at FROM studio_xiaohongshu_publish_attempts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return {"approvalReceiptHash": row["approval_hash"], "idempotencyKey": idempotency_key,
                "state": row["state"], **json.loads(row["data"]), "updatedAt": row["updated_at"]}

    def _save_attempt(self, approval_hash: str, idempotency_key: str, state: str, *, verification: str):
        record = {"verification": verification}
        now = _now()
        with self._connection(write=True) as db:
            db.execute(
                "INSERT INTO studio_xiaohongshu_publish_attempts VALUES (?,?,?,?,?) "
                "ON CONFLICT(idempotency_key) DO UPDATE SET state=excluded.state,data=excluded.data,updated_at=excluded.updated_at",
                (idempotency_key, approval_hash, state, self._canonical(record), now),
            )
        return {"approvalReceiptHash": approval_hash, "idempotencyKey": idempotency_key,
                "state": state, **record, "updatedAt": now}

    def publish(self, supplied: dict) -> dict:
        if not isinstance(supplied, dict) or set(supplied) != self._SUBMIT_FIELDS or supplied.get("publicationConsent") is not True:
            raise StudioError("exact_publication_approval_required", "Review and approve this exact Xiaohongshu image note, account, visibility and timing.", 422)
        manifest = self._normalize({key: supplied[key] for key in self._BASE_FIELDS})
        approval_hash, idempotency_key = self._receipt(manifest)
        if supplied.get("approvalReceiptHash") != approval_hash or supplied.get("idempotencyKey") != idempotency_key:
            raise StudioError("exact_publication_approval_required", "The Xiaohongshu approval receipt does not match the exact post.", 422)
        existing = self._load_attempt(idempotency_key)
        if existing is not None:
            if existing["approvalReceiptHash"] != approval_hash:
                raise StudioError("idempotency_conflict", "This Xiaohongshu idempotency key belongs to different content.", 409)
            if existing["state"] == "published":
                return {"publication": self._safe_record(existing), "replayed": True}
            if existing["state"] != "failed_pre_submit":
                raise StudioError("xiaohongshu_reconciliation_required", "A Xiaohongshu publish attempt is unresolved. Reconcile the profile before retrying.", 409)
        self._save_attempt(approval_hash, idempotency_key, "preparing", verification="not_attempted")
        try:
            self._assert_connected_identity(manifest)
            image_url = self._lease(manifest["assetId"])
        except StudioError:
            self._save_attempt(approval_hash, idempotency_key, "failed_pre_submit", verification="not_attempted")
            raise
        # Persist an unresolved state before the driver call, so a lost response
        # cannot turn into an accidental duplicate post.
        self._save_attempt(approval_hash, idempotency_key, "submitting", verification="not_attempted")
        try:
            self.broker.xiaohongshu_mcp.publish_image_note({
                "title": manifest["title"], "content": manifest["content"], "images": [image_url],
                "tags": [], "is_original": True, "visibility": "公开可见",
            })
        except StudioError:
            self._save_attempt(approval_hash, idempotency_key, "unresolved", verification="not_confirmed")
            raise
        finally:
            self._leases.pop(image_url.rsplit("/", 1)[-1], None)
        try:
            verified = self.broker.xiaohongshu_mcp.verify_published_title(manifest["title"])
        except StudioError:
            verified = False
        state = "published" if verified else "submitted_unverified"
        verification = "current_user_feed_title_matched" if verified else "provider_accepted_profile_match_pending"
        record = self._save_attempt(approval_hash, idempotency_key, state, verification=verification)
        return {"publication": self._safe_record(record), "replayed": False}

    def publish_approved(self, supplied: dict) -> dict:
        """Convert one visible Studio approval into the immutable server receipt."""
        expected = self._BASE_FIELDS | {"publicationConsent"}
        if not isinstance(supplied, dict) or set(supplied) != expected or supplied.get("publicationConsent") is not True:
            raise StudioError(
                "exact_publication_approval_required",
                "Review and approve this exact Xiaohongshu image note, account, visibility and timing.",
                422,
            )
        review = self.review({key: supplied[key] for key in self._BASE_FIELDS})
        return self.publish({
            **{key: supplied[key] for key in self._BASE_FIELDS},
            "approvalReceiptHash": review["approvalReceiptHash"],
            "idempotencyKey": review["idempotencyKey"],
            "publicationConsent": True,
        })


def register_xiaohongshu_publishing(app, store, broker, body_parser, port: int):
    service = XiaohongshuPublishing(store, broker, port)

    @app.get("/api/xiaohongshu-publishing")
    def status():
        return {"provider": "xiaohongshu", "policy": "exact_publication_approval_required",
                "route": "managed_native_mcp", "imageNotes": True, "scheduling": False,
                "identity": broker.xiaohongshu_status()}

    @app.post("/api/xiaohongshu-publishing/review-image")
    async def review_image(request: Request):
        return await run_in_threadpool(service.review, await body_parser(request))

    @app.post("/api/xiaohongshu-publishing/publish-image")
    async def publish_image(request: Request):
        return await run_in_threadpool(service.publish, await body_parser(request))

    @app.post("/api/xiaohongshu-publishing/publish-approved-image")
    async def publish_approved_image(request: Request):
        return await run_in_threadpool(service.publish_approved, await body_parser(request))

    @app.get("/api/xiaohongshu-publishing/assets/{token}")
    def leased_asset(token: str):
        data, mime = service.asset_content(token)
        return Response(data, media_type=mime, headers={
            "Cache-Control": "no-store", "Cross-Origin-Resource-Policy": "cross-origin",
        })

    return service
