"""Original-span extraction precedes any optional interpretation or English gloss."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from .contracts import digest

VERSION = "original-spans-lexical-candidate-1"
_YUE = re.compile(r"[嘅喺咗啲冇佢哋唔攞咁嚟睇嘢噉㗎啦囉吖呢係喎]")
_HANT = re.compile(r"[體學國為與這個們說時會廣東龍發後裡來網樂]")
_HANS = re.compile(r"[体学国为与这个们说时会广东龙发后里来网乐]")
_ENGLISH = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")


def extract(text: str) -> dict:
    if not isinstance(text, str) or len(text) > 16_000:
        raise ValueError("invalid_original_text")
    # NFC composes accents; neither NFKC nor script conversion overwrites the original.
    normalized = unicodedata.normalize("NFC", text)
    english = list(_ENGLISH.finditer(text))
    yue = bool(_YUE.search(text))
    language = ("yue-en" if english else "yue") if yue else ("zh-Hant" if _HANT.search(text) else
               "zh-Hans" if _HANS.search(text) else "en" if english else "und")
    spans = [{"start": m.start(), "end": m.end(), "text": m.group(), "language": "en"} for m in english]
    for match in re.finditer(r"[\u3400-\u9fff]+", text):
        spans.append({"start": match.start(), "end": match.end(), "text": match.group(),
                      "language": "yue" if _YUE.search(match.group()) else language if language.startswith("zh-") else "und"})
    emoji = [{"start": i, "end": i + 1, "text": ch} for i, ch in enumerate(text)
             if unicodedata.category(ch) == "So"]
    tokens = [m.group().casefold() for m in english]
    for match in re.finditer(r"[\u3400-\u9fff]+", normalized):
        value = match.group(); tokens.extend(value[i:i + 2] for i in range(max(0, len(value)-1)))
    return {"original": text, "normalized_auxiliary": normalized, "language_candidate": language,
            "language_qualification": "unqualified_lexical", "spans": sorted(spans, key=lambda s: s["start"]),
            "emoji": emoji, "punctuation": [ch for ch in text if unicodedata.category(ch).startswith("P")],
            "hashtags": re.findall(r"#[\w\u3400-\u9fff]+", text), "features": sorted(set(tokens)),
            "method_version": VERSION, "gloss": None, "region": None, "origin": None}


def repeated_patterns(observations: list[dict], *, baseline: dict[str, int] | None = None,
                      minimum_support: int = 3) -> list[dict]:
    """Observed recurrence, not a claim that a conventional expression is newly invented."""
    groups = {}
    for observation in observations:
        text = observation.get("payload", {}).get("text", "")
        if not text:
            continue
        extracted = extract(text)
        for feature in extracted["features"]:
            key = (extracted["language_candidate"], feature)
            groups.setdefault(key, set()).add(observation["observation_id"])
    result = []
    for (language, expression), refs in sorted(groups.items()):
        if len(refs) >= minimum_support:
            before = (baseline or {}).get(expression)
            result.append({"id": digest([VERSION, language, expression]), "expression": expression,
                           "language": language, "observation_count": len(refs), "evidence_refs": sorted(refs),
                           "baseline_count": before, "change": len(refs)-before if before is not None else None,
                           "status": "observed_recurrence" if before is None else "candidate_pattern_change",
                           "meaning": None, "origin": None, "qualification": "lexical_only",
                           "limitations": ["Native-language meaning review is not yet qualified."]})
    return result
