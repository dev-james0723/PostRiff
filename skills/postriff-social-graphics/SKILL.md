---
name: postriff-social-graphics
description: Create, adapt, and validate platform-native static social graphics, carousels, editorial covers, thumbnails, and vertical-video covers for a workspace's campaigns. Use after a CanonicalBrief and target ChannelDrafts exist; do not use for writing full captions, producing finished video, or publishing.
license: MIT
metadata:
  status: project-local-not-globally-installed
  derived-from: SocialMediaGraphicSkill.md
  project-contract: postriff-social-media-suite-design-revision-12
---

# PostRiff social graphics

Produce reviewable, platform-native visual assets for one workspace's creator, whose identity, brands, and visual preferences come from its memory files. This skill implements the static-graphic mode of the suite's `media-generation` layer. It consumes approved project contracts and returns asset candidates; it owns no account, scheduling, or publishing action.

## Required inputs

Load, in order:

1. The active `CanonicalBrief`.
2. Target `ChannelDraft` records and their `native_format_id` values.
3. Current account/platform capability records.
4. Available brand context, real photos, screenshots, video frames, logos, and font licenses.
5. The PostRiff Content Engine and its brand-identity selection.

If the brief lacks the creator's point of view, factual support, target formats, or required real media, stop with a clear missing-input record. Do not invent the creator's experience, product results, quotations, performance history, or emotional state.

## Route to the relevant reference

- Read [references/platform-output-specs.md](references/platform-output-specs.md) for every requested target. It contains planning defaults, native format families, and the required runtime-check boundary.
- Read [references/template-recipes.md](references/template-recipes.md) only for the selected content mode: current news, build-in-public, product launch, YouTube release, music/performance, personal reflection, education, or event/service.
- Read [references/guizang-visual-catalog.md](references/guizang-visual-catalog.md) for every visual request. Record whether its Editorial or Swiss reference system is eligible, not applicable, declined, or unavailable; applying it remains optional and subordinate to the selected brand, facts, rights, and current native format.
- Read [references/asset-contract-and-validation.md](references/asset-contract-and-validation.md) before production and again before returning the asset receipt.

## Decision sequence

### 1. Decide whether a visual adds meaning

Use no visual when a text-led X, Threads, LinkedIn, Reddit, Dcard, Zhihu, Bluesky, or Mastodon post is stronger without one. Never manufacture a quote card or decorative stock image merely to fill a slot.

Choose the source treatment:

- `real_photo`: the creator's performance, studio, workspace, event, or everyday life.
- `real_screenshot`: product UI, feature walkthrough, release evidence, chart, or document.
- `video_frame`: cover or thumbnail derived from a real recording.
- `generated_editorial`: conceptual, metaphorical, or atmospheric imagery that cannot be mistaken for documentary evidence.
- `designed_graphic`: typography, diagram, timeline, comparison, data, or carousel composition.
- `hybrid_composite`: real evidence plus designed labels, crop, hierarchy, or annotation.

For factual product/news content, prefer official or real evidence. A generated image must never imitate an official screenshot, product photograph, news photograph, medical image, event record, or proof that something happened.

### 2. Pick one visual thesis

Write a one-sentence visual thesis that supports the canonical claim. The image should communicate one of these jobs:

- establish the subject;
- show evidence;
- explain a relationship;
- make a sequence understandable;
- create an emotional frame;
- demonstrate a product or musical idea;
- give the viewer a reason to open the caption, article, or video.

Do not repeat the entire caption on the image. Avoid generic motivation, fake controversy, decorative metrics, engagement bait, and a fixed "five tips" structure when the idea does not need it.

### 3. Choose a master composition family

Use one of:

- `portrait-editorial` for feed visuals and visual essays;
- `square-adaptive` for destinations where square is safer or more native;
- `landscape-editorial` for link cards, article covers, video thumbnails, and wide feeds;
- `vertical-fullscreen` for Story, Reel/Short/TikTok covers, and vertical-video packaging;
- `vertical-pin` for Pinterest;
- `document-carousel` for LinkedIn or platform-native page documents;
- `native-article-cover` for note, Naver Blog, Zhihu, or an owned article;
- `community-native` for Reddit, Dcard, Discord, Telegram, Feishu/Lark, QQ, LINE, or Kakao contexts.

One composition may seed variants, but do not crop blindly. Recompose headline position, subject scale, reading order, and negative space for each aspect ratio.

If the visual choice is material, use the Guizang catalog to recommend no more
than three complete combinations of visual system, theme, and ordered layout
recipes, plus `No Guizang template / decide for me`. Xiaohongshu cards and WeChat
Official Account cover pairs should normally include an eligible Guizang option.
Do not expose an upstream option as executable when its state is
`reference_only`, `needs_review`, or license-blocked; the review must distinguish
a project-local interpretation from the actual upstream renderer.

### 4. Select the production method

- Use an image-generation tool for original conceptual/editorial imagery.
- Use HTML/CSS or another deterministic renderer for text-heavy graphics, diagrams, timelines, comparisons, and data cards.
- Use image editing/compositing for real screenshots, photos, product UI, and video frames.
- Use the relevant video workflow for motion assets; this skill may prepare a cover and motion brief but must not label a static image as a finished Reel, Short, TikTok, Douyin, Kuaishou, Moj, Snapchat, or WeChat Channels video.

Do not require HTML/CSS for every asset. Choose the renderer that preserves evidence, typography, export quality, and editability.

### 5. Build an asset family

Create only the variants required by selected `native_format_id` records. Keep a stable `variant_group_id` and record which asset is the source composition.

For carousels, design the complete sequence before rendering individual slides:

1. Cover: one clear promise, question, or tension.
2. Context: what happened or what problem exists.
3. Evidence or explanation: one idea per slide.
4. The creator's observation: distinguish interpretation from fact.
5. Unknown, trade-off, or limitation when relevant.
6. Landing: conclusion or useful next step; CTA only when earned.

The number of slides follows the idea. Do not add filler to reach a template count.

### 6. Localize visually

English, Traditional Chinese, Simplified Chinese, Japanese, Korean, and Indian regional-language graphics are separate layout variants. Reflow typography, punctuation, line breaks, emphasis, and reading density; do not paste translated text into an unchanged box.

Use Cantonese expressions only for an appropriate Hong Kong-facing account. Mainland-facing Xiaohongshu, Douyin, Weibo, WeChat Channels, Bilibili, and Kuaishou normally use natural Simplified Chinese. Dcard normally uses Taiwan Traditional Chinese. Machine translation alone cannot qualify a regional-language asset for unattended use.

Never translate a claim into a stronger claim. Preserve attribution, uncertainty, correction state, and qualification on every visual.

## Visual direction

Start from the workspace's own visual preferences in `BRAND.md` and any approved
past assets. Absent those, aim for editorial clarity with real attention to
rhythm, silence, texture, and pacing. The visual identity should feel human,
calm, specific, and contemporary — not like a generic startup template or an
influencer growth pack. These are defaults to be overridden by a stated
preference, not a house style to impose.

Prefer:

- meaningful negative space;
- a restrained palette with one purposeful accent;
- real material texture, photography, interface detail, working documents, or subtle systems imagery when relevant;
- typography with a clear reading order;
- visual contrast between the two sides of the creator's stated tension;
- imperfect human detail where it supports truth;
- consistency across a campaign without repeating the same layout.

Avoid:

- corporate blue as an automatic LinkedIn style;
- gradients, rounded cards, emojis, diagonal shapes, oversized numbers, or dark mode as automatic engagement devices;
- invented quotes, fake UI, fake metrics, fake testimonials, and fake before/after evidence;
- tiny body copy, edge-to-edge headline clutter, decorative hashtags, and unnecessary logos;
- engagement-bait text such as "Agree?", "RT if you agree", "Double tap", or "Save this" unless the user explicitly approves it and it genuinely serves the content;
- visually identical English, Chinese, Japanese, and Korean derivatives;
- relying on a mechanical safe-zone pass as proof of visual quality.

## Brand architecture

Select one identity per asset unless the campaign explicitly connects them:

Read the declared identities from the workspace `BRAND.md`. Typical shapes and
their visual character:

| Shape | Visual character |
|---|---|
| Personal | Reflective, personal, editorial; carries the creator's stated tension |
| Product or project | Clear, practical, product-led, real UI evidence |
| Service or studio | Warm, professional, photographic, service-oriented |
| Institution or event | Welcoming, credible, cultural, community-oriented |

A workspace speaks with one brand, so a graphic carries that workspace's identity; never invent a second brand. Do not place every project logo on a personal post. Do not insert personal vulnerability into a project-account graphic.

## Text-on-image rules

- Treat all numeric limits as composition heuristics, not universal laws.
- Use the fewest words that preserve the idea; do not impose a universal six-word line or three-line maximum.
- Make the smallest essential text readable in a phone-size preview.
- Keep one dominant headline and at most one subordinate explanatory level on covers.
- Put sources on data/news graphics when the visual contains a factual claim; retain full source metadata in the asset manifest.
- Never use a quotation mark treatment unless the exact quotation and attribution are verified.
- Keep important text and faces inside the current adapter's safe-area profile, then inspect the real platform preview when available.

## Output

Return:

1. A short visual rationale tied to the canonical brief.
2. The exact target/native-format list.
3. A structured asset manifest for every candidate.
4. Files or generation/edit prompts, with source and rights notes.
5. A contact sheet or equivalent review surface when more than one asset/slide exists.
6. Validation results separated into mechanical, visual, factual, localization, accessibility, and rights checks.
7. Explicit `not_done` items and blockers.

The asset manifest also records `visual_reference_provider`, reviewed commit,
provider state, selected system/theme/layout IDs, template version/hash, and
license mode whenever a Guizang reference influences the result.

An asset is `candidate_ready` only after local validation. It is not `approved`, `uploaded`, `scheduled`, or `published`. Any change to text, crop, ordered slide sequence, source media, language, or target format after campaign approval invalidates the affected approval receipt.

## Hard boundary

This skill never authenticates, uploads, schedules, publishes, edits, deletes, boosts, or verifies a live post. It prepares graphic candidates for the suite's existing approval and publishing pipeline.

## Curated content craft

For static graphics, carousels and video covers, also read the installed
`postriff-content-craft/references/visual-handoff.md` and the relevant sections of
its `platform-playbooks.md` and `algorithm-practice.md`. Coordinate cover/title,
slide/caption and opening visual/spoken promise; preserve meaningful pauses, real
media and the selected brand. Consider discovery/retention hypotheses when useful,
without turning experimental word counts or slide counts into composition rules.
These references supplement this skill's existing Guizang and validation workflow.
