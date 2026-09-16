# Asset contract and validation

## Input brief

Create one `GraphicAssetBrief` per source composition:

```json
{
  "campaign_id": "stable campaign ID",
  "brief_version": "immutable version",
  "canonical_claim": "one sentence",
  "creator_take_ref": "approved or pending point-of-view reference",
  "content_mode": "news | build | launch | youtube | music | reflection | education | event_service",
  "brand_identity": "one brand id declared in the workspace BRAND.md, or personal when the workspace declares none",
  "visual_job": "subject | evidence | explain | sequence | emotional_frame | demonstrate | open_content",
  "source_treatment": "real_photo | real_screenshot | video_frame | generated_editorial | designed_graphic | hybrid_composite",
  "target_ids": ["exact ChannelDraft target IDs"],
  "native_format_ids": ["instagram.carousel"],
  "languages": ["en", "zh-Hant", "zh-Hans"],
  "required_facts": ["claim IDs"],
  "required_qualifications": ["qualification IDs"],
  "source_asset_refs": ["safe local or approved source references"],
  "missing_inputs": [],
  "approval_state": "draft"
}
```

## Asset manifest

Return one immutable candidate record per export:

```json
{
  "asset_id": "stable ID",
  "campaign_id": "stable campaign ID",
  "target_id": "exact ChannelDraft target ID",
  "native_format_id": "instagram.carousel",
  "variant_group_id": "shared family ID",
  "source_composition_id": "master composition ID",
  "asset_role": "cover | carousel_slide | thumbnail | story_card | video_cover | article_cover | inline_figure | community_card",
  "sequence_index": 1,
  "source_type": "real | generated | edited | user_provided",
  "language": "zh-Hant",
  "width": 1080,
  "height": 1350,
  "aspect_ratio": "4:5",
  "mime_type": "image/png",
  "file_size_bytes": 0,
  "content_hash": "hash after export",
  "safe_area_profile": "versioned profile ID",
  "platform_constraints_version": "source and retrieval timestamp",
  "text_transcript": "all visible text in reading order",
  "fact_claim_ids": ["claim IDs represented visually"],
  "alt_text": "meaningful accessible description",
  "rights_or_source_note": "origin and permitted use",
  "generated_content_label": "required | not_required | unknown",
  "safe_to_reuse": false,
  "validation_state": "pending | candidate_ready | blocked"
}
```

Ordered carousels and Stories also return an ordered asset-ID list. A reordered slide/card sequence produces a new hash and invalidates any approval bound to the previous order.

## Production receipt

Report:

```text
VISUAL_RATIONALE:
TARGETS_AND_NATIVE_FORMATS:
SOURCE_COMPOSITIONS:
EXPORTED_ASSETS:
MECHANICAL_VALIDATION:
VISUAL_REVIEW:
FACT_AND_SOURCE_CHECK:
LOCALIZATION_REVIEW:
ACCESSIBILITY_REVIEW:
RIGHTS_REVIEW:
BLOCKERS:
NOT_DONE:
EXECUTION_STATE: candidate_only
```

## Mechanical validation

For every export:

- decode the image successfully;
- confirm width, height, aspect ratio, MIME type, file size, and nonzero content;
- confirm text and principal subjects remain inside the versioned safe-area profile;
- confirm font files are available and permitted for output use;
- detect missing images, placeholder text, overflow, clipped glyphs, broken characters, unintended transparency, and low-resolution source scaling;
- confirm carousel/Story page count and order;
- confirm content hash after final export;
- compare against current target constraints, not only planning defaults.

## Visual review

Inspect a rendered contact sheet and representative phone-size previews. Check:

- one clear focal point and reading order;
- headline legibility at realistic feed size;
- meaningful contrast rather than template decoration;
- correct crop in feed, grid, thumbnail, cover, and full-screen contexts where applicable;
- visual continuity without repetitive layouts;
- sufficient negative space for captions/subtitles or platform UI;
- whether the visual actually supports the sentence or idea;
- whether a community-native visual looks like an advertisement pasted from another platform.

A passing dimension or safe-zone check is not visual approval.

## Fact and evidence review

- Every visible factual claim maps to a current source-log claim ID.
- Attribution and uncertainty remain visible where required.
- Quotes match their verified wording and source.
- Product screenshots match the stated environment and release state.
- Generated visuals are not presented as evidence, documentary photography, official UI, or an actual performance/event.
- A correction or changed story version blocks stale text-bearing assets.

## Localization review

- Language and script match the selected account/audience.
- Line breaks, punctuation, font coverage, and emphasis are native to the language.
- Translation preserves claim strength, uncertainty, and tone.
- Mainland, Hong Kong, Taiwan, Japan, Korea, and India variants are localized rather than mechanically translated.
- Regional-language publishing that requires human review remains blocked until that review is recorded.

## Accessibility review

- Alt text describes meaning and relevant text, not decorative style alone.
- Essential information is not encoded only through color.
- Contrast remains readable in the actual export.
- Charts and diagrams have labels, units, and a text-equivalent explanation.
- Decorative assets are identified as decorative where the destination supports it.

## Rights and privacy review

- Record whether each source is user-provided, owned, licensed, official press material, generated, or third-party.
- Verify the permitted reuse context separately from source availability.
- Do not expose private UI, notifications, email addresses, tokens, browser chrome, location details, or unrelated people in screenshots/photos.
- Blur or crop private information before the agent receives or exports it where possible.
- Record music/audio rights for any associated video package even though this skill produces only static graphics and covers.

## Blocking conditions

Return `blocked` when:

- the native format or current constraints are unverified;
- required real evidence is missing;
- a visible fact lacks support or carries an unresolved correction;
- the source asset's rights are unknown;
- required font/glyph coverage fails;
- the export is clipped, unreadable, corrupt, or below required resolution;
- a static image is being used to impersonate a required video;
- a generated visual could reasonably be mistaken for official or documentary evidence;
- personal/private content lacks the required user confirmation.

`candidate_ready` means the local asset passed the recorded checks. It never means approved, uploaded, scheduled, published, or verified live.
