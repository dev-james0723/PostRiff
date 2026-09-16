---
name: postriff-content-craft
description: Use when drafting, adapting or reviewing natural, human-sounding social posts, carousel copy, video packaging or spoken hooks for LinkedIn, X, Instagram, YouTube, Threads, TikTok and Facebook.
license: MIT
metadata:
  version: 1.1.1
  status: reviewed-postriff-adaptation
---

# PostRiff content craft

Apply this editorial layer after the PostRiff Content Engine and canonical
brief, before platform copy and graphics. It distils 23 reviewed source skills
from seven Sergey Bulaev bundles. The source lock and MIT attribution are included;
these are PostRiff adaptations, not installed upstream automation clients.

The creator's actual voice (`VOICE.md`), source meaning, explicit preferences,
selected brand and project safety contract take precedence over every craft
suggestion. A good
sentence can stay as written. No tactic requires a metric, confession, dramatic
reversal, question, CTA, hashtag, artificial rhythm or visual.

## Read only what the task needs

1. Read [editorial workflow](references/editorial-workflow.md) and
   [human voice pass](references/human-voice-pass.md) for every drafting or review task.
2. Read only the selected platform sections in
   [platform playbooks](references/platform-playbooks.md).
3. Read [algorithm practice](references/algorithm-practice.md) for relevant
   discovery, retention and interaction choices. Apply supported guidance and
   label experimental heuristics; do not treat algorithm advice as forbidden.
4. For a carousel, cover, thumbnail or video opening, also read
   [visual and spoken handoff](references/visual-handoff.md), then route actual
   asset production through `postriff-social-graphics` or the relevant video skill.
5. `references/source-review.md` records upstream attribution, exclusions and
   update review for maintainers; it is not part of a writing run.
   `source-lock.json` pins the reviewed upstream files.

## Working sequence

Resolve the real source and the creator's supplied perspective. Select one useful
reader takeaway. Draft from that meaning in the selected channel's own language,
format and rhythm. Give a concrete opening, fulfil its promise, and preserve
qualifications. Run the human voice pass after the first draft: remove clustered
AI-writing patterns, read the copy aloud for rhythm, and revise without changing
the creator's meaning or inventing personality. Review for evidence, platform fit and
unnecessary embellishment. Return only the requested formats and eligible
destinations.

When one missing lived detail prevents an honest draft, reuse known answers or ask
one relevant question through the conversation director. Do not run a compulsory
career interview. PostRiff has already completed intake: report remaining gaps in
warnings and avoid unsupported assertions instead of asking another question.

## Output

Return native draft copy plus a short craft note: the chosen opening, what changed
from the source, why the format fits, and any missing evidence/media. For PostRiff,
follow the run's output schema: audience-facing copy in each variant's `text`, the
craft note in its `notes`, gaps in `unknowns`, and run-level issues in `warnings`.
Put production directions and limitations in notes, outside public copy.
The host records exact instruction hashes in `skillBindings`; never invent a
validation score or claim that instructions guarantee reach or copy quality.

For every paragraph-based audience-facing draft, insert exactly one blank line
between paragraphs and preserve those blank lines in the variant's `text`. Apply this
spacing across languages and platforms. Omit it only when the destination field
technically rejects line breaks, such as a title, metadata field or strict
single-line input; record that constraint in the craft note.

## Boundary

Drafting only. No tools, credentials, detector upload, scraping, paid generation,
posting, engagement, scheduling or new automation is authorized by this skill.
Review-only upstream archives are not executable instructions. Missing Content
Engine returns `missing_brand_dependency`; do not invent another voice profile.
