"""The guide manifest: every step-by-step guide Rafii may start on the person's screen (Rafii live agent, Contract 5).

`guide_manifest.json` is the one allowlist (id, routeId, title, summary, keywords). A guide card is built only from its
entries, and every guide opens a page from the route manifest. The steps themselves live on the web only
(`web/src/features/rafii-guide/guides.ts`); the web keeps a byte-identical twin of this file at
`web/src/lib/site-agent/guide-manifest.json`, and `tests/test_site_agent.py` fails when they drift or when a guide
names a route the route manifest doesn't know.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent / "guide_manifest.json"
_CJK = re.compile(r"[㐀-鿿]")


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def entries() -> list[dict]:
    return load()["guides"]


def ids() -> list[str]:
    return [guide["id"] for guide in entries()]


def find(guide_id) -> dict | None:
    if not isinstance(guide_id, str):
        return None
    return next((guide for guide in entries() if guide["id"] == guide_id), None)


@lru_cache(maxsize=1)
def _patterns() -> dict:
    """Per guide, one compiled pattern per keyword: whole words for Latin keywords (ASCII boundaries, so code-switched
    "點樣connect" still matches), plain substrings for CJK ones."""
    compiled = {}
    for guide in entries():
        compiled[guide["id"]] = [(keyword, re.compile(re.escape(keyword) if _CJK.search(keyword) else rf"(?<![A-Za-z0-9_-]){re.escape(keyword)}(?![A-Za-z0-9_-])", re.I))
                                 for keyword in guide.get("keywords") or [] if isinstance(keyword, str) and keyword.strip()]
    return compiled


def score(guide: dict, text: str) -> float:
    """How well `text` matches a guide: each matched keyword counts; a guide's first keywords (its action) count more,
    and so does a phrase (several words, or three or more CJK characters)."""
    total = 0.0
    for index, (keyword, pattern) in enumerate(_patterns().get(guide["id"], [])):
        if pattern.search(text):
            total += 1 + 1 / (index + 1) + (1 if " " in keyword.strip() or (_CJK.search(keyword) and len(keyword) >= 3) else 0)
    return total


def matches(text) -> list[dict]:
    """Guides whose keywords appear in `text`, best first (ties keep the manifest's order)."""
    if not isinstance(text, str) or not text.strip():
        return []
    scored = [(score(guide, text), index, guide) for index, guide in enumerate(entries())]
    return [guide for points, _index, guide in sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))]


def match(text) -> dict | None:
    """The best guide for `text` by keywords, or None."""
    found = matches(text)
    return found[0] if found else None


def describe(guide_id: str) -> dict | None:
    guide = find(guide_id)
    if guide is None:
        return None
    return {key: guide.get(key) for key in ("id", "routeId", "title", "summary")}


def listing() -> list[dict]:
    return [{"id": g["id"], "routeId": g["routeId"], "title": g["title"]} for g in entries()]
