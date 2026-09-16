#!/usr/bin/env python3
"""Dependency-free structural checks for the portable Codex handoff."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/specs/2026-09-12-james-au-social-media-suite-design.md"
ENGINE = ROOT / "docs/james-au-social-content-engine.md"
RSS_DECISION = ROOT / "docs/candidates/2026-09-12-rss-news-intake-amendment.md"
GRAPHICS_DECISION = ROOT / "docs/candidates/2026-09-12-social-media-graphic-skill-v2-design.md"
GRAPHICS_SKILL = ROOT / "skills/james-au-social-graphics/SKILL.md"
GRAPHICS_PLATFORM_SPECS = ROOT / "skills/james-au-social-graphics/references/platform-output-specs.md"
GRAPHICS_TEMPLATES = ROOT / "skills/james-au-social-graphics/references/template-recipes.md"
GRAPHICS_VALIDATION = ROOT / "skills/james-au-social-graphics/references/asset-contract-and-validation.md"
GUIZANG_DECISION = ROOT / "docs/candidates/2026-09-12-guizang-visual-reference-decision.md"
GUIZANG_CATALOG = ROOT / "skills/james-au-social-graphics/references/guizang-visual-catalog.md"
TEMPLATE_DECISION = ROOT / "docs/candidates/2026-09-12-template-library-amendment.md"
TEMPLATE_DEFAULTS = ROOT / "templates/defaults"
CODEX_AUTOMATION_DECISION = ROOT / "docs/candidates/2026-09-12-codex-native-automation-decision.md"
DISCOVERABILITY_DECISION = ROOT / "docs/candidates/2026-09-12-discoverability-skill-design.md"
DISCOVERABILITY_SKILL = ROOT / "skills/james-au-discoverability/SKILL.md"
DISCOVERABILITY_CONTRACT = ROOT / "skills/james-au-discoverability/references/discoverability-brief-contract.md"
DISCOVERABILITY_PLATFORM_GUIDANCE = ROOT / "skills/james-au-discoverability/references/platform-discovery-guidance.md"
MULTISOURCE_MOTION_DECISION = ROOT / "docs/candidates/2026-09-12-multisource-video-motion-intake-amendment.md"
V14_PLAN = ROOT / "docs/superpowers/plans/2026-09-12-v14-phase-0-skills.md"
V14_PROVIDER_REGISTRY = ROOT / "config/v14-provider-registry.json"
V14_FIXTURE_ROOT = ROOT / "fixtures/v14"
V14_DRY_RUN_RESULT = ROOT / "artifacts/v14-phase0/dry-run-result.json"
V14_IMPLEMENTATION_RECEIPT = ROOT / "artifacts/v14-phase0/IMPLEMENTATION_RECEIPT.md"
V14_SKILL_ROOTS = (
    ROOT / "skills/james-au-source-extraction-providers",
    ROOT / "skills/james-au-video-transcript-intake",
    ROOT / "skills/james-au-transcript-translation",
    ROOT / "skills/james-au-hyperframes-motion",
)
PHASE0B_CANDIDATE = ROOT / "docs/candidates/2026-09-12-phase-0b-orchestrator-installation-candidate.md"
PHASE0B_PLAN = ROOT / "docs/superpowers/plans/2026-09-12-phase-0b-orchestrator-installation.md"
PHASE0B_SOURCE_MANIFEST = ROOT / "config/phase0b-install-manifest.json"
PHASE0B_BUNDLE_ROOT = ROOT / "artifacts/phase0b-installation/bundle"
PHASE0B_BUNDLE_MANIFEST = ROOT / "artifacts/phase0b-installation/bundle-manifest.json"
PHASE0B_INSTALL_CANDIDATE = ROOT / "artifacts/phase0b-installation/GLOBAL_INSTALL_CANDIDATE.json"
PHASE0B_INSTALL_APPROVAL = ROOT / "artifacts/phase0b-installation/GLOBAL_INSTALL_APPROVAL.json"
PHASE0B_INSTALL_RECEIPT = ROOT / "artifacts/phase0b-installation/GLOBAL_INSTALL_RECEIPT.json"
PHASE0B_OFFICIAL_VALIDATION_RECEIPT = ROOT / "artifacts/phase0b-installation/OFFICIAL_VALIDATION_RECEIPT.json"
PHASE0B_IMPLEMENTATION_RECEIPT = ROOT / "artifacts/phase0b-installation/IMPLEMENTATION_RECEIPT.md"
ORCHESTRATOR_UPDATE_DECISION = ROOT / "docs/candidates/2026-09-13-orchestrator-first-run-update.md"
ORCHESTRATOR_UPDATE_ROOT = ROOT / "artifacts/orchestrator-v14-first-run-update"
ORCHESTRATOR_UPDATE_CANDIDATE = ORCHESTRATOR_UPDATE_ROOT / "candidate.json"
ORCHESTRATOR_UPDATE_APPROVAL = ORCHESTRATOR_UPDATE_ROOT / "approval.json"
ORCHESTRATOR_UPDATE_RECEIPT = ORCHESTRATOR_UPDATE_ROOT / "install-receipt.json"
ORCHESTRATOR_UPDATE_PACKAGE = ORCHESTRATOR_UPDATE_ROOT / "bundle/james-au-social-orchestrator"
ORCHESTRATOR_UPDATE_BACKUP = ORCHESTRATOR_UPDATE_ROOT / "backup/james-au-social-orchestrator"
PHASE0B_SKILL_ROOTS = (
    ROOT / "skills/james-au-social-orchestrator",
    ROOT / "skills/james-au-template-library",
    *V14_SKILL_ROOTS,
    ROOT / "skills/james-au-social-graphics",
    ROOT / "skills/james-au-discoverability",
)

REQUIRED_FILES = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "PROJECT_STATE.md",
    ROOT / ".env.example",
    ROOT / ".gitignore",
    ENGINE,
    SPEC,
    RSS_DECISION,
    GRAPHICS_DECISION,
    GRAPHICS_SKILL,
    GRAPHICS_PLATFORM_SPECS,
    GRAPHICS_TEMPLATES,
    GRAPHICS_VALIDATION,
    GUIZANG_DECISION,
    GUIZANG_CATALOG,
    TEMPLATE_DECISION,
    CODEX_AUTOMATION_DECISION,
    DISCOVERABILITY_DECISION,
    DISCOVERABILITY_SKILL,
    DISCOVERABILITY_CONTRACT,
    DISCOVERABILITY_PLATFORM_GUIDANCE,
    MULTISOURCE_MOTION_DECISION,
    V14_PLAN,
    V14_PROVIDER_REGISTRY,
    V14_DRY_RUN_RESULT,
    V14_IMPLEMENTATION_RECEIPT,
    ROOT / "src/__init__.py",
    ROOT / "src/james_au_social/__init__.py",
    ROOT / "src/james_au_social/canonical.py",
    ROOT / "src/james_au_social/contracts.py",
    ROOT / "src/james_au_social/provider_registry.py",
    ROOT / "src/james_au_social/transcript_pipeline.py",
    ROOT / "src/james_au_social/motion_planner.py",
    ROOT / "src/james_au_social/conversation.py",
    ROOT / "src/james_au_social/dry_run.py",
    ROOT / "fixtures/v14/supported-article.json",
    ROOT / "fixtures/v14/caption-tracks.json",
    ROOT / "fixtures/v14/source-transcript.json",
    ROOT / "fixtures/v14/transcript-translation.json",
    ROOT / "fixtures/v14/motion-request.json",
    ROOT / "tests/__init__.py",
    ROOT / "tests/test_contracts.py",
    ROOT / "tests/test_provider_registry.py",
    ROOT / "tests/test_transcript_pipeline.py",
    ROOT / "tests/test_motion_planner.py",
    ROOT / "tests/test_conversation.py",
    ROOT / "tests/test_v14_acceptance.py",
    ROOT / "tests/test_project_verifier.py",
    PHASE0B_CANDIDATE,
    PHASE0B_PLAN,
    PHASE0B_SOURCE_MANIFEST,
    PHASE0B_BUNDLE_MANIFEST,
    PHASE0B_INSTALL_CANDIDATE,
    PHASE0B_IMPLEMENTATION_RECEIPT,
    ORCHESTRATOR_UPDATE_DECISION,
    ORCHESTRATOR_UPDATE_CANDIDATE,
    ORCHESTRATOR_UPDATE_APPROVAL,
    ORCHESTRATOR_UPDATE_RECEIPT,
    ORCHESTRATOR_UPDATE_PACKAGE / "SKILL.md",
    ORCHESTRATOR_UPDATE_PACKAGE / "scripts/first_run.py",
    ORCHESTRATOR_UPDATE_PACKAGE / "scripts/james_au_social/onboarding.py",
    ORCHESTRATOR_UPDATE_BACKUP / "SKILL.md",
    ROOT / "src/james_au_social/install_manifest.py",
    ROOT / "src/james_au_social/template_library.py",
    ROOT / "src/james_au_social/orchestrator.py",
    ROOT / "src/james_au_social/install_verifier.py",
    ROOT / "scripts/build_phase0b_skill_bundle.py",
    ROOT / "scripts/install_phase0b_skills.py",
    ROOT / "scripts/verify_phase0b_install.py",
    ROOT / "scripts/build_orchestrator_update_candidate.py",
    ROOT / "scripts/install_approved_orchestrator_update.py",
    ROOT / "fixtures/phase0b/instagram-article-request.json",
    ROOT / "fixtures/phase0b/xiaohongshu-article-request.json",
    ROOT / "fixtures/phase0b/video-analysis-request.json",
    ROOT / "fixtures/phase0b/saved-template-input.md",
    ROOT / "tests/test_install_manifest.py",
    ROOT / "tests/test_template_library.py",
    ROOT / "tests/test_orchestrator.py",
    ROOT / "tests/test_phase0b_bundle.py",
    ROOT / "tests/test_phase0b_installer.py",
    ROOT / "tests/test_phase0b_project_verifier.py",
    ROOT / "tests/test_first_run_onboarding.py",
    ROOT / "tests/test_orchestrator_update_candidate.py",
]

for skill_root in V14_SKILL_ROOTS:
    REQUIRED_FILES.extend(
        [
            skill_root / "SKILL.md",
            next((skill_root / "references").glob("*.md"), skill_root / "references/missing.md"),
        ]
    )

for skill_root in PHASE0B_SKILL_ROOTS[:2]:
    REQUIRED_FILES.extend(
        [
            skill_root / "SKILL.md",
            skill_root / "agents/openai.yaml",
            next(
                (skill_root / "references").glob("*.md"),
                skill_root / "references/missing.md",
            ),
        ]
    )

PLATFORMS = [
    "YouTube",
    "Instagram",
    "Facebook",
    "LinkedIn",
    "X",
    "TikTok",
    "Threads",
    "Xiaohongshu",
    "Douyin",
    "WeChat Channels",
    "Bilibili",
    "Reddit",
    "Pinterest",
    "Bluesky",
    "Telegram",
    "Google Business Profile",
    "Discord",
    "Feishu / Lark",
    "Weibo",
    "Zhihu",
    "Tencent QQ",
    "Pixelfed",
    "Mastodon",
    "Snapchat",
    "WhatsApp Channels",
    "LINE Official Account",
    "note",
    "ShareChat",
    "Moj",
    "KakaoTalk Channel",
    "Naver Blog",
    "Kuaishou",
    "Dcard",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def verify_required_files() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    if missing:
        fail(f"missing required files: {', '.join(missing)}")
    print(f"PASS: {len(REQUIRED_FILES)} required files present")


def verify_json_fences(spec_text: str) -> None:
    blocks = re.findall(r"```json\s*\n(.*?)\n```", spec_text, flags=re.DOTALL)
    if not blocks:
        fail("design spec contains no fenced JSON examples")
    for index, block in enumerate(blocks, start=1):
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            fail(f"JSON block {index} is invalid: {exc}")
    print(f"PASS: {len(blocks)} fenced JSON blocks parse")


def verify_multisource_motion_candidate() -> None:
    text = MULTISOURCE_MOTION_DECISION.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, flags=re.DOTALL)
    if len(blocks) != 5:
        fail(f"expected 5 JSON contracts in multisource/motion candidate, found {len(blocks)}")
    for index, block in enumerate(blocks, start=1):
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            fail(f"multisource/motion candidate JSON block {index} is invalid: {exc}")
    required = (
        "NewsCrawler",
        "XhsSkills",
        "yt-dlp",
        "HyperFrames",
        "reference_only",
        "VideoTranscriptArtifact",
        "TranscriptTranslationArtifact",
        "MotionVideoJob",
        "faceless-explainer",
        "merged into design specification revision 14",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        fail(f"multisource/motion candidate missing: {', '.join(missing)}")
    print("PASS: multisource/video/motion candidate has 5 valid contracts and safety markers")


def verify_platforms(spec_text: str) -> None:
    missing = [name for name in PLATFORMS if f"### {name}\n" not in spec_text]
    if missing:
        fail(f"missing platform adapter headings: {', '.join(missing)}")
    print(f"PASS: all {len(PLATFORMS)} platform adapter headings present")


def verify_handoff_markers(spec_text: str, engine_text: str) -> None:
    markers = {
        "revision 14": "revision 14" in spec_text.lower(),
        "default email": "jamesaucreates@gmail.com" in spec_text,
        "RedFox variable": "REDFOX_API_KEY" in spec_text,
        "Xiaohongshu MCP variable": "XIAOHONGSHU_MCP_AUTH_TOKEN" in spec_text,
        "builder and musician voice": "builder" in engine_text.lower()
        and "musician" in engine_text.lower(),
        "RSS intake skill": "james-au-rss-news-intake" in spec_text,
        "RSS source registry": "RSS source registry" in spec_text,
        "breaking-news state": "awaiting_primary_source" in spec_text,
        "social graphics skill": "james-au-social-graphics" in spec_text,
        "graphics constraints boundary": "platform_constraints_unverified" in spec_text,
        "discoverability skill": "james-au-discoverability" in spec_text,
        "discoverability contract": "DiscoverabilityBrief" in spec_text,
        "search social distinction": "owned_search" in spec_text
        and "social_discovery" in spec_text,
        "no guaranteed virality": "never promises ranking or virality" in spec_text.lower(),
        "template library": "james-au-template-library" in spec_text,
        "Guizang reviewed commit": "cf4b810fac1c73fb65a2bb31d8c9278d82cbc4c5" in spec_text,
        "Guizang reference only": "reference_only" in spec_text,
        "Codex automation run": "CodexAutomationRun" in spec_text,
        "Codex heartbeat default": "thread heartbeat" in spec_text.lower(),
        "post approval action": "post_approval_action" in spec_text,
        "canonical JSON hashing": "RFC 8785/JCS" in spec_text,
        "automation control request": "AutomationControlRequest" in spec_text,
        "recipe activation receipt": "RecipeActivationReceipt" in spec_text,
        "remote media upload contract": "MediaUploadJob" in spec_text,
        "manual asset handoff": "AssetHandoffTarget" in spec_text,
        "analytics provenance": "AnalyticsObservation" in spec_text,
        "source acquisition provider": "SourceAcquisitionProvider" in spec_text,
        "NewsCrawler reviewed pin": "25fb3b4a20186905f5ce38f7a7f854050d402253" in spec_text,
        "XhsSkills reviewed pin": "138288d2f288e125a5b0c3aad7efecf6b74b51d9" in spec_text,
        "yt-dlp reviewed pin": "bbc809a1161d3bfca51fa36f59dda35556ee85a0" in spec_text,
        "video source contract": "VideoSourceArtifact" in spec_text,
        "video transcript contract": "VideoTranscriptArtifact" in spec_text,
        "translation contract": "TranscriptTranslationArtifact" in spec_text,
        "motion job contract": "MotionVideoJob" in spec_text,
        "HyperFrames route": "faceless-explainer" in spec_text,
        "coverage guarantee boundary": "literally real-time, exhaustive, or comprehensive" in spec_text,
    }
    missing = [name for name, found in markers.items() if not found]
    if missing:
        fail(f"missing handoff markers: {', '.join(missing)}")
    print(f"PASS: {len(markers)} handoff markers present")


def section_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        fail(f"missing section: {start}")
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        fail(f"missing section boundary after {start}: {end}")
    return text[start_index:end_index]


def verify_revision_14_contracts(spec_text: str, engine_text: str) -> None:
    ambiguous_approval_terms = (
        "matching_recipe",
        "authorized_by_recipe",
        "matching recipe authorization",
        "active-recipe authorization",
    )
    present_ambiguous_terms = [term for term in ambiguous_approval_terms if term in spec_text]
    if present_ambiguous_terms:
        fail(f"ambiguous recipe-as-publish-approval wording remains: {', '.join(present_ambiguous_terms)}")

    recipe = section_between(spec_text, "### 5.7 `AutomationRecipe`", "### 5.7.1")
    required_recipe_fields = (
        '"misfire_policy"',
        '"overlap_policy"',
        '"next_due_at"',
        '"cursor_ref"',
        '"template_policy"',
        '"notification_policy"',
        '"cost_policy"',
        '"recipe_expires_at"',
    )
    missing_recipe_fields = [field for field in required_recipe_fields if field not in recipe]
    if missing_recipe_fields:
        fail(f"revision 14 AutomationRecipe missing: {', '.join(missing_recipe_fields)}")
    if '"authorization_expires_at"' in recipe:
        fail("AutomationRecipe incorrectly owns route authorization expiry")

    activation = section_between(spec_text, "### 5.7.1 `RecipeActivationReceipt`", "### 5.7.2")
    if "never satisfies `PublishJob.approval_id`" not in activation:
        fail("RecipeActivationReceipt is not explicitly separated from publish approval")

    run = section_between(spec_text, "### 5.7.2 `CodexAutomationRun`", "### 5.8 `PublishJob`")
    required_run_fields = (
        "| rejected |",
        "| superseded |",
        "| cancelled",
        '"automation_ref"',
        '"run_idempotency_key"',
        '"publish_job_ids"',
    )
    missing_run_fields = [field for field in required_run_fields if field not in run]
    if missing_run_fields:
        fail(f"revision 14 CodexAutomationRun missing: {', '.join(missing_run_fields)}")

    approval = section_between(spec_text, "### 5.10 `ApprovalReceipt`", "### 5.11")
    if '"automation_recipe"' in approval:
        fail("ApprovalReceipt still conflates campaign approval with recipe activation")
    for field in ('"approval_payload_hash_schema"', '"approval_payload_hash"'):
        if field not in approval:
            fail(f"ApprovalReceipt missing {field}")

    media = section_between(spec_text, "### 5.8.1 Remote media upload contracts", "### 5.9")
    for marker in ("media_upload_job_id", "media_upload_attempt_id", "orphan_policy", "ambiguous_after_upload"):
        if marker not in media:
            fail(f"remote media contract missing {marker}")

    templates = section_between(spec_text, "### 5.18 Template library", "## 6.")
    for marker in (
        '"display_name"',
        '"eligible_brand_identities"',
        '"required_inputs"',
        '"preview_ref"',
        '"selection_source"',
        "project-local Guizang-informed",
        "AssetHandoffTarget",
        "AnalyticsObservation",
    ):
        if marker not in templates:
            fail(f"revision 14 template/handoff/analytics contract missing {marker}")

    provider = section_between(spec_text, "### 5.20 `SourceAcquisitionProvider`", "### 5.21")
    for marker in (
        '"provider_state"',
        '"allowed_operations"',
        '"denied_operations"',
        '"license_state"',
        '"terms_and_robots_review"',
        '"expires_at"',
        "Raw cookies never enter chat",
    ):
        if marker not in provider:
            fail(f"revision 14 source provider contract missing {marker}")

    video_source = section_between(spec_text, "### 5.21 `VideoSourceArtifact`", "### 5.22")
    for marker in ('"provider_commit_or_version"', '"rights_and_terms_note"', '"not_downloaded"'):
        if marker not in video_source:
            fail(f"revision 14 video source contract missing {marker}")

    transcript = section_between(spec_text, "### 5.22 `VideoTranscriptArtifact`", "### 5.23")
    for marker in ('"caption_source"', '"segments"', '"transcript_hash"', '"not_done"'):
        if marker not in transcript:
            fail(f"revision 14 transcript contract missing {marker}")

    translation = section_between(spec_text, "### 5.23 `TranscriptTranslationArtifact`", "### 5.24")
    for marker in ('"source_transcript_hash"', '"translation_provider_version"', '"omissions_or_uncertainties"'):
        if marker not in translation:
            fail(f"revision 14 translation contract missing {marker}")

    motion = section_between(spec_text, "### 5.24 `MotionVideoJob`", "## 6.")
    for marker in (
        '"hyperframes_version"',
        '"storyboard_hash"',
        '"composition_hash"',
        '"visual_review"',
        '"audio_review"',
        '"not_done"',
    ):
        if marker not in motion:
            fail(f"revision 14 motion contract missing {marker}")

    engine_markers = (
        "tracked remote-media upload",
        "reconcile an ambiguous upload",
        "One post is an observation",
        "Preserve the original timestamped transcript as an immutable source artifact",
        "faceless-explainer",
        "A rendered local MP4 is not uploaded, scheduled, published, or verified",
    )
    missing_engine_markers = [marker for marker in engine_markers if marker not in engine_text]
    if missing_engine_markers:
        fail(f"content engine missing revision 14 boundary: {', '.join(missing_engine_markers)}")

    print("PASS: revision 14 automation, provider, transcript, motion, approval, upload, template, handoff, and analytics contracts")


def verify_template_catalog() -> None:
    defaults = sorted(TEMPLATE_DEFAULTS.glob("*.md"))
    if len(defaults) != 6:
        fail(f"expected 6 active default templates, found {len(defaults)}")
    required_frontmatter = (
        "template_id:",
        "version:",
        "status: active",
        "kind:",
        "source_types:",
        "output_families:",
        "languages:",
    )
    for path in defaults:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            fail(f"template lacks front matter: {path.relative_to(ROOT)}")
        frontmatter = text.split("---", 2)[1]
        missing = [key for key in required_frontmatter if key not in frontmatter]
        if missing:
            fail(f"template {path.name} missing: {', '.join(missing)}")

    catalog = GUIZANG_CATALOG.read_text(encoding="utf-8")
    missing_layouts = [f"M{i:02d}" for i in range(1, 17) if f"`M{i:02d}`" not in catalog]
    missing_layouts += [f"S{i:02d}" for i in range(1, 13) if f"`S{i:02d}`" not in catalog]
    theme_ids = (
        "editorial.ink-classic",
        "editorial.indigo-porcelain",
        "editorial.forest-ink",
        "editorial.kraft-paper",
        "editorial.dune",
        "editorial.midnight-ink",
        "swiss.ikb",
        "swiss.lemon-yellow",
        "swiss.lemon-green",
        "swiss.safety-orange",
    )
    missing_themes = [theme for theme in theme_ids if f"`{theme}`" not in catalog]
    if missing_layouts or missing_themes:
        fail(
            "Guizang catalog incomplete: "
            f"layouts={missing_layouts}, themes={missing_themes}"
        )
    print("PASS: 6 active templates and complete Guizang 28-layout/10-theme catalog")


def _validate_skill_package(skill_root: Path) -> None:
    skill_file = skill_root / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n") or text.count("---") < 2:
        fail(f"skill frontmatter missing: {skill_root.name}")
    frontmatter = text.split("---", 2)[1]
    expected_name = f"name: {skill_root.name}"
    if expected_name not in frontmatter or "description:" not in frontmatter:
        fail(f"skill frontmatter invalid: {skill_root.name}")
    if re.search(r"\b(TODO|TBD|fill in)\b", text, flags=re.IGNORECASE):
        fail(f"skill contains unfinished placeholder: {skill_root.name}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith(("#", "/")):
            continue
        if not (skill_root / target.split("#", 1)[0]).resolve().is_file():
            fail(f"skill link missing: {skill_root.name} -> {target}")


def verify_v14_phase0_implementation() -> dict[str, int]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.james_au_social.dry_run import run_v14_dry_run
    from src.james_au_social.provider_registry import ProviderRegistry
    from tests.test_v14_acceptance import V14AcceptanceTests

    for path in REQUIRED_FILES:
        if not path.is_file():
            fail(f"V14 Phase 0 artifact missing: {path.relative_to(ROOT)}")

    for skill_root in V14_SKILL_ROOTS:
        _validate_skill_package(skill_root)

    registry = ProviderRegistry.from_file(V14_PROVIDER_REGISTRY)
    expected_states = {
        "newscrawler.news-extractor": "candidate_read_only",
        "xhsskills.xhs-apis": "reference_only",
        "ytdlp": "candidate_read_only",
        "hyperframes.local": "available_local_skill_unbound",
    }
    if registry.provider_ids() != tuple(sorted(expected_states)):
        fail("V14 provider registry does not contain the exact four reviewed providers")
    for provider_id, state in expected_states.items():
        if registry.get(provider_id)["provider_state"] != state:
            fail(f"V14 provider state mismatch: {provider_id}")
    if registry.get("xhsskills.xhs-apis")["allowed_operations"] != []:
        fail("XhsSkills exposes an executable operation")

    result = run_v14_dry_run(V14_FIXTURE_ROOT)
    stored_result = json.loads(V14_DRY_RUN_RESULT.read_text(encoding="utf-8"))
    if result != stored_result:
        fail("stored V14 dry-run result is stale")
    if result.get("execution_state") != "dry_run":
        fail("V14 run is not labelled dry_run")
    side_effects = result.get("external_side_effects")
    if side_effects != []:
        fail("V14 dry run reports external side effects")
    expected_ratios = ["16:9", "1:1", "9:16"]
    ratios = [item["aspect_ratio"] for item in result["motion_job"]["variants"]]
    if ratios != expected_ratios:
        fail(f"V14 native ratios mismatch: {ratios}")
    if result["translation"]["source_transcript_hash"] != result["transcript"]["transcript_hash"]:
        fail("V14 translation does not bind the immutable source transcript hash")

    fixture_count = len(list(V14_FIXTURE_ROOT.glob("*.json")))
    acceptance_count = unittest.defaultTestLoader.loadTestsFromTestCase(
        V14AcceptanceTests
    ).countTestCases()
    summary = {
        "skill_count": len(V14_SKILL_ROOTS),
        "fixture_count": fixture_count,
        "acceptance_test_count": acceptance_count,
        "external_side_effect_count": len(side_effects),
    }
    return summary


def verify_phase0b_implementation() -> dict[str, int | str]:
    import tempfile

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src.james_au_social.install_manifest import (
        INSTALL_SKILL_IDS,
        canonical_file_inventory,
        load_install_manifest,
        tree_hash,
    )
    from src.james_au_social.install_verifier import (
        apply_install,
        plan_install,
        verify_install,
    )
    from src.james_au_social.template_library import (
        load_template_catalog,
        template_creator_bridge_state,
    )

    phase0b_required = [
        PHASE0B_CANDIDATE,
        PHASE0B_PLAN,
        PHASE0B_SOURCE_MANIFEST,
        PHASE0B_BUNDLE_MANIFEST,
        PHASE0B_INSTALL_CANDIDATE,
        PHASE0B_OFFICIAL_VALIDATION_RECEIPT,
        PHASE0B_IMPLEMENTATION_RECEIPT,
        ROOT / "src/james_au_social/install_manifest.py",
        ROOT / "src/james_au_social/template_library.py",
        ROOT / "src/james_au_social/orchestrator.py",
        ROOT / "src/james_au_social/install_verifier.py",
        ROOT / "scripts/build_phase0b_skill_bundle.py",
        ROOT / "scripts/install_phase0b_skills.py",
        ROOT / "scripts/verify_phase0b_install.py",
        ROOT / "tests/test_phase0b_project_verifier.py",
    ]
    for skill_root in PHASE0B_SKILL_ROOTS:
        phase0b_required.append(skill_root / "SKILL.md")
    for path in phase0b_required:
        if not path.is_file():
            fail(f"Phase 0B artifact missing: {path.relative_to(ROOT)}")

    source_manifest = load_install_manifest(PHASE0B_SOURCE_MANIFEST, ROOT)
    if tuple(source_manifest["skill_ids"]) != INSTALL_SKILL_IDS:
        fail("Phase 0B source manifest skill list drifted")
    for skill_root in PHASE0B_SKILL_ROOTS:
        _validate_skill_package(skill_root)

    if not PHASE0B_BUNDLE_ROOT.is_dir():
        fail("Phase 0B bundle root is missing")
    bundle_children = sorted(path.name for path in PHASE0B_BUNDLE_ROOT.iterdir())
    if bundle_children != sorted(INSTALL_SKILL_IDS):
        fail("Phase 0B bundle does not contain the exact eight skill roots")
    bundle_manifest = json.loads(PHASE0B_BUNDLE_MANIFEST.read_text(encoding="utf-8"))
    computed_bundle_hash = tree_hash(canonical_file_inventory(PHASE0B_BUNDLE_ROOT))
    if computed_bundle_hash != bundle_manifest.get("bundle_hash"):
        fail("Phase 0B bundle manifest hash is stale")
    if bundle_manifest.get("template_count") != 6:
        fail("Phase 0B bundle template count is not six")
    if bundle_manifest.get("external_side_effects") != []:
        fail("Phase 0B bundle reports external side effects")

    candidate = json.loads(PHASE0B_INSTALL_CANDIDATE.read_text(encoding="utf-8"))
    if candidate.get("bundle_hash") != computed_bundle_hash:
        fail("Phase 0B global-install candidate hash is stale")
    if tuple(candidate.get("skill_ids", ())) != INSTALL_SKILL_IDS:
        fail("Phase 0B global-install candidate skill list drifted")
    if candidate.get("destination") != "/Users/ouxianxing/.codex/skills":
        fail("Phase 0B global-install destination drifted")
    if candidate.get("global_install_state") != "not_installed":
        fail("Phase 0B candidate incorrectly claims a global install")
    if candidate.get("write_state") != "not_executed":
        fail("Phase 0B candidate incorrectly claims a global write")
    if candidate.get("external_side_effects") != []:
        fail("Phase 0B candidate reports external side effects")

    templates = load_template_catalog(ROOT / "templates/defaults")
    if len(templates) != 6:
        fail("Phase 0B source template catalog is not six")
    bridge = template_creator_bridge_state(False)
    if bridge.get("state") != "unavailable" or "artifact_reference" in bridge:
        fail("Phase 0B Template Creator bridge fabricates availability")

    live_plan = plan_install(
        PHASE0B_BUNDLE_ROOT, Path("/Users/ouxianxing/.codex/skills")
    )
    candidate_states = {
        item["skill_id"]: item["state"] for item in candidate.get("targets", [])
    }
    live_states = {item["skill_id"]: item["state"] for item in live_plan["targets"]}
    if candidate_states == live_states:
        global_install_state = "not_installed"
        conflict_count = sum(state == "conflict" for state in live_states.values())
    elif set(live_states.values()) == {"already_installed"}:
        for path in (PHASE0B_INSTALL_APPROVAL, PHASE0B_INSTALL_RECEIPT):
            if not path.is_file():
                fail(f"Phase 0B global-install evidence missing: {path.relative_to(ROOT)}")
        approval = json.loads(PHASE0B_INSTALL_APPROVAL.read_text(encoding="utf-8"))
        receipt = json.loads(PHASE0B_INSTALL_RECEIPT.read_text(encoding="utf-8"))
        expected_install_fields = {
            "bundle_hash": computed_bundle_hash,
            "destination": live_plan["destination"],
        }
        for field, expected in expected_install_fields.items():
            if approval.get(field) != expected or receipt.get(field) != expected:
                fail(f"Phase 0B global-install {field} does not match the bundle")
        if approval.get("approval_state") != "approved":
            fail("Phase 0B global install lacks an approved receipt")
        if tuple(approval.get("skill_ids", ())) != INSTALL_SKILL_IDS:
            fail("Phase 0B global-install approval skill list drifted")
        if receipt.get("state") != "verified":
            fail("Phase 0B global-install receipt is not verified")
        if tuple(receipt.get("installed_skill_ids", ())) != INSTALL_SKILL_IDS:
            fail("Phase 0B global-install receipt skill list drifted")
        if approval.get("external_side_effects", []) != []:
            fail("Phase 0B global-install approval reports external side effects")
        if receipt.get("external_side_effects") != []:
            fail("Phase 0B global-install receipt reports external side effects")
        installed = verify_install(Path(str(live_plan["destination"])), PHASE0B_BUNDLE_ROOT)
        if installed.get("state") != "verified":
            fail("Phase 0B global installed bundle did not verify")
        global_install_state = "installed_verified"
        conflict_count = 0
    elif (
        live_states.get("james-au-social-orchestrator") == "conflict"
        and all(
            state == "already_installed"
            for skill_id, state in live_states.items()
            if skill_id != "james-au-social-orchestrator"
        )
    ):
        for path in (
            ORCHESTRATOR_UPDATE_CANDIDATE,
            ORCHESTRATOR_UPDATE_APPROVAL,
            ORCHESTRATOR_UPDATE_RECEIPT,
            ORCHESTRATOR_UPDATE_PACKAGE,
            ORCHESTRATOR_UPDATE_BACKUP,
        ):
            if not path.exists():
                fail(
                    "Approved orchestrator update evidence missing: "
                    f"{path.relative_to(ROOT)}"
                )
        update_candidate = json.loads(
            ORCHESTRATOR_UPDATE_CANDIDATE.read_text(encoding="utf-8")
        )
        update_approval = json.loads(
            ORCHESTRATOR_UPDATE_APPROVAL.read_text(encoding="utf-8")
        )
        update_receipt = json.loads(
            ORCHESTRATOR_UPDATE_RECEIPT.read_text(encoding="utf-8")
        )
        old_orchestrator_hash = tree_hash(
            canonical_file_inventory(
                PHASE0B_BUNDLE_ROOT / "james-au-social-orchestrator"
            )
        )
        candidate_orchestrator_hash = tree_hash(
            canonical_file_inventory(ORCHESTRATOR_UPDATE_PACKAGE)
        )
        installed_orchestrator = (
            Path(str(live_plan["destination"])) / "james-au-social-orchestrator"
        )
        installed_orchestrator_hash = tree_hash(
            canonical_file_inventory(installed_orchestrator)
        )
        backup_hash = tree_hash(canonical_file_inventory(ORCHESTRATOR_UPDATE_BACKUP))
        if update_candidate.get("state") != "candidate_not_installed":
            fail("Orchestrator update candidate state is invalid")
        if update_candidate.get("replacement_scope") != [
            "james-au-social-orchestrator"
        ]:
            fail("Orchestrator update replacement scope drifted")
        if update_candidate.get("expected_installed_tree_hash") != old_orchestrator_hash:
            fail("Orchestrator update expected old hash drifted")
        if update_candidate.get("candidate_tree_hash") != candidate_orchestrator_hash:
            fail("Orchestrator update candidate hash drifted")
        if update_candidate.get("candidate_files") != canonical_file_inventory(
            ORCHESTRATOR_UPDATE_PACKAGE
        ):
            fail("Orchestrator update file inventory drifted")
        if update_approval.get("approval_state") != "approved":
            fail("Orchestrator update lacks explicit approval")
        if update_approval.get("approval_scope") != [
            "james-au-social-orchestrator"
        ]:
            fail("Orchestrator update approval scope drifted")
        if update_approval.get("approved_candidate_tree_hash") != candidate_orchestrator_hash:
            fail("Orchestrator update approval hash drifted")
        if update_approval.get("approved_expected_installed_tree_hash") != old_orchestrator_hash:
            fail("Orchestrator update approval old hash drifted")
        if update_receipt.get("state") != "installed_hash_verified":
            fail("Orchestrator update receipt is not verified")
        if update_receipt.get("previous_tree_hash") != old_orchestrator_hash:
            fail("Orchestrator update receipt old hash drifted")
        if update_receipt.get("installed_tree_hash") != candidate_orchestrator_hash:
            fail("Orchestrator update receipt candidate hash drifted")
        if update_receipt.get("backup_tree_hash") != old_orchestrator_hash:
            fail("Orchestrator update backup receipt hash drifted")
        if backup_hash != old_orchestrator_hash:
            fail("Orchestrator update backup bytes drifted")
        if installed_orchestrator_hash != candidate_orchestrator_hash:
            fail("Installed orchestrator does not match approved candidate")
        if update_receipt.get("external_account_actions") != []:
            fail("Orchestrator update receipt reports external account actions")
        _validate_skill_package(installed_orchestrator)
        global_install_state = "installed_verified_with_orchestrator_update"
        conflict_count = 0
    else:
        fail("Phase 0B destination state changed outside the approved install")

    official_validation = json.loads(
        PHASE0B_OFFICIAL_VALIDATION_RECEIPT.read_text(encoding="utf-8")
    )
    if official_validation.get("state") != "official_validation_passed":
        fail("Phase 0B official validation receipt is not passed")
    if official_validation.get("bundle_hash") != computed_bundle_hash:
        fail("Phase 0B official validation receipt hash drifted")
    if official_validation.get("destination") != live_plan["destination"]:
        fail("Phase 0B official validation receipt destination drifted")
    if official_validation.get("dependency_environment") != "uv_isolated":
        fail("Phase 0B official validator did not use the isolated environment")
    if official_validation.get("global_python_modified") is not False:
        fail("Phase 0B official validation modified global Python")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(official_validation.get("pyyaml_version", ""))):
        fail("Phase 0B official validation lacks an exact PyYAML version")
    if official_validation.get("external_side_effects") != []:
        fail("Phase 0B official validation reports external side effects")
    official_results = official_validation.get("skill_results", [])
    if tuple(item.get("skill_id") for item in official_results) != INSTALL_SKILL_IDS:
        fail("Phase 0B official validation skill list drifted")
    if any(
        item.get("state") != "passed" or item.get("result") != "Skill is valid!"
        for item in official_results
    ):
        fail("Phase 0B official validation contains a failed skill")

    with tempfile.TemporaryDirectory() as temp:
        destination = Path(temp) / "skills"
        temporary_plan = plan_install(PHASE0B_BUNDLE_ROOT, destination)
        approval = {
            "approval_id": "project-verifier-temporary-install",
            "approval_state": "approved",
            "bundle_hash": temporary_plan["bundle_hash"],
            "skill_ids": list(INSTALL_SKILL_IDS),
            "destination": str(destination.resolve()),
            "approved_at": "2026-09-12T20:30:00+00:00",
            "expires_at": "2099-09-12T21:30:00+00:00",
        }
        apply_install(PHASE0B_BUNDLE_ROOT, destination, approval)
        isolated = verify_install(destination, PHASE0B_BUNDLE_ROOT)
        if isolated.get("state") != "verified":
            fail("Phase 0B isolated install did not verify")

    return {
        "skill_count": len(INSTALL_SKILL_IDS),
        "template_count": len(templates),
        "global_install_state": global_install_state,
        "official_validation_state": "passed",
        "destination_conflict_count": conflict_count,
        "external_side_effect_count": 0,
    }


def verify_env_template() -> None:
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(env_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f".env.example line {line_number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        if key == "PRIMARY_LOGIN_EMAIL":
            if value != "jamesaucreates@gmail.com":
                fail("PRIMARY_LOGIN_EMAIL does not match the approved default")
        elif value:
            fail(f"secret placeholder {key} must be empty")
    print("PASS: environment template contains no populated secret placeholders")


def main() -> int:
    verify_required_files()
    verify_multisource_motion_candidate()
    spec_text = SPEC.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    verify_json_fences(spec_text)
    verify_platforms(spec_text)
    verify_handoff_markers(spec_text, engine_text)
    verify_revision_14_contracts(spec_text, engine_text)
    verify_template_catalog()
    v14_summary = verify_v14_phase0_implementation()
    print(
        "PASS: V14 Phase 0 implementation has "
        f"{v14_summary['skill_count']} skills, "
        f"{v14_summary['fixture_count']} fixtures, "
        f"{v14_summary['acceptance_test_count']} acceptance tests, and "
        f"{v14_summary['external_side_effect_count']} external side effects"
    )
    phase0b_summary = verify_phase0b_implementation()
    print(
        "PASS: Phase 0B bundle has "
        f"{phase0b_summary['skill_count']} portable skills, "
        f"{phase0b_summary['template_count']} templates, "
        f"{phase0b_summary['destination_conflict_count']} destination conflicts, "
        f"global state {phase0b_summary['global_install_state']}, and "
        f"official validation {phase0b_summary['official_validation_state']}, with "
        f"{phase0b_summary['external_side_effect_count']} external side effects"
    )
    verify_env_template()
    print("PASS: portable Codex project verification complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
