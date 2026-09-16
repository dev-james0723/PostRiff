"""Portable skill-bundle manifest validation and deterministic file hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


INSTALL_SKILL_IDS = (
    "james-au-social-orchestrator",
    "james-au-template-library",
    "james-au-social-graphics",
    "james-au-discoverability",
    "james-au-source-extraction-providers",
    "james-au-video-transcript-intake",
    "james-au-transcript-translation",
    "james-au-hyperframes-motion",
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _resolve_source(repository_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("source_outside_repository")
    if ".." in Path(relative).parts:
        raise ValueError("source_outside_repository")
    repository = repository_root.resolve()
    resolved = (repository / relative).resolve()
    if not resolved.is_relative_to(repository):
        raise ValueError("source_outside_repository")
    return resolved


def _validate_resource_paths(repository_root: Path, value: object) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _validate_resource_paths(repository_root, nested)
        return
    _resolve_source(repository_root, value)


def load_install_manifest(path: Path, repository_root: Path) -> dict[str, object]:
    """Load the exact Phase 0B source map without performing a write."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("install_manifest_must_be_object")
    if value.get("schema_version") != "phase0b-install-manifest-v1":
        raise ValueError("unsupported_install_manifest_schema")
    if tuple(value.get("skill_ids", ())) != INSTALL_SKILL_IDS:
        raise ValueError("install_skill_ids_mismatch")
    skills = value.get("skills")
    if not isinstance(skills, dict) or set(skills) != set(INSTALL_SKILL_IDS):
        raise ValueError("install_skill_sources_mismatch")
    for skill_id in INSTALL_SKILL_IDS:
        expected = f"skills/{skill_id}"
        _resolve_source(repository_root, skills[skill_id])
        if skills.get(skill_id) != expected:
            raise ValueError(f"install_skill_source_mismatch:{skill_id}")
    resources = value.get("embedded_resources")
    if not isinstance(resources, dict):
        raise ValueError("embedded_resources_must_be_object")
    _validate_resource_paths(repository_root, resources)
    return json.loads(json.dumps(value))


def canonical_file_inventory(root: Path) -> list[dict[str, str | int]]:
    """Return a path-sorted SHA-256 inventory and reject links/special files."""

    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise ValueError("inventory_root_missing")
    inventory: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError("symlink_not_allowed")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("special_file_not_allowed")
        data = path.read_bytes()
        inventory.append(
            {
                "path": path.resolve().relative_to(resolved_root).as_posix(),
                "sha256": _hash_bytes(data),
                "size": len(data),
            }
        )
    return inventory


def tree_hash(inventory: Sequence[Mapping[str, object]]) -> str:
    """Hash a canonical inventory rather than mutable filesystem metadata."""

    return _hash_bytes(_canonical_json(list(inventory)))
