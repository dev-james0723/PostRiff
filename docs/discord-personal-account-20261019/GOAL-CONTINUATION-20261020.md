# Rafii Discord Full Integration — controlled qualification checkpoint

Date: 2026-10-20 UTC. Status: **SOURCE CANDIDATE / PRODUCTION NO-GO**.

## Preserved boundaries

- Owned source: `codex/discord-personal-account-20261019`, based on `0c3e1bf615bce1213d786ce1e8c87e7875701e44`. Preserve existing PR #211 and all unrelated worktrees and agents.
- No live Discord message, OAuth grant, command registration, schema application, production promotion, new billing or runtime flags. Webhook and User Install remain default OFF.
- Use only standard `ubuntu-24.04` GitHub-hosted runners for this public repository: https://docs.github.com/en/actions/reference/runners/github-hosted-runners. No paid runners or retained artifact/cache spending.

## Current-source local evidence

- Python multi-mode/OAuth/security/CI wiring: **100 / 100 passed**, source-specific raw log `evidence/20261019-hybrid-focused-python-final.txt`.
- Node UI contracts: **15 / 15 passed**, `evidence/20261019-hybrid-focused-node-final.txt`.
- `git diff --check` passed. No provider effects.
- Mac TypeScript invocation with protective 1 GiB heap cap exited **134** (V8 heap limit). This is *validation unavailable*, not TypeScript success or evidence of a code error. Run full typecheck in clean Linux CI instead.

## Kynlo condition

- Kynlo Beta plist requests pressure-aware mode, but live governor was still legacy with `memory-warning-recovery`.
- Beta service process group contained unrelated Codex and Chrome; no blind bootout, kickstart or process kill permitted. Physical macOS OOM protection stays enabled.
- Kynlo Hybrid connectivity must be freshly verified before any service action; use existing independent paired Mac agent for reversible low-impact source qualification, not a forced service restart.

## Next gating conditions

Commit/push only reviewed isolated source; run exact-SHA public standard GitHub Linux CI (full Python, PostgreSQL RLS/concurrency, Node units, TypeScript, lint, build, and isolated 390/1280 browser/axe). Fix every actual failed gate without weakening security. Record immutable source/test identities and final GO/NO-GO.

Real provider OAuth, exact message sending, scheduled production execution and public release require distinct fresh authorization and are **not** approved by this engineering goal.

## Initial Linux CI checkout incident
- The first pushed candidate `db6e12fe5d3ea3e00fefef9ace5bc13202122b78` started https://github.com/dev-james0723/PostRiff/actions/runs/39356678790.
- Its exact-source checkout **failed before dependencies or tests**: historical tracked gitlink `vendor/xiaohongshu-mcp-v2.5.0-login-fix` lacks the corresponding `.gitmodules` URL. Later Node/build failures are dependent effects, not test results on installed dependencies.
- Repair keeps that unrelated vendor path untouched and replaces `actions/checkout` with an explicit detached exact-SHA fetch/checkout, consistent with existing repository workflows. Downstream validation steps are now conditional on successful preparation.
- New local RED→GREEN checkout-contract regression observed one failure on the original workflow and four passes after the targeted fix. Fresh Linux acceptance for this new source is still required.
