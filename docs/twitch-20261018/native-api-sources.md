# Twitch native API implementation and source verification

Date: 2026-10-18 UTC. Worktree branch: `codex/rafii-twitch-full-20261018`.

## Evidence boundary

`src/postriff_phase2/twitch_native.py` contains **112 callable native operation contracts**, typed authorization/resource evidence, deterministic approval manifests, and a bounded injected-transport executor. `tests/test_twitch_native.py` currently runs **165 passing offline tests**: one independent request vector per operation, registry completeness, and 52 security/behavior tests. The tests neither contact Twitch nor use real credentials.

Every operation below is **Verified for its offline request contract; Unverified live**. Public developer-app registration, live consent, provider role/eligibility acceptance, actual writes, webhook delivery, commercial approval, deployed migrations, and production execution remain separate gates. A passing mock is not production evidence.

Boundary acceptance adds **36 passing EventSub tests** and **27 passing mounted HTTP tests** in `tests/test_twitch_eventsub.py` and `tests/test_twitch_http.py`. They cover byte-exact HMAC, duplicate headers/JSON keys, the ten-minute past and sixty-second future limits, registered callback identity, current credential generation, pending subscription binding, public OAuth routing, native route dispatch, browser Origin/session guards, and safe errors with network calls forbidden. The synthetic HTTP service proves routing; real PostgreSQL durability, locking and RLS remain separate acceptance evidence.

The [official HMAC construction](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/#verifying-the-event-message) signs message ID, timestamp and body, without the Message-Type header. The verifier therefore binds a revocation header to a documented disabled status in the signed body; changing the header of a valid notification cannot revoke the subscription. Pending callback binding also requires a nonempty, valid provider subscription ID. Regression tests first reproduced both failures and passed after the fixes. Revocation statuses come from [webhook revocation documentation](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/#revoking-your-subscription) plus the [2022-12-09 moderator-removal addition](https://dev.twitch.tv/docs/change-log/).

## Service integration contract

The service supplies validated token identity/scopes and binds the connection to its workspace. Native payloads reject identity, scope, role, URL, headers, and approval fields. Schemas reject unknown nested fields, coercion of strings or booleans into numbers, invalid ranges, invalid timestamps/time zones, oversized objects, and invalid conditional combinations.

`prepare_operation(action, payload, *, subject_id, broadcaster_id, scopes, roles=(), account_type='', live=False, rights=None, now=None)` returns `PreparedOperation`. Its `as_dict()` is semantic JSON; `payload_sha256` hashes that exact representation. Evidence times remain private, so revalidating identical facts preserves the approval digest. Internal manifests are immutable and authenticated with a process-local HMAC; a serialized or modified object cannot be dispatched.

`validate_operation_payload(action, payload)` runs the strict shape checks before provider preflights. `resource_ids_for_operation(action, payload)` returns the exact resource kind and IDs. `operation_scopes(action)` is a list of alternatives, each containing all required scopes. `union_supported_scopes()` is an OAuth allowlist, not a request for every permission.

`execute(client_id, access_token, prepared, transport, now=...)` sends one request to the fixed `https://api.twitch.tv/helix` origin. It never follows links or retries writes. The shared HTTP transport enforces HTTPS, response bounds, timeouts, and redirect rejection. Provider exceptions and response text never enter public error messages. Upstream 5xx, timeouts, redirects, malformed successful writes, or unclear acknowledgments have `unknown_result=True`; 4xx rejection is distinct. Rate-limit rejection is surfaced without automatic retry.

`RoleEvidence` binds subject, broadcaster, role set, observation and expiry, for at most 300 seconds. Broadcaster self-identity is derived. A moderator/editor claim in a request or scope is insufficient. `verify_roles` uses official read endpoints with bounded pagination; an editor lookup requires the broadcaster's separately validated editor-list grant.

`RightsEvidence(subject_id, broadcaster_id, resource_kind, resource_ids, client_id, checked_at, expires_at, ownership_verified=False, creator_app_verified=False, reuse_authorized=False, storage_authorized=False, metadata_json='{}')` is created only by trusted service code. `verify_resource_access` verifies exact clip/VOD/schedule ownership and reward creator-app control. Ownership does not imply copyright or consent. Download dispatch requires ownership, recorded per-action reuse assertion, and service storage authorization separately. A Twitch grant cannot supply those latter facts.

Stream keys bypass generic results through `execute_sensitive(..., secret_sink=...)`. The service must require a fresh human session and exact approval; the native executor returns only a delivery receipt. No key reaches an agent, ordinary result, or error trace.

## Material native behavior

| Family | Implemented behavior and remaining provider constraints | Official sources |
| --- | --- | --- |
| Channel and schedule | Metadata updates, schedules, vacation, recurring-series effects, and upcoming broadcasts are real Helix requests. Schedule creation never starts an encoder. Recurring start times cannot be edited; non-recurring scheduling has eligibility restrictions. | [Schedule guide](https://dev.twitch.tv/docs/api/schedule/), [Video broadcast](https://dev.twitch.tv/docs/video-broadcast/) |
| Chat and moderation | Connected subject is the sender/moderator. Replies bind the parent ID. HTTP 200 requires `is_sent=true` and an ID. User-token Shared Chat audience cannot be suppressed with the app-token-only field. Whispers may be silently dropped even after 204, so remain accepted with delivery unverified. | [Chat send/receive](https://dev.twitch.tv/docs/chat/send-receive-messages/), [Chat moderation](https://dev.twitch.tv/docs/chat/moderation/), [Whisper reference](https://dev.twitch.tv/docs/api/reference/#send-whisper) |
| Markers | Live-only; past-broadcast storage must have a recorded user declaration because Helix does not expose a setting that proves it. Read scope is `user:read:broadcast`, not `channel:read:broadcast`. | [Marker guide](https://dev.twitch.tv/docs/api/markers/), [Scopes](https://dev.twitch.tv/docs/authentication/scopes/) |
| Clips and VODs | Async clip creation remains accepted until a clip lookup finds the exact channel-owned ID. Official temporary clip download links are available; media is not fetched automatically. A selected VOD can be clipped or deleted only after channel ownership proof. | [Clip guide](https://dev.twitch.tv/docs/api/clips/), [Clip-from-VOD reference](https://dev.twitch.tv/docs/api/reference/#create-clip-from-vod), [Clip downloads](https://dev.twitch.tv/docs/api/reference/#get-clips-download) |
| Polls and predictions | Explicit choices, timing, points consequences, result/winner constraints, and affiliate/partner checks. Broadcaster token identity is required; UI moderator privileges do not make another user's token valid for these endpoints. Bits voting is not implemented because it is deprecated. | [Poll guide](https://dev.twitch.tv/docs/api/polls/), [Prediction guide](https://dev.twitch.tv/docs/api/predictions/) |
| Rewards | Own broadcaster identity plus manageable-reward preflight proves Rafii's client created the selected reward. Pending-redemption and deletion effects are disclosed in approval. | [Reward reference](https://dev.twitch.tv/docs/api/reference/#get-custom-reward), [Redemption reference](https://dev.twitch.tv/docs/api/reference/#update-redemption-status) |
| Subscriptions, Bits and ads | Reads and authorized ad controls only. Native commercial-start checks broadcaster identity, live state and affiliate/partner status. Current Hype Train status replaces the removed events endpoint. | [Ad reference](https://dev.twitch.tv/docs/api/reference/#start-commercial), [Changelog](https://dev.twitch.tv/docs/change-log/) |
| Analytics | Real stream/clip/video/follower/subscriber/Bits snapshots retain provenance; no synthetic Creator Dashboard values. Game/extension reports need a user token with the corresponding analytics scope and a developer resource owned by that user. Follower-count reads omit individual records; deprecated profile view_count is removed. | [Insights and analytics](https://dev.twitch.tv/docs/insights/), [Analytics reference](https://dev.twitch.tv/docs/api/reference/#get-extension-analytics) |
| EventSub | The service/EventSub module separately handles app-token webhook subscriptions, raw-body HMAC, durable receipt, replay rejection, deduplication, and revocation. Native scopes include only current implemented actions. | [Webhook handling](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/), [EventSub overview](https://dev.twitch.tv/docs/eventsub/) |

## Commercial, storage and AI decision

The [Twitch Developer Services Agreement](https://legal.twitch.com/en/legal/developer-agreement/) indexed official English text reports last modification 2024-12-04. Direct retrieval returned a navigation shell during this session; indexed official text was readable. Schedule 1 distinguishes ordinary API use from marketing/campaign-analysis services needing a separate agreement and approval. Rafii's intended marketing role warrants that application; this is not proof Twitch has approved Rafii.

The same agreement requires minimal permissions, user consent, publication preview, disclosed retention and deletion following revocation or reduced authorization. Storage needs an applicable authorization, content rights, or restricted 24-hour caching; that cache exception does not authorize sharing with third parties. Permission to use API data is not a license to third-party music/video rights. Content export/redistribution must be explicitly addressed in the requested agreement.

No Rafii-specific permission for AI-provider processing, training, retention, or autonomous actions was found. The application must identify subprocessors and requested processing and ask Twitch to confirm acceptable use. The engineering does not infer that Twitch's own [privacy notice](https://legal.twitch.com/en/legal/privacy-notice/) permits Rafii's model use. No application or message was sent.

## Explicit limitations and continuation

No generic Twitch text feed, arbitrary historical-chat archive, full-VOD download/upload, arbitrary Channel Points grants, subscription purchases, or Creator Dashboard revenue/watch-time/retention API is claimed. The `UNSUPPORTED` map provides these reasons to callers.

The fixed native origin excludes encoder ingest control. General extension-backend JWT management, Drops/game-organization entitlements, and beta Guest Star production are not covered by this broadcaster adapter; they require separate ownership, authorization and integration work. Some public read endpoints use intentionally narrow forms. The iCalendar path rejects a truncated response from the shared raw-text transport instead of reporting an incomplete calendar as valid. Twitch still controls transient state, limits, phone/Turbo/Prime eligibility, and provider approval; all live outcomes remain unverified.

The next engineer should preserve the registry/approval contract and run the offline suite before approved live work:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_twitch_native.py'
PYTHONPATH=src python -m unittest discover -s tests -p 'test_twitch_eventsub.py'
PYTHONPATH=src python -m unittest discover -s tests -p 'test_twitch_http.py'
```

Then exercise an approved isolated Twitch app/account through real consent, role denial, scope reduction, revoke, clip completion, chat-drop handling and signed webhook challenge/notification/revocation. Keep those live receipts separate from the offline test evidence.

## Exact implemented registry

The following table is generated from the implementation. Each row has an independent request contract vector in `tests/test_twitch_native.py`. OAuth alternatives are separated by **OR**; terms within each alternative are required together. Scope-free requests still need a validated user access token in this adapter. Additional predicates are enforced alongside workspace, consent, queue and agent permission gates supplied by the service.

<!-- REGISTRY_START -->

| Operation | Helix request | Scope alternatives | Extra native predicates |
| --- | --- | --- | --- |
| `twitch.channel.get` | `GET /channels` | No additional scope | any |
| `twitch.channel.update` | `PATCH /channels` | `channel:manage:broadcast` | broadcaster |
| `twitch.channel.editors.get` | `GET /channels/editors` | `channel:read:editors` | broadcaster |
| `twitch.channel.followers.get` | `GET /channels/followers` | `moderator:read:followers` | moderator |
| `twitch.channel.followers.total` | `GET /channels/followers` | No additional scope | any |
| `twitch.stream.get` | `GET /streams` | No additional scope | any |
| `twitch.stream.key.get` | `GET /streams/key` | `channel:read:stream_key` | broadcaster, secure human secret sink |
| `twitch.category.search` | `GET /search/categories` | No additional scope | any |
| `twitch.channel.labels.get` | `GET /content_classification_labels` | No additional scope | any |
| `twitch.channel.search` | `GET /search/channels` | No additional scope | any |
| `twitch.channel.followed.get` | `GET /channels/followed` | `user:read:follows` | any |
| `twitch.stream.followed.get` | `GET /streams/followed` | `user:read:follows` | any |
| `twitch.profile.get` | `GET /users` | No additional scope | broadcaster |
| `twitch.profile.update` | `PUT /users` | `user:edit` | broadcaster |
| `twitch.schedule.get` | `GET /schedule` | No additional scope | any |
| `twitch.schedule.calendar.get` | `GET /schedule/icalendar` | No additional scope | any |
| `twitch.schedule.settings.update` | `PATCH /schedule/settings` | `channel:manage:schedule` | broadcaster |
| `twitch.schedule.create` | `POST /schedule/segment` | `channel:manage:schedule` | broadcaster |
| `twitch.schedule.update` | `PATCH /schedule/segment` | `channel:manage:schedule` | broadcaster, schedule proof |
| `twitch.schedule.delete` | `DELETE /schedule/segment` | `channel:manage:schedule` | broadcaster, schedule proof |
| `twitch.marker.create` | `POST /streams/markers` | `channel:manage:broadcast` | editor, live, marker_settings proof |
| `twitch.marker.get` | `GET /streams/markers` | `user:read:broadcast` **OR** `channel:manage:broadcast` | editor |
| `twitch.chat.send` | `POST /chat/messages` | `user:write:chat` | any |
| `twitch.chat.reply` | `POST /chat/messages` | `user:write:chat` | any |
| `twitch.chat.chatters.get` | `GET /chat/chatters` | `moderator:read:chatters` | moderator |
| `twitch.chat.settings.get` | `GET /chat/settings` | No additional scope | any |
| `twitch.chat.settings.private.get` | `GET /chat/settings` | `moderator:read:chat_settings` | moderator |
| `twitch.chat.settings.update` | `PATCH /chat/settings` | `moderator:manage:chat_settings` | moderator |
| `twitch.chat.announcement.send` | `POST /chat/announcements` | `moderator:manage:announcements` | moderator |
| `twitch.chat.shoutout.send` | `POST /chat/shoutouts` | `moderator:manage:shoutouts` | moderator, live |
| `twitch.chat.shared.get` | `GET /shared_chat/session` | No additional scope | any |
| `twitch.chat.pin.get` | `GET /chat/pins` | `moderator:read:chat_messages` **OR** `moderator:manage:chat_messages` | moderator |
| `twitch.chat.pin.create` | `PUT /chat/pins` | `moderator:manage:chat_messages` | moderator |
| `twitch.chat.pin.update` | `PATCH /chat/pins` | `moderator:manage:chat_messages` | moderator |
| `twitch.chat.pin.delete` | `DELETE /chat/pins` | `moderator:manage:chat_messages` | moderator |
| `twitch.chat.message.delete` | `DELETE /moderation/chat` | `moderator:manage:chat_messages` | moderator |
| `twitch.chat.clear` | `DELETE /moderation/chat` | `moderator:manage:chat_messages` | moderator |
| `twitch.chat.emotes.get` | `GET /chat/emotes` | No additional scope | any |
| `twitch.chat.badges.get` | `GET /chat/badges` | No additional scope | any |
| `twitch.chat.emotes.global.get` | `GET /chat/emotes/global` | No additional scope | any |
| `twitch.chat.emotes.set.get` | `GET /chat/emotes/set` | No additional scope | any |
| `twitch.chat.emotes.user.get` | `GET /chat/emotes/user` | `user:read:emotes` | any |
| `twitch.chat.badges.global.get` | `GET /chat/badges/global` | No additional scope | any |
| `twitch.chat.color.get` | `GET /chat/color` | No additional scope | any |
| `twitch.chat.color.update` | `PUT /chat/color` | `user:manage:chat_color` | any |
| `twitch.chat.whisper.send` | `POST /whispers` | `user:manage:whispers` | any |
| `twitch.moderation.ban` | `POST /moderation/bans` | `moderator:manage:banned_users` | moderator |
| `twitch.moderation.timeout` | `POST /moderation/bans` | `moderator:manage:banned_users` | moderator |
| `twitch.moderation.unban` | `DELETE /moderation/bans` | `moderator:manage:banned_users` | moderator |
| `twitch.moderation.banned.get` | `GET /moderation/banned` | `moderation:read` **OR** `moderator:manage:banned_users` | broadcaster |
| `twitch.moderation.warn` | `POST /moderation/warnings` | `moderator:manage:warnings` | moderator |
| `twitch.moderation.channels.get` | `GET /moderation/channels` | `user:read:moderated_channels` | any |
| `twitch.moderation.moderators.get` | `GET /moderation/moderators` | `moderation:read` **OR** `channel:manage:moderators` | broadcaster |
| `twitch.moderation.moderator.add` | `POST /moderation/moderators` | `channel:manage:moderators` | broadcaster |
| `twitch.moderation.vip.add` | `POST /channels/vips` | `channel:manage:vips` | broadcaster |
| `twitch.moderation.moderator.remove` | `DELETE /moderation/moderators` | `channel:manage:moderators` | broadcaster |
| `twitch.moderation.vip.remove` | `DELETE /channels/vips` | `channel:manage:vips` | broadcaster |
| `twitch.moderation.vips.get` | `GET /channels/vips` | `channel:read:vips` **OR** `channel:manage:vips` | broadcaster |
| `twitch.moderation.blocked_terms.get` | `GET /moderation/blocked_terms` | `moderator:read:blocked_terms` **OR** `moderator:manage:blocked_terms` | moderator |
| `twitch.moderation.blocked_terms.add` | `POST /moderation/blocked_terms` | `moderator:manage:blocked_terms` | moderator |
| `twitch.moderation.blocked_terms.remove` | `DELETE /moderation/blocked_terms` | `moderator:manage:blocked_terms` | moderator |
| `twitch.moderation.unban_requests.get` | `GET /moderation/unban_requests` | `moderator:read:unban_requests` **OR** `moderator:manage:unban_requests` | moderator |
| `twitch.moderation.unban_requests.resolve` | `PATCH /moderation/unban_requests` | `moderator:manage:unban_requests` | moderator |
| `twitch.automod.settings.get` | `GET /moderation/automod/settings` | `moderator:read:automod_settings` **OR** `moderator:manage:automod_settings` | moderator |
| `twitch.automod.settings.update` | `PUT /moderation/automod/settings` | `moderator:manage:automod_settings` | moderator |
| `twitch.automod.check` | `POST /moderation/enforcements/status` | `moderation:read` | broadcaster |
| `twitch.automod.message.resolve` | `POST /moderation/automod/message` | `moderator:manage:automod` | moderator |
| `twitch.shield.get` | `GET /moderation/shield_mode` | `moderator:read:shield_mode` **OR** `moderator:manage:shield_mode` | moderator |
| `twitch.shield.update` | `PUT /moderation/shield_mode` | `moderator:manage:shield_mode` | moderator |
| `twitch.moderation.suspicious.add` | `POST /moderation/suspicious_users` | `moderator:manage:suspicious_users` | moderator |
| `twitch.moderation.suspicious.remove` | `DELETE /moderation/suspicious_users` | `moderator:manage:suspicious_users` | moderator |
| `twitch.moderation.user_blocks.get` | `GET /users/blocks` | `user:read:blocked_users` | broadcaster |
| `twitch.moderation.user_block.add` | `PUT /users/blocks` | `user:manage:blocked_users` | broadcaster |
| `twitch.moderation.user_block.remove` | `DELETE /users/blocks` | `user:manage:blocked_users` | broadcaster |
| `twitch.clip.get` | `GET /clips` | No additional scope | any |
| `twitch.clip.lookup` | `GET /clips` | No additional scope | any |
| `twitch.clip.create` | `POST /clips` | `clips:edit` | any, live |
| `twitch.clip.vod.create` | `POST /videos/clips` | `channel:manage:clips` **OR** `editor:manage:clips` | editor, video proof |
| `twitch.clip.download` | `GET /clips/downloads` | `channel:manage:clips` **OR** `editor:manage:clips` | editor, clip_download proof |
| `twitch.video.get` | `GET /videos` | No additional scope | any |
| `twitch.video.delete` | `DELETE /videos` | `channel:manage:videos` | broadcaster, video proof |
| `twitch.poll.get` | `GET /polls` | `channel:read:polls` **OR** `channel:manage:polls` | broadcaster, affiliate_or_partner |
| `twitch.prediction.get` | `GET /predictions` | `channel:read:predictions` **OR** `channel:manage:predictions` | broadcaster, affiliate_or_partner |
| `twitch.poll.create` | `POST /polls` | `channel:manage:polls` | broadcaster, affiliate_or_partner |
| `twitch.poll.end` | `PATCH /polls` | `channel:manage:polls` | broadcaster, affiliate_or_partner |
| `twitch.prediction.create` | `POST /predictions` | `channel:manage:predictions` | broadcaster, affiliate_or_partner |
| `twitch.prediction.end` | `PATCH /predictions` | `channel:manage:predictions` | broadcaster, affiliate_or_partner |
| `twitch.raid.start` | `POST /raids` | `channel:manage:raids` | broadcaster, live |
| `twitch.raid.cancel` | `DELETE /raids` | `channel:manage:raids` | broadcaster |
| `twitch.reward.get` | `GET /channel_points/custom_rewards` | `channel:read:redemptions` **OR** `channel:manage:redemptions` | broadcaster, affiliate_or_partner |
| `twitch.reward.create` | `POST /channel_points/custom_rewards` | `channel:manage:redemptions` | broadcaster, affiliate_or_partner |
| `twitch.reward.update` | `PATCH /channel_points/custom_rewards` | `channel:manage:redemptions` | broadcaster, affiliate_or_partner, reward proof |
| `twitch.reward.delete` | `DELETE /channel_points/custom_rewards` | `channel:manage:redemptions` | broadcaster, affiliate_or_partner, reward proof |
| `twitch.redemption.get` | `GET /channel_points/custom_rewards/redemptions` | `channel:read:redemptions` **OR** `channel:manage:redemptions` | broadcaster, affiliate_or_partner, reward proof |
| `twitch.redemption.update` | `PATCH /channel_points/custom_rewards/redemptions` | `channel:manage:redemptions` | broadcaster, affiliate_or_partner, reward proof |
| `twitch.subscription.get` | `GET /subscriptions` | `channel:read:subscriptions` | broadcaster, affiliate_or_partner |
| `twitch.subscription.check` | `GET /subscriptions/user` | `user:read:subscriptions` | any, affiliate_or_partner |
| `twitch.bits.leaderboard.get` | `GET /bits/leaderboard` | `bits:read` | broadcaster |
| `twitch.bits.cheermotes.get` | `GET /bits/cheermotes` | No additional scope | any |
| `twitch.bits.powerups.get` | `GET /bits/custom_power_ups` | `bits:read` | broadcaster, affiliate_or_partner |
| `twitch.hype_train.get` | `GET /hypetrain/status` | `channel:read:hype_train` | broadcaster |
| `twitch.ads.schedule.get` | `GET /channels/ads` | `channel:read:ads` | broadcaster, affiliate_or_partner |
| `twitch.ads.snooze` | `POST /channels/ads/schedule/snooze` | `channel:manage:ads` | broadcaster, affiliate_or_partner |
| `twitch.ads.commercial.start` | `POST /channels/commercial` | `channel:edit:commercial` | broadcaster, affiliate_or_partner, live |
| `twitch.goals.get` | `GET /goals` | `channel:read:goals` | broadcaster |
| `twitch.charity.get` | `GET /charity/campaigns` | `channel:read:charity` | broadcaster |
| `twitch.charity.donations.get` | `GET /charity/donations` | `channel:read:charity` | broadcaster |
| `twitch.analytics.stream.snapshot` | `GET /streams` | No additional scope | broadcaster |
| `twitch.analytics.clips.snapshot` | `GET /clips` | No additional scope | broadcaster |
| `twitch.analytics.videos.snapshot` | `GET /videos` | No additional scope | broadcaster |
| `twitch.analytics.extension.get` | `GET /analytics/extensions` | `analytics:read:extensions` | broadcaster |
| `twitch.analytics.game.get` | `GET /analytics/games` | `analytics:read:games` | broadcaster |

<!-- REGISTRY_END -->
