"""What the Manager may say, and the deterministic answer when it may not (spec §3.2, §9, §23, §29; WP10).

The Manager's reply is words about work the tools did. It is kept only when:
- it contains nothing credential-like (the site agent's secret patterns);
- it never claims an effect no Rafii tool can have (published, posted, approved, sent, replied, deleted, disconnected,
  bought) and never claims "scheduled" (scheduling is a proposal until a person applies it, outside the model);
- a claim that something was created, linked, generated, saved, changed or edited is backed by at least one verified
  entity the tools re-read this turn;
- every id it names came from a tool this turn;
- it is not empty and not too long.
Otherwise the answer is composed from the effect ledger alone (`compose`), and the reason is recorded in the trace.
The same check runs as an Agents SDK output guardrail on the Manager, so a failing reply trips before it is used.
"""
from __future__ import annotations

import re

from .context import EffectLedger

MAX_ANSWER = 2400
_ID_LIKE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{24,64}\b", re.I)
# First-person claims of effects no Rafii tool can have (or, for "scheduled", that only a person's approval can have).
_NEVER = re.compile(
    r"\b(?:i(?:'ve|\s+have)?|we(?:'ve|\s+have)?|rafii\s+(?:has\s+)?)\s*(?:just\s+|now\s+|already\s+|successfully\s+|gone\s+ahead\s+and\s+)?"
    r"(?:published|posted|approved|sent|replied|deleted|disconnected|bought|purchased|scheduled)\b"
    r"|(?:我|rafii)\s*(?:已經|已|成功)?(?:幫你)?(?:發佈|發布|出咗|發咗|排程|排好|批准|刪除|删除|斷開|断开|付款|購買|购买|回覆|回复|發送|发送)", re.I)
# Passive claims that a pending proposal already took effect ("your post has been scheduled").
_PASSIVE_EFFECT = re.compile(
    r"\b(?:has|have)\s+been\s+(?:scheduled|published|posted|approved|applied|sent)\b|\b(?:is|are)\s+now\s+(?:scheduled|published|live|approved)\b"
    r"|已(?:經)?(?:排程|排好|發佈|發布|批准|套用)", re.I)
_DID = re.compile(
    r"\b(?:i(?:'ve|\s+have)?|we(?:'ve|\s+have)?|rafii\s+(?:has\s+)?)\s*(?:just\s+|now\s+|already\s+|successfully\s+)?"
    r"(?:created|linked|added|attached|generated|saved|changed|updated|edited|rewrote|rewritten|shortened|made|removed|moved)\b"
    r"|(?:已經|已|成功)(?:幫你)?(?:建立|創建|创建|生成|整咗|加咗|加入|連結|链接|儲存|保存|更新|修改|改咗)", re.I)


def _secret(text: str) -> bool:
    from ..site_agent import knowledge
    return any(pattern.search(text) for pattern in knowledge.SECRET_PATTERNS)


def check(answer: str, ledger: EffectLedger) -> str | None:
    """None when the answer may be used; otherwise the reason it may not."""
    if not isinstance(answer, str) or not answer.strip():
        return "empty"
    if len(answer) > MAX_ANSWER:
        return "too_long"
    if _secret(answer):
        return "secret_like"
    if _NEVER.search(answer):
        return "claims_forbidden_effect"
    if ledger.proposals and _PASSIVE_EFFECT.search(answer):
        return "claims_pending_proposal_applied"
    verified = [c for c in ledger.changed if c.get("verified")] + [a for a in ledger.assets if a.get("verified")]
    if _DID.search(answer) and not verified:
        return "claims_unverified_change"
    for match in _ID_LIKE.findall(answer):
        if match.lower() not in ledger.known_ids:
            return "unknown_id"
    return None


def clean(text: str) -> str:
    """Links and markup are the panel's job (typed blocks, manifest routes only); the answer is plain prose."""
    from ..site_agent import policy as site_policy
    return site_policy.clean_answer(text)


# --- deterministic composition from the ledger -------------------------------------------------------------------------
_STATE_WORDS = {"planned": "not started", "running": "in progress", "done": "done", "needs_user": "needs you", "blocked": "blocked", "failed": "failed", "canceled": "cancelled"}


def compose(ledger: EffectLedger, task=None, *, language: str | None = None, note: str | None = None) -> tuple[str, str]:
    """(answer, speakable) built only from what the tools did and re-read."""
    lines = []
    if note:
        lines.append(note)
    for change in ledger.changed:
        state = "confirmed" if change.get("verified") else "NOT confirmed — please check it"
        lines.append(f"{change['type'].capitalize()} {change.get('change')} ({state}).")
    for asset in ledger.assets:
        lines.append(f"Saved a new {asset.get('kind', 'image')} image to your library" + (" — the original is unchanged" if asset.get("parentAssetId") else "") + ".")
    for proposal in ledger.proposals:
        lines.append("Prepared for your approval: " + "; ".join(proposal.get("summary") or [])[:300] + ". Nothing changes until you apply it.")
    if task is not None and task.steps:
        summary = task.summary()
        lines.append(f"{summary['done']} of {summary['total']} step(s) done:")
        lines.extend(f"- {line}" for line in summary["lines"])
    for error in ledger.errors[:4]:
        lines.append(f"Not done: {error['message']}")
    for warning in ledger.warnings[:3]:
        lines.append(warning["message"])
    if not lines:
        read = [a["label"] for a in ledger.tool_activity if a.get("status") == "verified"]
        lines.append(("I checked: " + ", ".join(dict.fromkeys(read)) + ". " if read else "") +
                     "I couldn't put together an answer I can stand behind, so I'm not guessing. Could you say a bit more about what you need?")
    answer = "\n".join(lines)
    spoken = []
    if ledger.changed or ledger.assets:
        confirmed = sum(1 for c in ledger.changed if c.get("verified")) + sum(1 for a in ledger.assets if a.get("verified"))
        spoken.append(f"I confirmed {confirmed} change{'s' if confirmed != 1 else ''} in your workspace.")
    if ledger.proposals:
        first = ledger.proposals[0]
        spoken.append("I've prepared this for your approval: " + "; ".join(first.get("summary") or [])[:220] + ". Say yes to apply it, or no to leave it.")
    if ledger.errors:
        spoken.append("Something didn't work: " + ledger.errors[0]["message"][:200])
    if not spoken:
        spoken.append(lines[0][:300])
    return answer, " ".join(spoken)


def reply_type():
    """The Manager's structured output (pydantic, so the SDK validates it)."""
    from pydantic import BaseModel, Field

    class ManagerReply(BaseModel):
        answer: str = Field(description="What you tell the person, in their language. Plain sentences; no links, no ids, no markdown tables.")
        speakable: str = Field(description="One to three short spoken sentences for voice: the outcome and the next step. No lists, links or ids.")
        language: str = Field(default="en", description="BCP 47 tag of the language you answered in (en, zh-Hant-HK for Cantonese, zh-Hans or zh-Hant for Mandarin).")
        follow_ups: list[str] = Field(default_factory=list, description="Up to three short follow-up questions the person might ask next.")

    return ManagerReply


def output_guardrail():
    from agents import GuardrailFunctionOutput, output_guardrail as decorate

    @decorate(name="rafii_truthful_answer")
    async def truthful(context, _agent, output):
        ledger = context.context.ledger
        text = getattr(output, "answer", output if isinstance(output, str) else "")
        reason = check(text, ledger) or (check(getattr(output, "speakable", ""), ledger) if getattr(output, "speakable", "") else None)
        if reason:
            ledger.guardrail_trips.append({"guardrail": "rafii_truthful_answer", "reason": reason})
        return GuardrailFunctionOutput(output_info={"reason": reason}, tripwire_triggered=bool(reason))

    return truthful


def input_guardrail():
    """Defense in depth: a request for a forbidden effect never reaches the model (the front door already refuses it)."""
    from agents import GuardrailFunctionOutput, input_guardrail as decorate

    @decorate(name="rafii_forbidden_effects", run_in_parallel=False)
    async def forbidden(context, _agent, raw_input):
        from ..site_agent import classifier, contracts as site_contracts
        text = raw_input if isinstance(raw_input, str) else _last_user_text(raw_input)
        request = context.context.request_text or text
        reading = classifier.classify(request, site_contracts.page_context(context.context.page_raw or {"route": "/app"}))
        tripped = reading.get("intent") == "forbidden"
        if tripped:
            context.context.ledger.guardrail_trips.append({"guardrail": "rafii_forbidden_effects", "reason": (reading.get("forbidden") or {}).get("category")})
        return GuardrailFunctionOutput(output_info={"intent": reading.get("intent")}, tripwire_triggered=tripped)

    return forbidden


def _last_user_text(items) -> str:
    for item in reversed(items or []):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""
