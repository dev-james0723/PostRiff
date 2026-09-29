# Rafii Needle Pulse — Interactive Audio Thread Map

**Date:** 2026-09-29  
**Status:** Approved product direction; implementation authorized  
**Repository:** `dev-james0723/PostRiff`  
**Canonical release branch:** `consumer-saas`  
**Implementation branch:** `feat/rafii-needle-pulse-thread-map-20260929`  
**Authoritative base SHA:** `eb343545a2a97b34165e62d7b2d75aaa3ddaca82`

## 1. Product intent

Replace the current thick waveform marker treatment with **Needle Pulse**: a sparse, quiet, premium vertical rail made from very fine horizontal needle lines.

Needle Pulse is both:
1. an audio-reactive waveform visualization; and
2. a precise thread-history navigator.

The product should feel like a restrained instrument rather than an equalizer: subtle at rest, sharply expressive at musical peaks, and highly legible when the user explores the conversation history.

## 2. Design principles

### 2.1 Visual character
- almost-black / current Rafii dark surface;
- monochrome warm-neutral foreground only;
- hairline visual language;
- no beads, pills, thick droplets, ribbon effects, particles, or glass tubes;
- use negative space as part of the design;
- strong peaks may glow slightly, but the core needle remains crisp.

### 2.2 Interaction character
- the rail should feel physically responsive to proximity;
- cursor/finger interaction should locally magnify and bend the waveform rather than simply changing color;
- interacting with one needle reveals the associated past message preview immediately;
- preview remains actionable: click/tap jumps to that exact turn or cluster.

### 2.3 Motion character
- audio peaks and valleys must dominate the shape;
- adjacent needles should not move at the same velocity;
- strong waveform peaks react faster;
- quieter needles respond more slowly and remain shorter;
- the whole rail may breathe slightly, but global motion must never flatten local contrast.

## 3. Preserve existing architecture

Do not regress the validated audio/navigation foundations already shipped on `consumer-saas`:

- real time-domain waveform sampling is the dominant local spatial signal;
- RMS/global envelope remains a small movement floor;
- FFT texture and spectral-flux transient remain secondary;
- per-marker transition speed varies with waveform amplitude;
- explicit external Music Sync via display/system-audio capture remains local;
- Rafii-owned media keeps its CORS-enabled Web Audio path;
- exact navigation IDs, cluster navigation, and conversation jumping remain intact;
- desktop reserved rail gutter / no-overlap behavior remains intact;
- reduced-motion behavior remains supported;
- current popover/preview content model should be reused rather than duplicated.

## 4. Desktop layout

### 4.1 Rail
- keep desktop rail in the existing reserved right gutter;
- target visible rail width: approximately 22–28px inside the existing hit-area/gutter;
- actual interaction hit target remains at least 40px wide;
- needles align to a common vertical spine/origin on the right edge and extend leftward into the rail;
- do not reduce the conversation's existing right padding in this phase.

### 4.2 Needle geometry
Each visible navigation group renders one needle:
- height: 1px default; selected/hovered may reach 1.5px visually through transform/glow, not layout;
- idle length: 3–5px;
- waveform peak length: 20–30px maximum;
- selected resting needle: around 10–12px;
- round line caps;
- low idle opacity;
- strongest peaks may receive a subtle warm-white bloom.

Needles should form a clear peak/valley silhouette when music plays.

## 5. Audio mapping

Use the existing `waveformPeak`, `globalPulse`, `texture`, and `travellingTransient` inputs.

Recommended motion energy remains waveform-dominant:

```text
energy =
  globalPulse * 0.10 +
  bodyWave * 0.03 +
  waveformPeak * 0.64 +
  texture * 0.13 +
  travellingTransient * 0.10
```

Map energy to Needle Pulse output:

```text
idleLength      = selected ? 11px : 4px
audioLength     = energy * ~24px
finalLength     = clamp(idleLength + audioLength, idleLength, ~30px)
opacity         = selected ? 1 : 0.30 + energy * 0.65
outwardOffset   = <= 1.5px
peakGlow        = only above a meaningful energy threshold
transitionMs    = 20 + (1 - waveformPeak) * 64
```

### 5.1 Peak contrast acceptance
A deterministic waveform vector must produce:
- at least 10px difference between a strong peak needle and a quiet valley needle;
- at least 20ms difference between the fastest and slowest needle response;
- high peaks visibly distributed across the rail, not concentrated only at the top.

## 6. Cursor interaction — desktop

### 6.1 Proximity field
When the pointer enters the desktop rail, compute pointer distance to each visible needle center.

Within approximately 48px vertical radius:
- closest needle receives the strongest treatment;
- neighboring needles receive a smoothly decaying treatment;
- do not require the pointer to land on the 1px line exactly.

### 6.2 Local magnification
The hovered / nearest needle:
- scales length by approximately 1.25–1.45x;
- increases opacity;
- may brighten slightly;
- preserves the audio-derived peak shape.

Neighbors within the proximity field:
- receive smaller proportional scale;
- this creates a lens/zoom feel rather than a single abrupt highlight.

### 6.3 Bend / magnetic deformation
Needles near the pointer should bend toward the cursor using translation rather than SVG path distortion.

Recommended implementation:
- translate X toward pointer by max 3–5px;
- slight additional length multiplier based on proximity;
- adjacent markers receive less displacement;
- no second animation loop; compute from pointer state and existing React render.

The result should look like the rail is magnetically attracted to the cursor.

### 6.4 Past-message preview
When a needle is the active proximity target:
- show the existing message preview popover immediately;
- preview includes kind / time / excerpt;
- keep it compact and visually tied to the needle;
- click on preview or needle jumps to the exact message/group;
- cluster behavior remains available for grouped turns.

Preview should not flicker while moving slowly between neighboring needles. Use a stable active-hover index based on nearest marker and a modest hysteresis / pointer radius.

## 7. Touch interaction — mobile

The current mobile-only compact navigation is not sufficient for this concept. Add a mobile Needle Pulse rail that coexists with the compact controls without blocking chat content.

### 7.1 Placement
- right edge of the mobile conversation viewport;
- slim visual footprint;
- safe-area aware;
- does not overlap composer or bottom navigation;
- hit zone can be wider than visible rail.

### 7.2 Touch exploration
Support pointer/touch via Pointer Events:
- touch/press and drag vertically over the rail;
- nearest needle becomes active;
- local needles magnify/bend as on desktop;
- show associated past-message preview while the finger remains engaged;
- preview should appear to the left of the rail so the finger does not cover it;
- release keeps no persistent modal state by default;
- tap active needle/preview jumps to the message.

No browser-native long-press selection should trigger on the rail.

### 7.3 Mobile preview
Use a compact anchored preview:
- max width around 220–260px depending on viewport;
- excerpt max 2–3 lines;
- show time / message kind;
- small action hint such as “Tap to jump”;
- must stay inside viewport.

## 8. Preview behavior

Reuse the existing Thread Map preview data.

Desktop:
- hover/proximity preview replaces or refines the current group-hover preview;
- keyboard focus must also show the same preview.

Mobile:
- active pointer/touch target shows preview;
- tapping preview triggers `jump(item)`.

Preview must reflect the exact marker currently being manipulated.

## 9. Selected/current-message state

Current visible/active conversation marker:
- longer resting needle (around 10–12px);
- full opacity;
- remains obvious even without audio;
- hover/magnetic behavior can further magnify it, but should not overwhelm neighboring peaks.

## 10. Reduced motion

When `prefers-reduced-motion` is enabled:
- audio-driven length changes may be reduced to a minimal static amplitude state or disabled;
- no magnetic bend animation;
- no travelling transient;
- pointer/focus still reveals the message preview;
- selected/current marker remains distinct;
- touch/keyboard navigation remains fully functional.

## 11. Accessibility

- keep each needle inside a minimum 40px pointer hit target;
- preserve descriptive `aria-label` values;
- keyboard focus can traverse markers;
- focused needle shows preview;
- `aria-expanded` remains correct for clusters;
- popup content must not be required to understand the selected state;
- screen-reader live text for audio source remains unchanged.

## 12. Performance

- reuse the existing audio update cadence (~45fps);
- do not add canvas/WebGL;
- do not add a second RAF loop;
- pointer proximity state should update through Pointer Events and lightweight React state;
- avoid layout measurement on every audio frame;
- cache marker center positions when possible, or derive normalized positions from group index;
- use transform/width/opacity for visual motion;
- use `will-change` only while audio or pointer interaction is active.

## 13. Desktop acceptance

With a deterministic synthetic audio fixture:
1. rail clearly reads as fine horizontal needles, not pills or dots;
2. strong peak-to-valley length spread >= 10px;
3. strong peak response at least 20ms faster than quiet response;
4. cursor entering rail activates nearest needle without requiring pixel-perfect aiming;
5. active needle and neighbors visibly magnify/bend toward cursor;
6. moving cursor vertically updates preview to the corresponding past message;
7. clicking active needle/preview jumps to the exact turn;
8. scrolling conversation does not cause rail/chat overlap;
9. existing cluster popover remains functional.

## 14. Mobile acceptance

At ~390px viewport:
1. Needle Pulse rail is visible and does not cover message text or composer;
2. touch/drag along rail changes active needle continuously;
3. local magnification/bend is visible under finger;
4. past-message preview is visible while interacting;
5. preview stays within viewport;
6. tap jumps to the correct past message;
7. no horizontal overflow;
8. reduced-motion mode preserves navigation and preview.

## 15. Non-goals

Not in this change:
- merging/deploying to production unless explicitly requested;
- changing the underlying conversation data model;
- changing external audio permission flow;
- redesigning Now Playing;
- adding multicolor spectrum;
- WebGL/canvas shaders;
- replacing the existing message navigation API.

## 16. Implementation sequence

1. Create this product spec on the isolated Needle Pulse branch.
2. Implement audio output remapping to needle geometry.
3. Implement desktop pointer-proximity interaction and preview.
4. Implement mobile rail + touch/drag preview interaction.
5. Add targeted unit/source-contract tests.
6. Run targeted Thread Map/audio tests.
7. Run TypeScript and production build.
8. Run controlled browser acceptance for desktop and mobile.
9. Commit final verified implementation.
10. Open/update a PR only; do not merge production without explicit instruction.
