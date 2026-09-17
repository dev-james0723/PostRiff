"""Post languages as locale tags (docs/postriff-worldwide-languages-plan.md §2–§6).

A language is stored as a canonical BCP 47 tag from `locale_catalogue.json` (built by
`scripts/build_locale_catalogue.mjs`, shared byte-for-byte with the web app): `zh-Hant-HK`,
`yue-Hant-HK`, `en-GB`, `es-419`. Values stored before tags existed (`English`, `繁體中文`)
are read through `canonical` and never rewritten where they are hashed. Every channel can
carry several languages; a person's picks per channel live in `state["languageSettings"]`.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path


CATALOGUE_PATH = Path(__file__).with_name("locale_catalogue.json")
SETTINGS_ACTION = "language_settings"
SELF_REFERENCE = ("feminine", "masculine", "neutral")
MAX_LANGUAGES_PER_CHANNEL = 4
FAMILY_SAID = {"chinese", "中文"}  # a family name keeps a regional pick that is already Chinese
_TAG = re.compile(r"^[a-z]{2,3}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|\d{3}))?(?:-(?:[a-z0-9]{5,8}|\d[a-z0-9]{3}))*$")
_FOLD_PUNCT = re.compile(r"[()（）·,，、\-_/]+")
_SPACES = re.compile(r"\s+")
_TOKEN = r"[^\s,.;:!?()，。、；：！？「」“”\"']+"
_WORDS = re.compile(_TOKEN + r"(?:[ \t]+" + _TOKEN + r"){0,2}")
_ENGLISH_TRIGGER = re.compile(r"\b(?:in|into|using)\s+", re.I)
_CJK_TRIGGER = re.compile(r"[用以成做]\s?")
_JOIN = re.compile(r"\s*(?:\band\b|&|/|\bor\b|同|和|及|、|與|与|或)\s*", re.I)
CLAUSE_SPLIT = re.compile(r"[，,。;；\n!?！？]+|\.\s")


def fold(value):
    """Case-, accent- and width-insensitive form for matching names and aliases."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if not 0x300 <= ord(ch) <= 0x36F)
    text = unicodedata.normalize("NFC", text)
    return _SPACES.sub(" ", _FOLD_PUNCT.sub(" ", text)).strip()


@lru_cache(maxsize=1)
def catalogue():
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _index():
    cat = catalogue()
    by_tag = {e["tag"]: e for e in cat["entries"]}
    names, named = {}, {}
    for e in cat["entries"]:
        for name in (e["native"], e["english"]):
            names.setdefault(fold(name), e["tag"])
        for said in e["namedAs"]:
            named.setdefault(fold(said), e["tag"])
    return {
        "by_tag": by_tag,
        "by_lower": {tag.lower(): tag for tag in by_tag},
        "bases": {tag.split("-")[0].lower() for tag in by_tag},
        "names": names,
        "named": named,
        # Scripts written without spaces match by prefix; longest first so 繁體中文 wins over 中文.
        "unspaced": sorted({(said, e["tag"]) for e in cat["entries"] for said in e["namedAs"] if not said.isascii()}, key=lambda item: -len(item[0])),
    }


def _shape(parts):
    out = [parts[0]]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            out.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            out.append(part.upper())
        else:
            out.append(part)
    return out


def canonical(value, family_ok=False):
    """The stored tag for a value, or None when it names no language PostRiff knows.

    Accepts legacy values, input aliases (`zh-HK`, `yue`, `tl`…), any casing, and a language's
    own or English name. `family_ok` also allows a bare `zh` / `yue`, used only for learning scopes.
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 64:
        return None
    cat, idx = catalogue(), _index()
    if raw in cat["legacy"]:
        return cat["legacy"][raw]
    lower = raw.replace("_", "-").lower()
    if lower in cat["inputAliases"]:
        return cat["inputAliases"][lower]
    if lower in idx["by_lower"]:
        return idx["by_lower"][lower]
    by_name = idx["names"].get(fold(raw))
    if by_name:
        return by_name
    if not _TAG.match(lower):
        return None
    parts = lower.split("-")
    if parts[0] not in idx["bases"]:
        return None
    shaped = _shape(parts)
    if shaped[0] in ("zh", "yue"):
        if len(shaped) == 1:
            return shaped[0] if family_ok else None
        if len(shaped[1]) != 4:  # zh-HK → zh-Hant-HK: Chinese always keeps its script
            shaped.insert(1, "Hant" if shaped[1] in ("HK", "MO", "TW") else "Hans")
    tag = "-".join(shaped)
    if len(shaped) == 1 and tag not in idx["by_tag"]:
        # `ja` means the one listed Japanese (ja-JP); `hi`, with two listed forms, stays a language on its own.
        listed = [t for t in idx["by_tag"] if t.split("-")[0] == tag]
        if len(listed) == 1:
            return listed[0]
    return idx["by_lower"].get(tag.lower(), tag)


def is_valid(value):
    return canonical(value) is not None


def same(a, b):
    left = canonical(a, family_ok=True)
    return left is not None and left == canonical(b, family_ok=True)


def _truncations(tag):
    parts = tag.split("-")
    return ["-".join(parts[:i]) for i in range(len(parts), 0, -1)]


def entry(value):
    """Catalogue entry for a tag. A valid tag the catalogue doesn't list borrows its nearest listed ancestor."""
    tag = canonical(value, family_ok=True)
    if tag is None:
        return None
    by_tag = _index()["by_tag"]
    if tag in by_tag:
        return by_tag[tag]
    for candidate in _truncations(tag)[1:]:
        if candidate in by_tag:
            base = by_tag[candidate]
            region = tag.split("-")[-1]
            return {**base, "tag": tag, "native": f"{base['native']} ({region})", "english": f"{base['english']} ({region})",
                    "promptName": f"{base['promptName']} ({region})", "tier": "available", "guide": None, "guideDepth": None,
                    "reviewed": False, "regionless": False, "parent": candidate, "aliases": [], "namedAs": []}
    regional = next((e for t, e in by_tag.items() if t.split("-")[0] == tag), None)
    if regional and "-" not in tag:  # `fil` reads as the listed `fil-PH`
        return {**regional, "tag": tag, "regionless": True, "tier": "available", "guide": None, "guideDepth": None, "parent": regional["tag"]}
    if tag in ("zh", "yue"):
        return {"tag": tag, "family": "zh", "native": "中文", "english": "Chinese", "promptName": "Chinese", "tier": "available", "guide": None,
                "guideDepth": None, "reviewed": False, "regionless": True, "parent": None, "dir": "ltr", "glyphs": None, "flag": "🌐",
                "countUnit": "characters", "gendered": False, "aliases": [], "namedAs": []}
    return None


def display(value):
    item = entry(value)
    return item["native"] if item else (value if isinstance(value, str) else "")


def english_name(value):
    item = entry(value)
    return item["english"] if item else (value if isinstance(value, str) else "")


def prompt_name(value):
    item = entry(value)
    return item["promptName"] if item else (value if isinstance(value, str) else "")


def count_unit(value):
    item = entry(value)
    return item["countUnit"] if item else "words"


def is_regionless(value):
    item = entry(value)
    return bool(item and item["regionless"])


def scope_chain(value):
    """Tags whose learned rules apply to a draft in this language: itself, its shorter forms, then its
    parent's (so a `zh-Hant` or `zh` rule reaches `yue-Hant-HK` drafts, and an `es-419` rule reaches `es-MX`)."""
    tag = canonical(value, family_ok=True)
    if tag is None:
        return []
    chain, seen, current = [], set(), tag
    while current and current not in seen:
        seen.add(current)
        for candidate in _truncations(current):
            if candidate not in chain:
                chain.append(candidate)
        item = entry(current)
        current = item.get("parent") if item else None
    return chain


def guide_references(value, exists):
    """Skill reference paths for a destination language: its own guide; otherwise the nearest ancestor's
    guide, then its family guide and the generic guide. `exists(path)` checks the skill package."""
    tag = canonical(value, family_ok=True)
    if tag is None:
        return ["references/locales/_generic.md"]
    item = entry(tag)
    if item and item.get("guide") and exists(item["guide"]):
        return [item["guide"]]
    references = []
    for ancestor in scope_chain(tag)[1:]:
        parent = entry(ancestor)
        if parent and parent.get("guide") and exists(parent["guide"]):
            references.append(parent["guide"])
            break
    base = tag.split("-")[0]
    family = "zh" if base == "yue" else base
    if family in catalogue()["familyGuides"] and exists(f"references/locales/_family-{family}.md"):
        references.append(f"references/locales/_family-{family}.md")
    references.append("references/locales/_generic.md")
    return references


def usual_for(platform):
    return catalogue()["usual"].get(platform)


def suggest_from_text(text):
    """A starting language from the script a message is typed in. Only a suggestion, never a decision."""
    text = text or ""
    ranges = (((0x3040, 0x30FF), "ja-JP"), ((0xAC00, 0xD7AF), "ko-KR"), ((0x0E00, 0x0E7F), "th-TH"), ((0x0900, 0x097F), "hi-IN"),
              ((0x0600, 0x06FF), "ar"), ((0x0590, 0x05FF), "he-IL"), ((0x0400, 0x04FF), "ru-RU"), ((0x3400, 0x9FFF), "zh-Hant"))
    for (low, high), tag in ranges:
        if any(low <= ord(ch) <= high for ch in text):
            return tag
    return catalogue()["defaultLocale"]


# --- languages named in a message ----------------------------------------------------------------
def _said_at(text, index):
    """(tag, said) for a language name starting exactly at `index`, else None."""
    idx, rest = _index(), text[index:]
    match = _WORDS.match(rest)
    if match:
        words = match.group(0).split()
        for size in range(len(words), 0, -1):
            span = re.match(_TOKEN + (r"[ \t]+" + _TOKEN) * (size - 1), rest)
            if span:
                tag = idx["named"].get(fold(span.group(0)))
                if tag:
                    return tag, span.group(0)
    for said, tag in idx["unspaced"]:
        if rest.startswith(said):
            return idx["named"].get(fold(said), tag), said
    return None


def named_languages(text):
    """Every language named as an instruction, in order: after "in / into / using", or after 用 / 以 / 成 / 做,
    plus languages joined to one ("… in Hong Kong Chinese and British English", "用繁體中文同英文").
    Region words never count, so "our show in Hong Kong" names nothing. Returns [{tag, said, start, end}]."""
    text = text if isinstance(text, str) else ""
    hits = {}

    def take(start, found):
        tag, said = found
        end = start + len(said)
        hits.setdefault(start, {"tag": tag, "said": said, "start": start, "end": end})
        for _ in range(3):
            joined = _JOIN.match(text, end)
            if not joined or joined.end() == end:
                break
            following = _said_at(text, joined.end())
            if not following:
                break
            hits.setdefault(joined.end(), {"tag": following[0], "said": following[1], "start": joined.end(), "end": joined.end() + len(following[1])})
            end = joined.end() + len(following[1])

    for match in _ENGLISH_TRIGGER.finditer(text):
        found = _said_at(text, match.end())
        if found:
            take(match.end(), found)
    for match in _CJK_TRIGGER.finditer(text):
        found = _said_at(text, match.end())
        if found and not found[1].isascii():
            take(match.end(), found)
    return [hits[key] for key in sorted(hits)]


def pair_with_channels(text, mentions):
    """Languages named in each clause, paired with the channels named in it.

    `mentions(clause)` returns [(index, platform)]. A run of languages belongs to the run of channels
    just before it, else just after; a clause that names languages and no channel applies to every
    channel (platforms == []). Returns [{"tags": [...], "said": [...], "platforms": [...]}]."""
    pairs = []
    for clause in CLAUSE_SPLIT.split(text if isinstance(text, str) else ""):
        languages = named_languages(clause)
        if not languages:
            continue
        events = [(hit["start"], "l", hit) for hit in languages] + [(index, "c", platform) for index, platform in mentions(clause)]
        events.sort(key=lambda event: (event[0], event[1]))
        if not any(kind == "c" for _, kind, _ in events):
            pairs.append({"tags": [h["tag"] for h in languages], "said": [h["said"] for h in languages], "platforms": []})
            continue
        runs = []
        for _, kind, value in events:
            if runs and runs[-1]["kind"] == kind:
                runs[-1]["items"].append(value)
            else:
                runs.append({"kind": kind, "items": [value], "used": False})
        for position, run in enumerate(runs):
            if run["kind"] != "l":
                continue
            before = runs[position - 1] if position > 0 else None
            after = runs[position + 1] if position + 1 < len(runs) else None
            target = before if before and not before["used"] else (after if after and not after["used"] else None)
            if target is None:
                continue
            target["used"] = True
            platforms = list(dict.fromkeys(target["items"]))
            pairs.append({"tags": [h["tag"] for h in run["items"]], "said": [h["said"] for h in run["items"]], "platforms": platforms})
    return pairs


def apply_named(current, tags, said):
    """A channel's languages once the message names `tags`: a family or no-region name keeps picks already in it."""
    result = []
    for tag, words in zip(tags, said):
        family = "zh" if fold(words) in FAMILY_SAID else tag
        fitting = [c for c in current if c != family and family in scope_chain(c)] if is_regionless(family) else []
        result.extend(fitting or [tag])
    return list(dict.fromkeys(result))


# --- per-channel language settings ------------------------------------------------------------
def settings(state):
    value = (state or {}).get("languageSettings")
    value = value if isinstance(value, dict) else {}
    channels = value.get("channels") if isinstance(value.get("channels"), dict) else {}
    return {
        "default": canonical(value.get("default")),
        "channels": {p: [t for t in (canonical(x) for x in tags) if t] for p, tags in channels.items() if isinstance(tags, list)},
        "selfReference": value.get("selfReference") if value.get("selfReference") in SELF_REFERENCE else None,
    }


def languages_for(platform, state=None):
    """A channel's starting languages: last used there, its usual language, the workspace default, English."""
    current = settings(state)
    remembered = current["channels"].get(platform)
    if remembered:
        return remembered
    usual = usual_for(platform)
    if usual:
        return [usual]
    return [current["default"] or catalogue()["defaultLocale"]]


def apply_language_action(state, action, payload, actor, now=None):
    """`language_settings`: merge per-channel languages, the workspace default and self-reference. True when consumed."""
    if action != SETTINGS_ACTION:
        return False
    from postriff_alpha.domain import AlphaError  # imported here: postriff_alpha.learning imports this module
    if not isinstance(payload, dict):
        raise AlphaError("Expected language settings.")
    current = state.get("languageSettings") if isinstance(state.get("languageSettings"), dict) else {}
    channels = dict(current.get("channels") or {})
    if "channels" in payload:
        if not isinstance(payload["channels"], dict) or len(payload["channels"]) > 50:
            raise AlphaError("Choose languages for up to 50 channels.")
        for platform, tags in payload["channels"].items():
            if not isinstance(platform, str) or not 1 <= len(platform) <= 60 or not isinstance(tags, list):
                raise AlphaError("Choose a list of languages for each channel.")
            if any(canonical(tag) is None for tag in tags):
                raise AlphaError("One of those languages isn't one PostRiff knows.")
            clean = list(dict.fromkeys(canonical(tag) for tag in tags))
            if len(clean) > MAX_LANGUAGES_PER_CHANNEL:
                raise AlphaError(f"Use up to {MAX_LANGUAGES_PER_CHANNEL} languages on one channel.")
            if clean:
                channels[platform] = clean
            else:
                channels.pop(platform, None)
    default = current.get("default")
    if "default" in payload:
        default = canonical(payload["default"]) if payload["default"] is not None else None
        if payload["default"] is not None and default is None:
            raise AlphaError("That default language isn't one PostRiff knows.")
    self_reference = current.get("selfReference")
    if "selfReference" in payload:
        if payload["selfReference"] is not None and payload["selfReference"] not in SELF_REFERENCE:
            raise AlphaError("Choose feminine, masculine or neutral wording.")
        self_reference = payload["selfReference"]
    state["languageSettings"] = {"default": default, "channels": channels, "selfReference": self_reference,
                                 "updatedBy": actor, "updatedAt": now if now is not None else time.time()}
    return True
