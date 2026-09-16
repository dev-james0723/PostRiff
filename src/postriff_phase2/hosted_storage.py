"""Private Supabase Storage boundary for decoded Phase 2 media.

The service key is held by this server-side adapter and is never returned in a
descriptor, state snapshot, object URL, or error. Browser uploads are absent.
"""
import base64
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from postriff_alpha.domain import AlphaError
from .media import decode_upload


UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
OBJECT = re.compile(r"[0-9a-f]{32}-[0-9a-f]{64}\.jpg")


class SupabaseStorage:
    def __init__(self, project_url, secret_key, *, bucket="postriff-private", send=None):
        parsed = urlparse(project_url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.path not in ("", "/"):
            raise ValueError("An exact Supabase project URL is required.")
        if not isinstance(secret_key, str) or len(secret_key) < 20:
            raise ValueError("A server-only Supabase secret key is required.")
        if not re.fullmatch(r"[a-z0-9-]{3,63}", bucket):
            raise ValueError("Use a valid private bucket name.")
        self.project_url = project_url.rstrip("/")
        self.secret_key = secret_key
        self.bucket = bucket
        self.send = send or self._send

    def _send(self, method, url, headers, body):
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
                data = response.read(9 * 1024 * 1024)
                if len(data) > 8 * 1024 * 1024:
                    raise AlphaError("Storage response exceeded the safe size limit.", 502)
                return response.status, dict(response.headers), data
        except HTTPError as error:
            error.read(65536)
            return error.code, dict(error.headers), b""
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error

    def _path(self, workspace_id, category, object_name):
        if not UUID.fullmatch(str(workspace_id)) or category not in ("media", "artwork") or not OBJECT.fullmatch(object_name):
            raise AlphaError("Invalid private object location.")
        return f"{workspace_id}/{category}/{object_name}"

    def _headers(self, content_type=None):
        headers = {"Authorization": "Bearer " + self.secret_key, "apikey": self.secret_key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def put_immutable(self, workspace_id, category, object_name, raw, content_type="image/jpeg"):
        path = self._path(workspace_id, category, object_name)
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 8 * 1024 * 1024:
            raise AlphaError("Decoded media is missing or too large.")
        url = f"{self.project_url}/storage/v1/object/{quote(self.bucket)}/{quote(path, safe='/')}"
        headers = self._headers(content_type)
        headers["x-upsert"] = "false"
        status, _, _ = self.send("POST", url, headers, raw)
        if status == 409:
            raise AlphaError("This immutable object already exists.", 409)
        if status not in (200, 201):
            raise AlphaError("Private storage rejected the decoded media.", 502)
        return path

    def get(self, workspace_id, category, object_name):
        path = self._path(workspace_id, category, object_name)
        url = f"{self.project_url}/storage/v1/object/{quote(self.bucket)}/{quote(path, safe='/')}"
        status, _, body = self.send("GET", url, self._headers(), None)
        if status == 404:
            raise AlphaError("This private media object is unavailable.", 404)
        if status != 200:
            raise AlphaError("Private storage could not read this object.", 502)
        return body

    def delete(self, workspace_id, category, object_name):
        path = self._path(workspace_id, category, object_name)
        url = f"{self.project_url}/storage/v1/object/{quote(self.bucket)}/{quote(path, safe='/')}"
        status, _, _ = self.send("DELETE", url, self._headers(), None)
        if status not in (200, 204, 404):
            raise AlphaError("Private storage could not delete this object.", 502)

    def signed_url(self, workspace_id, category, object_name, expires_in=300):
        if type(expires_in) is not int or not 60 <= expires_in <= 600:
            raise AlphaError("Use a short-lived media delivery window.")
        path = self._path(workspace_id, category, object_name)
        url = f"{self.project_url}/storage/v1/object/sign/{quote(self.bucket)}/{quote(path, safe='/')}"
        status, _, body = self.send("POST", url, self._headers("application/json"), json.dumps({"expiresIn": expires_in}).encode())
        try:
            signed = json.loads(body).get("signedURL") if status == 200 else None
        except (ValueError, TypeError):
            signed = None
        if not isinstance(signed, str) or not signed.startswith("/storage/v1/object/sign/"):
            raise AlphaError("Private storage did not create a safe delivery URL.", 502)
        return self.project_url + signed


class PrivateAssetService:
    """Decode first, then store an immutable rendition and return metadata only."""
    def __init__(self, storage):
        self.storage = storage

    def stage_upload(self, workspace_id, payload):
        # Vercel's Python runtime does not guarantee ffmpeg binaries. Pillow is
        # pinned for the hosted function and still performs a full decode.
        asset = decode_upload(payload, decoder="pillow")
        raw = base64.b64decode(asset.pop("data"), validate=True)
        object_name = f"{asset['id']}-{asset['hash']}.jpg"
        path = self.storage.put_immutable(workspace_id, "media", object_name, raw)
        asset.update({"storagePath": path, "objectName": object_name, "execution": "hosted-private-storage"})
        return asset

    def remove(self, workspace_id, asset):
        object_name = asset.get("objectName")
        if object_name:
            self.storage.delete(workspace_id, "media", object_name)
