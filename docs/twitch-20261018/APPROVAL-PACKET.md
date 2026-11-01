# Minimum external approval packet — not executed

Prepared for James on 2026-10-18. The user's existing authorization covers isolated engineering, free offline/mock/synthetic tests, documentation and local commits. The external actions below are outside that authorization. This packet is concrete review material, not a request to approve unidentified future work.

## A. Publish the reviewed candidate to GitHub

Repository: `dev-james0723/PostRiff`. Source branch: `codex/rafii-twitch-full-20261018`. Base branch: `consumer-saas`. Exact source commit is in the distribution `RECEIPT.json`; its patch and bundle accompany this packet.

Requested approval: push that branch and open a draft PR containing this candidate. Before pushing, read the latest canonical HEAD and active ownership, check migration 134 numbering and rebase only inside the owned isolated worktree if necessary. Re-run affected acceptance if the base changes. Do not merge or deploy under approval A.

Suggested PR title: **Add gated Twitch native OAuth, consented actions and durable EventSub**.

PR summary: Rafii currently has no public Twitch callback or native Twitch execution surface. This candidate integrates actual OAuth custody, 112 Helix operations, 35 EventSub types, exact per-action human approval, tenant-bound durable jobs and the existing Rafii UI/Agent model. Release and purpose flags remain off. Evidence contains actual disposable PostgreSQL RLS/concurrency tests and offline request/UI contracts; live acceptance remains pending.

## B. Deploy a disabled candidate after review

This is a separate approval. Target: the reviewed Rafii application serving `https://rafii.io` and **only** Supabase project `buoyhkbodnhzngaotoel`. Staging `oxacvkhpfgytkepxcaqh` is not an acceptable substitute or an implied production target.

Requested operations: review and apply candidate migration 134 to the canonical project; merge the exact accepted revision; deploy the callback/API/UI and bounded worker code with all four Twitch release/purpose flags false. No client secret should be included in logs, Git or the approval text. The exact production revision/deployment and database routing must be identified again immediately before execution because public health currently reports no source revision.

Required pre-execution evidence: complete schema compatibility review against the current production migration chain, approved rollback/forward-fix plan, verified deployed revision, unchanged unrelated mission ownership, database-target pairing and resource budget. Rollback begins by disabling Twitch execution and purpose flags. Retain audit metadata; do not automatically drop tables or destroy pending receipts. Unknown provider outcomes require explicit reconciliation, not replay.

Post-deploy acceptance: callback route exists at the exact fixed URL; arbitrary Host/redirect/workspace input cannot retarget it; unknown/expired/replayed OAuth state fails safely; unauthenticated native routes and direct table reads fail; other platform regression smoke checks remain healthy. These checks do not require enabling public Twitch connect.

## C. Secure developer-console operation and new app

Do this after callback deployment has been verified. Requested external action: James signs in securely to the official Twitch developer console and, once the worksheet is reviewed, authorizes creation of the Rafii app with the exact callback. Account email verification, two-factor authentication and CAPTCHA, if requested, are performed by James in the browser. Passwords and security codes must never be entered in chat or captured by an agent.

Required one-time handoff: **complete Twitch console sign-in / security verification in the browser and confirm that the console is ready**. No Google developer-console step is inherent in Twitch registration. Ask about Google only if an actual separate task or observed authentication dependency requires it.

The confidential app secret goes directly into the approved server secret store. A secret value is not part of this packet, Git, test receipts or chat. The app worksheet is in `DEVELOPER-APP-AND-COMMERCIAL-DRAFT.md`.

## D. Commercial, storage and AI authorization request

The complete unsent request is in `DEVELOPER-APP-AND-COMMERCIAL-DRAFT.md`. Requested approval: submit that text through a verified official Twitch business/developer review channel after the legal entity, authorized contact, privacy/deletion URLs and actual subprocessors are completed. No recipient address has been invented and no message has been sent.

This requests, rather than assumes, permission for paid multi-tenant creator/marketing services, permitted analytics, broadcaster-authorized reuse, storage/retention and AI assistance with per-action human approval. Any fees or contractual commitment require separate approval. Keep public execution/purpose flags disabled until the relevant written authorization is recorded.

## E. Named live canary and gradual public release

After A–D and the relevant written permission, identify a consenting workspace, exact Twitch account, app Client ID, callback deployment, approved scopes and a bounded test window. Approve a test packet naming the exact live operations and content. No arbitrary account or external destination may be selected by a model.

Start with OAuth identity, wrong-workspace/replay rejection, read-only eligibility, refresh and explicit revoke/reconnect. Then test signed webhook challenge/notification/revocation with content purpose authorization. Exercise individually approved harmless channel/chat/schedule mutations and confirm readback; test clips' asynchronous completion and unknown-outcome reconciliation. Monetized, destructive and audience-changing operations require separately named acceptance on an eligible approved account. Test stream-key delivery only if it is specifically required, in the secure human path.

Before all-customer release, prove worker throughput and startup/hourly validation capacity for the expected connection count, deployed browser interaction/accessibility, production tenant isolation, retention/deletion, operational alerting and rollback. The current code has global default-off flags; it does not claim a deployed customer allowlist. An isolated approved canary environment or an explicit canary restriction must be established before enabling any broad flag.

The current handoff seeks no standing approval for future paid resources, autonomous live mutations, credential disclosure or sending messages. Individual Rafii user approval remains mandatory even after the integration is released.
