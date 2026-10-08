"""Smart Collections (engineering spec §4 CollectionDefinition, §9; PRD R09, D4; T06).

A smart collection saves a versioned, ALLOWLISTED rule tree (rule_schema 1), never SQL, code or prompt text. Membership is
materialized as references in pr_library_collection_items (origin 'rule' or 'include'); no bytes are ever copied.

    rule      := group | predicate
    group     := {"all": [rule, ...]} | {"any": [rule, ...]} | {"not": rule}            (at most 4 group levels)
    predicate := {"field": F, "op": OP, "value": V, ["origin"|"timeZone"|"capability"]}  (at most 40 predicates)

Deterministic predicates and AI suggestions stay distinct: a model-suggested tag counts only when the predicate says
origin "ai_suggested" (or "any"), and members admitted only through such a tag carry that provenance. The plain-language
explanation is generated here from the normalized rule; a client never supplies it.

Only the newest processed version of each asset (its "current" version) is matched by a rule; an older version is in a
collection only by an explicit include. Exclude overrides beat everything. Includes must stay browsable: a deleted,
hidden or foreign item is never (re)admitted, including by undo. Every save, override and undo writes a new revision
snapshot and bumps the workspace organization revision; a stale expected revision is a 409.

Evaluation is incremental for one asset change (`reevaluate_for_asset`, called after commit/finalize hooks) and repaired
periodically by `reconcile_due` (LibraryIntelligence.tick), bounded per tick.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, textnorm, versions

RULE_SCHEMA = 1
MAX_DEPTH = 4
MAX_PREDICATES = 40
MAX_COLLECTIONS = 100
MAX_CANDIDATES = 5000
MAX_OVERRIDES = 200
MAX_PAGE = 100
DEFAULT_PAGE = 30
SAMPLE = 20
HISTORY = 20
RECONCILE_SECONDS = 600
RECONCILE_LIMIT = 5
PROCESSED = ("ready", "unsupported", "legacy", "failed")
WAITING = ("pending", "queued", "processing")

KINDS = ("image", "video", "audio", "document", "file")
SOURCE_KINDS = ("upload", "link", "note", "artifact")
TAG_ORIGINS = ("user", "ai_suggested", "any")
ORIENTATIONS = ("portrait", "landscape", "square")
GROUPS = ("all", "any", "not")
# field -> op -> value type. Anything else is rejected with a 400 that names the offending part.
FIELDS = {
    "kind": {"in": "kinds"},
    "tag": {"has": "tag", "has_any": "tags"},
    "title_contains": {"contains": "text120"},
    "filename_contains": {"contains": "text120"},
    "created_after": {"on_or_after": "date"},
    "created_before": {"before": "date"},
    "mime_prefix": {"starts_with": "mime"},
    "language": {"in": "languages"},
    "capability": {"in": "states"},
    "source_kind": {"in": "source_kinds"},
    "duration_ms": {"gte": "ms", "lte": "ms"},
    "orientation": {"eq": "orientation"},
    "usage": {"eq": "usage"},
    "text_matches": {"matches": "text200"},
}
EXTRAS = {"tag": {"origin": "user"}, "created_after": {"timeZone": "UTC"}, "created_before": {"timeZone": "UTC"}, "capability": {"capability": None}}
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
MIME = re.compile(r"^[a-z]+(/[a-z0-9.+\-]*)?$")
ZONE = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+\-]+){0,2}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
NAME = re.compile(r"^[^\x00]{1,80}$")

# --- SQL (tagged /*lio:...*/ so unit tests can emulate each statement) ---------------------------------------------------
COLL_COLS = ("id::text,name,kind,rule,rule_schema,explanation,revision,last_evaluated_revision,created_by::text,extract(epoch from created_at),"
             "extract(epoch from updated_at)")
COLL_GET = f"/*lio:coll.get*/ SELECT {COLL_COLS} FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s"
COLL_LOCK = f"/*lio:coll.lock*/ SELECT {COLL_COLS} FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s FOR UPDATE"
COLL_COUNT = "/*lio:coll.count*/ SELECT count(*) FROM public.pr_library_collections WHERE workspace_id=%s"
COLL_NAME_TAKEN = "/*lio:coll.name_taken*/ SELECT 1 FROM public.pr_library_collections WHERE workspace_id=%s AND name=%s AND id IS DISTINCT FROM %s"
COLL_INSERT = ("/*lio:coll.insert*/ INSERT INTO public.pr_library_collections(id,workspace_id,name,created_by,kind,rule,rule_schema,explanation,revision,"
               "last_evaluated_revision,updated_at) VALUES(%s,%s,%s,%s,'smart',%s::jsonb,%s,%s,1,null,now()) ON CONFLICT DO NOTHING RETURNING revision")
COLL_UPDATE = ("/*lio:coll.update*/ UPDATE public.pr_library_collections SET name=%s,rule=%s::jsonb,rule_schema=%s,explanation=%s,revision=revision+1,"
               "updated_at=now() WHERE workspace_id=%s AND id=%s AND revision=%s RETURNING revision")
COLL_BUMP = ("/*lio:coll.bump*/ UPDATE public.pr_library_collections SET revision=revision+1,updated_at=now() WHERE workspace_id=%s AND id=%s "
             "AND revision=%s RETURNING revision")
COLL_EVALUATED = "/*lio:coll.evaluated*/ UPDATE public.pr_library_collections SET last_evaluated_revision=%s,updated_at=now() WHERE workspace_id=%s AND id=%s"
COLL_SMART = ("/*lio:coll.smart*/ SELECT id::text,rule,revision FROM public.pr_library_collections WHERE workspace_id=%s AND kind='smart' "
              "AND rule IS NOT NULL ORDER BY created_at,id LIMIT 100 FOR UPDATE SKIP LOCKED")
COLL_DUE = ("/*lio:coll.due*/ SELECT workspace_id::text,id::text FROM public.pr_library_collections WHERE kind='smart' AND rule IS NOT NULL "
            "AND (last_evaluated_revision IS DISTINCT FROM revision OR updated_at<now()-make_interval(secs=>%s)) "
            "ORDER BY (last_evaluated_revision IS NOT DISTINCT FROM revision),updated_at LIMIT %s")
COLL_TRY = ("/*lio:coll.try*/ SELECT id::text,rule,revision,kind FROM public.pr_library_collections WHERE workspace_id=%s AND id=%s "
            "FOR UPDATE SKIP LOCKED")
ITEMS = "/*lio:items.list*/ SELECT asset_key,origin FROM public.pr_library_collection_items WHERE workspace_id=%s AND collection_id=%s"
ITEMS_FOR = ("/*lio:items.for*/ SELECT asset_key,origin FROM public.pr_library_collection_items WHERE workspace_id=%s AND collection_id=%s "
             "AND asset_key=ANY(%s)")
ITEMS_DELETE = "/*lio:items.delete*/ DELETE FROM public.pr_library_collection_items WHERE workspace_id=%s AND collection_id=%s AND asset_key=ANY(%s)"
ITEMS_UPSERT = ("/*lio:items.upsert*/ INSERT INTO public.pr_library_collection_items(workspace_id,collection_id,asset_key,origin) "
                "SELECT %s::uuid,%s::uuid,t.k,t.o FROM unnest(%s::text[],%s::text[]) AS t(k,o) ON CONFLICT(workspace_id,collection_id,asset_key) "
                "DO UPDATE SET origin=excluded.origin")
ITEMS_COUNT = "/*lio:items.count*/ SELECT origin,count(*) FROM public.pr_library_collection_items WHERE workspace_id=%s AND collection_id=%s GROUP BY origin"
OVR = "/*lio:ovr.list*/ SELECT asset_key,mode FROM public.pr_library_collection_overrides WHERE workspace_id=%s AND collection_id=%s"
OVR_FOR = ("/*lio:ovr.for*/ SELECT asset_key,mode FROM public.pr_library_collection_overrides WHERE workspace_id=%s AND collection_id=%s "
           "AND asset_key=ANY(%s)")
OVR_PUT = ("/*lio:ovr.put*/ INSERT INTO public.pr_library_collection_overrides(workspace_id,collection_id,asset_key,mode,created_by) "
           "SELECT %s::uuid,%s::uuid,t.k,%s::text,%s::uuid FROM unnest(%s::text[]) AS t(k) ON CONFLICT(workspace_id,collection_id,asset_key) "
           "DO UPDATE SET mode=excluded.mode,created_by=excluded.created_by,created_at=now()")
OVR_DELETE = "/*lio:ovr.delete*/ DELETE FROM public.pr_library_collection_overrides WHERE workspace_id=%s AND collection_id=%s AND asset_key=ANY(%s)"
OVR_CLEAR = "/*lio:ovr.clear*/ DELETE FROM public.pr_library_collection_overrides WHERE workspace_id=%s AND collection_id=%s"
REV_PUT = ("/*lio:rev.put*/ INSERT INTO public.pr_library_collection_revisions(workspace_id,collection_id,revision,snapshot,created_by) "
           "VALUES(%s,%s,%s,%s::jsonb,%s)")
REV_GET = "/*lio:rev.get*/ SELECT snapshot FROM public.pr_library_collection_revisions WHERE workspace_id=%s AND collection_id=%s AND revision=%s"
REV_LIST = ("/*lio:rev.list*/ SELECT revision,snapshot,created_by::text,extract(epoch from created_at) FROM public.pr_library_collection_revisions "
            "WHERE workspace_id=%s AND collection_id=%s ORDER BY revision DESC LIMIT %s")
LINEAGE_KEYS = ("/*lio:lineage.keys*/ SELECT replace(id::text,'-','') FROM public.pr_library_assets WHERE workspace_id=%s "
                "AND coalesce(lineage_id,id)=ANY(%s::uuid[]) LIMIT 1000")
F_ANNOTATIONS = ("/*lio:facts.annotations*/ SELECT version_key,field,value,origin FROM public.pr_library_annotations WHERE workspace_id=%s AND active "
                 "AND field=ANY(%s) AND version_key=ANY(%s)")
F_LANGUAGES = ("/*lio:facts.languages*/ SELECT version_key,array_agg(DISTINCT language) FROM public.pr_library_segments WHERE workspace_id=%s "
               "AND superseded_at IS NULL AND language IS NOT NULL AND version_key=ANY(%s) GROUP BY version_key")
F_CAPS = "/*lio:facts.caps*/ SELECT asset_key,capability,state FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=ANY(%s)"
F_USAGE = ("/*lio:facts.usage*/ SELECT asset_key,version_key FROM public.pr_library_usage_events WHERE workspace_id=%s "
           "AND (asset_key=ANY(%s) OR version_key=ANY(%s))")
F_USED_IN = ("/*lio:facts.used_in*/ SELECT DISTINCT from_version FROM public.pr_library_relations WHERE workspace_id=%s AND relation='used_in' "
             "AND status IN ('active','stale') AND from_version=ANY(%s)")
F_TEXT = ("/*lio:facts.text*/ SELECT DISTINCT version_key FROM public.pr_library_segments WHERE workspace_id=%s AND superseded_at IS NULL "
          "AND search_vector @@ to_tsquery('simple',%s) AND version_key=ANY(%s)")
F_CHUNKS = ("/*lio:facts.chunks*/ SELECT DISTINCT replace(asset_id::text,'-','') FROM public.pr_library_chunks WHERE workspace_id=%s "
            "AND asset_id=ANY(%s::uuid[]) AND (text ILIKE ALL(%s) OR text ILIKE ALL(%s))")


def _fail(message: str, status: int = 400, code: str = "library_rule_invalid"):
    raise AlphaError(message[:300], status, code=code)


def _label(value) -> str:
    return CONTROL.sub("", str(value))[:40]


# --- rule validation (pure) ----------------------------------------------------------------------------------------------
def _text(value, limit: int, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL.search(value):
        _fail(f"Use {what} of 1 to {limit} characters.")
    if c.UNSAFE.search(value):
        _fail("Rules hold plain words, not links, markup or query text.")
    return value.strip()


def _list(value, limit: int, what: str) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        _fail(f"Choose 1 to {limit} {what}.")
    return value


def _value(kind: str, value):
    if kind == "kinds":
        items = _list(value, len(KINDS), "file types")
        if not all(isinstance(x, str) and x in KINDS for x in items):
            _fail("Choose image, video, audio, document or file.")
        return [x for x in KINDS if x in items]
    if kind == "tag":
        return _text(value, 40, "a tag")
    if kind == "tags":
        return list(dict.fromkeys(_text(x, 40, "a tag") for x in _list(value, 20, "tags")))
    if kind == "text120":
        return _text(value, 120, "text")
    if kind == "text200":
        text = _text(value, 200, "words to match")
        if not textnorm.query_terms(text):
            _fail("Use words or characters to match in the text.")
        return text
    if kind == "date":
        if not isinstance(value, str) or not DAY.fullmatch(value):
            _fail("Use dates such as 2026-10-08.")
        try:
            date.fromisoformat(value)
        except ValueError:
            _fail("Use a real calendar date.")
        return value
    if kind == "mime":
        if not isinstance(value, str) or not 1 <= len(value) <= 100 or not MIME.fullmatch(value.strip().lower()):
            _fail("Use a content type prefix such as audio/ or image/png.")
        return value.strip().lower()
    if kind == "languages":
        items = _list(value, 8, "languages")
        if not all(isinstance(x, str) and LANGUAGE.fullmatch(x) for x in items):
            _fail("Use language codes such as yue, zh-Hant or en.")
        return list(dict.fromkeys(items))
    if kind == "states":
        items = _list(value, len(c.CAPABILITY_STATES), "processing states")
        if not all(isinstance(x, str) and x in c.CAPABILITY_STATES for x in items):
            _fail("Choose known processing states.")
        return [x for x in c.CAPABILITY_STATES if x in items]
    if kind == "source_kinds":
        items = _list(value, len(SOURCE_KINDS), "sources")
        if not all(isinstance(x, str) and x in SOURCE_KINDS for x in items):
            _fail("Choose upload, link, note or artifact.")
        return [x for x in SOURCE_KINDS if x in items]
    if kind == "ms":
        if type(value) is not int or not 0 <= value <= 86_400_000:
            _fail("Use a duration in milliseconds up to 24 hours.")
        return value
    if kind == "orientation":
        if value not in ORIENTATIONS:
            _fail("Choose portrait, landscape or square.")
        return value
    if value not in ("used", "unused"):
        _fail("Choose used or unused.")
    return value


def _zone(value) -> str:
    if not isinstance(value, str) or not ZONE.fullmatch(value):
        _fail("Use an IANA time zone such as Asia/Hong_Kong.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        _fail("Use an IANA time zone such as Asia/Hong_Kong.")
    return value


def _predicate(node: dict) -> dict:
    field = node.get("field")
    if not isinstance(field, str) or field not in FIELDS:
        _fail(f"“{_label(field)}” is not a supported criterion. Use one of: {', '.join(FIELDS)}.")
    allowed = {"field", "op", "value", *EXTRAS.get(field, {})}
    extra = [key for key in node if key not in allowed]
    if extra:
        _fail(f"A {field} criterion cannot use “{_label(extra[0])}”.")
    op = node.get("op")
    if not isinstance(op, str) or op not in FIELDS[field]:
        _fail(f"“{_label(op)}” does not apply to {field}. Use {' or '.join(FIELDS[field])}.")
    out = {"field": field, "op": op, "value": _value(FIELDS[field][op], node.get("value"))}
    if field == "tag":
        origin = node.get("origin", "user")
        if origin not in TAG_ORIGINS:
            _fail("A tag's origin is user, ai_suggested or any.")
        out["origin"] = origin
    elif field in ("created_after", "created_before"):
        out["timeZone"] = _zone(node.get("timeZone", "UTC"))
    elif field == "capability":
        if node.get("capability") not in c.CAPABILITIES:
            _fail("Name a processing capability such as transcribe or extract.")
        out["capability"] = node["capability"]
    return out


def validate_rule(rule) -> dict:
    """Return the canonical rule tree or raise a 400 naming what was rejected. Never executes or interpolates anything."""
    if not isinstance(rule, dict):
        _fail("A smart collection rule is a set of criteria, not text, code or a query.")
    count = [0]

    def walk(node, depth):
        if not isinstance(node, dict):
            _fail("Each criterion is an object with a field, an operator and a value.")
        groups = [key for key in GROUPS if key in node]
        if groups:
            if len(node) != 1:
                _fail(f"A group cannot also use “{_label(next(k for k in node if k not in GROUPS))}”." if any(k not in GROUPS for k in node)
                      else "Use one of all, any or not per group.")
            if depth > MAX_DEPTH:
                _fail(f"Nest criteria at most {MAX_DEPTH} levels deep.")
            key = groups[0]
            if key == "not":
                return {"not": walk(node["not"], depth + 1)}
            children = node[key]
            if not isinstance(children, list) or not children:
                _fail("Each group needs at least one criterion.")
            if len(children) > MAX_PREDICATES:
                _fail(f"Use at most {MAX_PREDICATES} criteria.")
            return {key: [walk(child, depth + 1) for child in children]}
        if "field" not in node:
            _fail(f"“{_label(next(iter(node), ''))}” is not part of a Library rule. Use all, any, not or a field criterion.")
        count[0] += 1
        if count[0] > MAX_PREDICATES:
            _fail(f"Use at most {MAX_PREDICATES} criteria.")
        return _predicate(node)

    tree = walk(rule, 1)
    if not any(key in tree for key in GROUPS):
        tree = {"all": [tree]}
    return tree


def predicates(rule: dict):
    if "all" in rule or "any" in rule:
        for child in rule.get("all") or rule.get("any"):
            yield from predicates(child)
    elif "not" in rule:
        yield from predicates(rule["not"])
    else:
        yield rule


def fields_used(rule: dict) -> set:
    return {p["field"] for p in predicates(rule)}


def text_key(value: str) -> str:
    return " ".join(textnorm.query_terms(value))


# --- explanation (pure) ------------------------------------------------------------------------------------------------
CAPABILITY_NOUNS = {"preview": "a preview", "extract": "text extraction", "transcribe": "transcription", "visual": "visual analysis",
                    "embed_text": "text indexing", "embed_visual": "visual indexing", "understand": "an understanding card"}
SOURCE_WORDS = {"upload": "upload", "link": "link", "note": "quick note", "artifact": "Rafii deliverable"}
KIND_NOUNS = {"image": "images", "video": "videos", "audio": "audio", "document": "documents", "file": "other files"}


def _quote(value) -> str:
    return f"“{CONTROL.sub('', str(value))}”"


def _or(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


def _phrase(p: dict) -> str:
    field, value = p["field"], p["value"]
    if field == "kind":
        return "are " + _or(KIND_NOUNS[k] for k in value)
    if field == "tag":
        tags = [value] if p["op"] == "has" else value
        quoted = _or(_quote(t) for t in tags)
        if p["origin"] == "ai_suggested":
            return f"have the AI-suggested tag {quoted} (a suggestion, not confirmed)"
        if p["origin"] == "any":
            return f"are tagged {quoted} (including AI suggestions)"
        return f"are tagged {quoted}"
    if field == "title_contains":
        return f"have {_quote(value)} in the title"
    if field == "filename_contains":
        return f"have {_quote(value)} in the file name"
    if field == "created_after":
        return f"were added on or after {value} ({p['timeZone']} time)"
    if field == "created_before":
        return f"were added before {value} ({p['timeZone']} time)"
    if field == "mime_prefix":
        return f"have a content type starting with {_quote(value)}"
    if field == "language":
        return "have content in " + _or(value)
    if field == "capability":
        return f"have {CAPABILITY_NOUNS[p['capability']]} " + _or(s.replace("_", " ") for s in value)
    if field == "source_kind":
        return "were added by " + _or(sorted(SOURCE_WORDS[s] for s in value))
    if field == "duration_ms":
        return f"are at {'least' if p['op'] == 'gte' else 'most'} {_clock(value)} long"
    if field == "orientation":
        return "are " + value
    if field == "usage":
        return "have been used in a draft or post" if value == "used" else "have not been used yet"
    return f"mention {_quote(value)} in their text"


def _clause(node: dict, top: bool = False) -> str:
    if "all" in node or "any" in node:
        joiner = " and " if "all" in node else " or "
        parts = [_clause(child) for child in (node.get("all") or node.get("any"))]
        text = joiner.join(parts)
        return text if top or len(parts) == 1 else f"({text})"
    if "not" in node:
        inner = node["not"]
        if "field" in inner and _phrase(inner).startswith("are "):
            return "are not " + _phrase(inner)[4:]
        return f"do not match ({_clause(inner, top=True)})"
    return _phrase(node)


def explain(rule: dict) -> str:
    """Plain-language explanation generated from a normalized rule; the same rule always reads the same."""
    return f"Current Library items that {_clause(rule, top=True)}."


# --- evaluation (pure) ---------------------------------------------------------------------------------------------------
def _day_start(day: str, zone: str) -> float:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, tzinfo=ZoneInfo(zone)).timestamp()


def _fold(value) -> str:
    return textnorm.fold(value).strip()


def _language_match(have: list, wanted: list) -> bool:
    have = [h.lower() for h in have or ()]
    for want in wanted:
        w = want.lower()
        if any(h == w or (len(w) <= 3 and h.split("-")[0] == w) for h in have):
            return True
    return False


def _match(p: dict, f: dict, hits: dict) -> bool:
    field, op, value = p["field"], p["op"], p["value"]
    if field == "kind":
        return f.get("kind") in value
    if field == "tag":
        wanted = [_fold(value)] if op == "has" else [_fold(v) for v in value]
        pool = []
        if p["origin"] in ("user", "any"):
            pool += [_fold(t) for t in f.get("tags") or ()]
        if p["origin"] in ("ai_suggested", "any"):
            pool += [_fold(t) for t in f.get("aiTags") or ()]
        return any(w in pool for w in wanted)
    if field == "title_contains":
        return _fold(value) in _fold(f.get("title") or "")
    if field == "filename_contains":
        return _fold(value) in _fold(f.get("filename") or "")
    if field == "created_after":
        return f.get("createdAt") is not None and float(f["createdAt"]) >= _day_start(value, p["timeZone"])
    if field == "created_before":
        return f.get("createdAt") is not None and float(f["createdAt"]) < _day_start(value, p["timeZone"])
    if field == "mime_prefix":
        return str(f.get("mime") or "").lower().startswith(value)
    if field == "language":
        return _language_match(f.get("languages") or [], value)
    if field == "capability":
        return (f.get("capabilities") or {}).get(p["capability"], "not_requested") in value
    if field == "source_kind":
        return f.get("sourceKind", "upload") in value
    if field == "duration_ms":
        duration = f.get("durationMs")
        if duration is None:
            return False
        return duration >= value if op == "gte" else duration <= value
    if field == "orientation":
        return f.get("orientation") == value
    if field == "usage":
        return bool(f.get("used")) == (value == "used")
    return f.get("key") in hits.get(text_key(value), ())


def evaluate(rule: dict, facts: dict, hits: dict | None = None) -> bool:
    hits = hits or {}
    if "all" in rule:
        return all(evaluate(child, facts, hits) for child in rule["all"])
    if "any" in rule:
        return any(evaluate(child, facts, hits) for child in rule["any"])
    if "not" in rule:
        return not evaluate(rule["not"], facts, hits)
    return _match(rule, facts, hits)


def provenance(rule: dict, facts: dict, hits: dict | None = None) -> list:
    """['ai_suggested_tag'] when the item matches only because of an AI-suggested tag."""
    if not facts.get("aiTags") or not evaluate(rule, facts, hits):
        return []
    return [] if evaluate(rule, {**facts, "aiTags": []}, hits) else ["ai_suggested_tag"]


def membership(rule: dict, facts: dict, overrides: dict, hits: dict | None = None) -> dict:
    """{key: 'rule'|'include'} for accessible candidates. Exclude beats everything; includes need an accessible item;
    only an asset's current version is matched by the rule."""
    out = {}
    for key, f in facts.items():
        mode = overrides.get(key)
        if mode == "exclude":
            continue
        if mode == "include":
            out[key] = "include"
        elif f.get("current", True) and evaluate(rule, f, hits):
            out[key] = "rule"
    return out


def legacy_used(state: dict) -> set:
    """Media referenced by prepared posts: the same rule the Library UI uses (jobs in any state; reviews awaiting approval
    that are not already a job)."""
    phase2 = (state or {}).get("phase2") or {}
    used, keys = set(), set()

    def media(manifest):
        return {m.get("id") for m in (manifest or {}).get("media") or [] if isinstance(m, dict) and isinstance(m.get("id"), str)}
    for job in phase2.get("jobs") or []:
        if isinstance(job, dict):
            manifest = job.get("manifest") or {}
            keys.update(x for x in (job.get("approvalDigest"), manifest.get("idempotencyKey")) if x)
            used |= media(manifest)
    for review in phase2.get("reviews") or []:
        if not isinstance(review, dict) or review.get("status") != "needs_review":
            continue
        manifest = review.get("manifest") or {}
        if review.get("digest") in keys or manifest.get("idempotencyKey") in keys:
            continue
        used |= media(manifest)
    return used


# --- facts (database) ----------------------------------------------------------------------------------------------------
def _orientation(media: dict):
    w, h = media.get("width"), media.get("height")
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or w <= 0 or h <= 0:
        return None
    return "square" if w == h else ("portrait" if h > w else "landscape")


def _facts(v: dict) -> dict:
    media = v.get("media") or {}
    duration = media.get("durationMs")
    return {"key": v["versionId"], "assetId": v["assetId"], "versionId": v["versionId"], "sha256": v["sha256"], "versionNo": v["versionNo"],
            "kind": v["kind"], "tags": list(v.get("tags") or []), "aiTags": [], "title": v.get("title") or "", "filename": v.get("filename") or "",
            "createdAt": v.get("createdAt"), "mime": v.get("mime") or "", "languages": [], "capabilities": {}, "sourceKind": v.get("sourceKind") or "upload",
            "durationMs": int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,
            "orientation": _orientation(media), "used": False, "current": True, "legacy": bool(v.get("legacy"))}


def _strings(value) -> list:
    if isinstance(value, dict):
        value = value.get("value", value.get("values"))
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str)]
    return []


def _mark_current(facts: dict):
    best = {}
    for key, f in facts.items():
        rank = (f["versionNo"], f["createdAt"] or 0, key)
        if f["assetId"] not in best or rank > best[f["assetId"]][0]:
            best[f["assetId"]] = (rank, key)
    heads = {key for _, key in best.values()}
    for key, f in facts.items():
        f["current"] = key in heads


def load_facts(ctx, keys=None, fields=frozenset()) -> tuple[dict, dict]:
    """Browsable, processed versions with the facts the given rule fields need. keys=None is the whole workspace
    (bounded by MAX_CANDIDATES); otherwise pass complete lineages so 'current' is decided correctly."""
    meta = {"partial": False, "notYetProcessed": 0}
    if keys is None:
        accessible = versions.accessible_keys(ctx)
        wanted = sorted(key for key, status in accessible.items() if status in PROCESSED)
        meta["notYetProcessed"] = sum(1 for status in accessible.values() if status in WAITING)
    else:
        wanted = list(dict.fromkeys(keys))
    if len(wanted) > MAX_CANDIDATES:
        wanted, meta["partial"] = wanted[:MAX_CANDIDATES], True
    loaded = versions.load(ctx, wanted) if wanted else {}
    facts = {key: _facts(v) for key, v in loaded.items()
             if v["status"] in PROCESSED and policy.authorize_source(ctx, v, "browse").allowed}
    _mark_current(facts)
    if not facts:
        return facts, meta
    cur, ws, keys = ctx.cur, ctx.workspace_id, list(facts)
    if fields & {"tag", "language"}:
        cur.execute(F_ANNOTATIONS, (ws, ["tag", "tags", "language"], keys))
        for key, field, value, origin in cur.fetchall():
            f = facts.get(key)
            if f is None:
                continue
            if field == "language":
                if origin != "ai_suggested":
                    f["languages"] += [x for x in _strings(value) if LANGUAGE.fullmatch(x)]
            elif origin == "ai_suggested":
                f["aiTags"] += _strings(value)
            else:
                f["tags"] += _strings(value)
    if "language" in fields:
        cur.execute(F_LANGUAGES, (ws, keys))
        for key, languages in cur.fetchall():
            if key in facts:
                facts[key]["languages"] += [x for x in languages or () if isinstance(x, str)]
    if "capability" in fields:
        cur.execute(F_CAPS, (ws, keys))
        for key, capability, state in cur.fetchall():
            if key in facts:
                facts[key]["capabilities"][capability] = state
    if "usage" in fields:
        lineages = sorted({f["assetId"] for f in facts.values()} | set(keys))
        cur.execute(F_USAGE, (ws, lineages, keys))
        events = cur.fetchall()
        cur.execute(F_USED_IN, (ws, keys))
        used = {r[0] for r in cur.fetchall()} | legacy_used(ctx.state)
        for key, f in facts.items():
            f["used"] = key in used or any(v == key or (v is None and a in (key, f["assetId"])) for a, v in events)
    return facts, meta


def text_hits(ctx, rule: dict, facts: dict) -> dict:
    """Lexical text matches for every text_matches value: normalized segments (CJK bigrams, S/T folding) unioned with the
    existing extracted-text chunks, so items not yet segmented still match. Values reach Postgres only as bound parameters."""
    values = {p["value"] for p in predicates(rule) if p["field"] == "text_matches"}
    if not values or not facts:
        return {}
    keys = list(facts)
    normalized = [str(uuid.UUID(hex=key)) for key, f in facts.items() if not f.get("legacy")]
    out = {}
    for value in values:
        found = set()
        query = textnorm.tsquery(value)
        if query:
            ctx.cur.execute(F_TEXT, (ctx.workspace_id, query, keys))
            found |= {r[0] for r in ctx.cur.fetchall()}
        words = [w for w in value.split() if w][:8]
        if normalized and words:
            # Extracted text (covers items not yet segmented): the words as typed, or folded (NFKC, Simplified -> Traditional).
            ctx.cur.execute(F_CHUNKS, (ctx.workspace_id, normalized, _like(words), _like(textnorm.fold(w) for w in words)))
            found |= {r[0] for r in ctx.cur.fetchall()}
        out[text_key(value)] = found
    return out


def _like(words) -> list:
    return ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]


def lineage_keys(ctx, keys) -> list:
    """Every version key in the lineages of `keys` (so the current version of each is decided correctly)."""
    keys = [c.asset_key(k) for k in keys]
    loaded = versions.load(ctx, keys)
    lineages = sorted({v["assetId"] for v in loaded.values() if not v["legacy"]} | {k for k in keys if k not in loaded})
    out = set(keys)
    if lineages:
        ctx.cur.execute(LINEAGE_KEYS, (ctx.workspace_id, [str(uuid.UUID(hex=k)) for k in lineages]))
        out |= {r[0] for r in ctx.cur.fetchall()}
    return sorted(out)


# --- collection rows ---------------------------------------------------------------------------------------------------
def _uuid(key) -> uuid.UUID:
    return uuid.UUID(hex=c.asset_key(key))


def _collection(row) -> dict:
    return {"id": c.asset_key(row[0]), "name": row[1], "kind": row[2], "rule": row[3], "ruleSchema": row[4], "explanation": row[5],
            "revision": int(row[6]), "lastEvaluatedRevision": int(row[7]) if row[7] is not None else None, "createdBy": row[8],
            "createdAt": float(row[9]) if row[9] is not None else None, "updatedAt": float(row[10]) if row[10] is not None else None}


def _get(ctx, collection_id, *, lock=False) -> dict:
    try:
        cid = _uuid(collection_id)
    except AlphaError:
        raise AlphaError("Collection unavailable.", 404, code="library_unavailable") from None
    ctx.cur.execute(COLL_LOCK if lock else COLL_GET, (ctx.workspace_id, cid))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("Collection unavailable.", 404, code="library_unavailable")
    return _collection(row)


def _smart(row: dict):
    if row["kind"] != "smart":
        raise AlphaError("This is a manual collection. Add or remove its items from each item's details.", 409, code="library_collection_manual")


def _check_revision(row: dict, expected):
    if expected is None or type(expected) is not int or expected != row["revision"]:
        raise AlphaError("This collection changed. Reload it and try again.", 409, code="library_collection_conflict")


def _writable(ctx):
    ctx.require("edit")
    if (ctx.state.get("workspace") or {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")


def _overrides(ctx, cid, keys=None) -> dict:
    if keys is None:
        ctx.cur.execute(OVR, (ctx.workspace_id, cid))
    else:
        ctx.cur.execute(OVR_FOR, (ctx.workspace_id, cid, list(keys)))
    return {key: mode for key, mode in ctx.cur.fetchall() if mode in ("include", "exclude")}


def _materialize(ctx, cid, desired: dict, keys=None) -> tuple[int, int]:
    """Write membership references for `keys` (None = the whole collection). Returns (added, removed)."""
    if keys is None:
        ctx.cur.execute(ITEMS, (ctx.workspace_id, cid))
    else:
        ctx.cur.execute(ITEMS_FOR, (ctx.workspace_id, cid, list(keys)))
    current = dict(ctx.cur.fetchall())
    scope = None if keys is None else set(keys)
    remove = sorted(k for k in current if (scope is None or k in scope) and k not in desired)
    upsert = sorted(k for k, o in desired.items() if (scope is None or k in scope) and current.get(k) != o)
    if remove:
        ctx.cur.execute(ITEMS_DELETE, (ctx.workspace_id, cid, remove))
    if upsert:
        ctx.cur.execute(ITEMS_UPSERT, (ctx.workspace_id, cid, upsert, [desired[k] for k in upsert]))
    return sum(1 for k in upsert if k not in current), len(remove)


def _evaluate(ctx, rule: dict, overrides: dict, keys=None) -> tuple[dict, dict, dict, dict]:
    facts, meta = load_facts(ctx, keys, fields_used(rule))
    hits = text_hits(ctx, rule, facts)
    return membership(rule, facts, overrides, hits), facts, hits, meta


def _counts(ctx, cid) -> dict:
    ctx.cur.execute(ITEMS_COUNT, (ctx.workspace_id, cid))
    counts = {"rule": 0, "include": 0, "manual": 0}
    for origin, n in ctx.cur.fetchall():
        counts[origin] = counts.get(origin, 0) + int(n)
    return counts


def _definition(ctx, row: dict, overrides: dict | None = None) -> dict:
    cid = _uuid(row["id"])
    counts = _counts(ctx, cid)
    if overrides is None:
        overrides = _overrides(ctx, cid)
    return {"id": row["id"], "name": row["name"], "kind": row["kind"], "rule": row["rule"], "ruleSchema": row["ruleSchema"],
            "explanation": row["explanation"] if row["kind"] == "smart" else "Items you add by hand.",
            "revision": row["revision"], "lastEvaluatedRevision": row["lastEvaluatedRevision"],
            "evaluationCurrent": row["kind"] != "smart" or row["lastEvaluatedRevision"] == row["revision"],
            "memberCount": sum(counts.values()), "members": counts,
            "overrides": {"include": sum(1 for m in overrides.values() if m == "include"), "exclude": sum(1 for m in overrides.values() if m == "exclude")},
            "createdAt": row["createdAt"], "updatedAt": row["updatedAt"]}


def _snapshot(action: str, row: dict, rule: dict, overrides: dict, members: int, **extra) -> str:
    return json.dumps({"action": action, "name": row["name"], "rule": rule, "ruleSchema": RULE_SCHEMA, "explanation": explain(rule),
                       "overrides": [{"assetKey": k, "mode": overrides[k]} for k in sorted(overrides)], "memberCount": members, **extra},
                      ensure_ascii=False, sort_keys=True)


def _audit(ctx, kind: str, subject: str, meta: dict):
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, kind, subject, meta)


def _finish(ctx, cid, row: dict, revision: int, rule: dict, overrides: dict, action: str, *, changes=None, warnings=(), **extra) -> dict:
    ctx.cur.execute(COLL_EVALUATED, (revision, ctx.workspace_id, cid))
    counts = _counts(ctx, cid)
    members = sum(counts.values())
    ctx.cur.execute(REV_PUT, (ctx.workspace_id, cid, revision, _snapshot(action, row, rule, overrides, members, **extra), ctx.actor))
    revs = policy.bump(ctx, organization=True)
    _audit(ctx, f"library.collection_{action}", row["id"], {"revision": revision, "members": members, "criteria": sum(1 for _ in predicates(rule)),
                                                              "overrides": len(overrides)})
    fresh = _get(ctx, row["id"])
    out = {"collection": _definition(ctx, fresh, overrides), "organizationRevision": revs["organizationRevision"], "warnings": [w for w in warnings if w]}
    if changes is not None:
        out["changes"] = changes
    return out


# --- public operations ---------------------------------------------------------------------------------------------------
def _name(value) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value.strip() or "\x00"):
        c.fail("Use a collection name from 1 to 80 characters.")
    return value.strip()


def _parse_overrides(value) -> dict:
    """{"include": [key...], "exclude": [key...]} -> {key: mode}."""
    if value is None:
        return {}
    if not isinstance(value, dict) or not set(value) <= {"include", "exclude"}:
        c.fail("Overrides list items to include or exclude.")
    out = {}
    for mode in ("include", "exclude"):
        keys = value.get(mode) or []
        if not isinstance(keys, list) or len(keys) > MAX_OVERRIDES:
            c.fail(f"Include or exclude at most {MAX_OVERRIDES} items.")
        for key in keys:
            if not isinstance(key, str) or not c.KEY.fullmatch(key.replace("-", "").lower()):
                c.fail("Choose valid Library items.")
            key = key.replace("-", "").lower()
            if key in out and out[key] != mode:
                c.fail("An item cannot be both included and excluded.")
            out[key] = mode
    return out


def _member(ref_facts: dict, origin: str, rule: dict, hits: dict) -> dict:
    f = ref_facts
    return {"assetRef": {"assetId": f["assetId"], "versionId": f["versionId"], "sha256": f["sha256"]}, "origin": origin, "title": f["title"],
            "kind": f["kind"], "provenance": provenance(rule, f, hits) if origin == "rule" else []}


def preview_collection(ctx, rule, overrides=None, *, collection_id=None, offset: int = 0, limit: int = DEFAULT_PAGE) -> dict:
    """Membership a rule would have right now: a page of member refs, the count, what changes against the saved
    collection and the explanation. Read-only; members are references, never file contents or links."""
    ctx.require("read")
    rule = validate_rule(rule)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        c.fail(f"Use a page of 1 to {MAX_PAGE} items.")
    current = None
    if collection_id is not None:
        row = _get(ctx, collection_id)
        cid = _uuid(row["id"])
        if overrides is None:
            overrides = _overrides(ctx, cid)
        ctx.cur.execute(ITEMS, (ctx.workspace_id, cid))
        current = dict(ctx.cur.fetchall())
    overrides = dict(overrides or {})
    desired, facts, hits, meta = _evaluate(ctx, rule, overrides)
    unavailable = sum(1 for key, mode in overrides.items() if mode == "include" and key not in facts)
    ordered = sorted(desired, key=lambda key: (-(facts[key]["createdAt"] or 0), key))
    page = ordered[offset:offset + limit]
    counts = {"rule": sum(1 for o in desired.values() if o == "rule"), "include": sum(1 for o in desired.values() if o == "include")}
    out = {"rule": rule, "ruleSchema": RULE_SCHEMA, "explanation": explain(rule), "count": len(desired), "counts": counts,
           "members": [_member(facts[key], desired[key], rule, hits) for key in page],
           "page": {"offset": offset, "limit": limit, "nextOffset": offset + limit if offset + limit < len(ordered) else None},
           "coverage": {"evaluated": len(facts), "partial": meta["partial"], "notYetProcessed": meta["notYetProcessed"]},
           "unavailableIncludes": unavailable, "changes": None, "warnings": []}
    if current is not None:
        added = [k for k in ordered if k not in current]
        removed = sorted(k for k in current if k not in desired)
        out["changes"] = {"added": {"count": len(added), "sample": [_member(facts[k], desired[k], rule, hits)["assetRef"] for k in added[:SAMPLE]]},
                          "removed": {"count": len(removed), "sample": removed[:SAMPLE]}}
    if unavailable:
        out["warnings"].append(f"{unavailable} included item{'s are' if unavailable != 1 else ' is'} unavailable and left out.")
    if meta["notYetProcessed"]:
        out["warnings"].append("Items still processing are checked again when they finish.")
    if meta["partial"]:
        out["warnings"].append(f"Only the first {MAX_CANDIDATES} items were checked.")
    return out


def save_collection(ctx, rule, expected_revision, *, collection_id=None, name=None) -> dict:
    """Create a smart collection (collection_id None) or save new criteria (expected_revision must match)."""
    _writable(ctx)
    rule = validate_rule(rule)
    explanation = explain(rule)
    rule_json = json.dumps(rule, ensure_ascii=False, sort_keys=True)
    if collection_id is None:
        name = _name(name)
        if expected_revision not in (None, 0):
            raise AlphaError("This collection changed. Reload it and try again.", 409, code="library_collection_conflict")
        ctx.cur.execute(COLL_COUNT, (ctx.workspace_id,))
        if int(ctx.cur.fetchone()[0]) >= MAX_COLLECTIONS:
            raise AlphaError(f"This workspace has reached {MAX_COLLECTIONS} collections.", 409, code="library_collection_limit")
        ctx.cur.execute(COLL_NAME_TAKEN, (ctx.workspace_id, name, None))
        if ctx.cur.fetchone():
            raise AlphaError("A collection with this name already exists.", 409, code="library_collection_name_taken")
        cid = uuid.uuid4()
        ctx.cur.execute(COLL_INSERT, (cid, ctx.workspace_id, name, ctx.actor, rule_json, RULE_SCHEMA, explanation))
        if not ctx.cur.fetchone():
            raise AlphaError("A collection with this name already exists.", 409, code="library_collection_name_taken")
        row = _get(ctx, cid.hex, lock=True)
        overrides, action, revision = {}, "created", 1
    else:
        row = _get(ctx, collection_id, lock=True)
        _smart(row)
        _check_revision(row, expected_revision)
        cid = _uuid(row["id"])
        name = row["name"] if name is None else _name(name)
        if name != row["name"]:
            ctx.cur.execute(COLL_NAME_TAKEN, (ctx.workspace_id, name, cid))
            if ctx.cur.fetchone():
                raise AlphaError("A collection with this name already exists.", 409, code="library_collection_name_taken")
        ctx.cur.execute(COLL_UPDATE, (name, rule_json, RULE_SCHEMA, explanation, ctx.workspace_id, cid, expected_revision))
        updated = ctx.cur.fetchone()
        if not updated:
            raise AlphaError("This collection changed. Reload it and try again.", 409, code="library_collection_conflict")
        revision = int(updated[0])
        row = {**row, "name": name}
        overrides, action = _overrides(ctx, cid), "saved"
    desired, facts, _, meta = _evaluate(ctx, rule, overrides)
    # A truncated evaluation only rewrites the items it actually checked; reconciliation covers the rest over time.
    added, removed = _materialize(ctx, cid, desired, list(facts) if meta["partial"] else None)
    warnings = [f"Only the first {MAX_CANDIDATES} items were checked; the rest are checked over time."] if meta["partial"] else []
    return _finish(ctx, cid, row, revision, rule, overrides, action, changes={"added": added, "removed": removed}, warnings=warnings)


def set_overrides(ctx, collection_id, keys, mode, expected_revision) -> dict:
    """Include, exclude or clear explicit overrides for items. Includes must be browsable right now."""
    _writable(ctx)
    if mode not in ("include", "exclude", "clear"):
        c.fail("Choose include, exclude or clear.")
    keys = sorted({c.asset_key(k) for k in keys or ()})
    if not 1 <= len(keys) <= MAX_OVERRIDES:
        c.fail(f"Choose 1 to {MAX_OVERRIDES} items.")
    row = _get(ctx, collection_id, lock=True)
    _smart(row)
    _check_revision(row, expected_revision)
    cid = _uuid(row["id"])
    if mode != "clear":
        # Overrides name items of this workspace only; an include must also be browsable right now.
        loaded = versions.load(ctx, keys)
        if any(k not in loaded for k in keys) or (mode == "include" and any(
                not policy.authorize_source(ctx, loaded[k], "browse").allowed or loaded[k]["status"] in ("deleting", "duplicate") for k in keys)):
            raise AlphaError("One of these items is unavailable.", 404, code="library_unavailable")
    if mode == "clear":
        ctx.cur.execute(OVR_DELETE, (ctx.workspace_id, cid, keys))
    else:
        ctx.cur.execute(OVR_PUT, (ctx.workspace_id, cid, mode, ctx.actor, keys))
    ctx.cur.execute(COLL_BUMP, (ctx.workspace_id, cid, expected_revision))
    bumped = ctx.cur.fetchone()
    if not bumped:
        raise AlphaError("This collection changed. Reload it and try again.", 409, code="library_collection_conflict")
    revision = int(bumped[0])
    rule = validate_rule(row["rule"])
    scope = lineage_keys(ctx, keys)
    overrides = _overrides(ctx, cid)
    desired, _, _, _ = _evaluate(ctx, rule, {k: overrides[k] for k in scope if k in overrides}, scope)
    added, removed = _materialize(ctx, cid, desired, scope)
    return _finish(ctx, cid, row, revision, rule, overrides, "overridden", changes={"added": added, "removed": removed}, mode=mode)


def undo(ctx, collection_id, expected_revision) -> dict:
    """Restore the previous rule and overrides as a NEW revision. Deleted, hidden or no-longer-browsable items are not
    restored, and grants are never touched: undo cannot bring back revoked access."""
    _writable(ctx)
    row = _get(ctx, collection_id, lock=True)
    _smart(row)
    _check_revision(row, expected_revision)
    cid = _uuid(row["id"])
    ctx.cur.execute(REV_GET, (ctx.workspace_id, cid, row["revision"]))
    latest = ctx.cur.fetchone()
    latest = latest[0] if latest else {}
    target = (int(latest["restoredRevision"]) if isinstance(latest, dict) and type(latest.get("restoredRevision")) is int else row["revision"]) - 1
    snapshot = None
    if target >= 1:
        ctx.cur.execute(REV_GET, (ctx.workspace_id, cid, target))
        found = ctx.cur.fetchone()
        snapshot = found[0] if found else None
    if not isinstance(snapshot, dict):
        raise AlphaError("There is no earlier version of this collection to restore.", 409, code="library_nothing_to_undo")
    rule = validate_rule(snapshot.get("rule"))
    wanted = {}
    for item in snapshot.get("overrides") or []:
        if isinstance(item, dict) and item.get("mode") in ("include", "exclude") and isinstance(item.get("assetKey"), str) and c.KEY.fullmatch(item["assetKey"]):
            wanted[item["assetKey"]] = item["mode"]
    loaded = versions.load(ctx, list(wanted)) if wanted else {}
    restorable = {k: m for k, m in wanted.items() if k in loaded and loaded[k]["status"] not in ("deleting", "duplicate", "missing")
                  and policy.authorize_source(ctx, loaded[k], "browse").allowed}
    dropped = sum(1 for k, m in wanted.items() if k not in restorable and m == "include")
    ctx.cur.execute(OVR_CLEAR, (ctx.workspace_id, cid))
    for mode in ("include", "exclude"):
        keys = sorted(k for k, m in restorable.items() if m == mode)
        if keys:
            ctx.cur.execute(OVR_PUT, (ctx.workspace_id, cid, mode, ctx.actor, keys))
    ctx.cur.execute(COLL_UPDATE, (row["name"], json.dumps(rule, ensure_ascii=False, sort_keys=True), RULE_SCHEMA, explain(rule), ctx.workspace_id, cid,
                                  expected_revision))
    updated = ctx.cur.fetchone()
    if not updated:
        raise AlphaError("This collection changed. Reload it and try again.", 409, code="library_collection_conflict")
    revision = int(updated[0])
    desired, _, _, _ = _evaluate(ctx, rule, restorable)
    added, removed = _materialize(ctx, cid, desired)
    warnings = [f"{dropped} included item{'s are' if dropped != 1 else ' is'} no longer available and {'were' if dropped != 1 else 'was'} not restored."] if dropped else []
    return _finish(ctx, cid, row, revision, rule, restorable, "undone", changes={"added": added, "removed": removed}, warnings=warnings,
                   restoredRevision=target, undoneRevision=row["revision"])


def collection(ctx, collection_id) -> dict:
    ctx.require("read")
    row = _get(ctx, collection_id)
    cid = _uuid(row["id"])
    ctx.cur.execute(REV_LIST, (ctx.workspace_id, cid, HISTORY))
    history = []
    for revision, snapshot, created_by, created in ctx.cur.fetchall():
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        entry = {"revision": int(revision), "action": snapshot.get("action"), "explanation": snapshot.get("explanation"),
                 "memberCount": snapshot.get("memberCount"), "byYou": created_by == ctx.actor,
                 "createdAt": float(created) if created is not None else None}
        if type(snapshot.get("restoredRevision")) is int:
            entry["restoredRevision"] = snapshot["restoredRevision"]
        history.append(entry)
    latest = history[0] if history and history[0]["revision"] == row["revision"] else {}
    target = (latest.get("restoredRevision") or row["revision"]) - 1
    return {"collection": _definition(ctx, row), "history": history, "canUndo": row["kind"] == "smart" and target >= 1}


# --- incremental evaluation and reconciliation ------------------------------------------------------------------------------
def reevaluate_for_asset(cur, workspace_id, asset_key) -> dict:
    """Re-evaluate every smart collection for one changed asset (its whole lineage, so a new current version replaces the
    old one). Runs inside the caller's transaction under a savepoint and never raises: a failure is repaired later by
    reconcile_due. Collections locked by a concurrent save are skipped (that save evaluates the whole Library)."""
    try:
        key = c.asset_key(asset_key)
    except AlphaError:
        return {"status": "invalid"}
    try:
        cur.execute("SAVEPOINT library_collections")
    except Exception:
        return {"status": "error"}
    try:
        from .jobs import system_context
        ctx = system_context(cur, workspace_id)
        if ctx is None:
            cur.execute("RELEASE SAVEPOINT library_collections")
            return {"status": "workspace_unavailable"}
        cur.execute(COLL_SMART, (ctx.workspace_id,))
        rows = cur.fetchall()
        summary = {"status": "ok", "collections": len(rows), "added": 0, "removed": 0}
        if rows:
            keys = lineage_keys(ctx, [key])
            parsed = []
            for cid_text, rule, _ in rows:
                try:
                    parsed.append((_uuid(cid_text), validate_rule(rule)))
                except AlphaError:
                    continue  # a rule from a future schema is left for its own code path, never guessed at
            fields = set().union(*(fields_used(rule) for _, rule in parsed)) if parsed else set()
            facts, _ = load_facts(ctx, keys, fields)
            for cid, rule in parsed:
                hits = text_hits(ctx, rule, facts)
                desired = membership(rule, facts, _overrides(ctx, cid, keys), hits)
                added, removed = _materialize(ctx, cid, desired, keys)
                summary["added"] += added
                summary["removed"] += removed
        cur.execute("RELEASE SAVEPOINT library_collections")
        try:
            from . import relations
            summary["similar"] = relations.refresh_similar(cur, workspace_id, key)
        except ImportError:
            pass
        return summary
    except Exception as error:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT library_collections")
        except Exception:
            pass
        print(json.dumps({"event": "library_intelligence.collections_reevaluate_failed", "error": type(error).__name__}), flush=True)
        return {"status": "error"}


def reconcile_due(intel, connect, *, limit: int = RECONCILE_LIMIT, stale_seconds: int = RECONCILE_SECONDS) -> dict:
    """Bounded periodic repair (LibraryIntelligence.tick): re-evaluate up to `limit` smart collections that were never
    evaluated at their current revision or not for `stale_seconds`. Each runs in its own transaction; never raises."""
    summary = {"status": "ok", "checked": 0, "added": 0, "removed": 0, "errors": 0}
    try:
        with connect() as db, db.cursor() as cur:
            cur.execute(COLL_DUE, (int(stale_seconds), int(limit)))
            due = cur.fetchall()
    except Exception as error:
        print(json.dumps({"event": "library_intelligence.collections_reconcile_failed", "error": type(error).__name__}), flush=True)
        return {**summary, "status": "error"}
    from .jobs import system_context
    for workspace_id, collection_id in due:
        try:
            with connect() as db, db.cursor() as cur:
                ctx = system_context(cur, workspace_id)
                if ctx is None:
                    continue
                cid = _uuid(collection_id)
                cur.execute(COLL_TRY, (ctx.workspace_id, cid))
                row = cur.fetchone()
                if not row or row[3] != "smart" or not row[1]:
                    continue
                rule = validate_rule(row[1])
                desired, _, _, meta = _evaluate(ctx, rule, _overrides(ctx, cid))
                added, removed = _materialize(ctx, cid, desired)
                cur.execute(COLL_EVALUATED, (int(row[2]), ctx.workspace_id, cid))
                summary["checked"] += 1
                summary["added"] += added
                summary["removed"] += removed
        except Exception as error:
            summary["errors"] += 1
            print(json.dumps({"event": "library_intelligence.collection_reconcile_failed", "error": type(error).__name__}), flush=True)
    return summary


# --- HTTP and actions ------------------------------------------------------------------------------------------------------
def preview_http(ctx, request):
    """POST .../collections/preview {rule, overrides?, collectionId?, offset?, limit?}."""
    body = request.get("body") or {}
    if not isinstance(body, dict) or not set(body) <= {"rule", "overrides", "collectionId", "offset", "limit"}:
        c.fail("Send a rule with optional overrides, a collection and a page.")
    return preview_collection(ctx, body.get("rule"), _parse_overrides(body.get("overrides")) if "overrides" in body else None,
                              collection_id=body.get("collectionId"), offset=body.get("offset", 0), limit=body.get("limit", DEFAULT_PAGE))


def collection_http(ctx, request):
    """GET .../collections/{key}: definition, explanation, revision history and member counts."""
    return collection(ctx, request["params"]["key"])


def _payload(envelope: dict, allowed: set) -> dict:
    payload = envelope.get("payload") or {}
    extra = set(payload) - allowed
    if extra:
        c.fail(f"This action does not accept “{_label(sorted(extra)[0])}”.")
    return payload


def preview_action(ctx, envelope, targets):
    payload = _payload(envelope, {"rule", "overrides", "collectionId", "offset", "limit"})
    result = preview_collection(ctx, payload.get("rule"), _parse_overrides(payload.get("overrides")) if "overrides" in payload else None,
                                collection_id=payload.get("collectionId"), offset=payload.get("offset", 0), limit=payload.get("limit", DEFAULT_PAGE))
    return c.action_result("applied", result=result, warnings=result["warnings"])


def save_action(ctx, envelope, targets):
    payload = _payload(envelope, {"rule", "name", "collectionId"})
    out = save_collection(ctx, payload.get("rule"), envelope.get("expectedRevision"), collection_id=payload.get("collectionId"), name=payload.get("name"))
    return c.action_result("applied", revision=out["collection"]["revision"], result=out, warnings=out["warnings"])


def override_action(ctx, envelope, targets):
    payload = _payload(envelope, {"collectionId", "mode"})
    if not targets:
        c.fail("Choose the items to include or exclude.")
    out = set_overrides(ctx, payload.get("collectionId"), [t["versionId"] for t in targets], payload.get("mode"), envelope.get("expectedRevision"))
    return c.action_result("applied", revision=out["collection"]["revision"], result=out, warnings=out["warnings"])


def undo_action(ctx, envelope, targets):
    payload = _payload(envelope, {"collectionId"})
    out = undo(ctx, payload.get("collectionId"), envelope.get("expectedRevision"))
    return c.action_result("applied", revision=out["collection"]["revision"], result=out, warnings=out["warnings"])
