"""Output policy for model-phrased answers (site agent §14.3 steps 5–7, §14.6, §18.5).

A model answer is kept only when it is well formed, cites only the evidence it was given, recommends only the links
it was offered, contains nothing that looks like a credential, names no id the evidence did not contain, and never
claims that something was done. Anything else is discarded whole (never repaired into something new) and the
grounded answer is shown instead, with the reason recorded in the trace.
"""
from __future__ import annotations

import re

from . import knowledge

MAX_ANSWER = 1500
_HTML = re.compile(r"<[^>]{1,200}>")
_LINK = re.compile(r"!?\[([^\]]{0,200})\]\(([^)]{0,500})\)")
_URL = re.compile(r"\bhttps?://\S+", re.I)
_ID_LIKE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{24,64}\b", re.I)
# "I published…", "Rafii has scheduled…", "已經幫你發佈" — Rafii's guide never performs these, so such a claim is false.
_DONE = re.compile(r"\b(?:i(?:'ve|\s+have)?|we(?:'ve|\s+have)?|rafii\s+(?:has\s+)?)\s*(?:just\s+|now\s+|already\s+)?(?:published|posted|scheduled|approved|connected|disconnected|deleted|removed|changed|updated|paused|resumed|sent|replied|bought|purchased|activated|cancelled|canceled)\b"
                   r"|(?:我|Rafii)?(?:已經|已)(?:幫你)?(?:發佈|發布|出咗|排程|批准|連接|斷開|刪除|更改|修改|暫停|恢復|付款|購買|回覆)", re.I)


def clean_answer(text: str) -> str:
    text = _HTML.sub("", text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _URL.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def validate_answer(answer, *, help_refs: set, fact_refs: set, action_refs: set, known_ids: set, grounding_required: bool) -> tuple[dict | None, str | None]:
    """(kept answer, None) or (None, reason)."""
    if not isinstance(answer, dict):
        return None, "not_object"
    text = answer.get("answer")
    if not isinstance(text, str) or not text.strip():
        return None, "empty"
    if len(text) > MAX_ANSWER:
        return None, "too_long"
    for pattern in knowledge.SECRET_PATTERNS:
        if pattern.search(text):
            return None, "secret_like"
    if _DONE.search(text):
        return None, "claims_action"
    for match in _ID_LIKE.findall(text):
        if match.lower() not in known_ids:
            return None, "unknown_id"

    def refs(key, allowed, limit):
        value = answer.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        if any(item not in allowed for item in value):
            return None
        return list(dict.fromkeys(value))[:limit]

    citations, facts, actions = refs("citations", help_refs, 6), refs("facts", fact_refs, 12), refs("actions", action_refs, 2)
    if citations is None or facts is None or actions is None:
        return None, "unknown_reference"
    sufficient = answer.get("sufficient")
    if not isinstance(sufficient, bool):
        return None, "shape"
    if grounding_required and sufficient and not citations and not facts:
        return None, "ungrounded"
    follow = [f.strip()[:100] for f in answer.get("followUps") or [] if isinstance(f, str) and f.strip()][:3]
    missing = [m.strip()[:120] for m in answer.get("missing") or [] if isinstance(m, str) and m.strip()][:3]
    return {"answer": clean_answer(text), "citations": citations, "facts": facts, "actions": actions, "followUps": follow,
            "sufficient": sufficient, "missing": missing}, None
