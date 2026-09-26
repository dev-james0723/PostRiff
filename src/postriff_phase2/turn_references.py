"""Chips on a drafting message: parse, check against the workspace, and report what was used (chat-context SPEC §5.2, §6).

Everything here is deterministic and reads `state` with `.get`, so a state without `phase2`, `contentSystem` or
`brief` works. Client labels are accepted for the request digest and dropped at `parse`: no output of this module
carries one. Labels in outputs come from `label_for`, and every unused item carries a message from `REASONS`.
"""
from __future__ import annotations

import copy
import re

from postriff_alpha.domain import AlphaError

from . import asset_kinds, fencing, media_consent
from .site_agent.routes import ID_VALUE
from .source_policy import EXCLUSION_REASONS, exclusion_message, project_context

MAX_REFERENCES = 12
MAX_ATTACHMENTS = 4
MAX_POSTS = 3
MAX_SOURCES = 20
LABEL_MAX = 80
MAX_TEXT = 6000          # all material sections together (ideas.MAX_TEXT)
INSPIRE_MAX = 2000
NOTE_MAX_CHARS = 1200
BUDGET_BYTES = 58_000
DERIVED_DEPTH = 5

KINDS = ("post", "account", "folder", "template", "source", "skill", "connector_item")
RESERVED_KINDS = ()
POST_ROLES = ("rework", "inspire")
MEDIA_ROLES = ("post", "reference")
SLOTS = ("A", "B", "C", "D")
ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
REFERENCE_KEYS = frozenset({"kind", "id", "label", "role"})
ATTACHMENT_KEYS = frozenset({"assetId", "role", "slot"})
INVALID = "Invalid draft request."
UNKNOWN_LABEL = "An item that isn't in this workspace"
HANDED_IN_LABEL = "Handed-in text"

REWORK_CUES = re.compile(r"(改寫|改写|修改|縮短|缩短|精簡|精简|潤飾|润饰|翻譯|翻译|改|\b(?:rewrite|rework|shorten|tighten|trim|edit|fix|polish|translate|adapt|update|revise|condense)\b)", re.IGNORECASE)

REASONS = {
    "not_in_workspace": "It isn't in this workspace.",
    "duplicate": "It was added twice, so it was used once.",
    "not_available_yet": "Rafii can't use this kind of item yet.",
    "skill_unavailable": "This skill isn't available right now.",
    "connector_unavailable": "This connected item isn't available to you anymore.",
    "connector_disabled": "This connector is turned off right now.",
    "connector_consent_required": "The workspace owner hasn't allowed connected text to reach a cloud writer.",
    "connector_fetch_failed": "The connected item couldn't be read securely. Reconnect it or choose it again.",
    "image_generation_turn": "Attachments aren't used when generating an image.",
    "no_room": "There wasn't room for it in this draft.",
    "free_writer": "The free preview writer doesn't use this. Choose another writer to use it.",
    "post_rejected": "This post was rejected in review.",
    "post_blocked": "A source this post came from was withdrawn or blocked.",
    "post_source_excluded": "A source this post came from can't be used here: {detail}.",
    "too_many_posts": "Only 3 posts can be used in one message.",
    "too_many_sources": "Too many sources for one draft (20 at most).",
    "account_disconnected": "This account is disconnected.",
    "platform_unsupported": "Rafii can't write for this platform yet.",
    "folder_empty": "This folder has no connected accounts.",
    "template_unavailable": "This template is no longer available.",
    "only_one_template": "Only one template is used per message.",
    "source_unavailable": "This source was withdrawn or can't be used for drafts.",
    "voice_sample": "Writing samples shape the voice; they aren't used as sources.",
    "no_approved_facts": "None of its facts are approved yet.",
    "media_not_ready": "This upload isn't finished.",
    "consent_required": "The workspace owner hasn't allowed Rafii to look at photos and videos.",
    "reader_unavailable": "Photo reading isn't available here.",
    "not_read_yet": "Rafii hadn't read it yet, so it was left out this time.",
    "read_failed": "Rafii couldn't read it. Try again from the attachment.",
    "no_frames": "Rafii has no frames from this video to look at.",
    "not_a_drafting_turn": "Attachments are used when Rafii writes a draft. This answer didn't use them.",
}

REMINDERS = {
    "material_clipped": "The post was shortened to fit.",
    "rework_extra": "Only one post can be reworked at a time; the others were used for ideas.",
    "template_fallback": "This template's content type is no longer available, so this draft uses general writing.",
    "routing_forced_draft": "This message has attachments, so Rafii wrote a draft. To set up a repeating task or change memory, send it without attachments.",
    "video_not_schedulable": "Video posts can't be scheduled from Rafii yet.",
    # One wording for a missing, foreign or otherwise invalid handed-in item: it never says whether it exists elsewhere.
    "material_unavailable": "This item is unavailable in this workspace.",
}

# Rafii's zh-Hant voice (site_agent.compose) for reminders added by this module; the web renders server messages verbatim.
LOCALIZED_REMINDERS = {"zh-Hant": {"material_unavailable": "呢個項目喺呢個工作區用唔到。"}}


class _Pricing:
    """`notes=PRICING`: every eligible reference is priced as a full-length note (SPEC §6.1)."""
    def __repr__(self):
        return "PRICING"


PRICING = _Pricing()


def message(reason):
    if reason in REASONS and reason != "post_source_excluded":
        return REASONS[reason]
    return exclusion_message(reason)


# --- labels ---------------------------------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_TRAILING_JOINERS = "‍︎️"


def _clip(value, limit):
    text = _SPACES.sub(" ", value if isinstance(value, str) else "").strip()
    text = "".join(ch for ch in text if not 0xD800 <= ord(ch) <= 0xDFFF)[:limit]   # code points; never a lone surrogate
    return text.rstrip(_TRAILING_JOINERS).rstrip()


def label_for(kind, record, slot=None):
    record = record if isinstance(record, dict) else {}
    if kind == "post":
        text = record.get("text") if isinstance(record.get("text"), str) else ""
        first = next((line for line in text.splitlines() if line.strip()), "")
        return _clip(first, 24) or f"{record.get('platform') or 'Social'} draft"
    if kind == "account":
        account = _clip(record.get("account"), 40)
        return _clip(f"{record.get('platform') or 'Account'} · {account}" if account else record.get("platform") or "Account", 40)
    if kind in ("image", "video"):
        return f"{'Video' if kind == 'video' else 'Photo'} {slot or 'A'}"
    fallback = {"template": "Template", "source": "Source", "folder": "Folder", "campaign": "Campaign", "skill": "Skill", "connector_item": "Connected item"}.get(kind, "Item")
    return _clip(record.get("title") if kind == "source" else record.get("name"), 40) or fallback


# --- shape ----------------------------------------------------------------------------------------

def parse(payload):
    """Strict shape check (SPEC §5.2). Returns {"references": [...], "attachments": [...]}, labels dropped."""
    payload = payload if isinstance(payload, dict) else {}
    raw_refs = payload.get("references")
    raw_atts = payload.get("attachments")
    raw_refs = [] if raw_refs is None else raw_refs
    raw_atts = [] if raw_atts is None else raw_atts
    if not isinstance(raw_refs, list) or len(raw_refs) > MAX_REFERENCES or not isinstance(raw_atts, list) or len(raw_atts) > MAX_ATTACHMENTS:
        raise AlphaError(INVALID)
    references = []
    for item in raw_refs:
        if not isinstance(item, dict) or not set(item) <= REFERENCE_KEYS or item.get("kind") not in KINDS:
            raise AlphaError(INVALID)
        if not isinstance(item.get("id"), str) or not ID_VALUE.match(item["id"]):
            raise AlphaError(INVALID)
        if "label" in item and (not isinstance(item["label"], str) or len(item["label"]) > LABEL_MAX):
            raise AlphaError(INVALID)
        role = item.get("role")
        if "role" in item and (item["kind"] != "post" or role not in POST_ROLES):
            raise AlphaError(INVALID)
        references.append({"kind": item["kind"], "id": item["id"], **({"role": role} if role else {})})
    attachments, taken = [], set()
    for item in raw_atts:
        if not isinstance(item, dict) or not set(item) <= ATTACHMENT_KEYS:
            raise AlphaError(INVALID)
        if not isinstance(item.get("assetId"), str) or not ASSET_ID.match(item["assetId"]) or item.get("role") not in MEDIA_ROLES:
            raise AlphaError(INVALID)
        if "slot" in item:
            if item["slot"] not in SLOTS or item["slot"] in taken:
                raise AlphaError(INVALID)
            taken.add(item["slot"])
        attachments.append({"assetId": item["assetId"], "role": item["role"], "slot": item.get("slot")})
    free = [slot for slot in SLOTS if slot not in taken]
    for item in attachments:
        if item["slot"] is None:
            item["slot"] = free.pop(0)
    return {"references": references, "attachments": attachments}


def present(refs):
    return bool(refs and (refs.get("references") or refs.get("attachments")))


# --- lookups --------------------------------------------------------------------------------------

def _phase2(state):
    return state.get("phase2") if isinstance(state.get("phase2"), dict) else {}


def _find(items, item_id):
    return next((item for item in items or [] if isinstance(item, dict) and item.get("id") == item_id), None)


def _variant(state, variant_id):
    return _find(state.get("variants"), variant_id)


def _live_campaign(state, campaign_id):
    planning = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    found = _find(planning.get("campaigns"), campaign_id)
    return found if found and found.get("status") != "cancelled" else None


def _unused(kind, item_id, label, reason, **extra):
    return {"kind": kind, "id": item_id, "label": label, "reason": reason, "message": message(reason), **extra}


def _post_block(variant):
    if variant.get("rejected"):
        return "post_rejected"
    if variant.get("blockedByRetraction") or variant.get("policyBlocked"):
        return "post_blocked"
    return None


# --- early: what must be known before understanding and destinations ---------------------------------

def early(state, refs, text, payload, *, platforms=()):
    """Validate `materialRef`, choose the single rework post and compute account/folder destinations (SPEC §6.1 step 4).

    `platforms` is the writer route's `supported_platforms()`; empty means no filtering (agent_runtime convention)."""
    state = state if isinstance(state, dict) else {}
    refs = refs or {"references": [], "attachments": []}
    payload = payload if isinstance(payload, dict) else {}
    used, unused, reminders = [], [], []
    material_ref, rework = None, None
    raw_ref = payload.get("materialRef") if isinstance(payload.get("materialRef"), dict) else None
    if raw_ref:
        kind, ref_id = raw_ref.get("type"), raw_ref.get("id")
        if kind == "draft" and isinstance(ref_id, str) and _variant(state, ref_id):
            material_ref = {"type": "draft", "id": ref_id, "title": label_for("post", _variant(state, ref_id))}
            rework = ref_id
        elif kind == "campaign" and isinstance(ref_id, str) and _live_campaign(state, ref_id):
            material_ref = {"type": "campaign", "id": ref_id, "title": label_for("campaign", _live_campaign(state, ref_id))}
        else:
            reminders.append(REMINDERS["material_unavailable"])
    handed_in = isinstance(payload.get("material"), str) and bool(payload["material"].strip())

    seen, posts = set(), []
    for ref in refs.get("references", []):
        key = (ref["kind"], ref["id"])
        record = _record(state, ref)
        label = _label(ref["kind"], record)
        if key in seen or (ref["kind"] == "post" and material_ref and material_ref["type"] == "draft" and ref["id"] == material_ref["id"]):
            unused.append(_unused(ref["kind"], ref["id"], label, "duplicate"))
            continue
        seen.add(key)
        if ref["kind"] == "post":
            if len(posts) >= MAX_POSTS:
                unused.append(_unused("post", ref["id"], label, "too_many_posts"))
            else:
                posts.append(ref)

    roles = {}
    if material_ref or handed_in:
        # A server caller's handed-in material keeps the rework slot; post chips become ideas (SPEC §5.2).
        roles = {ref["id"]: "inspire" for ref in posts}
    else:
        eligible = [ref for ref in posts if (v := _variant(state, ref["id"])) and not _post_block(v)]
        explicit = [ref for ref in eligible if ref.get("role") == "rework"]
        if explicit:
            rework = explicit[0]["id"]
            if len(explicit) > 1:
                reminders.append(REMINDERS["rework_extra"])
        elif len(posts) == 1 and eligible and "role" not in posts[0] and REWORK_CUES.search(text or ""):
            rework = posts[0]["id"]
        roles = {ref["id"]: "rework" if ref["id"] == rework else "inspire" for ref in posts}

    destinations = []
    channels = [c for c in _phase2(state).get("channels") or [] if isinstance(c, dict)]
    folders = [f for f in _phase2(state).get("channelFolders") or [] if isinstance(f, dict)]
    for ref in refs.get("references", []):
        if ref["kind"] not in ("account", "folder") or any(u["kind"] == ref["kind"] and u["id"] == ref["id"] and u["reason"] == "duplicate" for u in unused):
            continue
        if ref["kind"] == "account":
            channel = _find(channels, ref["id"])
            reason = _account_reason(channel, platforms)
            if reason:
                unused.append(_unused("account", ref["id"], label_for("account", channel) if channel else UNKNOWN_LABEL, reason))
                continue
            destinations.append({"platform": channel["platform"], "channelId": channel["id"]})
            used.append({"kind": "account", "id": ref["id"], "label": label_for("account", channel), "as": "destination"})
            continue
        folder = _find(folders, ref["id"])
        if not folder:
            unused.append(_unused("folder", ref["id"], UNKNOWN_LABEL, "not_in_workspace"))
            continue
        members = [_find(channels, account_id) for account_id in folder.get("accountIds") or []]
        members = [c for c in members if not _account_reason(c, platforms)]
        if not members:
            unused.append(_unused("folder", ref["id"], label_for("folder", folder), "folder_empty"))
            continue
        destinations += [{"platform": c["platform"], "channelId": c["id"]} for c in members]
        used.append({"kind": "folder", "id": ref["id"], "label": label_for("folder", folder), "as": "destination"})
    return {"materialRef": material_ref, "rework": rework, "posts": [ref["id"] for ref in posts], "roles": roles,
            "destinations": merge_destinations([], destinations), "report": {"used": used, "unused": unused, "reminders": reminders}}


def _account_reason(channel, platforms):
    if not channel or channel.get("revoked"):
        return "account_disconnected"
    if platforms and channel.get("platform") not in platforms:
        return "platform_unsupported"
    return None


def _record(state, ref):
    kind, item_id = ref["kind"], ref["id"]
    if kind == "post":
        return _variant(state, item_id)
    if kind == "source":
        return _find(state.get("sources"), item_id)
    if kind == "template":
        return _find((state.get("contentSystem") or {}).get("templates"), item_id)
    if kind == "account":
        return _find(_phase2(state).get("channels"), item_id)
    if kind == "folder":
        return _find(_phase2(state).get("channelFolders"), item_id)
    if kind == "skill":
        return _find(state.get("turnSkills"), item_id)
    if kind == "connector_item":
        return _find(state.get("turnConnectorItems"), item_id)
    return None


def _label(kind, record):
    return label_for(kind, record) if record else UNKNOWN_LABEL


def merge_destinations(payload_destinations, extra):
    """Chip destinations join the payload's, de-duplicated by (platform, channelId); with no payload destinations
    they replace the defaults (SPEC §6.1 step 7). Shared by turn, quick_start and estimate_request."""
    merged, seen = [], set()
    for destination in list(payload_destinations or []) + list(extra or []):
        if not isinstance(destination, dict):
            continue
        key = (destination.get("platform"), destination.get("channelId") or None)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(destination))
    return merged


def unused_all(state, refs, reason):
    """Every chip on the message reported unused for one reason (an image-generation turn, SPEC §6.10)."""
    state = state if isinstance(state, dict) else {}
    refs = refs or {"references": [], "attachments": []}
    unused = [_unused(ref["kind"], ref["id"], _label(ref["kind"], _record(state, ref)), reason) for ref in refs.get("references", [])]
    assets = _phase2(state).get("assets") or []
    for attachment in refs.get("attachments", []):
        asset = _find(assets, attachment["assetId"])
        live = asset and not asset.get("deleted") and not asset.get("deletionPending")
        kind = (asset_kinds.kind_of(asset) if live else None) or "image"
        label = label_for(kind, asset, attachment["slot"]) if live else UNKNOWN_LABEL
        unused.append(_unused(kind, attachment["assetId"], label, reason, role=attachment["role"]))
    return {"used": [], "unused": unused, "reminders": []}


def resolved_ids(state, refs):
    """Chips that name something in this workspace, as `{kind, id, role?}` (no labels): what a model may be told about."""
    state = state if isinstance(state, dict) else {}
    refs = refs or {"references": [], "attachments": []}
    out = [{"kind": ref["kind"], "id": ref["id"], **({"role": ref["role"]} if ref.get("role") else {})}
           for ref in refs.get("references", []) if _record(state, ref) is not None]
    assets = _phase2(state).get("assets") or []
    for item in refs.get("attachments", []):
        asset = _find(assets, item["assetId"])
        if asset and asset_kinds.is_ready(asset):
            out.append({"kind": asset_kinds.kind_of(asset), "id": asset["id"], "role": item["role"]})
    return out


def sent_ids(refs, report):
    """What the user message records (SPEC §5.10): the parsed ids and roles, without labels, leaving out ids that
    aren't in this workspace (they are named only in the report, as "An item that isn't in this workspace")."""
    missing = {(u["kind"], u["id"]) for u in (report or {}).get("unused", []) if u.get("reason") == "not_in_workspace"}
    missing_assets = {u["id"] for u in (report or {}).get("unused", []) if u.get("reason") == "not_in_workspace" and u["kind"] in ("image", "video")}
    references = [dict(ref) for ref in (refs or {}).get("references", []) if (ref["kind"], ref["id"]) not in missing]
    attachments = [dict(item) for item in (refs or {}).get("attachments", []) if item["assetId"] not in missing_assets]
    return {**({"references": references} if references else {}), **({"attachments": attachments} if attachments else {})}


# --- resolve: the full projection of chips for one route --------------------------------------------

def _provenance(state, variant, run_sources):
    """Source ids behind a post: its own, its runs' bindings, and the same for what it was derived from (depth ≤ 5)."""
    ids, run_ids, current, depth, visited = [], [], variant, 0, set()
    while current and depth <= DERIVED_DEPTH and current.get("id") not in visited:
        visited.add(current.get("id"))
        ids += [i for i in current.get("sourceIds") or [] if isinstance(i, str)]
        provenance = current.get("provenance") if isinstance(current.get("provenance"), dict) else {}
        proposed = current.get("proposedUpdate") if isinstance(current.get("proposedUpdate"), dict) else {}
        ids += [i for i in proposed.get("sourceIds") or [] if isinstance(i, str)]
        run_ids += [r for r in [provenance.get("runId"), *(current.get("runRefs") or []), proposed.get("runId")] if isinstance(r, str) and r]
        parent = provenance.get("derivedFrom")
        current = _variant(state, parent) if isinstance(parent, str) else None
        depth += 1
    bound = (run_sources(list(dict.fromkeys(run_ids))) if run_sources and run_ids else {}) or {}
    for run_id in dict.fromkeys(run_ids):
        ids += [i for i in bound.get(run_id) or [] if isinstance(i, str)]
    voice = {s.get("id") for s in state.get("sources") or [] if isinstance(s, dict) and s.get("kind") == "voice_sample"}
    return [i for i in dict.fromkeys(ids) if i not in voice]


def _provenance_exclusion(state, ids, provider_class):
    known = {s.get("id") for s in state.get("sources") or [] if isinstance(s, dict)}
    if any(i not in known for i in ids):
        return "retracted"
    if not ids:
        return None
    context = project_context(state, "draft", provider_class, ids)
    return next((e["reason"] for e in context["excluded"] if e["reason"] != "no_approved_facts"), None)


def _template_choice(state, template_id, actor):
    from . import content_types   # local import: content_types is heavy and only templates need it
    system = state.get("contentSystem") or {}
    template = _find(system.get("templates"), template_id)
    try:
        if template:
            if template.get("archived") or not (template.get("ownerUserId") == actor or template.get("visibility") == "workspace"):
                return template, None
            item = content_types.definition(state, template.get("contentTypeId"), template.get("contentTypeVersion"))
            format_id = (template.get("overrides") or {}).get("formatId") or (system.get("selection") or {}).get("formatId")
        else:
            item = content_types.definition(state, template_id)   # a catalog content type id is accepted too
            format_id = (system.get("selection") or {}).get("formatId")
    except (AlphaError, KeyError, TypeError):
        return template, None
    choice = {"contentTypeId": item["id"], "contentTypeVersion": item["version"], "formatId": format_id, "contentSkillRouteIds": list(item.get("skillRouteIds") or [])}
    return template or {"name": item.get("label")}, choice


def resolve(state, refs, *, actor, provider_class, route_kind, text="", payload_material=None, material_ref=None,
            notes=None, run_sources=None, source_ids=(), platforms=(), skills=(), connector_items=None):
    """Everything chips add to one writer request, plus the "Used this time" report (SPEC §6).

    route_kind "fixture" is the free preview writer; `notes` maps assetId → {status, processor, text, hash} for the
    asset's current hash, `None` when no reader is configured, or PRICING. `source_ids` are the payload/default ids."""
    state = state if isinstance(state, dict) else {}
    refs = refs or {"references": [], "attachments": []}
    fixture = route_kind == "fixture"
    ahead = early(state, refs, text, {"materialRef": material_ref, "material": payload_material}, platforms=platforms)
    used, unused = list(ahead["report"]["used"]), list(ahead["report"]["unused"])
    reminders = list(ahead["report"]["reminders"])
    skip = {(u["kind"], u["id"]) for u in unused}
    handled = {(u["kind"], u["id"]) for u in used}

    # Skills are validated from Registry.defaults()/SkillLibrary by the server caller. They
    # alter this turn's binder only and are never written into workspace preferences.
    skill_by_id = {item.get("id"): item for item in skills or () if isinstance(item, dict) and item.get("id")}
    skill_ids = []
    for ref in refs.get("references", []):
        if ref["kind"] != "skill" or ("skill", ref["id"]) in handled:
            continue
        handled.add(("skill", ref["id"]))
        item = skill_by_id.get(ref["id"])
        if item is None:
            unused.append(_unused("skill", ref["id"], UNKNOWN_LABEL, "skill_unavailable"))
            continue
        label = label_for("skill", item)
        skill_ids.append(ref["id"])
        used.append({"kind": "skill", "id": ref["id"], "label": label, "as": "skill"})

    # Connector records are produced only by the authenticated server-side provider fetch.
    # Their source ids enter project_context below, so source policy/egress/candidate fencing
    # stays exactly the same as every other document source.
    connector_items = connector_items if isinstance(connector_items, dict) else {}
    connector_source_ids = []
    for ref in refs.get("references", []):
        if ref["kind"] != "connector_item" or ("connector_item", ref["id"]) in handled:
            continue
        handled.add(("connector_item", ref["id"]))
        item = connector_items.get(ref["id"])
        if not isinstance(item, dict) or item.get("reason"):
            reason = (item or {}).get("reason") or "connector_unavailable"
            unused.append(_unused("connector_item", ref["id"], (item or {}).get("label") or UNKNOWN_LABEL, reason))
            continue
        connector_source_ids.append(item["source"]["id"])

    # Explicit sources first, so a picked source is never the one cut at 20 (SPEC §6.5).
    chip_sources = []
    for ref in refs.get("references", []):
        if ref["kind"] != "source" or (ref["kind"], ref["id"]) in skip | handled:
            continue
        handled.add(("source", ref["id"]))
        source = _find(state.get("sources"), ref["id"])
        if not source:
            unused.append(_unused("source", ref["id"], UNKNOWN_LABEL, "not_in_workspace"))
        elif source.get("kind") == "voice_sample":
            unused.append(_unused("source", ref["id"], label_for("source", source), "voice_sample"))
        elif not source.get("active") or source.get("sourcePolicy") == "prohibited":
            unused.append(_unused("source", ref["id"], label_for("source", source), "source_unavailable"))
        else:
            chip_sources.append(ref["id"])

    # Posts: lookup, block, provenance for this route, then their share of the 6,000-character material budget.
    material, material_items, owners, derived = [], [], {}, []
    ordered = list(chip_sources) + connector_source_ids
    handed_in = payload_material if isinstance(payload_material, str) and payload_material.strip() else None
    if ahead["materialRef"] and ahead["materialRef"]["type"] == "draft":
        variant = _variant(state, ahead["materialRef"]["id"])
        ids = _provenance(state, variant, run_sources)
        reason = _post_block(variant) or ("too_many_sources" if len(ordered) + len([i for i in ids if i not in ordered]) > MAX_SOURCES else None)
        detail = None if reason else _provenance_exclusion(state, ids, provider_class)
        if reason or detail:
            unused.append(_unused("post", variant["id"], label_for("post", variant), reason or "post_source_excluded", **({"message": REASONS["post_source_excluded"].format(detail=EXCLUSION_REASONS.get(detail, detail.replace("_", " ")))} if detail and not reason else {})))
            handed_in = None
        else:
            owners.update({i: ("post", variant["id"]) for i in ids if i not in ordered})
            ordered += [i for i in ids if i not in ordered]
            derived += ids
    if handed_in is not None:
        body = handed_in
        if len(body) > MAX_TEXT:
            body = body[:MAX_TEXT]
            reminders.append(REMINDERS["material_clipped"])
        label = ahead["materialRef"]["title"] if ahead["materialRef"] else HANDED_IN_LABEL
        material.append({"role": "rework" if ahead["materialRef"] and ahead["materialRef"]["type"] == "draft" else "handed_in", "label": label, "text": fencing.neutralize(body)})
        material_items.append(("post", ahead["materialRef"]["id"]) if ahead["materialRef"] and ahead["materialRef"]["type"] == "draft" else None)
    rework_ref = None
    for post_id in ahead["posts"]:
        variant = _variant(state, post_id)
        if not variant:
            unused.append(_unused("post", post_id, UNKNOWN_LABEL, "not_in_workspace"))
            continue
        label = label_for("post", variant)
        role = ahead["roles"].get(post_id, "inspire")
        block = _post_block(variant)
        if block:
            unused.append(_unused("post", post_id, label, block))
            continue
        ids = _provenance(state, variant, run_sources)
        fresh = [i for i in ids if i not in ordered]
        if len(ordered) + len(fresh) > MAX_SOURCES:
            unused.append(_unused("post", post_id, label, "too_many_sources"))
            continue
        detail = _provenance_exclusion(state, ids, provider_class)
        if detail:
            unused.append(_unused("post", post_id, label, "post_source_excluded", message=REASONS["post_source_excluded"].format(detail=EXCLUSION_REASONS.get(detail, detail.replace("_", " ")))))
            continue
        body = variant.get("text") if isinstance(variant.get("text"), str) else ""
        room = MAX_TEXT - sum(len(s["text"]) for s in material)
        if role == "rework":
            if len(body) > room:
                body = body[:room]
                reminders.append(REMINDERS["material_clipped"])
            rework_ref = post_id
        else:
            if fixture:
                unused.append(_unused("post", post_id, label, "free_writer"))
                continue
            if room <= 0:
                unused.append(_unused("post", post_id, label, "no_room"))
                continue
            body = body[:min(INSPIRE_MAX, room)]
        section = {"role": role, "label": label, "platform": variant.get("platform"), "language": variant.get("language"), "text": fencing.neutralize(body)}
        if role == "rework":
            material.insert(0, section)
            material_items.insert(0, ("post", post_id))
        else:
            material.append(section)
            material_items.append(("post", post_id))
        owners.update({i: ("post", post_id) for i in fresh})
        ordered += fresh
        derived += ids
        used.append({"kind": "post", "id": post_id, "label": label, "as": role})
    if ahead["materialRef"] and ahead["materialRef"]["type"] == "draft" and handed_in is not None:
        variant = _variant(state, ahead["materialRef"]["id"])
        used.append({"kind": "post", "id": variant["id"], "label": label_for("post", variant), "as": "rework"})

    # Sources: explicit chips must pass the route's policy; payload/default ids fill what is left of the 20.
    base = [i for i in source_ids or [] if isinstance(i, str) and i not in ordered]
    final = ordered + base[:max(0, MAX_SOURCES - len(ordered))]
    context = project_context(state, "draft", provider_class, final) if final else {"excluded": []}
    excluded = {e["id"]: e["reason"] for e in context["excluded"]}
    for source_id in chip_sources:
        source = _find(state.get("sources"), source_id)
        if source_id in excluded:
            unused.append(_unused("source", source_id, label_for("source", source), excluded[source_id]))
        else:
            used.append({"kind": "source", "id": source_id, "label": label_for("source", source), "as": "source"})
    connector_by_source = {item["source"]["id"]: (ref_id, item) for ref_id, item in connector_items.items()
                           if isinstance(item, dict) and isinstance(item.get("source"), dict)}
    for source_id in connector_source_ids:
        ref_id, item = connector_by_source[source_id]
        if source_id in excluded:
            reason = "connector_consent_required" if excluded[source_id] == "egress_consent_required" else excluded[source_id]
            unused.append(_unused("connector_item", ref_id, item["label"], reason))
        else:
            used.append({"kind": "connector_item", "id": ref_id, "label": item["label"], "as": "source"})
    chip_source_ids = [i for i in chip_sources if i not in excluded] + [i for i in ordered if i in owners]

    # Template: the first usable one counts; the report never claims overrides it doesn't apply (SPEC §6.4).
    content_type = None
    for ref in refs.get("references", []):
        if ref["kind"] != "template" or (ref["kind"], ref["id"]) in skip or ("template", ref["id"]) in handled:
            continue
        handled.add(("template", ref["id"]))
        record, choice = _template_choice(state, ref["id"], actor)
        label = label_for("template", record) if record else UNKNOWN_LABEL
        if choice is None:
            unused.append(_unused("template", ref["id"], label, "template_unavailable" if record else "not_in_workspace"))
        elif content_type is not None:
            unused.append(_unused("template", ref["id"], label, "only_one_template"))
        else:
            content_type = choice
            used.append({"kind": "template", "id": ref["id"], "label": label, "as": "template"})

    # Attachments: post media is recorded, never written about; references read through consent-checked notes.
    media, reference_notes, note_items, seen_assets, video_seen = [], [], [], set(), False
    assets = _phase2(state).get("assets") or []
    for attachment in refs.get("attachments", []):
        asset_id, role, slot = attachment["assetId"], attachment["role"], attachment["slot"]
        asset = _find(assets, asset_id)
        kind = (asset_kinds.kind_of(asset) if asset else None) or "image"
        label = label_for(kind, asset, slot) if asset else UNKNOWN_LABEL
        extra = {"role": role}
        if asset_id in seen_assets or (asset and kind == "video" and video_seen):
            unused.append(_unused(kind, asset_id, label, "duplicate", **extra))
            continue
        seen_assets.add(asset_id)
        if not asset or asset.get("deleted") or asset.get("deletionPending"):
            unused.append(_unused(kind, asset_id, UNKNOWN_LABEL, "not_in_workspace", **extra))
            continue
        video_seen = video_seen or kind == "video"
        if not asset_kinds.is_ready(asset):
            unused.append(_unused(kind, asset_id, label, "media_not_ready", **extra))
            continue
        if role == "post":
            media.append({"assetId": asset_id, "kind": kind, "role": "post", "slot": slot})
            if kind == "video":
                reminders.append(REMINDERS["video_not_schedulable"])
            used.append({"kind": kind, "id": asset_id, "label": label, "role": role, "as": "post_media"})
            continue
        reason, note_text = _note_for(state, asset, kind, notes, fixture)
        if reason:
            unused.append(_unused(kind, asset_id, label, reason, **extra))
            continue
        reference_notes.append({"label": label, "kind": "video_frames" if kind == "video" else "photo", "text": fencing.neutralize(note_text[:NOTE_MAX_CHARS])})
        note_items.append((kind, asset_id))
        used.append({"kind": kind, "id": asset_id, "label": label, "role": role, "as": "notes"})

    reminders = list(dict.fromkeys(reminders))
    return {
        "material": material, "materialItems": material_items, "materialRef": ahead["materialRef"],
        "reworkOf": rework_ref or (ahead["materialRef"]["id"] if ahead["materialRef"] and ahead["materialRef"]["type"] == "draft" and handed_in is not None else None),
        "sourceIds": final, "chipSourceIds": chip_source_ids, "sourceOwners": owners, "derivedSourceIds": list(dict.fromkeys(derived)),
        "contentType": content_type, "skillIds": skill_ids, "connectorSourceIds": connector_source_ids,
        "media": media, "referenceNotes": reference_notes, "noteItems": note_items,
        "destinations": ahead["destinations"],
        "report": {"used": used, "unused": unused, "reminders": reminders},
    }


def _note_for(state, asset, kind, notes, fixture):
    """(reason, text) for a reference attachment; exactly one of them is set."""
    if fixture:
        return "free_writer", None
    if kind == "video" and not asset.get("frames"):
        return "no_frames", None
    if media_consent.decision(state).get("cloud") is not True:
        return "consent_required", None
    if notes is None:
        return "reader_unavailable", None
    if notes is PRICING:
        return None, "x" * NOTE_MAX_CHARS
    note = notes.get(asset["id"]) if isinstance(notes, dict) else None
    if not isinstance(note, dict) or (note.get("hash") and note.get("hash") != asset.get("hash")):
        return "not_read_yet", None
    if note.get("status") == "failed":
        return "read_failed", None
    if note.get("status") != "ready" or not isinstance(note.get("text"), str):
        return "not_read_yet", None
    if not media_consent.allowed(state, note.get("processor")):
        return "consent_required", None
    return None, note["text"]


# --- budget ---------------------------------------------------------------------------------------

def trim_to_budget(request, measure, limit=BUDGET_BYTES, *, resolved):
    """Trim chip-added text until `measure(request) <= limit` (SPEC §6.8): inspiration → notes → rework (clip) →
    chip-added sources, last in first out. Returns {"request", "report"}; runs only (pricing skips it)."""
    request = copy.deepcopy(request)
    report = copy.deepcopy(resolved["report"])
    material_items = list(resolved.get("materialItems") or [])
    note_items = list(resolved.get("noteItems") or [])

    def move(kind, item_id):
        for item in [u for u in report["used"] if u["kind"] == kind and u["id"] == item_id]:
            report["used"].remove(item)
            report["unused"].append({**{k: v for k, v in item.items() if k != "as"}, "reason": "no_room", "message": REASONS["no_room"]})

    def fits():
        return measure(request) <= limit

    def done():
        # An emptied (or never present) field is left out, exactly as `_project` leaves it out, so the run's request
        # has the same keys as the estimate's (SPEC §6.1 exact-request pricing).
        for key in ("material", "referenceNotes"):
            if not request.get(key):
                request.pop(key, None)
        return {"request": request, "report": report}

    material = request.setdefault("material", [])
    notes = request.setdefault("referenceNotes", [])
    for index in range(len(material) - 1, -1, -1):
        if fits():
            return done()
        if material[index]["role"] == "inspire":
            material.pop(index)
            item = material_items.pop(index)
            if item:
                move(*item)
    while notes and not fits():
        notes.pop()
        move(*note_items.pop())
    for section in material:
        if fits():
            break
        over = measure(request) - limit
        keep = max(0, len(section["text"]) - over)   # a character is at least one byte, so this always fits or empties
        section["text"] = section["text"][:keep]
        if REMINDERS["material_clipped"] not in report["reminders"]:
            report["reminders"].append(REMINDERS["material_clipped"])
    sources = (request.get("context") or {}).get("sources")
    owners = resolved.get("sourceOwners") or {}
    for source_id in reversed(resolved.get("chipSourceIds") or []):
        if fits() or not isinstance(sources, list):
            break
        owner = owners.get(source_id, ("source", source_id))
        dropped = [s for s in sources if s.get("id") == source_id or owners.get(s.get("id")) == owner]
        for source in dropped:
            sources.remove(source)
        move(*owner)
    return done()
