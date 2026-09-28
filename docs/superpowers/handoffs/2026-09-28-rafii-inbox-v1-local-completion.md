# Rafii Inbox v1 local completion receipt

Date: 2026-09-28. Scope: local source implementation and disposable/synthetic verification only.

## Git and task commits

- Isolated worktree: `/Users/ouxianxing/.codex/worktrees/rafii-inbox-completion/James-Au-Studio`
- Branch: `codex/rafii-inbox-v1-20260928`
- Exact base, fetched `origin/consumer-saas`: `ee688397dd39d9cf3df6c99f22c488fa355b54ee`. Re-fetched after implementation; still current then. `origin/HEAD` points to `origin/consumer-saas`.
- Source HEAD before this receipt: `de9c03a3ba034e19949e085f695e4ccc4873b1e3`.
- Task 0: `bfeb1d6` copied and hash-checked the three saved planning artifacts as the first commit. All three still hash-match the untouched shared checkout.
- Task 1: existing AI reply commits `cd3c177` and `848ab49` are ancestors of this branch. Existing Engagement Copilot classifier and draft tools were reused.
- Task 2: `b68fba6` preserves cumulative verified OAuth capability rows across reconnects.
- Tasks 3, 4, 7, 8: `693f845` adds durable bounded Threads sync, pagination/batched reads, provider boundary, fenced reply worker, migration and tests.
- Tasks 5, 6: `a0108db` adds triage/freshness/receipt/attention UI, notification deep link, local browser fixture and evidence.
- Task 9: `de9c03a` records default-off switches, rollout state and the activation runbook.
- Task 10: this receipt records verification and remaining external gates.

The complete changed-file manifest is reproducible with `git diff --name-only ee688397dd39d9cf3df6c99f22c488fa355b54ee..HEAD`. The implementation changes are in `src/postriff_phase2/{oauth,audience,audience_sync,audience_worker,inbox_providers,hosted_app,hosted_worker}.py`, the existing coworker and notification modules, `web/src/features/inbox/`, the Inbox API types/client, the tour nudge, `migrations/postriff/047_inbox_operational_sync.sql`, the focused Python/PostgreSQL/browser tests, local test harnesses, `.env.example`, and the linked planning, rollout and evidence documents.

## Migration and verification

- Migration prefix `047` is unique across 278 current Git refs; their other highest prefix is `046`.
- `047_inbox_operational_sync.sql` SHA-256: `bcb9be5bf6069c1a80e94362cd473e436b0b56fa277baad51c7c7ba0fa369553`.
- Focused contracts: `PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_postriff_audience_contract tests.test_reply_writer tests.test_rafii_workflows.EngagementTest tests.test_inbox_oauth_capabilities tests.test_inbox_sync_contract tests.test_inbox_reply_worker_contract tests.test_inbox_provider_adapter` — 26 passed.
- Full Python: `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 2,867 tests OK, 244 skips.
- Focused disposable PostgreSQL: `PYTHONPATH=src .venv/bin/python scripts/rafii_pg_private.py postgres_audience postgres_channels postgres_coworker postgres_inbox_migration postgres_inbox_pagination postgres_inbox_sync postgres_inbox_worker` — seven groups passed. Migration fresh/upgrade/replay/forced RLS, OAuth regression, sync overlap, pagination and worker cases passed.
- Full disposable PostgreSQL: all 87 script groups have a passing run. The first all-groups command reached `postgres_trend_whitespace` after 84 successful groups and hit external disk exhaustion (`ENOSPC`). `postgres_trend_whitespace` then passed 35/35 in a fresh disposable run; `postgres_unified_notifications` and `postgres_video` also passed separately. This is segmented full coverage, not one uninterrupted clean run.
- Web: `node --test tests/*.test.cjs tests/*.test.mjs` — 447/447; `npm run typecheck` — passed; `npm run lint` — 0 errors/warnings; `POSTRIFF_BUILD_NO_CACHE=1 npm run build -- --webpack` — passed production build. The local fixture build with `POSTRIFF_API_ORIGIN=http://127.0.0.1:4460`, `POSTRIFF_DEV_SSR=1`, and synthetic Sentry-disabled environment also passed.
- Browser: `PYTHONPATH=src .venv/bin/python scripts/inbox_browser_local.py` — 14/14 scenarios, zero console/page errors or failed API requests. Chromium emulation at 1440x900, 768x1024, 430x932, 390x844; WebKit emulation at 390x844. Reduced motion enabled. No physical device was used. The browser used disposable PostgreSQL plus synthetic identity, provider and writer; no live provider/model call.
- Changed-file secret scan: 43 text files, one pre-existing `.env.example` Basic Auth example finding at line 6, no new credential finding.

Browser evidence: `inbox-v1-browser-evidence.json` and three screenshots in `inbox-v1-browser/` beside this receipt. The 430px screenshot confirms the Back control is visible after the Inbox tour nudge closes.

## Specific safety evidence

- OAuth: reconnecting for `comments_read` and `reply` preserved Direct `publish` and `analytics` in the PostgreSQL and browser journeys.
- Sync: one lease per connection, manual/scheduled overlap fence, bounded pages/items/posts, repeated-page upsert, durable server `lastSyncAt`, 429/transport cooldown, and connection removal during provider I/O were tested. Incomplete or failed listings never infer deletion; no automatic tombstone is written without verified provider deletion semantics.
- Replies: two workers competed for one approval and only one claimed it; `submitting` is committed before provider I/O. Crash before or after provider call, inconclusive publish, stale claim, revoked reply capability, changed credential, tombstoned source, workspace deletion and digest mismatch do not trigger a duplicate send. Old approvals made while the sender was off require exact reconfirmation. Synthetic Threads container/publish returned a reference; exact id, parent, text and owner were read back before `verified`.
- The browser covered loaded comments, manual refresh, provider error, triage filters, AI suggestion/edit/exact preview, approval with sender off, explicit reconfirmation, synthetic send, receipt progression, uncertain no-resend, unsupported-provider click-through, mobile sheet/back, and viewer permissions.

## Support, state and release gates

Threads is the only Inbox Direct provider implemented here. Meta's official [Threads API collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api) documents `reply_to_id`, container publishing, reply fields including `replied_to` and `is_reply_owned_by_me`, and the reply read/manage scopes. The collection warns that it may lag the developer changelog; the changelog fetch returned HTTP 429 in this run. `validation_unavailable`: Rafii's actual Threads app-review state and account scopes could not be verified without a separately staged real-provider account. Instagram/DM/mentions remain outside v1. Explicit proven deletion semantics remain unavailable, so absence or transient errors do not tombstone comments. A provider read-only preview/staging smoke remains an external gate.

| State | Result |
| --- | --- |
| Inbox v1 source implementation | Locally implementation-complete under synthetic Threads transport |
| Local/disposable database | Migration and full test coverage passed across segmented runs |
| Synthetic provider transport | Send and authoritative read-back verified; uncertain no-resend verified |
| Preview/staging real provider read | Not run; requires reviewed app, account and scopes |
| Live social reply mutation | Not run |
| Production migration | Not applied by this work; live database state not inspected |
| Production send flag | Not changed by this work; live value not inspected (source defaults off) |
| Production deployment | Not run by this work |

Activation runbook: `docs/superpowers/handoffs/2026-09-28-rafii-inbox-v1-activation-runbook.md`. Merge, push, release configuration, production migration and live replies require separate authorization and evidence. This branch was not pushed or merged.
