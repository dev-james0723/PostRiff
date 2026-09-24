# Raffi idle loop (not generated yet)

**Status on 2026-09-24:** blocked before generation. Nothing has been charged.

The motion will come from an image-to-video model on Vercel AI Gateway: Veo 3.1 or Kling, driven by first-frame and last-frame keyframes. It won't be a code rig. AI Gateway refuses every video job while the team's credit balance is under $10. The balance is $4.88, and the error is HTTP 402 `insufficient_funds`. To unblock it, top up AI Gateway credits for the team "jamesau0723-6572's projects". The $10 floor is checked before every job, so keep the balance above $10 plus the cost of the runs you plan.

## What is here

| File | What it is |
| --- | --- |
| `source/raffi-front.png` | Pose 1 (front view) cut from the character sheet: straight alpha, 416×502, transparent corners, no shadow. |
| `source/raffi-front@2x.png` | 2× working copy (832×1004) used to build the model keyframes. |
| `source/crop-box.json` | Crop box `x 242–658, y 12–514` of the 1536×1024 sheet, the background colour, and the matting method. |

The sheet background is a flat off-white (std under 0.5/255). An AI subject mask (`hyperframes remove-background` 0.8.73) is used only as a trimap. The edge band is re-solved against the known background, so the fur keeps its detail with no off-white halo.

## Still to do (after the top-up)

This section follows the Dori deliverable:

- `out/` (git-ignored): ProRes 4444 master, VP9-alpha WebM, HEVC-alpha MOV (via `avconvert`, alpha checked with AVFoundation), PNG sequence, contact sheet and `preview.html`.
- `web/public/raffi/`: a 320 px WebM and MOV, plus posters at 512, 256, 128 and 64 px.
- Measured numbers: loop seam, frame-to-frame smoothness, identity against `source/raffi-front.png`, and alpha checks.

This README gets replaced once the loop exists.
