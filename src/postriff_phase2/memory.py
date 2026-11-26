"""Memory files the agent reads before every draft (agent chat design §5), rendered from workspace state.

Plain Markdown, owned by the workspace. This phase renders them from the active voice profile
and brand context; the agent cannot change them. The same rendering feeds the Memory page and
the route-scoped writer projection. Completed receipts distinguish that eligible view from the exact bounded input sent.

A cloud route is the exception that is decided, not assumed: it reads these files only when the
workspace allowed it, and never a boundary marked private, local-only or excluded. The Memory page
shows that decision and what it withholds.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from . import locales

# How the person refers to themselves where a language's grammar shows the writer's gender (languages plan §5.5).
SELF_REFERENCE_LINES = {"feminine": "use feminine forms", "masculine": "use masculine forms", "neutral": "use neutral wording wherever the grammar allows"}

RENDER_VERSION = "brand-brain-memory/1.1"

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


def manual_profile_available(state, provider_class="local"):
    """An approved authored profile needs no fabricated sample grant; cloud consent still applies."""
    revision = active_profile(state)
    profile = (revision or {}).get("profile") or {}
    return bool(revision and not revision.get("stale") and profile.get("status") != "stale"
                and not profile.get("evidenceSourceIds")
                and (provider_class != "cloud" or egress(state).get("cloud") is True))


def boundary_fields(state):
    """Boundary answers live on the active voice revision (profiles.profile_finish keeps the approved fields
    there). A top-level `profile` is read as well, so a state that carries one is not silently ignored."""
    state = state or {}
    candidates = ((state.get("profile") or {}).get("fields") or []) + (((active_profile(state) or {}).get("profile") or {}).get("fields") or [])
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


# --- Trait scope (brand intelligence spec 5.6) --------------------------------------------------------------------------
# A trait may say where it holds: {platforms, accounts, languages}. Platform ids are compared without case, spaces or
# punctuation, so "LinkedIn" and "linkedin", "Google Business Profile" and "google_business_profile" are one platform.
SCOPE_KEYS = ("platforms", "accounts", "languages")


def platform_key(value):
    return "".join(ch for ch in value.casefold() if ch.isalnum()) if isinstance(value, str) else ""


def platform_name(value):
    """The product's own name for a platform id, or None: an id we do not know is never printed as text."""
    from .skills import CHANNEL_SKILLS
    key = platform_key(value)
    return next((name for name in CHANNEL_SKILLS if platform_key(name) == key), None) if key else None


def trait_scope(trait):
    """The trait's non-empty scope lists, or {} when it applies everywhere."""
    scope = trait.get("scope") if isinstance(trait, dict) and isinstance(trait.get("scope"), dict) else {}
    found = {key: [item for item in scope[key] if isinstance(item, str) and item] for key in SCOPE_KEYS if isinstance(scope.get(key), list)}
    return {key: items for key, items in found.items() if items}


def _settled(trait):
    """Kept, established and current: a trait that may render at all."""
    return trait.get("decision") != "reject" and trait.get("evidenceLevel") not in ("conflicting", "insufficient") and trait.get("status") != "historical"


def applies_everywhere(trait):
    """A trait that belongs in a profile's plain observation list: kept, established, current, and not tied to a
    platform, an account or a language. Everything that reads `observations` may then treat it as general."""
    return _settled(trait) and not trait_scope(trait)


def _language_matches(wanted, language):
    """A trait's or a lesson's language covers a draft's language and its regional forms: `zh-Hant` reaches
    `zh-Hant-HK` and `yue-Hant-HK` drafts, `en` every English draft (learning.applies reads a scope the same way)."""
    if not isinstance(language, str) or not language:
        return False
    chain = {language, *locales.scope_chain(language)}
    return any(isinstance(item, str) and (item in chain or (locales.canonical(item, family_ok=True) or item) in chain) for item in wanted)


def _account_key(value):
    return value.strip().lstrip("@").casefold() if isinstance(value, str) else ""


def _destination_accounts(destination, state):
    """Every name a destination's account goes by: its connection id and label, and for a connected channel the
    platform's own account id (what an imported account is keyed by)."""
    names = {_account_key(destination.get(key)) for key in ("channelId", "account")}
    phase2 = (state or {}).get("phase2") if isinstance((state or {}).get("phase2"), dict) else {}
    label = _account_key(destination.get("account"))
    for channel in phase2.get("channels") or []:
        if isinstance(channel, dict) and ((destination.get("channelId") and channel.get("id") == destination.get("channelId"))
                                          or (label and _account_key(channel.get("account")) == label)):
            names.update(_account_key(channel.get(key)) for key in ("id", "account", "providerAccountId"))
    names.discard("")
    return names


def trait_applies(trait, destinations, state=None):
    """Whether a trait renders for a request to these destinations. An unscoped trait renders everywhere. A scoped one
    renders only for a request that names destinations, when one of them matches every key the scope lists (platform,
    language, account). A trait tied to accounts belongs to a voice kept separate: it renders only when every
    destination is one of its accounts, so it never reaches another account's draft."""
    scope = trait_scope(trait)
    if not scope:
        return True
    found = []
    for destination in destinations or []:
        if isinstance(destination, dict):
            found.append((not scope.get("platforms") or platform_key(destination.get("platform")) in {platform_key(item) for item in scope["platforms"]})
                         and (not scope.get("languages") or _language_matches(scope["languages"], destination.get("language")))
                         and (not scope.get("accounts") or bool({_account_key(item) for item in scope["accounts"]} & _destination_accounts(destination, state))))
    return bool(found) and (all(found) if scope.get("accounts") else any(found))


def scope_label(trait):
    """How VOICE.md names where a scoped trait holds: platform and language names the product knows; never an
    account's id or handle."""
    scope, parts = trait_scope(trait), []
    if scope.get("platforms"):
        parts.append(" / ".join(dict.fromkeys(name for name in map(platform_name, scope["platforms"]) if name)) or "some channels")
    if scope.get("languages"):
        parts.append(" / ".join(dict.fromkeys(locales.display(item) for item in scope["languages"] if locales.canonical(item, family_ok=True))) or "some languages")
    if scope.get("accounts"):
        parts.append("one account" if len(scope["accounts"]) == 1 else "some accounts")
    return " · ".join(parts)


def voice_items(profile, destinations=None, state=None):
    """What VOICE.md lists under Observations: (the profile's plain observations, [(trait, line)] for each scoped trait
    that applies to these destinations). A trait marked as old style (`historical`) never renders, and neither does a
    scoped trait's wording on its own, even where a profile saved by older code still lists it as a plain observation."""
    dimensions = [item for item in profile.get("dimensions") or [] if isinstance(item, dict) and isinstance(item.get("observation"), str)]
    general = {item["observation"] for item in dimensions if applies_everywhere(item)} | {item for item in profile.get("userGuidance") or [] if isinstance(item, str)}
    hidden = {item["observation"] for item in dimensions if trait_scope(item) or item.get("status") == "historical"} - general
    plain = [item for item in profile.get("observations") or [] if not (isinstance(item, str) and item in hidden)]
    return plain, [(item, f"- [{scope_label(item)}] {item['observation']}") for item in dimensions if trait_scope(item) and _settled(item) and trait_applies(item, destinations, state)]


# --- Approved Genome lessons (brand intelligence spec 5.6) ---------------------------------------------------------------
MAX_GENOME_LINES = 12


def _cohort_known(value):
    return isinstance(value, str) and value.strip().casefold() not in ("", "unknown", "*", "any", "all")


def genome_applies(statement, destinations):
    """Whether an approved Genome lesson belongs to a request for these destinations: its cohort's platform, connection
    and language each match one destination wherever both name one. An unknown cohort value matches any destination,
    and so does a destination that names no account."""
    if not destinations:
        return True
    cohort = statement.get("cohort") if isinstance(statement.get("cohort"), dict) else {}
    platform, connection, language = (cohort.get(key) for key in ("platform", "connectionId", "language"))
    for destination in destinations:
        if not isinstance(destination, dict):
            continue
        if _cohort_known(platform) and destination.get("platform") and platform_key(platform) != platform_key(destination["platform"]):
            continue
        if _cohort_known(connection) and destination.get("channelId") and connection != destination["channelId"]:
            continue
        if _cohort_known(language) and destination.get("language") and not _language_matches([language], destination["language"]):
            continue
        return True
    return False


def genome_lines(genome, destinations=None):
    """The supported lessons of an approved Genome that VOICE.md carries for these destinations: the twelve newest
    (lessons are appended as they are approved), in the Genome's own order."""
    statements = [item for item in (genome or {}).get("statements") or [] if isinstance(item, dict) and item.get("grade") == "supported" and isinstance(item.get("text"), str)]
    return [item for item in statements if genome_applies(item, destinations)][-MAX_GENOME_LINES:]


def _section_lines(body, title):
    """The lines under one `## <title>` heading of a rendered file."""
    lines, inside = set(), False
    for line in body.splitlines():
        if line.startswith("## "):
            inside = line[3:] == title
        elif inside:
            lines.add(line)
    return lines


def render_files(state, shareable=None, destinations=None, content_type_id=None):
    """Return five derived files as {name, purpose, source, body, editHref}. Owner/local views may include private boundaries.
    With `shareable`, BOUNDARIES.md keeps only boundaries whose privacy is listed and says how many it left out.
    With `destinations`, VOICE.md carries only the learned preferences, scoped traits and Genome lessons that apply to
    them (a prompt slice); without, no scoped trait at all. A trait marked as old style is never rendered."""
    state = state or {}
    speaker = state.get("speaker") or {}
    hub = state.get("brandHub") or {}
    you = state.get("you") if isinstance(state.get("you"), dict) else {}
    revision = active_profile(state)
    profile = (revision or {}).get("profile") or {}
    all_boundaries = boundary_fields(state)
    if revision and (revision.get('stale') or profile.get('status') == 'stale'):
        revision, profile = None, {}
    boundaries = all_boundaries if shareable is None else [f for f in all_boundaries if f.get("privacy") in shareable]
    withheld = len(all_boundaries) - len(boundaries)

    identity = "\n".join([
        "# Identity", "",
        _line("Speaker", speaker.get("label")), _line("Mode", hub.get("mode")), _line("Purpose", hub.get("purpose")),
        _line("Audience", hub.get("audience")), _line("Subject", hub.get("subject")), _line("Identity sentence", you.get("identitySentence")),
        *([f"Referring to yourself in languages that mark gender: {SELF_REFERENCE_LINES[reference]}"] if (reference := locales.settings(state)["selfReference"]) else []),
        "", "> Public-facing facts only. Anything private stays in BOUNDARIES.md.",
    ])

    if revision:
        # A trait scoped to a platform, language or account is listed, labelled, only for a destination it matches.
        plain, scoped = voice_items(profile, destinations, state)
        voice = "\n".join([
            "# Voice", "",
            f"Revision {revision.get('revision')} · approved {_when(revision.get('approvedAt'))} · {revision.get('reason', '')}".rstrip(" ·"), "",
            f"Tone: {profile.get('tone') or '(not set)'}", "",
            "## Observations", "How to handle what you supply. A trait is never a reason to add a detail, habit or admission you did not supply.",
            *([f"- {item}" for item in plain] + [line for _, line in scoped] or ["- (none recorded)"]), "",
            *learning.render_lines(state, destinations, content_type_id), "",
            "## Writing example", ("> " + str(profile.get("writingExample")).replace("\n", "\n> ")) if profile.get("writingExample") else "(none supplied)", "",
            "## Unknowns kept explicit", *([f"- {item}" for item in profile.get("unknowns") or []] or ["- (none)"]),
        ])
    else:
        voice = "# Voice\n\nNo active voice profile yet. Drafts still work; review their wording before scheduling.\n\nSet it up in Brand → Voice."

    if boundaries:
        body = "\n".join(["# Boundaries", ""] + [f"- {f.get('label') or f.get('key') or f.get('id')}: {f.get('value', '')}" + (f" _({f['privacy']})_" if f.get("privacy") else "") for f in boundaries])
    elif withheld:
        body = "# Boundaries"
    else:
        body = "# Boundaries\n\nNo boundaries recorded yet.\n\nName the topics and personal details that must stay out of public content. Categories only, never secret values."
    if withheld:
        body += f"\n\n> {withheld} more boundar{'y is' if withheld == 1 else 'ies are'} private or local-only and not shared here. Keep drafts conservative about personal details."

    # Approved Genome extends the current voice file; stale/deleted/revoked evidence is excluded. With destinations, only
    # the lessons of a cohort they match.
    from .growth.service import current_genome
    approved_genome=current_genome(state)
    if approved_genome:
        lines=[s['text'] for s in genome_lines(approved_genome, destinations)]
        if lines:
            voice+='\n\n## Approved Creator Genome\nObserved writing preferences, never new personal facts or guaranteed outcomes.\n'+'\n'.join('- '+line for line in lines)
    agent = "\n".join(["# Agent", "", "How Rafii works with you.", ""] + [f"- {rule}" for rule in AGENT_RULES])
    brand = "\n".join([
        "# Brand", "",
        _line("Workspace speaker", hub.get("speaker")), _line("Mode", hub.get("mode")),
        "Layers: " + (", ".join(hub.get("layers") or []) or "(none)"), "",
        "> One workspace speaks with one brand today. Separate brands belong in their own workspaces.",
    ])
    return [
        {"name": "AGENT.md", "purpose": "How the agent works with you", "source": "Fixed in this version", "body": agent, "editHref": None},
        {"name": "IDENTITY.md", "purpose": "Who you are, publicly", "source": "From your brand context", "body": identity, "editHref": BRAND_HREF + "?section=identity"},
        {"name": "VOICE.md", "purpose": f"How you sound · rev {revision.get('revision')}" if revision else "How you sound · not set up", "source": "From your active voice profile" if revision else "No active voice profile yet", "body": voice, "editHref": BRAND_HREF + "?section=voice"},
        {"name": "BOUNDARIES.md", "purpose": "What stays out of content", "source": "From your profile answers" if boundaries else "Not recorded yet", "body": body, "editHref": BRAND_HREF + "?section=boundaries"},
        {"name": "BRAND.md", "purpose": "Brand context for this workspace", "source": "From your brand context", "body": brand, "editHref": BRAND_HREF},
    ]


def prompt_fragments(state, names=PROMPT_FILES, shareable=None, destinations=None, content_type_id=None):
    """The files a writing route receives, in order. AGENT.md is for people; BRAND.md duplicates IDENTITY.md for prompts."""
    files = {item["name"]: item["body"] for item in render_files(state, shareable, destinations, content_type_id)}
    return [{"name": name, "body": files[name]} for name in names if name in files]


def egress(state):
    """The workspace's decision about memory files and cloud models. Absent means not allowed."""
    decision = (state or {}).get("memoryEgress")
    return decision if isinstance(decision, dict) else {"cloud": False}


def projection(state, provider_class, destinations=None, content_type_id=None, voice_route=None):
    """What a writing route may read. Local routes get every prompt file; a cloud route gets them only
    when the workspace allowed it, with private, local-only, excluded and unlabelled boundaries removed.
    `learned` records which learned preferences the slice carried, for the run's usage."""
    import copy
    from . import voice_sources
    state = copy.deepcopy(state)
    revision = active_profile(state)
    profile = (revision or {}).get('profile') or {}
    evidence = profile.get('evidenceSourceIds') or []
    if evidence:
        # A workspace-wide memory grant cannot expand a sample's exact-route grant.
        # Raw sample examples never travel through the generic memory channel.
        profile['writingExample'] = ''
        allowed = voice_sources.project(state, evidence, 'generation', voice_route)['samples'] if voice_route else []
        if len(allowed) != len(evidence):
            revision['stale'] = True
    # A Creator Genome is also source-derived style. Its broad analysis consent cannot
    # confer downstream writer access to samples whose exact generation route is denied.
    genome = (state.get("brandHub") or {}).get("genome")
    genome_ids = [item.get("id") for item in (genome or {}).get("evidenceBindings", []) if item.get("id")]
    if genome_ids:
        eligible = voice_sources.project(state, genome_ids, "generation", voice_route)["samples"] if voice_route else []
        if len(eligible) != len(genome_ids):
            state["brandHub"].pop("genome", None)
    learned = learning.binding(state, destinations, content_type_id)
    if provider_class != "cloud":
        return {"files": prompt_fragments(state, destinations=destinations, content_type_id=content_type_id), "shared": True, "withheldBoundaries": 0, "learned": learned}
    if egress(state).get("cloud") is not True:
        return {"files": [], "shared": False, "withheldBoundaries": 0, "learned": {**learned, "used": [], "statements": [], "omitted": learned["used"] + learned["omitted"]}}
    withheld = sum(1 for f in boundary_fields(state) if f.get("privacy") not in CLOUD_SHAREABLE)
    return {"files": prompt_fragments(state, shareable=CLOUD_SHAREABLE, destinations=destinations, content_type_id=content_type_id), "shared": True, "withheldBoundaries": withheld, "learned": learned}


def egress_summary(state):
    """For the Memory page: the current decision and exactly what a cloud model would and would not read."""
    decision = egress(state)
    return {"cloud": decision.get("cloud") is True, "decidedAt": decision.get("decidedAt"), "decidedBy": decision.get("decidedBy"),
            "sharedFiles": list(PROMPT_FILES), "shareablePrivacy": list(CLOUD_SHAREABLE),
            "withheldBoundaries": sum(1 for f in boundary_fields(state) if f.get("privacy") not in CLOUD_SHAREABLE)}


def apply_memory_action(state, action, payload, actor, now):
    """Handle `memory_egress` (owner only, see permissions); return True when consumed."""
    if action in ("brand_brain_identity", "brand_brain_boundaries"):
        import copy
        if payload.get("confirmed") is not True:
            raise AlphaError("Confirm the identity or boundary changes and their effect on existing drafts.")
        fields = payload.get("fields")
        if action == "brand_brain_identity":
            allowed = ("speakerLabel", "identitySentence", "purpose", "audience", "subject", "speaker")
            if not isinstance(fields, dict) or not fields or any(key not in allowed for key in fields):
                raise AlphaError("Choose supported Brand Brain identity fields.")
            if any(not isinstance(value, str) or len(value) > 1200 for value in fields.values()):
                raise AlphaError("Keep each identity field within 1,200 characters.")
            for key, value in fields.items():
                value = value.strip()
                if key == "speakerLabel":
                    state.setdefault("speaker", {})["label"] = value
                elif key == "identitySentence":
                    from postriff_alpha import visuals
                    visuals.ensure(state)
                    state["you"][key] = value
                else:
                    state.setdefault("brandHub", {})[key] = value
        else:
            from postriff_alpha.profiles import PRIVACY
            if not isinstance(fields, list) or not 1 <= len(fields) <= 50:
                raise AlphaError("Supply between one and 50 boundary fields.")
            seen, updated = set(), []
            for field in fields:
                if not isinstance(field, dict) or not isinstance(field.get("id"), str) or not field["id"].strip() or len(field["id"]) > 100 or field["id"] in seen:
                    raise AlphaError("Each boundary needs a distinct field identifier.")
                if field.get("privacy") not in PRIVACY or any(not isinstance(field.get(key), str) or len(field[key]) > 1200 for key in ("label", "value")):
                    raise AlphaError("Each boundary needs a label, a short rule, and an explicit privacy classification.")
                seen.add(field["id"])
                updated.append({"id": field["id"], "key": field["id"], "section": "boundaries", "label": field["label"].strip(),
                                "value": field["value"].strip(), "privacy": field["privacy"], "updatedBy": actor, "updatedAt": now})
            existing = copy.deepcopy(state.setdefault("profile", {}).get("fields") or [])
            # Identifiers belonging to identity/questionnaire answers cannot be repurposed as boundaries.
            boundary_ids = {f.get("id") or f.get("key") for f in boundary_fields(state)}
            if any((f.get("id") or f.get("key")) in seen and (f.get("id") or f.get("key")) not in boundary_ids for f in existing):
                raise AlphaError("This identifier belongs to another profile field.")
            state["profile"]["fields"] = [f for f in existing if (f.get("id") or f.get("key")) not in seen] + updated
        return True
    if action != EGRESS_ACTION:
        return False
    cloud = payload.get("cloud")
    if not isinstance(cloud, bool) or payload.get("confirmed") is not True:
        raise AlphaError("Choose whether a cloud model may read your memory files, and confirm it.")
    state["memoryEgress"] = {"cloud": cloud, "decidedBy": actor, "decidedAt": now, "shareablePrivacy": list(CLOUD_SHAREABLE)}
    return True


def fingerprint(value):
    """Opaque canonical hash; raw memory never belongs in routine run receipts."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot(state, workspace_revision=None, *, shareable=None):
    files = render_files(state, shareable=shareable)
    return {"workspaceRevision": workspace_revision, "renderVersion": RENDER_VERSION,
            "renderDigest": fingerprint([{k: f[k] for k in ("name", "body")} for f in files]),
            "fileDigests": {f["name"]: fingerprint(f["body"]) for f in files},
            "activeVoiceRevision": (state.get("speaker") or {}).get("activeRevision"),
            "preferenceSetDigest": fingerprint(learning.active_items(state))}


def assemble(files, max_bytes=None):
    """Apply the writer's exact UTF-8 envelope budget before dispatch, never report an unsent tail.

    Only complete file headers and at least one body character are included. The returned files
    reproduce precisely the bytes a writer adapter joins, with explicit omission/truncation metadata.
    """
    selected, fragments, used = [], [], 0
    for file in files:
        body = file["body"]
        header = ("\n\n" if selected else "") + f"--- {file['name']} ---\n"
        remaining = None if max_bytes is None else max(0, max_bytes - used - len(header.encode()))
        sent = body if remaining is None else body.encode()[:remaining].decode(errors="ignore")
        if sent:
            selected.append({"name": file["name"], "body": sent})
            used += len((header + sent).encode())
        fragments.append({"name": file["name"], "digest": fingerprint(sent) if sent else None,
                          "bytesIncluded": len(sent.encode()), "bytesAvailable": len(body.encode()),
                          "truncated": bool(sent) and sent != body, "withheld": not bool(sent),
                          "reason": "prompt_budget" if sent != body else None})
    return selected, fragments


def prepare_writer(state, provider_class, writer_route, *, destinations=None, content_type_id=None,
                   voice_mode="personalized", max_bytes=None, voice_context=None):
    """Single projection/assembly/receipt for a concrete request; call before any writer I/O.

    Neutral overrides retain mandatory identity/boundaries but remove every voice preference.
    A cloud memory grant never substitutes for an exact per-source generation grant.
    """
    shared = projection(state, provider_class, destinations, content_type_id, voice_route=writer_route if voice_mode == "personalized" else None)
    candidates = shared["files"]
    if voice_mode != "personalized":
        candidates = [f for f in candidates if f["name"] != "VOICE.md"]
    files, fragments = assemble(candidates, max_bytes)
    names = [f["name"] for f in files]
    revision = active_profile(state)
    profile = (revision or {}).get("profile") or {}
    voice_body = next((f["body"] for f in files if f["name"] == "VOICE.md"), "")
    # A surviving file header is not evidence that approved style reached the writer.
    # The separate adapter tone must not restore voice omitted by the byte budget.
    tone_line = f"Tone: {profile.get('tone') or '(not set)'}"
    has_approved = bool(revision and not revision.get("stale") and profile.get("status") != "stale"
                        and tone_line in voice_body.splitlines())
    effective = "neutral" if voice_mode != "personalized" else "approved" if has_approved else "override" if (voice_context or {}).get("bindings") else "not_supplied"
    # A scoped learning binding is not proof it survived VOICE.md omission or byte truncation.
    learned = shared["learned"]
    available = {item["id"]: item for item in learning.active_items(state)}
    actual_ids = [key for key in learned["used"] if key in available and learning._line(available[key]) in voice_body]
    omitted = list(dict.fromkeys(learned["omitted"] + [key for key in learned["used"] if key not in actual_ids]))
    shared["learned"] = {**learned, "used": actual_ids, "statements": [available[key]["statement"] for key in actual_ids], "omitted": omitted}
    shared["files"] = files
    # Which voice traits and Genome lessons reached the writer, by id: a line counts only when it was sent whole.
    from .growth.service import current_genome
    sent = _section_lines(voice_body, "Observations")
    plain, scoped = voice_items(profile, destinations, state)
    lines = {id(trait): line for trait, line in scoped}
    traits_included = list(dict.fromkeys(
        trait["id"] for trait in profile.get("dimensions") or [] if isinstance(trait, dict) and isinstance(trait.get("id"), str) and isinstance(trait.get("observation"), str)
        and (lines.get(id(trait)) if trait_scope(trait) else f"- {trait['observation']}" if applies_everywhere(trait) and trait["observation"] in plain else None) in sent))
    lessons_sent = _section_lines(voice_body, "Approved Creator Genome")
    genome_included = [item.get("id") for item in genome_lines(current_genome(state), destinations) if f"- {item['text']}" in lessons_sent]
    source_ids = set(profile.get("evidenceSourceIds") or []) | {b.get("id") for b in (voice_context or {}).get("bindings", [])}
    source_ids.update(item.get("id") for item in ((state.get("brandHub") or {}).get("genome") or {}).get("evidenceBindings", []))
    source_grants = [{"id": s.get("id"), "hash": s.get("hash"), "active": s.get("active"),
                      "useGrants": s.get("useGrants"), "purposeGrants": s.get("purposeGrants"), "routeGrants": s.get("routeGrants"),
                      "selected": s.get("selected"), "revision": s.get("revision"), "contentHash": s.get("contentHash"), "grantRevision": s.get("grantRevision")}
                     for s in state.get("sources", []) if s.get("id") in source_ids]
    raw_files = {f["name"]: f["body"] for f in render_files(state)}
    withheld = [{"name": name, "reason": "cloud_memory_denied" if not shared["shared"] else "neutral_override" if name == "VOICE.md" and voice_mode != "personalized" else "prompt_budget"}
                for name in PROMPT_FILES if name not in names]
    receipt = {"renderVersion": RENDER_VERSION, "activeVoiceRevision": (state.get("speaker") or {}).get("activeRevision"),
               "effectiveVoiceMode": effective, "writerRoute": writer_route, "providerClass": provider_class,
               "cloudMemoryAllowed": egress(state).get("cloud") is True, "filesIncluded": names,
               "filesWithheld": withheld, "fragments": fragments, "withheldBoundaries": shared["withheldBoundaries"],
               "withheldFragments": ([{"kind": "approved_voice", "reason": "prompt_budget" if any(f["name"] == "VOICE.md" and (f["truncated"] or f["withheld"]) for f in fragments) else "source_route_or_stale"}] if revision and voice_mode == "personalized" and shared["shared"] and not has_approved else [])
                    + ([{"kind": "boundaries", "reason": "privacy", "count": shared["withheldBoundaries"]}] if shared["withheldBoundaries"] else []),
               "preferenceSetDigest": fingerprint(learning.active_items(state)), "preferenceSetRevision": learning.revision(state),
               "preferencesIncludedDigest": fingerprint([available[key] for key in actual_ids]),
               "traitsIncluded": traits_included, "genomeIncluded": genome_included,
               "identityContextRevision": fingerprint(raw_files["IDENTITY.md"]),
               "boundaryPolicyRevision": fingerprint(boundary_fields(state)),
               "sourceGrantDigest": fingerprint(source_grants), "voiceContextDigest": fingerprint(voice_context or {}), "memoryContextDigest": fingerprint(files),
               "policyDigest": fingerprint({"egress": egress(state), "sources": source_grants}),
               "destinations": destinations, "contentTypeId": content_type_id, "requestedVoiceMode": voice_mode,
               "maxBytes": max_bytes}
    return shared, receipt


def validate_receipt(state, receipt, voice_context=None):
    """Reject a run/apply when consent, approved memory, or source grants changed since dispatch."""
    if not receipt:  # Existing historical runs retain their original compatibility behavior.
        return
    _, current = prepare_writer(state, receipt["providerClass"], receipt["writerRoute"],
                                destinations=receipt.get("destinations"), content_type_id=receipt.get("contentTypeId"),
                                voice_mode=receipt["requestedVoiceMode"], max_bytes=receipt.get("maxBytes"), voice_context=voice_context)
    keys = ("memoryContextDigest", "policyDigest", "activeVoiceRevision", "preferenceSetDigest", "identityContextRevision", "boundaryPolicyRevision")
    if any(current[key] != receipt[key] for key in keys):
        raise AlphaError("Brand Brain memory or permissions changed while writing. Review the current voice and draft again.", 409)


def diagnostic_projection(state, provider_class, *, owner=False, voice_route=None):
    """The normal route projection with private boundaries redacted for non-owner viewers.

    Viewer redaction must never bypass source-specific grants or restore raw source examples.
    """
    shared = projection(state, provider_class, voice_route=voice_route)
    if not owner:
        safe_boundary = next(f for f in prompt_fragments(state, shareable=CLOUD_SHAREABLE) if f["name"] == "BOUNDARIES.md")
        shared["files"] = [safe_boundary if f["name"] == "BOUNDARIES.md" else f for f in shared["files"]]
        shared["restrictedViewer"] = True
    return shared
