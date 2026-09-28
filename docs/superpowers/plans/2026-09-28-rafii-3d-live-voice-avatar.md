# Rafii 3D Live Voice Avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reproducible Blender-authored Rafii 3D asset and a real-time Three.js Voice Mode avatar that listens, thinks, speaks, lip-syncs to actual output level, stops instantly on interruption, and degrades safely to the existing 2D art.

**Architecture:** The feature is split into a deterministic asset pipeline, a small pure avatar-state module, and a client-only Three.js renderer embedded in the existing Voice Mode UI. The 3D layer consumes existing `VoiceSnapshot` data only; it never owns audio or provider state. A static PNG fallback preserves call usability if WebGL or GLB loading fails.

**Tech Stack:** Blender 5.2+ Python, glTF/GLB 2.0, Three.js 0.186, React 19 / Next.js 16, Playwright, existing Voice Mode harness.

**Spec:** `docs/design/rafii-live-agent/RAFII_3D_LIVE_AVATAR_ENGINEERING_SPEC_2026-09-28.md`

## Global Constraints

- No paid service, external model provider, new OAuth scope, notification, migration or backend provider change.
- Canonical asset: `web/public/raffi/raffi-live-v1.glb`, <= 5 MB.
- Required named nodes: `RafiiRoot`, `Body`, `Head`, `EarL`, `EarR`, `EyeL`, `EyeR`, `Mouth`, `ArmL`, `ArmR`, `Tail01`, `Tail02`, `Tail03`, `Tail04`.
- Preferred mouth morph targets: `Open`, `Wide`, `Round`, `Smile`.
- Runtime modes are exactly `idle | listening | thinking | speaking | interrupted`.
- Lip sync is driven by the existing outgoing `VoiceSnapshot.level`; transcript text may only provide optional visual hints.
- Voice audio must never wait for, depend on or be routed through the 3D renderer.
- Reduced motion disables continuous decorative movement.
- Canvas is decorative/aria-hidden; existing Voice Mode status and controls remain authoritative and keyboard/touch accessible.
- WebGL/asset failure falls back to existing `/raffi/full-*.png` without changing call state.
- Renderer pixel ratio <= 2 desktop and <= 1.5 mobile/coarse pointer.
- WebKit/Safari-class verification is required.
- No implementation may silently change GPT-Live costs, provider selection, permissions or user data behavior.

## Review Focus

- Voice output stops or user interrupts mid-word: the mouth must close immediately and the avatar must not continue a canned speaking loop. Test in Task 2 and browser QA in Task 4.
- WebGL is unavailable or GLB fails to load: Voice Mode controls/transcript must remain usable with a static Rafii fallback. Test in Task 3 and Task 4.
- Voice panel mounts/unmounts repeatedly: no orphaned requestAnimationFrame loop, ResizeObserver or GPU resource may remain. Test instrumentation in Task 3 and review in Task 4.
- Reduced-motion users: no breathing/tail/ear/head fidget loop, while the speaking state remains understandable. Test in Task 3 and browser QA in Task 4.
- Small mobile layout and WebKit gesture constraints: 3D stage must not cause horizontal overflow or steal taps from voice controls. Test in Task 4.

---

### Task 1: Reproducible Blender asset pipeline and canonical GLB

**Files:**
- Create: `scripts/raffi_3d_build.py`
- Create: `web/public/raffi/raffi-live-v1.glb` (generated)
- Create: `web/tests/rafii-3d-asset.test.cjs`

**Interfaces:**
- Consumes: Blender 5.2+ executable available locally.
- Produces: GLB node names and mouth morph names consumed by `rafii-live-avatar.tsx`.

- [ ] **Step 1: Write the failing asset integrity test**
  - Parse the GLB header + JSON chunk directly in Node.
  - Assert magic/version 2, file <= 5 MB, all required node names exist, at least one mesh has morph targets and target names include `Open`, `Wide`, `Round`, `Smile`.
  - Assert no image payload exceeds the overall size budget.

- [ ] **Step 2: Run the test and verify RED**
  - Run: `cd web && node tests/rafii-3d-asset.test.cjs`
  - Expected: FAIL because `public/raffi/raffi-live-v1.glb` does not exist.

- [ ] **Step 3: Implement `scripts/raffi_3d_build.py`**
  - CLI: `blender --background --python scripts/raffi_3d_build.py -- --output web/public/raffi/raffi-live-v1.glb [--preview-dir <dir>]`.
  - Build the approved stylized raccoon from lightweight primitives/materials with the exact required node names.
  - Add a multi-segment striped tail hierarchy and a mouth mesh with `Open`, `Wide`, `Round`, `Smile` shape keys.
  - Configure neutral studio lighting only for optional preview renders; no lighting/camera is required in the exported runtime asset.
  - Export glTF 2.0 binary, apply transforms and keep asset scale consistent.

- [ ] **Step 4: Generate the canonical GLB**
  - Run the Blender CLI above with `--preview-dir /tmp/rafii-3d-preview`.
  - Expected: exit 0; generated GLB exists and is <= 5 MB.

- [ ] **Step 5: Verify GREEN**
  - Run: `cd web && node tests/rafii-3d-asset.test.cjs`
  - Expected: PASS.

- [ ] **Step 6: Commit**
  - `git add scripts/raffi_3d_build.py web/public/raffi/raffi-live-v1.glb web/tests/rafii-3d-asset.test.cjs && git commit -m "feat: add canonical Rafii 3D asset"`

### Task 2: Pure avatar-state and mouth-control contract

**Files:**
- Create: `web/src/features/rafii-voice/avatar-state.ts`
- Create: `web/tests/rafii-3d-avatar-state.test.cjs`

**Interfaces:**
- Consumes: `VoiceState`, `Speaker`, output `level`, `outputMuted`, and whether any delegation is running/collecting.
- Produces: `RafiiAvatarMode`, `resolveRafiiAvatarMode(input)`, `targetMouthOpen(input)`, and bounded smoothing helper(s) used by the renderer.

- [ ] **Step 1: Write failing tests**
  - connecting/reconnecting -> thinking.
  - live + user -> listening.
  - live + Rafii -> speaking.
  - live + work + no speaker -> thinking.
  - live + no speaker/work -> idle.
  - `outputMuted=true` or non-Rafii speaker -> mouth target 0 even if level is high.
  - speaking with level 0.6 -> non-zero bounded mouth target.
  - smoothing never overshoots [0, 1].

- [ ] **Step 2: Verify RED**
  - Run: `cd web && node tests/rafii-3d-avatar-state.test.cjs`
  - Expected: FAIL because module/functions do not exist.

- [ ] **Step 3: Implement minimal pure helpers**
  - No React/Three imports.
  - Keep thresholds/constants exported only when tests/runtime need them.

- [ ] **Step 4: Verify GREEN**
  - Run the same test; Expected: PASS.

- [ ] **Step 5: Commit**
  - `git add web/src/features/rafii-voice/avatar-state.ts web/tests/rafii-3d-avatar-state.test.cjs && git commit -m "feat: define Rafii live avatar states"`

### Task 3: Three.js live renderer with safe fallback

**Files:**
- Create: `web/src/features/rafii-voice/rafii-live-avatar.tsx`
- Modify: `web/src/features/rafii-voice/voice-mode.tsx`
- Create: `web/tests/rafii-3d-renderer-contract.test.cjs`

**Interfaces:**
- Consumes: `mode: RafiiAvatarMode`, `level: number`, `outputMuted: boolean`, `reducedMotion: boolean`.
- Produces: decorative stage with `data-rafii-3d`, `data-rafii-avatar-mode`, a canvas on success, and static PNG fallback on init/load failure.

- [ ] **Step 1: Write failing renderer-contract test**
  - Source-level contract test asserts the component owns `requestAnimationFrame`, `ResizeObserver`, `visibilitychange`, renderer disposal, and GLTFLoader; and that Voice Mode renders `RafiiLiveAvatar` while active.
  - This test is a guard for lifecycle hooks; behavior is also verified in a browser in Task 4.

- [ ] **Step 2: Verify RED**
  - Run: `cd web && node tests/rafii-3d-renderer-contract.test.cjs`
  - Expected: FAIL because component/integration do not exist.

- [ ] **Step 3: Implement `RafiiLiveAvatar`**
  - Imperative Three.js inside one client component.
  - Lazy-load `/raffi/raffi-live-v1.glb`.
  - Orthographic or mild perspective camera framed chest-up by default.
  - Neutral transparent stage; no external textures/network fetches beyond the local GLB.
  - Name-based node lookup for head, ears, arms and tail.
  - Name-based morph dictionary for mouth targets.
  - One RAF loop with delta-time-based interpolation; pause while document hidden.
  - Speaking: mouth follows smoothed output level, subtle head/arm/tail motion.
  - Listening: attentive head/ears; no mouth motion.
  - Thinking: subtle head tilt and settled tail.
  - Interrupted: immediate mouth zero, short attentive pose.
  - Idle: subtle breathing/blink/tail.
  - Reduced motion: no continuous decorative animation; keep static pose and only minimal mouth movement needed for speaking.
  - Dispose renderer/materials/geometries and observers on unmount.
  - If renderer/context/GLB fails, set fallback and render existing `/raffi/full-512.png`.

- [ ] **Step 4: Integrate with Voice Mode**
  - Derive mode using Task 2 helpers.
  - Place stage at top of active Voice Mode region without changing existing button semantics.
  - Keep all existing text/status/transcript behavior.

- [ ] **Step 5: Verify GREEN**
  - Run renderer-contract test.
  - Run: `cd web && npm run typecheck && npm run lint`
  - Expected: all exit 0.

- [ ] **Step 6: Commit**
  - `git add web/src/features/rafii-voice/rafii-live-avatar.tsx web/src/features/rafii-voice/voice-mode.tsx web/tests/rafii-3d-renderer-contract.test.cjs && git commit -m "feat: animate Rafii in live voice mode"`

### Task 4: Browser, responsive, accessibility and interruption QA

**Files:**
- Modify: `web/tests/rafii-live-agent-browser.cjs`
- Optional create: `docs/design/rafii-live-agent/RAFII_3D_LIVE_AVATAR_VERIFICATION_2026-09-28.md`

**Interfaces:**
- Consumes: active Voice Mode harness and DOM hooks from Task 3.
- Produces: browser evidence for Chromium/WebKit, desktop/mobile, interruption, reduced motion, overflow and accessibility.

- [ ] **Step 1: Add failing browser checks before changing implementation further**
  - When Voice Mode becomes live, assert one `[data-rafii-3d]`.
  - Assert mode becomes speaking when fake output level/speaker is Rafii.
  - Trigger Stop talking and assert mode leaves speaking and mouth-state hook reports closed.
  - Assert no horizontal overflow and primary voice buttons remain clickable.
  - Add reduced-motion context check with stage still present and continuous-motion marker disabled.
  - Run one section before implementation adjustment and confirm any newly added missing hook fails for the intended reason.

- [ ] **Step 2: Make only the minimal implementation/test-harness changes needed for GREEN**

- [ ] **Step 3: Run focused browser QA**
  - Start existing local API + dev web harness exactly as `web/tests/rafii-live-agent-browser.cjs` documents.
  - Chromium desktop 1440×900 voice section.
  - Chromium phone 390×844 voice-phone section.
  - WebKit desktop voice section.
  - WebKit phone voice-phone section.
  - Save screenshots to a temp evidence directory.

- [ ] **Step 4: Accessibility/runtime checks**
  - Existing axe serious/critical violations for Voice Mode: 0.
  - Console errors introduced by this feature: 0.
  - Failed local GLB/network requests: 0.
  - Reduced motion passes.
  - Static fallback is manually/synthetically forced once and leaves buttons usable.

- [ ] **Step 5: Full relevant verification**
  - `cd web && node tests/rafii-3d-asset.test.cjs && node tests/rafii-3d-avatar-state.test.cjs && node tests/rafii-3d-renderer-contract.test.cjs && node tests/voice-opening.test.cjs && node tests/voice-transcript.test.cjs && npm run typecheck && npm run lint && npm run build`
  - Run the project’s broader browser/voice suite that is practical in the disposable harness and name any pre-existing unrelated failure explicitly.

- [ ] **Step 6: Commit**
  - `git add web/tests/rafii-live-agent-browser.cjs docs/design/rafii-live-agent/RAFII_3D_LIVE_AVATAR_VERIFICATION_2026-09-28.md && git commit -m "test: verify Rafii 3D voice avatar"`

### Task 5: Whole-branch review and release

**Files:**
- Modify only if review finds a Critical/Important issue.
- Create/update release evidence as needed.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: reviewed branch, release identity and production verification.

- [ ] **Step 1: Run Superpowers whole-branch review**
  - Build review package from merge base to HEAD.
  - Fresh reviewer checks spec, plan, Review Focus and ledger rulings.

- [ ] **Step 2: One fix pass for Critical/Important findings**
  - Each fix must be RED -> GREEN and followed by the relevant green suite.
  - Minor findings are recorded, not silently mixed into scope.

- [ ] **Step 3: Final pre-release verification**
  - Fresh typecheck, lint, build, focused tests and browser checks.
  - Confirm `git status --short` is clean.
  - Confirm branch is based on current `origin/consumer-saas` or rebase/merge safely if base advanced.

- [ ] **Step 4: Push and open/merge release according to repository workflow**
  - Do not force-push shared branches.
  - Preserve concurrent Social Trends / hosted-social / V3 work.
  - Production/deploy action requires the Mission Control high-risk approval already requested for this run.

- [ ] **Step 5: Deploy and production verify**
  - Record production URL/environment and deployed commit.
  - Verify the deployed GLB returns 200 and is <= 5 MB.
  - Verify the live Voice Mode UI loads the 3D/fallback path and remains responsive at representative desktop/mobile sizes.
  - If safe synthetic voice is unavailable in production, do not incur provider cost merely for verification; verify the deployed client path and clearly mark real paid-audio lip sync as provider-dependent/not re-exercised.
  - Check console/network/runtime health.
  - Only after all applicable gates pass, mark production verification complete.
