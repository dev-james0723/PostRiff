---
name: postriff-video-transcript-intake
description: Inspect a permitted public video source and prepare provenance-rich caption or transcript artifacts for analysis. Use for caption discovery, transcript acquisition planning, and ASR fallback decisions; do not use for protected-media bypass, translation, content approval, or publishing.
license: MIT
metadata:
  status: project-local-phase0-fixture-only
  project-contract: postriff-social-media-suite-design-revision-14
---

# PostRiff video transcript intake

Prepare an immutable timestamped transcript from a reviewed public video source while keeping source access, caption provenance, rights, fact checking, translation, and reuse approval separate. Phase 0 evaluates local fixtures only and does not invoke yt-dlp.

## Required inputs

Require an exact permitted public URL, intended use, source registry record, provider decision, preferred source languages, and source-rights note. Never infer permission from an active browser session or accept raw cookies.

Read [references/caption-intake-contract.md](references/caption-intake-contract.md) before acquiring or interpreting caption data.

## Workflow

1. Evaluate `inspect_public_metadata` and `list_caption_tracks` through the provider registry.
2. List caption tracks before any acquisition; do not download video or audio.
3. Prefer a requested-language manual caption, then automatic caption, then another permitted manual or automatic caption.
4. Keep `no_caption`, extractor failure, authentication requirement, source unavailability, and rate limiting distinct.
5. Build `VideoSourceArtifact` and `VideoTranscriptArtifact` records with provider pin, timestamps, hashes, quality flags, and explicit not-done fields.
6. Offer ASR only as a separate plan requiring rights review and approval for any audio acquisition.

## Output

Return source and transcript artifacts, caption-selection reason, quality limitations, rights state, provider decision, and a list of actions not performed.

## Hard boundary

The yt-dlp provider is `candidate_read_only`. This skill never imports browser cookies, logs in, downloads video/audio in Phase 0, bypasses DRM or access controls, translates, treats speech as verified fact or the creator's view, uploads, schedules, or publishes.
