"""Server-authoritative feature readiness shared by Growth Studio and Trends.

One page-level answer to "can this workspace use this feature, and if not, what is
the real next step". The backend computes it; the browser only renders it.

Rules that keep it honest:
- A readiness value is advisory. ``canRun`` never replaces the per-dispatch role,
  consent, rights, budget and revision checks; it only decides which controls render.
- Reason codes are bounded identifiers. They never carry counts or names from
  other workspaces, provider error bodies, stack traces or secrets.
- ``nextStep.href`` is an in-app path only, so a payload can never send someone off-site.
- An outage never tells the person to reconnect: ``temporarily_unavailable`` only
  offers ``retry`` or ``wait``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# Most blocking first. The first state with a blocker wins.
PRECEDENCE = ("feature_disabled", "unsupported", "not_entitled", "setup_required",
              "temporarily_unavailable", "insufficient_data", "ready")
STATES = frozenset(PRECEDENCE)
NEXT_KINDS = frozenset(("connect", "consent", "plan", "retry", "wait", "contact_owner", "none"))
OUTAGE_NEXT_KINDS = frozenset(("retry", "wait", "none"))
# Steps only an owner (or a manager of connections) can take. Everyone else is
# routed to the owner instead of being shown a control that will be refused.
OWNER_KINDS = frozenset(("consent", "plan"))
KEYS = ("state", "reasonCodes", "canRead", "canRun", "lastSuccessfulReadAt", "nextStep")
MAX_REASONS = 8
_REASON = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_HREF = re.compile(r"^/app(?:/[a-z0-9_-]+)*/?(?:[?#][A-Za-z0-9=&_.-]*)?$")


class ReadinessError(ValueError):
    pass


def blocker(state, reason, *, next_kind="none", href=None, blocks_read=False, blocks_run=True):
    """One reason a feature cannot (fully) be used. ``ready`` is not a blocker state."""
    if state not in STATES or state == "ready":
        raise ReadinessError("invalid_readiness_state")
    _reason(reason)
    step = _step(next_kind, href)
    if state == "temporarily_unavailable" and step and step["kind"] not in OUTAGE_NEXT_KINDS:
        raise ReadinessError("outage_next_step_must_be_retry_or_wait")
    return {"state": state, "reason": reason, "next": step,
            "blocks_read": bool(blocks_read), "blocks_run": bool(blocks_run)}


def owner_step(kind, href, *, role, allowed_roles=("owner",)):
    """The step itself for an allowed role; contact_owner for everyone else."""
    if role in allowed_roles:
        return {"next_kind": kind, "href": href}
    return {"next_kind": "contact_owner", "href": None}


def resolve(blockers=(), *, can_read=True, can_run=True, last_successful_read_at=None):
    """Combine blockers into the single readiness payload (exactly KEYS)."""
    items = list(blockers or ())
    for item in items:
        if not isinstance(item, dict) or item.get("state") not in STATES:
            raise ReadinessError("invalid_readiness_blocker")
    if not items:
        state = "ready"
    else:
        state = min((item["state"] for item in items), key=PRECEDENCE.index)
    ordered = sorted(items, key=lambda item: PRECEDENCE.index(item["state"]))
    reasons = []
    for item in ordered:
        if item["reason"] not in reasons:
            reasons.append(item["reason"])
    step = next((item["next"] for item in ordered if item["state"] == state and item["next"]), None)
    read = bool(can_read) and not any(item["blocks_read"] for item in items)
    run = bool(can_run) and read and not any(item["blocks_run"] for item in items)
    return {"state": state, "reasonCodes": reasons[:MAX_REASONS], "canRead": read, "canRun": run,
            "lastSuccessfulReadAt": _instant(last_successful_read_at), "nextStep": step}


def validate(payload):
    """Fail closed on anything that is not exactly a readiness payload."""
    if not isinstance(payload, dict) or tuple(sorted(payload)) != tuple(sorted(KEYS)):
        raise ReadinessError("invalid_readiness_payload")
    if payload["state"] not in STATES:
        raise ReadinessError("invalid_readiness_state")
    if not isinstance(payload["reasonCodes"], list) or len(payload["reasonCodes"]) > MAX_REASONS:
        raise ReadinessError("invalid_readiness_reasons")
    for reason in payload["reasonCodes"]:
        _reason(reason)
    if type(payload["canRead"]) is not bool or type(payload["canRun"]) is not bool:
        raise ReadinessError("invalid_readiness_flags")
    if payload["canRun"] and not payload["canRead"]:
        raise ReadinessError("invalid_readiness_flags")
    if payload["state"] == "ready" and payload["reasonCodes"]:
        raise ReadinessError("ready_has_no_reasons")
    if payload["lastSuccessfulReadAt"] is not None:
        _instant(payload["lastSuccessfulReadAt"])
    step = payload["nextStep"]
    if step is not None:
        if not isinstance(step, dict) or not set(step) <= {"kind", "href"} or "kind" not in step:
            raise ReadinessError("invalid_readiness_next_step")
        _step(step["kind"], step.get("href"))
        if payload["state"] == "temporarily_unavailable" and step["kind"] not in OUTAGE_NEXT_KINDS:
            raise ReadinessError("outage_next_step_must_be_retry_or_wait")
    return payload


def _reason(reason):
    if not isinstance(reason, str) or not _REASON.fullmatch(reason):
        raise ReadinessError("invalid_readiness_reason")
    return reason


def _step(kind, href):
    if kind not in NEXT_KINDS:
        raise ReadinessError("invalid_readiness_next_kind")
    if href is not None and (not isinstance(href, str) or not _HREF.fullmatch(href)):
        raise ReadinessError("invalid_readiness_href")
    if kind == "none":
        return None
    return {"kind": kind, **({"href": href} if href else {})}


def _instant(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReadinessError("invalid_readiness_timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReadinessError("invalid_readiness_timestamp")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
