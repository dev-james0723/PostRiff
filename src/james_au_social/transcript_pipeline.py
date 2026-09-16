"""Caption-first, fixture-only transcript and translation primitives."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .canonical import canonical_hash
from .contracts import validate_contract


@dataclass(frozen=True)
class CaptionSelection:
    state: str
    caption_track_id: str | None
    caption_source: str | None
    language: str | None


def select_caption_track(
    tracks: Sequence[Mapping[str, object]], preferred_languages: Sequence[str]
) -> CaptionSelection:
    for language in preferred_languages:
        for source in ("manual_caption", "auto_caption"):
            for track in tracks:
                if track.get("language") == language and track.get("caption_source") == source:
                    return CaptionSelection(
                        "selected",
                        str(track["caption_track_id"]),
                        source,
                        language,
                    )
    for source in ("manual_caption", "auto_caption"):
        for track in tracks:
            if track.get("caption_source") == source:
                return CaptionSelection(
                    "selected",
                    str(track["caption_track_id"]),
                    source,
                    str(track["language"]),
                )
    return CaptionSelection("no_caption", None, None, None)


def build_video_source(metadata: Mapping[str, object]) -> dict[str, object]:
    hash_input = copy.deepcopy(dict(metadata))
    artifact = {
        "video_source_id": metadata["video_source_id"],
        "source_url": metadata["source_url"],
        "platform": metadata["platform"],
        "provider": "yt-dlp",
        "provider_commit_or_version": metadata["provider_commit_or_version"],
        "title": metadata["title"],
        "publisher_or_channel": metadata["publisher_or_channel"],
        "published_at": metadata.get("published_at"),
        "retrieved_at": metadata["retrieved_at"],
        "duration_seconds": metadata["duration_seconds"],
        "metadata_hash": canonical_hash(hash_input),
        "rights_and_terms_note": metadata["rights_and_terms_note"],
        "access_state": metadata["access_state"],
        "not_downloaded": ["video", "audio", "comments"],
    }
    return validate_contract("video_source_artifact", artifact)


def build_transcript(
    video_source: Mapping[str, object], caption: Mapping[str, object]
) -> dict[str, object]:
    segments = copy.deepcopy(caption["segments"])
    hash_input = {
        "video_source_id": video_source["video_source_id"],
        "source_language": caption["language"],
        "caption_source": caption["caption_source"],
        "caption_track_id": caption.get("caption_track_id"),
        "segments": segments,
    }
    artifact = {
        "transcript_id": f"transcript:{video_source['video_source_id']}:{caption.get('caption_track_id') or 'asr'}",
        "video_source_id": video_source["video_source_id"],
        "source_language": caption["language"],
        "caption_source": caption["caption_source"],
        "caption_track_id": caption.get("caption_track_id"),
        "segments": segments,
        "transcript_hash": canonical_hash(hash_input),
        "quality_flags": copy.deepcopy(caption.get("quality_flags", [])),
        "created_at": caption["created_at"],
        "not_done": ["not translated", "not fact-checked", "not approved for reuse"],
    }
    return validate_contract("video_transcript_artifact", artifact)


def plan_asr_fallback(video_source: Mapping[str, object]) -> dict[str, object]:
    access_state = video_source.get("access_state")
    if access_state != "public":
        return {
            "video_source_id": video_source.get("video_source_id"),
            "state": "blocked",
            "reason": f"access_state:{access_state}",
            "download_performed": False,
        }
    return {
        "video_source_id": video_source.get("video_source_id"),
        "state": "requires_separate_approval",
        "reason": "audio_acquisition_and_asr_not_authorized_in_phase0",
        "download_performed": False,
    }


def validate_translation_alignment(
    source_transcript: Mapping[str, object], translation: Mapping[str, object]
) -> list[str]:
    errors: list[str] = []
    if translation.get("source_transcript_hash") != source_transcript.get("transcript_hash"):
        errors.append("source_transcript_hash_mismatch")
    source_segments = source_transcript.get("segments", [])
    translated_segments = translation.get("segments", [])
    if not isinstance(source_segments, Sequence) or isinstance(source_segments, (str, bytes)):
        return errors + ["invalid_source_segments"]
    if not isinstance(translated_segments, Sequence) or isinstance(translated_segments, (str, bytes)):
        return errors + ["invalid_translation_segments"]

    seen: set[int] = set()
    previous = -1
    for position, translated in enumerate(translated_segments):
        if not isinstance(translated, Mapping):
            errors.append(f"translation_segment_{position}_invalid")
            continue
        index = translated.get("source_segment_index")
        if not isinstance(index, int) or index < 0 or index >= len(source_segments):
            errors.append(f"translation_segment_{position}_source_index_out_of_range")
            continue
        if index in seen:
            errors.append(f"segment_{index}_duplicate_source_index")
        if index < previous:
            errors.append(f"segment_{index}_reordered")
        seen.add(index)
        previous = index
        source = source_segments[index]
        if (
            translated.get("start_ms") != source.get("start_ms")
            or translated.get("end_ms") != source.get("end_ms")
        ):
            errors.append(f"segment_{index}_timestamp_mismatch")
        rendered = translated.get("translated_text")
        if not isinstance(rendered, str) or not rendered.strip():
            errors.append(f"segment_{index}_blank_translation")
    for index in range(len(source_segments)):
        if index not in seen:
            errors.append(f"segment_{index}_missing_translation")
    return errors


def build_translation(
    source_transcript: Mapping[str, object],
    translated_segments: Sequence[Mapping[str, object]],
    *,
    provider: str,
    provider_version: str,
    target_language: str,
    proper_nouns_and_terms: Sequence[Mapping[str, object]] = (),
    omissions_or_uncertainties: Sequence[str] = (),
) -> dict[str, object]:
    source_copy = copy.deepcopy(dict(source_transcript))
    source_segments = source_copy["segments"]
    segments: list[dict[str, object]] = []
    for item in translated_segments:
        index = item.get("source_segment_index")
        if not isinstance(index, int) or index < 0 or index >= len(source_segments):
            raise ValueError("translation_source_segment_index_out_of_range")
        source = source_segments[index]
        segments.append(
            {
                "source_segment_index": index,
                "start_ms": source["start_ms"],
                "end_ms": source["end_ms"],
                "translated_text": item.get("translated_text"),
            }
        )
    hash_input = {
        "source_transcript_id": source_copy["transcript_id"],
        "source_transcript_hash": source_copy["transcript_hash"],
        "source_language": source_copy["source_language"],
        "target_language": target_language,
        "translation_provider": provider,
        "translation_provider_version": provider_version,
        "segments": segments,
        "proper_nouns_and_terms": copy.deepcopy(list(proper_nouns_and_terms)),
        "omissions_or_uncertainties": list(omissions_or_uncertainties),
    }
    artifact = {
        "translation_id": f"translation:{source_copy['transcript_id']}:{target_language}:{provider_version}",
        **hash_input,
        "translation_hash": canonical_hash(hash_input),
        "review_state": "machine_candidate",
    }
    errors = validate_translation_alignment(source_copy, artifact)
    if errors:
        raise ValueError("translation_alignment_failed:" + ",".join(errors))
    return validate_contract("transcript_translation_artifact", artifact)
