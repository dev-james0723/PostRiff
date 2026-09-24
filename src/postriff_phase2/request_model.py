"""Rafii reads a request before acting on it (agent chat: automation or drafts).

When a message could ask for drafts on a schedule, a small model decides what the person wants: drafts now, or
drafts prepared again and again (an automation), and for an automation the days, time, topic, kind of post and voice.
It runs only where the writer the person chose would already receive the message: the person's own Claude Code for
a Claude Code writer, the managed gateway for a managed writer, never for the preview writer. A managed call's cost
is reserved before the message leaves and settled after (IdeasService._read_request). The answer is a proposal:
every field is checked against this workspace here, and the automation is saved with the Automations builder's
checks. When the model is unavailable, over budget, fails or answers out of bounds, the deterministic reading
(intent.is_automation_request, automation_chat) decides instead.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from zoneinfo import ZoneInfo

from postriff_alpha.domain import AlphaError, clean

from . import campaigns, content_types

UNDERSTANDING_MODEL = "anthropic/claude-haiku-4.5"
CLI_ALIAS = "haiku"
MAX_MESSAGE_CHARS = 2000
MAX_OUTPUT_TOKENS = 700
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
# Words that can introduce a recurring request in English or Chinese; a message without any is drafted as usual.
CUE = re.compile(
    r"\b(?:every|each|weekly|daily|monthly|fortnightly|bi-?weekly|twice|thrice|once\s+a|times\s+a|per\s+(?:week|month|day)"
    r"|a\s+(?:week|month)\b|regularly|routinely|recurring|automat\w*|keep\s+(?:posting|my|sharing)|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays"
    r"|count\s*down)"
    r"|逢|每|定期|自動|自动|倒數|倒数",
    re.I)

SYSTEM_PROMPT = """You read one message a person typed to Rafii, an assistant that drafts social media posts, and decide what they want.
- "automation": they want Rafii to prepare drafts again and again on a schedule (for example "every Tuesday", "twice a week", "each month", "keep my LinkedIn going with AI news", "逢星期二", "每月"). Only a request for future, recurring drafts counts.
- "draft": anything else, including one post about a recurring thing ("write my weekly recap") or a message that only describes a habit ("I practise every day, write about it").
For an automation, fill "automation": weekdays (or monthDays for a monthly schedule; use "last" for the last day), localTime only if a time is named (24-hour HH:MM), the topic, one sentence describing each draft (goal), a short name, contentTypeId and formatId only when the message asks for that kind of post (choose from the lists given), voice true when they ask for their own voice or style, and every assumption you had to make (for "twice a week" pick two well-spaced weekdays and say so). Use the person's words for the topic. Never invent facts, dates, accounts or channels. Answer with JSON only.
- A countdown to one dated event ("two weeks before, one week before and on the day", "倒數") is not a weekly or monthly schedule: fill "countdown" instead of weekdays or monthDays, with eventDate (YYYY-MM-DD, worked out from the message and "now") and daysBefore (whole days before the event; 0 is the day itself). Leave countdown out when the message names no date."""


def offered(state: dict) -> list[dict]:
    """The content types an automation can use here: this workspace's, plus the starter pack's (installed on use)."""
    items = {item["id"]: item for item in content_types.resolve_catalog(state)}
    for item in content_types.CREATOR_TYPES:
        items.setdefault(item["id"], item)
    return list(items.values())


def schema(state: dict) -> dict:
    types = [item["id"] for item in offered(state)]
    return {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["draft", "automation"]},
            "automation": {"type": "object", "additionalProperties": False, "properties": {
                "weekdays": {"type": "array", "maxItems": 7, "items": {"type": "string", "enum": list(campaigns.WEEKDAY_NAMES)}},
                "monthDays": {"type": "array", "maxItems": campaigns.MAX_MONTH_DAYS, "items": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 31}, {"type": "string", "enum": ["last"]}]}},
                "localTime": {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
                "countdown": {"type": "object", "additionalProperties": False, "required": ["eventDate", "daysBefore"], "properties": {
                    "eventDate": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                    "daysBefore": {"type": "array", "minItems": 1, "maxItems": campaigns.MAX_COUNTDOWN_STEPS,
                                   "items": {"type": "integer", "minimum": 0, "maximum": campaigns.MAX_COUNTDOWN_DAYS}}}},
                "topic": {"type": "string", "maxLength": 160},
                "goal": {"type": "string", "maxLength": 600},
                "name": {"type": "string", "maxLength": 80},
                "contentTypeId": {"type": "string", "enum": types},
                "formatId": {"type": "string", "enum": sorted(content_types.FORMAT_IDS)},
                "voice": {"type": "boolean"},
                "assumptions": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
            }},
        },
    }


def user_prompt(text: str, zone: str, now: float, state: dict) -> str:
    """Only the message, the date and the names of what this workspace offers; never sources, memory or accounts."""
    local = dt.datetime.fromtimestamp(now, ZoneInfo(zone))
    catalog = [{"id": item["id"], "label": item["label"], "formats": item.get("recommendedFormatIds", [])} for item in offered(state)]
    return "INPUT\n" + json.dumps({
        "message": clean(text, MAX_MESSAGE_CHARS), "now": local.strftime("%A %Y-%m-%d %H:%M"), "timeZone": zone,
        "contentTypes": catalog, "formats": [{"id": key, "label": label} for key, label in content_types.FORMATS],
    }, ensure_ascii=False, indent=1)


def price_quote_micro(state: dict, user: str) -> int:
    """A conservative ceiling: request bytes as tokens plus framing, and the full output allowance."""
    from .model_runtime import DEFAULT_PRICES
    ip, op = DEFAULT_PRICES[UNDERSTANDING_MODEL]
    size = len((SYSTEM_PROMPT + json.dumps(schema(state), separators=(",", ":")) + user).encode())
    return math.ceil((size + 1024) * ip + MAX_OUTPUT_TOKENS * op)


def call_for(runtime, override=None):
    """The structured call for this writer route, or None where the message must not go to another model."""
    if override is not None:
        return override
    from .cli_runtime import ClaudeCliRuntime
    from .learning_model import ClaudeCliCall, GatewayCall
    from .model_runtime import ServerModelRuntime
    if isinstance(runtime, ClaudeCliRuntime):
        return ClaudeCliCall(runtime, alias=CLI_ALIAS)
    if isinstance(runtime, ServerModelRuntime) and getattr(runtime, "api_key", None):
        return GatewayCall(runtime.api_key, model=UNDERSTANDING_MODEL, endpoint=runtime.endpoint, transport=runtime.transport)
    return None


def reading(answer, state: dict) -> dict | None:
    """The model's answer, kept only where it fits this workspace; None when it does not say what to do."""
    if not isinstance(answer, dict) or answer.get("action") not in ("draft", "automation"):
        return None
    if answer["action"] == "draft":
        return {"action": "draft"}
    raw = answer.get("automation") if isinstance(answer.get("automation"), dict) else {}
    out = {}
    weekdays = [day for day in campaigns.WEEKDAY_NAMES if day in (raw.get("weekdays") or [])]
    month_days = [day for day in (raw.get("monthDays") or []) if day == "last" or (type(day) is int and 1 <= day <= 31)][:campaigns.MAX_MONTH_DAYS]
    countdown = raw.get("countdown") if isinstance(raw.get("countdown"), dict) else None
    if countdown is not None:
        try:
            event, days_before = campaigns.countdown_of(countdown)
            countdown = {"eventDate": event.isoformat(), "daysBefore": days_before}
        except AlphaError:
            countdown = None
    if countdown:
        # A countdown runs before one event; days of the week or month would repeat after it.
        out["countdown"] = countdown
    elif weekdays:
        out["weekdays"] = weekdays
    elif month_days:
        out["monthDays"] = list(dict.fromkeys(month_days))
    if isinstance(raw.get("localTime"), str) and TIME.fullmatch(raw["localTime"]):
        out["localTime"] = raw["localTime"]
    for key, limit in (("topic", 160), ("goal", 600), ("name", 80)):
        if isinstance(raw.get(key), str) and raw[key].strip():
            out[key] = clean(raw[key], limit)
    if isinstance(raw.get("contentTypeId"), str):
        item = next((entry for entry in offered(state) if entry["id"] == raw["contentTypeId"]), None)
        if item is not None:
            out["contentTypeId"] = item["id"]
            if raw.get("formatId") in item.get("recommendedFormatIds", []):
                out["formatId"] = raw["formatId"]
    if isinstance(raw.get("voice"), bool):
        out["voice"] = raw["voice"]
    out["assumptions"] = [clean(item, 200) for item in (raw.get("assumptions") or []) if isinstance(item, str) and item.strip()][:4]
    return {"action": "automation", "automation": out}
