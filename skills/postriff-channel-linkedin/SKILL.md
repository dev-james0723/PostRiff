---
name: postriff-channel-linkedin
description: Prepare and validate linkedin native draft handoffs with exact account, destination and format bindings. This adapter does not provide a live publishing transport.
---

# linkedin adapter

This adapter adds what is specific to linkedin. The shared adapter contract (`postriff-adapter-contract`) is bound with it and governs asset rules, setup, browser fallback, approval and safety, the draft payload mapping, and verification. Its variants use `platform` `LinkedIn`.

## 1. Channel purpose

Concrete builder lessons and professional relevance, without corporate filler.

## 2. Audience and expected language

Planning language: `en`, subject to the workspace's actual audience. Preserve the creator's real angle as recorded in `IDENTITY.md` and `VOICE.md`; localize framing rather than mechanically translating. Keep qualifications and attribution intact.

## 3. Native content formats

The following are implemented **local draft schemas**, not current API capability declarations. Unsupported formats fail closed.

| Native format | Required media kind | Required native fields |
| --- | --- | --- |
| `linkedin.post` | optional | No extra fields |
| `linkedin.document` | document | `title` |

## 4. Caption/title/description rules

Write independently authored audience-facing `text`; put any required title or description in `notes`, labelled. Give the idea more room than it gets on X or Threads: open with the point in one or two lines, then the professional context (the situation, what is at stake, what changed and for whom), then a longer reflection on what the person learned, is weighing or would do differently, and close with one specific question or takeaway for peers. Short paragraphs of one to three sentences with a blank line between them; no corporate filler, no hashtag walls (at most three, at the end, only when the person uses them). Context and reflection frame what the approved facts and the idea support; they never add claims, numbers or experience the person did not supply. Stay within the `characterLimit` (3,000) and never silently truncate.
