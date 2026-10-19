"""Pure X thread planning. Commit each transition before provider I/O."""
import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from postriff_alpha.domain import AlphaError
from .x_direct_contract import NormalizedOperation, normalize_operation


def _fail(message="This X thread requires a new review."):
    raise AlphaError(message, 409, code="x_thread_state_invalid")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def _post_id(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None


def normalize_thread(body, workspace_id, account_id, actor_user_id, *,
                     write_cost_micros=None, read_cost_micros=None, max_readbacks=3):
    if (not isinstance(body, Mapping) or set(body) != {"posts"}
            or not isinstance(body["posts"], (list, tuple))
            or not 2 <= len(body["posts"]) <= 25):
        _fail("An X thread requires 2 to 25 exact posts.")
    if type(max_readbacks) is not int or not 1 <= max_readbacks <= 10:
        _fail("Invalid thread verification limit.")
    posts = []
    for post in body["posts"]:
        if not isinstance(post, Mapping) or set(post) != {"text"}:
            _fail("This thread supports exact text posts; other fields need a supported separate operation.")
        posts.append(normalize_operation("posts.create", workspace_id=workspace_id,
            account_id=account_id, actor_user_id=actor_user_id, body=dict(post)))
    for cost in (write_cost_micros, read_cost_micros):
        if cost is not None and (type(cost) is not int or cost <= 0):
            _fail("Invalid verified X cost policy.")
    estimate = (None if write_cost_micros is None or read_cost_micros is None else
                len(posts) * (write_cost_micros + max_readbacks * read_cost_micros))
    fingerprint = _digest({"kind": "x-thread-v1", "posts": [p.fingerprint for p in posts],
        "maxReadbacks": max_readbacks, "writeCostMicros": write_cost_micros,
        "readCostMicros": read_cost_micros})
    return NormalizedOperation(operation_id="posts.thread", method="POST", path="/2/tweets",
        body={"posts": [{"text": p.body["text"]} for p in posts]}, query={},
        fingerprint=fingerprint, estimated_cost_micros=estimate,
        max_billable_resources=len(posts) * (1 + max_readbacks))


def _child(plan, index, previous_id):
    body = {"text": plan.body["posts"][index]["text"]}
    operation = "posts.create" if index == 0 else "posts.reply"
    if index:
        if not _post_id(previous_id):
            _fail("The preceding thread post has no verified X receipt.")
        body["reply"] = {"in_reply_to_tweet_id": previous_id}
    return replace(plan, operation_id=operation, body=body, query={},
        fingerprint=_digest({"kind": "x-thread-child-v1", "parent": plan.fingerprint,
            "index": index, "operation": operation, "body": body}),
        estimated_cost_micros=None, max_billable_resources=1)


def _state(plan, p):
    items = p["items"]
    pending = items[-1]["state"] if items and items[-1]["state"] != "verified" else None
    if len(items) == len(plan.body["posts"]) and pending is None:
        return "complete"
    if p["cancelRequested"]:
        return "cancelled_uncertain" if pending == "uncertain" else "cancelling" if pending else "cancelled"
    return {"dispatching": "dispatching", "accepted": "awaiting_readback",
            "verifying": "awaiting_readback", "uncertain": "uncertain"}.get(pending, "ready")


def _checked(plan, progress):
    if (not isinstance(plan, NormalizedOperation) or plan.operation_id != "posts.thread"
            or plan.method != "POST" or plan.path != "/2/tweets" or plan.query
            or not isinstance(plan.body, Mapping) or set(plan.body) != {"posts"}
            or not isinstance(plan.body["posts"], (list, tuple))
            or not 2 <= len(plan.body["posts"]) <= 25
            or type(plan.max_billable_resources) is not int
            or any(not isinstance(p, Mapping) or set(p) != {"text"} or not isinstance(p["text"], str)
                   for p in plan.body["posts"])):
        _fail()
    count = len(plan.body["posts"])
    limit = plan.max_billable_resources // count - 1
    if plan.max_billable_resources != count * (limit + 1) or not 1 <= limit <= 10:
        _fail()
    if progress is not None and not isinstance(progress, Mapping):
        _fail()
    p = ({"planFingerprint": plan.fingerprint, "cancelRequested": False, "items": []}
         if progress is None else deepcopy(dict(progress)))
    if (p.get("planFingerprint") != plan.fingerprint or type(p.get("cancelRequested")) is not bool
            or not isinstance(p.get("items"), list) or len(p["items"]) > count):
        _fail()
    seen = set()
    for index, item in enumerate(p["items"]):
        if not isinstance(item, Mapping) or type(item.get("index")) is not int or item["index"] != index:
            _fail()
        item = p["items"][index] = dict(item)
        state, reference, checks = item.get("state"), item.get("reference"), item.get("readbacks")
        if (state not in {"dispatching", "accepted", "verifying", "verified", "uncertain"}
                or (index < len(p["items"]) - 1 and state != "verified")
                or type(checks) is not int or not 0 <= checks <= limit):
            _fail()
        previous = p["items"][index - 1]["reference"] if index else None
        expected = _child(plan, index, previous).fingerprint
        if item.get("fingerprint") != expected:
            _fail()
        if reference is not None:
            if not _post_id(reference) or reference in seen:
                _fail()
            seen.add(reference)
        if ((state in {"accepted", "verifying", "verified"} and reference is None)
                or (state in {"verifying", "verified"} and checks == 0)
                or (state == "dispatching" and (reference is not None or checks != 0))
                or (state == "verified" and (item.get("verification") != "provider_lookup"
                    or item.get("verifiedFingerprint") != expected))):
            _fail()
    p["state"] = _state(plan, p)
    return p


def initial_progress(plan):
    return _checked(plan, None)


def next_step(plan, progress):
    p = _checked(plan, progress)
    if p["state"] != "ready":
        return None
    index = len(p["items"])
    return _child(plan, index, p["items"][-1]["reference"] if index else None)


def begin_step(plan, progress):
    p = _checked(plan, progress)
    child = next_step(plan, p)
    if child is None:
        _fail("This thread has no dispatchable next post.")
    p["items"].append({"index": len(p["items"]), "fingerprint": child.fingerprint,
        "state": "dispatching", "reference": None, "readbacks": 0})
    return child, _checked(plan, p)


def current_step(plan, progress):
    p = _checked(plan, progress)
    if not p["items"] or p["items"][-1]["state"] == "verified":
        return None
    index = len(p["items"]) - 1
    return _child(plan, index, p["items"][index - 1]["reference"] if index else None)


def _pending(plan, progress, child):
    p = _checked(plan, progress)
    current = current_step(plan, p)
    fields = ("fingerprint", "operation_id", "method", "path", "body", "query", "max_billable_resources")
    if (current is None or not isinstance(child, NormalizedOperation)
            or any(getattr(current, name) != getattr(child, name) for name in fields)):
        _fail("The X thread step changed.")
    return p, p["items"][-1]


def accept_step(plan, progress, child, provider_reference):
    p, item = _pending(plan, progress, child)
    if not _post_id(provider_reference):
        _fail("X did not return a valid post receipt.")
    if item["state"] in {"accepted", "verifying"} and item["reference"] == provider_reference:
        return p
    if item["state"] != "dispatching":
        _fail()
    item.update(state="accepted", reference=provider_reference)
    return _checked(plan, p)


def begin_readback(plan, progress, child):
    p, item = _pending(plan, progress, child)
    limit = plan.max_billable_resources // len(plan.body["posts"]) - 1
    if item["state"] not in {"accepted", "verifying"} or item["readbacks"] >= limit:
        _fail("The permitted X read-back attempts are exhausted or unavailable.")
    item["state"], item["readbacks"] = "verifying", item["readbacks"] + 1
    return _checked(plan, p)


def advance_step(plan, progress, child, verification):
    p, item = _pending(plan, progress, child)
    if (item["state"] != "verifying" or not isinstance(verification, Mapping)
            or verification.get("state") != "verified"
            or verification.get("verification") != "provider_lookup"
            or verification.get("requestFingerprint") != child.fingerprint
            or verification.get("reference") != item["reference"]):
        _fail("The official X lookup has not matched this exact approved thread step.")
    item.update(state="verified", verification="provider_lookup", verifiedFingerprint=child.fingerprint)
    return _checked(plan, p)


def inconclusive_readback(plan, progress, child):
    p, item = _pending(plan, progress, child)
    if item["state"] != "verifying":
        _fail()
    limit = plan.max_billable_resources // len(plan.body["posts"]) - 1
    item["state"] = "accepted" if item["readbacks"] < limit else "uncertain"
    return _checked(plan, p)


def uncertain_step(plan, progress, child):
    p, item = _pending(plan, progress, child)
    item["state"] = "uncertain"
    return _checked(plan, p)


def cancel_thread(plan, progress):
    p = _checked(plan, progress)
    p["cancelRequested"] = True
    return _checked(plan, p)
