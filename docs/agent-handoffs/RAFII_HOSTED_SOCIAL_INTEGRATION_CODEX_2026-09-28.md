# Rafii hosted social integration: Codex handoff (2026-09-28)

## Execution state

- Branch: `codex/hosted-social-integration-20260928` in `/Users/ouxianxing/Documents/James-Au-Studio-hosted-integration-20260928`.
- Based on `origin/consumer-saas` at `84165f1`. Integration commits: `484b81b`, `ba09df2`, `679c085`.
- Local integration candidate only. This branch has not been pushed, merged, or deployed. No newly supported channel has a verified live OAuth or publish connection from this work.
- The dirty primary checkout `/Users/ouxianxing/Documents/James-Au-Studio` and other worktrees were untouched.

## Integration audit and changes

- Re-fetched and compared current `consumer-saas` with PR #22 (open, conflicting), PR #28 (open, stacked on #22), and PR #25 (open, TikTok site verification). Integrated their connector work and verification file locally without merging the stale PRs.
- Preserved current-base video upload/storage architecture. Added verified MP4/MOV video scheduling and bounded private video reads for YouTube/TikTok, with bucket/object/ETag/duration verification frozen into approval. Existing image flows remain image-only.
- Corrected a stale image-channel test and the actual rejection message for a verified video on LinkedIn. A private-storage body timeout now holds the publish attempt before provider submission.
- Removed obsolete “Rafii can't upload videos yet” YouTube/TikTok copy. Production video upload remains disabled until `RAFII_VIDEO_UPLOADS_ENABLED` is deliberately configured after deployment.

## Validation (local candidate)

- `ci-python`: PASS, 1,788 tests. `ci-web`: PASS, 398 tests. Typecheck and oxlint: PASS.
- Hosted Wave 3 connector and storage video focused tests: PASS; final focused storage/Wave 3/asset consumer run: 70 tests PASS before the last message-only validation split, followed by the full Python PASS.
- Targeted `ci-postgres` (channels, orchestration, video, consumer deletion): PASS.
- Credential-free Next.js production build: PASS. `ci-copy`: PASS. Offline `ci-secrets`: PASS.
- `ci-browser`: PASS on a disposable database with synthetic identity/provider responses; this checks local UI/API behavior, not provider authorization or production.
- Evidence JSON/log files are ignored under `docs/consumer-ready/evidence/` and tie each gate to a source fingerprint.

## Provider readiness as checked on 2026-09-28

The Vercel check inspected **production environment variable names only**; it did not read or verify values. No `POSTRIFF_OAUTH_<ID>_REVIEWED` variable names were present. Provider review, actual scopes, callbacks, account grants, publishing, and deployed behavior therefore remain unverified.

| Channel | Local code | Production credential names | Actual connection state |
| --- | --- | --- | --- |
| LinkedIn, Instagram | Existing hosted integrations retained | ID and secret names present | No regression smoke this turn; do not infer connected |
| Threads | Existing integration retained | Current review/grant state unknown | Unverified |
| Bluesky | Integrated | Client JWK name present | Metadata and OAuth not live verified |
| Mastodon | Integrated | Enabled flag name present | Instance registration and OAuth not live verified |
| Telegram | Integrated bot/code flow | Bot token and webhook secret names present on latest check | Bot identity, webhook, and chat/code flow unverified |
| Discord | Integrated | Client ID, secret, bot token names present | Install and channel picker unverified |
| X | Integrated | Client ID and secret names present | Callback, OAuth grant, read-back unverified |
| Facebook Pages | Integrated | Client ID and secret names present | Business login, Page grant/picker unverified |
| YouTube | Integrated including verified video path | Client ID and secret names present | OAuth and video publish unverified; production upload flag absent |
| TikTok | Integrated including verified video path and site file | Client ID present; client secret absent | Sandbox Target Users empty; Production shows Draft; site verification URL returned HTTP 404; login gate open |
| Pinterest | Integrated | Client ID and secret absent | Provider app approval/credentials unverified |
| Reddit | No hosted connector | None | Data Access Request submitted Sep 25; no approval reply found after Sep 24; pending |

`POSTRIFF_PUBLIC_BASE_URL` and `POSTRIFF_CREDENTIAL_KEY` names are present. Their values were not inspected. Current production has not received this integration branch, so the local feature and passing tests are not evidence of a production connection.

## First human gate

In Chrome, the TikTok for Developers Rafii Sandbox page is open at `https://developers.tiktok.com/app/7689508412459370497/sandbox/7689479552734136327#target-users`, and its **Add account** flow has opened a TikTok login popup. James must sign in to the TikTok account he owns, complete any 2FA/CAPTCHA, and personally accept any TikTok account/developer authorization or terms presented. No agent entered credentials or granted consent.

Immediately afterward, recheck that the target account appears in Sandbox Target Users (TikTok says display can take up to an hour), check the current URL-property/review state, then have James enter the TikTok client secret directly in Vercel production configuration without putting its value in chat or a file. Verify presence by name only. Separately review the deployment candidate and authorize deployment before any live Rafii OAuth smoke. Keep all `REVIEWED` flags off until provider approval is actually confirmed.

Official target-user procedure: https://developers.tiktok.com/docs/en/add-a-sandbox
