"""Adaptive UI Planner (rafii-ui-plan/1): which response form fits a finished Manager turn. Default OFF.

Frozen entry point:
- plan(result, request_text, modality, *, flags, scope="workspace", context=None) -> dict UiPlanV1
  {version, form, eligible, reason, journeyIds, baseline: {eligible, reason}, delta, interactions: {local, reads, actions},
   disclosure: {evidenceRefs, unavailableTools, unknownIsNotZero, asOfRequired}}

The planner wraps ui_projection.eligibility (the deterministic baseline) and never widens its safety vetoes: a turn the
baseline refuses because GenUI is off, the turn was not a metered Manager turn, it carries YouTube provider context, it is
a greeting/acknowledgement, it was voice without a view request, or it touched no journey's data stays plain text here
too. Inside that envelope it does three things the baseline cannot:
- picks a response *form* from FORMS (comparison, chart, table, timeline, cards, calendar, approval, recovery — or text);
- declines expensive UI a concise answer serves better: the person asked for a short or text-only answer ("just tell me",
  "no table", "簡單講"), or asked a count/yes-no question and no view;
- adds a view the baseline misses, only from a *verified* read in workspace scope and never in voice: a failure diagnosis
  over automation/job reads (J08/J02 → recovery), an attention read (J02 → cards), and a refinement of the view the person
  is looking at (uiContext present → keep the view).

Like the baseline it never calls a model and never sees private text: the plan holds enum values, journey ids, tool names
and counts only. Interactions are declared from the fixed INTERACTIONS table; they name *classes* the renderer already
enforces (local state, bound reads, ActionButton through the native approval path) and grant nothing by themselves. Business
actions are declared only when the GenUI actions flag is on.
"""
from __future__ import annotations

import re

from . import ui_contracts, ui_projection

VERSION = "rafii-ui-plan/1"
FORMS = ("text", "comparison", "chart", "table", "timeline", "cards", "calendar", "approval", "recovery")
# The baseline reasons the planner may never turn into a view (hard safety and spend vetoes).
HARD_VETOES = frozenset({"youtube_context", "disabled", "not_manager", "not_metered", "greeting", "voice"})

# Interaction classes per form. local: display state only, no model call, no business write. reads: bound, scoped queries.
# actions: typed proposals that render only through Rafii's ActionButton and the native approval/step-up/idempotency path.
INTERACTIONS = {
    "text": {"local": (), "reads": (), "actions": ()},
    "comparison": {"local": ("platform_toggle", "period_select", "metric_switch"), "reads": ("refresh",), "actions": ("draft_next_step",)},
    "chart": {"local": ("period_select", "metric_switch", "series_toggle"), "reads": ("refresh",), "actions": ()},
    "table": {"local": ("sort", "filter", "select_rows"), "reads": ("refresh", "next_page"), "actions": ()},
    "timeline": {"local": ("expand_item", "status_filter"), "reads": ("refresh", "older_runs"), "actions": ()},
    "cards": {"local": ("status_filter", "select_items", "expand_item"), "reads": ("refresh", "next_page"), "actions": ("draft_from_selection",)},
    "calendar": {"local": ("week_navigate", "platform_filter", "select_slot"), "reads": ("refresh",), "actions": ("review_proposal",)},
    "approval": {"local": ("expand_item",), "reads": ("refresh",), "actions": ("review_proposal",)},
    "recovery": {"local": ("expand_item",), "reads": ("refresh",), "actions": ("propose_retry",)},
}
DATA_FORMS = frozenset({"comparison", "chart", "table", "timeline", "cards", "calendar"})

_DECLINE_UI = re.compile(
    r"\bjust\s+(?:tell|say|give)\b|\bin\s+(?:one|a|1)\s+(?:sentence|line|word)\b(?!\s*(?:chart|graph|plot))|\bbriefly\b|\bquick\s+answer\b|\b(?:text|plain\s+text)\s+only\b"
    r"|\b(?:no|without(?:\s+a)?|don'?t\s+(?:need|want)(?:\s+a)?)\s+(?:tables?|charts?|graphs?|views?|widgets?|dashboards?)\b"
    r"|簡單講|簡單說|简单说|简单讲|一句(?:話|话)?(?:講|讲|說|说|總結|总结|概括|回答)|(?:唔使|唔駛|唔洗|不用|不要|無需|无需)[^。？！,，]{0,4}(?:表|圖|图)",
    re.I)
_COUNT_QUESTION = re.compile(
    r"^\s*(?:how\s+(?:many|much)|when\s+(?:is|does|will|did)|what\s+time|is\s+(?:my|the|there)|are\s+there|does\s+(?:my|the))\b"
    r"|^\s*(?:幾多|几多|多少|幾時|几时|什麼時候|什么时候|有冇|有沒有|有没有)", re.I)
# "each platform", "per post", "by channel": a count over several things is a breakdown, not a single number.
_BREAKDOWN = re.compile(r"\b(?:each|every|per|by\s+(?:platform|channel|post|week|day|month))\b|各個|各个|每個|每个|逐個|逐个|分別|分别", re.I)
# A view the person asked for in words the baseline's keyword list does not cover ("show them on a calendar").
_VIEW_REQUEST = re.compile(
    r"\b(?:show|display|put|lay)\b[^.?!。？！]{0,30}\b(?:calendar|table|chart|graph|cards?|timeline|view)\b|\bon\s+a\s+calendar\b"
    r"|(?:日曆|日历|月曆|月历)(?:顯示|显示|睇|看)?", re.I)
_DIAGNOSIS = re.compile(
    r"\bfail(?:ed|s|ing|ure)?\b|\berrors?\b|\bwent\s+wrong\b|\bbroke(?:n)?\b|\bstuck\b|\bpaused\b"
    r"|\bwhy\b[^.?!]{0,60}(?:\bnot\b|n't\b|\bstop|\bpaus|\bskip|\bmiss|\blate\b|\bblock)"
    r"|\bdid(?:n'?t|\s+not)\s+(?:publish|post|run|go\s+out|send|work)"
    r"|失敗|失败|出錯|出错|唔work|(?:點解|点解|為什麼|为什么|為何|为何)[^。？！]{0,12}(?:冇|唔|未|停|沒|没|不)", re.I)
_ATTENTION = re.compile(r"\battention\b|\bfollow[\s-]?up\b|\bneeds?\s+(?:fixing|action|review)\b|跟進|跟进|要處理|要处理|需要處理|需要处理", re.I)
_PLANNING = re.compile(r"\bplan\b|\bplanning\b|\bnext\s+week\b|\bcontent\s+calendar\b|規劃|规划|計劃|计划|下星期|下週|下周|下個禮拜|下个礼拜", re.I)
_COMPARE = re.compile(r"\bcompare|comparison|\bvs\.?\b|\bversus\b|\bagainst\b|side[\s-]by[\s-]side|比較|比较|對比|对比", re.I)
_TREND = re.compile(r"\btrend|over\s+time|\bchart\b|\bgraph\b|\bplot\b|趨勢|趋势|圖表|图表|走勢|走势", re.I)
_TABLE = re.compile(r"\btable\b|\bsort|\bfilter|\blist\b|\bspreadsheet\b|表格|排序|篩選|筛选|列出|清單|清单|列表", re.I)
_PLATFORMS = re.compile(r"\b(?:instagram|ig|tiktok|youtube|facebook|threads|linkedin|twitter|bluesky|mastodon|pinterest|telegram)\b"
                        r"|小紅書|小红书|微博|抖音", re.I)
_REFINEMENT = re.compile(r"^\s*(?:only|just)\b(?!\s+(?:tell|say|give))|^\s*(?:what|how)\s+about\b|\binstead\b"
                         r"|^\s*(?:只|淨係|净系|仲有|還有|还有)|改為|改为|換成|换成", re.I)

DIAGNOSIS_TOOLS = {"automation_get": "J08", "automation_explain": "J08", "job_get": "J02"}
ATTENTION_TOOLS = {"attention_summary": "J02"}


def _verified(result: dict) -> list[dict]:
    activity = result.get("toolActivity") if isinstance(result.get("toolActivity"), list) else []
    return [a for a in activity if isinstance(a, dict) and a.get("status") == "verified"]


def _unavailable(result: dict) -> list[str]:
    activity = result.get("toolActivity") if isinstance(result.get("toolActivity"), list) else []
    return list(dict.fromkeys(str(a.get("tool"))[:64] for a in activity if isinstance(a, dict) and a.get("status") in ("blocked", "failed")))[:12]


def _with_journey(journeys: list[str], journey: str) -> list[str]:
    return ([journey] + [j for j in journeys if j != journey])[:ui_projection.MAX_JOURNEYS]


def _form(result: dict, text: str, journeys: list[str], scope: str) -> str:
    """The form for an eligible turn, by fixed precedence (most specific signal first)."""
    tools = {str(a.get("tool")) for a in _verified(result)}
    if scope == "founder":
        return "table"
    if _PLANNING.search(text) and "J02" in journeys:
        return "calendar"
    if result.get("pendingApprovals"):
        return "approval"
    if _DIAGNOSIS.search(text) and tools & set(DIAGNOSIS_TOOLS):
        return "recovery"
    if ui_projection.asks_run_history(text) and len(ui_projection.runs_read(_verified(result))) >= ui_projection.MIN_RUNS_FOR_HISTORY:
        return "timeline"
    analytics = "J06" in journeys or bool(ui_projection._ANALYTICS.search(text)) or "publishing_summary" in tools
    if analytics and (_COMPARE.search(text) or len({m.group(0).lower() for m in _PLATFORMS.finditer(text)}) >= 2):
        return "comparison"
    if analytics and _TREND.search(text):
        return "chart"
    if _ATTENTION.search(text) or "attention_summary" in tools:
        return "cards"
    if _TABLE.search(text):
        return "table"
    if "J03" in journeys or "J07" in journeys:
        return "cards"
    if "J02" in journeys and tools & {"calendar_range", "schedule_propose"}:
        return "calendar"
    return "table"


def plan(result, request_text, modality, *, flags, scope="workspace", context=None) -> dict:
    """UiPlanV1 (see module docstring). Deterministic; never raises for odd input."""
    result = result if isinstance(result, dict) else {}
    text = request_text if isinstance(request_text, str) else ""
    context = context if isinstance(context, dict) else {}
    flags = flags if isinstance(flags, dict) else {}
    try:
        base = ui_projection.eligibility(result, text, modality, flags=flags, scope=scope)
    except Exception:  # noqa: BLE001 — the baseline is defensive too; a failure is simply "not eligible"
        base = {"eligible": False, "reason": "not_eligible", "journeyIds": []}
    journeys = [j for j in base.get("journeyIds") or [] if j in ui_contracts.JOURNEYS]
    eligible, reason = bool(base.get("eligible")), str(base.get("reason") or "")
    verified = {str(a.get("tool")) for a in _verified(result)}
    view_asked = ui_projection.wants_ui(text) or bool(_VIEW_REQUEST.search(text))

    if reason in HARD_VETOES or scope not in ("workspace", "founder"):
        eligible = False
    elif _DECLINE_UI.search(text):
        eligible, reason = False, "declined_ui"
    elif _COUNT_QUESTION.search(text) and not view_asked and not _BREAKDOWN.search(text):
        eligible, reason = False, "concise_answer" if eligible else reason
    elif not eligible and scope == "workspace" and modality != "voice":
        # Upgrades: only from verified reads, workspace scope, text modality.
        if _DIAGNOSIS.search(text) and verified & set(DIAGNOSIS_TOOLS):
            journey = next(DIAGNOSIS_TOOLS[t] for t in DIAGNOSIS_TOOLS if t in verified)
            eligible, reason, journeys = True, "diagnosis", _with_journey(journeys, journey)
        elif verified & set(ATTENTION_TOOLS) and _ATTENTION.search(text):
            eligible, reason, journeys = True, "attention", _with_journey(journeys, "J02")
        elif context.get("followsArtifact") and journeys and _REFINEMENT.search(text):
            eligible, reason = True, "follow_up"
        elif not eligible and view_asked and journeys:
            eligible, reason = True, "ui_intent"
    if eligible and not journeys:
        eligible, reason = False, "plain_answer"

    form = _form(result, text, journeys, scope) if eligible else "text"
    if form == "recovery":
        journeys = _with_journey(journeys, next(DIAGNOSIS_TOOLS[t] for t in DIAGNOSIS_TOOLS if t in verified))
    table = INTERACTIONS[form]
    delta = "same" if eligible == bool(base.get("eligible")) else ("upgrade" if eligible else "downgrade")
    refs = [r for r in result.get("references") or [] if isinstance(r, dict)] if isinstance(result.get("references"), list) else []
    return {"version": VERSION, "form": form, "eligible": eligible, "reason": reason[:64], "journeyIds": list(journeys),
            "baseline": {"eligible": bool(base.get("eligible")), "reason": str(base.get("reason") or "")[:64]}, "delta": delta,
            "interactions": {"local": list(table["local"]), "reads": list(table["reads"]),
                             "actions": list(table["actions"]) if flags.get("actions") else []},
            "disclosure": {"evidenceRefs": len(refs), "unavailableTools": _unavailable(result), "unknownIsNotZero": True,
                           "asOfRequired": form in DATA_FORMS}}
