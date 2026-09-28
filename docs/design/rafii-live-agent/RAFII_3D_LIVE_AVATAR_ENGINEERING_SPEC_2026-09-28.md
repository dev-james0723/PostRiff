# Rafii 3D Live Voice Avatar Engineering Spec — 2026-09-28

## Status
Approved for implementation by the owner under the “做到尾” workflow. This feature may be implemented, tested, committed and prepared for release without another design decision. Production merge/deploy remains subject to the repository's normal high-risk release gate.

## Goal
Make the existing Rafii raccoon character a real-time 3D presence inside Voice Mode. While a call is active, Rafii must visibly listen, think, speak and stop when interrupted, with live mouth motion synchronized to the actual outgoing voice signal. The experience must work on desktop and mobile, respect reduced motion, and never make Voice Mode less reliable.

## Character reference
The approved character is the owner-provided raccoon sheet from this conversation: oversized soft gray raccoon head, white muzzle and forehead markings, dark eye mask, large expressive eyes, small charcoal paws/feet, off-white hoodie, short body, oversized striped tail. The existing `web/public/raffi/*.png` images remain the 2D fallback and identity reference already in the product.

This implementation creates a no-cost Blender-authored canonical v1 asset. Tripo is deliberately not required for the first production release because it would introduce an external paid/provider gate. A later art pass may replace the mesh while preserving the runtime contract below.

## Scope

### Canonical asset
- Add a reproducible Blender 5.2+ Python build script and generated `web/public/raffi/raffi-live-v1.glb`.
- Keep the GLB at or below 5 MB. Target substantially below that limit.
- Web asset has no simulated hair particles. Plush/fur character comes from geometry, materials and lighting.
- Named transform nodes must include at least: `RafiiRoot`, `Body`, `Head`, `EarL`, `EarR`, `EyeL`, `EyeR`, `Mouth`, `ArmL`, `ArmR`, `Tail01`, `Tail02`, `Tail03`, `Tail04`.
- The mouth mesh exposes morph targets usable by the runtime for live expression. Preferred names: `Open`, `Wide`, `Round`, `Smile`.
- The asset should read clearly as the approved Rafii silhouette at small voice-panel sizes and at larger future hero sizes.

### Runtime state contract
Expose one small pure state vocabulary:
- `idle`
- `listening`
- `thinking`
- `speaking`
- `interrupted`

State is derived only from existing real Voice Mode state, speaker, output level and running delegations. Do not invent backend state and do not add provider calls.

Expected mapping:
- connecting/reconnecting with no speech → thinking
- live + user speaker → listening
- live + Rafii speaker → speaking
- live + no speaker + running/collecting delegation → thinking
- live + no speaker + no work → idle
- after `stopSpeaking()`, mouth closes immediately and the visual mode becomes interrupted/listening rather than continuing a canned speaking animation

### Live lip sync
- Primary production v1 driver is the existing real outgoing `VoiceSnapshot.level` from the WebRTC output path.
- Smooth the level locally so mouth movement is responsive but not jittery.
- The mouth must close immediately when output is muted/stopped or Rafii is no longer the speaker.
- Use transcript deltas only as optional viseme hints; no claim of phoneme-perfect synchronization is allowed until the provider exposes phoneme/viseme timestamps.
- The visual layer must never delay, buffer or own voice audio.

### Live movement
Animate independent layers rather than playing one long clip:
- breathing/body settle
- procedural blinking
- eye target / subtle gaze
- head tilt/nod
- ear reactions
- subtle arm gesture while speaking
- multi-segment tail motion
- mouth morphs
Movements must be restrained and characterful, not random or hyperactive.

### Web integration
- Keep the existing Voice Mode controls, transcript and status semantics.
- During an active voice session, place the 3D stage inside the Voice Mode region as the primary visual element without hiding controls.
- Add `data-rafii-3d` and a readable `data-rafii-avatar-mode` state hook for browser tests.
- The 3D canvas is decorative. Voice state remains available to assistive technology through the existing live status text.
- If WebGL, asset load or rendering fails, show the existing static full-body Rafii image and keep Voice Mode fully usable.

### Performance
- Lazy-load/render 3D only while Voice Mode is active.
- Pause the animation loop when the document is hidden.
- Cap renderer pixel ratio: <= 2 desktop, <= 1.5 mobile/coarse pointer.
- Target 60 FPS on modern desktop and a stable >= 30 FPS on representative mobile hardware/emulation.
- No new paid service, network provider, telemetry or user permission.
- No new backend migration.

### Accessibility and reduced motion
- `prefers-reduced-motion` / existing `useMotionPreference` must disable continuous decorative motion and procedural fidgeting. A static state pose plus live mouth open/close only when necessary to understand speaking is acceptable.
- The canvas is `aria-hidden`.
- All existing keyboard/touch controls and accessible names remain unchanged.
- No content may depend on hover.

### Failure and compatibility
- A 3D initialization error is non-fatal and must not change call state.
- WebKit/Safari-class behavior is required because mobile voice already has WebKit-specific gesture constraints.
- The code must cleanly dispose WebGL renderer, geometries, materials and observers on unmount.
- No leaking RAF loops across voice start/end cycles.
- Do not alter GPT-Live provider selection, costs, voice permissions, notification settings or external OAuth/provider rights.

## Release/verification contract
Before release:
1. Asset integrity test proves a valid GLB, required nodes, morph target names if present, and size <= 5 MB.
2. Unit tests prove state mapping and stop/interruption behavior.
3. Typecheck and lint are green.
4. Existing voice tests remain green.
5. Browser QA exercises active Voice Mode in Chromium and WebKit with desktop 1440×900 and mobile 390×844. If physical mobile is unavailable, label mobile verification as emulated.
6. Screenshot-based layout QA checks no clipping/overflow and controls remain tappable.
7. Reduced-motion behavior is checked.
8. Browser console and failed network requests are checked for regressions.
9. Production verification must exercise the live deployed voice panel without making a paid provider call if the production environment does not expose a safe synthetic voice harness; in that case verify the deployed asset, code path and idle/fallback surface and explicitly name the unverified provider-dependent portion.

## Future art-quality upgrade
A future Tripo or artist-authored mesh may replace `raffi-live-v1.glb` without changing runtime code as long as the required node/morph names and scale/orientation contract are preserved. That replacement is an art pipeline change, not a voice architecture change.
