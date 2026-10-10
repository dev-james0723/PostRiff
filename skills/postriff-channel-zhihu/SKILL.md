---
name: postriff-channel-zhihu
description: Prepare and validate zhihu native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
metadata:
  version: 1.1.0
---

# zhihu adapter

This adapter adds what is specific to zhihu. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `Zhihu`.

## 1. Channel purpose

Credible sourced depth; answers bind to one exact open question.

## 2. Audience and expected language

Planning language: `zh-Hans`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `zhihu.answer` | optional | `question_ref`, `promotion_disclosure` |
| `zhihu.article` | optional | `title` |
| `zhihu.idea` | optional | No extra fields |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Do not invent personal experience or product facts. Credible sourced depth; answers bind to one exact open question. Character limits remain unverified until a current account-specific constraint record exists; never silently truncate copy to fit an assumed limit.

## 5. Native reasoning

Editorial guidance reviewed 2026-10-09. It describes how readers use the surface, not current ranking rules: nothing here is an algorithm guarantee, and any platform limit stays unverified until a current constraint record exists. Examples are illustrations, never facts about the creator.

- Zhihu is question-led: an answer addresses the question that was actually asked, leads with a direct conclusion, then gives reasoning and evidence from the supplied facts.
- Disclose affiliation or promotion where the native field asks for it; an answer that sells without saying so is not acceptable.
- An article states its thesis in the title and develops it with sections; an idea (想法) is a short observation, not a compressed article.
- Separate what is established from what is opinion; cite sources plainly; never invent credentials, experience or data.
- Register is careful written Simplified Chinese unless the destination tag says otherwise.
