# Google OAuth Brand Approval — cross-project integration receipt (2026-10-11)

**Status: documentation reconciliation only; no Cloud credential changes, OAuth consent, provider submissions, legal attestations or YouTube publication.** This receipt supplements, not supersedes, the separate YouTube submission packet and release gates. See [SUBMISSION-TRACKER.json](SUBMISSION-TRACKER.json).

## Primary provider evidence

On **2026-10-09 07:31:31 UTC**, the owner received an automated Google Third Party Data Safety Team message, subject **[Do not reply] OAuth Verification Response**, expressly stating approval of **OAuth App Brand Verification** for **Google Cloud project `postriff` (number `692391842023`)**. The original message is retained in the owner's personal Gmail. Do not copy mailbox content, message URLs or private mailbox identifiers into this public repository.

The message states: new scopes or consent-screen changes can require verification, and the approval cannot be inherited for unapproved sensitive or restricted scopes. It does **not** list approved sensitive/restricted scopes, identify all client IDs, authorize YouTube compliance, grant extra quota, or approve `rafii-youtube-production`. No provider case/application reference was present in this message; **do not invent one**.

Google references: [OAuth verification overview](https://support.google.com/cloud/answer/13463073), [scope review](https://support.google.com/cloud/answer/15549135), [changes to approved app](https://support.google.com/cloud/answer/13464018), [brand approvals](https://support.google.com/cloud/answer/16868008).

## Project isolation matrix

| Google Cloud project | Verified purpose/configuration | Brand / sensitive scopes | YouTube audit / quota |
| --- | --- | --- | --- |
| **`postriff`**, `692391842023` | A pre-existing Google OAuth project; **active Google Sign-In, Gmail/Calendar and historical YouTube client mapping still needs exact production config + Cloud Clients readback**. Client names, approved scope set, redirects and publishing state have not been revalidated. | **Brand Approved**, provider message 2026-10-09. **Sensitive/restricted approvals not established by this evidence**. No automatic transfer to any other project. | Not evidence for the dedicated YouTube production project. |
| **`rafii-youtube-production`**, `568838253270` | Dedicated YouTube Data/Analytics project. 2026-10-10 [PR #162](https://github.com/dev-james0723/PostRiff/pull/162) OAuth readback reports External / In Production, verified `rafii.io` domain and branding, four declared scopes, **two separate Web clients** (Standard and AI-designated Agentic), each with **only** `https://rafii.io/api/oauth/youtube/callback` and no JavaScript origins. Actual current production credential selection not reverified. | **Verification required; OAuth verification NOT SUBMITTED in latest packet**. No provider approval for the four requested scopes evidenced. Console on 2026-10-10 also showed an unverified new-user cap. | **Compliance audit NOT SUBMITTED; quota extension NOT SUBMITTED; public upload eligibility UNVERIFIED**. Enabled APIs and configured default quotas are not approvals. |
| **`rafii-509720`**, `81579135390` | Dated staging reference (2026-10-08): External / Testing and a separate staging Web client with `https://rafii-consumer-staging.vercel.app/api/oauth/youtube/callback`. Not a verified production replacement. | No current scoped approval evidence; revalidate clients and requested scopes. | No approval inferred. |

Other relevant Google projects have not been exhaustively inventoried. A project ID/name is never an OAuth client ID; no inference from an ID suffix establishes issuer identity.

**Evidence precedence:** owner-held 2026-10-09 provider email for `postriff` brand, 2026-10-10 dated merged Google Console findings in [OAUTH-VERIFICATION.md](OAUTH-VERIFICATION.md) for `rafii-youtube-production`, 2026-10-11 Vercel/GitHub deployment readback for shipped code. Earlier 2026-10-09 [CURRENT-STATE.json](CURRENT-STATE.json) and [YOUTUBE-AUDIT.md](YOUTUBE-AUDIT.md) contain then-correct but superseded “not configured” project text; the code receipt from PR #162 is newer. None proves 2026-10-11 production secrets or fresh end-to-end account consent.

## Rafii scopes, not interchangeable approvals

Only four dedicated YouTube production scopes were recorded in the 2026-10-10 Console acceptance:

- `youtube.readonly`: identify/revalidate the intended immutable channel; read its own channel/video data.
- `youtube.upload`: owner-authorized original video upload, initially private.
- `youtube.force-ssl`: broad video/caption/comment/playlist/metadata management, requiring specific downstream operation approval rather than implied blanket deletion.
- `yt-analytics.readonly`: non-monetary Analytics reports; not earnings, memberships or `youtubepartner`.

These are **declared/requested** scopes, not **approved** scopes. Live scope classifications must be read from the production project's Data Access view. Do not add unused Gmail, Drive, revenue, CMS, or expanded channel-wide scopes to simplify a review. Any Google Sign-In `openid email profile` flows and Gmail/Calendar clients must be audited independently, by exact effective project, client ID fingerprint, callback and granted scope — never by hostname alone.

## Production deployment / client preservation

2026-10-11 Vercel readback: `https://rafii.io` is a verified domain on project `postriff-phase2-private`. Its production deployment is `dpl_BUZ9hDn7pY8KwWTV2paXjtbuqv9T`, SHA `b7b9b3ee94f89a80b1d80826226584d214b17847`. GitHub ancestry check confirms this SHA includes [PR #162](https://github.com/dev-james0723/PostRiff/pull/162). This verifies deployed **source**, not active Google credential configuration.

The authenticated Vercel environment-variable listing returned **403 Forbidden on 2026-10-11**. Accordingly, actual `POSTRIFF_OAUTH_YOUTUBE_STANDARD_CREDENTIAL_SOURCE`, `POSTRIFF_OAUTH_YOUTUBE_PENDING_*`, `POSTRIFF_OAUTH_YOUTUBE_LEGACY_*`, `POSTRIFF_OAUTH_YOUTUBE_AGENTIC_*`, `POSTRIFF_OAUTH_YOUTUBE_CALLBACK_ORIGIN` and `POSTRIFF_YOUTUBE_PUBLIC_BASE_URL` **were not read or changed**. Never expose actual secrets or whole client IDs in tracker, logs, screenshots, docs, PRs or review videos.

PR #162 provides code to select a dedicated Standard pair, preserve exactly matched historical encrypted v2 YouTube **read-only** grants through a restricted legacy issuer, and reject cross-client/agentic binding and mismatched redirects. It does not migrate historical Google refresh tokens to a new issuer. **Do not delete the old OAuth project/client or rotate credentials** until production mapping, legacy read-only refresh and holder-authorized reconnection acceptance are completed. Maintain existing Gmail/Calendar OAuth configuration and any active Google Sign-In flow. Changing `NEXT_PUBLIC_APP_URL` alone never registers a Python Google redirect.

**Fail-closed release:** `POSTRIFF_YOUTUBE_CREATOR_ENABLED=0`, `POSTRIFF_YOUTUBE_AGENTIC_ENABLED=0`, fleet and public publishing **OFF**. These are intended gates in merged source/receipts; production values were not independently re-read on 2026-10-11. Avoid claims that a disabled feature has been tested against real Google accounts.

## Submission packet continuity

Reuse, don't duplicate, these files: [OAUTH-VERIFICATION.md](OAUTH-VERIFICATION.md), [YOUTUBE-AUDIT.md](YOUTUBE-AUDIT.md), [QUOTA-EXTENSION.md](QUOTA-EXTENSION.md), [OWNER-FIELDS.md](OWNER-FIELDS.md), [REVIEW-DEMO-SHOTLIST.md](REVIEW-DEMO-SHOTLIST.md) and [GOOGLE-QUOTAS.observed.json](GOOGLE-QUOTAS.observed.json).

1. **Google OAuth verification, dedicated project only:** current Console `Branding / Audience / Clients / Data Access / Verification centre` readback, exact four minimum scopes and classifications, independently reviewed `https://rafii.io/privacy`, `https://rafii.io/terms`, deletion and operator/contact disclosures. Prepare a **truthful English demo** with actual consent/client ID in reviewer-visible address bar and deployed sensitive functionality. Reviewer/test account only by owner-approved sharing. Submit the exact scoped request using this project's Console after prerequisites; record project, scope list, provider confirmation, timestamp, case ID and decision separately. Do not resubmit the already-approved `postriff` brand because of an unrelated YouTube review.
2. **YouTube compliance audit:** separate [official form](https://support.google.com/youtube/contact/yt_api_form), actual operator/applicant identity/address, audited endpoint list and review account/access, validated policy/legal statements, real feature evidence and owner-accepted form attestations. The production project number is `568838253270`; no submission exists yet in the verified record.
3. **Quota extension:** dated default buckets only: 100 uploads/day, 100 search/day, 10,000 general units/day, separate Analytics defaults. [QUOTA-EXTENSION.md](QUOTA-EXTENSION.md) contains **forecasts**, not actual usage or owner-approved requests; submit numbers only after owner approves measured/labelled forecast and audit requirements. Do not treat requests, approvals or future public eligibility as interchangeable.

YouTube documentation for restrictions on public uploads has conflicting older/current text noted in the existing packet. Independently confirm project-specific requirements and owner-approved real publication eligibility; do not bypass the existing public publishing fence based on one help-page sentence.

## Required acceptance before any OAuth credential or launch switch

- Read-only Vercel **production** env key-to-client/project fingerprint mapping, including existing Google Sign-In and Gmail/Calendar clients, original Standard and separate Agentic clients. Do not print secret values.
- Google Cloud project/client inventory readback for `postriff`, `rafii-youtube-production`, `rafii-509720` and other active projects; exact client identity, registered callbacks, scopes and approval state for each.
- Owner-authorized existing Google Sign-In (including returning user) and historical Standard **read-only refresh** acceptance, and separate fresh Standard/Agentic consent with exact callback and isolated channel ID; ensure revocation/reconnect cannot silently cross issuers or tenants.
- A real disposable original review video and dedicated reviewer workspace with consent, privacy/terms/operator facts independently confirmed, demo/redaction and reviewer instructions tested before uploading any evidence externally.
- Google and YouTube **real** submission acknowledgement/case references; reviewer decisions and actual provider-backed acceptance recorded individually. No legal representation, demo URL, approval or success signal may be simulated in a public tracker.

**Outstanding owner/provider blockers:** production env read permissions; remaining Cloud-project scope/client map; actual operator/contact/legal facts and owner attestations; independently consenting test accounts and authorized disposable media; real recorded demonstration/reviewer access. Until resolved: **no verification submitted, no public YouTube rollout, no forced Google reconnect**.
