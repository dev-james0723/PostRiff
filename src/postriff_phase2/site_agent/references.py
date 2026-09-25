"""What "this draft", "that post", "the second one" and "the campaign we were just discussing" point to (§5.2, §18.3).

Every answer stores the items it named, in the order it showed them (`body.siteAgent.refs`: [{type, id, title}]).
A new message is resolved in a fixed order: "this" means what is selected on the page now; "that", ordinals and
"the one we discussed" mean the conversation's recent answers; a bare "it" means the page's selection, else the only
item the last answer named. When the words could mean several items, nothing is picked: the caller asks which one
(and never guesses for a change). A reference the page and the conversation cannot satisfy stays unresolved.
"""
from __future__ import annotations

import re

ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "last": -1,
            "第一": 0, "第二": 1, "第三": 2, "第四": 3, "第五": 4, "最後": -1}
TYPE_WORDS = (("draft", r"drafts?|草稿"), ("job", r"posts?|jobs?|帖|貼文"), ("campaign", r"campaigns?|活動"), ("automation", r"automations?|自動化"),
              ("source", r"sources?|來源"))
SAME = {"job": ("job", "review"), "review": ("job", "review"), "draft": ("draft",), "campaign": ("campaign", "automation"), "automation": ("automation", "campaign"),
        "source": ("source",)}
_ORDINAL = re.compile(r"\b(?:the\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th)\s+(?:one|draft|post|result|item|campaign|automation|source)\b|\bnumber\s+([1-9])\b|(第[一二三四五]|最後)(?:個|篇|項)", re.I)
_THAT = re.compile(r"\b(?:that|the)\s+(draft|post|job|campaign|automation|source)\b|\bthe\s+(draft|post|campaign|automation)\s+(?:we|i)\s+(?:were\s+|was\s+)?(?:just\s+)?(?:discussing|talking\s+about|discussed|looked\s+at)\b"
                   r"|(嗰個|嗰篇|頭先嗰個|頭先嗰篇)(草稿|帖|貼文|活動|自動化)?", re.I)
_THIS = re.compile(r"\bthis\s+(draft|post|job|campaign|automation|source)\b|呢(?:個|篇)(草稿|帖|貼文|活動|自動化)", re.I)
_BARE = re.compile(r"\b(?:it|that\s+one|this\s+one|that|this)\b|佢|呢個|嗰個", re.I)


def _type_of(word: str | None) -> str | None:
    if not word:
        return None
    for kind, pattern in TYPE_WORDS:
        if re.fullmatch(pattern, word, re.I):
            return kind
    return None


def _matches(ref: dict, kind: str | None) -> bool:
    return kind is None or ref.get("type") in SAME.get(kind, (kind,))


def resolve(text: str, page_entity: dict | None, history: list[list[dict]]) -> dict:
    """{"entity", "source": "page"|"conversation"|None, "candidates": [...], "ambiguous": bool}.
    `history` holds the refs of recent answers, newest first."""
    text = text or ""
    recent = [refs for refs in history if refs]
    flat = [ref for refs in recent for ref in refs]
    ordinal = _ORDINAL.search(text)
    if ordinal and recent:
        word = (ordinal.group(1) or ordinal.group(3) or "").lower()
        index = int(ordinal.group(2)) - 1 if ordinal.group(2) else ORDINALS.get(word, ORDINALS.get(ordinal.group(3) or "", None))
        kind = _type_of(re.search(r"(draft|post|campaign|automation|source)", ordinal.group(0), re.I).group(1)) if re.search(r"(draft|post|campaign|automation|source)", ordinal.group(0), re.I) else None
        listing = next((refs for refs in recent if len([r for r in refs if _matches(r, kind)]) > 1), recent[0])
        items = [r for r in listing if _matches(r, kind)]
        if index is not None and items and -len(items) <= index < len(items):
            return {"entity": items[index], "source": "conversation", "candidates": [], "ambiguous": False}
        return {"entity": None, "source": None, "candidates": items[:5], "ambiguous": True}
    this = _THIS.search(text)
    if this:
        kind = _type_of(this.group(1) or this.group(2))
        if page_entity and _matches(page_entity, kind):
            return {"entity": page_entity, "source": "page", "candidates": [], "ambiguous": False}
        found = next((r for r in flat if _matches(r, kind)), None)
        if found:
            return {"entity": found, "source": "conversation", "candidates": [], "ambiguous": False}
    that = _THAT.search(text)
    if that:
        kind = _type_of(next((g for g in that.groups()[:2] if g), None) or that.group(4))
        found = [r for r in flat if _matches(r, kind)]
        if found:
            return {"entity": found[0], "source": "conversation", "candidates": [], "ambiguous": False}
        if page_entity and _matches(page_entity, kind):
            return {"entity": page_entity, "source": "page", "candidates": [], "ambiguous": False}
        return {"entity": None, "source": None, "candidates": [], "ambiguous": False}
    if page_entity:
        return {"entity": page_entity, "source": "page", "candidates": [], "ambiguous": False}
    if _BARE.search(text) and recent:
        latest = recent[0]
        if len(latest) == 1:
            return {"entity": latest[0], "source": "conversation", "candidates": [], "ambiguous": False}
        return {"entity": None, "source": None, "candidates": latest[:5], "ambiguous": len(latest) > 1}
    return {"entity": None, "source": None, "candidates": [], "ambiguous": False}
