"""A chat request for recurring drafts becomes an automation (agent chat → Automations hub).

"Every Tuesday, draft me a news article post in my voice about AI for Science" asks Rafii to keep preparing drafts,
so it is not drafted once. Reading it is deterministic (no model request, no charge): the schedule, topic, content
type, voice and attached references fill the same fields as the Automations builder, and the automation is saved
with the builder's checks (`raffi_recurrence_save`). An owner's request is turned on at once when nothing is left for
the owner to decide; a per-run spending limit, a missing fact or a request from someone who is not an owner leaves
it waiting in the hub with the reason. Automations only prepare drafts: nothing here schedules or publishes a post.
"""
from __future__ import annotations

import datetime as dt
import re

from postriff_alpha.domain import AlphaError, clean

from . import campaigns, content_types, intent, voice_sources

DEFAULT_TIME = (9, 0)
EVENING_TIME = (18, 0)
DEFAULT_AUDIENCE = "The people who follow these accounts"
CREATOR_PACK = {"packId": content_types.CREATOR_PACK_ID, "version": content_types.CREATOR_PACK_VERSION}
DAYS = campaigns.WEEKDAY_NAMES
FORMAT_LABELS = dict(content_types.FORMATS)

_SHORT_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_FULL_DAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", re.I)
_SHORT_DAY = re.compile(r"(?:\b(?:every|each|on|and)\s+|[,&]\s*)(mon|tues?|wed|thur?s?|fri|sat|sun)\b", re.I)
_ZH_DAY = re.compile(r"(?:星期|禮拜|礼拜|週|周)([一二三四五六日天])")
_ZH_DAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_WEEKDAYS = re.compile(r"\b(?:every\s+weekday|on\s+weekdays|weekdays)\b|工作日|平日", re.I)
_WEEKENDS = re.compile(r"\b(?:every\s+weekend|on\s+weekends|weekends)\b|週末|周末", re.I)
_DAILY = re.compile(r"\b(?:every|each)\s+(?:day|morning|evening|night)\b|\bdaily\b|每(?:日|天)|日日", re.I)
_EVENING = re.compile(r"\b(?:every|each)\s+(?:evening|night)\b|每(?:日|天)?(?:晚|夜)", re.I)
_MONTHLY = re.compile(r"\b(?:every|each)\s+month\b|\bmonthly\b|\bof\s+(?:every|each|the)\s+month\b|每(?:個|个)?月", re.I)
_MONTH_DAY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b|\bon\s+the\s+(\d{1,2})\b|月\s*(\d{1,2})\s*(?:號|号|日)", re.I)
_LAST_DAY = re.compile(r"\blast\s+day\s+of\s+(?:every|each|the)\s+month\b|最後一日|最后一天", re.I)
_OTHER_WEEK = re.compile(r"\bevery\s+(?:other|second|two)\s+weeks?\b|\bbi-?weekly\b|\bfortnightly\b|隔星期|隔週|隔周|每兩個星期|每两个星期", re.I)

_ABOUT = re.compile(r"\b(?:about|regarding|covering|on\s+the\s+(?:topic|subject|theme)\s+of)\s+", re.I)
_TOPIC_LEAD = re.compile(r"^(?:the\s+)?(?:topic|subject|theme)s?\s+of\s+", re.I)
_TOPIC_END = re.compile(
    r"[.;!?\n,，。！？；]"
    r"|\s+(?:on\s+)?(?:every|each)\s"
    r"|\s+on\s+(?:mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays|weekdays|weekends|the\s+\d)"
    r"|\s+(?:weekly|monthly|daily|fortnightly|bi-?weekly)\b"
    r"|\s+(?:using|with\s+my|in\s+my|written\s+in|at\s+\d|for\s+(?:my\s+)?(?:linkedin|instagram|threads|facebook|twitter|tiktok|youtube)\b)"
    r"|\s+and\s+(?:post|publish|share|send|make|set|use|keep)\b"
    r"|\s+as\s+(?:an?\s+)?(?:carousels?|polls?|short\s+videos?|videos?|reels?|articles?|threads?|quote\s+cards?|posts?)\b",
    re.I)
_ZH_ABOUT = re.compile(r"(?:關於|关于|有關|有关)\s*")
_ZH_END = re.compile(r"[，,。.!！?？；;\n]|嘅|的|逢|每")
_NOUN = re.compile(
    r"\b(?:an?\s+|one\s+)?((?:(?!me\b|us\b|an?\b|the\b|of\b|my\b)[a-z][\w-]*\s+){0,2}"
    r"(?:post|article|piece|update|thread|carousel|video|reel|tip|story|recap|round-?up|newsletter|summary|quote|question|poll|announcement)s?)\b",
    re.I)
_VOICE = re.compile(
    r"\b(?:my|own)\s+(?:writing\s+)?(?:voice|style|tone)\b|\b(?:sounds?|writes?|written)\s+like\s+me\b|\bin\s+my\s+(?:own\s+)?words\b"
    r"|我(?:嘅|的)(?:語氣|语气|風格|风格|聲音|声音|口吻|文筆|文笔)|似我",
    re.I)

# What a message calls the drafts → content types in order of preference; the first this workspace offers wins
# (the starter pack is installed when only it has the type, as choosing its template on Home does).
_CONTENT = (
    (re.compile(r"\bnews\b|\bheadlines?\b|\bcommentary\b|\bround-?ups?\b|新聞|新闻|時事|时事", re.I), ("pack.creator:article_news_commentary",)),
    (re.compile(r"\btips?\b|\bhow[- ]tos?\b|\btutorials?\b|\blessons?\b|\bguides?\b|教學|教学|貼士|贴士|技巧", re.I), ("postriff:teach", "pack.creator:tutorial_how_to")),
    (re.compile(r"\bbehind[- ]the[- ]scenes\b|\bbuilding in public\b|\bprogress\b|\bupdates?\b|近況|近况|進度|进度", re.I), ("postriff:update", "pack.creator:building_in_public")),
    (re.compile(r"\bstor(?:y|ies)\b|\breflections?\b|故事|反思", re.I), ("postriff:story", "pack.creator:personal_reflection")),
    (re.compile(r"\bannouncements?\b|\bpromotions?\b|\boffers?\b|\blaunch(?:es)?\b|宣傳|宣传|公告", re.I), ("postriff:promote", "pack.creator:product_feature_launch")),
    (re.compile(r"\bquestions?\b|\bpolls?\b|\bdiscussions?\b|\bq\s*&\s*a\b|問題|问题|投票|討論|讨论", re.I), ("postriff:engage", "pack.creator:community_q_and_a")),
    (re.compile(r"\bquotes?\b|金句|語錄|语录", re.I), ("pack.creator:quick_thought_quote",)),
    (re.compile(r"\bopinions?\b|\bpoint of view\b|\bthought leadership\b|\bessays?\b|觀點|观点", re.I), ("pack.creator:deep_point_of_view",)),
)
_FORMAT = (
    (re.compile(r"\bcarousels?\b", re.I), "carousel"),
    (re.compile(r"\bpolls?\b|投票", re.I), "poll"),
    (re.compile(r"\b(?:short\s+videos?|reels?)\b|短片", re.I), "short_video"),
    (re.compile(r"\bquote\s+cards?\b", re.I), "quote_card"),
    (re.compile(r"\b(?:long[- ]form|full)\s+articles?\b|\barticles?\b(?!\s+posts?\b)|長文|长文", re.I), "article"),
)


def topic_of(text: str) -> str | None:
    """What the drafts are about: the words after "about" (or 關於), up to the schedule or settings that follow."""
    match = _ABOUT.search(text)
    if match:
        rest = _TOPIC_LEAD.sub("", text[match.end():])
        end = _TOPIC_END.search(rest)
    else:
        match = _ZH_ABOUT.search(text)
        if not match:
            return None
        rest = text[match.end():]
        end = _ZH_END.search(rest)
    topic = (rest[:end.start()] if end else rest).strip(" \t\"'“”‘’「」『』")
    return clean(topic, 160) if topic else None


def _weekdays(text: str) -> list[int]:
    days = {DAYS.index(m.group(1).capitalize()) for m in _FULL_DAY.finditer(text)}
    days |= {_SHORT_DAYS[m.group(1).lower()[:3]] for m in _SHORT_DAY.finditer(text)}
    days |= {_ZH_DAYS[m.group(1)] for m in _ZH_DAY.finditer(text)}
    return sorted(days)


def schedule_of(text: str, zone: str) -> tuple[dict, list[str]]:
    """The recurring schedule a message asks for (weekly unless a month is named) and what had to be assumed."""
    notes = []
    clock = next(iter(intent._clock_tokens(text)), None)
    if clock:
        hour, minute, assumed, label = clock
        if assumed:
            notes.append(f"I read “{label}” as {hour:02d}:{minute:02d}.")
    else:
        hour, minute = EVENING_TIME if _EVENING.search(text) else DEFAULT_TIME
        notes.append(f"No time was named, so each draft is ready at {hour:02d}:{minute:02d}.")
    local = f"{hour:02d}:{minute:02d}"
    days = _weekdays(text)
    if _MONTHLY.search(text) and not days:
        if _LAST_DAY.search(text):
            month_days = ["last"]
        else:
            month_days = sorted({int(next(g for g in m.groups() if g)) for m in _MONTH_DAY.finditer(text)} & set(range(1, 32)))[:campaigns.MAX_MONTH_DAYS]
        if not month_days:
            month_days = [1]
            notes.append("No day of the month was named, so it runs on the 1st.")
        return {"kind": "monthly", "monthDays": month_days, "localTime": local, "timeZone": zone}, notes
    if _OTHER_WEEK.search(text):
        notes.append("Every other week is not available yet, so it runs every week; pause it for the weeks you do not need.")
    if not days:
        if _WEEKDAYS.search(text):
            days = [0, 1, 2, 3, 4]
        elif _WEEKENDS.search(text):
            days = [5, 6]
        elif _DAILY.search(text):
            days = list(range(7))
        else:
            days = [0]
            notes.append("No day was named, so it runs every Monday.")
    return {"weekdays": [DAYS[day] for day in days], "localTime": local, "timeZone": zone}, notes


def _pack_installed(state: dict) -> bool:
    return any(item.get("id") == content_types.CREATOR_PACK_ID for item in content_types.ensure_content_state(state)["installedPacks"])


def content_of(state: dict, actor: str, now: float, text: str) -> dict | None:
    """The content type the message names, else the one selected on Home; None drafts without one."""
    format_id = next((value for pattern, value in _FORMAT if pattern.search(text)), None)
    for pattern, type_ids in _CONTENT:
        if not pattern.search(text):
            continue
        for type_id in type_ids:
            if type_id.startswith(content_types.CREATOR_PACK_ID + ":") and not _pack_installed(state):
                content_types.apply_content_action(state, "content_install_pack", CREATOR_PACK, actor, now)
            try:
                item = content_types.definition(state, type_id)
            except AlphaError:
                continue
            chosen = format_id if format_id in item.get("recommendedFormatIds", []) else None
            return _content_value(item, chosen)
    selection = (content_types.ensure_content_state(state).get("selection") or {})
    if selection.get("contentTypeId") in (None, "unclassified"):
        return None
    try:
        item = content_types.definition(state, selection["contentTypeId"], selection.get("contentTypeVersion"))
    except AlphaError:
        return None
    return _content_value(item, selection.get("formatId"))


def content_by_id(state: dict, actor: str, now: float, type_id: str, format_id: str | None) -> dict | None:
    """A content type chosen by id (Rafii's reading of the request), installing the starter pack if only it has it."""
    if type_id.startswith(content_types.CREATOR_PACK_ID + ":") and not _pack_installed(state):
        content_types.apply_content_action(state, "content_install_pack", CREATOR_PACK, actor, now)
    try:
        item = content_types.definition(state, type_id)
    except AlphaError:
        return None
    return _content_value(item, format_id if format_id in item.get("recommendedFormatIds", []) else None)


def _content_value(item: dict, format_id: str | None) -> dict:
    label = item.get("shortLabel") or item["label"]
    return {"contentTypeId": item["id"], "formatId": format_id, "label": f"{label} · {FORMAT_LABELS[format_id]}" if format_id in FORMAT_LABELS else label}


def voice_available(state: dict, route: str) -> bool:
    """Whether a selected writing sample is allowed for this writer route right now."""
    requested = [s["id"] for s in state.get("sources", []) if s.get("kind") == "voice_sample" and s.get("active") and s.get("selected")]
    if not requested:
        return False
    try:
        return bool(voice_sources.retrieve(state, requested, "generation", route)["samples"])
    except AlphaError:
        return False


def _phrase(text: str) -> str:
    match = _NOUN.search(text)
    return match.group(1) if match else "post"


def _with_article(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _join(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _ordinal(day: int) -> str:
    return "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def describe(schedule: dict) -> str:
    """"Every Tuesday at 09:00 (Asia/Hong_Kong)" for the reply and the card."""
    at = f" at {schedule.get('localTime', '09:00')} ({schedule.get('timeZone', 'UTC')})"
    if schedule.get("kind") == "monthly":
        days = ["the last day" if day == "last" else f"the {day}{_ordinal(day)}" for day in schedule["monthDays"]]
        return f"On {_join(days)} of every month{at}"
    names = list(schedule.get("weekdays") or [])
    if len(names) == 7:
        return f"Every day{at}"
    if names == list(DAYS[:5]):
        return f"Every weekday{at}"
    return f"Every {_join(names)}{at}"


def _first_run(next_occurrence: dict | None) -> str | None:
    if not next_occurrence:
        return None
    local = dt.datetime.fromisoformat(next_occurrence["local"])
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')} at {local.strftime('%H:%M')}"


def _understood_schedule(understood: dict, fallback: dict, zone: str) -> dict | None:
    """The schedule from Rafii's reading, kept only if the Automations builder accepts it."""
    local = understood.get("localTime") or fallback["localTime"]
    if understood.get("weekdays"):
        candidate = {"weekdays": understood["weekdays"], "localTime": local, "timeZone": zone}
    elif understood.get("monthDays"):
        candidate = {"kind": "monthly", "monthDays": understood["monthDays"], "localTime": local, "timeZone": zone}
    else:
        return None
    try:
        return campaigns.normalize_schedule(candidate)
    except AlphaError:
        return None


def create(state: dict, actor: str, now: float, text: str, zone: str, *, destinations: list[dict], route: str, voice_route: str,
           reasoning: str, paid: bool, voice: bool, source_ids: list[str], owner: bool, understood: dict | None = None) -> dict:
    """Save the automation a chat request describes and turn it on when an owner asked and nothing is left for the
    owner to decide. `understood` is Rafii's model reading (request_model.reading), already checked against this
    workspace; whatever it leaves out comes from the deterministic reading. Returns the card the reply carries."""
    understood = understood or {}
    topic = understood.get("topic") or topic_of(text)
    rest = text.replace(topic, " ") if topic and topic in text else text
    schedule, notes = schedule_of(rest, zone)
    chosen = _understood_schedule(understood, schedule, zone)
    if chosen is not None:
        schedule = chosen
        # The model named the days (and perhaps the time): only its own assumptions still need saying.
        notes = [note for note in notes if "time was named" in note and not understood.get("localTime")] + list(understood.get("assumptions") or [])
    content = content_by_id(state, actor, now, understood["contentTypeId"], understood.get("formatId")) if understood.get("contentTypeId") else None
    content = content or content_of(state, actor, now, rest)
    phrase = _phrase(rest)
    personalized = voice or bool(understood.get("voice")) or bool(_VOICE.search(rest))
    if personalized and not voice_available(state, voice_route):
        notes.append("No writing sample is allowed for this writer yet, so drafts stay neutral until you allow one on the Brand page.")
    if topic:
        goal = f"{_upper_first(_with_article(phrase))} about {topic}."
        name = f"{topic} · {_upper_first(phrase)}"
    else:
        goal = clean(text, 1200)
        name = f"{_upper_first(phrase)} · {describe(schedule).split(' at ')[0]}"
    goal = understood.get("goal") or goal
    name = understood.get("name") or name
    audience = clean((state.get("brandHub") or {}).get("audience") or "", 800) or DEFAULT_AUDIENCE
    payload = {
        "name": clean(name, 120), "goal": goal, "audience": audience, "facts": {}, "schedule": schedule,
        "destinations": [{key: d[key] for key in ("platform", "language", "channelId") if d.get(key)} for d in destinations],
        "contentType": content, "route": route, "reasoning": reasoning if reasoning in campaigns.REASONING else "quick",
        "maxCostUsdMicro": 0, "sourceIds": source_ids, "include": None, "voiceMode": "personalized" if personalized else "neutral",
    }
    saved = campaigns.apply_action(state, "raffi_recurrence_save", payload, actor, now)
    needs = []
    if not owner:
        needs.append({"code": "owner", "text": "An owner of this workspace turns it on."})
    if paid:
        needs.append({"code": "spend", "text": "This writer charges per run, so choose how much each run may spend, then turn it on."})
    if saved["missingFacts"]:
        needs.append({"code": "facts", "text": f"Add the {_join(saved['missingFacts'])} first, then turn it on."})
    if not needs:
        try:
            campaigns.apply_action(state, "raffi_recurrence_activate", {"taskId": saved["taskId"], "confirmed": True}, actor, now)
        except AlphaError as error:
            needs.append({"code": "review", "text": str(error)})
    return card(state, saved["taskId"], needs, notes)


def card(state: dict, task_id: str, needs: list[dict], notes: list[str]) -> dict:
    root = campaigns._root(state)
    task = next(item for item in root["recurringTasks"] if item["id"] == task_id)
    campaign = next(item for item in root["campaigns"] if item["id"] == task["campaignId"])
    sources = {item.get("id"): item for item in state.get("sources", [])}
    labels = task.get("accountLabels") or {}
    return {
        "taskId": task["id"], "campaignId": campaign["id"], "name": task["name"], "status": task["status"],
        "goal": campaign["goal"], "audience": campaign["audience"], "schedule": task["schedule"], "scheduleText": describe(task["schedule"]),
        "nextOccurrence": task.get("nextOccurrence"), "firstRun": _first_run(task.get("nextOccurrence")),
        "destinations": [{**d, **({"account": labels[d["channelId"]]} if labels.get(d.get("channelId")) else {})} for d in task["destinations"]],
        "contentLabel": task.get("contentLabel"), "voiceMode": task.get("voiceMode", "neutral"),
        "sources": [{"id": item, "title": clean(sources[item].get("title") or "Untitled source", 120)} for item in task.get("contextSourceIds", []) if item in sources],
        "needs": needs, "notes": notes,
    }


def reply(view: dict | None, failure: str | None = None) -> str:
    """Rafii's answer in the conversation: what will happen, when, and anything left to decide."""
    if view is None:
        return f"I could not set up that automation: {failure or 'something in the request is not available.'} You can build it in Automations instead."
    where = _join([f"{d['platform']} ({d['account']})" if d.get("account") else d["platform"] for d in view["destinations"]])
    parts = [f"{view['scheduleText']}, I'll prepare {view['goal'][:1].lower()}{view['goal'][1:].rstrip('.')} for {where}"]
    if view["voiceMode"] == "personalized":
        parts.append("in your voice")
    if view["sources"]:
        titles = [f"“{item['title']}”" for item in view["sources"]]
        parts.append(f"using {_join(titles)} as {'a reference' if len(titles) == 1 else 'references'}")
    sentence = ", ".join(parts) + "."
    # What is left to decide and what had to be assumed are on the card below the reply, not repeated here.
    if view["status"] == "active":
        text = f"Done. {sentence}"
        if view.get("firstRun"):
            text += f" The first draft will be ready {view['firstRun']}."
        return text + " Each draft waits for your review; nothing is published without you."
    return f"I've set this up. {sentence} It is waiting for you before it runs; the card below says what is left."
