"""Relationships and follow-ups over the existing Inbox (PRD R-REL-01/02; implementation plan G2-REL).

Authority: every operation runs inside the repository transaction for the session's verified principal; the path
workspace id selects a target and never grants access. Reads need ``read``; every change needs ``edit``; replying stays
``reply`` on the existing Inbox path (``audience.draft_reply → reply_preview → approve_reply``). Nothing here contacts
anyone: a due follow-up is an internal reminder.

Integrity: thread links are composite ``(workspace_id, id)`` foreign keys, so a record can never point at another
workspace's thread; a foreign or unknown thread answers the same 404. Owners must be active members. Creates take an
idempotency key (replay returns the record, a different request under the same key conflicts); changes take the
record's ``expectedRevision`` (409 ``revision_conflict``). Every change appends a content-free history row and audit
event (ids, enums and instants only). Relationship text never reaches product events, audit meta or logs.

Due times are UTC instants plus the IANA zone they were chosen in. A local time that does not exist because clocks
change is refused, and a repeated local time needs an explicit first/second choice — the publishing scheduler's rule
(``contracts.resolve_time``). A reminder's identity is ``<due revision>:<reminder instant>``: cosmetic edits never
change it, so they never re-alert; a new due time, or the end of a snooze, does.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

from ..contracts import digest
from ..permissions import Membership, require

FLAG = "RAFII_RELATIONSHIPS_ENABLED"
STATES = ("new", "replied", "waiting", "follow_up_due", "won", "closed")
OPEN_STATES = ("new", "replied", "waiting", "follow_up_due")
TERMINAL = ("won", "closed")
PROVENANCE = ("provider_native", "first_party_reported", "user_declared")
LIMITS = {"displayName": 120, "interest": 300, "nextAction": 200, "contactRef": 200, "contactAccount": 200, "note": 500}
MAX_NOTES = 20
MAX_THREADS = 20
PAGE_DEFAULT, PAGE_MAX = 25, 50
DUE_PAST_SECONDS = 366 * 86400          # a follow-up may be logged as already overdue, within a year
DUE_FUTURE_SECONDS = 3 * 366 * 86400
SNOOZE_MAX_SECONDS = 366 * 86400
EXCERPT = 280
EVENT = "relationship.follow_up_due"
_UUID = re.compile(r"^u?[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_KEY = re.compile(r"^[A-Za-z0-9_:.-]{8,80}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_ZONE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}$")
_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$")
_EPOCH_TEXT = re.compile(r"^\d{1,12}(?:\.\d{1,6})?$")
_ENUM = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
META_KEYS = {"threadId", "noteId", "owner", "previousOwner", "until", "dueRevision", "hasDue", "fields", "source", "resultId",
             "provenance", "fromSuggestion", "suggested", "reason"}
UPDATABLE_FIELDS = ("displayName", "interest", "nextAction", "contact")


# --- switches --------------------------------------------------------------------------------------------------------------
def enabled(values=None):
    """Same semantics as the coworker flags (off unless 1/true/yes/on; preview isolation applies)."""
    from ..coworker import flags
    try:
        source = flags._source(values)
    except Exception:  # noqa: BLE001 - a misconfigured environment never switches a feature on
        return False
    return flags._truthy(source.get(FLAG, ""))


def require_enabled():
    if not enabled():
        raise AlphaError("This feature isn't turned on yet.", 404, code="feature_disabled")


# --- pure validation -----------------------------------------------------------------------------------------------------
def _invalid(message, code="invalid_input"):
    return AlphaError(message, 400, code=code)


def text(value, limit, label, *, required=False, multiline=False):
    """Plain text within ``limit`` characters (code points, as PostgreSQL counts them), or None when empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _invalid(f"Add {label}.")
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise _invalid(f"{label.capitalize()} must be plain text.")
    cleaned = "\n".join(" ".join(line.split()) for line in value.replace("\r", "").split("\n")).strip() if multiline else " ".join(value.split())
    if len(cleaned) > limit:
        raise _invalid(f"{label.capitalize()} can be at most {limit} characters.")
    return cleaned


def ident(value, *, missing="Relationship unavailable.", code="relationship_not_found", status=404):
    """A canonical uuid string. Malformed ids answer exactly like unknown ones."""
    if not isinstance(value, str) or not _UUID.match(value):
        raise AlphaError(missing, status, code=code)
    return str(uuid.UUID(value.removeprefix("u")))


def idempotency_key(value, *, required):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _KEY.match(value):
        raise _invalid("Send an idempotency key of 8 to 80 letters, digits, '-', '_', ':' or '.'.", "idempotency_key_invalid")
    return value


def expected_revision(payload):
    value = (payload or {}).get("expectedRevision")
    if type(value) is not int or value < 1:
        raise _invalid("Send the revision you last read (expectedRevision).", "revision_required")
    return value


def zone(name):
    if not isinstance(name, str) or len(name) > 64 or not _ZONE.match(name):
        raise _invalid("Choose a valid IANA time zone, such as America/New_York.", "due_invalid")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise _invalid("Choose a valid IANA time zone, such as America/New_York.", "due_invalid") from None


def instant(value, label="time"):
    """ISO-8601 with an offset (or Z), or epoch seconds → epoch seconds (UTC)."""
    if isinstance(value, bool):
        raise _invalid(f"The {label} must be a time.", "time_invalid")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str) and 10 <= len(value) <= 40:
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise _invalid(f"The {label} must be an ISO-8601 time.", "time_invalid") from None
        if parsed.tzinfo is None:
            raise _invalid(f"The {label} needs a time zone offset.", "time_invalid")
        seconds = parsed.timestamp()
    else:
        raise _invalid(f"The {label} must be a time.", "time_invalid")
    if not 946_684_800 <= seconds <= 4_102_444_800:
        raise _invalid(f"The {label} is out of range.", "time_invalid")
    return seconds


def resolve_due(raw, now):
    """``{"local": "YYYY-MM-DDTHH:MM", "timeZone": zone, "fold"?: 0|1}`` or ``{"at": instant, "timeZone": zone}`` →
    ``{"at", "timeZone", "fold"}``; ``None`` clears the due time. Mirrors the scheduler: a nonexistent local time is
    refused; a repeated one needs ``fold`` (0 = first occurrence, 1 = second)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("Choose a due date, time and time zone.", "due_invalid")
    name = raw.get("timeZone")
    tz = zone(name)
    if raw.get("local") is not None:
        local = raw["local"]
        if not isinstance(local, str) or not _LOCAL.match(local):
            raise _invalid("Choose the due date and time as YYYY-MM-DDTHH:MM.", "due_invalid")
        try:
            naive = datetime.fromisoformat(local)
        except ValueError:
            raise _invalid("Choose a real calendar date and time.", "due_invalid") from None
        choices = [naive.replace(tzinfo=tz, fold=n) for n in (0, 1)]
        valid = [c for c in choices if c.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive]
        if not valid:
            raise _invalid("That local time doesn't exist on that day because the clocks change. Choose another time.", "due_time_nonexistent")
        ambiguous = len({c.utcoffset() for c in valid}) > 1
        fold = raw.get("fold")
        if ambiguous and (type(fold) is not int or fold not in (0, 1)):
            raise _invalid("That time happens twice on that day because the clocks change. Choose the first or the second.", "due_time_ambiguous")
        fold = fold if ambiguous else 0
        at = choices[fold].timestamp()
    elif raw.get("at") is not None:
        at = instant(raw["at"], "due time")
        fold = datetime.fromtimestamp(at, tz).fold
    else:
        raise _invalid("Choose a due date, time and time zone.", "due_invalid")
    if not now - DUE_PAST_SECONDS <= at <= now + DUE_FUTURE_SECONDS:
        raise _invalid("Choose a due time between a year ago and three years from now.", "due_invalid")
    return {"at": at, "timeZone": name, "fold": fold}


def due_view(at, zone_name, fold, revision):
    if at is None:
        return None
    local = datetime.fromtimestamp(at, zone(zone_name))
    return {"at": at, "utc": datetime.fromtimestamp(at, timezone.utc).isoformat(), "local": local.strftime("%Y-%m-%dT%H:%M"),
            "timeZone": zone_name, "fold": local.fold, "offset": local.strftime("%z"), "revision": revision}


def contact(raw):
    """Optional ``{"provider", "accountId"?, "ref"}``: an opaque reference scoped to one provider (+ account)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("Contact must name its platform and reference.")
    ref = text(raw.get("ref"), LIMITS["contactRef"], "contact reference")
    provider = raw.get("provider")
    if provider is None and ref is None:
        return None
    if not isinstance(provider, str) or not _PROVIDER.match(provider):
        raise _invalid("Name the contact's platform (for example threads).")
    account = text(raw.get("accountId"), LIMITS["contactAccount"], "contact account")
    return {"provider": provider, "accountId": account, "ref": ref}


def reminder_at(row):
    snoozed = row.get("snoozedUntil")
    return max(row["dueAt"], snoozed) if snoozed else row["dueAt"]


def reminder_token(row):
    """``<due revision>:<reminder instant>`` — the identity of one reminder (SQL twin: REMINDER_TOKEN_SQL)."""
    return f"{row['dueRevision']}:{int(reminder_at(row))}"


def dedupe_key(relationship_id, token):
    return f"{EVENT}:{relationship_id}:{token}"


REMINDER_TOKEN_SQL = ("(r.due_revision::text || ':' || floor(extract(epoch from greatest(r.due_at, r.snoozed_until)))::bigint::text)")
DUE_NOW_SQL = ("r.state NOT IN ('won','closed') AND r.due_at IS NOT NULL AND r.due_at <= to_timestamp(%s) "
               "AND (r.snoozed_until IS NULL OR r.snoozed_until <= to_timestamp(%s)) "
               f"AND r.followup_dismissed_key IS DISTINCT FROM {REMINDER_TOKEN_SQL}")


def followup(row, now):
    """Where this relationship's reminder stands now. ``dueNow`` is what Attention and notifications surface."""
    if row.get("dueAt") is None:
        return {"status": "none", "dueNow": False}
    if row["state"] in TERMINAL:
        return {"status": "inactive", "dueNow": False}
    if row.get("snoozedUntil") and row["snoozedUntil"] > now:
        return {"status": "snoozed", "dueNow": False, "until": row["snoozedUntil"]}
    if row["dueAt"] > now:
        return {"status": "scheduled", "dueNow": False}
    if row.get("followupDismissedKey") == reminder_token(row):
        return {"status": "dismissed", "dueNow": False}
    return {"status": "due", "dueNow": True, "since": reminder_at(row)}


def suggest(row, threads, now):
    """At most one suggested state with the evidence behind it. Deterministic and never applied here; it never suggests
    ``won`` (a purchase is the person's declaration) or ``closed``."""
    state = row["state"]
    if state in TERMINAL:
        return None
    changed = row.get("stateChangedAt") or 0
    sent = [(t["lastSentAt"], t["threadId"]) for t in threads if t.get("lastSentAt") and t["lastSentAt"] > changed]
    inbound = [(t["at"], t["threadId"]) for t in threads if not t.get("tombstoned") and t.get("at") and t["at"] > changed]
    suggestion = None
    if state in ("new", "waiting", "follow_up_due") and sent:
        at, thread_id = max(sent)
        suggestion = {"state": "replied", "reason": "reply_sent", "evidence": {"threadId": thread_id, "at": at}}
    elif state in ("replied", "waiting") and inbound:
        at, thread_id = max(inbound)
        suggestion = {"state": "follow_up_due", "reason": "new_message", "evidence": {"threadId": thread_id, "at": at}}
    elif state in ("new", "replied", "waiting") and row.get("dueAt") is not None and row["dueAt"] <= now \
            and not (row.get("snoozedUntil") and row["snoozedUntil"] > now):
        suggestion = {"state": "follow_up_due", "reason": "due_passed", "evidence": {"dueAt": row["dueAt"]}}
    if suggestion is None:
        return None
    evidence = suggestion["evidence"]
    suggestion["key"] = f"{suggestion['state']}:{suggestion['reason']}:{evidence.get('threadId') or ''}:{int(evidence.get('at') or evidence.get('dueAt') or 0)}"
    return None if suggestion["key"] == row.get("suggestionDismissedKey") else suggestion


def encode_cursor(row):
    return base64.urlsafe_b64encode(json.dumps([row["dueSort"], row["createdSort"], row["id"]]).encode()).decode().rstrip("=")


def decode_cursor(value):
    try:
        if not isinstance(value, str) or len(value) > 300:
            raise ValueError()
        decoded = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(decoded, list) or len(decoded) != 3:
            raise ValueError()
        due, created, rid = decoded
        if due is not None and (not isinstance(due, str) or not _EPOCH_TEXT.match(due)):
            raise ValueError()
        if not isinstance(created, str) or not _EPOCH_TEXT.match(created):
            raise ValueError()
        return due, created, str(uuid.UUID(rid))
    except (ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
        raise _invalid("This page cursor is invalid.", "cursor_invalid") from None


def page_limit(value):
    if value is None or value == "":
        return PAGE_DEFAULT
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _invalid("Choose a page size from 1 to 50.") from None
    if not 1 <= number <= PAGE_MAX:
        raise _invalid("Choose a page size from 1 to 50.")
    return number


def clean_meta(meta):
    """History and audit meta: allowlisted keys with ids, enums, small integers, booleans or field-name lists only."""
    out = {}
    for key, value in (meta or {}).items():
        if key not in META_KEYS or value is None:
            continue
        if isinstance(value, bool) or (isinstance(value, int) and 0 <= value <= 4_102_444_800):
            out[key] = value
        elif isinstance(value, str) and (_UUID.match(value) or _ENUM.match(value)):
            out[key] = value
        elif isinstance(value, list) and all(isinstance(v, str) and _ENUM.match(v) for v in value):
            out[key] = value[:10]
    return out


def excerpt(value):
    flat = " ".join(str(value or "").split())
    return flat[:EXCERPT] + ("…" if len(flat) > EXCERPT else "")


def reply_route(provider, reply_level, tombstoned, permalink):
    """How a reply to this thread can happen. ``direct`` only where an Inbox reply adapter exists and the account's
    reply level is Direct (Threads in this release); everything else is an honest, assisted provider link."""
    from ..inbox_providers import ThreadsInboxAdapter, adapter_for
    if adapter_for(provider) is not None and reply_level == "Direct" and not tombstoned:
        return {"kind": "direct", "provider": provider, "approval": "exact"}
    href = ThreadsInboxAdapter.source_permalink(permalink) if provider == "threads" else _https(permalink)
    reason = "source_removed" if tombstoned else ("not_direct" if adapter_for(provider) is not None else "unsupported_provider")
    return {"kind": "assisted", "provider": provider, "href": href, "reason": reason}


def _https(value):
    from urllib.parse import urlparse
    if not isinstance(value, str) or len(value) > 1000:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None


# --- rows ------------------------------------------------------------------------------------------------------------------
ROW_SQL = ("r.id::text,r.display_name,r.contact_provider,r.contact_account,r.contact_ref,r.interest,r.state,r.previous_state,"
           "extract(epoch from r.state_changed_at),r.owner_id::text,r.next_action,extract(epoch from r.due_at),r.due_time_zone,r.due_fold,"
           "r.due_revision,extract(epoch from r.snoozed_until),r.followup_dismissed_key,r.notified_key,r.suggestion_dismissed_key,r.notes,"
           "r.won_result_id::text,r.won_provenance,r.revision,r.created_by::text,extract(epoch from r.created_at),extract(epoch from r.updated_at),"
           "r.last_request_key,r.last_request_digest,extract(epoch from r.due_at)::text,extract(epoch from r.created_at)::text,"
           "ARRAY(SELECT rt.thread_id::text FROM public.pr_relationship_threads rt WHERE rt.workspace_id=r.workspace_id AND rt.relationship_id=r.id "
           "ORDER BY rt.linked_at DESC,rt.thread_id LIMIT 20)")
FIELDS = ("id", "displayName", "contactProvider", "contactAccount", "contactRef", "interest", "state", "previousState", "stateChangedAt",
          "ownerId", "nextAction", "dueAt", "dueTimeZone", "dueFold", "dueRevision", "snoozedUntil", "followupDismissedKey", "notifiedKey",
          "suggestionDismissedKey", "notes", "wonResultId", "wonProvenance", "revision", "createdBy", "createdAt", "updatedAt",
          "lastRequestKey", "lastRequestDigest", "dueSort", "createdSort", "threadIds")
_TIMES = ("stateChangedAt", "dueAt", "snoozedUntil", "createdAt", "updatedAt")


def parse_row(values):
    row = dict(zip(FIELDS, values))
    for key in _TIMES:
        if row[key] is not None:
            row[key] = float(row[key])
    notes = row["notes"]
    row["notes"] = json.loads(notes) if isinstance(notes, str) else list(notes or [])
    row["threadIds"] = list(row["threadIds"] or [])
    return row


def view(row, members, now, *, detail=False):
    owner = None
    if row["ownerId"]:
        owner = {"userId": row["ownerId"], "displayName": members.get(row["ownerId"], ""), "active": row["ownerId"] in members}
    out = {
        "id": row["id"], "revision": row["revision"], "displayName": row["displayName"],
        "contact": {"provider": row["contactProvider"], "accountId": row["contactAccount"], "ref": row["contactRef"]} if row["contactProvider"] else None,
        "interest": row["interest"], "state": row["state"], "previousState": row["previousState"], "stateChangedAt": row["stateChangedAt"],
        "owner": owner, "nextAction": row["nextAction"],
        "due": due_view(row["dueAt"], row["dueTimeZone"], row["dueFold"], row["dueRevision"]),
        "snoozedUntil": row["snoozedUntil"], "followUp": followup(row, now),
        "won": {"resultId": row["wonResultId"], "provenance": row["wonProvenance"]} if row["state"] == "won" else None,
        "threadIds": row["threadIds"], "noteCount": len(row["notes"]),
        "createdAt": row["createdAt"], "updatedAt": row["updatedAt"], "createdBy": row["createdBy"],
    }
    if detail:
        out["notes"] = [{"id": n.get("id"), "text": n.get("text"), "by": n.get("by"), "at": n.get("at")} for n in row["notes"] if isinstance(n, dict)]
    return out


def members(cur, workspace_id):
    cur.execute("SELECT m.user_id::text,coalesce(p.display_name,'') FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id "
                "WHERE m.workspace_id=%s AND m.status='active' AND p.deleted_at IS NULL", (workspace_id,))
    return {user_id: name for user_id, name in cur.fetchall()}


THREAD_SQL = ("SELECT t.id::text,t.provider,t.connection_id,t.author_handle,t.text,extract(epoch from coalesce(t.created_at_provider,t.ingested_at)),"
              "t.permalink,t.tombstoned_at IS NOT NULL,extract(epoch from rt.linked_at),"
              "(SELECT c.level FROM public.pr_channel_capabilities c WHERE c.workspace_id=t.workspace_id AND c.connection_id=t.connection_id AND c.capability='reply'),"
              "(SELECT jsonb_build_object('status',d.status,'text',d.text,'at',extract(epoch from d.updated_at)) FROM public.pr_reply_drafts d "
              " WHERE d.workspace_id=t.workspace_id AND d.thread_id=t.id ORDER BY d.updated_at DESC,d.id DESC LIMIT 1),"
              "(SELECT extract(epoch from max(d.updated_at)) FROM public.pr_reply_drafts d WHERE d.workspace_id=t.workspace_id AND d.thread_id=t.id "
              " AND d.status IN ('submitted','verified')),rt.relationship_id::text "
              "FROM public.pr_relationship_threads rt JOIN public.pr_audience_threads t ON t.workspace_id=rt.workspace_id AND t.id=rt.thread_id ")


def thread_view(values):
    thread_id, provider, connection_id, author, body, at, permalink, tombstoned, linked_at, level, last, last_sent, _rid = values
    last = json.loads(last) if isinstance(last, str) else last
    return {"threadId": thread_id, "provider": provider, "connectionId": connection_id, "author": author or "", "excerpt": excerpt(body),
            "at": float(at) if at is not None else None, "permalink": permalink, "tombstoned": bool(tombstoned),
            "linkedAt": float(linked_at) if linked_at is not None else None, "replyLevel": level or "Unsupported",
            "lastReply": {"status": last.get("status"), "excerpt": excerpt(last.get("text")), "at": float(last["at"]) if last.get("at") is not None else None} if last else None,
            "lastSentAt": float(last_sent) if last_sent is not None else None,
            "replyRoute": reply_route(provider, level or "Unsupported", bool(tombstoned), permalink)}


def linked_threads(cur, workspace_id, relationship_ids, *, latest_only=False):
    """{relationship id: [thread summaries, newest comment first]} (bounded to 20 per relationship)."""
    if not relationship_ids:
        return {}
    cur.execute(THREAD_SQL + "WHERE rt.workspace_id=%s AND rt.relationship_id=ANY(%s::uuid[]) "
                "ORDER BY rt.relationship_id,coalesce(t.created_at_provider,t.ingested_at) DESC,t.id DESC", (workspace_id, list(relationship_ids)))
    out = {}
    for values in cur.fetchall():
        bucket = out.setdefault(values[-1], [])
        if len(bucket) < (1 if latest_only else MAX_THREADS):
            bucket.append(thread_view(values))
    return out


def due_followups(cur, workspace_id, now):
    """Cross-slice interface for the notification detector: follow-ups due now (not snoozed, not dismissed for this
    reminder, relationship still open) → ``[{id, dueAt, timeZone, threadId|None, dueRevision, dedupeKey}]``, oldest due
    first, at most 50. ``threadId`` is the linked thread with the newest comment (the prior exchange)."""
    cur.execute(f"SELECT r.id::text,extract(epoch from r.due_at),r.due_time_zone,r.due_revision,{REMINDER_TOKEN_SQL},"
                "(SELECT rt.thread_id::text FROM public.pr_relationship_threads rt JOIN public.pr_audience_threads t ON t.workspace_id=rt.workspace_id AND t.id=rt.thread_id "
                " WHERE rt.workspace_id=r.workspace_id AND rt.relationship_id=r.id ORDER BY coalesce(t.created_at_provider,t.ingested_at) DESC,t.id DESC LIMIT 1) "
                f"FROM public.pr_relationships r WHERE r.workspace_id=%s AND {DUE_NOW_SQL} ORDER BY r.due_at,r.id LIMIT 50",
                (workspace_id, now, now))
    return [{"id": rid, "dueAt": float(due_at), "timeZone": zone_name, "threadId": thread_id, "dueRevision": revision,
             "dedupeKey": dedupe_key(rid, token)} for rid, due_at, zone_name, revision, token, thread_id in cur.fetchall()]


def link_id(value):
    """An id for stored links: ``u`` + the uuid's 32 hex digits. The notification store redacts digit runs that start
    after a non-word character (possible phone numbers), which breaks hyphenated uuids; a token that starts with a letter
    and has no hyphens can never match. ``ident`` and the Inbox accept this form."""
    return "u" + uuid.UUID(value).hex


def followup_event(item):
    """The notification/attention event for one due follow-up. Content-free: no name, note, interest or message text."""
    href = f"/app/inbox?filter=follow_ups&relationship={link_id(item['id'])}" + (f"&thread={link_id(item['threadId'])}" if item.get("threadId") else "")
    return {"event_type": EVENT, "dedupe_key": item["dedupeKey"], "entity_type": "relationship", "entity_id": item["id"],
            "payload": {"title": "A follow-up is due", "reason": "Follow-up due", "href": href}}


def detector_events(cur, workspace_id, now):
    """Events for ``notifications.detector.from_database``. Flag-gated; never raises and never poisons the caller's
    transaction (its own SAVEPOINT), so a database without migration 081 simply has no follow-up events."""
    if not enabled():
        return []
    try:
        cur.execute("SAVEPOINT relationship_followups")
    except Exception:  # noqa: BLE001
        return []
    try:
        events = [followup_event(item) for item in due_followups(cur, workspace_id, now)]
        cur.execute("RELEASE SAVEPOINT relationship_followups")
        return events
    except Exception:  # noqa: BLE001 - reminders are optional; the rest of the detector must still run
        try:
            cur.execute("ROLLBACK TO SAVEPOINT relationship_followups")
        except Exception:  # noqa: BLE001
            pass
        return []


def attention_context(cur, workspace_id, items, now):
    """Enrich ``relationship.follow_up_due`` Attention items (read by a member who may reply) with the prior exchange,
    the reason and the one action. Never raises; on any failure the items stay as they are."""
    wanted = {item.get("evidence", {}).get("entityId"): item for item in items if item.get("type") == EVENT}
    wanted.pop(None, None)
    if not wanted:
        return items
    try:
        cur.execute("SAVEPOINT relationship_attention")
    except Exception:  # noqa: BLE001
        return items
    try:
        cur.execute(f"SELECT {ROW_SQL} FROM public.pr_relationships r WHERE r.workspace_id=%s AND r.id=ANY(%s::uuid[])", (workspace_id, list(wanted)))
        rows = {row["id"]: row for row in map(parse_row, cur.fetchall())}
        latest = linked_threads(cur, workspace_id, list(rows), latest_only=True)
        people = members(cur, workspace_id)
        cur.execute("RELEASE SAVEPOINT relationship_attention")
    except Exception:  # noqa: BLE001
        try:
            cur.execute("ROLLBACK TO SAVEPOINT relationship_attention")
        except Exception:  # noqa: BLE001
            pass
        return items
    for rid, item in wanted.items():
        row = rows.get(rid)
        if row is None:
            continue
        thread = (latest.get(rid) or [None])[0]
        due = due_view(row["dueAt"], row["dueTimeZone"], row["dueFold"], row["dueRevision"])
        exchange = []
        if thread:
            exchange.append({"direction": "inbound", "author": thread["author"], "provider": thread["provider"], "excerpt": thread["excerpt"], "at": thread["at"]})
            if thread["lastReply"]:
                exchange.append({"direction": "outbound", "status": thread["lastReply"]["status"], "excerpt": thread["lastReply"]["excerpt"], "at": thread["lastReply"]["at"]})
        item["title"] = f"Follow up with {row['displayName']}"
        item["detail"] = row["nextAction"] or ""
        item["context"] = {"relationshipId": rid, "revision": row["revision"], "displayName": row["displayName"], "state": row["state"],
                           "nextAction": row["nextAction"], "interest": row["interest"], "due": due, "reason": "due",
                           "owner": {"userId": row["ownerId"], "displayName": people.get(row["ownerId"], ""), "active": row["ownerId"] in people} if row["ownerId"] else None,
                           "threadId": thread["threadId"] if thread else None, "exchange": exchange,
                           "replyRoute": thread["replyRoute"] if thread else {"kind": "assisted", "provider": row["contactProvider"], "href": None, "reason": "no_thread"}}
    return items


def declared_result(cur, workspace_id, result_id):
    """``won`` needs a declared business result in this workspace (results slice, migration 080)."""
    result_id = ident(result_id, missing="Choose the declared result this follow-up won.", code="result_required", status=400)
    try:
        from ..results import service as results_service
    except ImportError:
        results_service = None
    if results_service is None or not hasattr(results_service, "get_declared"):
        raise AlphaError("Marking a follow-up as won needs a declared business result, and results aren't available in this workspace yet.", 400, code="result_required")
    cur.execute("SAVEPOINT relationship_result")
    try:
        found = results_service.get_declared(cur, workspace_id, result_id)
        cur.execute("RELEASE SAVEPOINT relationship_result")
    except Exception:  # noqa: BLE001 - an unavailable results store is a refusal, never a guess
        cur.execute("ROLLBACK TO SAVEPOINT relationship_result")
        found = None
    if not found:
        raise AlphaError("That isn't a declared result in this workspace. Record the result first, then mark the follow-up as won.", 400, code="result_required")
    provenance = found.get("provenance") if isinstance(found, dict) else getattr(found, "provenance", None)
    return {"resultId": result_id, "provenance": provenance if provenance in PROVENANCE else None}


def record(cur, workspace_id, relationship_id, actor, kind, *, from_state=None, to_state=None, meta=None):
    """One append-only history row plus the matching audit event, both content-free."""
    from ..hosted import audit
    meta = clean_meta(meta)
    cur.execute("INSERT INTO public.pr_relationship_events(workspace_id,relationship_id,kind,from_state,to_state,actor,meta) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (workspace_id, relationship_id, kind, from_state, to_state, actor, json.dumps(meta)))
    audit(cur, workspace_id, actor, f"relationship.{kind}", relationship_id,
          {**({"from": from_state} if from_state else {}), **({"to": to_state} if to_state else {}), **meta})


# --- service ---------------------------------------------------------------------------------------------------------------
class RelationshipService:
    def __init__(self, hosted):
        self.hosted = hosted
        self.repository = hosted.repository
        self.clock = getattr(hosted, "clock", None) or time.time

    @contextmanager
    def _tx(self, token, workspace_id, need):
        require_enabled()
        workspace_id = ident(workspace_id, missing="Workspace unavailable.", code="permission_denied", status=403)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            member = Membership.from_row(*row[2:7])
            require(member, need)
            yield cur, workspace_id, principal, member

    # --- reads --------------------------------------------------------------------------------------------------------
    def list(self, workspace_id, token, query=None):
        query = {k: v for k, v in (query or {}).items() if v not in (None, "")}
        limit = page_limit(query.get("limit"))
        cursor = decode_cursor(query["cursor"]) if query.get("cursor") else None
        now = self.clock()
        with self._tx(token, workspace_id, "read") as (cur, workspace_id, principal, _member):
            where, params = ["r.workspace_id=%s"], [workspace_id]
            state = query.get("state", "open")
            if state == "open":
                where.append("r.state NOT IN ('won','closed')")
            elif state in STATES:
                where.append("r.state=%s")
                params.append(state)
            elif state != "all":
                raise _invalid("Filter by a known state.")
            due = query.get("due")
            if due == "due_now":
                where.append(DUE_NOW_SQL)
                params.extend([now, now])
            elif due == "overdue":
                where.append("r.due_at<=to_timestamp(%s)")
                params.append(now)
            elif due == "upcoming":
                where.append("r.due_at>to_timestamp(%s)")
                params.append(now)
            elif due == "none":
                where.append("r.due_at IS NULL")
            elif due == "any":
                where.append("r.due_at IS NOT NULL")
            elif due is not None:
                raise _invalid("Filter due by due_now, overdue, upcoming, any or none.")
            owner = query.get("owner")
            if owner == "me":
                where.append("r.owner_id=%s")
                params.append(principal)
            elif owner == "unassigned":
                where.append("r.owner_id IS NULL")
            elif owner is not None:
                where.append("r.owner_id=%s")
                params.append(ident(owner, missing="Filter by a member.", code="invalid_input", status=400))
            if query.get("thread"):
                where.append("EXISTS (SELECT 1 FROM public.pr_relationship_threads rt WHERE rt.workspace_id=r.workspace_id AND rt.relationship_id=r.id AND rt.thread_id=%s)")
                params.append(ident(query["thread"], missing="Thread unavailable.", code="thread_unavailable"))
            if cursor:
                cursor_due, cursor_created, cursor_id = cursor
                if cursor_due is None:
                    where.append("r.due_at IS NULL AND (extract(epoch from r.created_at),r.id)<(%s::numeric,%s::uuid)")
                    params.extend([cursor_created, cursor_id])
                else:
                    where.append("(r.due_at IS NULL OR extract(epoch from r.due_at)>%s::numeric OR (extract(epoch from r.due_at)=%s::numeric "
                                 "AND (extract(epoch from r.created_at),r.id)<(%s::numeric,%s::uuid)))")
                    params.extend([cursor_due, cursor_due, cursor_created, cursor_id])
            cur.execute(f"SELECT {ROW_SQL} FROM public.pr_relationships r WHERE {' AND '.join(where)} "
                        "ORDER BY r.due_at ASC NULLS LAST,r.created_at DESC,r.id DESC LIMIT %s", (*params, limit + 1))
            rows = [parse_row(values) for values in cur.fetchall()]
            has_more = len(rows) > limit
            rows = rows[:limit]
            people = members(cur, workspace_id)
            cur.execute(f"SELECT count(*) FILTER (WHERE r.state NOT IN ('won','closed')),count(*) FILTER (WHERE {DUE_NOW_SQL}) "
                        "FROM public.pr_relationships r WHERE r.workspace_id=%s", (now, now, workspace_id))
            open_count, due_count = cur.fetchone()
            return {"relationships": [view(row, people, now) for row in rows], "nextCursor": encode_cursor(rows[-1]) if has_more and rows else None,
                    "counts": {"open": open_count, "dueNow": due_count}, "asOf": now, "dataState": "available",
                    "limits": {"page": PAGE_MAX, "notes": MAX_NOTES, "threads": MAX_THREADS}}

    def detail(self, workspace_id, token, relationship_id):
        rid = ident(relationship_id)
        with self._tx(token, workspace_id, "read") as (cur, workspace_id, _principal, _member):
            return self._detail(cur, workspace_id, rid, self.clock())

    def _detail(self, cur, workspace_id, rid, now):
        row = self._row(cur, workspace_id, rid)
        threads = linked_threads(cur, workspace_id, [rid]).get(rid, [])
        cur.execute("SELECT kind,from_state,to_state,actor::text,meta,extract(epoch from occurred_at) FROM public.pr_relationship_events "
                    "WHERE workspace_id=%s AND relationship_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 20", (workspace_id, rid))
        history = [{"kind": kind, "from": from_state, "to": to_state, "actor": actor, "meta": meta if isinstance(meta, dict) else json.loads(meta or "{}"),
                    "at": float(at)} for kind, from_state, to_state, actor, meta, at in cur.fetchall()]
        out = view(row, members(cur, workspace_id), now, detail=True)
        out["threads"] = threads
        out["suggestion"] = suggest(row, threads, now)
        out["history"] = history
        out["replyRoute"] = threads[0]["replyRoute"] if threads else {"kind": "assisted", "provider": row["contactProvider"], "href": None, "reason": "no_thread"}
        return {"relationship": out, "asOf": now}

    def _row(self, cur, workspace_id, rid, *, lock=False):
        cur.execute(f"SELECT {ROW_SQL} FROM public.pr_relationships r WHERE r.workspace_id=%s AND r.id=%s" + (" FOR UPDATE OF r" if lock else ""), (workspace_id, rid))
        values = cur.fetchone()
        if values is None:
            raise AlphaError("Relationship unavailable.", 404, code="relationship_not_found")
        return parse_row(values)

    @staticmethod
    def _thread(cur, workspace_id, thread_id):
        tid = ident(thread_id, missing="That conversation isn't available in this workspace.", code="thread_unavailable")
        cur.execute("SELECT id::text,provider,connection_id,author_handle FROM public.pr_audience_threads WHERE workspace_id=%s AND id=%s", (workspace_id, tid))
        found = cur.fetchone()
        if not found:   # foreign and unknown threads answer the same
            raise AlphaError("That conversation isn't available in this workspace.", 404, code="thread_unavailable")
        return {"id": found[0], "provider": found[1], "connectionId": found[2], "author": found[3] or ""}

    @staticmethod
    def _owner(cur, workspace_id, user_id):
        if user_id is None:
            return None
        oid = ident(user_id, missing="Assign the follow-up to a member of this workspace.", code="owner_not_member", status=400)
        cur.execute("SELECT 1 FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id WHERE m.workspace_id=%s AND m.user_id=%s "
                    "AND m.status='active' AND p.deleted_at IS NULL", (workspace_id, oid))
        if cur.fetchone() is None:
            raise AlphaError("Assign the follow-up to a member of this workspace.", 400, code="owner_not_member")
        return oid

    # --- create -------------------------------------------------------------------------------------------------------
    def create(self, workspace_id, token, payload):
        payload = payload if isinstance(payload, dict) else {}
        key = idempotency_key(payload.get("idempotencyKey"), required=True)
        request = digest({"op": "create", "payload": {k: v for k, v in payload.items() if k != "idempotencyKey"}})
        now = self.clock()
        with self._tx(token, workspace_id, "edit") as (cur, workspace_id, principal, _member):
            cur.execute("SELECT id::text,request_digest FROM public.pr_relationships WHERE workspace_id=%s AND idempotency_key=%s", (workspace_id, key))
            existing = cur.fetchone()
            if existing:
                if existing[1] != request:
                    raise AlphaError("This idempotency key was already used for a different follow-up.", 409, code="idempotency_conflict")
                return {**self._detail(cur, workspace_id, existing[0], now), "replayed": True}
            thread = self._thread(cur, workspace_id, payload["threadId"]) if payload.get("threadId") is not None else None
            name = text(payload.get("displayName"), LIMITS["displayName"], "a name", required=thread is None)
            if name is None:
                name = (f"@{thread['author'].lstrip('@')}" if thread["author"] else "Conversation")[:LIMITS["displayName"]]
            who = contact(payload.get("contact")) if "contact" in payload else (
                {"provider": thread["provider"], "accountId": thread["connectionId"], "ref": thread["author"][:LIMITS["contactRef"]] or None} if thread else None)
            interest = text(payload.get("interest"), LIMITS["interest"], "the stated interest")
            next_action = text(payload.get("nextAction"), LIMITS["nextAction"], "the next action")
            due = resolve_due(payload.get("due"), now)
            owner = self._owner(cur, workspace_id, payload["ownerId"]) if "ownerId" in payload else principal
            cur.execute("INSERT INTO public.pr_relationships(workspace_id,display_name,contact_provider,contact_account,contact_ref,interest,owner_id,next_action,"
                        "due_at,due_time_zone,due_fold,due_revision,idempotency_key,request_digest,created_by) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,%s,%s) RETURNING id::text",
                        (workspace_id, name, who and who["provider"], who and who["accountId"], who and who["ref"], interest, owner, next_action,
                         due and due["at"], due and due["timeZone"], due["fold"] if due else 0, 1 if due else 0, key, request, principal))
            rid = cur.fetchone()[0]
            record(cur, workspace_id, rid, principal, "created", to_state="new",
                   meta={"source": "thread" if thread else "manual", "hasDue": due is not None, "owner": owner})
            if thread:
                cur.execute("INSERT INTO public.pr_relationship_threads(workspace_id,relationship_id,thread_id,linked_by) VALUES(%s,%s,%s,%s)",
                            (workspace_id, rid, thread["id"], principal))
                record(cur, workspace_id, rid, principal, "thread_linked", meta={"threadId": thread["id"]})
            return {**self._detail(cur, workspace_id, rid, now), "replayed": False}

    # --- changes ------------------------------------------------------------------------------------------------------
    def _change(self, workspace_id, token, relationship_id, payload, op, apply):
        """The one write path for existing records: lock, replay/conflict checks, ``apply(cur, row, principal, now)`` →
        (column updates, history events, product outcome or None), then one revision bump and an authoritative read-back."""
        payload = payload if isinstance(payload, dict) else {}
        rid = ident(relationship_id)
        key = idempotency_key(payload.get("idempotencyKey"), required=False)
        request = digest({"op": op, "relationship": rid, "payload": {k: v for k, v in payload.items() if k not in ("idempotencyKey", "expectedRevision")}})
        now = self.clock()
        with self._tx(token, workspace_id, "edit") as (cur, workspace_id, principal, _member):
            row = self._row(cur, workspace_id, rid, lock=True)
            if key is not None and key == row["lastRequestKey"]:
                if row["lastRequestDigest"] != request:
                    raise AlphaError("This idempotency key was already used for a different change.", 409, code="idempotency_conflict")
                return {**self._detail(cur, workspace_id, rid, now), "changed": False, "replayed": True}
            if expected_revision(payload) != row["revision"]:
                raise AlphaError("This follow-up changed since you opened it. Reload it and try again.", 409, code="revision_conflict")
            updates, events, outcome = apply(cur, workspace_id, row, principal, now)
            if not updates and not events:
                return {**self._detail(cur, workspace_id, rid, now), "changed": False, "replayed": False}
            columns, values = [], []
            for column, value in updates.items():
                if column in ("due_at", "snoozed_until", "state_changed_at"):
                    columns.append(f"{column}=to_timestamp(%s)")
                elif column == "notes":
                    columns.append("notes=%s::jsonb")
                    value = json.dumps(value)
                else:
                    columns.append(f"{column}=%s")
                values.append(value)
            columns += ["revision=revision+1", "updated_at=now()", "last_request_key=%s", "last_request_digest=%s"]
            values += [key, request if key else None]
            cur.execute(f"UPDATE public.pr_relationships SET {','.join(columns)} WHERE workspace_id=%s AND id=%s AND revision=%s RETURNING revision",
                        (*values, workspace_id, rid, row["revision"]))
            revision = cur.fetchone()[0]
            for kind, from_state, to_state, meta in events:
                record(cur, workspace_id, rid, principal, kind, from_state=from_state, to_state=to_state, meta=meta)
            if outcome:
                from .. import growth_events
                growth_events.emit(cur, workspace_id=workspace_id, event="relationship.followup_outcome", entity_id=rid, revision=revision,
                                   user_id=principal, values={"state": outcome[1], "previous": outcome[0]})
            return {**self._detail(cur, workspace_id, rid, now), "changed": True, "replayed": False}

    def update(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        unknown = set(payload) - set(UPDATABLE_FIELDS) - {"due", "expectedRevision", "idempotencyKey"}
        if unknown:
            raise _invalid("Only the name, contact, interest, next action and due time can be edited here.")

        def apply(cur, workspace_id, row, principal, now):
            updates, changed = {}, []
            values = {}
            if "displayName" in payload:
                values["display_name"] = (text(payload["displayName"], LIMITS["displayName"], "a name", required=True), row["displayName"])
            if "interest" in payload:
                values["interest"] = (text(payload["interest"], LIMITS["interest"], "the stated interest"), row["interest"])
            if "nextAction" in payload:
                values["next_action"] = (text(payload["nextAction"], LIMITS["nextAction"], "the next action"), row["nextAction"])
            for column, (value, current) in values.items():
                if value != current:
                    updates[column] = value
                    changed.append(column)
            if "contact" in payload:
                who = contact(payload["contact"])
                current = {"provider": row["contactProvider"], "accountId": row["contactAccount"], "ref": row["contactRef"]} if row["contactProvider"] else None
                if who != current:
                    updates.update({"contact_provider": who and who["provider"], "contact_account": who and who["accountId"], "contact_ref": who and who["ref"]})
                    changed.append("contact")
            events = [("updated", None, None, {"fields": changed})] if changed else []
            if "due" in payload:
                due = resolve_due(payload["due"], now)
                current = (row["dueAt"], row["dueTimeZone"], row["dueFold"]) if row["dueAt"] is not None else None
                if (due and (due["at"], due["timeZone"], due["fold"])) != current:
                    # A new due time is a new reminder: the revision moves on and any snooze of the old one ends.
                    updates.update({"due_at": due and due["at"], "due_time_zone": due and due["timeZone"], "due_fold": due["fold"] if due else 0,
                                    "due_revision": row["dueRevision"] + 1, "snoozed_until": None})
                    events.append(("due_changed", None, None, {"dueRevision": row["dueRevision"] + 1, "hasDue": due is not None}))
            return updates, events, None
        return self._change(workspace_id, token, relationship_id, payload, "update", apply)

    def transition(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        target = payload.get("to")
        if target not in STATES:
            raise _invalid("Choose new, replied, waiting, follow_up_due, won or closed.")

        def apply(cur, workspace_id, row, principal, now):
            current = row["state"]
            if target == current:
                return {}, [], None
            updates = {"state": target, "state_changed_at": now}
            meta = {"fromSuggestion": bool(payload.get("suggestionKey"))} if payload.get("suggestionKey") else {}
            if target == "won":
                won = declared_result(cur, workspace_id, payload.get("wonResultId"))
                updates.update({"won_result_id": won["resultId"], "won_provenance": won["provenance"],
                                "previous_state": current if current in OPEN_STATES else row["previousState"]})
                return updates, [("state", current, target, {**meta, "resultId": won["resultId"], "provenance": won["provenance"]})], (current, target)
            if target == "closed":
                updates.update({"won_result_id": None, "won_provenance": None,
                                "previous_state": current if current in OPEN_STATES else row["previousState"]})
                return updates, [("closed", current, target, meta)], (current, target)
            if current in TERMINAL:   # back into an open state: a reopen to the state the person chose
                updates.update({"previous_state": None, "won_result_id": None, "won_provenance": None})
                return updates, [("reopened", current, target, meta)], (current, target)
            return updates, [("state", current, target, meta)], (current, target)
        return self._change(workspace_id, token, relationship_id, payload, "transition", apply)

    def reopen(self, workspace_id, token, relationship_id, payload):
        """Undo of close/won: back to the open state it left (``new`` when unknown)."""
        def apply(cur, workspace_id, row, principal, now):
            if row["state"] not in TERMINAL:
                return {}, [], None
            target = row["previousState"] if row["previousState"] in OPEN_STATES else "new"
            return ({"state": target, "state_changed_at": now, "previous_state": None, "won_result_id": None, "won_provenance": None},
                    [("reopened", row["state"], target, {})], (row["state"], target))
        return self._change(workspace_id, token, relationship_id, payload, "reopen", apply)

    def snooze(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}

        def apply(cur, workspace_id, row, principal, now):
            if row["state"] in TERMINAL:
                raise AlphaError("Reopen this follow-up before snoozing it.", 409, code="relationship_closed")
            until = instant(payload.get("until"), "snooze time")
            if not now < until <= now + SNOOZE_MAX_SECONDS:
                raise _invalid("Snooze until a time within the next year.", "snooze_invalid")
            return {"snoozed_until": until}, [("snoozed", None, None, {"until": int(until)})], None
        return self._change(workspace_id, token, relationship_id, payload, "snooze", apply)

    def unsnooze(self, workspace_id, token, relationship_id, payload):
        def apply(cur, workspace_id, row, principal, now):
            if not row["snoozedUntil"]:
                return {}, [], None
            return {"snoozed_until": None}, [("unsnoozed", None, None, {})], None
        return self._change(workspace_id, token, relationship_id, payload, "unsnooze", apply)

    def assign(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        if "ownerId" not in payload:
            raise _invalid("Choose a member, or null to unassign.")

        def apply(cur, workspace_id, row, principal, now):
            owner = self._owner(cur, workspace_id, payload["ownerId"])
            if owner == row["ownerId"]:
                return {}, [], None
            return {"owner_id": owner}, [("assigned", None, None, {"owner": owner, "previousOwner": row["ownerId"]})], None
        return self._change(workspace_id, token, relationship_id, payload, "assign", apply)

    def link_thread(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}

        def apply(cur, workspace_id, row, principal, now):
            thread = self._thread(cur, workspace_id, payload.get("threadId"))
            if thread["id"] in row["threadIds"]:
                return {}, [], None
            if len(row["threadIds"]) >= MAX_THREADS:
                raise AlphaError(f"A follow-up can link at most {MAX_THREADS} conversations.", 409, code="too_many_threads")
            cur.execute("INSERT INTO public.pr_relationship_threads(workspace_id,relationship_id,thread_id,linked_by) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (workspace_id, row["id"], thread["id"], principal))
            return {}, [("thread_linked", None, None, {"threadId": thread["id"]})], None
        return self._change(workspace_id, token, relationship_id, payload, "link", apply)

    def unlink_thread(self, workspace_id, token, relationship_id, thread_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        tid = ident(thread_id, missing="That conversation isn't linked to this follow-up.", code="thread_unavailable")

        def apply(cur, workspace_id, row, principal, now):
            cur.execute("DELETE FROM public.pr_relationship_threads WHERE workspace_id=%s AND relationship_id=%s AND thread_id=%s", (workspace_id, row["id"], tid))
            if cur.rowcount != 1:
                raise AlphaError("That conversation isn't linked to this follow-up.", 404, code="thread_unavailable")
            return {}, [("thread_unlinked", None, None, {"threadId": tid})], None
        return self._change(workspace_id, token, relationship_id, {**payload, "threadId": tid}, "unlink", apply)

    def add_note(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        body = text(payload.get("text"), LIMITS["note"], "the note", required=True, multiline=True)

        def apply(cur, workspace_id, row, principal, now):
            if len(row["notes"]) >= MAX_NOTES:
                raise AlphaError(f"A follow-up keeps at most {MAX_NOTES} notes. Remove one first.", 409, code="notes_full")
            note = {"id": str(uuid.uuid4()), "text": body, "by": principal, "at": now}
            return {"notes": [*row["notes"], note]}, [("note_added", None, None, {"noteId": note["id"]})], None
        return self._change(workspace_id, token, relationship_id, payload, "note_add", apply)

    def remove_note(self, workspace_id, token, relationship_id, note_id, payload):
        payload = payload if isinstance(payload, dict) else {}
        nid = ident(note_id, missing="Note unavailable.", code="note_not_found")

        def apply(cur, workspace_id, row, principal, now):
            kept = [note for note in row["notes"] if not (isinstance(note, dict) and note.get("id") == nid)]
            if len(kept) == len(row["notes"]):
                raise AlphaError("Note unavailable.", 404, code="note_not_found")
            return {"notes": kept}, [("note_removed", None, None, {"noteId": nid})], None
        return self._change(workspace_id, token, relationship_id, {**payload, "noteId": nid}, "note_remove", apply)

    def dismiss_followup(self, workspace_id, token, relationship_id, payload):
        """"Not relevant": quiet this reminder until its due time (revision) or snooze changes. Undo restores it."""
        def apply(cur, workspace_id, row, principal, now):
            if not followup(row, now)["dueNow"]:
                raise AlphaError("This follow-up isn't due right now.", 409, code="followup_not_due")
            return {"followup_dismissed_key": reminder_token(row)}, [("followup_dismissed", None, None, {"dueRevision": row["dueRevision"]})], None
        return self._change(workspace_id, token, relationship_id, payload, "dismiss", apply)

    def restore_followup(self, workspace_id, token, relationship_id, payload):
        def apply(cur, workspace_id, row, principal, now):
            if not row["followupDismissedKey"]:
                return {}, [], None
            return {"followup_dismissed_key": None}, [("followup_restored", None, None, {"dueRevision": row["dueRevision"]})], None
        return self._change(workspace_id, token, relationship_id, payload, "restore", apply)

    def dismiss_suggestion(self, workspace_id, token, relationship_id, payload):
        payload = payload if isinstance(payload, dict) else {}

        def apply(cur, workspace_id, row, principal, now):
            threads = linked_threads(cur, workspace_id, [row["id"]]).get(row["id"], [])
            current = suggest(row, threads, now)
            if current is None or current["key"] != payload.get("key"):
                raise AlphaError("This suggestion changed. Reload the follow-up.", 409, code="suggestion_changed")
            return ({"suggestion_dismissed_key": current["key"]},
                    [("suggestion_dismissed", None, None, {"suggested": current["state"], "reason": current["reason"]})], None)
        return self._change(workspace_id, token, relationship_id, payload, "dismiss_suggestion", apply)
