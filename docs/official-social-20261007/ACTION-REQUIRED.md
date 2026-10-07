# Consolidated Action Required — candidate, not executed

The requested outcome is still blocked by the gates below. This is the single action list; an item is not permission to change another app or project. Never send secrets or account passwords in chat. Use the existing authenticated consoles and Vercel encrypted environment store. Minimum identity consent does not authorize posts, replies, deletes, uploads, broadcasts or historical imports.

## 1. Existing operator applications

| Provider / target | Exact secure page | Required human action and evidence | Minimum data/effect |
|---|---|---|---|
| LinkedIn, James Studio app 263833009 / client 86761m831bhyiu | https://www.linkedin.com/developers/apps/263833009/auth | Operator sign-in, OIDC Standard Tier, production callback and actual runtime mapping are confirmed. Approve the prepared branch-only preview callback/environment plan, then ordinary-user consent and acceptance. | `openid profile`, member `/v2/userinfo`; no organization permission or public-post manifest |
| Threads, app 2284812538978484 / product 1431031092226762 | https://developers.facebook.com/apps/2284812538978484/dashboard/ | Existing app is Testing / Unpublished. Only the old local callback is registered; production credentials are missing. Prepare hosted callback, secure product credentials and a genuine review demo; approve changes/submission separately. Inventory was recovered through the app selector. | `threads_basic`; identity, documented long-lived exchange/renewal only |
| Instagram, product 1717799895963991 in Rafii 1401844428820097 | https://developers.facebook.com/apps/1401844428820097/dashboard/ | Product ID matches actual runtime. Minimum permission says Ready for testing; parent Published does not prove advanced access. Verify registered product callback and public basic access. App Review currently errors. Insights review remains separate. | `instagram_business_basic`; identity; no Facebook Page requirement |
| Facebook, Rafii app 1401844428820097 | https://developers.facebook.com/apps/1401844428820097/business-login/configurations/ | Actual runtime maps to this app. Its only config 2961092884234131 requests four publishing/read scopes; no basic-only config exists. Verify minimum Page endpoint contract before approving a separate exact-scope config. Public Page access remains unverified; App Review errors. | `pages_show_list` baseline, eligible Page discovery/tasks/selection; any additional read scope must be evidenced and approved; no publishing/community permissions |
| YouTube, Rafii / rafii-509720 | https://console.cloud.google.com/auth/audience?project=rafii-509720 | Review transition from External Testing and applicable verification. Existing Rafii YouTube client/callback match production. Check YouTube API enabled/quota in this project. Shared upload/calendar/gmail declarations must not be silently removed. | `youtube.readonly`, actual channel lookup; no upload or analytics scope needed for connection |
| TikTok, Rafii app 7689508412459370497 | https://developers.tiktok.com/apps/ | Production runtime demonstrably uses sandbox 7689479552734136327's client key. Production remains Draft without products/scopes. Complete truthful production Login Kit metadata and genuine required sandbox demo, approve review submission, then deliberately switch credentials after approval. | `user.info.basic`; no Display/Content Posting request |
| Pinterest, Rafii app 1615884 | https://developers.pinterest.com/apps/1615884/configure/ | Signed-in console confirms Trial access pending. Secret is withheld and redirect edits are disabled. Await this existing request's result, then configure credentials/callback and any required real demo. No replacement app. | `user_accounts:read`; no boards/Pins scopes for identity |
| X, runtime client mapping pending; visible app 33504271 | https://console.x.com/accounts/2107161751049371648/apps/33504271 | Production start fails HTTP500: the live DB constraint rejects one-character `x`. Review/apply validated forward migration101 only with production DDL approval; no blanket migration apply. Then map runtime client and review OAuth2 setup, PKCE/callback and the bounded policy below. | `users.read tweet.read offline.access`; allowlisted `GET /2/users/me` only |

Every registered production callback must be exactly:
`https://postriff-phase2-private.vercel.app/api/oauth/{provider}/callback`
where provider is `linkedin`, `threads`, `instagram`, `facebook`, `x`, `youtube`, `tiktok`, or `pinterest`.

For provider-setting changes, return evidence of the actual app ID, selected product/access tier, registered callback, allowed scopes and approval state. Credentials remain in the secure store. An operator boolean or app-role login is not an approval receipt. No review submission has occurred.

## 2. Account-owner acceptance

Provide access to two isolated ordinary Rafii users/workspaces and eligible social accounts. Neither Rafii user may be Founder, and neither social user may hold developer/admin/tester roles on our provider app. Ownership/admin of their own Page is valid.

Owners perform password/passkey/MFA/CAPTCHA and official consent themselves. Authorize only the table's minimum identity/account reads and the test account's disconnect/reconnect. Identify workspace/account using a non-sensitive label or secure UI, not passwords/tokens. Test cancellation, partial/denied consent, wrong account, no eligible destination, lost Rafii session, reload, fresh login, duplicate callback and cross-workspace rejection. Leave genuinely time-dependent renewal pending until observed.

Real iPhone Safari acceptance is `validation_unavailable`: iPhone Mirroring timed out after reconnect. James must make the device available/unlocked in the normal supported workflow; no security controls were changed. Cloud Chromium at a narrow viewport is synthetic desktop-browser evidence only.

## 3. X spending proposal — disabled; approval required

Proposed initial onboarding authority: USD **1.00 total per app**, USD **0.05 total per workspace**, reserve USD **0.01 per identity request**, maximum **7 days** from approval. All reservations count, including failed/unknown provider responses. Allowed endpoint is exactly `GET /2/users/me`. No posts, searches, timelines, subscriptions, automatic top-ups or other endpoints. Ordinary users would inherit this bounded policy without manual per-user budget edits.

These are proposed ceilings, not a claim about X's current unit price. Before enabling, confirm the current endpoint price is no greater than the reserved ceiling. If not, stop and revise the proposal. USD5 visible credits does not authorize spending. James must explicitly approve app ID, ceilings and expiry; the engineer then records the approval reference and validated endpoint price. No policy or metered request was enabled in this task.

The implementation requires migration `100_social_cost_reservations.sql`, independent committed reservations, app-level locking and workspace limits. Forward migration `101_x_oauth_provider.sql` separately repairs the canonical provider ID constraint. Neither migration is applied in production. Existing narrower connection budgets take priority. Keep the encrypted credential key stable. Never reset usage by issuing a new policy to evade its approved limit.

## 4. Release gate

James explicitly authorized push, PR and preview in this conversation after reviewing source afda8f5186091351dab12d60fb05eeb46475fc1e. Production merge/deploy and provider/spending changes remain unauthorized. See HANDOFF.md for the exact candidate SHA and validation receipt before approval. Target is exclusively `postriff-phase2-private` / `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, repo `dev-james0723/PostRiff`, branch `codex/social-connection-recovery-20261007`. Do not touch `rafii-consumer-staging`.

Requested next release scope, once checks pass: update existing PR #131 against `consumer-saas`, run required checks and the authorized preview, then seek/execute explicitly approved merge and production release. Review migrations100/101 against the actual production database and recheck number claims before applying. Six historical ledger gaps need separate reconciliation. Initial enabled public providers: **none** until their app gates and ordinary-user acceptance pass; do not switch flags as part of a generic deployment.

Rollback: restore observed production deployment `dpl_9Jiq5wtAzg7iwJHC7DqW5kbJw8en` / source `91f6572c46fe9c357ca23ba43524f1ea3f27814e`; retain encrypted credentials and additive cost-reservation ledger. Do not drop the ledger, rotate the key or revoke customer grants. If production has advanced, reconcile the new source before releasing; do not overwrite it with this historical rollback anchor.
