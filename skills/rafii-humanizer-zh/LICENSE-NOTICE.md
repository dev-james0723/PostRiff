# Licence notice: rafii-humanizer-zh

This knowledge pack and the `zh` and `yue` sections of
`src/postriff_phase2/coworker/humanizer_patterns.json` are adapted from the
works below. All three are under the MIT License, and their notices are
reproduced here as that licence requires. The meaning fixtures in
`tests/fixtures/humanizer_meaning_cases.json` whose `origin` begins "adapted
from humanizer-zh" derive from Humanizer-zh's `tests/fixtures/cases.json`.

## op7418/Humanizer-zh

Source: https://github.com/op7418/Humanizer-zh (revision 2026-09-23).

```
MIT License

Copyright (c) 2026 歸藏

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## lieflat-less-ai-tone

The translationese marker table (`scripts/check-translationese.py` MARKERS) and
the whitelist editing discipline.

```
MIT License

Copyright (c) 2026 shiujan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## blader/humanizer (upstream lineage of Humanizer-zh families A–E)

```
MIT License

Copyright (c) 2025 Siqi Chen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## What was adapted

- **From Humanizer-zh:**
  - The editing constraints and their priority order (keep information and
    certainty; respect scope and genre; match the voice; then fix the patterns).
  - The genre guidance.
  - The 31 patterns in families A–F, with their keep boundaries. These are
    condensed in `references/patterns.md`, and each has a detector id.
  - The final checks.
  - The file and structure protections.
  - The 18 meaning-preservation case intents. These were re-expressed as
    source, bad rewrite and good rewrite, with some moved into zh-Hant, Hong
    Kong written Chinese, written Cantonese and English.
  - One example about a named group was generalised to a neutral association.
- **From lieflat-less-ai-tone:**
  - The whitelist discipline: minimal edits, unmatched sentences stay verbatim,
    and every content word must trace back to the source.
  - The list of features that are not a reason to edit.
  - Rules 1–11, folded into families A–F.
  - The translationese marker table. Its regexes were widened to full-width
    punctuation, given Traditional-character variants and tagged `actionable`,
    so that only the five structures upstream calls actionable can justify an
    edit.
- **New in Rafii:**
  - Traditional-character variants for every zh regex.
  - Written-Cantonese (yue-Hant-HK) markers and patterns, and a check for
    accidental 書面語/口語 mixing.
  - Script-integrity markers.
  - Regional-vocabulary and punctuation guidance for Mainland, Taiwan and Hong
    Kong.
  - Code-switching preservation.
  - Protection for brand terms.

## What was excluded, and why

- **Output rituals** (a draft plus a hit list, self-scores, explanations). Inside
  a product run the pass returns only the final text. Notes go to the run's
  structured fields.
- **The lieflat research statistics and per-model frequency claims.** Only the
  decisions derived from them are kept, as `actionable` flags and thresholds. The
  numbers belonged to a specific corpus and are not reproduced as product claims.
- **Any fixed personal voice, topic or regional default.** This pack is
  customer-neutral. Register comes from the workspace's brief and `VOICE.md`.
- **A dash ban.** As upstream Humanizer-zh already does, dashes are only a
  density clue.
