"""Safe link capture and quick notes (engineering spec §7 "Link/quick-note ingress"; T02).

Both create a normalized pr_library_assets row (source_kind 'link' or 'note') through the same validation, quota and
private storage path as uploads: the extension/MIME check of library_assets, the workspace storage limit, an immutable
private object verified by HEAD (bytes, type, etag), then a 'queued' row that the existing Library worker hashes,
deduplicates and extracts exactly like an uploaded file. Both are idempotent on idempotencyKey.

Link fetching is SSRF-safe: http/https only, default ports, no embedded credentials, public DNS names only (no IP
literals or local suffixes, via net_guard.public_host), every resolved address public (private, loopback, link-local and
metadata, CGNAT, unique-local, NAT64/6to4/IPv4-mapped, multicast and reserved ranges refused), every redirect hop re-vetted
(at most 3), and the connection pinned to the vetted address so a second DNS answer cannot rebind it. Responses are capped
at 2 MB and 10 s, identity-encoded, and limited to HTML, plain text and PDF. HTML is reduced to text by the existing
library_extract parser (scripts, styles and templates dropped); the page itself is never stored or rendered. Sign-in
walls and unavailable pages fail honestly; Rafii never uses browser sessions or cookies to get past them.
"""
from __future__ import annotations

import codecs
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from postriff_alpha.domain import AlphaError

from .. import library_extract, net_guard
from ..contracts import digest
from . import contracts as c
from . import jobs

LINK_MAX_BYTES = 2 * 1024 * 1024
LINK_TIMEOUT = 10.0
MAX_REDIRECTS = 3
MAX_URL = 2048
NOTE_MAX_CHARS = 100_000
USER_AGENT = "RafiiLibrary/1.0 (+private link capture)"
ACCEPT = "text/html,text/plain;q=0.9,application/pdf;q=0.8"
ALLOWED_TYPES = ("text/html", "text/plain", "application/pdf")
REDIRECTS = (301, 302, 303, 307, 308)
BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/128", "::1/128", "::ffff:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32", "2002::/16",
    "fc00::/7", "fe80::/10", "fec0::/10", "ff00::/8"))
PASSWORD_FIELD = re.compile(rb"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
SAFE_NAME = re.compile(r"[^\w .,()\-]+", re.U)


def _fail(message, code, status=422):
    raise AlphaError(message, status, code=code)


# --- address vetting ----------------------------------------------------------------------------------------------------
def public_ip(text):
    """The address if it is publicly routable and not in any special-purpose range, else None."""
    try:
        address = ipaddress.ip_address(str(text).split("%", 1)[0])
    except ValueError:
        return None
    if (not address.is_global or address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
            or address.is_reserved or address.is_unspecified):
        return None
    if any(address.version == net.version and address in net for net in BLOCKED_NETWORKS):
        return None
    return address


def _target(url):
    """Parse and vet one hop's URL without any network access."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL or any(ch in url for ch in "\r\n\t\x00"):
        _fail("Paste a complete web link.", "library_link_invalid")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        _fail("Paste a complete web link.", "library_link_invalid")
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        _fail("Use an http or https link.", "library_link_scheme")
    if parts.username is not None or parts.password is not None:
        _fail("Links with embedded sign-in details aren't accepted.", "library_link_credentials")
    default = 443 if scheme == "https" else 80
    if port not in (None, default):
        _fail("Use a link on the standard web port.", "library_link_port")
    try:
        host = net_guard.public_host(parts.hostname or "", message="blocked")
    except AlphaError:
        _fail("This link points to a private or local address, which Rafii doesn't fetch.", "library_link_blocked")
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    clean = urlunsplit((scheme, host if port is None else f"{host}:{port}", parts.path or "/", parts.query, ""))
    return {"scheme": scheme, "host": host, "port": default, "path": path, "url": clean}


def _vet(host, port, resolver):
    try:
        answers = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        _fail("This link's site couldn't be found.", "library_link_unreachable")
    addresses = []
    for answer in answers or []:
        try:
            ip = public_ip(answer[4][0])
        except (IndexError, TypeError):
            ip = None
        if ip is None:
            # One private answer is enough to refuse: the client could be steered to it.
            _fail("This link points to a private or local address, which Rafii doesn't fetch.", "library_link_blocked")
        addresses.append(str(ip))
    if not addresses:
        _fail("This link's site couldn't be found.", "library_link_unreachable")
    return addresses[0]


# --- pinned transport ---------------------------------------------------------------------------------------------------
def pinned_get(scheme, host, address, port, path, timeout, deadline, clock):
    """GET over a socket connected to the vetted address; TLS is verified for the original host name. Never follows a
    redirect, never decompresses, reads at most LINK_MAX_BYTES + 1 of a 2xx body within the deadline."""
    context = ssl.create_default_context() if scheme == "https" else None
    conn = (http.client.HTTPSConnection(host, port, timeout=timeout, context=context) if scheme == "https"
            else http.client.HTTPConnection(host, port, timeout=timeout))
    try:
        raw_socket = socket.create_connection((address, port), timeout=timeout)
        try:
            conn.sock = context.wrap_socket(raw_socket, server_hostname=host) if context else raw_socket
        except Exception:
            raw_socket.close()
            raise
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT, "Accept-Encoding": "identity"})
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        body = b""
        if 200 <= response.status < 300:
            declared = headers.get("content-length", "")
            if declared.isdigit() and int(declared) > LINK_MAX_BYTES:
                return {"status": response.status, "headers": {**headers, "too-large": "1"}, "body": b""}
            pieces, size = [], 0
            while size <= LINK_MAX_BYTES:
                left = deadline - clock()
                if left <= 0:
                    raise TimeoutError()
                conn.sock.settimeout(left)
                piece = response.read(min(65536, LINK_MAX_BYTES + 1 - size))
                if not piece:
                    break
                pieces.append(piece)
                size += len(piece)
            body = b"".join(pieces)
        return {"status": response.status, "headers": headers, "body": body}
    except TimeoutError as error:
        raise AlphaError("The link took too long to respond.", 504, code="library_link_timeout") from error
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise AlphaError("The link could not be reached.", 502, code="library_link_unreachable") from error
    finally:
        conn.close()


RESOLVER = socket.getaddrinfo
CONNECTOR = pinned_get


class _Title(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside, self.parts = False, []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.inside = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.inside = False

    def handle_data(self, data):
        if self.inside and sum(map(len, self.parts)) < 400:
            self.parts.append(data)


def _decode(raw: bytes, charset: str | None) -> str:
    name = "utf-8"
    if charset:
        try:
            name = codecs.lookup(charset.strip().strip("\"'")).name
        except LookupError:
            name = "utf-8"
    return raw.decode(name, errors="replace")


def _accept(response, url, redirects):
    status, headers, body = response["status"], response.get("headers") or {}, response.get("body") or b""
    if status in (401, 403, 407):
        _fail("This link needs a sign-in, so Rafii can't read it. Download the file and add it instead.", "library_link_login_required")
    if status in (404, 410):
        _fail("This link is unavailable.", "library_link_unavailable")
    if status == 429 or status >= 500:
        _fail("The site didn't respond properly. Try again later.", "library_link_unavailable", 502)
    if not 200 <= status < 300:
        _fail("This link could not be captured.", "library_link_failed")
    if (headers.get("content-encoding") or "identity").strip().lower() not in ("identity", ""):
        _fail("The site sent a compressed response Rafii didn't ask for.", "library_link_encoding")
    if headers.get("too-large") or len(body) > LINK_MAX_BYTES:
        _fail("This page is larger than 2 MB. Download it and add the file instead.", "library_link_too_large", 413)
    content_type = (headers.get("content-type") or "").split(";")
    mime = content_type[0].strip().lower()
    charset = next((p.split("=", 1)[1] for p in content_type[1:] if p.strip().lower().startswith("charset=")), None)
    if mime not in ALLOWED_TYPES:
        _fail("Rafii can capture web pages, plain text and PDF links.", "library_link_type")
    if not body:
        _fail("This link returned nothing to keep.", "library_link_empty")
    host = urlsplit(url).hostname or "link"
    if mime == "application/pdf":
        if not body.startswith(b"%PDF-"):
            _fail("This link did not return a real PDF.", "library_link_type")
        last = urlsplit(url).path.rsplit("/", 1)[-1]
        name = last if last.lower().endswith(".pdf") else f"{host}.pdf"
        return {"raw": body, "ext": "pdf", "mime": "application/pdf", "title": None, "filename": name, "contentType": mime, "sanitized": False}
    if mime == "text/html":
        if PASSWORD_FIELD.search(body):
            _fail("This page asks for a sign-in, so Rafii can't read it. Download the file and add it instead.", "library_link_login_required")
        text_html = _decode(body, charset)
        title_parser = _Title()
        try:
            title_parser.feed(text_html)
        except Exception:
            pass
        title = " ".join("".join(title_parser.parts).split())[:160] or None
        _, text = library_extract.extract_text(text_html.encode("utf-8"), "html")
    else:
        title = None
        text = library_extract.normalize(_decode(body, charset))
    if not text.strip():
        _fail("This page has no readable text without running its scripts.", "library_link_empty")
    raw = text.encode("utf-8")
    return {"raw": raw, "ext": "txt", "mime": "text/plain", "title": title, "filename": f"{title or host}.txt", "contentType": mime,
            "sanitized": mime == "text/html"}


def fetch_link(url, *, resolver=None, connector=None, clock=None) -> dict:
    """Fetch one user-supplied link safely. Returns {raw, ext, mime, title, filename, finalUrl, sourceUrl, redirects, ...}."""
    resolver = resolver or RESOLVER
    connector = connector or CONNECTOR
    clock = clock or time.monotonic
    deadline = clock() + LINK_TIMEOUT
    first = _target(url)
    current = first["url"]
    redirects = 0
    for _ in range(MAX_REDIRECTS + 1):
        target = _target(current)
        address = _vet(target["host"], target["port"], resolver)
        remaining = deadline - clock()
        if remaining <= 0:
            _fail("The link took too long to respond.", "library_link_timeout", 504)
        response = connector(target["scheme"], target["host"], address, target["port"], target["path"], remaining, deadline, clock)
        if response["status"] in REDIRECTS:
            location = (response.get("headers") or {}).get("location")
            if not location:
                _fail("The link redirected without a destination.", "library_link_failed")
            current = urljoin(target["url"], location)
            redirects += 1
            continue
        out = _accept(response, target["url"], redirects)
        return {**out, "sourceUrl": first["url"], "finalUrl": target["url"], "redirects": redirects, "httpStatus": response["status"],
                "fetchedBytes": len(response.get("body") or b"")}
    _fail("The link redirected too many times.", "library_link_redirects")


# --- storage ------------------------------------------------------------------------------------------------------------
def _filename(name: str, ext: str) -> str:
    stem = name.rsplit(".", 1)[0] if name.lower().endswith("." + ext) else name
    stem = " ".join(SAFE_NAME.sub(" ", stem).split())[:120].strip(" .") or "capture"
    return f"{stem}.{ext}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _storage(ctx):
    library = getattr(ctx.service, "library", None)
    storage = getattr(library, "storage", None)
    if library is None or storage is None or not callable(getattr(storage, "put_immutable", None)):
        raise AlphaError("File uploads aren't available yet.", 503, code="library_storage_not_configured")
    return library, storage


def _store(ctx, *, filename, mime, raw, title, title_source, source_kind, provenance) -> dict:
    """Same path as an upload: type/MIME validation, workspace quota, an immutable private object verified by HEAD, then
    a queued row for the existing Library worker (hash, duplicate check, extraction)."""
    from ..library_assets import _type
    library, storage = _storage(ctx)
    name, ext, mime, kind = _type(filename, mime)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= library_extract.MAX_FILE_BYTES:
        _fail("This item is empty or over 50 MB.", "library_too_large", 413)
    library.assert_capacity(ctx.cur, ctx.state, ctx.workspace_id, len(raw))
    asset_id = uuid.uuid4().hex
    object_name = f"{asset_id}.{ext}"
    storage.put_immutable(ctx.workspace_id, "file", object_name, raw, mime)
    try:
        info = storage.object_info(ctx.workspace_id, "file", object_name)
        if (info.get("bytes"), info.get("mime")) != (len(raw), mime) or not info.get("etag"):
            raise AlphaError("Private storage did not keep this item intact. Try again.", 503, code="library_storage_mismatch")
        ctx.cur.execute(
            "/*lij:intake.insert*/ INSERT INTO public.pr_library_assets(id,workspace_id,created_by,original_filename,display_title,title_source,kind,mime,"
            "extension,bytes,bucket,object_name,etag,processing_status,next_attempt_at,provenance,transcription_status,source_kind) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',now(),%s::jsonb,'not_applicable',%s)",
            (uuid.UUID(hex=asset_id), ctx.workspace_id, ctx.actor, name, (title or name.rsplit(".", 1)[0])[:160], title_source, kind, mime, ext, len(raw),
             getattr(library, "bucket", "postriff-library"), object_name, info["etag"], json.dumps(provenance), source_kind))
    except Exception:
        try:
            storage.delete(ctx.workspace_id, "file", object_name)
        except Exception:
            pass  # an orphan object is swept with the workspace prefix; the row was never committed
        raise
    return {"assetRef": {"assetId": asset_id, "versionId": asset_id, "sha256": ""}, "displayTitle": (title or name.rsplit(".", 1)[0])[:160],
            "originalFilename": name, "kind": kind, "mime": mime, "bytes": len(raw), "sourceKind": source_kind, "processing": "queued",
            "contentSha256": hashlib.sha256(raw).hexdigest(), "provenance": provenance}


def _writable(ctx):
    ctx.require("edit")
    if (ctx.state.get("workspace") or {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")


def _title(value):
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160 or "\x00" in value:
        c.fail("Use a title from 1 to 160 characters.")
    return " ".join(value.split())


def link_http(ctx, request):
    """POST .../ingest/link {url, idempotencyKey, title?}. Fetch happens only for a new key; a replay returns the first result."""
    body = request.get("body") or {}
    if not set(body) <= {"url", "idempotencyKey", "title"}:
        c.fail("This link request has unexpected fields.")
    _writable(ctx)
    url = _target(body.get("url"))["url"]
    title = _title(body.get("title"))
    key = jobs.request_key(body.get("idempotencyKey"))
    request_hash = digest({"kind": "link", "url": url, "title": title})
    prior = jobs.receipt(ctx, key, "ingest.link", request_hash)
    if prior is not None:
        return prior
    _storage(ctx)  # never fetch what cannot be kept
    fetched = fetch_link(url)
    provenance = {"source": "link", "sourceUrl": fetched["sourceUrl"], "finalUrl": fetched["finalUrl"], "retrievedAt": _now_iso(),
                  "httpStatus": fetched["httpStatus"], "contentType": fetched["contentType"], "redirects": fetched["redirects"],
                  "fetchedBytes": fetched["fetchedBytes"], "sanitized": fetched["sanitized"], "capturedBy": ctx.actor}
    if fetched.get("title"):
        provenance["pageTitle"] = fetched["title"]
    asset = _store(ctx, filename=_filename(title or fetched["filename"], fetched["ext"]), mime=fetched["mime"], raw=fetched["raw"],
                   title=title or fetched.get("title"), title_source="user" if title else "generated", source_kind="link", provenance=provenance)
    result = {"asset": asset, "status": "queued"}
    jobs.put_receipt(ctx, key, "ingest.link", request_hash, result)
    return {**result, "_status": 201}


def note_http(ctx, request):
    """POST .../ingest/note {text, authoredByMe, idempotencyKey, title?}. Authorship is explicit and kept in provenance; it
    records who wrote the note and never by itself admits the note as a voice sample (that needs its own approval)."""
    body = request.get("body") or {}
    if not set(body) <= {"text", "authoredByMe", "idempotencyKey", "title"}:
        c.fail("This note has unexpected fields.")
    _writable(ctx)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > NOTE_MAX_CHARS or "\x00" in text:
        c.fail(f"Write a note of up to {NOTE_MAX_CHARS:,} characters.")
    authored = body.get("authoredByMe")
    if type(authored) is not bool:
        raise AlphaError("Say whether you wrote this note yourself.", 422, code="library_note_authorship")
    title = _title(body.get("title"))
    key = jobs.request_key(body.get("idempotencyKey"))
    request_hash = digest({"kind": "note", "text": text, "authoredByMe": authored, "title": title})
    prior = jobs.receipt(ctx, key, "ingest.note", request_hash)
    if prior is not None:
        return prior
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Note")
    display = title or (first_line[:80] + ("…" if len(first_line) > 80 else ""))
    provenance = {"source": "note", "authoredByMe": authored, "createdBy": ctx.actor, "capturedAt": _now_iso()}
    if authored:
        provenance["author"] = ctx.actor
    asset = _store(ctx, filename=_filename(display, "txt"), mime="text/plain", raw=text.encode("utf-8"), title=display,
                   title_source="user" if title else "generated", source_kind="note", provenance=provenance)
    result = {"asset": asset, "status": "queued"}
    jobs.put_receipt(ctx, key, "ingest.note", request_hash, result)
    return {**result, "_status": 201}
