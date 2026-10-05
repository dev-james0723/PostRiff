"""Per-post choices a platform needs before Rafii may publish, frozen into the approved manifest.

The composer (web/src/lib/channels/tiktok-rules.ts and the schedule dialog) asks for them; this module is the server's
own check, so an approval can never carry options the composer would have refused. TikTok follows its Content Sharing
Guidelines: no default privacy level, interactions off unless the person allows them, commercial content disclosed
with at least one kind, branded content never private-only, and explicit consent to the exact declaration.
"""
import re
from datetime import date
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError

TIKTOK_PRIVACY = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY")
YOUTUBE_PRIVACY = ("private", "unlisted", "public")
PLATFORMS = ("TikTok", "YouTube", "Pinterest", "Google Business Profile")


def tiktok_consent_text(branded):
    """The exact declaration TikTok requires (Content Sharing Guidelines, point 4)."""
    if branded:
        return "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation"
    return "By posting, you agree to TikTok's Music Usage Confirmation"


def _flag(options, key, platform):
    value = options.get(key)
    if not isinstance(value, bool):
        raise AlphaError(f"Choose {platform}'s {key} setting.", 400)
    return value


def _video(media, platform):
    if len(media) != 1 or not str(media[0].get("mime") or "").startswith("video/"):
        raise AlphaError(f"{platform} posts from Rafii need exactly one verified video.", 409)
    return media[0]


def _tiktok(options, media):
    photos = bool(media) and all(str(a.get('mime', '')).startswith('image/') for a in media)
    photo_options = {}
    if photos:
        cover = options.get('coverIndex', 0)
        if type(cover) is not int or not 0 <= cover < len(media) or len(media) > 35: raise AlphaError('Choose a valid photo cover.', 400)
        title = options.get('title', '')
        if not isinstance(title, str) or len(title.encode('utf-16-le'))//2 > 90: raise AlphaError('Use a TikTok photo title up to 90 UTF-16 units.', 400)
        photo_options.update(coverIndex=cover,title=title)
        if 'isAigc' in options: photo_options['isAigc'] = _flag(options,'isAigc','TikTok')
    transfer = options.get('transferMode','file')
    if transfer not in ('file','url'): raise AlphaError('Choose file upload or verified URL transfer.',400)
    if options.get('mode') == 'inbox':
        if not photos: _video(media, 'TikTok')
        if options.get('consent') is not True: raise AlphaError('Approve transfer to the TikTok inbox.', 400)
        return {'mode': 'inbox', 'consent': True, 'transferMode':'url' if photos else transfer, **photo_options}
    video = None if photos else _video(media, "TikTok")
    privacy = options.get("privacyLevel")
    if privacy not in TIKTOK_PRIVACY:
        raise AlphaError("Choose who can see this TikTok post. There is no default.", 400)
    allow = {key: _flag(options, key, "TikTok") for key in ("allowComment", "allowDuet", "allowStitch")}
    commercial = options.get("commercial") if isinstance(options.get("commercial"), dict) else {}
    enabled = commercial.get("enabled") is True
    your_brand = enabled and commercial.get("yourBrand") is True
    branded = enabled and commercial.get("brandedContent") is True
    if enabled and not (your_brand or branded):
        raise AlphaError("Say whether this promotes your brand, branded content, or both, or turn off commercial content.", 400)
    if branded and privacy == "SELF_ONLY":
        raise AlphaError("Branded content can't be private on TikTok. Choose who can see it.", 400)
    consent = tiktok_consent_text(branded)
    if options.get("consent") is not True or options.get("consentText") != consent:
        raise AlphaError(f'Confirm: "{consent}".', 400)
    duration = video.get("duration") if video else 1
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise AlphaError("TikTok needs the video's length. Upload it again.", 409)
    extra = {}
    if not photos:
        extra['transferMode'] = transfer
        if 'coverTimestampMs' in options:
            cover = options['coverTimestampMs']
            if type(cover) is not int or not 0 <= cover < duration*1000: raise AlphaError('Choose a cover frame within the approved video.',400)
            extra['coverTimestampMs'] = cover
    if 'isAigc' in options: extra['isAigc'] = _flag(options,'isAigc','TikTok')
    if photos:
        extra.update(photo_options)
        if 'autoAddMusic' in options: extra['autoAddMusic'] = _flag(options,'autoAddMusic','TikTok')
    return {**extra, "privacyLevel": privacy, **allow, "commercial": {"enabled": enabled, "yourBrand": your_brand, "brandedContent": branded},
            "consent": True, "consentText": consent}


def _youtube(options, media, text):
    _video(media, "YouTube")
    title = options.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or "<" in title or ">" in title:
        raise AlphaError("Give the video a title of up to 100 characters, without < or >.", 400)
    if options.get("privacyStatus") not in YOUTUBE_PRIVACY:
        raise AlphaError("Choose private, unlisted or public for this video.", 400)
    made_for_kids = _flag(options, "madeForKids", "YouTube")
    if len(text.encode()) > 5000:
        raise AlphaError("A YouTube description allows 5,000 bytes. Shorten the text.", 409)
    result = {"title": title.strip(), "privacyStatus": options["privacyStatus"], "madeForKids": made_for_kids}
    for key in ('containsSyntheticMedia', 'notifySubscribers'):
        if key in options: result[key] = _flag(options, key, 'YouTube')
    if options.get('publishAt'):
        from datetime import datetime, timezone
        try: at = datetime.fromisoformat(options['publishAt'].replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError): raise AlphaError('Choose a valid future YouTube publication time.', 400)
        if at.tzinfo is None or at <= datetime.now(timezone.utc): raise AlphaError('YouTube publishAt must be in the future with a timezone.', 400)
        if result['privacyStatus'] != 'private': raise AlphaError('Native scheduled uploads must initially be private.', 400)
        result['publishAt'] = at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    if options.get('localizations'):
        localized = options['localizations']
        if not isinstance(localized, dict) or len(localized) > 50 or any(not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', lang) or not isinstance(value, dict) or set(value)-{'title', 'description'} or not isinstance(value.get('title'), str) or not 1 <= len(value['title']) <= 100 or not isinstance(value.get('description', ''), str) or len(value.get('description', '').encode()) > 5000 for lang, value in localized.items()):
            raise AlphaError('Review valid YouTube title/description localizations.', 400)
        result['localizations'] = localized
    return result


def _pinterest(options, media):
    if len(media) != 1 or not str(media[0].get("mime") or "").startswith(("image/", "video/")):
        raise AlphaError("A Pin needs exactly one image or video.", 409)
    board = options.get("boardId")
    if not isinstance(board, str) or not re.fullmatch(r"\d{1,30}", board):
        raise AlphaError("Choose the board for this Pin.", 400)
    title = options.get("title") or ""
    if not isinstance(title, str) or len(title) > 100:
        raise AlphaError("A Pin title allows 100 characters.", 400)
    link = options.get("link") or ""
    if link:
        try:
            parts = urlsplit(link) if isinstance(link, str) else None
        except ValueError:
            parts = None
        if not parts or parts.scheme not in ("http", "https") or not parts.hostname or len(link) > 2048 or parts.username or parts.password:
            raise AlphaError("The Pin link must be a web address starting with https://.", 400)
    result = {"boardId": board, "title": title.strip(), "link": link}
    if options.get('sectionId'):
        if not isinstance(options['sectionId'], str) or not re.fullmatch(r'\d{1,30}', options['sectionId']): raise AlphaError('Choose a valid board section.', 400)
        result['sectionId'] = options['sectionId']
    if media[0]['mime'].startswith('video/'):
        if options.get('coverImageUrl'): raise AlphaError('Use the video’s approved cover frame; mutable external cover URLs are not accepted.',400)
        result['coverSource'] = 'approved_poster'
    return result


def _gbp(options, media):
    selected = options.get("gbp")
    if not isinstance(selected, dict) or selected.get("topicType") not in ("STANDARD", "EVENT", "OFFER"):
        raise AlphaError("Choose an Update, Event or Offer for this Business Profile post.", 400)
    if len(media) > 1 or (media and media[0].get("mime") != "image/jpeg"):
        raise AlphaError("Business Profile needs at most one approved JPEG.", 409)
    topic = selected["topicType"]
    result = {"topicType": topic}
    if topic in ("EVENT", "OFFER"):
        event = selected.get("event")
        if not isinstance(event, dict) or not isinstance(event.get("title"), str) or not 1 <= len(event["title"].strip()) <= 58:
            raise AlphaError("Give this Business Profile Event or Offer a title of up to 58 characters.", 400)
        schedule = event.get("schedule")
        if not isinstance(schedule, dict):
            raise AlphaError("Choose the Event or Offer start and end times.", 400)
        for prefix in ("start", "end"):
            day, clock = schedule.get(prefix + "Date"), schedule.get(prefix + "Time")
            if not isinstance(day, dict) or not isinstance(clock, dict):
                raise AlphaError("Choose the Event or Offer start and end times.", 400)
            try:
                date(day["year"], day["month"], day["day"])
            except (KeyError, TypeError, ValueError) as error:
                raise AlphaError("Choose valid Event or Offer dates.", 400) from error
            if type(clock.get("hours")) is not int or type(clock.get("minutes")) is not int or not 0 <= clock["hours"] <= 23 or not 0 <= clock["minutes"] <= 59:
                raise AlphaError("Choose valid Event or Offer times.", 400)
        start = (schedule["startDate"]["year"], schedule["startDate"]["month"], schedule["startDate"]["day"],
                 schedule["startTime"]["hours"], schedule["startTime"]["minutes"])
        end = (schedule["endDate"]["year"], schedule["endDate"]["month"], schedule["endDate"]["day"],
               schedule["endTime"]["hours"], schedule["endTime"]["minutes"])
        if end <= start:
            raise AlphaError("The Event or Offer must end after it starts.", 400)
        result["event"] = {"title": event["title"].strip(), "schedule": {
            key: {field: schedule[key][field] for field in (("year", "month", "day") if key.endswith("Date") else ("hours", "minutes"))}
            for key in ("startDate", "startTime", "endDate", "endTime")}}
    if topic == "OFFER":
        offer = selected.get("offer")
        if not isinstance(offer, dict):
            raise AlphaError("Add an Offer code, redemption URL or terms.", 400)
        fields = {key: value.strip() for key in ("couponCode", "redeemOnlineUrl", "termsConditions")
                  if isinstance(value := offer.get(key), str) and value.strip()}
        if not fields or any(len(value) > 1000 for value in fields.values()):
            raise AlphaError("Add valid Offer details.", 400)
        if "redeemOnlineUrl" in fields:
            url = urlsplit(fields["redeemOnlineUrl"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise AlphaError("The Offer redemption URL must be HTTPS.", 400)
        result["offer"] = fields
    return {"gbp": result}


def normalize(platform, options, media, text):
    """The canonical options for the manifest, or None for platforms that need none (their manifests stay unchanged)."""
    if platform in ("LinkedIn", "Threads", "Instagram", "Facebook", "X"):
        if options is None and len(media) <= 1:
            return None
        from .social_formats import options as official_options
        return official_options(platform, options, media, text)
    if platform not in PLATFORMS:
        return None
    if not isinstance(options, dict):
        raise AlphaError(f"Choose the {platform} publishing options first.", 400)
    if platform == "TikTok":
        return _tiktok(options, media)
    if platform == "YouTube":
        return _youtube(options, media, text)
    if platform == "Google Business Profile":
        return _gbp(options, media)
    return _pinterest(options, media)
