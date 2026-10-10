"""CF-3 task engine modes. Only explicit authoritative mode may change legacy behavior.

Canonical flags are RAFII_TASK_ENGINE_{ENABLED,AUTHORITATIVE,BACKGROUND,WORKSPACES}.
All default off and require Agent V2. An empty allowlist enables no workspace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ENABLED = "RAFII_TASK_ENGINE_ENABLED"
AUTHORITATIVE = "RAFII_TASK_ENGINE_AUTHORITATIVE"
WORKSPACES = "RAFII_TASK_ENGINE_WORKSPACES"
BACKGROUND = "RAFII_TASK_ENGINE_BACKGROUND"
AGENT_V2 = "RAFII_AGENT_V2_ENABLED"


def _on(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    enabled: bool
    authoritative: bool
    background: bool
    workspaces: frozenset
    everywhere: bool

    def mode(self, workspace_id) -> str:
        if not self.enabled or not workspace_id or not (self.everywhere or str(workspace_id).lower() in self.workspaces):
            return "off"
        return "on" if self.authoritative else "shadow"

    def for_workspace(self, workspace_id) -> bool:
        return self.mode(workspace_id) == "on"

    @property
    def anywhere(self) -> bool:
        return self.enabled and self.authoritative and (self.everywhere or bool(self.workspaces))


def settings(environ=None, cfg=None) -> Settings:
    values = os.environ if environ is None else environ
    listed = [w.strip().lower() for w in str(values.get(WORKSPACES) or "").split(",") if w.strip()]
    enabled = _on(values.get(AGENT_V2)) and _on(values.get(ENABLED))
    authoritative = enabled and _on(values.get(AUTHORITATIVE))
    return Settings(enabled, authoritative, authoritative and _on(values.get(BACKGROUND)),
                    frozenset(w for w in listed if w != "*"), "*" in listed)


def mode_for(workspace_id, cfg=None, environ=None) -> str:
    try:
        if cfg is not None and callable(getattr(cfg, "task_engine_for", None)):
            result = cfg.task_engine_for(workspace_id)
            return result if result in ("off", "shadow", "on") else "off"
        return settings(environ).mode(workspace_id)
    except Exception:
        return "off"


def enabled_for(workspace_id, cfg=None, environ=None) -> bool:
    return mode_for(workspace_id, cfg, environ) == "on"


def shadow_for(workspace_id, cfg=None, environ=None) -> bool:
    return mode_for(workspace_id, cfg, environ) == "shadow"


def store_for(workspace_id, cfg=None, environ=None) -> bool:
    return mode_for(workspace_id, cfg, environ) != "off"


def anywhere(cfg=None, environ=None) -> bool:
    try:
        if cfg is not None and hasattr(cfg, "task_engine_workspaces"):
            return any(mode_for(w, cfg) == "on" for w in cfg.task_engine_workspaces)
        return settings(environ, cfg).anywhere
    except Exception:
        return False


def background(cfg=None, environ=None) -> bool:
    try:
        return settings(environ, cfg).background
    except Exception:
        return False


def background_for(workspace_id, cfg=None, environ=None) -> bool:
    if cfg is not None and callable(getattr(cfg, "task_engine_background_for", None)):
        return mode_for(workspace_id, cfg) == "on" and bool(cfg.task_engine_background_for(workspace_id))
    return mode_for(workspace_id, cfg, environ) == "on" and settings(environ).background
