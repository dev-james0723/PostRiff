"""Collect public Mastodon posts with their engagement for growth outcome validation (growth/outcomes.py).

Read-only use of each server's public REST API (no login), rate limited, standard library only. Only accounts that
chose to appear in their server's profile directory are considered, and an account that opted out of indexing
(`noindex`, or `indexable` false), bots and group accounts are skipped. Counts are read from the account's home
server, where they are complete. Creators are stored as a hash of their account URL. Output stays outside the
repository; default ~/Documents/rafii-outcomes.

    python3 scripts/growth_collect_mastodon.py run-all --dir ~/Documents/rafii-outcomes [--servers mastodon.social,mstdn.jp]

Posts are kept only in the language the text itself shows (growth_collect_common.detect); a server's language is
only where the search starts.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import growth_collect_common as K  # noqa: E402

SERVERS = ("mastodon.social", "mas.to", "mastodon.online", "mstdn.social", "hachyderm.io", "infosec.exchange",
           "chaos.social", "troet.cafe", "mastodon.art", "mstdn.jp", "fedibird.com", "masto.es", "mastodon.uno",
           "piaille.fr", "mastodon.world", "social.vivaldi.net")
DIRECTORY_PAGES = 4          # 80 accounts per page


def _ts(value):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def eligible_account(account):
    if not isinstance(account, dict) or account.get("bot") or account.get("group"):
        return False
    if account.get("noindex") is True or account.get("indexable") is False or account.get("discoverable") is False:
        return False
    return int(account.get("statuses_count") or 0) >= K.MIN_POSTS


def row_from_status(status, server, now):
    """A dataset row for one status, in whatever supported language its text shows, or None when not eligible."""
    if not isinstance(status, dict) or status.get("reblog") or status.get("in_reply_to_id"):
        return None
    if status.get("visibility") != "public" or status.get("sensitive") or status.get("spoiler_text"):
        return None
    text = K.strip_html(status.get("content"))
    created = _ts(status.get("created_at"))
    lang = K.detect(text, [status.get("language") or ""])
    if not text or lang not in K.LANGS or not K.age_ok(created, now) or len(text) < K.min_chars(lang):
        return None
    counts = [status.get(k) for k in ("favourites_count", "reblogs_count", "replies_count")]
    uri, account_url = status.get("uri") or "", ((status.get("account") or {}).get("url") or "")
    if not uri or not account_url or any(not isinstance(c, int) or c < 0 for c in counts):
        return None
    return {"id": "masto-" + K.digest(uri, 20), "platform": "mastodon", "lang": lang, "author": "masto-" + K.digest(account_url),
            "created_at": f"{created:.0f}", "text": text, "likes": counts[0], "reposts": counts[1], "replies": counts[2],
            "quotes": 0, "has_media": "1" if status.get("media_attachments") else "0", "collected_at": f"{now:.0f}",
            "source_uri": uri}


def collect_server(server, now, log=sys.stderr, max_pages=5):
    base = f"https://{server}"
    rows_by_lang, kept = {}, 0
    accounts = []
    for page in range(DIRECTORY_PAGES):
        try:
            batch = K.fetch(K.url(base, "/api/v1/directory", {"local": "true", "order": "active", "limit": 80, "offset": page * 80}))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            print(f"[{server}] directory unavailable ({type(error).__name__})", file=log, flush=True)
            break
        if not batch:
            break
        accounts += [a for a in batch if eligible_account(a)]
    for account in accounts:
        rows, max_id = [], None
        for _ in range(max_pages):
            params = {"exclude_replies": "true", "exclude_reblogs": "true", "limit": 40}
            if max_id:
                params["max_id"] = max_id
            try:
                statuses = K.fetch(K.url(base, f"/api/v1/accounts/{account['id']}/statuses", params))
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                break
            if not statuses:
                break
            rows += [r for r in (row_from_status(s, server, now) for s in statuses) if r]
            max_id = statuses[-1].get("id")
            oldest = _ts(statuses[-1].get("created_at"))
            if len(rows) >= K.MAX_POSTS * 2 or (oldest and (now - oldest) / 86400 > K.MAX_AGE_DAYS):
                break
        by_lang = {}
        for r in rows:
            by_lang.setdefault(r["lang"], []).append(r)
        chosen_any = False
        for lang, lang_rows in by_lang.items():          # a creator counts once per language they write enough in
            chosen = K.keep_creator(lang_rows)
            if chosen:
                rows_by_lang.setdefault(lang, []).extend(chosen)
                chosen_any = True
        kept += chosen_any
        print(f"  [{server}] {account.get('acct')}: {len(rows)} eligible{' - kept' if chosen_any else ''}", file=log, flush=True)
    return rows_by_lang, kept


def main(argv=None):
    parser = argparse.ArgumentParser(prog="growth_collect_mastodon.py")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("run-all")
    a.add_argument("--dir", required=True)
    a.add_argument("--servers", default=",".join(SERVERS))
    args = parser.parse_args(argv)
    base = K.outside_repo(os.path.join(args.dir, "x"))
    if not base:
        return 2
    base = os.path.dirname(base)
    now, all_rows = time.time(), {}
    for server in [s.strip() for s in args.servers.split(",") if s.strip()]:
        rows_by_lang, kept = collect_server(server, now)
        for lang, rows in rows_by_lang.items():
            all_rows.setdefault(lang, []).extend(rows)
        print(f"[{server}] {kept} creators kept", flush=True)
        for lang, rows in all_rows.items():      # write as we go, so a long run is never lost
            K.write_rows(os.path.join(base, f"mastodon-{lang}.csv"), rows)
    for lang, rows in sorted(all_rows.items()):
        print(f"[mastodon {lang}] {len({r['author'] for r in rows})} creators, {len(rows)} posts", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
