# YouTube release and real-acceptance runbook

State: local reviewable candidate; NOT PRODUCTION READY. Real acceptance is blocked. Do not equate a private upload, OAuth grant or a local build with release approval.

## Bind the actual project and ordinary creator

Identify the Rafii Google Cloud project ID/number and the exact OAuth client used by the existing deployment. Match the client to the Google Console; presence of environment-variable names cannot establish that binding. The observed D Festival project is not Rafii evidence. No production secret value has been read or copied into these artifacts. The read-only Vercel metadata API request was rejected with INVALID_ARGUMENT; gcloud is not installed.

Record Google Auth Platform audience/Testing versus Production, test-user access, branding, verified domains, published privacy policy/terms and exact authorized redirect URI. The callback is the configured POSTRIFF_PUBLIC_BASE_URL plus /api/oauth/youtube/callback. It must match the server-computed HTTPS callback and Google configuration exactly. Existing developer fixtures use loopback only and cannot supply production consent evidence.

Verify the requested sensitive/restricted scopes using current [Google verification requirements](https://support.google.com/cloud/answer/13463073?hl=en) and [OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies). Record verification approval references, scope coverage and date. Testing refresh-token lifetime and user caps can make a working test connection unsuitable for ongoing production use.

Independently record the [YouTube API compliance audit](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits), actual public-upload eligibility and any channel/account upload/Live/thumbnail/membership restrictions. [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) documents private-only restrictions for relevant unverified projects. A successful private upload cannot pass the public gate. Do not bypass either approval process.

Use an ordinary creator, not a Rafii administrator-only test. Connect the exact channel, read immutable Channel ID and actual tokeninfo scopes, then choose a reviewed test asset and exact visibility/schedule. Destructive/comment/Live/moderation actions need the real target IDs/content/authority and explicit action-time intent. Revenue and member data require a separate intentional enablement; ordinary publishing never requests them.

## Minimum feature grants

Initial connection: youtube.readonly. Upload: youtube.readonly + youtube.upload. Video edits/scheduling/captions/playlists/comments/Live: incremental youtube.readonly + youtube.force-ssl. Creator Analytics and Reporting: incremental youtube.readonly + yt-analytics.readonly. Only intentional sensitive enablement uses yt-analytics-monetary.readonly or youtube.channel-memberships.creator. The implementation never requests broad youtube/youtubepartner for ordinary creator use. Google may include previously granted scopes; actual granted scope is always inspected rather than assumed.

## Candidate rollout gates

Migration migrations/postriff/089_youtube_creator.sql must be reviewed against the target schema and applied in an authorized staging deployment before candidate behavior can run. Existing migration sequence, worker and private storage must be available. It was applied twice only on disposable local PostgreSQL. No remote database has changed.

Install the repository’s pinned requirements into the deployment runtime, including grpcio/protobuf for official streaming. REST fallback is implemented if gRPC is unavailable. Verify the runtime can read trusted private-storage video byte ranges and commit encrypted upload journal transactions before sending chunks.

Server configuration uses POSTRIFF_CREDENTIAL_KEY, POSTRIFF_OAUTH_YOUTUBE_CLIENT_ID, POSTRIFF_OAUTH_YOUTUBE_CLIENT_SECRET and POSTRIFF_PUBLIC_BASE_URL. POSTRIFF_YOUTUBE_CREATOR_ENABLED is OFF unless set to 1. RAFII_VIDEO_UPLOADS_ENABLED and a valid private POSTRIFF_VIDEO_BUCKET are separately required for assets. Capacity controls include POSTRIFF_YOUTUBE_VIDEO_MAX_BYTES/MAX_SECONDS, POSTRIFF_VIDEO_DAILY_BYTES and POSTRIFF_VIDEO_WORKSPACE_MAX_BYTES. Do not increase limits before storage/runtime acceptance is proven.

POSTRIFF_YOUTUBE_PROJECT_EVIDENCE is trusted server configuration bound to clientId and projectId. Its independent oauthVerification, youtubeComplianceAudit and publicUploadEligibility objects each require status verified, source google_platform, a real reference and observedAt. The model deliberately rejects missing, stale, malformed or future observations. Populate it only from independently verified Google records; never copy a synthetic fixture or change a legacy REVIEWED boolean to claim approval. A conservative 30-day observation freshness rule is Rafii policy, not a Google approval expiry. Keep verification/audit documents in access-controlled evidence storage.

Per-channel real acceptance lives in pr_youtube_settings.evidence.acceptance; READY requires PASS, execution real, same channelId, a real reference and fresh verifiedAt. There is no client-facing API to mint these claims. Review and store actual receipts using a trusted server/admin process after each real test. Channel eligibility is separately recorded from successful authorized official responses/probes. Some methods cannot expose all eligibility in advance, so a bounded exact reviewed probe may be required.

Encryption-key changes fail closed and require reconnect. The current vault does not implement automatic multi-key migration. Keep rotation as a separately reviewed operational change; do not overwrite the key expecting old refresh/upload secrets to decrypt. Stream keys must be shown only by the explicit fresh-owner action and must not enter screenshots, logs, analytics or shared receipts.

Run the existing secured worker/maintenance path. Successful authorization refresh is bounded to at most 30 minutes or less near expiry; failed checks back off. Native scheduled videos use conservative reconciliation and remain accepted by YouTube even when local scheduling dispatch is idle. Exact original-approver recovery can extend the unchanged known upload session/Video ID for up to 36 hours; lost initialization/session state never starts a replacement upload automatically.

## Quota and operational acceptance

Audit the exact project’s current quota allocations/usage in Google Console. Current normative [quota documentation](https://developers.google.com/youtube/v3/determine_quota_cost) gives a separate 100/day videos.insert allocation at one Video Uploads unit per call, separate 100/day search, and 10000 general units/day; reset is midnight Pacific. These defaults do not establish this project’s limits or remaining balance. Analytics and Reporting quotas are separate. Stale generated summary text saying 1600 must not override current method/body tables.

Rafii records attempted method/bucket estimates, including failed requests, and deduplicates operational alerts. It cannot see usage by other clients; never infer actual project remaining quota by subtracting workspace attempts from a default. Record quota exhaustion as quota, hold pointless retries and inspect official/provider retry instructions before a manual recovery.

Walk every applicable row in REAL-E2E-MATRIX.md. A real PASS requires IDs/timestamps, official redacted responses and processing/visibility/schedule readback. Shorts require official Analytics creatorContentType evidence; no hashtag/aspect-ratio inference can prove classification. Keep current views versus engagedViews semantics. Thumbnail/caption/podcast membership failures are separate steps and cannot retrigger upload. Live needs broadcast ID, distinct stream ID, liveChatId, ingestion authority, real lifecycle and archive reconciliation.

Official push requires an exact reviewed HTTPS Hub subscription, encrypted HMAC/verification secrets and signed delivery verification. Renewal only follows the approved renewal flag. Hints never prove publication. Community Posts and native Articles remain unsupported; no YouTube Studio or private endpoint fallback is allowed.

## Explicit implementation limits

- Rafii currently accepts MP4/MOV and defaults to 100 MB, even though YouTube may accept larger files. Byte-range storage/runtime throughput, quota and channel limits require real acceptance before increasing capacity. Duration/geometry are checked with bounded container inspection; full codec/audio/rotation analysis is not yet implemented.
- Thumbnails/podcast images honor the current 50 MB API media contract, but shared Rafii image ingestion accepts at most 8 MB. Podcast images must be square. Timed SRT/WebVTT captions have a 1 MB Rafii budget; deprecated sync and automatic caption-generation control are not offered.
- playlistImages.list current documentation accepts id/playlistId while discovery reports parent. The documented filters are implemented; this specific discrepancy remains a real-API release test.
- Interactive Analytics caps at 1000 rows and two years per query, with explicit completeness. Reporting ingestion caps at 32 MB/50000 rows. A large recurring bulk-ingestion runner has not been load tested or deployed.
- Live Chat uses bounded official gRPC batches/REST fallback and cursor recovery. Continuous long-lived streaming/load/concurrency is unproven. Membership/paid events can be exposed only when the official response and connected authority provide them.
- Third-party rights/Content ID, channel verification/Live restrictions, Analytics privacy thresholds and Google project verification cannot be decided by Rafii from aspect ratio, OAuth success or a legacy operator flag.
- Browser validation uses synthetic Google and identity. Turbopack dev hit an existing next/font resolver query failure; a supported Webpack dev launch passed the browser suite. The production Turbopack build passed. Do not interpret this local workaround as a deployment result.

## Reproduce local checks without creator calls

See VALIDATION.json for exact commands. The PostgreSQL harness binds only loopback port 55438 and deletes its generated database on exit. Browser fixture uses a separate generated database on port 55448 and local Python/Next ports 4348/4448; it does not read production credentials or egress to Google. Invoke tests/phase2/youtube_browser_fixture.py with --port 4348 --pg-port 55448 and POSTRIFF_DEV_WEB_ORIGIN=http://127.0.0.1:4448. Launch Next from web with POSTRIFF_API_ORIGIN=http://127.0.0.1:4348 and its supported --webpack -p 4448 flags. Do not supply real Supabase credentials; the existing loopback dev cookie/principal flow provides synthetic identity. Then run web/tests/youtube-creator-browser.cjs. Keep fixture/debug flags out of any deployed environment.

The Vercel CLI observed here is 60.1.3. Before an authorized Vercel rollout, upgrade to current 62.2.0 or later using npm i -g vercel@latest or pnpm add -g vercel@latest for compatibility. No global upgrade was performed in this task.
