# Private Trial candidate — four capabilities, creator-only evidence

2026-10-17. Qualified engineering candidate only. NOT DEPLOYED / NOT ENABLED. Scoped cloud qualification730d0440/v0czdxw6gg PASS; real provider acceptance NOT RUN. Canonical Rafii remains postriff-phase2-private/buoyhkbodnhzngaotoel. This mode does not assert Standard Access or public customer readiness.

## Exact authority

Server-only POSTRIFF_PINTEREST_PRIVATE_TRIAL=1 is distinct from the old read-only flag. Both cannot be enabled together. App1615884 only; explicit production API selection with POSTRIFF_PINTEREST_SANDBOX=false and POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT=production. No Sandbox-host or infrastructure substitution. OAuth exchange remains official server Basic Auth at the selected environment, with the registered https://rafii.io/api/oauth/pinterest/callback.

A policy binds one actor UUID, workspace UUID, stable Pinterest account ID and username,1–4 exact board IDs, explicit capabilities, fresh pilot UUID and expiry at most24h ahead. Planned existing actorb167161d-37f4-4bc3-ae22-2482c982e5a0/workspace568699ad-d66e-42b8-a7f1-e86d0c35ab02/@jamesaucreates/1126814906675966091. Board ID remains unknown; strict code refuses a placeholder. Proposed expiry18Oct2026 14:00EDT/18:00UTC, not activated. Do not re-use or extend the expired read-only pilot or erased grant. A policy change requires fresh OAuth because pending transactions, ciphertext custody and token envelopes bind its exact authority.

New variables under POSTRIFF_PINTEREST_TRIAL_: ACCOUNT_ID, BOARD_IDS, CAPABILITIES, ID; reuse exact WORKSPACE_ID, ACTOR_ID, USERNAME, EXPIRES_AT. Planned capabilities identity,boards_read,publish,schedule,analytics; publish+schedule must be paired because immediate and future Pins use the existing durable queue. Scope ceiling user_accounts:read,boards:read,pins:read,pins:write; no boards:write,ads or secret scopes. Each capability still requires the actual granted scopes. No public production-review flag is faked: productionReviewed/publicConnectionReady/productionEnabled remain false. Existing emergency disable overrides this lane.

## Publication and recovery

Every Pin needs an immutable current manifest, exact human approval digest, operator membership, bound account/board/section, frozen text/title/link/alt/immutable image, active lease and current credential. The image delivery URL must match the canonical existing private Supabase object path for the approved workspace asset. No arbitrary external image URL or alternate section can be injected at final dispatch.

Two non-refundable create attempts per exact policy; one per intent. Durable quota and prepared response journal commit independently before provider I/O. Same-intent races cannot spend the second slot; failed storage prevents the POST. A known returned Pin ID is independently journaled before the workspace proof transaction commits. Read-only reconciliation can recover that ID if the workspace proof commit is lost, then GET and match the original Pin. The journal never invents a successful read-back. If the provider response itself is lost and no ID is known, remain uncertain and require owner-side inspection; no blind POST retry. Disconnect erases grant ciphertext, cancels pending actions and stops reads even if receipt metadata remains.

All private-Trial create/read-back results preserve creator_only_trial, independent of API host; a Pinterest URL or public board does not prove public Pin visibility. Existing approved source receipts remain valid for unchanged baseline behavior only.

## Analytics

Separate POSTRIFF_PINTEREST_ANALYTICS_ENABLED=1 and current policy analytics capability are required. Collection still needs the existing global metric worker flag and workspace admission, the exact native read grant, current identity and only a Pin recorded by this policy's approved job/journal. Preserve other providers/allowlist entries; never replace a shared configuration blindly. Success with actual values (including zero), confirmed no_data and read_failed remain separate. No-data/failure never fabricates zero observations. First scheduled metric read is1h after verified publication; later reads stop when the bounded policy expires. Actual Trial data may have no engagement; do not promise public impressions.

## Required additive SQL, not applied

Existing quota table is already applied. New private response journal migration20261017_pinterest_trial_journal.sql and its rollback are candidates, server-only forced RLS and immutable hashed authority/intent/Pin-ID metadata; no credentials/content or workspace FK (avoids independent transaction deadlock). Missing journal schema blocks create before provider I/O. Existing candidate20261017_pinterest_metric_reads.sql expands the metric provider check and adds four definitions. Both require exact reviewed checksums, disposable PostgreSQL qualification and separate canonical-production SQL approval. Preserve prepared/known journal rows during code rollback; do not refund attempts. No production SQL executed in this phase.

## Review and activation sequence

1. COMPLETE:730d0440 qualified through the approved single paid v0czdxw6gg run. Grant1/1consumed; do not submit another run or imply production acceptance.
2. Resolve the existing named empty PUBLIC board approval; read back its actual ID and current account eligibility. Existing public board usability for Trial must be measured, not assumed; if Pinterest rejects it, stop and present a separate creator-only API-board scope/create proposal, never silently broaden OAuth.
3. Freeze codeSHA, both SQL checksums, exact board/asset IDs and time-bounded private configuration. Present one production-change bundle with drift check, impact to this account/workspace and rollback. No public admission, new organization, staging, resources or subscription.
4. After that approval, install only reviewed additive SQL/config/exact tested deployment, verify current baseline and fields, then human official four-scope OAuth consent. Record actual identity/boards/refresh. Fresh actual20–60fps window footage remains required; native recorder helper is only an uncompiled candidate.
5. Present both final image-Pin cards with actual immutable delivery metadata and board ID for exact write approval. Immediate card and revised18Oct12:00EDT/16:00UTC schedule are unapproved drafts. First1h analytics read must finish before proposed14:00EDT expiry. If deadlines cannot be met, ask for revised exact times, never autoextend.
6. Execute approved intents once; keep IDs/URL/read-back/account/board/visibility/no-duplicate/clock evidence. Exercise cancel/pause/reconnect/error controls only within granted scope. Finish disconnect and token erasure. Standard submission and third-party public acceptance remain separate.

Rollback: disable Pinterest execution/public/metric admission within the approved impact, preserve in-flight IDs/journal/uncertainty, cancel pending private work, restore exact approved previous source/config if separately authorized. Keep additive rows; database/code rollback cannot remove a real Pin. Deletion needs exact-ID approval. Monitor quota/journal failure, lease lag, unknown outcomes, revoked-grant reads and provider429/403 without logging secrets. No alert recipient/send or maintenance purge is activated by this document.
