"""Versioned question sets for Jev evaluations (growth Phase 0).

A question set is a JSON file in `question_sets/` named `<id>.v<version>.json`. It defines typed questions
for the AI Gateway Evaluation API (`boolean`, `choice`, `score`) and, for rubric sets such as Post Doctor,
how questions combine into dimensions and levels. Definitions are validated strictly at load time so a bad
file fails fast in tests instead of producing silent nonsense in production. The digest of the canonical
JSON is part of every cache key, so editing a set without bumping its version still invalidates caches.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

SETS_DIR = Path(__file__).with_name("question_sets")
TYPES = ("boolean", "choice", "score")
UNSURE = "unsure"
_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OPTION = re.compile(r"^[a-z0-9][a-z0-9_:.-]{0,63}$")
_FILE = re.compile(r"^(?P<id>[a-z][a-z0-9_-]*)\.v(?P<version>[1-9][0-9]*)\.json$")
MAX_INSTRUCTIONS = 1000
MAX_CHOICE_OPTIONS = 255
SCORE_LEVELS = (2, 10)


@dataclass(frozen=True)
class Question:
    name: str
    type: str
    instructions: str
    criteria: object = None

    def payload(self):
        body = {"type": self.type, "instructions": self.instructions}
        if self.criteria is not None:
            body["criteria"] = self.criteria
        return body

    def options(self):
        """Answer keys this question can return: option names, score rung indices as strings, or ()."""
        if self.type == "choice":
            return tuple(self.criteria)
        if self.type == "score":
            return tuple(str(i) for i in range(len(self.criteria)))
        return ()


@dataclass(frozen=True)
class QuestionSet:
    id: str
    version: int
    digest: str
    description: str
    state_rules: str
    abstain: dict
    questions: tuple
    raw: dict = field(repr=False, compare=False)

    @property
    def key(self):
        return f"{self.id}.v{self.version}"

    @property
    def names(self):
        return tuple(q.name for q in self.questions)

    def question(self, name):
        for q in self.questions:
            if q.name == name:
                return q
        raise KeyError(name)

    def payload_questions(self, names=None):
        """The `questions` object for POST /v1/evaluate (optionally a subset, order preserved)."""
        wanted = self.names if names is None else tuple(names)
        unknown = [n for n in wanted if n not in self.names]
        if unknown:
            raise KeyError(f"unknown questions: {unknown}")
        return {n: self.question(n).payload() for n in wanted}

    @property
    def dimensions(self):
        return self.raw.get("dimensions") or {}

    @property
    def risks(self):
        return self.raw.get("risks") or {}

    @property
    def levels(self):
        return self.raw.get("levels") or {}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:16]


def estimate_tokens(obj):
    """Conservative input-token estimate for budgeting before a call: ASCII ≈ 4 chars/token,
    every non-ASCII character (CJK, emoji) counted as one token. Never used for billing."""
    text = obj if isinstance(obj, str) else canonical(obj)
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return math.ceil(ascii_chars / 4) + (len(text) - ascii_chars)


def _text(value, name, limit=MAX_INSTRUCTIONS):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a non-empty string of at most {limit} characters")
    return value


def _question(name, spec):
    if not _NAME.match(name or ""):
        raise ValueError(f"invalid question name {name!r}")
    if not isinstance(spec, dict) or set(spec) - {"type", "instructions", "criteria"}:
        raise ValueError(f"{name}: only type, instructions and criteria are allowed")
    kind = spec.get("type")
    if kind not in TYPES:
        raise ValueError(f"{name}: type must be one of {TYPES}")
    instructions = _text(spec.get("instructions"), f"{name}.instructions")
    criteria = spec.get("criteria")
    if kind == "boolean":
        if criteria is not None:
            if not isinstance(criteria, dict) or not criteria or set(criteria) - {"true", "false"}:
                raise ValueError(f"{name}: boolean criteria may only define 'true' and 'false'")
            for key, value in criteria.items():
                _text(value, f"{name}.criteria.{key}")
    elif kind == "choice":
        if not isinstance(criteria, dict) or not 1 <= len(criteria) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"{name}: choice criteria must map 1-{MAX_CHOICE_OPTIONS} options to descriptions")
        for key, value in criteria.items():
            if not _OPTION.match(key):
                raise ValueError(f"{name}: invalid option name {key!r}")
            _text(value, f"{name}.criteria.{key}")
        if UNSURE not in criteria:
            raise ValueError(f"{name}: choice questions must offer an '{UNSURE}' option")
    else:
        if not isinstance(criteria, list) or not SCORE_LEVELS[0] <= len(criteria) <= SCORE_LEVELS[1]:
            raise ValueError(f"{name}: score criteria must list {SCORE_LEVELS[0]}-{SCORE_LEVELS[1]} rungs, lowest first")
        for i, value in enumerate(criteria):
            _text(value, f"{name}.criteria[{i}]")
    return Question(name, kind, instructions, criteria)


def _abstain(spec):
    spec = spec or {}
    band = spec.get("boolean_band", [0.35, 0.65])
    if (not isinstance(band, list) or len(band) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in band)
            or not 0 <= band[0] < band[1] <= 1):
        raise ValueError("abstain.boolean_band must be [low, high] with 0 <= low < high <= 1")
    out = {"boolean_band": [float(band[0]), float(band[1])]}
    for key in ("choice_min", "score_min"):
        value = spec.get(key, 0.5)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
            raise ValueError(f"abstain.{key} must be between 0 and 1")
        out[key] = float(value)
    return out


def _check_rubric(raw, questions):
    by_name = {q.name: q for q in questions}
    dims = raw.get("dimensions")
    if dims is None:
        return
    if not isinstance(dims, dict) or not dims:
        raise ValueError("dimensions must be a non-empty object")
    for dim, spec in dims.items():
        if not _NAME.match(dim) or not isinstance(spec, dict):
            raise ValueError(f"invalid dimension {dim!r}")
        items = spec.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError(f"{dim}: items must be a non-empty list")
        for item in items:
            q = by_name.get(item.get("q")) if isinstance(item, dict) else None
            if q is None or q.type == "choice":
                raise ValueError(f"{dim}: items must reference boolean or score questions")
            weight = item.get("weight")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not weight > 0:
                raise ValueError(f"{dim}.{q.name}: weight must be positive")
            if "invert" in item and not isinstance(item["invert"], bool):
                raise ValueError(f"{dim}.{q.name}: invert must be boolean")
    for risk in raw.get("risks") or {}:
        if by_name.get(risk) is None or by_name[risk].type != "boolean":
            raise ValueError(f"risk {risk!r} must be a boolean question")
    levels = raw.get("levels") or {}
    thresholds = levels.get("thresholds")
    names = levels.get("names") or {}
    if not isinstance(thresholds, list) or not thresholds or thresholds != sorted(thresholds) or not all(0 < t < 1 for t in thresholds):
        raise ValueError("levels.thresholds must be ascending values between 0 and 1")
    for lang, labels in names.items():
        if not isinstance(labels, list) or len(labels) != len(thresholds) + 1:
            raise ValueError(f"levels.names.{lang} must have one more entry than thresholds")
    minimum = levels.get("min_answered_weight", 0.5)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not 0 < minimum <= 1:
        raise ValueError("levels.min_answered_weight must be in (0, 1]")


def parse(raw):
    """Validate a question-set definition and return a QuestionSet."""
    if not isinstance(raw, dict):
        raise ValueError("question set must be a JSON object")
    qs_id = raw.get("id")
    if not isinstance(qs_id, str) or not _ID.match(qs_id):
        raise ValueError("id must be a short lowercase identifier")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    specs = raw.get("questions")
    if not isinstance(specs, dict) or not specs:
        raise ValueError("questions must be a non-empty object")
    questions = tuple(_question(name, spec) for name, spec in specs.items())
    _check_rubric(raw, questions)
    return QuestionSet(qs_id, version, digest(raw), raw.get("description", ""), raw.get("state_rules", ""),
                       _abstain(raw.get("abstain")), questions, raw)


def load(path):
    path = Path(path)
    match = _FILE.match(path.name)
    raw = json.loads(path.read_text(encoding="utf-8"))
    qs = parse(raw)
    if not match or match["id"] != qs.id or int(match["version"]) != qs.version:
        raise ValueError(f"{path.name}: file name must be {qs.id}.v{qs.version}.json")
    return qs


_REGISTRY = None


def registry(directory=None):
    """All question sets in the directory, keyed by `<id>.v<version>`. Cached for the default directory."""
    global _REGISTRY
    if directory is None and _REGISTRY is not None:
        return _REGISTRY
    found = {}
    for path in sorted(Path(directory or SETS_DIR).glob("*.json")):
        qs = load(path)
        found[qs.key] = qs
    if directory is None:
        _REGISTRY = found
    return found


def get(qs_id, version=None, directory=None):
    """A question set by id and exact version, or the highest version when version is None."""
    sets = registry(directory)
    if version is not None:
        try:
            return sets[f"{qs_id}.v{int(version)}"]
        except KeyError:
            raise KeyError(f"question set {qs_id}.v{version} not found") from None
    candidates = [qs for qs in sets.values() if qs.id == qs_id]
    if not candidates:
        raise KeyError(f"question set {qs_id} not found")
    return max(candidates, key=lambda qs: qs.version)
