"""Pure validation and attribution rules for customer business results (PRD R-OUT-01..03).

Three provenance classes stay distinct everywhere they are stored or shown:

* ``provider_native``      — a qualified native provider metric with account, definition and observation window;
* ``first_party_reported`` — an event from the person's approved site/form/booking integration (authentic transport,
                             not independent proof of the business claim);
* ``user_declared``        — a result the person entered or confirmed.

Money is optional, in native minor units plus a lower-case ISO currency, and never inferred from a lead. Totals are
kept per currency; unlike currencies are never added. ``None`` (unavailable) and ``0`` (measured zero) stay different.
Attribution uses only an explicit carried reference that resolves to the same workspace; nothing is guessed from
names, addresses or timing.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from postriff_alpha.domain import AlphaError

PROVENANCE = ("provider_native", "first_party_reported", "user_declared")
RESULT_TYPES = ("click", "lead", "booking", "newsletter_signup", "sale")
MONEY_TYPES = ("booking", "sale")           # a lead, sign-up or click never carries money
ATTRIBUTION = ("associated", "unattributed", "expired_window", "not_this_workspace")
ASSOCIATION_DEFINITION = "rafii.result-link-association.v1"
ASSOCIATION_WINDOW_DAYS = 30
MAX_AMOUNT_MINOR = 100_000_000_000
REF_PARAMETER = "rafii_ref"
_EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_CURRENCY = re.compile(r"^[a-z]{3}$")
_REF = re.compile(r"^(?P<slug>[A-Za-z0-9_-]{10,32})\.(?P<day>\d{8})$")
_CAMPAIGN = re.compile(r"^[A-Za-z0-9_:-]{1,80}$")


def _instant(value, name):
    """ISO-8601 (with offset or Z) or epoch seconds → epoch seconds (UTC)."""
    if isinstance(value, bool):
        raise AlphaError(f"{name} must be a time.", 400, code="result_time_invalid")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str) and 10 <= len(value) <= 40:
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise AlphaError(f"{name} must be an ISO-8601 time.", 400, code="result_time_invalid") from error
        if parsed.tzinfo is None:
            raise AlphaError(f"{name} needs a time zone offset.", 400, code="result_time_invalid")
        seconds = parsed.timestamp()
    else:
        raise AlphaError(f"{name} must be a time.", 400, code="result_time_invalid")
    if not 946_684_800 <= seconds <= 4_102_444_800:   # 2000-01-01 .. 2100-01-01
        raise AlphaError(f"{name} is out of range.", 400, code="result_time_invalid")
    return seconds


def money(raw, result_type):
    """``{"minor": int, "currency": "usd"}`` or None. Refuses money on types that never carry it."""
    if raw is None:
        return None
    if result_type not in MONEY_TYPES:
        raise AlphaError("Only a booking or a sale can carry an amount.", 400, code="result_amount_not_allowed")
    if not isinstance(raw, dict):
        raise AlphaError("Amount must be {minor, currency}.", 400, code="result_amount_invalid")
    minor, currency = raw.get("minor"), raw.get("currency")
    if not isinstance(minor, int) or isinstance(minor, bool) or not 0 <= minor <= MAX_AMOUNT_MINOR:
        raise AlphaError("Amount must be a whole number of minor units (cents).", 400, code="result_amount_invalid")
    if not isinstance(currency, str) or not _CURRENCY.match(currency.lower()):
        raise AlphaError("Currency must be a three-letter code.", 400, code="result_currency_invalid")
    return {"minor": minor, "currency": currency.lower()}


def parse_ref(value):
    """``<link slug>.<YYYYMMDD click day>`` → (slug, click date) or None. The day is the UTC day of the redirect; it
    identifies no person."""
    if not isinstance(value, str):
        return None
    match = _REF.match(value.strip())
    if not match:
        return None
    try:
        day = datetime.strptime(match["day"], "%Y%m%d").date()
    except ValueError:
        return None
    return match["slug"], day


def make_ref(slug, when):
    day = datetime.fromtimestamp(when, timezone.utc).strftime("%Y%m%d")
    return f"{slug}.{day}"


def normalize_first_party(payload, now):
    """A signed producer's JSON body → normalized event. Unknown fields are ignored, never stored."""
    if not isinstance(payload, dict):
        raise AlphaError("The event must be a JSON object.", 400, code="result_payload_invalid")
    event_id = payload.get("eventId")
    if not isinstance(event_id, str) or not _EVENT_ID.match(event_id):
        raise AlphaError("eventId is required (1–120 letters, digits, . _ : -).", 400, code="result_event_id_invalid")
    result_type = payload.get("type")
    if result_type not in RESULT_TYPES:
        raise AlphaError("type must be one of click, lead, booking, newsletter_signup, sale.", 400, code="result_type_invalid")
    occurred = _instant(payload.get("occurredAt"), "occurredAt")
    if occurred > now + 300:
        raise AlphaError("occurredAt is in the future.", 400, code="result_time_future")
    reversal_of = payload.get("reversalOf")
    if reversal_of is not None and (not isinstance(reversal_of, str) or not _EVENT_ID.match(reversal_of) or reversal_of == event_id):
        raise AlphaError("reversalOf must name an earlier eventId.", 400, code="result_reversal_invalid")
    campaign = payload.get("campaignRef")
    if campaign is not None and (not isinstance(campaign, str) or not _CAMPAIGN.match(campaign)):
        raise AlphaError("campaignRef must be a short identifier.", 400, code="result_campaign_invalid")
    ref = payload.get(REF_PARAMETER, payload.get("ref"))
    if ref is not None and parse_ref(ref) is None:
        ref = "invalid"     # kept as an explicit, unmatched reference instead of being guessed at
    return {"eventId": event_id, "type": result_type, "occurredAt": occurred, "amount": money(payload.get("amount"), result_type),
            "reversalOf": reversal_of, "campaignRef": campaign, "ref": ref, "test": payload.get("test") is True}


def normalize_declaration(payload, now):
    """A person's own declaration (``outcome_declare``)."""
    if not isinstance(payload, dict):
        raise AlphaError("Describe the result.", 400, code="result_payload_invalid")
    result_type = payload.get("type")
    if result_type not in RESULT_TYPES or result_type == "click":
        raise AlphaError("Choose a lead, booking, newsletter sign-up or sale.", 400, code="result_type_invalid")
    occurred = _instant(payload.get("occurredAt"), "occurredAt")
    if occurred > now + 300:
        raise AlphaError("A result can't be in the future.", 400, code="result_time_future")
    quantity = payload.get("quantity", 1)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 1000:
        raise AlphaError("Quantity is 1–1000.", 400, code="result_quantity_invalid")
    note = " ".join(str(payload.get("note") or "").split())[:500] or None
    campaign = payload.get("campaignRef")
    if campaign is not None and (not isinstance(campaign, str) or not _CAMPAIGN.match(campaign)):
        raise AlphaError("Choose a campaign from this workspace.", 400, code="result_campaign_invalid")
    link_id = payload.get("linkId")
    if link_id is not None and (not isinstance(link_id, str) or len(link_id) > 64):
        raise AlphaError("Choose a link from this workspace.", 400, code="result_link_invalid")
    return {"type": result_type, "occurredAt": occurred, "amount": money(payload.get("amount"), result_type), "quantity": quantity,
            "note": note, "campaignRef": campaign, "linkId": link_id}


def associate(ref, occurred_at, links_by_slug, *, window_days=ASSOCIATION_WINDOW_DAYS):
    """The explicit association rule (definition ``ASSOCIATION_DEFINITION``).

    ``links_by_slug`` holds only this workspace's links. An event is ``associated`` with a link when it carries that
    link's reference and occurred on or after the click day and no more than ``window_days`` after it. A reference to
    a link that is not in this workspace is ``not_this_workspace`` (and stays unattributed in every count); a missing
    or malformed reference is ``unattributed``; an old click is ``expired_window``. Nothing else is inferred."""
    parsed = parse_ref(ref) if ref not in (None, "invalid") else None
    if parsed is None:
        return {"attribution": "unattributed", "linkId": None, "definition": ASSOCIATION_DEFINITION}
    slug, day = parsed
    link = links_by_slug.get(slug)
    if link is None:
        return {"attribution": "not_this_workspace", "linkId": None, "definition": ASSOCIATION_DEFINITION}
    occurred_day = datetime.fromtimestamp(occurred_at, timezone.utc).date()
    if not day <= occurred_day <= day + timedelta(days=window_days):
        return {"attribution": "expired_window", "linkId": link["id"], "definition": ASSOCIATION_DEFINITION}
    return {"attribution": "associated", "linkId": link["id"], "campaignRef": link.get("campaignRef"), "definition": ASSOCIATION_DEFINITION}


def summarize(rows):
    """Counts and money per provenance and type, with corrections applied only to their own originals.

    ``rows``: dicts with provenance, type, kind ('event'|'amendment'|'reversal'), correctsId, id, quantity, amount,
    attribution, in the order they were received. An amendment is a complete new version of the event it corrects (the
    latest one wins, so an amended result still counts once); a reversal withdraws its original, whichever version is
    current. A row may also stand for a group of results the database already aggregated: ``reversed: True`` marks the
    group as withdrawn and ``events`` says how many of its results carried an amount.
    Returns per-class counts (never one blended number), per-currency totals, and the reversed/unattributed counts that
    must stay visible. A class with no rows is reported as ``None`` (unavailable), not zero."""
    reversed_ids = {r["correctsId"] for r in rows if r.get("kind") == "reversal" and r.get("correctsId")}
    current = {}
    for row in rows:
        if row.get("kind") == "amendment" and row.get("correctsId"):
            current[row["correctsId"]] = row
    out = {cls: None for cls in PROVENANCE}
    for original in rows:
        if original.get("kind") in ("reversal", "amendment"):
            continue
        row = current.get(original["id"], original)
        bucket = out[original["provenance"]] or {"counts": {}, "money": {}, "reversed": 0, "unattributed": 0, "associated": 0}
        out[original["provenance"]] = bucket
        quantity = row.get("quantity", 1)
        if original["id"] in reversed_ids or original.get("reversed"):
            bucket["reversed"] += quantity
            continue
        bucket["counts"][row["type"]] = bucket["counts"].get(row["type"], 0) + quantity
        if row.get("attribution") == "associated":
            bucket["associated"] += quantity
        else:
            bucket["unattributed"] += quantity
        amount = row.get("amount")
        if amount:
            per = bucket["money"].setdefault(amount["currency"], {"minor": 0, "events": 0})
            per["minor"] += amount["minor"]
            per["events"] += row.get("events", 1)
    return out


def utc_day(value):
    return datetime.fromtimestamp(value, timezone.utc).date() if not isinstance(value, date) else value
