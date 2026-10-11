"""Independent worker-boundary validation of Telegram identifiers and payloads."""
import copy
import json
from .publishing import METHODS


def validated(value, reference):
    if not isinstance(value, dict) or value.get("version") != 1 or set(value) - {"version", "apiPath", "messages", "payload"}: return None
    if value.get("apiPath") not in {"Bot API/" + m[0] for m in METHODS.values()}: return None
    messages = value.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 10: return None
    keys = {"chatId", "messageId", "date", "editDate", "mediaGroupId", "messageThreadId", "directMessagesTopicId", "url"}
    if any(not isinstance(m, dict) or set(m) - keys or type(m.get("chatId")) is not int or type(m.get("messageId")) is not int or m["messageId"] <= 0 or type(m.get("date")) is not int for m in messages): return None
    if reference != f"{messages[0]['chatId']}/{messages[0]['messageId']}": return None
    if len({m["chatId"] for m in messages}) != 1 or len({m["messageId"] for m in messages}) != len(messages): return None
    if len(messages) > 1 and (len({m.get("mediaGroupId") for m in messages}) != 1 or not messages[0].get("mediaGroupId")): return None
    body = value.get("payload")
    if not isinstance(body, dict) or body.get("chat_id") != messages[0]["chatId"]: return None
    if set(body) & {"token", "access_token", "accessToken", "password", "session", "auth_code", "allow_paid_broadcast", "star_count", "suggested_post_parameters"}: return None
    if len(json.dumps(value).encode()) > 131072: return None
    return copy.deepcopy(value)
