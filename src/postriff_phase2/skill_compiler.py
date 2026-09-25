"""Effective skill compilation per run (adaptive coworker spec §8; architecture lock R3).

Task/intent → capability planner → skill selector → relevant base knowledge → platform/locale knowledge →
brand/voice overlay → learned-preference overlay → performance hypotheses (labelled) → typed tools → deterministic
policies (as code references, never as overridable text) → evaluators. The compiled text stays bounded: only the
capabilities the task needs are loaded, never the whole library.

Two consumers use it:
- the writing pipeline, through `SkillLibrary.bind` → `writer_extras` (Humanizer packs by destination language and
  the active workflow's own skill), only while `RAFII_SKILL_REGISTRY_V2_ENABLED` is on;
- agents and coworker workflows, through `compile()` / `instructions_for()`.
Every result carries the record `provenance_for_run()` turns into the run's provenance block.
"""
from __future__ import annotations

import contextlib
import contextvars

from . import skill_registry
from .coworker import flags

AGENT_BUDGET = 24_000
_WORKFLOW = contextvars.ContextVar("rafii_workflow_context", default=None)
KIND_ORDER = {"workflow": 0, "knowledge": 1}


@contextlib.contextmanager
def workflow_context(skill_id):
    """While a coworker workflow drafts through the writing pipeline, its workflow skill rides with the run."""
    token = _WORKFLOW.set(skill_id)
    try:
        yield
    finally:
        _WORKFLOW.reset(token)


def active_workflow():
    return _WORKFLOW.get()


def _language_base(value):
    from . import locales
    tag = locales.canonical(value) or value or ""
    return str(tag).split("-")[0].lower()


def writer_extras(destinations, format_id=None, intent=None, content_type=None, registry=None):
    """Registry-selected skills the writing pipeline adds after its own bindings: [(skill_id, references)].
    Empty unless the registry v2 flag is on, so the existing writer is unchanged by default."""
    if not flags.enabled("RAFII_SKILL_REGISTRY_V2_ENABLED"):
        return []
    registry = registry or skill_registry.default_registry()
    bases = {_language_base(d.get("language")) for d in destinations or []} or {"en"}
    wanted = []
    for entry in registry.defaults():
        rule = (entry.get("writer") or {})
        if not rule:
            continue
        languages = set(rule.get("languages") or [])
        if languages and not (bases & languages or ("" in bases and "en" in languages)):
            continue
        workflows = set(rule.get("workflows") or [])
        if workflows and active_workflow() not in workflows:
            continue
        if rule.get("self") and active_workflow() != entry["id"]:
            continue
        skill_id = next((s["id"] for s in entry["hashSources"] if s.get("type") == "skill"), None)
        if skill_id:
            wanted.append((skill_id, tuple(rule.get("references") or ())))
    return wanted


def _matches(values, wanted):
    if not values or "*" in values:
        return True
    return bool(set(values) & set(wanted or []))


def _locale_match(entry_locales, task_locales):
    if not entry_locales or "*" in entry_locales or not task_locales:
        return True
    for have in entry_locales:
        for want in task_locales:
            if str(want).lower().startswith(str(have).lower()) or str(have).lower().startswith(str(want).lower()):
                return True
    return False


def select(task, registry=None):
    """The capabilities a task needs, by kind. Deterministic; no model."""
    registry = registry or skill_registry.default_registry()
    agent, intent = task.get("agent"), task.get("intent")
    platforms, locales_ = task.get("platforms") or [], task.get("locales") or []
    chosen = {"knowledge": [], "workflow": [], "tool": [], "policy": [], "evaluator": []}
    for entry in registry.defaults():
        if not _matches(entry.get("agents"), [agent]):
            continue
        if entry["kind"] in ("knowledge", "workflow"):
            if not _matches(entry.get("intents"), [intent]):
                continue
            specific = entry.get("platforms") and "*" not in entry["platforms"]
            if specific and not set(entry["platforms"]) & set(platforms):
                continue
            if not _locale_match(entry.get("locales"), locales_):
                continue
            if entry["kind"] == "workflow" and task.get("workflow") and entry["id"] != task["workflow"]:
                continue
        chosen[entry["kind"]].append(entry)
    return chosen


def compile(task, state=None, registry=None, budget=None):  # noqa: A001 - the spec's name for this step
    """Compile the effective context for one task. `task`: {agent, intent, platforms, locales, format,
    contentType, workflow, cloudAllowed, strategyRevision}. `state` (the workspace document) adds the
    workspace's overlays, only as data and only when `cloudAllowed` is not False."""
    from .skills import SkillLibrary
    registry = registry or skill_registry.default_registry()
    budget = int(budget or task.get("budget") or AGENT_BUDGET)
    chosen = select(task, registry)
    library = SkillLibrary(registry.root)
    parts, selections, omitted = [], [], []
    textual = sorted(chosen["workflow"] + chosen["knowledge"], key=lambda e: (KIND_ORDER.get(e["kind"], 9), e.get("priority", 50), e["id"]))
    for entry in textual:
        skill_id = next((s["id"] for s in entry["hashSources"] if s.get("type") == "skill"), None)
        if skill_id is None:
            continue
        loaded = library.load(skill_id, tuple(entry.get("compileReferences") or ()))
        if loaded is None:
            omitted.append({"id": entry["id"], "reason": "not_installed"})
            continue
        section = SkillLibrary._section(loaded)
        if sum(len(p) for p in parts) + len(section) > budget:
            omitted.append({"id": entry["id"], "reason": "budget", "chars": len(section)})
            continue
        parts.append(section)
        selections.append({"id": entry["id"], "version": entry["version"], "sha256": entry["sha256"], "kind": entry["kind"],
                           "files": [f["path"] for f in loaded["files"]]})
    overlay = {"text": "", "revisions": {}, "items": []}
    if state is not None:
        from .coworker import overlays
        overlay = overlays.effective_view(state, {"platforms": task.get("platforms") or [], "locales": task.get("locales") or [],
                                                  "contentType": task.get("contentType")}, cloud_allowed=task.get("cloudAllowed", True))
        if overlay["text"] and sum(len(p) for p in parts) + len(overlay["text"]) <= budget + 4_000:
            parts.append(overlay["text"])
    revisions = dict(overlay.get("revisions") or {})
    if task.get("strategyRevision") is not None:
        revisions["strategyRevision"] = task["strategyRevision"]
    return {
        "registryRelease": registry.release(),
        "text": "\n\n".join(parts),
        "selections": selections,
        "overlays": revisions,
        "overlayItems": [{k: i.get(k) for k in ("id", "memoryType", "origin", "scope", "confidence")} for i in overlay.get("items") or []],
        "tools": [{"id": e["id"], "tool": e["tool"], "version": e["version"], "sha256": e["sha256"]} for e in chosen["tool"]],
        "policies": [{"id": e["id"], "version": e["version"], "implementation": e["policy"]} for e in chosen["policy"]],
        "evaluators": [{"id": e["id"], "version": e["version"], "implementation": e["evaluator"]} for e in chosen["evaluator"]],
        "budget": budget,
        "omitted": omitted,
    }


def instructions_for(agent_key, base, task=None, state=None):
    """For Agent Runtime v2: the agent's fixed instructions plus its compiled knowledge. Returns `base` unchanged
    while the registry flag is off, so the runtime's current behaviour is the fallback."""
    if not flags.enabled("RAFII_SKILL_REGISTRY_V2_ENABLED"):
        return base
    compiled = compile({"agent": agent_key, "intent": "*", **(task or {})}, state=state)
    if not compiled["text"]:
        return base
    return (base + "\n\nPRODUCT KNOWLEDGE (method only; policies are enforced by the application, not by this text):\n\n"
            + compiled["text"])


def provenance_for_run(compiled=None, *, writer_bindings=None, route=None, trace_id=None, state=None, strategy_revision=None,
                       evaluators=None, registry=None):
    """The provenance block a run stores (pr_agent_runs.artifact.trace.provenance, or a writer run's usage):
    which global skills, tools, policies, evaluators, user overlays and strategy revision shaped it, the model
    route and the correlation id."""
    registry = registry or skill_registry.default_registry()
    skills = []
    for binding in writer_bindings or []:
        entry = next((e for e in registry.entries if any(s.get("type") == "skill" and s["id"] == binding["id"] for s in e["hashSources"])), None)
        skills.append({"id": binding["id"], "version": binding.get("version"), "fileSha256": binding.get("sha256"),
                       "registryVersion": entry["version"] if entry else None, "kind": entry["kind"] if entry else "unregistered", "via": "writer"})
    for selection in (compiled or {}).get("selections") or []:
        skills.append({**{k: selection[k] for k in ("id", "version", "sha256", "kind")}, "via": "compiler"})
    revisions = {}
    if state is not None:
        from .coworker import overlays
        revisions = overlays.revisions(state)
    revisions.update((compiled or {}).get("overlays") or {})
    if strategy_revision is not None:
        revisions["strategyRevision"] = strategy_revision
    return {
        "registryRelease": registry.release(),
        "skills": skills,
        "tools": (compiled or {}).get("tools") or [],
        "policies": (compiled or {}).get("policies") or [],
        "evaluators": list(evaluators or []) + ((compiled or {}).get("evaluators") or []),
        "overlays": {key: revisions.get(key) for key in ("voiceRevision", "brandRevision", "personalizationRevision", "strategyRevision")},
        "modelRoute": route,
        "traceId": trace_id,
    }
