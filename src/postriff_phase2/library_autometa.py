"""Automatic tags and a one-sentence summary for an uploaded document, from its own text. No model and no network.

Tags are the document's recurring key phrases (English runs of content words; CJK runs of two to four characters),
weighted towards the title lines and the file name. The summary is one sentence taken verbatim from the file: the
early sentence that carries most of those phrases. Both are plain extraction, so the product labels them "from the
file", never as AI. Slide counters, timestamps and page furniture are ignored.
"""
from __future__ import annotations

import re
from collections import Counter

MAX_TAGS = 5
MAX_TAG_CHARS = 40
STOP = frozenset("""
a an the and or but nor if then else of to in on at by for with from as into onto over under about above below between
through during before after again further once is are was were be been being am do does did doing have has had having
this that these those it its it's they them their there here what which who whom whose when where why how all any both
each few more most other some such only own same so than too very can will just should could would may might must shall
not no yes also our ours we us you your yours he him his she her hers i me my mine one two three four five six seven
eight nine ten first second third last next new use used using get got make made let lets let's now today
page pages slide slides minute minutes section part chapter figure table note notes etc via per vs
jpg jpeg png gif webp svg pdf doc docx xls xlsx csv txt md html htm json http https www com org
""".split())
CJK_FUNCTION = frozenset("的是了我你他她它佢們们嘅係唔喺在和與与有個个這这那就都也啲咗好一不冇吖呀啦喇咩嗎吗呢吧之其而及或被把為为從从對对以於于到等著着")
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*[A-Za-z0-9]|[A-Za-z]")
# Slide counters, timestamps, page numbers and similar furniture lines.
FURNITURE = re.compile(r"^\s*(?:slide\s*\d+(?:\s*/\s*\d+)?|page\s*\d+(?:\s*(?:/|of)\s*\d+)?|\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?|\d+)\s*$", re.I)
SENTENCE = re.compile(r"[^.!?。！？\n]+[.!?。！？]+|[^.!?。！？\n]{12,}$", re.M)


SEGMENT = re.compile(r"[|,;:()\[\]{}/·•–—\"“”‘’!?。！？，、；：（）]+|\s-\s|\.(?:\s|$)")
COUNTER = re.compile(r"\s*\b\d+\s*/\s*\d+\s*$")


def _lines(text: str) -> list[str]:
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" |\t")
        line = re.sub(r"^\s*(?:slide\s*\d+\s*(?:/\s*\d+)?|\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2})\s*", "", line, flags=re.I)
        line = COUNTER.sub("", line).strip()
        if line and not FURNITURE.match(line):
            out.append(line)
    return out


def _key(phrase: str) -> str:
    return phrase.replace("-", " ")


def _latin_phrases(segment: str) -> list[str]:
    phrases, run = [], []
    for token in WORD.findall(segment) + ["."]:
        word = token.lower().replace("’", "'")
        if word == "." or word in STOP or len(word) < 3 or word.isdigit():
            for n in range(1, min(4, len(run)) + 1):
                for i in range(len(run) - n + 1):
                    phrases.append(" ".join(run[i:i + n]))
            run = []
        else:
            run.append(word)
    return phrases


def _cjk_phrases(segment: str) -> list[str]:
    phrases = []
    for block in CJK.findall(segment):
        for size in range(2, 7):
            for i in range(len(block) - size + 1):
                piece = block[i:i + size]
                if piece[0] in CJK_FUNCTION or piece[-1] in CJK_FUNCTION:
                    continue
                phrases.append(piece)
    return phrases


def _phrases(line: str) -> list[str]:
    out = []
    for segment in SEGMENT.split(line):
        out += _latin_phrases(segment) + _cjk_phrases(segment)
    return out


def _size(phrase: str) -> int:
    return len(phrase.split()) if phrase.isascii() else len(phrase)


def suggest(text: str, filename: str = "") -> dict:
    """{'tags': [...], 'summary': str | None} for one document's extracted text."""
    lines = _lines(text)
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", filename or "")
    name_phrases = _phrases(re.sub(r"[_+]+|%[0-9A-Fa-f]{2}", " ", stem))
    if not lines:
        # No readable text (a scanned score, an image-only PDF): the file name is all there is to go on.
        words = [p for p in dict.fromkeys(name_phrases) if " " not in p and (len(p) >= 4 or not p.isascii())]
        return {"tags": words[:3], "summary": None}
    counts: Counter = Counter()
    sources: dict[str, set] = {}
    surface: dict[str, Counter] = {}
    for index, line in enumerate(lines[:4000]):
        weight = 3 if index < 3 else 1  # title lines say what the document is about
        for phrase in _phrases(line):
            counts[_key(phrase)] += weight
            sources.setdefault(_key(phrase), set()).add(index)
            surface.setdefault(_key(phrase), Counter())[phrase] += 1
    for phrase in name_phrases:
        counts[_key(phrase)] += 2
        sources.setdefault(_key(phrase), set()).add("name")
        surface.setdefault(_key(phrase), Counter())[phrase] += 1

    def score(key: str) -> float:
        size = _size(key)
        return counts[key] * (1 + (0.6 if key.isascii() else 0.3) * (size - 1))

    # A tag must recur: in two places at least (lines or the file name), never just once in a heading.
    candidates = [k for k, n in counts.items() if n >= 2 and len(sources.get(k, ())) >= 2 and len(k) <= MAX_TAG_CHARS]
    # A longer phrase that carries most of a shorter one's occurrences replaces it ("seventh" -> "seventh chord",
    # "大會堂" -> "香港大會堂"); fragments of a longer phrase that always occur inside it are dropped.
    keep = []
    for key in candidates:
        longer = [o for o in candidates if o != key and len(o) > len(key) and (f" {key} " in f" {o} " if key.isascii() else key in o)]
        if any(counts[o] >= 0.6 * counts[key] for o in longer):
            continue
        keep.append(key)
    ranked = sorted(keep, key=lambda k: (-score(k), k))
    tags: list[str] = []
    for key in ranked:
        if any(key in t or t in key or key.rstrip("s") == t.rstrip("s") for t in tags):
            continue
        tags.append(key)
        if len(tags) == MAX_TAGS:
            break
    display = [surface.get(k, Counter({k: 1})).most_common(1)[0][0] for k in tags]

    # PDFs wrap sentences across lines: rejoin a line that does not end a sentence with the next one.
    paragraphs: list[str] = []
    for line in lines[:400]:
        if paragraphs and not re.search(r"[.!?。！？:]$", paragraphs[-1]) and line[:1].islower():
            paragraphs[-1] += " " + line
        else:
            paragraphs.append(line)
    summary, best = None, 0.0
    order = 0
    for line in paragraphs:
        for match in SENTENCE.finditer(line):
            sentence = match.group(0).strip()
            order += 1
            if not 30 <= len(sentence) <= 220 or "|" in sentence:
                continue
            lowered = _key(sentence.lower())
            value = sum(score(t) for t in tags if t in lowered) / (1 + order * 0.03)
            if value > best:
                best, summary = value, sentence
    if summary is None:
        first = next((line for line in lines if len(line) >= 20 and "|" not in line), None)
        summary = first[:220] if first else None
    return {"tags": display, "summary": summary}
