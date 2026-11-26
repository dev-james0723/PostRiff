"""Learning signals (preference-learning design §3, §5.1): what the person did, as numbers, never as text.

`derive_events(before, after, ...)` compares a workspace state before and after one command and
returns the events that command implies: a draft edited, a candidate accepted, a draft the person
does not want, a destination approved, a job cancelled, a proposal decided. Every event carries ids,
the scope (platform, language, content type, format), the two revisions in force, and numeric
features of the text; it never carries the text itself. A later phase reads the text back from the
workspace at extraction time, when the source policies of that moment still apply.

`features()` and `edit_distance()` are the deterministic half of extraction (§5.2 C1): counts a
model could later explain, computed the same way for Chinese and English.
"""
from __future__ import annotations

import difflib
import re

EVENT_KINDS = ("draft.edited", "draft.update_accepted", "draft.rejected", "draft.approved", "job.cancelled", "post.published", "chat.instruction", "proposal.decided")
EVENT_TTL_DAYS = 180
EDIT_ORIGINS = ("author-edit", "chosen-opening")
# Revisions the person chose but did not write: an accepted tone or polish edit, a version brought back by undo or
# restore, and Post Doctor or Opportunity Lab text they applied. Accepting one says nothing about how the person
# writes, so none of them is an edit signal (no draft.edited, no draft.update_accepted and no edit distance), and an
# approval measures the person's own edits from the latest of them instead of from the first model text.
ASSISTED_ORIGINS = ("accepted-edit", "restored", "assistant-edit")
DECIDED = ("remembered", "post-only", "rejected", "undone", "deleted")

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z0-9À-ɏ'’-]+")
_TOKEN = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]|[A-Za-z0-9À-ɏ'’-]+|[^\sA-Za-z0-9À-ɏ぀-ヿ㐀-䶿一-鿿豈-﫿]")
_HASHTAG = re.compile(r"(?<![\w#])#[\w㐀-鿿]+")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿]")
_LIST_LINE = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)、．]|[①-⑳])\s*\S", re.M)
_CTA = re.compile(r"comment below|let me know|drop a |dm me|link in bio|follow (?:me|for|along)|share this|save this|留言|告訴我|告诉我|私訊|私信|追蹤|关注|轉發|转发|連結|链接", re.I)
_FULLWIDTH = re.compile(r"[，。！？：；「」『』（）]")
_HALFWIDTH = re.compile(r"[,.!?:;()\"']")
_REDACT = (
    (re.compile(r"https?://\S+|www\.\S+", re.I), "<url>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"(?<!\w)@[\w.]{2,}"), "<handle>"),
    (re.compile(r"\d[\d,.:/-]*"), "<num>"),
)


# A whole-post maximum the person stated outright in words ("under 80 words", "80 字以內"). Anything else names no
# limit here and is left to the sentence in VOICE.md: "about 80 words", a minimum however it is phrased ("never below
# 100 words"), a limit on part of a post ("sentences under 20 words"), and lengths in characters, whose meaning
# differs between what a person types and what edit-learning writes for Chinese, Japanese and Thai.
_NUMBER = r"(?<![\d,.])(?P<n>\d{1,3}(?:,\d{3})+|\d{1,5})(?![\d.])"
_UNIT = r"(?:words?\b|個字|个字|字(?![元符數数]))"
_LIMIT_BEFORE = re.compile(r"(?P<op>\b(?:under|below|fewer than|less than|shorter than|at most|no more than|not more than|up to|within|maximum of|max(?:imum)?)\b|少於|少于|不超過|不超过|唔好超過|唔超過|最多)\s*" + _NUMBER + r"\s*" + _UNIT, re.I)
_LIMIT_AFTER = re.compile(_NUMBER + r"\s*" + _UNIT + r"\s*(?P<op>\bor fewer\b|\bor less\b|\bmax(?:imum)?\b|以內|以内|之內|之内|[內内](?![㐀-鿿]))", re.I)
_EXCLUSIVE = ("under", "below", "fewer than", "less than", "shorter than", "少於", "少于")
_NEGATED = re.compile(r"(?:\b(?:not|never|no|don['’]?t|do not|cannot|can['’]?t)\b(?:\s+\w+){0,2}\s*|[不唔勿]\s*)$", re.I)
_MINIMUM = re.compile(r"\b(?:at least|min(?:imum)?|no fewer than|no less than)\b|至少|最少|起碼|起码", re.I)
_PART_OF_POST = re.compile(r"\b(?:sentences?|titles?|headlines?|hooks?|lines?|paragraphs?|openings?|bullets?|subjects?|bios?|comments?|repl(?:y|ies))\b|句|標題|标题|段|開頭|开头", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_COUNTED_WORD = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’-][A-Za-z0-9À-ɏ]+)*")
# The sentence in VOICE.md alone is not enough: a real writer met "under 80 words" 2 times in 5 from the sentence
# and 5 in 5 once the number sat on the destination. Added to a writer's rules only when a destination carries one.
# The last sentence exists because the writer then over-corrected: with "a shorter post is always acceptable" it
# returned 31 to 36 words against a limit of 79, and the owner preferred the draft written without the rule.
WORD_LIMIT_RULE = ("- A destination with `wordLimit` carries a length the person asked you to remember. Treat it like "
                   "`characterLimit`: count the words of that destination's text before returning (each Chinese, Japanese "
                   "or Korean character counts as one) and stay at or under it. The person asked for a ceiling, not a much "
                   "shorter post: land in the upper half of that room (between half the limit and the limit) whenever the "
                   "idea and their usual form give you that much to say.")


def word_count(text):
    """Words as a person counts them: Latin words (a hyphenated word or a link is one), CJK characters one each.
    A bullet's dash is not a word."""
    text = text if isinstance(text, str) else ""
    links = len(_URL.findall(text))
    rest = _URL.sub(" ", text)
    return links + len(_CJK.findall(rest)) + len(_COUNTED_WORD.findall(rest))


def length_limit(statement):
    """The whole-post word maximum a remembered length states outright ({"max" inclusive, "stated", "exclusive"}),
    or None. When in doubt it is None: a missed limit leaves the sentence in VOICE.md, a wrong one misleads."""
    if not isinstance(statement, str) or _MINIMUM.search(statement) or _PART_OF_POST.search(statement):
        return None
    found = _LIMIT_BEFORE.search(statement) or _LIMIT_AFTER.search(statement)
    if not found:
        return None
    stated, exclusive = int(found["n"].replace(",", "")), found["op"].lower() in _EXCLUSIVE
    if exclusive and _NEGATED.search(statement[:found.start("op")]):
        return None   # "never below 100 words" asks for more, not less
    limit = stated - 1 if exclusive else stated
    return {"max": limit, "stated": stated, "exclusive": exclusive} if limit >= 1 else None


def over_limit_reminder(limit, text):
    """A measured reminder when a draft runs past a remembered word maximum, else None.

    The writer's own note that it "kept under 80 words" is not evidence, so the draft is counted here. It reminds;
    it never shortens a draft or stops one being made. (An automation's unattended publishing holds any draft that
    carries a warning it does not recognise, this one included: a post that breaks the person's own rule waits
    for the person.)"""
    if not limit or not isinstance(text, str) or not text.strip():
        return None
    used = word_count(text)
    if used <= limit["max"]:
        return None
    return f"This draft has {used} words; your remembered preference asks for {'under' if limit['exclusive'] else 'at most'} {limit['stated']}. Shorten it, or keep it if this one should run long."


def length_reminder(statement, text):
    return over_limit_reminder(length_limit(statement), text)


def word_limit_field(request, destination):
    """`wordLimit` for one destination of a writer request, when the run bound a remembered length for it."""
    row = next((r for r in request.get("lengthLimits") or [] if isinstance(r, dict) and r.get("platform") == destination.get("platform")
                and r.get("language") == destination.get("language") and type(r.get("words")) is int), None)
    return {"wordLimit": row["words"]} if row else {}


def has_word_limit(request):
    return any(isinstance(r, dict) and type(r.get("words")) is int for r in request.get("lengthLimits") or [])


def tokens(text):
    """CJK characters one by one, Latin words as words, punctuation as its own token."""
    return _TOKEN.findall(text if isinstance(text, str) else "")


def edit_distance(before, after):
    """0 = identical, 1 = nothing in common; token-based so Chinese and English are treated alike."""
    a, b = tokens(before), tokens(after)
    if not a and not b:
        return 0.0
    return round(1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)


def features(text):
    """Numbers that describe form: length, opening, hashtags, emoji, punctuation, lists, closing, language mix."""
    text = text if isinstance(text, str) else ""
    stripped = text.strip()
    lines = [line for line in stripped.splitlines() if line.strip()]
    paragraphs = [block for block in re.split(r"\n\s*\n", stripped) if block.strip()]
    first = lines[0].strip() if lines else ""
    last = paragraphs[-1] if paragraphs else ""
    cjk = len(_CJK.findall(stripped))
    words = len(_WORD.findall(stripped))
    letters = cjk + words
    return {
        "chars": len(stripped), "tokens": cjk + words, "lines": len(lines), "paragraphs": len(paragraphs),
        "sentencesPerParagraph": round((len(re.findall(r"[.!?。！？]+", stripped)) or 1) / max(len(paragraphs), 1), 2),
        "firstLineTokens": len(_CJK.findall(first)) + len(_WORD.findall(first)),
        "firstLineQuestion": first.rstrip().endswith(("?", "？")),
        "hashtags": len(_HASHTAG.findall(stripped)), "emoji": len(_EMOJI.findall(stripped)),
        "exclamations": stripped.count("!") + stripped.count("！"), "questions": stripped.count("?") + stripped.count("？"),
        "listLines": len(_LIST_LINE.findall(stripped)), "closingCta": bool(_CTA.search(last)),
        "cjkRatio": round(cjk / letters, 3) if letters else 0.0,
        "fullwidthPunctuation": len(_FULLWIDTH.findall(stripped)), "halfwidthPunctuation": len(_HALFWIDTH.findall(stripped)),
    }


def redact(text):
    """For a model extractor: keep the shape of a draft, drop what could identify or quantify."""
    out = text if isinstance(text, str) else ""
    for pattern, replacement in _REDACT:
        out = pattern.sub(replacement, out)
    return out


def _scope(variant, manifest=None):
    if manifest:
        content = manifest.get("contentType") or {}
        return {"platform": manifest.get("platform"), "language": (manifest.get("payload") or {}).get("language"), "contentTypeId": content.get("id"), "formatId": content.get("formatId")}
    return {"platform": variant.get("platform"), "language": variant.get("language"), "contentTypeId": variant.get("contentTypeId"), "formatId": variant.get("formatId")}


def _first_model_text(variant):
    """The text as the model wrote it: the first revision that was not the person's own edit."""
    for record in variant.get("revisions") or []:
        if record.get("origin") not in EDIT_ORIGINS:
            return record.get("text") or ""
    return (variant.get("revisions") or [{}])[0].get("text") or variant.get("text") or ""


def _own_edits(variant):
    """(text the person's edits are measured from, how many of their edits followed it) at approval. A draft with no
    assisted revision is measured as it always was: from its first model text, counting every edit."""
    revisions = [record for record in variant.get("revisions") or [] if isinstance(record, dict)]
    latest = max((index for index, record in enumerate(revisions) if record.get("origin") in ASSISTED_ORIGINS), default=None)
    if latest is None:
        return _first_model_text(variant), sum(1 for record in revisions if record.get("origin") in EDIT_ORIGINS)
    return revisions[latest].get("text") or "", sum(1 for record in revisions[latest + 1:] if record.get("origin") in EDIT_ORIGINS)


def _event(kind, actor, now, subject, scope, features_, voice_revision, style_revision):
    return {"kind": kind, "actor": actor, "at": now, "subject": subject, "scope": scope, "features": features_,
            "voiceRevision": voice_revision, "styleRevision": style_revision}


def derive_events(before, after, actor, now, action=None, payload=None):
    """Events one command implies, from the state before and after it. Pure; never includes draft text."""
    before, after = before or {}, after or {}
    learning = after.get("learning") if isinstance(after.get("learning"), dict) else {}
    if learning.get("enabled") is False:
        return []
    style_revision = int(learning.get("revision", 0) or 0)
    voice_revision = (after.get("speaker") or {}).get("activeRevision")
    events = []
    previous = {v["id"]: v for v in (before.get("variants") or []) if isinstance(v, dict) and v.get("id")}
    for v in after.get("variants") or []:
        if not isinstance(v, dict):
            continue
        old = previous.get(v.get("id"))
        if old is None:
            continue
        if v.get("revision", 0) > old.get("revision", 0):
            origin = (v.get("revisions") or [{}])[-1].get("origin")
            subject = {"variantId": v["id"], "fromRevision": old.get("revision"), "toRevision": v.get("revision"), "origin": origin, "runId": v.get("runId")}
            if origin in EDIT_ORIGINS:
                events.append(_event("draft.edited", actor, now, subject, _scope(v), {"before": features(old.get("text")), "after": features(v.get("text")), "editDistance": edit_distance(old.get("text"), v.get("text"))}, voice_revision, v.get("styleRevision", style_revision)))
            elif origin == "accepted-fixture-replacement":
                events.append(_event("draft.update_accepted", actor, now, subject, _scope(v), {"editDistance": edit_distance(old.get("text"), v.get("text"))}, voice_revision, v.get("styleRevision", style_revision)))
            # ASSISTED_ORIGINS: deliberately no event. Measurement of tone and polish edits lives in product events.
        new_feedback = (v.get("feedback") or [])[len(old.get("feedback") or []):]
        for item in new_feedback:
            events.append(_event("draft.rejected", actor, now, {"variantId": v["id"], "revision": item.get("revision"), "feedbackId": item.get("id"), "runId": v.get("runId")}, _scope(v), {"reasons": list(item.get("reasons") or []), "text": features(v.get("text"))}, voice_revision, v.get("styleRevision", style_revision)))
    variants = {v["id"]: v for v in (after.get("variants") or []) if isinstance(v, dict) and v.get("id")}
    old_jobs = {j["id"]: j for j in ((before.get("phase2") or {}).get("jobs") or []) if isinstance(j, dict) and j.get("id")}
    for job in (after.get("phase2") or {}).get("jobs") or []:
        if not isinstance(job, dict) or not job.get("id"):
            continue
        manifest = job.get("manifest") or {}
        old = old_jobs.get(job["id"])
        if old is None:
            variant = variants.get(manifest.get("variantId")) or {}
            baseline, edits = _own_edits(variant)
            approved_text = (manifest.get("payload") or {}).get("text") or variant.get("text") or ""
            subject = {"jobId": job["id"], "variantId": manifest.get("variantId"), "contentRevision": manifest.get("contentRevision"), "scheduleId": job.get("scheduleId"), "channelId": manifest.get("channelId")}
            features_ = {"editCount": edits, "editDistance": edit_distance(baseline, approved_text) if variant else None, "approved": features(approved_text)}
            events.append(_event("draft.approved", actor, now, subject, _scope(variant, manifest), features_, manifest.get("voiceRevision", voice_revision), manifest.get("styleRevision", style_revision)))
        elif job.get("state") == "canceled" and old.get("state") != "canceled" or (job.get("cancelRequested") and not old.get("cancelRequested")):
            events.append(_event("job.cancelled", actor, now, {"jobId": job["id"], "variantId": manifest.get("variantId"), "state": job.get("state")}, _scope({}, manifest), {}, manifest.get("voiceRevision", voice_revision), manifest.get("styleRevision", style_revision)))
    old_proposals = {p["id"]: p for p in (before.get("preferences") or []) if isinstance(p, dict) and p.get("id")}
    for proposal in after.get("preferences") or []:
        if not isinstance(proposal, dict) or not proposal.get("id"):
            continue
        old = old_proposals.get(proposal["id"])
        if old is not None and old.get("status") == "proposed" and proposal.get("status") in DECIDED:
            scope = proposal.get("scope") or {"platform": proposal.get("platform"), "language": proposal.get("language"), "contentTypeId": proposal.get("contentTypeId")}
            events.append(_event("proposal.decided", actor, now, {"proposalId": proposal["id"], "decision": proposal["status"], "scopeKey": proposal.get("scopeKey"), "ruleKey": proposal.get("ruleKey"), "source": proposal.get("source")}, {**scope, "formatId": None}, {}, voice_revision, style_revision))
    return events


def published_event(job, actor, now, style_revision=None):
    """The worker's event once a provider confirmed a post; not derivable from a single command."""
    manifest = job.get("manifest") or {}
    return _event("post.published", actor, now, {"jobId": job.get("id"), "variantId": manifest.get("variantId"), "contentRevision": manifest.get("contentRevision"), "providerReference": job.get("providerReference")},
                  _scope({}, manifest), {"published": features((manifest.get("payload") or {}).get("text"))}, manifest.get("voiceRevision"), manifest.get("styleRevision", style_revision))


def contains_text(event, text):
    """Test helper: True when a draft's text leaked into an event (it never should)."""
    import json
    return bool(text) and text in json.dumps(event, ensure_ascii=False)
