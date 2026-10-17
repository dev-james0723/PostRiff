# Rafii × Mastodon — G3 Linux resource and isolation readiness
Date: 2026-10-17 · Source: Kynlo MacBook Pro · **Local Linux execution: NO-GO**

## Source and permission scope

- Private working tree: `/Users/ouxianxing/Documents/.agent-worktrees/rafii-mastodon-public-rc-20261017`.
- Start commit `b723b95d902cc4a42815951394ab3306524c2db4`; previous integrated RC `9d79030efd8fde00b85d8ec6b0ea7618dad2a5bb`. Remote `dev-james0723/PostRiff` `consumer-saas` checked read-only at `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1`; no drift observed.
- G2 ZIP integrity verified, 58/58 manifest entries match SHA-256; G1 source preserved. G2 passed the full original-config Node 24/Next 16.3.8 Production Build.
- Only free read-only inventory, security/source analysis, local evidence creation and a local-only documentation commit authorized. No Production writes or provider interactions.

## Host admission decision — FAIL

Kynlo fresh status (2026-10-17 18:43:24 UTC) observed 12 logical cores, 1-minute load 14.10 (previous same-turn snapshot 23.04), memory pressure WARN, approximately 3.3 GiB estimated available RAM, 26.4 GiB swap, **10 concurrently tracked Heavy Jobs** (earlier 9), approximately 18.2 GiB disk free; swap was growing. All seven conservative admission criteria recorded in `evidence/G3-RESOURCE-SAFETY-GATE.json` are false.

This resource gate is a cautious operator policy, not an official hardware minimum for the test suite. It prevents adverse interference with other active agents; it does **not** grant permission merely because metrics improve. Host resource status is time-sensitive and must be remeasured before any future execution.

## Real Linux inventory — no dedicated safe target

Read-only `colima list`:

| Profile | State | Configured CPU / RAM | G3 decision |
| --- | --- | --- | --- |
| `creative-pr91-20261017` | Running | 2 CPU / 4 GiB | Owned by another project; NEVER borrow, stop or alter |
| `reconstruction-isolated` | Running | 2 CPU / 4 GiB | Owned by another project; NEVER borrow, stop or alter |
| `default` | Stopped | 2 CPU / 4 GiB | Not dedicated; do not start |
| `df-story-engagement` | Stopped | 2 CPU / 3 GiB | Not dedicated; do not start |
| `james-au-xhs` | Stopped | 2 CPU / 2 GiB | Not dedicated; do not start |
| `james-au-xhs-amd64` | Stopped | 4 CPU / 2 GiB | Not dedicated; do not start |

No separate Linux computer was present among Kynlo devices. Availability of Colima/limactl/QEMU binaries alone does not prove isolation. **No new VM or container started. No existing one borrowed, started, stopped, pruned or modified.**

## Executable test-harness risk review

The checked-in suites correctly require genuine Linux and CI; do not remove or fake the guards:

- `tests/phase2/postgres_mastodon_scale.py`: Linux + CI, 1,000 synthetic accounts, 32 concurrent SQL workers; a real Linux nonproduction database is mandatory. **NOT RUN.**
- `web/tests/mastodon-account-browser.cjs`, `web/tests/mastodon-queue-browser.cjs`: Linux + CI and synthetic localhost Next/Python/Postgres paths; they use **Chromium**. **NOT RUN.**
- `scripts/cloud-mastodon-browser.sh`: installs `@actions/artifact` via npm, installs Chromium via Playwright, and runs artifact collection/upload. It doesn't implement a Mastodon **WebKit Linux E2E**. Running this unchanged would violate the offline/no-external-side-effect scope.
- `scripts/cloud-mastodon-validation.sh`: can invoke `sudo apt-get`. Do not run unchanged.
- A tested Linux **WebKit** Mastodon journey (same login, account/instance, Queue, schedule and approval assertions as Chromium) needs a separate revision-pinned offline implementation and independent validation. Two-engine success cannot be inferred from the current Chromium-only scripts.

Static audit receipt: `evidence/G3-LINUX-HARNESS-STATIC-AUDIT.json`. No Linux tests, installs, downloads, mocks of a Linux platform, paid runners, provider OAuth, posts, Deploy or Production operations occurred.

## What is already verified

- G2 full Next.js Production Build **PASS**, 114/114 static pages, TypeScript phase and manifests PASS. No need to repeat this expensive work under load.
- G2 macOS diagnostic browser smoke is not Linux CI acceptance.
- G1 Mastodon unit 136/136, PostgreSQL management 27 tests and synthetic Automation/tenant tests passed; G1 Production applied migration ledger 62/62 source parity, pending Mastodon 131–133.
- Source tree remains limited to this isolated worktree; no changes to another Agent's dirty tree.

## Explicit G3 final gate

**LOCAL SOURCE / BUILD: GO (as previously established). LINUX E2E: NOT RUN. LINUX WEBKIT COVERAGE: NOT PROVIDED BY EXISTING OFFICIAL SCRIPT. 1,000-USER LINUX CAPACITY: NOT RUN. PUBLIC / PRODUCTION: NO-GO.**

Before a future Linux attempt: verify Mac memory pressure normal, RAM and disk headroom, low competing load, swap activity stable, separately owned dedicated free Linux runner, matching Node/Python/PostgreSQL/Playwright binaries already provisioned offline, 127.0.0.1-only fixture networking, no billing/egress/credentials, and an independently reviewed WebKit equivalent. Use a bounded CPU/RAM runtime and clean up only own temporary resources.

Separate human approvals are still required for hosted preview, real OAuth on two independent Mastodon servers, every real external social action, Push, PR, Merge, Production schema, Deploy and invited/public customers. Do not enable Mastodon for public use.
