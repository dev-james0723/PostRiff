"""One creation-capability projection (Rafii Content Skills Integration, engineering spec §2–§5, §12).

The capability registry (`skills/rafii-registry.json`) and each channel skill's native-format table stay the
authorities; this module only projects them into what the composer, the writing routes and validation share:
one versioned row per mapped platform, its native formats, and independent operation states for drafting,
media, export, connection, publishing, analytics and learning. Nothing here publishes, connects or spends.

Rules this projection keeps:
- Drafting is not connecting and not publishing. A draft can target a platform without OAuth; publishing
  readiness still comes from `capabilities.publish_route` at execution time.
- Unknown evidence stays unknown. Code qualification (deterministic tests), model-route qualification (a
  permissioned paired benchmark) and production qualification (an authorized live check) are separate fields.
- The original five drafting platforms keep working unchanged. Every other platform is exposed only by a
  reversible rollout flag, so a failed load or a flag rollback never re-enables an unqualified platform.
- Native fields stay separate from public copy; private production notes never reach the text projection.
"""
from __future__ import annotations

import hashlib
import json
import re

from postriff_alpha.domain import AlphaError

SCHEMA = "rafii.creation-capabilities.v1"
NATIVE_DRAFT_SCHEMA = "rafii.native-draft.v1"
EXPORT_SCHEMA = "rafii.draft-export.v1"
# The drafting destinations every route supported before this projection. Their payloads, defaults and saved
# drafts keep working with the flags off; they are never removed by a rollback.
ORIGINAL_PLATFORMS = ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu")
# Rollout waves (spec PRD P0): Instagram and Facebook are the first release-blocking journeys, then every other
# mapped platform. Each wave is its own reversible coworker flag; neither changes publishing, OAuth or billing.
WAVE_FLAGS = (
    ("RAFII_CREATION_PROJECTION_ENABLED", ("Facebook",)),
    ("RAFII_CREATION_ALL_PLATFORMS_ENABLED", None),  # None: every row whose draft checks pass
)
OPERATIONS = ("draft", "media", "export", "connect", "publish", "analytics", "learning")
STATES = ("ready", "needs_input", "unavailable", "blocked", "unknown")
# Native fields that are written content (they appear in an export, each in its own slot) versus fields that bind a
# destination or a setting (never public copy; an unresolved one is listed, never invented).
CONTENT_FIELDS = {"title", "description", "question", "options", "sequence", "cta", "terms", "start", "end", "flair",
                  "category", "content_warning"}
# Structural slots a format adds beyond its caption/body, by native format kind.
_SLIDE_FORMATS = {"instagram.carousel", "pixelfed.album", "xiaohongshu.note", "linkedin.document"}
_SEGMENT_FORMATS = {"x.thread"}
_STORY_FORMATS = {"instagram.story", "facebook.story", "snapchat.story"}
_FORMAT_ROW = re.compile(r"^\|\s*`([a-z0-9._-]+)`\s*\|\s*([a-z]+)\s*\|\s*(.+?)\s*\|\s*$")
_FIELD = re.compile(r"`([a-z0-9_]+)`")
# The flag-off default format per original platform: what a request without `format` meant before this projection.
DEFAULT_FORMATS = {"LinkedIn": "linkedin.post", "Instagram": "instagram.post", "Threads": "threads.post", "X": "x.post",
                   "Xiaohongshu": "xiaohongshu.note", "Facebook": "facebook.page_post"}
# Stable error codes for rejected requests (spec §3).
ERRORS = {
    "unknown_platform": "Choose supported destinations.",
    "platform_not_enabled": "Choose supported destinations.",
    "unknown_format": "Choose a native format this platform supports.",
    "format_platform_mismatch": "Choose a native format this platform supports.",
    "duplicate_destination": "Choose supported destinations.",
    "unknown_language": "Choose supported destinations.",
    "schema_revision_mismatch": "Rafii's platform list changed. Reload and choose your destinations again.",
    "field_not_allowed": "That draft field isn't part of this platform's format.",
}


def _error(code, status=400):
    return AlphaError(ERRORS[code], status, code=code)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def parse_formats(skill_body):
    """Native formats from a channel skill's "Native content formats" table: [{id, mediaKind, nativeFields}].
    The table is the shipped, registry-hashed authority (the local Studio's `channel_adapters.PROFILES` mirrors it and a
    parity test catches drift)."""
    formats, in_section = [], False
    for line in (skill_body or "").splitlines():
        if line.startswith("## "):
            in_section = "native content formats" in line.lower()
            continue
        match = _FORMAT_ROW.match(line) if in_section else None
        if match:
            fields = _FIELD.findall(match.group(3))
            formats.append({"id": match.group(1), "mediaKind": match.group(2), "nativeFields": fields})
    return formats


def draft_slots(format_id, media_kind, native_fields):
    """The fields a native draft of this format may carry, in order. `caption` is the public body everywhere."""
    slots = ["caption"]
    slots += [f for f in native_fields if f in CONTENT_FIELDS]
    if format_id in _SLIDE_FORMATS:
        slots.append("slides")
    if format_id in _SEGMENT_FORMATS:
        slots.append("segments")
    if media_kind == "video":
        slots += ["spokenScript", "onScreenText"]
    if format_id in _STORY_FORMATS:
        slots.append("frames")
    if media_kind in ("image", "video", "document"):
        slots.append("altText")
    return slots


def binding_fields(native_fields):
    return [f for f in native_fields if f not in CONTENT_FIELDS]


def _flags(values=None):
    from .coworker import flags
    return {name: flags.enabled(name, values) for name, _ in WAVE_FLAGS}


def rollout(values=None):
    """{"waves": [...], "extra": platforms | "all"}: which non-original platforms the flags expose."""
    on = _flags(values)
    extra, everything = [], False
    for name, platforms in WAVE_FLAGS:
        if on[name]:
            if platforms is None:
                everything = True
            else:
                extra.extend(platforms)
    return {"flags": on, "extra": extra, "all": everything}


def _limits(platform):
    from .contracts import LIMITS
    limit = LIMITS.get(platform)
    if not limit:
        return {"verified": False, "characters": None, "version": None, "note": "No versioned limit is recorded; drafts are not checked against a length."}
    return {"verified": True, "characters": limit.get("characters"), "title": limit.get("title"), "version": limit.get("version"), "operation": limit.get("operation")}


def _publish_state(platform):
    from .capabilities import HOSTED_PUBLISHERS
    if platform in HOSTED_PUBLISHERS:
        return {"state": "needs_input", "reason": "live_check_required",
                "detail": f"Publishing to {platform} is decided when you ask to publish: provider review, a verified connected account, your plan and an approval of the exact content."}
    return {"state": "unavailable", "reason": "no_publisher", "detail": f"Rafii has no {platform} publisher; export the draft and post it yourself."}


def _media_state(fmt):
    kind = fmt["mediaKind"]
    if kind == "optional":
        return {"state": "ready", "reason": "media_optional", "detail": "Text works on its own; media is optional."}
    if kind == "video":
        return {"state": "needs_input", "reason": "video_input_required",
                "detail": "Needs a real video. Rafii writes the script and on-screen text; a script is not a finished video."}
    if kind == "document":
        return {"state": "needs_input", "reason": "document_input_required", "detail": "Needs a document file you supply."}
    return {"state": "needs_input", "reason": "image_input_required", "detail": "Needs an image from your Library or an approved image generation."}


class _Projection:
    """Built once per (registry release, skill files, flags); cheap to reuse."""

    def __init__(self, library=None, values=None, registry=None):
        from .skills import CHANNEL_SKILLS, SkillLibrary
        from .skill_registry import default_registry
        self.library = library or SkillLibrary()
        try:
            self.registry = registry or default_registry()
            release = self.registry.release()
        except Exception:  # noqa: BLE001 - a missing registry blocks extra platforms, never re-enables them
            self.registry, release = None, None
        self.release = release
        self.rollout = rollout(values)
        rows = []
        for platform, skill_id in CHANNEL_SKILLS.items():
            rows.append(self._row(platform, skill_id))
        self.rows = rows
        self.by_platform = {row["platform"]: row for row in rows}
        self.revision = "cap_" + _sha({"release": release, "rows": [(r["platform"], r["skill"].get("sha256"), [f["id"] for f in r["formats"]], r["operations"]["draft"]["state"]) for r in rows]})[:20]

    def _row(self, platform, skill_id):
        entry = self.registry.get(skill_id) if self.registry is not None else None
        loaded = self.library.load(skill_id) if self.library.available() else None
        formats = []
        if loaded is not None:
            for fmt in parse_formats(loaded["body"]):
                formats.append({**fmt, "draftFields": draft_slots(fmt["id"], fmt["mediaKind"], fmt["nativeFields"]),
                                "bindingFields": binding_fields(fmt["nativeFields"]), "media": _media_state(fmt),
                                "constraints": {"verified": False, "note": "Platform constraints for this format are unverified; Rafii never truncates to an assumed limit."}})
        blocker = None
        if self.registry is None:
            blocker = ("registry_unavailable", "The capability registry could not be read on this host.")
        elif entry is None:
            blocker = ("skill_unregistered", f"{skill_id} is not in the capability registry.")
        elif entry.get("deprecation") != "active" or entry.get("private"):
            blocker = ("skill_inactive", f"{skill_id} is not an active public skill.")
        elif loaded is None:
            blocker = ("skill_not_installed", f"{skill_id} is not installed on this host.")
        elif not formats:
            blocker = ("no_native_formats", f"{skill_id} declares no native formats.")
        original = platform in ORIGINAL_PLATFORMS
        exposed = original or self.rollout["all"] or platform in self.rollout["extra"]
        if blocker:
            draft = {"state": "blocked", "reason": blocker[0], "detail": blocker[1]}
        elif not exposed:
            draft = {"state": "unavailable", "reason": "rollout_not_enabled", "detail": f"{platform} drafting isn't switched on for this deployment yet."}
        else:
            draft = {"state": "ready", "reason": "ok", "detail": "Rafii writes native drafts for review, copy and export."}
        operations = {
            "draft": draft,
            "media": {"state": "needs_input" if any(f["media"]["state"] == "needs_input" for f in formats) else ("ready" if formats else "unknown"),
                      "reason": "per_format", "detail": "See each format's media requirement."},
            "export": {"state": "ready" if draft["state"] == "ready" else draft["state"], "reason": "ok" if draft["state"] == "ready" else draft["reason"],
                       "detail": "Copy or download the draft with a manifest; this is not a publication receipt."},
            "connect": {"state": "unknown", "reason": "checked_per_workspace", "detail": "Connections are shown on the Channels page for this workspace."},
            "publish": _publish_state(platform),
            "analytics": {"state": "unknown", "reason": "provider_and_consent_dependent", "detail": "Results appear only from an authorized, verified post; a missing metric is unavailable, never zero."},
            "learning": {"state": "needs_input", "reason": "user_approval_required", "detail": "Rafii proposes changes you can preview, accept, reject or undo."},
        }
        return {
            "platform": platform,
            "id": platform.lower().replace(" / ", "-").replace(" ", "-"),
            "labelKey": f"platform.{platform}",
            "original": original,
            "skill": {"id": skill_id, "version": loaded["version"] if loaded else None, "sha256": loaded["sha256"] if loaded else None,
                      "registryVersion": (entry or {}).get("version"), "required": ["postriff-content-craft", "postriff-adapter-contract", skill_id]},
            "formats": formats,
            "defaultFormat": DEFAULT_FORMATS.get(platform) or (formats[0]["id"] if formats else None),
            "limits": _limits(platform),
            "operations": operations,
            "qualification": {
                "code": "deterministic_tests" if not blocker else "blocked",
                "modelRoute": "unverified",
                "production": "unverified",
                "evidence": "tests/test_rafii_creation_capabilities.py",
            },
        }

    # -- queries ------------------------------------------------------------------------
    def draftable(self):
        return tuple(row["platform"] for row in self.rows if row["operations"]["draft"]["state"] == "ready")

    def public(self):
        """The versioned facet the browser reads. Method only: no skill bodies, prompts or private packages."""
        return {"schema": SCHEMA, "revision": self.revision, "registryRelease": self.release,
                "rollout": {"waves": [name for name, on in self.rollout["flags"].items() if on]},
                "originalPlatforms": list(ORIGINAL_PLATFORMS), "draftable": list(self.draftable()), "platforms": self.rows}


_CACHE = {}


def projection(values=None, library=None, registry=None):
    """The projection for these flags. The shipped registry and skill files are immutable at runtime, so the default
    build is cached per flag state (a flag flip or rollback takes effect on the next call)."""
    if library is not None or registry is not None:
        return _Projection(library=library, values=values, registry=registry)
    key = tuple(sorted(rollout(values)["flags"].items()))
    cached = _CACHE.get(key)
    if cached is None:
        cached = _CACHE[key] = _Projection(values=values)
    return cached


def draftable_platforms(values=None):
    """Platforms every drafting route accepts now. The original five whatever happens; more only when a wave flag is
    on and the row's draft checks pass. Any failure building the projection falls back to the original five."""
    try:
        found = projection(values).draftable()
    except Exception:  # noqa: BLE001
        return ORIGINAL_PLATFORMS
    return tuple(dict.fromkeys(ORIGINAL_PLATFORMS + tuple(p for p in found if p not in ORIGINAL_PLATFORMS)))


def validate_destinations(destinations, values=None, revision=None, proj=None):
    """Server-side check of a requested destination list (the browser never decides). Raises AlphaError with a stable
    code. Unique key: (platform, language, account, native format). Returns the destinations with `format` normalised
    (omitted for a platform-default request, so existing payloads and saved drafts hash the same)."""
    from . import locales
    proj = proj or None
    allowed = None
    seen, out = set(), []
    for d in destinations or []:
        platform = d.get("platform") if isinstance(d, dict) else None
        if not isinstance(platform, str) or not platform:
            raise _error("unknown_platform")
        tag = locales.canonical(d.get("language"))
        if tag is None:
            raise _error("unknown_language")
        if allowed is None:
            if proj is None:
                try:
                    proj = projection(values)
                except Exception:  # noqa: BLE001
                    proj = None
            allowed = set(proj.draftable()) | set(ORIGINAL_PLATFORMS) if proj is not None else set(ORIGINAL_PLATFORMS)
            if revision is not None and proj is not None and revision != proj.revision:
                raise _error("schema_revision_mismatch", 409)
        if platform not in allowed:
            from .skills import CHANNEL_SKILLS
            raise _error("platform_not_enabled" if platform in CHANNEL_SKILLS else "unknown_platform")
        fmt = d.get("format")
        if fmt is not None:
            row = proj.by_platform.get(platform) if proj is not None else None
            ids = {f["id"] for f in (row or {}).get("formats") or []}
            if not isinstance(fmt, str) or not row:
                raise _error("unknown_format")
            if fmt not in ids:
                raise _error("format_platform_mismatch" if any(fmt in {f["id"] for f in r["formats"]} for r in proj.rows) else "unknown_format")
        channel_id = d.get("channelId") if isinstance(d.get("channelId"), str) else None
        key = (platform, tag, channel_id, fmt or DEFAULT_FORMATS.get(platform))
        if key in seen:
            raise _error("duplicate_destination")
        seen.add(key)
        out.append(d)
    return out


# -- native drafts -------------------------------------------------------------------------
def _paragraphs(text):
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


PUBLISH_NOTE = "A draft is not publish-ready: publishing runs the live account, permission, plan and approval checks."
EXPORT_ONLY_NOTE = "Rafii can't publish this format yet. Export the draft and post it yourself."


def native_draft(variant, proj=None):
    """The structured native draft for one written variant: public fields in their own slots, destination bindings
    (unresolved ones listed, never invented), private notes kept apart, media requirement and unverified constraints.
    Deterministic: the same variant always yields the same payload."""
    platform = variant.get("platform")
    proj = proj or projection()
    row = proj.by_platform.get(platform)
    if row is None:
        return None
    fmt_id = variant.get("format") or row["defaultFormat"]
    fmt = next((f for f in row["formats"] if f["id"] == fmt_id), None)
    if fmt is None:
        return None
    text = variant.get("text") or ""
    fields = {"caption": text}
    supplied = variant.get("nativeFields") if isinstance(variant.get("nativeFields"), dict) else {}
    paragraphs = _paragraphs(text)
    if "title" in fmt["draftFields"]:
        if platform == "Xiaohongshu":
            # Existing contract: a Xiaohongshu note's first line is its title (locale_lint and previews read it so).
            fields["title"] = supplied.get("title") or text.strip().partition("\n")[0].strip()
        else:
            fields["title"] = supplied.get("title")
    for slot in fmt["draftFields"]:
        if slot in ("caption", "title"):
            continue
        if slot in supplied:
            fields[slot] = supplied[slot]
        elif slot == "slides":
            fields["slides"] = [{"index": i + 1, "text": p} for i, p in enumerate(paragraphs)] if len(paragraphs) > 1 else []
        elif slot == "segments":
            fields["segments"] = [{"index": i + 1, "text": p} for i, p in enumerate(paragraphs)]
        elif slot in ("spokenScript", "onScreenText", "frames", "altText"):
            fields[slot] = None
        else:
            fields[slot] = None
    bindings = {name: (variant.get("bindings") or {}).get(name) for name in fmt["bindingFields"]}
    unresolved = [name for name, value in bindings.items() if not value]
    missing_content = [slot for slot in fmt["draftFields"] if slot in CONTENT_FIELDS and slot in fmt["nativeFields"] and not fields.get(slot)]
    media = variant.get("media") if isinstance(variant.get("media"), list) else []
    media_state = fmt["media"]["state"]
    if fmt["mediaKind"] != "optional" and media:
        kinds = {m.get("kind") for m in media if isinstance(m, dict)}
        media_state = "attached_unvalidated" if kinds else media_state
    return {
        "schema": NATIVE_DRAFT_SCHEMA,
        "capabilityRevision": proj.revision,
        "platform": platform,
        "formatId": fmt_id,
        "fields": fields,
        "bindings": bindings,
        "unresolved": unresolved,
        "missingContent": missing_content,
        "privateNotes": [str(n) for n in (variant.get("privateNotes") or []) if isinstance(n, str)],
        "media": {"required": fmt["mediaKind"], "state": media_state, "reason": fmt["media"]["reason"]},
        "constraints": {"verified": False, "limits": row["limits"]},
        # The same rule as the approval gate (`store` refuses `format_not_publishable`): only a platform's default format
        # has a publisher, so any other format is export-only and the review says so before anyone tries to schedule it.
        "readiness": {"draft": "ready", "export": "ready", "publish": "not_checked", "publishNote": PUBLISH_NOTE}
        if fmt_id == DEFAULT_FORMATS.get(platform) else
        {"draft": "ready", "export": "ready", "publish": "export_only", "publishNote": EXPORT_ONLY_NOTE},
    }


def text_projection(native):
    """The old `text` preview/export contract, deterministically from a native draft. Title first (the Xiaohongshu
    contract), then the caption; slides and segments are already the caption's paragraphs for writer-produced drafts.
    Private notes, bindings and readiness never appear."""
    if not native:
        return ""
    fields = native.get("fields") or {}
    caption = str(fields.get("caption") or "")
    title = str(fields.get("title") or "").strip()
    if native.get("platform") == "Xiaohongshu" and title and not caption.strip().startswith(title):
        return title + "\n" + caption
    return caption


def skill_route(platform, bindings, omissions=(), proj=None):
    """Did the writer actually receive the instructions this platform's route requires (editorial core, adapter contract,
    channel adapter), whole? `bindings` are the run's recorded {id, version, sha256}; a hard cut of the skill text or a
    missing required skill makes the draft an unvalidated generic draft, never a platform-qualified one."""
    proj = proj or projection()
    row = proj.by_platform.get(platform)
    required = (row or {}).get("skill", {}).get("required") or []
    present = {b.get("id"): b for b in bindings or [] if isinstance(b, dict)}
    missing = [skill_id for skill_id in required if skill_id not in present]
    cut = any(isinstance(o, dict) and o.get("cut") for o in omissions or [])
    qualified = bool(row) and not missing and not cut
    return {"qualified": qualified, "generic": not qualified, "missing": missing, "cut": cut,
            "required": [{"id": skill_id, **({k: present[skill_id].get(k) for k in ("version", "sha256")} if skill_id in present else {})} for skill_id in required],
            "note": None if qualified else "Unvalidated generic draft: the platform's required writing instructions did not all reach the writer."}


def attach_native(variants, proj=None, bindings=None, omissions=()):
    """Adds `native` to every variant whose platform/format the projection knows. Existing fields are untouched, so
    an older reader keeps seeing the same `text`. With the run's skill bindings, each native draft also records whether
    its platform route was qualified (see `skill_route`)."""
    proj = proj or projection()
    for variant in variants or []:
        if not isinstance(variant, dict) or variant.get("native"):
            continue
        native = native_draft(variant, proj)
        if native is not None:
            if bindings is not None:
                native["skillRoute"] = skill_route(variant.get("platform"), bindings, omissions, proj)
                if native["skillRoute"]["generic"]:
                    variant.setdefault("warnings", []).append(native["skillRoute"]["note"])
            variant["native"] = native
    return variants


def current_native(variant, proj=None):
    """The native draft for the variant's current text. A person's edit to `text` wins: a stored native draft written
    for older text is rebuilt from the edited text (supplied native fields and bindings are kept)."""
    native = variant.get("native") if isinstance(variant.get("native"), dict) else None
    if native and (native.get("fields") or {}).get("caption") == variant.get("text"):
        return native
    # Only fields the writer supplied separately survive; slides, segments and a Xiaohongshu title derived from the old
    # text are derived again from the edited text.
    rebuilt = native_draft(variant, proj)
    return rebuilt or {}


def validate_native_fields(platform, format_id, fields, proj=None):
    """Schema check for a native draft's public fields (spec §5): only the format's slots, strings or ordered
    {"index","text"} lists. Returns (clean_fields, errors). Unknown limits are never enforced as if verified."""
    proj = proj or projection()
    row = proj.by_platform.get(platform)
    fmt = next((f for f in (row or {}).get("formats") or [] if f["id"] == format_id), None)
    if fmt is None:
        return {}, ["unknown_format"]
    out, errors = {}, []
    for key, value in (fields or {}).items():
        if key not in fmt["draftFields"]:
            errors.append(f"field_not_allowed:{key}")
        elif value is None or isinstance(value, str):
            out[key] = value
        elif isinstance(value, list) and all(isinstance(i, dict) and isinstance(i.get("text"), str) and type(i.get("index")) is int for i in value):
            indexes = [i["index"] for i in value]
            if indexes != list(range(1, len(value) + 1)):
                errors.append(f"order_invalid:{key}")
            else:
                out[key] = [{"index": i["index"], "text": i["text"]} for i in value]
        else:
            errors.append(f"type_invalid:{key}")
    return out, errors


# -- export ---------------------------------------------------------------------------------
def export_package(variants, *, campaign_id=None, created_at=None):
    """A manual-handoff package: one file per variant (exact text, native fields in order, attribution) plus a
    manifest with sha256 per file. Never a publication receipt: `published` is always False."""
    files, manifest = [], []
    proj = None
    for index, variant in enumerate(variants or []):
        native = current_native(variant, proj)
        platform = variant.get("platform") or "draft"
        slug = re.sub(r"[^a-z0-9]+", "-", platform.lower()).strip("-") or "draft"
        language = variant.get("language") or "und"
        name = f"{index + 1:02d}-{slug}-{native.get('formatId') or 'text'}-{language}.txt".replace("/", "-")
        lines = [variant.get("text") or ""]
        fields = native.get("fields") or {}
        for key in ("title", "description", "question", "options", "sequence", "cta", "terms", "start", "end", "flair", "category", "content_warning", "spokenScript", "onScreenText"):
            if fields.get(key) and not (key == "title" and platform == "Xiaohongshu"):
                lines.append(f"[{key}]\n{fields[key] if not isinstance(fields[key], list) else chr(10).join(map(str, fields[key]))}")
        for key in ("slides", "segments", "frames"):
            for item in fields.get(key) or []:
                lines.append(f"[{key[:-1]} {item.get('index')}]\n{item.get('text')}")
        if fields.get("altText"):
            lines.append(f"[alt text]\n{fields['altText']}")
        if variant.get("sourceIds"):
            lines.append("[sources]\n" + "\n".join(variant["sourceIds"]))
        body = "\n\n".join(lines).rstrip() + "\n"
        data = body.encode("utf-8")
        files.append({"name": name, "mime": "text/plain; charset=utf-8", "text": body})
        manifest.append({"file": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "platform": platform,
                         "formatId": native.get("formatId"), "language": language, "channelId": variant.get("channelId"),
                         "variantId": variant.get("id"), "media": [{"assetId": m.get("assetId") or m.get("id"), "kind": m.get("kind")} for m in variant.get("media") or [] if isinstance(m, dict)],
                         "unresolved": native.get("unresolved") or []})
    return {"schema": EXPORT_SCHEMA, "campaignId": campaign_id, "createdAt": created_at, "published": False,
            "note": "Manual handoff package. Nothing was posted; this is not a publication receipt.",
            "files": files, "manifest": manifest}
