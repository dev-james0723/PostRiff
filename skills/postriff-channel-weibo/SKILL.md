---
name: postriff-channel-weibo
description: Prepare and validate weibo native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
metadata:
  version: 1.1.0
---

# weibo adapter

This adapter adds what is specific to weibo. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Weibo`.

## 1. Channel purpose

Chinese public microblog with restrained topic markers; schedule authority is separate.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `weibo.post` | optional | No extra fields |
| `weibo.video` | video | `title` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Chinese public microblog with restrained topic markers; schedule authority is separate. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 5. Native reasoning

Editorial guidance reviewed 2026-10-09. It describes how readers use the surface, not current ranking rules: nothing here is an algorithm guarantee, and any platform limit stays unverified until a current constraint record exists. Examples are illustrations, never facts about the creator.

- A Weibo post is a short, public, timely statement: the first sentence carries the news or the point, then one or two lines of context.
- A topic tag (#话题#) is optional and only when the post genuinely belongs to that topic; never attach an unrelated trending topic.
- A video post needs a real video and a title field; the post text introduces it rather than transcribing it.
- Public replies arrive fast: avoid ambiguous claims that would need correction; keep qualifiers from the source.
- Register is concise Simplified Chinese unless the destination tag says otherwise; Traditional destinations get their own wording.
