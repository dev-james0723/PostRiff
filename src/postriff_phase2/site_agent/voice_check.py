"""Compare a draft or a sentence with the voice this workspace stored ("Does this sound like me?").

Only what can be checked is checked. Each finding names the stored trait it was compared with (an observation on the
approved voice profile, a learned preference, the approved writing example) and its basis:

- `measured`: counted in the text (sentences per paragraph, emoji, hashtags, a question mark, words per sentence);
- `heuristic`: a rule that can be wrong ("ends with a practical step" looks for an instruction in the last sentence);
- `needs_writer`: tone, word choice and anything else only a writer model can judge. Nothing here pretends to.

Evidence describes the text by its measurements, never by quoting it, so a finding can be shown or handed to a cloud
model without the draft's words. Pure functions over the workspace state; nothing is changed.
"""
from __future__ import annotations

import re

from postriff_alpha import learning

from .. import memory

EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
HASHTAG = re.compile(r"(?:^|\s)#[^\s#]{2,}")
LIST_LINE = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+", re.M)
_SENTENCE = re.compile(r"[^.!?。！？\n]+(?:[.!?。！？]+|$)")
_WORD = re.compile(r"[A-Za-z0-9']+|[㐀-鿿]")
# Instructions a closing "practical step" usually starts with (heuristic, English).
_STEP_VERBS = ("try", "pick", "play", "start", "spend", "write", "take", "set", "ask", "practise", "practice", "listen", "open", "choose", "book",
               "join", "read", "share", "comment", "tell", "give", "make", "find", "use", "add", "keep", "focus", "record", "count", "slow", "breathe",
               "put", "sit", "stand", "check", "note", "plan", "save", "reply", "download", "sign", "visit", "watch", "learn")


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text or "") if s.strip() and _WORD.search(s)]


def measure(text: str) -> dict:
    """What a person could count in the text."""
    paragraphs = _paragraphs(text)
    sentences = _sentences(text)
    words = _WORD.findall(text or "")
    per_paragraph = [len(_sentences(p)) for p in paragraphs] or [0]
    last = sentences[-1] if sentences else ""
    first = sentences[0] if sentences else ""
    return {"characters": len(text or ""), "words": len(words), "sentences": len(sentences), "paragraphs": len(paragraphs),
            "maxSentencesPerParagraph": max(per_paragraph), "avgWordsPerSentence": round(len(words) / len(sentences), 1) if sentences else 0.0,
            "firstSentenceWords": len(_WORD.findall(first)), "opensWithQuestion": first.rstrip().endswith(("?", "？")),
            "closingInstruction": bool(last) and (last.split() or [""])[0].strip("“\"'(").lower() in _STEP_VERBS,
            "closingQuestion": last.rstrip().endswith(("?", "？")), "emoji": len(EMOJI.findall(text or "")), "hashtags": len(HASHTAG.findall(text or "")),
            "exclamations": (text or "").count("!") + (text or "").count("！"), "listLines": len(LIST_LINE.findall(text or ""))}


def _finding(trait, source, verdict, basis, evidence):
    return {"trait": trait, "source": source, "verdict": verdict, "basis": basis, "evidence": evidence}


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _observation(trait: str, m: dict, source: str) -> dict:
    """An approved-profile observation, checked when it names something countable."""
    low = trait.lower()
    if re.search(r"\b(?:open|start|begin|first\s+line|hook)", low) and "question" in low:
        return _finding(trait, source, "matches" if m["opensWithQuestion"] else "differs", "measured",
                        "The first sentence ends with a question mark." if m["opensWithQuestion"] else "The first sentence is not a question.")
    if "paragraph" in low and re.search(r"\b(?:two|2)\s+sentences?\b|\bone\s+or\s+two\b", low):
        ok = m["maxSentencesPerParagraph"] <= 2
        return _finding(trait, source, "matches" if ok else "differs", "measured",
                        f"The longest paragraph has {_plural(m['maxSentencesPerParagraph'], 'sentence')} (the profile says two).")
    if "paragraph" in low and re.search(r"\bshort\b", low):
        ok = m["maxSentencesPerParagraph"] <= 3
        return _finding(trait, source, "matches" if ok else "differs", "measured", f"The longest paragraph has {_plural(m['maxSentencesPerParagraph'], 'sentence')}.")
    if re.search(r"\b(?:end|ends|close|closes|finish|finishes)\b", low) and re.search(r"\b(?:step|action|try|practical|instruction|call to action)\b", low):
        return _finding(trait, source, "matches" if m["closingInstruction"] else "differs", "heuristic",
                        "The last sentence starts with an instruction (a verb such as “try”)." if m["closingInstruction"] else "The last sentence does not start with an instruction.")
    if re.search(r"\b(?:end|ends|close|closes)\b", low) and "question" in low:
        return _finding(trait, source, "matches" if m["closingQuestion"] else "differs", "measured",
                        "The last sentence is a question." if m["closingQuestion"] else "The last sentence is not a question.")
    if re.search(r"\bshort\s+sentences?\b", low):
        ok = 0 < m["avgWordsPerSentence"] <= 14
        return _finding(trait, source, "matches" if ok else "differs", "measured", f"Sentences average {m['avgWordsPerSentence']} words.")
    if "emoji" in low and re.search(r"\b(?:no|never|avoid|without|rarely)\b", low):
        return _finding(trait, source, "matches" if m["emoji"] == 0 else "differs", "measured", f"{_plural(m['emoji'], 'emoji')} in the text.")
    if "hashtag" in low and re.search(r"\b(?:no|never|avoid|without|rarely)\b", low):
        return _finding(trait, source, "matches" if m["hashtags"] == 0 else "differs", "measured", f"{_plural(m['hashtags'], 'hashtag')} in the text.")
    return _finding(trait, source, "unclear", "needs_writer", "Tone and word choice can't be counted; a writer model has to judge this.")


def _preference(item: dict, m: dict, source: str) -> dict:
    """A learned preference, checked by its rule key and whether it says do or avoid."""
    rule, avoid, statement = item.get("ruleKey"), item.get("polarity") == "avoid", item.get("statement") or ""
    counts = {"emoji.use": ("emoji", "emoji"), "hashtags.use": ("hashtags", "hashtag"), "exclamation.use": ("exclamations", "exclamation mark"),
              "lists.use": ("listLines", "list line")}
    if rule in counts:
        key, word = counts[rule]
        ok = m[key] == 0 if avoid else m[key] > 0
        return _finding(statement, source, "matches" if ok else "differs", "measured", f"{_plural(m[key], word)} in the text.")
    if rule == "paragraphs.density":
        ok = m["maxSentencesPerParagraph"] <= 3
        return _finding(statement, source, "matches" if ok else "differs", "measured", f"The longest paragraph has {_plural(m['maxSentencesPerParagraph'], 'sentence')}.")
    if rule == "opening.style":
        if "question" in statement.lower():
            return _finding(statement, source, "matches" if m["opensWithQuestion"] else "differs", "measured",
                            "The first sentence is a question." if m["opensWithQuestion"] else "The first sentence is not a question.")
        if (item.get("params") or {}).get("shortOpenings") or "short" in statement.lower():
            ok = 0 < m["firstSentenceWords"] <= 12
            return _finding(statement, source, "matches" if ok else "differs", "measured", f"The first sentence has {_plural(m['firstSentenceWords'], 'word')}.")
    if rule == "closing.cta":
        has = m["closingInstruction"] or m["closingQuestion"]
        ok = not has if avoid else has
        return _finding(statement, source, "matches" if ok else "differs", "heuristic",
                        "The last sentence invites the reader to act or reply." if has else "The last sentence doesn't ask the reader to do anything.")
    return _finding(statement, source, "unclear", "needs_writer", "This preference isn't something that can be counted; a writer model has to judge it.")


def _example_rhythm(example: str, m: dict) -> dict | None:
    ex = measure(example)
    if not ex["sentences"] or not m["sentences"]:
        return None
    low, high = ex["avgWordsPerSentence"] * 0.6, ex["avgWordsPerSentence"] * 1.4
    ok = low <= m["avgWordsPerSentence"] <= high
    return _finding("Sentence length like your approved writing example", "writing example", "matches" if ok else "differs", "measured",
                    f"Sentences average {m['avgWordsPerSentence']} words here and {ex['avgWordsPerSentence']} in your example.")


def analyze(state: dict, text: str, platform: str | None = None) -> dict:
    """{"findings", "measured", "profile", "summary", "empty"}: the text checked against the stored voice only."""
    revision = memory.active_profile(state)
    profile = (revision or {}).get("profile") or {}
    stale = bool(revision and (revision.get("stale") or profile.get("status") == "stale"))
    m = measure(text)
    findings = []
    source = f"voice profile (revision {revision.get('revision')})" if revision else "voice profile"
    if revision and not stale:
        for observation in [str(o) for o in profile.get("observations") or []][:12]:
            findings.append(_observation(observation, m, source))
        if profile.get("tone"):
            findings.append(_finding(f"Tone: {profile['tone']}", source, "unclear", "needs_writer", "Tone can't be counted; a writer model has to judge it."))
        example = profile.get("writingExample") or ""
        rhythm = _example_rhythm(example, m) if example else None
        if rhythm:
            findings.append(rhythm)
    learned = []
    for item in learning.active_items(state):
        scope = item.get("scope") or {}
        if platform and scope.get("platform") not in (None, platform):
            continue
        label = learning.scope_label(scope)
        learned.append({"statement": item.get("statement"), "scope": label, "ruleKey": item.get("ruleKey"), "polarity": item.get("polarity")})
        findings.append(_preference(item, m, f"learned preference ({label})"))
    summary = {verdict: sum(1 for f in findings if f["verdict"] == verdict) for verdict in ("matches", "differs", "unclear")}
    return {"findings": findings, "measured": m, "summary": summary, "empty": not findings,
            "profile": {"revision": (revision or {}).get("revision"), "stale": stale, "tone": profile.get("tone"), "observations": len(profile.get("observations") or []),
                        "learned": learned}}
