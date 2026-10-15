---
name: postriff-channel-bilibili
description: Prepare and validate bilibili native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
metadata:
  version: 1.2.0
---

# bilibili adapter

This adapter adds what is specific to bilibili. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Bilibili`.

## 1. Channel purpose

Deep-dive, hobbyist and creator content with community context and useful depth.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `bilibili.video` | video | `title`, `description`, `cover_ref`, `category` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Deep-dive, hobbyist and creator content with community context and useful depth. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 5. Native reasoning

Editorial guidance reviewed 2026-10-09. It describes how readers use the surface, not current ranking rules: nothing here is an algorithm guarantee, and any platform limit stays unverified until a current constraint record exists. Examples are illustrations, never facts about the creator.

- Bilibili viewers often choose a video from its title and cover, then expect depth: the title names the specific subject, the description summarises what the video covers in order and credits sources.
- Write a chaptered spoken script: an opening that states the question, sections that each answer one part, and a close that summarises without a forced call to action.
- Category and cover are native fields; leave them unresolved rather than guessing.
- Keep corrections and caveats visible; long-form audiences notice when a claim lacks support.
- Register is conversational Simplified Chinese by default; follow the destination tag when it differs.
