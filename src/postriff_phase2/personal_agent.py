"""Read-only personal tool router for James Daily Call.

The opening brief is warm context, not a knowledge boundary. Follow-up questions
are routed to connected personal sources without invoking the Rafii social-content
Manager. All provider text is untrusted data and results are bounded for GPT-Live.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from postriff_alpha.domain import AlphaError, clean

from .agent_runtime_v2 import live_tools
from . import research


MAX_SPEAKABLE = 1200
MAX_WEB_QUESTION = 400

_CALENDAR_WORDS = re.compile(
    r"\b(calendar|schedule|appointment|appointments|meeting|meetings|event|events|class|classes|lesson|lessons|recital|rehearsal)\b"
    r"|行程|日程|活動|活动|會議|会议|課堂|课堂|上堂|堂|演出|排練|排练|幾時|几时",
    re.I,
)
_EMAIL_WORDS = re.compile(r"\b(gmail|email|emails|inbox|mail|reply|replied|unread)\b|郵件|邮件|電郵|电邮|收件箱|未讀|未读|回覆|回复|覆我|覆咗", re.I)
_PROJECT_WORDS = re.compile(r"\b(project|projects|codex|kynlo|orc|dori|d festival|rafii|mission|missions|branch|build|deploy|deployment|tests?|blocker|progress)\b|項目|项目|進度|进度|工程|任務|任务|分支|驗收|验收", re.I)
_WEATHER_WORDS = re.compile(r"\b(weather|temperature|forecast|rain|snow|hot|cold|windy)\b|天氣|天气|氣溫|气温|落雨|下雨|落雪|下雪|凍唔凍|冷唔冷|熱唔熱|热不热", re.I)
_WEB_WORDS = re.compile(r"\b(latest|news|current|price|pricing|release|released|launch|today's news|score|result|results)\b|最新|新聞|新闻|價格|价格|幾錢|多少钱|發布|发布|比賽結果|比赛结果", re.I)

_TIME_WORDS = re.compile(r"\b(today|tomorrow|week|weekend|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|今日|今天|聽日|听日|明天|今個禮拜|今个礼拜|今星期|本週|本周|下個禮拜|下个礼拜|下星期|下週|下周|週末|周末|星期[一二三四五六日天]|週[一二三四五六日天]|周[一二三四五六日天]", re.I)
_EXPLICIT_CALENDAR_RANGE = re.compile(
    r"\b(today|tomorrow|this\s+week|next\s+week|next\s+7\s+days?|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|20\d{2}-\d{2}-\d{2})\b"
    r"|今日|今天|聽日|听日|明天|今個禮拜|今个礼拜|今星期|本週|本周|下個禮拜|下个礼拜|下星期|下週|下周|週末|周末|星期[一二三四五六日天]|週[一二三四五六日天]|周[一二三四五六日天]",
    re.I,
)

_WEEKDAYS = {
    "monday": 0, "星期一": 0, "週一": 0, "周一": 0,
    "tuesday": 1, "星期二": 1, "週二": 1, "周二": 1,
    "wednesday": 2, "星期三": 2, "週三": 2, "周三": 2,
    "thursday": 3, "星期四": 3, "週四": 3, "周四": 3,
    "friday": 4, "星期五": 4, "週五": 4, "周五": 4,
    "saturday": 5, "星期六": 5, "週六": 5, "周六": 5,
    "sunday": 6, "星期日": 6, "星期天": 6, "週日": 6, "周日": 6,
}


@dataclass(frozen=True)
class PersonalToolResult:
    status: str
    kind: str
    speakable: str
    source_count: int = 0
    fresh_at: float | None = None

    def as_dict(self):
        return {
            "status": self.status,
            "kind": self.kind,
            "speakable": _bounded(self.speakable, MAX_SPEAKABLE),
            "sourceCount": int(self.source_count),
            **({"freshAt": float(self.fresh_at)} if self.fresh_at is not None else {}),
        }


def _bounded(value, limit):
    text = " ".join(str(value or "").split())
    return clean(text[:limit], limit) if text else ""


def _local_day(clock, zone):
    local = datetime.fromtimestamp(float(clock), zone)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def calendar_window(question, now, time_zone):
    """Resolve common English/Cantonese/Mandarin calendar ranges."""
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise AlphaError("Choose a valid time zone.", 400) from None
    text = (question or "").casefold()
    day = _local_day(now, zone)

    if re.search(r"\bnext\s+7\s+days?\b|未來\s*7\s*日|未来\s*7\s*天", text):
        return day.timestamp(), (day + timedelta(days=7)).timestamp(), "the next 7 days"
    if re.search(r"\bnext\s+week\b|下個禮拜|下个礼拜|下星期|下週|下周", text):
        monday = day + timedelta(days=(7 - day.weekday()))
        return monday.timestamp(), (monday + timedelta(days=7)).timestamp(), "next week"
    if re.search(r"\bthis\s+week\b|今個禮拜|今个礼拜|今星期|本週|本周", text):
        monday = day - timedelta(days=day.weekday())
        return day.timestamp(), (monday + timedelta(days=7)).timestamp(), "the rest of this week"
    if re.search(r"\bweekend\b|週末|周末", text):
        days_to_sat = (5 - day.weekday()) % 7
        saturday = day + timedelta(days=days_to_sat)
        if day.weekday() == 6:
            saturday = day - timedelta(days=1)
        return saturday.timestamp(), (saturday + timedelta(days=2)).timestamp(), "this weekend"
    if re.search(r"\btomorrow\b|聽日|听日|明天", text):
        start = day + timedelta(days=1)
        return start.timestamp(), (start + timedelta(days=1)).timestamp(), "tomorrow"
    if re.search(r"\btoday\b|今日|今天", text):
        return day.timestamp(), (day + timedelta(days=1)).timestamp(), "today"

    match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            start = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=zone)
        except ValueError:
            raise AlphaError("That date is not valid.", 400) from None
        return start.timestamp(), (start + timedelta(days=1)).timestamp(), match.group(0)

    for name, weekday in _WEEKDAYS.items():
        if name in text:
            delta = (weekday - day.weekday()) % 7
            if delta == 0 and not re.search(r"\btoday\b|今日|今天", text):
                delta = 7
            start = day + timedelta(days=delta)
            return start.timestamp(), (start + timedelta(days=1)).timestamp(), name

    # Calendar questions without a range get a useful bounded horizon rather than today's warm snapshot.
    return day.timestamp(), (day + timedelta(days=7)).timestamp(), "the next 7 days"


def _format_local(iso_value, zone):
    if not iso_value:
        return ""
    raw = str(iso_value)
    try:
        if len(raw) == 10:
            dt = datetime.fromisoformat(raw).replace(tzinfo=zone)
            return dt.strftime("%a %b %-d")
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(zone)
        return dt.strftime("%a %b %-d at %-I:%M %p")
    except (ValueError, TypeError):
        return _bounded(raw, 45)


def _search_terms(question):
    text = str(question or "")
    # Remove question scaffolding while preserving names, project titles and multilingual content.
    text = re.sub(r"(?i)\b(what|when|where|who|which|do|does|did|have|has|had|is|are|was|were|can|could|would|please|tell|show|find|check|me|my|the|a|an|any|about|on|for|in|this|that|next|today|tomorrow|week|email|emails|gmail|mail|inbox|reply|replied)\b", " ", text)
    for phrase in ("有冇", "有沒有", "有没有", "幫我", "帮我", "睇下", "看看", "查下", "查一下", "我", "嘅", "的", "電郵", "电邮", "郵件", "邮件", "回覆", "回复", "覆我", "今日", "今天", "聽日", "明天", "下個禮拜", "下星期", "下週", "下周"):
        text = text.replace(phrase, " ")
    text = re.sub(r"[^\w@.\-\u3400-\u9fff ]+", " ", text)
    terms = [part for part in text.split() if len(part) > 1][:8]
    return " ".join(terms)[:160]


def gmail_query(question):
    text = (question or "").casefold()
    parts = ["in:inbox"]
    if re.search(r"\bunread\b|未讀|未读", text):
        parts.append("is:unread")
    if re.search(r"\btoday\b|今日|今天", text):
        parts.append("newer_than:1d")
    elif re.search(r"\bthis\s+week\b|今個禮拜|今星期|本週|本周", text):
        parts.append("newer_than:7d")
    elif re.search(r"\brepl(?:y|ied)\b|回覆|回复|覆我|覆咗", text):
        parts.append("newer_than:30d")
    else:
        parts.append("newer_than:14d")
    if re.search(r"\bimportant\b|\bstarred\b|重要|要處理|要处理|attention", text):
        parts.append("{is:important is:starred}")
    address = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", question or "")
    if address:
        parts.append("from:" + address.group(0))
    terms = _search_terms(question)
    if terms and not address:
        parts.append('"' + terms.replace('"', "") + '"')
    parts += ["-category:promotions", "-category:social"]
    return " ".join(parts)[:500]


def _calendar_speakable(items, label, zone):
    if not items:
        return f"I checked your Google Calendar for {label}. You have no events in that range."
    lines = []
    for item in items[:8]:
        when = _format_local(item.get("start"), zone)
        title = _bounded(item.get("title") or "Busy", 80)
        location = _bounded(item.get("location"), 55)
        lines.append(f"{when}: {title}" + (f" at {location}" if location else ""))
    return f"I checked your Google Calendar for {label}. " + "; ".join(lines)


def _calendar_search_speakable(items):
    if not items:
        return "I searched your upcoming Google Calendar and didn't find a matching event."
    lines = []
    for item in items[:6]:
        title = _bounded(item.get("title") or "Busy", 85)
        excerpt = _bounded(item.get("excerpt"), 90)
        lines.append(title + (": " + excerpt if excerpt else ""))
    return "I searched your upcoming Google Calendar. " + "; ".join(lines)


def _gmail_speakable(items):
    if not items:
        return "I checked your Gmail and didn't find a matching message."
    lines = []
    for item in items[:5]:
        sender = _bounded(item.get("from"), 60)
        subject = _bounded(item.get("subject") or "Email", 90)
        lines.append((sender + ": " if sender else "") + subject)
    return "I checked your Gmail. " + "; ".join(lines)


def _project_speakable(items, query):
    if not items:
        return "I checked Project Pulse and couldn't find a matching active or recent project."
    terms = [x.casefold() for x in _search_terms(query).split() if len(x) > 2]
    if terms:
        matched = []
        for item in items:
            hay = " ".join(str(item.get(k) or "") for k in ("title", "project", "branch", "state", "verification", "nextAction", "client")).casefold()
            if any(term in hay for term in terms):
                matched.append(item)
        if matched:
            items = matched
    lines = []
    for item in items[:5]:
        name = _bounded(item.get("project") or item.get("title") or "Project", 70)
        state = _bounded(item.get("state"), 30)
        verification = _bounded(item.get("verification"), 55)
        action = _bounded(item.get("nextAction"), 85)
        detail = name + (f" is {state}" if state else "")
        if verification:
            detail += f", {verification}"
        if action:
            detail += f"; next: {action}"
        lines.append(detail)
    return "I checked Project Pulse. " + "; ".join(lines)


def _weather_place(question, default_place=""):
    text = str(question or "").strip()
    for pattern in (
        r"(?i)\bweather\s+(?:in|for|at)\s+([^?.!,]{2,80})",
        r"(?i)\bforecast\s+(?:in|for|at)\s+([^?.!,]{2,80})",
    ):
        match = re.search(pattern, text)
        if match:
            return _bounded(re.sub(r"\b(today|tomorrow|tonight)\b.*$", "", match.group(1), flags=re.I), 80)
    match = re.search(r"([^，。？！?]{2,50})(?:今日|今天|聽日|明天|今晚)?(?:嘅|的)?(?:天氣|天气)", text)
    if match:
        place = _bounded(match.group(1), 80)
        if not re.fullmatch(r"(今日|今天|聽日|明天|今晚|而家|現在|现在)", place):
            return place
    return _bounded(default_place, 80)


def _weather_speakable(found):
    current = found.get("current") or {}
    today = found.get("today") or {}
    c = current.get("temperatureC")
    feels = current.get("feelsLikeC")
    def f(value):
        return None if not isinstance(value, (int, float)) else round(value * 9 / 5 + 32)
    temp = f(c)
    feels_f = f(feels)
    pieces = [f"Weather for {found.get('place') or 'that place'}: {current.get('conditions') or 'conditions unavailable'}"]
    if temp is not None:
        pieces.append(f"{temp}°F ({c:g}°C)")
    if feels_f is not None:
        pieces.append(f"feels like {feels_f}°F")
    if isinstance(today.get("highC"), (int, float)) and isinstance(today.get("lowC"), (int, float)):
        pieces.append(f"today {f(today['lowC'])}–{f(today['highC'])}°F")
    if isinstance(today.get("rainChancePercent"), (int, float)):
        pieces.append(f"rain chance {int(today['rainChancePercent'])}%")
    return ", ".join(pieces) + "."


class JamesPersonalRouter:
    def __init__(self, daily):
        self.daily = daily

    @property
    def connectors(self):
        return getattr(self.daily.hosted, "productivity_connectors", None)

    def _calendar(self, question):
        if self.connectors is None:
            return PersonalToolResult("unavailable", "calendar", "Your Google Calendar connection is unavailable right now.")
        try:
            if not _EXPLICIT_CALENDAR_RANGE.search(question or ""):
                terms = _search_terms(question)
                if terms:
                    items = self.connectors.personal_calendar_search(
                        self.daily.cfg.workspace_id, self.daily.cfg.user_id, terms, 12,
                        account_bindings=self.daily.cfg.briefing_bindings,
                    )
                    return PersonalToolResult("ok", "calendar", _calendar_search_speakable(items), len(items), self.daily.clock())
            start, end, label = calendar_window(question, self.daily.clock(), self.daily.cfg.time_zone)
            items = self.connectors.personal_calendar_range(
                self.daily.cfg.workspace_id, self.daily.cfg.user_id, self.daily.cfg.time_zone, start, end, 20,
                account_bindings=self.daily.cfg.briefing_bindings,
            )
        except AlphaError:
            return PersonalToolResult("unavailable", "calendar", "I couldn't read your Google Calendar just now.")
        zone = ZoneInfo(self.daily.cfg.time_zone)
        return PersonalToolResult("ok", "calendar", _calendar_speakable(items, label, zone), len(items), self.daily.clock())

    def _gmail(self, question):
        if self.connectors is None:
            return PersonalToolResult("unavailable", "gmail", "Your Gmail connection is unavailable right now.")
        try:
            items = self.connectors.personal_gmail_search(
                self.daily.cfg.workspace_id, self.daily.cfg.user_id, gmail_query(question), 8,
                account_bindings=self.daily.cfg.briefing_bindings,
            )
        except AlphaError:
            return PersonalToolResult("unavailable", "gmail", "I couldn't search your Gmail just now.")
        return PersonalToolResult("ok", "gmail", _gmail_speakable(items), len(items), self.daily.clock())

    def _projects(self, question):
        result = self.daily.project_pulse.fetch()
        if result.get("status") != "ok":
            return PersonalToolResult("unavailable", "project", "Project Pulse is unavailable right now.")
        items = result.get("items") or []
        return PersonalToolResult("ok", "project", _project_speakable(items, question), len(items), self.daily.clock())

    def _weather(self, question, *, followup=False):
        place = _weather_place(question, self.daily.values.get("JAMES_DAILY_CALL_DEFAULT_WEATHER_PLACE", ""))
        if not place and followup:
            candidate = _bounded(question, 80)
            if candidate and not re.search(r"[?？]|\b(what|how|weather|forecast)\b|天氣|天气", candidate, re.I):
                place = candidate
        if not place:
            return PersonalToolResult("needs_input", "weather", "Which city or place should I check the weather for?")
        try:
            found = live_tools.default_weather().now(place, language="en", timeout=live_tools.TIMEOUT_SECONDS)
        except live_tools.PlaceNotFound:
            return PersonalToolResult("needs_input", "weather", f"I couldn't find a place called {_bounded(place, 60)}. Which city should I use?")
        except live_tools.WeatherUnavailable:
            return PersonalToolResult("unavailable", "weather", "The weather service didn't answer just now. Please try again in a moment.")
        return PersonalToolResult("ok", "weather", _weather_speakable(found), 1, self.daily.clock())

    def _web(self, question):
        try:
            with self.daily.hosted.connection_factory() as db, db.cursor() as cur:
                cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (self.daily.cfg.workspace_id,))
                row = cur.fetchone()
            state = row[0] if row and isinstance(row[0], dict) else json.loads(row[0]) if row and row[0] else {}
            if not research.allowed(state):
                return PersonalToolResult("unavailable", "web", "Web research is off for this account, so I can't verify that current fact in this call.")
            researcher = getattr(self.daily.hosted, "researcher", None) or research.Researcher()
            found = researcher.run(_bounded(question, MAX_WEB_QUESTION))
        except Exception:
            return PersonalToolResult("unavailable", "web", "I couldn't reach web research just now.")
        pages = found.get("pages") or []
        facts = []
        for page in pages[:2]:
            title = _bounded(page.get("title"), 80)
            published = _bounded(page.get("published"), 30)
            page_facts = [_bounded(x, 150) for x in (page.get("facts") or [])[:2] if x]
            if page_facts:
                facts.append((title + (f" ({published})" if published else "") + ": " + " ".join(page_facts)))
        if not facts:
            return PersonalToolResult("unavailable", "web", "I searched the web but couldn't verify a useful answer.")
        return PersonalToolResult("ok", "web", "I checked current web sources. " + " ".join(facts), len(pages), self.daily.clock())

    def route(self, question, hint=None):
        question = _bounded(question, 800)
        if not question:
            return PersonalToolResult("needs_input", "snapshot", "I didn't catch that. Please say the question again.").as_dict()

        # One question can mention multiple personal domains. Return a compact combined result.
        handlers = []
        calendarish = bool(_CALENDAR_WORDS.search(question)) or (
            bool(_TIME_WORDS.search(question)) and bool(re.search(r"\b(have|doing|busy|free|going|happening)\b|有咩|有什麼|有什么|做咩|安排", question, re.I))
        )
        if calendarish:
            handlers.append(self._calendar)
        if _EMAIL_WORDS.search(question):
            handlers.append(self._gmail)
        if _PROJECT_WORDS.search(question):
            handlers.append(self._projects)
        if _WEATHER_WORDS.search(question):
            handlers.append(self._weather)
        if _WEB_WORDS.search(question) and not handlers:
            handlers.append(self._web)

        # Call-local continuity: short follow-ups inherit the last verified personal tool domain.
        if not handlers and hint:
            base = str(hint).split("+", 1)[0]
            if base == "calendar" and (_TIME_WORDS.search(question) or len(question) <= 80):
                handlers.append(self._calendar)
            elif base == "gmail" and len(question) <= 160:
                handlers.append(self._gmail)
            elif base == "project" and len(question) <= 160:
                handlers.append(self._projects)
            elif base == "weather" and len(question) <= 100:
                handlers.append(lambda q: self._weather(q, followup=True))

        if not handlers:
            # Unknown personal follow-up: refresh bounded personal sources instead of silently routing to Rafii.
            try:
                text = self.daily.personal_context_refresh()
                return PersonalToolResult("ok", "snapshot", text, fresh_at=self.daily.clock()).as_dict()
            except Exception:
                return PersonalToolResult("unavailable", "snapshot", "I don't have enough verified personal data to answer that yet.").as_dict()

        results = [handler(question) for handler in handlers[:3]]
        speakable = " ".join(item.speakable for item in results if item.speakable)
        status = "ok" if any(item.status == "ok" for item in results) else results[0].status
        return PersonalToolResult(
            status, "+".join(item.kind for item in results), speakable,
            sum(item.source_count for item in results), self.daily.clock()
        ).as_dict()
