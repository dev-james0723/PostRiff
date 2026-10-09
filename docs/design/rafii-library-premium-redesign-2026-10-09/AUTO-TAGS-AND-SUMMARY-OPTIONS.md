# Auto tags and a one-sentence summary per asset, without the AI budget (2026-10-09)

James asked for AI-generated tags and a one-sentence summary on every upload, at no cost to the AI budget.

## What exists today (free, no model)

- **Upload time.** The Library stores the first 360 characters of a document's text as `summary`.
- **Enrichment (`RAFII_LIBRARY_ENRICHMENT_ENABLED`, runs in the cron worker).** Builds an extractive "understanding card": verbatim sentences, single-word keywords and useful passages, each with evidence (`understanding.understand_local`).
- **Photos.** Only local features (dominant colours, orientation).

### Measured on James's own file

Run locally on `11_Full_20min_Teaching_Script.pdf` (18 pages):

| Method | Tags | Summary |
|---|---|---|
| Existing extractive card | seventh, tone, leading, chord, chords, minor, seven, slide | "seventh chord built on the leading tone. does not create a leading-tone seventh chord. Spell the C-minor leading-tone seventh chord." |
| Improved heuristic (phrases, slide numbers and timestamps removed) | seventh, chord, leading-tone, minor, leading tone, note | "Spell the C-minor leading-tone seventh chord." |

**Conclusion.** Free heuristics can produce key phrases and a representative sentence from the file. They cannot produce a real summary ("A 20-minute teaching script on leading-tone seventh chords …"), and they cannot tag photos. Both need a model.

## Free or near-free model routes

| Route | Cost | Privacy | Coverage | Effort |
|---|---|---|---|---|
| **A. Small open models in the background worker** (for example a ~0.5B instruct model for text, and a small captioning/zero-shot model for photos), run on Vercel CPU | No AI bill; compute only, seconds of CPU per asset | Stays on Rafii's own runtime | Every device, every upload | High: model files in the function bundle, cold-start time, worker time limits |
| **B. On-device in the uploader's browser** (Chrome's built-in Summarizer on Gemini Nano; a small image model via WebAssembly elsewhere) | Free | Stays on the device | Desktop Chrome for text summaries; slow or heavy on phones; iPhone Safari has no built-in model | Medium–high |
| **C. Cloudflare Workers AI free allocation** | 10,000 Neurons/day free; on a free account, calls past the cap fail (paid plan $0.011 per 1,000 Neurons) | Separate vendor; needs a Cloudflare account and token | Every device, but quota-bound | Low: HTTP calls from the worker, with the existing ledger and caps |
| ~~Gemini API free tier~~ | Free | Free-tier content may be used to improve Google products and read by reviewers | — | **Not acceptable for private uploads** |

## Recommendation

**Step 1 is built (2026-10-09, `library_autometa.py`, `extract-v1`).**
- Every processed document gets up to 5 tags. They are recurring key phrases from its text (English runs, Traditional Chinese terms of 2–6 characters). A file with no text is tagged from its file name.
- Each document also gets one sentence copied verbatim from the file.
- Automatic tags fill the tags field only when it is empty, are listed separately (`aiTags`), and show dashed in the inspector.
- The summary is labelled "Extracted".
- On your teaching script it produced: leading-tone seventh chords, minor, a-flat, diminished, major.


1. **Free layer (built, see above).** James asked for tags to appear automatically, so they do; they never overwrite tags a person set, and they stay visibly marked as automatic.
2. **AI layer:** choose A (no vendor, no quota, more engineering) or C (fastest, needs a free Cloudflare account and token; stops at the daily quota and falls back to step 1).
   - Every result is labelled as a model suggestion.
   - Every result is cached by content hash, so each file is analysed once.
   - The person can always correct it.
   - Photos only get real tags from A, B or C.
