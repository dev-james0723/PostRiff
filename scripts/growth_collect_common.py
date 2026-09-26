"""Shared rules for the growth outcome collectors (growth_collect_bluesky.py, growth_collect_mastodon.py).

The selection rules here were fixed before collection (see CONTRACTS "Outcome validation") and apply identically
on every platform: original public posts only, 7-365 days old, long enough to judge, in a language we can identify
from the text itself (not only from a tag), and creators with at least MIN_POSTS such posts.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "rafii-outcome-research/0.2 (read-only research; github.com/dev-james0723/PostRiff)"
PAUSE = 0.4
MIN_AGE_DAYS, MAX_AGE_DAYS = 7, 365
MIN_POSTS, MAX_POSTS = 20, 60
COLUMNS = ("id", "platform", "lang", "author", "created_at", "text", "likes", "reposts", "replies", "quotes",
           "has_media", "collected_at", "source_uri")
LANGS = ("en", "zh-HK", "zh-TW", "ja", "ko", "es", "pt", "de", "fr")
LATIN_LANGS = ("en", "es", "pt", "de", "fr")

HAN = re.compile("[㐀-鿿豈-﫿]")
KANA = re.compile("[぀-ヿ]")
HANGUL = re.compile("[가-힯]")
LATIN = re.compile("[A-Za-zÀ-ɏ]")
CANTONESE = re.compile("[嘅咗喺冇啲嘢睇嚟佢哋]|唔[係好該使會]")
SIMPLIFIED_ONLY = re.compile("[这们说为时会对过发还吗个样么]")


def detect(text, tags=()):
    """Language of `text` among LANGS (or 'zh-CN'), or None when unclear. CJK languages are read from the script
    itself; Latin-script languages need a matching platform tag, since spelling alone is unreliable."""
    han, kana, hangul, latin = (len(p.findall(text)) for p in (HAN, KANA, HANGUL, LATIN))
    if kana >= 5:
        return "ja"
    if hangul >= 5:
        return "ko"
    if han >= 15:
        if SIMPLIFIED_ONLY.search(text):
            return "zh-CN"
        return "zh-HK" if CANTONESE.search(text) else "zh-TW"
    if latin >= 40 and not (han or kana or hangul):
        for tag in tags or ():
            base = (tag or "").split("-")[0].lower()
            if base in LATIN_LANGS:
                return base
    return None


def min_chars(lang):
    return 80 if lang in LATIN_LANGS else 30


def age_ok(created, now):
    return created is not None and MIN_AGE_DAYS <= (now - created) / 86400 <= MAX_AGE_DAYS


def digest(value, n=16):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:n]


def strip_html(content):
    """Mastodon status HTML -> plain text with line breaks."""
    text = re.sub(r"<br\s*/?>", "\n", content or "", flags=re.I)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def fetch(url, retries=4, pause=PAUSE):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}),
                                        timeout=25) as r:
                data = json.load(r)
            time.sleep(pause)
            return data
        except urllib.error.HTTPError as error:
            if error.code in (429, 502, 503) and attempt + 1 < retries:
                time.sleep(int(error.headers.get("Retry-After") or 2 ** (attempt + 2)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def url(base, path, params=None):
    return base.rstrip("/") + path + ("?" + urllib.parse.urlencode(params) if params else "")


def keep_creator(rows):
    """A creator's MAX_POSTS most recent eligible rows, or [] when fewer than MIN_POSTS."""
    if len(rows) < MIN_POSTS:
        return []
    return sorted(rows, key=lambda r: -float(r["created_at"]))[:MAX_POSTS]


def outside_repo(path):
    """Refuse to write inside a git checkout: the repository is public and the data is other people's posts."""
    out = os.path.abspath(os.path.expanduser(path))
    probe = os.path.dirname(out)
    while probe and probe != os.path.dirname(probe):
        if os.path.exists(os.path.join(probe, ".git")):
            print(f"error: {out} is inside a git checkout; write the dataset outside the repository", file=sys.stderr)
            return None
        probe = os.path.dirname(probe)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return out


def write_rows(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
