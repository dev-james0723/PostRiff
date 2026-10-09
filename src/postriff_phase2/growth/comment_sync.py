"""Bounded comment re-sync for the workspace's own Threads and Instagram posts (Audience).

Comments used to be read once, inside the publish-verification transaction, and never again. They are now also
re-read by the native reading step (``MetricScheduler.tick``, wired where ``metric_reads.tick`` already runs), so this
step shares that step's boundaries instead of inventing new ones:

- Admission: the env allowlist or an active ``growth_measurement`` enrollment; ``POSTRIFF_METRIC_READS`` is the
  kill switch. Work per tick is bounded by the reading step's ``max_reads`` (one page per claimed reading) and its
  time budget.
- Lease and fence: comments are fetched outside any transaction for a reading this worker holds, and stored only
  inside that reading's fenced completion, after ``comments_read`` and the stored grant scopes are re-checked under
  lock. A revocation (consent, connection, capability or enrollment) that commits first blocks the write.
- Only posts younger than ``MAX_AGE_SECONDS`` on connections whose ``comments_read`` capability is Direct and whose
  grant carries the native comment scopes.
- One page of at most ``PAGE_LIMIT`` comments with fields ``id,text,timestamp``: no author handle is requested or
  stored by this step.
- The upsert is idempotent on (workspace, provider, comment id) and never revives or edits a tombstoned comment.
- Nothing is ever replied to, liked, hidden or deleted.
"""
from __future__ import annotations

import math
from datetime import datetime
from urllib.parse import quote, urlencode

from ..providers import GRAPH_VERSION

COMMENT_SCOPES = {
    "threads": frozenset({"threads_basic", "threads_read_replies"}),
    "instagram": frozenset({"instagram_business_basic", "instagram_business_manage_comments"}),
}
MAX_AGE_SECONDS = 30 * 86400
PAGE_LIMIT = 50
MAX_TEXT = 4000
FIELDS = "id,text,timestamp"


def due(row, now):
    """A reading of an owned post young enough to re-read its comments."""
    anchor = row.get("anchorAt")
    return (row.get("provider") in COMMENT_SCOPES and row.get("offset") is not None
            and type(anchor) in (int, float) and math.isfinite(anchor) and 0 <= now - anchor < MAX_AGE_SECONDS)


def scoped(scopes, provider):
    return provider in COMMENT_SCOPES and COMMENT_SCOPES[provider] <= set(scopes or [])


def endpoint(provider, post_id):
    if provider == "threads":
        return f"https://graph.threads.net/{GRAPH_VERSION}/{quote(str(post_id), safe='')}/replies"
    return f"https://graph.instagram.com/{GRAPH_VERSION}/{quote(str(post_id), safe='')}/comments"


def _text(value):
    """Plain bounded text; an oversize or odd comment is trimmed, never allowed to fail the reading."""
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "")[:MAX_TEXT].strip()


def _instant(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value.replace("Z", "+0000"), pattern).timestamp()
        except ValueError:
            continue
    return None


def fetch(transport, access_token, provider, post_id):
    """One bounded page. {"status": int|None, "comments": [{"id", "text", "at"}]}; transport errors propagate."""
    response = transport("GET", endpoint(provider, post_id) + "?" + urlencode(
        {"fields": FIELDS, "limit": PAGE_LIMIT, "access_token": access_token}))
    comments = []
    body = response.get("body") if isinstance(response, dict) else None
    if response.get("status") == 200 and isinstance(body, dict) and isinstance(body.get("data"), list):
        for item in body["data"][:PAGE_LIMIT]:
            if not isinstance(item, dict):
                continue
            comment_id = item.get("id")
            if not isinstance(comment_id, (str, int)) or isinstance(comment_id, bool) or not str(comment_id).strip() or len(str(comment_id)) > 200:
                continue
            comments.append({"id": str(comment_id), "text": _text(item.get("text")), "at": _instant(item.get("timestamp"))})
    return {"status": response.get("status"), "comments": comments}


def comments_readable(cur, workspace_id, connection_id, provider, *, lock=False):
    """comments_read is Direct and the live stored grant carries the native comment scopes."""
    cur.execute("SELECT level FROM public.pr_channel_capabilities WHERE workspace_id=%s AND connection_id=%s "
                "AND capability='comments_read'" + (" FOR SHARE" if lock else ""), (workspace_id, connection_id))
    level = cur.fetchone()
    if not level or level[0] != "Direct":
        return False
    cur.execute("SELECT provider,scopes FROM public.pr_encrypted_credentials WHERE workspace_id=%s AND connection_id=%s "
                "AND revoked_at IS NULL" + (" FOR SHARE" if lock else ""), (workspace_id, connection_id))
    credential = cur.fetchone()
    return bool(credential) and credential[0] == provider and scoped(credential[1], provider)


def store(cur, workspace_id, connection_id, provider, post_id, comments):
    """Idempotent upsert. A tombstoned comment is never revived or changed; unchanged text is not rewritten."""
    written = 0
    for comment in comments:
        cur.execute("""INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text,created_at_provider)
                       VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s))
                       ON CONFLICT(workspace_id,provider,provider_comment_id) DO UPDATE
                         SET text=excluded.text, ingested_at=now(),
                             created_at_provider=coalesce(public.pr_audience_threads.created_at_provider, excluded.created_at_provider)
                         WHERE public.pr_audience_threads.tombstoned_at IS NULL
                           AND (public.pr_audience_threads.text IS DISTINCT FROM excluded.text
                                OR (public.pr_audience_threads.created_at_provider IS NULL AND excluded.created_at_provider IS NOT NULL))""",
                    (workspace_id, connection_id, provider, str(post_id), comment["id"], comment["text"], comment["at"]))
        written += cur.rowcount or 0
    return written
