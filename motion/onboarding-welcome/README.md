# Onboarding welcome loop

The 8-second loop above the three sentences in PostRiff's first-run Welcome
dialog. You type what you want to put out, three drafts come back (LinkedIn,
Instagram, Threads), the two that asked for a time get approved and drop into a
week calendar at 4pm and 5pm, and Threads stays a draft. Then it returns to the
empty composer, so the first and last frames are identical.

Built with HyperFrames (CLI pinned to `hyperframes@0.8.43`). The intent,
storyboard and visual rules are in `BRIEF.md`.

## Files

| Path | What it is |
| --- | --- |
| `index.html` | The composition: markup, palette tokens, and one paused GSAP timeline. Edit this to change the animation. |
| `index.motion.json` | Motion assertions that `check` verifies (entrance order, stays in frame, no frozen stretch). |
| `BRIEF.md` | The confirmed brief (intent-interview answers, storyboard, colour and motion rules). |
| `shot-plan.json` | Beat-by-beat plan with timings and motion tokens. |
| `build.sh` | Renders both themes and encodes the web files. |
| `assets/fonts/Geist-latin.woff2` | Geist, the app's sans (SIL Open Font License), copied from the local Next.js install so renders never need the network. |
| `hyperframes.json`, `meta.json`, `package.json` | HyperFrames project files created by `init`. |
| `CLAUDE.md`, `AGENTS.md` | Generic HyperFrames agent notes created by `init`. |

`renders/` and `snapshots/` are build output and are git-ignored.

## Outputs

Written to `web/public/onboarding/`:

- `welcome-loop-light.webm`, `welcome-loop-light.mp4`, `welcome-loop-light.jpg`
- `welcome-loop-dark.webm`, `welcome-loop-dark.mp4`, `welcome-loop-dark.jpg`

All are 896x560, 60fps, 8.000s, with no audio. The MP4s are H.264 High, yuv420p,
BT.709-tagged, with faststart. The WebMs are VP9 profile 0, yuv420p. Each JPG is
frame 1. The budget is 1.2 MB per video, and each file is currently about 240 KB.

## Re-render

Requirements: Node 22 or newer, and FFmpeg on `PATH` (or set `FFMPEG=/opt/homebrew/bin/ffmpeg`).
Run every command from this folder:

```bash
cd motion/onboarding-welcome
```

Both themes, start to finish (render, then MP4 + WebM + poster):

```bash
./build.sh
```

One theme:

```bash
./build.sh light
./build.sh dark
```

Re-encode without re-rendering (for example, to try another CRF):

```bash
SKIP_RENDER=1 CRF_H264=18 CRF_VP9=28 ./build.sh
```

The same steps by hand, for the light theme (use `"dark"` and `dark` for the other one):

```bash
# 1. Gate: lint + runtime + layout + motion + contrast
npx --yes hyperframes@0.8.43 check

# 2. Lossless master (PNG frames, opaque)
npx --yes hyperframes@0.8.43 render . --strict --strict-variables --quality high --fps 60 \
  --format png-sequence --variables '{"theme":"light"}' -o renders/light-frames

# 3. Encode
VF="scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
ffmpeg -y -framerate 60 -i renders/light-frames/frame_%06d.png -an -vf "$VF" \
  -c:v libx264 -preset veryslow -tune animation -crf 14 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -movflags +faststart ../../web/public/onboarding/welcome-loop-light.mp4
ffmpeg -y -framerate 60 -i renders/light-frames/frame_%06d.png -an -vf "$VF" \
  -c:v libvpx-vp9 -crf 22 -b:v 0 -row-mt 1 -deadline good -cpu-used 1 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  ../../web/public/onboarding/welcome-loop-light.webm
ffmpeg -y -i renders/light-frames/frame_000001.png -vf format=yuvj444p -q:v 2 -frames:v 1 \
  ../../web/public/onboarding/welcome-loop-light.jpg
```

## Preview and edit

```bash
npx --yes hyperframes@0.8.43 preview --background          # Studio, light theme
npx --yes hyperframes@0.8.43 snapshot --describe false --at 0,2.2,4.6,6.9   # stills in snapshots/
npx --yes hyperframes@0.8.43 preview --stop
```

Notes for editing `index.html`:

- **Theme.** The `theme` variable (`light` or `dark`) sets `data-theme` on `<html>`,
  and all colours are CSS custom properties in the two `:root` blocks.
- **Background.** The background fill sits on `#scene`, not on the root.
  PNG-sequence and WebM renders make the root transparent.
- **Layout constants.** `CARD_CENTER`, `SLOT_CENTER` and `COMPOSER_RAISE` in the
  script mirror the CSS positions. Update them together.
- **Motion.** Everything uses the app's `cubic-bezier(0.22, 1, 0.36, 1)` with
  40ms sibling staggers. Closes are shorter than opens, and the only overshoot
  is the 1.02 on the check.
- **Loop.** The last state must match t=0: an empty composer at rest with the
  first-line caret visible, and everything else hidden. After a render, compare
  `frame_000001.png` with `frame_000480.png`; they are byte-identical today.
- **Font.** The timeline is built after the font loads, because the typing
  reveal measures real glyph edges.
