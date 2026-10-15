"""Rafii Account Protection v2, phase P0: durable sign-in events, honest browser labels and security timestamps.

RAFII_ACCOUNT_PROTECTION_V2_MODE is `off` (the default: the legacy behaviour, unchanged) or `observe`: every first
sighting of a session writes a `session.observed` account event in the same transaction as the session row, before
any alert preference is read, and the sign-in paths that used to record a session silently (bootstrap, invitation
acceptance) alert like /api/me does. `observe` adds no friction and blocks nothing. `enforce` (P1) observes exactly
like `observe` and, in addition, requires a fresh independent second factor before a sensitive capability is used from
a risky session (security_gate, security_policy). No environment sets `enforce`.

A label is a coarse browser family and OS family from the User-Agent, never a device model and never proof of
anything: the header is supplied by the client.

Sign-in details (RAP-016, RAP-076). `sign_in_method` names how a session signed in from the `amr` claim Supabase signed
into its token; a session without one is "unknown", never a guessed method or factor. RAFII_SIGN_IN_DETAILS (default
off) decides what a first sighting also records on its `session.observed` event: `method` the sign-in method only;
`country`, `region` or `city` the method plus an approximate location at that granularity. The location comes only
from the geo headers Vercel's edge sets on the request (x-vercel-ip-country, -country-region, -city), read only when
running on Vercel (VERCEL=1), where the platform sets them itself. No IP address is stored and no third-party geo
service is called; the location never takes part in a security decision (RAP-042). Off: nothing new is recorded.
"""
from __future__ import annotations

import contextvars
from datetime import datetime, timezone
import re
from urllib.parse import unquote
import zoneinfo

MODES = ("off", "observe", "enforce")
UNRECOGNIZED = "Unrecognized browser"

# First match wins: Edge, Opera and Samsung Internet carry "Chrome/", Chrome on iOS and every Chromium carry "Safari/".
_BROWSERS = (("EdgiOS/", "Edge"), ("EdgA/", "Edge"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser/", "Samsung Internet"),
             ("FxiOS/", "Firefox"), ("Firefox/", "Firefox"), ("CriOS/", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
# iPhone and iPad agents also say "Mac OS X", Android agents also say "Linux".
_SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("CrOS", "ChromeOS"),
            ("Macintosh", "Mac"), ("Mac OS X", "Mac"), ("Linux", "Linux"))


def mode(values=None):
    from .coworker import flags
    value = str(flags._source(values).get("RAFII_ACCOUNT_PROTECTION_V2_MODE", "")).strip().lower()
    return value if value in MODES else "off"


def observing(values=None):
    """Observation runs in `observe` and in `enforce`: enforcement decides from what observation recorded."""
    return mode(values) in ("observe", "enforce")


def enforcing(values=None):
    return mode(values) == "enforce"


def browser_label(user_agent):
    """`Safari on iPhone`, `Chrome on Windows`, `Firefox`; `Unrecognized browser` when nothing matches. At most 40
    characters (pr_sessions.client_label) and built only from the fixed names above, so no header text is echoed."""
    agent = user_agent[:512] if isinstance(user_agent, str) else ""
    browser = next((name for token, name in _BROWSERS if token in agent), None)
    system = next((name for token, name in _SYSTEMS if token in agent), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or (f"Browser on {system}" if system else UNRECOGNIZED)


def _zone(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 64:
        return None
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None


def _day(moment, numeric):
    return f"{moment:%Y-%m-%d}" if numeric else f"{moment.day} {moment:%B %Y},"


def security_time(epoch, time_zone="", numeric=False):
    """When a security event happened, for a person to check against their own memory: the date and time in their
    IANA zone with the abbreviation that zone actually used on that date (PDT in October, not PST), then UTC.
    Without a valid zone, UTC alone. `numeric` writes the date as 2026-10-14 for copy in any language."""
    try:
        instant = datetime.fromtimestamp(float(epoch), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return "an unknown time"
    utc = f"{_day(instant, numeric)} {instant:%H:%M} UTC"
    zone = _zone(time_zone)
    if zone is None:
        return utc
    local = instant.astimezone(zone)
    # The UTC part repeats the date only when it differs from the local one.
    tail = f"{instant:%H:%M} UTC" if local.date() == instant.date() else utc
    return f"{_day(local, numeric)} {local:%H:%M} {local.tzname()} ({time_zone}) · {tail}"


# --- sign-in details (RAP-016, RAP-076) ---------------------------------------------------------------------------

# Supabase `amr` methods -> the codes the API returns. A second factor is reported separately, never as the sign-in.
_PRIMARY = {"password": "password", "otp": "email_code", "magiclink": "email_link", "email/signup": "email_link", "oauth": "oauth",
            "passkey": "passkey", "sso/saml": "sso", "anonymous": "anonymous"}
_SECOND = {"totp": "authenticator_app", "mfa/webauthn": "security_key", "mfa/phone": "phone_code"}
METHOD_CODES = frozenset(_PRIMARY.values()) | {"unknown"}
DETAIL_LEVELS = ("method", "country", "region", "city")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_REGION = re.compile(r"^[A-Z0-9]{1,3}$")
_CITY = re.compile(r"^[^\x00-\x1f<>&\"'`;]{1,40}$")


def sign_in_method(amr):
    """{"method": code, "secondFactor": code or None} from a verified `amr` list (newest entry of each kind). A token
    without a recognisable entry is {"method": "unknown", "secondFactor": None}: nothing is inferred from aal or iat."""
    entries = [m for m in amr if isinstance(m, dict) and isinstance(m.get("method"), str)] if isinstance(amr, list) else []
    def newest(table):
        found = [(m.get("timestamp") if type(m.get("timestamp")) in (int, float) else 0, table[m["method"]]) for m in entries if m["method"] in table]
        return max(found)[1] if found else None
    return {"method": newest(_PRIMARY) or "unknown", "secondFactor": newest(_SECOND)}


def detail_level(values=None):
    """What a first sighting records beyond the event itself: None (the default), or one of DETAIL_LEVELS."""
    from .coworker import flags
    value = str(flags._source(values).get("RAFII_SIGN_IN_DETAILS", "")).strip().lower()
    return value if value in DETAIL_LEVELS else None


def coarse_location(environ, level, values=None):
    """{"country", "region"?, "city"?} at `level` from Vercel's edge geo headers, or None (not on Vercel, the level is
    `method` or off, or no valid country). Values are validated shapes only; any other header text is dropped."""
    from .coworker import flags
    if level not in ("country", "region", "city") or str(flags._source(values).get("VERCEL", "")).strip() != "1" or not isinstance(environ, dict):
        return None
    country = str(environ.get("HTTP_X_VERCEL_IP_COUNTRY", "")).strip().upper()
    if not _COUNTRY.match(country) or country in ("XX", "T1"):
        return None
    found = {"country": country}
    region = str(environ.get("HTTP_X_VERCEL_IP_COUNTRY_REGION", "")).strip().upper()
    if level in ("region", "city") and _REGION.match(region):
        found["region"] = region
    city = unquote(str(environ.get("HTTP_X_VERCEL_IP_CITY", ""))[:120]).strip()
    if level == "city" and _CITY.match(city):
        found["city"] = city
    return found


def location_text(location):
    """"Kowloon, KKC, HK": city, region code and country code as recorded (no place names are looked up); None when
    nothing usable was recorded."""
    if not isinstance(location, dict) or not _COUNTRY.match(str(location.get("country", ""))):
        return None
    parts = [str(location[key]) for key in ("city", "region") if isinstance(location.get(key), str) and location[key]]
    return ", ".join(parts + [location["country"]])


# The sign-in details of the HTTP request being served (HostedApplication binds it): {"location": ...} or None.
_REQUEST = contextvars.ContextVar("rafii_sign_in_request", default=None)


def bind_request(environ):
    level = detail_level()
    return _REQUEST.set({"location": coarse_location(environ, level)} if level else None)


def reset_request(binding):
    _REQUEST.reset(binding)


def note_verified_amr(amr):
    """The token verifier hands the request the `amr` of the token it has just verified (only while details are on)."""
    request = _REQUEST.get()
    if request is not None:
        request["amr"] = amr if isinstance(amr, list) else []


def first_sighting_details():
    """The extra `session.observed` fields for a first sighting under RAFII_SIGN_IN_DETAILS; {} when it is off."""
    level = detail_level()
    if level is None:
        return {}
    request = _REQUEST.get() or {}
    details = {"method": sign_in_method(request.get("amr"))["method"]}
    if level != "method":
        # Recorded even when unavailable (None), so a notice can say so instead of guessing.
        details["location"] = request.get("location")
    return details
