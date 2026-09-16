"""Local-only top-level routing for the James Au social content suite."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from pathlib import Path

from .conversation import next_v14_question
from .onboarding import FirstRunOnboardingStore
from .template_library import load_template_catalog, recommend_templates


ROUTES: dict[str, tuple[str, ...]] = {
    "setup": (
        "james-au-conversation-director",
        "james-au-api-setup-wizard",
        "james-au-security-and-approval",
        "james-au-browser-auth-and-session",
        "james-au-publish-and-verify",
    ),
    "current_news": (
        "james-au-source-extraction-providers",
        "james-au-discoverability",
        "james-au-template-library",
        "james-au-social-graphics",
    ),
    "article_repurpose": (
        "james-au-template-library",
        "james-au-discoverability",
        "james-au-social-graphics",
    ),
    "video_analysis": (
        "james-au-video-transcript-intake",
        "james-au-transcript-translation",
        "james-au-template-library",
    ),
    "article_to_motion": (
        "james-au-template-library",
        "james-au-hyperframes-motion",
    ),
    "static_visual": (
        "james-au-template-library",
        "james-au-social-graphics",
    ),
    "discoverability": ("james-au-discoverability",),
}


def start_or_resume_first_run(
    state_path: str | Path, session_id: str
) -> dict[str, object]:
    """Return the single next onboarding question or safe assessment state."""

    return FirstRunOnboardingStore(state_path).start(session_id)


def _first_file(root: Path, relatives: tuple[str, ...]) -> Path | None:
    for relative in relatives:
        path = (root / relative).resolve()
        if path.is_file():
            return path
    return None


def _first_directory(root: Path, relatives: tuple[str, ...]) -> Path | None:
    for relative in relatives:
        path = (root / relative).resolve()
        if path.is_dir():
            return path
    return None


def _brand_dependency(root: Path) -> tuple[Path, str] | None:
    path = _first_file(
        root,
        (
            "docs/james-au-social-content-engine.md",
            "references/james-au-social-content-engine.md",
            "james-au-social-orchestrator/references/james-au-social-content-engine.md",
        ),
    )
    if path is None:
        return None
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def _template_root(root: Path) -> Path | None:
    return _first_directory(
        root,
        (
            "templates/defaults",
            "assets/default-templates",
            "james-au-template-library/assets/default-templates",
        ),
    )


def build_orchestration_plan(
    request: Mapping[str, object], resource_root: Path
) -> dict[str, object]:
    """Return one safe local plan or the next blocking question."""

    mode = request.get("mode")
    if mode not in ROUTES:
        return {
            "execution_state": "blocked",
            "reason": "unsupported_orchestrator_mode",
            "external_actions": [],
        }
    brand_dependency = _brand_dependency(resource_root.resolve())
    if brand_dependency is None:
        return {
            "execution_state": "blocked",
            "reason": "missing_brand_dependency",
            "external_actions": [],
        }
    question = next_v14_question(request)
    if question is not None:
        if question["state"] == "blocked":
            return {
                "execution_state": "blocked",
                "reason": question["reason"],
                "questions": [],
                "external_actions": [],
            }
        return {
            "execution_state": "awaiting_answer",
            "questions": [copy.deepcopy(question)],
            "external_actions": [],
        }

    skill_route = list(ROUTES[str(mode)])
    if mode == "video_analysis" and request.get("target_language") == "none":
        skill_route.remove("james-au-transcript-translation")

    recommendations: tuple[dict[str, object], ...] = ()
    template_root = _template_root(resource_root.resolve())
    required_template_fields = {
        "source_type",
        "output_family",
        "native_format_id",
        "language",
    }
    if template_root is not None and required_template_fields.issubset(request):
        recommendations = recommend_templates(
            load_template_catalog(template_root), request
        )

    engine_path, engine_hash = brand_dependency
    return {
        "execution_state": "local_plan_ready",
        "mode": mode,
        "campaign_id": request.get("campaign_id", "campaign-pending"),
        "content_engine": {
            "name": "james-au-social-content-engine",
            "version": "revision-14-project-contract",
            "hash": engine_hash,
            "resolved_from": engine_path.name,
        },
        "skill_route": skill_route,
        "template_recommendations": [
            {
                "template_id": item["template_id"],
                "version": item["version"],
                "content_hash": item["content_hash"],
            }
            for item in recommendations
        ],
        "provider_execution_state": "disabled",
        "publication_state": "not_requested",
        "external_actions": [],
        "not_done": [
            "not researched live",
            "not generated as final copy",
            "not rendered",
            "not uploaded",
            "not scheduled",
            "not published",
        ],
    }
