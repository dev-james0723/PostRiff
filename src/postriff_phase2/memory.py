"""Memory files the agent reads before every draft (agent chat design §5), rendered from workspace state.

Plain Markdown, owned by the workspace. This phase renders them from the active voice profile
and brand context; the agent cannot change them. The same rendering feeds the Memory page and
the prompt of any writing route, so what the person sees is exactly what the model is given.

A cloud route is the exception that is decided, not assumed: it reads these files only when the
workspace allowed it, and never a boundary marked private, local-only or excluded. The Memory page
shows that decision and what it withholds.
"""
from __future__ import annotations

from datetime import datetime, timezone

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError

FILE_ORDER = ("AGENT.md", "IDENTITY.md", "VOICE.md", "BOUNDARIES.md", "BRAND.md")
# In this order on purpose: a cloud route caps the joined files at MAX_MEMORY_BYTES from the tail
# (model_runtime), so a long VOICE.md loses its own tail, never the boundaries.
PROMPT_FILES = ("BOUNDARIES.md", "IDENTITY.md", "VOICE.md")
EGRESS_ACTION = "memory_egress"
# Boundary privacy states (postriff_alpha.profiles.PRIVACY) that may reach a cloud model once the
# workspace allows it. private, local_only, excluded and unlabelled boundaries never leave.
CLOUD_SHAREABLE = ("public", "workspace_only")
BRAND_HREF = "/app/workspace/brand"
AGENT_RULES = (
    "Channels and times named in a message win over the composer chips.",
    "Every draft, schedule plan and memory note is a proposal until the person approves it.",
    "The chat cannot publish, reply, connect an account, spend money or delete anything.",
    "Only sources the person added and marked usable are read; nothing else in the workspace is visible to the agent.",
    "Unknown facts stay out of drafts until the person confirms they are excluded.",
    "Approving a plan binds the exact text, media, account and time of each row (one job per destination).",
    "A cloud model reads these files only if you allow it, and never a boundary marked private or local-only.",
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


def boundary_fields(state):
    """Boundary answers live on the active voice revision (profiles.profile_finish keeps the approved fields
    there). A top-level `profile` is read as well, so a state that carries one is not silently ignored."""
    state = state or {}
    candidates = (((active_profile(state) or {}).get("profile") or {}).get("fields") or []) + ((state.get("profile") or {}).get("fields") or [])
    fields, seen = [], set()
    for f in candidates:
        if not isinstance(f, dict):
            continue
        identity = f.get("id") or f.get("key") or id(f)
        if identity in seen:
            continue
        seen.add(identity)
        if any(word in f"{f.get('section', '')} {f.get('key', '')} {f.get('id', '')}".lower() for word in ("boundar", "privacy")):
            fields.append(f)
    return fields


def render_files(state, shareable=None):
    """Return the five core files as {name, purpose, source, body, editHref}. Never includes private field values.
    With `shareable`, BOUNDARIES.md keeps only boundaries whose privacy is listed and says how many it left out."""
    state = state or {}
    speaker = state.get("speaker") or {}
    hub = state.get("brandHub") or {}
    you = state.get("you") if isinstance(state.get("you"), dict) else {}
    revision = active_profile(state)
    profile = (revision or {}).get("profile") or {}
    all_boundaries = boundary_fields(state)
    boundaries = all_boundaries if shareable is None else [f for f in all_boundaries if f.get("privacy") in shareable]
    withheld = len(all_boundaries) - len(boundaries)

    identity = "\n".join([
        "# Identity", "",
        _line("Speaker", speaker.get("label")), _line("Mode", hub.get("mode")), _line("Purpose", hub.get("purpose")),
        _line("Audience", hub.get("audience")), _line("Subject", hub.get("subject")), _line("Identity sentence", you.get("identitySentence")),
        "", "> Public-facing facts only. Anything private stays in BOUNDARIES.md.",
    ])

    if revision:
        voice = "\n".join([
            "# Voice", "",
            f"Revision {revision.get('revision')} · approved {_when(revision.get('approvedAt'))} · {revision.get('reason', '')}".rstrip(" ·"), "",
            f"Tone: {profile.get('tone') or '(not set)'}", "",
            "## Observations", "How to handle what you supply. A trait is never a reason to add a detail, habit or admission you did not supply.",
            *([f"- {item}" for item in profile.get("observations") or []] or ["- (none recorded)"]), "",
            *learning.render_lines(state), "",
            "## Writing example", ("> " + str(profile.get("writingExample")).replace("\n", "\n> ")) if profile.get("writingExample") else "(none supplied)", "",
            "## Unknowns kept explicit", *([f"- {item}" for item in profile.get("unknowns") or []] or ["- (none)"]),
        ])
    else:
        voice = "# Voice\n\nNo active voice profile yet. Drafts can be previewed, but nothing can be scheduled until one is approved.\n\nSet it up in Brand → Voice (about two minutes)."

    if boundaries:
        body = "\n".join(["# Boundaries", ""] + [f"- {f.get('label') or f.get('key') or f.get('id')}: {f.get('value', '')}" + (f" _({f['privacy']})_" if f.get("privacy") else "") for f in boundaries])
    elif withheld:
        body = "# Boundaries"
    else:
        body = "# Boundaries\n\nNo boundaries recorded yet.\n\nName the topics and personal details that must stay out of public content. Categories only, never secret values."
    if withheld:
        body += f"\n\n> {withheld} more boundar{'y is' if withheld == 1 else 'ies are'} private or local-only and not shared here. Keep drafts conservative about personal details."

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


def prompt_fragments(state, names=PROMPT_FILES, shareable=None):
    """The files a writing route receives, in order. AGENT.md is for people; BRAND.md duplicates IDENTITY.md for prompts."""
    files = {item["name"]: item["body"] for item in render_files(state, shareable)}
    return [{"name": name, "body": files[name]} for name in names if name in files]


def egress(state):
    """The workspace's decision about memory files and cloud models. Absent means not allowed."""
    decision = (state or {}).get("memoryEgress")
    return decision if isinstance(decision, dict) else {"cloud": False}


def projection(state, provider_class):
    """What a writing route may read. Local routes get every prompt file; a cloud route gets them only
    when the workspace allowed it, with private, local-only, excluded and unlabelled boundaries removed."""
    if provider_class != "cloud":
        return {"files": prompt_fragments(state), "shared": True, "withheldBoundaries": 0}
    if egress(state).get("cloud") is not True:
        return {"files": [], "shared": False, "withheldBoundaries": 0}
    withheld = sum(1 for f in boundary_fields(state) if f.get("privacy") not in CLOUD_SHAREABLE)
    return {"files": prompt_fragments(state, shareable=CLOUD_SHAREABLE), "shared": True, "withheldBoundaries": withheld}


def egress_summary(state):
    """For the Memory page: the current decision and exactly what a cloud model would and would not read."""
    decision = egress(state)
    return {"cloud": decision.get("cloud") is True, "decidedAt": decision.get("decidedAt"), "decidedBy": decision.get("decidedBy"),
            "sharedFiles": list(PROMPT_FILES), "shareablePrivacy": list(CLOUD_SHAREABLE),
            "withheldBoundaries": sum(1 for f in boundary_fields(state) if f.get("privacy") not in CLOUD_SHAREABLE)}


def apply_memory_action(state, action, payload, actor, now):
    """Handle `memory_egress` (owner only, see permissions); return True when consumed."""
    if action != EGRESS_ACTION:
        return False
    cloud = payload.get("cloud")
    if not isinstance(cloud, bool) or payload.get("confirmed") is not True:
        raise AlphaError("Choose whether a cloud model may read your memory files, and confirm it.")
    state["memoryEgress"] = {"cloud": cloud, "decidedBy": actor, "decidedAt": now, "shareablePrivacy": list(CLOUD_SHAREABLE)}
    return True
