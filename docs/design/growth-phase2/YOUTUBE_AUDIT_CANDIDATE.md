# YouTube audit preparation — candidate, not submitted

Prepared 2026-09-27. No Google account, project, quota, scopes or production settings were changed. This branch supports native Threads/Instagram outcome observations and Threads comment analysis only; it does not add YouTube analysis.

The current [YouTube policy guide](https://developers.google.com/youtube/terms/developer-policies-guide) directs developers to obtain specific approval before producing additional derived metrics or retaining data beyond standard limits. The [derived-metrics policy](https://developers.google.com/youtube/terms/derived-metrics-policy) describes the conditional exception for accepted analytics clients. Keep the YouTube gate closed until a written decision covers the precise use case and retention.

Candidate use-case description for owner review:

> Rafii helps individual creators plan and review their creative practice. We propose showing authorized creators native outcomes of their own published videos beside advice saved before publication. Creator-specific comparisons would be clearly identified as Rafii-generated associations, with source metrics and observation windows visible. They would not be presented as YouTube scores or causal predictions. We seek explicit review of any derived comparison and its storage before enabling that behavior. This is a proposed extension; the current Phase 2 implementation does not perform it.

The current [audit form](https://support.google.com/youtube/contact/yt_api_form?hl=en) requires organization/contact details, project numbers, the client URL, privacy policy, access for reviewers, use cases, quota information and supporting evidence. The owner still needs to supply/verify these items before a submission can be prepared for final approval:

- Legal applicant and authorized contact; production client and public privacy-policy URLs.
- Exact Google Cloud project number, current quota, endpoint inventory and observed/requested daily volume. Do not invent usage or request a higher quota without a calculation.
- Requested derived comparisons, inputs, formulas, labels, example screens and exact retention periods; separate native counts from Rafii-generated results.
- Data inventory covering OAuth grants, collection, third-party processing, storage, revocation/deletion, periodic refresh and any exports. Confirm policy-specific periods against the intended implementation.
- A dedicated reviewer account with appropriate synthetic examples, a screencast and privacy/deletion screenshots; credentials must be provided securely at submission time, never committed here.

The audit request remains a local candidate. External submission and reviewer access require authorization covering the completed packet. The official [quota and compliance guide](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) is the submission reference; no audit outcome is implied by this document.
