"""Bounded canonical provider options and immutable ordered media selection."""
import json
import re
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError
from . import asset_kinds

VIDEO_PLATFORMS = ("LinkedIn", "Threads", "Instagram", "Facebook", "X", "YouTube", "TikTok", "Pinterest", "Douyin", "Kuaishou")
MULTI_LIMITS = {"LinkedIn": 20, "Threads": 20, "Instagram": 10, "Facebook": 10, "X": 4, "TikTok": 35}


def web_url(value):
    try: p = urlsplit(value)
    except (TypeError, ValueError): raise AlphaError("Use a valid HTTPS destination URL.", 400)
    if (not isinstance(value, str) or len(value) > 2048 or p.scheme != "https" or not p.hostname
            or p.username or p.password or any(ord(c) < 32 for c in value)):
        raise AlphaError("Use a valid HTTPS destination URL.", 400)
    return value


def ordered_media(assets, payload, platform):
    ids = payload.get("assetIds")
    if ids is None: ids = [payload["assetId"]] if payload.get("assetId") else []
    if not isinstance(ids, list) or len(ids) > MULTI_LIMITS.get(platform, 1) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise AlphaError("Choose unique media in the approved order within this platform's limit.", 400)
    result = []
    for identifier in ids:
        asset = next((a for a in assets if a.get("id") == identifier), None)
        if asset is None or payload.get("rightsConfirmed") is not True:
            raise AlphaError("Media unavailable or rights not confirmed.", 409)
        kind = asset_kinds.kind_of(asset)
        if kind == "video":
            if platform not in VIDEO_PLATFORMS or not asset_kinds.is_postable_video(asset):
                raise AlphaError("A verified video is required.", 409)
            fields = ("id", "hash", "mime", "bytes", "width", "height", "duration", "durationSource", "bucket", "objectName", "etag", "verified")
            media = {k: asset[k] for k in fields}
            media["alt"] = ""
            if platform == 'Pinterest':
                poster = asset.get('poster')
                if not isinstance(poster, dict) or not all(k in poster for k in ('objectName','hash','width','height','bytes')):
                    raise AlphaError('A Pinterest video needs its immutable verified cover frame.',409)
                media['poster'] = {k:poster[k] for k in ('objectName','hash','width','height','bytes')}
        elif kind == "document":
            if platform != "LinkedIn" or not asset_kinds.is_ready(asset):
                raise AlphaError("This destination does not accept the verified document.", 409)
            media = {k: asset[k] for k in ("id", "hash", "mime", "bytes", "pages", "objectName")}
            media["alt"] = ""
        elif kind == "image":
            if asset.get('mime') == 'image/gif' and (platform != 'X' or len(ids) != 1):
                raise AlphaError('Rafii preserves GIF animation for one X attachment. Other destinations require a static image.', 409)
            alt = (payload.get("mediaAlt") or {}).get(identifier, payload.get("alt", ""))
            if not asset_kinds.is_postable_image(asset) or not isinstance(alt, str) or not 1 <= len(alt.strip()) <= 1000:
                raise AlphaError("Decoded image, alt text and rights confirmation are required.", 409)
            if platform in ("YouTube", "Douyin", "Kuaishou"):
                raise AlphaError("This destination requires a video.", 409)
            if platform == "Instagram" and (payload.get("publishOptions") or {}).get("format") != "story" and not 0.8 <= asset["width"]/asset["height"] <= 1.91:
                raise AlphaError("Instagram feed images must have an aspect ratio from 4:5 to 1.91:1.", 409)
            media = {k: asset[k] for k in ("id", "hash", "sourceHash", "mime", "bytes", "width", "height", "duration")}
            if asset.get("objectName"): media["objectName"] = asset["objectName"]
            media["alt"] = alt.strip()
        else: raise AlphaError("Unsupported media format.", 409)
        media["rightsConfirmed"] = True
        result.append(media)
    if len(result) > 1 and platform in ("LinkedIn", "Facebook", "X", "TikTok") and any(not str(a["mime"]).startswith("image/") for a in result):
        raise AlphaError("This destination accepts multiple images, or one video/document.", 409)
    if platform in ("Instagram", "Pinterest") and not result:
        raise AlphaError("This destination requires approved media.", 409)
    if platform == 'TikTok' and any((a['mime'].startswith('video/') and (min(a['width'],a['height']) < 360 or max(a['width'],a['height']) > 4096)) or (a['mime'].startswith('image/') and (a['mime'] not in ('image/jpeg','image/webp') or a['bytes'] > 20_000_000 or min(a['width'],a['height']) > 1080 or max(a['width'],a['height']) > 1920)) for a in result):
        raise AlphaError('TikTok requires video dimensions 360–4096 pixels; photos must be JPEG/WebP up to 20 MB and fit 1080p.',409)
    if platform == 'X' and any(a['mime'].startswith('video/') and (a['duration'] > 140 or a['mime'] != 'video/mp4') or a['mime'] == 'image/jpeg' and a['bytes'] > 5_000_000 for a in result):
        raise AlphaError('Rafii uses the standard X limits: JPEG up to 5 MB, or MP4 up to 140 seconds. Extended-video eligibility is not assumed.', 409)
    return result


def options(platform, value, media, text):
    value = {} if value is None else value
    if not isinstance(value, dict): raise AlphaError("Choose valid publishing options.", 400)
    allowed = {
        'LinkedIn': {'destinationType', 'authorUrn', 'title', 'description', 'link', 'poll'},
        'Threads': {'reply_to_id', 'quote_post_id', 'reply_control', 'topic_tag', 'link_attachment', 'poll_attachment', 'text_attachment', 'is_ghost_post', 'gif_attachment', 'location_id', 'text_entities', 'is_spoiler_media', 'enable_reply_approvals'},
        'Instagram': {'format'}, 'Facebook': {'format', 'link', 'scheduledPublishTime'},
        'X': {'replyToId', 'quoteId', 'poll', 'thread'},
    }
    if set(value) - allowed.get(platform, set()): raise AlphaError('Unsupported publishing option.', 400)
    if platform == "LinkedIn":
        result = {"destinationType": value.get("destinationType", "member")}
        if result["destinationType"] not in ("member", "organization"): raise AlphaError("Choose member or organization.", 400)
        if value.get("authorUrn"):
            pattern = r"urn:li:organization:\d+" if result["destinationType"] == "organization" else r"urn:li:person:[A-Za-z0-9_-]+"
            if not re.fullmatch(pattern, str(value["authorUrn"])): raise AlphaError("Invalid LinkedIn destination URN.", 400)
            result["authorUrn"] = value["authorUrn"]
        elif result["destinationType"] == "organization": raise AlphaError("Choose an authorized organization.", 400)
        for key, limit in (("title", 200), ("description", 500)):
            if key in value:
                if not isinstance(value[key], str) or len(value[key]) > limit: raise AlphaError("LinkedIn metadata is too long.", 400)
                result[key] = value[key]
        if value.get("link"):
            if media or value.get("poll"): raise AlphaError("Choose one LinkedIn content type.", 400)
            if not result.get('title', '').strip():
                raise AlphaError('A LinkedIn link post needs an explicit title. Rafii does not scrape the destination.', 400)
            result["link"] = web_url(value["link"])
        if value.get("poll"):
            poll = value["poll"]
            if (media or not isinstance(poll, dict) or not isinstance(poll.get("question"), str) or not 1 <= len(poll["question"]) <= 140
                    or not isinstance(poll.get("options"), list) or not 2 <= len(poll["options"]) <= 4
                    or any(not isinstance(o, dict) or not isinstance(o.get("text"), str) or not 1 <= len(o["text"]) <= 30 for o in poll["options"])):
                raise AlphaError("LinkedIn polls need a question and 2–4 options.", 400)
            duration = (poll.get("settings") or {}).get("duration")
            if duration not in ("ONE_DAY", "THREE_DAYS", "SEVEN_DAYS", "FOURTEEN_DAYS"): raise AlphaError("Choose a supported poll duration.", 400)
            result["poll"] = {"question": poll["question"], "options": [{"text": o["text"]} for o in poll["options"]], "settings": {"duration": duration, "voteSelectionType": "SINGLE_VOTE"}}
        return result
    if platform == "Instagram":
        form = value.get("format", "carousel" if len(media) > 1 else "reel" if media and media[0]["mime"].startswith("video/") else "image")
        if form not in ("image", "carousel", "reel", "story"): raise AlphaError("Choose image, carousel, reel or story.", 400)
        if form == "carousel" and not 2 <= len(media) <= 10: raise AlphaError("Instagram API carousels need 2–10 media items.", 400)
        if form != "carousel" and len(media) != 1: raise AlphaError("Choose one media item.", 400)
        if form == "reel" and not media[0]["mime"].startswith("video/"): raise AlphaError("A Reel needs video.", 400)
        if form == "image" and not media[0]["mime"].startswith("image/"): raise AlphaError("An image post needs an image.", 400)
        if form == "story" and len(text) > 0: raise AlphaError("The current Story API does not accept this caption; review without a caption.", 409)
        return {"format": form}
    if platform == "Threads":
        result = {}
        for flag in ('is_spoiler_media','enable_reply_approvals'):
            if flag in value:
                if type(value[flag]) is not bool: raise AlphaError('Choose a valid Threads setting.',400)
                if flag == 'is_spoiler_media' and not media: raise AlphaError('A media spoiler requires media.',400)
                result[flag] = str(value[flag]).lower()
        if 'location_id' in value:
            if not re.fullmatch(r'\d{1,30}',str(value['location_id'])): raise AlphaError('Choose a provider-native Threads location.',400)
            result['location_id'] = value['location_id']
        if 'gif_attachment' in value:
            gif = value['gif_attachment']
            if media or value.get('poll_attachment') or value.get('link_attachment') or not isinstance(gif,dict) or set(gif) != {'gif_id','provider'} or gif.get('provider') != 'TENOR' or not re.fullmatch(r'\d{1,30}',str(gif.get('gif_id',''))): raise AlphaError('A Threads GIF attachment requires a Tenor ID on a text post.',400)
            result['gif_attachment'] = json.dumps(gif,separators=(',',':'))
        if 'text_entities' in value:
            entities = value['text_entities']
            if not isinstance(entities,list) or not 1 <= len(entities) <= 20 or any(not isinstance(e,dict) or set(e) != {'entity_type','offset','length'} or e.get('entity_type') != 'SPOILER' or type(e.get('offset')) is not int or type(e.get('length')) is not int or not 0 <= e['offset'] < e['offset']+e['length'] <= len(text.encode('utf-16-le'))//2 for e in entities): raise AlphaError('Review valid Threads spoiler offsets and lengths in UTF-16 units.',400)
            result['text_entities'] = json.dumps(entities,separators=(',',':'))
        for key in ("reply_to_id", "quote_post_id"):
            if key in value:
                if not re.fullmatch(r"\d{1,30}", str(value[key])): raise AlphaError("Choose a valid parent/quote ID.", 400)
                result[key] = value[key]
        if "reply_control" in value:
            if value["reply_control"] not in ("everyone", "accounts_you_follow", "mentioned_only", "parent_post_author_only", "followers_only"): raise AlphaError("Choose a valid reply audience.", 400)
            result["reply_control"] = value["reply_control"]
        if value.get("link_attachment"): result["link_attachment"] = web_url(value["link_attachment"])
        if value.get("poll_attachment"):
            poll = value["poll_attachment"]
            if (media or "link_attachment" in result or not isinstance(poll, dict) or not 2 <= len(poll) <= 4
                    or not all(k in ("option_a", "option_b", "option_c", "option_d") and isinstance(v, str) and 1 <= len(v) <= 25 for k, v in poll.items())
                    or not {"option_a", "option_b"}.issubset(poll)):
                raise AlphaError("Threads polls need 2–4 options and cannot attach media or links.", 400)
            result["poll_attachment"] = json.dumps(poll, separators=(",", ":"))
        if value.get("text_attachment"):
            attachment = value["text_attachment"]
            if media or value.get("poll_attachment") or not isinstance(attachment, dict) or not isinstance(attachment.get("plaintext"), str) or not 1 <= len(attachment["plaintext"]) <= 10000:
                raise AlphaError("Choose a valid Threads text attachment.", 400)
            data = {"plaintext": attachment["plaintext"]}
            if attachment.get("link_attachment_url"): data["link_attachment_url"] = web_url(attachment["link_attachment_url"])
            result["text_attachment"] = json.dumps(data, separators=(",", ":"))
        if "is_ghost_post" in value:
            if type(value["is_ghost_post"]) is not bool: raise AlphaError("Choose a valid ghost-post setting.", 400)
            result["is_ghost_post"] = "true" if value["is_ghost_post"] else "false"
        if value.get("topic_tag"):
            if not isinstance(value["topic_tag"], str) or len(value["topic_tag"]) > 50: raise AlphaError("Choose a valid topic tag.", 400)
            result["topic_tag"] = value["topic_tag"]
        return result
    if platform == 'Facebook':
        result = {'format': value.get('format', 'feed')}
        if result['format'] not in ('feed', 'reel', 'story'): raise AlphaError('Choose Page feed, Reel or Story.', 400)
        if result['format'] in ('reel', 'story') and len(media) != 1: raise AlphaError('Reels and Stories require one media item.', 400)
        if result['format'] == 'reel' and not media[0]['mime'].startswith('video/'): raise AlphaError('A Reel needs video.', 400)
        if result['format'] == 'story' and text: raise AlphaError('Review the Story without a feed caption.', 400)
        if value.get('link'):
            if media or result['format'] != 'feed': raise AlphaError('A link post cannot carry another format.', 400)
            result['link'] = web_url(value['link'])
        if 'scheduledPublishTime' in value:
            import time
            at = value['scheduledPublishTime']
            if result['format'] != 'feed' or any(a['mime'].startswith('video/') for a in media) or type(at) is not int or not 600 <= at-time.time() <= 30*86400:
                raise AlphaError('Rafii native Page scheduling currently accepts feed text/photo posts from 10 minutes to 30 days ahead.', 400)
            result['scheduledPublishTime'] = at
        return result
    if platform == 'X':
        result = {}
        for key in ('replyToId', 'quoteId'):
            if key in value:
                if not re.fullmatch(r'\d{1,19}', str(value[key])): raise AlphaError('Choose a valid X post ID.', 400)
                result[key] = value[key]
        if value.get('poll'):
            poll = value['poll']
            if (media or not isinstance(poll, dict) or not isinstance(poll.get('options'), list) or not 2 <= len(poll['options']) <= 4
                    or any(not isinstance(v, str) or not 1 <= len(v) <= 25 for v in poll['options'])
                    or type(poll.get('duration_minutes')) is not int or not 5 <= poll['duration_minutes'] <= 10080):
                raise AlphaError('An X poll needs 2–4 options and a 5-minute to 7-day duration, without media.', 400)
            result['poll'] = {'options': poll['options'], 'duration_minutes': poll['duration_minutes']}
        if value.get('thread'):
            thread = value['thread']
            if not isinstance(thread, list) or not 1 <= len(thread) <= 24 or any(not isinstance(t, str) or not 1 <= len(t) <= 280 for t in thread):
                raise AlphaError('An X thread needs 1–24 additional posts of up to 280 characters.', 400)
            result['thread'] = list(thread)
        return result
    return value
