"""The pack's editable copy, prepared deterministically from a draft (PRD R-VIS-01/02).

`creative.plan_assets` supplies the carousel structure (hook → points → close) and the brief's single call to action;
the draft's own sentences fill it in order. Nothing is invented: a draft with fewer sentences than slides leaves a slide
empty for the person to write, and alt text starts as exactly the text the slide shows (plus the image's own stored
description when one exists), never an observation about the picture.
"""
from __future__ import annotations

from .. import locales
from ..coworker import creative
from . import checks

KEYS = tuple(f"s{i}" for i in range(1, checks.SLIDES + 1))
TEXT_LIMIT = 2000
CAPTION_LIMIT = 5000
_CJK_ENDERS = "。！？"
_LATIN_ENDERS = ".!?"
_CLOSERS = "」』”’）)］】〉》\"'"
_CJK_CLAUSE = "，；：、"
_LATIN_CLAUSE = (", ", "; ", ": ", " — ", " – ")
MIN_SPLIT = 24   # a sentence shorter than this is never cut into clauses
_LABELS = {"en": {"generated": "AI-generated image", "edited": "AI-edited image", "image": "Image", "none": "no description saved"},
           "zh": {"generated": "AI 生成圖像", "edited": "AI 編修圖像", "image": "圖片", "none": "未儲存描述"}}


def language(tag) -> str:
    """The pack's language as a canonical locale tag ('und' when the draft names none PostRiff knows)."""
    return locales.canonical(tag) or "und"


def _ui(lang: str) -> str:
    return "zh" if lang.lower().startswith("zh") else "en"


def _latin_end(text: str, i: int) -> bool:
    """A Latin . ! ? ends a sentence only before a space, a CJK character or the end (so 9.5, rafii.app and ?c= stay)."""
    j = i + 1
    while j < len(text) and (text[j] in _CLOSERS or text[j] in _LATIN_ENDERS):
        j += 1
    return j == len(text) or text[j].isspace() or checks.is_cjk(text[j])


def sentences(text: str) -> list[str]:
    """Sentences in order, with any closing quote or bracket kept on its sentence; every line break also ends one."""
    out, current, i = [], "", 0
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            if current.strip():
                out.append(current.strip())
            current, i = "", i + 1
            continue
        current += ch
        if ch in _CJK_ENDERS or (ch in _LATIN_ENDERS and _latin_end(text, i)):
            while i + 1 < len(text) and (text[i + 1] in _CLOSERS or text[i + 1] in _CJK_ENDERS or text[i + 1] in _LATIN_ENDERS):
                i += 1
                current += text[i]
            if current.strip():
                out.append(current.strip())
            current = ""
        i += 1
    if current.strip():
        out.append(current.strip())
    return out


def display_length(text: str) -> int:
    """Rough visual length: a CJK character is about two Latin letters wide."""
    return sum(2 if checks.is_cjk(ch) else 1 for ch in text)


def _clause_cut(unit: str):
    """The clause boundary nearest the middle of a unit: after CJK ，；：、 or a ―― pair, or after a Latin comma,
    semicolon, colon or spaced dash."""
    cuts = [i + 1 for i, ch in enumerate(unit[:-1]) if ch in _CJK_CLAUSE]
    cuts += [i + 2 for i in range(len(unit) - 2) if unit[i:i + 2] == "——"]
    cuts += [i + len(mark.rstrip()) for mark in _LATIN_CLAUSE for i in range(len(unit)) if unit.startswith(mark, i) and 0 < i < len(unit) - len(mark)]
    cuts = [c for c in cuts if unit[:c].strip() and unit[c:].strip()]
    return min(cuts, key=lambda c: (abs(len(unit) / 2 - c), c)) if cuts else None


def units(text: str, wanted: int = checks.SLIDES) -> list[str]:
    """Sentences, and while there are fewer than `wanted`, the visually longest sentence cut at its middle clause
    boundary. Every character of the draft stays, in order."""
    parts = sentences(text)
    while len(parts) < wanted:
        ranked = sorted(((display_length(p), -i) for i, p in enumerate(parts) if display_length(p) >= MIN_SPLIT and _clause_cut(p)), reverse=True)
        if not ranked:
            break
        index = -ranked[0][1]
        cut = _clause_cut(parts[index])
        parts[index:index + 1] = [parts[index][:cut].strip(), parts[index][cut:].strip()]
    return parts


def _join(parts: list[str]) -> str:
    text = ""
    for part in parts:
        if text and not (checks.is_cjk(text[-1]) or checks.is_cjk(part[0])):
            text += " "
        text += part
    return text


def split_draft(text: str, cta: str | None = None) -> list[str]:
    """Six slide texts: the first sentence is the hook; the sentence carrying the brief's call to action (else the
    last sentence) is the close; the rest fill the four points in order, balanced by length. No sentence is dropped
    or rewritten."""
    parts = units(text)
    slides = [""] * checks.SLIDES
    if not parts:
        return slides
    slides[0] = parts.pop(0)
    if len(parts) > 1:
        close = next((i for i, part in enumerate(parts) if cta and cta.lower() in part.lower()), len(parts) - 1)
        slides[-1] = parts.pop(close)
    elif parts:
        slides[-1] = parts.pop()
    points = checks.SLIDES - 2
    groups, group, used, total = [], [], 0, sum(len(p) for p in parts)
    for index, part in enumerate(parts):
        group.append(part)
        used += len(part)
        later_parts, later_groups = len(parts) - index - 1, points - len(groups) - 1
        # Close this slide once it holds its share of the text, or when each later slide still needs a sentence.
        if later_groups > 0 and (used >= total * (len(groups) + 1) / points or later_parts == later_groups):
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    for i, chosen in enumerate(groups):
        slides[1 + i] = _join(chosen)
    return slides


def generated_label(asset, lang: str = "en") -> str | None:
    """Rafii-made imagery is labelled on the slide and in its alt text, so it is never read as documentary proof."""
    if not isinstance(asset, dict):
        return None
    lineage = asset.get("lineage") if isinstance(asset.get("lineage"), dict) else {}
    operation = lineage.get("operation")
    words = _LABELS[_ui(lang)]
    if operation in ("generated", "generate"):
        return words["generated"]
    if operation in ("edit", "variant"):
        return words["edited"]
    return words["generated"] if asset.get("origin") == "rafii_agent" else None


def default_alt(position: int, text: str, asset=None, lang: str = "en") -> str:
    """What the slide visibly shows: its position, its text verbatim, and the image's own stored description."""
    zh = _ui(lang) == "zh"
    flat = " ".join(text.split())
    alt = f"第 {position} 張，共 {checks.SLIDES} 張。" + (f"文字：{flat}" if flat else "") if zh else \
        f"Slide {position} of {checks.SLIDES}." + (f" Text: {flat}" if flat else "")
    if asset is not None:
        words = _LABELS["zh" if zh else "en"]
        described = " ".join(str(asset.get("alt") or "").split()) or words["none"]
        alt += ("" if zh else " ") + f"{generated_label(asset, lang) or words['image']}{'：' if zh else ': '}{described}{'。' if zh else '.'}"
    return alt[:checks.ALT_MAX]


def from_draft(state: dict, variant: dict) -> dict:
    text = checks.normalize_text(variant.get("text") or "", 20_000)
    spec = creative.PLATFORM_SPECS.get((variant.get("platform"), "carousel"))
    platform = variant["platform"] if spec and spec["size"] == [checks.WIDTH, checks.HEIGHT] else "Instagram"
    first = sentences(text)[:1]
    plan = creative.plan_assets(state, {"message": first[0] if first else "", "copy": text, "slides": checks.SLIDES, "documentary": True},
                                [platform], fmt="carousel", assets=[])
    carousel = plan["plans"][0]["carousel"]
    if carousel["slides"] != checks.SLIDES:
        raise ValueError("the creative plan no longer yields six slides")
    cta = plan["plans"][0]["cta"]["primary"]
    lang = language(variant.get("language"))
    texts = [t[:TEXT_LIMIT] for t in split_draft(text, cta)]
    return {"slides": [{"key": KEYS[i], "text": texts[i], "altText": default_alt(i + 1, texts[i], lang=lang), "imageAssetId": None,
                        "plannedRole": carousel["structure"][i].split(":")[0]} for i in range(checks.SLIDES)],
            "caption": text[:CAPTION_LIMIT], "language": lang,
            "plan": {"schema": plan["schema"], "platform": platform, "structure": carousel["structure"], "rule": carousel["rule"],
                     "cta": cta, "numbersToVerify": plan["numbersToVerify"], "registryRelease": plan["compiled"]["registryRelease"]}}
