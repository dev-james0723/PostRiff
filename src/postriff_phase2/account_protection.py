"""Rafii Account Protection v2, phase P0: durable sign-in events, honest browser labels and security timestamps.

RAFII_ACCOUNT_PROTECTION_V2_MODE is `off` (the default: the legacy behaviour, unchanged) or `observe`: every first
sighting of a session writes a `session.observed` account event in the same transaction as the session row, before
any alert preference is read, and the sign-in paths that used to record a session silently (bootstrap, invitation
acceptance) alert like /api/me does. `observe` adds no friction and blocks nothing; `enforce` belongs to P1 and is
treated as `off` here, so a premature value can never switch on an enforcement this phase does not have.

A label is a coarse browser family and OS family from the User-Agent, never a device model and never proof of
anything: the header is supplied by the client.
"""
from __future__ import annotations

from datetime import datetime, timezone
import zoneinfo

MODES = ("off", "observe")
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
    return mode(values) == "observe"


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


def security_time(epoch, time_zone=""):
    """When a security event happened, for a person to check against their own memory: the date and time in their
    IANA zone with the abbreviation that zone actually used on that date (PDT in October, not PST), then UTC.
    Without a valid zone, UTC alone."""
    try:
        instant = datetime.fromtimestamp(float(epoch), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return "an unknown time"
    utc = f"{instant.day} {instant:%B %Y}, {instant:%H:%M} UTC"
    zone = _zone(time_zone)
    if zone is None:
        return utc
    local = instant.astimezone(zone)
    # The UTC part repeats the date only when it differs from the local one.
    tail = f"{instant:%H:%M} UTC" if local.date() == instant.date() else utc
    return f"{local.day} {local:%B %Y}, {local:%H:%M} {local.tzname()} ({time_zone}) · {tail}"
