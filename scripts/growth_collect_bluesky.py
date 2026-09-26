"""Collect public Bluesky posts with their engagement for growth outcome validation (growth/outcomes.py).

Read-only use of Bluesky's public AppView (no login, no writes), rate limited, standard library only. Creators are
stored as a hash of their DID. Output stays outside the repository (it is public); default ~/Documents/rafii-outcomes.

    python3 scripts/growth_collect_bluesky.py run-all  --dir ~/Documents/rafii-outcomes [--langs en,zh-HK,ja]
    python3 scripts/growth_collect_bluesky.py discover --lang ja --out DIR/bluesky-creators-ja.json
    python3 scripts/growth_collect_bluesky.py collect  --lang ja --creators DIR/bluesky-creators-ja.json --out DIR/bluesky-ja.csv

Selection rules are shared with every platform (growth_collect_common.py). English creators are found by searching
profiles for topics close to Rafii's users; other languages by searching recent posts in that language (Bluesky
answers the first page of a post search without login).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import growth_collect_common as K  # noqa: E402

PUBLIC = "https://public.api.bsky.app/xrpc"
SEARCH = "https://api.bsky.app/xrpc"
EN_TOPICS = ("music teacher", "piano teacher", "music educator", "musician", "composer", "writing coach", "author",
             "teacher", "educator", "coach", "small business", "designer", "illustrator", "photographer",
             "content creator", "language teacher", "yoga teacher", "chef", "podcaster", "freelancer", "productivity",
             "marketing", "startup founder", "nonprofit", "therapist", "fitness coach", "baker", "artist")
QUERIES = {
    "zh-HK": ("嘅", "咗", "唔係", "喺度", "冇", "啲", "嘢", "睇", "嚟", "點解", "而家", "佢哋", "我哋", "今日", "返工",
              "香港", "好似", "真係", "唔好", "邊度", "食飯", "咁樣", "其實", "朋友", "屋企"),
    "zh-TW": ("今天", "覺得", "真的", "我們", "音樂", "學生", "老師", "分享", "因為", "這個", "台灣", "工作", "朋友",
              "喜歡", "時間", "問題", "應該", "還是", "東西", "開始"),
    "ja": ("今日", "ピアノ", "仕事", "思う", "本当に", "みんな", "ありがとう", "練習", "先生", "写真", "音楽", "好き",
           "時間", "友達", "作品"),
    "ko": ("오늘", "생각", "정말", "사람", "음악", "공부", "사진", "일상", "감사", "선생님", "시간", "친구", "작업"),
    "es": ("hoy", "gracias", "música", "profesor", "creo", "nuevo", "vida", "clase", "siempre", "trabajo", "libro"),
    "pt": ("hoje", "obrigado", "música", "professor", "acho", "novo", "vida", "aula", "sempre", "trabalho", "livro"),
    "de": ("heute", "danke", "Musik", "Lehrer", "glaube", "neue", "Leben", "Unterricht", "immer", "Arbeit", "Buch"),
    "fr": ("aujourd'hui", "merci", "musique", "professeur", "pense", "nouveau", "vie", "cours", "toujours", "travail", "livre"),
}
SEARCH_LANG = {"zh-HK": None, "zh-TW": "zh", "ja": "ja", "ko": "ko", "es": "es", "pt": "pt", "de": "de", "fr": "fr"}


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
    if not text or not K.age_ok(created, now) or len(text) < K.min_chars(target):
        return None
    if K.detect(text, record.get("langs") or ()) != target:
        return None
    uri, did = post.get("uri") or "", (post.get("author") or {}).get("did") or ""
    counts = [post.get(k) for k in ("likeCount", "repostCount", "replyCount", "quoteCount")]
    if not uri or not did or any(not isinstance(c, int) or c < 0 for c in counts):
        return None
    return {"id": "bsky-" + K.digest(uri, 20), "platform": "bluesky", "lang": target, "author": "bsky-" + K.digest(did),
            "created_at": f"{created:.0f}", "text": text, "likes": counts[0], "reposts": counts[1], "replies": counts[2],
            "quotes": counts[3], "has_media": "1" if post.get("embed") else "0", "collected_at": f"{now:.0f}",
            "source_uri": uri}


def discover(target, limit):
    found = {}
    if target == "en":
        for topic in EN_TOPICS:
            try:
                actors = K.fetch(K.url(PUBLIC, "/app.bsky.actor.searchActors", {"q": topic, "limit": 25})).get("actors", [])
            except urllib.error.HTTPError:
                continue
            for actor in actors:
                found.setdefault(actor["did"], {"did": actor["did"], "handle": actor.get("handle"), "source": topic})
        return list(found.values())[:limit]
    for q in QUERIES[target]:
        params = {"q": q, "limit": 100}
        if SEARCH_LANG[target]:
            params["lang"] = SEARCH_LANG[target]
        try:
            posts = K.fetch(K.url(SEARCH, "/app.bsky.feed.searchPosts", params)).get("posts", [])
        except urllib.error.HTTPError:
            continue
        for p in posts:
            record = p.get("record") or {}
            if K.detect(record.get("text", ""), record.get("langs") or ()) == target:
                did = p["author"]["did"]
                found.setdefault(did, {"did": did, "handle": p["author"].get("handle"), "source": f"search:{q}"})
    return list(found.values())[:limit]


def collect(creators, target, now=None, max_pages=8, log=sys.stderr):
    now = time.time() if now is None else now
    rows, kept = [], 0
    for creator in creators:
        eligible, cursor = [], None
        for _ in range(max_pages):
            params = {"actor": creator["did"], "limit": 100, "filter": "posts_no_replies"}
            if cursor:
                params["cursor"] = cursor
            try:
                page = K.fetch(K.url(PUBLIC, "/app.bsky.feed.getAuthorFeed", params))
            except (urllib.error.HTTPError, urllib.error.URLError):
                break
            eligible += [r for r in (row_from_feed_item(i, target, now) for i in page.get("feed", [])) if r]
            cursor = page.get("cursor")
            if not cursor or len(eligible) >= K.MAX_POSTS:
                break
        chosen = K.keep_creator(eligible)
        rows += chosen
        kept += bool(chosen)
        print(f"  {creator.get('handle')}: {len(eligible)} eligible{' - kept' if chosen else ''}", file=log, flush=True)
    return rows, kept


def main(argv=None):
    parser = argparse.ArgumentParser(prog="growth_collect_bluesky.py")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--lang", choices=K.LANGS, required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--limit", type=int, default=300)
    c = sub.add_parser("collect")
    c.add_argument("--creators", required=True)
    c.add_argument("--lang", choices=K.LANGS, required=True)
    c.add_argument("--out", required=True)
    a = sub.add_parser("run-all")
    a.add_argument("--dir", required=True)
    a.add_argument("--langs", default=",".join(K.LANGS))
    a.add_argument("--limit", type=int, default=300)
    args = parser.parse_args(argv)
    if args.command == "discover":
        out = K.outside_repo(args.out)
        if not out:
            return 2
        creators = discover(args.lang, args.limit)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(creators, handle, ensure_ascii=False, indent=1)
        print(f"{len(creators)} candidate creators -> {out}")
        return 0
    if args.command == "collect":
        out = K.outside_repo(args.out)
        if not out:
            return 2
        with open(os.path.expanduser(args.creators), encoding="utf-8") as handle:
            creators = json.load(handle)
        rows, kept = collect(creators, args.lang)
        K.write_rows(out, rows)
        print(f"{kept} creators kept, {len(rows)} posts -> {out}")
        return 0
    base = K.outside_repo(os.path.join(args.dir, "x"))
    if not base:
        return 2
    base = os.path.dirname(base)
    for lang in [l.strip() for l in args.langs.split(",") if l.strip()]:
        creators = discover(lang, args.limit)
        with open(os.path.join(base, f"bluesky-creators-{lang}.json"), "w", encoding="utf-8") as handle:
            json.dump(creators, handle, ensure_ascii=False, indent=1)
        print(f"[{lang}] {len(creators)} candidates", flush=True)
        rows, kept = collect(creators, lang)
        K.write_rows(os.path.join(base, f"bluesky-{lang}.csv"), rows)
        print(f"[{lang}] {kept} creators kept, {len(rows)} posts", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
