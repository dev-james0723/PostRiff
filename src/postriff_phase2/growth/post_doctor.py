"""Post Doctor (growth Phase 0): level a draft on nine dimensions from one Jev judgment.

Deterministic code does all arithmetic: dimension scores are weighted means of answered boolean probabilities,
levels come from calibration thresholds, similarity and length are computed here, never asked of a model.
Levels are weak / medium / strong / very strong plus a confidence; they are never a probability of going viral.
The service never rewrites text (rewrites are Phase 1 and may only use creator-supplied facts).

Assumptions (reversible, documented in CONTRACTS):
- A question that is abstained, invalid or unanswered contributes no weight; it is never read as "no".
- Fix hints come from answered items whose adjusted probability is below 0.5, ordered by lost weight w·(1−p′).
- The confidence abstention rule counts abstained, invalid and unanswered questions together.
- `fit_winners` stays None in Phase 0 even above the post threshold; the winners comparison ships with Creator
  Genome (Phase 1) and needs ≥ 10 measured posts.
- Any `zh*` language uses the `zh-HK` copy when present; anything else falls back to `en`.
- Calibration comes only from a golden-set profile: accepted per dimension and per language group (lang.py),
  applied only to primary judgments by the profiled model. "calibrated" confidence needs all nine dimensions.
"""
from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass, field, replace

from .. import text_measure
from . import advice_context, calibration, questions
from .judgments import subject_hash
from .lang import lang_group

FLAG = "POSTRIFF_POST_DOCTOR"
TASK = "postdoctor.judge"
DEFAULT_MODEL = "typesafe-ai/jev"
RISK_THRESHOLD = 0.65
MAX_FIXES = 2
CONFIDENCE = ("low", "medium", "high")
PROFILE_VERSION = 2   # 2: accepted entries carry an isotonic calibrator; `model` is the served model
_SPACE = re.compile(r"\s+")


def enabled(env=None):
    """Post Doctor runs only when POSTRIFF_POST_DOCTOR is exactly "1"; default off."""
    return (os.environ if env is None else env).get(FLAG) == "1"


class PostDoctorDisabled(Exception):
    code = "post_doctor_disabled"


@dataclass(frozen=True)
class DimensionResult:
    id: str
    level: int | None          # 0..3; None when too little of the dimension's weight was answered
    score: float | None
    fixes: tuple               # localized hints for the weakest answered questions (max 2)
    answered_weight: float     # fraction of the dimension's total weight that was answered, 0..1
    calibrated: bool = False   # level used thresholds accepted for this language on the golden set
    missing_context: tuple = ()
    p_strong: float | None = None   # calibrated P(a person rates this dimension strong or better); calibrated dims only.
                                    # For monitoring and ranking fixes; never shown as a score or read as virality.


@dataclass(frozen=True)
class PostDoctorResult:
    question_set: str
    dimensions: tuple
    risks: tuple               # risk question names with P(true) >= 0.65
    computed: dict             # similarity_recent, fit_winners, length_fit
    confidence: str            # "low" | "medium" | "high"
    confidence_reasons: tuple
    judgment: object
    context: dict = field(default_factory=dict)


def _lang_key(mapping, lang):
    if not isinstance(mapping, dict):
        return None
    if lang in mapping:
        return mapping[lang]
    if isinstance(lang, str) and lang.lower().startswith("zh") and "zh-HK" in mapping:
        return mapping["zh-HK"]
    return mapping.get("en")


def level_names(qs, lang="en"):
    return tuple(_lang_key(qs.levels.get("names"), lang) or ())


def levels_from_judgment(qs, judgment, *, thresholds=None, lang="en"):
    """`thresholds`: None (question-set defaults), one ascending list for every dimension, or {dimension: list}
    where missing dimensions use the defaults. A dimension given its own list is reported `calibrated`."""
    default = list(qs.levels["thresholds"])
    per_dim = thresholds if isinstance(thresholds, dict) else {}
    shared = list(thresholds) if isinstance(thresholds, (list, tuple)) else None
    min_weight = float(qs.levels.get("min_answered_weight", 0.5))
    results = []
    for dim_id, dim in qs.dimensions.items():
        total = answered = weighted = 0.0
        lost = []
        for item in dim["items"]:
            w = float(item.get("weight", 1.0))
            total += w
            p = judgment.probability(item["q"])
            if p is None:
                continue
            p = 1 - p if item.get("invert") else p
            answered += w
            weighted += w * p
            if p < 0.5:
                lost.append((w * (1 - p), item))
        fraction = answered / total if total else 0.0
        score = weighted / answered if answered else None
        own = per_dim.get(dim_id)
        cuts = list(own) if own is not None else (shared or default)
        level = calibration.to_level(score, cuts) if score is not None and fraction >= min_weight else None
        lost.sort(key=lambda pair: -pair[0])
        fixes = tuple(h for h in (_lang_key(item.get("fix"), lang) for _, item in lost[:MAX_FIXES]) if h)
        results.append(DimensionResult(dim_id, level, None if level is None else round(score, 4), fixes,
                                       round(fraction, 4), own is not None and level is not None))
    return tuple(results)


def risks_from_judgment(qs, judgment, threshold=RISK_THRESHOLD):
    return tuple(r for r in qs.risks if (judgment.probability(r) or 0.0) >= threshold)


def _normalise(text):
    text = unicodedata.normalize("NFKC", text if isinstance(text, str) else "").casefold()
    return _SPACE.sub(" ", text).strip()


def _grams(text, n=3):
    text = _normalise(text)
    if not text:
        return frozenset()
    if len(text) < n:
        return frozenset([text])
    return frozenset(text[i:i + n] for i in range(len(text) - n + 1))


def similarity_recent(text, recent_texts):
    """Highest character-trigram Jaccard similarity to any recent text (code points, so CJK-safe); None if n/a."""
    draft = _grams(text)
    if not draft:
        return None
    best = None
    for other in recent_texts or ():
        grams = _grams(other)
        if not grams:
            continue
        value = len(draft & grams) / len(draft | grams)
        best = value if best is None else max(best, value)
    return None if best is None else round(best, 4)


def length_fit(platform, text):
    counted = text_measure.measure(platform, text)
    limit = counted["limit"]
    status = "unknown" if not limit else ("over" if counted["used"] > limit else "ok")
    return {**counted, "status": status, "over_by": max(0, counted["used"] - limit) if limit else 0}


def confidence(qs, judgment, *, calibrated, posts_with_metrics):
    """(level, reasons). low: uncalibrated for the language (or fallback/unanswered); medium: calibrated but
    fewer than 10 measured posts; high otherwise. One step lower when more than a third of asked questions
    did not yield a usable answer."""
    reasons = []
    status = getattr(judgment, "status", "ok")
    if status != "ok":
        reasons.append(f"judge_{status}")
    if not calibrated:
        reasons.append("uncalibrated_language")
    elif not judgment.calibrated and status == "ok":
        reasons.append("fallback_model")
    minimum = int(qs.raw.get("computed", {}).get("fit_winners", {}).get("min_posts_with_metrics", 10))
    if status != "ok" or not calibrated or not judgment.calibrated:
        step = 0
    elif posts_with_metrics < minimum:
        step = 1
        reasons.append("few_measured_posts")
    else:
        step = 2
    asked = len(qs.names)
    usable = sum(1 for a in judgment.answers.values() if not a.abstained)
    if asked and (asked - usable) * 3 > asked:
        reasons.append("many_abstained")
        step = max(0, step - 1)
    return CONFIDENCE[step], tuple(reasons)


def _numbers(values, length=None):
    return (isinstance(values, list) and bool(values) and (length is None or len(values) == length)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values))


def validate_profile(profile, qs):
    """Return `profile` if it is a calibration profile for this exact question set whose accepted entries carry
    ascending finite thresholds (one per level boundary) and a non-decreasing finite isotonic calibrator on [0, 1];
    otherwise raise ValueError (never another exception type)."""
    if not isinstance(profile, dict) or profile.get("version") != PROFILE_VERSION:
        raise ValueError("unsupported calibration profile")
    if profile.get("question_set") != qs.key or profile.get("digest") != qs.digest:
        raise ValueError("calibration profile was fitted on a different question set; recalibrate")
    languages = profile.get("languages")
    if not isinstance(profile.get("model"), str) or not isinstance(languages, dict):
        raise ValueError("calibration profile has no model or languages")
    boundaries = len(qs.levels["thresholds"])
    for dims in languages.values():
        if not isinstance(dims, dict):
            raise ValueError("calibration profile has a malformed language entry")
        for entry in dims.values():
            if not isinstance(entry, dict):
                raise ValueError("calibration profile has a malformed dimension entry")
            if entry.get("accepted") is not True:
                continue
            ts, iso = entry.get("thresholds"), entry.get("isotonic")
            if not _numbers(ts, boundaries) or ts != sorted(ts):
                raise ValueError("calibration profile has malformed thresholds")
            xs = iso.get("x") if isinstance(iso, dict) else None
            ys = iso.get("y") if isinstance(iso, dict) else None
            if (not _numbers(xs) or not _numbers(ys, len(xs)) or xs != sorted(xs) or ys != sorted(ys)
                    or not all(0 <= y <= 1 for y in ys)):
                raise ValueError("calibration profile has a malformed calibrator")
    return profile


def _creator_state(creator):
    """Only plain text/number facts the creator supplied; nested or other values are dropped."""
    out = {}
    for key, value in (creator or {}).items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
            out[key] = list(value)
    return out


class PostDoctorService:
    def __init__(self, judgments, *, question_set=None, model=DEFAULT_MODEL, profile=None, env=None):
        """`judgments`: JudgmentService wired to router.evaluator("postdoctor.judge").
        `profile`: a calibration profile from golden.calibration_profile / golden.load_profile. Without one every
        level uses the question-set defaults and confidence stays low."""
        self.judgments = judgments
        self.qs = question_set or questions.get("postdoctor", 2 if (os.environ if env is None else env).get("POSTRIFF_POST_DOCTOR_V2") == "1" else 1)
        self.model = model
        self.profile = None if profile is None else validate_profile(profile, self.qs)
        self.env = env

    def check(self, *, workspace_id, draft_text, platform, lang, creator=None, recent_texts=(),
              posts_with_metrics=0, goal="general", format_id="text"):
        if not enabled(self.env):
            raise PostDoctorDisabled("Post Doctor is not enabled")
        if not isinstance(draft_text, str) or not draft_text.strip():
            raise ValueError("draft_text is required")
        creator = _creator_state(creator)
        state = {"draft": draft_text, "platform": platform, "lang": lang, "creator": creator}
        context = advice_context.build(creator, goal=goal, format_id=format_id) if self.qs.version >= 2 else {}
        if context:
            state.update(creator=context["creator"], goal=context["goal"], format=context["format"])
        subject = subject_hash("postdoctor", platform, lang, draft_text, questions.canonical(creator), questions.canonical(context))
        judgment = self.judgments.judge(self.qs, state, subject=subject, scope=f"personal:{workspace_id}",
                                        model=self.model, workspace_id=workspace_id)
        accepted = self.accepted(lang, judgment)
        dims = levels_from_judgment(self.qs, judgment, thresholds={d: e["thresholds"] for d, e in accepted.items()}, lang=lang)
        absent = advice_context.missing(self.qs, state) if context else {}
        dims = tuple(replace(d, level=None, score=None, fixes=(), answered_weight=0, calibrated=False, missing_context=absent[d.id])
                     if d.id in absent else d for d in dims)
        dims = tuple(replace(d, p_strong=round(calibration.isotonic_apply(accepted[d.id]["isotonic"], d.score), 4))
                     if d.calibrated else d for d in dims)
        calibrated = len(accepted) == len(self.qs.dimensions)
        computed = {
            "similarity_recent": similarity_recent(draft_text, recent_texts),
            "fit_winners": None,
            "length_fit": length_fit(platform, draft_text),
        }
        level, reasons = confidence(self.qs, judgment, calibrated=calibrated, posts_with_metrics=posts_with_metrics)
        if absent:
            level, reasons = "low", reasons + ("missing_context",)
        if accepted and not calibrated:
            reasons = reasons + ("partly_calibrated",)
        return PostDoctorResult(self.qs.key, dims, risks_from_judgment(self.qs, judgment), computed, level,
                                reasons, judgment, context)

    def accepted(self, lang, judgment):
        """{dimension: profile entry} accepted for this language group. Fits were made on primary answers from the
        profiled model, so a fallback model's judgment gets none; nor does any language without its own accepted fit."""
        if self.profile is None or not judgment.calibrated or getattr(judgment, "status", "ok") != "ok":
            return {}
        if judgment.model != self.profile.get("model"):
            return {}
        dims = (self.profile.get("languages") or {}).get(lang_group(lang)) or {}
        return {d: e for d, e in dims.items() if isinstance(e, dict) and e.get("accepted") is True and d in self.qs.dimensions}
