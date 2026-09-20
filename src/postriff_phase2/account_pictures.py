"""Connected accounts' profile pictures, kept so post previews can draw the account the way its app does.

The picture URL comes from the identity response each adapter already reads at connect and re-verify
(providers.py). It is downloaded from the provider's own image host only (HTTPS, no redirects, bounded),
fully decoded, cropped to a square and re-encoded as a small JPEG without metadata, then stored beside the
connection (migration 012). Disconnect deletes it. A picture that cannot be fetched or decoded is simply
absent, and previews fall back to a lettered avatar.
"""
import hashlib
import io
import ssl
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from postriff_alpha.domain import AlphaError
from .providers import _NoRedirect

# Where LinkedIn (userinfo `picture`), Threads and Instagram (Graph `…profile_picture_url`) serve pictures.
PICTURE_HOSTS = ("media.licdn.com", ".fbcdn.net", ".cdninstagram.com")
MAX_DOWNLOAD = 2 * 1024 * 1024
SIDE = 200


def fetch_image(url):
    """Bounded HTTPS GET: 10 s timeout, no redirects, 2 MB cap. Returns (status, content type, bytes)."""
    request = Request(url, headers={"Accept": "image/jpeg,image/png,image/webp"}, method="GET")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=10, context=ssl.create_default_context()) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(MAX_DOWNLOAD + 1)
    except HTTPError as error:
        return error.code, "", b""
    except (URLError, TimeoutError, OSError, AlphaError):
        return 0, "", b""


def allowed_url(url):
    if not isinstance(url, str) or len(url) > 4096:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
        and any(host == allowed or (allowed.startswith(".") and host.endswith(allowed)) for allowed in PICTURE_HOSTS)
    )


def square_jpeg(raw):
    """Decode fully and re-encode as a SIDE x SIDE JPEG without metadata; None when it is not a usable picture."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                return None
            width, height = image.size
            if not 32 <= width <= 4096 or not 32 <= height <= 4096:
                return None
            image.load()  # full decode: truncated or corrupt input fails here
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "P") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                image = flat
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(image, (SIDE, SIDE), method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def picture_from_identity(identity, fetch=fetch_image):
    """("absent", None) when the provider reports no usable picture URL, ("unavailable", None) when it could not be
    fetched or decoded this time, ("ok", (jpeg, sha256)) otherwise."""
    url = identity.get("pictureUrl") if isinstance(identity, dict) else None
    if not allowed_url(url):
        return "absent", None
    status, content_type, raw = fetch(url)
    kind = (content_type or "").split(";")[0].strip().lower()
    if status != 200 or not raw or len(raw) > MAX_DOWNLOAD or not kind.startswith("image/"):
        return "unavailable", None
    jpeg = square_jpeg(raw)
    if not jpeg:
        return "unavailable", None
    return "ok", (jpeg, hashlib.sha256(jpeg).hexdigest())


def guarded(cur, action, *args):
    """Run a picture read or write inside a savepoint. Pictures only decorate previews, so a fault here (say the
    table is not migrated yet) never fails the connection, disconnect or channel list around it."""
    mark = "picture_" + uuid.uuid4().hex[:8]
    cur.execute(f"SAVEPOINT {mark}")
    try:
        result = action(cur, *args)
    except Exception:  # noqa: BLE001 - see docstring
        cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
        return None
    cur.execute(f"RELEASE SAVEPOINT {mark}")
    return result


def store(cur, workspace_id, connection_id, outcome):
    """Apply a `picture_from_identity` result: replace, remove when the account has none, keep on a failed fetch."""
    status, picture = outcome
    if status == "ok":
        jpeg, digest = picture
        cur.execute(
            "INSERT INTO public.pr_channel_pictures(workspace_id,connection_id,picture,digest) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(workspace_id,connection_id) DO UPDATE SET picture=excluded.picture,digest=excluded.digest,fetched_at=now()",
            (workspace_id, connection_id, jpeg, digest),
        )
    elif status == "absent":
        remove(cur, workspace_id, connection_id)


def remove(cur, workspace_id, connection_id):
    cur.execute("DELETE FROM public.pr_channel_pictures WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))


def digests(cur, workspace_id):
    cur.execute("SELECT connection_id,digest FROM public.pr_channel_pictures WHERE workspace_id=%s", (workspace_id,))
    return {row[0]: row[1] for row in cur.fetchall()}


def read(cur, workspace_id, connection_id):
    cur.execute("SELECT picture,digest FROM public.pr_channel_pictures WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
    row = cur.fetchone()
    return (bytes(row[0]), row[1]) if row else None
