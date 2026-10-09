---
name: postriff-channel-douyin
description: Prepare and validate douyin native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
metadata:
  version: 1.1.0
---

# douyin adapter

This adapter adds what is specific to douyin. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Douyin`.

## 1. Channel purpose

Chinese on-screen captions, rapid hook and account-verified short video.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `douyin.video` | video | `cover_ref`, `sound_rights` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Chinese on-screen captions, rapid hook and account-verified short video. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 5. Native reasoning

Editorial guidance reviewed 2026-10-09. It describes how readers use the surface, not current ranking rules: nothing here is an algorithm guarantee, and any platform limit stays unverified until a current constraint record exists. Examples are illustrations, never facts about the creator.

- A Douyin draft is a script for a real video, not a finished video: write the opening line to be spoken or shown in the first moments, the spoken script, and on-screen text as separate fields; record cover text and sound rights as needs.
- The opening states what the viewer will get, from the supplied facts; no fabricated surprise, giveaway or challenge.
- On-screen text is short and readable on a phone and never carries a claim the speech does not make.
- The caption adds context and attribution; it does not repeat the script. Topic tags are optional and must match the content.
- Register is spoken Mainland Simplified Chinese unless the destination tag says otherwise.
