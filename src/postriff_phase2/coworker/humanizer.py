"""Hidden quality stage: draft → voice fit → humanizer → fact/meaning preservation → platform/locale lint → candidate
(adaptive coworker spec §10; architecture lock H1).

Deterministic and model-free. It never rewrites a draft: it annotates the candidate with findings and says what a
revise-capable route should fix. Pattern data (`humanizer_patterns.json`) is generalised from MIT-licensed
humanizer skills (attribution in `skills/rafii-humanizer-*/LICENSE-NOTICE.md`); patterns are clues judged in
clusters, never a blacklist, and the approved brand terminology is never flagged.

The meaning-preservation check compares the candidate with its source (or approved facts) and reports every
number, date, name, negation, hedge, attribution, scope, status or causal claim that changed, plus invented
feelings or anecdotes. A violation blocks nothing by itself here; the Weekly Operator and Source-to-Campaign
quality gates decide (a changed fact marks the draft `needs_revision`).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

VERSION = "1.0.0"
PATTERNS_PATH = Path(__file__).with_name("humanizer_patterns.json")
VIOLATIONS = ("number_changed", "number_added", "date_changed", "name_changed", "name_added", "negation_lost", "hedge_removed", "certainty_added",
              "attribution_lost", "scope_changed", "status_changed", "causal_added", "anecdote_added", "feeling_added", "brand_term_changed")

_WORD = re.compile(r"[A-Za-z']+|[一-鿿]")


@lru_cache(maxsize=1)
def patterns():
    if not PATTERNS_PATH.is_file():
        return {"version": "missing", "en": {}, "zh": {}, "yue": {}, "thresholds": {}, "_compiled": {}}
    data = json.loads(PATTERNS_PATH.read_text())
    compiled = {"en": [], "zh": [], "yue": []}
    groups = {"en": ("phrase_patterns", "signposting", "chatbot_residue"), "zh": ("phrase_patterns", "translationese"), "yue": ("phrase_patterns",)}
    for lang, names in groups.items():
        for group in names:
            for item in (data.get(lang) or {}).get(group) or []:
                if not isinstance(item, dict) or not item.get("regex"):
                    continue
                # Translationese structures the upstream research did not find actionable are informational only.
                if group == "translationese" and not item.get("actionable"):
                    continue
                compiled[lang].append((item["id"], re.compile(item["regex"], re.I), item.get("family") or group, float(item.get("weight", 1.0))))
    data["_compiled"] = compiled
    return data


def _words(text):
    return max(1, len(_WORD.findall(text or "")))


def _cjk(text):
    return sum(1 for ch in text or "" if "\u4e00" <= ch <= "\u9fff")


def _language(locale):
    base = str(locale or "en").split("-")[0].lower()
    return "zh" if base in ("zh", "yue") else "en"


def detect(text, locale="en", brand_terms=()):
    """Synthetic-writing clues. A finding is raised only for a cluster (enough weighted hits from at least two
    families), never for one word; density thresholds are per 100 words (en) or per 1000 CJK characters (zh).
    Approved brand terms are never counted. Script mixing (a Simplified-only character in Traditional copy or the
    reverse) is reported as a locale finding."""
    data = patterns()
    thresholds = data.get("thresholds") or {}
    lang = _language(locale)
    lowered_locale = str(locale or "").lower()
    groups = [lang] + (["yue"] if lowered_locale.startswith(("yue", "zh-hant-hk")) else [])
    protected = [t.lower() for t in brand_terms or () if t]
    for term in brand_terms or ():
        if term:
            # Approved terminology is never evidence of synthetic writing: it is removed before scanning.
            text = re.sub(re.escape(term), " ", text or "", flags=re.I)
    hits = []
    for group in groups:
        for pid, regex, family, weight in data.get("_compiled", {}).get(group, []):
            for match in regex.finditer(text or ""):
                if any(term in match.group(0).lower() for term in protected):
                    continue
                hits.append({"id": pid, "family": family, "weight": weight, "match": match.group(0)[:60]})
    vocabulary = []
    if lang == "en":
        lowered = (text or "").lower()
        vocabulary = [w for w in (data.get("en") or {}).get("ai_vocabulary") or [] if isinstance(w, str) and w.lower() not in protected
                      and re.search(r"\b" + re.escape(w.lower()) + r"\b", lowered)]
    weighted = sum(h["weight"] for h in hits) + 0.5 * len(vocabulary)
    families = {h["family"] for h in hits} | ({"vocabulary"} if vocabulary else set())
    findings = []
    if lang == "en":
        size, density = _words(text), round(100 * weighted / _words(text), 2)
        dense = size < int(thresholds.get("min_words_for_density", 40)) or density >= float(thresholds.get("density_per_100_words_warn", 2.0))
    else:
        size, density = _cjk(text), round(1000 * weighted / max(1, _cjk(text)), 2)
        dense = size < int(thresholds.get("min_cjk_chars_for_density", 80)) or density >= float(thresholds.get("zh_density_per_1000_chars_warn", 4.0))
    if weighted >= float(thresholds.get("cluster_min_hits", 3)) and len(families) >= int(thresholds.get("cluster_min_distinct_families", 2)) and dense:
        findings.append({"code": "synthetic_cluster", "detail": f"{len(hits) + len(vocabulary)} synthetic-writing clues across {len(families)} families.",
                         "examples": [h["match"] for h in hits[:4]] + vocabulary[:3]})
    dashes = len(re.findall(r"—|–|--", text or ""))
    if dashes >= 3 and (100 * dashes / _words(text) >= float(thresholds.get("dash_density_per_100_words_clue", 1.5))):
        findings.append({"code": "dash_density", "detail": f"{dashes} dashes; a clue only, keep intentional ones."})
    markers = (data.get("zh") or {}).get("script_markers") or {}
    if lang == "zh" and markers:
        traditional = lowered_locale.startswith(("zh-hant", "zh-tw", "zh-hk", "zh-mo", "yue"))
        wrong = markers.get("hans_only", "") if traditional else markers.get("hant_only", "")
        mixed = sorted({ch for ch in text or "" if ch in wrong})
        if mixed and lowered_locale not in ("zh", ""):
            findings.append({"code": "script_mixed", "detail": f"{'Simplified' if traditional else 'Traditional'} characters in {locale} copy: {''.join(mixed[:8])}"})
    register = None
    if lowered_locale.startswith(("yue", "zh-hant-hk")):
        colloquial = [m for m in (data.get("yue") or {}).get("colloquial_markers") or [] if m in (text or "")]
        register = {"colloquialMarkers": colloquial[:8], "written": not colloquial}
    return {"hits": hits, "vocabulary": vocabulary, "density": density, "families": sorted(families), "dashes": dashes, "findings": findings, "register": register}


WEEK_WORDS = {"週": "周", "星期": "周", "禮拜": "周", "礼拜": "周", "天": "日"}


@lru_cache(maxsize=1)
def _lexicon():
    """Compiled meaning lexicon (data in humanizer_patterns.json → meaning_lexicon: en + zh token lists per category,
    date/number/name patterns). Data-driven so a locale pack can extend it without code changes."""
    lex = patterns().get("meaning_lexicon") or {}
    categories = {}
    for lang in ("en", "zh"):
        for category, expressions in (lex.get(lang) or {}).items():
            categories.setdefault(category, []).extend(re.compile(x, re.I) for x in expressions)
    return {"date": re.compile(lex.get("date_regex") or r"(?!x)x", re.I), "number": re.compile(lex.get("number_regex") or r"\d+(?:\.\d+)?"),
            "name": re.compile(lex.get("latin_name_regex") or r"(?!x)x"), "stop": set(lex.get("name_leading_stopwords") or []), "categories": categories}


def _norm_date(text):
    text = re.sub(r"\s+", "", text.lower())
    text = re.sub(r"(day)s$", r"\1", text)
    for a, b in WEEK_WORDS.items():
        text = text.replace(a, b)
    return text


def _tokens(text, brand_terms):
    from collections import Counter
    lex = _lexicon()
    text = text or ""
    dates = Counter(_norm_date(m.group(0)) for m in lex["date"].finditer(text))
    rest = lex["date"].sub(" ", text)
    numbers = Counter(n.replace(",", "") for n in lex["number"].findall(rest))
    for term in brand_terms:
        rest = rest.replace(term, " ")
    names = Counter()
    for match in lex["name"].finditer(rest):
        token = match.group(0)
        before = rest[:match.start()].rstrip()
        if not before or before[-1] in ".!?。！？:：「“\"(（\n":
            parts = token.split()
            if parts[0] in lex["stop"]:
                parts = parts[1:]
            elif len(parts) == 1:
                continue  # a single capitalised word opening a sentence is not evidence of a name
            if not parts:
                continue
            token = " ".join(parts)
        names[token] += 1
    categories = {}
    for category, expressions in lex["categories"].items():
        found = Counter()
        for expression in expressions:
            for match in expression.finditer(text):
                found[match.group(0).lower()] += 1
        categories[category] = found
    brands = Counter({term: text.count(term) for term in brand_terms})
    return dates, numbers, names, categories, brands


def meaning_diff(source, candidate, brand_terms=()):
    """What the candidate changed relative to its source: [{code, detail}] in VIOLATIONS order. Empty = preserved.
    Counts, not presence: dropping one of two hedges is a lost hedge."""
    brand_terms = [t for t in brand_terms or () if t]
    sd, sn, s_names, sc, sb = _tokens(source, brand_terms)
    od, on, o_names, oc, ob = _tokens(candidate, brand_terms)
    total = lambda counter: sum(counter.values())  # noqa: E731
    found = {}
    if sn - on:
        found["number_changed"] = f"missing or changed: {sorted(sn - on)[:5]}"
    elif on - sn:
        found["number_added"] = f"not in the source: {sorted(on - sn)[:5]}"
    if sd != od:
        found["date_changed"] = f"source {sorted(sd)[:3]} vs candidate {sorted(od)[:3]}"
    if s_names - o_names:
        found["name_changed"] = f"missing: {sorted(s_names - o_names)[:4]}"
    elif o_names - s_names:
        found["name_added"] = f"not in the source: {sorted(o_names - s_names)[:4]}"
    get = lambda cats, key: cats.get(key) or __import__("collections").Counter()  # noqa: E731
    if total(get(oc, "negation")) < total(get(sc, "negation")):
        found["negation_lost"] = "the candidate has fewer negations than the source"
    if total(get(oc, "hedge")) < total(get(sc, "hedge")):
        found["hedge_removed"] = "uncertainty in the source was dropped"
    if get(oc, "certainty") - get(sc, "certainty"):
        found["certainty_added"] = f"added certainty: {sorted(get(oc, 'certainty') - get(sc, 'certainty'))[:3]}"
    if total(get(oc, "attribution")) < total(get(sc, "attribution")):
        found["attribution_lost"] = "a source attribution was dropped"
    if get(oc, "scope") != get(sc, "scope"):
        found["scope_changed"] = "a qualifier of scope changed (some/all, only/every)"
    if (get(oc, "done") - get(sc, "done")) or total(get(oc, "planned")) < total(get(sc, "planned")):
        found["status_changed"] = "something planned or in progress now reads as done"
    if get(oc, "causal") - get(sc, "causal"):
        found["causal_added"] = "a cause-and-effect claim not in the source"
    if get(oc, "anecdote") - get(sc, "anecdote"):
        found["anecdote_added"] = "a personal anecdote not in the source"
    if get(oc, "feeling") - get(sc, "feeling"):
        found["feeling_added"] = "a feeling not in the source"
    for term in brand_terms:
        if ob[term] < sb[term]:
            found["brand_term_changed"] = f"approved term “{term}” was changed or removed"
    return [{"code": code, "detail": found[code]} for code in VIOLATIONS if code in found]


# --- checks for an edit of text the author already has (draft_edits.fidelity) -------------------------------------------
# A tone or polish edit must also keep what `meaning_diff` does not look at: links, quoted words and the language the
# text is written in. Reported with these three codes beside VIOLATIONS; like every finding here they annotate and
# never block. Mixed-language text is read per run of one script, so an English phrase inside a Chinese post is
# scanned with the English patterns and the Chinese around it with the Chinese ones.
EDIT_VIOLATIONS = ("url_changed", "quote_changed", "language_changed")

_LINK = re.compile(r"https?://[^\s<>\"'「」『』（）()，。！？、；]+|www\.[^\s<>\"'「」『』（）()，。！？、；]+"
                   r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
                   r"|(?<![A-Za-z0-9_@/.])@[A-Za-z0-9_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?"
                   r"|(?<![\w#&/])#(?=\w*[^\W\d_])\w+", re.I)
_QUOTED = re.compile("“([^“”\n]{2,400})”|「([^「」\n]{2,400})」|『([^『』\n]{2,400})』|\"([^\"\n]{2,400})\"|‘([^‘’\n]{6,400})’")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f'\u2019-]*")
_RUN = re.compile(r"(?P<zh>[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+)|(?P<en>[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f'\u2019-]*)")
# Other scripts, counted per character at a weight that makes a word of each worth about the same.
_SCRIPTS = (("kana", re.compile(r"[\u3040-\u30ff]"), 0.4), ("hangul", re.compile(r"[\uac00-\ud7a3\u1100-\u11ff]"), 0.5),
            ("cyrillic", re.compile(r"[\u0400-\u04ff]"), 0.2), ("greek", re.compile(r"[\u0370-\u03ff]"), 0.2),
            ("arabic", re.compile(r"[\u0600-\u06ff]"), 0.2), ("hebrew", re.compile(r"[\u0590-\u05ff]"), 0.2),
            ("thai", re.compile(r"[\u0e00-\u0e7f]"), 0.2), ("devanagari", re.compile(r"[\u0900-\u097f]"), 0.2))
# Function words: a text made of these is English, whatever its nouns are.
_ENGLISH = frozenset("the a an and or but to of in on at for with from by is are was were be been it this that these those we you i they he she our your my "
                     "their will can not have has had do does as if so about more what when how all there here us me just than then out up no".split())
SCRIPT_LABELS = {"latin": "Latin-script", "han": "Chinese", "kana": "Japanese", "hangul": "Korean"}


def links(text):
    """Every URL, email address, @handle and #hashtag in the text, exactly as written (a multiset)."""
    from collections import Counter
    return Counter(match.group(0).rstrip(".,;:!?…") for match in _LINK.finditer(text or ""))


def quotations(text):
    """The words inside each pair of quotation marks (“ ”, " ", 「 」, 『 』, ‘ ’), whatever the marks are."""
    from collections import Counter
    return Counter(" ".join(next(group for group in match.groups() if group is not None).split()) for match in _QUOTED.finditer(text or ""))


def link_diff(source, candidate):
    """What changed among links, handles, hashtags and email addresses, or None. They are compared character for character."""
    before, after = links(source), links(candidate)
    if before - after:
        return f"missing or changed: {sorted(before - after)[:4]}"
    if after - before:
        return f"not in the original: {sorted(after - before)[:4]}"
    return None


def quote_diff(source, candidate):
    """Quoted words that are no longer word for word the same, or quoted words the original does not have; or None."""
    before, after = quotations(source), quotations(candidate)
    if before - after:
        return f"quoted words changed or removed: {sorted(before - after)[:3]}"
    if after - before:
        return f"quoted words not in the original: {sorted(after - before)[:3]}"
    return None


def language_profile(text):
    """Counts that describe which language a text is written in, never the text: weighted units per script, characters
    found only in Simplified or only in Traditional writing, distinct written-Cantonese markers, and the share of
    Latin-script words that are English function words. Links, handles and hashtags are left out."""
    text = _LINK.sub(" ", text or "")
    words = [word.lower() for word in _LATIN_WORD.findall(text)]
    han = len(_HAN.findall(text))
    units = {"latin": float(len(words)), "han": round(han * 0.6, 2)}
    for name, pattern, weight in _SCRIPTS:
        found = len(pattern.findall(text))
        if found:
            units[name] = round(found * weight, 2)
    data = patterns()
    markers = (data.get("zh") or {}).get("script_markers") or {}
    yue = data.get("yue") or {}
    plain = text
    for compound in yue.get("exclude_compounds") or []:
        plain = plain.replace(compound, " ")
    return {"units": {name: value for name, value in units.items() if value}, "words": len(words), "han": han,
            "hans": sum(1 for ch in text if ch in markers.get("hans_only", "")), "hant": sum(1 for ch in text if ch in markers.get("hant_only", "")),
            "cantonese": sum(1 for marker in yue.get("colloquial_markers") or [] if marker in plain),
            "english": round(sum(1 for word in words if word in _ENGLISH) / len(words), 3) if words else 0.0}


def _share(profile, script):
    total = sum(profile["units"].values())
    return profile["units"].get(script, 0.0) / total if total else 0.0


def languages(text):
    """Which editing packs a text needs, by what it is written in: "zh" for a real share of Chinese, "en" for a real
    share of English phrases (function words, not a lone product name). Either, both or neither; main language first."""
    profile = language_profile(text)
    found = []
    if profile["han"] >= 4 and _share(profile, "han") >= 0.15:
        found.append(("zh", profile["units"].get("han", 0.0)))
    if profile["words"] >= 3 and _share(profile, "latin") >= 0.15 and profile["english"] >= 0.06:
        found.append(("en", profile["units"].get("latin", 0.0)))
    return tuple(name for name, _ in sorted(found, key=lambda item: -item[1]))


def language_shift(source, candidate):
    """How the language of a candidate differs from its source, as one sentence, or None: another main script, script
    conversion (Traditional and Simplified), written Cantonese against standard written Chinese, a second language
    removed from or added to the mix, or English replaced by another Latin-script language. Counts decide; a text too
    short to judge is left alone."""
    before, after = language_profile(source), language_profile(candidate)
    if sum(before["units"].values()) < 1.5 or not sum(after["units"].values()):
        return None
    main = max(before["units"], key=before["units"].get)
    if _share(before, main) >= 0.6 and _share(after, main) <= 0.4:
        now = max(after["units"], key=after["units"].get)
        return f"the original is mostly {SCRIPT_LABELS.get(main, main)} text and the candidate is mostly {SCRIPT_LABELS.get(now, now)}"
    if before["hant"] >= 2 and not before["hans"] and after["hans"] >= 2:
        return "Traditional Chinese characters were converted to Simplified"
    if before["hans"] >= 2 and not before["hant"] and after["hant"] >= 2:
        return "Simplified Chinese characters were converted to Traditional"
    if before["cantonese"] >= 2 and not after["cantonese"] and after["han"] >= 4:
        return "written Cantonese became standard written Chinese"
    if not before["cantonese"] and before["han"] >= 12 and after["cantonese"] >= 2:
        return "standard written Chinese became written Cantonese"
    for script, amount in before["units"].items():
        if script == main or amount < 1.5 or _share(before, script) < 0.12:
            continue
        if after["units"].get(script, 0.0) < 0.4 * amount:
            return f"{SCRIPT_LABELS.get(script, script)} wording that was mixed into the original was removed or translated"
    for script, amount in after["units"].items():
        if script != main and amount >= 2 and _share(after, script) >= 0.2 and _share(before, script) < 0.04:
            return f"{SCRIPT_LABELS.get(script, script)} wording was mixed in that the original does not have"
    if main == "latin" and before["words"] >= 12 and after["words"] >= 6:
        if before["english"] >= 0.15 and after["english"] <= 0.03:
            return "the original is in English and the candidate is not"
        if before["english"] <= 0.03 and after["english"] >= 0.15:
            return "the candidate is in English and the original is not"
    return None


def segments(text):
    """The text as runs of one script, in order: [("zh" | "en", run)]. Spaces, digits and punctuation stay with the
    run before them, so a phrase keeps its shape for the phrase patterns."""
    runs, last = [], 0
    for match in _RUN.finditer(text or ""):
        kind = match.lastgroup
        between = text[last:match.start()]
        if runs and runs[-1][0] == kind:
            runs[-1][1] += between + match.group(0)
        else:
            if runs:
                runs[-1][1] += between
            runs.append([kind, ("" if runs else between) + match.group(0)])
        last = match.end()
    if runs:
        runs[-1][1] += (text or "")[last:]
    return [(kind, run) for kind, run in runs]


def detect_mixed(text, locale="en", brand_terms=()):
    """`detect` for text that mixes Chinese and English: each language's runs are scanned with that language's own
    patterns (Cantonese ones too where the Chinese is written Cantonese), and the findings say which language they are
    about. Text in one language is scanned as `detect` scans it."""
    parts = {}
    for kind, run in segments(text):
        parts.setdefault(kind, []).append(run)
    if len(parts) < 2:
        only = next(iter(parts), _language(locale))
        return {**detect(text, _part_locale(only, locale, text), brand_terms), "languages": [only]}
    results = {kind: detect((" " if kind == "en" else "").join(runs), _part_locale(kind, locale, "".join(runs)), brand_terms) for kind, runs in parts.items()}
    order = sorted(results, key=lambda kind: 0 if kind == _language(locale) else 1)
    return {"hits": [{**hit, "language": kind} for kind in order for hit in results[kind]["hits"]],
            "vocabulary": [word for kind in order for word in results[kind]["vocabulary"]],
            "density": max(results[kind]["density"] for kind in order), "families": sorted({family for kind in order for family in results[kind]["families"]}),
            "dashes": sum(results[kind]["dashes"] for kind in order),
            "findings": [{**finding, "language": kind} for kind in order for finding in results[kind]["findings"]],
            "register": next((results[kind]["register"] for kind in order if results[kind]["register"]), None), "languages": order}


def _part_locale(kind, locale, text):
    """The locale one language's runs are scanned as: the text's own locale when it is that language, else what the runs
    themselves show (written Cantonese, Simplified or Traditional Chinese; plain English)."""
    if _language(locale) == kind:
        return locale
    if kind == "en":
        return "en"
    profile = language_profile(text)
    return "yue-Hant-HK" if profile["cantonese"] >= 2 else "zh-Hans" if profile["hans"] > profile["hant"] else "zh-Hant"


def lint(text, platform=None, locale=None):
    from .. import locale_lint, text_measure
    findings = []
    reminders = locale_lint.reminders(text, locale or "en", platform)
    for reminder in reminders or []:
        findings.append({"code": "locale", "detail": reminder if isinstance(reminder, str) else json.dumps(reminder, ensure_ascii=False)[:200]})
    if platform:
        try:
            over = text_measure.over_by(platform, text)
        except Exception:  # noqa: BLE001 - an unknown platform is simply not measured
            over = None
        if over:
            findings.append({"code": "too_long", "detail": f"{over} characters over the {platform} limit"})
    return findings


def evaluate(candidate, *, source=None, locale="en", platform=None, brand_terms=(), voice_state=None):
    """The whole hidden stage for one candidate. Returns findings per stage, the evaluator versions for provenance
    and `blocking`: meaning violations (a changed fact) block `ready_for_review`; style clues never do."""
    stages = {}
    if voice_state is not None:
        try:
            from ..site_agent import voice_check
            result = voice_check.analyze(voice_state, candidate, platform)
            differs = [f for f in (result.get("findings") or []) if f.get("verdict") == "differs"]
            stages["voiceFit"] = {"checked": len(result.get("findings") or []), "differs": [{"trait": f.get("trait"), "evidence": f.get("evidence")} for f in differs[:5]]}
        except Exception as error:  # noqa: BLE001 - voice fit is advisory; its absence is reported
            stages["voiceFit"] = {"unavailable": type(error).__name__}
    stages["humanizer"] = detect(candidate, locale, brand_terms)
    violations = meaning_diff(source, candidate, brand_terms) if source else []
    stages["meaning"] = {"violations": violations, "compared": bool(source)}
    stages["lint"] = lint(candidate, platform, locale)
    return {"evaluator": "rafii.humanizer", "version": VERSION, "patternsVersion": patterns().get("version"), "stages": stages,
            "blocking": [v["code"] for v in violations], "styleFindings": stages["humanizer"]["findings"],
            "ok": not violations, "rewritten": False}
