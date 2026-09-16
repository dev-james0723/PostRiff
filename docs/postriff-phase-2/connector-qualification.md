# Connector qualification

Checked 2026-09-14. The existing local James Au Studio LinkedIn identity is connected with `openid profile email w_member_social`, an active token and publishing readiness. Instagram credentials exist, but `@jamesaucreates` remains not connected. This check did not modify either account or publish content.

| Contract | Qualification achieved | Current execution |
|---|---|---|
| LinkedIn member text / one decoded image | Live local identity and `w_member_social` capability present; image initialize/upload/status plus post/reconciliation candidates tested | Local broker is publish-ready; token is not migrated to hosted runtime and no image operation was executed in this Phase 2 run |
| Instagram professional single-image post | Container/status/publish/evidence candidates tested; intended username and OAuth client are present | `@jamesaucreates` is not connected; no identity, professional account type, token or live media operation is verified |
| Threads and other channels | Native drafting/export only | No connector or publishing claim |

LinkedIn identity and local publish capability are live-provider verified in the separate owner-only Studio broker. Hosted token custody, image submission/publication/recovery and cloud operation are not achieved. Instagram remains unconnected. Browser login and callback completion never confer these levels by themselves. App configuration, identity, account type, scopes, expiry, revocation, capability version and last check remain separate fields.

## Official evidence and limits

[LinkedIn Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-03) documents member posting and restricted `r_member_social` reads. A successful create/request ID is acceptance evidence, not independent publication verification. The candidate requires an explicitly supplied supported API version; it does not assume write access grants read/reconciliation access. The test version is a fixture, not live qualification.

[Meta's official Instagram collection](https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00) was found in current official search results, supporting professional-account publishing and the `instagram_business_content_publish` permission. Direct Meta/Postman page retrieval failed. Therefore the proposed Graph version, image format/alt-text handling, account access and limits require a fresh official-doc/account check before any live request. No third-party tutorial supplied production qualification.

Local preflight uses conservative versioned limits: LinkedIn 3000 characters; Instagram 2200 characters, one JPEG rendition, 4:5–1.91:1, and an 8 MB upload cap. It rejects unsupported video rather than pretending to validate/publish it. These limits are a local contract, not a claim that current provider behavior has been verified.

## Failure/recovery fixtures

Success, denial, expiry, accepted, delayed, failed, rate-limited, timed-out, duplicate, uncertain, malformed and capability-loss cases are deterministic. The browser demonstrated one verified fixture, one failed fixture and one uncertain fixture with separate receipts. [Outcome evidence](evidence/partial-outcomes-desktop.png). An uncertain result never automatically creates a second submission.

Remaining integration includes live OAuth state/PKCE, token persistence/refresh/revocation, exact identity/capability probes, credential-free hosted image delivery, provider-specific live reconciliation and an enabled remote social worker. The complete request contracts are implemented locally, but neither provider has been exercised end to end by the hosted application.
