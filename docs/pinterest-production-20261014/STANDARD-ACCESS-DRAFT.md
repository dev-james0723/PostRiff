# Standard Access application package — prepared, not submitted

Checked2026-10-17. App1615884 **Trial access active**, native My apps card and available Upgrade form verified through Kynlo. **Standard NOT APPROVED. No pending application displayed.** Supporting owner-mail search found only14Oct Trial approval; do not treat that bounded search as a universal historical search. [Current receipt](evidence/public-release-preflight-20261017.json).

## Exact fields prepared for review

- App name / company display: Rafii / Rafii, preserving existing entries. Public policy identifies operator Au Hin Sing; no invented corporate entity.
- Website: **https://rafii.io** (form currently has old postriff-phase2-private.vercel.app).
- Privacy: **https://rafii.io/privacy** (form currently has old host/privacy).
- Audience: Creators and Businesses, existing checked values observed. Business accounts are the initial acceptance cohort; personal-account entitlement is conditional.
- Purpose text candidate:

> Rafii is a content workspace for creators and small businesses. Each customer connects their own eligible Pinterest account using Pinterest’s official Authorization Code OAuth flow. Rafii reads that account’s identity and authorized boards, helps prepare original image Pin drafts from customer-supplied content, and presents the image, title, description, destination link and selected board for review. Each Pin requires explicit approval. Approved Pins are published immediately or by Rafii’s durable queue at the chosen local time; Rafii reads back the provider Pin ID and destination before reporting verified publication. Optional analytics shows available impressions, saves, Pin clicks and outbound clicks for that customer’s own Pins, with successful, no-data and failed reads distinguished. Users can cancel pending jobs, pause automation, reconnect or disconnect. We do not request Pinterest passwords or session cookies, scrape Pinterest, train models on Pinterest data, provide competitor benchmarking, or sell Pinterest data. Trial demonstrations are labeled creator-only and do not assert public visibility. Public access remains disabled until Standard and production acceptance pass.

- Reporting: **candidate change from currently unchecked to checked only if submitting the tested optional own-Pin analytics use case**. Disclose that its release is separately gated; do not claim live analytics succeeded.
- Read-only scopes: user_accounts:read,boards:read. Image publishing plus read-back: user_accounts:read,boards:read,pins:read,pins:write. Optional native analytics: user_accounts:read,boards:read,pins:read. No ads/billing/boards:write/secret-board/comment scopes.
- Callback: https://rafii.io/api/oauth/pinterest/callback, already registered. No developer-console redirect modification proposed.

## Missing submission assets and substantive review

1. **Actual OAuth plus live API demo video**: dedicated recording agent assigned by the human. Form recommends MP4 under2GB and requires20–60fps, authentication and main Pinterest features. Kynlo’s4fps recorder cannot produce submission-compliant source footage; do not upsample to misrepresent capture. Full recording requires verified exact workspace/session (restore it only if the IDs differ), a new scoped private read-only window and human consent. The old window expired20:40:56Z and credentials remain erased. A read-only OAuth/identity/boards video can demonstrate real API activity without publishing; the mission’s complete Pin journey still needs approved writes and read-back.
2. Actual eligible board and two approved Pin operations. [Reviewable full previews](pin-previews/index.html) and [payload metadata](pin-previews/pins.json) are prepared; no board ID fabricated.
3. Public privacy/terms both HTTP200 rechecked. They still say draft/pending legal review and contain retention/transfer/jurisdiction placeholders. [Policy review candidate](POLICY-REVIEW-CANDIDATE.md) lists exact gaps; mere reachability is insufficient.
4. Pinterest Guidelines restrict storage and external sharing of API data. Account/token custody, essential Pin-ID receipts, retained native metrics and any AI/model egress need accurate disclosure and provider clarification; do not claim an exception to those rules. Provider-data-to-Agent/model gates remain closed. The full Developer/API Terms body did not load through official documentation, so compliance sign-off is incomplete.
5. Local analytics/expiry/scheduling repairs need delta remote checks before deployment. Current live baseline remains e2e5169f, not these repairs.
6. A real **non-app-owner business account in its own Rafii workspace** must pass [third-party acceptance](THIRD-PARTY-ACCEPTANCE.md). Owner success is not customer acceptance. Personal accounts need separate eligibility confirmation where PINNER_DATA_ACCESS_DENIED applies.

## Review and submission procedure

Present final20–60fps actual footage, its source/deployment/tier and redacted receipts, final field values, scopes and policy text to James. Do not upload files, modify saved app fields or click Submit upgrade request until separately approved. Do not create duplicate requests if the app later shows pending review. After an approved submission, capture the actual provider status and any decision; no review-time estimate.

The recording agent’s actual partial clip is preparation evidence only until the missing OAuth/API segments and format requirements pass. Its detailed receipt is maintained in standard-access-video/ and evidence/standard-access-video-20261017.json.
