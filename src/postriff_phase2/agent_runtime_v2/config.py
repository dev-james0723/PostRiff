"""Feature flags, model aliases and the model router for the Rafii Agent Runtime (spec ADR-006, §21, §36, §41).

Nothing here is hard-coded into business logic: every model id comes from an alias with a documented default, and the
router records why it chose a route. A route that is not configured is reported as unavailable, never replaced by
another paid provider behind the person's back (§21 "Do not silently fall back to a paid model/provider").

Providers:
- ``openai``: the OpenAI API with a server-held ``OPENAI_API_KEY`` (Agents SDK Responses model, GPT-Live, the
  Responses image tool). Required for Voice Mode.
- ``gateway``: Vercel AI Gateway's OpenAI-compatible endpoint with ``AI_GATEWAY_API_KEY`` (or the deployment's
  ``VERCEL_OIDC_TOKEN``), the route the product already uses for writing and images.

Keys are read on the server only. They never enter a prompt, an event, an artifact, a log line or a browser payload.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# --- feature flags (§41) ----------------------------------------------------------------------------------------------
FLAGS = ("RAFII_AGENT_V2_ENABLED", "RAFII_VOICE_ENABLED", "RAFII_IMAGE_AGENT_ENABLED", "RAFII_SPECIALISTS_ENABLED", "RAFII_PROACTIVE_V2_ENABLED", "RAFII_AGENT_THINKING_STATES_ENABLED",
         # Generative UI (rafii-genui/1). Off unless set; RAFII_GENUI_WORKSPACES narrows a canary to listed workspaces.
         "RAFII_GENUI_ENABLED", "RAFII_GENUI_ACTIONS_ENABLED", "RAFII_GENUI_EDITS_ENABLED", "RAFII_GENUI_FOUNDER_ENABLED",
         "RAFII_AGENT_PERMISSIONS_ENABLED", "RAFII_AGENT_PERMISSIONS_ENFORCED",
         "RAFII_TASK_ENGINE_ENABLED", "RAFII_TASK_ENGINE_AUTHORITATIVE", "RAFII_TASK_ENGINE_BACKGROUND")

# --- model aliases (ADR-006) ------------------------------------------------------------------------------------------
# Defaults are aliases for development. Pin dated snapshots in production only after the evals pass (ADR-006).
# Verified against developers.openai.com on 2026-09-24: gpt-6-sol (agentic workflows), gpt-6-luna (efficient, high
# volume), both with image input; gpt-image-2.5-sunburst (editing precision) and -flare (fast) as the Responses
# image_generation tool's model or on the Images API; gpt-live-1 only on /v1/live/sessions.
DEFAULT_MODELS = {
    "RAFII_AGENT_PRIMARY_MODEL": "gpt-6-sol",
    "RAFII_AGENT_FAST_MODEL": "gpt-6-luna",
    "RAFII_AGENT_VISION_MODEL": "gpt-6-sol",
    "RAFII_AGENT_IMAGE_MODEL_QUALITY": "gpt-image-2.5-sunburst",
    "RAFII_AGENT_IMAGE_MODEL_FAST": "gpt-image-2.5-flare",
    "RAFII_LIVE_MODEL": "gpt-live-1",
}
GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# Workload classes (§21). "deterministic" never reaches a model.
WORKLOADS = ("deterministic", "fast_language", "standard_reasoning", "deep_reasoning", "vision", "voice_front_end", "image_fast", "image_quality")
_ALIAS_FOR = {
    "fast_language": "RAFII_AGENT_FAST_MODEL",
    "standard_reasoning": "RAFII_AGENT_PRIMARY_MODEL",
    "deep_reasoning": "RAFII_AGENT_PRIMARY_MODEL",
    "vision": "RAFII_AGENT_VISION_MODEL",
    "voice_front_end": "RAFII_LIVE_MODEL",
    "image_fast": "RAFII_AGENT_IMAGE_MODEL_FAST",
    "image_quality": "RAFII_AGENT_IMAGE_MODEL_QUALITY",
}
# Conservative USD per 1M tokens (input, output) for the reservation; the provider's usage settles the ledger.
# Override with RAFII_AGENT_MODEL_PRICES='{"model": [in, out]}'. A model without a price cannot be reserved and so
# is not called (the same rule as model_runtime._price).
DEFAULT_PRICES = {
    "gpt-6-sol": (2.0, 10.0),
    "gpt-6-luna": (0.1, 0.5),
    "gpt-6-astra": (10.0, 50.0),
    "gpt-5.6-terra": (2.0, 12.0),
}
# Per generated image (USD micro), by quality route: the reservation, and the charge when the provider reports no cost
# (the OpenAI Responses image tool reports tokens, not money). Override with RAFII_AGENT_IMAGE_PRICES='{"image_fast": 0.04, "image_quality": 0.19}' (USD).
DEFAULT_IMAGE_ESTIMATE_USD_MICRO = {"image_fast": 40_000, "image_quality": 190_000}
# Voice: GPT-Live costs $0.05 per minute, billed per second (15 s are billed at session creation and credited).
DEFAULT_LIVE_USD_MICRO_PER_MINUTE = 50_000
MAX_VOICE_MINUTES = 30


def _flag(values, name) -> bool:
    return str(values.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


PERMISSIONS_MODES = ("off", "shadow", "enforce")


def permissions_mode(value) -> str:
    """RAFII_AGENT_PERMISSIONS_MODE as one of PERMISSIONS_MODES. Anything else (unset, a typo) is "off": today's behaviour,
    which every existing route and tool still authorizes on its own."""
    mode = str(value or "").strip().lower()
    return mode if mode in PERMISSIONS_MODES else "off"


@dataclass(frozen=True)
class Route:
    """One routing decision, recorded in the trace (§21)."""
    workload: str
    provider: str | None
    model: str | None
    reason: str
    available: bool
    blocker: str | None = None

    def trace(self) -> dict:
        return {"workload": self.workload, "provider": self.provider, "model": self.model, "reason": self.reason,
                "available": self.available, **({"blocker": self.blocker} if self.blocker else {})}


@dataclass
class RuntimeConfig:
    flags: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    provider: str | None = None           # "openai" | "gateway" | None (no model route configured)
    base_url: str | None = None
    prices: dict = field(default_factory=dict)
    image_estimates: dict = field(default_factory=dict)
    live_usd_micro_per_minute: int = DEFAULT_LIVE_USD_MICRO_PER_MINUTE
    openai_tracing: bool = False
    has_openai_key: bool = False
    has_gateway_key: bool = False
    genui_workspaces: frozenset = frozenset()   # empty: every workspace once RAFII_GENUI_ENABLED is on
    # Rafii agent permissions (rafii-agent-authz/1, CF-2 §8.2): off | shadow | enforce, narrowed to listed workspaces.
    # Fail-closed allowlist: empty means no workspace; "*" must be written out to mean every workspace (X10).
    permissions_mode: str = "off"
    permissions_workspaces: frozenset = frozenset()
    task_engine_workspaces: frozenset = frozenset()
    release_sha: str = ""
    # A trusted server integration must verify both fixed-corpus receipts for this release.
    # Never populated from browser input or an environment verified=true escape hatch.
    permissions_gate_reader: object = field(default=None, repr=False)

    # The key itself is never an attribute: `credential()` reads it when a request is made.
    _env: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_environment(cls, values=None) -> "RuntimeConfig":
        values = dict(os.environ if values is None else values)
        models = {name: (values.get(name) or default).strip() for name, default in DEFAULT_MODELS.items()}
        has_openai = bool(values.get("OPENAI_API_KEY"))
        has_gateway = bool(values.get("AI_GATEWAY_API_KEY") or values.get("VERCEL_OIDC_TOKEN"))
        requested = (values.get("RAFII_AGENT_PROVIDER") or "").strip().lower()
        if requested not in ("", "openai", "gateway"):
            raise ValueError("RAFII_AGENT_PROVIDER must be openai or gateway.")
        provider = requested or ("openai" if has_openai else "gateway" if has_gateway else None)
        if provider == "openai" and not has_openai:
            provider = None
        if provider == "gateway" and not has_gateway:
            provider = None
        prices = dict(DEFAULT_PRICES)
        if values.get("RAFII_AGENT_MODEL_PRICES"):
            import json
            try:
                prices.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(values["RAFII_AGENT_MODEL_PRICES"]).items()})
            except (ValueError, TypeError, IndexError, KeyError, AttributeError) as error:
                raise ValueError("RAFII_AGENT_MODEL_PRICES must be a JSON object of model → [input, output] USD per million tokens.") from error
        image_prices = dict(DEFAULT_IMAGE_ESTIMATE_USD_MICRO)
        if values.get("RAFII_AGENT_IMAGE_PRICES"):
            import json
            try:
                given = json.loads(values["RAFII_AGENT_IMAGE_PRICES"])
                if not isinstance(given, dict):
                    raise TypeError("not an object")
                image_prices.update({k: int(round(float(given[k]) * 1_000_000)) for k in image_prices if k in given})
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise ValueError("RAFII_AGENT_IMAGE_PRICES must be a JSON object of image_fast / image_quality → USD per image.") from error
        base = values.get("RAFII_AGENT_BASE_URL") or (OPENAI_BASE_URL if provider == "openai" else GATEWAY_BASE_URL if provider == "gateway" else None)
        return cls(flags={name: _flag(values, name) for name in FLAGS}, models=models, provider=provider, base_url=base, prices=prices,
                   image_estimates=image_prices, openai_tracing=_flag(values, "RAFII_AGENT_OPENAI_TRACING") and has_openai,
                   has_openai_key=has_openai, has_gateway_key=has_gateway,
                   genui_workspaces=frozenset(w.strip().lower() for w in str(values.get("RAFII_GENUI_WORKSPACES") or "").split(",") if w.strip()),
                   permissions_mode=("enforce" if _flag(values, "RAFII_AGENT_PERMISSIONS_ENFORCED") else "shadow") if _flag(values, "RAFII_AGENT_PERMISSIONS_ENABLED") else "off",
                   task_engine_workspaces=frozenset(w.strip().lower() for w in str(values.get("RAFII_TASK_ENGINE_WORKSPACES") or "").split(",") if w.strip()),
                   release_sha=str(values.get("VERCEL_GIT_COMMIT_SHA") or ""),
                   permissions_workspaces=frozenset(w.strip().lower() for w in str(values.get("RAFII_AGENT_PERMISSIONS_WORKSPACES") or "").split(",") if w.strip()),
                   _env={k: values.get(k) for k in ("OPENAI_API_KEY", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN")})

    # --- flags -------------------------------------------------------------------------------------------------------
    def enabled(self, name: str) -> bool:
        return bool(self.flags.get(name))

    def genui_for(self, workspace_id: str | None, *, founder: bool = False) -> dict:
        """Generative UI eligibility for one workspace: the deployment flags, narrowed by the canary allowlist. Enabling never
        grants a domain permission; every route still checks membership, role and the original approval path."""
        listed = not self.genui_workspaces or str(workspace_id or "").lower() in self.genui_workspaces
        on = self.enabled("RAFII_GENUI_ENABLED") and self.enabled("RAFII_AGENT_V2_ENABLED") and listed
        if founder:
            on = on and self.enabled("RAFII_GENUI_FOUNDER_ENABLED")
        return {"enabled": on, "actions": on and self.enabled("RAFII_GENUI_ACTIONS_ENABLED"), "edits": on and self.enabled("RAFII_GENUI_EDITS_ENABLED"),
                "canary": bool(self.genui_workspaces)}

    def task_engine_for(self, workspace_id: str | None) -> str:
        """CF-3 canonical switches only; legacy draft flags cannot activate execution."""
        if not workspace_id or not self.enabled("RAFII_AGENT_V2_ENABLED") or not self.enabled("RAFII_TASK_ENGINE_ENABLED"):
            return "off"
        listed = "*" in self.task_engine_workspaces or str(workspace_id).lower() in self.task_engine_workspaces
        if not listed:
            return "off"
        return "on" if self.enabled("RAFII_TASK_ENGINE_AUTHORITATIVE") else "shadow"

    def task_engine_background_for(self, workspace_id: str | None) -> bool:
        return self.task_engine_for(workspace_id) == "on" and self.enabled("RAFII_TASK_ENGINE_BACKGROUND")

    def permissions_for(self, workspace_id: str | None) -> str:
        """The agent-permissions mode for one workspace (CF-2 §8.2): "off" (nothing is evaluated: today's behaviour), "shadow"
        (decisions are computed and logged, never applied) or "enforce". Off unless the mode is set AND the workspace is
        listed; an empty list is no workspace and "*" is every workspace. The mode never grants anything: every route and
        tool keeps its own membership, role and approval checks."""
        if self.permissions_mode == "off" or not workspace_id:
            return "off"
        listed = "*" in self.permissions_workspaces or str(workspace_id).lower() in self.permissions_workspaces
        if not listed:
            return "off"
        if self.permissions_mode != "enforce":
            return self.permissions_mode
        engine = getattr(self, "task_engine_for", None)
        if not callable(engine) or engine(workspace_id) != "on":
            return "shadow"
        # Activation still requires all enforcement adapters (E2–E10) to be wired.
        from . import authz
        if not authz.enforcement_ready():
            return "shadow"
        if self.genui_for(workspace_id)["enabled"]:
            reader = self.permissions_gate_reader
            try:
                if not self.release_sha or not callable(reader) or reader(workspace_id, self.release_sha) is not True:
                    return "shadow"
            except Exception:
                return "shadow"
        return "enforce"

    # --- credentials (server-side only) ------------------------------------------------------------------------------
    def credential(self, provider: str | None = None) -> str | None:
        provider = provider or self.provider
        if provider == "openai":
            return self._env.get("OPENAI_API_KEY") or None
        if provider == "gateway":
            return self._env.get("AI_GATEWAY_API_KEY") or self._env.get("VERCEL_OIDC_TOKEN") or None
        return None

    def qualified(self, model: str, provider: str | None = None) -> str:
        """The id the provider expects: the gateway needs a vendor prefix ("openai/gpt-6-sol")."""
        provider = provider or self.provider
        if provider == "gateway" and "/" not in model:
            return "openai/" + model
        return model.split("/", 1)[1] if provider == "openai" and model.startswith("openai/") else model

    # --- routing (§21) -----------------------------------------------------------------------------------------------
    def route(self, workload: str, *, reason: str) -> Route:
        if workload not in WORKLOADS:
            raise ValueError(f"Unknown workload {workload!r}.")
        if workload == "deterministic":
            return Route(workload, None, None, reason, True)
        model = self.models[_ALIAS_FOR[workload]]
        if workload == "voice_front_end":
            # GPT-Live runs only on the OpenAI API (WebRTC); the gateway has no Live transport.
            if not self.has_openai_key:
                return Route(workload, "openai", model, reason, False, blocker="OPENAI_API_KEY is not configured on this deployment, so Voice Mode can't start a GPT-Live session.")
            return Route(workload, "openai", model, reason, True)
        if self.provider is None:
            return Route(workload, None, model, reason, False, blocker="No model route is configured (OPENAI_API_KEY or AI_GATEWAY_API_KEY).")
        return Route(workload, self.provider, self.qualified(model), reason, True)

    def price(self, model: str) -> tuple[float, float] | None:
        bare = model.split("/", 1)[-1]
        return self.prices.get(model) or self.prices.get(bare)

    def estimate_usd_micro(self, model: str, input_tokens: int, output_tokens: int) -> int | None:
        price = self.price(model)
        if price is None:
            return None
        return int(round((input_tokens * price[0] + output_tokens * price[1])))  # USD/MTok × tokens = micro-USD

    def public(self) -> dict:
        """What the browser and traces may see: flags, aliases and availability. Never a credential."""
        return {"flags": dict(self.flags), "models": dict(self.models), "provider": self.provider,
                "voiceAvailable": self.has_openai_key and self.enabled("RAFII_VOICE_ENABLED"),
                "imageAvailable": self.provider is not None and self.enabled("RAFII_IMAGE_AGENT_ENABLED")}


def choose_reasoning(message: str, *, modality: str, attachments: int, steps_hint: int) -> tuple[str, str]:
    """(workload, reason) for the Manager itself. Deep reasoning only when the request needs it (§36: "Do not
    automatically escalate every query to the largest model")."""
    text = message.lower()
    if attachments:
        return "vision", "the request carries an image"
    if steps_hint >= 3 or any(word in text for word in ("plan a", "campaign plan", "strategy", "compare", "why does", "analy", "計劃", "策略", "分析")):
        return "deep_reasoning", "multi-step or analytical request"
    if len(text) < 60 and modality == "voice":
        return "standard_reasoning", "short spoken request"
    return "standard_reasoning", "default route for workspace requests"
