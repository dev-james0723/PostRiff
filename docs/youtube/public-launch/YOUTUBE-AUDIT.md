# Rafii YouTube compliance audit packet

Prepared 2026-10-08. **NOT SUBMITTED.** This packet prepares truthful answers; it is not an approval, signed representation, production acceptance or quota allocation. See [SUBMISSION-TRACKER.json](SUBMISSION-TRACKER.json) for independent review states.

## Boundaries and known facts

- Product/API client name: **Rafii**, from `web/src/config/site.ts` and the user's launch instruction. The internal OAuth client label does not change the public product name.
- Canonical customer domain: **https://rafii.io**, explicitly selected by the owner. The coordinating release agent reports its live Vercel binding as `dpl_AHypcnB4iRUv47iw3ZNQDEpuR4Wc`, with `www`; this packet does not independently prove Search Console ownership or that this candidate is deployed there.
- Production project **Rafii YouTube Production**, ID `rafii-youtube-production`, number `568838253270`, was created and observed by the coordinating release agent during this mission. No production clients, API/consent configuration or review submission is confirmed. Existing `rafii-509720` (number `81579135390`) is the separate prior staging reference. Never infer a project number from an OAuth client ID.
- Prior staging evidence: client `Rafii YouTube Staging acceptance`; redirect `https://rafii-consumer-staging.vercel.app/api/oauth/youtube/callback`; External Testing; no Google verification, YouTube audit or public-upload approval in that receipt. This is historical configuration evidence, not the current production configuration.
- Public source currently names `support@postriff.app` and `privacy@postriff.app`. Their monitoring, deliverability and suitability for the Rafii launch are unverified. Operator identity, legal address, jurisdiction and registration remain explicit placeholders. Do not infer them from an email, GitHub account or channel.

## Current upload-policy evidence supersedes the old packet

On 2026-10-08 the live official [videos.insert documentation](https://developers.google.com/youtube/v3/docs/videos/insert?hl=en), marked updated 2026-10-08, says: “Videos uploaded from unverified API projects are not restricted to private viewing mode.” Independent bounded HTTPS retrievals of the English `.com`, cache-busted `.com` and `.cn` pages returned the same statement. Older search-cache excerpts and the earlier review packet retain a post-2020 private-only rule. The official revision history also retains the older restriction without an identified superseding entry. Record this documentation conflict and obtain project-specific provider/Google evidence; neither wording establishes this project’s eligibility or approval.

**Rafii project public-upload eligibility remains UNVERIFIED.** The change does not establish a particular account's eligibility, remove OAuth verification, grant quota, or prove a public upload. Keep release gates until the live project requirements, any Google correspondence and separately authorized provider acceptance establish the applicable result. Do not run a public test without the affected account owner's exact test-publication consent. The [audit guidance](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) still requires a compliance audit before additional quota; private-upload acceptance and higher-quota approval remain separate.

## Concrete form answers

Use the current [YouTube Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form). These are candidate field values, to be reconciled with the demonstrated release before submission.

| Field | Prepared answer / required completion |
| --- | --- |
| Request type | Compliance audit to request additional quota. Do not claim Google requested a periodic re-audit. |
| Applying as organization or individual | **OWNER REQUIRED**; neither is established by the brand. |
| Full legal name, organization/parent name, address, country, size, primary contact | **OWNER REQUIRED**. Use official operator facts; the form supports an individual applicant. |
| Organization website / client access | `https://rafii.io`, after verifying the reviewed build and reviewer-access path. |
| Client name | Rafii; does not include the word YouTube. |
| Privacy / terms | `https://rafii.io/privacy` and `https://rafii.io/terms`, after review, public accessibility and content verification. |
| Target audience | Independent creators and customer workspaces. Do not select internal employee-only use. |
| Business model | Public SaaS is authorized by the owner. Actual free/freemium/subscription pricing, operating entity and rollout timing require owner confirmation; source still describes proposed paid plans. |
| Use-case categories | Video Uploading & Account Management; Tools for Creators; Analytics & Reporting only for released, demonstrated reports. |
| Google OAuth | Yes. Each customer chooses their Google account and intended channel and independently grants scopes. No customer Cloud project is required. |
| Project number | `568838253270` for `rafii-youtube-production`; project creation verified this mission, subsequent configuration and approval unverified. |
| Endpoints | `channels.list`, `videos.insert`, `videos.list`, `videos.update`, `thumbnails.set`, plus released caption/playlist/comment methods shown in the demo. Exclude unused Live, revenue, memberships and search. The form includes deprecated endpoint options: listing there does not make them supported. |
| Requested quota | Separate upload and general values from [QUOTA-EXTENSION.md](QUOTA-EXTENSION.md), after owner selects the forecast. Search increase is not needed for the modeled workflow. |
| Reviewer access | Dedicated reviewer workspace/account with non-sensitive example data and access to every submitted feature. Exact login method and access instructions must be tested. Do not provide customer credentials. |
| Google representative / Content Owner / Ads IDs | Only actual known relationships and applicable IDs. Ordinary creator authorization is not CMS content-owner authority. |

**Product value — candidate answer:** Rafii helps independent creators organize their own videos, prepare metadata and publication plans, authorize an intended channel, and execute approved official YouTube operations. It records provider outcomes and shows native creator reports where permitted. Customer workspaces remain separate. Scheduling, bounded automation and recovery reduce repetitive publishing work; Rafii does not require customer-managed Cloud projects or manufacture audience engagement.

**Data-flow answer — conditional on release proof:** The customer grants feature-specific OAuth permissions. Rafii stores encrypted credentials in server-side workspace/channel records, binds jobs to immutable Channel IDs, checks the acting member and grant, and streams selected Library media through the official resumable upload protocol. A receipt distinguishes uploaded, processing, scheduled and actually published states. AI processing and any external processors must be disclosed before their use, and the demonstrated automation must stay within the customer's expressly enabled policy. Do not convert this intended flow into a claim of provider-backed acceptance without receipts.

## OAuth evidence included with the audit

OAuth verification is tracked independently in Google's Verification Center. Explain scope purpose in-product and in the demo: `youtube.readonly` for selected-channel/private-state reads; `youtube.upload` for the upload-only upgrade; `youtube.force-ssl` for management operations; `yt-analytics.readonly` for nonmonetary reports. `force-ssl` can also upload, so do not request both upload and management solely for a redundant operation. Google consent is separate from Rafii approval of a particular publication. See [minimum-scope verification guidance](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification) and [Analytics query authorization](https://developers.google.com/youtube/analytics/reference/reports/query).

## Attachments and demonstration

Prepare one attachment manifest bound to the actual production ref, URL and project/client IDs. The form accepts image/PDF evidence. Capture public homepage with privacy link and YouTube branding, complete YouTube privacy/deletion sections, terms, OAuth grant/revocation, upload/review interface and Analytics/automation controls actually submitted. Add architecture and tenant-boundary diagrams when available.

The English end-to-end video must show correct branding and OAuth client ID, each requested scope and its actual feature, channel selection, incremental upgrade, approved private upload, processing readback, eligible future scheduling/rescheduling/cancellation, pause/revoke controls, deletion result and supported reports. Record exact build, timestamps and provider receipt references. Redact secrets and unrelated data. A synthetic walkthrough cannot demonstrate real authorization or upload. Creating an unlisted review-video link requires separate owner sharing consent because the launch instruction forbids public publication and does not supply an exact demo asset or recipient disclosure.

## Owner's final submission checklist

1. Confirm all operator/contact facts, selected project/client configuration, actual traffic forecast and reviewer-access account. The production project number is now known.
2. Approve reviewed policy/terms and operational processor, retention, deletion and region statements. Draft pages cannot establish compliance.
3. Verify the submitted release and evidence. Keep unknown/failed real acceptance explicit; do not claim unsupported capabilities.
4. Review and personally accept the form's Section 7: API Terms, privacy understanding, duty to track/notify changed use cases, termination understanding, any demo-access waiver, truthfulness, submission-data processing including automated/LLM evaluation, and support recording. Submit itself certifies those statements. The user expressly withheld authority for agents to accept legal attestations; agents must not check or submit them.
5. Complete any confirmation-email verification; record submission/case ID, timestamp, packet fingerprint, responses, corrections and decision. A static form contains success text even before submission; that is not evidence that anything was sent.

Any optional derived-metrics/storage amendment needs its own owner acceptance and Google's applicable decision. Do not enroll by implication; see [derived-metrics policy](https://developers.google.com/youtube/terms/derived-metrics-policy). Changes requested by Google must be implemented and re-evidenced through the legitimate review flow.
