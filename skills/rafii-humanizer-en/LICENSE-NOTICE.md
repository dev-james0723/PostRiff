# Licence notice: rafii-humanizer-en

This knowledge pack and the English section of
`src/postriff_phase2/coworker/humanizer_patterns.json` are adapted from the
works below. Both are under the MIT License, and their notices are reproduced
here as that licence requires.

## blader/humanizer (v2.8.0)

Source: https://github.com/blader/humanizer. The pattern catalogue is based on
Wikipedia's "Signs of AI writing" (WikiProject AI Cleanup). No Wikipedia text is
reproduced here. Only the observations, as summarised by the upstream skill, are
used.

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

## op7418/Humanizer-zh

Source: https://github.com/op7418/Humanizer-zh. From this skill we used its
meaning-preservation priorities (keep information and degree of certainty first;
keep negation, conditions, status and attribution) and the intents of its
fixture cases.

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

## What was adapted

- All 33 upstream pattern families (content, language, style, communication, and
  filler and hedging) were condensed into `references/patterns.md`. Each has a
  detector id, a fix and a keep-when rule.
- The upstream "AI vocabulary" list, the signposting phrases and the chatbot
  artefacts became regexes and word lists in `humanizer_patterns.json`. Several
  clues specific to social copy were added: engagement bait, hook formulas,
  unfilled template slots, chatbot citation markup, and residue from the editing
  stage itself.
- The false-positive guidance ("what not to flag") and the signs of human
  writing were kept. They were tightened into a cluster rule backed by numeric
  thresholds.
- The voice-calibration idea was generalised. The voice now comes from the
  workspace's approved voice (`VOICE.md`), its examples and overlays, and not from
  one person's writing sample.
- Every before-and-after example was rewritten. Some upstream "after" examples
  add facts (a named survey, a year, a building). Rafii examples use only
  information present in the "before" text.

## What was excluded, and why

- **The em/en-dash ban (upstream §14 and the final scan for dashes).** Dashes are
  legitimate punctuation and part of many approved voices. Here dash density is
  only a clue (`dash_density_per_100_words_clue`).
- **"PERSONALITY AND SOUL" (have opinions, let some mess in, add first person,
  humour or tangents).** Adding opinions, feelings or asides that the owner did
  not supply violates the product rule against inventing content. It also
  imposes a house voice. The voice is anchored to the workspace instead.
- **The draft, audit and final output ritual, and the change summary.** Inside a
  product run, the humanizer returns only the final text. Findings go to the
  run's structured note or warning field. There is no self-score.
- **The upstream full example.** It introduces named people, studies and
  statistics that are absent from its input. That is exactly the failure the
  meaning check exists to block.
- **Any personal or workspace-specific voice, topic or default.** This pack is
  customer-neutral.
