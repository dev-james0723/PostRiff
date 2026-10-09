# Real YouTube creator acceptance matrix

Updated 2026-10-05T14:18:45.175213+00:00. **0 real PASS; 0 READY; no Google creator test was executed.**

151 explicit cases. Local synthetic/unit/PostgreSQL/browser results are recorded separately and cannot satisfy these cases. Each real PASS requires an ordinary creator Channel ID, timestamps, immutable resource IDs, a redacted official receipt and applicable screenshots/links. Sensitive, public and destructive cases require the reviewed target, content, authority and effects before execution.

| Case | Expected official evidence | Official method | State |
|---|---|---|---|
| connection.oauth | Exact callback, CSRF state, PKCE and one-use committed exchange succeed with an ordinary creator. | Google OAuth authorization/token | BLOCKED — CREDENTIALS |
| connection.identity | Immutable Channel ID and channel metadata resolve from the authenticated grant. | channels.list | BLOCKED — CREDENTIALS |
| connection.actual_scopes | Google tokeninfo grants, audience and requested feature match; UI shows human capabilities. | Google OAuth tokeninfo | BLOCKED — CREDENTIALS |
| connection.refresh | Expired access token refreshes with encrypted offline refresh token. | Google OAuth token | BLOCKED — CREDENTIALS |
| connection.reconnect | Incremental grant retains refresh token only for the same non-revoked canonical channel. | Google OAuth token, channels.list | BLOCKED — CREDENTIALS |
| connection.disconnect | Own tokens/data purge; remote revocation outcome is recorded without breaking another workspace. | Google OAuth revoke | BLOCKED — CREDENTIALS |
| connection.revoked | Official invalid_grant/invalid_token causes purge and reconnect state, without retry storms. | Google OAuth token/tokeninfo | BLOCKED — CREDENTIALS |
| connection.client_failure | Official invalid_client is a project configuration failure, not falsely classified as creator revocation. | Google OAuth token | BLOCKED — CREDENTIALS |
| connection.workspace_isolation | Two workspaces and identities cannot access each other’s credentials or creator resources. | channels.list | BLOCKED — CREDENTIALS |
| connection.brand_channel | Channel selection and account-wide revoke semantics are verified for distinct Brand Channel IDs. | channels.list, Google OAuth revoke | BLOCKED — CREDENTIALS |
| video.resumable_init | Approved original asset starts exactly one durable encrypted official upload session. | videos.insert | BLOCKED — CREDENTIALS |
| video.chunk_progress | Accepted byte ranges and final Video ID are persisted; bytes uploaded is not publication. | videos.insert | BLOCKED — CREDENTIALS |
| video.interrupted_resume | Network interruption resumes the same session from an official byte-range probe. | videos.insert | BLOCKED — CREDENTIALS |
| video.token_expiry | Refresh during a multi-chunk upload preserves original session and exact approval. | Google OAuth token, videos.insert | BLOCKED — CREDENTIALS |
| video.ambiguous_init | Lost initialization response is held; no replacement upload session is created. | videos.insert | BLOCKED — CREDENTIALS |
| video.ambiguous_final | Lost final response reconciles the same upload session/Video ID without duplicate upload. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.session_expiry | Expired session or missing journal requires a new separately reviewed action; no automatic duplicate. | videos.insert | BLOCKED — CREDENTIALS |
| video.recovery_approval | Original approver reviews unchanged digest and resumes only the same known session/Video ID. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.cancel | Explicit cancellation stops sending bytes and records whether a provider video already exists. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.private | Processed video is confirmed private by official readback. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.metadata | Exact title, description, tags, category, languages, license and optional status fields round trip. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.description | Line breaks, links, timestamps, hashtags, credits and localized descriptions remain exact. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.processing | Uploaded, processing, processed, failed and rejected states match official fields. | videos.list | BLOCKED — CREDENTIALS |
| video.upload_limit | Official uploadLimitExceeded is held as channel upload limit; no immediate retry storm. | videos.insert | BLOCKED — CREDENTIALS |
| video.quota | Official quota exhaustion is classified, usage recorded and further writes held. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| video.edit | Partial updates preserve omitted snippet/status/recording/localization fields. | videos.list, videos.update | BLOCKED — CREDENTIALS |
| video.delete | Exact Video ID and explicit destructive approval are audited; unknown deletion is not retried. | videos.delete, videos.list | BLOCKED — CREDENTIALS |
| video.mime_codec | Real MP4/MOV duration, geometry, rotation, audio and codec acceptance is checked at app/provider boundary. | videos.insert, videos.list | BLOCKED — CREDENTIALS |
| publication.public | Audited project eligibility plus processing and official public readback; private upload alone cannot pass. | videos.insert, videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.unlisted | Official unlisted visibility and canonical link are verified. | videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.native_schedule | Private never-published processed video has future publishAt accepted and read back. | videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.reschedule | Official future publishAt changes and the same immutable Video ID is retained. | videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.cancel_schedule | Schedule clears into an explicitly reviewed private state without accidental publication. | videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.publication_reconcile | After publishAt, official privacy/upload state proves publication; local cron is not source of truth. | videos.list | BLOCKED — GOOGLE APPROVAL |
| publication.invalid_schedule | Past/published/non-private/invalid-time cases are rejected without silently publishing. | videos.update, videos.list | BLOCKED — GOOGLE APPROVAL |
| shorts.vertical | Current eligible vertical video uploads through videos.insert and is SHORTS in official Analytics. | videos.insert, reports.query | BLOCKED — CREDENTIALS |
| shorts.square | Current eligible square video is classified from official content-type evidence. | videos.insert, reports.query | BLOCKED — CREDENTIALS |
| shorts.duration_boundary | 180-second eligible asset and over-boundary rejection are tested; channel/date rules are recorded. | videos.insert, reports.query | BLOCKED — CREDENTIALS |
| shorts.no_hashtag_override | No short=true or separate Shorts API exists; hashtag does not override provider classification. | videos.insert, reports.query | BLOCKED — CREDENTIALS |
| shorts.comments | Shorts thread/reply IDs and ownership round trip. | commentThreads.list, comments.insert | BLOCKED — CREDENTIALS |
| shorts.analytics | SHORTS dimension, views and engagedViews provenance/definitions are retained. | reports.query | BLOCKED — CREDENTIALS |
| shorts.content_id | Any over-one-minute Content ID restriction is recorded as account/content limitation. | videos.list, reports.query | BLOCKED — CREDENTIALS |
| shorts.schedule | Eligible Short is scheduled using native video status.publishAt and later reconciled. | videos.update, videos.list, reports.query | BLOCKED — GOOGLE APPROVAL |
| thumbnail.eligibility | A reviewed real custom-thumbnail operation independently proves channel eligibility. | thumbnails.set | BLOCKED — ACCOUNT ELIGIBILITY |
| thumbnail.upload | Valid JPEG/PNG within current media limit produces readback thumbnails. | thumbnails.set, videos.list | BLOCKED — ACCOUNT ELIGIBILITY |
| thumbnail.replace | Reviewed replacement retains the existing Video ID. | thumbnails.set, videos.list | BLOCKED — ACCOUNT ELIGIBILITY |
| thumbnail.failure_isolation | Thumbnail failure holds the attachment while never re-uploading the video. | thumbnails.set, videos.list | BLOCKED — ACCOUNT ELIGIBILITY |
| thumbnail.validation | Media bytes, dimensions, MIME and Rafii’s smaller image-ingestion budget are validated. | thumbnails.set | BLOCKED — ACCOUNT ELIGIBILITY |
| captions.list | Owned video caption track IDs and languages list correctly. | captions.list | BLOCKED — CREDENTIALS |
| captions.srt | Timed SRT language/name/draft declaration uploads and serving/readback verifies. | captions.insert, captions.list | BLOCKED — CREDENTIALS |
| captions.vtt | Timed WebVTT including Unicode is accepted without truncation. | captions.insert, captions.list | BLOCKED — CREDENTIALS |
| captions.replace | Existing track is replaced by exact ID and metadata is preserved. | captions.update, captions.list | BLOCKED — CREDENTIALS |
| captions.draft | Draft state updates and reads back where supported. | captions.update, captions.list | BLOCKED — CREDENTIALS |
| captions.delete | Explicit track-ID deletion is audited and read-only reconciled. | captions.delete, captions.list | BLOCKED — CREDENTIALS |
| captions.failure_isolation | Caption failure does not create a duplicate video or bypass publication guards. | captions.insert, captions.list | BLOCKED — CREDENTIALS |
| playlists.list_select | Owned playlists paginate and selected immutable IDs are retained. | playlists.list | BLOCKED — CREDENTIALS |
| playlists.create | Reviewed title/description/privacy creates a playlist and ID receipt. | playlists.insert | BLOCKED — CREDENTIALS |
| playlists.edit | Partial metadata/privacy edit preserves omitted fields. | playlists.list, playlists.update | BLOCKED — CREDENTIALS |
| playlists.localize | Default language and localized titles/descriptions round trip. | playlists.update, playlists.list | BLOCKED — CREDENTIALS |
| playlists.add | Episode/video insertion is a separate durable idempotent step after video creation. | playlistItems.insert, playlistItems.list | BLOCKED — CREDENTIALS |
| playlists.remove | Exact playlist item deletion leaves the video intact and is audited. | playlistItems.delete, playlistItems.list | BLOCKED — CREDENTIALS |
| playlists.reorder | Position update preserves same item and resource IDs. | playlistItems.update, playlistItems.list | BLOCKED — CREDENTIALS |
| playlists.delete | Explicit owned playlist deletion does not delete its videos. | playlists.delete, playlists.list | BLOCKED — CREDENTIALS |
| playlists.failure_isolation | Ambiguous or failed membership insertion never repeats video upload. | playlistItems.insert, playlistItems.list | BLOCKED — CREDENTIALS |
| podcast.identify | Owned playlists expose official status.podcastStatus. | playlists.list | BLOCKED — CREDENTIALS |
| podcast.enable | Reviewed official podcast status updates and reads back. | playlists.update, playlists.list | BLOCKED — CREDENTIALS |
| podcast.disable | Reviewed status returns a podcast to an ordinary playlist where permitted. | playlists.update, playlists.list | BLOCKED — CREDENTIALS |
| podcast.artwork | Square JPEG/PNG within API/app limits uploads and artwork ID/readback verifies. | playlistImages.insert, playlistImages.list | BLOCKED — CREDENTIALS |
| podcast.artwork_replace | Existing image update/delete is reviewed and exact IDs are retained. | playlistImages.update, playlistImages.delete, playlistImages.list | BLOCKED — CREDENTIALS |
| podcast.filter_conflict | Live acceptance resolves current documented id/playlistId versus discovery parent discrepancy. | playlistImages.list | BLOCKED — CREDENTIALS |
| podcast.episode | Video publishing and podcast playlist membership remain two idempotent operations. | videos.insert, playlistItems.insert | BLOCKED — CREDENTIALS |
| podcast.metadata | Podcast playlist title/description/privacy/localizations round trip. | playlists.update, playlists.list | BLOCKED — CREDENTIALS |
| comments.threads | Official top-level thread pagination preserves comment/thread/video/channel IDs. | commentThreads.list | BLOCKED — CREDENTIALS |
| comments.replies_read | All returned reply pages preserve parent and thread hierarchy. | comments.list | BLOCKED — CREDENTIALS |
| comments.inbox_filters | Video/newest/search/moderation/unanswered filters report returned-page coverage. | commentThreads.list, comments.list | BLOCKED — CREDENTIALS |
| comments.create | Human-approved exact text creates a top-level thread, not a reply resource. | commentThreads.insert | BLOCKED — CREDENTIALS |
| comments.reply | Human-approved exact text creates a reply under the reviewed top-level comment. | comments.insert | BLOCKED — CREDENTIALS |
| comments.edit_owned | Owned comment updates and official readback verifies exact text. | comments.update, comments.list | BLOCKED — CREDENTIALS |
| comments.delete_owned | Owned exact comment deletion is explicitly approved and audited. | comments.delete, comments.list | BLOCKED — CREDENTIALS |
| comments.ai_draft | AI-assisted text remains a draft until a human approves the exact reply. | comments.insert | BLOCKED — CREDENTIALS |
| comments.comments_disabled | Disabled/deleted/Made-for-Kids comments surface an explicit provider restriction. | commentThreads.list, commentThreads.insert | BLOCKED — CREDENTIALS |
| moderation.held | Held-for-review comments list only with actual owner authority. | commentThreads.list | BLOCKED — ACCOUNT ELIGIBILITY |
| moderation.publish | Reviewed held comment changes to published and reads back where allowed. | comments.setModerationStatus, commentThreads.list | BLOCKED — ACCOUNT ELIGIBILITY |
| moderation.reject | Reviewed rejection and optional author ban are audited with original comment IDs. | comments.setModerationStatus | BLOCKED — ACCOUNT ELIGIBILITY |
| moderation.authority | Foreign or unauthorized moderation is rejected before a provider write. | comments.setModerationStatus | BLOCKED — ACCOUNT ELIGIBILITY |
| analytics.daily | Views, engaged views, estimated minutes watched, average duration, likes/comments/shares and subscribers gained/lost return official columns. | reports.query | BLOCKED — CREDENTIALS |
| analytics.content_type | Current creatorContentType semantics distinguish SHORTS/VIDEO/other without guessing geometry. | reports.query | BLOCKED — CREDENTIALS |
| analytics.retention | Owned-video retention report returns ratio metrics or an explicit unavailable result. | reports.query | BLOCKED — CREDENTIALS |
| analytics.traffic | Official insightTrafficSourceType report validates its metric combinations. | reports.query | BLOCKED — CREDENTIALS |
| analytics.geography | Country report validates its metric combinations and privacy-withheld rows. | reports.query | BLOCKED — CREDENTIALS |
| analytics.device | Official deviceType report has correct source provenance. | reports.query | BLOCKED — CREDENTIALS |
| analytics.playback_location | Official playback-location report round trips. | reports.query | BLOCKED — CREDENTIALS |
| analytics.demographics | Permitted age/gender report reports withheld data as unavailable, not zero. | reports.query | BLOCKED — CREDENTIALS |
| analytics.playlist | Owned-playlist performance report filters immutable playlist ID. | reports.query | BLOCKED — CREDENTIALS |
| analytics.live_on_demand | Official liveOrOnDemand breakdown is retained. | reports.query | BLOCKED — CREDENTIALS |
| analytics.paging | Paging up to Rafii’s 1000-row budget exposes completeness and does not query-storm. | reports.query | BLOCKED — CREDENTIALS |
| analytics.cache_revocation | Authorized cached reports expire and purge on revoked authorization. | Google OAuth token, reports.query | BLOCKED — CREDENTIALS |
| revenue.enable | Owner intentionally enables the monetary flag and grants the actual monetary scope separately. | Google OAuth authorization/token | NOT AUTHORIZED |
| revenue.metrics | Authorized eligible revenue/ad revenue/monetized playback/CPM/ad-impression columns return sensitive provenance. | reports.query | NOT AUTHORIZED |
| revenue.isolation | Non-owner/other-workspace access, scope-only implicit access and stale-auth access are rejected. | reports.query | NOT AUTHORIZED |
| revenue.financial_reports | Financial and unclassified bulk report types require the same explicit sensitive gate. | reportTypes.list, jobs.list/get, jobs.reports.list/get | NOT AUTHORIZED |
| reporting.types | Official eligible reportTypes list, with non-monetary allowlist and no implicit sensitive enablement. | reportTypes.list | BLOCKED — CREDENTIALS |
| reporting.job | Explicit reviewed job creation retains job ID and report type. | jobs.create, jobs.get | BLOCKED — CREDENTIALS |
| reporting.reports | Generated report list/get retain coverage, created time and ingestion timestamp. | jobs.reports.list/get | BLOCKED — CREDENTIALS |
| reporting.download | Only bounded official-host report download with no redirects is accepted. | Official Reporting download URL | BLOCKED — CREDENTIALS |
| reporting.ingest | 32 MB / 50000-row budget and channel/column shape validation are enforced. | jobs.reports.get, Official Reporting download URL | BLOCKED — CREDENTIALS |
| reporting.correction | Newer report for the same coverage replaces older data; late reports do not fabricate completeness. | jobs.reports.list/get | BLOCKED — CREDENTIALS |
| reporting.delete | Exact report job deletion is explicitly reviewed and audited. | jobs.delete, jobs.get | BLOCKED — CREDENTIALS |
| reporting.expiry | Authorized report data expires at 30 days or earlier on revocation. | Google OAuth token | BLOCKED — CREDENTIALS |
| live.eligibility | Explicit reviewed probe independently establishes actual Live-enabled channel authority. | liveBroadcasts.insert | BLOCKED — ACCOUNT ELIGIBILITY |
| live.schedule | Future scheduled start/end, privacy and immutable broadcast ID round trip. | liveBroadcasts.insert, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.edit | Title/description/category/privacy/Made-for-Kids/DVR/recording/auto-start-stop edits preserve omitted fields. | liveBroadcasts.update, videos.update, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.stream | Distinct stream resource creates with immutable stream ID and supported CDN configuration. | liveStreams.insert, liveStreams.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.ingestion | Fresh-owner-only ingestion config read clears the stream key from normal UI/caches/logs. | liveStreams.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.bind | Owned stream binds to the owned broadcast while retaining both IDs. | liveBroadcasts.bind, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.monitor | Stream health and broadcast lifecycle map actual official states. | liveStreams.list, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.testing | Ready broadcast transitions to testing with valid ingestion. | liveBroadcasts.transition | BLOCKED — ACCOUNT ELIGIBILITY |
| live.start | Actual live transition requires ingestion and official live readback. | liveBroadcasts.transition, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.end | Reviewed completion transitions and actual start/end timestamps are read back. | liveBroadcasts.transition, liveBroadcasts.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.archive | Completed broadcast reconciles resulting archive/video processing and canonical URL. | liveBroadcasts.list, videos.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.thumbnail | Live broadcast/video thumbnail follows separate eligibility and review. | thumbnails.set, videos.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live.delete | Owned broadcast and stream deletes are separate explicit audited actions. | liveBroadcasts.delete, liveStreams.delete | BLOCKED — ACCOUNT ELIGIBILITY |
| live.invalid_transition | Official invalid transitions/restrictions are held without an automatic destructive retry. | liveBroadcasts.transition | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.stream_read | Official streamList gRPC over TLS returns active chat events within the bounded batch window. | liveChatMessages.streamList | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.fallback | REST fallback obeys official pollingIntervalMillis and preserves the cursor. | liveChatMessages.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.reconnect | Reconnect preserves ordering, duplicates, revisions and last provider cursor. | liveChatMessages.streamList, liveChatMessages.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.send | Human-approved exact message writes only to the connected identity’s owned active broadcast/chat. | liveChatMessages.insert | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.poll | Official poll insert and close transition preserve chat/poll IDs. | liveChatMessages.insert, liveChatMessages.transition | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.delete_message | Observed same-chat message delete requires actual authority and an audited exact target. | liveChatMessages.delete | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.moderators | List/add/remove moderator remains bound to the owned broadcast/chat. | liveChatModerators.list/insert/delete | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.timeout_ban | Actual authorized temporary/permanent ban and unban retain IDs and audit. | liveChatBans.insert/delete | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.paid_events | Super Chat/Super Sticker and available membership-event schemas display official source events. | liveChatMessages.streamList, liveChatMessages.list | BLOCKED — ACCOUNT ELIGIBILITY |
| live_chat.rate_limit | Provider rate limits/ended chat/disabled chat recover or surface explicit restrictions without aggressive polling. | liveChatMessages.streamList, liveChatMessages.list | BLOCKED — ACCOUNT ELIGIBILITY |
| memberships.enable | Owner intentionally enables the feature and grants the dedicated membership scope. | Google OAuth authorization/token | NOT AUTHORIZED |
| memberships.levels | Eligible approved creator membership levels return official IDs. | membershipsLevels.list | NOT AUTHORIZED |
| memberships.members | Eligible member list/update modes paginate with workspace-sensitive isolation. | members.list | NOT AUTHORIZED |
| memberships.disabled | Non-approved/disabled membership channels show the official restriction rather than Full Access. | members.list | NOT AUTHORIZED |
| compliance.made_for_kids | Explicit human selfDeclaredMadeForKids survives upload/edit and official readback. | videos.insert/update/list | BLOCKED — CREDENTIALS |
| compliance.synthetic_media | Explicit human containsSyntheticMedia survives upload/edit and audit without AI-copy inference. | videos.insert/update/list | BLOCKED — CREDENTIALS |
| compliance.subscriber_notification | Exact approved notifySubscribers boolean is included only at upload initialization. | videos.insert | BLOCKED — CREDENTIALS |
| compliance.localization | Default language, audio language and localized metadata preserve exact text/omitted locales. | videos.insert/update/list | BLOCKED — CREDENTIALS |
| compliance.push_signed | Reviewed official Hub subscription receives signed channel-bound upload/title/description hints. | Official YouTube WebSub Hub | BLOCKED — CREDENTIALS |
| compliance.push_hint_only | Notification wakes readback and never becomes processing/publication proof by itself. | videos.list | BLOCKED — CREDENTIALS |
| adaptation.video_asset | Campaign adapter rejects image/text-only content and offers explicit video/script/link conversion. | videos.insert | BLOCKED — CREDENTIALS |
| adaptation.composer | Video/Short/Live controls reflect real permissions, source-of-truth schedule and exact declarations. | videos.insert, videos.update, liveBroadcasts.insert | BLOCKED — CREDENTIALS |
| adaptation.existing_connectors | Instagram/X/Bluesky/Telegram shared approval, scheduling, errors and receipts retain existing behavior. | Existing official connector methods | BLOCKED — CREDENTIALS |
| unsupported.community_posts | Community publishing stays unsupported; no Studio automation/private endpoint fallback. | No documented public write API | UNSUPPORTED BY OFFICIAL API |
| unsupported.native_article | No native YouTube Article object is fabricated. | No documented public Article resource | UNSUPPORTED BY OFFICIAL API |
| unsupported.automatic_captions | Automatic YouTube caption generation cannot be triggered/controlled by this integration. | No documented generation-control API | UNSUPPORTED BY OFFICIAL API |
| unsupported.force_shorts | No separate Shorts upload endpoint, short=true field or hashtag classification override is offered. | No documented classification override | UNSUPPORTED BY OFFICIAL API |
| unsupported.notification_edit | Post-upload subscriber-notification toggle is not offered. | No documented post-upload toggle | UNSUPPORTED BY OFFICIAL API |
