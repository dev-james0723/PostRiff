# Rafii × Twitch — G1 integration candidate

Date: 2026-10-18 UTC. Canonical repository: `dev-james0723/PostRiff`.

This is a real isolated engineering continuation of the verified G0 foundation. It contains the OAuth adapter, existing encrypted-custody integration, 112 Helix operation contracts and executor, 35 supported EventSub types, durable approval/dispatch and event storage, authenticated HTTP routes, actual Rafii UI and scoped Agent tools. **It is not deployed, is not publicly connectable, and is not live-accepted.**

The full public-integration goal remains open. Ordinary broadcaster capabilities covered here must still pass live acceptance. Extension-backend JWT administration, Drops/game-organization entitlements and Guest Star beta need separate specialized adapters and are not declared implemented by this release.

## Provenance and preserved work

| Item | Evidence |
| --- | --- |
| Candidate branch | `codex/rafii-twitch-full-20261018` |
| Canonical `consumer-saas` base | `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1` |
| G0 archive SHA-256 | `155b82dc751e834a3dabf9f51a314cb1636ad43f3e5a243e8727f6a16be07ce7` |
| G0 internal integrity | All 12 checksum entries and all 12 receipt entries match; 48 baseline tests pass |
| Existing Mac main checkout | `/Users/ouxianxing/Documents/James-Au-Studio`, HEAD `80bc24d20397a90257cb5571f8a3914a652bfb51`; its dirty files are preserved |
| Isolated engineering worktree | `/workspace/scratch/84c4d423cd8c/rafii-twitch-worktree` |
| Mac continuation destination | `/Users/ouxianxing/Documents/Rafii-Twitch-FullAccess-20261018/Engineering-G1` |
| Production Supabase | `buoyhkbodnhzngaotoel` only |
| Known staging project | `oxacvkhpfgytkepxcaqh`; never treated as production |

The final commit, bundle and patch hashes are recorded in the distribution `RECEIPT.json`. That post-commit receipt avoids a self-referencing commit hash. The original G0 archive and Mac handoff remain unchanged.

## What is integrated

OAuth uses the existing transaction/state, membership and Vault paths. The Twitch adapter uses a confidential authorization-code flow with the fixed Rafii callback and minimum progressive scopes. Client ID, Twitch subject and authorization generation are sealed into the encrypted credential. Startup/hourly sweeps and every worker use validate custody; refresh rotates the pair atomically. Reconnect, scope loss and revocation invalidate old authority. Current Channels projections recognize valid refresh custody and distinguish app-binding failures from access expiry.

Native mutations require an exact preview and current human approval. The encrypted manifest binds workspace, connection, actor, authorization generation, payload, execution time and any rights/marker declaration. A worker rechecks current membership, permissions, generation, live/eligibility facts, resources and purpose flags. It commits a dispatch fence before the external write. An ambiguous result becomes `outcome_unknown`; an accepted asynchronous clip stays `accepted`; partial deletion stays `partial`. None is silently retried. Known clip IDs can be checked with a separate explicit read.

Candidate migration `134_twitch_native.sql` introduces five native tables with forced RLS and no browser/PostgREST table access. Composite constraints bind actions, subscriptions and events to workspace, connection and generation. The service authenticates through the existing workspace repository and writes through the existing audit log. Migration numbering must be rechecked against other missions before PR; 131–133 were intentionally left free for existing work.

EventSub records a tenant-bound subscription and encrypted secret before the provider POST. A signed challenge can arrive before the create response without deadlocking. Raw-byte HMAC, replay bounds, duplicate headers/JSON rejection, documented revocation statuses, durable deduplication and generation checks protect receipt handling. Viewer payloads use encrypted bounded retention; disconnect, scope reduction and purpose withdrawal purge them. Events are delivered to the authenticated native inbox; this candidate does not claim delivery through unrelated email/mobile channels.

The actual `/app/twitch` route uses the existing workspace/session, Channels, UI components and API client. It displays real required scopes, eligibility and permission reasons, typed fields, exact review, human approval and durable receipts. It does not auto-read provider data or auto-retry mutations. Stream keys and official clip URLs use a separate recent-sign-in path and transient UI memory. All Twitch content is excluded from the generic Site Agent page collector.

Three scoped Agent tools expose local connection context, approved-purpose numeric snapshots, and draft preparation. Current explicit human intent, workspace permissions and separate AI-purpose clearance apply. Agents cannot approve, dispatch, grant OAuth consent or retrieve encoder secrets. The existing frozen permission baseline is preserved.

## Evidence to read

| File | Purpose |
| --- | --- |
| `acceptance-results.json`, `acceptance.log` | Final distinct Twitch Python test IDs, outcomes and source hashes; includes real disposable PostgreSQL acceptance |
| `oauth-regression-results.json` | Distinct existing integration regressions, including the actual pinned SDK gate |
| `ui-acceptance.md` | 21 behavioral/API tests, 6 React rendering tests, 112 schema checks, full TypeScript and targeted lint |
| `g0-integrity.json` | Original archive, internal checksums and baseline verification |
| `production-callback-observation.json` | Read-only public site observation: health 200; Twitch callback 404 |
| `FEATURE-STATUS.md`, `feature-status.json` | Every implemented native operation and registered EventSub type with offline/live/release status |
| `native-api-sources.md` | Exact official endpoints, scope alternatives, restrictions and source URLs |
| `APPROVAL-PACKET.md` | Concrete external operations awaiting James's approval |
| `DEVELOPER-APP-AND-COMMERCIAL-DRAFT.md` | App registration worksheet and unsent formal request |
| `AGENT-HANDOFF.md` | Ownership, recovery, acceptance and next executable steps |

The PostgreSQL evidence uses actual transactions, row locks, RLS roles, constraints and concurrent workers in a disposable database. It loads a minimal Rafii schema fixture plus migration 134. It does not establish that the complete production migration history, production load, installed production RLS or deployed browser behavior has passed.

## Current release truth

At the time recorded in `production-callback-observation.json`, `https://rafii.io/api/oauth/twitch/callback` returned HTTP 404 with `Unknown OAuth provider.` The candidate mounts the callback in tested code, but production does not yet have that route. The public health response also gives no deployed source revision and reports `customerValidated:false`; it cannot prove this candidate is running.

No new Twitch app, live OAuth grant, real refresh/revoke, live native mutation, live EventSub subscription or webhook has been completed. No GitHub push, PR, merge, deployment, production migration, paid service or commercial application sending occurred in this engineering phase.

`RAFII_TWITCH_PUBLIC_CONNECT`, `RAFII_TWITCH_COMMERCIAL_APPROVED`, `RAFII_TWITCH_CONTENT_STORAGE_APPROVED` and `RAFII_TWITCH_AI_PROCESSING_APPROVED` default to false. These declarations do not constitute evidence of Twitch authorization. Live account eligibility and API approval remain Twitch's decision.

## Material operational limits

The existing authenticated cron receives a bounded maintenance step; the new `python -m postriff_phase2.twitch_worker` entry point can drain a dedicated durable worker. No new worker was deployed. Production throughput, crash recovery under platform deadlines, hourly validation capacity, metrics/alerts and a deployed browser acceptance run remain release gates. A serverless cron with a limit of one must not be advertised as proven capacity for all customers.

Scheduling creates Twitch calendar entries and separately approved Rafii execution times. It does not start an encoder. Encoder ingest and stream keys remain separate security concerns. Download support retrieves only officially allowed short-lived clip URLs after rights approval; no media is downloaded automatically. Full-VOD download/upload and Creator Dashboard watch-time, retention or revenue are not fabricated.
