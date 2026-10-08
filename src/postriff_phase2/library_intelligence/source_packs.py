"""Task source packs: the bounded, explained set of Library sources one draft may use (engineering spec §5 TaskContext /
SourcePack, §10; implementation plan T08; PRD R12, D2; acceptance A049–A051).

A pack keeps two reference sets apart and never mixes them:
- evidence: Library items, passages or moments whose facts may support the draft. Recommendations come only from the
  shared search over the task's explicit scope with purpose `draft_evidence` (approved facts the source policy lets a
  draft use); a person's own selections are kept too, marked `needs_review` until their facts are reviewed in Ideas.
- style: approved voice spans from voice.style_exemplars (persona, brand and language scoped). Style text is never
  evidence and never becomes an Ideas source.

Ranking is an order with reasons, never a score: task relevance (how many of the goal's words a passage matches, fused by
rank across the searches), then penalties for a format that does not fit the channels, an older version and recent
reuse; at most one passage per item. Rights are a constraint: prohibited or withdrawn sources are left out, and unknown or
unapproved rights become warnings, never "cleared". Missing inputs are named as specific gaps. A pack never holds more
than MAX_EVIDENCE evidence refs and needs an explicit scope, so the whole Library is never attached to a prompt.

Attaching hands the refs to the existing Ideas/Drafts path in one state change: evidence enters Ideas as reviewable
sources (an item already imported keeps its reviewed source; anything else is imported as an excerpt with no approved
facts), the draft records `librarySources` (refs, purposes, rationale, gaps, rights warnings, returnTo), and the result
carries the composer fields the existing writer takes (sourceIds, voiceMode, voiceSourceIds). Every ref is re-authorized
first (policy.authorize_source, then policy.recheck); anything that narrowed since the pack's snapshot blocks the attach
and is reported as a conflict.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from postriff_alpha.domain import AlphaError

from .. import source_policy
from . import contracts as c
from . import policy, relations, textnorm, versions, voice
from . import segments as seg

MAX_EVIDENCE = 20          # evidence refs in one pack, selections and recommendations together
MAX_RECOMMENDED = 8        # recommended evidence refs added by search
MAX_STYLE = 6              # voice examples per polarity
MAX_QUERIES = 5            # lexical searches derived from the goal (each matches all of its words)
QUERY_LIMIT = 20           # hits per search
EXCERPT_CHARS = 19000      # same bound as library_assets.as_source
RETURN_MAX_CHARS = 4000
RECENT_DAYS = 30
REUSE_THRESHOLD = 2        # uses in RECENT_DAYS before an item yields to fresher material
EXCERPT_KINDS = ("text", "page", "slide", "sheet", "transcript", "ocr", "note")
VISUAL_CHANNELS = frozenset({"instagram", "tiktok", "pinterest", "youtube", "xiaohongshu", "pixelfed", "snapchat", "douyin", "kuaishou", "bilibili"})
STOP = seg.ENGLISH | frozenset("post posts write draft drafts announce announcing share sharing about make create help want need please using use new "
                               "article caption content tell let get give some any more most".split())
EVENT_WORDS = ("recital", "concert", "gig", "show", "workshop", "masterclass", "launch", "event", "performance", "festival", "exhibition", "talk",
               "webinar", "演奏會", "音樂會", "演出", "活動", "講座", "工作坊", "展覽")
PRICE_WORDS = ("ticket", "tickets", "price", "prices", "pricing", "booking", "fee", "fees", "門票", "票價", "收費")
DATE = re.compile(r"(?i)\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|"
                  r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b|\b\d{4}-\d{2}-\d{2}\b|"
                  r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\d{1,2}\s*月\s*\d{1,2}\s*[日號号]|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|星期[一二三四五六日天]")
VENUE = re.compile(r"(?i)\b(?:hall|venue|theatre|theater|studio|church|cathedral|centre|center|auditorium|arena|club|gallery|park|room)\b|"
                   r"大會堂|音樂廳|劇院|地點|場地|會場")
PRICE = re.compile(r"(?i)(?:hk\$|us\$|\$|£|€|¥)\s*\d|\b\d+(?:\.\d+)?\s*(?:hkd|usd|gbp|eur|rmb|cny|twd|dollars?)\b|\bfree\b|免費|\d+\s*元")
TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,60}$")
DRAFT_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
RETURN_KEYS = ("query", "scope", "filters", "sort", "density", "selection", "anchor", "view")

PACK_COLS = ("id::text,revision,status,task_context,evidence_refs,style_refs,rationale,gaps,rights_warnings,grant_revision,draft_id,created_by::text,"
             "extract(epoch from created_at),extract(epoch from updated_at)")
PACK_INSERT = ("/*lis:pack.insert*/ INSERT INTO public.pr_library_source_packs(id,workspace_id,revision,task_context,evidence_refs,style_refs,rationale,"
               "gaps,rights_warnings,grant_revision,status,created_by) VALUES(%s,%s,1,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,'draft',%s)")
PACK_GET = f"/*lis:pack.get*/ SELECT {PACK_COLS} FROM public.pr_library_source_packs WHERE workspace_id=%s AND id=%s"
PACK_LOCK = f"/*lis:pack.lock*/ SELECT {PACK_COLS} FROM public.pr_library_source_packs WHERE workspace_id=%s AND id=%s FOR UPDATE"
PACK_ATTACH = ("/*lis:pack.attach*/ UPDATE public.pr_library_source_packs SET status='attached',draft_id=%s,task_context=task_context||%s::jsonb,"
               "revision=revision+1,updated_at=now() WHERE workspace_id=%s AND id=%s AND revision=%s AND status='draft' RETURNING revision")
USAGE_RECENT = ("/*lis:usage.recent*/ SELECT asset_key,count(*) FROM public.pr_library_usage_events WHERE workspace_id=%s AND asset_key=ANY(%s) "
                "AND at>now()-make_interval(days=>%s) GROUP BY asset_key")
SEGMENT_GET = ("/*lis:segment.get*/ SELECT id,kind,text,locator,language,speaker_label,origin,(superseded_at IS NOT NULL) "
               "FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s AND id=%s")


def _fail(message: str, status: int, code: str):
    raise AlphaError(message, status, code=code)


# --- inputs ----------------------------------------------------------------------------------------------------------
def task_context(value) -> dict:
    """TaskContext with an explicit scope: a pack never defaults to the whole Library."""
    if not isinstance(value, dict):
        c.fail("Describe the task for this source pack.")
    if value.get("scope") is None:
        _fail("Choose where to look: the whole Library, a collection or selected items.", 422, "library_pack_scope_required")
    return c.task_context(value)


def _no_links(value, depth=0):
    if depth > 6:
        _fail("The Library state to return to is nested too deeply.", 400, "library_return_invalid")
    if isinstance(value, dict):
        for item in value.values():
            _no_links(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _no_links(item, depth + 1)
    elif isinstance(value, str) and c.UNSAFE.search(value):
        _fail("The Library state to return to can't contain links, markup or query text.", 400, "library_return_invalid")


def return_to(value) -> dict | None:
    """Opaque Library state (query, scope, filters, sort, density, selection, anchor, view) carried to the draft and back.
    Validated, bounded and link-free; never trusted for identity or permission."""
    if value is None:
        return None
    if not isinstance(value, dict) or not set(value) <= set(RETURN_KEYS):
        _fail("The Library state to return to has unexpected fields.", 400, "library_return_invalid")
    if len(json.dumps(value, ensure_ascii=False, default=str)) > RETURN_MAX_CHARS:
        _fail("The Library state to return to is too large.", 400, "library_return_invalid")
    _no_links(value)
    out: dict = {}
    if "query" in value:
        if not isinstance(value["query"], str) or len(value["query"]) > c.MAX_QUERY or "\x00" in value["query"]:
            _fail("The saved search is too long.", 400, "library_return_invalid")
        out["query"] = value["query"]
    if "scope" in value:
        out["scope"] = c.scope(value["scope"])
    if "filters" in value:
        out["filters"] = c.filters(value["filters"])
    for name in ("sort", "density", "view"):
        if name in value:
            if not isinstance(value[name], str) or not TOKEN.fullmatch(value[name]):
                _fail(f"The saved {name} is invalid.", 400, "library_return_invalid")
            out[name] = value[name]
    if "selection" in value:
        chosen = value["selection"]
        if not isinstance(chosen, list) or len(chosen) > c.MAX_SELECTION:
            _fail(f"Keep at most {c.MAX_SELECTION} selected items.", 400, "library_return_invalid")
        keys = [str(k).replace("-", "").lower() if isinstance(k, str) else "" for k in chosen]
        if any(not c.KEY.fullmatch(k) for k in keys):
            _fail("The saved selection is invalid.", 400, "library_return_invalid")
        out["selection"] = list(dict.fromkeys(keys))
    if "anchor" in value:
        anchor = value["anchor"]
        if not isinstance(anchor, str) or not TOKEN.fullmatch(anchor):
            _fail("The saved position is invalid.", 400, "library_return_invalid")
        out["anchor"] = anchor.replace("-", "").lower() if c.KEY.fullmatch(anchor.replace("-", "").lower()) else anchor
    return out


# --- evidence ---------------------------------------------------------------------------------------------------------
def _rights(ctx, version: dict) -> str:
    """approved_public | needs_review | internal | unknown, or 'excluded' when the source may not be used at all."""
    source = policy.ideas_source(ctx, version)
    if source is None:
        return "unknown"
    if not source.get("active") or source.get("sourcePolicy") == "prohibited":
        return "excluded"
    name = source.get("sourcePolicy")
    if name == "public_quote" or (name == "rewrite_approval" and source_policy.use_approved(source)):
        return "approved_public"
    if name == "internal_reference":
        return "internal"
    return "needs_review"


def _current(ctx, version: dict) -> bool:
    if version.get("legacy"):
        return True
    try:
        return versions.current(ctx, version["assetId"])["versionId"] == version["versionId"]
    except AlphaError:
        return True


def _segment(ctx, version_key: str, segment_id: str):
    ctx.cur.execute(SEGMENT_GET, (ctx.workspace_id, version_key, uuid.UUID(hex=c.asset_key(segment_id))))
    row = ctx.cur.fetchone()
    if not row:
        return None
    sid, kind, text, loc, language, speaker, origin, superseded = row
    return {"id": (sid if isinstance(sid, uuid.UUID) else uuid.UUID(str(sid))).hex, "kind": kind, "text": text,
            "locator": loc if isinstance(loc, dict) or loc is None else json.loads(loc), "superseded": bool(superseded)}


def _entry(ctx, version: dict, *, selection: str, why: list, segment_id=None, locator=None) -> tuple[dict, object]:
    decision = policy.authorize_source(ctx, version, "draft_evidence")
    entry = {"purpose": "evidence", "selection": selection, "assetRef": versions.ref(version), "title": version["title"], "kind": version["kind"],
             "locatorLabel": c.locator_label(locator) if locator else ("passage" if segment_id else "whole item"),
             "review": "approved" if decision.allowed else "needs_review", "reviewReason": None if decision.allowed else decision.reason,
             "rights": _rights(ctx, version), "current": _current(ctx, version), "why": list(why),
             "snapshot": {"grantRevision": decision.grant_revision, "sha256": version["sha256"], "versionNo": version["versionNo"],
                          "evidenceAllowed": decision.allowed, "reason": decision.reason}}
    if segment_id:
        entry["segmentId"] = segment_id
    if locator:
        entry["locator"] = locator
    if decision.allowed and decision.candidate_only:
        entry["why"].append("Facts approved; public use still needs approval.")
    elif decision.allowed:
        entry["why"].append("Facts approved for drafts.")
    if not entry["current"]:
        entry["why"].append("A newer version of this item exists.")
    return entry, decision


def _selected(ctx, raw) -> tuple[dict, object, dict]:
    """A person's own selection: browsable in this workspace, at an exact passage or moment when one is named."""
    ref = c.source_ref(raw)
    version = versions.resolve(ctx, ref["assetRef"])
    policy.require(policy.authorize_source(ctx, version, "browse"))
    segment_id, locator = ref.get("segmentId"), ref.get("locator")
    if segment_id:
        found = _segment(ctx, version["versionId"], segment_id)
        if found is None:
            _fail("This passage is unavailable.", 404, "library_unavailable")
        if found["superseded"]:
            _fail("This passage was corrected. Select the current text.", 409, "library_segment_changed")
        locator = locator or found["locator"]
    if locator:
        locator = c.locator(locator, **seg.bounds(ctx.cur, ctx.workspace_id, version))
    entry, decision = _entry(ctx, version, selection="user", why=["You selected this."], segment_id=segment_id, locator=locator)
    return entry, decision, version


# --- recommendation ---------------------------------------------------------------------------------------------------
def _queries(task: dict) -> list[str]:
    """Short lexical queries from the goal (then the audience): each search matches all its words, so one word or CJK
    bigram per query keeps recall honest and bounded."""
    text = task["userGoal"] + " " + (task.get("audience") or "")
    out = []
    for term in textnorm.query_terms(text):
        if textnorm.CJK.match(term):
            if len(term) >= 2:
                out.append(term)
            continue
        cleaned = re.sub(r"[^0-9a-zà-ɏ']", "", term)
        if len(cleaned) >= 3 and cleaned not in STOP and cleaned.strip("'") not in STOP:
            out.append(cleaned)
    return list(dict.fromkeys(out))[:MAX_QUERIES]


def _recent_uses(ctx, asset_keys: list) -> dict:
    if not asset_keys:
        return {}
    ctx.cur.execute(USAGE_RECENT, (ctx.workspace_id, sorted(set(asset_keys)), RECENT_DAYS))
    return {k: int(n) for k, n in ctx.cur.fetchall()}


def _fits(kind: str, channels: list) -> bool:
    if not channels:
        return True
    visual = any(ch.lower() in VISUAL_CHANNELS for ch in channels)
    return kind in ("image", "video") if visual else kind in ("document", "audio", "file", "video")


def _recommend(ctx, task: dict, exclude: set, room: int, warnings: list) -> tuple[list, list]:
    """Search the explicit scope for approved evidence, fuse by rank, then order with reasons."""
    from . import search
    queries = _queries(task)
    if not queries or room <= 0:
        return [], queries
    hits, lists = {}, []
    for query in queries:
        try:
            result = search.search_library(ctx, {"query": query, "scope": task["scope"], "purpose": "draft_evidence", "modes": ["lexical"],
                                                 "limit": QUERY_LIMIT})
        except AlphaError as error:
            if error.code == "library_retrieval_disabled":
                warnings.append("Library search is off here, so only the items you selected were considered.")
                return [], queries
            raise
        keys = []
        for hit in result.get("hits") or []:
            key = hit["assetRef"]["versionId"]
            keys.append(key)
            hits.setdefault(key, {"hit": hit, "terms": []})["terms"].append(query)
        lists.append(keys)
        warnings += [w for w in (result.get("warnings") or [])[:2] if w not in warnings]
    if not hits:
        return [], queries
    from .search import rrf
    relevance = rrf(lists)
    loaded = versions.load(ctx, list(hits))
    uses = _recent_uses(ctx, [v["assetId"] for v in loaded.values()])
    channels = task.get("channels") or []
    rank = {k: i for i, k in enumerate(relevance)}

    def order(key):
        version = loaded.get(key)
        penalty = 0 if version is None or _fits(version["kind"], channels) else 1
        penalty += 1 if version is not None and uses.get(version["assetId"], 0) >= REUSE_THRESHOLD else 0
        return (-len(hits[key]["terms"]), penalty, rank[key])

    out, seen_assets = [], set()
    for key in sorted(relevance, key=order):
        version = loaded.get(key)
        if version is None or key in exclude or version["assetId"] in seen_assets:
            continue
        seen_assets.add(version["assetId"])
        hit, used = hits[key]["hit"], uses.get(version["assetId"], 0)
        why = ["Matches: " + ", ".join(hits[key]["terms"]) + "."]
        if channels:
            why.append(("Fits " if _fits(version["kind"], channels) else "Less suited to ") + ", ".join(channels) + ".")
        why.append(f"Used {used} time{'s' if used != 1 else ''} in the last {RECENT_DAYS} days." if used else f"Not used in the last {RECENT_DAYS} days.")
        entry, decision = _entry(ctx, version, selection="recommended", why=why, segment_id=hit.get("segmentId"), locator=hit.get("locator"))
        if entry["rights"] == "excluded" or not decision.allowed:
            continue  # the search already applied the policy; a decision that changed since is simply left out
        out.append((entry, decision, version))
        if len(out) >= room:
            break
    return out, queries


def _style_language(task: dict) -> str | None:
    locale = task.get("locale")
    if isinstance(locale, str) and voice.LANGUAGE.fullmatch(locale):
        return locale
    return seg.detect_language(task["userGoal"])["language"]


def _style_entry(item: dict, polarity: str, bindings: dict, grant_revision: int) -> dict:
    binding = bindings.get(item.get("voiceSourceId")) or {}
    return {"purpose": "style", "polarity": polarity, "sampleId": item["sampleId"], "voiceSourceId": item.get("voiceSourceId"),
            "assetRef": item["assetRef"], "locator": item["locator"], "locatorLabel": item["locatorLabel"], "language": item["language"],
            "snapshot": {"grantRevision": grant_revision, "voiceAllowed": True, "sampleRevision": binding.get("revision"), "contentHash": binding.get("contentHash")}}


def _style(ctx, result: dict) -> list:
    revision = policy.revisions(ctx)["grantRevision"]
    bindings = {b["id"]: b for b in result.get("bindings") or []}
    return [_style_entry(x, polarity, bindings, revision) for polarity in ("positive", "negative") for x in result.get(polarity) or []]


# --- gaps and warnings -------------------------------------------------------------------------------------------------
def _approved_facts(ctx, entries: list) -> list[str]:
    out = []
    for entry, _, version in entries:
        if entry["review"] != "approved":
            continue
        source = policy.ideas_source(ctx, version) or {}
        out += [f.get("text") or "" for f in source.get("facts") or [] if f.get("approved")]
    return out


def _first_word(text: str, words) -> str | None:
    lowered = text.lower()
    found = [(lowered.find(w), w) for w in words if lowered.find(w) >= 0]
    return min(found)[1] if found else None


def _gaps(ctx, task: dict, entries: list, style: list, *, style_requested: bool, persona: str, language) -> list:
    gaps = []
    facts = _approved_facts(ctx, entries)
    goal = task["userGoal"]
    if not entries:
        gaps.append({"code": "no_evidence", "message": "Nothing in this scope matches the goal. Select items or widen the scope."})
    elif not any(e["review"] == "approved" for e, _, _ in entries):
        gaps.append({"code": "no_approved_evidence", "message": "None of these items has approved facts yet. Review their facts before relying on them."})
    event = _first_word(goal, EVENT_WORDS)
    if event:
        if not any(DATE.search(f) for f in facts):
            gaps.append({"code": "missing_fact_date", "message": f"No approved fact gives the {event} date."})
        if not any(VENUE.search(f) for f in facts):
            gaps.append({"code": "missing_fact_venue", "message": f"No approved fact gives the {event} venue."})
    if _first_word(goal, PRICE_WORDS) and not any(PRICE.search(f) for f in facts):
        gaps.append({"code": "missing_fact_price", "message": "No approved fact gives ticket prices."})
    visual = next((ch for ch in task.get("channels") or [] if ch.lower() in VISUAL_CHANNELS), None)
    if visual and not any(e["kind"] in ("image", "video") and policy.authorize_source(ctx, v, "public_use").allowed for e, _, v in entries):
        gaps.append({"code": "missing_public_image", "message": f"No image approved for public use for {visual}."})
    for entry, _, _ in entries:
        if entry["selection"] == "user" and entry["review"] != "approved" and entry["kind"] not in ("image", "video"):
            gaps.append({"code": "evidence_needs_review", "assetRef": entry["assetRef"],
                         "message": f"“{entry['title'][:80]}” has no approved facts yet; they stay unapproved until you review them in Ideas."})
    if style_requested:
        if language is None:
            gaps.append({"code": "voice_language_unknown", "message": "Choose the draft's language to use your voice examples."})
        elif not any(s["polarity"] == "positive" for s in style):
            who = "your workspace voice" if persona == voice.DEFAULT_PERSONA else f"the persona “{persona[:40]}”"
            gaps.append({"code": "missing_voice_examples", "message": f"No approved voice examples for {who} in {language}."})
    return gaps


def _notes(entries: list) -> list:
    """Per-ref warnings: rights (never 'cleared') and currency. D's version replacement appends to the same list."""
    notes = []
    for entry, _, _ in entries:
        title = entry["title"][:80]
        code = {"unknown": "rights_unknown", "needs_review": "public_use_not_approved", "internal": "internal_reference"}.get(entry["rights"])
        message = {"rights_unknown": f"Rights for “{title}” are unknown. Confirm you may use it before publishing.",
                   "public_use_not_approved": f"Public use of “{title}” hasn't been approved.",
                   "internal_reference": f"“{title}” is an internal reference and stays out of public drafts."}.get(code)
        if code:
            notes.append({"code": code, "assetRef": entry["assetRef"], "message": message})
        if not entry["current"]:
            notes.append({"code": "older_version", "assetRef": entry["assetRef"],
                          "message": f"“{title}” cites an older version. Review the newer version before relying on it."})
    return notes


# --- build and persist ----------------------------------------------------------------------------------------------------
def _scope_label(scope: dict) -> str:
    if scope["kind"] == "workspace":
        return "your whole Library"
    if scope["kind"] == "collection":
        return "the chosen collection"
    return f"the {len(scope['assetRefs'])} selected item{'s' if len(scope['assetRefs']) != 1 else ''}"


def _build(ctx, raw_task, explicit, *, recommend: bool, style_ids=None, return_state=None) -> dict:
    ctx.require("edit")
    seg.writable(ctx)
    task = task_context(raw_task)
    back = return_to(return_state)
    explicit = list(explicit or [])
    if len(explicit) > MAX_EVIDENCE:
        _fail(f"Choose at most {MAX_EVIDENCE} sources for one pack.", 422, "library_pack_too_many")
    warnings, entries, rejected = [], [], []
    for raw in explicit:
        entry, decision, version = _selected(ctx, raw)
        if entry["rights"] == "excluded":
            rejected.append({"code": "excluded_by_policy", "assetRef": entry["assetRef"],
                             "message": f"“{entry['title'][:80]}” can't be used: its source was withdrawn or its use policy doesn't allow it."})
            continue
        if any(e["assetRef"]["versionId"] == entry["assetRef"]["versionId"] and e.get("segmentId") == entry.get("segmentId")
               and e.get("locator") == entry.get("locator") for e, _, _ in entries):
            continue
        entries.append((entry, decision, version))
    queries = []
    if recommend:
        found, queries = _recommend(ctx, task, {e["assetRef"]["versionId"] for e, _, _ in entries}, min(MAX_RECOMMENDED, MAX_EVIDENCE - len(entries)),
                                    warnings)
        entries += found
    persona = task.get("personaId") or voice.DEFAULT_PERSONA
    language = _style_language(task)
    style = []
    if style_ids:
        picked = voice.exemplars_by_ids(ctx, list(style_ids))
        if picked["excluded"]:
            _fail("A chosen voice example is unavailable or no longer approved.", 409, "library_pack_voice_unavailable")
        style = _style(ctx, picked)
    elif recommend and language is not None:
        found_style = voice.style_exemplars(ctx, persona, language, MAX_STYLE)
        if not found_style["enabled"]:
            warnings += found_style.get("warnings") or []
        style = _style(ctx, found_style)
    # Purpose decisions are rechecked before the snapshot is stored (a revoke that landed meanwhile wins).
    if entries:
        fresh = policy.recheck(ctx, [d for _, d, _ in entries])
        for (entry, before, _), after in zip(entries, fresh):
            if before.allowed and not after.allowed:
                entry.update(review="needs_review", reviewReason=after.reason)
                entry["snapshot"].update(evidenceAllowed=False, reason=after.reason, grantRevision=after.grant_revision)
    gaps = _gaps(ctx, task, entries, style, style_requested=recommend and not style_ids, persona=persona, language=language)
    notes = _notes(entries) + rejected
    rationale = [{"code": "scope", "message": f"Looked only in {_scope_label(task['scope'])}."},
                 {"code": "queries", "message": ("Searched approved evidence for: " + ", ".join(queries) + ".") if queries else
                  "Used only the sources you chose; nothing was searched."},
                 {"code": "ranking", "message": "Ordered by match to the goal, then fit for the channels, current versions and less recent use; "
                                                "at most one passage per item."},
                 {"code": "cap", "message": f"At most {MAX_EVIDENCE} evidence sources; the rest of the Library is never attached."},
                 {"code": "style", "message": f"{sum(1 for s in style if s['polarity'] == 'positive')} approved voice examples and "
                                              f"{sum(1 for s in style if s['polarity'] == 'negative')} don't-write-like-this examples, kept apart from evidence."}]
    grant_revision = policy.revisions(ctx)["grantRevision"]
    stored_task = {**task, "returnTo": back, "style": {"personaId": persona, "language": language}, "queries": queries}
    evidence = [e for e, _, _ in entries]
    pack_id = uuid.uuid4()
    ctx.cur.execute(PACK_INSERT, (pack_id, ctx.workspace_id, json.dumps(stored_task), json.dumps(evidence), json.dumps(style), json.dumps(rationale),
                                  json.dumps(gaps), json.dumps(notes), grant_revision, ctx.actor))
    key = pack_id.hex
    by_version = {v["versionId"]: v for _, _, v in entries}
    style_versions = versions.load(ctx, [s["assetRef"]["versionId"] for s in style])
    for item in evidence + style:
        version = by_version.get(item["assetRef"]["versionId"]) or style_versions.get(item["assetRef"]["versionId"])
        if version is None:
            continue
        relations.record_used_in(ctx, version, "source_pack", key, evidence={"packRevision": 1})
        _usage(ctx, version, "source_pack", f"source_pack:{key}:{version['versionId']}:{item['purpose']}", {"packId": key, "purpose": item["purpose"]},
               segment_id=item.get("segmentId"))
    _audit(ctx, "library.source_pack_created", key, {"evidence": len(evidence), "style": len(style), "scope": task["scope"]["kind"],
                                                     "recommended": sum(1 for e in evidence if e["selection"] == "recommended")})
    return {"contractVersion": c.CONTRACT_VERSION, "packId": key, "revision": 1, "status": "draft", "taskContext": task, "returnTo": back,
            "evidenceRefs": evidence, "styleRefs": style, "rationale": rationale, "gaps": gaps, "rightsWarnings": notes, "grantRevision": grant_revision,
            "draftId": None, "style": stored_task["style"], "limits": {"maxEvidence": MAX_EVIDENCE, "maxRecommended": MAX_RECOMMENDED},
            "warnings": list(dict.fromkeys(warnings))}


def recommend_sources(ctx, task, *, return_to=None) -> dict:
    """recommend_sources(ctx, task: TaskContext) -> SourcePack (implementation plan T08). Persisted at revision 1."""
    raw = task if isinstance(task, dict) else {}
    return _build(ctx, task, raw.get("selectedSourceRefs") or [], recommend=True, return_state=return_to)


def create_pack(ctx, task, evidence, style_sample_ids, *, return_to=None) -> dict:
    """A pack from explicitly chosen evidence and voice examples only; nothing is searched."""
    return _build(ctx, task, evidence, recommend=False, style_ids=list(style_sample_ids or []), return_state=return_to)


def _usage(ctx, version: dict, event_type: str, dedup: str, source: dict, *, draft_id=None, segment_id=None):
    from . import usage
    usage.record_usage(ctx.cur, ctx.workspace_id, version["assetId"], version["versionId"], event_type, draft_id=draft_id, dedup_key=dedup[:300],
                       source=source, segment_id=segment_id)


def _audit(ctx, kind: str, subject: str, meta: dict):
    from ..hosted import audit
    audit(ctx.cur, ctx.workspace_id, ctx.actor, kind, subject, meta)


# --- reading a pack -------------------------------------------------------------------------------------------------------
def _json(value):
    return value if isinstance(value, (dict, list)) or value is None else json.loads(value)


def _load(ctx, pack_id, *, lock: bool) -> dict | None:
    key = c.asset_key(pack_id)
    ctx.cur.execute(PACK_LOCK if lock else PACK_GET, (ctx.workspace_id, uuid.UUID(hex=key)))
    row = ctx.cur.fetchone()
    if not row:
        return None
    names = ("id", "revision", "status", "task_context", "evidence_refs", "style_refs", "rationale", "gaps", "rights_warnings", "grant_revision",
             "draft_id", "created_by", "created_at", "updated_at")
    out = dict(zip(names, row))
    for name in ("task_context", "evidence_refs", "style_refs", "rationale", "gaps", "rights_warnings"):
        out[name] = _json(out[name])
    out["id"] = c.asset_key(out["id"])
    return out


def _contract(row: dict) -> dict:
    task = dict(row["task_context"] or {})
    back, attachment, style_meta = task.pop("returnTo", None), task.pop("attachment", None), task.pop("style", None)
    task.pop("queries", None)
    return {"contractVersion": c.CONTRACT_VERSION, "packId": row["id"], "revision": int(row["revision"]), "status": row["status"], "taskContext": task,
            "returnTo": back, "evidenceRefs": row["evidence_refs"] or [], "styleRefs": row["style_refs"] or [], "rationale": row["rationale"] or [],
            "gaps": row["gaps"] or [], "rightsWarnings": row["rights_warnings"] or [], "grantRevision": int(row["grant_revision"]),
            "draftId": row["draft_id"], "style": style_meta, "attachment": attachment,
            "limits": {"maxEvidence": MAX_EVIDENCE, "maxRecommended": MAX_RECOMMENDED}}


def _change(purpose: str, ref, change: str, **extra) -> dict:
    return {"purpose": purpose, "assetRef": ref if isinstance(ref, dict) else {}, "change": change, **extra}


def _narrowed(purpose, ref, decision) -> dict:
    return _change(purpose, ref, "permission_narrowed", before={"allowed": True},
                   after={"allowed": False, "reason": decision.reason, "message": policy.message(decision.reason)})


def _revalidate(ctx, row: dict, *, lock: bool) -> dict:
    """Re-resolve and re-authorize every ref against the pack's snapshot (policy.authorize_source, and with `lock` also
    policy.recheck after the caller took the workspace row lock). Only narrowing is a change; a newly granted use is not."""
    changes, evidence, style, checked = [], [], [], []
    for raw in row["evidence_refs"] or []:
        entry = raw if isinstance(raw, dict) else {}
        ref = entry.get("assetRef") if isinstance(entry.get("assetRef"), dict) else entry
        try:
            version = versions.resolve(ctx, ref)
        except AlphaError as error:
            changes.append(_change("evidence", ref, "version_changed" if error.code == "library_version_mismatch" else "unavailable"))
            continue
        decision = policy.authorize_source(ctx, version, "draft_evidence")
        if (entry.get("snapshot") or {}).get("evidenceAllowed") and not decision.allowed:
            changes.append(_narrowed("evidence", versions.ref(version), decision))
        if entry.get("segmentId"):
            found = _segment(ctx, version["versionId"], entry["segmentId"])
            if found is None or found["superseded"]:
                changes.append(_change("evidence", versions.ref(version), "passage_changed"))
        evidence.append((entry, version, decision))
        checked.append(("evidence", entry, version, decision))
    for raw in row["style_refs"] or []:
        entry = raw if isinstance(raw, dict) else {}
        ref = entry.get("assetRef") if isinstance(entry.get("assetRef"), dict) else entry
        try:
            version = versions.resolve(ctx, ref)
        except AlphaError as error:
            changes.append(_change("style", ref, "version_changed" if error.code == "library_version_mismatch" else "unavailable"))
            continue
        decision = policy.authorize_source(ctx, version, "voice")
        if not decision.allowed:
            changes.append(_narrowed("style", versions.ref(version), decision))
        elif not entry.get("sampleId"):
            changes.append(_change("style", versions.ref(version), "voice_example_missing"))
        else:
            picked = voice.exemplars_by_ids(ctx, [entry["sampleId"]])
            if picked["excluded"]:
                changes.append(_change("style", versions.ref(version), "voice_example_withdrawn", after={"reason": picked["excluded"][0]["reason"]}))
        style.append((entry, version, decision))
        checked.append(("style", entry, version, decision))
    if lock and checked:
        fresh = policy.recheck(ctx, [d for *_, d in checked])
        for (purpose, entry, version, before), after in zip(checked, fresh):
            if before.allowed and not after.allowed and not any(ch["purpose"] == purpose and ch["assetRef"] == versions.ref(version) for ch in changes):
                changes.append(_narrowed(purpose, versions.ref(version), after))
    return {"changes": changes, "evidence": evidence, "style": style}


def get_pack(ctx, pack_id) -> dict:
    ctx.require("read")
    row = _load(ctx, pack_id, lock=False)
    if row is None:
        _fail("This source pack is unavailable.", 404, "library_unavailable")
    pack = _contract(row)
    check = _revalidate(ctx, row, lock=False)
    back, removed = pack["returnTo"], 0
    if back and back.get("selection"):
        accessible = versions.accessible_keys(ctx)
        kept = [k for k in back["selection"] if k in accessible]
        removed = len(back["selection"]) - len(kept)
        back = {**back, "selection": kept}
        if c.KEY.fullmatch(str(back.get("anchor") or "")) and back["anchor"] not in accessible:
            back.pop("anchor")
    pack.update(returnTo=back, returnToRemoved=removed,
                validity={"attachable": pack["status"] == "draft" and not check["changes"], "changes": check["changes"]})
    return pack


# --- attaching to a draft ---------------------------------------------------------------------------------------------------
def _active_segments(ctx, version: dict) -> list:
    out, cursor = [], None
    for _ in range(seg.MAX_SEGMENTS // seg.MAX_PAGE_LIMIT):
        page = seg.list_segments(ctx, version, cursor=cursor, limit=seg.MAX_PAGE_LIMIT)
        out += [s for s in page["segments"] if s["kind"] in EXCERPT_KINDS]
        cursor = page["nextCursor"]
        if not cursor:
            break
    return out


def _overlaps(a: dict | None, b: dict) -> bool:
    if not a or a.get("kind") != b.get("kind"):
        return False
    if a["kind"] == "time":
        return a["startMs"] < b["endMs"] and a["endMs"] > b["startMs"]
    if a["kind"] == "text":
        return a["start"] < b["end"] and a["end"] > b["start"]
    if a["kind"] == "page":
        return a["page"] == b["page"]
    if a["kind"] == "slide":
        return a["slide"] == b["slide"]
    if a["kind"] == "sheet":
        return a["sheetName"] == b["sheetName"]
    return False


def _excerpt(ctx, version: dict, entry: dict) -> tuple[str, bool]:
    """The cited text: the exact passage, the passages at the locator, or the whole extracted text (as_source bound)."""
    if entry.get("segmentId"):
        found = _segment(ctx, version["versionId"], entry["segmentId"])
        parts = [found["text"]] if found and not found["superseded"] else []
    else:
        segments = _active_segments(ctx, version)
        if entry.get("locator"):
            segments = [s for s in segments if _overlaps(s.get("locator"), entry["locator"])]
        parts = [s["text"] for s in segments]
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    return text[:EXCERPT_CHARS], len(text) > EXCERPT_CHARS


def _plan(ctx, evidence: list, pack_key: str) -> tuple[list, list]:
    plan, warnings = [], []
    for entry, version, _ in evidence:
        item = {"entry": entry, "version": version, "reuse": None, "text": None}
        source = policy.ideas_source(ctx, version)
        if source is not None and source.get("active"):
            item["reuse"] = source["id"]   # keeps the facts already reviewed in Ideas
        else:
            text, clipped = _excerpt(ctx, version, entry)
            if not text:
                warnings.append(f"“{version['title'][:80]}” has no extracted text yet, so it wasn't added to Ideas.")
            else:
                label = entry.get("locatorLabel") or "whole item"
                item.update(text=text, title=f"{version['title']} · {label}"[:200],
                            origin={"kind": "library", "assetId": version["versionId"], "lineageId": version["assetId"], "sha256": version["sha256"],
                                    "locator": entry.get("locator") or label, "segmentId": entry.get("segmentId"), "packId": pack_key, "clipped": clipped})
        plan.append(item)
    return plan, warnings


def _attach_state(state: dict, run, plan: list, style: list, draft_id: str, pack: dict, ctx) -> dict:
    """One state change through the hosted command router: Ideas sources via the domain `source` action (facts are never
    approved here) and the draft's librarySources record. The draft's text and sourceIds stay exactly as written."""
    for item in plan:
        sid = None
        if item["reuse"]:
            found = next((s for s in state.get("sources", []) if s.get("id") == item["reuse"] and s.get("active")), None)
            sid = found["id"] if found else None
        if sid is None and item["text"]:
            body = item["text"].strip()
            fingerprint = hashlib.sha256(("text" + body).encode()).hexdigest()
            existing = next((s for s in state.get("sources", []) if s.get("fingerprint") == fingerprint and s.get("active")), None)
            if existing is not None:
                sid = existing["id"]
            else:
                run(state, "source", {"kind": "text", "title": item["title"], "text": body})
                created = state["sources"][-1]
                created.update(origin=item["origin"], sourcePolicy="rewrite_approval", egressConsent=["local"])
                sid = created["id"]
        item["ideasSourceId"] = sid
    variant = next((v for v in state.get("variants", []) if v.get("id") == draft_id), None)
    if variant is None:
        _fail("This draft is unavailable.", 404, "library_draft_unavailable")
    samples = {s.get("id"): s for s in state.get("sources", []) if s.get("kind") == "voice_sample"}
    evidence_out = [{"purpose": "evidence", "assetRef": i["entry"]["assetRef"], "segmentId": i["entry"].get("segmentId"), "locator": i["entry"].get("locator"),
                     "locatorLabel": i["entry"].get("locatorLabel"), "title": i["entry"].get("title") or i["version"]["title"],
                     "ideasSourceId": i["ideasSourceId"], "review": i["entry"].get("review", "needs_review"), "rights": i["entry"].get("rights", "unknown")}
                    for i in plan]
    style_out = []
    for entry, version, _ in style:
        sample = samples.get(entry.get("voiceSourceId"))
        usable = (entry.get("polarity") == "positive" and sample is not None and sample.get("active") and sample.get("selected")
                  and "generation" in (sample.get("purposeGrants") or []))
        style_out.append({"purpose": "style", "polarity": entry.get("polarity"), "sampleId": entry.get("sampleId"), "voiceSourceId": entry.get("voiceSourceId"),
                          "assetRef": versions.ref(version), "locator": entry.get("locator"), "locatorLabel": entry.get("locatorLabel"),
                          "language": entry.get("language"), "usableByWriter": bool(usable)})
    previous = variant.get("librarySources")
    if isinstance(previous, dict) and previous.get("packId") != pack["packId"]:
        # An earlier pack's record is kept (bounded), never silently overwritten.
        variant["librarySourcesHistory"] = (list(variant.get("librarySourcesHistory") or []) + [previous])[-5:]
    variant["librarySources"] = {"packId": pack["packId"], "packRevision": pack["revision"] + 1, "attachedAt": ctx.now, "attachedBy": ctx.actor,
                                 "goal": pack["taskContext"].get("userGoal"), "evidence": evidence_out, "style": style_out, "rationale": pack["rationale"],
                                 "gaps": pack["gaps"], "rightsWarnings": pack["rightsWarnings"], "returnTo": pack["returnTo"]}
    return {"evidence": evidence_out, "style": style_out}


def attach_pack_to_draft(ctx, pack_id, draft_id, expected_revision) -> dict:
    """attach_pack_to_draft(ctx, pack_id, draft_id, expected_revision) -> result (implementation plan T08).

    `expected_revision` is the pack's revision (stale -> 409). Returns status 'applied', or 'conflict' with what changed
    when a permission, source decision, passage or version narrowed since the snapshot (nothing is written then)."""
    seg.writable(ctx)
    if not callable(getattr(ctx.service, "commands", None)):
        _fail("Drafts aren't available here.", 503, "library_drafts_unavailable")
    if not isinstance(draft_id, str) or not DRAFT_ID.fullmatch(draft_id):
        c.fail("Choose a draft.")
    row = _load(ctx, pack_id, lock=True)
    if row is None:
        _fail("This source pack is unavailable.", 404, "library_unavailable")
    pack = _contract(row)
    if pack["status"] == "superseded":
        _fail("This source pack was replaced. Make a new one.", 409, "library_pack_closed")
    if type(expected_revision) is not int or expected_revision != pack["revision"]:
        _fail("This source pack changed. Reload it before attaching.", 409, "library_pack_conflict")
    if pack["status"] == "attached":
        if pack["draftId"] == draft_id:
            attachment = pack["attachment"] or {}
            return {"status": "applied", "alreadyAttached": True, "packId": pack["packId"], "revision": pack["revision"], "draftId": draft_id,
                    "composer": attachment.get("composer"), "returnTo": pack["returnTo"], "gaps": pack["gaps"], "rightsWarnings": pack["rightsWarnings"],
                    "warnings": []}
        _fail("This source pack is already attached to another draft. Make a new pack for this one.", 409, "library_pack_attached")
    if not any(v.get("id") == draft_id for v in ctx.state.get("variants", [])):
        _fail("This draft is unavailable.", 404, "library_draft_unavailable")
    voice.hold_workspace(ctx)  # serialize with grant revokes before the final recheck (policy.recheck itself takes no lock)
    check = _revalidate(ctx, row, lock=True)
    if check["changes"] or pack["status"] == "revoked":
        changes = check["changes"] or [_change("pack", {}, "pack_revoked", message="A permission this pack relied on was withdrawn.")]
        return {"status": "conflict", "packId": pack["packId"], "revision": pack["revision"], "packStatus": pack["status"], "draftId": draft_id,
                "changes": changes, "grantRevision": {"snapshot": pack["grantRevision"], "current": policy.revisions(ctx)["grantRevision"]}}
    plan, warnings = _plan(ctx, check["evidence"], pack["packId"])
    changed = voice.mutate_state(ctx, lambda state, run: _attach_state(state, run, plan, check["style"], draft_id, pack, ctx))
    attached = changed["result"]
    usable = [s["voiceSourceId"] for s in attached["style"] if s["usableByWriter"]]
    composer = {"draftId": draft_id, "sourcePackId": pack["packId"], "sourceIds": sorted({i["ideasSourceId"] for i in plan if i.get("ideasSourceId")}),
                "voiceMode": "personalized" if usable else "neutral", "voiceSourceIds": usable}
    if any(s["polarity"] == "positive" and not s["usableByWriter"] for s in attached["style"]):
        warnings.append("Some voice examples aren't selected for Rafii's writer yet; select them in Voice settings to use them in drafts.")
    attachment = {"attachment": {"draftId": draft_id, "composer": composer, "at": ctx.now, "by": ctx.actor,
                                 "ideasSourceIds": {i["version"]["versionId"]: i.get("ideasSourceId") for i in plan}}}
    ctx.cur.execute(PACK_ATTACH, (draft_id, json.dumps(attachment), ctx.workspace_id, uuid.UUID(hex=pack["packId"]), pack["revision"]))
    saved = ctx.cur.fetchone()
    if not saved:
        _fail("This source pack changed. Reload it before attaching.", 409, "library_pack_conflict")
    revision = int(saved[0])
    for item in plan:
        version = item["version"]
        relations.record_used_in(ctx, version, "draft", draft_id, evidence={"packRevision": revision})
        if item.get("ideasSourceId"):
            relations.record_used_in(ctx, version, "idea", item["ideasSourceId"], evidence={"packRevision": revision})
        _usage(ctx, version, "draft_attached", f"draft_attached:{pack['packId']}:{draft_id}:{version['versionId']}:evidence",
               {"packId": pack["packId"], "purpose": "evidence"}, draft_id=draft_id, segment_id=item["entry"].get("segmentId"))
    for _, version, _ in check["style"]:
        relations.record_used_in(ctx, version, "draft", draft_id, evidence={"packRevision": revision})
        _usage(ctx, version, "draft_attached", f"draft_attached:{pack['packId']}:{draft_id}:{version['versionId']}:style",
               {"packId": pack["packId"], "purpose": "style"}, draft_id=draft_id)
    _audit(ctx, "library.source_pack_attached", pack["packId"], {"evidence": len(plan), "style": len(attached["style"]),
                                                                 "imported": sum(1 for i in plan if i.get("text") and i.get("ideasSourceId"))})
    return {"status": "applied", "alreadyAttached": False, "packId": pack["packId"], "revision": revision, "draftId": draft_id,
            "evidence": attached["evidence"], "style": attached["style"], "composer": composer, "returnTo": pack["returnTo"], "gaps": pack["gaps"],
            "rightsWarnings": pack["rightsWarnings"], "warnings": warnings}


# --- HTTP and actions ---------------------------------------------------------------------------------------------------------
def recommend_http(ctx, request):
    """POST .../source-packs — body is a TaskContext plus an optional returnTo."""
    body = dict(request.get("body") or {})
    back = body.pop("returnTo", None)
    return {**recommend_sources(ctx, body, return_to=back), "_status": 201}


def pack_http(ctx, request):
    """GET .../source-packs/{key} — the pack, whether it can still be attached, and the Library state to return to."""
    return get_pack(ctx, request["params"]["key"])


def select_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """sources.select (read-only): what each chosen item, passage or moment would contribute as evidence."""
    payload = envelope.get("payload") or {}
    if not set(payload) <= {"passages"}:
        c.fail("Send the chosen items and optional passages.")
    passages = payload.get("passages") or []
    if not isinstance(passages, list) or len(passages) > len(targets):
        c.fail("Send at most one passage per chosen item.")
    out = []
    for n, version in enumerate(targets):
        extra = passages[n] if n < len(passages) and isinstance(passages[n], dict) else {}
        raw = {"assetRef": versions.ref(version), **{k: extra[k] for k in ("segmentId", "locator") if extra.get(k) is not None}}
        entry, _, _ = _selected(ctx, raw)
        out.append(entry)
    return c.action_result("applied", result={"candidates": out, "limits": {"maxEvidence": MAX_EVIDENCE}})


def create_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """source_pack.create from explicitly chosen evidence (every one also sent as a target) and voice examples."""
    payload = envelope.get("payload") or {}
    if not set(payload) <= {"taskContext", "returnTo", "evidence", "styleSampleIds"}:
        c.fail("Send a task, the chosen evidence and optional voice examples.")
    raw_task = payload.get("taskContext")
    evidence = payload["evidence"] if "evidence" in payload else (raw_task or {}).get("selectedSourceRefs") or []
    if not isinstance(evidence, list):
        c.fail("Send the chosen evidence as a list.")
    declared = {t["versionId"] for t in targets}
    for raw in evidence:
        if c.source_ref(raw)["assetRef"]["versionId"] not in declared:
            c.fail("Send every chosen source as a target.")
    pack = create_pack(ctx, raw_task, evidence, payload.get("styleSampleIds") or [], return_to=payload.get("returnTo"))
    return c.action_result("applied", revision=pack["revision"], result=pack, warnings=pack.get("warnings", []))


def attach_action(ctx, envelope: dict, targets: list[dict]) -> dict:
    """source_pack.attach {packId, draftId}; expectedRevision is the pack's revision."""
    payload = envelope.get("payload") or {}
    if not set(payload) <= {"packId", "draftId"}:
        c.fail("Send the pack and the draft.")
    result = attach_pack_to_draft(ctx, payload.get("packId"), payload.get("draftId"), envelope.get("expectedRevision"))
    if result["status"] == "conflict":
        return c.action_result("conflict", result=result, warnings=["Permissions or sources changed since this pack was made. Review the changes."])
    return c.action_result("applied", revision=result["revision"], result=result, warnings=result.get("warnings", []))
