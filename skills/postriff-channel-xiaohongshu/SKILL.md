---
name: postriff-channel-xiaohongshu
description: Prepare and validate xiaohongshu native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
metadata:
  version: 1.2.0
---

# xiaohongshu adapter

This adapter adds what is specific to xiaohongshu. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Xiaohongshu`.

## 1. Channel purpose

Cover-first useful Chinese notes; keep third-party research signals separate from browser publishing.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `xiaohongshu.note` | image | `title`, `originality` |
| `xiaohongshu.video` | video | `title`, `originality` |

## 4. Caption/title/description rules

The title opens `text` (the preview and the note page show the first line as the title): at most 20 characters, each Chinese character counting as one, concrete about what the reader will save rather than clickbait. Then a blank line and a structured body: a one- or two-line hook, then the useful points as short lines or a short numbered or bulleted list. A closing line that invites saving or a comment is optional; leave it out when it would feel forced. Topic tags are optional: when they help readers find the note, add a few on the last line written `#tag`, no spaces inside a tag (for example `#学习笔记 #读书分享`), chosen from the topic, never trending tags unrelated to it; no fixed number is required. Write natively for Xiaohongshu readers: first person, practical, warm and specific, in Simplified Chinese unless the destination's `languageId` says otherwise; not a translated LinkedIn post. The body stays within the `characterLimit` (1,000). Keep WeChat IDs, phone numbers, links and other ways off the platform out of the text: Xiaohongshu hides notes that send readers away. Do not invent personal experience or product facts. PostRiff drafts Xiaohongshu notes for review, copy and export; it has no publishing route for them.

## 5. Native reasoning

Editorial guidance reviewed 2026-10-09. It describes how readers use the surface, not current ranking rules: nothing here is an algorithm guarantee, and any platform limit stays unverified until a current constraint record exists. Examples are illustrations, never facts about the creator.

- The note is read cover-first: the cover image (or first frame) and the title make one promise, and the body keeps it. Plan what the cover shows before writing; record cover text and alt text as separate fields, never inside the body.
- Useful beats clever: a reader saves a note that answers a concrete question (how, which, what to avoid) with specifics from the supplied facts. When the facts do not support a step, leave it out and list it under unknowns.
- Image notes carry the sequence: one idea per image, in the order the body uses them; the body adds context instead of repeating every word on the images.
- Register follows the destination tag: zh-Hans-CN writes Mainland Simplified usage; zh-Hant-TW and zh-Hant-HK readers need their own wording, not a character conversion.
- Example (illustration only): a cover reading 「新手揉面三个误区」 promises three mistakes; the body names three, each tied to a supplied fact.
