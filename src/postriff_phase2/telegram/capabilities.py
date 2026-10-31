"""Destination rights are observations, never OAuth scopes or an E2E qualification."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    api: str
    layer: str = "bot"
    implemented: bool = True
    limitation: str = ""


CATALOG = {
    "identity": Capability("getChat/getChatMember"),
    "publish": Capability("sendMessage"),
    "text": Capability("sendMessage"), "photo": Capability("sendPhoto"),
    "text_formatting": Capability("MessageEntity/Telegram HTML/MarkdownV2", limitation="UTF16 structured entities; HTML is parsed server-side; MarkdownV2 supports an explicit strict subset."),
    "album": Capability("sendMediaGroup", limitation="2–10 items; audio and document albums must be homogeneous; no album keyboard."),
    "photo_album": Capability("sendMediaGroup/InputMediaPhoto"),
    "video_album": Capability("sendMediaGroup/InputMediaVideo"),
    "mixed_album": Capability("sendMediaGroup/InputMediaPhoto+InputMediaVideo"),
    "audio_album": Capability("sendMediaGroup/InputMediaAudio"),
    "document_album": Capability("sendMediaGroup/InputMediaDocument"),
    "live_photo_album": Capability("sendMediaGroup/InputMediaLivePhoto", limitation="Paired video/still dependencies for each Live Photo; requires separate real acceptance."),
    "video": Capability("sendVideo"), "animation": Capability("sendAnimation"),
    "live_photo": Capability("sendLivePhoto", limitation="Upload/file_id only; MPEG4 video at most 10 seconds/10 MB plus a still image; no URL input."),
    "audio": Capability("sendAudio"), "voice": Capability("sendVoice"),
    "video_note": Capability("sendVideoNote", limitation="Circular MPEG4, at most 60 seconds; no caption or URL input."),
    "document": Capability("sendDocument"), "poll": Capability("sendPoll/stopPoll", limitation="Unavailable in channel DM chats; question/option entities only custom emoji."),
    "location": Capability("sendLocation/editMessageLiveLocation/stopMessageLiveLocation", implemented=False),
    "venue": Capability("sendVenue", implemented=False),
    "link_preview": Capability("sendMessage.link_preview_options"),
    "buttons": Capability("InlineKeyboardMarkup", limitation="URL/copy text; Mini App only bot private chat. Payment/game/login/inline actions are disabled."),
    "custom_emoji": Capability("MessageEntity.custom_emoji", implemented=False, limitation="Bot ownership/Premium/Fragment eligibility must be independently verified."),
    "reply": Capability("ReplyParameters/message_thread_id/direct_messages_topic_id"),
    "comments_read": Capability("message/edited_message updates", limitation="Observed updates only; linked discussion-group access required; no Bot API history backfill."),
    "edit_own": Capability("editMessageText/editMessageCaption/editMessageMedia/editMessageReplyMarkup", limitation="Only recorded Rafii messages; media/album and Business edit restrictions apply."),
    "delete_own": Capability("deleteMessage/deleteBusinessMessages", limitation="Bot API ordinary messages generally under 48 hours; service/dice restrictions apply."),
    "pin": Capability("pinChatMessage/unpinChatMessage", limitation="Separate channel edit or group pin permission; unavailable for Business."),
    "topics": Capability("message_thread_id", limitation="Observed/manual verified topic IDs; Bot API has no enumerate-all-topics method."),
    "topic_management": Capability("createForumTopic/editForumTopic/closeForumTopic/reopenForumTopic", implemented=False),
    "schedule": Capability("Rafii immutable approval manifest + hosted worker", limitation="Rafii-managed; not Telegram-native scheduling."),
    "engagement": Capability("message_reaction/message_reaction_count/poll/poll_answer updates", limitation="Observed only, potentially delayed/incomplete; not channel view statistics."),
    "reactions": Capability("setMessageReaction + reaction updates", limitation="Bots cannot use paid reactions; custom emoji restricted to existing/allowed reactions."),
    "reaction_set": Capability("setMessageReaction", limitation="One ordinary emoji or removal; observed reaction updates require separate administrator access."),
    "business_messaging": Capability("getBusinessConnection/business_message + send methods", layer="business", limitation="can_reply; private chats with incoming activity in previous 24 hours."),
    "business_read": Capability("readBusinessMessage", layer="business", implemented=False),
    "channel_dm": Capability("direct_messages_topic_id", limitation="Channel's can_manage_direct_messages; an observed DM topic is required; no poll."),
    "suggested_posts": Capability("approveSuggestedPost/declineSuggestedPost", limitation="Only unpaid suggestions; paid Stars/TON approval is disabled."),
    "approve_suggested_post": Capability("approveSuggestedPost", limitation="Only unpaid suggestions; optional Telegram send_date; separate can_post_messages right."),
    "decline_suggested_post": Capability("declineSuggestedPost", limitation="Only unpaid suggestions; separate can_manage_direct_messages right."),
    "paid_media": Capability("sendPaidMedia", implemented=False, limitation="Monetization disabled pending transaction/product safeguards."),
    "native_schedule": Capability("messages.sendMessage.schedule_date/getScheduledHistory/editMessage/sendScheduledMessages/deleteScheduledMessages", implemented=False, layer="advanced", limitation="Optional connector; channel administrator plain-text schedules only; repeat intervals require Premium. Groups/topics use Rafii scheduling."),
    "detailed_analytics": Capability("stats.getBroadcastStats/getMegagroupStats/getMessageStats/getMessagePublicForwards", implemented=False, layer="advanced", limitation="Eligible administrator access; asynchronous graph loading is disabled."),
    "story_publish": Capability("stories.sendStory/editStory/deleteStories", layer="advanced", implemented=False, limitation="Explicit user-session consent, eligibility and boost/limit checks required."),
    "story_analytics": Capability("stats.getStoryStats/stories.getStoryViewsList", layer="advanced", implemented=False),
    "story_statistics_basic": Capability("stats.getStoryStats", implemented=False, layer="advanced", limitation="Basic native graph response only; no complete story dashboard/views-list implementation."),
    "business_stories": Capability("postStory/editStory/deleteStory", layer="business", implemented=False, limitation="BusinessBotRights.can_manage_stories; separate from channel Stories."),
    "telegraph": Capability("Telegraph createPage/editPage/getPage/getPageList/getViews", implemented=False, layer="telegraph", limitation="Separate public article and encrypted Telegraph grant; disabled pending real acceptance."),
    "forward": Capability("forwardMessage", limitation="Protected content and unsupported service/paid types cannot be forwarded."),
    "copy": Capability("copyMessage", limitation="Cannot copy service/paid/invoice messages; quiz correct answers must be known."),
    "ephemeral_messages": Capability("EphemeralMessageParameters/editEphemeralMessage*/deleteEphemeralMessage", implemented=False, limitation="New official API surface; outside durable publishing/receipt semantics."),
    "poll_media": Capability("InputPollMedia/InputPollOptionMedia", implemented=False),
    "rich_message": Capability("sendRichMessage/InputRichMessage", implemented=False, limitation="Bot API 10.3 rich blocks require a separate normalized model and receipt validator."),
    "sticker": Capability("sendSticker", implemented=False),
    "contact": Capability("sendContact", implemented=False),
    "business_checklist": Capability("sendChecklist/editMessageChecklist", layer="business", implemented=False),
    "managed_bot_administration": Capability("getManagedBotAccessSettings/setManagedBotAccessSettings", layer="managed", limitation="Separate verified OIDC owner and authenticated managed-bot event; exact encrypted access preview/confirmation. Never a destination publishing permission."),
    "guest_messaging": Capability("answerGuestQuery", implemented=False, limitation="Guest authorization is not a selected destination grant."),
    "communities": Capability("Community/ChatFullInfo.community", implemented=False, limitation="Metadata only; no implicit authority across linked chats."),
}

ALBUM_TYPES={'photo_album','video_album','mixed_album','audio_album','document_album','live_photo_album'}
SEND_TYPES = {"publish", "text", "text_formatting", "photo", "album", "video", "animation", "live_photo", "audio", "voice", "video_note", "document", "poll", "link_preview", "buttons", "reply", "schedule", "forward", "copy"} | ALBUM_TYPES
SEND_RIGHTS = {"photo": "can_send_photos", "video": "can_send_videos", "animation": "can_send_other_messages", "live_photo": "can_send_videos", "audio": "can_send_audios", "voice": "can_send_voice_notes", "video_note": "can_send_video_notes", "document": "can_send_documents", "poll": "can_send_polls"}
SEND_RIGHTS.update(photo_album='can_send_photos',video_album='can_send_videos',audio_album='can_send_audios',document_album='can_send_documents')


def destination_type(chat):
    if chat.get("is_direct_messages") is True:
        return "channel_dm"
    if chat.get("type") == "channel":
        return "public_channel" if chat.get("username") else "private_channel"
    if chat.get("type") == "supergroup":
        return "forum_supergroup" if chat.get("is_forum") else "supergroup"
    return {"group": "basic_group", "private": "user_dm"}.get(chat.get("type"), "unknown")


def provider_capabilities(provider, chat_id, mode="bot", business_id=None, *, workspace_id=None, actor_id=None):
    """Keep reviewed evidence distinct from a server-scoped owner canary grant."""
    candidate = getattr(provider, "candidate_capabilities", None)
    return {"qualified": provider.qualified(chat_id, mode, business_id),
            "candidate": candidate(chat_id, mode, business_id, workspace_id=workspace_id, actor_id=actor_id) if candidate else ()}


def compute(chat, member, *, mode="bot", qualified=(), candidate=(), business=None, incoming_at=None, now=0, implemented=None):
    """Availability = API ∩ layer ∩ destination ∩ actual rights ∩ code ∩ real acceptance.

    `qualified` is server-owned acceptance evidence, never a request/composer field.
    `candidate` permits an explicitly scoped owner canary to gather that evidence;
    it never marks a capability tested and never replaces fresh Telegram rights.
    Missing observations fail closed. `apiAvailable` does not mean Rafii supports it.
    """
    kind = destination_type(chat)
    status = member.get("status")
    admin = status in ("creator", "administrator")
    present = status in ("creator", "administrator", "member") or (status == "restricted" and member.get("is_member") is True)
    rights = member if admin or status == "restricted" else (chat.get("permissions") or {})
    channel = kind in ("public_channel", "private_channel")
    business = business or {}
    business_live = mode == "business" and business.get("is_enabled") is True
    business_rights = business.get("rights") or {}
    recent = type(incoming_at) in (int, float) and 0 <= now - incoming_at < 86400
    can_send = (business_live and business_rights.get("can_reply") is True and recent) if mode == "business" else (
        present and (rights.get("can_post_messages") is True if channel else
                     rights.get("can_manage_direct_messages") is True if kind == "channel_dm" else
                     admin or rights.get("can_send_messages") is True or kind == "user_dm"))
    values = {}
    for name, spec in CATALOG.items():
        code = spec.implemented if implemented is None else name in implemented
        layer_ok = spec.layer == mode or (mode == "business" and spec.layer == "bot")
        permitted = present if name == "identity" else can_send if name in SEND_TYPES else False
        missing = []
        if name in SEND_RIGHTS and not channel and not admin and mode == "bot" and kind != "user_dm":
            permitted = can_send and rights.get(SEND_RIGHTS[name]) is True
            if not permitted: missing.append(SEND_RIGHTS[name])
        if name == "album":
            permitted = can_send and (channel or admin or mode == "business" or kind == "user_dm" or any(rights.get(r) is True for r in ("can_send_photos", "can_send_videos",'can_send_audios','can_send_documents')))
        if name in ('mixed_album','live_photo_album'):
            permitted=can_send and (channel or admin or mode=='business' or kind=='user_dm' or all(rights.get(r) is True for r in ('can_send_photos','can_send_videos')))
        if name == "poll" and kind == "channel_dm": permitted = False
        if name == "edit_own": permitted = can_send
        if name == "delete_own":
            permitted = business_live and business_rights.get("can_delete_sent_messages") is True if mode == "business" else can_send
        if name == "pin":
            right = "can_edit_messages" if channel else "can_pin_messages"
            permitted = mode == "bot" and admin and rights.get(right) is True
            if not permitted: missing.append(right)
        if name == "topics": permitted = can_send and kind in ("forum_supergroup",) and mode == "bot"
        if name == "topic_management": permitted = admin and rights.get("can_manage_topics") is True
        if name in ("engagement", "reactions"): permitted = mode == "bot" and admin
        if name=='reaction_set': permitted=mode=='bot' and can_send
        if name == "comments_read": permitted = mode == "bot" and present and not channel
        if name == "channel_dm": permitted = mode == "bot" and kind == "channel_dm" and rights.get("can_manage_direct_messages") is True
        if name in ('suggested_posts','approve_suggested_post','decline_suggested_post'):
            approve=rights.get('can_post_messages') is True;decline=rights.get('can_manage_direct_messages') is True
            permitted=mode=='bot' and kind=='channel_dm' and (approve if name=='approve_suggested_post' else decline if name=='decline_suggested_post' else approve or decline)
        if name == "business_messaging": permitted = business_live and business_rights.get("can_reply") is True and recent
        if mode == 'business' and name in ('forward','copy','topics','channel_dm','suggested_posts','pin','engagement','reactions'): permitted = False
        if name == "business_stories": permitted = business_live and business_rights.get("can_manage_stories") is True
        if not code: state = "disabled"
        elif not layer_ok: state = "requires_" + spec.layer + "_connection"
        elif not permitted: state = "permission_required"
        elif name != "identity" and name not in qualified and name not in candidate: state = "requires_e2e"
        else: state = "available"
        values[name] = {"state": state, "apiAvailable": True, "implemented": code,
                        "e2eTested": name in qualified, "candidateExecution": name in candidate and name not in qualified,
                        "enabled": state == "available",
                        "api": spec.api, "connectionType": spec.layer, "missingRights": missing,
                        "limitation": spec.limitation}
    return values
