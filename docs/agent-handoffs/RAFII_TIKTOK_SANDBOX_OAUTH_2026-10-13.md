# Rafii × TikTok Sandbox OAuth — isolated implementation and handoff
Date: 2026-10-13 (US Eastern)
Repository: dev-james0723/PostRiff
Base: consumer-saas @ 7e993563be9841f7f98758fb0c8c52f158ea7252
Branch: codex/rafii-tiktok-sandbox-oauth-20261013
Worktree: /Users/ouxianxing/Documents/.agent-worktrees/rafii-tiktok-sandbox-oauth-20261013
Authorization boundary: local code only; NO Push, Merge, Deploy, TikTok publishing, personal consent, or TikTok App Review submission.

## Verified external facts
- TikTok App ID 7689508412459370497, Sandbox ID 7689479552734136327; target user @jamesaucreates listed (September 28, 2026).
- Sandbox: Login Kit enabled; scopes user.info.basic and video.publish listed; Direct Post toggled on.
- Registered Sandbox Web callback URLs include https://rafii.io/api/oauth/tiktok/callback and https://postriff-phase2-private.vercel.app/api/oauth/tiktok/callback.
- Production App status displayed Draft; this is not a TikTok public posting approval.
- Rafii official Channels UI showed TikTok 'Not available yet' and disabled Continue.
- HTTP GET returned 200 and exact TikTok site-verification token on rafii.io and postriff-phase2-private.vercel.app. TikTok URL Property portal verification is separate.
- Vercel Production variable *names* for TikTok Client ID and Secret exist. Their contents were not inspected; names do not establish a valid application grant.
- Primary checkout had unrelated unstaged changes. All edits here are in a separate worktree.

## Deliverables (current local candidate)
- src/postriff_phase2/wave3_connectors.py: optional dedicated Sandbox credential lane, opt-in flag POSTRIFF_TIKTOK_SANDBOX_ENABLED=true; never falls back to Production client key or secret. Explicitly rejects Vercel production and canonical production origins.
- src/postriff_phase2/providers.py: Sandbox cannot inherit operator review, publish-approved or publishing-tested flags.
- src/postriff_phase2/hosted_social.py: explicit identity-only Sandbox deny in publishing-worker selection, including if a review flag was accidentally mutated.
- src/postriff_phase2/oauth.py: safe explanatory setup issue for Sandbox mistakenly targeting Production.
- scripts/tiktok_sandbox_preflight.py: read-only JSON static readiness check, identity-only scope, no TikTok requests or secret contents; exit 0 on readiness, 2 on blocked.
- tests/test_tiktok_sandbox_oauth.py: thirteen synthetic security and regression tests.
- .env.example: Preview-only, placeholder variable names; no real secret values.

## Verification classification
- Base Git commit 7e993563 and isolated branch: VERIFIED.
- Original Hosted Wave 3 tests: 40 PASS using existing .venv.
- New isolated Sandbox tests: 13 PASS.
- Relevant regression: 124 PASS across Wave 1, Wave 3, Sandbox and readiness/onboarding modules; Python syntax compilation PASS; git diff --check PASS.
- Exact Sandbox Client Key/Secret loaded in isolated Preview: BLOCKED, no authorized Preview secret configuration yet.
- Stable isolated HTTPS Preview callback registered in TikTok Sandbox: BLOCKED, requires a separate approval to create/modify.
- Human OAuth consent, code exchange, profile read, refresh, disconnect: NOT RUN, cannot be simulated as live.
- Real TikTok posts and Production submission: ZERO, deliberately disallowed.

- Read-only preflight smoke with empty env: exit 2 (blocked as expected); provider HTTP calls 0; publishing authorization false; no secrets printed.

## Next step after approval
1. Approve separately a private Preview deployment with its exact stable HTTPS callback; add that callback to TikTok Sandbox Login Kit, not Production.
2. Configure PREVIEW ONLY: POSTRIFF_TIKTOK_SANDBOX_ENABLED=true, POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_ID and _CLIENT_SECRET, POSTRIFF_PUBLIC_BASE_URL and POSTRIFF_CREDENTIAL_KEY. All secrets go directly into protected Preview settings; NEVER in chat/git/logs. Do not change global Production OAuth origin.
3. Run the read-only scripts/tiktok_sandbox_preflight.py against the isolated Preview configuration. Passing it establishes only static configuration.
4. In Rafii authenticated Preview choose TikTok -> Account only -> scope user.info.basic. James personally completes TikTok login, 2FA/CAPTCHA and consent; agent must stop before consent.
5. Read back providerAccountId and granted scopes, encrypted token storage, one-time state/nonce, token refresh and disconnect; verify no unexpected second account. Do not post.
6. Only after full evidence, request separate permission before a Production App Review submission, Merge, Push, Deploy or actual post.

## Material risk
Rafii connectReady=false comes from adapter/credential shape, missing Fernet vault key, invalid fixed HTTPS callback, provider gate or operator pause; it does not automatically mean TikTok rejected Sandbox Login Kit. Variable name presence alone cannot distinguish these reasons. Obtain authenticated setupIssues without reading secret values. Never set POSTRIFF_OAUTH_TIKTOK_REVIEWED=true as a workaround.

Official documentation:
https://developers.tiktok.com/docs/en/add-a-sandbox
https://developers.tiktok.com/docs/en/login-kit-web
