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


def render_files(state, shareable=None, destinations=None, content_type_id=None):
    """Return five derived files as {name, purpose, source, body, editHref}. Owner/local views may include private boundaries.
    With `shareable`, BOUNDARIES.md keeps only boundaries whose privacy is listed and says how many it left out.
    With `destinations`, VOICE.md carries only the learned preferences that apply to them (a prompt slice)."""
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
        voice = "\n".join([
            "# Voice", "",
            f"Revision {revision.get('revision')} · approved {_when(revision.get('approvedAt'))} · {revision.get('reason', '')}".rstrip(" ·"), "",
            f"Tone: {profile.get('tone') or '(not set)'}", "",
            "## Observations", "How to handle what you supply. A trait is never a reason to add a detail, habit or admission you did not supply.",
            *([f"- {item}" for item in profile.get("observations") or []] or ["- (none recorded)"]), "",
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

    # Approved Genome extends the current voice file; stale/deleted/revoked evidence is excluded.
    from .growth.service import current_genome
    approved_genome=current_genome(state)
    if approved_genome:
        lines=[s['text'] for s in approved_genome.get('statements',[]) if s.get('grade')=='supported'][:12]
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
