# Personal API tokens — local implementation and security review

Status: implemented locally on 2026-09-19. Migration `016_api_tokens.sql` is a candidate, validated only on disposable PostgreSQL. It has not run against production. James approved tokens on trial plans, with the same writing allowance as the app.

## Contract

Interactive sessions manage tokens with `GET/POST /api/workspaces/{workspaceId}/tokens` and `DELETE /api/workspaces/{workspaceId}/tokens/{tokenId}`. Creation requires `manage_connections` and the existing server-side fresh-sign-in check. Revocation does not require step-up. POST takes `name`, `scopes` (`["read"]` or `["read","draft"]`) and `expiresDays` (30, 90, 365). The response contains `{item, secret}`; list/revoke never return the secret or hash. There is no second reveal endpoint.

Scripts send `Authorization: Bearer <token>`. Tokens use an explicit route allowlist:

- Read: workspace snapshot, connected-account list, memory files, conversation list/messages and run events.
- Draft: quick-start, create conversation, conversation turns/attachments, apply a completed candidate to drafts, cancel a draft run. Schedule proposals are candidate plans from those turns. Applying a candidate does not approve a publication.
- Denied: all action commands, approval/publishing/replies, channel connection or verification changes, billing/usage-cost routes, members/invitations, account/security, token management, tools invoke, cron and unknown future routes.

Draft clients must supply the same source-use confirmations as the app. `ownContent` and `confirmUse` are assertions made by the caller; possessing a token does not establish copyright ownership. Cloud/research consent, source policies, plan allowance and live edit permission remain enforced by the existing Ideas service.

## Security review

- 256-bit random bearer material; only SHA-256 hash and short identifying prefix stored. No secret in audit, list responses or React Query caches. Reveal state clears on close, workspace switch, page hide and component effect cleanup. Copy requires an explicit click.
- Every HTTP request validates scope against an explicit route allowlist and the creator's current membership. Token removal, revocation, expiry, profile deletion and account tombstones fail closed. The repository rechecks the token and locks its grant inside every workspace transaction; mutating services also check the live edit permission.
- Lock order is workspace then token for authorization, repository actions and revocation. Preliminary identity resolution finishes its separate transaction before acquiring the workspace lock.
- Only a recognized bearer-token request may skip browser CSRF headers, and it passes the scope guard before any public or sensitive route. Interactive-session requests retain the existing origin/header checks.
- Tokens never satisfy `assert_fresh`; even an owner token cannot access token management or security operations. A fresh interactive sign-in is required to create/reveal a new secret.
- Creation rate limited to 5/min/person; draft requests to 20/min/token. Last-used writes are throttled to once per minute. Token names/client labels are bounded and rendered as text. No token is accepted from a URL.
- Token table is service-role only with forced RLS; browser `authenticated` and `anon` have no table grants. Revocation metadata is retained in the list for 30 days; this does not delete audit records.

## Verification and limits

`tests/test_postriff_api_tokens.py` exercises the route allowlist. `tests/phase2/postgres_api_tokens.py`, run through `scripts/postriff_disposable_postgres.py`, covers trial creation, step-up, scopes, one-time secret custody, HTTP read/draft requests without browser headers, a deterministic draft with zero external model requests and no publication jobs, workspace isolation, current-role downgrade/removal, expiry/revocation and RLS.

A synthetic browser pass exercised scopes/expiry, one-time reveal, clearing and keyboard hold-to-revoke. It did not mint production credentials. Production migration and an actual Supabase sign-in/MFA ceremony remain deployment checks. Do not claim deployment readiness from local fixtures.
