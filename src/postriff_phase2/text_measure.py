"""How long a post is, the way each platform counts (plan §7.4).

Python's `len` counts code points; browsers count UTF-16 units; X weights CJK characters as two.
Every draft-length check goes through `measure` so the server and the web app agree with each
other and with the platform. Counts only ever produce a reminder while drafting.
"""
from __future__ import annotations

from .contracts import LIMITS

# twitter-text v3: code points in these ranges weigh 1, everything else (CJK, emoji…) weighs 2.
_X_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
UNITS = {"X": "x-weighted"}


def measure(platform, text):
    """{"used", "limit", "unit"} for a draft on a platform; `limit` is None when PostRiff has no versioned limit for it."""
    text = text if isinstance(text, str) else ""
    unit = UNITS.get(platform, "codepoint")
    if unit == "x-weighted":
        used = sum(1 if any(low <= ord(ch) <= high for low, high in _X_LIGHT) else 2 for ch in text)
    else:
        used = len(text)
    limit = (LIMITS.get(platform) or {}).get("characters")
    return {"used": used, "limit": limit, "unit": unit}


def over_by(platform, text):
    counted = measure(platform, text)
    return max(0, counted["used"] - counted["limit"]) if counted["limit"] else 0
