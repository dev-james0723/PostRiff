"""Memory files the agent reads before every draft (agent chat design §5), rendered from workspace state.

Plain Markdown, owned by the workspace. This phase renders them from the active voice profile
and brand context; the agent cannot change them. The same rendering feeds the Memory page and
the prompt of any writing route, so what the person sees is exactly what the model is given.
"""
from __future__ import annotations

from datetime import datetime, timezone

FILE_ORDER = ("AGENT.md", "IDENTITY.md", "VOICE.md", "BOUNDARIES.md", "BRAND.md")
BRAND_HREF = "/app/workspace/brand"
AGENT_RULES = (
    "Channels and times named in a message win over the composer chips.",
    "Every draft, schedule plan and memory note is a proposal until the person approves it.",
    "The chat cannot publish, reply, connect an account, spend money or delete anything.",
    "Only sources the person added and marked usable are read; nothing else in the workspace is visible to the agent.",
    "Unknown facts stay out of drafts until the person confirms they are excluded.",
    "Approving a plan binds the exact text, media, account and time of each row (one job per destination).",
)


def _line(label, value):
    value = value.strip() if isinstance(value, str) else ""
    return f"{label}: {value}" if value else f"{label}: (not set)"


def _when(value):
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            return value
    return "unknown time"


def active_profile(state):
    speaker = state.get("speaker") or {}
    active = speaker.get("activeRevision")
    return next((r for r in speaker.get("revisions", []) if r.get("revision") == active), None)


def render_files(state):
    """Return the five core files as {name, purpose, source, body, editHref}. Never includes private field values."""
    state = state or {}
    speaker = state.get("speaker") or {}
    hub = state.get("brandHub") or {}
    you = state.get("you") if isinstance(state.get("you"), dict) else {}
    revision = active_profile(state)
    profile = (revision or {}).get("profile") or {}
    fields = [f for f in ((state.get("profile") or {}).get("fields") or []) if isinstance(f, dict)]
    boundaries = [f for f in fields if any(word in f"{f.get('section', '')} {f.get('key', '')} {f.get('id', '')}".lower() for word in ("boundar", "privacy"))]

    identity = "\n".join([
        "# Identity", "",
        _line("Speaker", speaker.get("label")), _line("Mode", hub.get("mode")), _line("Purpose", hub.get("purpose")),
        _line("Audience", hub.get("audience")), _line("Subject", hub.get("subject")), _line("Identity sentence", you.get("identitySentence")),
        "", "> Public-facing facts only. Anything private stays in BOUNDARIES.md.",
    ])

    if revision:
        preferences = profile.get("preferences") or []
        voice = "\n".join([
            "# Voice", "",
            f"Revision {revision.get('revision')} · approved {_when(revision.get('approvedAt'))} · {revision.get('reason', '')}".rstrip(" ·"), "",
            f"Tone: {profile.get('tone') or '(not set)'}", "",
            "## Observations", *([f"- {item}" for item in profile.get("observations") or []] or ["- (none recorded)"]), "",
            "## Preferences", *([f"- {p.get('platform')} · {p.get('language')} · {p.get('key')}: {p.get('value')}" for p in preferences] or ["- (none yet; edits kept in the Queue become preferences)"]), "",
            "## Writing example", ("> " + str(profile.get("writingExample")).replace("\n", "\n> ")) if profile.get("writingExample") else "(none supplied)", "",
            "## Unknowns kept explicit", *([f"- {item}" for item in profile.get("unknowns") or []] or ["- (none)"]),
        ])
    else:
        voice = "# Voice\n\nNo active voice profile yet. Drafts can be previewed, but nothing can be scheduled until one is approved.\n\nSet it up in Brand → Voice (about two minutes)."

    if boundaries:
        body = "\n".join(["# Boundaries", ""] + [f"- {f.get('label') or f.get('key') or f.get('id')}: {f.get('value', '')}" + (f" _({f['privacy']})_" if f.get("privacy") else "") for f in boundaries])
    else:
        body = "# Boundaries\n\nNo boundaries recorded yet.\n\nName the topics and personal details that must stay out of public content. Categories only, never secret values."

    agent = "\n".join(["# Agent", "", "How the PostRiff agent works with you today. These are the rules the current build enforces, not aspirations.", ""] + [f"- {rule}" for rule in AGENT_RULES])
    brand = "\n".join([
        "# Brand", "",
        _line("Workspace speaker", hub.get("speaker")), _line("Mode", hub.get("mode")),
        "Layers: " + (", ".join(hub.get("layers") or []) or "(none)"), "",
        "> One workspace speaks with one brand today. Separate brands belong in their own workspaces.",
    ])
    return [
        {"name": "AGENT.md", "purpose": "How the agent works with you", "source": "Fixed in this version", "body": agent, "editHref": None},
        {"name": "IDENTITY.md", "purpose": "Who you are, publicly", "source": "From your brand context", "body": identity, "editHref": BRAND_HREF},
        {"name": "VOICE.md", "purpose": f"How you sound · rev {revision.get('revision')}" if revision else "How you sound · not set up", "source": "From your active voice profile", "body": voice, "editHref": BRAND_HREF},
        {"name": "BOUNDARIES.md", "purpose": "What stays out of content", "source": "From your profile answers" if boundaries else "Not recorded yet", "body": body, "editHref": BRAND_HREF},
        {"name": "BRAND.md", "purpose": "Brand context for this workspace", "source": "From your brand context", "body": brand, "editHref": BRAND_HREF},
    ]


def prompt_fragments(state, names=("VOICE.md", "IDENTITY.md", "BOUNDARIES.md")):
    """The files a writing route receives, in order. AGENT.md is for people; BRAND.md duplicates IDENTITY.md for prompts."""
    files = {item["name"]: item["body"] for item in render_files(state)}
    return [{"name": name, "body": files[name]} for name in names if name in files]
