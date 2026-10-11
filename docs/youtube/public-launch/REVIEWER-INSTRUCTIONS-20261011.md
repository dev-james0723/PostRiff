# Rafii Google / YouTube Reviewer Instructions — Candidate, not yet sendable

Prepared **2026-10-11** from the production source, merged PR #162, dated Google Console receipts and currently available official forms. **NOT SUBMITTED. NO REVIEWER ACCESS OR REAL DEMO HAS BEEN PROVISIONED.** This is a field-ready English draft with explicit unverified items; remove blockers only with matching real evidence. Never submit this file verbatim while any REQUIRED item below remains unresolved.

## Application and project boundary

- **Public app / brand:** Rafii — `https://rafii.io`.
- **Google Cloud project for this application:** `rafii-youtube-production`; project number `568838253270`.
- **Google OAuth client type:** Web application; **two distinct registered clients**, one for direct Standard connection and one separately AI-designated Agentic connection. Never substitute credentials or proof from `postriff` / `692391842023`.
- **Authorized redirect (both YouTube clients):** `https://rafii.io/api/oauth/youtube/callback`. No approved JavaScript origins recorded on 2026-10-10 Console snapshot.
- **Scope set:** `https://www.googleapis.com/auth/youtube.readonly`, `https://www.googleapis.com/auth/youtube.upload`, `https://www.googleapis.com/auth/youtube.force-ssl`, `https://www.googleapis.com/auth/yt-analytics.readonly`.
- **Availability:** Rafii supports owner-directed YouTube creator workflows in code; **creator/agentic/fleet/public release are disabled** pending independent review and owner-granted real acceptance. Do not claim these can currently be demonstrated end-to-end.
- **Public policy pages:** `https://rafii.io/privacy`, `https://rafii.io/terms` (both HTTP 200 on 2026-10-11). **BLOCKED**: live documents explicitly say **Draft — pending qualified legal review** and mention placeholders.

## Reviewer's proposed safe test path (enable only in an approved review environment)

1. Sign in to an **owner-provisioned, disposable reviewer workspace**: **REQUIRED: actual account invitation/SSO instructions and test credentials delivered privately by the owner, not in this file.** Do not disclose customer credentials. Identify the exact installed deployment/SHA to reviewers.
2. Open **Channels → Connect → YouTube**, select the Standard direct account authorization. In the Google consent URL the submitted client ID must be shown to the reviewer; capture its exact correspondence with the dedicated project's Standard client without logging secrets.
3. Select an independently authorized **test Google account** and its immutable intended YouTube Channel ID; demonstrate read-only channel selection and revalidation. Do not represent one channel's token as permission for another.
4. Request upload incrementally only for the feature being tested. Use an **owner-approved disposable original** (REQUIRED: actual media provenance, file hash and owner's explicit approval) and an authorized private test upload. Distinguish upload API success, video-processing confirmation, YouTube Video ID and visibility readback. Do not set a live public or unlisted visibility absent separate explicit owner/test-publication approval and verified project eligibility.
5. Request additional management or Analytics scopes only when demonstrating the matching implemented feature. Show owner-approved metadata/schedule/caption/comment/playlist management and non-monetary video/channel reports **only if their deployed functionality can genuinely be exercised**, with provider readback. Omit, rather than pretend to demonstrate, an unsupported feature.
6. For AI workflows, show an **independent** Agentic client consent by the workspace owner, an exact reviewable policy with chosen channel, content source, schedule, limits, pause/revoke and intervention. **REQUIRED: separately authorized Agentic test consent** and feature-specific acceptance before claiming an autonomous outcome. Agentic is off today.
7. Test access denial across unrelated workspaces, disconnect/revocation and in-product deletion controls with approved disposable accounts. Protect unrelated users, secrets and personal media.

### Reviewer-visible video plan

Follow [REVIEW-DEMO-SHOTLIST.md](REVIEW-DEMO-SHOTLIST.md), shots 1–13, as the feature-to-scope matrix. The **actual** truthful English capture must show the deployed app's branding, exact Google consent/client identity, narrow granted scopes, owner-driven operations, results, deletion and AI consent only where truly executable. Redact tokens, one-time authorization codes, PII and private unrelated accounts. **Demo URL: NOT CREATED**; no video, demo upload or publication completed in this documentation update.

If the release gate prevents real testing, communicate the blocker to the reviewer and delay the claim or scope. Synthetic API fixtures, source tests, preview cards and empty video links are not proof of actual Google authorization or uploading.

## Data use and custody (draft for reviewed app disclosure)

Rafii receives only OAuth scopes a workspace owner elects to grant for connected channel workflows; stores grants in protected encrypted server custody, enforces workspace/channel binding, and applies separate operation approvals and deletion/revocation paths. Legacy read-only refresh grants may remain bound to the original Standard issuer; a new Standard/Agentic client never inherits refresh credentials or scopes by migration. There is no Gmail/Calendar approval through this YouTube project and no cross-project inheritance from the `postriff` Brand Verification decision.

Do not submit claims about controller identity, lawful basis, retention, legal jurisdiction, third-party processor disclosures or deletion effectiveness unless independently checked against the **final legally reviewed and deployed** policy and actual product.

## Submission workflow / confirmation receipts

**Google OAuth:** Review project's `Branding → Audience → Clients → Data Access → Verification centre` in the actual Console; inspect classification for all four scopes. After owner confirms legal documents, minimum scopes, consent, reviewer access and real English demo, submit scoped verification through that project's Console. Record provider application/case ID, UTC timestamp, exact project + scope snapshot, and official decision only on receipt.

**YouTube compliance audit / higher quota:** Use the [official Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form) for project **568838253270**. Reference [YOUTUBE-AUDIT.md](YOUTUBE-AUDIT.md) and [QUOTA-EXTENSION.md](QUOTA-EXTENSION.md) for endpoint list and separate forecast figures, but obtain the operator's true legal identity, address, contact, entity status, reviewed disclosures, reviewer access and explicit required attestations. Do not claim the proposed 4,000 uploads/day or 1.5M general units/day is an approved Google allocation or an owner-approved forecast.

**Confirmation record template (fill only after official action):**
- Project ID and project number: `PENDING READBACK`.
- Workstream (Google OAuth scopes / YouTube audit / quota extension): `NOT SUBMITTED`.
- Actual submitted scope snapshot, submission timestamp UTC, application ID/case reference: `PENDING PROVIDER RECEIPT`.
- Reviewer video URL and authorized viewer list: `PENDING GENUINE OWNER-APPROVED VIDEO`.
- Official approval status/approved scope/quota and decision timestamp: `NONE`.
- Human form attestations: `PENDING OWNER`.

## Submission blockers as of 2026-10-11

The owner must confirm legal/operator/contact facts and qualified review of the still-draft privacy/terms; actual Vercel production OAuth client-to-project mapping must be read with appropriate permissions (environment list returned 403); remaining Cloud project clients/scopes need live readback; each distinct account holder must provide OAuth consent; a disposable test asset, reviewer workspace and actual feature-correct demonstration must be authorized. No evidence of these human/provider actions is present in this reconciliation. Do not weaken flags or backfill fake success receipts to bypass them.
