"""Deterministic intent and schedule parsing for Ideas turns (agent chat design §4.1, step ①).

A pure function, no model. It recognises channel names and natural-language times in
English and Cantonese / Traditional Chinese, pairs them inside a clause, and returns a
candidate plan. Parsed text is never an instruction to the runtime: the plan is only a
proposal that the user approves through the existing review → approve chain.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LANGUAGES = ("English", "繁體中文")
INTENTS = ("draft", "schedule", "publish_now", "research")
DEFAULT_ZONE = "UTC"

# Display platform → aliases. ASCII aliases match on word boundaries, CJK aliases as substrings.
PLATFORM_ALIASES = (
    ("Instagram", ("instagram", "insta", "ig")),
    ("LinkedIn", ("linkedin", "領英", "领英")),
    ("Threads", ("threads",)),
    ("Facebook", ("facebook", "fb", "面書", "臉書", "脸书")),
    ("X", ("twitter", "x.com", "推特")),
    ("TikTok", ("tiktok",)),
    ("YouTube", ("youtube",)),
    ("Xiaohongshu", ("xiaohongshu", "rednote", "xhs", "小紅書", "小红书")),
    ("Bilibili", ("bilibili", "b站")),
    ("Zhihu", ("zhihu", "知乎")),
    ("Weibo", ("weibo", "微博")),
    ("Douyin", ("douyin", "抖音")),
    ("WeChat Channels", ("wechat", "微信", "視頻號", "视频号")),
    ("Pinterest", ("pinterest",)),
    ("Reddit", ("reddit",)),
    ("Bluesky", ("bluesky",)),
    ("Telegram", ("telegram",)),
    ("Mastodon", ("mastodon",)),
    ("Snapchat", ("snapchat",)),
    ("Discord", ("discord",)),
)

_CJK = re.compile(r"[一-鿿]")
_SPLIT = re.compile(r"[、，,;；。！!？?\n]+|\s+(?:and|then)\s+|同埋|然後|然后|跟住|之後|之后")
_DAY_WORDS = (
    (re.compile(r"大後日|大后日|大後天|大后天"), 3),
    (re.compile(r"後日|后日|後天|后天|day after tomorrow", re.I), 2),
    (re.compile(r"聽日|听日|明日|明天|tomorrow|\btmr\b", re.I), 1),
    (re.compile(r"今日|今天|today|tonight", re.I), 0),
)
_WEEKDAY_ZH = re.compile(r"(下(?:個|个)?)?(?:星期|禮拜|礼拜|週|周)([一二三四五六日天])")
_WEEKDAY_EN = re.compile(r"\b(next\s+|this\s+)?(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_ZH = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|號|号)?")
_DATE_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_DATE_EN = re.compile(rf"\b(\d{{1,2}})\s*({_MONTHS})[a-z]*\b|\b({_MONTHS})[a-z]*\s+(\d{{1,2}})\b", re.I)
_TIME = re.compile(
    r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)(?![a-z])"   # 4pm · 4:30 pm
    r"|(?<!\d)(\d{1,2}):(\d{2})(?!\d)"                                  # 16:00 · 4:30
    r"|(?<!\d)(\d{1,2})\s*[點点時时]\s*(半|(\d{1,2})\s*分?)?"              # 4 點 · 3 點半 · 4 點 15 分
    r"|中午|正午|\bnoon\b|午夜|\bmidnight\b",
    re.I,
)
_PERIOD_PM = re.compile(r"晏晝|晏昼|下晝|下昼|下午|午後|午后|夜晚|晚上|傍晚|夜|tonight|evening|afternoon|night", re.I)
_PERIOD_AM = re.compile(r"朝早|上晝|上昼|早上|早晨|上午|凌晨|morning", re.I)
_PUBLISH_NOW = re.compile(r"(?:post|publish|send|出|發|发)[^。\n]{0,24}(?:right now|\bnow\b|即刻|而家|立即|馬上|马上)|(?:right now|\bnow\b|即刻|而家|立即|馬上|马上)[^。\n]{0,24}(?:post|publish|send|出|發|发)", re.I)
_RESEARCH = re.compile(r"\bresearch\b|調研|调研|搵(?:下|吓|一下)?(?:資料|资料|素材|例子)|查(?:下|吓|一下)|look up|find sources|搜(?:集|索)|素材", re.I)
_ZH_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_EN_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_EN_MONTHS = {name: index + 1 for index, name in enumerate(_MONTHS.split("|"))}


def safe_zone(value):
    """An IANA zone the platform can resolve, else UTC. Never raises on user input."""
    if isinstance(value, str) and 1 <= len(value) <= 64:
        try:
            ZoneInfo(value)
            return value
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return DEFAULT_ZONE


def detect_language(text):
    return "繁體中文" if _CJK.search(text or "") else "English"


def _platform_mentions(segment):
    lowered = segment.lower()
    found = []
    for platform, aliases in PLATFORM_ALIASES:
        best = None
        for alias in aliases:
            if _CJK.search(alias):
                index = segment.find(alias)
            else:
                match = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", lowered)
                index = match.start() if match else -1
            if index >= 0 and (best is None or index < best):
                best = index
        if best is not None:
            found.append((best, platform))
    return [platform for _, platform in sorted(found)]


def _explicit_day(segment, today):
    """Return (date, label) for the first day reference in the segment, or (None, None)."""
    for pattern, offset in _DAY_WORDS:
        match = pattern.search(segment)
        if match:
            return today + timedelta(days=offset), match.group(0)
    match = _WEEKDAY_ZH.search(segment)
    if match:
        target = _ZH_WEEKDAYS[match.group(2)]
        delta = (target - today.weekday()) % 7
        if match.group(1) and delta == 0:
            delta = 7
        return today + timedelta(days=delta), match.group(0)
    match = _WEEKDAY_EN.search(segment)
    if match:
        target = _EN_WEEKDAYS[match.group(2).lower()]
        delta = (target - today.weekday()) % 7
        if match.group(1) and match.group(1).strip().lower() == "next" and delta == 0:
            delta = 7
        return today + timedelta(days=delta), match.group(0)
    match = _DATE_ISO.search(segment)
    if match:
        try:
            return today.replace(year=int(match.group(1)), month=int(match.group(2)), day=int(match.group(3))), match.group(0)
        except ValueError:
            return None, None
    for pattern, order in ((_DATE_ZH, (1, 2)), (_DATE_SLASH, (1, 2))):
        match = pattern.search(segment)
        if match:
            month, day = int(match.group(order[0])), int(match.group(order[1]))
            return _month_day(today, month, day), match.group(0)
    match = _DATE_EN.search(segment)
    if match:
        if match.group(1):
            day, month = int(match.group(1)), _EN_MONTHS[match.group(2).lower()[:3]]
        else:
            month, day = _EN_MONTHS[match.group(3).lower()[:3]], int(match.group(4))
        return _month_day(today, month, day), match.group(0)
    return None, None


def _month_day(today, month, day):
    for year in (today.year, today.year + 1):
        try:
            candidate = today.replace(year=year, month=month, day=day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def _clock_tokens(segment):
    """Yield (hour, minute, assumed, label) for every time expression in the segment."""
    for match in _TIME.finditer(segment):
        label = match.group(0)
        window = segment[max(0, match.start() - 8):match.start()]
        pm_hint = bool(_PERIOD_PM.search(window))
        am_hint = bool(_PERIOD_AM.search(window))
        token = label.lower()
        if token in ("中午", "正午", "noon"):
            yield 12, 0, False, label
            continue
        if token in ("午夜", "midnight"):
            yield 0, 0, False, label
            continue
        if match.group(1):
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            meridiem = match.group(3).lower().replace(".", "")
            explicit = True
        elif match.group(4):
            hour, minute = int(match.group(4)), int(match.group(5))
            meridiem = None
            explicit = hour >= 13 or match.group(4).startswith("0")
        else:
            hour = int(match.group(6))
            minute = 30 if match.group(7) == "半" else int(match.group(8) or 0)
            meridiem = None
            explicit = hour >= 13
        if hour > 23 or minute > 59:
            continue
        assumed = False
        if meridiem == "pm" or (meridiem is None and pm_hint and not explicit):
            hour = hour % 12 + 12
        elif meridiem == "am" or (meridiem is None and am_hint and not explicit):
            hour = hour % 12
        elif not explicit:
            if 1 <= hour <= 6:
                hour, assumed = hour + 12, True
            elif 7 <= hour <= 11:
                assumed = True
        yield hour, minute, assumed, label


def parse_request(text, now, zone=DEFAULT_ZONE, supported=None):
    """Parse a chat turn into an intent, mentioned channels and a candidate schedule.

    `now` is an epoch; `zone` an IANA name (already validated with `safe_zone`); `supported`
    an optional iterable of platform names the runtime can draft for. Every time is returned
    as a naive local ISO string ("2026-09-16T16:00") for the platform's `resolve_time`.
    """
    text = text if isinstance(text, str) else ""
    zone = safe_zone(zone)
    now_local = datetime.fromtimestamp(now, ZoneInfo(zone)).replace(tzinfo=None)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    supported_set = set(supported) if supported else None
    destinations, unattached, warnings = [], [], []
    carry_day = None
    for segment in (s for s in _SPLIT.split(text) if s and s.strip()):
        platforms = _platform_mentions(segment)
        day, day_label = _explicit_day(segment, today)
        if day is None and day_label is not None:
            warnings.append(f"“{day_label}” is not a valid date; that time was ignored.")
            continue
        if day is not None:
            carry_day = day
        times = []
        for hour, minute, assumed, label in _clock_tokens(segment):
            base = day if day is not None else carry_day
            explicit_day = base is not None
            when = (base or today).replace(hour=hour, minute=minute)
            rolled = False
            if when <= now_local and not explicit_day:
                when, rolled = when + timedelta(days=1), True
            times.append({"localTime": when.strftime("%Y-%m-%dT%H:%M"), "assumed": assumed, "label": label, "past": when <= now_local, "rolled": rolled})
        for index, platform in enumerate(platforms):
            if any(d["platform"] == platform for d in destinations):
                continue
            slot = times[min(index, len(times) - 1)] if times else None
            destinations.append({"platform": platform, "supported": supported_set is None or platform in supported_set, **_slot(slot)})
        if not platforms:
            unattached.extend(times)
        elif len(times) > len(platforms):
            unattached.extend(times[len(platforms):])
    # Times without a channel in their clause fall to earlier channels that still lack one.
    for destination in destinations:
        if destination["localTime"] is None and unattached:
            destination.update(_slot(unattached.pop(0)))
    for destination in destinations:
        if destination.get("assumed"):
            warnings.append(f"Read “{destination['label']}” as {destination['localTime'][11:]} for {destination['platform']}; change it if that is not what you meant.")
        if destination.get("past"):
            warnings.append(f"{destination['platform']} at {destination['localTime'].replace('T', ' ')} has already passed in {zone}.")
        if destination.get("rolled"):
            warnings.append(f"“{destination['label']}” had already passed today, so {destination['platform']} moved to tomorrow.")
    unsupported = [d["platform"] for d in destinations if not d["supported"]]
    has_times = any(d["localTime"] for d in destinations) or bool(unattached)
    if _PUBLISH_NOW.search(text):
        intent = "publish_now"
    elif has_times:
        intent = "schedule"
    elif _RESEARCH.search(text):
        intent = "research"
    else:
        intent = "draft"
    return {
        "intent": intent,
        "language": detect_language(text),
        "timeZone": zone,
        "destinations": [{k: d[k] for k in ("platform", "supported", "localTime", "assumed")} for d in destinations],
        "unattachedTimes": [{"localTime": t["localTime"], "assumed": t["assumed"]} for t in unattached],
        "unsupported": unsupported,
        "warnings": warnings,
        "hasTimes": has_times,
    }


def _slot(slot):
    if not slot:
        return {"localTime": None, "assumed": False, "label": None, "past": False, "rolled": False}
    return {"localTime": slot["localTime"], "assumed": slot["assumed"], "label": slot["label"], "past": slot["past"], "rolled": slot["rolled"]}


def resolve_destinations(parsed, requested, language, default):
    """Channels named in the message win; otherwise the composer's selection; otherwise the default."""
    if language not in LANGUAGES:
        language = parsed["language"]
    named = [d["platform"] for d in parsed["destinations"] if d["supported"]]
    if named:
        return [{"platform": platform, "language": language} for platform in named]
    if isinstance(requested, list) and requested:
        return [{"platform": d.get("platform"), "language": d.get("language", language)} for d in requested if isinstance(d, dict)]
    return [dict(d) for d in default]


def build_plan(parsed, destinations):
    """Attach parsed times to the destinations that will actually be drafted. None when nothing is timed."""
    spare = list(parsed["unattachedTimes"])
    rows = []
    for destination in destinations:
        match = next((d for d in parsed["destinations"] if d["platform"] == destination["platform"] and d["localTime"]), None)
        slot = match or (spare.pop(0) if spare else None)
        if slot is None and parsed["unattachedTimes"]:
            slot = parsed["unattachedTimes"][-1]
        rows.append({"platform": destination["platform"], "language": destination["language"], "localTime": slot["localTime"] if slot else None, "assumed": bool(slot and slot["assumed"])})
    if not any(row["localTime"] for row in rows):
        return None
    return {"kind": "schedule", "intent": parsed["intent"], "timeZone": parsed["timeZone"], "destinations": rows, "unsupported": list(parsed["unsupported"]), "warnings": list(parsed["warnings"])}
