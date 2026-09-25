"""Feature flags for the coworker upgrade (architecture lock §5).

Same semantics as `agent_runtime_v2/config._flag`: off unless the value is 1/true/yes/on. Values come from the
environment the hosted app was built with (`deployment.isolated_environment`, which pins preview), set once by
`attach(values)`; before that, from `os.environ` through the same isolation. Flags reach the browser only through
the coworker status payload (`public()`), never as NEXT_PUBLIC_* build flags.
"""
from __future__ import annotations

import os

FLAGS = (
    "RAFII_SKILL_REGISTRY_V2_ENABLED",
    "RAFII_NOTIFICATIONS_V2_ENABLED",
    "RAFII_WEB_PUSH_ENABLED",
    "RAFII_ADAPTIVE_SKILLS_ENABLED",
    "RAFII_WEEKLY_OPERATOR_ENABLED",
    "RAFII_RESEARCH_BROKER_ENABLED",
    "RAFII_CREATIVE_AGENT_ENABLED",
    "RAFII_PERFORMANCE_LEARNING_ENABLED",
    "RAFII_LISTENING_ENABLED",
    "RAFII_ENGAGEMENT_COPILOT_ENABLED",
    "RAFII_GROWTH_EXPERIMENTS_ENABLED",
)
# Flags whose features reach an external service (email, push, the public web). Preview pins them off.
EGRESS_FLAGS = ("RAFII_NOTIFICATIONS_V2_ENABLED", "RAFII_WEB_PUSH_ENABLED", "RAFII_RESEARCH_BROKER_ENABLED", "RAFII_LISTENING_ENABLED")

_values = None


def _truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def attach(values):
    """Use the hosted app's (already isolated) environment from now on."""
    global _values
    _values = dict(values) if values is not None else None


def _source(values=None):
    if values is not None:
        return values
    if _values is not None:
        return _values
    from ..deployment import isolated_environment
    try:
        return isolated_environment(os.environ)
    except ValueError:
        # A misconfigured preview must not switch features on by accident.
        return {}


def enabled(name, values=None):
    if name not in FLAGS:
        raise KeyError(f"Unknown coworker flag {name}")
    return _truthy(_source(values).get(name, ""))


def snapshot(values=None):
    source = _source(values)
    return {name: _truthy(source.get(name, "")) for name in FLAGS}


def public(values=None):
    """What the browser may know: which features are on. Never a credential or a raw value."""
    return {"flags": snapshot(values)}


def require(name, values=None):
    if not enabled(name, values):
        from postriff_alpha.domain import AlphaError
        raise AlphaError("This Rafii feature isn’t turned on yet.", 404, code="feature_disabled")
