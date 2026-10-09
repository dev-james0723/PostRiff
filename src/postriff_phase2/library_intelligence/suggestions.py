"""Quiet, in-app Library suggestions (engineering spec §11; PRD R14, D6; UI spec §2 "Suggested for you"; T11).

`evaluate_suggestions(ctx, event)` turns one trigger into deduplicated rows in pr_library_suggestions:

    version_linked       a draft/pack/post cites a superseded version            -> outdated_source (one per recipient per link)
    capability_failed    a capability of an item failed                          -> failed_processing
    draft_changed        an active draft: withdrawn sources (critical), sources  -> source_integrity / missing_input /
                         without approved facts, a relevant unused item             unused_relevant
    collection_proposal  a reversible smart-collection proposal                  -> organization
    permission_revoked   critical warnings                                       -> permission
    source_integrity                                                             -> source_integrity
    sweep                the bounded periodic pass (evaluate_due) over all of the above

Noise limits: a durable dedup key per trigger/target/version (unique per recipient), debounce of bursts for proactive
triggers, and at most DAILY_CAP new noncritical suggestions per recipient per 24 h. Critical permission/source-integrity
warnings bypass the cap but are still deduplicated, and cannot be switched off. Dismiss suppresses that identity for
good; snooze defaults to 7 days (editable per category); a disabled category persists.

Delivery is in-app ONLY. This module never sends email, push or SMS, never creates schedules and never publishes;
pr_library_suggestion_prefs.external_opt_in is stored by the schema but nothing reads it here. Proactive triggers run
only with RAFII_LIBRARY_SUGGESTIONS_ENABLED; warnings that follow an explicit user action (a version link) and critical
warnings do not depend on that flag. Reasons are descriptive: they say what matched and what is affected, never that an
item caused an outcome.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, textnorm, versions

CATEGORIES = ("outdated_source", "unused_relevant", "missing_input", "failed_processing", "organization", "permission", "source_integrity")
CRITICAL = frozenset({"permission", "source_integrity"})
PRIORITY = {"permission": 0, "source_integrity": 0, "outdated_source": 1, "missing_input": 2, "failed_processing": 3, "unused_relevant": 4,
            "organization": 5}
DAILY_CAP = 3
CAP_WINDOW_SECONDS = 86400
DEBOUNCE_SECONDS = 120
SWEEP_SECONDS = 3600
SNOOZE_DEFAULT_DAYS = 7
EXPIRES_DAYS = 30
HISTORY_DAYS = 30
INBOX_LIMIT = 20
MAX_RECIPIENTS = 20
MAX_AFFECTED = 50
SWEEP_WORKSPACES = 5
SWEEP_FAILED = 20
SWEEP_STALE = 200
SWEEP_DRAFTS = 5
SWEEP_OPEN = 500
PROPOSAL_MIN_ITEMS = 3
SEARCH_TERMS = 3
SEARCH_LIMIT = 10
RRF_K = 60
RANKING_VERSION = "rrf-60-recency-kind-v1"
SYSTEM_ACTOR = "00000000-0000-0000-0000-000000000000"
EVENT_TYPES = ("version_linked", "capability_failed", "draft_changed", "collection_proposal", "permission_revoked", "source_integrity", "sweep")
PROACTIVE = frozenset({"capability_failed", "draft_changed", "collection_proposal", "sweep"})
ACTIONS = ("seen", "dismiss", "snooze", "apply", "disable_category", "enable_category", "preferences")
OPEN_STATES = ("new", "seen", "snoozed")
DEPENDENT_KINDS = ("draft", "post", "source_pack", "idea", "asset")
HIDDEN = ("deleting", "duplicate", "missing")
KEYLIKE = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
DELIVERY = {"channels": ["in_app"], "external": False,
            "note": "Suggestions stay inside Rafii. Nothing is sent by email, push or SMS, and nothing is scheduled or published."}
CAPABILITY_NOUNS = {"preview": "a preview", "extract": "text extraction", "transcribe": "transcription", "visual": "visual analysis",
                    "embed_text": "text indexing", "embed_visual": "visual indexing", "understand": "the understanding card"}
STOP = frozenset("""a an and are as at be been but by can for from has have here how i if in into is it its just more my new no not now of on or our out
so than that the their them then there these they this those to too up us was we were what when where which who will with you your about after
again all also any because before being both could did does doing each few had having he her him his more most much must off once only other
own same she should some such tell very would yours today tomorrow tonight week weekend monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december""".split())
URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
HASHTAG = re.compile(r"#([^\s#.,!?;:，。！？、]{2,40})")
LATIN = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’\-]{2,39}")
CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]{2,}")
REASONS = {
    "permission": "Access to a source used by this work was withdrawn. Review the affected work before publishing it.",
    "source_integrity": "A source cited by this work was withdrawn or changed. Review the affected work before publishing it.",
}

LOCK = "/*lio:sugg.lock*/ SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
MEMBERS = ("/*lio:sugg.members*/ SELECT m.user_id::text FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id "
           "WHERE m.workspace_id=%s AND m.status='active' AND p.deleted_at IS NULL AND m.role IN ('owner','admin','editor') "
           "ORDER BY (m.role='owner') DESC,m.user_id LIMIT %s")
IS_MEMBER = ("/*lio:sugg.is_member*/ SELECT m.user_id::text FROM public.pr_memberships m JOIN public.pr_profiles p ON p.user_id=m.user_id "
             "WHERE m.workspace_id=%s AND m.status='active' AND p.deleted_at IS NULL AND m.user_id=ANY(%s::uuid[])")
PREFS = ("/*lio:sugg.prefs*/ SELECT recipient::text,category,disabled,snooze_days,external_opt_in FROM public.pr_library_suggestion_prefs "
         "WHERE workspace_id=%s AND recipient=ANY(%s::uuid[])")
# The daily cap is per person across every workspace they belong to (spec §11), not per workspace.
TODAY = ("/*lio:sugg.today*/ SELECT recipient::text,count(*) FROM public.pr_library_suggestions WHERE recipient=ANY(%s::uuid[]) "
         "AND NOT critical AND created_at>now()-make_interval(secs=>%s) GROUP BY recipient")
PUT = ("/*lio:sugg.put*/ INSERT INTO public.pr_library_suggestions(id,workspace_id,recipient,dedup_key,category,critical,trigger,candidate_refs,affected,"
       "reason,consent_revision,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,"
       "CASE WHEN %s::int IS NULL THEN NULL ELSE now()+make_interval(days=>%s::int) END) "
       "ON CONFLICT(workspace_id,recipient,dedup_key) DO NOTHING RETURNING id::text,extract(epoch from created_at)")
RECENT = ("/*lio:sugg.recent*/ SELECT 1 FROM public.pr_library_metrics WHERE workspace_id=%s AND feature='library.suggestions' AND event='evaluated' "
          "AND dims->>'target'=%s AND at>now()-make_interval(secs=>%s) LIMIT 1")
STAMP = "/*lio:sugg.stamp*/ INSERT INTO public.pr_library_metrics(workspace_id,feature,event,value,dims) VALUES(%s,'library.suggestions','evaluated',%s,%s::jsonb)"
HISTORY = ("/*lio:sugg.history*/ SELECT candidate_refs,extract(epoch from created_at),state FROM public.pr_library_suggestions WHERE workspace_id=%s "
           "AND recipient=%s AND category='unused_relevant' AND created_at>now()-make_interval(days=>%s) ORDER BY created_at DESC LIMIT 200")
SUGG_COLS = ("id::text,category,critical,trigger,candidate_refs,affected,reason,state,extract(epoch from snooze_until),extract(epoch from created_at),"
             "extract(epoch from expires_at)")
INBOX = (f"/*lio:sugg.inbox*/ SELECT {SUGG_COLS} FROM public.pr_library_suggestions WHERE workspace_id=%s AND recipient=%s "
         "AND (state IN ('new','seen') OR (state='snoozed' AND snooze_until<=now())) AND (expires_at IS NULL OR expires_at>now()) "
         "ORDER BY critical DESC,created_at DESC LIMIT %s")
GET = (f"/*lio:sugg.get*/ SELECT {SUGG_COLS},recipient::text,coalesce(expires_at<=now(),false) FROM public.pr_library_suggestions "
       "WHERE workspace_id=%s AND id=%s AND recipient=%s FOR UPDATE")
SET = ("/*lio:sugg.set*/ UPDATE public.pr_library_suggestions SET state=%s,snooze_until=NULL,updated_at=now() WHERE workspace_id=%s AND id=%s "
       "RETURNING state,extract(epoch from snooze_until)")
SNOOZE = ("/*lio:sugg.snooze*/ UPDATE public.pr_library_suggestions SET state='snoozed',snooze_until=now()+make_interval(days=>%s),updated_at=now() "
          "WHERE workspace_id=%s AND id=%s RETURNING state,extract(epoch from snooze_until)")
PREF_PUT = ("/*lio:sugg.pref_put*/ INSERT INTO public.pr_library_suggestion_prefs(workspace_id,recipient,category,disabled,snooze_days) "
            "VALUES(%s,%s,%s,coalesce(%s::boolean,false),coalesce(%s::int,7)) ON CONFLICT(workspace_id,recipient,category) DO UPDATE "
            "SET disabled=coalesce(%s::boolean,pr_library_suggestion_prefs.disabled),snooze_days=coalesce(%s::int,pr_library_suggestion_prefs.snooze_days),"
            "updated_at=now() RETURNING disabled,snooze_days,external_opt_in")
SUPPRESS_CATEGORY = ("/*lio:sugg.suppress_category*/ UPDATE public.pr_library_suggestions SET state='suppressed',updated_at=now() WHERE workspace_id=%s "
                     "AND recipient=%s AND category=%s AND state IN ('new','seen','snoozed') AND NOT critical")
CAPABILITY = "/*lio:sugg.capability*/ SELECT state,error_code FROM public.pr_library_capabilities WHERE workspace_id=%s AND asset_key=%s AND capability=%s"
FAILED = ("/*lio:sugg.failed*/ SELECT asset_key,capability,error_code FROM public.pr_library_capabilities WHERE workspace_id=%s AND state='failed' "
          "AND updated_at>now()-make_interval(days=>7) ORDER BY updated_at DESC LIMIT %s")
STALE = ("/*lio:sugg.stale*/ SELECT from_version,to_kind,to_key,evidence FROM public.pr_library_relations WHERE workspace_id=%s AND relation='used_in' "
         "AND status='stale' ORDER BY updated_at DESC LIMIT %s")
OPEN = ("/*lio:sugg.open*/ SELECT id::text,candidate_refs FROM public.pr_library_suggestions WHERE workspace_id=%s AND state IN ('new','seen','snoozed') "
        "ORDER BY created_at DESC LIMIT %s")
SUPPRESS = "/*lio:sugg.suppress*/ UPDATE public.pr_library_suggestions SET state='suppressed',updated_at=now() WHERE workspace_id=%s AND id=ANY(%s::uuid[])"
EXPIRE = ("/*lio:sugg.expire*/ UPDATE public.pr_library_suggestions SET state='expired',updated_at=now() WHERE workspace_id=%s "
          "AND state IN ('new','seen','snoozed') AND expires_at<=now()")
TAGS = ("/*lio:sugg.tags*/ SELECT t,count(*) FROM public.pr_library_assets a,unnest(a.tags) AS t WHERE a.workspace_id=%s "
        "AND a.processing_status IN ('ready','unsupported') GROUP BY t HAVING count(*)>=%s ORDER BY count(*) DESC,t LIMIT %s")
COLLECTION_NAMES = "/*lio:sugg.collections*/ SELECT name FROM public.pr_library_collections WHERE workspace_id=%s"
DUE = ("/*lio:sugg.due*/ SELECT w.id::text FROM public.pr_workspaces w WHERE NOT (w.state ? 'accountBlock') AND NOT (w.state ? 'accountDeletion') "
       "AND (EXISTS(SELECT 1 FROM public.pr_library_assets a WHERE a.workspace_id=w.id) OR CASE WHEN jsonb_typeof(w.state->'variants')='array' "
       "THEN jsonb_array_length(w.state->'variants')>0 ELSE false END) AND NOT EXISTS(SELECT 1 FROM public.pr_library_metrics m WHERE m.workspace_id=w.id "
       "AND m.feature='library.suggestions' AND m.event='evaluated' AND m.dims->>'target'=%s AND m.at>now()-make_interval(secs=>%s)) "
       "ORDER BY w.id LIMIT %s")


def _key(value) -> str:
    return str(value).replace("-", "").lower()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _epoch(value) -> float:
    """Draft revision times are epoch numbers or ISO-8601 strings; anything else sorts last."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        from datetime import datetime, timezone
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _clip(text, limit: int = 80) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(text or ""))[:limit]


# --- pure helpers ---------------------------------------------------------------------------------------------------------
def draft_terms(text: str, limit: int = SEARCH_TERMS) -> list[str]:
    """A few salient search terms from a draft: hashtags, proper nouns, CJK runs, then long words. Library search ANDs
    every term of one query, so a whole draft is searched as several short queries rather than one."""
    text = URL.sub(" ", str(text or "")[:4000])  # links are never search terms
    out, seen = [], set()

    def add(term):
        term = term.strip("-'’")
        folded = textnorm.fold(term)
        if len(term) < 2 or folded in seen or folded in STOP or not textnorm.query_terms(term) or c.UNSAFE.search(term):
            return
        seen.add(folded)
        out.append(term)
    for tag in HASHTAG.findall(text):
        add(tag)
    words = LATIN.findall(text)
    for word in words:
        if word[0].isupper():
            add(word)
    for run in CJK_RUN.findall(text):
        add(run[:4])
    for word in sorted(words, key=lambda w: (-len(w), w)):
        if len(word) >= 6:
            add(word)
    return out[:limit]


def rank_candidates(candidates: list, history: dict, now: float, *, limit: int | None = None, k: int = RRF_K) -> list:
    """Relevance by reciprocal-rank fusion over the term lists, then two controls so one popular item does not win every
    time: a recency penalty for items recently surfaced to this person (fading over about a week, stronger for repeats),
    and a kind-diversity discount for each item of the same kind already picked. Ties prefer newer items."""
    def base(cand):
        return sum(1.0 / (k + p + 1) for p in cand.get("positions") or ())

    def penalty(key):
        seen = history.get(key)
        if not seen:
            return 1.0
        age = max(0.0, now - float(seen.get("lastAt") or 0.0))
        recency = 1.0 - 0.9 * math.exp(-age / (7 * 86400.0))
        return recency / (1.0 + 0.5 * max(0, int(seen.get("count") or 1) - 1))

    scored = [(base(cand) * penalty(cand["key"]), cand) for cand in candidates]
    picked, kinds = [], {}
    while scored and (limit is None or len(picked) < limit):
        best = max(scored, key=lambda item: (item[0] * 0.5 ** kinds.get(item[1].get("kind"), 0), float(item[1].get("createdAt") or 0), item[1]["key"]))
        scored.remove(best)
        picked.append(dict(best[1]))
        kinds[best[1].get("kind")] = kinds.get(best[1].get("kind"), 0) + 1
    return picked


# --- event validation -----------------------------------------------------------------------------------------------------
def _affected(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        c.fail("List at most 200 affected items.")
    out = []
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in DEPENDENT_KINDS or not isinstance(item.get("key"), str) \
                or not KEYLIKE.fullmatch(item["key"]):
            c.fail("Each affected item needs a kind and key.")
        entry = {"kind": item["kind"], "key": item["key"]}
        if item.get("recipient") is not None:
            try:
                entry["recipient"] = str(uuid.UUID(str(item["recipient"])))
            except ValueError:
                c.fail("A recipient must be a member id.")
        out.append(entry)
    return out


def _event(value) -> dict:
    if not isinstance(value, dict) or value.get("type") not in EVENT_TYPES:
        c.fail("Unknown suggestion trigger.")
    kind = value["type"]
    out = {"type": kind}
    if kind == "version_linked":
        out.update(old=c.asset_ref(value.get("old")), new=c.asset_ref(value.get("new")), affected=_affected(value.get("affected")))
    elif kind == "capability_failed":
        if value.get("capability") not in c.CAPABILITIES:
            c.fail("Name the processing capability that failed.")
        out.update(assetKey=c.asset_key(value.get("assetKey")), capability=value["capability"])
    elif kind == "draft_changed":
        if not isinstance(value.get("draftId"), str) or not KEYLIKE.fullmatch(value["draftId"]):
            c.fail("Name the draft that changed.")
        out["draftId"] = value["draftId"]
    elif kind == "collection_proposal":
        from . import collections
        name = value.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            c.fail("Name the proposed collection.")
        out.update(rule=collections.validate_rule(value.get("rule")), name=name.strip())
    elif kind in CRITICAL:
        out.update(assetKey=c.asset_key(value["assetKey"]) if value.get("assetKey") is not None else None, affected=_affected(value.get("affected")))
        if not out["affected"]:
            c.fail("Name the affected work.")
    return out


def _identity(ctx, event: dict) -> str:
    kind = event["type"]
    if kind == "draft_changed":
        return f"draft_changed:{event['draftId']}:{ctx.actor}"
    if kind == "capability_failed":
        return f"capability_failed:{event['assetKey']}:{event['capability']}"
    if kind == "collection_proposal":
        return "collection_proposal:" + _digest(event["rule"])[:24]
    return kind


def _target(identity: str) -> str:
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


# --- recipients -----------------------------------------------------------------------------------------------------------
def _editors(ctx) -> list:
    if "suggestionEditors" not in ctx.caches:
        ctx.cur.execute(MEMBERS, (ctx.workspace_id, MAX_RECIPIENTS))
        ctx.caches["suggestionEditors"] = [r[0] for r in ctx.cur.fetchall()]
    return list(ctx.caches["suggestionEditors"])


def _active(ctx, ids) -> list:
    ids = sorted({i for i in ids if i})
    if not ids:
        return []
    ctx.cur.execute(IS_MEMBER, (ctx.workspace_id, ids))
    found = {r[0] for r in ctx.cur.fetchall()}
    return [i for i in ids if i in found]


def _actor_or_editors(ctx) -> list:
    if ctx.actor != SYSTEM_ACTOR:
        try:
            own = _active(ctx, [str(uuid.UUID(str(ctx.actor)))])
        except ValueError:
            own = []
        if own:
            return own
    return _editors(ctx)


# --- candidates -----------------------------------------------------------------------------------------------------------
def _candidate(category, recipients, dedup, reason, affected, refs, trigger) -> dict:
    return {"category": category, "recipients": list(recipients), "dedup": dedup[:300], "reason": reason[:400], "affected": affected[:MAX_AFFECTED],
            "candidateRefs": refs, "trigger": trigger}


def _version_linked(ctx, event: dict, recipients=None) -> list:
    loaded = versions.load(ctx, [event["old"]["versionId"], event["new"]["versionId"]])
    old, new = loaded.get(event["old"]["versionId"]), loaded.get(event["new"]["versionId"])
    if old is None or new is None or new["status"] in HIDDEN:
        return []
    groups: dict = {}
    fallback = None
    for item in event["affected"]:
        named = _active(ctx, [item["recipient"]]) if item.get("recipient") else []
        if not named:
            fallback = fallback if fallback is not None else (list(recipients) if recipients is not None else _actor_or_editors(ctx))
            named = fallback
        for recipient in named:
            groups.setdefault(recipient, []).append({"kind": item["kind"], "key": item["key"], "citesVersion": versions.ref(old)})
    out = []
    for recipient, items in groups.items():
        n = len(items)
        reason = (f"A newer version of “{_clip(old['title'])}” was added. {n} item{'s' if n != 1 else ''} still "
                  f"cite{'s' if n == 1 else ''} version {old['versionNo']}; review the change before replacing it.")
        out.append(_candidate("outdated_source", [recipient], f"outdated_source:{old['versionId']}:{new['versionId']}", reason, items,
                              [versions.ref(new)], {"event": "version_linked", "old": versions.ref(old), "new": versions.ref(new),
                                                    "why": {"method": "version_link"}}))
    return out


def _failed_candidate(ctx, version: dict, capability: str, error_code, recipients) -> dict:
    noun = CAPABILITY_NOUNS.get(capability, capability)
    reason = f"Rafii couldn't finish {noun} for “{_clip(version['title'])}”. The original file is safe; you can retry processing from its details."
    return _candidate("failed_processing", recipients, f"failed_processing:{version['versionId']}:{capability}", reason,
                      [{"kind": "asset", "key": version["versionId"], "assetRef": versions.ref(version)}], [versions.ref(version)],
                      {"event": "capability_failed", "capability": capability, "errorCode": _clip(error_code, 80) or None,
                       "why": {"method": "processing_state"}})


def _capability_failed(ctx, event: dict) -> list:
    ctx.cur.execute(CAPABILITY, (ctx.workspace_id, event["assetKey"], event["capability"]))
    row = ctx.cur.fetchone()
    if not row or row[0] != "failed":
        return []
    version = versions.load(ctx, [event["assetKey"]]).get(event["assetKey"])
    if version is None or version["status"] in HIDDEN:
        return []
    return [_failed_candidate(ctx, version, event["capability"], row[1], _editors(ctx))]


def _variant(ctx, draft_id: str):
    return next((v for v in (ctx.state.get("variants") or []) if isinstance(v, dict) and v.get("id") == draft_id), None)


def _draft_label(variant: dict) -> str:
    platform = str(variant.get("platform") or "").strip()
    return f"{platform.title()} draft" if platform else "Draft"


def _search(ctx, request):
    from . import search
    return search.search_library(ctx, request)


def _history(ctx, recipient: str) -> dict:
    ctx.cur.execute(HISTORY, (ctx.workspace_id, recipient, HISTORY_DAYS))
    out: dict = {}
    for refs, created, state in ctx.cur.fetchall():
        for r in refs if isinstance(refs, list) else []:
            key = r.get("versionId") if isinstance(r, dict) else None
            if not key:
                continue
            seen = out.setdefault(key, {"count": 0, "lastAt": 0.0, "dismissed": False})
            seen["count"] += 1
            seen["lastAt"] = max(seen["lastAt"], float(created or 0))
            seen["dismissed"] = seen["dismissed"] or state == "dismissed"
    return out


def _cited_by_drafts(ctx) -> set:
    """Library versions already used in a draft through an imported Ideas source (the same trace usage.py reports)."""
    cited_sources = {sid for v in (ctx.state.get("variants") or []) if isinstance(v, dict) for sid in v.get("sourceIds") or []}
    return {(s.get("origin") or {}).get("assetId") for s in (ctx.state.get("sources") or [])
            if isinstance(s, dict) and s.get("id") in cited_sources and isinstance(s.get("origin"), dict)} - {None}


def _unused(ctx, variant: dict, recipients, cited: set) -> list:
    """One relevant, not-yet-used Library item for this draft revision, chosen per recipient with diversity controls.
    'Unused' means no usage event or citation (search's usage filter) and not already cited by any draft's sources."""
    if not policy.enabled("retrieval"):
        return []
    cited = set(cited) | _cited_by_drafts(ctx)
    terms = draft_terms(variant.get("text") or "")
    lists, hits, matched = [], {}, {}
    for term in terms:
        try:
            response = _search(ctx, {"query": term, "scope": {"kind": "workspace"}, "purpose": "browse", "filters": {"usage": "unused"},
                                     "modes": ["lexical"], "limit": SEARCH_LIMIT})
        except AlphaError:
            continue
        keys = []
        for hit in response.get("hits") or []:
            ref = hit.get("assetRef") or {}
            key = ref.get("versionId")
            if not isinstance(key, str) or key in keys:
                continue
            keys.append(key)
            hits.setdefault(key, hit)
            matched.setdefault(key, []).append(term)
        lists.append(keys)
    if not hits:
        return []
    loaded = versions.load(ctx, list(hits))
    pool = []
    for key, hit in hits.items():
        version = loaded.get(key)
        if version is None or version["status"] in HIDDEN or key in cited or version["assetId"] in cited:
            continue
        pool.append({"key": key, "kind": version["kind"], "createdAt": version["createdAt"],
                     "positions": [keys.index(key) for keys in lists if key in keys]})
    out = []
    revision = variant.get("revision") if type(variant.get("revision")) is int else 0
    for recipient in recipients:
        history = _history(ctx, recipient)
        ranked = rank_candidates([p for p in pool if not history.get(p["key"], {}).get("dismissed")], history, ctx.now, limit=1)
        if not ranked:
            continue
        version, hit = loaded[ranked[0]["key"]], hits[ranked[0]["key"]]
        terms_used = matched[version["versionId"]]
        reason = (f"“{_clip(version['title'])}” hasn't been used yet and matches {', '.join('“' + _clip(t, 40) + '”' for t in terms_used)} "
                  f"in your {_draft_label(variant)}.")
        out.append(_candidate("unused_relevant", [recipient], f"unused_relevant:{variant['id']}:{revision}", reason,
                              [{"kind": "draft", "key": variant["id"]}], [versions.ref(version)],
                              {"event": "draft_changed", "draftId": variant["id"], "draftRevision": revision,
                               "why": {"method": "lexical", "matchedTerms": terms_used, "matchReasons": (hit.get("matchReasons") or [])[:3],
                                       "ranking": RANKING_VERSION, "unusedFilter": True}}))
    return out


def _draft_candidates(ctx, variant: dict, recipients) -> list:
    if not isinstance(variant.get("id"), str) or not KEYLIKE.fullmatch(variant["id"]):
        return []
    sources = {s.get("id"): s for s in (ctx.state.get("sources") or []) if isinstance(s, dict)}
    cited = [sources[sid] for sid in variant.get("sourceIds") or [] if sid in sources]
    label = _draft_label(variant)
    out = []
    withdrawn = sorted(s["id"] for s in cited if not s.get("active", True))
    if withdrawn:
        out.append(_candidate("source_integrity", recipients, f"source_integrity:draft:{variant['id']}:{_digest(withdrawn)[:16]}",
                              f"Your {label} cites a source that was withdrawn. Review the draft before publishing it.",
                              [{"kind": "draft", "key": variant["id"]}] + [{"kind": "idea", "key": sid} for sid in withdrawn], [],
                              {"event": "draft_changed", "draftId": variant["id"], "why": {"method": "source_review"}}))
    unapproved = sorted(s["id"] for s in cited if s.get("active", True) and not any(isinstance(f, dict) and f.get("approved") for f in s.get("facts") or []))
    if unapproved:
        n = len(unapproved)
        out.append(_candidate("missing_input", recipients, f"missing_input:{variant['id']}:{_digest(unapproved)[:16]}",
                              f"Your {label} cites {n} source{'s' if n != 1 else ''} without approved facts. Review "
                              f"{'them' if n != 1 else 'it'} before relying on this draft.",
                              [{"kind": "draft", "key": variant["id"]}] + [{"kind": "idea", "key": sid} for sid in unapproved], [],
                              {"event": "draft_changed", "draftId": variant["id"], "why": {"method": "source_review"}}))
    cited_assets = {(s.get("origin") or {}).get("assetId") for s in cited if isinstance(s.get("origin"), dict)} - {None}
    return out + _unused(ctx, variant, recipients, cited_assets)


def _draft_changed(ctx, event: dict) -> list:
    variant = _variant(ctx, event["draftId"])
    return [] if variant is None else _draft_candidates(ctx, variant, _actor_or_editors(ctx))


def _collection_proposal(ctx, event: dict, recipients=None) -> list:
    from . import collections
    ctx.cur.execute(COLLECTION_NAMES, (ctx.workspace_id,))
    if event["name"] in {r[0] for r in ctx.cur.fetchall()}:
        return []
    preview = collections.preview_collection(ctx, event["rule"], None, limit=5)
    if preview["count"] < PROPOSAL_MIN_ITEMS:
        return []
    reason = (f"A smart collection “{_clip(event['name'])}” would gather {preview['count']} items. {preview['explanation']} "
              "Nothing changes until you apply it, and it can be undone.")
    return [_candidate("organization", recipients if recipients is not None else _actor_or_editors(ctx), "organization:" + _digest(event["rule"])[:24],
                       reason, [{"kind": "proposal", "name": event["name"], "itemCount": preview["count"]}],
                       [m["assetRef"] for m in preview["members"]],
                       {"event": "collection_proposal", "proposal": {"name": event["name"], "rule": event["rule"]},
                        "why": {"method": "smart_collection_preview", "explanation": preview["explanation"]}})]


def _critical(ctx, event: dict) -> list:
    category = event["type"]
    affected = [{"kind": a["kind"], "key": a["key"]} for a in event["affected"]]
    dedup = f"{category}:{event['assetKey'] or '-'}:{_digest(sorted((a['kind'], a['key']) for a in affected))[:16]}"
    return [_candidate(category, _editors(ctx), dedup, REASONS[category], affected, [],
                       {"event": category, "assetKey": event["assetKey"], "why": {"method": "access_check" if category == "permission" else "source_review"}})]


def _housekeeping(ctx):
    ctx.cur.execute(EXPIRE, (ctx.workspace_id,))
    ctx.cur.execute(OPEN, (ctx.workspace_id, SWEEP_OPEN))
    rows = ctx.cur.fetchall()
    keys = {r.get("versionId") for _, refs in rows for r in (refs if isinstance(refs, list) else []) if isinstance(r, dict)} - {None}
    loaded = versions.load(ctx, sorted(keys)) if keys else {}
    gone = [sid for sid, refs in rows if any(isinstance(r, dict) and (loaded.get(r.get("versionId")) is None or
                                                                      loaded[r["versionId"]]["status"] in HIDDEN) for r in (refs if isinstance(refs, list) else []))]
    if gone:
        ctx.cur.execute(SUPPRESS, (ctx.workspace_id, [str(uuid.UUID(hex=_key(g))) for g in gone]))


def _sweep(ctx, event: dict) -> list:
    """Bounded periodic pass: housekeeping, failed processing, stale citations (re-deriving warnings the cap deferred),
    the most recent drafts and organization proposals from frequent tags."""
    _housekeeping(ctx)
    editors = _editors(ctx)
    if not editors:
        return []
    out = []
    ctx.cur.execute(FAILED, (ctx.workspace_id, SWEEP_FAILED))
    failed = ctx.cur.fetchall()
    loaded = versions.load(ctx, [r[0] for r in failed]) if failed else {}
    for key, capability, error_code in failed:
        version = loaded.get(key)
        if version is not None and version["status"] not in HIDDEN:
            out.append(_failed_candidate(ctx, version, capability, error_code, editors))
    ctx.cur.execute(STALE, (ctx.workspace_id, SWEEP_STALE))
    groups: dict = {}
    for from_version, to_kind, to_key, evidence in ctx.cur.fetchall():
        newer = (evidence or {}).get("supersededBy") if isinstance(evidence, dict) else None
        if not isinstance(newer, dict) or to_kind not in DEPENDENT_KINDS or not isinstance(to_key, str) or not KEYLIKE.fullmatch(to_key):
            continue
        try:
            new_ref = c.asset_ref(newer)
        except AlphaError:
            continue
        groups.setdefault((from_version, new_ref["versionId"]), {"new": new_ref, "affected": []})["affected"].append({"kind": to_kind, "key": to_key})
    for (old_key, _), group in groups.items():
        old = versions.load(ctx, [old_key]).get(old_key)
        if old is not None:
            out += _version_linked(ctx, {"old": versions.ref(old), "new": group["new"], "affected": group["affected"]}, editors)
    drafts = [v for v in (ctx.state.get("variants") or []) if isinstance(v, dict) and (v.get("text") or v.get("sourceIds"))]
    drafts.sort(key=lambda v: max([_epoch(r.get("at")) for r in v.get("revisions") or [] if isinstance(r, dict)] or [0.0]), reverse=True)
    for variant in drafts[:SWEEP_DRAFTS]:
        out += _draft_candidates(ctx, variant, editors)
    ctx.cur.execute(TAGS, (ctx.workspace_id, PROPOSAL_MIN_ITEMS, 3))
    from . import collections
    for tag, _ in ctx.cur.fetchall():
        try:
            rule = collections.validate_rule({"all": [{"field": "tag", "op": "has", "value": tag}]})
        except AlphaError:
            continue
        out += _collection_proposal(ctx, {"rule": rule, "name": f"Tagged {_clip(tag, 60)}"}, editors)
    return out


BUILDERS = {"version_linked": _version_linked, "capability_failed": _capability_failed, "draft_changed": _draft_changed,
            "collection_proposal": _collection_proposal, "permission_revoked": _critical, "source_integrity": _critical, "sweep": _sweep}


# --- emission ---------------------------------------------------------------------------------------------------------------
def _prefs(ctx, recipients) -> dict:
    if not recipients:
        return {}
    ctx.cur.execute(PREFS, (ctx.workspace_id, sorted(recipients)))
    return {(r, cat): {"disabled": bool(disabled), "snoozeDays": int(days), "externalOptIn": bool(ext)} for r, cat, disabled, days, ext in ctx.cur.fetchall()}


def _today(ctx, recipients) -> dict:
    if not recipients:
        return {}
    ctx.cur.execute(TODAY, (sorted(recipients), CAP_WINDOW_SECONDS))
    return {r: int(n) for r, n in ctx.cur.fetchall()}


def _emit(ctx, candidates: list) -> list:
    candidates = [cand for cand in candidates if cand["recipients"]]
    if not candidates:
        return []
    recipients = sorted({r for cand in candidates for r in cand["recipients"]})
    for recipient in recipients:  # serializes the cross-workspace daily cap per person; sorted to avoid lock-order deadlocks
        ctx.cur.execute(LOCK, (f"library-suggestions:{recipient}",))
    prefs, today = _prefs(ctx, recipients), _today(ctx, recipients)
    revision = policy.revisions(ctx)["grantRevision"]
    created = []
    for cand in sorted(candidates, key=lambda x: (PRIORITY[x["category"]], x["dedup"])):
        critical = cand["category"] in CRITICAL
        for recipient in cand["recipients"]:
            if not critical and (prefs.get((recipient, cand["category"]), {}).get("disabled") or today.get(recipient, 0) >= DAILY_CAP):
                continue  # deferred, not lost: the periodic pass re-derives it from durable state
            expires = None if critical else EXPIRES_DAYS
            ctx.cur.execute(PUT, (uuid.uuid4(), ctx.workspace_id, recipient, cand["dedup"], cand["category"], critical,
                                  json.dumps(cand["trigger"], ensure_ascii=False, sort_keys=True), json.dumps(cand["candidateRefs"]),
                                  json.dumps(cand["affected"], ensure_ascii=False), cand["reason"], revision, expires, expires))
            row = ctx.cur.fetchone()
            if not row:
                continue  # the same identity already exists (including a dismissed one): never recreated
            if not critical:
                today[recipient] = today.get(recipient, 0) + 1
            created.append({"id": _key(row[0]), "recipient": recipient, "category": cand["category"], "critical": critical, "reason": cand["reason"],
                            "affected": cand["affected"], "candidateRefs": cand["candidateRefs"], "why": cand["trigger"].get("why"), "state": "new",
                            "createdAt": float(row[1]) if row[1] is not None else None})
    return created


def evaluate_suggestions(ctx, event) -> list:
    """evaluate_suggestions(ctx, event) -> Suggestion[] (implementation plan T11). Returns only the rows created now."""
    ctx.require("read")
    event = _event(event)
    kind = event["type"]
    if kind in PROACTIVE:
        if not policy.enabled("suggestions"):
            return []
        target = _target(_identity(ctx, event))
        ctx.cur.execute(RECENT, (ctx.workspace_id, target, SWEEP_SECONDS if kind == "sweep" else DEBOUNCE_SECONDS))
        if ctx.cur.fetchone():
            return []  # a burst of the same trigger is coalesced; the periodic pass covers anything missed
        ctx.cur.execute(STAMP, (ctx.workspace_id, 1, json.dumps({"target": target, "type": kind})))
    return _emit(ctx, BUILDERS[kind](ctx, event))


# --- reading and changing state -----------------------------------------------------------------------------------------------
def _actions(category: str, critical: bool) -> list:
    out = ["open", "dismiss", "snooze"]
    if category == "organization":
        out.append("apply")
    if not critical:
        out.append("disable_category")
    return out


def _public(row) -> dict:
    sid, category, critical, trigger, refs, affected, reason, state, snooze, created, expires = row[:11]
    trigger = trigger if isinstance(trigger, dict) else {}
    out = {"id": _key(sid), "category": category, "critical": bool(critical), "reason": reason, "affected": affected or [], "candidateRefs": refs or [],
           "why": trigger.get("why"), "state": state, "snoozeUntil": float(snooze) if snooze is not None else None,
           "createdAt": float(created) if created is not None else None, "expiresAt": float(expires) if expires is not None else None,
           "actions": _actions(category, bool(critical))}
    if category == "organization" and isinstance(trigger.get("proposal"), dict):
        out["proposal"] = trigger["proposal"]
    return out


def _preferences(prefs: dict, recipient: str) -> dict:
    return {cat: {"disabled": prefs.get((recipient, cat), {}).get("disabled", False),
                  "snoozeDays": prefs.get((recipient, cat), {}).get("snoozeDays", SNOOZE_DEFAULT_DAYS), "canDisable": cat not in CRITICAL}
            for cat in CATEGORIES}


def inbox(ctx) -> dict:
    """The caller's own in-app suggestions. Items whose referenced Library items are gone or hidden are left out."""
    ctx.require("read")
    ctx.cur.execute(INBOX, (ctx.workspace_id, ctx.actor, INBOX_LIMIT * 2))
    rows = ctx.cur.fetchall()
    prefs = _prefs(ctx, [ctx.actor])
    disabled = {cat for (r, cat), p in prefs.items() if p["disabled"]}
    keys = {r.get("versionId") for row in rows for r in (row[4] if isinstance(row[4], list) else []) if isinstance(r, dict)} - {None}
    loaded = versions.load(ctx, sorted(keys)) if keys else {}
    out = []
    for row in rows:
        refs = row[4] if isinstance(row[4], list) else []
        if row[1] in disabled and not row[2]:
            continue
        if any(not isinstance(r, dict) or loaded.get(r.get("versionId")) is None or loaded[r["versionId"]]["status"] in HIDDEN for r in refs):
            continue
        out.append(_public(row))
    return {"suggestions": out[:INBOX_LIMIT], "cap": {"noncriticalPerDay": DAILY_CAP, "shownToday": _today(ctx, [ctx.actor]).get(ctx.actor, 0)},
            "preferences": _preferences(prefs, ctx.actor), "delivery": dict(DELIVERY), "proactiveEnabled": policy.enabled("suggestions")}


def inbox_http(ctx, request):
    """GET .../suggestions."""
    return inbox(ctx)


def _set_preference(ctx, category: str, action: str, snooze_days) -> dict:
    if category not in CATEGORIES:
        c.fail("Choose a suggestion category.")
    if action == "disable_category" and category in CRITICAL:
        c.fail("Safety warnings about permissions and sources can't be turned off.")
    if action == "preferences" and snooze_days is None:
        c.fail("Choose how many days a snooze lasts.")
    disabled = {"disable_category": True, "enable_category": False}.get(action)
    ctx.cur.execute(PREF_PUT, (ctx.workspace_id, ctx.actor, category, disabled, snooze_days, disabled, snooze_days))
    row = ctx.cur.fetchone()
    if disabled:
        ctx.cur.execute(SUPPRESS_CATEGORY, (ctx.workspace_id, ctx.actor, category))
    return {"preference": {"category": category, "disabled": bool(row[0]), "snoozeDays": int(row[1])}}


def set_suggestion_state(ctx, suggestion_id, action, *, snooze_days=None, category=None) -> dict:
    """set_suggestion_state(ctx, id, action) -> state. Only the recipient can change a suggestion; anyone else gets the same
    answer as for a missing one. apply on an organization proposal creates the smart collection (edit permission)."""
    ctx.require("read")
    if action not in ACTIONS:
        c.fail("Choose seen, dismiss, snooze, apply or a category preference.")
    if snooze_days is not None and (type(snooze_days) is not int or not 1 <= snooze_days <= 90):
        c.fail("Snooze for 1 to 90 days.")
    if suggestion_id is None:
        if action not in ("disable_category", "enable_category", "preferences"):
            c.fail("Choose a suggestion.")
        return _set_preference(ctx, category, action, snooze_days)
    try:
        sid = uuid.UUID(hex=c.asset_key(suggestion_id))
    except AlphaError:
        raise AlphaError("This suggestion is unavailable.", 404, code="library_unavailable") from None
    ctx.cur.execute(GET, (ctx.workspace_id, sid, ctx.actor))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("This suggestion is unavailable.", 404, code="library_unavailable")
    current = _public(row)
    out: dict = {"warnings": []}
    if action in ("seen", "dismiss", "snooze", "apply") and not (action == "dismiss" and current["state"] == "dismissed"):
        # Only an open suggestion changes state, so a dismissed, suppressed (revoked), expired or applied one is never
        # revived by a snooze or applied again; the row lock above makes "apply" happen exactly once.
        if current["state"] not in OPEN_STATES or bool(row[12]):
            if action == "apply" and current["state"] == "applied":
                raise AlphaError("This suggestion was already applied.", 409, code="library_suggestion_applied")
            raise AlphaError("This suggestion is no longer available.", 409, code="library_suggestion_unavailable")
    if action in ("disable_category", "enable_category", "preferences"):
        out.update(_set_preference(ctx, current["category"], action, snooze_days))
    elif action == "seen":
        if current["state"] == "new":
            ctx.cur.execute(SET, ("seen", ctx.workspace_id, sid))
    elif action == "dismiss":
        if current["state"] != "dismissed":
            ctx.cur.execute(SET, ("dismissed", ctx.workspace_id, sid))
    elif action == "snooze":
        days = snooze_days or _prefs(ctx, [ctx.actor]).get((ctx.actor, current["category"]), {}).get("snoozeDays") or SNOOZE_DEFAULT_DAYS
        ctx.cur.execute(SNOOZE, (int(days), ctx.workspace_id, sid))
    else:
        if current["category"] == "organization":
            proposal = (row[3] or {}).get("proposal") if isinstance(row[3], dict) else None
            if not isinstance(proposal, dict):
                raise AlphaError("This proposal can no longer be applied.", 409, code="library_suggestion_stale")
            ctx.require("edit")
            from . import collections
            saved = collections.save_collection(ctx, proposal.get("rule"), None, name=proposal.get("name"))
            out.update(collection=saved["collection"])
            out["warnings"] += saved.get("warnings") or []
        ctx.cur.execute(SET, ("applied", ctx.workspace_id, sid))
    ctx.cur.execute(GET, (ctx.workspace_id, sid, ctx.actor))
    out["suggestion"] = _public(ctx.cur.fetchone())
    return out


def set_state_action(ctx, envelope, targets):
    """suggestion.set_state: payload {suggestionId?, action, snoozeDays?, category?}."""
    payload = envelope.get("payload") or {}
    extra = sorted(set(payload) - {"suggestionId", "action", "snoozeDays", "category"})
    if extra:
        c.fail(f"This action does not accept “{str(extra[0])[:40]}”.")
    out = set_suggestion_state(ctx, payload.get("suggestionId"), payload.get("action"), snooze_days=payload.get("snoozeDays"),
                               category=payload.get("category"))
    return c.action_result("applied", result=out, warnings=out.get("warnings") or [])


# --- periodic pass ---------------------------------------------------------------------------------------------------------------
def evaluate_due(intel, connect, *, limit: int = SWEEP_WORKSPACES) -> dict:
    """Bounded periodic pass for LibraryIntelligence.tick: sweep up to `limit` workspaces not swept within SWEEP_SECONDS,
    each in its own transaction. Never raises."""
    summary = {"status": "ok", "workspaces": 0, "created": 0, "errors": 0}
    if not policy.enabled("suggestions"):
        return {**summary, "status": "disabled"}
    try:
        with connect() as db, db.cursor() as cur:
            cur.execute(DUE, (_target("sweep"), SWEEP_SECONDS, int(limit)))
            due = [r[0] for r in cur.fetchall()]
    except Exception as error:
        print(json.dumps({"event": "library_intelligence.suggestions_due_failed", "error": type(error).__name__}), flush=True)
        return {**summary, "status": "error"}
    from .jobs import system_context
    for workspace_id in due:
        try:
            with connect() as db, db.cursor() as cur:
                ctx = system_context(cur, workspace_id)
                if ctx is None:
                    continue
                created = evaluate_suggestions(ctx, {"type": "sweep"})
                summary["workspaces"] += 1
                summary["created"] += len(created)
        except Exception as error:
            summary["errors"] += 1
            print(json.dumps({"event": "library_intelligence.suggestions_sweep_failed", "error": type(error).__name__}), flush=True)
    return summary
