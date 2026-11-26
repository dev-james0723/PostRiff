"""One page of an account's own posts, with their text, from a provider's official API (voice import, spec 5.2).

`read_page(provider, *, token, account, cursor, since, transport)` builds one request, sends it through the injected
transport and returns `Page(items, next_cursor, more, skipped)`. It holds no state and touches no database: the
importer (voice_import.py) owns consent, admission, tokens, cursors and storage, and has already checked that the
connection may be read (for LinkedIn: the app's restricted approval and the member's grant).

Each item is `{externalId, text, publishedAt, permalink, kind, contentType}`; `kind` is original, reply, quote or
repost. A repost is listed without its text: the words belong to someone else, so they are counted and never kept.
`skipped` counts listed entries that carry nothing to keep (media without a caption, posts that are not public, another
author's post, malformed entries).

Failures: `ReaderHTTP(status, retry_after)` for a provider answer that is not a usable page (never read as an empty
history), `ReaderPaging` when paging cannot continue truthfully (a repeated or missing cursor), and the transport's own
`AlphaError` when the provider could not be reached.

Servers a person chose (a Mastodon server, a Bluesky account's own data server) are contacted only by a plain public
https name that also resolves to public addresses at request time, the same check their adapters make; `resolver` is
that DNS lookup and is injected in tests. The shared transport refuses responses over 256 kB, so a page refused as too
large is asked again once at a quarter of the size.
"""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import NamedTuple
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from postriff_alpha.domain import AlphaError

from .net_guard import assert_public, public_host, public_https_url
from .provider_base import GRAPH_VERSION

SUPPORTED = ("threads", "instagram", "bluesky", "mastodon", "linkedin")
KINDS = ("original", "reply", "quote", "repost")
PAGE_SIZES = {"threads": 50, "instagram": 25, "bluesky": 100, "mastodon": 40, "linkedin": 25}
THREADS_FIELDS = "id,text,timestamp,media_type,permalink,is_quote_post"
MAX_TEXT = 20_000
# Meta answers a rate limit with an error code rather than HTTP 429 (application, user, page, custom and the
# business-use-case range).
_META_RATE_CODES = frozenset({4, 17, 32, 613})
_CURSOR = re.compile(r"[A-Za-z0-9_.~=-]{1,2048}")
_OPAQUE = re.compile(r"[\x21-\x7e]{1,512}")
_DID = re.compile(r"did:(?:plc:[a-z2-7]{24}|web:[a-z0-9.%-]{3,253})")
_AT_POST = re.compile(r"at://(did:[a-z0-9:.%-]{5,260})/app\.bsky\.feed\.post/([A-Za-z0-9._~:-]{1,64})")
_LOCAL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_NEXT_LINK = re.compile(r'<([^<>]{1,2048})>\s*;\s*rel="next"')
_MEDIA = {"TEXT_POST": "text", "IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel", "AUDIO": "audio"}


class Page(NamedTuple):
    items: list
    next_cursor: str | None
    more: bool
    skipped: int = 0


class ReaderHTTP(Exception):
    """The provider did not return a usable page. `status` is its HTTP status (429 for a rate limit however it was
    reported, 502 for an unreadable body, 400 for a request that was refused before it was sent); `retry_after` is the
    provider's wait in whole seconds, when it gave one."""
    def __init__(self, status, retry_after=None):
        super().__init__(f"provider page status {status}")
        self.status, self.retry_after = status, retry_after


class ReaderPaging(Exception):
    """Paging cannot continue: the provider repeated a cursor, or announced another page without a usable one."""


def _retry_after(headers):
    value = headers.get("retry-after") if isinstance(headers, dict) else None
    return int(value) if isinstance(value, str) and value.strip().isdigit() and len(value.strip()) <= 6 else None


def _fail(response):
    status = response.get("status") if isinstance(response, dict) else None
    body = response.get("body") if isinstance(response, dict) else None
    error = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
    code = error.get("code")
    if type(code) is int and (code in _META_RATE_CODES or 80000 <= code < 80100):
        status = 429
    elif error.get("is_transient") is True:
        status = 503
    elif status == 200 or type(status) is not int:
        status = 502
    raise ReaderHTTP(status, _retry_after(response.get("headers") if isinstance(response, dict) else None))


def _body(response, kind):
    """The parsed body of a 200 answer of the expected type; anything else is a failure, never an empty page."""
    if not isinstance(response, dict) or response.get("status") != 200:
        _fail(response)
    body = response.get("body")
    if not isinstance(body, kind) or (isinstance(body, dict) and body.get("error")):
        _fail(response)
    return body


def _when(value):
    """ISO 8601 in UTC, or None. A time without an offset is not guessed."""
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None


def _https(value, roots=None):
    """An https link without credentials (on one of `roots` when given), else None."""
    if not isinstance(value, str) or not 8 < len(value) <= 2048:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return None
    return value if roots is None or any(host == root or host.endswith("." + root) for root in roots) else None


def _text(value):
    return value.strip() if isinstance(value, str) and len(value) <= MAX_TEXT else ""


def _item(external_id, text, published, permalink, kind, content_type):
    return {"externalId": external_id, "text": "" if kind == "repost" else text, "publishedAt": published, "permalink": permalink,
            "kind": kind, "contentType": "post" if kind == "repost" else content_type}


# --- Threads ---------------------------------------------------------------------------------------------------------
def _threads(token, account, cursor, transport, size, resolver):
    """The same host, version and token placement as the metadata-only history import (growth/history_import.py)."""
    params = {"fields": THREADS_FIELDS, "limit": size, "access_token": token}
    if cursor:
        params["after"] = cursor
    body = _body(transport("GET", f"https://graph.threads.net/{GRAPH_VERSION}/me/threads?" + urlencode(params)), dict)
    rows = body.get("data", [])
    if not isinstance(rows, list):
        raise ReaderHTTP(502)
    items, skipped = [], 0
    for row in rows:
        post_id = str(row.get("id")) if isinstance(row, dict) and isinstance(row.get("id"), (str, int)) and not isinstance(row.get("id"), bool) else ""
        if not 0 < len(post_id) <= 300:
            skipped += 1
            continue
        repost, text = row.get("media_type") == "REPOST_FACADE", _text(row.get("text"))
        if not text and not repost:
            skipped += 1                      # a photo or video with no caption carries no writing
            continue
        kind = "repost" if repost else "quote" if row.get("is_quote_post") is True else "original"
        items.append(_item(post_id, text, _when(row.get("timestamp")), _https(row.get("permalink"), ("threads.net", "threads.com")),
                           kind, _MEDIA.get(row.get("media_type"), "post")))
    paging = body.get("paging") if isinstance(body.get("paging"), dict) else {}
    if not paging.get("next"):
        return Page(items, None, False, skipped)
    cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
    after = cursors.get("after")
    if not isinstance(after, str) or not _CURSOR.fullmatch(after):
        raise ReaderPaging("Threads announced another page without a usable cursor")
    return Page(items, after, True, skipped)   # the provider's `next` URL is never followed


# --- Instagram and LinkedIn: the existing picker reader (social_history.fetch_page) -------------------------------------
def _via_picker(provider, platform, token, account, cursor, transport, size):
    """Reuse the reviewed owned-post reader: same endpoint, identity checks, owner filter and cursor rules. It reports
    every failure as a customer message, so the provider's own answer is kept here to classify it."""
    from .social_history import fetch_page
    if cursor is not None and (not isinstance(cursor, str) or not _CURSOR.fullmatch(cursor)):
        raise ReaderPaging("the stored cursor is not usable")
    calls, answers = [], []

    def tap(method, url, **kwargs):
        calls.append(url)
        answer = transport(method, url, **kwargs)
        answers.append(answer)
        return answer
    # history_approved: the importer has already checked the app's approval and the member's grant.
    adapter = SimpleNamespace(id=provider, platform=platform, transport=tap, history_approved=True)
    try:
        page = fetch_page(adapter, token, account, cursor, min(size, 25))
    except AlphaError:
        if not calls:
            raise ReaderHTTP(400) from None                # refused before any request: this is not that kind of account
        if not answers:
            raise                                          # the transport itself failed: unreachable or oversized
        answer = answers[-1]
        if not isinstance(answer, dict) or answer.get("status") != 200:
            _fail(answer)
        paging = answer["body"].get("paging") if isinstance(answer.get("body"), dict) else None
        if isinstance(paging, dict) and paging.get("next"):
            raise ReaderPaging(f"{platform} announced another page without a usable cursor") from None
        raise ReaderHTTP(502) from None
    media = {"IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}
    items = [_item(post["id"], post["text"], post.get("publishedAt") or None, post.get("permalink"), "original",
                   media.get(post.get("mediaType"), "post")) for post in page["posts"]]
    return Page(items, page["nextCursor"], page["nextCursor"] is not None, int(page.get("skippedCount") or 0))


def _instagram(token, account, cursor, transport, size, resolver):
    return _via_picker("instagram", "Instagram", token, account, cursor, transport, size)


def _linkedin(token, account, cursor, transport, size, resolver):
    return _via_picker("linkedin", "LinkedIn", token, account, cursor, transport, size)


# --- Bluesky -----------------------------------------------------------------------------------------------------------
def _bluesky(token, account, cursor, transport, size, resolver):
    """The account's own repository on its own data server (com.atproto.repo.listRecords). That read is public, so no
    authorization is sent and the connection's tokens never leave Rafii. `token` is the stored connection as JSON; only
    its `did` and `pds` are read. Reposts live in another collection and never appear here."""
    try:
        session = json.loads(token) if isinstance(token, str) else None
    except ValueError:
        session = None
    pds = session.get("pds") if isinstance(session, dict) else None
    if not isinstance(account, str) or not _DID.fullmatch(account) or not isinstance(pds, str) or session.get("did") != account:
        raise ReaderHTTP(400)
    try:
        origin = urlsplit(pds)
        plain = (origin.scheme == "https" and bool(origin.hostname) and not origin.username and not origin.password
                 and origin.port in (None, 443) and origin.path in ("", "/") and not origin.query and not origin.fragment
                 and public_host(origin.hostname) == origin.hostname.lower())
    except (ValueError, AlphaError):
        plain = False
    if not plain:
        raise ReaderHTTP(400)                  # only a plain public https origin is ever contacted
    if cursor is not None and (not isinstance(cursor, str) or not _OPAQUE.fullmatch(cursor)):
        raise ReaderPaging("the stored cursor is not usable")
    params = {"repo": account, "collection": "app.bsky.feed.post", "limit": size}
    if cursor:
        params["cursor"] = cursor
    url = pds.rstrip("/") + "/xrpc/com.atproto.repo.listRecords?" + urlencode(params)
    public_https_url(url, resolver)            # resolved again at request time, as the adapter does; a refusal is retried later
    body = _body(transport("GET", url), dict)
    records = body.get("records", [])
    if not isinstance(records, list):
        raise ReaderHTTP(502)
    items, skipped = [], 0
    for record in records:
        match = _AT_POST.fullmatch(record["uri"]) if isinstance(record, dict) and isinstance(record.get("uri"), str) else None
        value = record.get("value") if match and isinstance(record.get("value"), dict) else {}
        text = _text(value.get("text"))
        if not match or match.group(1) != account or not text:
            skipped += 1                       # a malformed record, or a post with no words
            continue
        embed = value.get("embed") if isinstance(value.get("embed"), dict) else {}
        embedded = str(embed.get("$type", ""))
        media = str(embed["media"].get("$type", "")) if isinstance(embed.get("media"), dict) else embedded
        if isinstance(value.get("reply"), dict):
            kind = "reply"
        elif embedded in ("app.bsky.embed.record", "app.bsky.embed.recordWithMedia"):
            kind = "quote"
        else:
            kind = "original"
        content = "image" if "images" in media else "video" if "video" in media else "text"
        permalink = f"https://bsky.app/profile/{quote(account, safe=':')}/post/{quote(match.group(2), safe='')}"
        items.append(_item(match.group(2), text, _when(value.get("createdAt")), permalink, kind, content))
    following = body.get("cursor")
    if following is None or following == "" or not records:
        return Page(items, None, False, skipped)
    if not isinstance(following, str) or not _OPAQUE.fullmatch(following):
        raise ReaderPaging("Bluesky returned an unusable cursor")
    return Page(items, following, True, skipped)


# --- Mastodon ----------------------------------------------------------------------------------------------------------
class _PlainText(HTMLParser):
    """Status HTML to text: paragraphs and line breaks kept, tags dropped, entities decoded."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "p" and self.parts:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(value):
    if not isinstance(value, str) or len(value) > 4 * MAX_TEXT:
        return ""
    parser = _PlainText()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # noqa: BLE001 - unreadable markup is a post without usable text
        return ""
    return _text(re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)))


def _mastodon_bearer(token, host):
    """The bearer for this server, or None for a public read. A stored session names its own server; its token is never
    sent anywhere else."""
    if not isinstance(token, str) or not token:
        return None
    if not token.startswith("{"):
        return token
    try:
        session = json.loads(token)
        if not isinstance(session, dict) or not isinstance(session.get("at"), str) or not session["at"] or public_host(session.get("instance")) != host:
            raise ValueError("session")
    except (ValueError, AlphaError):
        raise ReaderHTTP(400) from None
    return session["at"]


def _mastodon(token, account, cursor, transport, size, resolver):
    local, separator, server = account.rpartition("@") if isinstance(account, str) else ("", "", "")
    try:
        host = public_host(server) if separator and _LOCAL_ID.fullmatch(local) else None
    except AlphaError:
        host = None
    if not host or host != server.lower():
        raise ReaderHTTP(400)                  # only a plain public server name is ever contacted
    if cursor is not None and (not isinstance(cursor, str) or not _LOCAL_ID.fullmatch(cursor)):
        raise ReaderPaging("the stored cursor is not usable")
    bearer = _mastodon_bearer(token, host)
    assert_public(host, resolver)              # resolved again at request time; a refusal is retried later
    params = {"limit": size, "exclude_reblogs": "false"}
    if cursor:
        params["max_id"] = cursor
    url = f"https://{host}/api/v1/accounts/{quote(local, safe='')}/statuses?" + urlencode(params)
    response = transport("GET", url, headers={"Authorization": "Bearer " + bearer}) if bearer else transport("GET", url)
    rows = _body(response, list)
    items, skipped, last = [], 0, None
    for row in rows:
        status_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(status_id, str) or not _LOCAL_ID.fullmatch(status_id):
            skipped += 1
            continue
        last = status_id
        published, link = _when(row.get("created_at")), _https(row.get("url")) or _https(row.get("uri"))
        if isinstance(row.get("reblog"), dict):
            items.append(_item(status_id, "", published, link, "repost", "post"))
            continue
        text = html_text(row.get("content"))
        if row.get("visibility") not in ("public", "unlisted") or not text:
            skipped += 1                       # followers-only and direct posts are private writing; never imported
            continue
        kind = "reply" if row.get("in_reply_to_id") else "quote" if isinstance(row.get("quote"), dict) else "original"
        media = row.get("media_attachments") if isinstance(row.get("media_attachments"), list) else []
        first = media[0].get("type") if media and isinstance(media[0], dict) else None
        content = {"image": "image", "video": "video", "gifv": "video", "audio": "audio"}.get(first, "text")
        items.append(_item(status_id, text, published, link, kind, content))
    headers = response.get("headers") if isinstance(response.get("headers"), dict) else {}
    if isinstance(headers.get("link"), str):
        match = _NEXT_LINK.search(headers["link"])
        following = (parse_qs(urlsplit(match.group(1)).query).get("max_id") or [None])[0] if match else None
        if match and (not following or not _LOCAL_ID.fullmatch(following)):
            raise ReaderPaging("Mastodon announced another page without a usable cursor")
    else:
        following = last                       # servers that send no Link header: continue until an empty page
    return Page(items, following, following is not None, skipped)


_READERS = {"threads": _threads, "instagram": _instagram, "bluesky": _bluesky, "mastodon": _mastodon, "linkedin": _linkedin}


def read_page(provider, *, token, account, cursor, since, transport, limit=None, resolver=socket.getaddrinfo) -> Page:
    """One page, newest first, starting at `cursor` (None = the newest post). `since` (an aware datetime) drops older
    posts and ends the run at the first one. `limit` overrides the provider's page size. `token` is the access token
    (Threads, Instagram, LinkedIn), the stored session or bearer or None (Mastodon), or the stored connection as JSON
    with `did` and `pds` (Bluesky). `account` is the provider's account id."""
    reader = _READERS.get(provider)
    if reader is None:
        raise ValueError(f"voice import has no reader for {provider}")
    size = limit if type(limit) is int and limit > 0 else PAGE_SIZES[provider]
    try:
        page = reader(token, account, cursor, transport, size, resolver)
    except AlphaError as error:
        # The shared transport refuses a response over 256 kB with a 502: ask once for a quarter of the page.
        if limit is not None or getattr(error, "status", None) != 502 or size < 4:
            raise
        page = reader(token, account, cursor, transport, size // 4, resolver)
    if page.next_cursor is not None and page.next_cursor == cursor:
        raise ReaderPaging("the provider repeated a cursor")
    if since is None:
        return page
    kept, reached = [], False
    for item in page.items:
        if item["publishedAt"] is not None and datetime.fromisoformat(item["publishedAt"]) < since:
            reached = True
            continue
        kept.append(item)
    return Page(kept, None, False, page.skipped) if reached else Page(kept, page.next_cursor, page.more, page.skipped)
