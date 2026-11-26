"""Analysis quality: the stops a person chooses between when Rafii reads their writing with AI.

A person chooses Economy, Balanced or Best, never a model: the main screen shows quality and its credit quote only.
Each stop holds a ranked list of models from several makers on Rafii's managed route (the Vercel AI Gateway: one key,
one budget, one bill). Rafii runs the first model in the list this deployment offers; the list's order is the
best-value order found by the live check (scripts/brand_intel_live_check.py: 30 synthetic posts with nine planted
style traits, JSON answers, cost). A model joins a stop only after that check.

An operator maps stops to models per deployment with POSTRIFF_ANALYSIS_QUALITY_MODELS, a JSON object whose values are
a model id or a ranked list of ids: {"economy": ["<id>", "<id>"], "balanced": "<id>", "best": [...]}. A stop it leaves
out keeps its defaults. A model is offered only when this deployment offers it (POSTRIFF_MODEL_IDS) and can price it.

"Advanced · choose AI provider" lets a person who must use one provider name a model from the chosen stop's list. Such
a choice is honoured exactly or refused; it is never replaced by another model. Without a choice nothing is replaced
either: the stop's recommended model is the one quoted, approved and recorded on the receipt.
"""
from __future__ import annotations

import json
import logging
import os

from postriff_alpha.domain import AlphaError

STOPS = ("economy", "balanced", "best")
DEFAULT_STOP = "balanced"
ENV = "POSTRIFF_ANALYSIS_QUALITY_MODELS"
# Ranked best value first, from the live checks of 2026-11-25 (see the module docstring). A model is listed only when it
# completed the analysis and named at least 7 of the 9 planted traits; cost is per 30 posts (four calls).
#   economy:  claude-haiku-5.5 9/9 US$0.0055 · qwen3.8-flash 7/9 US$0.0053
#   balanced: gemini-3.8-flash 9/9 US$0.0155 · claude-sonnet-5.5 7–8/9 about US$0.06 · qwen3.8-max 8/9 US$0.059
#   best:     claude-opus-5.5 9/9 US$0.15 (it also named two true habits nobody planted) · gemini-4-neon 9/9 US$0.18 ·
#             qwen3.8-max-prime 8/9 US$0.11
# Not listed: gpt-6-sol and gpt-6-luna 6/9, muse-spark-1.2 6/9, gemini-3.5-flash-lite 5/9, mistral-small 3/9,
# llama-4-scout 3/9; mistral-medium-3.5 failed the output check; gpt-6.2-astra was not run (cost). Open-weights models
# served only by third-party hosts (DeepSeek, Llama) need POSTRIFF_MODEL_PROVIDERS to name hosts first: an owner's decision.
DEFAULT_MODELS = {
    "economy": ["anthropic/claude-haiku-5.5", "alibaba/qwen3.8-flash"],
    "balanced": ["google/gemini-3.8-flash", "anthropic/claude-sonnet-5.5", "alibaba/qwen3.8-max"],
    "best": ["anthropic/claude-opus-5.5", "google/gemini-4-neon", "alibaba/qwen3.8-max-prime"],
}
_LOG = logging.getLogger(__name__)


def maker(model):
    """The maker part of a gateway model id ("anthropic/claude-opus-5.5" → "anthropic")."""
    return model.split("/", 1)[0] if isinstance(model, str) and "/" in model else ""


def configured(values=None):
    """{stop: [model id, …]} ranked: the defaults, with any stop POSTRIFF_ANALYSIS_QUALITY_MODELS names replacing its
    list. A value may be one id or a list of ids; anything unreadable keeps the default for that stop."""
    models = {stop: list(ids) for stop, ids in DEFAULT_MODELS.items()}
    raw = (os.environ if values is None else values).get(ENV)
    if not raw:
        return models
    try:
        given = json.loads(raw)
    except ValueError:
        _LOG.warning(json.dumps({"event": "analysis_quality.config_unreadable", "env": ENV}))
        return models
    if not isinstance(given, dict):
        return models
    for stop in STOPS:
        value = given.get(stop)
        ids = [value] if isinstance(value, str) else value if isinstance(value, list) else None
        cleaned = list(dict.fromkeys(item.strip() for item in ids or [] if isinstance(item, str) and item.strip()))
        if cleaned:
            models[stop] = cleaned
    return models


def _offered(runtime, model):
    """True when this runtime may run the model: listed in its selectable set and priced."""
    listed = getattr(runtime, "models", None) or [getattr(runtime, "model", None)]
    if model not in listed:
        return False
    try:
        runtime._price(model)
    except Exception:  # noqa: BLE001 - an unpriced or unknown model is simply not offered
        return False
    return True


def stops(runtime, values=None):
    """[{id, model, available, choices}] in slider order. `model` is the stop's recommended model (the first offered,
    else the first listed); `choices` lists every model of the stop with its maker and whether it is offered, for
    "Advanced · choose AI provider". With no managed runtime nothing is available."""
    rows = []
    for stop, ids in configured(values).items():
        choices = [{"model": model, "maker": maker(model), "available": runtime is not None and _offered(runtime, model)} for model in ids]
        offered = [choice["model"] for choice in choices if choice["available"]]
        rows.append({"id": stop, "model": offered[0] if offered else ids[0], "available": bool(offered), "choices": choices})
    return rows


def default_stop(runtime, values=None):
    """The stop a screen starts on: Balanced when offered, else the cheaper offered stop, else Best, else None."""
    available = {item["id"] for item in stops(runtime, values) if item["available"]}
    return next((stop for stop in (DEFAULT_STOP, "economy", "best") if stop in available), None)


def check(stop):
    """A stop named in a request: one of STOPS, or None for the default. Anything else is refused (400)."""
    if stop is None or stop in STOPS:
        return stop
    raise AlphaError("Choose Economy, Balanced or Best.", 400, code="analysis_quality_invalid")


def check_model(model):
    """A model named under Advanced: a gateway id, or None for the stop's recommended model."""
    if model is None or (isinstance(model, str) and 0 < len(model) <= 200 and "/" in model):
        return model
    raise AlphaError("Choose an AI provider from the list.", 400, code="analysis_model_invalid")


def model_for(runtime, stop, values=None, model=None):
    """(stop actually used, model) for a request. No stop: the default stop, or, when no stop is offered on this
    deployment, the runtime's default model with stop None (as before stops existed). A named model must be one of the
    stop's models and offered; otherwise the request is refused (400 or 409), never served by another model."""
    stop, model = check(stop), check_model(model)
    listed = stops(runtime, values)
    if stop is None:
        stop = default_stop(runtime, values)
        if stop is None:
            if model is not None:
                raise AlphaError("This AI provider is not offered here. Choose another.", 409, code="analysis_model_unavailable")
            return None, runtime.model
    item = next(row for row in listed if row["id"] == stop)
    if model is not None:
        choice = next((row for row in item["choices"] if row["model"] == model), None)
        if choice is None:
            raise AlphaError("This AI provider is not one of this quality's choices.", 400, code="analysis_model_invalid")
        if not choice["available"]:
            raise AlphaError("This AI provider is not offered here. Choose another.", 409, code="analysis_model_unavailable")
        return stop, model
    if not item["available"]:
        raise AlphaError("This analysis quality is not offered here. Choose another.", 409, code="analysis_quality_unavailable")
    return stop, item["model"]
