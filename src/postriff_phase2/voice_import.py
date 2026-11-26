"""Voice import: the person's own posts, kept as text evidence for voice analysis (spec IMP-1 … IMP-7; migration 140).

Two routes fill one store:
- official_api. Someone who manages connections asks once per account (`request`: interactive session, consent with
  `confirmed: true`). The cron step (`tick`) then pages through the account's own posts with the server-side token.
  Each page's posts, counters and cursor are written in one transaction fenced on the run's lease; no HTTP runs inside
  a transaction; a run interrupted anywhere resumes from its stored cursor.
- platform_export. The browser parses the export file and sends normalised records in batches (`items`); the file
  itself never reaches the server.

Both go through the same batch rules (`prepare`, `plan_batch`): one row per post of one account whatever route supplied
it (`routes` lists every one), a changed text is a new revision, the same text elsewhere points at its earliest copy,
a repost is recorded without the other author's words, a post Rafii itself published is marked from the publish
journal, and the person's own corrections survive a re-read. Nothing here calls a model.

A run's counters describe exactly what it listed:
  discovered   every item the provider page or the export batch listed (plus what the browser said it skipped)
  unsupported  items with no usable text (media without a caption, records the browser could not read)
  failed       items refused as invalid (no id, text over 20,000 characters, wrong types)
  retrieved    items stored as a post row (new, or an existing row seen again); discovered = retrieved + unsupported + failed
  duplicates   of the retrieved: already held through another route, listed twice by this run, or the same text as an earlier post
  excluded     of the retrieved and not duplicates: reposts, posts Rafii published, text too short to carry a voice
  removed      posts a complete newest-to-oldest pass no longer found at the provider, deleted here (row and text)

Lock order everywhere in this module: the workspace row, then the run row, then post rows. `oauth.disconnect` holds the
workspace row and purges inside its own transaction (`purge_connection`), so the page store takes the workspace row
first and can never deadlock with it.

Off unless POSTRIFF_VOICE_IMPORT is "1". Official reads are further limited to the providers named in
POSTRIFF_VOICE_IMPORT_PROVIDERS (none by default: uploads only), and optionally to the workspaces listed in
POSTRIFF_VOICE_IMPORT_WORKSPACES. Removal never waits for the flag: a disconnect's purge and the cron's sweep of
disconnected accounts (`purge_connection`, `sweep_revoked`) run whatever it says, as the history import's purge does.
Every statement is guarded by `to_regclass`, so the code is inert before the migration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from postriff_alpha.domain import AlphaError

from . import leases
from . import voice_evidence as evidence
from . import voice_import_readers as readers

FLAG = "POSTRIFF_VOICE_IMPORT"
PROVIDERS_FLAG = "POSTRIFF_VOICE_IMPORT_PROVIDERS"
WORKSPACES_FLAG = "POSTRIFF_VOICE_IMPORT_WORKSPACES"
CONSENT_VERSION = "voice-import.v1"
REQUESTS_PER_HOUR = 5          # provider reads asked for (requests and refreshes), per workspace
UPLOADS_PER_HOUR = 30          # export uploads started, per workspace: one sitting covers every platform's export
LEASE_SECONDS = 120
PAGES_PER_TICK = 3
RUNS_PER_TICK = 2
MAX_ATTEMPTS = 5
MAX_ITEMS = 200
MAX_BATCH_BYTES = 512 * 1024
MAX_BODY = 20_000
MAX_PAGES = 2000               # a runaway guard, not a product cap: the provider's own limit applies
UPLOAD_IDLE_SECONDS = 1800     # an upload nobody continued stops holding its account
POSTS_PAGE = 50
EXCERPT_CHARS = 280
TERMINAL_HTTP = (400, 401, 403, 404)
REPOST_BODY = "[repost]"       # a repost row keeps no words; this placeholder satisfies the non-empty body column
ROUTES = ("official_api", "platform_export")
PLATFORMS = (
    # provider, platform, the scope an official read needs (None: none), export files the browser can parse
    ("threads", "Threads", "threads_basic", ("your_instagram_activity/threads/threads_and_replies.json",)),
    ("instagram", "Instagram", "instagram_business_basic",
     ("your_instagram_activity/media/posts_1.json", "your_instagram_activity/content/posts_1.json", "content/posts_1.json")),
    ("bluesky", "Bluesky", None, ()),
    ("mastodon", "Mastodon", None, ("outbox.json",)),
    ("linkedin", "LinkedIn", "r_member_social", ("Shares.csv",)),
    ("facebook", "Facebook", None, ("your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json", "posts/your_posts_1.json")),
    ("x", "X", None, ("data/tweets.js", "data/note-tweet.js")),
)
_PLATFORM = {row[0]: row for row in PLATFORMS}
# The hosts an export's post links may point at. A link elsewhere is not kept; Mastodon instances are anywhere (https only).
EXPORT_HOSTS = {
    "x": ("x.com", "twitter.com", "mobile.twitter.com"),
    "instagram": ("instagram.com", "www.instagram.com"),
    "facebook": ("facebook.com", "www.facebook.com", "m.facebook.com"),
    "threads": ("threads.net", "www.threads.net", "threads.com", "www.threads.com"),
    "linkedin": ("linkedin.com", "www.linkedin.com"),
    "bluesky": ("bsky.app",),
    "mastodon": None,
}
_NO_CONNECTOR = {
    "facebook": ("scope_not_requested", "Reading a Page's posts needs a Facebook permission Rafii does not ask for. Upload the Page's data export instead."),
    "x": ("billed_reads", "X charges for every post read through its API, so Rafii reads X posts only from your archive. Upload your X archive instead."),
}
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FAR = datetime.max.replace(tzinfo=timezone.utc)
logger = logging.getLogger("postriff.voice_import")
logger.setLevel(logging.INFO)

_RUN_COLUMNS = ("id::text, workspace_id::text, route, provider, connection_id, account_key, account_label, status, consent, requested_since, "
                "observed_oldest, observed_newest, discovered, retrieved, duplicates, excluded, unsupported, failed_items, removed, pages, "
                "more_remaining, total_known, cursor, watermark, attempts, lease_owner, retry_at, failure_class, created_at, updated_at, last_sync_at")
_RUN_KEYS = ("id", "workspaceId", "route", "provider", "connectionId", "accountKey", "accountLabel", "status", "consent", "requestedSince",
             "observedOldest", "observedNewest", "discovered", "retrieved", "duplicates", "excluded", "unsupported", "failedItems", "removed", "pages",
             "moreRemaining", "totalKnown", "cursor", "watermark", "attempts", "leaseOwner", "retryAt", "failure", "createdAt", "updatedAt", "lastSyncAt")
_POST_KEYS = ("id", "provider", "account_key", "provider_post_id", "import_id", "routes", "connection_id", "permalink", "published_at", "body",
              "body_hash", "norm_hash", "language", "content_type", "originality", "authorship", "generation_origin", "label", "voice_scope",
              "duplicate_of", "status", "exclusion_reason", "revision", "first_seen_at")
_POST_COLUMNS = ("id::text, provider, account_key, provider_post_id, import_id::text, routes, connection_id, permalink, published_at, body, "
                 "body_hash, norm_hash, language, content_type, originality, authorship, generation_origin, label, voice_scope, "
                 "duplicate_of::text, status, exclusion_reason, revision, first_seen_at")
_POST_VIEW = (f"id::text, provider, account_key, published_at, permalink, left(body, {EXCERPT_CHARS}), language, originality, authorship, "
              "generation_origin, label, status, exclusion_reason")


# --- flags ------------------------------------------------------------------------------------------------------------
def enabled(values):
    return (values or {}).get(FLAG) == "1"


def allowed_providers(values):
    """The providers whose official API may be read, named one by one. Unset means none: uploads only."""
    raw = (values or {}).get(PROVIDERS_FLAG, "")
    names = re.split(r"[\s,]+", raw.lower()) if isinstance(raw, str) else []
    return frozenset(name for name in names if name in readers.SUPPORTED)


def allowed_workspaces(values):
    """None when no list is set (every workspace). A list admits exactly its UUIDs; a malformed list admits nobody."""
    raw = (values or {}).get(WORKSPACES_FLAG, "")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return frozenset(str(uuid.UUID(value.strip())) for value in raw.split(","))
    except (ValueError, AttributeError):
        return frozenset()


def mount(service, database, values, *, transport):
    """Attach the importer when the flag is on; otherwise touch nothing. `oauth.voice_import` lets a disconnect remove
    what was read through the connection."""
    if not enabled(values):
        return None
    importer = VoiceImporter(database, service.oauth, transport=transport, values=values)
    service.voice_import = importer
    service.oauth.voice_import = importer
    return importer


# --- small helpers ----------------------------------------------------------------------------------------------------
def _note(event, error=None, **fields):
    # Ids, counts and classes only: exception text can carry tokens, post text or provider payloads.
    logger.warning(json.dumps({"event": event, **({"exceptionType": type(error).__name__} if error else {}), **fields}))


def _guarded(cur, operation, event):
    """Run `operation` in its own savepoint; roll only it back on failure. Returns its result or None; never raises."""
    mark = "voice_import_" + uuid.uuid4().hex[:8]
    try:
        cur.execute(f"SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001 - the transaction is already unusable; its owner decides
        _note(event, error)
        return None
    try:
        result = operation()
    except Exception as error:  # noqa: BLE001 - a purge must never fail the disconnect that asked for it
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
            cur.execute(f"RELEASE SAVEPOINT {mark}")
        except Exception:  # noqa: BLE001
            pass
        _note(event, error)
        return None
    try:
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception as error:  # noqa: BLE001
        _note(event, error)
        return None
    return result


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) and value.tzinfo else None


def _moment(value):
    """An aware UTC datetime from an ISO 8601 string with an offset, or from epoch seconds; None for anything else."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 4_102_444_800:
        return datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, str) or not value or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _state(row):
    state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    return state if isinstance(state, dict) else {}


def _plain(value, limit, message):
    if not isinstance(value, str) or len(value.strip()) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in value.strip()):
        raise AlphaError(message, 400)
    return value.strip()


def _channel_label(state, connection_id):
    for channel in ((state.get("phase2") or {}).get("channels") or []) if isinstance(state.get("phase2"), dict) else []:
        if isinstance(channel, dict) and channel.get("id") == connection_id and isinstance(channel.get("account"), str):
            return channel["account"][:120] or None
    return None


# --- request and batch shapes (validated before any database work) -------------------------------------------------------
def parse_request(payload):
    """`POST /voice-imports` body → {route, provider, connectionId, accountKey, accountLabel, consent, since}."""
    if not isinstance(payload, dict):
        raise AlphaError("Expected an import request.", 400)
    consent = payload.get("consent")
    if not isinstance(consent, dict) or consent.get("confirmed") is not True:
        raise AlphaError("Confirm whose writing this is and that Rafii may keep the text of these posts.", 400, code="consent_required")
    if consent.get("ownership") not in evidence.AUTHORSHIP:
        raise AlphaError("Say whose writing this is: yours, your organisation's, or several authors'.", 400)
    if consent.get("voiceScope") not in ("brand", "separate"):
        raise AlphaError("Choose whether this account is part of the brand voice or kept separate.", 400)
    route, provider = payload.get("route"), payload.get("provider")
    if route not in ROUTES:
        raise AlphaError("Choose a connected account or an export upload.", 400)
    if not isinstance(provider, str) or provider not in _PLATFORM:
        raise AlphaError("Choose a supported platform.", 400)
    since = payload.get("since")
    if since is not None:
        since = _moment(since + "T00:00:00+00:00" if isinstance(since, str) and _DATE.fullmatch(since) else since) if isinstance(since, str) else None
        if since is None:
            raise AlphaError("Give the starting date as a date, or a time with its offset.", 400)
    wanted = {"route": route, "provider": provider, "connectionId": None, "accountKey": None, "accountLabel": None,
              "consent": {"ownership": consent["ownership"], "voiceScope": consent["voiceScope"]}, "since": since}
    if route == "official_api":
        connection = payload.get("connectionId")
        if not isinstance(connection, str) or not 1 <= len(connection) <= 200:
            raise AlphaError("Choose the connected account to read.", 400)
        wanted["connectionId"] = connection          # the account key and name come from the connection, never from the client
        return wanted
    key, label = payload.get("accountKey"), payload.get("accountLabel")
    key = "export" if key is None else _plain(key, 200, "Name the account with up to 200 plain characters.")
    if not key:
        raise AlphaError("Name the account with up to 200 plain characters.", 400)
    label = _plain(label, 120, "Keep the account name under 120 characters.") if label is not None else ""
    wanted.update(accountKey=key, accountLabel=label or f"{_PLATFORM[provider][1]} export")
    return wanted


def parse_batch(payload):
    """`POST /voice-imports/{id}/items` body → {items, skipped {unsupported, empty}, final, seq}. Structure only: each
    record is judged on its own later, so one bad record never refuses the batch."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise AlphaError("Send the parsed posts as a list of records.", 400)
    if len(payload["items"]) > MAX_ITEMS:
        raise AlphaError(f"Send at most {MAX_ITEMS} posts in one batch.", 400)
    skipped = payload.get("skipped", {})
    if (not isinstance(skipped, dict) or set(skipped) - {"unsupported", "empty"}
            or any(type(count) is not int or not 0 <= count <= 1_000_000 for count in skipped.values())):
        raise AlphaError("Report skipped records as whole numbers of unsupported and empty items.", 400)
    final, seq = payload.get("final", False), payload.get("seq")
    if type(final) is not bool or (seq is not None and (type(seq) is not int or seq < 1)):
        raise AlphaError("Mark the last batch with final: true and number batches from 1.", 400)
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_BATCH_BYTES:
        raise AlphaError("This batch is larger than 512 kB. Send fewer posts at a time.", 413, code="voice_import_batch_too_large")
    return {"items": payload["items"], "skipped": {"unsupported": skipped.get("unsupported", 0), "empty": skipped.get("empty", 0)},
            "final": final, "seq": seq}


def _correction(payload):
    if not isinstance(payload, dict) or not payload or set(payload) - {"authorship", "label", "excluded"}:
        raise AlphaError("Say who wrote the post, how it should be read, or whether to leave it out.", 400)
    if "authorship" in payload and payload["authorship"] not in ("self", "team", "guest", "unknown"):
        raise AlphaError("Choose who wrote this post: you, your team, someone else, or not known.", 400)
    if "label" in payload and payload["label"] not in ("representative", "outdated", "aspirational", None):
        raise AlphaError("Choose representative, outdated or aspirational, or clear the label.", 400)
    if "excluded" in payload and type(payload["excluded"]) is not bool:
        raise AlphaError("Say whether to leave this post out with true or false.", 400)
    return payload


# --- batch rules (pure) -------------------------------------------------------------------------------------------------
def _clean(raw):
    """One incoming record → a normalised post, "unsupported" (no words to keep) or None (invalid)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("externalId"), str):
        return None
    post_id = raw["externalId"].strip()
    if not 1 <= len(post_id) <= 300 or any(ord(ch) < 32 for ch in post_id):
        return None
    kind = raw.get("kind") if isinstance(raw.get("kind"), str) and raw["kind"] in readers.KINDS else None
    text = raw.get("text")
    if kind == "repost" or text is None:
        text = ""                                    # a repost's words belong to someone else: never kept, never classified
    elif not isinstance(text, str):
        return None
    else:
        text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) > MAX_BODY:
            return None
    if not text and kind != "repost":
        return "unsupported"
    return {"externalId": post_id, "text": text, "kind": kind, "published_at": _moment(raw.get("publishedAt")),
            "permalink": readers._https(raw.get("permalink")), "contentType": raw.get("contentType")}


def export_link(provider, link):
    """An export record's https link, kept only when its host is the platform's own (EXPORT_HOSTS); else None. The
    browser sent it, so a link to any other site is not stored."""
    if link is None or provider not in EXPORT_HOSTS:
        return None
    hosts = EXPORT_HOSTS[provider]
    return link if hosts is None or (urlsplit(link).hostname or "").lower() in hosts else None


def prepare(items, *, run, journal):
    """Validate and classify one page or batch: {posts, unsupported, failed}. `run` carries provider, accountKey,
    connectionId, route and consent; `journal` is `voice_evidence.journal(state)`."""
    posts, unsupported, failed = [], 0, 0
    for raw in items:
        post = _clean(raw)
        if post is None:
            failed += 1
            continue
        if post == "unsupported":
            unsupported += 1
            continue
        if run.get("route") == "platform_export":
            post["permalink"] = export_link(run["provider"], post["permalink"])
        facts = evidence.classify({"externalId": post["externalId"], "text": post["text"], "kind": post["kind"], "contentType": post["contentType"],
                                   "connectionId": run.get("connectionId"), "provider": run["provider"]}, consent=run["consent"], journal=journal)
        body = post["text"]
        if post["kind"] == "repost":
            body = REPOST_BODY
            marker = f"repost\x1f{run['provider']}\x1f{run['accountKey']}\x1f{post['externalId']}"
            facts.update(language="und", generation_origin="unknown", body_hash=evidence.body_hash(REPOST_BODY),
                         norm_hash=hashlib.sha256(marker.encode("utf-8")).hexdigest())    # unique: reposts are never grouped
        posts.append({**post, "body": body, **facts})
    return {"posts": posts, "unsupported": unsupported, "failed": failed}


def sibling_hashes(posts, by_key):
    """The text groups a batch can change: those of the incoming posts and of the rows they replace."""
    return {post["norm_hash"] for post in posts} | {row["norm_hash"] for row in by_key.values()}


def _manual(row):
    return row["status"] == "excluded" and row["exclusion_reason"] == "manual"


def _status(row, manual):
    return evidence.resolve_status(originality=row["originality"], generation_origin=row["generation_origin"], authorship=row["authorship"],
                                   label=row["label"], manual=manual, too_short=evidence.too_short(row["body"]),
                                   duplicate=row["duplicate_of"] is not None)


def _order(row):
    return (row["published_at"] is None, row["published_at"] or _FAR, row["first_seen_at"], row["id"])


def _settle(rows, manual):
    """Point every copy of a text at its earliest copy, within one voice group, then give each row its status.
    Reposts and texts too short to identify a post are never grouped. `rows` must hold every row of each group."""
    groups = {}
    for row in rows:
        row["duplicate_of"] = None
        if row["originality"] != "repost" and not evidence.too_short(row["body"]):
            groups.setdefault((evidence.group_key(row["voice_scope"], row["provider"], row["account_key"]), row["norm_hash"]), []).append(row)
    for members in groups.values():
        first = min(members, key=_order)
        for row in members:
            row["duplicate_of"] = None if row is first else first["id"]
    for row in rows:
        row["status"], row["exclusion_reason"] = _status(row, manual[row["id"]])


def regroup(rows):
    """After posts were removed: settle the given rows (every row of each affected text) and return the ones whose
    `duplicate_of`, `status` or `exclusion_reason` changed. The rows are updated in place."""
    rows = list(rows)
    before = {row["id"]: (row["duplicate_of"], row["status"], row["exclusion_reason"]) for row in rows}
    _settle(rows, {row["id"]: _manual(row) for row in rows})
    return [row for row in rows if (row["duplicate_of"], row["status"], row["exclusion_reason"]) != before[row["id"]]]


def plan_batch(posts, by_key, siblings, *, run, now):
    """What one page or batch does to the store. `posts` come from `prepare`; `by_key` maps provider post id → the
    stored row of this account; `siblings` are the stored rows sharing a text group with the batch (`sibling_hashes`).
    Returns {inserts, seen, regrouped, counts {retrieved, duplicates, excluded}, observed (oldest, newest)}: `inserts`
    are new rows, `seen` are stored rows this batch listed again (all columns may have changed), `regrouped` are other
    rows whose original or status changed because of it."""
    scope = "separate" if run["consent"].get("voiceScope") == "separate" else "brand"
    working = {}
    for row in [*by_key.values(), *siblings]:
        working.setdefault(row["id"], dict(row))
    keyed = {post_id: working[row["id"]] for post_id, row in by_key.items()}
    manual = {row_id: _manual(row) for row_id, row in working.items()}
    before = {row_id: (row["duplicate_of"], row["status"], row["exclusion_reason"]) for row_id, row in working.items()}
    inserts, seen, occurrences, oldest, newest = [], {}, [], None, None
    for post in posts:
        row = keyed.get(post["externalId"])
        if row is None:
            row = {"id": str(uuid.uuid4()), "provider": run["provider"], "account_key": run["accountKey"], "provider_post_id": post["externalId"],
                   "import_id": run["id"], "routes": [run["route"]], "connection_id": run.get("connectionId"), "permalink": post["permalink"],
                   "published_at": post["published_at"], "body": post["body"], "body_hash": post["body_hash"], "norm_hash": post["norm_hash"],
                   "language": post["language"], "content_type": post["content_type"], "originality": post["originality"],
                   "authorship": post["authorship"], "generation_origin": post["generation_origin"], "label": None, "voice_scope": scope,
                   "duplicate_of": None, "status": post["status"], "exclusion_reason": post["exclusion_reason"], "revision": 1, "first_seen_at": now}
            working[row["id"]], keyed[post["externalId"]], manual[row["id"]] = row, row, False
            inserts.append(row)
            flagged = False
        else:
            # The same post again: through another route, or listed twice by this run. Seen again later by the same
            # route it is only refreshed.
            flagged = row["import_id"] == run["id"] or run["route"] not in row["routes"]
            if run["route"] not in row["routes"]:
                row["routes"] = [*row["routes"], run["route"]]
            if post["body_hash"] != row["body_hash"]:        # edited at the source: a new revision of the same post
                row.update(body=post["body"], body_hash=post["body_hash"], norm_hash=post["norm_hash"], language=post["language"],
                           revision=int(row["revision"]) + 1)
            row.update(import_id=run["id"], connection_id=run.get("connectionId") or row["connection_id"], voice_scope=scope,
                       permalink=post["permalink"] or row["permalink"], published_at=post["published_at"] or row["published_at"])
            if post["originality"] != "unknown":
                row["originality"] = post["originality"]
            if post["generation_origin"] == "rafii_published":
                row["generation_origin"] = "rafii_published"
            if post["contentType"]:
                row["content_type"] = post["content_type"]
            # authorship, label and the person's own exclusion are theirs: a re-read never resets them
            if row["id"] in before:
                seen[row["id"]] = row
        occurrences.append((row, flagged))
        published = row["published_at"]
        if published is not None:
            oldest = published if oldest is None or published < oldest else oldest
            newest = published if newest is None or published > newest else newest
    _settle(list(working.values()), manual)
    counts = {"retrieved": len(occurrences), "duplicates": 0, "excluded": 0}
    for row, flagged in occurrences:
        if flagged or row["duplicate_of"] is not None:
            counts["duplicates"] += 1
        elif row["status"] == "excluded":
            counts["excluded"] += 1
    regrouped = [row for row_id, row in working.items()
                 if row_id in before and row_id not in seen and (row["duplicate_of"], row["status"], row["exclusion_reason"]) != before[row_id]]
    return {"inserts": inserts, "seen": list(seen.values()), "regrouped": regrouped, "counts": counts, "observed": (oldest, newest)}


def batch_counts(listed, prepared, plan, skipped):
    """The run counters one page or batch adds. `listed` is the number of records received; `skipped` is what the
    reader or the browser already left out ({unsupported, empty})."""
    extra = int(skipped.get("unsupported", 0)) + int(skipped.get("empty", 0))
    return {"discovered": listed + extra, "retrieved": plan["counts"]["retrieved"], "duplicates": plan["counts"]["duplicates"],
            "excluded": plan["counts"]["excluded"], "unsupported": prepared["unsupported"] + extra, "failed": prepared["failed"]}


def stale_proposal(state, removed_ids, now):
    """Mark the pending voice proposal stale when it was built from imported posts and cites one that is gone.
    Returns True when `state` changed. The active voice is never touched."""
    speaker = state.get("speaker") if isinstance(state, dict) else None
    proposal = speaker.get("provisional") if isinstance(speaker, dict) else None
    removed = set(removed_ids or ())
    if not removed or not isinstance(proposal, dict) or proposal.get("analysisMethod") != "voice_import" or proposal.get("status") == "stale":
        return False
    cited = set()
    for dimension in proposal.get("dimensions") if isinstance(proposal.get("dimensions"), list) else []:
        proof = dimension.get("evidence") if isinstance(dimension, dict) else None
        # Posts that show the pattern, and those that do the opposite (`counterPostIds`; `counter` is their count).
        for key in ("postIds", "counterPostIds", "counter"):
            values = proof.get(key) if isinstance(proof, dict) else None
            if isinstance(values, list):
                cited.update(value for value in values if isinstance(value, str))
    if not cited & removed:
        return False
    proposal.update(status="stale", staleReason="imported_posts_removed", staleAt=now)
    return True


# --- statements shared by both routes -------------------------------------------------------------------------------------
def _load(cur, workspace_id, where, params):
    cur.execute(f"SELECT {_POST_COLUMNS} FROM public.pr_voice_posts WHERE workspace_id=%s AND {where}", (workspace_id, *params))
    return [dict(zip(_POST_KEYS, row)) for row in cur.fetchall()]


def _save_regrouped(cur, workspace_id, rows):
    if rows:
        cur.executemany("UPDATE public.pr_voice_posts SET duplicate_of=%s::uuid, status=%s, exclusion_reason=%s WHERE id=%s::uuid AND workspace_id=%s",
                        [(row["duplicate_of"], row["status"], row["exclusion_reason"], row["id"], workspace_id) for row in rows])


def _write(cur, workspace_id, plan):
    if plan["inserts"]:
        cur.executemany(
            """INSERT INTO public.pr_voice_posts(id, workspace_id, provider, account_key, provider_post_id, import_id, routes, connection_id, permalink,
                   published_at, body, body_hash, norm_hash, language, content_type, originality, authorship, generation_origin, label, voice_scope,
                   duplicate_of, status, exclusion_reason, revision, first_seen_at, last_seen_at)
               VALUES(%s::uuid, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, now())""",
            [(row["id"], workspace_id, row["provider"], row["account_key"], row["provider_post_id"], row["import_id"], row["routes"], row["connection_id"],
              row["permalink"], row["published_at"], row["body"], row["body_hash"], row["norm_hash"], row["language"], row["content_type"],
              row["originality"], row["authorship"], row["generation_origin"], row["label"], row["voice_scope"], row["duplicate_of"], row["status"],
              row["exclusion_reason"], row["revision"], row["first_seen_at"]) for row in plan["inserts"]])
    if plan["seen"]:
        cur.executemany(
            """UPDATE public.pr_voice_posts SET import_id=%s::uuid, routes=%s, connection_id=%s, permalink=%s, published_at=%s, body=%s, body_hash=%s,
                   norm_hash=%s, language=%s, content_type=%s, originality=%s, generation_origin=%s, voice_scope=%s, duplicate_of=%s::uuid, status=%s,
                   exclusion_reason=%s, revision=%s, last_seen_at=now()
               WHERE id=%s::uuid AND workspace_id=%s""",
            [(row["import_id"], row["routes"], row["connection_id"], row["permalink"], row["published_at"], row["body"], row["body_hash"],
              row["norm_hash"], row["language"], row["content_type"], row["originality"], row["generation_origin"], row["voice_scope"],
              row["duplicate_of"], row["status"], row["exclusion_reason"], row["revision"], row["id"], workspace_id) for row in plan["seen"]])
    _save_regrouped(cur, workspace_id, plan["regrouped"])


def _regroup(cur, workspace_id, hashes):
    """Posts were removed: the copies they were the original of get a new original."""
    if hashes:
        _save_regrouped(cur, workspace_id, regroup(_load(cur, workspace_id, "norm_hash = ANY(%s)", (sorted(hashes),))))


def _run(cur, workspace_id, import_id, lock=False):
    cur.execute(f"SELECT {_RUN_COLUMNS} FROM public.pr_voice_imports WHERE id::text=%s AND workspace_id=%s" + (" FOR UPDATE" if lock else ""),
                (import_id, workspace_id))
    row = cur.fetchone()
    return dict(zip(_RUN_KEYS, row)) if row else None


def _payload(run):
    """What a person sees of a run: never its cursor, lease or anything from the connection."""
    consent = run["consent"] if isinstance(run["consent"], dict) else {}
    waiting = run["status"] in ("pending", "running") and run["retryAt"] is not None
    return {"id": run["id"], "route": run["route"], "provider": run["provider"], "connectionId": run["connectionId"], "accountKey": run["accountKey"],
            "accountLabel": run["accountLabel"], "status": run["status"],
            "consent": {"ownership": consent.get("ownership"), "voiceScope": consent.get("voiceScope"), "at": consent.get("at")},
            "requestedSince": _iso(run["requestedSince"]), "observed": {"oldest": _iso(run["observedOldest"]), "newest": _iso(run["observedNewest"])},
            "counts": {"discovered": run["discovered"], "retrieved": run["retrieved"], "duplicates": run["duplicates"], "excluded": run["excluded"],
                       "unsupported": run["unsupported"], "failed": run["failedItems"], "removedAtSource": run["removed"]},
            "pages": run["pages"], "moreRemaining": run["moreRemaining"], "totalKnown": bool(run["totalKnown"]), "failure": run["failure"],
            "retryAt": _iso(run["retryAt"]) if waiting else None, "lastSyncAt": _iso(run["lastSyncAt"]), "createdAt": _iso(run["createdAt"]),
            "updatedAt": _iso(run["updatedAt"])}


def _post_view(row):
    keys = ("id", "provider", "accountKey", "publishedAt", "permalink", "excerpt", "language", "originality", "authorship", "generationOrigin",
            "label", "status", "exclusionReason")
    view = dict(zip(keys, row))
    view["publishedAt"] = _iso(view["publishedAt"])
    if view["originality"] == "repost":
        view["excerpt"] = ""                         # nothing of a repost's text was kept
    return view


# --- disconnect: whatever POSTRIFF_VOICE_IMPORT says (like the history import's purge) --------------------------------------
def installed(cur) -> bool:
    """True once migration 140 is applied."""
    cur.execute("SELECT to_regclass('public.pr_voice_imports') IS NOT NULL")
    found = cur.fetchone()
    return bool(found and found[0])


def purge_connection(cur, workspace_id, connection_id, state=None, *, now):
    """oauth.disconnect, inside its transaction (it holds the workspace row), whether or not the importer is mounted:
    the flag may have been switched off after posts were read through this connection. Cancels the connection's runs
    and deletes the posts read through it; a post the person also uploaded keeps its row as an upload. Returns True
    when `state` was changed (a pending proposal citing removed posts is now stale), so the caller saves it. Never
    raises: its own savepoint, logged; whatever it could not remove, `sweep_revoked` removes later. Does nothing
    before migration 140."""
    removed = _guarded(cur, lambda: _purge(cur, workspace_id, connection_id), "voice_import.purge_failed")
    return bool(removed) and stale_proposal(state, removed, now)


def _purge(cur, workspace_id, connection_id):
    from .hosted import audit
    if not installed(cur):
        return []
    cur.execute("""UPDATE public.pr_voice_imports SET status='cancelled', failure_class='disconnected', lease_owner=NULL, lease_until=NULL,
                          retry_at=NULL, updated_at=now()
                   WHERE workspace_id=%s AND connection_id=%s AND status IN ('pending','running')""", (workspace_id, connection_id))
    cur.execute("""DELETE FROM public.pr_voice_posts WHERE workspace_id=%s AND connection_id=%s AND NOT ('platform_export' = ANY(routes))
                   RETURNING id::text, norm_hash""", (workspace_id, connection_id))
    deleted = cur.fetchall()
    cur.execute("UPDATE public.pr_voice_posts SET routes=array_remove(routes,'official_api'), connection_id=NULL WHERE workspace_id=%s AND connection_id=%s",
                (workspace_id, connection_id))
    if deleted:
        _regroup(cur, workspace_id, {norm for _, norm in deleted})
        audit(cur, workspace_id, None, "voice_import.connection_purged", connection_id, {"posts": len(deleted)})
    return [post_id for post_id, _ in deleted]


def sweep_revoked(connection_factory, *, limit=3, clock=time.time):
    """Cron, whatever POSTRIFF_VOICE_IMPORT says: connections already disconnected whose official-route runs or posts
    are still stored (their purge failed, or ran before this code). One transaction each, workspace row first, so it
    never races a page store. Returns {status, purged}; does nothing before migration 140; never raises."""
    try:
        with connection_factory() as db, db.cursor() as cur:
            if not installed(cur):
                return {"status": "not_migrated"}
            cur.execute("""SELECT DISTINCT i.workspace_id::text, i.connection_id FROM public.pr_voice_imports i
                           WHERE i.route='official_api'
                             AND NOT EXISTS (SELECT 1 FROM public.pr_encrypted_credentials c
                                             WHERE c.workspace_id=i.workspace_id AND c.connection_id=i.connection_id AND c.revoked_at IS NULL)
                             AND (i.status IN ('pending','running')
                                  OR EXISTS (SELECT 1 FROM public.pr_voice_posts p WHERE p.workspace_id=i.workspace_id AND p.connection_id=i.connection_id))
                           LIMIT %s""", (limit,))
            orphans = cur.fetchall()
            db.commit()
        for workspace_id, connection_id in orphans:
            with connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s FOR UPDATE", (workspace_id,))
                found = cur.fetchone()
                state = _state((None, found[0])) if found else {}
                if purge_connection(cur, workspace_id, connection_id, state, now=clock()):
                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
                db.commit()
        return {"status": "ok", "purged": len(orphans)}
    except Exception as error:  # noqa: BLE001 - the cron's later steps must still run
        _note("voice_import.sweep_failed", error)
        return {"status": "unavailable"}


class VoiceImporter:
    def __init__(self, database, oauth, *, transport, values, clock=time.time, monotonic=time.monotonic, worker_id=None, rand=random.random,
                 resolver=socket.getaddrinfo):
        self.database = database
        self.oauth = oauth
        self.transport = transport
        self.providers = allowed_providers(values)
        self.workspaces = allowed_workspaces(values)
        self.clock = clock
        self.monotonic = monotonic
        self.rand = rand
        self.resolver = resolver
        self.worker_id = worker_id or f"vi-{uuid.uuid4().hex[:12]}"
        self._migrated = False

    # --- what can work here ---------------------------------------------------------------------------------------------
    def _official(self, provider):
        """(available, reason code, sentence) for reading a connected account of this platform on this deployment."""
        _, platform, _, files = _PLATFORM[provider]
        if provider in _NO_CONNECTOR:
            return (False, *_NO_CONNECTOR[provider])
        if provider not in self.providers:
            return False, "not_enabled", f"Reading {platform} posts from a connected account is not turned on here." + (" Upload an export instead." if files else "")
        adapter = (getattr(self.oauth, "providers", None) or {}).get(provider)
        if adapter is None:
            return False, "not_configured", f"{platform} accounts cannot be connected here yet." + (" Upload an export instead." if files else "")
        if provider == "linkedin" and getattr(adapter, "history_approved", False) is not True:
            return False, "closed_permission", "LinkedIn no longer gives new apps permission to read a member's posts. Upload your LinkedIn data export instead."
        return True, None, None

    @staticmethod
    def _export(provider):
        if _PLATFORM[provider][3]:
            return True, None, None
        return False, "deferred", "Bluesky's export is a binary archive Rafii cannot read yet. Connect the account instead."

    def routes(self):
        """One row per platform: which route works here and, for one that does not, why."""
        rows = []
        for provider, platform, _, files in PLATFORMS:
            official, export = self._official(provider), self._export(provider)
            rows.append({"provider": provider, "platform": platform,
                         "official": {"available": official[0], "reason": official[1], "detail": official[2]},
                         "export": {"available": export[0], "files": list(files), "reason": export[1], "detail": export[2]}})
        return rows

    def _require_route(self, provider, route):
        available, _, detail = self._official(provider) if route == "official_api" else self._export(provider)
        if not available:
            raise AlphaError(detail, 409, code="voice_import_route_unavailable")

    # --- admission ------------------------------------------------------------------------------------------------------
    def _admit(self, workspace_id):
        if self.workspaces is not None and str(workspace_id) not in self.workspaces:
            raise AlphaError("Voice import is not enabled.", 404, code="feature_disabled")

    def _installed(self, cur):
        if not self._migrated:
            cur.execute("SELECT to_regclass('public.pr_voice_imports') IS NOT NULL")
            self._migrated = bool(cur.fetchone()[0])
        return self._migrated

    def _ready(self, cur):
        if not self._installed(cur):
            raise AlphaError("Voice import is not enabled.", 404, code="feature_disabled")

    def _throttle(self, cur, workspace_id, route):
        from .hosted import throttle
        scope, limit = ((f"voice-import:{workspace_id}", REQUESTS_PER_HOUR) if route == "official_api"
                        else (f"voice-import-upload:{workspace_id}", UPLOADS_PER_HOUR))
        try:
            throttle(cur, scope, limit, 3600)
        except AlphaError as error:
            if error.status == 429:
                raise AlphaError("Too many imports were started in the last hour. Try again later.", 429, code="voice_import_throttled") from None
            raise

    def _session(self, token, workspace_id, requirement):
        """The workspace transaction of a member who holds `requirement`; yields (cur, row, actor)."""
        from contextlib import contextmanager
        from .hosted import _membership
        from .permissions import require

        @contextmanager
        def opened():
            with self.oauth.repository.transaction(token, workspace_id) as (cur, row, actor):
                require(_membership(row), requirement)
                self._ready(cur)
                yield cur, row, actor
        return opened()

    @staticmethod
    def _credential(cur, workspace_id, connection_id):
        cur.execute("SELECT provider, provider_account_id, scopes, access_ciphertext, key_id FROM public.pr_encrypted_credentials "
                    "WHERE workspace_id=%s AND connection_id=%s AND revoked_at IS NULL", (workspace_id, connection_id))
        return cur.fetchone()

    def _readable(self, cur, workspace_id, connection_id, provider):
        """The live connection of this platform, holding the scope its history needs."""
        found = self._credential(cur, workspace_id, connection_id)
        if not found or found[0] != provider or not found[1]:
            raise AlphaError("Connect this account before importing its posts.", 404, code="connection_unavailable")
        scope = _PLATFORM[provider][2]
        if scope and scope not in (found[2] or []):
            raise AlphaError(f"Reconnect this {_PLATFORM[provider][1]} account so Rafii may read its posts.", 409, code="voice_import_permission_required")
        return found

    @staticmethod
    def _owned(cur, workspace_id, import_id, lock=False):
        run = _run(cur, workspace_id, import_id, lock) if isinstance(import_id, str) and _UUID.fullmatch(import_id) else None
        if run is None:
            raise AlphaError("This import is not available.", 404, code="voice_import_unknown")
        return run

    def _start(self, cur, workspace_id, *, route, provider, connection_id, account_key, label, consent, since, watermark, actor):
        """Insert the run, or refuse when the account already has one in flight."""
        cur.execute("""UPDATE public.pr_voice_imports SET status='failed', failure_class='abandoned', updated_at=now()
                       WHERE workspace_id=%s AND provider=%s AND account_key=%s AND status='receiving' AND updated_at < now() - make_interval(secs => %s::float8)""",
                    (workspace_id, provider, account_key, UPLOAD_IDLE_SECONDS))
        cur.execute("""INSERT INTO public.pr_voice_imports(workspace_id, route, provider, connection_id, account_key, account_label, status, consent,
                                                           requested_since, watermark, requested_by)
                       VALUES(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                       ON CONFLICT (workspace_id, provider, account_key) WHERE status IN ('pending','receiving','running') DO NOTHING
                       RETURNING id::text""",
                    (workspace_id, route, provider, connection_id, account_key, label, "pending" if route == "official_api" else "receiving",
                     json.dumps(consent), since, watermark, str(actor)))
        created = cur.fetchone()
        if not created:
            raise AlphaError("An import for this account is already running.", 409, code="voice_import_active")
        return created[0]

    # --- customer surface -----------------------------------------------------------------------------------------------
    def request(self, workspace_id, token, payload):
        from .api_tokens import is_api_token
        from .hosted import audit
        if is_api_token(token):
            raise AlphaError("An interactive sign-in is required to import posts.", 403, code="interactive_required")
        wanted = parse_request(payload)
        self._admit(workspace_id)
        self._require_route(wanted["provider"], wanted["route"])
        provider, route, scope = wanted["provider"], wanted["route"], wanted["consent"]["voiceScope"]
        with self._session(token, workspace_id, "manage_connections") as (cur, row, actor):
            self._throttle(cur, workspace_id, route)
            if route == "official_api":
                account_key = self._readable(cur, workspace_id, wanted["connectionId"], provider)[1]
                label = _channel_label(_state(row), wanted["connectionId"]) or account_key[:120]
            else:
                account_key, label = wanted["accountKey"], wanted["accountLabel"]
            cur.execute("SELECT voice_scope FROM public.pr_voice_posts WHERE workspace_id=%s AND provider=%s AND account_key=%s LIMIT 1",
                        (workspace_id, provider, account_key))
            held = cur.fetchone()
            if held and held[0] != scope:
                raise AlphaError("This account's posts were imported for the other voice. Delete that import first to change it.", 409,
                                 code="voice_scope_conflict")
            consent = {"version": CONSENT_VERSION, "ownership": wanted["consent"]["ownership"], "voiceScope": scope, "retainText": True,
                       "by": str(actor), "at": _iso(datetime.fromtimestamp(self.clock(), timezone.utc))}
            import_id = self._start(cur, workspace_id, route=route, provider=provider, connection_id=wanted["connectionId"], account_key=account_key,
                                    label=label, consent=consent, since=wanted["since"], watermark=None, actor=actor)
            audit(cur, workspace_id, actor, "voice_import.requested", import_id,
                  {"consentVersion": CONSENT_VERSION, "route": route, "provider": provider, "ownership": consent["ownership"], "voiceScope": scope})
            return {"import": _payload(_run(cur, workspace_id, import_id))}

    def items(self, workspace_id, token, import_id, payload):
        """One batch of an export upload: records the browser parsed. `seq` (optional, from 1) makes a retried batch a
        no-op instead of a second count."""
        batch = parse_batch(payload)
        self._admit(workspace_id)
        with self._session(token, workspace_id, "manage_connections") as (cur, row, _actor):
            run = self._owned(cur, workspace_id, import_id, lock=True)
            if run["route"] != "platform_export" or run["status"] != "receiving":
                raise AlphaError("This import is not waiting for records.", 409, code="voice_import_not_receiving")
            if batch["seq"] is not None and batch["seq"] <= run["pages"]:
                return {"import": _payload(run)}
            if batch["seq"] is not None and batch["seq"] != run["pages"] + 1:
                raise AlphaError("A batch is missing before this one.", 409, code="voice_import_batch_order")
            counts, observed = self._apply(cur, run, batch["items"], batch["skipped"], evidence.journal(_state(row)))
            self._advance(cur, run, counts, observed, status="done" if batch["final"] else "receiving", more=False if batch["final"] else None,
                          cursor=None, release=False)
            return {"import": _payload(_run(cur, workspace_id, import_id))}

    def cancel(self, workspace_id, token, import_id):
        """Stop a run: the next page is not read and no further batch is accepted. Stored posts stay until the import
        is deleted."""
        from .hosted import audit
        self._admit(workspace_id)
        with self._session(token, workspace_id, "manage_connections") as (cur, _row, actor):
            self._owned(cur, workspace_id, import_id, lock=True)
            cur.execute("""UPDATE public.pr_voice_imports SET status='cancelled', lease_owner=NULL, lease_until=NULL, retry_at=NULL, updated_at=now()
                           WHERE id::text=%s AND workspace_id=%s AND status IN ('pending','receiving','running') RETURNING id""", (import_id, workspace_id))
            if cur.fetchone():
                audit(cur, workspace_id, actor, "voice_import.cancelled", import_id, {})
            return {"import": _payload(_run(cur, workspace_id, import_id))}

    def refresh(self, workspace_id, token, import_id, payload=None):
        """A new run for a connected account: from the watermark (posts newer than the newest one held), or, with
        `full: true`, the whole account from newest to oldest. Only a full pass can tell that a post was deleted."""
        from .hosted import audit
        payload = {} if payload is None else payload
        if not isinstance(payload, dict) or type(payload.get("full", False)) is not bool:
            raise AlphaError("Say whether to read the whole account again with full: true or false.", 400)
        full = payload.get("full", False)
        self._admit(workspace_id)
        with self._session(token, workspace_id, "manage_connections") as (cur, row, actor):
            previous = self._owned(cur, workspace_id, import_id, lock=True)
            if previous["route"] != "official_api":
                raise AlphaError("Upload a newer export to refresh this account.", 409, code="voice_import_refresh_unavailable")
            self._require_route(previous["provider"], "official_api")
            self._throttle(cur, workspace_id, "official_api")
            found = self._readable(cur, workspace_id, previous["connectionId"], previous["provider"])
            if found[1] != previous["accountKey"]:
                raise AlphaError("Connect this account before importing its posts.", 404, code="connection_unavailable")
            since = None
            if not full:
                cur.execute("""SELECT max(published_at) FROM public.pr_voice_posts
                               WHERE workspace_id=%s AND provider=%s AND account_key=%s AND 'official_api' = ANY(routes)""",
                            (workspace_id, previous["provider"], previous["accountKey"]))
                since = cur.fetchone()[0]              # nothing held yet: the run reads everything
            label = _channel_label(_state(row), previous["connectionId"]) or previous["accountLabel"]
            new_id = self._start(cur, workspace_id, route="official_api", provider=previous["provider"], connection_id=previous["connectionId"],
                                 account_key=previous["accountKey"], label=label, consent=previous["consent"], since=since, watermark=_iso(since),
                                 actor=actor)
            audit(cur, workspace_id, actor, "voice_import.refreshed", new_id, {"provider": previous["provider"], "full": since is None})
            return {"import": _payload(_run(cur, workspace_id, new_id))}

    def delete(self, workspace_id, token, import_id):
        """Remove everything this account supplied: its posts (text and rows) and its runs."""
        from .hosted import audit
        self._admit(workspace_id)
        with self._session(token, workspace_id, "manage_connections") as (cur, row, actor):
            run = self._owned(cur, workspace_id, import_id, lock=True)
            account = (workspace_id, run["provider"], run["accountKey"])
            cur.execute("DELETE FROM public.pr_voice_posts WHERE workspace_id=%s AND provider=%s AND account_key=%s RETURNING id::text, norm_hash", account)
            deleted = cur.fetchall()
            cur.execute("DELETE FROM public.pr_voice_imports WHERE workspace_id=%s AND provider=%s AND account_key=%s", account)
            _regroup(cur, workspace_id, {norm for _, norm in deleted})
            state = _state(row)
            if stale_proposal(state, [post_id for post_id, _ in deleted], self.clock()):
                cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), workspace_id))
            audit(cur, workspace_id, actor, "voice_import.deleted", import_id, {"provider": run["provider"], "route": run["route"], "posts": len(deleted)})
            return {"deleted": True, "posts": len(deleted)}

    def status(self, workspace_id, token):
        self._admit(workspace_id)
        with self._session(token, workspace_id, "read") as (cur, row, _actor):
            cur.execute(f"SELECT {_RUN_COLUMNS} FROM public.pr_voice_imports WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 50", (workspace_id,))
            imports = [_payload(dict(zip(_RUN_KEYS, found))) for found in cur.fetchall()]
            return {"imports": imports, "coverage": evidence.coverage(cur, workspace_id, _state(row)), "routes": self.routes()}

    def posts(self, workspace_id, token, query=None):
        """The evidence browser: up to 50 stored posts as excerpts, newest first, filtered by `provider`, `accountKey`,
        `status` or a comma list of `ids`, continued with `cursor`."""
        query = query if isinstance(query, dict) else {}
        where, params = ["workspace_id=%s", "status<>'gone'"], [workspace_id]
        for key, column in (("provider", "provider"), ("accountKey", "account_key")):
            if query.get(key) is not None:
                where.append(f"{column}=%s")
                params.append(_plain(query[key], 200, "Choose a platform and account from the list."))
        if query.get("status") is not None:
            if query["status"] not in ("retrieved", "eligible", "excluded"):
                raise AlphaError("Choose retrieved, eligible or excluded posts.", 400)
            where.append("status=%s")
            params.append(query["status"])
        if query.get("ids") is not None:
            ids = [value for value in str(query["ids"]).split(",") if value]
            if not 1 <= len(ids) <= POSTS_PAGE or not all(_UUID.fullmatch(value) for value in ids):
                raise AlphaError(f"Ask for between 1 and {POSTS_PAGE} posts by id.", 400)
            where.append("id = ANY(%s::uuid[])")
            params.append(ids)
        if query.get("cursor") is not None:
            try:
                published, post_id = base64.urlsafe_b64decode(str(query["cursor"]) + "=" * (-len(str(query["cursor"])) % 4)).decode("ascii").split("|")
                moment = _moment(published)
                if moment is None or not _UUID.fullmatch(post_id):
                    raise ValueError("cursor")
            except (ValueError, UnicodeDecodeError):
                raise AlphaError("This page of posts is no longer available. Start again from the first page.", 400) from None
            where.append("(coalesce(published_at, 'epoch'::timestamptz), id) < (%s::timestamptz, %s::uuid)")
            params += [moment, post_id]
        self._admit(workspace_id)
        with self._session(token, workspace_id, "read") as (cur, _row, _actor):
            cur.execute(f"""SELECT {_POST_VIEW} FROM public.pr_voice_posts WHERE {' AND '.join(where)}
                            ORDER BY coalesce(published_at, 'epoch'::timestamptz) DESC, id DESC LIMIT %s""", (*params, POSTS_PAGE + 1))
            rows = cur.fetchall()
        following = None
        if len(rows) > POSTS_PAGE:
            rows = rows[:POSTS_PAGE]
            last = _iso(rows[-1][3]) or "1970-01-01T00:00:00+00:00"
            following = base64.urlsafe_b64encode(f"{last}|{rows[-1][0]}".encode("ascii")).decode("ascii").rstrip("=")
        return {"posts": [_post_view(found) for found in rows], "nextCursor": following}

    def correct_post(self, workspace_id, token, post_id, payload):
        """The person's own word on one post: who wrote it, how to read it, or leave it out. Survives every re-read."""
        from .hosted import audit
        change = _correction(payload)
        if not isinstance(post_id, str) or not _UUID.fullmatch(post_id):
            raise AlphaError("This post is not available.", 404, code="voice_post_unknown")
        self._admit(workspace_id)
        with self._session(token, workspace_id, "edit") as (cur, _row, actor):
            cur.execute(f"SELECT {_POST_COLUMNS} FROM public.pr_voice_posts WHERE id::text=%s AND workspace_id=%s AND status<>'gone' FOR UPDATE",
                        (post_id.lower(), workspace_id))
            found = cur.fetchone()
            if not found:
                raise AlphaError("This post is not available.", 404, code="voice_post_unknown")
            post = dict(zip(_POST_KEYS, found))
            manual = change["excluded"] if "excluded" in change else _manual(post)
            post.update({key: change[key] for key in ("authorship", "label") if key in change})
            post["status"], post["exclusion_reason"] = _status(post, manual)
            cur.execute("UPDATE public.pr_voice_posts SET authorship=%s, label=%s, status=%s, exclusion_reason=%s WHERE id::text=%s AND workspace_id=%s",
                        (post["authorship"], post["label"], post["status"], post["exclusion_reason"], post["id"], workspace_id))
            audit(cur, workspace_id, actor, "voice_import.post_corrected", post["id"], {"fields": sorted(change)})
            cur.execute(f"SELECT {_POST_VIEW} FROM public.pr_voice_posts WHERE id::text=%s AND workspace_id=%s", (post["id"], workspace_id))
            return {"post": _post_view(cur.fetchone())}

    # --- disconnect -----------------------------------------------------------------------------------------------------
    def purge_connection(self, cur, workspace_id, connection_id, state=None):
        """oauth.disconnect with the importer mounted: the module's `purge_connection` on this importer's clock."""
        return purge_connection(cur, workspace_id, connection_id, state, now=self.clock())

    # --- storing one page or batch ---------------------------------------------------------------------------------------
    def _apply(self, cur, run, items, skipped, journal):
        prepared = prepare(items, run=run, journal=journal)
        by_key, siblings = {}, []
        if prepared["posts"]:
            ids = sorted({post["externalId"] for post in prepared["posts"]})
            by_key = {row["provider_post_id"]: row for row in _load(cur, run["workspaceId"], "provider=%s AND account_key=%s AND provider_post_id = ANY(%s)",
                                                                    (run["provider"], run["accountKey"], ids))}
            siblings = _load(cur, run["workspaceId"], "norm_hash = ANY(%s)", (sorted(sibling_hashes(prepared["posts"], by_key)),))
        plan = plan_batch(prepared["posts"], by_key, siblings, run=run, now=datetime.fromtimestamp(self.clock(), timezone.utc))
        _write(cur, run["workspaceId"], plan)
        return batch_counts(len(items), prepared, plan, skipped), plan["observed"]

    @staticmethod
    def _advance(cur, run, counts, observed, *, status, more, cursor, release, watermark=None):
        cur.execute("""UPDATE public.pr_voice_imports SET discovered=discovered+%s, retrieved=retrieved+%s, duplicates=duplicates+%s,
                              excluded=excluded+%s, unsupported=unsupported+%s, failed_items=failed_items+%s, removed=removed+%s, pages=pages+1,
                              observed_oldest=least(observed_oldest, %s::timestamptz), observed_newest=greatest(observed_newest, %s::timestamptz),
                              cursor=%s, more_remaining=coalesce(%s, more_remaining), status=%s, failure_class=NULL, attempts=0, retry_at=NULL,
                              watermark=coalesce(%s, watermark), lease_owner=CASE WHEN %s THEN NULL ELSE lease_owner END,
                              lease_until=CASE WHEN %s THEN NULL ELSE lease_until END, last_sync_at=now(), updated_at=now()
                       WHERE id::text=%s""",
                    (counts["discovered"], counts["retrieved"], counts["duplicates"], counts["excluded"], counts["unsupported"], counts["failed"],
                     counts.get("removed", 0), observed[0], observed[1], cursor, more, status, watermark, release, release, run["id"]))

    def _remove_unseen(self, cur, run):
        """A complete newest-to-oldest pass has seen everything the provider returns: official-route posts of this
        account it did not see were deleted at the source, so their text and rows go here too. A post the person also
        uploaded keeps its row and loses only the official route."""
        account = (run["workspaceId"], run["provider"], run["accountKey"], run["createdAt"])
        cur.execute("""DELETE FROM public.pr_voice_posts WHERE workspace_id=%s AND provider=%s AND account_key=%s
                         AND routes = ARRAY['official_api']::text[] AND last_seen_at < %s RETURNING id::text, norm_hash""", account)
        deleted = cur.fetchall()
        cur.execute("""UPDATE public.pr_voice_posts SET routes=array_remove(routes,'official_api'), connection_id=NULL
                       WHERE workspace_id=%s AND provider=%s AND account_key=%s AND 'official_api' = ANY(routes) AND last_seen_at < %s""", account)
        if deleted:
            _regroup(cur, run["workspaceId"], {norm for _, norm in deleted})
            cur.execute("SELECT state->'speaker'->'provisional'->>'analysisMethod' FROM public.pr_workspaces WHERE id=%s", (run["workspaceId"],))
            method = cur.fetchone()
            if method and method[0] == "voice_import":
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (run["workspaceId"],))
                state = _state((None, cur.fetchone()[0]))
                if stale_proposal(state, [post_id for post_id, _ in deleted], self.clock()):
                    cur.execute("UPDATE public.pr_workspaces SET state=%s::jsonb, revision=revision+1 WHERE id=%s", (json.dumps(state), run["workspaceId"]))
        return len(deleted)

    def _store_page(self, run, page, done, journal):
        """One page of an official run: its posts, the counters and the cursor in one transaction fenced on the lease.
        Returns the page's counts, or None when the run is no longer this worker's to write (cancelled, re-claimed,
        disconnected, workspace being deleted): nothing is stored then."""
        with self.database() as db, db.cursor() as cur:
            cur.execute("SELECT state ? 'accountDeletion' OR state ? 'accountBlock' FROM public.pr_workspaces WHERE id=%s FOR NO KEY UPDATE",
                        (run["workspaceId"],))
            workspace = cur.fetchone()
            cur.execute("SELECT discovered FROM public.pr_voice_imports WHERE id::text=%s AND lease_owner=%s AND status='running' FOR UPDATE",
                        (run["id"], self.worker_id))
            live = cur.fetchone()
            if not workspace or workspace[0] or not live or not self._credential(cur, run["workspaceId"], run["connectionId"]):
                db.rollback()
                return None
            counts, observed = self._apply(cur, run, page.items, {"unsupported": page.skipped, "empty": 0}, journal)
            watermark = None
            if done:
                # Only a pass that read the whole account, and that the provider answered with at least one item, proves a
                # removal: an empty answer cannot be told from a read the provider limited.
                if run["requestedSince"] is None and live[0] + counts["discovered"] > 0:
                    counts["removed"] = self._remove_unseen(cur, run)
                cur.execute("""SELECT max(published_at) FROM public.pr_voice_posts
                               WHERE workspace_id=%s AND provider=%s AND account_key=%s AND 'official_api' = ANY(routes)""",
                            (run["workspaceId"], run["provider"], run["accountKey"]))
                watermark = _iso(cur.fetchone()[0])
            self._advance(cur, run, counts, observed, status="done" if done else "running", more=not done, cursor=page.next_cursor, release=done,
                          watermark=watermark)
            db.commit()
        return counts

    # --- cron step ----------------------------------------------------------------------------------------------------------
    def claim(self, limit):
        admitted = "" if self.workspaces is None else " AND workspace_id = ANY(%s::uuid[])"
        params = (self.worker_id, LEASE_SECONDS, *(() if self.workspaces is None else (sorted(self.workspaces),)), limit)
        with self.database() as db, db.cursor() as cur:
            cur.execute(f"""UPDATE public.pr_voice_imports i SET status='running', lease_owner=%s, lease_until=now() + make_interval(secs => %s),
                                   attempts=attempts+1, updated_at=now()
                            WHERE i.id IN (SELECT id FROM public.pr_voice_imports
                                           WHERE route='official_api' AND (status='pending' OR (status='running' AND (lease_until IS NULL OR lease_until < now())))
                                             AND (retry_at IS NULL OR retry_at <= now()){admitted}
                                           ORDER BY updated_at LIMIT %s FOR UPDATE SKIP LOCKED)
                            RETURNING i.id::text, i.workspace_id::text, i.provider, i.connection_id, i.account_key, i.route, i.cursor, i.pages,
                                      i.attempts, i.requested_since, i.consent, i.created_at""", params)
            rows = cur.fetchall()
            db.commit()
        keys = ("id", "workspaceId", "provider", "connectionId", "accountKey", "route", "cursor", "pages", "attempts", "requestedSince", "consent", "createdAt")
        return [dict(zip(keys, row)) for row in rows]

    def _eligible(self, run):
        """What a claimed run needs to read: None when it may no longer run (the connection was revoked or changed, the
        workspace is being deleted or is not admitted, the provider was switched off)."""
        if (self.workspaces is not None and run["workspaceId"] not in self.workspaces) or not self._official(run["provider"])[0]:
            return None
        with self.database() as db, db.cursor() as cur:
            cur.execute("SELECT state ? 'accountDeletion', state ? 'accountBlock', state->'phase2'->'jobs' FROM public.pr_workspaces WHERE id=%s",
                        (run["workspaceId"],))
            workspace = cur.fetchone()
            credential = self._credential(cur, run["workspaceId"], run["connectionId"]) if workspace and not workspace[0] and not workspace[1] else None
        scope = _PLATFORM[run["provider"]][2]
        if (not credential or credential[0] != run["provider"] or credential[1] != run["accountKey"] or (scope and scope not in (credential[2] or []))):
            return None
        # Bluesky is read from the account's own public repository: only where it lives is needed, never a token.
        stored = self.oauth.vault.decrypt(credential[3], credential[4]) if run["provider"] == "bluesky" else None
        jobs = workspace[2] if isinstance(workspace[2], list) else []
        return {"scopes": list(credential[2] or []), "journal": evidence.journal({"phase2": {"jobs": jobs}}), "stored": stored}

    def _token(self, run, context):
        if run["provider"] == "bluesky":
            try:
                session = json.loads(context["stored"])
                return json.dumps({"did": session["did"], "pds": session["pds"]})
            except (ValueError, TypeError, KeyError):
                raise AlphaError("The stored connection cannot be read.", 409) from None
        grant = self.oauth.token_for_worker(run["workspaceId"], run["connectionId"])
        if grant.get("providerAccountId") not in (None, run["accountKey"]):
            raise AlphaError("The connected account changed.", 409)
        if run["provider"] == "mastodon" and "read:statuses" not in (grant.get("scopes") or []):
            return None                                # an identity-only grant: public posts need no authorization
        return grant["accessToken"]

    def _live(self, run):
        with self.database() as db, db.cursor() as cur:
            cur.execute("SELECT 1 FROM public.pr_voice_imports WHERE id::text=%s AND lease_owner=%s AND status='running'", (run["id"], self.worker_id))
            return cur.fetchone() is not None

    def _finish(self, run, status, failure=None, more=None):
        with self.database() as db, db.cursor() as cur:
            cur.execute("""UPDATE public.pr_voice_imports SET status=%s, failure_class=%s, more_remaining=coalesce(%s, more_remaining), lease_owner=NULL,
                                  lease_until=NULL, retry_at=NULL, updated_at=now()
                           WHERE id::text=%s AND lease_owner=%s AND status='running'""", (status, failure, more, run["id"], self.worker_id))
            db.commit()

    def _handback(self, run, failure=None, delay=None, refund=False):
        """Give the run back, keeping its cursor: claimable again at once, or after `delay` seconds. `refund` returns
        the attempt a claim took when the run was never tried (deadline), so deferral never fails a run."""
        with self.database() as db, db.cursor() as cur:
            cur.execute("""UPDATE public.pr_voice_imports SET failure_class=%s, retry_at=now() + make_interval(secs => %s::float8), lease_owner=NULL,
                                  lease_until=NULL, attempts=CASE WHEN %s THEN greatest(0, attempts-1) ELSE attempts END, updated_at=now()
                           WHERE id::text=%s AND lease_owner=%s AND status='running'""", (failure, delay, refund, run["id"], self.worker_id))
            db.commit()

    def _retry(self, run, failure, retry_after=None):
        if run["attempts"] >= MAX_ATTEMPTS:
            self._finish(run, "failed", failure)
            return "failed"
        self._handback(run, failure=failure, delay=leases.backoff_seconds(run["attempts"], retry_after=retry_after, rand=self.rand))
        return "retry"

    def run_one(self, run, deadline):
        """Advance one claimed run by up to PAGES_PER_TICK pages. Returns a short outcome word; never raises."""
        try:
            context = self._eligible(run)
            if context is None:
                self._finish(run, "cancelled", "not_eligible")
                return "cancelled"
            token = self._token(run, context)
        except AlphaError as error:
            if getattr(error, "status", None) in (404, 409):
                self._finish(run, "failed", "credential")
                return "failed"
            return self._retry(run, "transport")
        except Exception as error:  # noqa: BLE001 - one run must not stop the step
            _note("voice_import.prepare_failed", error)
            return self._retry(run, "error")
        cursor, pages = run["cursor"], run["pages"]
        for _ in range(PAGES_PER_TICK):
            if self.monotonic() >= deadline:
                break
            if not self._live(run):
                return "cancelled"                     # cancelled or taken over: the next page is not read
            if pages >= MAX_PAGES:
                self._finish(run, "done", "page_cap", more=True)
                return "done"
            try:
                page = readers.read_page(run["provider"], token=token, account=run["accountKey"], cursor=cursor, since=run["requestedSince"],
                                         transport=self.transport, resolver=self.resolver)
            except readers.ReaderHTTP as error:
                if error.status in TERMINAL_HTTP:
                    self._finish(run, "failed", f"http_{error.status}")
                    return "failed"
                return self._retry(run, f"http_{error.status}", error.retry_after)
            except readers.ReaderPaging:
                self._finish(run, "failed", "incomplete_paging", more=True)
                return "failed"
            except AlphaError:
                return self._retry(run, "transport")
            except Exception as error:  # noqa: BLE001
                _note("voice_import.read_failed", error)
                return self._retry(run, "error")
            done = not page.more or page.next_cursor is None
            try:
                stored = self._store_page(run, page, done, context["journal"])
            except Exception as error:  # noqa: BLE001 - the page's transaction rolled back; read it again from the same cursor
                _note("voice_import.store_failed", error)
                return self._retry(run, "store")
            if stored is None:
                return "lost_lease"
            if done:
                return "done"
            cursor, pages = page.next_cursor, pages + 1
            run = {**run, "attempts": 0}               # a stored page reset the run's attempts
        self._handback(run)
        return "continued"

    def tick(self, max_runs=RUNS_PER_TICK, max_seconds=20.0):
        """Bounded cron step. Returns a dict of counts; never raises."""
        counts = {"status": "ok", "claimed": 0}
        try:
            with self.database() as db, db.cursor() as cur:
                if not self._installed(cur):
                    return {"status": "not_migrated"}
                cur.execute("""UPDATE public.pr_voice_imports SET status='failed', failure_class='abandoned', updated_at=now()
                               WHERE status='receiving' AND updated_at < now() - make_interval(secs => %s::float8)""", (UPLOAD_IDLE_SECONDS,))
                db.commit()
            deadline = self.monotonic() + max_seconds
            runs = self.claim(max_runs)
            counts["claimed"] = len(runs)
            for run in runs:
                if self.monotonic() >= deadline:
                    self._handback(run, refund=True)
                    counts["deferred"] = counts.get("deferred", 0) + 1
                    continue
                outcome = self.run_one(run, deadline)
                counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as error:  # noqa: BLE001 - later cron steps must still run
            _note("voice_import.tick_failed", error)
            counts["status"] = "unavailable"
        return counts
