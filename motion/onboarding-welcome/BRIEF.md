---
workflow: motion-graphics
flow: automation
storyboard: no
message: "Say it once, get a draft per channel, approve what goes out, and it lands in your calendar. Nothing publishes on its own."
destination: in-app first-run Welcome dialog (web/src/features/onboarding/welcome-dialog.tsx, 448px wide)
aspect: 896x560
language: en
audience: first-time PostRiff users (creators of any kind; general audience)
length: 8s
angle: product-ui-illustration
narration: no
export: mp4 + webm, light and dark
---

## Intent

A short, seamless 8-second loop that sits above the three sentences of PostRiff's
Welcome dialog and shows the product's loop without words: type what you want to
put out, drafts come back one per channel, you approve the ones you want, the
approved ones land in a calendar, and the one you did not approve stays a draft.
The founder asked for HyperFrames (and Remotion) to make the app feel less static,
and asked for execution without waiting for review. Calm, precise, product-UI
feel that matches the app's motion system, not a promo.

How the intent interview was answered (no person was available; answered from the
brief handed to this run, 2026-09-16):

- Subject and input: PostRiff's core loop, with no source media; an invented UI
  illustration built in HTML. No search and no asset sourcing.
- Route: `/motion-graphics` (short, unnarrated, motion is the message). The route's
  run-shape questions do not apply; the founder's "execute without waiting for
  review" counts as the render approval.
- Triage: formed request (storyboard supplied), so no pitch round.
- Remembered defaults and recipes: none on record (`prefs.mjs get` returned `{}`,
  `recipe.mjs list` returned `[]`).

### Storyboard (as supplied)

1. 0 to 2s: composer card; a sentence types in ("A post about what we learned this
   week" / "Instagram 4pm · LinkedIn 5pm"); caret blinks; send button is pressed.
2. 2 to 4s: three draft cards fan out from the composer, labelled LinkedIn,
   Instagram, Threads, each with a generic glyph and grey placeholder lines.
3. 4 to 5.5s: the Approve pill on the first two cards is pressed and a check draws
   in. The Threads card stays a draft (no time was asked for it).
4. 5.5 to 7.2s: the composer gives way to a mini week calendar; the two approved
   cards shrink into the 4pm and 5pm slots.
5. 7.2 to 8s: everything closes and the empty composer returns, so the first and
   last frames are identical.

## Customizations

- Theme switch: one composition, an enum variable `theme` (`light` default, `dark`),
  rendered twice with `--variables`.
- LIGHT: background #FAFAFA, cards #FFFFFF, hairline #E5E5E5, text #171717,
  secondary lines #A3A3A3, accent #111111.
- DARK: background #0A0A0A, cards #171717, hairline #262626, text #FAFAFA,
  secondary lines #737373, accent #FAFAFA.
- 12px card radius, soft shadow. Font: Geist (the app's sans), bundled locally from
  the Next.js install; Inter, then system-ui as fallbacks.
- Motion: open ease cubic-bezier(0.22, 1, 0.36, 1) (the app's `--ease-smooth-out`),
  closes shorter than opens, 40ms sibling stagger, no overshoot except a 1.02 scale
  on the check.
- Deliverables in `web/public/onboarding/`: `welcome-loop-{light,dark}.{webm,mp4}`
  (each under 1.2 MB; MP4 is H.264 yuv420p with faststart) and first-frame posters
  `welcome-loop-{light,dark}.jpg`.

## Notes

- Illustration, not data: no metrics, follower counts, names, handles or personal
  brands. Placeholder lines stand in for copy. Platform glyphs are generic shapes
  (briefcase, photo, speech bubble), never trademark logos. The only numbers are
  the two times, 4pm and 5pm, which the typed sentence asks for.
- No audio, no captions, no paragraphs: the dialog carries the words.
- Integration check: the 896x560 video is shown at about 448px wide, so every size
  on screen is halved. Type was set at 15 to 26px (about 7.5 to 13px in the dialog)
  and the typed sentence is split over two lines so it stays readable at that width.
- Rendered at 60fps (UI motion reads smoother; flat colours keep each file near
  240 KB, well under the 1.2 MB budget).
- Grey (#A3A3A3 / #737373) is used only for shapes (placeholder lines, dashed
  outlines), never for text, so the contrast gate passes in both themes.
- Do not edit anything under `web/src`; the parent session wires the video into
  the dialog.
