# Existing-production read-only Trial pilot — candidate

2026-10-15 UTC. **PREPARED; NOT ACTIVATED.** Source `6d36716cfcc945fcc93a819ba243ffa870a1a799` adds quota least-privilege hardening validated by cloud7lkkltn4d9; retained b99cf89a source checks passed bcz5vdqznw. Current live5e4f4e13 is not yet incorporated; local merge approval pending. This is an explicit change to the earlier new-staging design, following the human's existing-production-only direction. It creates no organization, database, Vercel project or subscription. It does not authorize execution.

## Target and effects to review

Use existing Rafii Vercel project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, origin `https://rafii.io`, and canonical Supabase `postriff-phase2-private` / `buoyhkbodnhzngaotoel`. This is shared production infrastructure, not an isolated staging environment. Keep production login, existing vault key, sessions and other connectors intact; never copy them elsewhere.

A restricted pilot deployment/configuration would permit only the approved actor in one approved workspace to connect the approved Pinterest username. OAuth uses Pinterest's official consent page and `https://rafii.io/api/oauth/pinterest/callback`; the single exact URI was separately approved, saved in app `1615884` and verified after reload. See the callback registration receipt; no repeated console approval is needed. Sandbox API and token operations use `https://api-sandbox.pinterest.com`; **Rafii production infrastructure and Pinterest Sandbox are different boundaries.** Sandbox boards are separate from live boards. This pilot is not public production acceptance.

The pilot persists only that tenant's normal encrypted grant, OAuth transaction, profile metadata without avatar download, capability and audit records. It adds hashed rate counters to one additive server-only table. It neither clones production data nor changes Auth/RLS policies. Deployment touches the shared application and must be reviewed against the then-current live SHA. Recheck drift before requesting or executing the final operation.

## Exact configuration candidate

Reuse the existing production vault key; do not rotate it or install the unused local staging key. Securely install the existing app1615884 client ID/secret only within reviewed credential-management scope; never reset the secret or put it in evidence.

- `POSTRIFF_PINTEREST_SANDBOX=true`
- `POSTRIFF_PINTEREST_TRIAL_READONLY=1`
- `POSTRIFF_PINTEREST_TRIAL_WORKSPACE_ID`: `568699ad-d66e-42b8-a7f1-e86d0c35ab02` (own active-owner membership verified; human selection pending)
- `POSTRIFF_PINTEREST_TRIAL_ACTOR_ID`: `b167161d-37f4-4bc3-ae22-2482c982e5a0` (active owner verified; human selection pending)
- `POSTRIFF_PINTEREST_TRIAL_USERNAME`: `jamesaucreates` (signed-in developer profile verified; human selection/API eligibility pending)
- `POSTRIFF_PINTEREST_TRIAL_EXPIRES_AT`: **PENDING exact Unix seconds, within 24 hours at activation**
- `POSTRIFF_OAUTH_PINTEREST_CALLBACK_ORIGIN=https://rafii.io`, only after exact registered URI agreement is verified.
- Keep public `ENABLED`, `VERIFIED`, `REVIEWED`, `POLICY_APPROVED` and Agent/provider-data gates closed. The read-only lane cannot set the public production diagnostic true. Existing emergency DISABLED overrides the pilot.

Missing/malformed/wildcard/expired configuration fails closed. The existing quota SQL checksum remains `9a9b20f0e41ce5ba65c1bf013ed9e427e4b60237dc1e9130ac9043253f56fce4`; use only this reviewed additive file after production schema/privilege preflight and specific migration approval. Do not apply the historical clean-database bootstrap inventory. Runtime fails closed if durable budget storage is absent.

## Allowed test and observable limits

After exact deployment/configuration, account/tenant and live-consent authorization: Rafii login → profile/boards connection choice → official consent → state-checked callback → code exchange → numeric account identity and username agreement → board pagination → refresh → reconnect → disconnect. Requested scopes are only `user_accounts:read,boards:read`; older broader grants are rejected. Check actor/workspace before token custody or network and again at callback; changing the allowlist invalidates pending callbacks. Board reads reconfirm the account. Expiry stops token access/refresh; disconnect cleanup remains possible.

The strict egress allowlist permits only Sandbox GET `/v5/user_account`, GET `/v5/boards` and POST `/v5/oauth/token` for authorization_code/refresh_token. Sections, Pin reads, Pin writes, board mutation, analytics, Agent data access and publication/scheduling are excluded. The Rafii pilot cap is 100 total requests per UTC day, including token calls. This is more conservative than Pinterest's documented Trial1000/day; at most200 requests across two UTC dates fall in any rolling day. Other out-of-band use of app1615884 is outside this local counter and must be reconciled during the pilot. Provider429 always remains authoritative.

Record redacted requests, actual identity/account type/board observations, refresh/reconnection/disconnect outcomes, exact hosting/source/environment, dates and both positive/negative tenant tests. Never label mock, Sandbox or queue acceptance as live public publication. No Pin will be created by this pilot.

## Rollback and remaining inputs

Emergency pause via the existing DISABLED flag; then approved actor disconnects, encrypted grant is erased and pending authority is canceled. Preserve audit/history and uncertain receipts. Any deployment rollback/config changes remain an exact reviewed external action. No irreversible schema removal is required for this pilot rollback.

The exact workspace, Rafii actor, Pinterest account and time window remain unresolved; the prior input question is pending. After those facts arrive, freeze a concrete deployment/config/SQL/callback operation and request the required approval once. The user has already selected the existing production project; do not ask them to choose a new organization/database or revive paid/Free proposals. Actual human OAuth consent, a specific real Pin, Standard submission, production release/canary and public expansion remain separate gates.

Official sources checked 2026-10-15: [Sandbox](https://developers.pinterest.com/docs/developer-tools/sandbox/), [rate limits](https://developer.pinterest.com/docs/reference/rate-limits/), [OAuth](https://developer.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/).

## Fresh preflight — 2026-10-15 continuation

Live rafii.io is now5e4f4e13/READY, not yet merged into this candidate. The exact rafii.io callback was approved and persisted. Client ID/secret and quota table remain absent. Team metadata still says Pro/overdue, but the newer READY deployment means that field alone does not prove deployment rejection. No deploy/payment/configuration change was attempted. [NEXT-ACTION-MERGE](NEXT-ACTION-MERGE.md) is the exact pending local action. The new quota migration explicitly removes inherited service-role privileges and forces RLS; cloud disposablePG passed. [Fresh preflight](evidence/pilot-continuation-preflight.json) · [Quota results](evidence/quota-permission-validation.json). This broader pilot remains inactive and requires its exact credentials/configuration/migration/deployment/identity/consent authorization.
