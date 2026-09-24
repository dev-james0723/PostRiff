---
documentId: help_privacy_models
sourceType: product_help
title: Models, providers and your data
summary: Which writer runs, what leaves Rafii, and the owner's cloud switches.
routeFamilies: [models, memory, account, help]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: privacy-models
keywords: [model, writer, provider, claude, codex, cloud, egress, privacy, data, which ai, 模型, 供應商, 雲端, 私隱, 隱私, 資料, 邊個AI]
---
# Models, providers and your data

## Three kinds of writer

On [Models & providers](/app/account/models) you choose where drafts are written:

- A coding CLI (Claude Code or Codex) signed in on the machine that serves the Rafii API, paid by its own subscription.
- Rafii's managed model, metered to this workspace in writing batches.
- The deterministic preview, which calls no model and costs nothing.

The writer you pick is used by Home, every conversation and the Rafii panel in this browser. On a hosted deployment a CLI will run through a desktop companion on your own computer; that companion is not available yet.

## What leaves Rafii

- The text you draft from (an idea, a link, your message) goes to the writer you picked.
- A cloud model reads your memory files only when an owner turns on cloud memory, and never a boundary marked private or local-only.
- A cloud model reads a source's approved facts only when that source's cloud switch is on.
- Web research sends search queries only when an owner turned research on.

## Rafii panel answers

When the Rafii panel uses a cloud writer to phrase an answer, it sends the help passages and workspace facts needed for your question (states, counts, times and reasons), not your drafts, sources or private memory. With a writer on your own machine it may include draft text you asked about.

## Owner switches

Only an owner can turn cloud memory and web research on or off, on [Memory](/app/workspace/memory). Each decision is recorded in the audit log.
