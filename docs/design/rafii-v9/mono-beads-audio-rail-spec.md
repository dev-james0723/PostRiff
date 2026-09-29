# Rafii Mono Beads Audio-Reactive Thread Map

**Date:** 2026-09-29  
**Status:** Approved for implementation  
**Target branch:** `consumer-saas`  
**Implementation branch:** `feat/rafii-mono-beads-thread-map-20260929`  
**Authoritative base SHA:** `eb343545a2a97b34165e62d7b2d75aaa3ddaca82`

## 1. Goal

Replace the current thick liquid/capsule Thread Map markers with a quieter **Mono Beads** visual system: a very thin vertical spine with small monochrome pearl-like beads that remain useful as exact conversation-navigation markers while reacting to music with refined variation in size, glow, and offset.

The new rail must feel:
- minimal rather than decorative;
- premium rather than playful;
- musical without looking like a generic equalizer;
- alive without every marker moving together;
- readable as navigation even when audio is inactive.

## 2. Preserve these existing invariants

Do not regress the current audio architecture:
- real time-domain waveform sampling remains the primary local peak/valley signal;
- RMS/global envelope remains only a small movement floor;
- spectral texture and transient detection remain secondary;
- per-marker response speed remains variable;
- external display/system-audio capture remains explicit and local;
- Rafii-owned media continues to use the CORS-enabled Web Audio path;
- reduced-motion remains supported;
- desktop Thread Map stays in the reserved right gutter and never overlaps the conversation;
- mobile Thread Map behavior and exact navigation semantics remain unchanged.

## 3. Visual anatomy

### 3.1 Spine
Desktop rail gets one hairline spine behind the markers:
- width: 1px;
- visual opacity: roughly 10–16%;
- color: current text/foreground family, no bright accent color;
- extends only through the marker stack, not through the Music Sync control;
- never receives pointer events.

It is orientation/support, not the main visual.

### 3.2 Beads
Each visible Thread Map group becomes one circular bead.

Resting sizes:
- ordinary bead: about 2.25px;
- cadence bead (optional every fifth visible group): max +0.25px, subtle only;
- current/selected bead: about 4–4.5px.

Audio-reactive size range:
- ordinary peak bead: target 7–8.5px maximum;
- selected peak bead: may reach about 9px;
- no pill/capsule stretching: width and height must stay equal.

The design should still read correctly if glow is disabled.

### 3.3 Material
Monochrome only:
- inactive bead: `currentColor`, low opacity;
- active bead: same color, higher opacity;
- peak bead: soft outer bloom using a low-alpha box shadow;
- no gradients, glass tubes, particles, ribbons, or multicolor spectrum.

Target impression: small luminous pearls on a quiet string.

## 4. Motion model

Keep the already validated audio signal mix, but remap it to bead properties instead of long marker width.

Inputs:
- `waveformPeak`: dominant spatial peak/valley profile;
- `texture`: secondary FFT detail;
- `globalPulse`: subtle whole-rail floor;
- `travellingTransient`: subtle directional emphasis;
- `focus`: active navigation context.

Recommended energy mix remains approximately:
```
energy =
  globalPulse * 0.10 +
  bodyWave * 0.03 +
  waveformPeak * 0.64 +
  texture * 0.13 +
  travellingTransient * 0.10
```

### 4.1 Bead mapping
Map the same `energy` to:
- diameter, not width-only;
- opacity;
- halo/glow radius and alpha;
- small outward X displacement.

Suggested implementation:
- idle diameter: 2.25–2.5px;
- selected idle: 4.25px;
- diameter contribution: roughly `energy * 5.5–6.0px`;
- outward offset: max ~2px;
- peak glow blur: max ~8px, low alpha;
- quiet beads should not glow.

### 4.2 Variable response speed
Keep per-marker transition speed driven by waveform amplitude:
- strongest peaks: ~20–30ms;
- medium: ~35–55ms;
- quiet beads: ~65–85ms.

This is intentional: large peaks should catch quickly while small beads settle more slowly.

### 4.3 Travelling emphasis
The travelling transient may brighten or slightly offset beads, but must not create a visible “snake” or ribbon. It is a subtle accent only.

## 5. Interaction

The beads remain the existing Thread Map buttons:
- click jumps to the exact turn/group;
- clustered groups still open their current cluster menu;
- hover/focus preview remains unchanged;
- hit target remains large even though the visible bead is tiny;
- selected state remains visually discoverable via larger resting bead and full opacity;
- Music Sync control remains above the rail.

Do not shrink the button hit area when shrinking the bead.

## 6. Reduced motion

When reduced motion is enabled:
- no audio-driven scale/translation/glow animation;
- no travelling transient;
- beads remain static at resting sizes;
- selected bead is still distinguishable;
- all navigation still works.

## 7. Layout / no-overlap

Preserve:
- desktop rail container around `w-12`;
- existing conversation right gutter `lg:pr-14`;
- marker hit target within the rail;
- no visible bead/halo may cross into readable chat content.

The rail may look much narrower, but its reserved layout gutter should not be reduced in this phase.

## 8. Performance

- Reuse the existing ~45fps audio commit cadence.
- Do not add a second RAF loop.
- No canvas/WebGL for this version.
- Use simple CSS transforms/opacity/box-shadow.
- `will-change` only while audio is active.
- Do not allocate large objects inside each bead render beyond the existing motion array.

## 9. Acceptance criteria

### Automated
1. Existing audio-reactive tests remain green.
2. Mono Beads output is circular: computed width equals height.
3. Idle ordinary bead stays <= 3px.
4. Selected resting bead remains clearly larger than ordinary idle bead.
5. Strong waveform peaks produce visibly larger beads than valleys.
6. Peak/valley diameter spread for the existing synthetic test vector is >= 3.5px.
7. Stronger peak has a faster transition than quiet bead by >= 20ms.
8. Glow radius/alpha increases with peak energy but remains zero/near-zero for quiet idle markers.
9. Reduced-motion path renders static beads.
10. Thread Map still reserves the existing no-overlap gutter.

### Visual acceptance
With an amplitude-modulated synthetic fixture:
- rail reads as a thin string of beads, not bars/capsules;
- no more than a minority of beads are visually dominant at once;
- distinct peaks and valleys are obvious at a glance;
- glow is subtle enough that bead cores stay crisp;
- top/middle/bottom can all react independently;
- rail never overlaps chat content while scrolling.

## 10. Non-goals

Not in this phase:
- replacing thread navigation semantics;
- changing mobile navigation architecture;
- changing audio capture permissions;
- adding color themes to the waveform;
- introducing WebGL, shaders, 3D, particle systems, or canvas rendering;
- shrinking the desktop gutter;
- redesigning Now Playing.

## 11. Release sequence

1. Implement on isolated branch from the authoritative base.
2. Add/adjust targeted tests.
3. Run targeted Node tests.
4. Run TypeScript.
5. Run production web build.
6. Verify Vercel preview.
7. Run controlled browser visual acceptance with real Web Audio input.
8. Merge only after evidence is green.
9. Deploy `consumer-saas` production and verify exact merge SHA, health, and runtime errors.
