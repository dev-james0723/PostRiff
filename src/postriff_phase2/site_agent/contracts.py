"""Typed contracts of the site agent: page context, answer blocks, tool results (site agent §6.1, §9.6, §11.3, §13).

The browser sends a small page-context envelope with each turn. Nothing in it is authority: the route must be in the
route manifest, a selected entity is only an id the server re-reads inside the workspace, and `visibleState` is a few
short display values. The DOM, form values and page text are never accepted. An unknown route makes the context
stale; the answer then says so instead of reasoning about a page the server does not know.

`outline` (Rafii live agent, Contract 3) is the labels of what is visible on the screen: headings, buttons, tabs,
statuses, links, regions and dialogs, never input values or private areas. It is untrusted data: every label is
re-capped here, and one that reads like an instruction is dropped.
"""
from __future__ import annotations

import datetime as dt
import re

from . import routes

VERSION = 1
MAX_MESSAGE = 4000
ENTITY_TYPES = ("conversation", "source", "automation", "automation_run", "job", "review", "draft", "connection", "asset",
                "memory_proposal", "help_document")
UI_CAPABILITIES = ("navigate", "show_help", "highlight", "focus_composer", "guide", "voice")
BLOCK_TYPES = ("text", "citation_list", "navigation_card", "diagnostic_card", "proposal_diff", "question_form", "tool_activity",
               "warning", "handoff_card", "error", "operate_result", "result_list", "calendar_card", "guide_card", "voice_command")
VOICE_COMMANDS = ("end_call", "mute", "stop_speaking", "style")
MAX_VISIBLE_KEYS = 12
_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9]{0,31}$")
_BUILD = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

# --- the page outline (Contract 3) ---------------------------------------------------------------------------------------
OUTLINE_ROLES = ("heading", "button", "tab", "status", "link", "region", "dialog")
OUTLINE_STATES = ("selected", "disabled", "expanded", "checked")
MAX_OUTLINE_ITEMS = 40
MAX_OUTLINE_TEXT = 80
MAX_OUTLINE_CHARS = 3000
_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_INVISIBLE = re.compile(r"[­​-‏‪-‮⁠-⁤﻿]")   # zero-width and direction marks hide words from the check
# A label is a few words naming something on the screen. One that addresses a model, or carries markup or code, is dropped.
_INSTRUCTION_LIKE = re.compile(r"\bignore\b|\bsystem\b|\byou\s+are\b|\binstructions?\b|\bdisregard\b|\bjailbreak\b|\bprompt\s+injection\b"
                               r"|指示|忽略|無視|无视|系統提示|系统提示|```|<\s*/?\s*[a-z]", re.I)


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


def outline(raw) -> list[dict]:
    """The visible screen labels, re-validated (Contract 3): at most 40 items and about 3,000 characters, roles and
    states from the allowlists, each label cut to 80 characters, a `target` only when it is a plain data-tour id, and
    any label that looks like an instruction (or markup, or code) dropped. Idempotent: re-running it changes nothing."""
    if not isinstance(raw, list):
        return []
    out, total = [], 0
    for item in raw[:MAX_OUTLINE_ITEMS]:
        if not isinstance(item, dict) or item.get("role") not in OUTLINE_ROLES or not isinstance(item.get("text"), str):
            continue
        label = " ".join(_CONTROL.sub(" ", _INVISIBLE.sub("", item["text"])).split())[:MAX_OUTLINE_TEXT].strip()
        if not label or _INSTRUCTION_LIKE.search(label):
            continue
        entry = {"role": item["role"], "text": label}
        target = item.get("target")
        if isinstance(target, str) and _TARGET.match(target):
            entry["target"] = target
        if item.get("state") in OUTLINE_STATES:
            entry["state"] = item["state"]
        size = sum(len(value) for value in entry.values())
        if total + size > MAX_OUTLINE_CHARS:
            break
        total += size
        out.append(entry)
    return out


def page_context(raw) -> dict:
    """The page context, normalised. `issues` names what was dropped; `stale` means the route is unknown."""
    out = {"route": None, "routeId": None, "routeFamily": None, "params": {}, "title": None, "selectedEntity": None,
           "visibleState": {}, "uiCapabilities": [], "clientBuild": None, "outline": [], "stale": False, "issues": []}
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
    screen = raw.get("outline")
    if screen is not None:
        out["outline"] = outline(screen)
        if not isinstance(screen, list) or len(out["outline"]) < len(screen):
            out["issues"].append("outline_dropped")
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


def guide_card(guide_id: str, route_id: str, href: str, title: str, summary: str, *, auto: bool = False) -> dict:
    """A step-by-step guide the panel can run on the screen (Contract 2); `auto` when the person asked to be shown."""
    return {"type": "guide_card", "guideId": guide_id, "routeId": route_id, "href": href, "title": title, "summary": summary, "auto": bool(auto)}


def voice_command(command: str, style: dict | None = None) -> dict:
    """A panel control the voice session executes (Contract 2): end_call, mute, stop_speaking, or style with its patch."""
    if command not in VOICE_COMMANDS:
        raise ValueError(f"unknown voice command {command!r}")
    return {"type": "voice_command", "command": command, **({"style": dict(style)} if command == "style" and style else {})}


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


def calendar_card(*, range_view: dict, statuses: list[dict], entries: list[dict], total: int | None, queue: dict, sources: dict, href: str | None) -> dict:
    """A structured, read-only calendar view.

    It deliberately has no action field.  The only optional destination is an allowlisted page link;
    scheduling, approval, editing and publishing remain on their existing product surfaces.
    """
    shown = entries[:6]
    return {"type": "calendar_card", "range": range_view, "statuses": statuses, "entries": shown, "total": total,
            "truncated": isinstance(total, int) and total > len(shown), "queue": queue, "sources": sources, "href": href}
