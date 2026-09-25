"""Engagement Copilot (adaptive coworker spec §12 AI Inbox / Engagement Copilot; architecture lock L1).

Works only on what the workspace's connected, permitted integrations already ingested (`pr_audience_threads`).
Triage and summaries are deterministic; the reply method (`rafii-engagement-triage`) is compiled for the drafting
route. A drafted reply is a row in `pr_reply_drafts` with status `draft`: sending stays `AudienceService
.approve_reply` (reply permission, exact digest, `confirmed: true`) and the worker's send path. Nothing here sends.

Urgency is never manufactured: an item's priority comes from a fixed rule table (category and age), and no
engagement item is ever "immediate" on its own.
"""
from __future__ import annotations

import json
import re
import time

from postriff_alpha.domain import AlphaError

from .. import skill_compiler
from ..permissions import require

CATEGORIES = ("question", "complaint", "lead", "praise", "press_or_partner", "spam", "abusive", "other")
PRIORITY = {"complaint": "needs_reply", "question": "needs_reply", "lead": "needs_reply", "press_or_partner": "review", "praise": "fyi",
            "other": "fyi", "spam": "ignore", "abusive": "review"}
RULES = (
    ("spam", r"(follow for follow|f4f|crypto|airdrop|dm me for|check my profile|click (?:the )?link in my bio|earn \$\d+|whatsapp \+?\d)"),
    ("abusive", r"\b(idiot|stupid|scam artist|shut up|trash|垃圾|白痴|仆街|死開)\b"),
    ("complaint", r"(not working|doesn'?t work|broken|refund|disappointed|terrible|worst|never arrived|charged twice|投訴|退款|壞咗|唔work|失望|差劲|差勁)"),
    ("lead", r"(price|pricing|how much|quote|demo|buy|purchase|order|available in|shipping|book (?:a|an)|contact you|collab|合作|幾錢|价格|價錢|報價|购买|購買)"),
    ("press_or_partner", r"(journalist|reporter|press|media inquiry|interview|partnership|sponsor|記者|採訪|赞助|贊助)"),
    ("question", r"(\?|？|\b(how|what|when|where|why|which|can you|could you|do you|is there|does it)\b|點樣|點解|幾時|邊度|係咪|有冇|怎么|怎麼|为什么|為什麼|吗|嗎)"),
    ("praise", r"(love (?:this|it)|great|amazing|awesome|thank you|thanks|well done|beautiful|好正|好靚|多謝|谢谢|謝謝|讚|赞|😍|🔥|👏)"),
)
_COMPILED = [(category, re.compile(pattern, re.I)) for category, pattern in RULES]
FRESH_HOURS = 72


def classify(text):
    for category, pattern in _COMPILED:
        if pattern.search(text or ""):
            return category
    return "other"


def triage_item(thread, now=None):
    now = now or time.time()
    category = classify(thread.get("text"))
    replied = any(r.get("status") in ("approved", "submitting", "submitted", "verified") for r in thread.get("replies") or [])
    created = thread.get("createdAtProvider") or thread.get("ingestedAt") or now
    age_hours = max(0.0, (now - created) / 3600)
    priority = PRIORITY[category]
    reasons = [f"category: {category}"]
    if replied:
        priority, reasons = "done", reasons + ["already answered"]
    elif priority == "needs_reply" and age_hours > 24 * 14:
        priority, reasons = "review", reasons + ["older than two weeks"]
    elif priority == "needs_reply":
        reasons.append("unanswered" + (f", {int(age_hours)} h old" if age_hours >= 1 else ", new"))
    return {"threadId": thread.get("threadId"), "author": thread.get("author"), "provider": thread.get("provider"), "category": category, "priority": priority,
            "fresh": age_hours <= FRESH_HOURS, "ageHours": round(age_hours, 1), "why": "; ".join(reasons), "urgent": False,
            "summary": summarize(thread, category), "replyAvailable": bool(thread.get("replyAvailable"))}


def summarize(thread, category=None):
    text = " ".join((thread.get("text") or "").split())
    excerpt = text[:160] + ("…" if len(text) > 160 else "")
    who = f"@{thread.get('author')}" if thread.get("author") else "Someone"
    verb = {"question": "asked", "complaint": "complained", "lead": "asked about buying or working together", "praise": "praised the post",
            "press_or_partner": "asked about press or a partnership", "spam": "posted what looks like spam", "abusive": "posted an abusive comment"}.get(category or classify(text), "commented")
    return f"{who} {verb} on {thread.get('provider') or 'a post'}: “{excerpt}”"


def triage(threads, now=None):
    items = [triage_item(t, now) for t in threads if not t.get("tombstoned")]
    order = {"needs_reply": 0, "review": 1, "fyi": 2, "done": 3, "ignore": 4}
    items.sort(key=lambda i: (order[i["priority"]], i["ageHours"]))
    counts = {p: sum(1 for i in items if i["priority"] == p) for p in order}
    return {"items": items, "counts": counts, "note": "Priorities come from fixed rules (category and age). Nothing here is urgent on its own."}


def _starter(category, author, facts):
    handle = f"@{author}" if author else "there"
    if category == "question":
        return f"Thanks for asking, {handle}. [ANSWER: add the approved answer here{' — known facts: ' + '; '.join(facts[:2]) if facts else ''}]"
    if category == "complaint":
        return f"Sorry this happened, {handle}. Could you send us the details by direct message so we can look into it? [NEXT STEP: the workspace's supported fix or contact route]"
    if category == "lead":
        return f"Thanks for your interest, {handle}! [DETAILS: price, availability or how to order — only approved facts]"
    if category == "press_or_partner":
        return f"Thank you for reaching out, {handle}. [CONTACT: the workspace's approved press or partnership contact]"
    if category == "praise":
        return f"Thank you, {handle}! That means a lot."
    return f"Thanks for commenting, {handle}."


def draft_reply(service, workspace_id, token, thread_id, *, now=None):
    """A reply suggestion for one thread, saved as a draft for review. The compiled engagement method rides with the
    request (and its provenance); on this deterministic route the text is a labelled starter with explicit
    placeholders for any fact the workspace has not approved. Sending is a separate, approved action."""
    now = now or time.time()
    compiled = skill_compiler.compile({"agent": "content", "intent": "engagement_reply", "workflow": "rafii-engagement-triage"})
    with service.repository.transaction(token, workspace_id) as (cur, row, principal):
        member = service.ideas._member(row)
        require(member, "edit")
        cur.execute("SELECT text,author_handle,provider FROM public.pr_audience_threads WHERE id::text=%s AND workspace_id=%s AND tombstoned_at IS NULL", (thread_id, workspace_id))
        thread = cur.fetchone()
        if not thread:
            raise AlphaError("Thread unavailable.", 404)
        category = classify(thread[0])
        if category in ("spam", "abusive"):
            return {"drafted": False, "category": category, "reason": "Rafii does not draft replies to spam or abusive comments; hide or report them from the platform instead."}
        state = service.ideas._state(row)
        facts = [f["text"] for s in state.get("sources") or [] if s.get("active") for f in s.get("facts") or [] if f.get("approved")][:5]
        text = _starter(category, thread[1], facts)
        provenance = skill_compiler.provenance_for_run(compiled, state=state)
        # Truthful provenance: the method was attached, but this deterministic starter was not written by a model.
        provenance["route"] = {"kind": "deterministic_starter", "methodApplied": False}
        for skill in provenance["skills"]:
            skill["applied"] = False
        events = [{"at": now, "state": "draft", "by": "engagement_copilot", "category": category, "provenance": provenance}]
        cur.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status,events) VALUES(%s,%s,%s,'copilot',%s,'draft',%s::jsonb) RETURNING id::text",
                    (workspace_id, thread_id, principal, text, json.dumps(events)))
        draft_id = cur.fetchone()[0]
        cur.execute("SELECT status,origin,text FROM public.pr_reply_drafts WHERE id::text=%s AND workspace_id=%s", (draft_id, workspace_id))
        stored = cur.fetchone()
        verified = stored is not None and stored[0] == "draft" and stored[2] == text
    return {"drafted": True, "verified": verified, "draftId": draft_id, "category": category, "text": text, "status": "draft",
            "label": "Suggested reply — review before sending", "placeholders": re.findall(r"\[[A-Z ]+:[^\]]*\]", text),
            "sending": "Not sent. Approving and sending use the existing reply approval.", "provenance": provenance}
