"""Substack capabilities, public-feed transport, and manual editorial handoffs.

This module deliberately has no OAuth or Publisher API implementation: a usable
first-party protocol contract and Rafii-specific authorization are unverified.
Public feed enrollment never establishes account authentication or ownership.
The hosted service must authorize workspace access before calling these helpers.
"""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

from postriff_alpha.domain import AlphaError


RESEARCH_AS_OF = "2026-10-18"
CAPABILITY_STATUSES = frozenset({
    "available", "unsupported", "requires_official_approval",
    "requires_account_eligibility", "permission_missing", "temporarily_unavailable",
})
CONNECTION_MODES = {
    "public_feed": "Public Feed Added",
    "official_mcp_analytics": "Official MCP Analytics — Read Only",
    "official_authorized": "Official Authorized Connection",
    "official_partnership": "Official Partnership Publishing",
}
METRIC_PROVENANCE = frozenset({"verified_official", "imported", "derived", "unavailable"})
OFFICIAL_MCP_URL = "https://mcp.substack.com/api/v1/mcp"
MCP_EVIDENCE = "https://support.substack.com/hc/en-us/articles/50834026608916-How-to-connect-Substack-to-your-AI-Assistant"
API_EVIDENCE = "https://substack.com/api-tos"
PUBLISHER_EVIDENCE = "https://substack.com/startups"
NOTES_EVIDENCE = "https://on.substack.com/p/new-on-substack-creator-match-audience"
RSS_EVIDENCE = "https://support.substack.com/hc/en-us/articles/360038239391-Is-there-an-RSS-feed-for-my-publication"

MAX_FEED_BYTES = 1024 * 1024
MAX_FEED_ITEMS = 100
MAX_XML_ELEMENTS = 10000
MAX_DRAFT_BODY = 200000
_RESERVED_HOSTS = frozenset({
    "www", "api", "mcp", "publisher-api", "support", "help", "account", "accounts",
    "admin", "auth", "oauth", "login", "signup", "static", "cdn", "substack",
    "assets", "image", "images", "links", "email", "emails", "app", "status",
})
_PUBLICATION_HOST = re.compile(r"^(?!-)([a-z0-9-]{1,63})(?<!-)\.substack\.com$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FEED_CONTENT_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"})
_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")


def _capability(status, reason, *evidence):
    return {"status": status, "reason": reason, "evidence": list(evidence)}


def get_substack_capabilities(context=None):
    """Return JSON capability descriptions; caller-supplied flags cannot grant APIs.

    Context is server-owned connection state. Eligibility failures can explain a
    restriction; even claimed approval/authentication cannot enable a protocol
    implementation that this version does not contain.
    """
    context = {} if context is None else context
    if not isinstance(context, Mapping):
        raise AlphaError("Substack connection context is invalid.", code="invalid_substack_context")
    mode = context.get("mode", "public_feed")
    if not isinstance(mode, str) or mode not in CONNECTION_MODES:
        raise AlphaError("Choose a supported Substack connection method.", code="invalid_substack_mode")
    internal = "Available inside Rafii. This action does not write to Substack."
    capabilities = {name: _capability("available", internal) for name in (
        "draft_create", "draft_edit", "draft_preview", "draft_approval", "manual_handoff", "editorial_schedule",
    )}
    for name in ("public_feed_read", "public_feed_remove", "publication_info"):
        capabilities[name] = _capability(
            "available", "Public feed metadata and excerpts only. A publication URL does not authenticate an account or verify ownership.", RSS_EVIDENCE)
    approval_reason = "Rafii needs verified official access terms, a usable protocol contract, and live authorization acceptance before enabling this operation."
    for name in (
        "account_connect", "account_reconnect", "account_disconnect", "publication_select",
        "publication_ownership_verify", "admin_editor_roles", "permission_changes", "token_refresh",
        "account_status_monitoring", "multiple_publications", "profile_read",
    ):
        capabilities[name] = _capability("requires_official_approval", approval_reason, API_EVIDENCE, MCP_EVIDENCE)
    for name in (
        "publication_analytics", "subscriber_counts", "subscriber_growth", "paid_subscribers",
        "revenue_reporting", "paid_retention", "post_performance", "traffic_sources",
        "publication_settings_read", "historical_reporting",
    ):
        status, reason = "requires_official_approval", approval_reason
        if mode == "official_mcp_analytics":
            if context.get("is_admin") is False or context.get("is_bestseller") is False:
                status = "requires_account_eligibility"
                reason = "Official MCP requires a publication Admin and an eligible Bestseller publication; Substack determines eligibility."
            elif context.get("status") in ("revoked", "disconnected"):
                status, reason = "permission_missing", "The publication authorization is no longer active."
        capabilities[name] = _capability(status, reason, MCP_EVIDENCE)
    publisher_operations = (
        "post_draft_create", "post_draft_edit", "post_publish", "post_schedule", "post_schedule_cancel",
        "post_update", "newsletter_send", "audience_selection", "publication_settings_write",
        "sections_manage", "tags_manage", "content_import", "content_export", "comments_read",
        "comments_reply", "comments_moderate", "community_chat", "engagement_activity",
        "notifications_read", "subscribers_read", "subscriber_segments", "subscriber_import",
        "subscriber_export", "subscriber_status", "subscriber_changes", "subscriber_email_send",
        "image_upload", "video_publish", "podcast_publish", "audio_publish", "livestream_metadata",
        "media_import", "media_export", "payment_status", "subscription_tiers",
        "gift_subscriptions", "founding_subscriptions", "payment_manage",
    )
    for name in publisher_operations:
        capabilities[name] = _capability("requires_official_approval", approval_reason, PUBLISHER_EVIDENCE)
    for name in ("notes_create", "notes_schedule", "notes_reply", "notes_restack", "notes_like", "notes_quotes", "notes_media", "notes_analytics"):
        capabilities[name] = _capability(
            "requires_official_approval", "An official Notes integration partnership exists, but it grants no rights to Rafii. Rafii needs its own operation-specific approval and contract.", NOTES_EVIDENCE)
    for name in ("email_opens", "email_clicks", "content_conversion", "churn"):
        capabilities[name] = _capability(
            "requires_official_approval", "Exact official metric fields and definitions have not been verified; no value will be fabricated.", MCP_EVIDENCE, PUBLISHER_EVIDENCE)
    capabilities["metric_import"] = _capability(
        "temporarily_unavailable", "User-supplied metric import is not connected to the hosted workflow in this version; imported values must retain their source and observation time.")
    if mode == "official_mcp_analytics":
        # This is a mode boundary, independent of any caller-claimed grant.
        excluded = set(publisher_operations) | {name for name in capabilities if name.startswith("notes_")} | {"profile_read"}
        for name in excluded:
            capabilities[name] = _capability(
                "unsupported", "This operation is not exposed by the verified official MCP read-only analytics surface. Separate official access is required.", MCP_EVIDENCE)
    return capabilities


def require_substack_capability(capability, context=None):
    if not isinstance(capability, str):
        raise AlphaError("Choose a supported Substack operation.", 409, code="substack_capability_unavailable")
    result = get_substack_capabilities(context).get(capability)
    if not result or result["status"] != "available":
        raise AlphaError(
            result["reason"] if result else "This Substack operation is not supported.",
            409, code="substack_capability_unavailable")
    return result


def validate_publication_url(value):
    """Normalize a public Substack home/feed URL without resolving or fetching it.

    Custom domains need a separate ownership and DNS policy and are not accepted
    here. The network reader must still pin public DNS results and reject redirects.
    """
    if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise AlphaError("Enter a public HTTPS Substack publication URL.", code="invalid_substack_url")
    if not value.isascii() or "\\" in value or "?" in value or "#" in value:
        raise AlphaError("Use a publication URL without credentials, parameters, or fragments.", code="invalid_substack_url")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        port = parts.port
    except ValueError as error:
        raise AlphaError("Enter a valid Substack publication URL.", code="invalid_substack_url") from error
    match = _PUBLICATION_HOST.fullmatch(host)
    if (parts.scheme != "https" or not match or match.group(1) in _RESERVED_HOSTS
            or parts.username is not None or parts.password is not None or port is not None
            or parts.path not in ("", "/", "/feed", "/feed/") or "%" in parts.netloc):
        raise AlphaError("Use https://publication.substack.com or its /feed address. Custom and service domains are not supported here.", code="invalid_substack_url")
    return {"host": host, "publication_url": f"https://{host}", "feed_url": f"https://{host}/feed"}


def _public_address(address):
    if not address.is_global or address.is_multicast or getattr(address, "scope_id", None):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # is_global alone accepts the NAT64 prefix even when its embedded IPv4
        # is private. Check known transition forms before pinning the socket.
        embedded = [address.ipv4_mapped, address.sixtofour]
        if address.teredo:
            embedded.extend(address.teredo)
        if address in _NAT64_WELL_KNOWN:
            embedded.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if any(value is not None and (not value.is_global or value.is_multicast) for value in embedded):
            return False
    return True


def _pinned_public_feed_get(method, url, headers=None, *, resolver=socket.getaddrinfo):
    """Bounded HTTPS GET, public DNS checked once, TLS hostname checked, no redirects."""
    if method != "GET":
        raise AlphaError("The Substack public feed transport is read-only.", 405, code="substack_read_only")
    target = validate_publication_url(url)
    if url != target["feed_url"]:
        raise AlphaError("The feed transport only accepts the canonical feed URL.", code="invalid_substack_url")
    try:
        answers = resolver(target["host"], 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise AlphaError("The publication could not be reached.", 503, code="substack_feed_unavailable") from error
    addresses = []
    for answer in answers or []:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (ValueError, IndexError, TypeError) as error:
            raise AlphaError("The publication resolved to an unsafe address.", 400, code="unsafe_substack_address") from error
        if not _public_address(address):
            raise AlphaError("The publication resolved to an unsafe address.", 400, code="unsafe_substack_address")
        addresses.append(str(address))
    if not addresses:
        raise AlphaError("The publication could not be reached.", 503, code="substack_feed_unavailable")
    conn = http.client.HTTPSConnection(target["host"], timeout=10, context=ssl.create_default_context())
    try:
        raw_socket = socket.create_connection((addresses[0], 443), timeout=10)
        try:
            conn.sock = conn._context.wrap_socket(raw_socket, server_hostname=target["host"])
        except Exception:
            raw_socket.close()
            raise
        # Deliberately ignore supplied headers: credentials and cookies never enter this reader.
        conn.request("GET", "/feed", headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Accept-Encoding": "identity", "User-Agent": "Rafii-Public-Feed/1.0 (+https://rafii.io)",
        })
        response = conn.getresponse()
        raw = response.read(MAX_FEED_BYTES + 1)
        if len(raw) > MAX_FEED_BYTES:
            raise AlphaError("The publication feed exceeds the allowed size.", 413, code="substack_feed_too_large")
        return {"status": response.status, "headers": {k.lower(): v for k, v in response.getheaders()}, "body": raw}
    except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as error:
        raise AlphaError("The publication feed is temporarily unavailable.", 503, code="substack_feed_unavailable") from error
    finally:
        conn.close()


def fetch_public_feed(publication_url, *, transport=None, resolver=socket.getaddrinfo):
    target = validate_publication_url(publication_url)
    reader = transport or (lambda method, url: _pinned_public_feed_get(method, url, resolver=resolver))
    try:
        response = reader("GET", target["feed_url"])
    except (OSError, TimeoutError) as error:
        raise AlphaError("The publication feed is temporarily unavailable.", 503, code="substack_feed_unavailable") from error
    if not isinstance(response, Mapping):
        raise AlphaError("Substack returned an invalid feed response.", 502, code="invalid_substack_feed")
    status = response.get("status")
    if status == 429:
        raise AlphaError("The publication feed is rate limited. Try again later.", 429, code="substack_feed_rate_limited")
    if status != 200:
        raise AlphaError("The publication did not return a usable public feed. Redirects are not followed.", 502, code="substack_feed_unavailable")
    headers = response.get("headers") or {}
    if not isinstance(headers, Mapping):
        raise AlphaError("Substack returned invalid response headers.", 502, code="invalid_substack_feed")
    lowered = {str(key).lower(): str(value) for key, value in headers.items()}
    content_type = lowered.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in _FEED_CONTENT_TYPES or lowered.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
        raise AlphaError("The publication did not return an uncompressed XML feed.", 502, code="invalid_substack_feed_type")
    return normalize_public_feed(response.get("body"), target["publication_url"])


class _PlainText(HTMLParser):
    _DROP = frozenset({"script", "style", "iframe", "object", "embed", "head", "form", "textarea", "button", "select", "svg", "math"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.blocked = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self._DROP:
            self.blocked.append(tag)
        elif not self.blocked and tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if not self.blocked:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.blocked:
            del self.blocked[self.blocked.index(tag):]
        elif not self.blocked:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def _plain_text(value, limit):
    parser = _PlainText()
    parser.feed(str(value or ""))
    parser.close()
    return " ".join(_CONTROL.sub("", "".join(parser.parts)).split())[:limit]


def _local_name(element):
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _child_text(element, name):
    child = next((item for item in element if _local_name(item) == name), None)
    return "".join(child.itertext()) if child is not None else ""


def _feed_item_url(value, host):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.hostname != host or parts.username is not None or parts.password is not None
                or parts.port is not None or parts.query or parts.fragment or not parts.path.startswith("/p/")
                or "%" in parts.netloc):
            return None
    except ValueError:
        return None
    return f"https://{host}{parts.path}"


def _observation_time(value, *, required=False):
    if not isinstance(value, str) or len(value) > 100:
        if required:
            raise AlphaError("An observation time with a timezone is required.", code="invalid_substack_time")
        return None
    try:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        if required:
            raise AlphaError("Use a valid date and time with a timezone.", code="invalid_substack_time")
        return None


def normalize_public_feed(raw, publication_url):
    """Parse public RSS/Atom into bounded inert excerpts, never private post bodies."""
    target = validate_publication_url(publication_url)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8")
        except UnicodeError as error:
            raise AlphaError("The feed text is invalid.", 502, code="invalid_substack_feed") from error
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_FEED_BYTES:
        raise AlphaError("The public feed is empty or exceeds the allowed size.", 502, code="invalid_substack_feed")
    try:
        text = raw.decode("utf-8-sig")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE) or "\x00" in text:
            raise ValueError("XML declarations with entities are prohibited")
        root = ElementTree.fromstring(text)
    except (UnicodeError, ValueError, ElementTree.ParseError) as error:
        raise AlphaError("The publication returned an unsafe or malformed XML feed.", 502, code="invalid_substack_feed") from error
    if sum(1 for _ in root.iter()) > MAX_XML_ELEMENTS:
        raise AlphaError("The XML feed exceeds the structural limit.", 502, code="invalid_substack_feed")
    if _local_name(root) == "rss":
        channel = next((item for item in root if _local_name(item) == "channel"), None)
        if channel is None:
            raise AlphaError("The feed is missing its publication channel.", 502, code="invalid_substack_feed")
        entries = [entry for entry in channel if _local_name(entry) == "item"]
    elif _local_name(root) == "feed":
        channel = root
        entries = [entry for entry in root if _local_name(entry) == "entry"]
    else:
        raise AlphaError("The response is not an RSS or Atom publication feed.", 502, code="invalid_substack_feed")
    items, seen = [], set()
    for entry in entries:
        link = _child_text(entry, "link").strip()
        if not link:
            link = next((child.get("href", "") for child in entry
                         if _local_name(child) == "link" and child.get("rel", "alternate") == "alternate"), "")
        link = _feed_item_url(link, target["host"])
        if not link or link in seen:
            continue
        seen.add(link)
        items.append({
            "id": hashlib.sha256(link.encode()).hexdigest()[:32], "url": link,
            "title": _plain_text(_child_text(entry, "title"), 300),
            "summary": _plain_text(_child_text(entry, "description") or _child_text(entry, "summary"), 1200),
            "publishedAt": _observation_time(_child_text(entry, "pubDate") or _child_text(entry, "published") or _child_text(entry, "updated")),
            "provenance": "public_feed",
        })
        if len(items) == MAX_FEED_ITEMS:
            break
    return {
        "publicationUrl": target["publication_url"], "feedUrl": target["feed_url"],
        "title": _plain_text(_child_text(channel, "title"), 300),
        "description": _plain_text(_child_text(channel, "description") or _child_text(channel, "subtitle"), 1200),
        "items": items, "itemCount": len(items), "provenance": "public_feed",
        "accountAuthenticated": False, "ownershipVerified": False,
        "analyticsConnected": False, "publishingAuthorized": False,
    }


def _draft_text(value, field, limit, *, allow_newlines=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit or _CONTROL.search(value)
            or (not allow_newlines and ("\r" in value or "\n" in value or "\t" in value))):
        raise AlphaError(f"Enter valid {field} within the allowed size.", code="invalid_substack_draft")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise AlphaError(f"The {field} contains invalid text.", code="invalid_substack_draft") from error
    # A reviewed body must survive export byte-for-byte; trimming or normalizing
    # it after approval would make the exported payload differ from its digest.
    return value if allow_newlines else value.strip()


def build_manual_handoff(publication_url, draft):
    """Create an inert content package, not an approval or provider publish receipt.

    The service must bind its own approval to workspace, destination, revision,
    and this content digest. Render body as text; never trust Markdown raw HTML.
    """
    target = validate_publication_url(publication_url)
    if not isinstance(draft, Mapping):
        raise AlphaError("A Substack draft is required.", code="invalid_substack_draft")
    body_format = draft.get("format", "markdown")
    content_type = draft.get("contentType", "article")
    title = "" if content_type == "note" and draft.get("title", "") == "" else _draft_text(draft.get("title"), "title", 300)
    body = _draft_text(draft.get("body"), "draft body", MAX_DRAFT_BODY, allow_newlines=True)
    audience = draft.get("audience", "free")
    if audience == "all":
        audience = "everyone"
    if body_format not in ("markdown", "plain_text") or content_type not in ("article", "note", "podcast", "video") or audience not in ("free", "paid", "everyone"):
        raise AlphaError("Choose a supported manual draft format, content type, and audience.", code="invalid_substack_draft")
    scheduled_for = draft.get("scheduledFor")
    if scheduled_for is not None:
        scheduled_for = _observation_time(scheduled_for, required=True)
    envelope = {
        "publicationUrl": target["publication_url"], "title": title, "body": body,
        "format": body_format, "contentType": content_type, "audience": audience, "scheduledFor": scheduled_for,
    }
    digest = hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        **envelope, "status": "manual_action_required", "contentHash": digest,
        "autoPublished": False, "providerScheduled": False, "providerReceipt": None,
        "schedulingMode": "rafii_editorial_reminder" if scheduled_for else None,
        "renderAs": "text", "bodyHtmlEscaped": html.escape(body, quote=True),
        "mediaPreparationRequired": content_type in ("podcast", "video"),
        "instructions": ("Review the destination, audience, and content, then open your official Substack publication dashboard and complete publication yourself. "
                         + ("This package contains draft text; add and review the required media in Substack. " if content_type in ("podcast", "video") else "")
                         + "This package has not published or scheduled anything on Substack."),
    }


def _metric_name(name):
    if not isinstance(name, str) or not _METRIC_NAME.fullmatch(name):
        raise AlphaError("Use a valid metric name.", code="invalid_substack_metric")
    return name


def _metric_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        raise AlphaError("A metric needs a finite numeric value.", code="invalid_substack_metric")
    return value


def normalize_imported_metric(name, value, *, observed_at, source):
    """Imported values cannot be promoted into verified official API statistics."""
    return {
        "metric": _metric_name(name), "value": _metric_value(value), "provenance": "imported",
        "observedAt": _observation_time(observed_at, required=True),
        "source": _draft_text(source, "metric source", 300), "verifiedOfficial": False,
    }


def unavailable_metric(name, reason):
    return {"metric": _metric_name(name), "value": None, "provenance": "unavailable",
            "reason": _draft_text(reason, "metric explanation", 500), "verifiedOfficial": False}
