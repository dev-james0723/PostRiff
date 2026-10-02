"""Inbox-specific provider boundary. Connector presence never implies comment or reply support."""
from urllib.parse import quote, urlencode, urlparse

from postriff_alpha.domain import AlphaError
from .providers import GRAPH_VERSION


class ThreadsInboxAdapter:
    provider = "threads"

    @staticmethod
    def list_comments(post_id, token, transport, *, after=None, limit=50, fields="id,text,username,timestamp,permalink"):
        if not str(post_id).isdigit() or not 1 <= limit <= 50 or after is not None and (not isinstance(after, str) or len(after) > 256):
            raise AlphaError("Invalid Threads comment page.", 400)
        if fields not in ("id,text,username,timestamp,permalink", "id,text,replied_to,is_reply_owned_by_me"):
            raise AlphaError("Unsupported Threads fields.", 400)
        query = {"fields": fields, "limit": limit, "access_token": token}
        if after:
            query["after"] = after
        return transport("GET", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(str(post_id))}/replies?" + urlencode(query))

    @staticmethod
    def source_permalink(value):
        if not isinstance(value, str) or len(value) > 1000:
            return None
        parsed = urlparse(value)
        return value if parsed.scheme == "https" and parsed.hostname in ("threads.net", "www.threads.net", "threads.com", "www.threads.com") and not parsed.username and not parsed.password else None

    @staticmethod
    def send_reply(manifest, token, transport):
        user = str(manifest.get("providerAccountId") or "")
        reply_to = str(manifest.get("replyToCommentId") or "")
        text = manifest.get("text")
        if not user.isdigit() or not reply_to.isdigit() or not isinstance(text, str) or not 0 < len(text) <= 500:
            return {"state": "held", "confirmed": "Invalid exact Threads reply manifest."}
        container = transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads",
                              form={"media_type": "TEXT", "text": text, "reply_to_id": reply_to, "access_token": token})
        cid = str((container.get("body") or {}).get("id") or "")
        if container.get("status") in (401, 403):
            return {"state": "held", "confirmed": "Threads rejected the reply permission before creating a container."}
        if container.get("status") != 200 or not cid.isdigit():
            return {"state": "uncertain", "confirmed": "Container result is inconclusive; do not resend."}
        published = transport("POST", f"https://graph.threads.net/{GRAPH_VERSION}/{quote(user)}/threads_publish",
                              form={"creation_id": cid, "access_token": token})
        reply_id = str((published.get("body") or {}).get("id") or "")
        return ({"state": "submitted", "reference": reply_id, "confirmed": "Threads returned a reply id; read-back is pending."}
                if published.get("status") == 200 and reply_id.isdigit() else
                {"state": "uncertain", "confirmed": "Publish result is inconclusive; do not resend."})

    def reconcile_reply(self, manifest, reference, token, transport):
        if not str(reference).isdigit() or not str(manifest.get("threadPostId") or "").isdigit():
            return False
        response = self.list_comments(manifest["threadPostId"], token, transport, limit=50,
                                      fields="id,text,replied_to,is_reply_owned_by_me")
        if response.get("status") != 200 or not isinstance((response.get("body") or {}).get("data"), list):
            return False
        return any(isinstance(item, dict) and str(item.get("id")) == reference
                   and (item.get("replied_to") or {}).get("id") == manifest.get("replyToCommentId")
                   and item.get("text") == manifest.get("text") and item.get("is_reply_owned_by_me") is True
                   for item in response["body"]["data"][:50])

    @staticmethod
    def error(status):
        return {"availability": "unavailable", "reason": f"Threads returned HTTP {status if isinstance(status, int) else 'unknown'}.",
                "errorCode": f"provider_{status if isinstance(status, int) else 'unknown'}"}


_ADAPTERS = {"threads": ThreadsInboxAdapter()}


def adapter_for(provider):
    return _ADAPTERS.get(provider)
