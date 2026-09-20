"""Local, deterministic voice-profile proposals backed by selected sample evidence.

This analyser describes observable writing form only. It does not infer identity,
beliefs, diagnoses, experience or factual claims, and it never activates a profile.
"""
from __future__ import annotations

import re

from postriff_alpha.domain import AlphaError
from . import voice_sources

DIMENSIONS = (
    "language", "code_switching", "formality", "warmth", "humor", "vocabulary", "person", "sentence_length",
    "paragraph_length", "openings", "narrative_structure", "calls_to_action", "promotional_intensity", "emoji",
    "hashtags", "punctuation",
)

_CJK = re.compile(r"[一-鿿]")
_LATIN_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")
_HASHTAG = re.compile(r"(?<!\w)#[^\s#]+")
_FIRST_PERSON = re.compile(r"\b(?:I|me|my|mine|we|us|our|ours)\b|我哋|我們|我们|我", re.I)
_CTA = re.compile(r"\b(?:join|book|buy|learn|read|share|tell me|comment|visit|sign up)\b|歡迎|立即|報名|留言|分享|按連結|点击|點擊", re.I)
_PROMO = re.compile(r"\b(?:sale|offer|discount|limited|tickets?|buy|book now)\b|優惠|折扣|限時|門票|購買|立即預訂", re.I)
_HUMOR = re.compile(r"\b(?:lol|haha|hehe)\b|哈哈|😂|🤣", re.I)
_WARM = re.compile(r"\b(?:hello|hi|thank|thanks|welcome|glad)\b|你好|多謝|謝謝|歡迎|很高興", re.I)
_FORMAL = re.compile(r"\b(?:therefore|furthermore|regarding|sincerely)\b|謹此|敬請|因此|此外", re.I)


def _level(support: list[str], counter: list[str]) -> str:
    if support and counter:
        return "conflicting"
    return "supported" if len(support) >= 3 else "limited"


def _dimension(identifier: str, observation: str, support: list[str], counter: list[str] | None = None) -> dict:
    counter = counter or []
    return {"id": identifier, "observation": observation, "support": support, "counterEvidence": counter, "evidenceLevel": _level(support, counter)}


def validate_proposal(output: dict, projection: dict) -> dict:
    if not isinstance(output, dict) or not isinstance(output.get("dimensions"), list):
        raise AlphaError("Voice analysis returned an invalid structure.", 422)
    allowed_evidence = {sample["id"] for sample in projection.get("samples", [])}
    dimensions, quarantined = [], []
    for raw in output["dimensions"]:
        if not isinstance(raw, dict):
            quarantined.append({"reason": "invalid_dimension"})
            continue
        identifier = raw.get("id")
        if identifier not in DIMENSIONS:
            quarantined.append({"id": identifier, "reason": "unsupported_dimension"})
            continue
        observation = raw.get("observation")
        support, counter = raw.get("support", []), raw.get("counterEvidence", [])
        if not isinstance(observation, str) or not observation.strip() or len(observation) > 240:
            quarantined.append({"id": identifier, "reason": "invalid_observation"})
            continue
        if not isinstance(support, list) or not isinstance(counter, list) or any(not isinstance(item, str) for item in support + counter):
            raise AlphaError("Voice analysis evidence is invalid.", 422)
        if (set(support) | set(counter)) - allowed_evidence:
            raise AlphaError("Voice analysis cited unavailable evidence.", 409)
        if not support:
            quarantined.append({"id": identifier, "reason": "unsupported_observation"})
            continue
        dimensions.append(_dimension(identifier, observation.strip(), list(dict.fromkeys(support)), list(dict.fromkeys(counter))))
    return {"dimensions": dimensions, "quarantined": quarantined}


def build_proposal(state: dict, source_ids: list[str], actor: str, now: float, route: str = "local-rules") -> dict:
    projection = voice_sources.project(state, source_ids, "analysis", route)
    samples = projection["samples"]
    if not samples:
        raise AlphaError("Select and allow at least one writing sample for this analysis.", 409)
    ids = [sample["id"] for sample in samples]
    texts = {sample["id"]: sample["text"] for sample in samples}

    def split(predicate):
        support = [source_id for source_id, text in texts.items() if predicate(text)]
        return support, [source_id for source_id in ids if source_id not in support]

    languages = sorted({sample.get("language") or ("CJK" if _CJK.search(sample["text"]) else "Unspecified") for sample in samples})
    dimensions = [_dimension("language", "Uses " + ", ".join(languages) + ".", ids)]
    for identifier, pattern, yes, no in (
        ("code_switching", lambda text: bool(_CJK.search(text) and _LATIN_WORD.search(text)), "Mixes CJK and English words within samples.", "Keeps languages separate within samples."),
        ("formality", lambda text: bool(_FORMAL.search(text)), "Uses formal connective or courtesy language.", "Uses mostly conversational phrasing."),
        ("warmth", lambda text: bool(_WARM.search(text)), "Uses greetings, thanks or welcoming language.", "Warmth is not consistently signalled in the selected text."),
        ("humor", lambda text: bool(_HUMOR.search(text)), "Uses explicit laughter or playful emoji.", "Humor is not explicitly marked in the selected text."),
        ("person", lambda text: bool(_FIRST_PERSON.search(text)), "Uses first-person language.", "Avoids first-person language in the selected text."),
        ("calls_to_action", lambda text: bool(_CTA.search(text)), "Uses a direct call to action.", "Does not consistently use a direct call to action."),
        ("promotional_intensity", lambda text: bool(_PROMO.search(text)), "Uses explicit promotional language.", "Keeps promotional language restrained."),
        ("emoji", lambda text: bool(_EMOJI.search(text)), "Uses emoji.", "Does not consistently use emoji."),
        ("hashtags", lambda text: bool(_HASHTAG.search(text)), "Uses hashtags.", "Does not consistently use hashtags."),
    ):
        support, counter = split(pattern)
        evidence = support or counter
        dimensions.append(_dimension(identifier, yes if support else no, evidence, counter if support else []))

    sentence_counts = []
    paragraph_counts = []
    exclamation, questions = [], []
    for source_id, text in texts.items():
        sentences = [item.strip() for item in re.split(r"[.!?。！？]+", text) if item.strip()]
        words = re.findall(r"[A-Za-z0-9]+|[一-鿿]", text)
        sentence_counts.append((source_id, len(words) / max(len(sentences), 1)))
        paragraphs = [item for item in re.split(r"\n\s*\n|\n", text) if item.strip()]
        paragraph_counts.append((source_id, len(paragraphs)))
        if "!" in text or "！" in text:
            exclamation.append(source_id)
        if "?" in text or "？" in text:
            questions.append(source_id)
    average_sentence = round(sum(value for _, value in sentence_counts) / len(sentence_counts))
    average_paragraphs = round(sum(value for _, value in paragraph_counts) / len(paragraph_counts), 1)
    dimensions.extend([
        _dimension("sentence_length", f"Averages about {average_sentence} words or CJK characters per sentence in this sample set.", ids),
        _dimension("paragraph_length", f"Averages {average_paragraphs:g} short text blocks per sample.", ids),
        _dimension("openings", "Openings vary; keep the first line inspectable rather than assuming a fixed hook.", ids),
        _dimension("narrative_structure", "Selected samples are too limited to claim one fixed narrative structure.", ids),
        _dimension("vocabulary", "Reuse form and rhythm only; do not transfer names, dates, prices or claims from these samples.", ids),
        _dimension("punctuation", "Uses " + ("exclamation marks" if exclamation else "restrained exclamation") + (" and questions." if questions else "."), ids),
    ])
    validated = validate_proposal({"dimensions": dimensions}, projection)
    observations = [item["observation"] for item in validated["dimensions"] if item["evidenceLevel"] != "conflicting"]
    return {
        "schema": "postriff.voice-profile-proposal.v1",
        "status": "proposed",
        "tone": "warm",
        "toneBasis": "editable_starting_value",
        "writingExample": samples[0]["text"][:6000],
        "observations": observations,
        "unknowns": ["This profile is provisional until an owner approves it.", "Samples show writing form only; identity, beliefs, qualifications and factual claims remain unknown."],
        "preferences": [],
        "dimensions": validated["dimensions"],
        "quarantined": validated["quarantined"],
        "evidenceSourceIds": ids,
        "sourceBindings": [{"id": sample["id"], "revision": sample["revision"], "contentHash": sample["contentHash"]} for sample in samples],
        "analysisRoute": route,
        "analysisDigest": projection["digest"],
        "proposedBy": actor,
        "proposedAt": now,
    }


def apply_action(state: dict, action: str, payload: dict, actor: str, now: float) -> bool:
    if action != "voice_profile_analyze":
        return False
    source_ids = payload.get("sourceIds")
    route = payload.get("route", "local-rules")
    state.setdefault("speaker", {})["provisional"] = build_proposal(state, source_ids, actor, now, route)
    return True
