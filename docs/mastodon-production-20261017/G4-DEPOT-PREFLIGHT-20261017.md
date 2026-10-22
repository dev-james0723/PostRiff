# Rafii × Mastodon — G4 Depot Linux Preflight
Date: 2026-10-17 · **Platform readiness PASS; actual E2E and capacity NOT RUN; Production/Public NO-GO.**

## Source and execution boundary

- Local isolated worktree: `/Users/ouxianxing/Documents/.agent-worktrees/rafii-mastodon-public-rc-20261017`.
- Starting G3 R2 source: `9a5108e7d2817cf20711d67af29b10b8475dadc7`; manually scoped Depot CI workflow commits: `a8edfd86f7542d19fa76f70e0f9599d09e062a63` and checkout-remediation `2769f83bcd731d00f8950f0196d84981328233eb`.
- Remote `consumer-saas` main remained `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1`; Depot CLI uploaded an approximately 4.8 MB source **patch to Depot Cache**, not a GitHub Push/PR/Merge.
- Depot org `jf34f85hr0`; CLI v2.102.15; workflow `.depot/workflows/mastodon-g4-linux-preflight.yml`: manual `workflow_dispatch`, exactly one selected `preflight` job, `depot-ubuntu-24.04` 2 CPU/8 GB, `timeout-minutes: 3`, contents read permission, no package installs or real Mastodon calls. No automatic retry.

## Actual remote runs

| Run | UTC interval | Result | Evidence |
| --- | --- | --- | --- |
| `1jzd7jlcsb` | 19:06:55–19:07:06 (11 s) | FAILED before test | Checkout failed at orphan Gitlink; no Mastodon test ran |
| `7zk48c2bh0` | 19:11:37–19:11:55 (18 s) | **FINISHED/PASS** | Patch applied, candidate verified, Linux tool inventory recorded |

First run failed during `actions/checkout`: the repository contains two Gitlinks under `vendor/xiaohongshu-mcp-v2.5.0-*` with no `.gitmodules` metadata. A throwaway local index test proved that excluding these **in the copy only** makes Git's submodule iteration succeed. Revised Depot checkout used a contents-read token only until the controlled first step, then removed it and removed both orphan Gitlinks from the ephemeral runner's **index only**. Original repository Gitlinks, Mac worktrees and GitHub remained intact.

## Verified Ubuntu 24.04 runner inventory

- `uname` reported genuine **Linux x86_64**, two CPUs; source patch verified with SHA-256 of `G3-R2-READONLY-20261017.md` = `9d53f7329990d3a5678688e1f125a46e01d454322029f60947ec60f2e0bb026c`, and migrations `131`/`132`/`133` present.
- Node `v22.23.2`, npm `10.9.8`, Python `3.12.3`, PostgreSQL `16.15` CLI and pg_config available, Python `cryptography` available.
- **Missing:** project `web/node_modules`, Python `psycopg`, Playwright Python, pytest and cached Linux Chromium/WebKit revisions. Node 24 is also not the active runner Node.
- No authenticated workspace browser, real Mastodon OAuth, provider post, test database admission, Linux browser journey or 1,000-user concurrency execution occurred. A successful source checkout is **not** an E2E or load test.

## Cost / entitlement facts

- Depot's published 2 CPU rate is **$0.0001/sec ($0.006/min)** with per-second billing. Wall clock run intervals were 11s and 18s; the rough runner-compute estimate is **$0.0011 + $0.0018 = $0.0029** if fully billable and excluding separate storage, cache, tests, plan fees, taxes or credits. This is NOT an invoice or confirmed additional charge.
- Each run was constrained by `timeout-minutes: 3` (~$0.018 of runner compute at this published rate); actual organization usage cap, credits and invoice attribution remain **unverified**. Included plan minutes are NOT a hard cap.

## Why the Linux release gates remain closed

1. Full offline Python/PostgreSQL synthetic load test requires `psycopg`; project Linux Playwright E2E needs pinned Node packages, a matching Chromium and WebKit, and a separately reviewed WebKit acceptance harness. Runner currently lacks these.
2. Previous user conditions explicitly forbade downloads/installs and new unbounded paid resource use. The new request to use Depot allowed this **small timeboxed Depot preflight**, not permission to install packages, trigger retries or enable production providers.
3. Existing CI browser scripts exercise Chromium only, and cloud scripts may invoke external `apt-get`, `npm install`, Playwright downloads and artifact upload; none was run in these two preflights.
4. Before proceeding, obtain express authorization for timeboxed **pinned dependency/browser installation** inside a separate Depot job and a cost ceiling. Preserve a non-production isolated test environment, no real Provider calls, no production keys and no GitHub Push/PR/Merge/Deploy. Disallow automatic retries and cap runner execution time.

## Decision

**G4 Depot connection, patch and Linux base runtime: PASS. Linux Chromium E2E: NOT RUN. Linux WebKit E2E: NOT RUN. Linux 1,000-user capacity: NOT RUN. Real Mastodon provider acceptance: NOT RUN. Public/Production: NO-GO.**

Evidence: `~/Documents/Rafii-Mastodon-Public-RC-20261017/evidence/depot-g4-preflight-dispatch.log`, `depot-g4-preflight-attempt.log`, `depot-g4-preflight-round2-dispatch.log`, `depot-g4-preflight-round2.log`, `depot-g4-runner-readiness.json`.
