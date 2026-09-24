"""Date ranges named in a question, in the person's time zone ("this week", "Friday", "next week", 聽日, 上個星期).

Used by the calendar, publishing and search reads. A range is [start, end) in epoch seconds with a readable label.
Weeks run Monday to Sunday. A bare weekday means that day in the current week, or next week's when it has passed.
Nothing here guesses beyond the words: no range named means no range.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ZH_DAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def _zone(name):
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 — an unknown zone reads as UTC, never an error
        return ZoneInfo("UTC")


def _day_start(date, zone):
    return dt.datetime(date.year, date.month, date.day, tzinfo=zone)


def _range(start_date, days, zone, label):
    start = _day_start(start_date, zone)
    end = _day_start(start_date + dt.timedelta(days=days), zone)
    return {"start": start.timestamp(), "end": end.timestamp(), "label": label, "startDate": start_date.isoformat(),
            "endDate": (start_date + dt.timedelta(days=days - 1)).isoformat()}


def parse(text: str, now: float, zone_name: str | None) -> dict | None:
    """The first range the text names, or None."""
    zone = _zone(zone_name)
    today = dt.datetime.fromtimestamp(now, zone).date()
    monday = today - dt.timedelta(days=today.weekday())
    lower = (text or "").lower()
    if re.search(r"\btoday\b|今日|今天", lower):
        return _range(today, 1, zone, "today")
    if re.search(r"\btomorrow\b|聽日|明天|明日", lower):
        return _range(today + dt.timedelta(days=1), 1, zone, "tomorrow")
    if re.search(r"\byesterday\b|琴日|尋日|昨天|昨日", lower):
        return _range(today - dt.timedelta(days=1), 1, zone, "yesterday")
    if re.search(r"\bnext\s+week\b|下(?:個|个)?(?:星期|禮拜|礼拜|週|周)(?![一二三四五六日天])", lower):
        return _range(monday + dt.timedelta(days=7), 7, zone, "next week")
    if re.search(r"\blast\s+week\b|\bpast\s+week\b|上(?:個|个)?(?:星期|禮拜|礼拜|週|周)(?![一二三四五六日天])", lower):
        return _range(monday - dt.timedelta(days=7), 7, zone, "last week")
    if re.search(r"\bthis\s+week\b|\bthe\s+week\b|今(?:個|个)?(?:星期|禮拜|礼拜|週|周)(?![一二三四五六日天])|呢(?:個|个)?(?:星期|禮拜)", lower):
        return _range(monday, 7, zone, "this week")
    if re.search(r"\bnext\s+7\s+days\b|\bcoming\s+week\b", lower):
        return _range(today, 7, zone, "the next 7 days")
    if re.search(r"\blast\s+month\b|上(?:個|个)?月", lower):
        first = today.replace(day=1)
        previous = (first - dt.timedelta(days=1)).replace(day=1)
        return _range(previous, (first - previous).days, zone, "last month")
    if re.search(r"\bthis\s+month\b|今(?:個|个)?月|呢(?:個|个)?月", lower):
        first = today.replace(day=1)
        following = (first + dt.timedelta(days=32)).replace(day=1)
        return _range(first, (following - first).days, zone, "this month")
    if re.search(r"\bnext\s+month\b|下(?:個|个)?月", lower):
        first = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        following = (first + dt.timedelta(days=32)).replace(day=1)
        return _range(first, (following - first).days, zone, "next month")
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lower)
    if iso:
        try:
            day = dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return _range(day, 1, zone, day.isoformat())
        except ValueError:
            return None
    named = re.search(r"\b(" + "|".join(_MONTHS) + r")[a-z]*\s+(\d{1,2})\b|\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")[a-z]*\b", lower)
    if named:
        month_name = named.group(1) or named.group(4)
        day_number = int(named.group(2) or named.group(3))
        month = next(i for i, m in enumerate(_MONTHS, 1) if m.startswith(month_name[:3]))
        try:
            day = dt.date(today.year, month, day_number)
            return _range(day, 1, zone, day.isoformat())
        except ValueError:
            return None
    for index, name in enumerate(WEEKDAYS):
        if re.search(rf"\b(next\s+)?{name}s?\b|\b(next\s+)?{name[:3]}\b", lower):
            later = re.search(rf"\bnext\s+{name[:3]}", lower)
            day = monday + dt.timedelta(days=index)
            if day < today or later:
                day += dt.timedelta(days=7)
            return _range(day, 1, zone, day.strftime("%A %Y-%m-%d"))
    zh = re.search(r"(下(?:個|个)?)?(?:星期|禮拜|礼拜|週|周)([一二三四五六日天])", text or "")
    if zh:
        day = monday + dt.timedelta(days=_ZH_DAY[zh.group(2)])
        if day < today or zh.group(1):
            day += dt.timedelta(days=7)
        return _range(day, 1, zone, day.strftime("%A %Y-%m-%d"))
    return None


def local(epoch: float | None, zone_name: str | None) -> str | None:
    if not isinstance(epoch, (int, float)):
        return None
    return dt.datetime.fromtimestamp(epoch, _zone(zone_name)).strftime("%a %Y-%m-%d %H:%M")


def date_of(epoch: float, zone_name: str | None) -> str:
    return dt.datetime.fromtimestamp(epoch, _zone(zone_name)).date().isoformat()
