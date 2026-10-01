"""Customer business results (PRD R-OUT-01..03, plan G2-OUT): declarations, one signed first-party receiver, tracking
links, and truthful reads.

* Declarations (`user_declared`): declare, amend and reverse. Every change is a new append-only row; an amendment is a
  complete new version of the result it corrects, a reversal withdraws it. Only the person's own declarations can be
  amended or reversed here; a connected producer corrects its own events with ``reversalOf``.
* Connections (`first_party_reported`, owner only): the secret is shown once, stored only encrypted with the existing
  CredentialVault, and rotated with a 24-hour grace for the previous one. Pausing or removing stops ingestion; removal
  destroys the secret and keeps the evidence already received (it is deleted with the workspace, like other records).
* Public ingestion: size cap → connection lookup → rate budget (before any signature work) → signature on the exact
  bytes → verified-event budget → JSON → normalization → association against this workspace's own links only →
  idempotent insert (exact replay is a no-op; a conflicting payload is quarantined, never applied).
* Tracking links: server-created opaque slugs bound to one validated public HTTPS destination. The redirect appends
  ``rafii_ref=<slug>.<YYYYMMDD>`` and counts the click into a daily aggregate; no address, user agent or identifier
  is stored. Counts are clicks, not people.

Nothing here logs or stores a request body, secret, contact detail or URL in an audit row or product event.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import socket
import time
import uuid
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from postriff_alpha.domain import AlphaError

from .. import growth_events, net_guard
from ..permissions import require
from . import model, signing

FLAG = "RAFII_RESULTS_ENABLED"
SUMMARY_DEFINITION = "rafii.results-summary.v1"
DECLARED_LINK_DEFINITION = "rafii.user-declared-link.v1"
ROTATION_GRACE_SECONDS = 24 * 3600
MAX_CONNECTIONS = 10                # live (not removed) connections per workspace
MAX_ACTIVE_LINKS = 200
DELIVERY_BUDGET_FACTOR = 3          # unverified deliveries allowed per minute = 3 × the verified rate
LINK_BURST_PER_MINUTE = 300         # more counted clicks than this on one link in a minute are treated as automated
STALE_AFTER_SECONDS = 7 * 86400
PAGE_DEFAULT, PAGE_MAX = 25, 50
PRODUCERS = ("form", "booking", "newsletter", "store", "other")
WEBHOOK_PREFIX = "/api/results/webhook/"
LINK_PREFIX = "/api/l/"
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_SLUG = re.compile(r"^[A-Za-z0-9_-]{10,32}$")
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\<>\"`]")
_URL_SAFE = "/:?#[]@!$&'()*+,;=%-._~"
# A conservative, documented heuristic: automated fetchers that announce themselves, link-preview services, scripts
# and headless browsers. It cannot catch every bot, and is described in the product as "likely bots excluded where
# detectable", never as exact. Nothing about the request is stored.
_BOT = re.compile(r"bot\b|bot/|crawl|spider|slurp|preview|facebookexternalhit|facebookcatalog|embedly|whatsapp|telegram|discord|"
                  r"skypeuri|linkexpanding|headless|phantomjs|lighthouse|pingdom|uptime|monitor|python|curl|wget|httpclient|"
                  r"okhttp|go-http-client|axios|node-fetch|scrapy|java/|libwww|feedfetcher|validator|bingpreview|vkshare|qwant",
                  re.IGNORECASE)


# --- rules (pure) ---------------------------------------------------------------------------------------------------
def enabled(values=None):
    """Same semantics as the coworker flags (off unless 1/true/yes/on; preview-isolated environment)."""
    from ..coworker import flags
    return flags._truthy(flags._source(values).get(FLAG, ""))


def require_enabled(values=None):
    if not enabled(values):
        raise AlphaError("This feature is not available.", 404, code="feature_disabled")


def idempotency_key(payload):
    key = payload.get("idempotencyKey") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not _KEY.match(key):
        raise AlphaError("Send an idempotencyKey (8–80 letters, digits, - or _) for this change.", 400, code="idempotency_key_required")
    return key


def request_digest(operation, target, payload):
    body = {k: v for k, v in (payload or {}).items() if k != "idempotencyKey"}
    canonical = json.dumps({"op": operation, "target": target, "body": body}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def expected_revision(payload):
    value = payload.get("expectedRevision") if isinstance(payload, dict) else None
    if type(value) is not int or value < 1:
        raise AlphaError("Send the expectedRevision you last saw.", 400, code="revision_required")
    return value


def page_limit(value):
    if value is None or value == "":
        return PAGE_DEFAULT
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or not 1 <= value <= PAGE_MAX:
        raise AlphaError(f"Choose a page size from 1 to {PAGE_MAX}.", 400, code="invalid_request")
    return value


def encode_cursor(epoch, ident):
    return base64.urlsafe_b64encode(json.dumps([float(epoch), ident]).encode()).decode().rstrip("=")


def decode_cursor(cursor):
    if cursor is None or cursor == "":
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 200:
            raise ValueError()
        decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(decoded, list) or len(decoded) != 2 or isinstance(decoded[0], bool):
            raise ValueError()
        return float(decoded[0]), str(uuid.UUID(decoded[1]))
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError, binascii.Error):
        raise AlphaError("This page cursor is invalid.", 400, code="invalid_request") from None


def likely_bot(user_agent, method, purpose):
    """True when the request is probably not a person following the link (see _BOT)."""
    if method != "GET" or (purpose or "").strip().lower() in ("prefetch", "preview", "prerender"):
        return True
    agent = (user_agent or "").strip()
    return not agent or bool(_BOT.search(agent))


def redirect_location(destination, ref):
    """The stored destination with ``rafii_ref`` appended to its own query, which is kept byte for byte."""
    parts = urlsplit(destination)
    query = parts.query + ("&" if parts.query else "") + f"{model.REF_PARAMETER}={ref}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def validate_destination(url, resolver=socket.getaddrinfo, own_origin=None):
    """A public https:// address on the default port, without credentials, that is not this app's own redirect."""
    if not isinstance(url, str) or not 12 <= len(url.strip()) <= 2048:
        raise AlphaError("Enter the full https:// address people should reach (up to 2,048 characters).", 400, code="link_destination_invalid")
    url = url.strip()
    if _UNSAFE_URL_CHARS.search(url):
        raise AlphaError("That address has spaces or characters a link can't carry.", 400, code="link_destination_invalid")
    if not url.isascii():
        url = quote(url, safe=_URL_SAFE)   # a pasted path or query in any language, percent-encoded as UTF-8 (hosts must be ASCII)
    try:
        net_guard.public_https_url(url, resolver)
    except AlphaError:
        raise AlphaError("Links can only point to a public https:// website.", 400, code="link_destination_unsafe") from None
    parts = urlsplit(url)
    if any(name == model.REF_PARAMETER for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise AlphaError(f"The address already carries {model.REF_PARAMETER}; Rafii adds it on each click.", 400, code="link_destination_invalid")
    if own_origin:
        own = urlsplit(own_origin)
        if (parts.hostname or "").lower() == (own.hostname or "").lower() and parts.path.startswith(LINK_PREFIX):
            raise AlphaError("A tracking link can't point to another tracking link.", 400, code="link_destination_invalid")
    return url


def connection_health(status, last_received, last_event, last_error_code, last_error_at, now):
    lag = round(last_received - last_event) if last_received is not None and last_event is not None else None
    if status == "removed":
        state, reason = "unavailable", "removed"
    elif status == "paused":
        state, reason = "unavailable", "paused"
    elif last_error_at is not None and (last_received is None or last_error_at > last_received):
        state, reason = ("partial" if last_received is not None else "unavailable"), last_error_code
    elif last_received is None:
        state, reason = "unavailable", "no_events_yet"
    elif now - last_received > STALE_AFTER_SECONDS:
        state, reason = "stale", "no_recent_events"
    else:
        state, reason = "available", None
    return {"lastReceivedAt": last_received, "lastEventAt": last_event, "lagSeconds": lag, "lastErrorCode": last_error_code,
            "lastErrorAt": last_error_at, "dataState": state, "reason": reason}


def summary_state(coverage, end, now):
    """unavailable: no result source at all; partial: the period is still open (it ends now or later, so results can still
    arrive), or a source is paused or failing."""
    if not coverage["connections"] and not coverage["declarations"]:
        return "unavailable"
    if end >= now or coverage["paused"] or coverage["errored"]:
        return "partial"
    return "available"


def _ms(seconds):
    return round(float(seconds), 3)


def _uuid(value):
    try:
        return str(uuid.UUID(str(value))) if isinstance(value, str) and len(value) <= 64 else None
    except ValueError:
        return None


def _epoch(value):
    if isinstance(value, datetime):
        return value.timestamp() if value.tzinfo else value.replace(tzinfo=timezone.utc).timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise AlphaError("A period needs a start and an end time.", 400, code="invalid_request")


def _num(value):
    return float(value) if value is not None else None


def _object(payload):
    if not isinstance(payload, dict):
        raise AlphaError("Expected a structured request.", 400)
    return payload


def _label(value, fallback=None):
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    if not text and fallback:
        text = fallback
    if not 1 <= len(text) <= 80:
        raise AlphaError("Give it a short name (1–80 characters).", 400, code="result_label_invalid")
    return text


def _campaign(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.match(r"^[A-Za-z0-9_:-]{1,80}$", value):
        raise AlphaError("A campaign label is up to 80 letters, digits, - _ or :.", 400, code="result_campaign_invalid")
    return value


# --- SQL shared by the reads ---------------------------------------------------------------------------------------
# The current version of a result: its latest amendment (database commit order), or the original when there is none.
_VERSION = ("CROSS JOIN LATERAL (SELECT x.result_type,x.occurred_at,x.amount_minor,x.currency,x.quantity,x.link_id,x.campaign_ref,"
            "x.attribution,x.attribution_definition,x.note FROM public.pr_result_events x WHERE x.workspace_id=e.workspace_id AND "
            "(x.id=e.id OR (x.corrects_id=e.id AND x.kind='amendment')) ORDER BY (x.kind='amendment') DESC,x.created_at DESC,x.id DESC LIMIT 1) v")
_REVERSAL = "LEFT JOIN public.pr_result_events r ON r.workspace_id=e.workspace_id AND r.corrects_id=e.id AND r.kind='reversal'"
_EVENT_COLUMNS = ("e.id::text,e.provenance,e.connection_id::text,extract(epoch from e.received_at),e.test,v.result_type,"
                  "extract(epoch from v.occurred_at),v.amount_minor,v.currency,v.quantity,v.link_id::text,v.campaign_ref,v.attribution,"
                  "v.attribution_definition,v.note,(SELECT count(*) FROM public.pr_result_events c WHERE c.workspace_id=e.workspace_id "
                  "AND c.corrects_id=e.id AND c.kind='amendment'),r.id::text,extract(epoch from r.received_at),extract(epoch from e.occurred_at),"
                  "cn.label,cn.producer,l.label,l.slug")
_EVENT_JOINS = (f"FROM public.pr_result_events e {_VERSION} {_REVERSAL} "
                "LEFT JOIN public.pr_result_connections cn ON cn.workspace_id=e.workspace_id AND cn.id=e.connection_id "
                "LEFT JOIN public.pr_tracking_links l ON l.workspace_id=e.workspace_id AND l.id=v.link_id")


def _event_view(r):
    (ident, provenance, connection_id, received, test, rtype, occurred, minor, currency, quantity, link_id, campaign, attribution,
     definition, note, amendments, reversal_id, reversed_at, original_occurred, connection_label, producer, link_label, slug) = r
    return {"id": ident, "provenance": provenance, "type": rtype, "occurredAt": float(occurred), "receivedAt": float(received),
            "lagSeconds": round(float(received) - float(original_occurred)) if provenance == "first_party_reported" else None,
            "amount": {"minor": int(minor), "currency": currency} if minor is not None else None, "quantity": quantity,
            "linkId": link_id, "link": {"label": link_label, "slug": slug} if link_id and slug else None, "campaignRef": campaign,
            "attribution": attribution, "attributionDefinition": definition, "note": note if provenance == "user_declared" else None,
            "connectionId": connection_id, "connection": {"label": connection_label, "producer": producer} if connection_id else None,
            "test": bool(test), "revision": 1 + int(amendments), "amended": int(amendments) > 0,
            "status": "reversed" if reversal_id else "active", "reversedAt": _num(reversed_at), "reversalId": reversal_id,
            "editable": provenance == "user_declared" and not reversal_id}


def _read_event(cur, workspace_id, result_id):
    cur.execute(f"SELECT {_EVENT_COLUMNS} {_EVENT_JOINS} WHERE e.workspace_id=%s AND e.id=%s AND e.kind='event'", (workspace_id, result_id))
    row = cur.fetchone()
    return _event_view(row) if row else None


def _root(cur, workspace_id, result_id):
    """The original a result id (or one of its amendments) belongs to, in this workspace only; None otherwise."""
    ident = _uuid(result_id)
    if ident is None:
        return None
    cur.execute("SELECT CASE WHEN kind='amendment' THEN corrects_id::text ELSE id::text END,kind FROM public.pr_result_events "
                "WHERE workspace_id=%s AND id=%s", (workspace_id, ident))
    row = cur.fetchone()
    if row is None or row[1] == "reversal":
        return None
    return row[0]


def get_declared(cur, workspace_id, result_id):
    """The person's own declared result (current version) for cross-slice use, e.g. a relationship marked "won".
    None when the id is missing, belongs to another workspace, or is not a declaration. ``reversed`` says whether it was
    withdrawn; the caller decides what a withdrawn result means for it."""
    root = _root(cur, workspace_id, result_id)
    view = _read_event(cur, workspace_id, root) if root else None
    if view is None or view["provenance"] != "user_declared":
        return None
    return {k: view[k] for k in ("id", "provenance", "type", "occurredAt", "amount", "quantity", "linkId", "campaignRef", "attribution",
                                 "revision")} | {"reversed": view["status"] == "reversed"}


def _coverage(cur, workspace_id):
    cur.execute("SELECT count(*) FILTER (WHERE status<>'removed'),count(*) FILTER (WHERE status='active'),count(*) FILTER (WHERE status='paused'),"
                "count(*) FILTER (WHERE status='removed'),count(*) FILTER (WHERE status='active' AND last_error_at IS NOT NULL AND "
                "(last_received_at IS NULL OR last_error_at>last_received_at)),extract(epoch from max(last_received_at)) "
                "FROM public.pr_result_connections WHERE workspace_id=%s", (workspace_id,))
    live, active, paused, removed, errored, last = cur.fetchone()
    cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_result_events WHERE workspace_id=%s AND provenance='user_declared')", (workspace_id,))
    declarations = bool(cur.fetchone()[0])
    return {"connections": int(live), "active": int(active), "paused": int(paused), "removed": int(removed), "errored": int(errored),
            "lastReceivedAt": _num(last), "declarations": declarations}


def _grouped(cur, workspace_id, start, end):
    """One row per (class, type, withdrawn, associated, currency) for results whose current version occurred in
    [start, end). Test events are excluded. The database aggregates, so the read stays bounded."""
    cur.execute(f"SELECT e.provenance,v.result_type,(r.id IS NOT NULL),(v.attribution='associated'),v.currency,sum(v.quantity),"
                f"sum(v.amount_minor),count(v.amount_minor) FROM public.pr_result_events e {_VERSION} {_REVERSAL} "
                "WHERE e.workspace_id=%s AND e.kind='event' AND NOT e.test AND v.occurred_at>=to_timestamp(%s) AND v.occurred_at<to_timestamp(%s) "
                "GROUP BY 1,2,3,4,5", (workspace_id, start, end))
    return [{"id": f"group-{i}", "provenance": provenance, "type": rtype, "kind": "event", "quantity": int(quantity),
             "amount": {"minor": int(minor), "currency": currency} if currency else None, "events": int(events),
             "attribution": "associated" if associated else "unattributed", "reversed": bool(withdrawn)}
            for i, (provenance, rtype, withdrawn, associated, currency, quantity, minor, events) in enumerate(cur.fetchall())]


def period_summary(cur, workspace_id, start, end, *, now=None):
    """Cross-slice interface (proof, goals): ``model.summarize`` per provenance for results whose current version
    occurred in [start, end), plus the association definition, asOf and dataState. Counts and ids only, no text."""
    now = time.time() if now is None else float(now)
    start, end = _epoch(start), _epoch(end)
    out = model.summarize(_grouped(cur, workspace_id, start, end))
    return {**out, "definition": model.ASSOCIATION_DEFINITION, "asOf": now, "dataState": summary_state(_coverage(cur, workspace_id), end, now)}


def _budget(cur, scope, limit, window_seconds):
    """hosted.throttle's fixed-window counter (hashed scope), answering instead of raising."""
    from ..hosted import bucket
    cur.execute("INSERT INTO public.pr_auth_throttle(bucket,window_start,count) VALUES(%s,now(),1) ON CONFLICT(bucket) DO UPDATE SET "
                "count=CASE WHEN public.pr_auth_throttle.window_start < now()-make_interval(secs=>%s) THEN 1 ELSE public.pr_auth_throttle.count+1 END, "
                "window_start=CASE WHEN public.pr_auth_throttle.window_start < now()-make_interval(secs=>%s) THEN now() ELSE public.pr_auth_throttle.window_start END "
                "RETURNING count", (bucket(scope), window_seconds, window_seconds))
    return cur.fetchone()[0] <= limit


def _insert_event(cur, workspace_id, *, provenance, rtype, provider_event_id, occurred, received, connection_id=None, kind="event",
                  corrects_id=None, amount=None, quantity=1, link_id=None, campaign=None, attribution="unattributed",
                  definition=model.ASSOCIATION_DEFINITION, digest, declared_by=None, note=None, test=False):
    cur.execute("INSERT INTO public.pr_result_events(workspace_id,provenance,result_type,connection_id,provider_event_id,kind,corrects_id,"
                "occurred_at,received_at,amount_minor,currency,quantity,link_id,campaign_ref,attribution,attribution_definition,payload_digest,"
                "declared_by,note,test,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()) RETURNING id::text",
                (workspace_id, provenance, rtype, connection_id, provider_event_id, kind, corrects_id, _ms(occurred), _ms(received),
                 amount["minor"] if amount else None, amount["currency"] if amount else None, quantity, link_id, campaign, attribution,
                 definition, digest, declared_by, note, bool(test)))
    return cur.fetchone()[0]


class Delivery:
    """The answer to one webhook delivery: HTTP status, a content-free body, extra headers, and the health code to
    record on the connection (None when nothing went wrong)."""
    __slots__ = ("status", "body", "headers", "error")

    def __init__(self, status, body, headers=None, error=None):
        self.status, self.body, self.headers, self.error = status, body, headers or [], error


def _refused(http_status, code, message, health=None, headers=None, **extra):
    return Delivery(http_status, {"error": message, "code": code, **extra}, headers, health or code)


# --- the service ----------------------------------------------------------------------------------------------------
class ResultsService:
    def __init__(self, hosted, *, resolver=None):
        self.hosted = hosted
        self.repository = hosted.repository
        self.connection_factory = hosted.connection_factory
        self.clock = getattr(hosted, "clock", time.time)
        self.resolver = resolver or socket.getaddrinfo
        self.public_base_url = (getattr(hosted, "public_base_url", "") or "").rstrip("/")

    # -- shared ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _member(row):
        from ..hosted import _membership
        return _membership(row)

    @property
    def _vault(self):
        oauth = getattr(self.hosted, "oauth", None)
        return getattr(oauth, "vault", None)

    def _encrypt(self, secret):
        vault = self._vault
        if vault is None or not getattr(vault, "fernet", None):
            raise AlphaError("Connections can't be created here yet: secure key storage isn't set up.", 503, code="results_vault_unavailable")
        return vault.encrypt(secret)

    def _decrypt(self, ciphertext, key_id):
        vault = self._vault
        if not ciphertext or vault is None or not getattr(vault, "fernet", None):
            return None
        try:
            return vault.decrypt(ciphertext, key_id)
        except AlphaError:
            return None   # a changed vault key: the connection needs a new secret (health says so)

    @staticmethod
    def _replay(cur, workspace_id, key, operation, digest):
        cur.execute("SELECT operation,request_digest,subject_id::text FROM public.pr_result_mutations WHERE workspace_id=%s AND idempotency_key=%s",
                    (workspace_id, key))
        row = cur.fetchone()
        if row is None:
            return None
        if row[0] != operation or row[1] != digest:
            raise AlphaError("This request key was already used for a different change.", 409, code="idempotency_conflict")
        return row[2]

    @staticmethod
    def _remember(cur, workspace_id, key, operation, digest, subject_id):
        cur.execute("INSERT INTO public.pr_result_mutations(workspace_id,idempotency_key,operation,request_digest,subject_id) VALUES(%s,%s,%s,%s,%s)",
                    (workspace_id, key, operation, digest, subject_id))

    def _endpoint(self, connection_id):
        path = WEBHOOK_PREFIX + connection_id
        return {"path": path, "url": self.public_base_url + path if self.public_base_url else None, "method": "POST",
                "signatureHeader": "X-Rafii-Signature", "scheme": signing.SCHEME, "replayWindowSeconds": signing.REPLAY_WINDOW_SECONDS,
                "maxBodyBytes": signing.MAX_BODY_BYTES}

    # -- reads ---------------------------------------------------------------------------------------------------------
    def summary(self, workspace_id, token, start=None, end=None):
        require_enabled()
        now = self.clock()
        end = now if end is None else _epoch(end)
        start = end - 30 * 86400 if start is None else _epoch(start)
        if not start < end or end - start > 3700 * 86400:
            raise AlphaError("Choose a period of up to ten years that ends after it starts.", 400, code="invalid_request")
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            require(self._member(row), "read")
            coverage = _coverage(cur, workspace_id)
            classes = model.summarize(_grouped(cur, workspace_id, start, end))
            cur.execute("SELECT count(*) FROM public.pr_result_events WHERE workspace_id=%s AND kind='event' AND test AND occurred_at>=to_timestamp(%s) "
                        "AND occurred_at<to_timestamp(%s)", (workspace_id, start, end))
            tests = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM public.pr_result_quarantine WHERE workspace_id=%s", (workspace_id,))
            quarantined = int(cur.fetchone()[0])
            first_day = datetime.fromtimestamp(start, timezone.utc).date()
            last_day = datetime.fromtimestamp(end - 0.001, timezone.utc).date()   # clicks are per UTC day; the end is exclusive
            cur.execute("SELECT coalesce(sum(clicks),0),coalesce(sum(likely_bot),0) FROM public.pr_link_clicks WHERE workspace_id=%s AND day>=%s AND day<=%s",
                        (workspace_id, first_day, last_day))
            clicks, bots = cur.fetchone()
            cur.execute("SELECT count(*) FROM public.pr_tracking_links WHERE workspace_id=%s", (workspace_id,))
            links = int(cur.fetchone()[0])
        return {"definitionVersion": SUMMARY_DEFINITION, "definition": model.ASSOCIATION_DEFINITION, "asOf": now,
                "period": {"start": start, "end": end, "open": end >= now}, "dataState": summary_state(coverage, end, now),
                "classes": classes, "testEvents": tests, "quarantined": quarantined,
                "clicks": {"counted": int(clicks), "likelyBot": int(bots), "links": links, "unit": "clicks_not_people",
                           "days": {"start": first_day.isoformat(), "end": last_day.isoformat()}} if links else None,
                "coverage": {"connections": {k: coverage[k] for k in ("active", "paused", "removed", "errored")},
                             "lastReceivedAt": coverage["lastReceivedAt"], "declarations": coverage["declarations"],
                             "providerNative": "not_connected"}}

    def events(self, workspace_id, token, query=None):
        require_enabled()
        query = query or {}
        limit = page_limit(query.get("limit"))
        before = decode_cursor(query.get("cursor"))
        clauses, params = [], []
        provenance = query.get("provenance")
        if provenance:
            if provenance not in model.PROVENANCE:
                raise AlphaError("Unknown result source.", 400, code="invalid_request")
            clauses.append("e.provenance=%s")
            params.append(provenance)
        rtype = query.get("type")
        if rtype:
            if rtype not in model.RESULT_TYPES:
                raise AlphaError("Unknown result type.", 400, code="invalid_request")
            clauses.append("v.result_type=%s")
            params.append(rtype)
        attribution = query.get("attribution")
        if attribution:
            if attribution == "not_associated":
                clauses.append("v.attribution<>'associated'")
            elif attribution in model.ATTRIBUTION:
                clauses.append("v.attribution=%s")
                params.append(attribution)
            else:
                raise AlphaError("Unknown attribution.", 400, code="invalid_request")
        status = query.get("status")
        if status:
            if status not in ("active", "reversed"):
                raise AlphaError("Unknown status.", 400, code="invalid_request")
            clauses.append("r.id IS NULL" if status == "active" else "r.id IS NOT NULL")
        if before:
            clauses.append("(v.occurred_at,e.id)<(to_timestamp(%s),%s::uuid)")
            params.extend(before)
        where = "".join(" AND " + c for c in clauses)
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            require(member, "read")
            cur.execute(f"SELECT {_EVENT_COLUMNS} {_EVENT_JOINS} WHERE e.workspace_id=%s AND e.kind='event'{where} "
                        "ORDER BY v.occurred_at DESC,e.id DESC LIMIT %s", (workspace_id, *params, limit + 1))
            rows = cur.fetchall()
        items = [_event_view(r) for r in rows[:limit]]
        cursor = encode_cursor(items[-1]["occurredAt"], items[-1]["id"]) if len(rows) > limit else None
        return {"items": items, "nextCursor": cursor, "limit": limit, "asOf": self.clock(), "definition": model.ASSOCIATION_DEFINITION,
                "canEdit": member.allows("edit")}

    # -- declarations --------------------------------------------------------------------------------------------------
    def _declared_link(self, cur, workspace_id, link_id):
        if link_id is None:
            return None
        ident = _uuid(link_id)
        row = None
        if ident:
            cur.execute("SELECT id::text,campaign_ref FROM public.pr_tracking_links WHERE workspace_id=%s AND id=%s", (workspace_id, ident))
            row = cur.fetchone()
        if row is None:
            raise AlphaError("That link isn't in this workspace.", 404, code="result_link_unavailable")
        return {"id": row[0], "campaignRef": row[1]}

    def declare(self, workspace_id, token, payload):
        require_enabled()
        payload = _object(payload)
        key = idempotency_key(payload)
        digest = request_digest("result_declare", None, payload)
        now = self.clock()
        value = model.normalize_declaration(payload, now)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            replayed = self._replay(cur, workspace_id, key, "result_declare", digest)
            if replayed:
                return {"result": _read_event(cur, workspace_id, replayed), "replayed": True}
            link = self._declared_link(cur, workspace_id, value["linkId"])
            attribution = "associated" if link else "unattributed"
            ident = _insert_event(cur, workspace_id, provenance="user_declared", rtype=value["type"], provider_event_id="usr_" + uuid.uuid4().hex,
                                  occurred=value["occurredAt"], received=now, amount=value["amount"], quantity=value["quantity"],
                                  link_id=link["id"] if link else None, campaign=(link or {}).get("campaignRef") or value["campaignRef"],
                                  attribution=attribution, definition=DECLARED_LINK_DEFINITION if link else model.ASSOCIATION_DEFINITION,
                                  digest=signing.event_digest(value), declared_by=principal, note=value["note"])
            self._remember(cur, workspace_id, key, "result_declare", digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "result.declared", ident, {"type": value["type"], "provenance": "user_declared"})
            growth_events.emit(cur, workspace_id=workspace_id, event="result.ingested", entity_id=ident, revision=0, user_id=principal,
                               values={"provenance": "user_declared", "result_type": value["type"], "attribution": attribution})
            return {"result": _read_event(cur, workspace_id, ident), "replayed": False}

    def _correctable(self, cur, workspace_id, result_id, revision):
        root = _root(cur, workspace_id, result_id)
        view = _read_event(cur, workspace_id, root) if root else None
        if view is None:
            raise AlphaError("Result unavailable.", 404, code="result_unavailable")
        if view["provenance"] != "user_declared":
            raise AlphaError("Only results you reported can be changed here. A connected tool corrects its own events.", 409, code="result_not_editable")
        if view["status"] == "reversed":
            raise AlphaError("This result was already reversed.", 409, code="result_already_reversed")
        if view["revision"] != revision:
            raise AlphaError("This result changed since you opened it. Reload and try again.", 409, code="revision_conflict")
        return view

    def amend(self, workspace_id, token, result_id, payload):
        require_enabled()
        payload = _object(payload)
        key = idempotency_key(payload)
        digest = request_digest("result_amend", str(result_id), payload)
        revision = expected_revision(payload)
        now = self.clock()
        value = model.normalize_declaration({k: v for k, v in payload.items() if k not in ("idempotencyKey", "expectedRevision")}, now)
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            replayed = self._replay(cur, workspace_id, key, "result_amend", digest)
            if replayed:
                return {"result": _read_event(cur, workspace_id, _root(cur, workspace_id, replayed)), "replayed": True}
            current = self._correctable(cur, workspace_id, result_id, revision)
            link = self._declared_link(cur, workspace_id, value["linkId"])
            attribution = "associated" if link else "unattributed"
            ident = _insert_event(cur, workspace_id, provenance="user_declared", rtype=value["type"], provider_event_id="usr_" + uuid.uuid4().hex,
                                  kind="amendment", corrects_id=current["id"], occurred=value["occurredAt"], received=now, amount=value["amount"],
                                  quantity=value["quantity"], link_id=link["id"] if link else None,
                                  campaign=(link or {}).get("campaignRef") or value["campaignRef"], attribution=attribution,
                                  definition=DECLARED_LINK_DEFINITION if link else model.ASSOCIATION_DEFINITION,
                                  digest=signing.event_digest(value), declared_by=principal, note=value["note"])
            self._remember(cur, workspace_id, key, "result_amend", digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "result.amended", current["id"], {"type": value["type"], "revision": current["revision"] + 1})
            return {"result": _read_event(cur, workspace_id, current["id"]), "replayed": False}

    def reverse(self, workspace_id, token, result_id, payload):
        require_enabled()
        payload = _object(payload)
        key = idempotency_key(payload)
        digest = request_digest("result_reverse", str(result_id), payload)
        revision = expected_revision(payload)
        now = self.clock()
        note = " ".join(str(payload.get("note") or "").split())[:500] or None
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            replayed = self._replay(cur, workspace_id, key, "result_reverse", digest)
            if replayed:
                return {"result": _read_event(cur, workspace_id, _root_of_reversal(cur, workspace_id, replayed)), "replayed": True}
            current = self._correctable(cur, workspace_id, result_id, revision)
            ident = _insert_event(cur, workspace_id, provenance="user_declared", rtype=current["type"], provider_event_id="usr_" + uuid.uuid4().hex,
                                  kind="reversal", corrects_id=current["id"], occurred=now, received=now, quantity=current["quantity"],
                                  link_id=current["linkId"], campaign=current["campaignRef"], attribution=current["attribution"],
                                  definition=current["attributionDefinition"], digest=signing.event_digest({"reverses": current["id"], "note": note}),
                                  declared_by=principal, note=note)
            self._remember(cur, workspace_id, key, "result_reverse", digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "result.reversed", current["id"], {"type": current["type"], "provenance": "user_declared"})
            growth_events.emit(cur, workspace_id=workspace_id, event="result.reversed", entity_id=current["id"], revision=0, user_id=principal,
                               values={"provenance": "user_declared", "result_type": current["type"]})
            return {"result": _read_event(cur, workspace_id, current["id"]), "replayed": False}

    # -- connections (owner) -------------------------------------------------------------------------------------------
    _CONNECTION_COLUMNS = ("id::text,label,producer,status,secret_fingerprint,previous_fingerprint,extract(epoch from previous_expires_at),"
                           "rate_per_minute,rate_per_day,extract(epoch from last_received_at),extract(epoch from last_event_at),last_error_code,"
                           "extract(epoch from last_error_at),extract(epoch from created_at),extract(epoch from updated_at),"
                           "extract(epoch from removed_at),revision")

    def _connection_views(self, cur, workspace_id, rows, now, owner=True):
        ids = [r[0] for r in rows]
        counts, quarantine = {}, {}
        if ids:
            cur.execute("SELECT connection_id::text,count(*) FILTER (WHERE kind='event' AND NOT test),count(*) FILTER (WHERE kind='reversal' AND NOT test),"
                        "count(*) FILTER (WHERE test) FROM public.pr_result_events WHERE workspace_id=%s AND connection_id=ANY(%s::uuid[]) "
                        "AND received_at>=to_timestamp(%s) GROUP BY connection_id", (workspace_id, ids, now - 86400))
            counts = {r[0]: r[1:] for r in cur.fetchall()}
            cur.execute("SELECT connection_id::text,count(*),count(*) FILTER (WHERE received_at>=to_timestamp(%s)) FROM public.pr_result_quarantine "
                        "WHERE workspace_id=%s AND connection_id=ANY(%s::uuid[]) GROUP BY connection_id", (now - 86400, workspace_id, ids))
            quarantine = {r[0]: r[1:] for r in cur.fetchall()}
        views = []
        for (ident, label, producer, status, fingerprint, previous, previous_until, per_minute, per_day, received, event_at, error, error_at,
             created, updated, removed, revision) in rows:
            accepted, reversals, tests = counts.get(ident, (0, 0, 0))
            held, held_recent = quarantine.get(ident, (0, 0))
            grace = previous is not None and previous_until is not None and float(previous_until) > now
            health = connection_health(status, _num(received), _num(event_at), error, _num(error_at), now)
            health.update({"accepted24h": int(accepted), "reversals24h": int(reversals), "testEvents24h": int(tests),
                           "quarantined": int(held), "quarantined24h": int(held_recent)})
            views.append({"id": ident, "label": label, "producer": producer, "status": status, "revision": revision,
                          "fingerprint": fingerprint if status != "removed" else None,
                          "previousFingerprint": previous if grace else None, "previousExpiresAt": float(previous_until) if grace else None,
                          "ratePerMinute": per_minute, "ratePerDay": per_day, "createdAt": float(created), "updatedAt": float(updated),
                          "removedAt": _num(removed), "endpoint": self._endpoint(ident) if owner and status != "removed" else None, "health": health})
        return views

    def _connection(self, cur, workspace_id, connection_id, now):
        cur.execute(f"SELECT {self._CONNECTION_COLUMNS} FROM public.pr_result_connections WHERE workspace_id=%s AND id=%s", (workspace_id, connection_id))
        row = cur.fetchone()
        return self._connection_views(cur, workspace_id, [row], now)[0] if row else None

    def connections(self, workspace_id, token):
        require_enabled()
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            require(member, "read")
            cur.execute(f"SELECT {self._CONNECTION_COLUMNS} FROM public.pr_result_connections WHERE workspace_id=%s "
                        "ORDER BY (status='removed'),created_at DESC,id DESC LIMIT 50", (workspace_id,))
            views = self._connection_views(cur, workspace_id, cur.fetchall(), now, owner=member.allows("owner"))
        return {"connections": views, "canManage": member.allows("owner"), "limit": MAX_CONNECTIONS, "asOf": now,
                "rotationGraceSeconds": ROTATION_GRACE_SECONDS}

    def create_connection(self, workspace_id, token, payload):
        require_enabled()
        payload = _object(payload)
        key = idempotency_key(payload)
        digest = request_digest("result_connection_create", None, payload)
        label = _label(payload.get("label"))
        producer = payload.get("producer")
        if producer not in PRODUCERS:
            raise AlphaError("Choose what sends the results: a form, booking, newsletter, store or other tool you control.", 400, code="result_producer_invalid")
        per_minute, per_day = payload.get("ratePerMinute", 60), payload.get("ratePerDay", 5000)
        if type(per_minute) is not int or not 1 <= per_minute <= 600 or type(per_day) is not int or not 1 <= per_day <= 100_000:
            raise AlphaError("Rate limits are 1–600 per minute and 1–100,000 per day.", 400, code="result_rate_invalid")
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "owner")
            replayed = self._replay(cur, workspace_id, key, "result_connection_create", digest)
            if replayed:
                return {"connection": self._connection(cur, workspace_id, replayed, now), "secret": None, "secretShown": False, "replayed": True}
            cur.execute("SELECT count(*) FROM public.pr_result_connections WHERE workspace_id=%s AND status<>'removed'", (workspace_id,))
            if cur.fetchone()[0] >= MAX_CONNECTIONS:
                raise AlphaError(f"A workspace can have {MAX_CONNECTIONS} connections. Remove one you no longer use first.", 409, code="result_connection_limit")
            secret = signing.new_secret()
            ciphertext, key_id = self._encrypt(secret)
            cur.execute("INSERT INTO public.pr_result_connections(workspace_id,label,producer,secret_ciphertext,secret_key_id,secret_fingerprint,"
                        "rate_per_minute,rate_per_day,created_by,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) RETURNING id::text",
                        (workspace_id, label, producer, ciphertext, key_id, signing.secret_fingerprint(secret), per_minute, per_day, principal, _ms(now), _ms(now)))
            ident = cur.fetchone()[0]
            self._remember(cur, workspace_id, key, "result_connection_create", digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "result_connection.created", ident, {"producer": producer})
            return {"connection": self._connection(cur, workspace_id, ident, now), "secret": secret, "secretShown": True, "replayed": False}

    def connection_action(self, workspace_id, token, connection_id, action, payload):
        require_enabled()
        if action not in ("rotate", "pause", "resume", "remove"):
            raise AlphaError("Unknown connection action.", 404)
        payload = _object(payload)
        key = idempotency_key(payload)
        operation = f"result_connection_{action}"
        digest = request_digest(operation, str(connection_id), payload)
        revision = expected_revision(payload)
        ident = _uuid(connection_id)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "owner")
            replayed = self._replay(cur, workspace_id, key, operation, digest)
            if replayed:
                return {"connection": self._connection(cur, workspace_id, replayed, now), "secret": None, "secretShown": False, "replayed": True}
            found = None
            if ident:
                cur.execute("SELECT status,revision,secret_ciphertext,secret_key_id,secret_fingerprint FROM public.pr_result_connections "
                            "WHERE workspace_id=%s AND id=%s FOR UPDATE", (workspace_id, ident))
                found = cur.fetchone()
            if found is None:
                raise AlphaError("Connection unavailable.", 404, code="result_connection_unavailable")
            status, current_revision, ciphertext, key_id, fingerprint = found
            if status == "removed":
                raise AlphaError("This connection was removed. Create a new one instead.", 409, code="result_connection_removed")
            if current_revision != revision:
                raise AlphaError("This connection changed since you opened it. Reload and try again.", 409, code="revision_conflict")
            secret = None
            if action == "rotate":
                secret = signing.new_secret()
                new_ciphertext, new_key = self._encrypt(secret)
                cur.execute("UPDATE public.pr_result_connections SET previous_ciphertext=%s,previous_key_id=%s,previous_fingerprint=%s,"
                            "previous_expires_at=to_timestamp(%s),secret_ciphertext=%s,secret_key_id=%s,secret_fingerprint=%s,"
                            "updated_at=to_timestamp(%s),revision=revision+1 WHERE workspace_id=%s AND id=%s",
                            (ciphertext, key_id, fingerprint, _ms(now + ROTATION_GRACE_SECONDS), new_ciphertext, new_key,
                             signing.secret_fingerprint(secret), _ms(now), workspace_id, ident))
            elif action in ("pause", "resume"):
                if status != ("active" if action == "pause" else "paused"):
                    raise AlphaError(f"This connection is already {status}.", 409, code="result_connection_state")
                cur.execute("UPDATE public.pr_result_connections SET status=%s,updated_at=to_timestamp(%s),revision=revision+1 WHERE workspace_id=%s AND id=%s",
                            ("paused" if action == "pause" else "active", _ms(now), workspace_id, ident))
            else:
                cur.execute("UPDATE public.pr_result_connections SET status='removed',secret_ciphertext=NULL,secret_key_id=NULL,previous_ciphertext=NULL,"
                            "previous_key_id=NULL,previous_fingerprint=NULL,previous_expires_at=NULL,removed_at=to_timestamp(%s),"
                            "updated_at=to_timestamp(%s),revision=revision+1 WHERE workspace_id=%s AND id=%s", (_ms(now), _ms(now), workspace_id, ident))
            self._remember(cur, workspace_id, key, operation, digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, f"result_connection.{action}d" if action != "rotate" else "result_connection.rotated", ident, {})
            return {"connection": self._connection(cur, workspace_id, ident, now), "secret": secret, "secretShown": secret is not None, "replayed": False}

    # -- tracking links --------------------------------------------------------------------------------------------------
    _LINK_COLUMNS = ("id::text,slug,destination,campaign_ref,label,status,association_window_days,definition_version,extract(epoch from created_at),"
                     "extract(epoch from updated_at),extract(epoch from disabled_at),revision")

    def _link_views(self, cur, workspace_id, rows):
        ids = [r[0] for r in rows]
        clicks, results = {}, {}
        if ids:
            cur.execute("SELECT link_id::text,coalesce(sum(clicks),0),coalesce(sum(likely_bot),0),count(*) FROM public.pr_link_clicks "
                        "WHERE workspace_id=%s AND link_id=ANY(%s::uuid[]) GROUP BY link_id", (workspace_id, ids))
            clicks = {r[0]: r[1:] for r in cur.fetchall()}
            cur.execute(f"SELECT v.link_id::text,e.provenance,count(*) FROM public.pr_result_events e {_VERSION} {_REVERSAL} WHERE e.workspace_id=%s "
                        "AND e.kind='event' AND NOT e.test AND r.id IS NULL AND v.attribution='associated' AND v.link_id=ANY(%s::uuid[]) "
                        "GROUP BY 1,2", (workspace_id, ids))
            for link_id, provenance, count in cur.fetchall():
                results.setdefault(link_id, {})[provenance] = int(count)
        views = []
        for ident, slug, destination, campaign, label, status, window, definition, created, updated, disabled, revision in rows:
            counted, bots, days = clicks.get(ident, (0, 0, 0))
            path = LINK_PREFIX + slug
            views.append({"id": ident, "slug": slug, "path": path, "url": self.public_base_url + path if self.public_base_url else None,
                          "destination": destination, "campaignRef": campaign, "label": label, "status": status, "windowDays": window,
                          "definitionVersion": definition, "createdAt": float(created), "updatedAt": float(updated), "disabledAt": _num(disabled),
                          "revision": revision, "clicks": {"counted": int(counted), "likelyBot": int(bots), "days": int(days), "unit": "clicks_not_people"},
                          "associatedResults": results.get(ident, {})})
        return views

    def _link(self, cur, workspace_id, link_id):
        cur.execute(f"SELECT {self._LINK_COLUMNS} FROM public.pr_tracking_links WHERE workspace_id=%s AND id=%s", (workspace_id, link_id))
        row = cur.fetchone()
        return self._link_views(cur, workspace_id, [row])[0] if row else None

    def links(self, workspace_id, token, query=None):
        require_enabled()
        query = query or {}
        limit = page_limit(query.get("limit"))
        before = decode_cursor(query.get("cursor"))
        with self.repository.transaction(token, workspace_id) as (cur, row, _):
            member = self._member(row)
            require(member, "read")
            sql = f"SELECT {self._LINK_COLUMNS} FROM public.pr_tracking_links WHERE workspace_id=%s"
            params = [workspace_id]
            if before:
                sql += " AND (created_at,id)<(to_timestamp(%s),%s::uuid)"
                params.extend(before)
            cur.execute(sql + " ORDER BY created_at DESC,id DESC LIMIT %s", (*params, limit + 1))
            rows = cur.fetchall()
            items = self._link_views(cur, workspace_id, rows[:limit])
        cursor = encode_cursor(items[-1]["createdAt"], items[-1]["id"]) if len(rows) > limit else None
        return {"items": items, "nextCursor": cursor, "limit": limit, "canEdit": member.allows("edit"),
                "definition": model.ASSOCIATION_DEFINITION, "windowDays": model.ASSOCIATION_WINDOW_DAYS}

    def create_link(self, workspace_id, token, payload):
        require_enabled()
        payload = _object(payload)
        key = idempotency_key(payload)
        digest = request_digest("tracking_link_create", None, payload)
        destination = validate_destination(payload.get("destination"), self.resolver, own_origin=self.public_base_url or None)
        campaign = _campaign(payload.get("campaignRef"))
        label = _label(payload.get("label"), fallback=(urlsplit(destination).hostname or "")[:80])
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            replayed = self._replay(cur, workspace_id, key, "tracking_link_create", digest)
            if replayed:
                return {"link": self._link(cur, workspace_id, replayed), "replayed": True}
            cur.execute("SELECT count(*) FROM public.pr_tracking_links WHERE workspace_id=%s AND status='active'", (workspace_id,))
            if cur.fetchone()[0] >= MAX_ACTIVE_LINKS:
                raise AlphaError(f"A workspace can have {MAX_ACTIVE_LINKS} active links. Turn off one you no longer share first.", 409, code="result_link_limit")
            ident = None
            for _ in range(4):   # 144 random bits; a collision is practically impossible, but never an error
                cur.execute("INSERT INTO public.pr_tracking_links(workspace_id,slug,destination,campaign_ref,label,association_window_days,definition_version,"
                            "created_by,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s)) ON CONFLICT (slug) DO NOTHING RETURNING id::text",
                            (workspace_id, secrets.token_urlsafe(18), destination, campaign, label, model.ASSOCIATION_WINDOW_DAYS,
                             model.ASSOCIATION_DEFINITION, principal, _ms(now), _ms(now)))
                found = cur.fetchone()
                if found:
                    ident = found[0]
                    break
            if ident is None:
                raise AlphaError("The link couldn't be created. Try again.", 503, code="retry_later")
            self._remember(cur, workspace_id, key, "tracking_link_create", digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, "tracking_link.created", ident, {})
            return {"link": self._link(cur, workspace_id, ident), "replayed": False}

    def link_action(self, workspace_id, token, link_id, action, payload):
        require_enabled()
        if action not in ("disable", "enable"):
            raise AlphaError("Unknown link action.", 404)
        payload = _object(payload)
        key = idempotency_key(payload)
        operation = f"tracking_link_{action}"
        digest = request_digest(operation, str(link_id), payload)
        revision = expected_revision(payload)
        ident = _uuid(link_id)
        now = self.clock()
        with self.repository.transaction(token, workspace_id) as (cur, row, principal):
            require(self._member(row), "edit")
            replayed = self._replay(cur, workspace_id, key, operation, digest)
            if replayed:
                return {"link": self._link(cur, workspace_id, replayed), "replayed": True}
            found = None
            if ident:
                cur.execute("SELECT status,revision FROM public.pr_tracking_links WHERE workspace_id=%s AND id=%s FOR UPDATE", (workspace_id, ident))
                found = cur.fetchone()
            if found is None:
                raise AlphaError("Link unavailable.", 404, code="result_link_unavailable")
            if found[1] != revision:
                raise AlphaError("This link changed since you opened it. Reload and try again.", 409, code="revision_conflict")
            target = "disabled" if action == "disable" else "active"
            if found[0] == target:
                raise AlphaError(f"This link is already {'off' if target == 'disabled' else 'on'}.", 409, code="result_link_state")
            if target == "active":
                cur.execute("SELECT count(*) FROM public.pr_tracking_links WHERE workspace_id=%s AND status='active'", (workspace_id,))
                if cur.fetchone()[0] >= MAX_ACTIVE_LINKS:
                    raise AlphaError(f"A workspace can have {MAX_ACTIVE_LINKS} active links.", 409, code="result_link_limit")
            cur.execute("UPDATE public.pr_tracking_links SET status=%s,disabled_at=CASE WHEN %s='disabled' THEN to_timestamp(%s) END,"
                        "updated_at=to_timestamp(%s),revision=revision+1 WHERE workspace_id=%s AND id=%s",
                        (target, target, _ms(now), _ms(now), workspace_id, ident))
            self._remember(cur, workspace_id, key, operation, digest, ident)
            from ..hosted import audit
            audit(cur, workspace_id, principal, f"tracking_link.{action}d", ident, {})
            return {"link": self._link(cur, workspace_id, ident), "replayed": False}

    # -- public: the tracking redirect -----------------------------------------------------------------------------------
    def redirect(self, slug, method, user_agent=None, purpose=None):
        """The 302 location for an active link (counting the click), or None (unknown, disabled, flag off)."""
        if not enabled() or not isinstance(slug, str) or not _SLUG.match(slug):
            return None
        now = self.clock()
        bot = likely_bot(user_agent, method, purpose)
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT id::text,workspace_id::text,destination FROM public.pr_tracking_links WHERE slug=%s AND status='active'", (slug,))
                row = cur.fetchone()
                if row is None:
                    return None
                link_id, workspace_id, destination = row
                if not bot and not _budget(cur, f"results:link-burst:{link_id}", LINK_BURST_PER_MINUTE, 60):
                    bot = True
                cur.execute("INSERT INTO public.pr_link_clicks(workspace_id,link_id,day,clicks,likely_bot) VALUES(%s,%s,%s,%s,%s) ON CONFLICT (link_id,day) "
                            "DO UPDATE SET clicks=public.pr_link_clicks.clicks+excluded.clicks,likely_bot=public.pr_link_clicks.likely_bot+excluded.likely_bot",
                            (workspace_id, link_id, datetime.fromtimestamp(now, timezone.utc).date(), 0 if bot else 1, 1 if bot else 0))
        return redirect_location(destination, model.make_ref(slug, now))

    # -- public: the signed first-party receiver -------------------------------------------------------------------------
    def ingest(self, connection_id, header, raw, now=None):
        """One webhook delivery → Delivery. Never raises for an expected refusal, so the connection's health code and
        rate counters are committed together with the answer. The body, secret and any contact detail are never logged."""
        now = self.clock() if now is None else now
        if not enabled():
            return Delivery(404, {"error": "Not found.", "code": "feature_disabled"})
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return Delivery(400, {"error": "The body must be one JSON object.", "code": "result_payload_invalid"})
        if len(raw) > signing.MAX_BODY_BYTES:
            return Delivery(413, {"error": f"The event must be at most {signing.MAX_BODY_BYTES} bytes.", "code": "result_body_too_large"})
        ident = _uuid(connection_id)
        if ident is None:
            return Delivery(404, {"error": "Not found.", "code": "not_found"})
        with self.connection_factory() as db:
            with db.cursor() as cur:
                cur.execute("SELECT workspace_id::text,status,secret_ciphertext,secret_key_id,previous_ciphertext,previous_key_id,"
                            "extract(epoch from previous_expires_at),rate_per_minute,rate_per_day FROM public.pr_result_connections WHERE id=%s FOR UPDATE",
                            (ident,))
                row = cur.fetchone()
                if row is None or row[1] != "active":
                    return Delivery(404, {"error": "Not found.", "code": "not_found"})
                outcome = self._deliver(cur, ident, row, header, bytes(raw), now)
                if outcome.error:
                    cur.execute("UPDATE public.pr_result_connections SET last_error_code=%s,last_error_at=to_timestamp(%s) WHERE id=%s",
                                (outcome.error[:60], _ms(now), ident))
        return outcome

    def _deliver(self, cur, connection_id, row, header, raw, now):
        workspace_id, _status, current, current_key, previous, previous_key, previous_until, per_minute, per_day = row
        # 1. Rate budget for every attempt, before any signature work (floods of unauthenticated deliveries).
        if not _budget(cur, f"results:deliveries:{connection_id}", per_minute * DELIVERY_BUDGET_FACTOR, 60):
            return _refused(429, "result_rate_limited", "Too many deliveries for this connection. Retry in a minute.", "rate_limited", [("Retry-After", "60")])
        # 2. Signature over the exact bytes, against the current secret and the previous one inside its grace period.
        accepted = [self._decrypt(current, current_key)]
        if previous and previous_until is not None and float(previous_until) > now:
            accepted.append(self._decrypt(previous, previous_key))
        accepted = [s for s in accepted if s]
        if not accepted:
            return _refused(503, "results_unavailable", "This connection can't verify deliveries right now.", "secret_unavailable")
        try:
            signing.verify(header, raw, accepted, now)
        except signing.SignatureError as error:
            stale = error.code == "timestamp_outside_window"
            return _refused(401, "result_timestamp_stale" if stale else "result_signature_invalid",
                            "The signature timestamp is outside the five-minute window." if stale else "The signature is missing, malformed or doesn't match.",
                            error.code)
        # 3. Verified events have their own per-minute and per-day budget.
        if not _budget(cur, f"results:events:{connection_id}:m", per_minute, 60):
            return _refused(429, "result_rate_limited", "This connection's per-minute budget is used up. Retry in a minute.", "rate_limited", [("Retry-After", "60")])
        if not _budget(cur, f"results:events:{connection_id}:d", per_day, 86400):
            return _refused(429, "result_rate_limited", "This connection's daily budget is used up.", "daily_budget_exhausted", [("Retry-After", "3600")])
        # 4. Parse and normalize; unknown fields are dropped, never stored.
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _refused(400, "result_payload_invalid", "The body must be one JSON object.", "payload_invalid")
        try:
            event = model.normalize_first_party(payload, now)
        except AlphaError as error:
            return _refused(400, error.code or "result_payload_invalid", str(error), error.code or "payload_invalid")
        digest = signing.event_digest(event)
        # 5. Idempotent identity per (workspace, connection, eventId).
        cur.execute("SELECT id::text,payload_digest,attribution FROM public.pr_result_events WHERE workspace_id=%s AND connection_id=%s "
                    "AND provider_event_id=%s AND provenance='first_party_reported'", (workspace_id, connection_id, event["eventId"]))
        existing = cur.fetchone()
        if existing:
            if existing[1] == digest:
                return Delivery(200, {"receiptId": existing[0], "status": "duplicate", "attribution": existing[2]})
            held = self._quarantine(cur, workspace_id, connection_id, event["eventId"], digest, "conflicting_payload", existing[0])
            return _refused(409, "result_conflict", "This eventId was already received with different content. The new version was quarantined, not applied.",
                            "conflicting_payload", receiptId=held, status="quarantined")
        if event["reversalOf"]:
            return self._reverse_reported(cur, workspace_id, connection_id, event, digest, now)
        link, window = {}, model.ASSOCIATION_WINDOW_DAYS
        parsed = model.parse_ref(event["ref"]) if event["ref"] not in (None, "invalid") else None
        if parsed:
            cur.execute("SELECT id::text,campaign_ref,association_window_days FROM public.pr_tracking_links WHERE workspace_id=%s AND slug=%s",
                        (workspace_id, parsed[0]))
            found = cur.fetchone()
            if found:
                link, window = {parsed[0]: {"id": found[0], "campaignRef": found[1]}}, found[2]
        association = model.associate(event["ref"], event["occurredAt"], link, window_days=window)
        campaign = association.get("campaignRef") if association["attribution"] == "associated" and association.get("campaignRef") else event["campaignRef"]
        ident = _insert_event(cur, workspace_id, provenance="first_party_reported", rtype=event["type"], connection_id=connection_id,
                              provider_event_id=event["eventId"], occurred=event["occurredAt"], received=now, amount=event["amount"],
                              link_id=association["linkId"], campaign=campaign, attribution=association["attribution"],
                              definition=association["definition"], digest=digest, test=event["test"])
        self._received(cur, connection_id, event["occurredAt"], now)
        if not event["test"]:
            growth_events.emit(cur, workspace_id=workspace_id, event="result.ingested", entity_id=ident, revision=0, user_id=None,
                               values={"provenance": "first_party_reported", "result_type": event["type"], "attribution": association["attribution"]})
        return Delivery(200, {"receiptId": ident, "status": "accepted", "attribution": association["attribution"]})

    def _reverse_reported(self, cur, workspace_id, connection_id, event, digest, now):
        cur.execute("SELECT id::text,kind,result_type,quantity,link_id::text,campaign_ref,attribution,attribution_definition,"
                    "EXISTS(SELECT 1 FROM public.pr_result_events r WHERE r.workspace_id=e.workspace_id AND r.corrects_id=e.id AND r.kind='reversal') "
                    "FROM public.pr_result_events e WHERE workspace_id=%s AND connection_id=%s AND provider_event_id=%s AND provenance='first_party_reported'",
                    (workspace_id, connection_id, event["reversalOf"]))
        original = cur.fetchone()
        if original is None:
            return _refused(409, "result_reversal_unknown", "reversalOf names an event this connection hasn't reported. Send the original first.")
        ident, kind, rtype, quantity, link_id, campaign, attribution, definition, already = original
        if kind != "event" or rtype != event["type"]:
            return _refused(409, "result_reversal_invalid", "A reversal must name an original event of the same type.")
        if already:
            held = self._quarantine(cur, workspace_id, connection_id, event["eventId"], digest, "reversal_duplicate", ident)
            return _refused(409, "result_already_reversed", "That event was already reversed. This delivery was quarantined.", "reversal_duplicate",
                            receiptId=held, status="quarantined")
        reversal = _insert_event(cur, workspace_id, provenance="first_party_reported", rtype=rtype, connection_id=connection_id,
                                 provider_event_id=event["eventId"], kind="reversal", corrects_id=ident, occurred=event["occurredAt"], received=now,
                                 amount=event["amount"], quantity=quantity, link_id=link_id, campaign=campaign, attribution=attribution,
                                 definition=definition, digest=digest, test=event["test"])
        self._received(cur, connection_id, event["occurredAt"], now)
        if not event["test"]:
            growth_events.emit(cur, workspace_id=workspace_id, event="result.reversed", entity_id=ident, revision=0, user_id=None,
                               values={"provenance": "first_party_reported", "result_type": rtype})
        return Delivery(200, {"receiptId": reversal, "status": "accepted", "attribution": attribution})

    @staticmethod
    def _quarantine(cur, workspace_id, connection_id, event_id, digest, reason, existing_id):
        cur.execute("INSERT INTO public.pr_result_quarantine(workspace_id,connection_id,provider_event_id,payload_digest,reason,existing_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT (workspace_id,connection_id,provider_event_id,payload_digest) DO NOTHING RETURNING id::text",
                    (workspace_id, connection_id, event_id, digest, reason, existing_id))
        found = cur.fetchone()
        if found:
            return found[0]
        cur.execute("SELECT id::text FROM public.pr_result_quarantine WHERE workspace_id=%s AND connection_id=%s AND provider_event_id=%s AND payload_digest=%s",
                    (workspace_id, connection_id, event_id, digest))
        return cur.fetchone()[0]

    @staticmethod
    def _received(cur, connection_id, occurred, now):
        cur.execute("UPDATE public.pr_result_connections SET last_received_at=to_timestamp(%s),last_event_at=to_timestamp(%s) WHERE id=%s",
                    (_ms(now), _ms(occurred), connection_id))


def _root_of_reversal(cur, workspace_id, reversal_id):
    cur.execute("SELECT corrects_id::text FROM public.pr_result_events WHERE workspace_id=%s AND id=%s", (workspace_id, reversal_id))
    row = cur.fetchone()
    return row[0] if row else None
