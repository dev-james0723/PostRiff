"""How Rafii talks to one person: tone, detail, speaking pace, voice, language and initiative.

A person-level setting (not per workspace) stored on public.pr_profiles.agent_style (migration 030) as a small JSON
object of enum values. It shapes the Manager's written answer and `speakable`, and GPT-Live's spoken delivery.
Only enum values are stored and only fixed sentences chosen by them reach a prompt, never the person's own words.
"""
from __future__ import annotations

import json

from postriff_alpha.domain import AlphaError

TONES = ("friendly", "professional", "playful", "direct")
DETAILS = ("concise", "balanced", "detailed")
PACES = ("slower", "normal", "faster")
VOICES = ("marin", "cedar", "sage", "verse", "coral", "alloy")
LANGUAGES = ("auto", "en", "yue", "cmn")
INITIATIVE = ("ask", "suggest")

FIELDS = {"tone": TONES, "detail": DETAILS, "pace": PACES, "voice": VOICES, "language": LANGUAGES, "initiative": INITIATIVE}
DEFAULT = {"tone": "friendly", "detail": "balanced", "pace": "normal", "voice": "marin", "language": "auto", "initiative": "suggest"}

# The starting points offered before the first voice call; every field can be changed afterwards.
PRESETS = {
    "friendly": {"tone": "friendly", "detail": "balanced", "pace": "normal", "initiative": "suggest"},
    "concise": {"tone": "direct", "detail": "concise", "pace": "normal", "initiative": "ask"},
    "explainer": {"tone": "friendly", "detail": "detailed", "pace": "slower", "initiative": "suggest"},
}

MAX_STORED_BYTES = 512

_TONE_LINES = {
    "friendly": "Tone: warm and friendly, like a helpful coworker. Plain words, no jargon.",
    "professional": "Tone: professional and polished. Courteous and precise, no slang.",
    "playful": "Tone: light and upbeat. A little gentle humour is fine, never at the person's expense; stay accurate.",
    "direct": "Tone: direct and matter-of-fact. No small talk and no filler.",
}
_TEXT_DETAIL_LINES = {
    "concise": "Length: as short as possible, one or two sentences. Give details only when asked.",
    "balanced": "Length: short by default; add the one detail that helps most.",
    "detailed": "Length: explain step by step and say why. Short numbered steps are fine in the written answer.",
}
_VOICE_DETAIL_LINES = {
    "concise": "Keep each spoken answer to one short sentence unless the person asks for more.",
    "balanced": "Keep spoken answers to one to three short sentences.",
    "detailed": "Explain in up to five short sentences; when there are steps, give them one at a time and check the person is with you.",
}
_PACE_LINES = {
    "slower": "Speak a little slower than usual, with short pauses between ideas.",
    "normal": "",
    "faster": "Speak a little faster than usual and keep it crisp.",
}
_INITIATIVE_LINES = {
    "ask": "Answer what was asked. Don't suggest extra next steps unless the person asks.",
    "suggest": "When it helps, offer one useful next step.",
}


def normalize(raw) -> dict:
    """Any stored or sent value becomes a complete, valid style; unknown keys and values fall back to the default."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    style = {key: (raw.get(key) if raw.get(key) in allowed else DEFAULT[key]) for key, allowed in FIELDS.items()}
    style["chosen"] = raw.get("chosen") is True
    return style


def validate_patch(patch) -> dict:
    """A PATCH from the person: only known keys with allowed values, or a named preset. Returns the partial change."""
    if not isinstance(patch, dict) or not patch:
        raise AlphaError("Choose how Rafii should talk to you.")
    change = {}
    preset = patch.get("preset")
    if preset is not None:
        if preset not in PRESETS:
            raise AlphaError("Choose one of the listed styles.")
        change.update(PRESETS[preset])
    for key, value in patch.items():
        if key in ("preset", "chosen"):
            continue
        if key not in FIELDS:
            raise AlphaError("That style setting doesn't exist.")
        if value not in FIELDS[key]:
            raise AlphaError("Choose one of the listed options.")
        change[key] = value
    if patch.get("chosen") is not None:
        if type(patch["chosen"]) is not bool:
            raise AlphaError("That style setting doesn't exist.")
        change["chosen"] = patch["chosen"]
    if not change:
        raise AlphaError("Choose how Rafii should talk to you.")
    return change


def merge(current, change) -> dict:
    return normalize({**normalize(current), **change})


def load(cur, principal) -> dict:
    """The person's style, or the default. Tolerates a database where migration 030 has not been applied yet."""
    mark = "agent_style_read"
    try:
        cur.execute(f"SAVEPOINT {mark}")
        cur.execute("SELECT agent_style FROM public.pr_profiles WHERE user_id=%s AND deleted_at IS NULL", (principal,))
        row = cur.fetchone()
        cur.execute(f"RELEASE SAVEPOINT {mark}")
    except Exception:  # noqa: BLE001 - an unmigrated column must not break a turn; the default style applies
        cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
        return normalize({})
    return normalize(row[0] if row else {})


def text_block(style) -> str:
    """Style lines for the Manager's written answer and its `speakable` (fixed text chosen by enum values)."""
    s = normalize(style)
    lines = ["## How this person wants Rafii to talk", _TONE_LINES[s["tone"]], _TEXT_DETAIL_LINES[s["detail"]], _INITIATIVE_LINES[s["initiative"]],
             "For `speakable`: " + _VOICE_DETAIL_LINES[s["detail"]]]
    return "\n".join(line for line in lines if line)


def voice_block(style) -> str:
    """Style lines for GPT-Live's spoken delivery."""
    s = normalize(style)
    lines = ["Delivery the person chose:", _TONE_LINES[s["tone"]], _VOICE_DETAIL_LINES[s["detail"]], _PACE_LINES[s["pace"]], _INITIATIVE_LINES[s["initiative"]]]
    return "\n".join(line for line in lines if line)


def voice_id(style) -> str:
    return normalize(style)["voice"]


def locale(style) -> str:
    return normalize(style)["language"]
