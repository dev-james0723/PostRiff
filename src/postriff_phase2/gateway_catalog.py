"""What the Vercel AI Gateway says about each model: whether it thinks before answering, which reasoning controls it
takes, and which request parameters it accepts. The writer decides output headroom, the reasoning level it sends and
the optional parameters from this, never from the model's name alone.

Source: the gateway's public catalogue (https://ai-gateway.vercel.sh/v1/models). A snapshot ships with the code
(gateway_catalog.json, refreshed by scripts/refresh_gateway_catalog.py). On Vercel the running app also refreshes it in
memory at most once a day, in the background: a request never waits for the catalogue, and a failed refresh keeps the
snapshot. No credential is needed or sent.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

CATALOG_URL = "https://ai-gateway.vercel.sh/v1/models"
REFRESH_SECONDS = 24 * 3600
FETCH_TIMEOUT_SECONDS = 8
# Used only for a model the catalogue does not list (a newer id than the snapshot).
FALLBACK_THINKING_PREFIXES = ("openai/gpt-6", "openai/gpt-5", "openai/o", "google/gemini-2.5", "google/gemini-3", "deepseek/", "alibaba/qwen")
# Every effort id the gateway's unified reasoning object can carry, lowest first.
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

_SNAPSHOT = Path(__file__).with_name("gateway_catalog.json")
_lock = threading.Lock()
_state = {"models": None, "loadedAt": 0.0, "refreshing": False, "snapshot": None, "refreshedAt": None}


def _load_snapshot():
    """(models, the date the shipped snapshot was fetched)."""
    try:
        data = json.loads(_SNAPSHOT.read_text())
    except (OSError, ValueError):
        return {}, None
    fetched = data.get("fetched") if isinstance(data.get("fetched"), str) else None
    return data.get("models") or {}, fetched


def _models():
    if _state["models"] is None:
        with _lock:
            if _state["models"] is None:
                (_state["models"], _state["snapshot"]), _state["loadedAt"] = _load_snapshot(), time.time()
    _maybe_refresh()
    return _state["models"]


def version():
    """Which catalogue a run was decided with: the shipped snapshot's fetch date, and when a background refresh last
    replaced it (None while the snapshot is in use). Recorded on each run's reasoning block."""
    _models()
    return {"snapshot": _state["snapshot"], "refreshedAt": _state["refreshedAt"]}


def _refresh_allowed():
    """Only a deployed app fetches (never tests, the dev harness or CI): Vercel sets VERCEL=1."""
    return os.environ.get("VERCEL") == "1" and os.environ.get("POSTRIFF_GATEWAY_CATALOG_REFRESH", "1") != "0"


def _maybe_refresh():
    if not _refresh_allowed() or _state["refreshing"] or time.time() - _state["loadedAt"] < REFRESH_SECONDS:
        return
    with _lock:
        if _state["refreshing"]:
            return
        _state["refreshing"] = True
    threading.Thread(target=_refresh, name="gateway-catalog-refresh", daemon=True).start()


def parse(data):
    """The catalogue response → {id: {reasoning, params, maxTokens}} for language models."""
    models = {}
    for item in (data or {}).get("data") or []:
        if not isinstance(item, dict) or item.get("type") != "language" or not isinstance(item.get("id"), str):
            continue
        entry = {}
        if isinstance(item.get("reasoning_options"), list) and item["reasoning_options"]:
            entry["reasoning"] = [o for o in item["reasoning_options"] if isinstance(o, dict)]
        if isinstance(item.get("supported_parameters"), list):
            entry["params"] = sorted(str(p) for p in item["supported_parameters"])
        if isinstance(item.get("max_tokens"), int):
            entry["maxTokens"] = item["max_tokens"]
        models[item["id"]] = entry
    return models


def _refresh(transport=None):
    try:
        if transport is None:
            from urllib.request import Request, urlopen
            with urlopen(Request(CATALOG_URL, headers={"Accept": "application/json"}), timeout=FETCH_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read(8 * 1024 * 1024))
        else:
            data = transport(CATALOG_URL)
        models = parse(data)
        if models:   # an empty or broken answer never replaces what we have
            _state["models"] = models
            _state["refreshedAt"] = time.time()
    except Exception:  # noqa: BLE001 - the snapshot stays; the next day tries again
        pass
    finally:
        _state["loadedAt"] = time.time()
        _state["refreshing"] = False


def entry(model):
    return _models().get(model) if isinstance(model, str) else None


def thinking(model, level=None):
    """True when a drafting call to this model will spend reasoning tokens inside max_tokens, with the reasoning we send
    (drafting_reasoning): a level above "none", or a model that reasons without an effort scale (budget-only). A
    toggle-only model (thinking off unless asked) needs no headroom. `level` is an explicit effort the person chose:
    "none" turns thinking off; any other listed level thinks. Without one (Auto, or a pass mode), the baseline decides."""
    if level == "none":
        return False
    if level in EFFORTS and level in levels(model):
        return True
    known = entry(model)
    if known is None:
        return isinstance(model, str) and model.startswith(FALLBACK_THINKING_PREFIXES)
    if not known.get("reasoning"):
        return False
    sent = drafting_reasoning(model)
    if sent is not None:
        return sent.get("effort") != "none"
    return not _has_toggle(model)


def supports(model, parameter):
    """Whether the gateway lists this request parameter for the model; an unlisted model keeps today's behaviour."""
    known = entry(model)
    if known is None or "params" not in known:
        return True
    return parameter in known["params"]


def levels(model):
    """The effort levels this model lists in the catalogue (in the catalogue's order), or [] when it has no effort
    scale or does not take the `reasoning` parameter. Only these are ever sent as an explicit level."""
    return _efforts(model) if supports(model, "reasoning") else []


def max_tokens(model):
    """The catalogue's output limit for this model (every per-level cap is clamped to it); None when unlisted."""
    value = (entry(model) or {}).get("maxTokens")
    return value if type(value) is int and value > 0 else None


def _efforts(model):
    for option in (entry(model) or {}).get("reasoning") or []:
        if option.get("type") == "effort" and isinstance(option.get("values"), list):
            return [str(v) for v in option["values"]]
    return []


def _has_toggle(model):
    return any(option.get("type") == "toggle" for option in (entry(model) or {}).get("reasoning") or [])


def _lowest(values):
    for wanted in ("low", "minimal"):
        if wanted in values:
            return wanted
    return next((v for v in values if v != "none"), values[0])


def drafting_reasoning(model):
    """The gateway's unified `reasoning` object for writing (the "Auto" baseline chosen for quality): "low" (else
    "minimal") on the model's effort scale; a model that must reason and lists neither gets its lowest level above
    "none". Never "none": that is only a person's own choice. Nothing is sent to a model with no effort scale (a
    toggle-only model stays at its default, off; a budget-only model reasons on its own and only gets headroom), nor
    to a model whose scale has only heavy levels but can keep thinking off. A level a model does not list is never sent."""
    values = _efforts(model)
    if not values or not supports(model, "reasoning"):
        return None
    if "low" not in values and "minimal" not in values and _has_toggle(model):
        # Only heavy levels on the scale (deepseek-v4-pro: none/high/max) and thinking can stay off: send nothing, as
        # for a toggle-only model. A caption does not need its slow "high"; the person can choose it in the picker.
        return None
    return {"effort": _lowest(values)}


def structured_reasoning(model):
    """The `reasoning` object for short structured side calls (request reading, extraction): thinking off ("none")
    where the model offers it, as these calls always ran; otherwise the lowest level; nothing without a scale."""
    values = _efforts(model)
    if not values or not supports(model, "reasoning"):
        return None
    return {"effort": "none"} if "none" in values else {"effort": _lowest(values)}
