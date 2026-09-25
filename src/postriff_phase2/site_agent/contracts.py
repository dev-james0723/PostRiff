"""Typed contracts of the site agent: page context, answer blocks, tool results (site agent §6.1, §9.6, §11.3, §13).

The browser sends a small page-context envelope with each turn. Nothing in it is authority: the route must be in the
route manifest, a selected entity is only an id the server re-reads inside the workspace, and `visibleState` is a few
short display values. The DOM, form values and page text are never accepted. An unknown route makes the context
stale; the answer then says so instead of reasoning about a page the server does not know.
"""
from __future__ import annotations

import datetime as dt
import re

from . import routes

VERSION = 1
MAX_MESSAGE = 4000
ENTITY_TYPES = ("conversation", "source", "automation", "automation_run", "job", "review", "draft", "connection", "asset",
                "memory_proposal", "help_document")
UI_CAPABILITIES = ("navigate", "show_help", "highlight", "focus_composer")
BLOCK_TYPES = ("text", "citation_list", "navigation_card", "diagnostic_card", "proposal_diff", "question_form", "tool_activity",
               "warning", "handoff_card", "error", "operate_result", "result_list")
MAX_VISIBLE_KEYS = 12
_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9]{0,31}$")
_BUILD = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def _visible_value(value):
    if isinstance(value, bool) or (isinstance(value, int) and abs(value) < 10**9):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        return text[:80] if text else None
    if isinstance(value, list):
        items = [_visible_value(item) for item in value[:10]]
        items = [item for item in items if isinstance(item, (str, int)) and not isinstance(item, bool)]
        return items or None
    return None


def page_context(raw) -> dict:
    """The page context, normalised. `issues` names what was dropped; `stale` means the route is unknown."""
    out = {"route": None, "routeId": None, "routeFamily": None, "params": {}, "title": None, "selectedEntity": None,
           "visibleState": {}, "uiCapabilities": [], "clientBuild": None, "stale": False, "issues": []}
    if not isinstance(raw, dict):
        out.update(stale=True, issues=["missing"])
        return out
    route = raw.get("route")
    path = route.split("?")[0].split("#")[0] if isinstance(route, str) else None
    matched = routes.match(path) if path else None
    if matched is None:
        out.update(stale=True, issues=["unknown_route"])
        return out
    entry = matched["route"]
    out.update(route=path.rstrip("/") or "/", routeId=entry["id"], routeFamily=entry["family"], params=matched["params"], title=entry["title"])
    entity = raw.get("selectedEntity")
    if entry["id"] == "conversation":
        out["selectedEntity"] = {"type": "conversation", "id": matched["params"]["conversationId"]}
    elif entry["id"] == "help_article":
        out["selectedEntity"] = {"type": "help_document", "id": matched["params"]["documentId"]}
    elif isinstance(entity, dict) and entity:
        kind, ident = entity.get("type"), entity.get("id")
        if kind in entry.get("entityTypes", []) and isinstance(ident, str) and routes.ID_VALUE.match(ident):
            out["selectedEntity"] = {"type": kind, "id": ident}
        else:
            out["issues"].append("entity_dropped")
    visible = raw.get("visibleState")
    if isinstance(visible, dict):
        for key, value in list(visible.items())[:MAX_VISIBLE_KEYS]:
            cleaned = _visible_value(value) if isinstance(key, str) and _KEY.match(key) else None
            if cleaned is None:
                out["issues"].append("visible_dropped")
            else:
                out["visibleState"][key] = cleaned
    capabilities = raw.get("uiCapabilities")
    if isinstance(capabilities, list):
        out["uiCapabilities"] = [c for c in dict.fromkeys(capabilities) if c in UI_CAPABILITIES][:8]
    build = raw.get("clientBuild")
    if isinstance(build, str) and _BUILD.match(build):
        out["clientBuild"] = build
    out["issues"] = sorted(set(out["issues"]))
    return out


def page_summary(page: dict) -> dict:
    """What is kept of the page context on the message and in traces: ids and labels, never visible values."""
    return {"routeId": page.get("routeId"), "routeFamily": page.get("routeFamily"), "title": page.get("title"),
            "entity": page.get("selectedEntity"), "stale": bool(page.get("stale"))}


def iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def result(data, *, now: float, ok: bool = True, verified: bool = True, source: str = "server", warnings=(), next_actions=()) -> dict:
    """The envelope every site-agent tool returns (§9.6). ok is not verified: a read that could not confirm its
    answer says verified=False and the answer must treat it as unconfirmed."""
    return {"ok": ok, "verified": bool(ok and verified), "observedAt": iso(now), "source": source, "data": data,
            "warnings": [w for w in warnings if w], "nextActions": list(next_actions)}


# --- blocks (§11.3) ---------------------------------------------------------------------------------------------------
def text(value: str) -> dict:
    return {"type": "text", "text": value}


def citations(items: list[dict]) -> dict:
    return {"type": "citation_list", "citations": items}


def navigation(label: str, href: str, route_id: str, *, reason: str | None = None, auto: bool = False) -> dict:
    return {"type": "navigation_card", "label": label, "href": href, "routeId": route_id, "reason": reason, "auto": auto}


def diagnostic(title: str, status: str, *, evidence=(), cause: str | None = None, steps=(), verified: bool = True, links=()) -> dict:
    return {"type": "diagnostic_card", "title": title, "status": status, "evidence": list(evidence), "cause": cause,
            "steps": list(steps), "verified": verified, "links": list(links)}


def question(prompt: str, options=()) -> dict:
    return {"type": "question_form", "prompt": prompt, "options": list(options)[:4]}


def warning(message: str, code: str) -> dict:
    return {"type": "warning", "message": message, "code": code}


def handoff(trace_id: str, summary: list[str], href: str) -> dict:
    return {"type": "handoff_card", "traceId": trace_id, "summary": summary, "href": href}


def error(message: str, code: str) -> dict:
    return {"type": "error", "message": message, "code": code}
