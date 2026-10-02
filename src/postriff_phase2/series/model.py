"""Signature Series: pure logic over workspace state (PRD R-SER-01/02). No I/O, no model call, no clock of its own.

Storage. A series is a campaign of ``kind: "series"`` in ``state.raffi.campaignPlanning.campaigns`` (projected into
``pr_campaigns`` by ``planning_store.sync``). Its goal/audience/facts are set once at creation; everything the series
does lives in ``campaign["series"]`` with its own ``revision``, so ``_apply_brief`` never pauses an automation and the
campaign version (and the trend context digest) never moves. Every list is bounded (``MAX_*``).

Rules kept here, deterministic and testable:
- originals are read, never written: a post origin is a verified job, a source origin an active source with approved
  facts; episodes keep lineage (origin kind, id, content digest) and reference drafts, never copy them;
- an episode has one role (explanation, worked example, case study, FAQ, update) and one angle; a new episode never
  repeats an angle already in the series, a rejected angle, or a role the person said not to repeat; translations
  and other versions of the same episode attach to that episode instead of becoming new ones;
- every claim names its support (post or source fact) with that support's version and a review-by date; missing,
  changed, withdrawn, deleted or expired support makes the episode ``needs_fact_review``: it cannot be approved, an
  automation following the series skips it, and its linked drafts carry an unknown that Queue refuses to schedule;
- exact duplicates (normalised text digest) of the original, a published post or another episode's draft are refused;
  near duplicates (character trigrams, so CJK-safe) are warnings a person acknowledges;
- angle decisions live in the scoped, revocable overlay store (``memoryType: "strategy"``, scope ``seriesId``) when
  workspace memory is on and the person may write it, otherwise on the series record; the next plan reads both.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

from postriff_alpha.domain import AlphaError, uid

from ..contracts import digest

SCHEMA = "rafii.series.v1"
FLAG = "RAFII_SERIES_ENABLED"
ROLES = ("explanation", "worked_example", "case_study", "faq", "update")
STATUSES = ("active", "paused", "completed", "archived")
# pr_campaigns.status allows needs_input|draft|active|completed|cancelled; "draft" would read as a campaign gap.
CAMPAIGN_STATUS = {"active": "active", "paused": "active", "completed": "completed", "archived": "cancelled"}
EPISODE_STATES = ("planned", "approved", "drafting", "drafted", "skipped")
DECISIONS = ("accept", "reject", "do_not_repeat")
CLAIM_ACTIONS = ("reviewed", "update", "remove")
MIN_PLAN, MAX_PLAN, DEFAULT_PLAN = 2, 6, 3
MAX_EPISODES = 12          # kept (non-skipped) episodes; older skipped ones are pruned, their decisions stay
MAX_SERIES = 30
MAX_CLAIMS = 12            # per series
MAX_EPISODE_CLAIMS = 3
MAX_DRAFTS = 6             # draft references per episode (versions for other platforms/languages)
MAX_ASSETS = 6
MAX_DECISIONS = 40
MAX_KEYS = 20
MAX_SOURCES = 5
MIN_AGE_DAYS, MAX_AGE_DAYS, DEFAULT_MIN_AGE = 14, 365, 30
REVIEW_MAX_DAYS = 365      # a claim is re-checked at least yearly before it is reused
SIMILAR = 0.6              # reviewable near-duplicate warning (character trigram Jaccard)
ANGLE_SIMILAR = 0.75       # a reworded rejected angle is still the rejected angle
UNKNOWN_PREFIX = "Series fact check:"
DAY = 86400
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
_DAY_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CLOSERS = "」』”\"’'）)]"
_INJECTION = None


def enabled(values=None) -> bool:
    """RAFII_SERIES_ENABLED, default off; read from the same isolated environment as the coworker flags."""
    from ..coworker import flags
    return flags._truthy(flags._source(values).get(FLAG, ""))


def require_enabled():
    if not enabled():
        raise AlphaError("This feature is not available.", 404, code="feature_disabled")


# --- text ---------------------------------------------------------------------------------------------------------
def normalize_text(text) -> str:
    """NFKC, case-folded, letters and numbers only: punctuation, spacing and emoji never make a copy look new."""
    value = unicodedata.normalize("NFKC", text if isinstance(text, str) else "").casefold()
    return "".join(ch for ch in value if unicodedata.category(ch)[0] in "LN")


def text_digest(text) -> str:
    return digest({"normalized": normalize_text(text)})


def similarity(a, b):
    """Character-trigram Jaccard (code points, so CJK-safe), from Post Doctor; None when either side is empty."""
    from ..growth.post_doctor import similarity_recent
    return similarity_recent(a or "", [b or ""])


def _injection(text):
    global _INJECTION
    if _INJECTION is None:
        from ..coworker.research_broker import INJECTION_PATTERNS
        _INJECTION = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
    return any(p.search(text) for p in _INJECTION)


def sentences(text):
    """Sentences, CJK-aware: split after 。！？ (and their closing quotes) always, after . ! ? only before a space."""
    out, buf, chars = [], [], text if isinstance(text, str) else ""
    i = 0

    def flush():
        value = " ".join("".join(buf).split()).strip(" -•")
        buf.clear()
        if value:
            out.append(value)
    while i < len(chars):
        ch = chars[i]
        if ch == "\n":
            flush()
        else:
            buf.append(ch)
            if ch in "。！？!?.":
                while i + 1 < len(chars) and chars[i + 1] in _CLOSERS:
                    i += 1
                    buf.append(chars[i])
                if ch in "。！？" or i + 1 >= len(chars) or chars[i + 1].isspace():
                    flush()
        i += 1
    flush()
    return out


def is_cjk(text) -> bool:
    letters = [ch for ch in text or "" if unicodedata.category(ch)[0] == "L"]
    return bool(letters) and sum(1 for ch in letters if "぀" <= ch <= "鿿" or "豈" <= ch <= "﫿") / len(letters) > 0.3


_QUOTE = re.compile(r"[“\"「『]([^”\"」』]{8,300})[”\"」』]")
_DIGIT = re.compile(r"\d")
_DATEISH = re.compile(r"\b(?:19|20)\d{2}\b|\d{1,2}\s*月|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_IMPERATIVE = re.compile(r"^(?:please\s+)?(?:spend|try|start|begin|practi[sc]e|use|set|write|read|do|pick|choose|make|take|ask|focus|keep|add|play|listen|record|plan|check|repeat|count)\b", re.I)
_HOW_TO = re.compile(r"\bhow to\b|\bsteps?\b|分鐘|步驟|先|試|開始|方法|練習|每天|做法", re.I)
_TIME_SENSITIVE = re.compile(r"[$€£¥%]|\b(?:now|today|this (?:week|month|year)|until|ends?|deadline|price|pricing|discount|sale|limited|early[- ]bird)\b|截至|今年|目前|優惠|價|限時|截止|早鳥", re.I)
_CASE = re.compile(r"\b(?:student|client|customer|case|patient|member|for example)\b|學生|學員|客戶|個案|例如", re.I)
_MONTHS = {name: number for number, names in enumerate((("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
                                                          ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
                                                          ("oct", "october"), ("nov", "november"), ("dec", "december")), 1) for name in names}
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATES = (
    (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"), ("y", "m", "d")),
    (re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号]"), ("y", "m", "d")),
    (re.compile(r"\b" + _MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I), ("mon", "d", "y")),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+(20\d{2})\b", re.I), ("d", "mon", "y")),
)


def actionable(sentence) -> bool:
    """An instruction someone can follow (an imperative opening, or a how-to cue): material for a worked example."""
    return bool(_IMPERATIVE.search(sentence.strip()) or _HOW_TO.search(sentence))


def claim_type(text) -> str:
    """Same order as the fact pack: quote, statistic, event, statement."""
    if _QUOTE.search(text):
        return "quote"
    if _DIGIT.search(text):
        return "statistic"
    if _DATEISH.search(text):
        return "event"
    return "statement"


def dates_in(text):
    """Full calendar dates written in the text (ISO, slashes, 年月日, English month names)."""
    found = []
    for pattern, order in _DATES:
        for match in pattern.finditer(text or ""):
            parts = dict(zip(order, match.groups()))
            try:
                month = _MONTHS[parts["mon"].lower()[:3]] if "mon" in parts else int(parts["m"])
                found.append(dt.date(int(parts["y"]), month, int(parts["d"])))
            except (KeyError, ValueError):
                continue
    return sorted(set(found))


def _day(now) -> dt.date:
    return dt.datetime.fromtimestamp(now, dt.timezone.utc).date()


def parse_day(value):
    if not isinstance(value, str) or not _DAY_TEXT.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _epoch(value) -> float:
    from ..campaigns import _epoch as epoch
    return epoch(value)


def default_review_by(text, kind, base: dt.date) -> str:
    """The base date plus the fact pack's freshness window for this kind (at most a year), or an earlier date the
    claim itself names after the base (a deadline or event day): `ends September 15, 2026` expires then."""
    from ..coworker.fact_pack import FRESH_DAYS
    limit = base + dt.timedelta(days=min(FRESH_DAYS.get(kind, 365), REVIEW_MAX_DAYS))
    named = [day for day in dates_in(text) if day >= base]
    return min([limit] + named).isoformat()


# --- lookups ------------------------------------------------------------------------------------------------------
def planning(state) -> dict:
    """The campaign planning state, read-only (absent parts read as empty)."""
    return ((state.get("raffi") or {}).get("campaignPlanning") or {})


def planning_root(state) -> dict:
    """The campaign planning state for a write (created when missing, as campaigns._root)."""
    return state.setdefault("raffi", {}).setdefault("campaignPlanning", {"campaigns": [], "recurringTasks": [], "occurrences": []})


def all_series(state):
    root = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    return [c for c in root.get("campaigns") or [] if isinstance(c, dict) and c.get("kind") == "series" and isinstance(c.get("series"), dict)]


def find(state, series_id, *, required=True):
    found = next((c for c in all_series(state) if c.get("id") == series_id), None) if isinstance(series_id, str) else None
    if found is None and required:
        raise AlphaError("Series unavailable.", 404)
    return found


def episode_of(series, episode_id, *, required=True):
    found = next((e for e in series.get("episodes") or [] if e.get("id") == episode_id), None)
    if found is None and required:
        raise AlphaError("Episode unavailable.", 404)
    return found


def claim_of(series, claim_id, *, required=True):
    found = next((c for c in series.get("claims") or [] if c.get("id") == claim_id), None)
    if found is None and required:
        raise AlphaError("That fact is not part of this series.", 404)
    return found


def _jobs(state):
    return [j for j in (state.get("phase2") or {}).get("jobs") or [] if isinstance(j, dict)]


def _job(state, job_id):
    return next((j for j in _jobs(state) if j.get("id") == job_id), None)


def _source(state, source_id):
    return next((s for s in state.get("sources") or [] if isinstance(s, dict) and s.get("id") == source_id), None)


def _variant(state, variant_id):
    return next((v for v in state.get("variants") or [] if isinstance(v, dict) and v.get("id") == variant_id), None)


def job_text(job) -> str:
    return str(((job or {}).get("manifest") or {}).get("payload", {}).get("text") or "").strip()


def verified_at(job):
    at = ((job or {}).get("verification") or {}).get("at")
    return at if (job or {}).get("state") == "verified" and isinstance(at, (int, float)) else None


def source_version(source) -> str:
    """Content fingerprint plus the approved facts: re-approving different facts is a new version."""
    from ..source_policy import facts_digest
    return digest({"fingerprint": (source or {}).get("fingerprint"), "facts": facts_digest(source or {})})[:16]


def approved_facts(source):
    return [f for f in (source or {}).get("facts") or [] if isinstance(f, dict) and f.get("approved") and str(f.get("text") or "").strip()]


def eligible_post(state, job_id, now, min_age_days):
    """Evergreen eligibility: a verified post with text, at least `min_age_days` old."""
    job = _job(state, job_id)
    at = verified_at(job)
    if job is None or at is None or not job_text(job):
        raise AlphaError("Choose a published post from this workspace.", 404)
    if at > now - min_age_days * DAY:
        raise AlphaError(f"Choose a post published at least {min_age_days} days ago.", 409, code="unsupported_input")
    return job


def usable_source(state, source_id):
    source = _source(state, source_id)
    if source is None or not source.get("active") or source.get("kind") == "voice_sample":
        raise AlphaError("That source is not available in this workspace.", 404, code="source_unavailable")
    if not approved_facts(source):
        raise AlphaError("Approve at least one fact in this source first.", 409, code="approval_required")
    return source


def origin_text(state, origin):
    """The original's current text, or None when it is gone (deleted, withdrawn, no approved facts)."""
    if origin.get("kind") == "post":
        job = _job(state, origin.get("id"))
        return job_text(job) if verified_at(job) is not None else None
    source = _source(state, origin.get("id"))
    if source is None or not source.get("active"):
        return None
    facts = approved_facts(source)
    return "\n".join(str(f["text"]).strip() for f in facts) if facts else None


def prior_use(state, *, exclude_task=None):
    """Where each published post was already reused: evergreen automations (any task but `exclude_task`) and series
    origins. {jobId: [{"kind", "id"}]} — a second use is never blind."""
    out = {}
    for task in planning(state).get("recurringTasks") or []:
        if task.get("id") == exclude_task:
            continue
        for job_id in task.get("evergreenUsed") or []:
            if isinstance(job_id, str) and not job_id.startswith("episode:"):
                out.setdefault(job_id, []).append({"kind": "automation", "id": task.get("id")})
    for campaign in all_series(state):
        origin = campaign["series"].get("origin") or {}
        if origin.get("kind") == "post" and campaign["series"].get("status") != "archived":
            out.setdefault(origin.get("id"), []).append({"kind": "series", "id": campaign["id"]})
    return out


# --- claims -------------------------------------------------------------------------------------------------------
def _claim(text, support, base, review_by=None):
    text = " ".join(str(text).split())[:280]
    kind = claim_type(text)
    return {"id": "cl_" + digest({"support": [support.get("kind"), support.get("id"), support.get("factId")], "text": text})[:12], "text": text,
            "claimType": kind, "support": support, "reviewBy": review_by or default_review_by(text, kind, base), "status": "supported"}


def analyze(text):
    """Questions, claim sentences and planning signals of an original (instruction-like text is dropped as data)."""
    questions, claims, flagged = [], [], 0
    for sentence in sentences(text):
        if _injection(sentence):
            flagged += 1
            continue
        if "?" in sentence or "？" in sentence:
            if len(sentence) >= 4:
                questions.append(sentence[:200])
        elif len(sentence) >= 8:
            claims.append(sentence)
    joined = " ".join(claims)
    return {"questions": questions[:3], "claims": claims, "injectionFlags": flagged,
            "signals": {"question": bool(questions), "howTo": any(actionable(c) for c in claims),
                        "timeSensitive": bool(_TIME_SENSITIVE.search(joined) or any(dates_in(c) for c in claims)),
                        "case": bool(_CASE.search(joined) or any(_QUOTE.search(c) for c in claims))}}


def origin_claims(state, origin, now, review_by=None):
    """Claims of the original with their support version. `review_by` (YYYY-MM-DD) overrides the default dates."""
    if origin["kind"] == "post":
        job = _job(state, origin["id"])
        base = _day(verified_at(job) or now)
        found = analyze(job_text(job))
        support = {"kind": "post", "id": origin["id"], "version": origin["contentDigest"][:16]}
        return found, [_claim(text, support, base, review_by) for text in found["claims"]]
    source = _source(state, origin["id"])
    base = _day(_epoch(source.get("reviewedAt") or source.get("createdAt")) or now)
    claims = []
    for fact in approved_facts(source):
        support = {"kind": "source", "id": source["id"], "factId": fact.get("id"), "version": source_version(source)}
        claims.append(_claim(fact["text"], support, base, review_by))
    return analyze("\n".join(str(f["text"]) for f in approved_facts(source))), claims


def source_claims(source, now, review_by=None):
    base = _day(_epoch(source.get("reviewedAt") or source.get("createdAt")) or now)
    return [_claim(f["text"], {"kind": "source", "id": source["id"], "factId": f.get("id"), "version": source_version(source)}, base, review_by)
            for f in approved_facts(source)]


def claim_state(state, claim, today):
    """(state, detail): ok | removed | source_unavailable | missing_support | source_changed | expired."""
    if claim.get("status") == "removed":
        return "removed", None
    support = claim.get("support") or {}
    if support.get("kind") == "post":
        job = _job(state, support.get("id"))
        if verified_at(job) is None:
            return "source_unavailable", "deleted"
        if text_digest(job_text(job))[:16] != support.get("version"):
            return "source_changed", None
    elif support.get("kind") == "source":
        source = _source(state, support.get("id"))
        if source is None:
            return "source_unavailable", "deleted"
        if not source.get("active"):
            return "source_unavailable", "withdrawn"
        fact = next((f for f in source.get("facts") or [] if f.get("id") == support.get("factId")), None)
        if support.get("factId") and (fact is None or not fact.get("approved")):
            return "missing_support", None
        if source_version(source) != support.get("version"):
            return "source_changed", None
    elif support.get("kind") != "user":
        # "user": a fact the person corrected and stated themselves; only its review date applies.
        return "missing_support", None
    review_by = parse_day(claim.get("reviewBy"))
    if review_by is None:
        return "missing_support", None
    if today > review_by:
        return "expired", claim["reviewBy"]
    return "ok", None


REASON_CODES = {"expired": "claim_expired", "source_unavailable": "source_unavailable", "missing_support": "missing_support", "source_changed": "source_changed"}


def episode_issues(state, series, episode, today):
    """[(claim, state, detail)] for the episode's claims that need a fact review."""
    issues = []
    for claim_id in episode.get("claimIds") or []:
        claim = claim_of(series, claim_id, required=False)
        if claim is None:
            continue
        found, detail = claim_state(state, claim, today)
        if found not in ("ok", "removed"):
            issues.append((claim, found, detail))
    return issues


def fact_state(state, series, episode, today) -> str:
    return "needs_fact_review" if episode_issues(state, series, episode, today) else "ok"


# --- decisions (scoped, revocable preferences) --------------------------------------------------------------------
def decision_active(state, decision) -> bool:
    if decision.get("status") != "active":
        return False
    if decision.get("storage") != "overlay":
        return True
    from ..coworker import overlays
    item = next((i for i in overlays.scoped_items(state, "strategy", seriesId=decision.get("seriesId")) if i.get("id") == decision.get("overlayId")), None)
    return bool(item and item.get("status") == "active")


def active_decisions(state, campaign):
    return [d for d in campaign["series"].get("decisions") or [] if decision_active(state, d)]


def preferences(state, campaign):
    """What the next plan honours: excluded angle keys (and their texts, for reworded repeats), blocked roles,
    accepted roles first, and which decision ids shaped it."""
    out = {"excludedKeys": set(), "excludedTexts": [], "blockedRoles": set(), "acceptedRoles": [], "ids": {}}
    for item in active_decisions(state, campaign):
        out["ids"].setdefault(item["role"], []).append(item["id"])
        if item["decision"] == "accept":
            if item["role"] not in out["acceptedRoles"]:
                out["acceptedRoles"].append(item["role"])
        elif item["decision"] == "do_not_repeat" and item.get("level") == "role":
            out["blockedRoles"].add(item["role"])
        else:
            out["excludedKeys"].add(item["angleKey"])
            out["excludedTexts"].append(item.get("angleText") or "")
    return out


def decision_statement(campaign, decision, role, angle_text):
    verb = {"accept": "Prefer", "reject": "Do not use", "do_not_repeat": "Do not repeat"}[decision]
    what = f"the {role.replace('_', ' ')} role" if decision == "do_not_repeat" and angle_text is None else f"the {role.replace('_', ' ')} angle “{angle_text[:120]}”"
    return f"Series “{campaign['series']['title'][:60]}”: {verb} {what}."[:240]


# --- planner ------------------------------------------------------------------------------------------------------
QUESTIONS = {
    "en": {"explanation": "What is it, and why does it matter?", "worked_example": "How do I put it into practice?",
           "case_study": "What does it look like in a real case?", "faq": "What do people ask most often about it?",
           "update": "What has changed since the original?"},
    "zh": {"explanation": "這是甚麼？為甚麼重要？", "worked_example": "實際上可以怎樣做？", "case_study": "真實個案是怎樣的？",
           "faq": "大家最常問甚麼？", "update": "原文發布後有甚麼改變？"},
}
ANGLES = {
    "en": {"explanation": "Explain why this matters: {c}", "worked_example": "Walk through one concrete example of: {c}",
           "case_study": "Show one real case from your own work about: {c}", "faq": "Answer the most common question about: {c}",
           "update": "Revisit what has changed since the original: {c}"},
    "zh": {"explanation": "解釋這點為甚麼重要：{c}", "worked_example": "用一個具體例子示範：{c}", "case_study": "分享一個你自己工作中的真實個案：{c}",
           "faq": "回答關於這點最常見的問題：{c}", "update": "回顧原文發布後的改變：{c}"},
}
ASKED = {"en": "Answer the question people ask: {c}", "zh": "回答大家常問的問題：{c}"}
GENERIC = {
    "en": {"explanation": "the core idea of the original", "worked_example": "putting the original idea into practice", "faq": "the original idea"},
    "zh": {"explanation": "原文的核心意思", "worked_example": "把原文的想法付諸實行", "faq": "原文的想法"},
}


def lang(language) -> str:
    return "zh" if isinstance(language, str) and language.split("-")[0] in ("zh", "yue") else "en"


def role_order(signals, accepted=()):
    """Default order: explanation; a question in the original puts FAQ next, a how-to puts the worked example next;
    update only for time-sensitive material, case study only when the original has a real case to build on. Roles a
    person accepted come first."""
    order = ["explanation"]
    if signals.get("question"):
        order.append("faq")
    if signals.get("howTo"):
        order.append("worked_example")
    for role in ("faq", "worked_example"):
        if role not in order:
            order.append(role)
    if signals.get("timeSensitive"):
        order.append("update")
    if signals.get("case"):
        order.append("case_study")
    first = [role for role in accepted if role in order]
    return first + [role for role in order if role not in first]


def angle_key(role, text) -> str:
    return digest({"role": role, "angle": normalize_text(text)})[:16]


def angle_variants(series, role):
    """Deterministic (text, anchor claim id or None, question) candidates for one role, best first."""
    language = lang(series.get("language"))
    claims = [c for c in series.get("claims") or [] if c.get("status") != "removed"]
    template = ANGLES[language][role]
    excerpt = lambda text: text if len(text) <= 100 else text[:99].rstrip() + "…"
    out = []
    if role == "faq":
        for question in series.get("questions") or []:
            out.append((ASKED[language].format(c=excerpt(question)), None, question[:200]))
    picks = claims
    if role == "worked_example":
        picks = [c for c in claims if actionable(c["text"])] + [c for c in claims if not actionable(c["text"])]
    elif role == "update":
        picks = [c for c in claims if _TIME_SENSITIVE.search(c["text"]) or dates_in(c["text"]) or c["claimType"] in ("statistic", "event")]
    elif role == "case_study":
        picks = [c for c in claims if _CASE.search(c["text"]) or c["claimType"] == "quote"]
    for claim in picks:
        out.append((template.format(c=excerpt(claim["text"])), claim["id"], None))
    if role in GENERIC[language]:
        out.append((template.format(c=GENERIC[language][role]), None, None))
    return out


def _similar_to_any(text, others, threshold):
    return any((similarity(text, other) or 0) >= threshold for other in others if other)


def _episode_claims(series, role, anchor):
    claims = [c for c in series.get("claims") or [] if c.get("status") != "removed"]
    chosen = [anchor] if anchor else []
    if role in ("explanation", "faq", "worked_example") and claims:
        chosen.append(claims[0]["id"])
    elif role == "update":
        chosen += [c["id"] for c in claims if c["claimType"] in ("statistic", "event")]
    return list(dict.fromkeys(chosen))[:MAX_EPISODE_CLAIMS]


def plan(state, campaign, target, now):
    """Add planned episodes until `target` are waiting (planned), honouring the active decisions. Returns the new
    episodes (already appended). Never repeats an angle in the series, a rejected/do-not-repeat angle (or a close
    rewording of it) or a blocked role; roles not yet in the series come before second angles of a used role."""
    series = campaign["series"]
    prefs = preferences(state, campaign)
    episodes = series.setdefault("episodes", [])
    kept = [e for e in episodes if e.get("state") != "skipped"]
    waiting = [e for e in kept if e.get("state") == "planned"]
    room = min(target - len(waiting), MAX_EPISODES - len(kept))
    if room <= 0:
        return []
    order = [r for r in role_order(series.get("signals") or {}, prefs["acceptedRoles"]) if r not in prefs["blockedRoles"]]
    # Set-aside episodes are not "taken": a rejected angle stays out through its decision, so revoking it frees it.
    taken = {e["angle"]["key"] for e in kept}
    anchors = {e.get("anchorClaimId") for e in kept if e.get("anchorClaimId")}
    used = {}
    for e in kept:
        used[e["role"]] = used.get(e["role"], 0) + 1
    language = lang(series.get("language"))
    origin = series.get("origin") or {}
    new = []
    for second_pass in (False, True):
        for role in order:
            if len(new) >= room:
                break
            if not second_pass and used.get(role):
                continue
            # Prefer an anchor fact no episode builds on yet (a stable sort, so the role's own order decides ties).
            for text, anchor, question in sorted(angle_variants(series, role), key=lambda v: v[1] in anchors):
                key = angle_key(role, text)
                if key in taken or key in prefs["excludedKeys"] or _similar_to_any(text, prefs["excludedTexts"], ANGLE_SIMILAR):
                    continue
                index = max([e.get("index", 0) for e in episodes] + [0]) + 1
                accepted = role in prefs["acceptedRoles"]
                episode = {"id": "ep_" + uid()[:12], "index": index, "role": role, "question": question or QUESTIONS[language][role],
                           "angle": {"key": key, "text": text}, "anchorClaimId": anchor, "state": "planned", "angleDecision": None,
                           "claimIds": _episode_claims(series, role, anchor), "draftRefs": [], "assetIds": [],
                           "lineage": {"originKind": origin.get("kind"), "originId": origin.get("id"), "originDigest": origin.get("contentDigest")},
                           "basis": {"reason": "accepted_role" if accepted else ("after_rejection" if prefs["excludedKeys"] else "default"),
                                     "decisionIds": prefs["ids"].get(role, [])[-5:]},
                           "automation": [], "factState": "ok", "createdAt": now, "updatedAt": now}
                episodes.append(episode)
                new.append(episode)
                taken.add(key)
                if anchor:
                    anchors.add(anchor)
                used[role] = used.get(role, 0) + 1
                break
    _prune(series)
    return new


def _prune(series):
    """Keep at most MAX_EPISODES non-skipped episodes plus the four newest skipped ones (decisions keep the rest)."""
    skipped = [e for e in series["episodes"] if e.get("state") == "skipped"]
    drop = {e["id"] for e in skipped[:-4]}
    if drop:
        series["episodes"] = [e for e in series["episodes"] if e["id"] not in drop]


# --- drafts, duplicates, gates ------------------------------------------------------------------------------------
def linked_elsewhere(state, variant_id, episode_id=None):
    """(campaign, episode) already holding this draft, other than `episode_id`."""
    for campaign in all_series(state):
        for episode in campaign["series"].get("episodes") or []:
            if episode.get("id") != episode_id and any(ref.get("variantId") == variant_id for ref in episode.get("draftRefs") or []):
                return campaign, episode
    return None


def draft_checks(state, campaign, episode, variant_id):
    """Refuse an exact duplicate, warn on a near one. {"refusal": {code, message, duplicateOf} | None, "warnings": [...]}."""
    series = campaign["series"]
    variant = _variant(state, variant_id)
    if variant is None:
        raise AlphaError("That draft is not in this workspace.", 404)
    if variant.get("rejected"):
        return {"refusal": {"code": "draft_rejected", "message": "This draft was set aside. Edit it or choose another one."}, "warnings": []}
    if any(ref.get("variantId") == variant_id for ref in episode.get("draftRefs") or []):
        return {"refusal": {"code": "already_linked", "message": "This draft is already part of this episode."}, "warnings": []}
    elsewhere = linked_elsewhere(state, variant_id, episode["id"])
    if elsewhere:
        return {"refusal": {"code": "duplicate_episode", "message": f"This draft is already episode {elsewhere[1].get('index')} of a series. One draft is one episode.",
                            "duplicateOf": {"kind": "episode", "id": elsewhere[1]["id"]}}, "warnings": []}
    text = str(variant.get("text") or "")
    if not normalize_text(text):
        return {"refusal": {"code": "draft_empty", "message": "This draft has no text yet."}, "warnings": []}
    mine = text_digest(text)
    origin = series.get("origin") or {}
    original = origin_text(state, origin)
    if origin.get("kind") == "post" and original and text_digest(original) == mine:
        return {"refusal": {"code": "duplicate_episode", "message": "This draft repeats the original post word for word. An episode needs its own angle.",
                            "duplicateOf": {"kind": "original", "id": origin["id"]}}, "warnings": []}
    for job in _jobs(state):
        if verified_at(job) is not None and text_digest(job_text(job)) == mine:
            return {"refusal": {"code": "duplicate_episode", "message": "This draft is word for word a post you already published.",
                                "duplicateOf": {"kind": "post", "id": job["id"]}}, "warnings": []}
    others = []
    for other_campaign in all_series(state):
        for other in other_campaign["series"].get("episodes") or []:
            for ref in other.get("draftRefs") or []:
                linked = _variant(state, ref.get("variantId"))
                if linked is None or other.get("id") == episode["id"]:
                    continue
                if text_digest(linked.get("text")) == mine:
                    return {"refusal": {"code": "duplicate_episode", "message": f"This draft repeats episode {other.get('index')} word for word.",
                                        "duplicateOf": {"kind": "episode", "id": other["id"]}}, "warnings": []}
                if other_campaign is campaign:
                    others.append((other, linked))
    warnings = []
    if original:
        value = similarity(text, original) or 0
        if value >= SIMILAR:
            warnings.append({"id": f"similar_to_original:{origin.get('id')}", "code": "similar_to_original", "similarity": value, "refId": origin.get("id")})
    for other, linked in others:
        value = similarity(text, linked.get("text")) or 0
        if value >= SIMILAR:
            warnings.append({"id": f"similar_to_episode:{other['id']}", "code": "similar_to_episode", "similarity": value, "refId": other["id"], "index": other.get("index")})
    best = None
    for job in _jobs(state):
        if verified_at(job) is None or (origin.get("kind") == "post" and job.get("id") == origin.get("id")):
            continue
        value = similarity(text, job_text(job)) or 0
        if value >= SIMILAR and (best is None or value > best[0]):
            best = (value, job["id"])
    if best:
        warnings.append({"id": f"similar_to_post:{best[1]}", "code": "similar_to_post", "similarity": best[0], "refId": best[1]})
    return {"refusal": None, "warnings": warnings}


WORDS = {"expired": "its support expired on {detail}", "source_unavailable": "its source was {detail}", "missing_support": "it has no approved supporting fact",
         "source_changed": "its source changed after it was checked"}


def gate_unknown(issues) -> str:
    claim, found, detail = issues[0]
    text = claim["text"] if len(claim["text"]) <= 80 else claim["text"][:79] + "…"
    more = f" (and {len(issues) - 1} more)" if len(issues) > 1 else ""
    reason = WORDS[found].format(detail=detail or "removed")
    return f"{UNKNOWN_PREFIX} “{text}” — {reason}{more}. Update or remove this fact in the series before publishing."


def _strip_gate(variant) -> bool:
    before = list(variant.get("unknowns") or [])
    variant["unknowns"] = [u for u in before if not (isinstance(u, str) and u.startswith(UNKNOWN_PREFIX))]
    return variant["unknowns"] != before


def apply_gates(state, campaign, today) -> int:
    """Gate the linked drafts of every episode that needs a fact review with Queue's own blockers (needsReview and an
    unknown), and lift only the series' own unknown once the facts are fixed. A person who confirmed in Queue that
    this exact draft leaves the detail out (uncertainty review of this revision) is respected. Returns drafts changed."""
    series, changed = campaign["series"], 0
    for episode in series.get("episodes") or []:
        issues = episode_issues(state, series, episode, today)
        episode["factState"] = "needs_fact_review" if issues else "ok"
        episode["factReasons"] = sorted({REASON_CODES[found] for _, found, _ in issues})
        unknown = gate_unknown(issues) if issues else None
        for ref in episode.get("draftRefs") or []:
            variant = _variant(state, ref.get("variantId"))
            if variant is None or variant.get("rejected"):
                continue
            if unknown is None:
                changed += _strip_gate(variant)
                continue
            review = variant.get("uncertaintyReview") or {}
            if unknown in (review.get("excludedFromDraft") or []) and review.get("revision") == variant.get("revision"):
                continue
            if unknown not in (variant.get("unknowns") or []):
                _strip_gate(variant)
                variant["unknowns"] = list(variant.get("unknowns") or []) + [unknown]
                variant["needsReview"] = True
                changed += 1
    return changed


def next_gate_at(state, campaign, today):
    """When the next currently-valid claim of an episode with drafts expires (UTC midnight after its review-by day)."""
    series, best = campaign["series"], None
    for episode in series.get("episodes") or []:
        if not episode.get("draftRefs"):
            continue
        for claim_id in episode.get("claimIds") or []:
            claim = claim_of(series, claim_id, required=False)
            if claim is None or claim_state(state, claim, today)[0] != "ok":
                continue
            day = parse_day(claim.get("reviewBy"))
            at = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), dt.timezone.utc).timestamp()
            best = at if best is None else min(best, at)
    return best


def watch_list(state, campaign):
    """Active sources behind the claims of episodes with drafts, with the review stamp they had: the sweep notices a
    withdrawal, deletion or re-approval without a clock."""
    series, ids = campaign["series"], []
    for episode in series.get("episodes") or []:
        if not episode.get("draftRefs"):
            continue
        for claim_id in episode.get("claimIds") or []:
            claim = claim_of(series, claim_id, required=False)
            support = (claim or {}).get("support") or {}
            if support.get("kind") == "source" and support.get("id") not in ids:
                ids.append(support["id"])
    out = []
    for source_id in ids[:MAX_SOURCES * 2]:
        source = _source(state, source_id)
        if source is not None and source.get("active"):
            out.append({"id": source_id, "reviewedAt": source.get("reviewedAt")})
    return out


def refresh(state, campaign, now) -> int:
    """Recompute everything derived from the clock and the workspace: fact states, Queue gates, the sweep's next
    instant and watched sources, and the campaign status. Returns the number of drafts whose gate changed."""
    today = _day(now)
    changed = apply_gates(state, campaign, today)
    series = campaign["series"]
    series["nextGateAt"] = next_gate_at(state, campaign, today)
    series["watch"] = watch_list(state, campaign)
    campaign["status"] = CAMPAIGN_STATUS[series.get("status", "active")]
    return changed


# --- idempotency / revision -----------------------------------------------------------------------------------------
def check_key(value):
    if not isinstance(value, str) or not _KEY.match(value):
        raise AlphaError("Send an idempotency key (8–80 letters, digits, '-', '_', '.' or ':').", 400)
    return value


def replay(series, key, request):
    """True when this key already applied this exact request; a key reused for a different request is a conflict."""
    for entry in series.get("keys") or []:
        if entry.get("key") == key:
            if entry.get("request") != request:
                raise AlphaError("This idempotency key was already used for a different request.", 409, code="idempotency_conflict")
            return True
    return False


def remember(series, key, request, op, now):
    series["keys"] = (list(series.get("keys") or []) + [{"key": key, "request": request, "op": op, "at": now}])[-MAX_KEYS:]


def check_revision(series, expected):
    if type(expected) is not int:
        raise AlphaError("Send the series revision you are changing (expectedRevision).", 400)
    if expected != series.get("revision"):
        raise AlphaError("This series changed. Read the current version first.", 409, code="revision_conflict")


def touch(campaign, actor, now):
    series = campaign["series"]
    series["revision"] = int(series.get("revision", 1)) + 1
    series["updatedAt"], series["updatedBy"] = now, actor
    campaign["updatedAt"] = now


# --- evergreen ------------------------------------------------------------------------------------------------------
_DEAD = ("cancelled", "missed", "held", "failed")


def _automation_live(state, episode):
    refs = {item.get("occurrenceId") for item in episode.get("automation") or []}
    return any(o.get("id") in refs and o.get("state") not in _DEAD for o in planning(state).get("occurrences") or [])


def automation_ready(state, campaign, episode, today):
    """The approved episode an automation may draft now: approved (or drafting with no live run), facts in order."""
    if episode.get("state") not in ("approved", "drafting") or episode.get("draftRefs"):
        return False
    if episode.get("state") == "drafting" and _automation_live(state, episode):
        return False
    return fact_state(state, campaign["series"], episode, today) == "ok"


def evergreen_episode(state, task, config, now):
    """Evergreen following a series: the series' approved episode as the run's older material (same evergreen slot in
    the run context, so no second reshare engine), or None when nothing is approved, its facts need a review, the
    series is paused/finished, or series are switched off."""
    if not enabled():
        return None
    campaign = find(state, config.get("seriesId"), required=False)
    if campaign is None or campaign["series"].get("status") != "active":
        return None
    series, today = campaign["series"], _day(now)
    origin = series.get("origin") or {}
    text = origin_text(state, origin)
    if not text:
        return None
    for episode in sorted(series.get("episodes") or [], key=lambda e: e.get("index", 0)):
        if not automation_ready(state, campaign, episode, today):
            continue
        claims = [c["text"] for c in (claim_of(series, i, required=False) for i in episode.get("claimIds") or []) if c and c.get("status") != "removed"]
        return {"jobId": origin.get("id") if origin.get("kind") == "post" else None, "platform": origin.get("platform"),
                "publishedAt": origin.get("publishedAt"), "text": text[:600], "seriesId": campaign["id"], "episodeId": episode["id"],
                "episode": {"index": episode.get("index"), "role": episode["role"], "angle": episode["angle"]["text"],
                            "question": episode.get("question"), "claims": claims}}
    return None


def mark_drafting(state, series_id, episode_id, task_id, occurrence_id, now):
    """An automation run took this approved episode: it stays one episode, drafted once, until a draft is linked."""
    campaign = find(state, series_id, required=False)
    episode = episode_of(campaign["series"], episode_id, required=False) if campaign else None
    if episode is None:
        return False
    episode["state"] = "drafting"
    episode["automation"] = (list(episode.get("automation") or []) + [{"taskId": task_id, "occurrenceId": occurrence_id, "at": now}])[-5:]
    episode["updatedAt"] = now
    touch(campaign, None, now)
    return True


def followable(state, series_id, kept=None):
    """An automation may follow an existing, unarchived series (validated when the automation is saved). With the
    series feature off (D-012: admission stops) a new follow is refused, but the follow *this* automation already has
    (`kept`, its saved seriesId) is kept, so saving it still works while the person can clear the follow. Another
    automation following the same series never lets a new one start."""
    if not enabled():
        if kept == series_id and followers(state, series_id):
            return find(state, series_id, required=False)
        require_enabled()
    campaign = find(state, series_id, required=False)
    if campaign is None or campaign["series"].get("status") == "archived":
        raise AlphaError("Choose a series from this workspace.", 409)
    return campaign


def followers(state, series_id):
    return [t.get("id") for t in planning(state).get("recurringTasks") or []
            if t.get("status") != "cancelled" and ((t.get("include") or {}).get("evergreen") or {}).get("seriesId") == series_id]
