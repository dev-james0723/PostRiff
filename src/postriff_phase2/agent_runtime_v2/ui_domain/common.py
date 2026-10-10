"""Shared plumbing of lane D's domain adapters: one request's domain context, a service view bound to the request's
single transaction, opaque cursors, bounded time windows and exact time zones.

The bound service matters for correctness, not style. `ui_transaction` holds the workspace row lock (`FOR UPDATE OF w`)
for the whole request. Every existing service method that takes `(workspace_id, token)` opens its *own* transaction on a
new connection and would wait for that lock forever. `bind()` returns a shallow copy of the service whose repository
re-selects the same member row on the request's cursor instead (the same SELECT `PostgresWorkspaceRepository.transaction`
runs, minus the session verification that `ui_transaction` already did). Existing readers and commands
(`repository.get/command`, `UniversalLibrary.list/detail`, `HostedLearning.proposals/decide`, …) therefore run unchanged,
inside the one transaction, so a domain command and its `pr_ui_actions` receipt commit or roll back together.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

from .. import ui_contracts

DAY = 86400


@dataclass
class DomainContext:
    """Everything a binding handler may use for one request. `state` is this member's view of the workspace, read in
    the request's transaction; `artifact` is the persisted presentation the request names (never client input)."""
    runtime: Any
    cur: Any
    auth: Any                                   # ui_http.UiAuth
    workspace_id: str
    principal: str
    member: Any                                 # permissions.Membership (current, re-read)
    state: dict
    revision: int
    artifact: dict
    manifest: dict
    now: float
    zone: str = "UTC"
    founder: dict | None = None                 # founder scope only: {principal, mode, environment, control}
    _bound: Any = None
    notes: list = field(default_factory=list)

    @property
    def service(self):
        if self._bound is None:
            self._bound = bind(self.runtime.service, self.cur, self.principal, self.workspace_id)
        return self._bound

    def refresh_state(self) -> dict:
        """Re-read the workspace inside the same transaction (after a command), for verification."""
        self.cur.execute("SELECT revision,state FROM public.pr_workspaces WHERE id=%s", (self.workspace_id,))
        row = self.cur.fetchone()
        if not row:
            raise AlphaError("Workspace unavailable.", 403)
        self.revision = int(row[0])
        self.state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        return self.state

    def site_context(self):
        from ...site_agent import tools as site_tools
        return site_tools.Context(state=self.state, membership=self.member, principal=self.principal, workspace_id=self.workspace_id, cur=self.cur,
                                  service=self.service, now=self.now, page={}, model_id=None, zone=self.zone)


def bind(service, cur, principal: str, workspace_id: str):
    """A view of `service` whose repository runs every transaction/command on `cur` (see the module docstring)."""
    from ...hosted import MEMBER_COLUMNS
    repository = copy.copy(service.repository)

    @contextmanager
    def transaction(_token, requested_workspace, *, allow_deleting=False):
        _ = allow_deleting
        if requested_workspace != workspace_id:
            raise AlphaError("Workspace unavailable.", 403)
        cur.execute(f"SELECT w.revision,w.state,{MEMBER_COLUMNS} FROM public.pr_workspaces w JOIN public.pr_memberships m ON m.workspace_id=w.id "
                    "JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE w.id=%s AND m.user_id=%s AND m.status='active' AND p.deleted_at IS NULL FOR UPDATE OF w",
                    (workspace_id, principal))
        row = cur.fetchone()
        if not row:
            raise AlphaError("Workspace unavailable.", 403)
        from .. import authz
        authz.recheck_transaction(cur, workspace_id, principal, row)
        yield cur, row, principal

    def assert_fresh(_token, _principal):
        # No generated control reaches a step-up action (they are excluded from every manifest); refuse if one ever tried.
        raise AlphaError("Sign in again on the page itself to confirm this sensitive action.", 403, code="step_up_required")

    repository.transaction = transaction
    repository.assert_fresh = assert_fresh
    bound = copy.copy(service)
    bound.repository = repository
    library = getattr(service, "library", None)
    if library is not None:
        bound.library = copy.copy(library)
        bound.library.service = bound
    return bound


# --- references ------------------------------------------------------------------------------------------------------
def ref(kind: str, ident) -> str:
    return f"{kind}:{ident}"


# --- time --------------------------------------------------------------------------------------------------------------
def iso(epoch) -> str | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def zone(value, default: str = "UTC") -> str:
    """An exact IANA zone. A malformed zone is refused (never silently swapped), an absent one is the default."""
    if value is None:
        return default
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise AlphaError("Choose a valid time zone.", 400, code="ui_zone")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise AlphaError("Choose a valid time zone.", 400, code="ui_zone") from None
    return value


def local(epoch, zone_name: str) -> str | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    return dt.datetime.fromtimestamp(epoch, ZoneInfo(zone_name)).strftime("%Y-%m-%dT%H:%M")


def offset(epoch, zone_name: str) -> str | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    return dt.datetime.fromtimestamp(epoch, ZoneInfo(zone_name)).strftime("%z")


def window(inputs: dict, zone_name: str, now: float, *, default_days: int = 7, max_days: int | None = None) -> tuple[float, float]:
    """[start, end) epoch seconds from `start`/`end` dates (YYYY-MM-DD, inclusive end date) in `zone_name`. At most
    BOUNDS.queryWindowDays (or a narrower existing bound) long; a reversed or oversized window is refused, never clipped."""
    limit = min(max_days or ui_contracts.BOUNDS["queryWindowDays"], ui_contracts.BOUNDS["queryWindowDays"])
    tz = ZoneInfo(zone_name)
    today = dt.datetime.fromtimestamp(now, tz).date()
    try:
        start = dt.date.fromisoformat(inputs["start"]) if inputs.get("start") else today
        end = dt.date.fromisoformat(inputs["end"]) if inputs.get("end") else start + dt.timedelta(days=default_days - 1)
    except ValueError:
        raise AlphaError("Use dates like 2026-10-09.", 400, code="ui_window") from None
    if end < start:
        raise AlphaError("The end date is before the start date.", 400, code="ui_window")
    if (end - start).days + 1 > limit:
        raise AlphaError(f"Choose a period of at most {limit} days.", 400, code="ui_window")
    begin = dt.datetime.combine(start, dt.time(0, 0), tz).timestamp()
    finish = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0, 0), tz).timestamp()
    return begin, finish


# --- opaque cursors ----------------------------------------------------------------------------------------------------
def _cursor_key() -> bytes:
    # A per-process key is enough: a cursor is a convenience (an offset into the same query), not authority. Signing it
    # stops a client from steering it to another binding or argument set; every page is still re-authorized.
    global _KEY
    if _KEY is None:
        import os
        _KEY = hashlib.sha256((os.environ.get("RAFII_GENUI_VALIDATOR_SECRET") or "rafii-genui-cursor") .encode()).digest()
    return _KEY


_KEY: bytes | None = None


def encode_cursor(binding: str, inputs: dict, offset_value: int) -> str:
    body = json.dumps({"b": binding, "h": ui_contracts.args_hash(binding, inputs)[:16], "o": int(offset_value)}, separators=(",", ":"))
    mac = hmac.new(_cursor_key(), body.encode(), hashlib.sha256).hexdigest()[:16]
    return "c1." + base64.urlsafe_b64encode(body.encode()).decode().rstrip("=") + "." + mac


def decode_cursor(binding: str, inputs: dict, cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        tag, payload, mac = cursor.split(".")
        body = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        expected = hmac.new(_cursor_key(), body.encode(), hashlib.sha256).hexdigest()[:16]
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor") from None
    if tag != "c1" or not hmac.compare_digest(mac, expected) or data.get("b") != binding or data.get("h") != ui_contracts.args_hash(binding, inputs)[:16]:
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor")
    value = data.get("o")
    if type(value) is not int or not 0 <= value <= 100_000:
        raise AlphaError("Invalid cursor.", 400, code="ui_cursor")
    return value


def page_size(inputs: dict, default: int | None = None) -> int:
    value = inputs.get("limit")
    size = value if type(value) is int else (default or ui_contracts.BOUNDS["queryPageDefault"])
    return max(1, min(size, ui_contracts.BOUNDS["queryPageMax"]))


def paginate(binding: str, inputs: dict, cursor: str | None, items: list, *, default: int | None = None) -> tuple[list, str | None, int]:
    """(page, nextCursor, offset) over a complete, deterministically ordered list."""
    query_inputs = {k: v for k, v in inputs.items() if k != "limit"}
    start = decode_cursor(binding, query_inputs, cursor)
    size = page_size(inputs, default)
    page = items[start:start + size]
    more = start + size < len(items)
    return page, (encode_cursor(binding, query_inputs, start + size) if more else None), start


def excerpt(text, limit: int = 160) -> str | None:
    flat = " ".join(str(text or "").split())
    if not flat:
        return None
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def now() -> float:
    return time.time()
