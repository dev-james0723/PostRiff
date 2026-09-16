"""A chat instruction read as a preference proposal (preference-learning design §3 signal 1, §5.5).

Deterministic, no model: the sentence names what to do or avoid (hashtags, emoji, openings, the
closing, lists, length, language mix, punctuation), optionally for one channel or language. A
sentence the vocabulary does not cover becomes an `other` proposal in the person's own words, which
still has to pass `learning.lint`. The person decides; nothing here writes memory.
"""
from __future__ import annotations

import re

from . import intent

NEGATION = re.compile(r"\b(?:no|not|don'?t|do not|never|stop|without|avoid|skip|drop|fewer|less)\b|唔好|不要|唔要|唔使|不用|唔加|不加|唔用|別|冇|無|去掉|刪走|删掉|少啲|少一點", re.I)
LANGUAGE_WORDS = (("繁體中文", re.compile(r"繁體|繁体|中文|廣東話|粤語|粵語|traditional chinese|\bchinese\b|cantonese", re.I)), ("English", re.compile(r"英文|\benglish\b", re.I)))
RULES = (
    ("hashtags.use", re.compile(r"hashtags?|標籤|标签|#", re.I), {"avoid": "No hashtags.", "do": "Use hashtags."}),
    ("emoji.use", re.compile(r"emojis?|表情|emoticons?", re.I), {"avoid": "No emoji.", "do": "Use emoji."}),
    ("exclamation.use", re.compile(r"exclamation|感嘆號|感叹号|嘆號", re.I), {"avoid": "No exclamation marks.", "do": "Exclamation marks are fine."}),
    ("closing.cta", re.compile(r"call to action|\bcta\b|comment below|留言|follow|追蹤|关注|link in bio|dm me|私訊|私信", re.I), {"avoid": "Don't end with a call to action.", "do": "End with a call to action."}),
    ("lists.use", re.compile(r"bullets?|bullet points?|lists?|列點|列点|條列|条列", re.I), {"avoid": "No bullet lists.", "do": "Use bullet lists."}),
    ("paragraphs.density", re.compile(r"paragraphs?|段落|分段|一段", re.I), {"avoid": "Keep paragraphs short.", "do": "Keep paragraphs short."}),
    ("opening.style", re.compile(r"opening|first (?:line|sentence)|開頭|开头|第一句|起首|hook", re.I), {"avoid": "Don't open with a question.", "do": "Put the point in the first sentence."}),
    ("length.target", re.compile(r"\bshorter\b|\blonger\b|\bshort\b|\blong\b|\bwords?\b|\bcharacters?\b|字數|字数|長度|长度|短啲|短一點|長啲|长一点|簡短|简短", re.I), None),
    ("language.mix", re.compile(r"mix|夾雜|夹杂|中英|bilingual|translate|翻譯|翻译|術語|术语", re.I), None),
    ("punctuation.style", re.compile(r"punctuation|標點|标点|全形|半形|full-?width|half-?width", re.I), None),
)
WORKING_STYLE = re.compile(r"\bask(?:ing)?\b|questions?|問我|问我|清單|checklist|options?|版本|variants?|drafts? per|幾個|几个", re.I)


def platform_mentioned(text):
    lowered = text.lower()
    for platform, aliases in intent.PLATFORM_ALIASES:
        for alias in aliases:
            if alias.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
                    return platform
            elif alias in text:
                return platform
    return None


def language_mentioned(text):
    for language, pattern in LANGUAGE_WORDS:
        if pattern.search(text):
            return language
    return None


def instruction_to_proposal(text, language=None):
    """The proposal a standing instruction implies. Statement templates are English for known rules so
    VOICE.md reads as one document; an unknown rule keeps the person's own sentence."""
    sentence = " ".join((text or "").split())
    polarity = "avoid" if NEGATION.search(sentence) else "do"
    scope = {"platform": platform_mentioned(sentence), "language": language_mentioned(sentence), "contentTypeId": None}
    kind, rule_key, statement = "writing_preference", "other", sentence
    for key, pattern, templates in RULES:
        if pattern.search(sentence):
            rule_key = key
            if templates:
                statement = templates[polarity]
            break
    if rule_key == "other" and WORKING_STYLE.search(sentence):
        kind = "working_style"
    params = {}
    if rule_key == "opening.style" and polarity == "do" and re.search(r"short|簡短|简短|短", sentence, re.I):
        params = {"shortOpenings": True}
        statement = "Use shorter openings."
    return {"type": kind, "ruleKey": rule_key, "polarity": polarity, "scope": scope, "statement": statement, "params": params,
            "source": "chat", "why": "You said so in chat.", "evidence": []}
