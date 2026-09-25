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
