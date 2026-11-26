"""A zero-network writer that follows one-click tone and polish edits (draft_edits), for the local dev harness, unit
tests and the PostgreSQL suite. Synthetic: no model is called and the output is not a quality result.

For an edit request the writer returns the passage it was handed (`material`, role "rework"), tidied of doubled spaces,
with one fixed, fact-free mark for the tone or for polish (an emoji at the end). Every name, number, date, link and
quotation stays as it was, so the fidelity check reports nothing, and a browser can click a tone and see a candidate.
A custom tone whose instruction asks to leave the text unchanged returns the passage as it is: the no-change outcome.
Every other request is answered by the writer it extends, exactly as before.
"""
from __future__ import annotations

import re

from postriff_phase2 import draft_edits, fencing
from postriff_phase2.agent_runtime import FixtureAgentRuntime, safe_event
from postriff_phase2.contracts import digest

MARKS = {"warm": "🙂", "professional": "📌", "direct": "👉", "playful": "🎉", "custom": "✨", "polish": "✅"}
UNCHANGED = re.compile(r"\b(?:unchanged|as it is|no change|leave it)\b", re.I)
_DOUBLED = re.compile(r"(?<=\S)[ \t]{2,}(?=\S)")


def edited(passage, edit):
    """The fixture's answer to one edit: deterministic, and the same for the same passage and edit."""
    edit = edit if isinstance(edit, dict) else {}
    if edit.get("tone") == "custom" and UNCHANGED.search(edit.get("instruction") or ""):
        return passage
    mark = MARKS.get(edit.get("tone") if edit.get("mode") == "tone" else "polish", MARKS["custom"])
    tidy = "\n".join(_DOUBLED.sub(" ", line) for line in passage.split("\n"))
    return tidy.rstrip() + " " + mark


class FixtureEdits:
    """Mixin for a FixtureAgentRuntime: answers a request that carries `edit` as `edited` does, else defers."""
    supports_edits = True

    def start_turn(self, request, emit):
        fields = fencing.writer_fields(request)
        if not isinstance(fields.get("edit"), dict):
            return super().start_turn(request, emit)
        destination = (request.get("destinations") or [{}])[0]
        passage = next((section["text"] for section in fields.get("material") or [] if section.get("role") == "rework"), "")
        text = edited(passage, fields["edit"])
        emit(safe_event("run.started", model=self.model, reasoning="quick", contextDigest=digest(request["context"])))
        emit(safe_event("progress.updated", stage="drafting", percent=50))
        for start in range(0, len(text), 400):
            emit(safe_event("message.delta", destination=0, text=text[start:start + 400]))
        emit(safe_event("message.completed", destination=0))
        variant = {**{key: destination[key] for key in ("platform", "language", "channelId", "format") if destination.get(key)},
                   "text": text, "sourceIds": [], "unknowns": [], "warnings": [], "candidateOnly": False}
        voice = request.get("voiceContext") or {"mode": "neutral", "bindings": [], "digest": None, "route": None}
        artifact = {"variants": [variant], "voiceContext": {key: voice.get(key) for key in ("mode", "bindings", "digest", "route")}}
        emit(safe_event("artifact.created", artifactHash=digest(artifact), variants=1))
        emit(safe_event("run.completed", usage={"provenance": "measured_locally", "modelRequests": 0}))
        return {"artifact": artifact, "usage": {"provenance": "measured_locally", "modelRequests": 0, "costUsd": 0}}


class EditingFixtureWriter(FixtureEdits, FixtureAgentRuntime):
    """The template writer ("Templates (no AI model)"), able to follow an edit."""


def editing(runtime):
    """The same fixture writer (same model id, same settings), able to follow an edit. Any other writer, or one that
    already follows edits, is returned as it is."""
    if not isinstance(runtime, FixtureAgentRuntime) or getattr(runtime, "supports_edits", False):
        return runtime
    kind = type(runtime)
    clone = object.__new__(type("Editing" + kind.__name__, (FixtureEdits, kind), {}))
    clone.__dict__.update(runtime.__dict__)
    return clone


def attach(service):
    """Dev harness: every fixture writer follows edits, then the route is mounted as POSTRIFF_DRAFT_EDITS=1 mounts it."""
    ideas = service.ideas
    swapped = {id(runtime): editing(runtime) for runtime in ideas.runtimes}
    ideas.runtimes = [swapped[id(runtime)] for runtime in ideas.runtimes]
    ideas.runtime = swapped.get(id(ideas.runtime)) or editing(ideas.runtime)
    return draft_edits.mount(service, {draft_edits.FLAG: "1"})
