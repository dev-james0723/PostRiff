"""Read-only, explicitly selected Notion and Gmail sources for Rafii turns.

The provider adapters only construct/parse bounded HTTPS calls through an injectable
transport.  The service owns authentication, encrypted token custody, short-lived
picker receipts and the final server-side re-fetch.  There is deliberately no sync,
webhook, workspace crawl or background worker in this module.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from email.header import decode_header, make_header
from urllib.parse import quote, urlencode, urlparse

from postriff_alpha.domain import AlphaError, clean

from .contracts import digest
from .oauth import pkce_pair
from .permissions import require
from .providers import http_transport


PROVIDERS = ("notion", "gmail", "google_calendar")
FLAG_NAMES = {
    "notion": "RAFII_NOTION_CONNECTOR_ENABLED",
    "gmail": "RAFII_GMAIL_CONNECTOR_ENABLED",
    "google_calendar": "RAFII_GOOGLE_CALENDAR_CONNECTOR_ENABLED",
}
OAUTH_TTL = 600
SELECTION_TTL = 600
MAX_RESULTS = 12
MAX_REMOTE_TEXT = 120_000
MAX_CACHED_EXCERPT = 12_000
MAX_FACTS = 40
MAX_FACT_CHARS = 1_200
CONNECTION_ID = re.compile(r"^pc_[0-9a-f]{32}$")
REFERENCE_ID = re.compile(r"^ci_[0-9a-f]{32}$")
CONSENT_ACTION = "connector_egress"
PROCESSORS = ("Rafii's selected writing model",)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def flags_from_environment(values=None):
    values = os.environ if values is None else values
    return {provider: _truthy(values.get(name)) for provider, name in FLAG_NAMES.items()}


def egress_decision(state):
    found = (state or {}).get("connectorEgress")
    return found if isinstance(found, dict) else {"cloud": False, "processors": []}


def apply_connector_egress(state, action, payload, actor, now):
    """Owner-only workspace decision, routed by ``permissions.classify``."""
    if action != CONSENT_ACTION:
        return False
    payload = payload if isinstance(payload, dict) else {}
    if set(payload) - {"cloud", "confirmed"} or not isinstance(payload.get("cloud"), bool) or payload.get("confirmed") is not True:
        raise AlphaError("Choose whether connected text may reach a cloud writer, and confirm it.", 400)
    state["connectorEgress"] = {
        "cloud": payload["cloud"],
        "decidedBy": actor,
        "decidedAt": now,
        "processors": list(PROCESSORS) if payload["cloud"] else [],
    }
    return True


class InvalidGrant(Exception):
    """A refresh grant was permanently rejected and must be revoked locally."""


def _body(response):
    body = response.get("body", {}) if isinstance(response, dict) else {}
    return body if isinstance(body, dict) else {}


def _oauth_body(response):
    body = _body(response)
    if body.get("error") == "invalid_grant":
        raise InvalidGrant()
    if response.get("status") != 200 or not isinstance(body.get("access_token"), str) or not body["access_token"]:
        raise AlphaError("The provider did not complete this authorization step.", 502)
    return body


def _scopes(value):
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(dict.fromkeys(value))
    if isinstance(value, str):
        return list(dict.fromkeys(part for part in re.split(r"[\s,]+", value.strip()) if part))
    return []


def _api_body(response, message="The connected provider could not read this item."):
    if not isinstance(response, dict):
        raise AlphaError(message, 502)
    if response.get("status") == 401:
        raise AlphaError("This connection needs to be refreshed.", 409, code="connector_reauthorization_required")
    body = _body(response)
    if not 200 <= int(response.get("status") or 0) < 300:
        raise AlphaError(message, 502)
    return body


class ProductivityProvider:
    id = ""
    label = ""
    scopes = ()

    def __init__(self, client_id, client_secret, transport=None):
        if not isinstance(client_id, str) or not client_id or not isinstance(client_secret, str) or not client_secret:
            raise AlphaError(f"{self.label} OAuth credentials are required.", 503)
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport or http_transport

    def minimum_scopes(self):
        return list(self.scopes)

    def revoke(self, access_token):
        return False


def _notion_rich_text(value):
    if not isinstance(value, list):
        return ""
    return "".join(str(item.get("plain_text") or "") for item in value if isinstance(item, dict)).strip()


def _notion_title(page):
    properties = page.get("properties") if isinstance(page, dict) else {}
    for prop in (properties or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title = _notion_rich_text(prop.get("title"))
            if title:
                return title
    return "Untitled Notion page"


def extract_notion_blocks(blocks):
    """Flatten only textual Notion block fields; URLs/files and instructions are not followed."""
    lines = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        value = block.get(kind) if isinstance(block.get(kind), dict) else {}
        text = _notion_rich_text(value.get("rich_text"))
        if kind == "to_do" and text:
            text = ("[x] " if value.get("checked") else "[ ] ") + text
        elif kind in ("bulleted_list_item", "numbered_list_item") and text:
            text = "- " + text
        elif kind == "child_page":
            text = clean(value.get("title", ""), 300)
        elif kind == "table_row":
            cells = [_notion_rich_text(cell) for cell in value.get("cells") or []]
            text = " | ".join(cell for cell in cells if cell)
        if text:
            lines.append(text)
        children = block.get("_children")
        if isinstance(children, list):
            lines.extend(extract_notion_blocks(children))
    return "\n".join(lines)[:MAX_REMOTE_TEXT]


class NotionProvider(ProductivityProvider):
    id, label = "notion", "Notion"
    scopes = ("read_content",)
    AUTH = "https://api.notion.com/v1/oauth/authorize"
    TOKEN = "https://api.notion.com/v1/oauth/token"
    SEARCH = "https://api.notion.com/v1/search"
    API = "https://api.notion.com/v1"
    VERSION = "2022-06-28"

    def authorize_url(self, redirect_uri, state, challenge):
        return self.AUTH + "?" + urlencode({
            "owner": "user", "client_id": self.client_id, "response_type": "code",
            "redirect_uri": redirect_uri, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def _basic(self):
        raw = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        return {"Authorization": "Basic " + raw}

    def exchange(self, code, verifier, redirect_uri):
        body = _oauth_body(self.transport("POST", self.TOKEN, headers=self._basic(), body={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }))
        owner = body.get("owner") if isinstance(body.get("owner"), dict) else {}
        user = owner.get("user") if isinstance(owner.get("user"), dict) else {}
        account_id = str(user.get("id") or body.get("workspace_id") or "")
        if not account_id:
            raise AlphaError("Notion did not identify the connected account.", 502)
        return {
            "accessToken": body["access_token"], "refreshToken": body.get("refresh_token"),
            "expiresIn": body.get("expires_in"), "scopes": self.minimum_scopes(),
            "providerAccountId": account_id,
            "accountLabel": clean(body.get("workspace_name") or user.get("name") or "Notion workspace", 160),
        }

    def refresh(self, refresh_token):
        body = _oauth_body(self.transport("POST", self.TOKEN, headers=self._basic(), body={
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }))
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token") or refresh_token,
                "expiresIn": body.get("expires_in"), "scopes": self.minimum_scopes()}

    def _headers(self, access_token):
        return {"Authorization": "Bearer " + access_token, "Notion-Version": self.VERSION}

    def search(self, access_token, query, limit=MAX_RESULTS):
        query = clean(query, 200).strip()
        if not query:
            raise AlphaError("Enter a Notion page name to search.", 400)
        body = _api_body(self.transport("POST", self.SEARCH, headers=self._headers(access_token), body={
            "query": query, "filter": {"property": "object", "value": "page"},
            "page_size": min(MAX_RESULTS, max(1, int(limit))),
        }))
        items = []
        for page in body.get("results") or []:
            if isinstance(page, dict) and page.get("object") == "page" and isinstance(page.get("id"), str):
                items.append({"itemId": page["id"], "title": _notion_title(page), "excerpt": ""})
        return items[:limit]

    def _children(self, access_token, block_id, depth=0, budget=None):
        budget = budget if isinstance(budget, list) else [240]
        if depth > 4 or budget[0] <= 0:
            return []
        output, cursor = [], None
        while budget[0] > 0:
            query_string = {"page_size": min(100, budget[0])}
            if cursor:
                query_string["start_cursor"] = cursor
            url = f"{self.API}/blocks/{quote(block_id, safe='')}/children?{urlencode(query_string)}"
            body = _api_body(self.transport("GET", url, headers=self._headers(access_token)))
            for block in body.get("results") or []:
                if not isinstance(block, dict):
                    continue
                copy = dict(block)
                budget[0] -= 1
                if copy.get("has_children") and isinstance(copy.get("id"), str) and budget[0] > 0:
                    copy["_children"] = self._children(access_token, copy["id"], depth + 1, budget)
                output.append(copy)
                if budget[0] <= 0:
                    break
            if not body.get("has_more") or not isinstance(body.get("next_cursor"), str) or budget[0] <= 0:
                break
            cursor = body["next_cursor"]
        return output

    def get_item(self, access_token, item_id):
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 300:
            raise AlphaError("This connected item is unavailable.", 404)
        page = _api_body(self.transport("GET", f"{self.API}/pages/{quote(item_id, safe='')}", headers=self._headers(access_token)))
        if page.get("object") != "page" or str(page.get("id") or "") != item_id:
            raise AlphaError("This connected item is unavailable.", 404)
        text = extract_notion_blocks(self._children(access_token, item_id))
        return {"itemId": item_id, "title": _notion_title(page), "text": text}


def _b64url(value):
    if not isinstance(value, str):
        return ""
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


_HTML_TAG = re.compile(r"<[^>]+>")


def _plain_html(value):
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value)
    return "\n".join(line.strip() for line in html.unescape(_HTML_TAG.sub(" ", value)).splitlines() if line.strip())


def extract_gmail_message(message):
    """Return subject and readable body from a Gmail ``format=full`` message."""
    payload = message.get("payload") if isinstance(message, dict) and isinstance(message.get("payload"), dict) else {}
    headers = {str(h.get("name") or "").lower(): str(h.get("value") or "") for h in payload.get("headers") or [] if isinstance(h, dict)}
    try:
        subject = str(make_header(decode_header(headers.get("subject") or "Untitled email")))
    except (LookupError, UnicodeError):
        subject = headers.get("subject") or "Untitled email"
    plain, rich = [], []

    def visit(part):
        if not isinstance(part, dict):
            return
        mime = str(part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data") if isinstance(part.get("body"), dict) else None
        decoded = _b64url(data)
        if decoded and mime == "text/plain":
            plain.append(decoded)
        elif decoded and mime == "text/html":
            rich.append(_plain_html(decoded))
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    text = "\n\n".join(part.strip() for part in (plain or rich) if part.strip())
    return {"title": clean(subject, 300) or "Untitled email", "text": text[:MAX_REMOTE_TEXT],
            "from": clean(headers.get("from", ""), 300), "date": clean(headers.get("date", ""), 120)}


class GmailProvider(ProductivityProvider):
    id, label = "gmail", "Gmail"
    GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
    scopes = (GMAIL_READONLY,)
    AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN = "https://oauth2.googleapis.com/token"
    API = "https://gmail.googleapis.com/gmail/v1/users/me"
    REVOKE = "https://oauth2.googleapis.com/revoke"

    def authorize_url(self, redirect_uri, state, challenge):
        return self.AUTH + "?" + urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": self.GMAIL_READONLY, "state": state, "access_type": "offline",
            "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def exchange(self, code, verifier, redirect_uri):
        body = _oauth_body(self.transport("POST", self.TOKEN, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }))
        scopes = _scopes(body.get("scope"))
        if self.GMAIL_READONLY not in scopes:
            raise AlphaError("Gmail read-only permission was not granted.", 409, code="connector_scope_missing")
        profile = _api_body(self.transport("GET", f"{self.API}/profile", headers={"Authorization": "Bearer " + body["access_token"]}))
        address = str(profile.get("emailAddress") or "")
        if not address:
            raise AlphaError("Gmail did not identify the connected account.", 502)
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token"),
                "expiresIn": body.get("expires_in"), "scopes": scopes,
                "providerAccountId": address.lower(), "accountLabel": clean(address, 160)}

    def refresh(self, refresh_token):
        body = _oauth_body(self.transport("POST", self.TOKEN, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }))
        scopes = _scopes(body.get("scope")) or self.minimum_scopes()
        if self.GMAIL_READONLY not in scopes:
            raise InvalidGrant()
        return {"accessToken": body["access_token"], "refreshToken": refresh_token,
                "expiresIn": body.get("expires_in"), "scopes": scopes}

    @staticmethod
    def _headers(access_token):
        return {"Authorization": "Bearer " + access_token}

    def search(self, access_token, query, limit=MAX_RESULTS):
        query = clean(query, 500).strip()
        if not query:
            raise AlphaError("Enter a Gmail search.", 400)
        count = min(MAX_RESULTS, max(1, int(limit)))
        body = _api_body(self.transport("GET", f"{self.API}/messages?{urlencode({'q': query, 'maxResults': count})}", headers=self._headers(access_token)))
        output = []
        for row in body.get("messages") or []:
            item_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(item_id, str):
                continue
            query_string = urlencode([("format", "metadata"), ("metadataHeaders", "Subject"), ("metadataHeaders", "From"), ("metadataHeaders", "Date")])
            message = _api_body(self.transport("GET", f"{self.API}/messages/{quote(item_id, safe='')}?{query_string}", headers=self._headers(access_token)))
            extracted = extract_gmail_message(message)
            output.append({"itemId": item_id, "title": extracted["title"], "excerpt": clean(message.get("snippet", ""), 500),
                           "from": extracted.get("from", ""), "date": extracted.get("date", "")})
        return output[:count]

    def get_item(self, access_token, item_id):
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 300:
            raise AlphaError("This connected item is unavailable.", 404)
        message = _api_body(self.transport("GET", f"{self.API}/messages/{quote(item_id, safe='')}?format=full", headers=self._headers(access_token)))
        if str(message.get("id") or "") != item_id:
            raise AlphaError("This connected item is unavailable.", 404)
        return {"itemId": item_id, **extract_gmail_message(message)}

    def revoke(self, access_token):
        response = self.transport("POST", self.REVOKE, form={"token": access_token})
        return int(response.get("status") or 0) in (200, 204)


class GoogleCalendarProvider(ProductivityProvider):
    """Read-only Google Calendar adapter. Event descriptions/attachments are never fetched for the daily brief."""
    id, label = "google_calendar", "Google Calendar"
    CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
    scopes = (CALENDAR_READONLY,)
    AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN = "https://oauth2.googleapis.com/token"
    API = "https://www.googleapis.com/calendar/v3"
    REVOKE = "https://oauth2.googleapis.com/revoke"

    def authorize_url(self, redirect_uri, state, challenge):
        return self.AUTH + "?" + urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": self.CALENDAR_READONLY, "state": state, "access_type": "offline",
            "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def exchange(self, code, verifier, redirect_uri):
        body = _oauth_body(self.transport("POST", self.TOKEN, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }))
        scopes = _scopes(body.get("scope"))
        if self.CALENDAR_READONLY not in scopes:
            raise AlphaError("Google Calendar read-only permission was not granted.", 409, code="connector_scope_missing")
        primary = _api_body(self.transport("GET", f"{self.API}/calendars/primary", headers={"Authorization": "Bearer " + body["access_token"]}))
        account_id = str(primary.get("id") or "primary")
        return {"accessToken": body["access_token"], "refreshToken": body.get("refresh_token"),
                "expiresIn": body.get("expires_in"), "scopes": scopes,
                "providerAccountId": account_id,
                "accountLabel": clean(primary.get("summary") or "Google Calendar", 160)}

    def refresh(self, refresh_token):
        body = _oauth_body(self.transport("POST", self.TOKEN, form={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }))
        scopes = _scopes(body.get("scope")) or self.minimum_scopes()
        if self.CALENDAR_READONLY not in scopes:
            raise InvalidGrant()
        return {"accessToken": body["access_token"], "refreshToken": refresh_token,
                "expiresIn": body.get("expires_in"), "scopes": scopes}

    @staticmethod
    def _headers(access_token):
        return {"Authorization": "Bearer " + access_token}

    @staticmethod
    def _event(event):
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            return None
        start = event.get("start") if isinstance(event.get("start"), dict) else {}
        end = event.get("end") if isinstance(event.get("end"), dict) else {}
        return {"itemId": event["id"], "title": clean(event.get("summary") or "Busy", 300),
                "start": clean(start.get("dateTime") or start.get("date") or "", 80),
                "end": clean(end.get("dateTime") or end.get("date") or "", 80),
                "location": clean(event.get("location") or "", 300)}

    def events_between(self, access_token, time_min, time_max, limit=12):
        params = urlencode({"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "orderBy": "startTime",
                            "maxResults": min(24, max(1, int(limit)))})
        body = _api_body(self.transport("GET", f"{self.API}/calendars/primary/events?{params}", headers=self._headers(access_token)))
        output = []
        for raw in body.get("items") or []:
            item = self._event(raw)
            if item and raw.get("status") != "cancelled":
                output.append(item)
        return output[:limit]

    def search(self, access_token, query, limit=MAX_RESULTS):
        now = datetime.now(timezone.utc)
        params = {"timeMin": now.isoformat().replace("+00:00", "Z"),
                  "timeMax": (now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": min(MAX_RESULTS, max(1, int(limit)))}
        query = clean(query, 200).strip()
        if query:
            params["q"] = query
        body = _api_body(self.transport("GET", f"{self.API}/calendars/primary/events?{urlencode(params)}", headers=self._headers(access_token)))
        output = []
        for raw in body.get("items") or []:
            item = self._event(raw)
            if item and raw.get("status") != "cancelled":
                output.append({"itemId": item["itemId"], "title": item["title"],
                               "excerpt": " · ".join(v for v in (item["start"], item["location"]) if v)[:500]})
        return output[:limit]

    def get_item(self, access_token, item_id):
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 300:
            raise AlphaError("This connected item is unavailable.", 404)
        raw = _api_body(self.transport("GET", f"{self.API}/calendars/primary/events/{quote(item_id, safe='')}", headers=self._headers(access_token)))
        item = self._event(raw)
        if not item or item["itemId"] != item_id:
            raise AlphaError("This connected item is unavailable.", 404)
        text = "\n".join(v for v in (item["title"], "Start: " + item["start"] if item["start"] else "",
                                          "End: " + item["end"] if item["end"] else "",
                                          "Location: " + item["location"] if item["location"] else "") if v)
        return {"itemId": item_id, "title": item["title"], "text": text}

    def revoke(self, access_token):
        response = self.transport("POST", self.REVOKE, form={"token": access_token})
        return int(response.get("status") or 0) in (200, 204)


def _credential_shape(value):
    return isinstance(value, str) and 0 < len(value) <= 8192 and not any(ch.isspace() for ch in value) and not value.startswith("<")


def providers_from_environment(values, transport=None):
    """Mount configured adapters only; feature flags are checked separately by the service."""
    providers = {}
    classes = (("notion", NotionProvider), ("gmail", GmailProvider), ("google_calendar", GoogleCalendarProvider))
    for provider, cls in classes:
        # Calendar may deliberately reuse the same Google OAuth app as Gmail, but receives its own read-only grant.
        prefixes = [f"RAFII_{provider.upper()}_", f"POSTRIFF_OAUTH_{provider.upper()}_"]
        if provider == "google_calendar":
            prefixes += ["RAFII_GMAIL_", "POSTRIFF_OAUTH_GMAIL_"]
        pair = next(((values.get(prefix + "CLIENT_ID"), values.get(prefix + "CLIENT_SECRET"))
                     for prefix in prefixes if values.get(prefix + "CLIENT_ID") is not None or values.get(prefix + "CLIENT_SECRET") is not None), (None, None))
        client_id, secret = pair
        if _credential_shape(client_id) and _credential_shape(secret):
            providers[provider] = cls(client_id, secret, transport=transport)
    return providers


def _new_id(prefix):
    return prefix + secrets.token_hex(16)


def _facts(text, reference_id):
    output = []
    for paragraph in re.split(r"\n\s*\n|\n(?=[-*] )", text or ""):
        paragraph = " ".join(paragraph.split()).strip()
        if not paragraph:
            continue
        for start in range(0, len(paragraph), MAX_FACT_CHARS):
            part = paragraph[start:start + MAX_FACT_CHARS].strip()
            if part:
                output.append({"id": f"{reference_id}-f{len(output)+1}", "text": part, "approved": True,
                               "locator": f"connected item paragraph {len(output)+1}"})
            if len(output) >= MAX_FACTS:
                return output
    return output


def synthetic_source(provider, reference_id, connection_id, remote, *, cloud=False, now=None):
    text = str(remote.get("text") or "")[:MAX_REMOTE_TEXT]
    return {
        "id": "connector:" + reference_id,
        "kind": "document",
        "title": clean(remote.get("title") or "Connected item", 300),
        "active": True,
        "createdAt": float(time.time() if now is None else now),
        "sourcePolicy": "rewrite_approval",
        "egressConsent": ["local", "cloud"] if cloud else ["local"],
        "useApprovals": [],
        "facts": _facts(text, reference_id),
        "origin": {"kind": "productivity_connector", "provider": provider, "referenceId": reference_id,
                   "connectionId": connection_id, "itemId": remote.get("itemId")},
        "unknowns": ["Fetched on demand from a connected account; review the selected facts before publishing."],
    }


class ProductivityConnectorService:
    """Authenticated service boundary for connection management and explicit picks."""

    def __init__(self, repository, vault, providers=None, public_base_url=None, flags=None, clock=time.time, selection_ttl=SELECTION_TTL):
        self.repository = repository
        self.vault = vault
        self.providers = dict(providers or {})
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.flags = flags_from_environment() if flags is None else {provider: bool((flags or {}).get(provider)) for provider in PROVIDERS}
        self.clock = clock
        self.selection_ttl = min(1800, max(60, int(selection_ttl)))

    def _provider(self, provider_id, *, require_enabled=True):
        if provider_id not in PROVIDERS:
            raise AlphaError("Unknown productivity connector.", 404)
        if require_enabled and not self.flags.get(provider_id, False):
            raise AlphaError("This connector is turned off on this deployment.", 404, code="feature_disabled")
        provider = self.providers.get(provider_id)
        if provider is None:
            raise AlphaError("This connector is not configured.", 503, code="connector_not_configured")
        return provider

    def callback_uri(self, provider_id):
        self._provider(provider_id, require_enabled=False)
        origin = urlparse(self.public_base_url)
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            raise AlphaError("A fixed public HTTPS app origin, without a path or query, is required for OAuth.", 503)
        return f"{self.public_base_url}/api/oauth/{provider_id}/callback"

    @staticmethod
    def callback_redirect(web_base_url, provider_id, query):
        allowed = {key: clean(value, 512) for key, value in (query or {}).items() if key in ("state", "code", "error", "error_description")}
        allowed["provider"] = provider_id
        return f"{web_base_url.rstrip('/')}/connectors/connect?{urlencode(allowed)}"

    @staticmethod
    def _membership(row):
        from .hosted import _membership
        return _membership(row)

    def start(self, workspace_id, token, provider_id):
        provider = self._provider(provider_id)
        redirect = self.callback_uri(provider_id)
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        verifier_ct, key_id = self.vault.encrypt(verifier)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "manage_connections")
            cur.execute("INSERT INTO public.pr_connector_oauth_transactions(workspace_id,member_id,provider,redirect_uri,scopes,state_hash,verifier_ciphertext,key_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) RETURNING id::text",
                        (workspace_id, principal, provider_id, redirect, provider.minimum_scopes(), hashlib.sha256(state.encode()).hexdigest(), verifier_ct, key_id, self.clock() + OAUTH_TTL))
            transaction_id = cur.fetchone()[0]
        return {"transactionId": transaction_id, "provider": provider_id, "authorizeUrl": provider.authorize_url(redirect, state, challenge),
                "scopes": provider.minimum_scopes(), "expiresAt": self.clock() + OAUTH_TTL}

    def complete(self, workspace_id, token, provider_id, state, code, error=None):
        provider = self._provider(provider_id)
        if not isinstance(state, str) or not 20 <= len(state) <= 128:
            raise AlphaError("Connection request unavailable.", 404)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "manage_connections")
            cur.execute("SELECT id::text,member_id::text,provider,redirect_uri,scopes,verifier_ciphertext,key_id,extract(epoch from expires_at),consumed_at IS NOT NULL FROM public.pr_connector_oauth_transactions WHERE workspace_id=%s AND state_hash=%s FOR UPDATE",
                        (workspace_id, hashlib.sha256(state.encode()).hexdigest()))
            found = cur.fetchone()
            if not found:
                raise AlphaError("Connection request unavailable.", 404)
            transaction_id, member_id, stored_provider, redirect, requested, verifier_ct, key_id, expires_at, consumed = found
            if consumed or stored_provider != provider_id or member_id != str(principal):
                cur.execute("UPDATE public.pr_connector_oauth_transactions SET consumed_at=coalesce(consumed_at,now()),outcome=coalesce(outcome,'mismatch') WHERE id::text=%s", (transaction_id,))
                raise AlphaError("Connection request unavailable.", 404)
            if expires_at <= self.clock():
                cur.execute("UPDATE public.pr_connector_oauth_transactions SET consumed_at=now(),outcome='expired' WHERE id::text=%s", (transaction_id,))
                raise AlphaError("This connection request expired. Start again.", 409)
            if error or not isinstance(code, str) or not code:
                cur.execute("UPDATE public.pr_connector_oauth_transactions SET consumed_at=now(),outcome='denied' WHERE id::text=%s", (transaction_id,))
                return {"connected": False, "reason": "denied"}
            verifier = self.vault.decrypt(verifier_ct, key_id)
            grant = provider.exchange(code, verifier, redirect)
            granted = _scopes(grant.get("scopes"))
            if set(requested or ()) - set(granted):
                raise AlphaError("The required read-only permission was not granted.", 409, code="connector_scope_missing")
            account_id = str(grant.get("providerAccountId") or "")
            if not account_id:
                raise AlphaError("The provider did not identify the connected account.", 502)
            cur.execute("SELECT connection_id FROM public.pr_connector_credentials WHERE workspace_id=%s AND member_id=%s AND provider=%s AND provider_account_id=%s",
                        (workspace_id, principal, provider_id, account_id))
            existing = cur.fetchone()
            connection_id = existing[0] if existing else _new_id("pc_")
            access_ct, token_key_id = self.vault.encrypt(grant["accessToken"])
            refresh_ct = self.vault.encrypt(grant["refreshToken"])[0] if grant.get("refreshToken") else None
            expires_at = self.clock() + float(grant.get("expiresIn") or 0) if grant.get("expiresIn") else None
            cur.execute("INSERT INTO public.pr_connector_credentials(workspace_id,connection_id,member_id,provider,provider_account_id,account_label,access_ciphertext,refresh_ciphertext,key_id,scopes,access_expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT(workspace_id,member_id,provider,provider_account_id) DO UPDATE SET account_label=excluded.account_label,access_ciphertext=excluded.access_ciphertext,refresh_ciphertext=coalesce(excluded.refresh_ciphertext,public.pr_connector_credentials.refresh_ciphertext),key_id=excluded.key_id,scopes=excluded.scopes,access_expires_at=excluded.access_expires_at,revoked_at=NULL,updated_at=now()",
                        (workspace_id, connection_id, principal, provider_id, account_id, clean(grant.get("accountLabel") or provider.label, 160), access_ct, refresh_ct, token_key_id, granted, expires_at))
            cur.execute("UPDATE public.pr_connector_oauth_transactions SET consumed_at=now(),outcome='exchanged' WHERE id::text=%s", (transaction_id,))
        return {"connected": True, "connectionId": connection_id, "provider": provider_id,
                "account": clean(grant.get("accountLabel") or provider.label, 160), "scopes": granted,
                "expiresAt": expires_at}

    def catalog(self, workspace_id, token):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "read")
            cur.execute("SELECT connection_id,provider,account_label,scopes,extract(epoch from access_expires_at),revoked_at IS NOT NULL FROM public.pr_connector_credentials WHERE workspace_id=%s AND member_id=%s ORDER BY created_at", (workspace_id, principal))
            connections = [{"connectionId": item[0], "provider": item[1], "account": item[2], "scopes": list(item[3] or []),
                            "expiresAt": item[4], "revoked": bool(item[5])} for item in cur.fetchall()]
        return {"providers": [{"id": pid, "enabled": bool(self.flags.get(pid)), "configured": pid in self.providers,
                               "scopes": list(getattr(self.providers.get(pid), "scopes", ()))} for pid in PROVIDERS],
                "connections": connections}

    def _connection(self, cur, workspace_id, principal, connection_id, *, lock=False):
        if not isinstance(connection_id, str) or not CONNECTION_ID.match(connection_id):
            return None
        cur.execute("SELECT connection_id,provider,account_label,access_ciphertext,refresh_ciphertext,key_id,scopes,extract(epoch from access_expires_at),revoked_at IS NOT NULL FROM public.pr_connector_credentials WHERE workspace_id=%s AND member_id=%s AND connection_id=%s" + (" FOR UPDATE" if lock else ""),
                    (workspace_id, principal, connection_id))
        found = cur.fetchone()
        if not found:
            return None
        return {"connectionId": found[0], "provider": found[1], "account": found[2], "accessCiphertext": found[3],
                "refreshCiphertext": found[4], "keyId": found[5], "scopes": list(found[6] or []),
                "expiresAt": found[7], "revoked": bool(found[8])}

    @staticmethod
    def _purge(cur, workspace_id, connection_id):
        cur.execute("DELETE FROM public.pr_connector_selections WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))

    @staticmethod
    def _purge_expired(cur, workspace_id, principal):
        cur.execute("DELETE FROM public.pr_connector_selections WHERE workspace_id=%s AND member_id=%s AND expires_at<=now()", (workspace_id, principal))

    def _mark_revoked(self, cur, workspace_id, connection_id):
        cur.execute("UPDATE public.pr_connector_credentials SET revoked_at=coalesce(revoked_at,now()),access_ciphertext='',refresh_ciphertext=NULL,updated_at=now() WHERE workspace_id=%s AND connection_id=%s", (workspace_id, connection_id))
        self._purge(cur, workspace_id, connection_id)

    def _refresh_locked(self, cur, workspace_id, connection):
        provider = self._provider(connection["provider"])
        if not connection.get("refreshCiphertext"):
            self._mark_revoked(cur, workspace_id, connection["connectionId"])
            raise AlphaError("Reconnect this account to continue.", 409, code="connector_reauthorization_required")
        refresh_token = self.vault.decrypt(connection["refreshCiphertext"], connection["keyId"])
        try:
            grant = provider.refresh(refresh_token)
        except InvalidGrant as error:
            self._mark_revoked(cur, workspace_id, connection["connectionId"])
            raise AlphaError("Reconnect this account to continue.", 409, code="connector_reauthorization_required") from error
        access_ct, key_id = self.vault.encrypt(grant["accessToken"])
        refresh_ct = self.vault.encrypt(grant.get("refreshToken") or refresh_token)[0]
        expires_at = self.clock() + float(grant.get("expiresIn") or 0) if grant.get("expiresIn") else None
        scopes = _scopes(grant.get("scopes")) or connection["scopes"]
        if set(provider.minimum_scopes()) - set(scopes):
            self._mark_revoked(cur, workspace_id, connection["connectionId"])
            raise AlphaError("Reconnect this account to continue.", 409, code="connector_scope_missing")
        cur.execute("UPDATE public.pr_connector_credentials SET access_ciphertext=%s,refresh_ciphertext=%s,key_id=%s,scopes=%s,access_expires_at=to_timestamp(%s),updated_at=now() WHERE workspace_id=%s AND connection_id=%s",
                    (access_ct, refresh_ct, key_id, scopes, expires_at, workspace_id, connection["connectionId"]))
        connection.update(accessCiphertext=access_ct, refreshCiphertext=refresh_ct, keyId=key_id, scopes=scopes, expiresAt=expires_at)
        return grant["accessToken"]

    def _access_token(self, cur, workspace_id, connection):
        if connection["revoked"]:
            raise AlphaError("This connected account is unavailable.", 409, code="connector_reauthorization_required")
        if connection.get("expiresAt") is not None and connection["expiresAt"] <= self.clock() + 30:
            return self._refresh_locked(cur, workspace_id, connection)
        return self.vault.decrypt(connection["accessCiphertext"], connection["keyId"])

    def refresh(self, workspace_id, token, connection_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "manage_connections")
            connection = self._connection(cur, workspace_id, principal, connection_id, lock=True)
            if not connection:
                raise AlphaError("Connected account unavailable.", 404)
            self._refresh_locked(cur, workspace_id, connection)
            return {"connectionId": connection_id, "provider": connection["provider"], "refreshed": True,
                    "expiresAt": connection.get("expiresAt")}

    def disconnect(self, workspace_id, token, connection_id):
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "manage_connections")
            connection = self._connection(cur, workspace_id, principal, connection_id, lock=True)
            if not connection:
                raise AlphaError("Connected account unavailable.", 404)
            access_token = None if connection["revoked"] else self.vault.decrypt(connection["accessCiphertext"], connection["keyId"])
            self._mark_revoked(cur, workspace_id, connection_id)
        revoked_remotely = False
        if access_token:
            try:
                revoked_remotely = bool(self._provider(connection["provider"], require_enabled=False).revoke(access_token))
            except Exception:
                revoked_remotely = False
        return {"connectionId": connection_id, "provider": connection["provider"], "disconnected": True,
                "providerRevocationPending": not revoked_remotely}

    def picker_search(self, workspace_id, token, connection_id, query, limit=MAX_RESULTS):
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise AlphaError(f"Choose between 1 and {MAX_RESULTS} results.", 400)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "read")
            self._purge_expired(cur, workspace_id, principal)
            connection = self._connection(cur, workspace_id, principal, connection_id, lock=True)
            if not connection:
                raise AlphaError("Connected account unavailable.", 404)
            provider = self._provider(connection["provider"])
            access_token = self._access_token(cur, workspace_id, connection)
            items = provider.search(access_token, query, limit)
            expires_at = self.clock() + self.selection_ttl
            receipts = []
            for item in items:
                reference_id = _new_id("ci_")
                title = clean(item.get("title") or "Connected item", 300)
                excerpt = clean(item.get("excerpt") or "", 500)
                cur.execute("INSERT INTO public.pr_connector_selections(workspace_id,member_id,reference_id,connection_id,provider,item_id,title,content_digest,excerpt,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,to_timestamp(%s))",
                            (workspace_id, principal, reference_id, connection_id, connection["provider"], item["itemId"], title, excerpt or None, expires_at))
                receipts.append({"referenceId": reference_id, "connectionId": connection_id, "provider": connection["provider"],
                                 "title": title, "excerpt": excerpt, "expiresAt": expires_at})
            return {"connectionId": connection_id, "provider": connection["provider"], "items": receipts}

    def _selection(self, cur, workspace_id, principal, reference_id):
        cur.execute("SELECT s.reference_id,s.connection_id,s.provider,s.item_id,s.title,c.account_label,c.access_ciphertext,c.refresh_ciphertext,c.key_id,c.scopes,extract(epoch from c.access_expires_at),c.revoked_at IS NOT NULL FROM public.pr_connector_selections s JOIN public.pr_connector_credentials c ON c.workspace_id=s.workspace_id AND c.connection_id=s.connection_id AND c.member_id=s.member_id AND c.provider=s.provider WHERE s.workspace_id=%s AND s.member_id=%s AND s.reference_id=%s AND s.expires_at>now() FOR UPDATE OF s,c",
                    (workspace_id, principal, reference_id))
        found = cur.fetchone()
        if not found:
            return None
        connection = {"connectionId": found[1], "provider": found[2], "account": found[5], "accessCiphertext": found[6],
                      "refreshCiphertext": found[7], "keyId": found[8], "scopes": list(found[9] or []),
                      "expiresAt": found[10], "revoked": bool(found[11])}
        return {"referenceId": found[0], "connection": connection, "provider": found[2], "itemId": found[3], "title": found[4]}

    def turn_refetch(self, workspace_id, token, reference_ids, request_digest, *, provider_class="cloud"):
        if not isinstance(reference_ids, list) or len(reference_ids) > MAX_RESULTS or len(set(reference_ids)) != len(reference_ids):
            raise AlphaError("Choose at most 12 distinct connected items.", 400)
        if not isinstance(request_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", request_digest):
            raise AlphaError("The connector fetch is not bound to this turn.", 409)
        if provider_class not in ("local", "cloud"):
            raise AlphaError("Unsupported provider class.", 400)
        results, providers = {}, []
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._membership(row), "edit")
            self._purge_expired(cur, workspace_id, principal)
            state = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            cloud = egress_decision(state).get("cloud") is True
            for reference_id in reference_ids:
                if not isinstance(reference_id, str) or not REFERENCE_ID.match(reference_id):
                    results[reference_id] = {"reason": "connector_unavailable"}
                    continue
                selection = self._selection(cur, workspace_id, principal, reference_id)
                if not selection:
                    results[reference_id] = {"reason": "connector_unavailable"}
                    continue
                provider_id = selection["provider"]
                label = clean(selection["title"], 300)
                providers.append(provider_id)
                if not self.flags.get(provider_id, False):
                    results[reference_id] = {"label": label, "reason": "connector_disabled"}
                    continue
                provider = self.providers.get(provider_id)
                if provider is None:
                    results[reference_id] = {"label": label, "reason": "connector_disabled"}
                    continue
                try:
                    access_token = self._access_token(cur, workspace_id, selection["connection"])
                    remote = provider.get_item(access_token, selection["itemId"])
                except AlphaError as error:
                    results[reference_id] = {"label": label, "reason": "connector_fetch_failed"}
                    if error.code in ("connector_reauthorization_required", "connector_scope_missing"):
                        self._mark_revoked(cur, workspace_id, selection["connection"]["connectionId"])
                    continue
                source = synthetic_source(provider_id, reference_id, selection["connection"]["connectionId"], remote,
                                          cloud=cloud, now=self.clock())
                excerpt = str(remote.get("text") or "")[:MAX_CACHED_EXCERPT]
                content_digest = hashlib.sha256(str(remote.get("text") or "").encode()).hexdigest()
                cur.execute("UPDATE public.pr_connector_selections SET title=%s,content_digest=%s,excerpt=%s,fetched_at=now() WHERE workspace_id=%s AND member_id=%s AND reference_id=%s",
                            (source["title"], content_digest, excerpt or None, workspace_id, principal, reference_id))
                results[reference_id] = {"label": source["title"], "provider": provider_id, "source": source}
            cur.execute("INSERT INTO public.pr_connector_fetches(workspace_id,member_id,request_digest,reference_ids,providers,fetched_count) VALUES(%s,%s,%s,%s,%s,%s)",
                        (workspace_id, principal, request_digest, list(reference_ids), list(dict.fromkeys(providers)),
                         sum(1 for item in results.values() if item.get("source"))))
        return results

    def daily_brief_context(self, workspace_id, principal, time_zone):
        """Internal, bounded read for James Daily Call. No message body or calendar description is fetched.

        This method has no HTTP route. The caller must already be a trusted server-side worker bound to the configured
        user/workspace. It reuses encrypted OAuth custody and returns only short display metadata plus opaque source ids.
        Provider text is data, never instructions.
        """
        try:
            zone = ZoneInfo(time_zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise AlphaError("Choose a valid time zone.", 400) from None
        local = datetime.fromtimestamp(self.clock(), zone)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        to_utc = lambda value: value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        out = {"generatedAt": self.clock(), "timeZone": time_zone,
               "gmail": {"status": "unavailable", "items": []},
               "calendar": {"status": "unavailable", "items": []}}
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id "
                        "WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, principal))
            if not cur.fetchone():
                raise AlphaError("Workspace unavailable.", 403)
            for provider_id, bucket in (("gmail", "gmail"), ("google_calendar", "calendar")):
                if not self.flags.get(provider_id, False):
                    out[bucket]["status"] = "disabled"
                    continue
                if provider_id not in self.providers:
                    out[bucket]["status"] = "unconfigured"
                    continue
                cur.execute("SELECT connection_id FROM public.pr_connector_credentials WHERE workspace_id=%s AND member_id=%s "
                            "AND provider=%s AND revoked_at IS NULL ORDER BY updated_at DESC LIMIT 1", (workspace_id, principal, provider_id))
                row = cur.fetchone()
                if not row:
                    out[bucket]["status"] = "not_connected"
                    continue
                connection = self._connection(cur, workspace_id, principal, row[0], lock=True)
                try:
                    access = self._access_token(cur, workspace_id, connection)
                    provider = self.providers[provider_id]
                    if provider_id == "gmail":
                        primary = provider.search(access, "in:inbox newer_than:7d {is:important is:starred} -category:promotions -category:social", 6)
                        if not primary:
                            primary = provider.search(access, "in:inbox newer_than:1d -category:promotions -category:social", 6)
                        out[bucket]["items"] = [{"sourceId": "gmail:" + str(item["itemId"])[:180],
                                                  "subject": clean(item.get("title") or "Email", 240),
                                                  "from": clean(item.get("from") or "", 160),
                                                  "snippet": clean(item.get("excerpt") or "", 360),
                                                  "date": clean(item.get("date") or "", 100)} for item in primary[:6]]
                    else:
                        events = provider.events_between(access, to_utc(day_start), to_utc(day_end), 12)
                        out[bucket]["items"] = [{"sourceId": "gcal:" + str(item["itemId"])[:180],
                                                  "title": clean(item.get("title") or "Busy", 240),
                                                  "start": clean(item.get("start") or "", 80),
                                                  "end": clean(item.get("end") or "", 80),
                                                  "location": clean(item.get("location") or "", 240)} for item in events[:12]]
                    out[bucket]["status"] = "ok"
                except AlphaError as error:
                    out[bucket]["status"] = "reauthorization_required" if error.code in ("connector_reauthorization_required", "connector_scope_missing") else "unavailable"
                except Exception:
                    out[bucket]["status"] = "unavailable"
            db.commit()
        return out

    def revoke_workspace(self, workspace_id):
        """Best-effort provider revocation before workspace cascade deletes encrypted rows."""
        pending = []
        with self.repository.connection_factory() as db, db.cursor() as cur:
            cur.execute("SELECT connection_id,provider,access_ciphertext,key_id FROM public.pr_connector_credentials WHERE workspace_id=%s AND revoked_at IS NULL", (workspace_id,))
            rows = cur.fetchall()
        for connection_id, provider_id, ciphertext, key_id in rows:
            try:
                access_token = self.vault.decrypt(ciphertext, key_id)
                revoked = bool(self._provider(provider_id, require_enabled=False).revoke(access_token))
            except Exception:
                revoked = False
            if not revoked and provider_id not in pending:
                pending.append(provider_id)
        return pending


__all__ = [
    "CONSENT_ACTION", "FLAG_NAMES", "GmailProvider", "GoogleCalendarProvider", "InvalidGrant", "NotionProvider",
    "ProductivityConnectorService", "ProductivityProvider", "apply_connector_egress",
    "egress_decision", "extract_gmail_message", "extract_notion_blocks", "flags_from_environment",
    "providers_from_environment", "synthetic_source",
]
