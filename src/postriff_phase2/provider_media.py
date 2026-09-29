"""Bounded, no-redirect media upload to a fixed official HTTPS provider host."""
import http.client
import json
import secrets
import ssl
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError


def stream_multipart_video(url, token, chunks, expected_bytes, *, host="open.douyin.com"):
    """Upload one verified MP4 without holding the file in memory.

    The caller owns the one-use media iterator; only a fixed provider host is allowed.
    """
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != host or parts.port not in (None, 443)
            or parts.username or parts.password or parts.fragment or not isinstance(token, str) or not token):
        raise AlphaError("The provider upload address is invalid.", 502)
    if type(expected_bytes) is not int or not 0 < expected_bytes <= 100_000_000:
        raise AlphaError("Approved video size is invalid.", 409)
    boundary = "rafii" + secrets.token_hex(12)
    prefix = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"video\"; filename=\"rafii.mp4\"\r\n"
              "Content-Type: video/mp4\r\n\r\n").encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    connection = http.client.HTTPSConnection(host, timeout=120, context=ssl.create_default_context())
    try:
        connection.putrequest("POST", parts.path + ("?" + parts.query if parts.query else ""))
        connection.putheader("access-token", token)
        connection.putheader("Accept", "application/json")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(len(prefix) + expected_bytes + len(suffix)))
        connection.endheaders()
        connection.send(prefix)
        total = 0
        for chunk in chunks:
            if not isinstance(chunk, bytes) or not chunk or len(chunk) > 5 * 1024 * 1024:
                raise AlphaError("Approved video stream changed.", 409)
            total += len(chunk)
            if total > expected_bytes:
                raise AlphaError("Approved video stream changed.", 409)
            connection.send(chunk)
        if total != expected_bytes:
            raise AlphaError("Approved video stream changed.", 409)
        connection.send(suffix)
        response = connection.getresponse()
        raw = response.read(262145)
        if len(raw) > 262144:
            raise AlphaError("Provider response limit exceeded.", 502)
        mime = response.getheader("content-type", "").split(";", 1)[0].strip().lower()
        if raw and mime != "application/json":
            raise AlphaError("Provider upload response was not JSON.", 502)
        try:
            body = json.loads(raw) if raw else {}
        except ValueError as error:
            raise AlphaError("Provider upload response was invalid.", 502) from error
        return {"status": response.status, "headers": {k.lower(): v for k, v in response.getheaders()}, "body": body}
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
        raise AlphaError("Provider video upload outcome is uncertain.", 503) from error
    finally:
        connection.close()
