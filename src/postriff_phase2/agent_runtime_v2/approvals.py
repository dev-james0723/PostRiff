"""Approvals across modalities (spec §3.3, §7.4, §13, ADR-H1/H2).

Conversation is not authorization. A "yes" — typed or spoken, in English, Cantonese or Mandarin — applies a proposal
only when it binds to exactly one open proposal that Rafii presented in its latest answer, within the binding window.
The application then does what it always does: `SiteAgentService.apply_proposal` re-checks the digest, the stored
state (stale proposals are refused), the member's permission and the plan gate, applies through the workspace command,
and audits. After that, this module re-reads the workspace and compares it with the proposal before anything is
reported as done.

A proposal Rafii created is never approved by Rafii. A dismissed proposal is not retried without a new request.
"""
from __future__ import annotations

import re
import time

from postriff_alpha.domain import AlphaError

BIND_WINDOW_SECONDS = 600

_YES = (r"yes|yeah|yep|yup|sure|ok(?:ay)?|confirm(?:ed)?|go\s+ahead|do\s+it|apply\s+it|please\s+do|sounds\s+good|that'?s\s+right|correct|approve\s+it"
        r"|係(?:呀|啊|嘅)?|好(?:呀|啊|嘅|的|吧)?|得(?:呀|啦)?|可以(?:呀|啊|的)?|確認|确认|冇問題|没问题|沒問題|就咁做(?:啦)?|做啦|套用(?:佢)?|是(?:的)?|行|對|对|同意")
_NO = (r"no|nope|don'?t|do\s+not|cancel(?:\s+it)?|stop|not\s+now|never\s+mind|dismiss(?:\s+it)?"
       r"|唔好|唔使|取消|不要|不用|算了|唔要|先唔好|不必")
_FILLER = r"(?:\s*(?:please|thanks|thank\s+you|rafii|raffi|唔該|謝謝|谢谢|啦|吧|呀|啊|喇))*"
_CONFIRM = re.compile(rf"^\s*(?:{_YES})(?:\s*[,，]?\s*(?:{_YES}))*{_FILLER}\s*[.!。！]*\s*$", re.I)
_REJECT = re.compile(rf"^\s*(?:{_NO})(?:\s*[,，]?\s*(?:{_NO}))*{_FILLER}\s*[.!。！]*\s*$", re.I)
_CANCEL_WORK = re.compile(r"^\s*(?:cancel\s+(?:that|it|this|the\s+(?:task|request|image|draft))|stop\s+(?:that|it|working\s+on\s+(?:that|it))|never\s+mind"
                          r"|取消(?:佢|呢個|嗰個|它|这个|那个)?|唔使做喇|唔好做喇|不用做了|别做了|別做了)\s*[.!。！]*\s*$", re.I)


def is_confirmation(text: str) -> bool:
    return bool(text) and len(text) <= 60 and bool(_CONFIRM.match(text))


def is_rejection(text: str) -> bool:
    return bool(text) and len(text) <= 60 and bool(_REJECT.match(text)) and not _CANCEL_WORK.match(text)


def is_cancel_request(text: str) -> bool:
    return bool(text) and len(text) <= 60 and bool(_CANCEL_WORK.match(text))


# --- reading proposals --------------------------------------------------------------------------------------------------
def _answers(cur, workspace_id, conversation_id, limit=40):
    """Assistant answers (not transcripts), newest first: (message id, seq, created epoch, siteAgent body)."""
    cur.execute("SELECT id::text,seq,extract(epoch from created_at),body->'siteAgent' FROM public.pr_messages WHERE conversation_id::text=%s AND workspace_id=%s "
                "AND role='assistant' AND body ? 'siteAgent' ORDER BY seq DESC LIMIT %s", (conversation_id, workspace_id, limit))
    return [(mid, seq, float(at), site or {}) for mid, seq, at, site in cur.fetchall()]


def open_proposals(cur, workspace_id: str, conversation_id: str, now: float) -> list[dict]:
    items = []
    for message_id, seq, at, site in _answers(cur, workspace_id, conversation_id):
        for proposal in site.get("proposals") or []:
            if isinstance(proposal, dict) and proposal.get("status") == "proposed" and proposal.get("expiresAt", 0) > now:
                # When Rafii presented it: the proposal's own creation time (the same clock that checks the window), else the message's.
                presented = proposal.get("createdAt") if isinstance(proposal.get("createdAt"), (int, float)) else at
                items.append({"proposalId": proposal["id"], "messageId": message_id, "seq": seq, "presentedAt": float(presented), "type": proposal.get("type"),
                              "summary": proposal.get("summary") or [], "digest": proposal.get("digest"), "expiresAt": proposal.get("expiresAt"),
                              "requiredPermission": proposal.get("requiredPermission"), "proposal": proposal})
    return items


def find(cur, workspace_id: str, conversation_id: str, proposal_id: str) -> dict | None:
    for message_id, seq, at, site in _answers(cur, workspace_id, conversation_id, limit=200):
        for proposal in site.get("proposals") or []:
            if isinstance(proposal, dict) and proposal.get("id") == proposal_id:
                return {"messageId": message_id, "seq": seq, "presentedAt": at, "proposal": proposal}
    return None


def bind(cur, workspace_id: str, conversation_id: str, now: float) -> dict:
    """Which proposal a bare "yes"/"no" may refer to.

    {"bind": item} — exactly one open proposal, presented in the latest answer, within the window;
    {"ask": text, "candidates": [...]} — several open, or the open one is not the one just presented;
    {"none": reason} — nothing open (the reply goes to the Manager as ordinary conversation)."""
    open_items = open_proposals(cur, workspace_id, conversation_id, now)
    if not open_items:
        return {"none": "no_open_proposal"}
    answers = _answers(cur, workspace_id, conversation_id, limit=1)
    latest = answers[0] if answers else None
    presented_now = [item for item in open_items if latest and item["messageId"] == latest[0] and now - item["presentedAt"] <= BIND_WINDOW_SECONDS]
    if len(open_items) == 1 and len(presented_now) == 1:
        return {"bind": presented_now[0]}
    # Listed in the order Rafii proposed them, so "the first one" is the first proposal the person heard or saw.
    ordered = sorted(open_items, key=lambda item: item["seq"])
    candidates = [{"type": "proposal", "id": item["proposalId"], "title": "; ".join(item["summary"])[:120]} for item in ordered][:5]
    if len(open_items) > 1:
        return {"ask": "There are several changes waiting for you. Which one do you mean?", "candidates": candidates}
    item = open_items[0]
    return {"ask": "Just to be sure, do you want me to apply this: " + "; ".join(item["summary"])[:200] + "?", "candidates": candidates, "restate": item}


# --- verification (§23) --------------------------------------------------------------------------------------------------
def verify_applied(state: dict, proposal: dict) -> tuple[bool, list[dict]]:
    """Re-read the workspace and compare with what the applied proposal intended."""
    result = proposal.get("result") or {}
    p2 = state.get("phase2") or {}
    checks = []
    if proposal.get("type") in ("schedule_draft", "reschedule_post"):
        review = next((r for r in p2.get("reviews", []) if r.get("id") == result.get("reviewId")), None)
        manifest = (review or {}).get("manifest") or {}
        checks.append({"what": "a review exists for the exact post", "expected": "present", "actual": "present" if review else "missing", "verified": review is not None})
        if review is not None:
            checks.append({"what": "the draft", "expected": proposal.get("variantId"), "actual": manifest.get("variantId"), "verified": manifest.get("variantId") == proposal.get("variantId")})
            checks.append({"what": "the time", "expected": proposal.get("localTime"), "actual": (manifest.get("timing") or {}).get("local"),
                           "verified": (manifest.get("timing") or {}).get("local") == proposal.get("localTime")})
            checks.append({"what": "the account", "expected": proposal.get("channelId"), "actual": manifest.get("channelId"), "verified": manifest.get("channelId") == proposal.get("channelId")})
            checks.append({"what": "state", "expected": "waiting for approval (not published)", "actual": review.get("status"), "verified": review.get("status") == "needs_review"})
            media = proposal.get("media") or None
            if media:
                attached = [m.get("id") for m in manifest.get("media") or []]
                checks.append({"what": "the image", "expected": media.get("assetId"), "actual": attached[0] if attached else None, "verified": media.get("assetId") in attached})
        if proposal.get("jobId"):
            job = next((j for j in p2.get("jobs", []) if j.get("id") == proposal["jobId"]), None)
            checks.append({"what": "the old post", "expected": "canceled", "actual": (job or {}).get("state"), "verified": (job or {}).get("state") == "canceled"})
    elif proposal.get("type") == "automation_change":
        root = (state.get("raffi") or {}).get("campaignPlanning") or {}
        task = next((t for t in root.get("recurringTasks") or [] if t.get("id") == proposal.get("taskId")), None)
        checks.append({"what": "the automation", "expected": "present", "actual": "present" if task else "missing", "verified": task is not None})
        if task is not None:
            checks.append({"what": "version", "expected": result.get("version"), "actual": task.get("version"), "verified": result.get("version") is None or task.get("version") == result.get("version")})
            checks.append({"what": "status", "expected": result.get("status"), "actual": task.get("status"), "verified": result.get("status") is None or task.get("status") == result.get("status")})
    else:
        checks.append({"what": "proposal type", "expected": "known", "actual": proposal.get("type"), "verified": False})
    return all(c["verified"] for c in checks), checks


def decide(service, workspace_id: str, token: str, *, conversation_id: str, message_id: str, proposal_id: str, digest: str, decision: str,
           zone: str | None = None) -> dict:
    """Apply or dismiss through the site agent's own path, then verify by re-reading. Never bypasses its checks."""
    site = service.site_agent
    payload = {"messageId": message_id, "conversationId": conversation_id, "proposalId": proposal_id, "digest": digest, **({"timeZone": zone} if zone else {})}
    if decision == "dismiss":
        closed = site.dismiss_proposal(workspace_id, token, payload)
        return {"outcome": (closed.get("proposal") or {}).get("status") or "dismissed", "verified": True, "checks": [], "proposal": closed.get("proposal")}
    if decision != "apply":
        raise AlphaError("Choose apply or dismiss.", 400)
    applied = None
    for attempt in range(2):
        payload["expectedRevision"] = service.repository.get(workspace_id, token)["revision"]
        try:
            applied = site.apply_proposal(workspace_id, token, payload)
            break
        except AlphaError as error:
            if error.code != "workspace_revision_conflict" or attempt:
                raise
    state = service.repository.get(workspace_id, token)["state"]
    with service.repository.transaction(token, workspace_id) as (cur, _row, _principal):
        stored = find(cur, workspace_id, conversation_id, proposal_id)
    proposal = (stored or {}).get("proposal") or {}
    if proposal.get("status") != "applied":
        return {"outcome": proposal.get("status") or "unknown", "verified": False, "checks": [], "proposal": (applied or {}).get("proposal")}
    verified, checks = verify_applied(state, proposal)
    return {"outcome": "applied", "verified": verified, "checks": checks, "proposal": (applied or {}).get("proposal"), "result": proposal.get("result"),
            "revision": (applied or {}).get("revision")}


def now() -> float:
    return time.time()
