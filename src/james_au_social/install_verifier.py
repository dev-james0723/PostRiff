"""Read-only installation planning and exact approval-gated skill copying."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from .install_manifest import INSTALL_SKILL_IDS, canonical_file_inventory, tree_hash


def _bundle_summary(bundle: Path) -> dict[str, object]:
    root = bundle.resolve()
    if not root.is_dir() or bundle.is_symlink():
        raise ValueError("bundle_missing")
    children = sorted(path.name for path in root.iterdir())
    if children != sorted(INSTALL_SKILL_IDS):
        raise ValueError("bundle_skill_roots_mismatch")
    skills: dict[str, dict[str, object]] = {}
    for skill_id in INSTALL_SKILL_IDS:
        inventory = canonical_file_inventory(root / skill_id)
        skills[skill_id] = {
            "tree_hash": tree_hash(inventory),
            "files": inventory,
        }
    inventory = canonical_file_inventory(root)
    return {
        "bundle_hash": tree_hash(inventory),
        "total_bytes": sum(int(item["size"]) for item in inventory),
        "skills": skills,
    }


def _reject_unsafe_destination(destination: Path) -> Path:
    expanded = destination.expanduser()
    resolved = expanded.resolve()
    if resolved in {Path("/").resolve(), Path.home().resolve()}:
        raise ValueError("unsafe_install_destination")
    if expanded.exists() and expanded.is_symlink():
        raise ValueError("unsafe_install_destination")
    if expanded.exists() and not expanded.is_dir():
        raise ValueError("unsafe_install_destination")
    return resolved


def plan_install(bundle: Path, destination: Path) -> dict[str, object]:
    """Inspect the exact destination without creating or changing it."""

    summary = _bundle_summary(bundle)
    resolved_destination = _reject_unsafe_destination(destination)
    skills = summary["skills"]
    if not isinstance(skills, dict):
        raise ValueError("bundle_skill_roots_mismatch")
    targets: list[dict[str, object]] = []
    for skill_id in INSTALL_SKILL_IDS:
        target = resolved_destination / skill_id
        expected_hash = skills[skill_id]["tree_hash"]
        if not target.exists():
            state = "new"
            actual_hash = None
        elif target.is_symlink() or not target.is_dir():
            state = "conflict"
            actual_hash = None
        else:
            actual_hash = tree_hash(canonical_file_inventory(target))
            state = "already_installed" if actual_hash == expected_hash else "conflict"
        targets.append(
            {
                "skill_id": skill_id,
                "destination": str(target),
                "state": state,
                "expected_tree_hash": expected_hash,
                "actual_tree_hash": actual_hash,
            }
        )
    return {
        "schema_version": "phase0b-install-plan-v1",
        "bundle_hash": summary["bundle_hash"],
        "skill_ids": list(INSTALL_SKILL_IDS),
        "destination": str(resolved_destination),
        "total_bytes": summary["total_bytes"],
        "targets": targets,
        "write_state": "not_executed",
        "external_side_effects": [],
    }


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"approval_time_invalid:{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"approval_time_invalid:{field}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"approval_time_invalid:{field}")
    return parsed.astimezone(timezone.utc)


def _validate_approval(
    approval: Mapping[str, object], plan: Mapping[str, object]
) -> None:
    if approval.get("approval_state") != "approved":
        raise ValueError("install_not_approved")
    if not isinstance(approval.get("approval_id"), str) or not approval["approval_id"]:
        raise ValueError("approval_id_missing")
    if approval.get("bundle_hash") != plan.get("bundle_hash"):
        raise ValueError("approval_bundle_hash_mismatch")
    if approval.get("skill_ids") != plan.get("skill_ids"):
        raise ValueError("approval_skill_ids_mismatch")
    if approval.get("destination") != plan.get("destination"):
        raise ValueError("approval_destination_mismatch")
    approved_at = _parse_time(approval.get("approved_at"), "approved_at")
    expires_at = _parse_time(approval.get("expires_at"), "expires_at")
    now = datetime.now(timezone.utc)
    if approved_at > now or expires_at <= now or expires_at <= approved_at:
        raise ValueError("approval_expired_or_not_current")


def apply_install(
    bundle: Path,
    destination: Path,
    approval: Mapping[str, object],
) -> dict[str, object]:
    """Install new exact skill trees; never overwrite a conflicting target."""

    plan = plan_install(bundle, destination)
    _validate_approval(approval, plan)
    conflicts = [item for item in plan["targets"] if item["state"] == "conflict"]
    if conflicts:
        raise ValueError("installed_skill_conflict")
    new_ids = [item["skill_id"] for item in plan["targets"] if item["state"] == "new"]
    existing_ids = [
        item["skill_id"]
        for item in plan["targets"]
        if item["state"] == "already_installed"
    ]
    resolved_destination = Path(str(plan["destination"]))
    if not new_ids:
        return {
            "state": "verified",
            "bundle_hash": plan["bundle_hash"],
            "destination": plan["destination"],
            "installed_skill_ids": [],
            "already_installed_skill_ids": existing_ids,
            "external_side_effects": [],
        }

    destination_was_created = not resolved_destination.exists()
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=".phase0b-install-", dir=str(resolved_destination.parent)
        )
    )
    promoted: list[Path] = []
    try:
        for skill_id in new_ids:
            shutil.copytree(bundle.resolve() / skill_id, stage / skill_id)
            expected = next(
                item["expected_tree_hash"]
                for item in plan["targets"]
                if item["skill_id"] == skill_id
            )
            actual = tree_hash(canonical_file_inventory(stage / skill_id))
            if actual != expected:
                raise ValueError("staged_skill_hash_mismatch")
        resolved_destination.mkdir(parents=True, exist_ok=True)
        for skill_id in new_ids:
            target = resolved_destination / skill_id
            if target.exists():
                raise ValueError("installed_skill_conflict")
            (stage / skill_id).rename(target)
            promoted.append(target)
        shutil.rmtree(stage)
        verified = verify_install(resolved_destination, bundle)
        return {
            "state": verified["state"],
            "bundle_hash": plan["bundle_hash"],
            "destination": plan["destination"],
            "installed_skill_ids": new_ids,
            "already_installed_skill_ids": existing_ids,
            "external_side_effects": [],
        }
    except Exception:
        for path in reversed(promoted):
            if path.exists():
                shutil.rmtree(path)
        if stage.exists():
            shutil.rmtree(stage)
        if destination_was_created and resolved_destination.exists():
            try:
                resolved_destination.rmdir()
            except OSError:
                pass
        raise


def _validate_skill_links(skill_root: Path) -> None:
    skill_file = skill_root / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n") or f"name: {skill_root.name}" not in text:
        raise ValueError(f"installed_skill_frontmatter_invalid:{skill_root.name}")
    if re.search(r"\b(TODO|TBD|fill in)\b", text, flags=re.IGNORECASE):
        raise ValueError(f"installed_skill_scaffold_marker:{skill_root.name}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith(("#", "/")):
            continue
        if not (skill_root / target.split("#", 1)[0]).is_file():
            raise ValueError(f"installed_skill_link_missing:{skill_root.name}")


def _run_orchestrator_smoke(destination: Path) -> dict[str, object]:
    scripts = destination / "james-au-social-orchestrator/scripts"
    code = """
import json
import pathlib
import sys
from james_au_social.orchestrator import build_orchestration_plan
request = {
    "mode": "article_repurpose",
    "campaign_id": "installed-smoke",
    "source_artifact_id": "article-smoke",
    "source_type": "article",
    "james_angle": "A supplied test angle",
    "target_families": "choose_targets",
    "target_id": "instagram-smoke",
    "output_family": "carousel",
    "native_format_id": "instagram.carousel",
    "language": "en",
    "template_decision": "decide_for_me",
    "resolved_at": "2026-09-12T20:00:00Z"
}
print(json.dumps(build_orchestration_plan(request, pathlib.Path(sys.argv[1])), sort_keys=True))
"""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(scripts),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code, str(destination)],
        cwd=destination.parent,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def verify_install(destination: Path, bundle: Path) -> dict[str, object]:
    """Verify exact installed bytes and run the bundled orchestrator in isolation."""

    plan = plan_install(bundle, destination)
    if any(item["state"] != "already_installed" for item in plan["targets"]):
        raise ValueError("installed_bundle_incomplete_or_changed")
    resolved_destination = Path(str(plan["destination"]))
    for skill_id in INSTALL_SKILL_IDS:
        _validate_skill_links(resolved_destination / skill_id)
    templates = list(
        (
            resolved_destination
            / "james-au-template-library/assets/default-templates"
        ).glob("*.md")
    )
    if len(templates) != 6:
        raise ValueError("installed_template_count_mismatch")
    smoke = _run_orchestrator_smoke(resolved_destination)
    if smoke.get("execution_state") != "local_plan_ready":
        raise ValueError("installed_orchestrator_smoke_failed")
    if smoke.get("external_actions") != []:
        raise ValueError("installed_orchestrator_reported_external_action")
    return {
        "state": "verified",
        "bundle_hash": plan["bundle_hash"],
        "skill_count": len(INSTALL_SKILL_IDS),
        "template_count": len(templates),
        "orchestrator_state": smoke["execution_state"],
        "external_side_effects": [],
    }
