---
documentId: help_ts_writer_unavailable
sourceType: troubleshooting
title: The writer or model is unavailable
summary: Why a model cannot run and what Rafii does instead.
routeFamilies: [models, home, billing, help]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: ts-writer
keywords: [model unavailable, writer unavailable, claude not signed in, codex login, budget, stop-line, 402, 模型用唔到, 模型唔得, 登入]
---
# The writer or model is unavailable

## A CLI writer is not signed in

Claude Code or Codex must be installed and signed in on the machine that serves Rafii. Run its sign-in in Terminal, then choose Check again on [Models & providers](/app/account/models).

## The managed model is over budget

Each paid call reserves its estimate first. It does not run when the writing allowance is used up, the workspace budget is not approved yet, or the spending stop-line would be passed. See [Usage & plan](/app/account/billing).

## What Rafii does instead

Rafii never switches to a different paid model on its own. The Rafii panel answers from help articles and your workspace without a model and says so; drafting waits until a writer is available.
