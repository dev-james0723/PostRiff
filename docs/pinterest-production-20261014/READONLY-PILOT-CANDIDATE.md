# Existing-production read-only Trial pilot — inactive candidate

Updated2026-10-17. **PREPARED; NOT ACTIVATED.** Current7432 local baseline merge and cloud verification are complete; same-type future local syncs are authorized. Latest exact source/CI are in [FINAL-RECEIPT](FINAL-RECEIPT.md). The abandoned new-staging proposals remain historical. No new organization, database, project or subscription.

Use only existing Vercel `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, `https://rafii.io`, and canonical Supabase **postriff-phase2-private / buoyhkbodnhzngaotoel**. This is a private trial on shared production hosting, not isolated staging or public release. Reuse existing Auth, vault key, sessions, scheduling and encrypted grant storage.

## Exact inactive configuration

- Existing Pinterest app1615884 client ID/secret via secure secret management; no secret reset or evidence copy.
- `POSTRIFF_PINTEREST_SANDBOX=false`
- **`POSTRIFF_PINTEREST_TRIAL_API_ENVIRONMENT=production`** (explicit official API selection)
- `POSTRIFF_PINTEREST_TRIAL_READONLY=1`
- Workspace proposed:`568699ad-d66e-42b8-a7f1-e86d0c35ab02`
- Actor proposed:`b167161d-37f4-4bc3-ae22-2482c982e5a0`
- Username proposed:`jamesaucreates`
- `POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT`: exact activation UTC +4hours, recorded before deployment; within code's24hour maximum.
- `POSTRIFF_OAUTH_PINTEREST_CALLBACK_ORIGIN=https://rafii.io`; callback `https://rafii.io/api/oauth/pinterest/callback` already approved, saved and reload-verified2026-10-15.
- Keep public `POSTRIFF_OAUTH_PINTEREST_ENABLED/VERIFIED/REVIEWED/POLICY_APPROVED` and Agent/provider-data gates closed. Explicit `POSTRIFF_OAUTH_PINTEREST_DISABLED=true` remains emergency override.

Actor/workspace/username and4hour window need human approval, together with the external bundle. These are proposed identities, not real API verification. The earlier owner/profile observations were2026-10-15 and must be rechecked at execution.

## Containment and source changes

Official API lane requires both explicit selector and matching SANDBOX=false; absent/mismatched/arbitrary selectors fail closed. Sandbox remains the default and its compatibility transport cannot select production. Egress permits only selected-host GET `/v5/user_account`, GET `/v5/boards`, and POST `/v5/oauth/token` with authorization_code/refresh_token. Sections, Pin reads/writes, board mutation, analytics, Agent access and publishing/scheduling are excluded.

Two scopes only:`user_accounts:read,boards:read`. Credentials alone never enable public connections. Exact workspace/actor, expected username, expiry, minimal scopes and durable100requests/UTCday cap apply, including token operations. Other app use outside Rafii's counter remains a pilot limitation. Provider429 is authoritative.

Pending OAuth custody binds App ID, API environment, read-only mode and complete pilot authority. After current tenant/actor/expiry checks pass, a changed binding consumes and rejects the callback before provider exchange; it cannot be replayed after restoring settings. Previously pending legacy Pinterest callbacks require a fresh connection. Token envelopes independently bind App ID/environment; Sandbox grants cannot be reused against the official API. Disconnect remains available after expiry, removes ciphertext and cancels future authority/jobs. No remote provider revoke endpoint is claimed.

## Permitted future test and receipts

After scoped external approval and actual human consent: Rafii login → profile/boards connection → official consent → authenticated state/callback exchange → numeric identity/username/type → board pagination → refresh → reconnect → disconnect. Record actual identity, environment, access tier, exact source/deployment and dates; never record tokens/codes/states/private names. Any eligibility denial stays a real failure, not a business-account guarantee.

This trial cannot prove public onboarding, Pin publication/visibility, scheduling, Standard Access or production readiness. No real Pin is included. [Exact next operation](NEXT-ACTION-READONLY-PILOT.md) · [Current read-only preflight](evidence/readonly-trial-preflight-20261017.json).

Official sources checked2026-10-17: [OAuth](https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/), [Sandbox](https://developers.pinterest.com/docs/developer-tools/sandbox/), [access tiers](https://developers.pinterest.com/docs/key-concepts/access-tiers/). API environment and app access tier are distinct; Sandbox entities/tokens are separate from production.
