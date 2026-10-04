"""Private Supabase Storage boundary for decoded Phase 2 media and verified chat videos.

The service key is held by this server-side adapter and is never returned in a
descriptor, state snapshot, object URL, or error. Every request goes to the
configured project host through an opener that never follows a redirect, because
CPython's redirect handler would forward the key (chat-context SPEC §7.4). Browser
video uploads use a signed URL; approved video publishing reads the exact object
through a separately bounded server-side path.
"""
import base64
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from postriff_alpha.domain import AlphaError
from .media import decode_upload


UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
OBJECT = re.compile(r"[0-9a-f]{32}-[0-9a-f]{64}\.jpg")
VIDEO_OBJECT = re.compile(r"[0-9a-f]{32}\.(mp4|mov)")
MAX_BODY = 8 * 1024 * 1024
MAX_VIDEO_BODY = 100_000_000
LIST_PAGE = 100
LIST_PAGES = 200


class _NoRedirect(HTTPRedirectHandler):
    """A 30x surfaces as an HTTPError with its own status; nothing is re-sent anywhere."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def storage_opener(context=None):
    return build_opener(_NoRedirect(), HTTPSHandler(context=context or ssl.create_default_context()))


class SupabaseStorage:
    def __init__(self, project_url, secret_key, *, bucket="postriff-private", video_bucket="postriff-video", file_bucket="postriff-library", send=None, opener=None):
        parsed = urlparse(project_url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.path not in ("", "/"):
            raise ValueError("An exact Supabase project URL is required.")
        if not isinstance(secret_key, str) or len(secret_key) < 20:
            raise ValueError("A server-only Supabase secret key is required.")
        if not re.fullmatch(r"[a-z0-9-]{3,63}", bucket) or not re.fullmatch(r"[a-z0-9-]{3,63}", video_bucket) or not re.fullmatch(r"[a-z0-9-]{3,63}", file_bucket):
            raise ValueError("Use a valid private bucket name.")
        self.project_url = project_url.rstrip("/")
        self.host = parsed.hostname
        self.secret_key = secret_key
        self.bucket = bucket
        self.video_bucket = video_bucket
        self.file_bucket = file_bucket
        self.opener = opener or storage_opener()
        self.send = send or self._send

    def _open(self, method, url, headers, body, *, timeout=20):
        if urlparse(url).scheme != "https" or urlparse(url).hostname != self.host:
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        return self.opener.open(Request(url, data=body, headers=headers, method=method), timeout=timeout)

    def _send(self, method, url, headers, body):
        try:
            with self._open(method, url, headers, body) as response:
                data = response.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    raise AlphaError("Storage response exceeded the safe size limit.", 502)
                return response.status, dict(response.headers), data
        except HTTPError as error:
            error.read(65536)
            if 300 <= error.code < 400:
                raise AlphaError("Private storage answered from an unexpected location.", 502) from None
            return error.code, dict(error.headers), b""
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error

    def _bucket(self, category):
        if category == "video": return self.video_bucket
        if category == "file": return self.file_bucket
        return self.bucket

    def _path(self, workspace_id, category, object_name):
        pattern = VIDEO_OBJECT if category == "video" else FILE_OBJECT if category == "file" else OBJECT if category in ("media", "artwork") else None
        if not UUID.fullmatch(str(workspace_id)) or pattern is None or not isinstance(object_name, str) or not pattern.fullmatch(object_name):
            raise AlphaError("Invalid private object location.")
        return f"{workspace_id}/{category}/{object_name}"

    def _object_url(self, category, path):
        return f"{self.project_url}/storage/v1/object/{quote(self._bucket(category))}/{quote(path, safe='/')}"

    def _headers(self, content_type=None):
        headers = {"Authorization": "Bearer " + self.secret_key, "apikey": self.secret_key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def put_immutable(self, workspace_id, category, object_name, raw, content_type="image/jpeg"):
        if category == "video":
            raise AlphaError("Invalid private object location.")   # videos arrive only through a signed upload
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
        if category == "video":
            raise AlphaError("Invalid private object location.")   # the generic image route stays capped at 8 MB
        path = self._path(workspace_id, category, object_name)
        url = self._object_url(category, path)
        status, _, body = self.send("GET", url, self._headers(), None)
        if status == 404:
            raise AlphaError("This private media object is unavailable.", 404)
        if status != 200:
            raise AlphaError("Private storage could not read this object.", 502)
        return body

    def get_verified_video(self, workspace_id, object_name, *, expected_bytes, expected_mime, expected_etag):
        """Read one approved video for a publisher, with an exact HEAD/GET identity and a hard 100 MB cap."""
        if (type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_VIDEO_BODY
                or expected_mime not in ("video/mp4", "video/quicktime")
                or not isinstance(expected_etag, str) or not expected_etag or len(expected_etag) > 200):
            raise AlphaError("Approved video metadata is invalid.", 409, code="video_manifest_invalid")
        path = self._path(workspace_id, "video", object_name)
        info = self.object_info(workspace_id, "video", object_name)
        if (info["bytes"], info["mime"], info["etag"]) != (expected_bytes, expected_mime, expected_etag):
            raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
        url = self._object_url("video", path)
        try:
            response = self._open("GET", url, self._headers(), None, timeout=120)
        except HTTPError as error:
            error.close()
            raise AlphaError("Private storage could not read the approved video.", 502) from None
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error
        try:
            headers = {k.lower(): v for k, v in response.headers.items()}
            content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
            length = headers.get("content-length")
            if (response.status != 200 or content_type != expected_mime
                    or (length is not None and length != str(expected_bytes))
                    or (headers.get("etag") is not None and headers["etag"] != expected_etag)):
                raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
            raw = response.read(expected_bytes + 1)
            if len(raw) != expected_bytes:
                raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
            return raw
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error
        finally:
            response.close()

    def iter_verified_video(self, workspace_id, object_name, *, expected_bytes, expected_mime, expected_etag,
                            chunk_size=5 * 1024 * 1024):
        """Stream an immutable approved video with fixed memory use and exact metadata checks."""
        if (type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_VIDEO_BODY
                or expected_mime not in ("video/mp4", "video/quicktime")
                or not isinstance(expected_etag, str) or not expected_etag or len(expected_etag) > 200
                or type(chunk_size) is not int or not 1 <= chunk_size <= 5 * 1024 * 1024):
            raise AlphaError("Approved video metadata is invalid.", 409, code="video_manifest_invalid")
        path = self._path(workspace_id, "video", object_name)
        info = self.object_info(workspace_id, "video", object_name)
        if (info["bytes"], info["mime"], info["etag"]) != (expected_bytes, expected_mime, expected_etag):
            raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")

        def chunks():
            try:
                response = self._open("GET", self._object_url("video", path), self._headers(), None, timeout=120)
            except HTTPError as error:
                error.close()
                raise AlphaError("Private storage could not read the approved video.", 502) from None
            except (URLError, TimeoutError, OSError) as error:
                raise AlphaError("Private storage is temporarily unavailable.", 503) from error
            try:
                headers = {k.lower(): v for k, v in response.headers.items()}
                mime = (headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                if (response.status != 200 or mime != expected_mime
                        or (headers.get("content-length") is not None and headers["content-length"] != str(expected_bytes))
                        or (headers.get("etag") is not None and headers["etag"] != expected_etag)):
                    raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
                remaining = expected_bytes
                while remaining:
                    piece = response.read(min(chunk_size, remaining))
                    if not piece:
                        raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
                    remaining -= len(piece)
                    yield piece
                if response.read(1):
                    raise AlphaError("Approved video changed or is unavailable.", 409, code="video_changed")
            except (URLError, TimeoutError, OSError) as error:
                raise AlphaError("Private storage is temporarily unavailable.", 503) from error
            finally:
                response.close()

        return chunks()

    def delete(self, workspace_id, category, object_name):
        path = self._path(workspace_id, category, object_name)
        url = self._object_url(category, path)
        status, _, _ = self.send("DELETE", url, self._headers(), None)
        if status not in (200, 204, 404):
            raise AlphaError("Private storage could not delete this object.", 502)

    def signed_url(self, workspace_id, category, object_name, expires_in=300):
        if type(expires_in) is not int or not 60 <= expires_in <= 600:
            raise AlphaError("Use a short-lived media delivery window.")
        path = self._path(workspace_id, category, object_name)
        url = f"{self.project_url}/storage/v1/object/sign/{quote(self._bucket(category))}/{quote(path, safe='/')}"
        status, _, body = self.send("POST", url, self._headers("application/json"), json.dumps({"expiresIn": expires_in}).encode())
        try:
            signed = json.loads(body).get("signedURL") if status == 200 else None
        except (ValueError, TypeError, AttributeError):
            signed = None
        # Storage returns a path relative to /storage/v1; older fixtures include that prefix.
        if isinstance(signed, str) and signed.startswith("/storage/v1/object/sign/"):
            signed = signed[len("/storage/v1"):]
        expected = f"/object/sign/{quote(self._bucket(category))}/{quote(path, safe='/')}?"
        try:
            tokens = parse_qs(urlparse(signed).query).get("token", []) if isinstance(signed, str) else []
        except ValueError:
            tokens = []
        if not isinstance(signed, str) or not signed.startswith(expected) or "#" in signed or len(tokens) != 1 or not tokens[0]:
            raise AlphaError("Private storage did not create a safe delivery URL.", 502)
        return self.project_url + "/storage/v1" + signed

    # --- chat videos (SPEC §7.3, §7.4) ------------------------------------------------------------------

    def signed_upload_url(self, workspace_id, category, object_name):
        """A single-object upload URL for the browser's PUT. No `x-upsert`: an existing object can't be replaced."""
        path = self._path(workspace_id, category, object_name)
        bucket = self._bucket(category)
        url = f"{self.project_url}/storage/v1/object/upload/sign/{quote(bucket)}/{quote(path, safe='/')}"
        status, _, body = self.send("POST", url, self._headers("application/json"), b"{}")
        try:
            signed = json.loads(body).get("url") if status == 200 else None
        except (ValueError, TypeError, AttributeError):
            signed = None
        expected = f"/object/upload/sign/{quote(bucket)}/{quote(path, safe='/')}?"
        if isinstance(signed, str) and signed.startswith("/storage/v1" + expected):
            signed = signed[len("/storage/v1"):]
        if not isinstance(signed, str) or not signed.startswith(expected) or "token=" not in signed or "#" in signed:
            raise AlphaError("Private storage did not create a safe upload URL.", 502)
        return f"{self.project_url}/storage/v1{signed}"

    def object_info(self, workspace_id, category, object_name):
        path = self._path(workspace_id, category, object_name)
        status, headers, _ = self.send("HEAD", self._object_url(category, path), self._headers(), None)
        if status == 404 or status == 400:
            raise AlphaError("This private media object is unavailable.", 404)
        if status != 200:
            raise AlphaError("Private storage could not read this object.", 502)
        found = {k.lower(): v for k, v in (headers or {}).items()}
        try:
            size = int(found.get("content-length"))
        except (TypeError, ValueError):
            size = None
        return {"bytes": size, "mime": (found.get("content-type") or "").split(";")[0].strip().lower() or None, "etag": found.get("etag")}

    def read_range(self, workspace_id, category, object_name, start, length):
        """At most `length` bytes from `start`, read with the no-redirect opener and closed early even when storage
        ignores Range and answers 200 (then `ranged` is False)."""
        if type(start) is not int or type(length) is not int or start < 0 or not 1 <= length <= MAX_BODY:
            raise AlphaError("Invalid private object range.")
        path = self._path(workspace_id, category, object_name)
        headers = {**self._headers(), "Range": f"bytes={start}-{start + length - 1}"}
        try:
            response = self._open("GET", self._object_url(category, path), headers, None)
        except HTTPError as error:
            error.close()
            if error.code == 404 or error.code == 400:
                raise AlphaError("This private media object is unavailable.", 404) from None
            if error.code == 416:
                return {"data": b"", "ranged": True}
            raise AlphaError("Private storage could not read this object.", 502) from None
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error
        try:
            ranged = response.status == 206
            if response.status not in (200, 206):
                raise AlphaError("Private storage could not read this object.", 502)
            data = response.read(length) if ranged or start == 0 else b""
            return {"data": data[:length], "ranged": ranged}
        finally:
            response.close()

    def get_bounded(self, workspace_id, category, object_name, max_bytes=MAX_FILE_BODY):
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_FILE_BODY:
            raise AlphaError("Invalid private object read limit.")
        path = self._path(workspace_id, category, object_name)
        try:
            response = self._open("GET", self._object_url(category, path), self._headers(), None, timeout=120)
        except HTTPError as error:
            error.close()
            if error.code in (400, 404): raise AlphaError("This private file object is unavailable.", 404) from None
            raise AlphaError("Private storage could not read this file.", 502) from None
        except (URLError, TimeoutError, OSError) as error:
            raise AlphaError("Private storage is temporarily unavailable.", 503) from error
        try:
            if response.status != 200: raise AlphaError("Private storage could not read this file.", 502)
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes: raise AlphaError("Private file exceeded the safe size limit.", 413)
            return data
        finally:
            response.close()

    def bucket_info(self, bucket=None):
        name = bucket or self.video_bucket
        status, _, body = self.send("GET", f"{self.project_url}/storage/v1/bucket/{quote(name)}", self._headers(), None)
        if status in (400, 404):
            return None
        if status != 200:
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        try:
            found = json.loads(body)
        except (ValueError, TypeError):
            raise AlphaError("Private storage is temporarily unavailable.", 503) from None
        if not isinstance(found, dict):
            raise AlphaError("Private storage is temporarily unavailable.", 503)
        return {"id": found.get("id") or found.get("name"), "public": found.get("public") is True,
                "fileSizeLimit": found.get("file_size_limit"), "allowedMimeTypes": list(found.get("allowed_mime_types") or [])}

    def list_prefix(self, prefix, bucket=None):
        """Every object name under `{workspace}/{category}/` (paginated, bounded)."""
        parts = str(prefix).strip("/").split("/")
        if not UUID.fullmatch(parts[0]) or len(parts) > 2 or (len(parts) == 2 and parts[1] not in ("media", "artwork", "video", "file")):
            raise AlphaError("Invalid private object location.")
        folder = "/".join(parts)
        name = bucket or (self.video_bucket if parts[-1] == "video" else self.file_bucket if parts[-1] == "file" else self.bucket)
        found = []
        for page in range(LIST_PAGES):
            body = json.dumps({"prefix": folder, "limit": LIST_PAGE, "offset": page * LIST_PAGE, "sortBy": {"column": "name", "order": "asc"}}).encode()
            status, _, raw = self.send("POST", f"{self.project_url}/storage/v1/object/list/{quote(name)}", self._headers("application/json"), body)
            if status != 200:
                raise AlphaError("Private storage is temporarily unavailable.", 503)
            try:
                items = json.loads(raw)
            except (ValueError, TypeError):
                raise AlphaError("Private storage is temporarily unavailable.", 503) from None
            if not isinstance(items, list):
                raise AlphaError("Private storage is temporarily unavailable.", 503)
            found += [f"{folder}/{item['name']}" for item in items if isinstance(item, dict) and isinstance(item.get("name"), str) and "/" not in item["name"]]
            if len(items) < LIST_PAGE:
                return found
        raise AlphaError("Private storage listing is too large.", 503)


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
        """Kind-aware: a video removes its video object, then its poster and frames (media category). 404 is success."""
        from .asset_kinds import kind_of
        object_name = asset.get("objectName")
        if kind_of(asset) == "video":
            if object_name:
                self.storage.delete(workspace_id, "video", object_name)
            images = [asset.get("poster")] + list(asset.get("frames") or [])
            for name in dict.fromkeys(i.get("objectName") for i in images if isinstance(i, dict) and i.get("objectName")):
                self.storage.delete(workspace_id, "media", name)
        elif object_name:
            self.storage.delete(workspace_id, "media", object_name)
