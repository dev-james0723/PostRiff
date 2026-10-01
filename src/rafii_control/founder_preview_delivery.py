"""Pure Founder Demo delivery simulation, persisted in the existing Demo payload.

This adapter never admits a real call, addresses a recipient, imports a provider
runtime, or records customer/operating spend. The enclosing founder service owns
source authorization, AAL2/CSRF, audit, and the Demo row transaction/revision.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_phase2.notifications.email_render import one_line, render
from postriff_phase2.phone.contracts import CallReceipt, STATES, TERMINAL, transition
from .auth import ControlError

_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_OPERATIONS = frozenset(("start", "advance", "reconcile", "retry", "acknowledge", "cancel"))
_EMAIL_STATES = frozenset(("queued", "provider_accepted", "delivered", "failed", "retrying", "suppressed", "ambiguous"))
_EMAIL_TERMINAL = frozenset(("delivered", "failed", "suppressed"))
_EMAIL_RANK = {"queued": 0, "retrying": 0, "provider_accepted": 1}
_CALL_ACTIVE = frozenset(STATES) - TERMINAL
_MAX_ATTEMPTS = 2
_MAX_DAILY_CALLS = 2
_COOLDOWN = timedelta(minutes=5)
_MARKER = "DEMO — simulated, not sent"
_METADATA = dict(simulation=True, simulatedOnly=True, externalDelivery=False,
                 providerCalls=0, operationsCost="not_applicable")


def _error(code, status=409):
    raise ControlError("PREVIEW_DELIVERY_" + code, status)


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        _error("INVALID", 400)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            _error("INVALID", 400)
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _error("INVALID", 400)


def _validate(state, payload, request_id, now):
    if not isinstance(state, dict) or state.get("mode") != "demo":
        _error("DEMO_REQUIRED", 403)
    if (not isinstance(payload, dict) or set(payload) - {"operation", "channel", "sourceId", "attemptId", "outcome"}
            or not {"operation", "channel", "sourceId"} <= set(payload)):
        _error("INVALID", 400)
    for name in ("sourceId", "attemptId"):
        if name in payload and (not isinstance(payload[name], str) or not _ID.fullmatch(payload[name])):
            _error("INVALID", 400)
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        _error("INVALID", 400)
    operation, channel = payload["operation"], payload["channel"]
    if not isinstance(operation, str) or operation not in _OPERATIONS or channel not in ("email", "call"):
        _error("INVALID", 400)
    if operation == "start":
        if "attemptId" in payload or "outcome" in payload:
            _error("INVALID", 400)
    elif "attemptId" not in payload:
        _error("INVALID", 400)
    if operation in ("advance", "reconcile"):
        allowed = STATES if channel == "call" else _EMAIL_STATES
        if not isinstance(payload.get("outcome"), str) or payload["outcome"] not in allowed:
            _error("INVALID", 400)
    elif "outcome" in payload:
        _error("INVALID", 400)
    attempts = state.get("contactAttempts", [])
    if not isinstance(attempts, list) or any(not isinstance(a, dict) for a in attempts):
        _error("STATE_INVALID", 409)
    for attempt in attempts:
        if (attempt.get("channel") not in ("call", "email")
                or not isinstance(attempt.get("state"), str)
                or attempt.get("state") not in (STATES if attempt.get("channel") == "call" else _EMAIL_STATES)
                or any(not isinstance(attempt.get(key), str) or not _ID.fullmatch(attempt[key]) for key in ("id", "sourceId"))
                or type(attempt.get("attemptNumber")) is not int or not 1 <= attempt["attemptNumber"] <= _MAX_ATTEMPTS
                or not isinstance(attempt.get("operationRequests"), dict)):
            _error("STATE_INVALID", 409)
        try:
            if _timestamp(attempt.get("updatedAt")) < _timestamp(attempt.get("createdAt")):
                _error("STATE_INVALID", 409)
        except ControlError:
            _error("STATE_INVALID", 409)
    try:
        local_zone = ZoneInfo(state.get("timeZone", "UTC"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        _error("INVALID", 400)
    stamp = _timestamp(now)
    return attempts, stamp, local_zone


def _result(attempt, attempts, *, replayed=False):
    return dict(**_METADATA, attempt=copy.deepcopy(attempt),
                contactAttempts=copy.deepcopy(attempts), replayed=replayed)


def _remember(attempt, request_id, digest, *, cleanup=False):
    operations = attempt.setdefault("operationRequests", {})
    if len(operations) >= 256 and request_id not in operations:
        if not cleanup: _error("REPLAY_CAPACITY", 429)
        # Safe terminal/end-call cleanup cannot be starved by read/event replay
        # bookkeeping. State remains terminal; enclosing action replay/audit is
        # still durable. Retain the newest operation and the initial claim.
        keys=list(operations)
        operations.pop(keys[1] if len(keys)>1 else keys[0])
    operations[request_id] = digest


def _receipt(attempt):
    if attempt["channel"] == "call":
        # No fabricated provider call reference or settled duration/cost.
        receipt = CallReceipt(state=attempt["state"], failure="simulated_failure" if attempt["state"] == "failed" else None)
        attempt["receipt"] = dict(**asdict(receipt), **_METADATA)


def _scheduled_source(state, source_id):
    """Only explicit source metadata denotes an automatic/scheduled start."""
    for collection in ("reports", "followUps", "incidents"):
        for source in state.get(collection, []) if isinstance(state.get(collection, []), list) else []:
            if isinstance(source, dict) and source.get("id") == source_id:
                return source.get("deliveryMode") in ("scheduled", "automatic")
    return False


def _admission(attempts, stamp, local_zone, *, automatic):
    calls = [a for a in attempts if a.get("channel") == "call"]
    if any(a.get("state") in _CALL_ACTIVE for a in calls):
        _error("CALL_ACTIVE")
    local = stamp.astimezone(local_zone)
    if automatic and (local.hour >= 22 or local.hour < 8):
        _error("QUIET_HOURS", 429)
    if sum(_timestamp(a.get("createdAt")).astimezone(local_zone).date() == local.date() for a in calls) >= _MAX_DAILY_CALLS:
        _error("DAILY_LIMIT", 429)


def _new_attempt(payload, request_id, stamp, parent=None):
    attempt_id = "sim-" + hashlib.sha256((request_id + ":" + payload["channel"] + ":" + payload["sourceId"]).encode()).hexdigest()[:32]
    return dict(**_METADATA, id=attempt_id, sourceId=payload["sourceId"], channel=payload["channel"],
                state=("retrying" if parent else "queued") if payload["channel"] == "email" else "requested",
                createdAt=stamp.isoformat(), updatedAt=stamp.isoformat(),
                acknowledgement="unacknowledged", acknowledged=False, acknowledgedAt=None,
                retryOf=parent["id"] if parent else None,
                rootAttemptId=(parent.get("rootAttemptId") or parent["id"]) if parent else attempt_id,
                attemptNumber=parent["attemptNumber"] + 1 if parent else 1,
                admission="simulated_only_no_live_admission", operationRequests={})


def delivery_action(state: dict, payload: dict, *, request_id: str, now: str) -> dict:
    """Mutate only ``state.contactAttempts``; never dispatch or silently redial.

    ``state`` is ``demo_payload.founderIntelligence`` with mode/timeZone. The
    caller must authorize sourceId against its reports/reminders/incidents first.
    Exactly two attempts per source/channel and two calls per local day are
    permitted. Duplicate IDs cannot change content, and uncertain outcomes need
    an explicit, definitive reconciliation before another call can start.
    """
    original, stamp, local_zone = _validate(state, payload, request_id, now)
    attempts = copy.deepcopy(original)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    for recorded in attempts:
        prior = recorded.get("operationRequests", {}).get(request_id)
        if prior is not None:
            if prior != digest:
                _error("CONFLICT")
            return _result(recorded, original, replayed=True)

    operation, channel, source_id = payload["operation"], payload["channel"], payload["sourceId"]
    matching = [a for a in attempts if a.get("sourceId") == source_id and a.get("channel") == channel]
    if operation == "start":
        if matching:
            # Only the explicit retry operation can create a later attempt.
            attempt = matching[-1]
            _remember(attempt, request_id, digest)
            state["contactAttempts"] = attempts
            return _result(attempt, attempts, replayed=True)
        if channel == "call":
            _admission(attempts, stamp, local_zone, automatic=_scheduled_source(state, source_id))
        attempt = _new_attempt(payload, request_id, stamp)
        attempts.append(attempt)
    else:
        attempt = next((a for a in matching if a.get("id") == payload["attemptId"]), None)
        if attempt is None:
            _error("NOT_FOUND", 404)
        if stamp < _timestamp(attempt.get("updatedAt")):
            _error("STALE_EVENT")
        current = attempt["state"]
        terminal = TERMINAL if channel == "call" else _EMAIL_TERMINAL
        if operation == "retry":
            if current == "ambiguous":
                _error("AMBIGUOUS")
            if current not in (("failed", "no_answer") if channel == "call" else ("failed",)):
                _error("RETRY_NOT_ALLOWED")
            if len(matching) >= _MAX_ATTEMPTS or attempt is not matching[-1]:
                _error("RETRY_LIMIT", 429)
            if stamp - _timestamp(attempt["updatedAt"]) < _COOLDOWN:
                _error("COOLDOWN", 429)
            if channel == "call":
                _admission(attempts, stamp, local_zone, automatic=True)
            attempt = _new_attempt(payload, request_id, stamp, parent=attempt)
            attempts.append(attempt)
        elif operation == "acknowledge":
            if current != ("completed" if channel == "call" else "delivered"):
                _error("ACKNOWLEDGEMENT_NOT_ALLOWED")
            attempt.update(acknowledgement="acknowledged", acknowledged=True,
                           acknowledgedAt=attempt.get("acknowledgedAt") or stamp.isoformat())
        elif operation == "reconcile":
            if current != "ambiguous":
                _error("RECONCILE_NOT_ALLOWED")
            if payload["outcome"] not in terminal:
                _error("DEFINITIVE_OUTCOME_REQUIRED")
            attempt.update(state=payload["outcome"], reconciledAt=stamp.isoformat(), reconciliation="explicit_simulated_evidence")
        elif current == "ambiguous":
            _error("AMBIGUOUS")
        elif operation == "cancel":
            if current not in terminal:
                if channel == "email" and current == "provider_accepted":
                    _error("CANNOT_CANCEL")
                attempt["state"] = "cancelled" if channel == "call" else "suppressed"
        elif operation == "advance" and current not in terminal:
            incoming = payload["outcome"]
            if channel == "call":
                # The existing ranked vocabulary handles out-of-order states;
                # uncertainty additionally holds any currently active call.
                attempt["state"] = "ambiguous" if incoming == "ambiguous" else transition(current, incoming)
            elif incoming == "ambiguous" or incoming in _EMAIL_TERMINAL:
                if incoming == "suppressed" and current == "provider_accepted":
                    _error("CANNOT_CANCEL")
                attempt["state"] = incoming
            elif _EMAIL_RANK.get(incoming, -1) >= _EMAIL_RANK.get(current, -1):
                attempt["state"] = incoming
        if attempt["state"] != current or operation == "acknowledge":
            attempt["updatedAt"] = stamp.isoformat()
    terminal = TERMINAL if channel == "call" else _EMAIL_TERMINAL
    _remember(attempt, request_id, digest, cleanup=attempt['state'] in terminal or operation=='acknowledge')
    _receipt(attempt)
    state["contactAttempts"] = attempts
    return _result(attempt, attempts)


def _safe_impact_text(value, limit):
    if not isinstance(value, str):
        _error("INVALID", 400)
    text = one_line(value, limit)
    # Incident titles are operational metadata, never destinations or links.
    text = re.sub(r"https?://\S+|[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\+[1-9][0-9]{7,14}", "[redacted]", text)
    return text


def _payment_evidence(incident):
    """One original Demo payment record, with no private/text/log projection."""
    records = incident.get("affectedRecords", [])
    if not isinstance(records, list):
        _error("INVALID", 400)
    refs = ("invoiceId", "subscriptionId", "paymentId")
    # Preview coverage is deliberately bounded; this is not a full incident
    # export. Outage metadata without payment references stays out of email.
    for record in records[:10]:
        if not isinstance(record, dict):
            _error("INVALID", 400)
        if not any(key in record for key in refs):
            continue
        if any(not isinstance(record.get(key), str) or not _ID.fullmatch(record[key]) for key in refs):
            _error("INVALID", 400)
        amount, currency = record.get("amountMinor"), record.get("currency")
        if (type(amount) is not int or not 0 <= amount <= 10**12
                or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
            _error("INVALID", 400)
        return [{key: record[key] for key in (*refs, "amountMinor", "currency")}]
    return []


def email_preview(incident: dict, *, locale="en") -> dict:
    """Render a safe, explicitly unsent incident preview using the shared template.

    The shared renderer has /app links; the UI should use actionPath for Control
    navigation. Its fixed .invalid origin is preview text, never a user URL.
    Unknown incident fields, private bodies and recipients never reach rendering.
    """
    if not isinstance(incident, dict) or not isinstance(incident.get("id"), str) or not _ID.fullmatch(incident["id"]):
        _error("INVALID", 400)
    if not isinstance(locale, str) or len(locale) > 40:
        _error("INVALID", 400)
    severity = incident.get("severity", "info")
    if severity not in ("critical", "high", "medium", "low", "warning", "info"):
        _error("INVALID", 400)
    count = incident.get("affectedCount", 0)
    if type(count) is not int or not 0 <= count <= 10000:
        _error("INVALID", 400)
    state = incident.get("state", "open")
    if state not in ("open", "investigating", "recovering", "resolved", "normal", "stale", "unavailable"):
        _error("INVALID", 400)
    observed = _timestamp(incident["observedAt"]).isoformat() if "observedAt" in incident else "unavailable"
    impact = dict(id=incident["id"], title=_safe_impact_text(incident.get("title", "Founder incident"), 120),
                  severity=severity, affectedCount=count, state=state, observedAt=observed)
    payments = _payment_evidence(incident)
    details = [("Execution", _MARKER), ("Incident", impact["id"]), ("Title", impact["title"]),
               ("Severity", severity), ("Affected Demo subscribers", str(count)), ("State", state), ("Observed at", observed)]
    if payments:
        payment = payments[0]
        details.extend([("Payment evidence", "Original simulated evidence; 1 record shown"),
                        ("Invoice", payment["invoiceId"]), ("Subscription", payment["subscriptionId"]),
                        ("Payment", payment["paymentId"]),
                        ("Amount (minor units)", f'{payment["amountMinor"]} {payment["currency"]}')])
    preview = render("analytics_anomaly", locale=locale, base_url="https://rafii.invalid", href="/app",
                     transactional=True, details=details)
    preview["subject"] = _MARKER + (" — [Recovered]" if state == "resolved" else "") + " — " + preview["subject"]
    preview["preheader"] = _MARKER + " — " + preview["preheader"]
    preview["text"] = _MARKER + "\n\n" + preview["text"]
    preview["html"] = preview["html"].replace("<body ", '<body data-execution="simulation" ').replace(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="rf-page"',
        f'<p role="status">{html.escape(_MARKER)}</p><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="rf-page"', 1)
    # srcdoc previews must not fetch an avatar or offer a misleading /app CTA.
    # Preserve the shared renderer's markup, while the enclosing UI owns its
    # separate Control actionPath. The text twin retains only the fixed origin.
    preview["html"] = re.sub(r'<img\b[^>]*>', '', preview["html"])
    preview["html"] = re.sub(r'href="https://rafii\.invalid[^"]*"', 'href="#preview-only"', preview["html"])
    return dict(**preview, **_METADATA, impact=impact, paymentEvidence=payments,
                actionPath="/control/advanced", rendererLinks="disabled_preview_only")
