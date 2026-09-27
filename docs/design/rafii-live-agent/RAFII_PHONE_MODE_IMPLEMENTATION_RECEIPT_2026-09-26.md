# Rafii Phone Mode implementation receipt — 2026-09-26

Locally implemented and verified on `feat/rafii-live-agent`, in `/Users/ouxianxing/Documents/James-Au-Studio-live-agent`. Phone Mode delegates to the existing `AgentRuntimeService.turn`; it does not run a separate Rafii bot. Real telephony, GPT-Live and Manager input were simulated in local acceptance tests. Workspace writes, permissions, publishing approval checks, ledger, SQL/RLS, HTTP/WebSocket handlers and browser UI were exercised against actual code and disposable PostgreSQL.

No paid telephone call or verification SMS was made. No customer email/push, production credentials, production migration, deployment, push or release-branch merge was performed. Phone flags remain off in `.env.example`. Temporary test servers and their disposable database were stopped.

## Implemented behavior

- Shared browser/phone GPT-Live session policy, style, history, delegation contract and verified speakable-result handling. The browser Voice Mode regression suite still passes.
- Provider-neutral outbound/lifecycle and audio-transport contracts, deterministic fake provider, server-side Twilio Calls/Media Streams/Verify adapter, signed callbacks and media handshake, stable provider identifiers, no recording, conservative answering-machine rejection, and an ASGI media host. `api/phone.py` now exports the lazy media service; Vercel routes only `/api/phone/media/*` there before the existing HTTP API, with a 660-second function limit. Import/build does not initialize credentials, PostgreSQL or a provider; the global phone flag is rechecked on every upgrade.
- Explicit **Call Rafii** actions in the existing Rafii panel and notification surfaces. Calls bind the authenticated account, workspace and existing conversation before dispatch. Navigation, opening notifications and reloading never dial.
- Server Phone Session Controller: shared Manager/tools/model routing/memory/approvals, backend delegation, transcript continuity, verified spoken results, playback interruption, English/Cantonese/Mandarin hang-up commands, disconnect handling and duration watchdog. Tool access is fenced when the person hangs up, revokes permission, loses membership or reaches the cap.
- Shared reversible `draft_edit` tool uses the existing author-edit command and revision checks, refuses queued drafts, re-reads the result and invalidates publishing approval. The test edited the second LinkedIn draft, preserved the first, showed the edit in the already-open web Queue without reloading, and kept publishing review required.
- Encrypted personal phone identity, masked display, verification throttles/attempt limits, preferences, call history, provider-event and delegation idempotency, revocation, and account-deletion cascades. Caller ID grants no workspace access. Sensitive provider bodies are discarded and phone numbers are excluded from notification payloads and diagnostics.
- Notification V2 phone attention delivery is opt-in and deterministic. Routine success, billing and security events do not call. Approval escalation needs a verified deadline within 24 hours. Quiet hours, membership, allowlists, provider/Live availability, duplicate suppression and shared automatic-call limits are rechecked before delivery. Failed calls can fall back through existing push/email preferences.
- User-created daily/weekly briefings reuse the existing cron and campaign schedule parser; there is no parallel scheduler or catch-up redial loop.
- Phone settings include verification, explicit calling, proactive/scheduled switches, local time zone and quiet hours, one/two automatic calls per day, eligible categories, fallback, recent calls and number deletion. Credit plans require an explicit call credit limit; automatic calls have a separate saved per-call limit that defaults to zero. Missing limits and insufficient wallet balances never dial.
- Separate phone global/outbound/scheduled/proactive/verification flags, initial 600-second cap, configured daily cost ceiling, approved country prefixes and positive reviewed telephony-rate ceiling. Live and telephony costs reserve against the existing ledger before dispatch. Unknown provider acceptance is reconciled without redial. Uncertain hang-up remains `ending` and blocks another call; confirmed provider state and final duration/Live usage reconcile once. Missing real usage remains held. On credit plans, the existing CreditBook issues exact component quotes and the shared Manager reserves against the remaining authenticated call limit. Settled spend and unknown holds count against that limit; Manager continuation after a proposal uses the same bound authority. Paid drafting, research and media keep their existing task credit approvals. No model can increase the call limit.

The telephony rate is a configured ceiling covering PSTN, Media Streams and answering-machine detection, with duration rounded to whole minutes; this version does not import vendor invoices. First-call carrier behavior, real GPT-Live availability/audio and actual vendor charges still need the separately authorized live test.

## Repository reconciliation and migration

The initial branch was ahead 16/behind 7 of `origin/consumer-saas`. Changes were inspected and reconciled deliberately as the target advanced. The latest integrated target is `81c4a9fe7e738e401551f72d341a8ccf214a3ea3` (including chat attachments/connectors and the Context Pocket fixes). Product commits are `811371e` (Phone Mode and signed media deployment) and `35b6a47` (credit limits and billing integration). Tested implementation HEAD is `d25fe074afd5449a6f3f70e56895cbb768e2cd9b`, ahead 6/behind 0 at verification; the separate receipt commit adds no product code. Merge resolutions preserve both writer defaults/agent style and the incoming chat-media/connectors migrations. Nothing was pushed.

The approved Phone Mode input plans, unrelated Notification System plans, the concurrently edited `NOTIFICATIONS.md` and local coordinator symlink were preserved and excluded from product commits. The exact 56-file product change inventory is in the verification JSON.
Migration numbers were checked across all relevant local/remote Rafii/PostRiff refs and active worktrees before creation. Upstream owns 031 chat media and 032 productivity connectors; separate growth branches also contain a 032 collision that must be reconciled by that workstream. No already-applied migration was renumbered; this implementation adds only `migrations/postriff/033_phone_mode.sql`. It creates seven server-only tables: numbers, preferences, verification limits, calls, provider events, delegations and schedules. All force RLS, deny browser/anonymous access and cascade on account/workspace deletion as appropriate. Notification delivery adds the `phone` channel. The migration was applied only to disposable local databases.

## Verification

Every row below passed. The exact changed-file manifest, source hashes, commands and retained raw logs/screenshots are in `RAFII_PHONE_MODE_VERIFICATION_2026-09-26.json`. Evidence is retained locally under `.token-pilot/evidence/rafii-phone-20260926/`.

| Check | Observed result |
| --- | --- |
| Python unittest discovery | 1,477 passed, including 18 Phone Mode unit tests |
| Phone PostgreSQL acceptance | Ten groups passed: identity, continuity/edit/approval, ambiguous create, membership/schedule, Notification V2, signed media/usage/uncertain hang-up, in-flight tool cancellation, credit approvals/bounded Manager holds/refunds, RLS, account deletion |
| Existing PostgreSQL regressions | Seven existing suites passed: agent runtime/browser voice (55), runtime references, style, consumer campaign worker, deletion, coworker/Notification V2 (35), and the latest quick-start regression |
| Web unit tests | 385 passed |
| Phone browser acceptance | Passed credit approval/wallet gates, explicit single dial, no navigation/reload dial, same-runtime draft edit, visible live web refresh, publishing approval, hang-up, scheduled briefing, revocation, mobile layout and axe accessibility |
| Existing GPT-Live browser regression | 30/30 passed, including mobile/tablet, continuity, reconnection, approvals and accessibility |
| TypeScript | `tsc --noEmit` passed; generated test-dist entries were removed from `tsconfig.json`, then the check passed again |
| oxlint | Zero errors/warnings on 804 source files |
| Copy audit | Zero banned phrases |
| Next.js production build | Passed, 99 pages generated; no deployment |
| Git whitespace check | `git diff --check` passed |

Local acceptance models and phone audio are explicitly synthetic. The signed ASGI test sends audio frames through the real Twilio transport adapter and GPT-Live event controller using an injected fake Live connection and scripted existing Manager. The browser test uses the same controller/runtime/draft command with synthetic input; the saved draft and review state are real local application state.

The Voice success fixture now explicitly grants the synthetic owner’s consent to the injected media processors through the same fixture pattern used by the existing PostgreSQL tests. The phone lifecycle fixture keeps its local day away from midnight when aging calls, so the daily-limit test is deterministic. Neither change relaxes product privacy or policy.

Non-blocking test warnings are retained in the logs: an existing CLI-runtime unclosed-file warning and Starlette's notice that its currently supported WSGI compatibility middleware is deprecated. Neither check was treated as failed or hidden.

## Before the first real phone call

There are no unresolved local validation failures. Read-only release checks found the isolated Vercel project `rafii-consumer-staging` (Pro, Fluid Compute, `iad1`) has no deployments and no configured remote environment variables. The local worktree is now linked to that exact existing project; linking did not deploy. Its approved staging Supabase database is reachable through the TLS session pooler and all 18 existing migration-ledger checksums match this release. Ten migrations remain unapplied: 020–025 and 030–033. Phone tables are absent there. This task added only 033; the other nine are incoming prerequisites.

An in-memory Preview configuration derived from the existing approved staging configuration passed the hosted environment preflight and runtime composition without connecting a provider or uploading credentials. It pins staging identity/storage/database/secrets, uses `https://rafii-consumer-staging.vercel.app`, and keeps all phone, notification, push, research and listening egress off. Default process-environment preflight accurately remains `pending` until those values are installed remotely. Preview intentionally cannot place a real call.

The remaining release/live gates are concrete external actions:

1. Separately authorize feature-branch push and a deployment to the isolated `rafii-consumer-staging` project, its staging-only environment configuration, and application of the exact ten pending migrations. Apply database prerequisites before serving the new release. Keep the current production project untouched. The migration CLI only allows loopback applies; a separately reviewed staging runner must retain the staging identity/checksum guards.
2. Supply server-held test Twilio account/auth/caller number and GPT-Live credentials/model route. Those keys are absent from the reviewed staging source. Preserve the stable existing encryption vault, and review country prefixes, PSTN/Media Streams/AMD rate ceiling, normal workspace budget and credits. Do not upload production credentials.
3. After separate paid-test authorization, use an explicitly approved test deployment that permits phone egress. Enable only phone global/outbound; keep scheduled/proactive off. If real SMS verification is needed, separately authorize it and configure Twilio Verify plus its verification flag.
4. Sign in as the test account, verify its own number, enable **Call Rafii**, select the intended conversation and approve a sufficient credit limit. The caller’s identity is bound server-side before dispatch.

After staging-release authorization and environment/migration setup, the linked Preview deployment command is:

```sh
cd /Users/ouxianxing/Documents/James-Au-Studio-live-agent
npx --yes vercel@60.1.3 deploy --scope jamesau0723-6572s-projects
```

This deploys Preview with phone egress off; it is not a live-call command. The global Vercel CLI is older; upgrade with `npm i -g vercel@latest` for compatibility, or continue using the explicitly versioned command.

For an approved standalone live-test host instead of Vercel, the exact command remains:

```sh
PYTHONPATH=src /tmp/rafii-phone-env/bin/python -m uvicorn postriff_phase2.phone.asgi:create_app --factory --host 127.0.0.1 --port 4752 --no-access-log
```

That command requires the approved server environment and public HTTPS/WSS forwarding; it neither loads an env file nor dials. The Vercel media route is already implemented, so a separate standalone host is optional.

The exact paid-call action, only after prerequisites and explicit authorization, is to press **Call Rafii** once inside the intended authenticated conversation. Answer normally, request the second LinkedIn draft edit, verify the web draft, say “Publish it” to verify the approval boundary, and end the call. Reconcile signed duration and final Live usage before another paid attempt if the result is uncertain. Real PSTN/audio/AMD behavior and vendor charges remain unverified.

The transport was checked against current official [OpenAI GPT-Live WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets), [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation), [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams/websocket-messages), [Calls API](https://www.twilio.com/docs/voice/api/call-resource) and [request-signature security](https://www.twilio.com/docs/usage/security) documentation before Twilio coding. No direct SIP accept endpoint was mistaken for an outbound PSTN origination API.

Token Pilot enrolled only its authorized reversible local coordinator files. The backup and managed-file inventory remain in `.token-pilot/`; `.claude/skills/token-pilot` is the local enrollment symlink, separate from the product implementation. Usage measurement is unknown; no billing or token savings are inferred.
