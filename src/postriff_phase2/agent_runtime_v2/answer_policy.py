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
# English first person ("I've", "I’ve", "we have", "Rafii has") with the adverbs a claim is usually dressed in.
_EN_I = r"\b(?:i(?:['’]ve|\s+have)?|we(?:['’]ve|\s+have)?|rafii\s+(?:has\s+)?)\s*(?:(?:just|now|already|also|then|successfully|gone\s+ahead\s+and|went\s+ahead\s+and)\s+){0,2}"
# Chinese (Cantonese in Traditional, Mandarin in Simplified or Traditional) often drops the subject, so a claim is first person
# (我/我哋/我們/Rafii) or "for you" (幫你/帮你/為你…) after a completion marker (已經/已经/成功…), and 將/把 may move the object
# before the verb ("我已經將篇帖發佈咗"). The object gap never crosses punctuation or a negation ("保存为草稿而没有发布").
_ZH_I = r"(?:我哋|我們|我们|我|rafii(?=\s*[㐀-鿿]))"
_ZH_DONE = r"(?:已經|已经|已|成功|啱啱|剛剛|刚刚)"
_ZH_FOR = r"(?:幫你|帮你|為你|为你|替你|同你)"
_ZH_OBJ = r"(?:(?:將|将|把)[^。，、,.!?！？；;：:\n不冇沒没未唔無无別别]{0,12}?)?"
# Code-switching puts English verbs in Chinese sentences ("我已經幫你 publish 咗"); CJK letters are word characters, so the
# English verbs end at a lookahead rather than \b. "post", "schedule" and "reply" are also nouns here ("將個 post 準備好"), so
# they count as verbs only before a completion or direction word ("post 咗", "schedule 喺星期六").
_ZH_FORBIDDEN = (r"發佈|發布|发布|出咗|發咗|发咗|發送|发送|排程|排好|排期|批准|刪除|删除|斷開|断开|付款|購買|购买|回覆|回复"
                 r"|(?:publish(?:ed)?|posted|scheduled|approv(?:e|ed)|send|sent|delet(?:e|ed)|replied|disconnect(?:ed)?|buy|bought)(?![a-z])"
                 r"|(?:post|schedule|reply)(?=\s*(?:咗|了|好|埋|上|喺|在|到))")
_ZH_PREPARED = r"準備好|准备好|預備好|预备好|擬好|拟好|寫好|写好|(?:prepare|prepared|draft|drafted|set\s*up)\s*好"
_ZH_CHANGED = (r"建立|創建|创建|生成|整咗|整好|加咗|加入|連結|连结|鏈接|链接|連接|连接|儲存|储存|保存|更新|修改|改咗|改好|改短|縮短|缩短|"
               r"編輯|编辑|重寫|重写|製作|制作"
               r"|(?:creat(?:e|ed)|generat(?:e|ed)|sav(?:e|ed)|link(?:ed)?|add(?:ed)?|edit(?:ed)?|updat(?:e|ed)|rewr(?:ite|ote)|shorten(?:ed)?)(?![a-z])")
_ZH_COMPLETE = r"(?:咗|了|好|完)"
# First-person claims of effects no Rafii tool can have (or, for "scheduled", that only a person's approval can have).
_NEVER = re.compile(
    _EN_I + r"(?:published|posted|approved|sent|replied|deleted|disconnected|bought|purchased|scheduled)\b"
    rf"|{_ZH_I}\s*{_ZH_DONE}\s*{_ZH_FOR}?\s*{_ZH_OBJ}(?:{_ZH_FORBIDDEN})"
    rf"|{_ZH_DONE}\s*{_ZH_FOR}\s*{_ZH_OBJ}(?:{_ZH_FORBIDDEN})", re.I)
# Without a completion marker ("我幫你發佈咗", "幫你發佈咗") it is a claim unless its clause negates, offers or asks
# ("我唔可以幫你發佈咗", "你想我幫你排程嗎？", "我發佈前會先問你").
_ZH_UNMARKED = re.compile(rf"{_ZH_I}\s*{_ZH_FOR}?\s*{_ZH_OBJ}(?:{_ZH_FORBIDDEN})|{_ZH_FOR}\s*{_ZH_OBJ}(?:{_ZH_FORBIDDEN})\s*{_ZH_COMPLETE}", re.I)
_ZH_NOT_A_CLAIM = re.compile(r"不|冇|沒|没|未|唔|無|无|別|别|能|可以|會|会|要|想|應該|应该|如果|若")
# Passive claims that a pending proposal already took effect ("your post has been scheduled").
_PASSIVE_EFFECT = re.compile(
    r"\b(?:has|have)\s+been\s+(?:scheduled|published|posted|approved|applied|sent)\b|\b(?:is|are)\s+now\s+(?:scheduled|published|live|approved)\b"
    r"|已(?:經|经)?\s*(?:排程|排好|排期|發佈|發布|发布|批准|套用|應用|应用|發送|发送|(?:schedul(?:e|ed)|publish(?:ed)?|approv(?:e|ed)|appl(?:y|ied))(?![a-z]))", re.I)
# "I've prepared / proposed / set up …" claims a proposal (or a verified change) exists this turn.
_PREPARED = re.compile(_EN_I + r"(?:prepared|proposed|set\s+up|queued|lined\s+up|drafted|written|wrote)\b"
                       rf"|{_ZH_I}\s*{_ZH_DONE}?\s*{_ZH_FOR}?\s*(?:{_ZH_PREPARED})", re.I)
_DID = re.compile(
    _EN_I + r"(?:created|linked|added|attached|generated|saved|changed|updated|edited|rewrote|rewritten|shortened|made|removed|moved)\b"
    rf"|{_ZH_I}\s*{_ZH_FOR}?\s*{_ZH_OBJ}(?:{_ZH_CHANGED})\s*{_ZH_COMPLETE}"
    rf"|{_ZH_DONE}\s*{_ZH_FOR}?\s*{_ZH_OBJ}(?:{_ZH_CHANGED})", re.I)


def _claims_forbidden(text: str) -> bool:
    if _NEVER.search(text):
        return True
    for match in _ZH_UNMARKED.finditer(text):
        start = max(text.rfind(p, 0, match.start()) for p in "。，,.!?！？；;\n")
        end = min([i for i in (text.find(p, match.end()) for p in "。，,.!?！？；;\n") if i >= 0] or [len(text)])
        tail = text[match.end():end + 1]
        if not _ZH_NOT_A_CLAIM.search(text[start + 1:match.start()]) and not re.search(r"[嗎吗呢未?？]|^\s*(?:之)?前", tail):
            return True
    return False


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
    if _claims_forbidden(answer):
        return "claims_forbidden_effect"
    if ledger.proposals and _PASSIVE_EFFECT.search(answer):
        return "claims_pending_proposal_applied"
    verified = [c for c in ledger.changed if c.get("verified")] + [a for a in ledger.assets if a.get("verified")]
    if _DID.search(answer) and not verified:
        return "claims_unverified_change"
    if _PREPARED.search(answer) and not ledger.proposals and not verified:
        return "claims_missing_proposal"
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
