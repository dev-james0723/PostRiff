# Coding-Agent Handoff — Rafii Mono Beads Thread Map

Execute this task; do not stop after inspection or another proposal.

## Repository
- GitHub: `dev-james0723/PostRiff`
- Canonical release branch: `consumer-saas`
- Authoritative base: `eb343545a2a97b34165e62d7b2d75aaa3ddaca82`
- Working branch: `feat/rafii-mono-beads-thread-map-20260929`

## Read first
1. `docs/design/rafii-v9/mono-beads-audio-rail-spec.md`
2. `web/src/lib/media/audio-reactive.ts`
3. `web/src/features/context-navigation/thread-navigator.tsx`
4. `web/tests/audio-reactive-thread.test.cjs`
5. `web/src/features/agent/conversation-view.tsx`
6. `web/src/features/now-playing/now-playing-bar.tsx`

Treat the spec as authoritative.

## Objective
Replace the current thick liquid/capsule markers with the approved **Mono Beads** visual language:
- ultra-thin vertical spine;
- tiny circular monochrome beads;
- waveform peaks map mainly to bead diameter;
- subtle glow and <=~2px outward offset;
- per-bead variable response speed remains;
- no thick pills, ribbons, particles, or decorative glass effects.

## Preserve
- current time-domain waveform peak/valley physics;
- current CORS fix for Rafii-owned media;
- external Music Sync behavior;
- current 48px rail and 56px conversation gutter;
- exact Thread Map navigation, cluster popovers, tooltips;
- reduced motion;
- mobile behavior.

## Likely files
- `web/src/lib/media/audio-reactive.ts`
- `web/src/features/context-navigation/thread-navigator.tsx`
- `web/tests/audio-reactive-thread.test.cjs`

Avoid unrelated refactors.

## Required acceptance
- targeted audio/thread tests pass;
- TypeScript passes;
- production build passes;
- visible markers are circular, not capsules;
- ordinary idle bead <=3px;
- waveform peak/valley diameter spread >=3.5px on a deterministic test vector;
- peak response is >=20ms faster than quiet response;
- quiet beads have little/no halo;
- selected bead remains obvious without audio;
- controlled browser acceptance proves distinct bead sizes across the rail and no chat overlap.

## Release
Do not overwrite concurrent work. Re-fetch `consumer-saas` before merge. Merge only as a fast-forward-safe PR/merge from the isolated branch. Production deploy only after all required evidence is green. Verify Vercel production metadata points at the exact merge SHA, `/api/health` returns 200, and recent runtime errors are clean.
