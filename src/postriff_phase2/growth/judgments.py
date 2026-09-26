"""Validated, cached Jev judgments (growth Phase 0).

JudgmentService asks one question set about one subject (a draft, an own post, a comment, a public item),
validates every answer against the question definitions, applies the abstain rules, and caches the result.
An invalid or abstained answer is never treated as "no": invalid names are reported and excluded, abstained
answers are kept but flagged. Cache scopes keep a creator's own material private: `personal:<workspace>` keys
are never shared across workspaces; only public content may use the `shared` scope.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from typing import Protocol

from .questions import QuestionSet
from .router import RouterError

# Transient router outcomes that degrade to an explicit abstention instead of failing the caller.
# auth / budget / bad_request stay errors: they are configuration or input problems, not availability.
DEGRADABLE = ("timeout", "rate_limited", "upstream", "unavailable", "malformed")

PROB_TOLERANCE = 0.02
_SCOPE = re.compile(r"^(shared|personal:[A-Za-z0-9_-]{1,64})$")


@dataclass(frozen=True)
class Answer:
    name: str
    type: str
    value: object          # boolean: probability of true; choice: option name; score: interpolated rung
    probabilities: dict | None
    top: float             # confidence of the leading answer
    abstained: bool


@dataclass(frozen=True)
class Judgment:
    question_set: str
    digest: str
    model: str
    route: str             # "primary" | "fallback"
    calibrated: bool       # False for fallback answers (LLM pseudo-probabilities)
    answers: dict
    invalid: tuple
    cost_usd: float | None
    cost_source: str
    generation_id: str | None
    latency_ms: int
    cache_key: str
    cached: bool = False
    status: str = "ok"     # "ok", or the router error code when no model answered ("timeout", "upstream", ...)
    attempts: tuple = ()   # UsageEvents of the call that produced this judgment (empty when cached)
    elapsed_ms: int | None = None   # end-to-end wait including retries and fallbacks (None when unknown)

    def probability(self, name):
        """P(true) for a boolean answer that is valid and not abstained, else None."""
        answer = self.answers.get(name)
        if answer is None or answer.type != "boolean" or answer.abstained:
            return None
        return answer.value


class Evaluation(Protocol):
    answers: dict
    route: str
    model: str
    calibrated: bool
    cost_usd: float | None
    cost_source: str
    generation_id: str | None
    latency_ms: int


class Evaluator(Protocol):
    def __call__(self, question_set: QuestionSet, state, *, workspace_id=None, subject=None) -> Evaluation: ...


class JudgmentCache(Protocol):
    def get(self, key): ...
    def put(self, key, judgment): ...


class MemoryJudgmentCache:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return self.items.get(key)

    def put(self, key, judgment):
        self.items[key] = judgment


def subject_hash(*parts):
    """Stable hash of the subject content (never stored as text in keys)."""
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def cache_key(scope, subject, question_set, model):
    if not isinstance(scope, str) or not _SCOPE.match(scope):
        raise ValueError("scope must be 'shared' or 'personal:<workspace id>'")
    if not isinstance(subject, str) or not re.fullmatch(r"[0-9a-f]{64}", subject):
        raise ValueError("subject must be a sha256 hex digest from subject_hash()")
    return f"{scope}|{question_set.key}|{question_set.digest}|{model}|{subject}"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _distribution(probabilities, options):
    if not isinstance(probabilities, dict) or set(probabilities) != set(options):
        return None
    if not all(_number(v) and 0 <= v <= 1 for v in probabilities.values()):
        return None
    if abs(sum(probabilities.values()) - 1) > PROB_TOLERANCE:
        return None
    return {k: float(v) for k, v in probabilities.items()}


def _one(question, raw, abstain):
    if not isinstance(raw, dict) or raw.get("type") != question.type:
        return None
    if question.type == "boolean":
        p = raw.get("probability")
        if not _number(p) or not 0 <= p <= 1:
            return None
        low, high = abstain["boolean_band"]
        return Answer(question.name, "boolean", float(p), None, max(p, 1 - p), low <= p <= high)
    options = question.options()
    probs = _distribution(raw.get("probabilities"), options)
    if probs is None:
        return None
    top_key = max(probs, key=probs.get)
    top = probs[top_key]
    if question.type == "choice":
        choice = raw.get("choice")
        if choice not in options or probs[choice] < top - 1e-9:
            return None
        return Answer(question.name, "choice", choice, probs, top, top < abstain["choice_min"] or choice == "unsure")
    score = raw.get("score")
    if not _number(score) or not 0 <= score <= len(options) - 1:
        return None
    return Answer(question.name, "score", float(score), probs, top, top < abstain["score_min"])


def validate_answers(question_set, raw_answers, names=None):
    """Return ({name: Answer}, invalid_names) for the asked questions."""
    asked = question_set.names if names is None else tuple(names)
    raw_answers = raw_answers if isinstance(raw_answers, dict) else {}
    valid, invalid = {}, []
    for name in asked:
        answer = _one(question_set.question(name), raw_answers.get(name), question_set.abstain)
        if answer is None:
            invalid.append(name)
        else:
            valid[name] = answer
    return valid, tuple(invalid)


class JudgmentService:
    def __init__(self, evaluate: Evaluator, cache: JudgmentCache | None = None):
        self.evaluate = evaluate
        self.cache = cache if cache is not None else MemoryJudgmentCache()

    def judge(self, question_set, state, *, subject, scope, model, workspace_id=None):
        """Judge `state` with `question_set`. `subject` is subject_hash(...) of the judged content."""
        if scope.startswith("personal:") and workspace_id is not None and scope != f"personal:{workspace_id}":
            raise ValueError("a personal judgment must use its own workspace scope")
        key = cache_key(scope, subject, question_set, model)
        hit = self.cache.get(key)
        if hit is not None:
            return replace(hit, cached=True)
        try:
            evaluation = self.evaluate(question_set, state, workspace_id=workspace_id, subject=subject)
        except RouterError as error:
            if error.code not in DEGRADABLE:
                raise
            return unanswered(question_set, key, error.code, error.attempts, getattr(error, "elapsed_ms", None))
        answers, invalid = validate_answers(question_set, evaluation.answers)
        judgment = Judgment(
            question_set=question_set.key, digest=question_set.digest, model=evaluation.model, route=evaluation.route,
            calibrated=bool(evaluation.calibrated) and evaluation.route == "primary", answers=answers, invalid=invalid,
            cost_usd=evaluation.cost_usd, cost_source=evaluation.cost_source, generation_id=evaluation.generation_id,
            latency_ms=evaluation.latency_ms, cache_key=key, attempts=tuple(getattr(evaluation, "attempts", ()) or ()),
            elapsed_ms=getattr(evaluation, "elapsed_ms", None))
        if not invalid:  # never cache a partly invalid judgment; the next request can succeed
            self.cache.put(key, judgment)
        return judgment


def unanswered(question_set, key, status, attempts=(), elapsed_ms=None):
    """A judgment in which every question abstained because no model answered; never cached."""
    known = [e.cost_usd for e in attempts if e.cost_usd is not None]
    return Judgment(
        question_set=question_set.key, digest=question_set.digest, model="none", route="none", calibrated=False,
        answers={}, invalid=(), cost_usd=sum(known) if known else None,
        cost_source="gateway" if attempts and len(known) == len(attempts) else "unknown",
        generation_id=None, latency_ms=sum(e.latency_ms for e in attempts), cache_key=key, status=status,
        attempts=tuple(attempts), elapsed_ms=elapsed_ms)
