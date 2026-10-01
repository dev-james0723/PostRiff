"""Pure brief composition (PRD R-BRF-01/02): 0–3 actionable opportunities from stored candidates.

Inputs are normalized candidates (``sources``: the Social Trend weekly pool, open listening opportunities and stored
Radar scans), the recipient's context (goals, their own material, angles already planned) and their action history.
Nothing here reads a provider, a model or the network. Ordering favours what the person can credibly address
(their own material), audience questions, goal fit and recency; it never uses source popularity or a model score.

Zero items is a valid edition. A candidate without a known retrieval time (or a verified, unexpired stored
projection) is not "fresh"; a whitespace candidate without its observed-gap evidence is not shown at all.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFINITION_VERSION = "rafii.brief.v1.2026-10-01"
MAX_ITEMS = 3
MAX_AGE_SECONDS = 7 * 86400        # stored evidence retrieved longer ago than this is stale for a brief
DISMISS_COOLDOWN = 7 * 86400       # a dismissed item may come back after a week; "not relevant" stays out until restored
SOURCES = ("trends", "listening", "radar")
SOURCE_ORDER = {name: index for index, name in enumerate(SOURCES)}
EFFORTS = ("quick", "medium", "deep")
ACTIONS = ("accept", "save_idea", "dismiss", "not_relevant", "restore")
OPEN_ACTIONS = ("accept", "save_idea")      # the one supported action an item carries
REASONS = {"dismiss": ("not_now", "already_covered", "too_much_effort", "other"),
           "not_relevant": ("wrong_topic", "wrong_audience", "wrong_platform", "low_quality_source", "other")}
CADENCES = ("weekly", "daily")
SHORT_PLATFORMS = {"x", "threads", "bluesky", "mastodon"}
_QUESTION = re.compile(r"[?？]\s*$|^\s*(how|what|why|when|which|who|can|should|is|are|does|do)\b|嗎|如何|為什麼|为什么|怎麼|怎么", re.I)
_LATIN = re.compile(r"[a-z0-9]{3,}")
_CJK = re.compile(r"[㐀-鿿豈-﫿]+")
_STOP = {"the", "and", "for", "with", "your", "you", "this", "that", "from", "are", "was", "were", "has", "have", "not", "but",
         "what", "why", "how", "who", "can", "will", "about", "into", "over", "more", "most", "post", "posts", "new", "our",
         "source", "note", "idea", "ideas"}


# --- small pure helpers ------------------------------------------------------------------------------------------------
def zone(name):
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _midnight(day, tz):
    return datetime.combine(day, dtime(0), tzinfo=tz).timestamp()


def edition_window(now, zone_name):
    """(edition key, period start, period end): the ISO week of `now` in the recipient's zone, Monday 00:00 to the
    next Monday 00:00 local, resolved on the actual dates (DST-safe; a 23/25-hour day stays one day)."""
    tz = zone(zone_name)
    local = datetime.fromtimestamp(now, tz).date()
    monday = local - timedelta(days=local.weekday())
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}", _midnight(monday, tz), _midnight(monday + timedelta(days=7), tz)


def local_day(now, zone_name):
    tz = zone(zone_name)
    day = datetime.fromtimestamp(now, tz).date()
    return _midnight(day, tz), _midnight(day + timedelta(days=1), tz)


def tokens(text):
    text = str(text or "").lower()
    found = {t for t in _LATIN.findall(text) if t not in _STOP}
    for run in _CJK.findall(text):
        found |= {run[i:i + 2] for i in range(max(1, len(run) - 1))} if len(run) > 1 else set()
    return found


def item_id(source, source_ref):
    return "bi_" + hashlib.sha256(f"{source}:{source_ref}".encode()).hexdigest()[:20]


def is_question(title):
    return bool(_QUESTION.search(str(title or "")))


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


# --- relevance ---------------------------------------------------------------------------------------------------------
def relevance(candidate, context):
    """Why this item is relevant to this person, from their goals, their own material and declared interests.
    Returns {"matches": [...], "reason", "credible", "goal"}; no match means the item is not shown. Goal and
    material matching read the item's own content only (title and stored content text), never Rafii's angle
    template or the watch query, so a declared interest can't masquerade as a match with the person's material."""
    text = tokens(" ".join(str(candidate.get(k) or "") for k in ("title", "matchText")))
    matches = []
    for source in context.get("material") or []:
        if tokens(source.get("title")) & text:
            matches.append({"kind": "material", "label": str(source.get("title") or "")[:80], "ref": source.get("id")})
            break
    for goal in context.get("goals") or []:
        if tokens(goal) & text:
            matches.append({"kind": "goal", "label": str(goal)[:80]})
            break
    if context.get("brand") and tokens(context["brand"]) & text:
        matches.append({"kind": "brand", "label": str(context["brand"])[:80]})
    for interest in candidate.get("interests") or []:
        if interest.get("label"):
            matches.append({"kind": "interest", "label": str(interest["label"])[:80], "via": interest.get("via")})
            break
    fit = candidate.get("fit") or {}
    if any(isinstance(fit.get(k), dict) and fit[k].get("assessment") == "supported" for k in ("audience", "brand")):
        matches.append({"kind": "fit", "label": "stored workspace-fit assessment"})
    first = matches[0] if matches else None
    reason = None
    if first:
        reason = {"material": "Builds on your own material “{label}”.", "goal": "Matches your goal “{label}”.", "brand": "Matches your brand subject “{label}”.",
                  "interest": "Matches what you asked Rafii to watch: “{label}”.", "fit": "A stored workspace-fit assessment rates its audience relevance as supported."}[first["kind"]].format(label=first["label"])
    return {"matches": matches[:3], "reason": reason, "credible": any(m["kind"] == "material" for m in matches),
            "goal": any(m["kind"] == "goal" for m in matches)}


def effort(candidate):
    hint = candidate.get("effortHint")
    if hint in EFFORTS:
        return hint
    platforms = {str(p).lower() for p in candidate.get("platforms") or []}
    if candidate.get("kind") == "whitespace" or len(candidate.get("evidence") or []) >= 3:
        return "deep"
    if platforms and platforms <= SHORT_PLATFORMS:
        return "quick"
    return "medium"


# --- history -----------------------------------------------------------------------------------------------------------
def latest_actions(rows):
    """rows: [{source, sourceRef, action, at, seq}] in any order → {(source, ref): latest row}. Actions recorded at the
    same instant keep their recorded order (seq), never an id's random order."""
    latest = {}
    for row in sorted(rows, key=lambda r: (r.get("at") or 0, r.get("seq") or 0)):
        latest[(row["source"], row["sourceRef"])] = row
    return latest


def _history_reason(candidate, latest, now):
    row = latest.get((candidate["source"], candidate["sourceRef"]))
    if not row or row["action"] == "restore":
        return None
    if row["action"] == "not_relevant":
        return "not_relevant"
    if row["action"] == "dismiss":
        return "dismissed" if now - (row.get("at") or 0) < DISMISS_COOLDOWN else None
    return "acted"


def _disqualified(candidate, latest, now):
    if candidate.get("source") not in SOURCES or not str(candidate.get("title") or "").strip() or not candidate.get("sourceRef"):
        return "invalid"
    if (candidate.get("action") or {}).get("kind") not in OPEN_ACTIONS:
        return "unsupported_action"
    expires = candidate.get("expiresAt")
    if isinstance(expires, (int, float)) and expires <= now:
        return "expired"
    retrieved = candidate.get("retrievedAt")
    if not isinstance(retrieved, (int, float)):
        if candidate.get("freshnessBasis") != "verified_unexpired_projection":
            return "retrieval_time_unknown"
    elif now - retrieved > MAX_AGE_SECONDS:
        return "stale"
    if candidate.get("kind") == "whitespace" and not candidate.get("gapEvidence"):
        return "whitespace_without_evidence"
    if candidate.get("unsafe"):
        return "unsafe_source_text"
    if candidate.get("lowConfidence"):
        return "low_confidence"
    fit = candidate.get("fit") or {}
    if any(isinstance(value, dict) and value.get("assessment") == "concern" for value in fit.values()):
        return "fit_concern"
    return _history_reason(candidate, latest, now)


# --- composition -------------------------------------------------------------------------------------------------------
def _item(candidate, rel):
    evidence = [{"url": e.get("url"), "ref": str(e.get("ref"))[:120] if e.get("ref") else None, "label": str(e.get("label") or "")[:80] or None,
                 "publishedAt": e.get("publishedAt"), "retrievedAt": e.get("retrievedAt")}
                for e in (candidate.get("evidence") or [])[:3]]
    return {"id": item_id(candidate["source"], candidate["sourceRef"]), "source": candidate["source"], "sourceRef": str(candidate["sourceRef"])[:200],
            "sourceRevision": str(candidate.get("sourceRevision") or "1")[:64], "kind": candidate.get("kind") or "signal",
            "title": " ".join(str(candidate["title"]).split())[:160], "excerpt": (" ".join(str(candidate.get("excerpt")).split())[:240] or None) if candidate.get("excerpt") else None,
            "evidence": evidence, "gapEvidence": list(candidate.get("gapEvidence") or [])[:6] if candidate.get("kind") == "whitespace" else [],
            "publishedAt": candidate.get("publishedAt"), "retrievedAt": candidate.get("retrievedAt"), "expiresAt": candidate.get("expiresAt"),
            "freshnessBasis": "retrieved_at" if isinstance(candidate.get("retrievedAt"), (int, float)) else candidate.get("freshnessBasis"),
            "dataMode": "stored", "coverage": candidate.get("coverage") or {"availability": "unknown"},
            "relevance": {"reason": rel["reason"], "matches": rel["matches"]},
            "angle": {"id": (candidate.get("angle") or {}).get("id"), "text": " ".join(str((candidate.get("angle") or {}).get("text") or "").split())[:240]},
            "effort": effort(candidate), "action": dict(candidate["action"]),
            "platforms": [str(p)[:30] for p in (candidate.get("platforms") or [])][:6], "language": candidate.get("language"),
            "limitations": [str(x)[:200] for x in (candidate.get("limitations") or [])][:3]}


def compose(candidates, context, history, now, limit=MAX_ITEMS):
    """{"items": 0–limit items, "considered": n, "excluded": {reason: count}}. Deterministic for the same inputs."""
    latest = latest_actions(history or [])
    excluded, eligible, seen_refs = Counter(), [], set()
    for candidate in candidates:
        reason = _disqualified(candidate, latest, now)
        key = (candidate.get("source"), candidate.get("sourceRef"))
        if reason is None and key in seen_refs:
            reason = "duplicate_item"
        if reason:
            excluded[reason] += 1
            continue
        seen_refs.add(key)
        rel = relevance(candidate, context)
        if not rel["matches"]:
            excluded["no_relevance"] += 1
            continue
        eligible.append((candidate, rel))

    def rank(entry):
        candidate, rel = entry
        recency = candidate.get("publishedAt") if isinstance(candidate.get("publishedAt"), (int, float)) else candidate.get("retrievedAt") or 0
        return (not rel["credible"], candidate.get("kind") != "question", not rel["goal"], -float(recency or 0),
                SOURCE_ORDER.get(candidate["source"], 9), item_id(candidate["source"], candidate["sourceRef"]))

    planned = {_norm(a) for a in context.get("recentAngles") or [] if _norm(a)}
    chosen, chosen_meta = [], []
    for candidate, rel in sorted(eligible, key=rank):
        angle = _norm((candidate.get("angle") or {}).get("text"))
        topic = tokens(candidate["title"])
        urls = {e.get("url") for e in candidate.get("evidence") or [] if e.get("url")}
        if angle and angle in planned:
            excluded["already_planned"] += 1
            continue
        if any(angle and angle == a or _jaccard(topic, t) >= 0.6 or (urls & u) for a, t, u in chosen_meta):
            excluded["duplicate_topic"] += 1
            continue
        if len(chosen) >= limit:
            excluded["over_limit"] += 1
            continue
        chosen.append(_item(candidate, rel))
        chosen_meta.append((angle, topic, urls))
    return {"items": chosen, "considered": len(candidates), "excluded": dict(excluded)}


def material_digest(items):
    """What makes two editions materially different: which source items (and their revisions), their effort and
    action. Titles, wording and coverage text are cosmetic and never re-alert."""
    material = [[i["source"], i["sourceRef"], i["sourceRevision"], i["effort"], i["action"].get("kind"), (i.get("angle") or {}).get("id")] for i in items]
    return hashlib.sha256(json.dumps(sorted(material, key=json.dumps), separators=(",", ":")).encode()).hexdigest()


def data_state(coverage):
    states = [c.get("state") for c in coverage]
    if not any(s in ("available", "empty", "stale") for s in states):
        return "unavailable"
    return "partial" if "unavailable" in states else "available"


# --- delivery (PRD R-BRF-02) -----------------------------------------------------------------------------------------
def delivery_decision(*, items, new_items, cadence, edition_delivered, delivered_today):
    """Whether this stored revision may alert its recipient (None) or why not: never for an empty edition or one with
    nothing the person was not already told about; weekly cadence alerts once per edition; every cadence at most
    once per recipient per local day. Preferences (quiet hours, mute, unsubscribe, digest) are applied afterwards by
    the notification planner, and they win."""
    if cadence not in CADENCES:
        raise ValueError(cadence)
    if items <= 0:
        return "empty_edition"
    if cadence == "weekly" and edition_delivered:
        return "edition_already_delivered"
    if new_items <= 0:
        return "no_new_items"
    if delivered_today:
        return "daily_cap"
    return None


COPY = {
    "en": {"title": "{n} opportunities to consider this week", "title_one": "1 opportunity to consider this week",
           "why": "From stored sources matched to your goals and material. Nothing is drafted or published until you choose."},
    "zh-Hant": {"title": "本週有 {n} 個值得考慮的機會", "title_one": "本週有 1 個值得考慮的機會",
                "why": "根據已儲存的資料來源，配合你的目標與素材整理。在你選擇之前，不會撰寫或發佈任何內容。"},
}


def copy_locale(locale):
    value = str(locale or "").lower()
    return "zh-Hant" if value.startswith(("zh", "yue")) else "en"


def notification_copy(locale, count):
    strings = COPY[copy_locale(locale)]
    return {"title": strings["title_one"] if count == 1 else strings["title"].format(n=count), "why": strings["why"]}
