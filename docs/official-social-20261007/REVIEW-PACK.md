# Authentication review preparation — not submitted

Use with ACTION-REQUIRED.md and CONNECTION-ACCEPTANCE.json. Text below is a scope-justification draft, not evidence that the application is approved. Actual legal operator identity/domain verification, reviewer access and genuine footage remain human-gated. Do not invent them or upload a fixture recording.

## Shared reviewer explanation

Rafii lets an authenticated customer connect their own social identity or eligible destination to the workspace they manage. The customer selects a provider in Channels, follows the provider's official consent page, and returns to the same Rafii account/workspace. The backend exchanges the code and stores encrypted credentials. The app displays the actual identity and granted permissions. Additional operations require their own permissions and guards. Basic connection does not enable publishing automatically. Users can disconnect in Channels and use the published data deletion instructions.

## Minimum scope justifications

- LinkedIn `openid profile`: identify the member using OIDC UserInfo. No organization discovery, restricted member reads or publishing in this demonstration. ID tokens are not consumed by this implementation; do not describe an unimplemented ID-token validation flow.
- Threads `threads_basic`: identify the consenting Threads account and retain the connection using documented exchange/renewal. No content publishing or insights requested.
- Instagram `instagram_business_basic`: identify the consenting Business/Creator account through Instagram Login. No Facebook Page is necessary for this route. No insights or publishing demonstration included.
- Facebook `pages_show_list`: discover Pages available to the consenting owner, display granted tasks and choose a destination. Basic Page identity contract and exact Business Login config must be verified before submission. Do not assert personal-profile identity is a connected Page.
- YouTube `youtube.readonly`: resolve the consenting user's actual channel via `channels.list(mine=true)`. No upload, public-video compliance demonstration or analytics requested in this connection-first package.
- TikTok `user.info.basic`: display the consenting user's basic identity via Login Kit. No Display API or Content Posting request. A developer sandbox demonstration, if the portal requires one, must be labelled sandbox; separate ordinary-user production proof follows approval.
- Pinterest `user_accounts:read`: resolve the account identity. Board and Pin access is deferred until a workflow needs it. Trial/sandbox evidence must be labelled and cannot qualify public access.
- X `users.read tweet.read offline.access`: documented OAuth2 identity/renewal path; the app calls only the approved `GET /2/users/me` endpoint under bounded onboarding authority. No metered calls occur before spending approval.

## Genuine demonstration shot list

1. Show environment/revision and sign in through normal Rafii UI as the designated reviewer/test owner.
2. Open Channels and Connect; show account eligibility and minimum requested permissions.
3. Show official consent, recording only non-sensitive UI. Do not record passwords, codes, tokens, raw callback query strings or client secrets.
4. Return to original workspace. Show real provider name and selected destination (Facebook Page / YouTube channel where applicable), actual grants and “publishing not enabled” when applicable.
5. Navigate, reload and start a fresh Rafii session; show persisted connection.
6. With explicit test-account approval, disconnect and reconnect; demonstrate no impact to the second isolated workspace. Do not revoke a shared grant without checking its other uses.
7. Show cancellation/denial recovery. Renew only when genuinely eligible; show reauthorization instructions otherwise.

Record provider, app ID, environment, source revision, pseudonymous account/workspace labels, destination ID (redacted outside secure receipt), actual grant, timestamps and server trace reference. Each recording must state app-role/sandbox or ordinary-external-user classification. No genuine recording is available yet; cloud fixture images are engineering evidence only.

## Privacy/deletion and metadata

The following production pages returned HTTP200 on 2026-10-07:
- https://postriff-phase2-private.vercel.app/privacy
- https://postriff-phase2-private.vercel.app/terms
- https://postriff-phase2-private.vercel.app/data-deletion

Reachability does not certify their legal adequacy or match to provider console registrations. Before submission, the operator must verify current legal entity/contact, data retention, deletion process and domain ownership against these actual pages. Existing sensitive values and reviewer login details belong only in the provider's secure review form, never in this repository. No business description/testimonial was invented. No application was submitted; submission receipt is NOT_AVAILABLE.
