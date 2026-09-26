"""Tools that make Rafii useful from live voice (Rafii live agent, Contract 6): the weather and the writing skills.

`weather_now` answers "what's the weather in …" from Open-Meteo's public geocoding and forecast APIs (no key, no cost).
Only the place name leaves Rafii — no workspace data, no account — so it is not web research and needs no research
consent. The transport is injectable (tests never reach the network) and bounded like the product's other provider
calls: an allowlisted HTTPS endpoint, no redirects, a timeout and a size cap. Answers are cached for ten minutes per
place, in this process only.

`skills_list` lists the product's own writing skills (`postriff-*`) from the capability registry. A person's private
skills (`james-au-*`, or anything marked private) are never listed, and the writing pipeline never binds them on a
hosted run either. Draft results name the skills their writing run bound (`bound_skills`), so answers can say which
platform skill shaped a draft.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from . import contracts
from .context import RafiiRunContext
from .tool_adapter import register

log = logging.getLogger("postriff.agent_runtime")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ALLOWED_ENDPOINTS = (GEOCODING_URL, FORECAST_URL)
USER_AGENT = "Rafii weather/1.0"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 256 * 1024
CACHE_SECONDS = 600
CACHE_ENTRIES = 256
MAX_PLACE = 120
SOURCE = "Open-Meteo"
SOURCE_URL = "https://open-meteo.com"
_CJK = re.compile(r"[㐀-鿿]")

# WMO weather interpretation codes (Open-Meteo `weather_code`) in plain words: (English, Traditional Chinese).
CONDITIONS = {
    0: ("clear sky", "晴朗"), 1: ("mainly clear", "大致晴朗"), 2: ("partly cloudy", "部分時間有雲"), 3: ("overcast", "密雲"),
    45: ("fog", "有霧"), 48: ("freezing fog", "凍霧"),
    51: ("light drizzle", "微雨"), 53: ("drizzle", "毛毛雨"), 55: ("heavy drizzle", "較大的毛毛雨"),
    56: ("light freezing drizzle", "輕微凍毛毛雨"), 57: ("freezing drizzle", "凍毛毛雨"),
    61: ("light rain", "小雨"), 63: ("rain", "中雨"), 65: ("heavy rain", "大雨"),
    66: ("light freezing rain", "輕微凍雨"), 67: ("freezing rain", "凍雨"),
    71: ("light snow", "小雪"), 73: ("snow", "中雪"), 75: ("heavy snow", "大雪"), 77: ("snow grains", "米雪"),
    80: ("light showers", "小陣雨"), 81: ("showers", "陣雨"), 82: ("violent showers", "大驟雨"),
    85: ("light snow showers", "小陣雪"), 86: ("heavy snow showers", "大陣雪"),
    95: ("thunderstorms", "雷暴"), 96: ("thunderstorms with light hail", "雷暴伴有小冰雹"), 99: ("thunderstorms with heavy hail", "雷暴伴有大冰雹"),
}


def conditions(code, language: str = "en") -> str | None:
    """A weather code in plain words (None when the code is unknown)."""
    words = CONDITIONS.get(code) if isinstance(code, int) and not isinstance(code, bool) else None
    if words is None:
        return None
    return words[1] if language.startswith("zh") else words[0]


class WeatherUnavailable(Exception):
    """The weather service couldn't be reached or gave no usable answer. The reason is for logs, never for the person."""


class PlaceNotFound(Exception):
    """The geocoder knows no place by that name."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise WeatherUnavailable("redirect refused")


def https_get_json(url: str, params: dict, timeout: float) -> dict:
    """GET an allowlisted Open-Meteo endpoint: HTTPS only, no redirects, a timeout and a size cap; a JSON object back."""
    if url not in ALLOWED_ENDPOINTS:
        raise WeatherUnavailable("endpoint not allowed")
    request = Request(url + "?" + urlencode(params), headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET")
    try:
        with build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(request, timeout=timeout) as response:
            raw, status = response.read(MAX_RESPONSE_BYTES + 1), response.status
    except HTTPError as error:
        raise WeatherUnavailable(f"http {error.code}") from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise WeatherUnavailable(type(error).__name__) from error
    if status != 200:
        raise WeatherUnavailable(f"http {status}")
    if len(raw) > MAX_RESPONSE_BYTES:
        raise WeatherUnavailable("response too large")
    try:
        body = json.loads(raw)
    except ValueError as error:
        raise WeatherUnavailable("unreadable response") from error
    if not isinstance(body, dict):
        raise WeatherUnavailable("unreadable response")
    return body


def _number(value, digits: int = 1):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:  # NaN
        return None
    return round(float(value), digits) if digits else int(round(float(value)))


def _first(series):
    return series[0] if isinstance(series, list) and series else None


def _observed(local_time, offset_seconds) -> str | None:
    """Open-Meteo's local observation time with the place's UTC offset (ISO 8601)."""
    if not isinstance(local_time, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", local_time):
        return None
    if isinstance(offset_seconds, bool) or not isinstance(offset_seconds, int):
        return local_time
    sign = "+" if offset_seconds >= 0 else "-"
    hours, minutes = divmod(abs(offset_seconds) // 60, 60)
    return f"{local_time}{sign}{hours:02d}:{minutes:02d}"


def clean_place(value) -> str:
    """The place as the person named it: plain text, one line, bounded (it is the only thing sent)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split()).strip(" .,;:!?。，！？")[:MAX_PLACE]


class Weather:
    """Current conditions and today's forecast for a named place, cached for ten minutes per place and language."""

    def __init__(self, transport=None, clock=time.monotonic):
        self.transport = transport or https_get_json
        self.clock = clock
        self._cache: dict = {}
        self._lock = threading.Lock()

    def _cached(self, key):
        with self._lock:
            hit = self._cache.get(key)
            if hit and self.clock() - hit[0] < CACHE_SECONDS:
                return hit[1]
            self._cache.pop(key, None)
        return None

    def _remember(self, key, value) -> None:
        with self._lock:
            if len(self._cache) >= CACHE_ENTRIES:
                self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]))
            self._cache[key] = (self.clock(), value)

    def _geocode(self, place: str, language: str, timeout: float) -> dict:
        # "Tokyo, Japan": the geocoder searches names only, so the part after the comma picks among the matches.
        name, _, hint = place.partition(",")
        name, hint = name.strip(), hint.strip().casefold()
        found = self.transport(GEOCODING_URL, {"name": name or place, "count": 10 if hint else 1, "language": language, "format": "json"}, timeout)
        results = [r for r in (found.get("results") or []) if isinstance(r, dict) and _number(r.get("latitude"), 4) is not None
                   and _number(r.get("longitude"), 4) is not None and isinstance(r.get("name"), str)]
        if hint:
            preferred = [r for r in results if any(hint in str(r.get(k) or "").casefold() for k in ("country", "country_code", "admin1", "admin2"))]
            results = preferred or results
        if not results:
            raise PlaceNotFound(place)
        return results[0]

    def now(self, place: str, *, language: str = "en", timeout: float = TIMEOUT_SECONDS) -> dict:
        """{place, region, country, countryCode, timezone, current, today, units, source, sourceUrl, observedAt}.
        Raises PlaceNotFound or WeatherUnavailable."""
        place = clean_place(place)
        if not place:
            raise PlaceNotFound(place)
        language = "zh" if language.startswith("zh") else "en"
        key = (place.casefold(), language)
        cached = self._cached(key)
        if cached is not None:
            return cached
        spot = self._geocode(place, language, timeout)
        forecast = self.transport(FORECAST_URL, {
            "latitude": _number(spot["latitude"], 4), "longitude": _number(spot["longitude"], 4),
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone": "auto", "forecast_days": 1}, timeout)
        current, daily = forecast.get("current"), forecast.get("daily")
        if not isinstance(current, dict) or _number(current.get("temperature_2m")) is None:
            raise WeatherUnavailable("no current conditions")
        daily = daily if isinstance(daily, dict) else {}
        code = current.get("weather_code") if isinstance(current.get("weather_code"), int) else None
        result = {
            "place": spot["name"][:80], "region": (spot.get("admin1") or None) if isinstance(spot.get("admin1"), str) else None,
            "country": spot.get("country") if isinstance(spot.get("country"), str) else None,
            "countryCode": spot.get("country_code") if isinstance(spot.get("country_code"), str) else None,
            "timezone": forecast.get("timezone") if isinstance(forecast.get("timezone"), str) else None,
            "current": {"temperatureC": _number(current.get("temperature_2m")), "feelsLikeC": _number(current.get("apparent_temperature")),
                        "conditions": conditions(code, language) or ("unknown" if language == "en" else "未知"), "weatherCode": code,
                        "windKmh": _number(current.get("wind_speed_10m")), "humidityPercent": _number(current.get("relative_humidity_2m"), 0),
                        "time": current.get("time") if isinstance(current.get("time"), str) else None},
            "today": {"date": _first(daily.get("time")) if isinstance(_first(daily.get("time")), str) else None,
                      "highC": _number(_first(daily.get("temperature_2m_max"))), "lowC": _number(_first(daily.get("temperature_2m_min"))),
                      "rainChancePercent": _number(_first(daily.get("precipitation_probability_max")), 0)},
            "units": {"temperature": "°C", "wind": "km/h", "humidity": "%", "rainChance": "%"},
            "source": SOURCE, "sourceUrl": SOURCE_URL,
            "observedAt": _observed(current.get("time"), forecast.get("utc_offset_seconds")),
        }
        self._remember(key, result)
        return result


_DEFAULT: Weather | None = None


def default_weather() -> Weather:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Weather()
    return _DEFAULT


PLACE_QUESTION = "Which city or place should I check the weather for?"
UNAVAILABLE = "The weather service didn't answer just now, so I couldn't check the weather. Please try again in a moment."


def lookup(ctx: RafiiRunContext, place, *, language: str | None = None) -> dict:
    """The weather as a tool result (also used by the /weather command): a plain answer or a plain refusal, never an
    exception text, a URL or a provider detail."""
    place = clean_place(place)
    if not place:
        return {"ok": False, "needsUser": True, "code": "place_needed", "question": PLACE_QUESTION}
    weather = getattr(ctx.service, "weather", None) or default_weather()
    language = language or ("zh" if _CJK.search(place) else "en")
    try:
        found = weather.now(place, language=language, timeout=ctx.provider_timeout(TIMEOUT_SECONDS))
    except PlaceNotFound:
        return {"ok": False, "code": "place_not_found", "error": f"I couldn't find a place called “{place}”. Try the city's name, or add its country."}
    except WeatherUnavailable as error:
        log.warning(json.dumps({"event": "weather.unavailable", "reason": str(error)[:60], "traceId": ctx.trace_id}))
        return {"ok": False, "code": "weather_unavailable", "error": UNAVAILABLE}
    ctx.ledger.facts.append({"text": f"Weather for {found['place']}: {SOURCE}, observed {found['observedAt'] or 'just now'}", "kind": "external", "rule": "weather_now"})
    return {"ok": True, "verified": True, "source": SOURCE, "observedAt": found.get("observedAt"), "data": found}


@register(contracts.ToolSpec("weather_now", contracts.READ, "read", "Current weather and today's forecast for a named place (a city or town, optionally "
                             "with its country, e.g. 'Hong Kong' or 'Paris, France'), from Open-Meteo: temperature and feels-like in °C, conditions in words, "
                             "wind, humidity, today's high and low and chance of rain, with the observation time. Only the place name leaves Rafii (no "
                             "workspace data, no account), so it works even when web research is off. Without a place it asks which one."),
          {"place": {"type": "string", "maxLength": MAX_PLACE}},
          "Checked the weather")
def weather_now(ctx: RafiiRunContext, args: dict) -> dict:
    return lookup(ctx, args.get("place"))


# --- writing skills -----------------------------------------------------------------------------------------------------------
SKILL_PREFIX = "postriff-"
_SKILL_KINDS = ("knowledge", "workflow", "tool")   # policies and evaluators are code, never writing guidance
_USE = ("writing", "images", "research")


def _use(agents) -> str:
    agents = set(agents or [])
    if "creative" in agents:
        return "images"
    if "writer" in agents:
        return "writing"
    return "research" if "research" in agents else "writing"


def skill_title(skill_id: str, platforms=()) -> str:
    """A short human title: "Instagram channel skill", "Content craft"."""
    platforms = [p for p in platforms or [] if isinstance(p, str) and p != "*"]
    if skill_id.startswith(SKILL_PREFIX + "channel-") and len(platforms) == 1:
        return f"{platforms[0]} channel skill"
    return skill_id.removeprefix(SKILL_PREFIX).replace("-", " ").capitalize()


def _registry():
    from .. import skill_registry
    return skill_registry.default_registry()


def _product(entry) -> bool:
    sid = entry.get("id") if isinstance(entry, dict) else None
    return (isinstance(sid, str) and sid.startswith(SKILL_PREFIX) and not entry.get("private") and entry.get("deprecation") == "active"
            and entry.get("kind") in _SKILL_KINDS and any(s.get("type") == "skill" for s in entry.get("hashSources") or [] if isinstance(s, dict)))


def product_skills(platform: str | None = None) -> list[dict]:
    """Every active product skill (never a private one), optionally only those that apply to one platform."""
    wanted = (platform or "").strip().casefold()
    out = []
    for entry in _registry().entries:
        if not _product(entry):
            continue
        platforms = [p for p in entry.get("platforms") or [] if isinstance(p, str)]
        general = not platforms or "*" in platforms
        if wanted and not general and not any(p.casefold() == wanted for p in platforms):
            continue
        description = entry.get("description") if isinstance(entry.get("description"), str) else ""
        if entry["id"].startswith(SKILL_PREFIX + "channel-") and not general:
            description = f"How posts for {', '.join(platforms)} are shaped: formats, limits and the platform's conventions."
        out.append({"id": entry["id"], "title": skill_title(entry["id"], platforms), "description": contracts.trim(description, 220),
                    "platforms": ["all"] if general else platforms, "use": _use(entry.get("agents"))})
    return sorted(out, key=lambda s: (_USE.index(s["use"]), s["platforms"] != ["all"], s["title"]))


def bound_skills(bindings) -> list[dict]:
    """The product skills a writing run bound, as [{id, title}] (a private skill is never named)."""
    registry = None
    out = []
    for binding in bindings or []:
        sid = binding.get("id") if isinstance(binding, dict) else binding
        if not isinstance(sid, str) or not sid.startswith(SKILL_PREFIX) or any(s["id"] == sid for s in out):
            continue
        try:
            registry = registry or _registry()
            entry = registry.get(sid) or {}
        except Exception:  # noqa: BLE001 — naming a skill never breaks a draft
            entry = {}
        if entry.get("private"):
            continue
        out.append({"id": sid, "title": skill_title(sid, entry.get("platforms") or [])})
    return out


@register(contracts.ToolSpec("skills_list", contracts.READ, "read", "Rafii's own writing skills (product skills only): id, title, what each is for, the "
                             "platforms it covers and its use (writing, images, research). The writing pipeline binds them by platform and format on every "
                             "draft, and draft results name the skills a draft was written with. Optional platform filter (e.g. 'Instagram')."),
          {"platform": {"type": "string", "maxLength": 40}},
          "Listed Rafii's writing skills")
def skills_list(ctx: RafiiRunContext, args: dict) -> dict:
    _ = ctx
    skills = product_skills(args.get("platform"))
    return {"ok": True, "verified": True, "source": "Rafii skill registry", "data": {"skills": skills, "count": len(skills)}}
