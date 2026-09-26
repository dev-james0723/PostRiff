"""Collect public Bluesky posts with their engagement for growth outcome validation (growth/outcomes.py).

Read-only use of Bluesky's public AppView (no login, no writes), rate limited, standard library only. Output rows
match outcomes.COLUMNS. Creators are stored as a hash of their DID; post text and counts are kept because the
evaluation needs them. Keep the output OUTSIDE the repository (the repository is public): the default folder is
~/Documents/rafii-outcomes.

    python3 scripts/growth_collect_bluesky.py discover --lang en    --out ~/Documents/rafii-outcomes/creators-en.json
    python3 scripts/growth_collect_bluesky.py discover --lang zh-HK --out ~/Documents/rafii-outcomes/creators-zh.json
    python3 scripts/growth_collect_bluesky.py collect  --creators ~/Documents/rafii-outcomes/creators-en.json \\
        --lang en --out ~/Documents/rafii-outcomes/bluesky-en.csv

Selection rules (fixed before collection, see CONTRACTS "Outcome validation"): original posts only (no reposts or
replies), at least 7 and at most 365 days old, at least 80 characters (English) or 30 (Chinese), language matching
the target; creators with at least 20 such posts; at most 60 most recent eligible posts per creator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

PUBLIC = "https://public.api.bsky.app/xrpc/"
SEARCH = "https://api.bsky.app/xrpc/"          # searchPosts answers here without login (first page only)
UA = "rafii-outcome-research/0.1 (read-only; contact via github.com/dev-james0723/PostRiff)"
PAUSE = 0.35
MIN_AGE_DAYS, MAX_AGE_DAYS = 7, 365
MIN_CHARS = {"en": 80, "zh-HK": 30}
MIN_POSTS, MAX_POSTS = 20, 60
COLUMNS = ("id", "platform", "lang", "author", "created_at", "text", "likes", "reposts", "replies", "quotes",
           "has_media", "collected_at", "source_uri")
EN_TOPICS = ("music teacher", "piano teacher", "music educator", "musician", "writing coach", "author", "teacher",
             "educator", "coach", "small business", "designer", "illustrator", "photographer", "content creator",
             "language teacher", "yoga teacher", "chef", "podcaster", "freelancer", "productivity")
ZH_QUERIES = ("嘅", "咗", "唔係", "喺度", "冇", "啲", "嘢", "睇", "嚟", "點解", "而家", "佢哋", "我哋", "今日", "返工",
              "香港", "好似", "真係", "唔好", "邊度")
CANTONESE = re.compile(r"[嘅咗喺冇啲嘢睇嚟佢哋]|唔[係好該使會]")
HAN = re.compile("[\u3400-\u9fff\uf900-\ufaff]")   # CJK ideographs (Python re has no \p{Han})
SIMPLIFIED_ONLY = re.compile(r"[这们说为时会对过发还吗个样么]")


def classify(text, target):
    """True when `text` belongs to the target language: English, or Cantonese (at least one Cantonese particle and
    no simplified-only characters)."""
    han = len(HAN.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if target == "en":
        return han == 0 and latin >= 40
    return han >= 15 and bool(CANTONESE.search(text)) and not SIMPLIFIED_ONLY.search(text)


def _ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def row_from_feed_item(item, target, now):
    """A dataset row for one getAuthorFeed item, or None when it is not eligible."""
    if not isinstance(item, dict) or item.get("reason"):          # a repost of someone else's post
        return None
    post = item.get("post") or {}
    record = post.get("record") or {}
    if record.get("reply"):
        return None
    text = (record.get("text") or "").strip()
    created = _ts(record.get("createdAt"))
    if created is None or not text:
        return None
    age_days = (now - created) / 86400
    if not MIN_AGE_DAYS <= age_days <= MAX_AGE_DAYS or len(text) < MIN_CHARS[target] or not classify(text, target):
        return None
    uri, did = post.get("uri") or "", (post.get("author") or {}).get("did") or ""
    counts = [post.get(k) for k in ("likeCount", "repostCount", "replyCount", "quoteCount")]
    if not uri or not did or any(not isinstance(c, int) or c < 0 for c in counts):
        return None
    return {"id": "bsky-" + hashlib.sha256(uri.encode()).hexdigest()[:20], "platform": "other", "lang": target,
            "author": hashlib.sha256(did.encode()).hexdigest()[:16], "created_at": f"{created:.0f}", "text": text,
            "likes": counts[0], "reposts": counts[1], "replies": counts[2], "quotes": counts[3],
            "has_media": "1" if post.get("embed") else "0", "collected_at": f"{now:.0f}", "source_uri": uri}


def _get(base, method, params, retries=4):
    url = base + method + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25) as r:
                data = json.load(r)
            time.sleep(PAUSE)
            return data
        except urllib.error.HTTPError as error:
            if error.code in (429, 502, 503) and attempt + 1 < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt + 1 < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def discover(target, limit):
    """Candidate creators as [{did, handle, source}] — English by topic search over profiles, Cantonese from the first
    page of post searches for common Cantonese words. Nothing is kept about them but the DID and handle."""
    found = {}
    if target == "en":
        for topic in EN_TOPICS:
            for actor in _get(PUBLIC, "app.bsky.actor.searchActors", {"q": topic, "limit": 25}).get("actors", []):
                found.setdefault(actor["did"], {"did": actor["did"], "handle": actor.get("handle"), "source": topic})
    else:
        counts = {}
        for q in ZH_QUERIES:
            try:
                posts = _get(SEARCH, "app.bsky.feed.searchPosts", {"q": q, "limit": 100}).get("posts", [])
            except urllib.error.HTTPError:
                continue
            for p in posts:
                if classify((p.get("record") or {}).get("text", ""), "zh-HK"):
                    did = p["author"]["did"]
                    counts[did] = counts.get(did, 0) + 1
                    found.setdefault(did, {"did": did, "handle": p["author"].get("handle"), "source": "cantonese-search"})
        found = {d: v for d, v in found.items() if counts.get(d, 0) >= 1}
    return list(found.values())[:limit]


def collect(creators, target, now=None, max_pages=8):
    """Rows for creators with at least MIN_POSTS eligible posts (their MAX_POSTS most recent)."""
    now = time.time() if now is None else now
    rows, kept = [], 0
    for creator in creators:
        eligible, cursor = [], None
        for _ in range(max_pages):
            params = {"actor": creator["did"], "limit": 100, "filter": "posts_no_replies"}
            if cursor:
                params["cursor"] = cursor
            try:
                page = _get(PUBLIC, "app.bsky.feed.getAuthorFeed", params)
            except urllib.error.HTTPError:
                break
            for item in page.get("feed", []):
                row = row_from_feed_item(item, target, now)
                if row:
                    eligible.append(row)
            cursor = page.get("cursor")
            if not cursor or len(eligible) >= MAX_POSTS:
                break
        if len(eligible) >= MIN_POSTS:
            eligible.sort(key=lambda r: -float(r["created_at"]))
            rows += eligible[:MAX_POSTS]
            kept += 1
        print(f"  {creator.get('handle')}: {len(eligible)} eligible{' - kept' if len(eligible) >= MIN_POSTS else ''}", file=sys.stderr)
    return rows, kept


def main(argv=None):
    parser = argparse.ArgumentParser(prog="growth_collect_bluesky.py")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--lang", choices=("en", "zh-HK"), required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--limit", type=int, default=300)
    c = sub.add_parser("collect")
    c.add_argument("--creators", required=True)
    c.add_argument("--lang", choices=("en", "zh-HK"), required=True)
    c.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = os.path.abspath(os.path.expanduser(args.out))
    if os.path.exists(os.path.join(os.getcwd(), ".git")) and out.startswith(os.getcwd() + os.sep):
        print("error: write the dataset outside the repository (it is public)", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if args.command == "discover":
        creators = discover(args.lang, args.limit)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(creators, handle, ensure_ascii=False, indent=1)
        print(f"{len(creators)} candidate creators -> {out}")
        return 0
    with open(os.path.expanduser(args.creators), encoding="utf-8") as handle:
        creators = json.load(handle)
    rows, kept = collect(creators, args.lang)
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{kept} creators kept, {len(rows)} posts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
