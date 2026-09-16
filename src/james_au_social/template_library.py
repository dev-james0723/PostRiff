"""Dependency-free template discovery, selection, and safe local saving."""

from __future__ import annotations

import copy
import hashlib
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path


REQUIRED_TEMPLATE_FIELDS = (
    "template_id",
    "version",
    "status",
    "kind",
    "source_types",
    "output_families",
    "languages",
)
LIST_FIELDS = {
    "source_types",
    "output_families",
    "native_format_ids",
    "languages",
}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ARTIFACT_REFERENCE = re.compile(r"^artifact-template-[a-z0-9][a-z0-9-]{2,127}$")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_inline_list(value: str) -> list[str]:
    if not value.startswith("[") or not value.endswith("]"):
        raise ValueError("template_list_must_use_brackets")
    body = value[1:-1].strip()
    if not body:
        return []
    items = [item.strip().strip('"\'') for item in body.split(",")]
    if any(not item for item in items):
        raise ValueError("template_list_contains_blank")
    return items


def _parse_template(path: Path, *, require_path_match: bool = True) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.suffix != ".md":
        raise ValueError("invalid_template_file")
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise ValueError("template_frontmatter_missing")
    frontmatter_text, body = raw[4:].split("\n---\n", 1)
    frontmatter: dict[str, object] = {}
    for line in frontmatter_text.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError("template_frontmatter_line_invalid")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if key in frontmatter:
            raise ValueError(f"duplicate_template_field:{key}")
        frontmatter[key] = _parse_inline_list(value) if key in LIST_FIELDS else value
    for field in REQUIRED_TEMPLATE_FIELDS:
        if field not in frontmatter:
            raise ValueError(f"template_field_missing:{field}")
    if require_path_match and frontmatter["template_id"] != path.stem:
        raise ValueError("template_id_path_mismatch")
    if not isinstance(frontmatter["version"], str) or not SEMVER.fullmatch(
        frontmatter["version"]
    ):
        raise ValueError("template_version_invalid")
    if frontmatter["status"] not in {
        "candidate",
        "active",
        "deprecated",
        "archived",
        "unavailable",
    }:
        raise ValueError("template_status_invalid")
    if frontmatter["kind"] not in {"content", "visual", "hybrid", "artifact_reference"}:
        raise ValueError("template_kind_invalid")
    if not body.strip():
        raise ValueError("template_body_missing")
    if re.search(r"\b(TODO|TBD|fill in)\b", raw, flags=re.IGNORECASE):
        raise ValueError("template_scaffold_marker")
    heading = next(
        (line[2:].strip() for line in body.splitlines() if line.startswith("# ")),
        str(frontmatter["template_id"]).replace("-", " ").title(),
    )
    native_format_ids = frontmatter.get("native_format_ids", [])
    if not isinstance(native_format_ids, list):
        raise ValueError("template_native_formats_invalid")
    return {
        **frontmatter,
        "native_format_ids": native_format_ids,
        "display_name": heading,
        "description": heading,
        "scope": "project",
        "eligible_brand_identities": [
            "james_au",
            "my_best_life_os",
            "fantasia_studio",
            "d_festival",
        ],
        "required_inputs": [],
        "optional_inputs": [],
        "preview_ref": None,
        "template_path": path.as_posix(),
        "template_skill_ref": None,
        "content_hash": _sha256(raw.encode("utf-8")),
        "provenance": "original_project_default",
        "rights_note": "project-local template; generated media rights reviewed separately",
        "created_at": "2026-09-12T00:00:00Z",
        "updated_at": "2026-09-12T00:00:00Z",
        "body": body.strip(),
    }


def load_template_catalog(root: Path) -> tuple[dict[str, object], ...]:
    """Load all Markdown templates below one explicit local directory."""

    resolved = root.resolve()
    if not resolved.is_dir() or root.is_symlink():
        raise ValueError("template_library_missing")
    catalog: list[dict[str, object]] = []
    versions: set[tuple[str, str]] = set()
    for path in sorted(root.glob("*.md"), key=lambda item: item.name):
        template = _parse_template(path)
        identity = (str(template["template_id"]), str(template["version"]))
        if identity in versions:
            raise ValueError("duplicate_template_version")
        versions.add(identity)
        catalog.append(template)
    return tuple(copy.deepcopy(catalog))


def recommend_templates(
    catalog: Sequence[Mapping[str, object]],
    request: Mapping[str, object],
    limit: int = 3,
) -> tuple[dict[str, object], ...]:
    """Return at most three active, target-eligible templates."""

    if limit < 0:
        raise ValueError("template_limit_invalid")
    source_type = request.get("source_type")
    output_family = request.get("output_family")
    native_format_id = request.get("native_format_id")
    language = request.get("language")
    ranked: list[tuple[int, str, str, dict[str, object]]] = []
    for raw_template in catalog:
        template = copy.deepcopy(dict(raw_template))
        if template.get("status") != "active":
            continue
        if source_type not in template.get("source_types", []):
            continue
        if language not in template.get("languages", []):
            continue
        native_match = native_format_id in template.get("native_format_ids", [])
        family_match = output_family in template.get("output_families", [])
        if not native_match and not family_match:
            continue
        score = 100 if native_match else 50
        if family_match:
            score += 20
        ranked.append(
            (-score, str(template["template_id"]), str(template["version"]), template)
        )
    ranked.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in ranked[: min(limit, 3)])


def build_template_selection(
    template: Mapping[str, object],
    request: Mapping[str, object],
    overrides: Mapping[str, object],
) -> dict[str, object]:
    """Bind one exact template version into the V14 TemplateSelection shape."""

    for field in ("target", "native_format_id", "language", "resolved_at"):
        if not request.get(field):
            raise ValueError(f"template_selection_field_missing:{field}")
    template_ref = f"{template['template_id']}@{template['version']}"
    content_hash = template.get("content_hash")
    if not isinstance(content_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", content_hash
    ):
        raise ValueError("template_hash_invalid")
    return {
        "selection_id": f"selection-{template['template_id']}-{request['target']}",
        "campaign_id": request.get("campaign_id", "campaign-pending"),
        "target_ids": [request["target"]],
        "eligible_template_versions": [template_ref],
        "recommended_template_versions": [template_ref],
        "decision": "selected",
        "selected_template_version": template_ref,
        "selected_template_hash": content_hash,
        "selection_source": request.get("selection_source", "campaign_answer"),
        "user_overrides": copy.deepcopy(dict(overrides)),
        "visual_reference": {
            "provider": "project_local",
            "reviewed_commit": None,
            "provider_state": request.get("visual_reference_state", "needs_review"),
            "system": None,
            "theme_id": None,
            "layout_recipe_ids": [],
            "license_mode": "reference_only",
        },
        "preview_ref": None,
        "preview_approved": False,
        "resolved_at": request["resolved_at"],
        "native_format_id": request["native_format_id"],
        "language": request["language"],
    }


def save_markdown_template(
    source: Path, library_root: Path, destination_name: str
) -> Path:
    """Copy one validated Markdown template without overwriting or escaping."""

    destination_part = Path(destination_name)
    if (
        destination_part.is_absolute()
        or ".." in destination_part.parts
        or len(destination_part.parts) != 1
        or destination_part.suffix != ".md"
    ):
        raise ValueError("template_destination_outside_library")
    if source.is_symlink() or not source.is_file() or source.suffix != ".md":
        raise ValueError("invalid_template_source")
    template = _parse_template(source, require_path_match=False)
    if destination_part.stem != template["template_id"]:
        raise ValueError("template_id_path_mismatch")
    library_root.mkdir(parents=True, exist_ok=True)
    if library_root.is_symlink():
        raise ValueError("template_library_symlink_not_allowed")
    root = library_root.resolve()
    destination = (root / destination_part).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("template_destination_outside_library")
    if destination.exists():
        raise ValueError("template_already_exists")
    shutil.copyfile(source, destination)
    _parse_template(destination)
    return destination


def template_creator_bridge_state(available: bool) -> dict[str, object]:
    """Describe bridge availability without fabricating an artifact result."""

    if available:
        return {"state": "available", "artifact_reference_required": True}
    return {
        "state": "unavailable",
        "fallback": "project_markdown",
        "reason": "template_creator_not_callable",
    }


def validate_artifact_template_reference(reference: str) -> str:
    if ARTIFACT_REFERENCE.fullmatch(reference) is None:
        raise ValueError("invalid_artifact_template_reference")
    return reference
