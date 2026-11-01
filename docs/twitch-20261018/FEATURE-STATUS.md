# Twitch capability status — G1 engineering candidate

Each **Verified** here means offline implementation and the named acceptance evidence. Live acceptance is **Unverified**, and public execution is **Blocked**. The native operation cases are not independent live integration tests.

## Native operations

| Action | Official request | Offline | Live | Public release |
| --- | --- | --- | --- | --- |
| `twitch.channel.get` | `GET /channels` | Verified | Unverified | Blocked |
| `twitch.channel.update` | `PATCH /channels` | Verified | Unverified | Blocked |
| `twitch.channel.editors.get` | `GET /channels/editors` | Verified | Unverified | Blocked |
| `twitch.channel.followers.get` | `GET /channels/followers` | Verified | Unverified | Blocked |
| `twitch.channel.followers.total` | `GET /channels/followers` | Verified | Unverified | Blocked |
| `twitch.stream.get` | `GET /streams` | Verified | Unverified | Blocked |
| `twitch.stream.key.get` | `GET /streams/key` | Verified | Unverified | Blocked |
| `twitch.category.search` | `GET /search/categories` | Verified | Unverified | Blocked |
| `twitch.channel.labels.get` | `GET /content_classification_labels` | Verified | Unverified | Blocked |
| `twitch.channel.search` | `GET /search/channels` | Verified | Unverified | Blocked |
| `twitch.channel.followed.get` | `GET /channels/followed` | Verified | Unverified | Blocked |
| `twitch.stream.followed.get` | `GET /streams/followed` | Verified | Unverified | Blocked |
| `twitch.profile.get` | `GET /users` | Verified | Unverified | Blocked |
| `twitch.profile.update` | `PUT /users` | Verified | Unverified | Blocked |
| `twitch.schedule.get` | `GET /schedule` | Verified | Unverified | Blocked |
| `twitch.schedule.calendar.get` | `GET /schedule/icalendar` | Verified | Unverified | Blocked |
| `twitch.schedule.settings.update` | `PATCH /schedule/settings` | Verified | Unverified | Blocked |
| `twitch.schedule.create` | `POST /schedule/segment` | Verified | Unverified | Blocked |
| `twitch.schedule.update` | `PATCH /schedule/segment` | Verified | Unverified | Blocked |
| `twitch.schedule.delete` | `DELETE /schedule/segment` | Verified | Unverified | Blocked |
| `twitch.marker.create` | `POST /streams/markers` | Verified | Unverified | Blocked |
| `twitch.marker.get` | `GET /streams/markers` | Verified | Unverified | Blocked |
| `twitch.chat.send` | `POST /chat/messages` | Verified | Unverified | Blocked |
| `twitch.chat.reply` | `POST /chat/messages` | Verified | Unverified | Blocked |
| `twitch.chat.chatters.get` | `GET /chat/chatters` | Verified | Unverified | Blocked |
| `twitch.chat.settings.get` | `GET /chat/settings` | Verified | Unverified | Blocked |
| `twitch.chat.settings.private.get` | `GET /chat/settings` | Verified | Unverified | Blocked |
| `twitch.chat.settings.update` | `PATCH /chat/settings` | Verified | Unverified | Blocked |
| `twitch.chat.announcement.send` | `POST /chat/announcements` | Verified | Unverified | Blocked |
| `twitch.chat.shoutout.send` | `POST /chat/shoutouts` | Verified | Unverified | Blocked |
| `twitch.chat.shared.get` | `GET /shared_chat/session` | Verified | Unverified | Blocked |
| `twitch.chat.pin.get` | `GET /chat/pins` | Verified | Unverified | Blocked |
| `twitch.chat.pin.create` | `PUT /chat/pins` | Verified | Unverified | Blocked |
| `twitch.chat.pin.update` | `PATCH /chat/pins` | Verified | Unverified | Blocked |
| `twitch.chat.pin.delete` | `DELETE /chat/pins` | Verified | Unverified | Blocked |
| `twitch.chat.message.delete` | `DELETE /moderation/chat` | Verified | Unverified | Blocked |
| `twitch.chat.clear` | `DELETE /moderation/chat` | Verified | Unverified | Blocked |
| `twitch.chat.emotes.get` | `GET /chat/emotes` | Verified | Unverified | Blocked |
| `twitch.chat.badges.get` | `GET /chat/badges` | Verified | Unverified | Blocked |
| `twitch.chat.emotes.global.get` | `GET /chat/emotes/global` | Verified | Unverified | Blocked |
| `twitch.chat.emotes.set.get` | `GET /chat/emotes/set` | Verified | Unverified | Blocked |
| `twitch.chat.emotes.user.get` | `GET /chat/emotes/user` | Verified | Unverified | Blocked |
| `twitch.chat.badges.global.get` | `GET /chat/badges/global` | Verified | Unverified | Blocked |
| `twitch.chat.color.get` | `GET /chat/color` | Verified | Unverified | Blocked |
| `twitch.chat.color.update` | `PUT /chat/color` | Verified | Unverified | Blocked |
| `twitch.chat.whisper.send` | `POST /whispers` | Verified | Unverified | Blocked |
| `twitch.moderation.ban` | `POST /moderation/bans` | Verified | Unverified | Blocked |
| `twitch.moderation.timeout` | `POST /moderation/bans` | Verified | Unverified | Blocked |
| `twitch.moderation.unban` | `DELETE /moderation/bans` | Verified | Unverified | Blocked |
| `twitch.moderation.banned.get` | `GET /moderation/banned` | Verified | Unverified | Blocked |
| `twitch.moderation.warn` | `POST /moderation/warnings` | Verified | Unverified | Blocked |
| `twitch.moderation.channels.get` | `GET /moderation/channels` | Verified | Unverified | Blocked |
| `twitch.moderation.moderators.get` | `GET /moderation/moderators` | Verified | Unverified | Blocked |
| `twitch.moderation.moderator.add` | `POST /moderation/moderators` | Verified | Unverified | Blocked |
| `twitch.moderation.vip.add` | `POST /channels/vips` | Verified | Unverified | Blocked |
| `twitch.moderation.moderator.remove` | `DELETE /moderation/moderators` | Verified | Unverified | Blocked |
| `twitch.moderation.vip.remove` | `DELETE /channels/vips` | Verified | Unverified | Blocked |
| `twitch.moderation.vips.get` | `GET /channels/vips` | Verified | Unverified | Blocked |
| `twitch.moderation.blocked_terms.get` | `GET /moderation/blocked_terms` | Verified | Unverified | Blocked |
| `twitch.moderation.blocked_terms.add` | `POST /moderation/blocked_terms` | Verified | Unverified | Blocked |
| `twitch.moderation.blocked_terms.remove` | `DELETE /moderation/blocked_terms` | Verified | Unverified | Blocked |
| `twitch.moderation.unban_requests.get` | `GET /moderation/unban_requests` | Verified | Unverified | Blocked |
| `twitch.moderation.unban_requests.resolve` | `PATCH /moderation/unban_requests` | Verified | Unverified | Blocked |
| `twitch.automod.settings.get` | `GET /moderation/automod/settings` | Verified | Unverified | Blocked |
| `twitch.automod.settings.update` | `PUT /moderation/automod/settings` | Verified | Unverified | Blocked |
| `twitch.automod.check` | `POST /moderation/enforcements/status` | Verified | Unverified | Blocked |
| `twitch.automod.message.resolve` | `POST /moderation/automod/message` | Verified | Unverified | Blocked |
| `twitch.shield.get` | `GET /moderation/shield_mode` | Verified | Unverified | Blocked |
| `twitch.shield.update` | `PUT /moderation/shield_mode` | Verified | Unverified | Blocked |
| `twitch.moderation.suspicious.add` | `POST /moderation/suspicious_users` | Verified | Unverified | Blocked |
| `twitch.moderation.suspicious.remove` | `DELETE /moderation/suspicious_users` | Verified | Unverified | Blocked |
| `twitch.moderation.user_blocks.get` | `GET /users/blocks` | Verified | Unverified | Blocked |
| `twitch.moderation.user_block.add` | `PUT /users/blocks` | Verified | Unverified | Blocked |
| `twitch.moderation.user_block.remove` | `DELETE /users/blocks` | Verified | Unverified | Blocked |
| `twitch.clip.get` | `GET /clips` | Verified | Unverified | Blocked |
| `twitch.clip.lookup` | `GET /clips` | Verified | Unverified | Blocked |
| `twitch.clip.create` | `POST /clips` | Verified | Unverified | Blocked |
| `twitch.clip.vod.create` | `POST /videos/clips` | Verified | Unverified | Blocked |
| `twitch.clip.download` | `GET /clips/downloads` | Verified | Unverified | Blocked |
| `twitch.video.get` | `GET /videos` | Verified | Unverified | Blocked |
| `twitch.video.delete` | `DELETE /videos` | Verified | Unverified | Blocked |
| `twitch.poll.get` | `GET /polls` | Verified | Unverified | Blocked |
| `twitch.prediction.get` | `GET /predictions` | Verified | Unverified | Blocked |
| `twitch.poll.create` | `POST /polls` | Verified | Unverified | Blocked |
| `twitch.poll.end` | `PATCH /polls` | Verified | Unverified | Blocked |
| `twitch.prediction.create` | `POST /predictions` | Verified | Unverified | Blocked |
| `twitch.prediction.end` | `PATCH /predictions` | Verified | Unverified | Blocked |
| `twitch.raid.start` | `POST /raids` | Verified | Unverified | Blocked |
| `twitch.raid.cancel` | `DELETE /raids` | Verified | Unverified | Blocked |
| `twitch.reward.get` | `GET /channel_points/custom_rewards` | Verified | Unverified | Blocked |
| `twitch.reward.create` | `POST /channel_points/custom_rewards` | Verified | Unverified | Blocked |
| `twitch.reward.update` | `PATCH /channel_points/custom_rewards` | Verified | Unverified | Blocked |
| `twitch.reward.delete` | `DELETE /channel_points/custom_rewards` | Verified | Unverified | Blocked |
| `twitch.redemption.get` | `GET /channel_points/custom_rewards/redemptions` | Verified | Unverified | Blocked |
| `twitch.redemption.update` | `PATCH /channel_points/custom_rewards/redemptions` | Verified | Unverified | Blocked |
| `twitch.subscription.get` | `GET /subscriptions` | Verified | Unverified | Blocked |
| `twitch.subscription.check` | `GET /subscriptions/user` | Verified | Unverified | Blocked |
| `twitch.bits.leaderboard.get` | `GET /bits/leaderboard` | Verified | Unverified | Blocked |
| `twitch.bits.cheermotes.get` | `GET /bits/cheermotes` | Verified | Unverified | Blocked |
| `twitch.bits.powerups.get` | `GET /bits/custom_power_ups` | Verified | Unverified | Blocked |
| `twitch.hype_train.get` | `GET /hypetrain/status` | Verified | Unverified | Blocked |
| `twitch.ads.schedule.get` | `GET /channels/ads` | Verified | Unverified | Blocked |
| `twitch.ads.snooze` | `POST /channels/ads/schedule/snooze` | Verified | Unverified | Blocked |
| `twitch.ads.commercial.start` | `POST /channels/commercial` | Verified | Unverified | Blocked |
| `twitch.goals.get` | `GET /goals` | Verified | Unverified | Blocked |
| `twitch.charity.get` | `GET /charity/campaigns` | Verified | Unverified | Blocked |
| `twitch.charity.donations.get` | `GET /charity/donations` | Verified | Unverified | Blocked |
| `twitch.analytics.stream.snapshot` | `GET /streams` | Verified | Unverified | Blocked |
| `twitch.analytics.clips.snapshot` | `GET /clips` | Verified | Unverified | Blocked |
| `twitch.analytics.videos.snapshot` | `GET /videos` | Verified | Unverified | Blocked |
| `twitch.analytics.extension.get` | `GET /analytics/extensions` | Verified | Unverified | Blocked |
| `twitch.analytics.game.get` | `GET /analytics/games` | Verified | Unverified | Blocked |

## EventSub (35 registered types)

| Type | Version | Offline transport and binding | Live | Public release |
| --- | --- | --- | --- | --- |
| `stream.online` | 1 | Verified | Unverified | Blocked |
| `stream.offline` | 1 | Verified | Unverified | Blocked |
| `channel.update` | 2 | Verified | Unverified | Blocked |
| `channel.follow` | 2 | Verified | Unverified | Blocked |
| `channel.chat.message` | 1 | Verified | Unverified | Blocked |
| `channel.chat.message_delete` | 1 | Verified | Unverified | Blocked |
| `channel.chat.clear` | 1 | Verified | Unverified | Blocked |
| `channel.chat.clear_user_messages` | 1 | Verified | Unverified | Blocked |
| `channel.chat.notification` | 1 | Verified | Unverified | Blocked |
| `channel.chat_settings.update` | 1 | Verified | Unverified | Blocked |
| `channel.ban` | 1 | Verified | Unverified | Blocked |
| `channel.unban` | 1 | Verified | Unverified | Blocked |
| `channel.subscribe` | 1 | Verified | Unverified | Blocked |
| `channel.subscription.end` | 1 | Verified | Unverified | Blocked |
| `channel.subscription.gift` | 1 | Verified | Unverified | Blocked |
| `channel.subscription.message` | 1 | Verified | Unverified | Blocked |
| `channel.cheer` | 1 | Verified | Unverified | Blocked |
| `channel.bits.use` | 1 | Verified | Unverified | Blocked |
| `channel.ad_break.begin` | 1 | Verified | Unverified | Blocked |
| `channel.poll.begin` | 1 | Verified | Unverified | Blocked |
| `channel.poll.progress` | 1 | Verified | Unverified | Blocked |
| `channel.poll.end` | 1 | Verified | Unverified | Blocked |
| `channel.prediction.begin` | 1 | Verified | Unverified | Blocked |
| `channel.prediction.progress` | 1 | Verified | Unverified | Blocked |
| `channel.prediction.lock` | 1 | Verified | Unverified | Blocked |
| `channel.prediction.end` | 1 | Verified | Unverified | Blocked |
| `channel.channel_points_custom_reward.add` | 1 | Verified | Unverified | Blocked |
| `channel.channel_points_custom_reward.update` | 1 | Verified | Unverified | Blocked |
| `channel.channel_points_custom_reward.remove` | 1 | Verified | Unverified | Blocked |
| `channel.channel_points_custom_reward_redemption.add` | 1 | Verified | Unverified | Blocked |
| `channel.channel_points_custom_reward_redemption.update` | 1 | Verified | Unverified | Blocked |
| `channel.shield_mode.begin` | 1 | Verified | Unverified | Blocked |
| `channel.shield_mode.end` | 1 | Verified | Unverified | Blocked |
| `automod.message.hold` | 2 | Verified | Unverified | Blocked |
| `automod.message.update` | 2 | Verified | Unverified | Blocked |

## Scope and remaining gates

Per-operation scope alternatives, subject/role/eligibility, live state, ownership, approval, workspace permission and purpose requirements are in `feature-status.json` and `native-api-sources.md`. Runtime availability uses actual grants and fresh context; this static table is not runtime authority.

OAuth, consent, queue, HTTP, UI and database boundaries have their separate receipts. A passing native request vector alone does not establish a complete live workflow.

General extension-backend JWT administration, Drops/game-organization entitlements and Guest Star beta need separate adapters and authorization. They are not implemented or accepted by this broadcaster integration; the full Twitch ecosystem is not declared complete.

Schedules do not start encoders. Full-VOD download/upload, arbitrary Channel Points grants, historical chat archives and Creator Dashboard revenue/watch-time/retention are not fabricated. See the unsupported-capability reasons and official source mapping.
