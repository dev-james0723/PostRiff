"""Typed agent tools for the RAFII Product Growth program (PRD R-ENG-01, AC28).

Each slice keeps its tools in `<slice>/agent_tools.py` with `register()` and a `TOOL_SCOPES` map; this module registers
the present ones into the single Agent Runtime v2 registry and extends specialist scopes through the runtime's own
extension point. Every tool passes the runtime's gate (scope, voice parity, live permission, cancellation, schema), so
voice and text have identical authority. Reads never create paid work or external effects; nothing here sends,
publishes, replies or charges — those stay behind their own approvals and quotes.
"""
from __future__ import annotations

import importlib

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


def _present():
    for name in SLICES:
        try:
            yield importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name and name.startswith(error.name):
                continue   # slice not part of this build
            raise


def register():
    modules = list(_present())
    for module in modules:
        module.register()
    try:
        from .agent_runtime_v2 import specialists
    except ImportError:
        return modules
    scopes = {}
    for module in modules:
        for tool, agents in getattr(module, "TOOL_SCOPES", {}).items():
            for agent in agents:
                scopes.setdefault(agent, []).append(tool)
    for agent, names in scopes.items():
        try:
            specialists.extend_scope(agent, names)
        except (ValueError, AttributeError):
            continue
    return modules
