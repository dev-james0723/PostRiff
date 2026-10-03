"""Read-only Kynlo Project Pulse client for James Daily Call.

This client accepts only a dedicated HTTPS endpoint and a dedicated bearer secret.
It never exposes device credentials, terminal access, file contents, approvals, or
raw Mission Control events to the Daily Call runtime.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from postriff_alpha.domain import AlphaError


MAX_BODY = 64 * 1024
MAX_ITEMS = 12


def _enabled(value):
    return str(value or "").lower() in ("1", "true", "yes", "on")


def _bounded(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _http_json(url, token, timeout=5):
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "User-Agent": "James-Daily-Call-Project-Pulse/1",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        if int(getattr(response, "status", 0) or 0) != 200:
            raise ValueError("unexpected status")
        raw = response.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("response too large")
    return json.loads(raw.decode("utf-8"))


class ProjectPulseClient:
    def __init__(self, values, transport=None):
        self.values = dict(values or {})
        self.transport = transport or _http_json

    @property
    def enabled(self):
        return _enabled(self.values.get("JAMES_PROJECT_PULSE_ENABLED"))

    def _endpoint(self):
        value = str(self.values.get("JAMES_PROJECT_PULSE_URL") or "").strip()
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/internal/project-pulse"
        ):
            raise AlphaError("Project Pulse endpoint is not configured.", 503, code="project_pulse_unconfigured")
        return value

    def _token(self):
        value = str(self.values.get("JAMES_PROJECT_PULSE_TOKEN") or "")
        if len(value) < 32 or len(value) > 512 or any(ch.isspace() for ch in value):
            raise AlphaError("Project Pulse credential is not configured.", 503, code="project_pulse_unconfigured")
        return value

    def fetch(self):
        if not self.enabled:
            return {"status": "disabled", "items": []}
        try:
            payload = self.transport(self._endpoint(), self._token(), 5)
        except urllib.error.HTTPError as error:
            status = "unauthorized" if error.code in (401, 403) else "unavailable"
            return {"status": status, "items": []}
        except (AlphaError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"status": "unavailable", "items": []}
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return {"status": "unavailable", "items": []}
        rows = payload.get("missions")
        if not isinstance(rows, list):
            return {"status": "unavailable", "items": []}

        items = []
        seen = set()
        for raw in rows[:40]:
            if not isinstance(raw, dict):
                continue
            title = _bounded(raw.get("title"), 140)
            if not title:
                continue
            item = {
                "title": title,
                "project": _bounded(raw.get("projectKey"), 100),
                "branch": _bounded(raw.get("branch"), 120),
                "state": _bounded(raw.get("state"), 40),
                "verification": _bounded(raw.get("verificationState"), 80),
                "nextAction": _bounded(raw.get("nextAction"), 200),
                "client": _bounded(raw.get("client"), 24),
                "updatedAt": _bounded(raw.get("updatedAt"), 60),
            }
            dedupe = (item["project"], item["title"], item["state"], item["nextAction"])
            if dedupe in seen:
                continue
            seen.add(dedupe)
            items.append(item)
            if len(items) >= MAX_ITEMS:
                break
        return {"status": "ok", "items": items}
