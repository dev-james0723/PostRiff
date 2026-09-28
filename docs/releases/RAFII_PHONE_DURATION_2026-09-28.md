# Rafii phone duration — 2026-09-28

Status: candidate under release validation. User approved a maximum of one hour and requested continuation until credits run out. Existing deployment authorization covers this phone repair. No additional paid call or top-up is authorized.

Changes:
- Retire the former RAFII_PHONE_MAX_SECONDS=60 test cap. New call rows allow up to 3600 seconds; paid Dial outbound calls explicitly request that maximum. Dial free-account limits are still respected. Legacy Twilio transport retains its own 600-second bound.
- Reserve the first minute, then atomically reserve additional minutes while the call is active. The authenticated manual-call UI approves available-balance spending; older explicit per-call limits and automatic-call limits are still honored. Concurrent wallet/Manager spending shares the workspace lock. Missing credits never become an overdraft. Unused time is released on confirmed final settlement, with unknown usage retained.
- Remove the separate daily USD cap for explicitly requested calls. Automatic calls retain it. Shared operator budgets, account/role verification, concurrency, opt-out and paid-task approvals remain enforced. Allowance-plan workspaces continue through their existing ledger; this release does not activate credit billing or alter plan terms.
- Dial audio is handed over at approximately nine minutes, before the existing 660-second Vercel invocation ends. The same PSTN call reconnects through Dial's documented protocol. A short audio gap is possible; no call is redialed. A signed, single-use 20-second handoff window and generation fence prevent duplicate streams/old tools. Transcript context and cumulative usage persist; no repeated greeting, press-1 or sign-in code.
- Add migration 043 for the one-hour constraint, funded time and handoff state. Existing call rows retain their previously approved timeout and holds. Apply migration before the new application.

Validation completed locally: 246 Rafii unit tests; real disposable PostgreSQL hour simulation, insufficient-credit rollback, simultaneous renewal, final idempotent settlement, handoff expiry/generation fencing; signed ASGI Dial handoff/resumption and inbound/outbound regression suites. Tests use fake providers and a synthetic model, never real paid calls. Web types/lint and full CI recorded below when complete.

External blocker verified in the signed-in Dial dashboard: current account is still free-tier, with a 300-second hard cap and $0.44 provider balance. Saving 3600 seconds was rejected. The unsaved edit was cancelled. No top-up, subscription, payment-method change or auto-reload was performed. Provider evidence: /private/tmp/rafii-dial-free-tier-limit.png. Therefore one-hour real calling is NOT yet accepted, even after application deployment.

References:
- https://docs.getdial.ai/api-reference/rest-api/calls/make-call
- https://docs.getdial.ai/api-reference/rest-api/account/update-account
- https://docs.getdial.ai/api-reference/self-hosted-audio-protocol/overview
- https://vercel.com/docs/functions/websockets
- https://vercel.com/docs/functions/limitations

Remaining: full CI, migration/deployment and signed-in UI verification. Then the account owner must complete a Dial top-up or subscription to lift its free-tier restriction; set the number to 3600 seconds for inbound calls. A new paid test approval is required for actual extended audio validation.
