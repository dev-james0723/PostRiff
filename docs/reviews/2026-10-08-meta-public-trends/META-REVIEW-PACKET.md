# Meta public discovery review packet

Date: 2026-10-10. Execution state: **local implementation and synthetic validation candidate**.
Public provider approval, live third-party reads, production database admission and source activation remain separate gates.

## Current app evidence and missing gate

The parent task's live browser inspection identified Rafii Meta App **1401844428820097** as **Published**. Its new App Review requests were **NOT SUBMITTED**. The observed use cases covered Instagram and Pages, with owned Instagram business/Page permissions; no Threads use case was listed. Published mode does not establish approval for any public operation in this packet. App/business ownership, the intended HINSINGAU identity and proposed Rafi Page remain to be verified independently. This packet does not submit a request or alter the app.

Current truthful status for each operation: `BLOCKED_PROVIDER_REVIEW`. No genuine approved, non-owned third-party response was available to this implementation. Synthetic fixtures are labeled synthetic and must never appear as live results in a reviewer recording or customer UI.

## Three exact implemented operation paths

| Public operation | Pinned request path | Population and limits |
| --- | --- | --- |
| Threads `keyword_search` | `GET https://graph.threads.net/v1.0/keyword_search` with bounded `q`, `search_type=RECENT` or `TOP`, fixed fields, optional validated cursor | Public keyword sample returned by the reviewed Threads operation. Ranking is not prevalence, engagement or a complete count. |
| Instagram `hashtag_discovery` | `GET https://graph.facebook.com/v24.0/ig_hashtag_search` with the reviewed professional `user_id` and hashtag, followed by `GET https://graph.facebook.com/v24.0/{returned_hashtag_id}/recent_media` | Public hashtag sample available to a Facebook Login-linked professional account. Enforce at most 30 distinct hashtags per account across a rolling seven days, plus a separately reviewed request budget. |
| Facebook `page_public_posts` | `GET https://graph.facebook.com/v24.0/{reviewed_page_id}/posts` | Posts from the exact eligible, reviewed third-party public Page. Private, age/region-restricted or unreviewed Pages, personal feeds and Groups are excluded. |

The current candidate pins Facebook Graph `v24.0`; supported version and fields must be rechecked during actual review. The Facebook Graph version must exactly match the server capability and independent App Review/diagnostic records. Threads uses its own `v1.0` API, never the Facebook version by substitution. No provider-supplied next-page URL is followed. Authorization belongs in the supported credential header, never a URL, job payload, log, model input or UI receipt. Separate `profile_posts` and Business Discovery operations are follow-on review work, not implemented coverage in these three paths.

## App Review features are separate from OAuth scopes

| Operation | Current token evidence | Independent human App Review evidence | Not sufficient |
| --- | --- | --- | --- |
| Threads keyword | Correct Threads app/user, Threads Login, `threads_basic` and `threads_keyword_search`, valid current diagnostic | Exact app and keyword operation approval, including the requested scopes and API version | `threads_basic`, publishing, own insights, developer role, or Published mode alone |
| Instagram hashtag | Facebook Login user token, bound linked Page/professional IG account, `instagram_basic` and exact approved required token scopes | Instagram Public Content Access **feature**, recorded separately from OAuth token scopes | Existing Page-free Instagram Login or `instagram_business_basic` owned analytics permission |
| Facebook public Page | Correct app/system-user token, exact app/subject/account, current verified OAuth scopes where applicable | Page Public Content Access **feature**, approved Page IDs, public/unrestricted eligibility and reviewed version | `pages_show_list`, managed Page role or `pages_read_engagement` by itself |

Never fabricate feature names as though the OAuth token debugger granted them. The capability/source policy may name a required feature for operation admission, but the proof has separate `verified_scopes`, `approved_scopes` and `approved_features` fields.

## Diagnostic transport is explicitly unresolved

[Meta's official Threads Postman diagnostic example](https://www.postman.com/meta/threads/request/34203612-e9a7f46e-e48c-4987-a203-22fb25a4b604) documents `GET /debug_token` with `input_token` in the query. A supported POST-body or other secret-free-URL diagnostic variant was **not verified** during this work. The [Graph debug-token reference](https://developers.facebook.com/docs/graph-api/reference/debug_token/) was inaccessible during the public documentation check. An unverified protocol is not implemented as though it were supported.

`meta_control.py` therefore makes **no diagnostic network request**. Its declared state is `blocked_safe_diagnostic_transport_unverified`. Existing owned OAuth helpers are not reused for public verification, particularly where they put credentials in URLs or use the wrong Threads API version. The import path below is an operator-reviewed exception boundary, not an automated verification claim.

## Service-only operator evidence import

`MetaPublicControlService(store, app_ids=..., evidence_reader=..., clock=...)` receives its trusted app allowlist and evidence reader from server configuration. There is no browser, agent-job or public HTTP registration endpoint. The parent web service may expose safe status and an authenticated owner/editor revoke action only.

`register_connection(policy=..., token=..., diagnostic_ref=..., app_review_ref=..., consent_ref=..., selection=..., quota_rules=...)` resolves three independent private records. A browser-supplied `verified=true`, ready policy, arbitrary `ReviewProof`, screenshot claim or client JSON cannot provide those records.

Required trusted records:

1. `meta_token_diagnostic`: raw provider diagnostic response, capture time, private artifact SHA-256 and named operator, exact app/provider/operation/version/login path/workspace/account, inspected subject and SHA-256 fingerprint of the actual secret token. The identity envelope records the account inspected by the operator. For Instagram it also binds the Facebook subject, linked Page and business/creator account type. The import independently checks the raw response's app ID, `is_valid` boolean, token type, current granted scopes, subject, token/data-access expiry and future issuance. No raw diagnostic/identity response is persisted in the grant.
2. `meta_app_review`: separate app/provider/operation/version, `status=approved`, private review artifact hash, named human reviewer, review/expiry timestamps, exact approved OAuth scopes, approved features, eligible Page IDs, Page restrictions and reviewed quota reference/limits. An app's Published status is not this record. The evidence repository must be operator-controlled; the importer cannot independently prove that a human attestation is authentic.
3. `meta_public_consent`: separate current `status=granted`, exact app/workspace/account/provider/operation/token fingerprint, consent/expiry timestamps, private evidence hash and reviewer. No generic platform connection or source-wide consent is substituted.

Both the independent App Review record **and** consent record must also bind `source_policy_id`, `source_policy_version`, `scope_key`, provider and operation, the exact `rights_digest` (SHA-256 of canonical source-policy rights JSON), and an integer `max_retention_seconds`. The requested retention cannot exceed either ceiling. Changing LLM processing, raw/metric storage, derivative rights, cross-source combination, sharing, right expiry or audience scope changes that digest and requires newly bound operator evidence. A new policy version cannot reuse evidence for the old version. Token/scope success supplies none of these processing rights.

Only after `ReviewProof` validation does one transaction encrypt the token with the existing `CredentialVault` under `meta_public_threads`, `meta_public_instagram` or `meta_public_facebook`, then insert the immutable grant. The raw token, diagnostic response and raw evidence are not logged, returned, queued or stored in the grant. Operator evidence artifacts stay in approved private custody; do not commit them or upload them to a model.

An operator may additionally record `third_party_source_ids` (at most 20 exact provider-prefixed post identities) and `third_party_evidence_ref` on that same approved private App Review record. The reviewer must inspect the genuine public records and confirm that they are not owned by the connected account, retaining the evidence artifact under that reference. These optional fields are copied only from the trusted evidence repository into immutable grant selection; caller/browser selection cannot set them. Missing attestation leaves third-party status unverified. Runtime qualification must require both a real `provider_response` and an exact listed source identity. A synthetic response never becomes live, and no unavailable author is invented. This is a named human attestation boundary, not independent automated ownership detection. Enrollment still does not activate a source.

The current conservative import rejects an absent, expired or zero/non-expiring token expiry rather than inventing a validity horizon. Supporting a provider's indefinite token semantics requires an explicit reviewed rule and evidence, not silently treating zero as valid forever.

A diagnostic proof lasts **at most 15 minutes** from capture and is shortened by token/data-access, review, consent and policy expiry. Renewal uses `previous_authorization_id`, a strictly newer diagnostic and a new source-policy version; it inserts a new grant/credential, revokes the old grant and erases its credential in one transaction. Operator revalidation remains necessary while automated diagnostic transport is unresolved.

Enrollment returns `verification_method=operator_evidence_import` and `activation_state=awaiting_live_public_read`. It never enables a source, creates a job or certifies live coverage. Separate controlled canary acceptance must establish genuine third-party data before customer activation.

## Reviewer use cases and UI recording

Use a real permitted Meta reviewer/test account and a real authorized Rafii workspace. Verify current app domain, provider-specific consent screen and exact callback URI in server configuration and Meta Console before submitting. Do not reuse an owned Instagram callback or stale hostname by assumption. The app/business owner must approve any external App Review submission, business verification or changed permission request.

For each operation, record these steps separately:

1. Sign in to Rafii and open Trends → Public Sources. Show the operation's current permission/review status and named sampling population. Before approval, the UI must show unavailable/blocked coverage, not sample fixture cards presented as public data.
2. Show the correct independent provider consent path. For Instagram hashtag discovery, explain the linked professional account/Page requirement without changing the existing Page-free owned Instagram integration.
3. With actual review and current token/consent evidence admitted by the operator, choose one bounded keyword, hashtag or previously reviewed public Page. Obtain separate authorization for the live canary. Show one real non-owned third-party public record returned by the precise operation.
4. Show its canonical provider ID/link, original timestamp where available, retrieval time, workspace, operation, policy revision, retention boundary, provenance and exclusions. A successful HTTP response without an admitted stored observation does not pass.
5. Inspect the stored observation through the authorized end-user Trends UI. Missing author or native metrics display unavailable, never zero. Show honest empty, expired, quota-exhausted and provider-denied states. Do not demonstrate private feeds, personal accounts or research-only Meta Content Library access.
6. Revoke as an owner/editor. Verify further acquisition, result projection and model processing fail closed, then exercise the reviewed retention/deletion flow. A viewer or another workspace must not revoke or access the connection.
7. Repeat with an ordinary authorized user, not only a privileged app-role account. Capture the exact deployed SHA, policy/grant IDs and acceptance time in the private receipt without secrets.

## Retention, revocation and JEV

Each operation needs independent explicit rights for retrieval, raw storage, metric storage/derivation, excerpt/link display, LLM processing, combination and cross-workspace sharing. Unknown rights deny the action. Do not infer AI rights from public visibility or OAuth success. Respect source expiry, deletions, workspace deletion, token revocation and shorter contractual retention. Do not introduce cross-workspace public-content caching by default.

Revocation takes the shared trend trust fence exclusively before changing the grant and encrypted custody; model egress/reads hold the corresponding shared fence. Grant validity and current source rights are checked again before I/O and commit. Revoked or expired evidence must not appear through descendants or JEV evidence packs. A stored ciphertext digest binds the grant to the exact encrypted credential, so token replacement cannot silently preserve an old approval.

JEV is an optional semantic evaluator of admitted evidence. It does not fetch Meta posts, fill in absent metrics, manufacture trends, estimate unsupported whole-network prevalence, or replace native measurements with a generic score. Counts/velocity/lifecycle require comparable measured windows. JEV outputs must be labeled interpretation-only with evidence references and qualification; its answer probability is not a calibrated real-world outcome probability. Real model egress additionally requires current LLM-processing rights, entitlement and bounded authorized spend.

## Acceptance ledger

| Gate | Current evidence |
| --- | --- |
| Local control/adapters and synthetic negatives | Implementation candidate; record exact validation receipt separately |
| App Published | Parent live browser observation for app 1401844428820097 |
| Public App Review | **NOT SUBMITTED / not approved** in current inspected evidence |
| Current public token diagnostic + consent | Not imported or exercised on a real credential |
| Genuine third-party live read on all three networks | **Not performed; blocked** |
| Stored/pipeline-processed genuine observations | **Not performed** |
| Real end-user public coverage | **Not verified** |
| Live JEV over Meta public evidence | **Not performed** |
| Production migration, enablement or deployment | **Not performed by this control-plane work** |

Code, synthetic tests, app publication, an owned analytics connection and a draft review packet cannot convert any blocked row into a pass.
