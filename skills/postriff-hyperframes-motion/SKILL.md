---
name: postriff-hyperframes-motion
description: Plan and validate target-native HyperFrames motion explainers from an approved article, transcript translation, or CanonicalBrief. Use for local motion briefs and 16:9, 1:1, or 9:16 composition plans; do not use for source verification, unreviewed rendering, upload, scheduling, or publishing.
license: MIT
metadata:
  status: project-local-phase0-plan-only
  project-contract: postriff-social-media-suite-design-revision-14
---

# PostRiff HyperFrames motion

Turn one approved idea into a reviewable target-native motion plan while preserving facts, voice, translation uncertainty, rights, and publication boundaries. Phase 0 produces `MotionVideoJob` records only; it does not scaffold or render a HyperFrames project.

## Required inputs

Require approved source artifact IDs and hashes, one clear angle, duration, narration mode, target families, storyboard/composition data, template selection, caption or translation references, media-rights records, and an exact HyperFrames version pin.

Read [references/motion-job-and-validation.md](references/motion-job-and-validation.md) before planning variants or interpreting validation state.

## Routing

- Use `faceless-explainer` for an article, transcript, topic, or canonical brief that teaches or argues one clear idea; normally 30-90 seconds, never more than about three minutes under this contract.
- Use `motion-graphics` only for a motion-first, unnarrated unit under ten seconds.
- Map YouTube/embed to 16:9, LinkedIn/X/Instagram feed to 1:1, and Shorts/Reels/TikTok to 9:16.
- Compose and review every selected ratio independently; do not crop one master mechanically.

## Output

Return one `MotionVideoJob` with source, brief, storyboard, composition, template, caption/translation, rights, and version hashes; native variants; pending validation dimensions; no output assets; and explicit not-rendered/not-uploaded/not-scheduled/not-published states.

## Hard boundary

The installed HyperFrames entrypoint is an unbound future execution dependency. This skill never treats availability as render authority, calls HyperFrames in Phase 0, hides a failed check, equates lint/check with visual approval, uploads media, schedules, publishes, or verifies a live post.
