"""Typed agent tools for the RAFII Product Growth program (PRD R-ENG-01, AC28).

Each slice keeps its tools in `<slice>/agent_tools.py` with `register()` and a `TOOL_SCOPES` map; this module registers
the present ones into the single Agent Runtime v2 registry and extends specialist scopes through the runtime's own
extension point. Every tool passes the runtime's gate (scope, voice parity, live permission, cancellation, schema), so
voice and text have identical authority. Reads never create paid work or external effects; nothing here sends,
publishes, replies or charges — those stay behind their own approvals and quotes. A person's own decisions (accepting
a carousel, adopting or rejecting a next-week strategy, accepting a trend opportunity) are never recorded by a tool:
those tools point to the page where the person makes them.

The runtime loads this module from `domain_tools.EXTENSION_MODULES` on every `ensure_registered()` (the path
`AgentRuntimeService` takes), so the tools reach production turns without a separate call. `register()` is
idempotent: tools register once, scopes are re-bound on every call (a runtime that reset its extension points gets
them back), and one slice that fails to register never keeps the others out.
"""
from __future__ import annotations

import importlib
import logging

SLICES = (
    "postriff_phase2.first_week.agent_tools",
    "postriff_phase2.source_uploads.agent_tools",
    "postriff_phase2.relationships.agent_tools",
    "postriff_phase2.results.agent_tools",
    "postriff_phase2.series.agent_tools",
    "postriff_phase2.visual_pack.agent_tools",
    "postriff_phase2.briefs.agent_tools",
    "postriff_phase2.proof.agent_tools",
)
log = logging.getLogger("postriff.agent_runtime")


def _present():
    for name in SLICES:
        try:
            yield importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name and name.startswith(error.name):
                continue   # slice not part of this build
            raise


def register(strict=False):
    """Register every present slice and bind its scopes. `strict` (CI and the skill lock) raises on a slice that fails
    to register; the runtime path logs it and keeps the other slices."""
    modules = []
    for module in _present():
        try:
            module.register()
        except Exception:  # noqa: BLE001 - one broken slice never keeps the other slices' tools out of the runtime
            if strict:
                raise
            log.error("agent_runtime.growth_v2_slice_failed %s", module.__name__)
            continue
        modules.append(module)
    try:
        from .agent_runtime_v2 import specialists, tool_adapter
    except ImportError:
        return modules
    scopes = {}
    for module in modules:
        for tool, agents in getattr(module, "TOOL_SCOPES", {}).items():
            if tool not in tool_adapter.REGISTRY:
                continue   # a scope never names a tool the registry does not have
            for agent in agents:
                scopes.setdefault(agent, []).append(tool)
    for agent, names in scopes.items():
        try:
            specialists.extend_scope(agent, names)
        except (ValueError, AttributeError):
            continue
    return modules
