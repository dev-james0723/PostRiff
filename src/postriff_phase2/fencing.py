"""Neutralise reference-derived text before a writer reads it (chat-context SPEC §3 S3, §6.8).

The transport is structured JSON, so this is defence in depth: text taken from a post, a handed-in brief or a
machine note can't close a `<<<`/`>>>` fence or pose as one of the writer's own section labels.
"""
from __future__ import annotations

from postriff_alpha.domain import AlphaError
from postriff_alpha.generation import MATERIAL_LABEL

# Lines that open with one of these read like a section the writer was given, so they are quoted.
FENCE_LABELS = (MATERIAL_LABEL, "Reference notes", "Material")


def neutralize(text):
    if not isinstance(text, str):
        raise AlphaError("Invalid draft request.")
    if "\x00" in text:
        raise AlphaError("Use plain text within the displayed size limit.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
    labels = tuple(label.casefold() for label in FENCE_LABELS)
    return "\n".join(f"> {line}" if line.lstrip().casefold().startswith(labels) else line for line in text.split("\n"))


MATERIAL_MAX = 6000          # all sections together (ideas.MAX_TEXT)
NOTES_MAX = 4
NOTE_MAX = 1200
SECTION_ROLES = ("rework", "handed_in", "inspire")
NOTE_KINDS = ("photo", "video_frames")


def _clip(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def writer_fields(request):
    """The writer contract's data fields (chat-context SPEC §6.8): `material` sections (rework | handed_in first, then
    inspire; ≤ 6,000 characters in total) and `referenceNotes` (≤ 4 × 1,200). Each text is neutralised again here so a
    route never depends on the caller having done it. Keys are omitted when empty."""
    out = {}
    sections = [s for s in request.get("material") or [] if isinstance(s, dict) and s.get("role") in SECTION_ROLES] if isinstance(request.get("material"), list) else []
    sections.sort(key=lambda s: 0 if s["role"] != "inspire" else 1)
    room, material = MATERIAL_MAX, []
    for section in sections:
        text = neutralize(_clip(section.get("text"), room))
        if not text.strip():
            continue
        room -= len(text)
        item = {"role": section["role"], "label": neutralize(_clip(section.get("label"), 80)), "text": text}
        item.update({k: section[k] for k in ("platform", "language") if isinstance(section.get(k), str) and section[k]})
        material.append(item)
        if room <= 0:
            break
    if material:
        out["material"] = material
    notes = [n for n in request.get("referenceNotes") or [] if isinstance(n, dict)] if isinstance(request.get("referenceNotes"), list) else []
    kept = [{"label": neutralize(_clip(n.get("label"), 20)), "kind": n.get("kind") if n.get("kind") in NOTE_KINDS else "photo", "text": neutralize(_clip(n.get("text"), NOTE_MAX))}
            for n in notes[:NOTES_MAX] if isinstance(n.get("text"), str) and n["text"].strip()]
    if kept:
        out["referenceNotes"] = kept
    return out


def fixture_material(request):
    """What the free preview writer may use: only the rework or handed-in text, never inspiration or notes."""
    sections = request.get("material") if isinstance(request.get("material"), list) else []
    kept = [s["text"] for s in sections if isinstance(s, dict) and s.get("role") in ("rework", "handed_in") and isinstance(s.get("text"), str)]
    return neutralize("\n\n".join(kept)[:MATERIAL_MAX])
