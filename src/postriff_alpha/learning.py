"""Learned writing preferences: the part of memory that changes as the person edits and decides.

Preference-learning design (docs/postriff-preference-learning.md), decision A1: a learned
preference lives in `state["learning"]` under its own style revision, never in the voice profile.
Approvals bind the exact text and the voice revision (`build_manifest`, `current()`), so
remembering a preference must not hold a scheduled job or force a draft to regenerate; it only
shapes the next draft. A preference describes form (length, openings, hashtags, how a post
closes), never a fact, a credential or an experience.

Nothing here proposes anything by itself. Server code creates proposals through `propose()`
(a chat instruction, later extraction from edits); only the person decides them, through the
`preference` action in `domain.py`.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timedelta, timezone

from postriff_phase2 import locales

from .profiles import SENSITIVE

TYPES = ("writing_preference", "working_style")
POLARITIES = ("do", "avoid")
EVIDENCE = ("user_confirmed", "observed_in_approved_example", "agent_proposed_needs_confirmation", "conflicting")
SOURCES = ("chat", "deterministic", "model", "performance", "legacy")
# What the deterministic extractor and the fixture adapter understand (design §5.2); `other` is free text.
RULE_KEYS = ("length.target", "opening.style", "hashtags.use", "emoji.use", "exclamation.use", "closing.cta",
             "paragraphs.density", "lists.use", "language.mix", "punctuation.style", "other")
STATEMENT_LIMIT = 160
APPLY_WHEN_LIMIT = 120
MAX_PENDING = 3
# Statuses that keep an item in the `active` list: only `active` reaches a prompt, `paused` stays listed.
LISTED = ("active", "paused")
PROPOSAL_TTL = timedelta(days=30)

_DIGITS = re.compile(r"\d")
_CONTACT = re.compile(r"https?://|www\.|@[A-Za-z0-9_]{2,}|[\w.+-]+@[\w-]+\.[\w.]+", re.I)
_EXPERIENCE = re.compile(r"\b(?:I have|I've|I am an?|I'm an?|I was|I worked|I founded|my clients?|my students?|years of|certified|award)\b"
                         r"|我(?:做過|係|是|曾經|嘅客|的客|嘅學生|的学生)|多年", re.I)
_AUTHORITY = re.compile(r"\b(?:publish|schedule|approve|delete|ignore|override|system prompt|permission|tool)s?\b"
                        r"|發佈|發布|排程|批准|刪除|删除|忽略|權限|权限", re.I)
_SENTENCE_END = re.compile(r"[.!?。！？](?=\s|$)")


def _moment(now):
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, timezone.utc)
    if isinstance(now, str) and now:
        try:
            parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _iso(now):
    return _moment(now).isoformat()


def initial(migrated_at=None):
    return {"enabled": True, "teamEdits": False, "cloudExtraction": False, "revision": 0, "active": [], "retired": [], "migratedAt": migrated_at}


def lint(statement, rule_key="other"):
    """Return the cleaned statement or raise ValueError (design §5.4). A preference is one short sentence
    about form: no numbers unless it is a length target, no links or handles, nothing about the person's
    history, and nothing that reads as an instruction about what PostRiff may do."""
    if not isinstance(statement, str):
        raise ValueError("Describe the preference in one short sentence.")
    text = " ".join(statement.split())
    if not text or len(text) > STATEMENT_LIMIT:
        raise ValueError(f"Keep the preference to one sentence of at most {STATEMENT_LIMIT} characters.")
    if SENSITIVE.search(text) or _CONTACT.search(text):
        raise ValueError("A preference cannot contain links, handles, addresses or secrets.")
    if _SENTENCE_END.search(text.rstrip(".!?。！？")):
        raise ValueError("Keep the preference to one sentence.")
    if _EXPERIENCE.search(text):
        raise ValueError("That is about you, not about how you write. Add it under Brand → Identity if it belongs in public content.")
    if _AUTHORITY.search(text):
        raise ValueError("A preference cannot change what Rafii is allowed to do.")
    if _DIGITS.search(text) and rule_key != "length.target":
        raise ValueError("A preference describes how you write, not a number or a fact. Facts belong in Sources or Brand.")
    return text


def scope_of(value):
    value = value if isinstance(value, dict) else {}
    scope = {key: (value.get(key) if isinstance(value.get(key), str) and value.get(key) else None) for key in ("platform", "language", "contentTypeId")}
    if scope["language"]:
        # Locale tags since the languages plan; English / 繁體中文 read as en / zh-Hant, `zh` is a Chinese-wide scope.
        scope["language"] = locales.canonical(scope["language"], family_ok=True) or scope["language"]
    return scope


def scope_key(type_, rule_key, polarity, scope):
    return "|".join([type_, rule_key, polarity] + [scope.get(key) or "*" for key in ("platform", "language", "contentTypeId")])


def canonical_scope_key(key):
    """A scope key written before locale tags (…|Instagram|繁體中文|*) as it is written now (…|Instagram|zh-Hant|*)."""
    parts = key.split("|") if isinstance(key, str) else []
    if len(parts) != 6 or parts[4] == "*":
        return key
    parts[4] = locales.canonical(parts[4], family_ok=True) or parts[4]
    return "|".join(parts)


def scope_label(scope):
    platform, content_type = scope.get("platform"), scope.get("contentTypeId")
    language = locales.display(scope["language"]) if scope.get("language") else None
    if platform and language:
        label = f"{platform} · {language}"
    elif platform:
        label = f"{platform} · all languages"
    elif language:
        label = f"All channels · {language}"
    else:
        label = "All channels"
    return label + (f" · {content_type}" if content_type else "")


def applies(item, platform, language, content_type_id=None):
    """A scope's language covers the draft's language and its parents: a `zh-Hant` rule reaches `zh-Hant-HK`
    and `yue-Hant-HK` drafts, an `en` rule every English draft."""
    scope = item.get("scope") or {}
    if scope.get("language") is not None:
        wanted = locales.canonical(scope["language"], family_ok=True) or scope["language"]
        if wanted != language and wanted not in locales.scope_chain(language):
            return False
    return all(scope.get(key) in (None, value) for key, value in (("platform", platform), ("contentTypeId", content_type_id)))


def normalize_proposal(raw):
    """Accept the founder-alpha shape ({key, value, platform, language}) as well as the design shape."""
    p = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if p.get("key") == "shortOpenings" and not p.get("ruleKey"):
        p.update({"type": "writing_preference", "ruleKey": "opening.style", "polarity": "do", "statement": "Use shorter openings.",
                  "params": {"shortOpenings": bool(p.get("value", True))}, "source": p.get("source") or "legacy"})
    p["type"] = p.get("type") or "writing_preference"
    p["polarity"] = p.get("polarity") or "do"
    p["ruleKey"] = p.get("ruleKey") or "other"
    p["scope"] = scope_of(p.get("scope") or {"platform": p.get("platform"), "language": p.get("language"), "contentTypeId": p.get("contentTypeId")})
    p["params"] = p.get("params") if isinstance(p.get("params"), dict) else {}
    p["source"] = p.get("source") if p.get("source") in SOURCES else "legacy"
    p["applyWhen"] = p.get("applyWhen") if isinstance(p.get("applyWhen"), str) else ""
    p["evidence"] = [e for e in (p.get("evidence") or []) if isinstance(e, dict)]
    p["op"] = p.get("op") if p.get("op") in ("add", "update", "retire") else "add"
    p["replaces"] = p.get("replaces") if isinstance(p.get("replaces"), str) else None
    return p


def _active_profile(state):
    speaker = state.get("speaker") or {}
    return next((r for r in speaker.get("revisions", []) if r.get("revision") == speaker.get("activeRevision")), None)


def _item(p, actor, since, evidence_state, summary):
    return {"id": p["id"], "type": p["type"], "ruleKey": p["ruleKey"], "polarity": p["polarity"], "scope": p["scope"],
            "scopeKey": scope_key(p["type"], p["ruleKey"], p["polarity"], p["scope"]), "statement": p["statement"], "applyWhen": p["applyWhen"],
            "params": p["params"], "evidenceState": evidence_state, "evidenceSummary": summary, "source": p["source"],
            "status": "active", "since": since, "confirmedBy": actor, "proposalId": p["id"]}


def _activate(learning, item):
    """One active item per scope; the item it replaces is kept as retired. Every change is a new style revision."""
    for existing in learning["active"]:
        if existing["status"] in LISTED and existing["scopeKey"] == item["scopeKey"]:
            existing.update({"status": "retired", "validTo": item["since"], "retiredReason": "replaced"})
            learning["retired"].append(existing)
    learning["active"] = [x for x in learning["active"] if x["status"] in LISTED] + [item]
    learning["revision"] += 1


def _migrate(state, learning, now):
    """Once per workspace. Preferences remembered under the old design (kept inside the voice profile) move
    here as user-confirmed items. Proposals the old design created silently on a draft's first edit were
    never shown by the consumer web, so they expire instead of waiting for a decision nobody was asked for."""
    stamp = _iso(now)
    revision = _active_profile(state) or {}
    for legacy in ((revision.get("profile") or {}).get("preferences") or []):
        p = normalize_proposal(legacy)
        p.setdefault("id", uuid.uuid4().hex)
        try:
            p["statement"] = lint(p.get("statement"), p["ruleKey"])
        except ValueError:
            continue
        _activate(learning, _item(p, None, revision.get("approvedAt") or stamp, "user_confirmed", "remembered from an edit"))
    for proposal in state["preferences"]:
        if proposal.get("status") == "proposed":
            proposal.update({"status": "expired", "expiredAt": stamp, "expiredReason": "never_shown"})
    learning["migratedAt"] = stamp


def _migrate_locale_tags(state, learning, now):
    """Once per workspace: scopes stored as English / 繁體中文 become en / zh-Hant, so a rule keeps applying
    and a new proposal for the same scope replaces it instead of sitting beside it (languages plan §6)."""
    for item in list(learning.get("active") or []) + list(learning.get("retired") or []):
        if isinstance(item, dict) and isinstance(item.get("scope"), dict):
            item["scope"] = scope_of(item["scope"])
            if item.get("type") and item.get("ruleKey") and item.get("polarity"):
                item["scopeKey"] = scope_key(item["type"], item["ruleKey"], item["polarity"], item["scope"])
    for proposal in state.get("preferences") or []:
        if isinstance(proposal, dict) and isinstance(proposal.get("scope"), dict):
            proposal["scope"] = scope_of(proposal["scope"])
        if isinstance(proposal, dict) and isinstance(proposal.get("language"), str):
            proposal["language"] = locales.canonical(proposal["language"], family_ok=True) or proposal["language"]
    learning["localeTagsAt"] = _iso(now)


def _expire(state, now):
    moment = _moment(now)
    for proposal in state["preferences"]:
        if proposal.get("status") == "proposed" and proposal.get("expiresAt") and _moment(proposal["expiresAt"]) <= moment:
            proposal.update({"status": "expired", "expiredAt": _iso(now), "expiredReason": "no_decision"})


def ensure(state, now=None):
    learning = state.get("learning")
    if not isinstance(learning, dict):
        learning = state["learning"] = initial()
    for key, value in initial().items():
        learning.setdefault(key, copy.deepcopy(value))
    state.setdefault("preferences", [])
    if learning["migratedAt"] is None:
        _migrate(state, learning, now)
    if not learning.get("localeTagsAt"):
        _migrate_locale_tags(state, learning, now)
    _expire(state, now)
    return learning


def revision(state):
    learning = (state or {}).get("learning")
    return int(learning.get("revision", 0)) if isinstance(learning, dict) else 0


def active_items(state):
    learning = (state or {}).get("learning")
    return [item for item in (learning.get("active") or []) if item.get("status") == "active"] if isinstance(learning, dict) else []


def flag(state, name, platform, language, content_type_id=None):
    """A machine-readable knob some active item sets for this destination (the fixture adapter's shortOpenings)."""
    return any((item.get("params") or {}).get(name) for item in active_items(state) if applies(item, platform, language, content_type_id))


def propose(state, proposal, now=None):
    """Server code, never a client, adds a pending proposal. Returns the record, or None when there is nothing
    new to ask: the same preference is already active or already waiting, or three proposals are waiting."""
    learning = ensure(state, now)
    p = normalize_proposal(proposal)
    if p["type"] not in TYPES or p["polarity"] not in POLARITIES or p["ruleKey"] not in RULE_KEYS:
        raise ValueError("Unsupported preference proposal.")
    p["statement"] = lint(p.get("statement"), p["ruleKey"])
    p["applyWhen"] = " ".join(p["applyWhen"].split())[:APPLY_WHEN_LIMIT]
    key = scope_key(p["type"], p["ruleKey"], p["polarity"], p["scope"])
    if any(item["scopeKey"] == key and item["statement"] == p["statement"] for item in learning["active"] if item["status"] == "active"):
        return None
    pending = [x for x in state["preferences"] if x.get("status") == "proposed"]
    if len(pending) >= MAX_PENDING or any(normalize_key(x) == key for x in pending):
        return None
    created = _moment(now)
    record = {"id": p.get("id") or uuid.uuid4().hex, "type": p["type"], "ruleKey": p["ruleKey"], "polarity": p["polarity"], "scope": p["scope"],
              "scopeKey": key, "statement": p["statement"], "applyWhen": p["applyWhen"], "params": p["params"], "source": p["source"],
              "op": p["op"], "replaces": p["replaces"],
              "evidence": p["evidence"], "why": " ".join(str(p.get("why") or "").split())[:240], "label": p.get("label") or p["statement"],
              "variantId": p.get("variantId"), "platform": p["scope"]["platform"], "language": p["scope"]["language"],
              "status": "proposed", "createdAt": created.isoformat(), "expiresAt": (created + PROPOSAL_TTL).isoformat()}
    state["preferences"].append(record)
    return record


def normalize_key(proposal):
    p = normalize_proposal(proposal)
    return scope_key(p["type"], p["ruleKey"], p["polarity"], p["scope"])


def remember(state, proposal, actor=None, now=None):
    """The person accepted a proposal: it becomes an active item and the style revision moves on.
    The voice revision does not change, so nothing already approved becomes stale."""
    learning = ensure(state, now)
    p = normalize_proposal(proposal)
    p.setdefault("id", uuid.uuid4().hex)
    p["statement"] = lint(p.get("statement"), p["ruleKey"])
    if p["source"] in ("chat", "legacy"):
        evidence_state, summary = "user_confirmed", {"chat": "you said so", "legacy": "remembered from an edit"}[p["source"]]
    else:
        evidence_state = "observed_in_approved_example"
        summary = f"from {len(p['evidence'])} edits" if p["evidence"] else "from your edits"
    item = _item(p, actor, _iso(now), evidence_state, summary)
    if p["replaces"]:
        # An update or a conflict: the item this one supersedes retires in the same style revision.
        _retire(learning, p["replaces"], now, "replaced")
    _activate(learning, item)
    return item


def _retire(learning, item_id, now, reason):
    retired = [item for item in learning["active"] if item["id"] == item_id and item["status"] in LISTED]
    for item in retired:
        item.update({"status": "retired", "validTo": _iso(now), "retiredReason": reason})
        learning["retired"].append(item)
    if retired:
        learning["active"] = [x for x in learning["active"] if x["status"] in LISTED]
    return bool(retired)


def retire(state, item_id, now=None, reason="undone"):
    """Retire an active or paused item; it stays in `retired` for the record and for undo."""
    learning = ensure(state, now)
    if _retire(learning, item_id, now, reason):
        learning["revision"] += 1
        return True
    return False


MAX_PROMPT_ITEMS = 12
MAX_PROMPT_CHARS = 1500


def _line(item):
    since = str(item.get("since") or "")[:10]
    return f"- [{scope_label(item.get('scope') or {})}] {item['statement']} — {item.get('evidenceSummary') or 'remembered'}" + (f" · {since}" if since else "")


def select(state, destinations, content_type_id=None, max_items=MAX_PROMPT_ITEMS, max_chars=MAX_PROMPT_CHARS):
    """Items for one turn (design §5.7): those whose scope covers any destination, the most specific first,
    within a bounded slice. Returns (chosen, omitted ids)."""
    items = [item for item in active_items(state) if any(applies(item, d.get("platform"), d.get("language"), content_type_id) for d in destinations)]

    def rank(item):
        scope = item.get("scope") or {}
        return (bool(scope.get("contentTypeId")), bool(scope.get("platform")), bool(scope.get("language")), item.get("evidenceState") == "user_confirmed", item.get("since") or "")

    chosen, omitted, used = [], [], 0
    for item in sorted(items, key=rank, reverse=True):
        length = len(_line(item))
        if len(chosen) >= max_items or used + length > max_chars:
            omitted.append(item["id"])
            continue
        chosen.append(item)
        used += length
    return chosen, omitted


def binding(state, destinations=None, content_type_id=None):
    """What a run received from learning, recorded on the run so the effect of each item can be measured later."""
    if destinations:
        chosen, omitted = select(state, destinations, content_type_id)
    else:
        chosen, omitted = active_items(state), []
    return {"styleRevision": revision(state), "used": [item["id"] for item in chosen], "statements": [item["statement"] for item in chosen], "omitted": omitted}


def render_lines(state, destinations=None, content_type_id=None):
    """The VOICE.md section. Form only; the message and the approved facts always win over these.
    With destinations, only the items that apply to them, within the prompt slice."""
    rev = revision(state)
    lines = ["## Learned from how you edit" + (f" (style rev {rev})" if rev else ""),
             "Form only. The facts and what you ask for in the message win over these."]
    items = select(state, destinations, content_type_id)[0] if destinations else active_items(state)
    items = sorted(items, key=lambda item: (scope_label(item.get("scope") or {}), item.get("since") or ""))
    lines.extend(_line(item) for item in items)
    return lines + (["- (none yet)"] if not items else [])


def set_status(state, item_id, status, now=None, reason=None):
    """Pause, resume or retire one item (Memory page). Paused items stay listed but leave the prompt."""
    if status not in ("active", "paused", "retired"):
        raise ValueError("Choose active, paused or retired.")
    if status == "retired":
        return retire(state, item_id, now, reason or "retired")
    learning = ensure(state, now)
    for item in learning["active"]:
        if item["id"] == item_id and item["status"] in LISTED and item["status"] != status:
            item["status"] = status
            item["statusChangedAt"] = _iso(now)
            learning["revision"] += 1
            return True
    return False


def all_items(state):
    """Every item the Memory page lists: active and paused, then retired."""
    learning = (state or {}).get("learning")
    if not isinstance(learning, dict):
        return []
    return [item for item in learning.get("active") or [] if item.get("status") in LISTED] + list(learning.get("retired") or [])


def summary(state):
    learning = (state or {}).get("learning") if isinstance((state or {}).get("learning"), dict) else initial()
    return {"enabled": learning.get("enabled", True), "teamEdits": learning.get("teamEdits", False), "cloudExtraction": learning.get("cloudExtraction", False),
            "revision": int(learning.get("revision", 0) or 0), "resetAt": learning.get("resetAt"), "items": all_items(state)}


def apply(store, s, action, p, now=None):
    """`learning_settings` and `learning_reset` (owner-only on the hosted API). Returns True when consumed."""
    if action == "learning_settings":
        learning = ensure(s, now)
        changed = {}
        for key in ("enabled", "teamEdits", "cloudExtraction"):
            if key in p:
                if not isinstance(p[key], bool):
                    raise ValueError("Settings are explicit true/false choices.")
                changed[key] = p[key]
        if not changed:
            raise ValueError("Choose a setting to change.")
        learning.update(changed)
        learning["settingsChangedAt"] = _iso(now)
        return True
    if action == "learning_reset":
        if p.get("confirmed") is not True:
            raise ValueError("Confirm that you want Rafii to forget what it learned.")
        learning = ensure(s, now)
        learning.update({"active": [], "retired": [], "revision": learning["revision"] + 1, "resetAt": _iso(now)})
        for proposal in s.get("preferences") or []:
            if proposal.get("status") == "proposed":
                proposal.update({"status": "expired", "expiredAt": _iso(now), "expiredReason": "reset"})
        return True
    return False
