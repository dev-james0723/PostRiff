# Rafii public YouTube acceptance evidence

2026-10-09. **Public launch incomplete. Zero new provider upload, native scheduling, public publication or Autopilot execution in this mission.** The machine-readable [acceptance matrix](PROVIDER-ACCEPTANCE.json) lists every requested scenario and its exact missing evidence. [CURRENT-STATE.json](CURRENT-STATE.json) separates this mission's observations from earlier receipts.

## Verified prior-source subset

Earlier same-day staging receipts prove one owner's read-only Google consent, immutable Channel ID `UC989xgvhGRS3PYEuH2-_iGw`, manual identity revalidation, bounded video-list reading and proactive refresh before token expiry. Sources are `public-rollout-20261008/STAGING-CONNECTION-ACCEPTANCE.json` and `STAGING-PROACTIVE-REFRESH-METADATA.json` in the acceptance directory recorded in the JSON matrix. They do not prove multiple independent account holders, expired-token recovery, upload/manage/Analytics grants or current production behavior. New strict client/lane binding deliberately requires a one-time reconnect for legacy refresh custody whose issuing client was not recorded.

The earlier formal 151-case matrix reported zero real passes and preceded those later staging receipts. Keep the later narrow receipts without converting them into complete formal creator acceptance. The earlier successful cloud run `hj3tjs65wn` validated its own candidate source; it does not validate the current reconciled release.

## Current mission state

The coordinating release agent observed creation of **Rafii YouTube Production**, project `rafii-youtube-production`, number `568838253270`. Project identity and owner-approved activation of YouTube Data API and YouTube Analytics API are verified. The production Data API allocation is100 uploads/day,100 search/day and10,000 Queries/day; exact Console labels/values are retained in `GOOGLE-QUOTAS.observed.json`. A higher-quota request has not been submitted or approved. Console activation and quotas were observed on October 8. On October 9 the current Chrome control path reports a request-header-policy error; configuration cannot continue until that session is reconnected. Production OAuth clients, consent branding/audience/publishing status and review submissions remain unconfigured; verified support/developer contacts and policy approval are still required. Existing `rafii-509720` (`81579135390`) remains a separate staging reference; its External/Testing status comes from the prior receipt.

The release agent observed `https://rafii.io` serving commit `bb4ca5aa`, deployment `dpl_AHypcnB4iRUv47iw3ZNQDEpuR4Wc`, with current Library preserved. This is the running baseline, not deployment of this integration. A validated release may deploy with unapproved YouTube public and agentic gates disabled. Production subsequently advanced to `65b1ea83` (PR #135 canonical-origin migration). The candidate preserves that newer code; current denied YouTube/Gmail callbacks land on rafii.io. This HTTP observation does not prove Google registration or consent. PR #136 was subsequently merged and deployed, with its exact-SHA read-only production smoke passing. PR #137 then advanced production to 94ca0dbd; the current candidate starts from that commit and preserves OpenUI. Concurrent draft PR #138 adds broader consent-generation/privacy handling but is not deployed and an earlier main CI failed on a fixture; its corrected head awaits fresh CI; it must not be counted as verified production behavior. This phase reserves migration 105 because live enrollment migration 103 and the separate Library candidate 104 already exist. The release owner records the final candidate, migration, CI, merge/deployment and exact-SHA smoke separately.

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Production OAuth, public non-tester onboarding | BLOCKED | New project only; clients and approved scopes absent |
| OAuth verification, YouTube audit, quota request | NOT SUBMITTED | Draft packets exist; no application IDs or provider confirmation |
| Current production daily upload allocation | VERIFIED DEFAULT: 100/day | Actual dedicated-project Console allocation observed; higher quota and public-upload eligibility remain unapproved |
| Read-only connection and proactive refresh | VERIFIED, prior source | One owner's earlier staging grant; not current v2 production acceptance |
| Separate standard/agentic custody and dispatch | IMPLEMENTED BUT UNVERIFIED | Synthetic regression; no actual agentic client/grant |
| Large-video private storage | BLOCKED | Verified Free 50 MB global ceiling and 50000000-byte private bucket; owner billing decision pending |
| Private upload, processing and native scheduling | BLOCKED | Write consent, approved disposable asset and provider resources absent |
| Public publishing and Autopilot execution | BLOCKED | Relevant provider approvals, policy/asset consent and actual provider receipts absent |
| Independent-account isolation at provider | BLOCKED | Multiple genuinely independent holder consents absent |

Real acceptance records must identify deployment SHA, workspace/connection, exact immutable Channel ID, approved action/policy, provider method/result, relevant timestamps and redacted receipt. Keep tokens, authorization codes/state/verifiers, resumable session URLs, customer media and unrelated private details out of evidence. Mark an attempted but unverified response as such. A successful request, private processing or accepted future schedule is not a verified public publication.

Current read-only production observation: canonical and protected health both report `c77774788bf938a08785a3eb544be9897f9e7af3`, deployment `dpl_4soM3871evYy4p6bKCo1VfACheoP`, on2026-10-09T07:01:56Z;6/6 public checks passed. This verifies transport/version/protection only. Three exposed automation bypasses were revoked and the replacement is loaded; a separate Stripe bypass still requires the correct sandbox context. New publishing gates remain off and provider acceptance is still unexecuted.

Thumbnail write acceptance and resource URL observation are separate from image-content verification. YouTube may retain stable thumbnail URLs after a replacement; the new receipt keeps `verified=false`/`contentVerified=false` and reports resource observation without retrying an accepted write. Actual replacement image content remains unverified.

Current candidate cloud validation: JCB `cknkhlfd0c`, base `4a0bd786ac43f50de9f00c4fbb63d6d65e7434ba`, source fingerprint `8cb2e295de73dbde3c0fbf2d344f8fdbc87204cbdec8f7cb903cc6cb80c3d574`;499 Python tests,845 Node tests,10 PostgreSQL modules, build and synthetic Chromium1440/390/320 passed. This includes Analytics project/day/minute concurrency and truthful thumbnail receipts. New phase Google provider acceptance calls remain0.
