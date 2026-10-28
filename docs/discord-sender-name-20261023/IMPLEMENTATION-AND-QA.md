# Discord customer sender names — implementation and QA

Date: 2026-10-23. Branch: `codex/discord-sender-name-20261023`.
Base: `claude/discord-launch-rc-20261023` at `2a5a523d788eef67a5c7dbed609a98efa6650eef`.

Status: implementation and local synthetic acceptance complete; production release and live Discord acceptance pending. This change has not been deployed, merged, or used to send a real Discord message. No production flags, secrets, database schema, domains or Vercel controls were changed.

## Corrections after the independent review (RC2 integration branch)

Added 2026-10-23 on `claude/discord-rc2-sendername-20261023`. The text below this section is the upstream branch's own account and is kept as
written; where it conflicts with this section, this section is right. Full per-finding detail: `docs/sender-name/EVIDENCE.md`.

1. **Who may edit.** A webhook name is a Rafii setting: any member who may manage connections edits it (the member who authorized the
   webhook must still hold that permission). Only the member whose Discord account installed the bot may change the bot nickname. "Only the
   authorizing member ... can edit" below is true for the bot only.
2. **The sensitive-action gate is not what protects the POST.** `security_gate.require` returns immediately unless
   `RAFII_ACCOUNT_PROTECTION_V2_MODE=enforce`, which nothing in the repository sets. The controls that actually apply are the fresh sign-in
   (`assert_fresh`, the step-up window), the application guard header, the role check and the exact-state fingerprint.
3. **The independent code review named under "Verification receipt" left no artifact in the repository**, and the regressions it refers to
   were shadowed: the reviewer's deletion-mutation run found 58 of 101 mutants of the sender-name code surviving the upstream sender-name
   tests. Do not cite that row as evidence. The mutation result for this branch is in `EVIDENCE.md`.
4. **"That display name cannot be frozen per post"** stays true of what Discord renders, but Rafii no longer ignores it: with the nickname
   capability on, a review records the nickname Discord last reported and a queued bot post is HELD at dispatch, nothing sent, if Discord
   reports another one.
5. **Several workspaces can hold one server.** The bot nickname is one value per server. Rafii writes it from a workspace only while that
   workspace is the server's only live Rafii installation; with two, neither can (`nickname_authority_other_workspace`). The capability is
   OFF by default (`POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED`), and the whole feature is OFF by default in every environment
   (`POSTRIFF_DISCORD_SENDER_NAMES_ENABLED` unset; only the exact string `true` turns it on, whatever the environment label says).
6. **PostgreSQL.** "Local PostgreSQL binaries were unavailable" described the upstream machine. On this branch the PostgreSQL suites
   (`tests/test_discord_sender_name_postgres.py`) run against a disposable PostgreSQL 16 cluster, including the real request coordinator,
   the W-02 lane and the minute-tick worker. The owned cloud qualification (CI uses PostgreSQL 17) has still not been run for this change.
7. **Rollback.** Besides queued manifests that carry a frozen custom name being held by the older worker, a NEW approval made under the older
   worker silently drops the name, because the older worker ignores the setting. Customers' future posts would be sent under the
   webhook's own name without any message. Say so in the rollback instructions.
8. **Counts.** The test counts under "Verification receipt" are the upstream branch's. This branch's are in `EVIDENCE.md`.
9. **Webhook route.** The webhook route (`POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED`/`_QUALIFIED`) stays off at opening, so the webhook name ships
   dark and nothing in this feature that a customer can reach in Wave 1 is a webhook.

## Customer behavior

Connections now offers **Edit sender name** for an authorized Discord installation or incoming webhook. English, Traditional Chinese and Simplified Chinese include a sender preview, scope description, pending state, success receipt, reload recovery, and session-verification recovery. Only the authorizing member with workspace connection-management permission can edit.

| Mode | What changes | Approval behavior |
| --- | --- | --- |
| Webhook | Server-owned setting on this one connection; future approved sends include Discord's `username` field | Name is shown in review and frozen into the wire digest. Already approved jobs and automation decisions retain their original custom name, including legacy decisions with no override. |
| Bot | The shared bot member's nickname in the exact authorized server | Explicit shared-server confirmation required. Everyone using that bot in the same server sees the nickname, including future replies. Other servers and the global bot username are unaffected. |

Bot editing requires the current authorizer's Manage Nicknames permission (or owner/Administrator) and the bot's Change Nickname permission (or Administrator). Bot messages continue to use the server's current nickname; that display name cannot be frozen per post. Discord/native administrators or authorized connections in another workspace can also change the same shared nickname. Discord offers no conditional nickname update that excludes those writers.

Webhook names are validated at 1–80 Unicode code points; bot nicknames at 1–32. Surrounding spaces, non-normalized Unicode, control/format characters and reserved webhook substrings are rejected. Avatars remain outside this change. Personal user accounts never become automated message senders.

Webhook save verifies custody and stores a setting; it does not mutate the webhook resource or send a test message. The first real publication still needs approval and provider acceptance. Its reconciliation checks the returned message's author username against the frozen name.

## Boundaries and recovery

- GET/POST `/api/workspaces/{workspace}/channels/{connection}/discord-sender-name` use existing authenticated workspace transactions, connection-management permission and credential validation. POST requires a fresh session and the existing sensitive-connections security gate.
- A settings fingerprint binds workspace, member, connection, authorization generation, credential custody, targets, sender revision and observed name. Stale editors cannot overwrite a newer save.
- Bot writes use only `PATCH /guilds/{guild}/members/@me` with `{ "nick": "…" }`. The global bot profile endpoint is not used. Live server/member permission checks precede the write; local custody is checked immediately before transport after rate admission.
- An exclusive edit claim is committed before the bot PATCH. Competing edits in the same connection stop before provider mutation. Provider IO runs outside workspace transactions.
- The exact rate admission is stored in that claim while still reserved. An ambiguous write holds further edits. An explicit reload after the two-minute deadline must freshly read the member, match the original claim, and atomically reconcile its exact unbound nickname admission before clearing the claim. A replacement claim cannot be cleared by a late reader.
- Known-unsent final-guard denials retire only their exact nickname admission. Later readback of an ambiguous idempotent nickname operation records an observation with a NULL original HTTP status. Neither path refunds quota, fabricates the original PATCH result, retries a provider write, or relaxes publication admission.
- Audit entries record the operation scope and server ID, without credentials or webhook secrets.

## Verification receipt

All provider transports and credentials in the tests are synthetic. The shared-rate tests exercise the production coordinator algorithm over the existing storage double; they are not PostgreSQL concurrency qualification or a capacity test.

| Check | Result |
| --- | --- |
| Discord Python discovery | 496 tests run, 0 failures, 11 conditional skips |
| Campaign, automation chat and credit-rebind regression modules | 40 passed |
| Discord frontend contract modules | 23 passed |
| TypeScript | Passed |
| Lint | 0 errors; 37 existing warnings in unrelated files |
| New source/test secret scan | No findings in the four new code/test files |
| Running app browser | Passed: English 1280px and 390px, Traditional Chinese 390px, Simplified Chinese 1280px |
| Independent code review | Critical/Important findings repaired and covered by regressions; final minor bot-kind and terminal-cleanup checks also repaired |

Browser cases cover keyboard opening, connection-specific webhook editing, preview, explicit shared-bot confirmation, duplicate-click prevention, pending close protection, stale-save refusal, reload without retry, overlong nicknames, localized session-verification recovery and horizontal overflow. The local harness used Chromium 153.0.8010.0, an isolated webpack development server and synthetic API routes. Off-origin browser requests were blocked. A local Noto CJK fallback was supplied for Chinese visual inspection; this does not change production font assets.

Evidence: [browser receipt](evidence/browser-receipt.json), [English webhook editor](evidence/en-webhook.png), [Traditional Chinese mobile bot editor](evidence/zh-Hant-bot.png).

Reproduce the scoped checks from the repository root:

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_discord*.py'
PYTHONPATH=src:tests python -m unittest test_postriff_campaigns test_postriff_automation_chat test_automation_credit_rebind
cd web
npm run typecheck
npm run lint
node --test tests/discord-*.test.cjs
```

The new browser harness is wired into `scripts/discord-multimode-validation-cloud.sh`. That existing cloud route also runs the owned PostgreSQL qualification. Its cloud run has not been executed for this change. Local PostgreSQL binaries were unavailable. No production build or hosted acceptance was performed.

## Release handoff

Before public release, integrate this branch with the selected launch candidate and record its exact resulting source SHA. Run the existing owned PostgreSQL/cloud qualification and the authorized hosted acceptance, including two mutually unauthorized workspaces/members, both sender modes, permission removal, simultaneous edits, timeout/reload recovery, and one separately approved publication whose observed sender name matches the preview. Follow repository `AGENTS.md` for the single production-target staged build and exact human release authorization.

This name change does not establish W-02 capacity, change rollout gates, or authorize broad customer launch. Existing launch and capacity requirements still apply.

Rollback must account for queued manifests containing a frozen custom name: the older worker cannot verify their new wire digest and will hold them. Preserve compatible dispatch/reconciliation code until those jobs are settled, or review and cancel/reapprove them through the normal authorized flow.

Primary API references: [Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook) and [Modify Current Member](https://docs.discord.com/developers/resources/guild#modify-current-member).
