"""Semantic product events for the RAFII Product Growth program (PRD R-MET-03).

One writer, one taxonomy. Events go into the existing ``pr_product_events`` table with the dedupe key
``<event>:<entity id>:<revision>`` and the property rules of the Founder P1 writer (``product_events``):

* event names ``[a-z][a-z_]{0,39}.[a-z][a-z_]{0,39}``;
* properties are enum strings ``[a-z][a-z0-9_-]{0,39}`` unless the event lists them as counts, which accept
  non-negative integers up to 1,000,000; anything else (text, ids, floats, bools, contact data, URLs) is dropped;
* ``user_id`` None means a system/worker actor, never a forged user;
* the write runs inside the caller's transaction behind its own SAVEPOINT and never raises.

When ``postriff_phase2.product_events`` (Founder P1) is present, this module registers its events there once and
delegates every write, so there is never a second taxonomy.
"""
from __future__ import annotations

import json
import logging
import re

# event → (enum properties, count properties)
TAXONOMY = {
    "continuation.claimed": ({"source", "selection", "outcome"}, set()),
    "draft.accepted": ({"origin", "channel"}, {"revision"}),
    "week.scope_approved": ({"mode", "channel"}, {"slots"}),
    "week.scope_changed": ({"change"}, {"slots"}),
    "week.completed": ({"handoff"}, {"slots", "verified", "assisted"}),
    "relationship.followup_outcome": ({"state", "previous"}, set()),
    "result.ingested": ({"provenance", "result_type", "attribution"}, set()),
    "result.reversed": ({"provenance", "result_type"}, set()),
    "series.episode_accepted": ({"role"}, {"episode"}),
    "visual_pack.accepted": ({"format", "language"}, {"slides", "revision"}),
    "visual_pack.exported": ({"handoff"}, {"slides", "revision"}),
    "brief.delivered": ({"coverage", "channel"}, {"items"}),
    "brief.action": ({"action", "reason", "effort"}, set()),
    "strategy.decided": ({"decision", "scope"}, set()),
    "proof.revised": ({"frequency", "reason"}, {"revision"}),
}
_EVENT = re.compile(r"^[a-z][a-z_]{0,39}\.[a-z][a-z_]{0,39}$")
_ENUM = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MAX_COUNT = 1_000_000
log = logging.getLogger("postriff.growth_events")

try:   # Founder P1 writer, when merged
    from . import product_events as _shared  # type: ignore[attr-defined]
except ImportError:   # pragma: no cover - depends on the integration state
    _shared = None
_REGISTERED = False


def _register_shared():
    global _REGISTERED
    if _shared is None or _REGISTERED:
        return
    for event, (enums, counts) in TAXONOMY.items():
        _shared.register({event: set(enums) | set(counts)}, counts=tuple(sorted(counts)))
    _REGISTERED = True


def properties(event, values):
    enums, counts = TAXONOMY[event]
    out = {}
    for key, value in (values or {}).items():
        if key in counts and isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT:
            out[key] = value
        elif key in enums and isinstance(value, str) and _ENUM.match(value):
            out[key] = value
    return out


def dedupe_key(event, entity_id, revision):
    return f"{event}:{entity_id}:{revision}"[:200]


def emit(cur, *, workspace_id, event, entity_id, revision=0, user_id=None, values=None):
    """Record one event (idempotent per entity revision). Returns True when this call wrote it, False otherwise —
    including on any failure, which is logged without content and never breaks the caller's transaction."""
    if event not in TAXONOMY or not _EVENT.match(event):
        raise ValueError(f"unknown growth event {event!r}")   # a programming error, not a runtime condition
    props = properties(event, values)
    if _shared is not None:
        try:
            _register_shared()
            return bool(_shared.record(cur, workspace_id, user_id, event, entity_id, revision, props))
        except Exception as error:  # noqa: BLE001 - an interface mismatch falls back to the identical local write
            log.warning(json.dumps({"event": "growth_event.shared_writer_unavailable", "reason": type(error).__name__}))
    try:
        cur.execute("SAVEPOINT growth_event")
        cur.execute("INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key) VALUES(%s,%s,%s,%s::jsonb,%s) "
                    "ON CONFLICT DO NOTHING", (workspace_id, user_id, event, json.dumps(props), dedupe_key(event, entity_id, revision)))
        wrote = getattr(cur, "rowcount", 1) == 1
        cur.execute("RELEASE SAVEPOINT growth_event")
        return wrote
    except Exception as error:  # noqa: BLE001 - instrumentation must never fail the product action
        try:
            cur.execute("ROLLBACK TO SAVEPOINT growth_event")
        except Exception:  # noqa: BLE001
            pass
        log.warning(json.dumps({"event": "growth_event.skipped", "name": event, "reason": type(error).__name__}))
        return False
