# Public YouTube OAuth verification and credential custody

2026-10-08. Implementation candidate; this document is not a Google approval, Console mutation, submission, or provider acceptance result. The earlier staging setup receipt records External Testing, a separate staging web client, declared creator scopes and Analytics/Reporting API enablement. The production project Rafii YouTube Production (`rafii-youtube-production`, number `568838253270`) was created during this mission; no production client, API/branding configuration or review submission is confirmed. Domain ownership and review status still require actual provider evidence. See CURRENT-STATE.json. The current mission authorizes legitimate configuration and submissions but excludes invented operator facts, legal attestations and another account holder's consent.

## Public configuration and review

Use a dedicated production YouTube project and keep staging separate. This isolates the YouTube consent/review boundary from existing Gmail/Calendar integrations; changing only an OAuth client in their shared project does not establish independent grant/revocation boundaries. Keep the existing Gmail/Calendar variables and grants intact. Customers authorize Rafii's server application; they do not create their own Cloud projects. Google recommends separate testing and production projects. [Sensitive-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

Configure External/In Production, recognizable branding, verified authorized domains, exact deployed HTTPS callback, and publicly accessible homepage, privacy, terms and contact/deletion information. Publishing status alone does not approve scopes: unapproved sensitive/restricted scopes can still incur a lifetime 100-new-user cap. Approved scope requests are exempt from that cap. Testing has a separate 100-listed-tester limit and seven-day authorization/refresh expiry. Workspace administrator/account restrictions can still prevent consent. [Google audience rules](https://support.google.com/cloud/answer/15549945?hl=en)

Before submitting, verify domain ownership using an associated project owner/editor, confirm actual operator/support/privacy facts, and review the published data disclosures. Current Google review requires published branding before data-access verification. Prepare narrow-scope justifications and an accurate English demonstration showing the consent flow, app name, OAuth client ID in the address bar and each requested sensitive feature. Retain the resulting submission reference/date and later decision separately. A draft or demo is not a submission, and submission is not approval. [Current verification procedure](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

## Dedicated YouTube callback origin and controlled cutover

The candidate adds optional server variable `POSTRIFF_YOUTUBE_PUBLIC_BASE_URL`. When absent or empty, all callbacks preserve their existing `POSTRIFF_PUBLIC_BASE_URL` behavior. When set to a fixed HTTPS origin, it changes only the YouTube authorization redirect URI and the public YouTube callback's destination in the signed-in app. Standard and agentic clients both use that same dedicated origin; other social providers and existing Gmail/Calendar configuration remain unchanged. `NEXT_PUBLIC_APP_URL` alone does not configure Python OAuth callbacks.

For the intended production cutover, register exactly `https://rafii.io/api/oauth/youtube/callback` on each applicable new YouTube client before setting the override to `https://rafii.io`. Reject origins containing user information, non-root paths, query strings, fragments, whitespace or malformed ports. Request `Host` and `X-Forwarded-Host` never select the destination. Both a cold public callback and an already-mounted runtime use the configured fixed origin; preview overrides must equal the explicitly approved staging origin.

Keep the override **unset on the old production client** until the new client's redirect is registered and the deployment/client configuration has been reviewed together. Preserve the existing Gmail/Calendar/global variables. Allow existing ten-minute OAuth transactions to finish or expire before switching, then start fresh consent: completion exchanges against the exact redirect URI stored with that single-use state, and changing the configured client still fails the protected client-binding check. Switching an origin or client does not migrate historical refresh grants or approve Google verification.

This is an implementation candidate only. No override has been enabled by this workstream, no new production OAuth client registration is confirmed, and the existing live callback's redirect to the older private app origin remains a recorded cutover gate. Synthetic origin/callback regressions cover both lanes, in-flight stored redirect preservation and hot/cold handling; their new-source execution is assigned to the root's next remote validation.

## Scope justifications for the released creator workflow

| Scope | Purpose and narrower-scope boundary |
| --- | --- |
| `youtube.readonly` | Discover and revalidate the authorizing immutable Channel ID; read owned video/channel status. Also required alongside Analytics access for `reports.query`. It cannot upload or manage videos. |
| `youtube.upload` | Upload the exact approved video through official resumable `videos.insert` and apply authorized thumbnails. Initial upload permission is incremental; no broad account permission is requested merely to upload. |
| `youtube.force-ssl` | Manage reviewed metadata, native publication scheduling/rescheduling/cancellation, caption tracks, playlists and authorized comments. `videos.update` and caption methods do not accept upload-only permission. It is powerful, including deletion capability: Rafii must separately authorize each effect and never imply blanket deletion consent. |
| `yt-analytics.readonly` | Retrieve nonmonetary channel/video performance for the connected creator. No revenue or membership access is included. |

Official method references: [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [videos.update](https://developers.google.com/youtube/v3/docs/videos/update), [captions.list](https://developers.google.com/youtube/v3/docs/captions/list), [reports.query](https://developers.google.com/youtube/analytics/reference/reports/query). Existing per-feature scope maps remain incremental. Revenue/membership scopes require separate intentional enablement. No `youtube`/`youtubepartner` shortcut is needed for ordinary creator features. Shorts use the video upload API; Rafii must not promise a dedicated Shorts publishing endpoint or infer successful classification from dimensions alone.

## Standard versus AI-agent authorization

Google's current client guidance requires separate standard and agentic client IDs for applications with both direct/human workflows and Google-calling AI agents/tools/MCP. Client designation grants no extra permissions or verification exemption. A deterministic worker executing an exact already-approved operation is not automatically a Google-calling AI agent; classification follows actual tool/data flow. [Manage OAuth Clients](https://support.google.com/cloud/answer/15549257?hl=en)

`YouTubeProvider.mount` remains the standard connector and mounts a separate child adapter from `POSTRIFF_OAUTH_YOUTUBE_AGENTIC_CLIENT_ID` / `_CLIENT_SECRET`. It rejects reuse of the standard client ID and stays execution-disabled unless `POSTRIFF_YOUTUBE_AGENTIC_ENABLED=1`. Agentic evidence comes only from `POSTRIFF_YOUTUBE_AGENTIC_PROJECT_EVIDENCE`; standard evidence cannot approve the agentic client.

The explicit Autopilot connection route requests `autopilot` with `{authorizationLane:'agentic',agenticConsent:true}`. It requires workspace owner authority and a fresh session both when starting and completing consent. The single-use encrypted transaction binds the exact selected client/lane; changing configuration, replaying state or selecting another existing connection fails closed. It requests read, upload and manage scopes for the separate channel policy; analytics remains incremental. Standard connection IDs remain unchanged; agentic connections use a distinct ID for the same immutable YouTube Channel ID.

Worker routing uses `provider_for_grant` / `provider_for_connection` from protected encrypted custody, never the projected UI lane. Refresh, inspection, API calls and revocation use that same exact client. An unconfigured agentic client cannot fall back to standard credentials. Real Google consent, client designation/verification, public-upload eligibility and provider-backed dual-lane acceptance remain unverified external release gates. An enable flag does not approve them.

## Implemented credential binding and compatibility

New access and refresh values contain version 2 envelopes with exact `clientId` and `authorizationLane`, inside existing application encryption. Bound-client/lane mismatches fail before a provider refresh/API request. OAuth start custody records the same client/lane; a configuration change before completion requires a new transaction. Incremental upgrades reuse a prior refresh only when both prior access and refresh envelopes independently match the current client/lane.

Revocation cleanup is fenced to the exact access custody observed by the failing refresh or API operation. A failed old refresh or old API response cannot purge a concurrent fresh consent. Calls without an observed credential cannot authorize cleanup. Provider account drift is handled with the same fence. Identity quota admission commits outside workspace locks, after a callback is consumed and before exchange/identity calls; it remains reserved if the later flow fails. Real-provider identity checks fail closed when the hosted admission hook is absent.

Legacy version 1 access has no historical issuer metadata. Google tokeninfo can prove its current audience while it is valid, preserving foreground access. It cannot prove the issuer of a raw historical refresh token. Such refresh tokens are **never sent or reused**, including upgrade fallback. They remain encrypted and are marked refresh-disabled; the secret-free channel projection displays `refreshBindingRequired` with one reconnection explanation. Expired/unknown legacy binding or issuer mismatch returns a binding-specific reconnect outcome, preserving ciphertext and authorization evidence. It does not mark a grant revoked or purge customer data. A concurrent new consent wins over conditional migration markers.

The existing staging connection can therefore require one new Google consent to obtain a bound refresh token; valid access need not be discarded first. After new consent, the migration banner clears. Ordinary bound access-token expiry still refreshes automatically and is not displayed as grant expiry. Gmail/Calendar storage/configuration paths are unchanged. Real independent-account, refresh, partial-consent, revocation and cross-lane acceptance remain required; offline tests are not provider proof.

## Independent YouTube gates and an official documentation conflict

Current `videos.insert` reference says unverified API uploads are not restricted to private viewing, whereas the official revision history still retains the July 28, 2020 private-lock rule without an identified superseding entry. Record this conflict rather than assert either project-specific outcome. Keep public-upload eligibility fail-closed until Google's applicable project decision and separately authorized provider acceptance resolve it. [Current upload reference](https://developers.google.com/youtube/v3/docs/videos/insert), [official revision history](https://developers.google.com/youtube/v3/revision_history)

OAuth verification, applicable YouTube compliance review, project public-upload eligibility and capacity remain distinct. The current audit guide gives defaults of 100 uploads/day, 100 searches/day and 10,000 general units/day, with audit required for more allocation. These are not the selected production project's approved quotas; inspect Console and retain the actual allocation and request decision. [Audit/quota process](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)

## Acceptance still required

- Public domain/client/callback binding and actual External/In Production state.
- Scope approval covering exactly the deployed workflow; independent audit/quota decisions where applicable.
- New ordinary-account connection and existing read-only upgrade using fresh bound refresh custody.
- Two independent accounts/workspaces plus Brand-channel identities, denial/partial consent, refresh and revocation.
- Separate standard/agentic consent and dispatch isolation before exposing any Google-calling AI tools.
- Real approved private upload/processing and, after required gates and explicit publication consent, native scheduling/publication/readback.

Validation receipt: focused synthetic credential-binding Python tests passed locally; broad integration/Node/browser/build checks are assigned to the root's cloud validation. No external configuration, credential provisioning, submission, account consent, content upload or publication was performed by this workstream.
