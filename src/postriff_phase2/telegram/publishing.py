"""One Bot API submission, receipt validation and zero blind retry after ambiguity."""
import copy
import re
import time
from postriff_alpha.domain import AlphaError
from .capabilities import compute, destination_type, provider_capabilities
from .content import keyboard, normalize, fail

METHODS = {"text": ("sendMessage", "text"), "photo": ("sendPhoto", "photo"), "video": ("sendVideo", "video"),
           "animation": ("sendAnimation", "animation"), "audio": ("sendAudio", "audio"), "voice": ("sendVoice", "voice"),
           "video_note": ("sendVideoNote", "video_note"), "document": ("sendDocument", "document"),
           "live_photo": ("sendLivePhoto", "live_photo"), "album": ("sendMediaGroup", "media"), "poll": ("sendPoll", "poll")}
MEDIA_OPTIONS = {"photo": {"has_spoiler", "show_caption_above_media"},
                 "video": {"duration", "width", "height", "supports_streaming", "start_timestamp", "has_spoiler", "show_caption_above_media", "useThumbnail", "coverFile"},
                 "animation": {"duration", "width", "height", "has_spoiler", "show_caption_above_media", "useThumbnail"},
                 "live_photo": {"has_spoiler", "show_caption_above_media"},
                 "audio": {"duration", "performer", "title"}, "voice": {"duration"}, "video_note": {"duration", "length", "useThumbnail"}, "document": set()}


def deep_link(chat, message_id, thread_id=None):
    username = chat.get("username")
    if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{4,32}", username):
        return f"https://t.me/{username}/{message_id}"
    cid = str(chat.get("id", ""))
    if chat.get("type") in ("channel", "supergroup") and re.fullmatch(r"-100[0-9]+", cid):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


def snapshot(provider, session):
    chat = provider.call("getChat", {"chat_id": session["chat"]})
    member = provider.call("getChatMember", {"chat_id": session["chat"], "user_id": provider.me()["id"]})
    if not isinstance(chat, dict) or chat.get("id") != session["chat"] or not isinstance(member, dict):
        raise AlphaError("Telegram destination could not be verified.", 409, code="telegram_permission_required")
    if chat.get("is_direct_messages"):
        parent = chat.get("parent_chat")
        if not isinstance(parent, dict) or type(parent.get("id")) is not int:
            raise AlphaError("Telegram did not identify the parent channel.", 409)
        member = provider.call("getChatMember", {"chat_id": parent["id"], "user_id": provider.me()["id"]})
    return chat, member


def asset_bytes(host, manifest, asset):
    if host.assets is None: raise AlphaError("Media storage is unavailable.", 503)
    category = "video" if str(asset.get("mime", "")).startswith("video/") else "media"
    if category == "video":
        raw = host.assets.storage.get_verified_video(manifest["workspaceId"], asset.get("objectName") or asset["id"],
              expected_bytes=asset.get("bytes"), expected_mime=asset.get("mime"), expected_etag=asset.get("etag"))
    else:
        raw = host.assets.storage.get(manifest["workspaceId"], category, asset.get("objectName") or asset["id"])
    if not isinstance(raw, bytes) or len(raw) != asset.get("bytes"):
        raise AlphaError("The approved media dependency changed.", 409)
    # Approved hashes are checked again at the storage boundary, not only in workspace state.
    import hashlib
    if hashlib.sha256(raw).hexdigest() != asset.get("hash"):
        raise AlphaError("The approved media hash changed.", 409)
    return raw


def payload(manifest, session, chat, host, *, file_check=None):
    options = normalize(manifest.get("publishOptions"), manifest.get("media", []), manifest["payload"]["text"])["telegram"]
    kind = options["format"]
    mode = "business" if session.get("business_connection_id") else "bot"
    chat_kind = destination_type(chat)
    body = {"chat_id": session["chat"]}
    if mode == "business": body["business_connection_id"] = session["business_connection_id"]
    thread = options.get("messageThreadId")
    dm_topic = options.get("directMessagesTopicId")
    if session.get("thread") and not thread: fail("Approve this post again with its forum topic selected.")
    if session.get("dm_topic") and not dm_topic: fail("Approve this post again with its DM topic selected.")
    if chat_kind == "forum_supergroup" and not thread: fail("Select a verified forum topic before publishing.")
    if thread:
        if chat_kind != "forum_supergroup" and not (chat_kind == "user_dm" and chat.get("is_forum")): fail("This destination has no forum-topic surface.")
        if session.get("thread") and session["thread"] != thread: fail("The approved target differs from this connected topic.")
        body["message_thread_id"] = thread
    if chat_kind == "channel_dm":
        if not dm_topic or kind == "poll": fail("Channel DMs need a verified DM topic and cannot receive polls.")
        if session.get("dm_topic") and session["dm_topic"] != dm_topic: fail("The selected DM topic changed.")
        body["direct_messages_topic_id"] = dm_topic
    elif dm_topic: fail("DM topics are only valid for channel direct-message chats.")
    if options.get("replyToMessageId"):
        body["reply_parameters"] = {"message_id": options["replyToMessageId"], "allow_sending_without_reply": False}
    if "silent" in options: body["disable_notification"] = options["silent"]
    if "protectContent" in options: body["protect_content"] = options["protectContent"]
    if "buttons" in options: body["reply_markup"] = keyboard(options["buttons"], destination=chat_kind, business=mode == "business")
    if "linkPreview" in options: body["link_preview_options"] = options["linkPreview"]
    text, es = options["text"], options["entities"]
    if kind == "text": body.update(text=text, entities=es)
    elif kind == "poll":
        body.update(options["poll"])
        if body.get("close_date") and not 5 <= body["close_date"] - time.time() <= 2628000: fail("The poll close date expired or is too far in the future.")
        if chat_kind not in ("public_channel", "private_channel") and any(k in body for k in ("members_only", "country_codes")): fail("Poll member/country restrictions are channel-only.")
    elif kind != "video_note": body.update(caption=text, caption_entities=es)
    mo = options.get("mediaOptions", {})
    live_video_indexes={d['sourceIndex'] for d in mo.get('albumItems',[]) if d['type']=='live_photo'}
    if kind != "album" and set(mo) - MEDIA_OPTIONS.get(kind, set()): fail("Media metadata does not apply to this message format.")
    files, sources = [], []
    for i, asset in enumerate(manifest.get("media", [])):
        mime = str(asset.get("mime") or "")
        source_kind = "video" if mime.startswith("video/") else "photo" if mime.startswith("image/") else None
        if not source_kind: fail("This file type needs a verified Telegram file import.")
        if kind == "photo" and source_kind != "photo": fail("Photos require an image.")
        if kind in ("video", "animation", "video_note") and mime != "video/mp4": fail("Telegram video formats require verified MPEG4.")
        if kind == 'album' and source_kind=='video' and mime!='video/mp4': fail('Telegram video albums require verified MPEG4.')
        if (kind=='live_photo' and source_kind=='video') or i in live_video_indexes:
            if mime!='video/mp4' or not 0<asset.get('duration',0)<=10 or asset.get('bytes',0)>10*1024*1024:
                fail('Live Photo videos require MPEG4, at most 10 seconds and 10 MB.')
        if kind == "photo" or (kind in ("album","live_photo") and source_kind == "photo"):
            if asset.get("bytes", 0) > 10 * 1024 * 1024 or asset.get("width", 0) + asset.get("height", 0) > 10000 or min(asset.get("width", 0), asset.get("height", 0)) <= 0 or max(asset["width"], asset["height"]) / min(asset["width"], asset["height"]) > 20:
                fail("Telegram photos allow 10 MB, a dimension sum of 10000 and an aspect ratio at most 20.")
        elif asset.get("bytes", 0) > 50 * 1024 * 1024: fail("Telegram hosted Bot API uploads allow at most 50 MB for this format.")
        if kind == "video_note" and (asset.get("duration", 0) > 60 or asset.get("width") != asset.get("height")): fail("Video Notes require a square MPEG4 video no longer than 60 seconds.")
        name = f"media_{i}"
        raw = asset_bytes(host, manifest, asset)
        files.append((name, name + (".mp4" if source_kind == "video" else ".jpg"), mime, raw))
        sources.append({"input": "attach://" + name, "kind": source_kind, "assetId": asset["id"]})
    for f in options.get("fileIds", []):
        if not file_check or not file_check(manifest["workspaceId"], f, session): fail("The Telegram file is not recorded for this workspace and bot.")
        sources.append({"input": f["fileId"], "kind": 'video' if f['kind']=='live_photo' and (kind=='live_photo' or kind=='album') else f["kind"], "recordId": f["recordId"]})
    if kind == "album":
        album_kinds = mo.get("albumKinds")
        if album_kinds is not None and (not isinstance(album_kinds, list) or len(album_kinds) != len(sources)): fail("Choose one media type per album item.")
        descriptors = mo.get('albumItems') or [{'type': album_kinds[i] if album_kinds else s['kind'], 'sourceIndex': i} for i,s in enumerate(sources)]
        types = [d['type'] for d in descriptors]
        if any(t not in ("photo", "video", "audio", "document", "live_photo") for t in types): fail("This message type cannot be put in a media group.")
        if any(t == "audio" for t in types) and set(types) != {"audio"}: fail("Audio albums contain only audio.")
        if any(t == "document" for t in types) and set(types) != {"document"}: fail("Document albums contain only documents.")
        allowed = {"albumKinds", "albumItems", "has_spoiler", "show_caption_above_media"}
        if set(mo) - allowed: fail("Unsupported album metadata.")
        items = []
        for i, descriptor in enumerate(descriptors):
            source = sources[descriptor['sourceIndex']]
            if types[i] == 'live_photo':
                if source['kind'] != 'video' or sources[descriptor['photoIndex']]['kind'] != 'photo': fail("A Live Photo album item requires video and still-photo dependencies.")
            elif types[i] != source["kind"] and types[i] != "document": fail("Album media type differs from the approved file.")
            item = {"type": types[i], "media": source["input"]}
            if types[i] == 'live_photo': item['photo'] = sources[descriptor['photoIndex']]['input']
            if i == 0: item.update(caption=text, caption_entities=es)
            if types[i] in ("photo", "video", "live_photo"):
                item.update({k: v for k, v in mo.items() if k in ("has_spoiler", "show_caption_above_media")})
            items.append(item)
        body.pop("caption", None); body.pop("caption_entities", None); body["media"] = items
    elif kind == "live_photo":
        if sorted(s["kind"] for s in sources) != ["photo", "video"]: fail("A Live Photo requires a still image and short video.")
        body["live_photo"] = next(s["input"] for s in sources if s["kind"] == "video")
        body["photo"] = next(s["input"] for s in sources if s["kind"] == "photo")
        body.update(mo)
    elif kind not in ("text", "poll"):
        if sources[0]["kind"] != kind and kind not in ("animation", "video_note", "document"): fail("The recorded file type differs from this Telegram format.")
        body[METHODS[kind][1]] = sources[0]["input"]
        body.update({k:v for k,v in mo.items() if k not in ('useThumbnail','coverFile')})
        if mo.get('coverFile'):
            cover = mo['coverFile']
            if not file_check or not file_check(manifest['workspaceId'],cover,session): fail("The video cover is not recorded for this workspace and bot.")
            body['cover'] = cover['fileId']
        if mo.get('useThumbnail'):
            if not manifest.get('media') or sources[0]['input'][:9] != 'attach://': fail("Telegram thumbnails require a new upload with a verified video poster.")
            poster = manifest['media'][0].get('poster')
            if not isinstance(poster,dict): fail("No verified poster is available for this video.")
            raw = host.assets.storage.get(manifest['workspaceId'],'media',poster['objectName'])
            import hashlib, io
            from PIL import Image
            if len(raw) != poster['bytes'] or hashlib.sha256(raw).hexdigest() != poster['hash']: fail("The approved video poster changed.")
            with Image.open(io.BytesIO(raw)) as im:
                im = im.convert('RGB'); im.thumbnail((320,320)); out = io.BytesIO(); im.save(out,format='JPEG',quality=75)
            if len(out.getvalue()) > 200000: fail("Telegram thumbnail exceeds 200 KB.")
            files.append(('thumbnail','thumbnail.jpg','image/jpeg',out.getvalue())); body['thumbnail']='attach://thumbnail'
    return METHODS[kind][0], body, files, options


def receipt(response, chat_id, method, expected, body):
    data = response.get("body") if isinstance(response, dict) and isinstance(response.get("body"), dict) else {}
    if response.get("status") != 200 or data.get("ok") is not True:
        code = data.get("error_code", response.get("status"))
        if code in (400, 401, 403):
            return {"state": "held" if code in (401, 403) else "failed", "confirmed": "Telegram rejected the request before acceptance; review payload, connection and permissions."}
        if code == 429:
            retry = (data.get("parameters") or {}).get("retry_after")
            return {"state": "scheduled", "confirmed": "Telegram rate limited the request before acceptance.", "retryAfter": retry if type(retry) is int and 0 < retry <= 86400 else 60}
        return {"state": "uncertain", "confirmed": "Telegram outcome is unknown. Inspect this destination; do not retry the create operation."}
    result = data.get("result")
    messages = result if isinstance(result, list) else [result]
    required = len(body.get("media", [])) if method == "sendMediaGroup" else 1
    if len(messages) != required or any(not isinstance(m, dict) or type(m.get("message_id")) is not int or m["message_id"] <= 0 or (m.get("chat") or {}).get("id") != chat_id or type(m.get("date")) is not int for m in messages):
        return {"state": "uncertain", "confirmed": "Telegram returned an incomplete or mismatched Message receipt. Do not retry an album or post."}
    if len({m["message_id"] for m in messages}) != required:
        return {"state": "uncertain", "confirmed": "Telegram returned duplicate album identifiers; reconcile without resubmission."}
    if method == "sendMediaGroup" and (not all(m.get("media_group_id") for m in messages) or len({m["media_group_id"] for m in messages}) != 1):
        return {"state": "uncertain", "confirmed": "Telegram did not confirm the entire media group. Do not split or retry it."}
    first = messages[0]
    content_ok = first.get("text") == expected["text"] if method == "sendMessage" else first.get("poll", {}).get("question") == expected["poll"]["question"] if method == "sendPoll" else True if method == "sendVideoNote" else first.get("caption", "") == expected["text"]
    if method == 'sendMediaGroup':
        if any(not m.get(i['type']) for m,i in zip(messages,body['media'])): content_ok=False
    elif method not in ('sendMessage','sendPoll'):
        returned_field = METHODS[expected['format']][1]
        if not first.get(returned_field): content_ok=False
    if method == 'sendPoll':
        returned_poll = first.get('poll',{})
        if [o.get('text') for o in returned_poll.get('options',[])] != [o['text'] for o in expected['poll']['options']]: content_ok=False
        for key in ('type','is_anonymous','allows_multiple_answers','allows_revoting','shuffle_options','allow_adding_options','hide_results_until_closes'):
            if key in expected['poll'] and returned_poll.get(key) != expected['poll'][key]: content_ok=False
    if body.get("message_thread_id") and any(m.get("message_thread_id") != body["message_thread_id"] for m in messages): content_ok = False
    for field in ("text", "caption"):
        source = body['media'][0] if method == 'sendMediaGroup' else body
        requested = source.get("entities" if field == "text" else "caption_entities", [])
        returned = first.get("entities" if field == "text" else "caption_entities", [])
        if any(e not in returned for e in requested): content_ok = False
    if body.get("direct_messages_topic_id") and any((m.get("direct_messages_topic") or {}).get("topic_id") != body["direct_messages_topic_id"] for m in messages): content_ok = False
    if body.get('reply_parameters') and (first.get('reply_to_message') or {}).get('message_id') != body['reply_parameters']['message_id']: content_ok=False
    records = [{"chatId": chat_id, "messageId": m["message_id"], "date": m["date"], "editDate": m.get("edit_date"), "mediaGroupId": m.get("media_group_id"), "messageThreadId": m.get("message_thread_id"), "directMessagesTopicId": (m.get("direct_messages_topic") or {}).get("topic_id"), "url": deep_link(m["chat"], m["message_id"])} for m in messages]
    outcome = {"state": "verified" if content_ok else "published", "reference": f"{chat_id}/{first['message_id']}", "verification": "provider_receipt", "confirmed": "Telegram returned the created Message receipt." if content_ok else "Telegram created messages, but content/thread differs from approval. Review; do not resubmit.",
               "telegram": {"version": 1, "apiPath": "Bot API/" + method, "messages": records, "payload": copy.deepcopy(body)}, "_telegramMessages": messages}
    if records[0]["url"]: outcome["url"] = records[0]["url"]
    return outcome


def submit(manifest, provider, token, host):
    return _submit(manifest, provider, token, host)


def _submit(manifest, provider, token, host):
    session = provider.session(token)
    if session.get("workspace") and session["workspace"] != manifest["workspaceId"]:
        return {"state": "held", "confirmed": "Telegram credential does not belong to this workspace."}
    provider = provider.for_session(session)
    try:
        if session.get('parentConnectionId') and (not getattr(provider,'destination_authorizer',None) or not provider.destination_authorizer(manifest['workspaceId'],session)):
            return {'state':'held','confirmed':'The parent channel grant was revoked. Reauthorize this Channel DM topic.'}
        if session.get("business_connection_id"):
            if not provider.business_resolver: raise AlphaError("Business connection unavailable.", 409)
            _, chat, incoming_at = provider.business_resolver(manifest["workspaceId"], session["business_connection_id"], session["chat"])
            member = {"status": "member"}
        else:
            chat, member = snapshot(provider, session)
            incoming_at = None
        opts = normalize(manifest.get("publishOptions"), manifest.get("media", []), manifest["payload"]["text"])["telegram"]
        mode = "business" if session.get("business_connection_id") else "bot"
        business = provider.call("getBusinessConnection", {"business_connection_id": session["business_connection_id"]}) if mode == "business" else None
        caps = compute(chat, member, mode=mode, **provider_capabilities(provider, session["chat"], mode, session.get("business_connection_id"), workspace_id=manifest["workspaceId"], actor_id=manifest.get('actor')), business=business,
                       incoming_at=incoming_at, now=time.time())
        required = {opts["format"], "publish"}
        if opts['format']=='album':
            source_types=['video' if str(a.get('mime','')).startswith('video/') else 'photo' for a in manifest.get('media',[])]+['video' if f['kind']=='live_photo' else f['kind'] for f in opts.get('fileIds',[])]
            mo=opts.get('mediaOptions',{})
            kinds={d['type'] for d in mo['albumItems']} if mo.get('albumItems') else set(mo.get('albumKinds') or source_types)
            if not kinds or not kinds <= {'photo','video','audio','document','live_photo'}: fail('This message type cannot be put in a Telegram media group.')
            required.add('live_photo_album' if 'live_photo' in kinds else next(iter(kinds))+'_album' if len(kinds)==1 else 'mixed_album')
        if opts.get("buttons"): required.add("buttons")
        if opts.get("linkPreview"): required.add("link_preview")
        if any(i.get('type') == 'live_photo' for i in opts.get('mediaOptions', {}).get('albumItems', [])): required.add('live_photo')
        if opts.get("entities"): required.add("text_formatting")
        if any(e["type"] == "custom_emoji" for e in opts.get("entities", [])): required.add("custom_emoji")
        poll_entity_sets = [opts.get('poll', {}).get(k, []) for k in ('question_entities','explanation_entities','description_entities')] + [o.get('text_entities',[]) for o in opts.get('poll',{}).get('options',[])]
        if any(e.get('type')=='custom_emoji' for es in poll_entity_sets for e in es): required.add('custom_emoji')
        if opts.get("replyToMessageId"): required.add("reply")
        if opts.get("messageThreadId") or session.get("thread"): required.add("topics")
        if chat.get("is_direct_messages"): required.add("channel_dm")
        if any(caps[k]["state"] != "available" for k in required):
            reasons = ", ".join(f"{k}: {caps[k]['state']}" for k in sorted(required) if caps[k]["state"] != "available")
            return {"state": "held", "confirmed": "Telegram capability unavailable: " + reasons}
        method, body, files, expected = payload(manifest, session, chat, host, file_check=getattr(provider, "file_check", None))
    except AlphaError as e:
        return {"state": "held" if e.code != "telegram_payload_invalid" else "failed", "confirmed": str(e)}
    try:
        response = provider.request(method, body, files=files) if files else provider.request(method, body)
    except Exception:
        # Tokens appear in Telegram request URLs. Never propagate transport exception text.
        return {"state": "uncertain", "confirmed": "Telegram transport outcome is unknown. Reconcile before any retry."}
    outcome = receipt(response, session["chat"], method, expected, body)
    outcome['_telegramBotId'] = provider.me()['id']
    return outcome
