"""Immutable Telegram adaptation. Unknown fields/content are rejected, never discarded."""
import copy
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from postriff_alpha.domain import AlphaError

FORMATS = ("text", "photo", "album", "video", "animation", "live_photo", "audio", "voice", "video_note", "document", "poll")
ENTITY_TYPES = {"mention", "hashtag", "cashtag", "bot_command", "url", "email", "phone_number", "bold", "italic", "underline", "strikethrough", "spoiler", "blockquote", "expandable_blockquote", "code", "pre", "text_link", "text_mention", "custom_emoji", "date_time"}
STYLE = {"bold", "italic", "underline", "strikethrough", "spoiler"}
RESERVED = r"_*[]()~`>#+-=|{}.!"


def fail(message):
    raise AlphaError(message, 400, code="telegram_payload_invalid")


def fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        fail(f"Unsupported {label} fields. Review the Telegram content explicitly.")
    return copy.deepcopy(value)


def utf16(value):
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        fail("Telegram text contains an invalid Unicode surrogate.")


def web_url(value, *, telegram=False):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        fail("Use a valid link without whitespace.")
    try:
        parts = urlsplit(value)
        valid = parts.scheme in ("http", "https") and bool(parts.hostname) and not parts.username and not parts.password
        valid |= bool(telegram and re.fullmatch(r"tg://user\?id=[1-9][0-9]{0,15}", value))
        if not valid: fail("Use an HTTP/HTTPS link or an authorized Telegram mention.")
    except ValueError:
        fail("Use a valid link.")
    return value


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        fail(f"Invalid Telegram {label}.")
    return value


def entities(text, values):
    if not isinstance(values, list) or len(values) > 100:
        fail("Use at most 100 structured Telegram entities.")
    boundaries = {0}
    at = 0
    for c in text:
        at += utf16(c); boundaries.add(at)
    result = []
    for value in values:
        e = fields(value, ("type", "offset", "length", "url", "user", "language", "custom_emoji_id", "unix_time", "date_time_format"), "entity")
        if e.get("type") not in ENTITY_TYPES: fail("Unknown Telegram entity type.")
        start = integer(e.get("offset"), 0, at, "entity offset")
        length = integer(e.get("length"), 1, at, "entity length")
        if start not in boundaries or start + length not in boundaries: fail("Telegram entities must use complete UTF-16 character boundaries.")
        kind = e["type"]
        allowed = {"type", "offset", "length"} | ({"url"} if kind == "text_link" else {"user"} if kind == "text_mention" else {"language"} if kind == "pre" else {"custom_emoji_id"} if kind == "custom_emoji" else {"unix_time", "date_time_format"} if kind == "date_time" else set())
        if set(e) - allowed: fail("Entity metadata does not match its type.")
        if kind == "text_link": web_url(e.get("url"), telegram=True)
        if kind == "text_mention":
            user = fields(e.get("user"), ("id", "is_bot", "first_name", "last_name", "username", "language_code", "is_premium"), "mention user")
            integer(user.get("id"), 1, 2 ** 52, "mention ID")
            if type(user.get("is_bot")) is not bool or not isinstance(user.get("first_name"), str): fail("A mention requires a Telegram User object.")
        if kind == "custom_emoji" and not re.fullmatch(r"[0-9]{1,30}", str(e.get("custom_emoji_id", ""))): fail("Invalid custom emoji ID.")
        if kind == 'date_time':
            integer(e.get('unix_time'),0,2**31-1,'date-time timestamp')
            if 'date_time_format' in e and (not isinstance(e['date_time_format'],str) or not re.fullmatch(r'r|w?[dD]?[tT]?',e['date_time_format'])): fail("Use a Telegram-supported date-time format.")
        if "language" in e and (not isinstance(e["language"], str) or len(e["language"]) > 64): fail("Invalid code-block language.")
        for other in result:
            a, b = other["offset"], other["offset"] + other["length"]
            end = start + length
            if start < b and a < end:
                contained = (a <= start and end <= b) or (start <= a and b <= end)
                if not contained or (kind not in STYLE and other["type"] not in STYLE) or kind in ("pre", "code") or other["type"] in ("pre", "code"):
                    fail("Telegram entities overlap in a way the API does not allow.")
        result.append(e)
    return sorted(result, key=lambda e: (e["offset"], -e["length"]))


class TelegramHTML(HTMLParser):
    TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline", "ins": "underline", "s": "strikethrough", "strike": "strikethrough", "del": "strikethrough", "tg-spoiler": "spoiler", "code": "code", "pre": "pre", "a": "text_link", "blockquote": "blockquote", "tg-emoji": "custom_emoji", "tg-time": "date_time"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.stack, self.result = "", [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        kind = self.TAGS.get(tag)
        if tag == "span" and attrs == {"class": "tg-spoiler"}: kind = "spoiler"
        if not kind: fail("Telegram HTML contains an unsupported tag.")
        extra = {}
        if tag == "a": extra = {"url": web_url(attrs.get("href"), telegram=True)}
        elif tag == "tg-emoji": extra = {"custom_emoji_id": attrs.get("emoji-id")}
        elif tag == 'tg-time':
            try: extra = {'unix_time': int(attrs['unix']), 'date_time_format': attrs.get('format','')}
            except (ValueError,KeyError): fail("Date-time tags need a valid Unix timestamp.")
        elif tag == "blockquote" and "expandable" in attrs: kind = "expandable_blockquote"
        elif tag == "code" and self.stack and self.stack[-1][1] == "pre":
            language = attrs.get("class", "")
            if language and not re.fullmatch(r"language-[\w+-]{1,64}", language): fail("Invalid code-block language.")
            if language: self.stack[-1][3]["language"] = language[9:]
            kind = None
        allowed = {"href"} if tag == "a" else {"unix","format"} if tag == 'tg-time' else {"emoji-id"} if tag == "tg-emoji" else {"expandable"} if tag == "blockquote" else {"class"} if tag in ("span", "code") else set()
        if set(attrs) - allowed: fail("Unsupported Telegram HTML attributes.")
        self.stack.append((tag, kind, utf16(self.text), extra))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag: fail("Telegram HTML tags must be balanced.")
        _, kind, start, extra = self.stack.pop()
        length = utf16(self.text) - start
        if kind and length: self.result.append({"type": kind, "offset": start, "length": length, **extra})

    def handle_data(self, data): self.text += data
    def handle_comment(self, data): fail("HTML comments are not Telegram message content.")
    def handle_decl(self, decl): fail("HTML declarations are not supported.")


def markdown(text):
    """Strict MarkdownV2 subset converted to entities; ambiguous markup is rejected."""
    result, es = "", []
    tokens = {"*": "bold", "_": "italic", "__": "underline", "~": "strikethrough", "||": "spoiler", "`": "code", "```": "pre"}
    stack = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            if i + 1 == len(text) or not 1 <= ord(text[i + 1]) <= 126: fail("Invalid MarkdownV2 escape.")
            result += text[i + 1]; i += 2; continue
        if stack and stack[-1][1] in ("code", "pre"):
            token = stack[-1][0]
            if not text.startswith(token, i): result += c; i += 1; continue
        token = next((s for s in ("```", "__", "||", "*", "_", "~", "`") if text.startswith(s, i)), None)
        if token:
            kind = tokens[token]
            if stack and stack[-1][0] == token:
                _, kind, start, extra = stack.pop()
                if utf16(result) == start: fail("Empty MarkdownV2 entity.")
                es.append({"type": kind, "offset": start, "length": utf16(result) - start, **extra})
                i += len(token); continue
            extra = {}
            i += len(token)
            if token == "```":
                newline = text.find("\n", i)
                if newline >= 0 and re.fullmatch(r"[\w+-]{0,64}", text[i:newline]):
                    if newline > i: extra["language"] = text[i:newline]
                    i = newline + 1
            stack.append((token, kind, utf16(result), extra)); continue
        if c in RESERVED:
            fail("Escape MarkdownV2 punctuation; use HTML or structured entities for links and blockquotes.")
        result += c; i += 1
    if stack: fail("MarkdownV2 formatting must be balanced.")
    return result, entities(result, es)


def formatted(text, mode=None, entity_values=None):
    if not isinstance(text, str): fail("Telegram text must be a string.")
    utf16(text)
    if mode and entity_values: fail("Choose a parse mode or structured entities, not both.")
    if mode in (None, "plain"):
        return text, entities(text, entity_values or [])
    if mode == "HTML":
        parser = TelegramHTML()
        parser.feed(text); parser.close()
        if parser.stack: fail("Telegram HTML tags must be balanced.")
        return parser.text, entities(parser.text, parser.result)
    if mode == "MarkdownV2": return markdown(text)
    fail("Choose plain text, Telegram HTML or MarkdownV2.")


def keyboard(value, *, destination=None, business=False):
    if value is None: return None
    if not isinstance(value, list) or not 1 <= len(value) <= 20: fail("Use 1–20 inline-button rows.")
    result = []
    for row in value:
        if not isinstance(row, list) or not 1 <= len(row) <= 8: fail("Use 1–8 buttons in each row.")
        output = []
        for b in row:
            b = fields(b, ("text", "url", "copy_text", "web_app", "style"), "button")
            if not isinstance(b.get("text"), str) or not 1 <= len(b["text"]) <= 128: fail("Give every button a short label.")
            if len(set(b) & {"url", "copy_text", "web_app"}) != 1: fail("Choose exactly one supported action for each button.")
            if "url" in b: web_url(b["url"], telegram=True)
            if "copy_text" in b:
                ct = fields(b["copy_text"], ("text",), "copy-text button")
                if not isinstance(ct.get("text"), str) or not 1 <= len(ct["text"]) <= 256: fail("Copy-text buttons accept 1–256 characters.")
            if "web_app" in b:
                app = fields(b["web_app"], ("url",), "Mini App")
                web_url(app.get("url"))
                if not app["url"].startswith("https://") or business or destination != "user_dm": fail("Mini App buttons require an HTTPS app in a bot private chat.")
            if "style" in b and b["style"] not in ("danger", "success", "primary"): fail("Unknown Telegram button style.")
            output.append(b)
        result.append(output)
    return {"inline_keyboard": result}


def poll(value):
    allowed = ("question", "question_entities", "options", "is_anonymous", "type", "allows_multiple_answers", "correct_option_ids", "explanation", "explanation_entities", "description", "description_entities", "open_period", "close_date", "is_closed", "allows_revoting", "shuffle_options", "allow_adding_options", "hide_results_until_closes", "members_only", "country_codes")
    p = fields(value, allowed, "poll")
    question = p.get("question")
    if not isinstance(question, str) or not 1 <= len(question) <= 300: fail("Poll question allows 1–300 characters.")
    options = p.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= 12: fail("A Telegram poll needs 1–12 options.")
    for option in options:
        fields(option, ("text", "text_entities"), "poll option")
        if not isinstance(option.get("text"), str) or not 1 <= len(option["text"]) <= 100: fail("Poll options allow 1–100 characters.")
        if any(e["type"] != "custom_emoji" for e in entities(option["text"], option.get("text_entities", []))): fail("Poll option entities can only be custom emoji.")
    if any(e["type"] != "custom_emoji" for e in entities(question, p.get("question_entities", []))): fail("Poll question entities can only be custom emoji.")
    kind = p.setdefault("type", "regular")
    if kind not in ("regular", "quiz"): fail("Choose a regular poll or quiz.")
    for k in allowed:
        if k.startswith(("is_", "allows_", "allow_", "hide_", "shuffle_", "members_")) and k in p and type(p[k]) is not bool: fail("Poll switches must be true or false.")
    if kind == "quiz":
        ids = p.get("correct_option_ids")
        if not isinstance(ids, list) or not ids or any(type(i) is not int or not 0 <= i < len(options) for i in ids) or ids != sorted(set(ids)):
            fail("Quiz correct-option IDs must be sorted, unique and in range.")
        if len(ids) > 1 and not p.get("allows_multiple_answers"): fail("Multiple correct answers require multiple-answer voting.")
    elif "correct_option_ids" in p or "explanation" in p: fail("Correct answers and explanations are quiz-only.")
    if p.get("allow_adding_options") and (p.get("is_anonymous", True) or kind == "quiz"): fail("Dynamic options require a non-anonymous regular poll.")
    if "open_period" in p: integer(p["open_period"], 5, 2628000, "poll open period")
    if "close_date" in p: integer(p["close_date"], 1, 2 ** 40, "poll close date")
    if "open_period" in p and "close_date" in p: fail("Choose an open period or close date.")
    for k, limit in (("explanation", 200), ("description", 1024)):
        if k in p:
            if not isinstance(p[k], str) or len(p[k]) > limit: fail(f"Poll {k} is too long.")
            if k == "explanation" and p[k].count("\n") > 2: fail("Poll explanations allow at most two line feeds.")
            if k + "_entities" in p: entities(p[k], p[k + "_entities"])
    if "country_codes" in p and (not isinstance(p["country_codes"], list) or len(p["country_codes"]) > 12 or any(not isinstance(c, str) or not re.fullmatch(r"[A-Z]{2}", c) for c in p["country_codes"])): fail("Choose at most 12 two-letter poll country codes.")
    return p


def normalize(options, media, text):
    options = options or {}
    outer = fields(options, ("telegram",), "Telegram publishing options")
    value = fields(outer.get("telegram", {}), ("version", "format", "text", "parseMode", "entities", "linkPreview", "buttons", "silent", "protectContent", "messageThreadId", "directMessagesTopicId", "replyToMessageId", "poll", "mediaOptions", "pinAfterPublish", "fileIds", "omitCaption"), "Telegram composer")
    if "version" in value and value["version"] != 1: fail("Unsupported Telegram content version.")
    inferred = "album" if len(media) > 1 else ("video" if media and str(media[0].get("mime", "")).startswith("video/") else "photo" if media else "text")
    kind = value.get("format", inferred)
    if kind not in FORMATS: fail("Unsupported Telegram post format.")
    canonical = "text" in value
    parsed, es = formatted(text, value.get("parseMode"), None if canonical and value.get("parseMode") else value.get("entities"))
    if 'omitCaption' in value:
        if value['omitCaption'] is not True or kind != 'video_note': fail("Explicit caption omission is only available for Video Notes.")
        parsed, es = '', []
    if canonical and (value["text"] != parsed or value.get("entities", []) != es):
        fail("The canonical Telegram adaptation differs from the approved source.")
    limit = 4096 if kind == "text" else 1024
    if len(parsed) > limit: fail(f"This Telegram format allows {limit} characters after parsing.")
    if kind == "text" and (not parsed or media): fail("A text post needs text and cannot silently discard media.")
    if kind == "video_note" and parsed: fail("Video Notes cannot carry captions. Remove or adapt this text explicitly.")
    if kind == "poll" and (media or not value.get("poll")): fail("A poll needs native poll options and cannot silently discard attached media.")
    if kind == "poll" and parsed and parsed != value["poll"].get("question"): fail("Use the draft text as the poll question, or explicitly adapt the draft.")
    if not isinstance(value.get('fileIds', []), list): fail("Choose recorded Telegram files.")
    count = len(media) + len(value.get("fileIds", []))
    if kind in ('text','poll') and count:fail('Text and poll messages cannot silently discard recorded media files.')
    items = value.get('mediaOptions', {}).get('albumItems') if isinstance(value.get('mediaOptions', {}), dict) else None
    if items is not None:
        if kind != 'album' or not isinstance(items,list): fail("Paired album descriptors apply only to an album.")
        used = []
        for item in items:
            item = fields(item, ('type','sourceIndex','photoIndex'), 'album item')
            if item.get('type') not in ('photo','video','audio','document','live_photo'): fail("Unsupported album item type.")
            used.append(integer(item.get('sourceIndex'),0,count-1,'album source index'))
            if item['type'] == 'live_photo': used.append(integer(item.get('photoIndex'),0,count-1,'live-photo still index'))
            elif 'photoIndex' in item: fail("Only Live Photos have a paired still image.")
        if sorted(used) != list(range(count)): fail("Every approved album dependency must be used exactly once.")
        count = len(items)
    if kind == "album" and not 2 <= count <= 10: fail("A Telegram album requires 2–10 media items.")
    if kind not in ("text", "poll", "album", "live_photo") and count != 1: fail("Choose exactly one media file for this Telegram format.")
    if kind == "live_photo" and count != 2: fail("A Live Photo needs a short video and a still image.")
    if "fileIds" in value:
        if not isinstance(value["fileIds"], list): fail("Choose recorded Telegram files.")
        for fid in value["fileIds"]:
            f = fields(fid, ("fileId", "kind", "recordId"), "Telegram file")
            if not isinstance(f.get("fileId"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{5,512}", f["fileId"]) or f.get("kind") not in FORMATS or not isinstance(f.get("recordId"), str): fail("Use a workspace-recorded Telegram file.")
    result = {"version": 1, "format": kind, "text": parsed, "entities": es}
    if value.get('omitCaption'): result['omitCaption'] = True
    if value.get("parseMode"): result["parseMode"] = value["parseMode"]
    for key in ("silent", "protectContent", "pinAfterPublish"):
        if key in value:
            if type(value[key]) is not bool: fail("Telegram switches must be true or false.")
            result[key] = value[key]
    for key in ("messageThreadId", "directMessagesTopicId", "replyToMessageId"):
        if key in value: result[key] = integer(value[key], 1, 2 ** 52, key)
    if "messageThreadId" in value and "directMessagesTopicId" in value: fail("Choose a forum thread or channel DM topic, not both.")
    if value.get("pinAfterPublish"): fail("Pin after publishing requires a separate receipt-based approval. Publish first, then pin.")
    if "linkPreview" in value:
        preview = fields(value["linkPreview"], ("is_disabled", "url", "prefer_small_media", "prefer_large_media", "show_above_text"), "link preview")
        if kind != "text": fail("Link-preview controls apply to text messages.")
        for key, v in preview.items():
            if key == "url": web_url(v)
            elif type(v) is not bool: fail("Link-preview switches must be true or false.")
        if preview.get("prefer_small_media") and preview.get("prefer_large_media"): fail("Choose a small or large preview.")
        result["linkPreview"] = preview
    if "buttons" in value:
        if kind == "album": fail("Telegram albums cannot carry inline keyboards; approve a separate CTA message.")
        # Destination-sensitive Mini App validation runs again after live permission verification.
        result["buttons"] = value["buttons"]
        keyboard(value["buttons"], destination="user_dm")
    if kind == "poll":
        result["poll"] = poll(value["poll"])
        if es:
            if any(e['type']!='custom_emoji' for e in es):fail('Telegram poll questions cannot carry this text formatting. Use plain question text; supported question entities are custom emoji only.')
            if result['poll'].get('question_entities',es)!=es:fail('The poll question entities differ from the approved source.')
            result['poll']['question_entities']=es
    if "mediaOptions" in value:
        mo = fields(value["mediaOptions"], ("has_spoiler", "show_caption_above_media", "width", "height", "duration", "supports_streaming", "start_timestamp", "title", "performer", "length", "albumKinds", "albumItems", "useThumbnail", "coverFile"), "media options")
        if 'albumKinds' in mo and 'albumItems' in mo: fail("Choose simple or paired album descriptors.")
        if 'coverFile' in mo:
            cf = fields(mo['coverFile'], ('fileId','kind','recordId'), 'video cover')
            if cf.get('kind') != 'photo' or not isinstance(cf.get('fileId'),str): fail("Choose a recorded photo as the video cover.")
        for key in ("has_spoiler", "show_caption_above_media", "supports_streaming", "useThumbnail"):
            if key in mo and type(mo[key]) is not bool: fail("Media switches must be true or false.")
        for key in ("width", "height", "duration", "start_timestamp", "length"):
            if key in mo: integer(mo[key], 0, 2 ** 31 - 1, key)
        for key in ("title", "performer"):
            if key in mo and (not isinstance(mo[key], str) or len(mo[key]) > 256): fail("Audio metadata is too long.")
        result["mediaOptions"] = mo
    if "fileIds" in value: result["fileIds"] = value["fileIds"]
    if len(json.dumps(result).encode()) > 65536: fail("Telegram publishing options are too large.")
    return {"telegram": result}
