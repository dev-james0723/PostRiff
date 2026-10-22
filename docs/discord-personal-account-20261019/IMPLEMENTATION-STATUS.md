# Discord multi-mode source candidate — 2026-10-19

**SOURCE_IMPLEMENTED_UNQUALIFIED · NO-GO. The full goal remains active.**

Owned branch `codex/discord-personal-account-20261019`, base HEAD `0c3e1bf615bce1213d786ce1e8c87e7875701e44`. Initial worktree was clean. This session's changes remain **uncommitted** in the owned source directory. No push/PR/merge/deployment/live provider effect occurred. Earlier baseline push and another agent's PR211 acceptance lane remain separate.

## Implemented source

- Incoming-webhook purpose uses version2 encrypted single-use state, PKCE and exact Discord issuer, independent identify/app/subject proof and webhook-resource proof. Old identity/bot v1 callbacks retain compatibility. Secrets stay in the existing vault, never resource cards or manifests. OAuth creation does not approve a channel/message.
- Explicit channel consent reuses choose_destination. Distinct sender/credential/destination bindings enter frozen review and exact approval. The same queue/Worker/rate coordinator performs reserve/seal/consume/create/readback. No alternate sender or queue was added. Webhook requests use fixed paths, no Bot/Bearer substitution, `wait=true`, text only, suppressed mentions/automatic embeds. No threads, attachments, identity overrides or implicit extra effects.
- Known IDs only are read back. Ambiguous creates are never reposted; rotating the webhook cannot bypass an unresolved equivalent same-channel delivery. Generation, active authorizer permission, cancellation and lease checks remain enforced. Legacy bot delivery digests remain compatible.
- Bounded raw HTTPS Ed25519 interaction endpoint, separate signed PING verification and useful-command activation, app/user/owner/private-context checks, persistent replay/mapping schema, ephemeral response and no interaction-token storage. The proposed first command opens an authenticated private draft/review entry; it never returns draft content, publishes or schedules. Ambiguous/unlinked users receive the Channels recovery flow.
- Explicit actor-owned private mapping bind/remove and private entry validation before workspace selection. Dry-run-only command/config tooling validates supplied public application/command snapshots; it cannot register commands. Matching supplied command needs no registration. Command creation requires an absent-name/type registry check.
- Mode choices/unavailable/reconnect states, stored private-link status, scope upgrade, callback fencing and sender labels across composer/review/channel/automation surfaces. Discord copy covers existing English, Traditional and Simplified UI packs. No generic Discord Assisted fallback.
- Additive candidate migration131 plus real PostgreSQL/RLS/replay fixture and running-app390/1280 browser/keyboard/axe harness. These two harnesses are **prepared but NOT_RUN**.

## Actual verification

The final before/after source manifests match **2191 input-file SHA256 hashes**. This is source provenance, not2191 passing tests. The machine-readable matrix binds the exact fingerprint and raw logs.

| Local synthetic Python check | Result |
|---|---|
| New multi-mode custody/review/Worker/rate/uncertainty/adapter tests |20 passed|
| Signed interaction, private entry, config/CLI/qualification tests |12 passed|
| Existing OAuth lifecycle |24 passed|
| Existing approved-publication regression |31 passed|
| Existing personal-account projection/contract |6 passed|
| **Final focused batch** |**93 passed, no skips**|

Separate narrow checks also passed: pool7, Mastodon adapter2 and existing bounded rate-template1. They are not a full-repository regression result. Final lightweight Python AST, three-pack key parity, shell syntax, whitespace and `git diff --check` passed. Non-Discord connector class source matches the base exactly. Dependency/lockfiles, root rules and `vercel.json` are unchanged; Git deployment remains disabled.

Core backend tests retain observed RED→GREEN logs. UI test execution was denied before running, so UI RED/GREEN, compilation and browser success are not claimed. Implementation-side diff review repaired the caught misplaced adapter branch, CLI import shadowing, old-bot deduplication, webhook hourly-age handling, rate admission and qualification-PING issues. This is not independent release sign-off.

## Required checks not completed

Full Discord discovery, full web units, TypeScript/lint, running browser and persistent PG/RLS/Linux gates remain `validation_unavailable`. Local full-suite/Node execution was denied by the cloud hard guard. The exact routed `jcb test` attempt exited2 on an inaccessible receipt-lock path; doctor independently exited2 because Depot authentication is unavailable. No remote run was submitted. See raw reasons in `evidence/validation-blockers.json`.

The prepared Linux wrapper needs the established Python/dependency and PG17 runner prerequisites. It is not currently an automatically mapped/submitted JCB task. The coordinator must review/pin this candidate and run the canonical Linux batch before treating it as engineering-qualified. Historical whole-Python macOS renderer failures remain unresolved; no sandbox/network/resource guard was changed.

Actual customer OAuth/callback, approved live send/readback, true live scheduling/cancel, portal/command/install/interaction latency, production artifact/tenant isolation/rollback and release-owner authorization remain external gates. New modes remain defaultOFF. No authorization click was repeated, no old frozen `2026-10-19T03:00Z` review was retimed, and no other acceptance worktree was modified.

Current acceptance: [ACCEPTANCE-MATRIX.md](ACCEPTANCE-MATRIX.md), [machine-readable matrix](ACCEPTANCE-MATRIX.json), [execution ledger](EXECUTION-LEDGER.md), [official protocol sources](OFFICIAL-SOURCES.md).
