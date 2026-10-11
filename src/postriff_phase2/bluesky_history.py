"""Public owned-post observations through the official Bluesky AppView.

The caller is the existing authenticated history-selection service: importing
writing samples still requires its exact selection, authorship and AI consent.
Counts are public observations, never impressions, reach or private analytics.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from postriff_alpha.domain import AlphaError

APPVIEW = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def fetch_owned_page(adapter, token, account_id, cursor=None, limit=25):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise AlphaError("Read between 1 and 25 posts per page.", 400)
    if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9_.~=:;-]{1,2048}", cursor)):
        raise AlphaError("This Bluesky cursor is invalid.", 400)
    session = json.loads(token)
    if not isinstance(account_id, str) or session.get("did") != account_id:
        raise AlphaError("Bluesky history does not belong to this connection.", 403)
    params = {"actor": account_id, "limit": limit, "filter": "posts_no_replies"}
    if cursor:
        params["cursor"] = cursor
    # No bearer/DPoP credential is disclosed to the public AppView.
    body = adapter._get_json(APPVIEW + "?" + urlencode(params))
    feed, next_cursor = body.get("feed"), body.get("cursor")
    if not isinstance(feed, list) or len(feed) > limit:
        raise AlphaError("Bluesky returned an invalid post page.", 502)
    if next_cursor is not None and (not isinstance(next_cursor, str)
            or not re.fullmatch(r"[A-Za-z0-9_.~=:;-]{1,2048}", next_cursor) or next_cursor == cursor):
        raise AlphaError("Bluesky pagination could not be verified.", 502)
    posts, seen = [], set()
    for entry in feed:
        if not isinstance(entry, dict) or entry.get("reason"):
            continue  # A repost is someone else's writing.
        post = entry.get("post")
        if not isinstance(post, dict) or not isinstance(post.get("author"), dict) or post["author"].get("did") != account_id:
            continue
        uri, record = post.get("uri"), post.get("record")
        if (not isinstance(uri, str) or not re.fullmatch(re.escape("at://" + account_id + "/app.bsky.feed.post/") + r"[A-Za-z0-9._~:-]{1,512}", uri)
                or uri in seen or not isinstance(record, dict) or record.get("$type") != "app.bsky.feed.post"):
            continue
        text = record.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 3000:
            continue
        published = ""
        try:
            instant = datetime.fromisoformat(record.get("createdAt", "").replace("Z", "+00:00"))
            if instant.tzinfo:
                published = instant.astimezone(timezone.utc).isoformat()
        except (TypeError, AttributeError, ValueError):
            pass
        metrics = {key: post[key] for key in ("likeCount", "replyCount", "repostCount", "quoteCount")
                   if type(post.get(key)) is int and post[key] >= 0}
        posts.append({"id": uri, "externalPostId": uri, "provider": "bluesky", "providerAccountId": account_id,
                      "text": text.strip(), "publishedAt": published, "permalink": "https://bsky.app/profile/" + account_id + "/post/" + uri.rsplit("/", 1)[1],
                      "thumbnailUrl": None, "mediaType": "POST", "platform": "Bluesky", "publicEngagement": metrics})
        seen.add(uri)
    dates = sorted(post["publishedAt"] for post in posts if post["publishedAt"])
    return {"posts": posts, "nextCursor": next_cursor, "scannedCount": len(feed), "skippedCount": len(feed) - len(posts),
            "partialCoverage": cursor is not None or next_cursor is not None,
            "coverage": {"startedFromBeginning": cursor is None, "endReached": next_cursor is None,
                         "from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                         "undatedCount": sum(not post["publishedAt"] for post in posts), "eligibleCount": len(posts)},
            "coverageNote": "Only retrieved original posts by the connected DID. Reposts, replies and empty posts are excluded. Public engagement counts are snapshots; no impressions or private analytics are available."}
