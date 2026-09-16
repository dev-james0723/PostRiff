"""Offline end-to-end revision 14 fixture orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import validate_contract
from .motion_planner import plan_motion_job
from .provider_registry import ProviderRegistry
from .transcript_pipeline import (
    build_video_source,
    plan_asr_fallback,
    select_caption_track,
    validate_translation_alignment,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILES = {
    "article": "supported-article.json",
    "captions": "caption-tracks.json",
    "transcript": "source-transcript.json",
    "translation": "transcript-translation.json",
    "motion": "motion-request.json",
}


def _inside_repository(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("path_outside_repository")
    return resolved


def _load_fixtures(fixture_root: Path) -> dict[str, object]:
    root = fixture_root if fixture_root.is_absolute() else REPOSITORY_ROOT / fixture_root
    root = _inside_repository(root)
    loaded: dict[str, object] = {}
    for key, name in FIXTURE_FILES.items():
        path = _inside_repository(root / name)
        if not path.is_file():
            raise ValueError(f"missing_fixture:{name}")
        loaded[key] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def run_v14_dry_run(fixture_root: Path) -> dict[str, object]:
    fixtures = _load_fixtures(fixture_root)
    registry = ProviderRegistry.from_file(REPOSITORY_ROOT / "config/v14-provider-registry.json")

    decisions = {
        "newscrawler.news-extractor": registry.evaluate(
            "newscrawler.news-extractor", "extract_public_url"
        ),
        "xhsskills.xhs-apis": registry.evaluate(
            "xhsskills.xhs-apis", "search_public_notes"
        ),
        "ytdlp": registry.evaluate("ytdlp", "list_caption_tracks"),
        "hyperframes.local": registry.evaluate(
            "hyperframes.local", "plan_motion_video"
        ),
    }
    accepted_decisions = {"dry_run_only", "denied"}
    if any(item.decision not in accepted_decisions for item in decisions.values()):
        raise ValueError("unexpected_provider_decision")

    article = fixtures["article"]
    captions = fixtures["captions"]
    transcript = validate_contract("video_transcript_artifact", fixtures["transcript"])
    translation = validate_contract(
        "transcript_translation_artifact", fixtures["translation"]
    )
    alignment_errors = validate_translation_alignment(transcript, translation)
    if alignment_errors:
        raise ValueError("fixture_translation_misaligned:" + ",".join(alignment_errors))
    selected = select_caption_track(captions["tracks"], ["en"])
    if selected.caption_source != transcript["caption_source"]:
        raise ValueError("fixture_caption_selection_mismatch")

    video_source = build_video_source(
        {
            "video_source_id": transcript["video_source_id"],
            "source_url": "https://example.invalid/watch?v=ai-science-fixture",
            "platform": "youtube",
            "provider_commit_or_version": registry.get("ytdlp")["reviewed_commit"],
            "title": "Offline AI for Science fixture",
            "publisher_or_channel": "Fixture Lab",
            "published_at": "2026-09-12T12:00:00Z",
            "retrieved_at": "2026-09-12T12:05:00Z",
            "duration_seconds": 120,
            "rights_and_terms_note": "synthetic fixture only; no media acquired",
            "access_state": "public",
        }
    )
    asr_fallback = plan_asr_fallback(video_source)
    motion_job = plan_motion_job(fixtures["motion"])

    provider_output: dict[str, dict[str, object]] = {}
    for provider_id in registry.provider_ids():
        record = registry.get(provider_id)
        provider_output[provider_id] = {
            "provider_state": record["provider_state"],
            "reviewed_commit": record["reviewed_commit"],
            "executable_operations": [],
            "dry_run_operations": record["allowed_operations"],
        }

    return {
        "execution_state": "dry_run",
        "external_side_effects": [],
        "providers": provider_output,
        "provider_decisions": {
            key: {
                "operation": value.operation,
                "decision": value.decision,
                "reason": value.reason,
                "record_hash": value.record_hash,
            }
            for key, value in decisions.items()
        },
        "source_extraction": article,
        "claim_state": "awaiting_source_tier_evaluation",
        "story_cluster": {
            "story_cluster_id": "story-ai-science-fixture",
            "evidence_refs": ["rss-fixture-entry", "newscrawler-fixture-extraction"],
            "confidence_effect": "none_until_claim_level_review",
        },
        "xhs_research_state": "reference_only",
        "video_source": video_source,
        "caption_selection": {
            "state": selected.state,
            "caption_track_id": selected.caption_track_id,
            "caption_source": selected.caption_source,
            "language": selected.language,
        },
        "asr_fallback": asr_fallback,
        "transcript": transcript,
        "translation": translation,
        "content_gate": "awaiting_james_angle",
        "motion_job": motion_job,
        "contracts": {
            "source_acquisition_provider": registry.get("newscrawler.news-extractor"),
            "video_source_artifact": video_source,
            "video_transcript_artifact": transcript,
            "transcript_translation_artifact": translation,
            "motion_video_job": motion_job,
        },
        "not_done": [
            "no third-party provider installed or invoked",
            "no cookie or account session accessed",
            "no live crawl or media download",
            "no external translation",
            "no HyperFrames scaffold or render",
            "no upload, schedule, publish, or live verification",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    output = _inside_repository(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = run_v14_dry_run(args.fixtures)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE: {output.relative_to(REPOSITORY_ROOT)}")
    print("EXECUTION_STATE: dry_run")
    print("EXTERNAL_SIDE_EFFECTS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
