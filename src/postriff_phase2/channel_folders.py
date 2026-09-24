"""Channel folders: named, saved sets of connected-account ids (Rafii v9 Channel Bloom).

A folder is a batch-selection shortcut, not a platform, a container or a workflow preset. It
never changes output languages, the model, reasoning, voice, sources or content type; it only
helps choose destinations. Folders live in workspace state (`state["phase2"]["channelFolders"]`),
reach every page through the same snapshot, and change through the single mutation channel
(`POST .../actions`), so tenancy, membership permission (`edit`) and expected-revision
concurrency are the ones every other workspace change already has.

Members are connection ids (`phase2.channels[].id`), never platform names and never
credentials. Deleting a folder neither disconnects nor deselects accounts. A member whose
connection has since been removed stays recorded so the person can see it and decide; it is
reported by the client as missing, never silently dropped or remapped by platform name.

Limits follow the accepted prototype and are enforced here (the client mirrors them):
40-character names, 50 folders per workspace, no nesting.
"""
from __future__ import annotations

import re
import uuid

from postriff_alpha.domain import AlphaError, clean

NAME_MAX = 40
FOLDER_MAX = 50
SYMBOLS = ("folder", "spark", "music", "briefcase", "heart", "globe")
STATE_KEY = "channelFolders"
ACTIONS = ("folder_save", "folder_delete", "folder_move")

_SPACES = re.compile(r"\s+")


def folders(state):
    """The workspace's folder list, created on first use (older states have none)."""
    phase2 = state.setdefault("phase2", {})
    items = phase2.get(STATE_KEY)
    if not isinstance(items, list):
        items = []
        phase2[STATE_KEY] = items
    return items


def connection_ids(state):
    return {c.get("id") for c in (state.get("phase2") or {}).get("channels", []) if isinstance(c, dict) and c.get("id")}


def normalize_name(value):
    return _SPACES.sub(" ", clean(value if isinstance(value, str) else "", 200)).strip()


def validate(payload, existing, valid_ids, keep_ids=()):
    """Return a clean folder record or raise. `keep_ids` are members already stored on this
    folder that may stay even when their connection has gone (an explicit choice, not a drop)."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected a folder.")
    folder_id = payload.get("id") if isinstance(payload.get("id"), str) and payload.get("id") else None
    name = normalize_name(payload.get("name"))
    if not name:
        raise AlphaError("Give your folder a name.")
    if len(name) > NAME_MAX:
        raise AlphaError(f"Keep the folder name within {NAME_MAX} characters.")
    if any(f["id"] != folder_id and f["name"].casefold() == name.casefold() for f in existing):
        raise AlphaError("That folder name is already in use. Try another.")
    raw_ids = payload.get("accountIds")
    if not isinstance(raw_ids, list):
        raise AlphaError("Choose at least one account.")
    account_ids = []
    for value in raw_ids:
        if not isinstance(value, str) or not value or value in account_ids:
            continue
        if value not in valid_ids and value not in keep_ids:
            raise AlphaError("One of the accounts is not connected to this workspace.", 400)
        account_ids.append(value)
    if not account_ids:
        raise AlphaError("Choose at least one account.")
    symbol = payload.get("symbol") if payload.get("symbol") in SYMBOLS else "folder"
    return {"id": folder_id or str(uuid.uuid4()), "name": name, "symbol": symbol, "pinned": payload.get("pinned") is True, "accountIds": account_ids}


def _ordered(items):
    """Pinned folders first, stable within each section (the shelf order)."""
    return sorted(items, key=lambda f: (0 if f.get("pinned") else 1))


def apply_action(state, action, payload, actor, now):
    """Handle the `p2_folder_*` commands (the `p2_` prefix is stripped by the caller)."""
    if action not in ACTIONS:
        return False
    items = folders(state)
    if action == "folder_save":
        record = validate(payload, items, connection_ids(state), keep_ids=next((f["accountIds"] for f in items if f["id"] == payload.get("id")), ()))
        current = next((f for f in items if f["id"] == record["id"]), None)
        if current is None:
            if len(items) >= FOLDER_MAX:
                raise AlphaError(f"This workspace already has {FOLDER_MAX} folders. Delete one before adding another.")
            items.append({**record, "createdAt": now, "createdBy": actor, "updatedAt": now, "updatedBy": actor})
        else:
            current.update({**record, "id": current["id"], "updatedAt": now, "updatedBy": actor})
        return True
    if action == "folder_delete":
        folder_id = payload.get("id")
        if not any(f["id"] == folder_id for f in items):
            raise AlphaError("Folder unavailable.", 404)
        items[:] = [f for f in items if f["id"] != folder_id]
        return True
    if action == "folder_move":
        folder_id, delta = payload.get("id"), payload.get("delta")
        if delta not in (-1, 1):
            raise AlphaError("Move a folder up or down by one place.")
        ordered = _ordered(items)
        index = next((i for i, f in enumerate(ordered) if f["id"] == folder_id), -1)
        if index < 0:
            raise AlphaError("Folder unavailable.", 404)
        target = index + delta
        if target < 0 or target >= len(ordered) or bool(ordered[target].get("pinned")) != bool(ordered[index].get("pinned")):
            return True  # already at the edge of its pinned/unpinned section: nothing to change
        ordered[index], ordered[target] = ordered[target], ordered[index]
        for f in ordered:
            f["updatedAt"] = now
        items[:] = ordered
        return True
    return False


def view(state):
    """Folders with each member's current connection state, for pages that need it server-side."""
    ids = connection_ids(state)
    return [{**f, "members": [{"id": account_id, "connected": account_id in ids} for account_id in f["accountIds"]]} for f in folders(state)]
