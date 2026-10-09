"""Lane D — deterministic eligibility and the authorized UI projection (spec §2.2-2.3, §6.1; 02-CONTRACTS §3).

Frozen entry points:
- eligibility(result, request_text, modality, *, flags) -> dict UiTurnHandoffV1 {eligible, slot, reason, journeyIds}
  Pure and deterministic: greetings/plain answers/acknowledgements -> not eligible; compare/table/filter/chart/journey tool
  results -> eligible. Called by service._persist (A seam) and stored as result.ui.
- project_ui_context(cur, auth, verified_result, surface, selection_state) -> dict UiProjection {manifest_id, journey_ids,
  component_group_ids, data_bindings, action_bindings, allowed_context, fallback_text, egress_decision}. Only data refs, counts,
  kinds and opaque ids the Manager already saw; never media bytes, signed URLs, private text or secrets.

Eligibility is a predicate on the finished turn's *structure* plus a small keyword list for explicit UI intents in
English, Traditional and Simplified Chinese. It never calls a model. A turn is eligible only when it is a completed,
metered Manager turn (so the data already reached that cloud processor; a site-agent fallback, a deterministic answer
or a scripted harness run never is), it is not a greeting/acknowledgement, and it touched at least one journey's data
— and then either the person asked for a view ("compare", "table", "chart", "filter", "timeline", …) or the turn
produced something worth working with (a collection read, a proposal waiting for review, a verified change).

The projection is what the restricted Presenter may see (A-DECISIONS D-A17): binding names and their argument schemas,
counts per kind, tool states, rule labels and opaque `{type, id}` references. Titles, excerpts, draft text, voice
samples, memory bodies, Library text, evidence quotes, `createdBy`, provenance and URLs never enter it; values reach the
browser only through bound queries. `fallback_text` is the native answer for the native fallback slot and is never part
of a presenter prompt.
"""
from __future__ import annotations

import json
import os
import re

from . import ui_contracts, ui_domain

# --- journey signals ---------------------------------------------------------------------------------------------------
# Tool (agent ToolSpec name) → journey. Collection reads make a result worth a working view on their own.
TOOL_JOURNEYS = {
    "draft_get": "J01", "draft_create": "J01", "draft_rewrite": "J01", "draft_edit": "J01", "voice_check": "J01", "models_summary": "J01",
    "calendar_range": "J02", "queue_summary": "J02", "job_get": "J02", "schedule_propose": "J02", "reviews_list": "J02", "publishing_summary": "J02",
    "library_search": "J03", "library_read": "J03", "image_list": "J03", "image_analyze": "J03", "workspace_search": "J03",
    "brand_summary": "J04", "voice_profile": "J04", "memory_context": "J04", "memory_summary": "J04", "privacy_egress_state": "J04",
    "campaign_list": "J05", "campaign_get": "J05", "campaign_items": "J05", "campaign_link": "J05", "campaign_unlink": "J05", "campaign_membership": "J05",
    "web_research": "J07", "research_search": "J07", "research_fetch": "J07",
    "automation_list": "J08", "automation_get": "J08", "automation_explain": "J08", "automation_change_propose": "J08", "channels_capabilities": "J08",
    "ui_guide": "J08",
}
COLLECTION_TOOLS = {"calendar_range", "queue_summary", "content_search", "campaign_list", "campaign_get", "campaign_items", "automation_list", "library_search",
                    "image_list", "publishing_summary", "attention_summary", "voice_profile", "brand_summary", "memory_context", "web_research", "research_search",
                    "reviews_list", "channels_capabilities", "workspace_search"}
REF_JOURNEYS = {"draft": "J01", "post": "J01", "job": "J02", "review": "J02", "asset": "J03", "image": "J03", "library_file": "J03", "media": "J03",
                "voice_sample": "J04", "campaign": "J05", "source": "J07", "automation": "J08", "automation_run": "J08", "connection": "J08"}
PROPOSAL_JOURNEYS = {"schedule_draft": "J02", "reschedule_post": "J02", "automation_change": "J08"}
MAX_JOURNEYS = 3
# D-A52: run-history reads. automation_get returns an automation's latest runs and automation_explain reads its stored run
# history; each harvests a single automation reference, so without this a question about several runs was a "single fact"
# although J08's manifest shows run history (automation_history → RunHistory). They count as a collection read only when
# the person asked about runs or history, so a one-run "why didn't it publish?" stays a native answer.
RUN_HISTORY_TOOLS = {"automation_get", "automation_explain"}
_RUN_HISTORY = re.compile(
    r"\bruns\b|\brun\s+history\b|\bhistory\b|\b(?:last|latest|recent|past|previous)\s+(?:\d+\s+|few\s+|couple\s+of\s+)?(?:automation\s+)?(?:runs?|times)\b"
    r"|運行紀錄|运行记录|執行紀錄|执行记录|運行記錄|執行記錄|歷史|历史|最近幾次|最近几次|上幾次|上几次",
    re.I)

# Explicit UI intents (en / zh-Hant / zh-Hans). Word boundaries for Latin words; CJK words are matched as substrings.
_UI_INTENT = re.compile(
    r"\b(?:compare|comparison|side[\s-]by[\s-]side|table|tabulate|spreadsheet|chart|graph|plot|filter|sort(?:ed)?\s+by|timeline|calendar\s+view|week\s+view|"
    r"agenda|dashboard|breakdown|break\s+it\s+down|list\s+(?:all|my|the)|show\s+(?:me\s+)?(?:all|my|the)|matrix|grid|gallery|trend|over\s+time|by\s+platform|"
    r"which\s+(?:one|ones)\s+(?:did|performed|is|are))\b"
    r"|比較|比较|對比|对比|表格|列表|圖表|图表|篩選|筛选|排序|時間線|时间线|時間表|时间表|日程|一覽|一览|清單|清单|列出|趨勢|趋势|畫個圖|画个图|做個表|做个表|逐個|逐个",
    re.I)
_ANALYTICS = re.compile(r"\b(?:analytics|perform(?:ance|ed|ing|s)?|views?|reach|likes?|impressions?|engagement|metrics?|stats|statistics|insights?|growth)\b"
                        r"|表現|表现|數據|数据|瀏覽|浏览|觸及|触及|互動|互动|讚好|点赞|點讚|成效|分析", re.I)
_GREETING = re.compile(r"^\s*(?:hi|hey|hello|yo|hiya|good\s+(?:morning|afternoon|evening|night)|morning|你好|您好|哈囉|哈啰|嗨|早晨|早安|早上好|午安|晚安|喂)"
                       r"[\s!！.,，。~～]*(?:rafii|raffi)?[\s!！.,，。~～]*$", re.I)
_ACK = re.compile(r"^\s*(?:ok(?:ay)?|k|sure|great|cool|nice|perfect|thanks?(?:\s+you)?|thx|ty|got\s+it|noted|sounds\s+good|yes|yep|no|nope|"
                  r"好|好的|好啊|好呀|好嘅|得|得啦|ok啦|收到|知道了|知道|明白|明白了|多謝|多谢|謝謝|谢谢|唔該|唔该|冇問題|没问题|係|是|不用|唔使)[\s!！.,，。~～]*$", re.I)

_NOT = {"eligible": False, "slot": "main", "journeyIds": []}


def is_greeting_or_ack(text: str) -> bool:
    return bool(_GREETING.match(text or "") or _ACK.match(text or ""))


def wants_ui(text: str) -> bool:
    return bool(_UI_INTENT.search(text or ""))


def asks_run_history(text: str) -> bool:
    return bool(_RUN_HISTORY.search(text or ""))


def detect_journeys(result: dict, request_text: str = "", *, scope: str = "workspace") -> list[str]:
    """Journeys the turn touched, in order of first evidence: tools that ran (not blocked), proposals waiting, changed
    entities, references; J06 when the person asked about performance and the turn read publishing/attention data."""
    if scope == "founder":
        return ["J09"] if (result or {}).get("founder") or any(str(a.get("tool") or "").startswith("founder_") for a in (result or {}).get("toolActivity") or []
                                                               if isinstance(a, dict)) else []
    found: list[str] = []

    def add(journey):
        if journey in ui_contracts.CONSUMER_JOURNEYS and journey not in found:
            found.append(journey)

    activity = [a for a in (result or {}).get("toolActivity") or [] if isinstance(a, dict) and a.get("status") in ("verified", "unverified")]
    analytics = bool(_ANALYTICS.search(request_text or ""))
    for item in activity:
        tool = str(item.get("tool") or "")
        if analytics and tool in ("publishing_summary", "attention_summary", "calendar_range"):
            add("J06")
        if tool == "content_search":
            add("J01")
        add(TOOL_JOURNEYS.get(tool))
    for approval in (result or {}).get("pendingApprovals") or []:
        if isinstance(approval, dict):
            add(PROPOSAL_JOURNEYS.get(str(approval.get("type") or "")))
    for changed in (result or {}).get("changedEntities") or []:
        if isinstance(changed, dict):
            add(REF_JOURNEYS.get(str(changed.get("type") or "")))
    for reference in (result or {}).get("references") or []:
        if isinstance(reference, dict):
            add(REF_JOURNEYS.get(str(reference.get("type") or "")))
    if analytics and not found and activity:
        add("J06")
    return found[:MAX_JOURNEYS]


def eligibility(result, request_text, modality, *, flags):  # lane D
    """{eligible, slot, reason, journeyIds}. Deterministic; never raises for odd input (the caller also guards)."""
    result = result if isinstance(result, dict) else {}
    text = request_text if isinstance(request_text, str) else ""
    if not (flags or {}).get("enabled"):
        return {**_NOT, "reason": "disabled"}
    if result.get("composedBy") != "manager":
        return {**_NOT, "reason": "not_manager"}
    if ((result.get("usage") or {}).get("billing")) != "metered":
        return {**_NOT, "reason": "not_metered"}
    if is_greeting_or_ack(text):
        return {**_NOT, "reason": "greeting"}
    journeys = detect_journeys(result, text)
    intent = wants_ui(text)
    if not journeys:
        return {**_NOT, "reason": "plain_answer"}
    if modality == "voice" and not intent:
        # Voice speaks speakableSummary only; a view nobody asked to see would be spend without a viewer.
        return {**_NOT, "reason": "voice", "journeyIds": journeys}
    if intent:
        return {"eligible": True, "slot": "main", "reason": "ui_intent", "journeyIds": journeys}
    activity = [a for a in result.get("toolActivity") or [] if isinstance(a, dict) and a.get("status") in ("verified", "unverified")]
    rich = (any(str(a.get("tool")) in COLLECTION_TOOLS for a in activity) or bool(result.get("pendingApprovals"))
            or any(isinstance(c, dict) and c.get("verified") for c in result.get("changedEntities") or [])
            or len([r for r in result.get("references") or [] if isinstance(r, dict)]) >= 2
            or (asks_run_history(text) and any(str(a.get("tool")) in RUN_HISTORY_TOOLS for a in activity)))
    if rich:
        return {"eligible": True, "slot": "main", "reason": "rich_result", "journeyIds": journeys}
    return {**_NOT, "reason": "single_fact", "journeyIds": journeys}


# --- the projection ----------------------------------------------------------------------------------------------------
_ASSETS = None


def _assets() -> dict:
    """C's generated asset manifest (component groups per journey), when built; {} before it exists."""
    global _ASSETS
    if _ASSETS is None:
        path = os.path.join(os.path.dirname(__file__), "generated", "openui-assets.json")
        try:
            with open(path, encoding="utf-8") as handle:
                _ASSETS = json.load(handle)
        except (OSError, ValueError):
            _ASSETS = {}
    return _ASSETS


def component_groups(journeys: list[str]) -> list[str]:
    spec = _assets().get("journeys") or {}
    groups: list[str] = []
    for journey in journeys:
        for group in (spec.get(journey) or {}).get("groups") or []:
            if isinstance(group, str) and group not in groups:
                groups.append(group)
    return groups


_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _refs(result: dict, selection_state: dict | None) -> list[dict]:
    """Opaque references only: {type, id}. Titles stay out (a campaign title is its private goal text)."""
    out: list[dict] = []

    def add(kind, ident):
        if isinstance(kind, str) and isinstance(ident, str) and _ID.match(ident) and re.match(r"^[a-z_]{2,30}$", kind):
            item = {"type": kind, "id": ident}
            if item not in out:
                out.append(item)

    for reference in result.get("references") or []:
        if isinstance(reference, dict):
            add(reference.get("type"), reference.get("id"))
    for changed in result.get("changedEntities") or []:
        if isinstance(changed, dict):
            add(changed.get("type"), changed.get("id"))
    for approval in result.get("pendingApprovals") or []:
        if isinstance(approval, dict):
            add("proposal", approval.get("proposalId"))
    for asset in result.get("generatedAssets") or []:
        if isinstance(asset, dict):
            add("asset", asset.get("assetId") or asset.get("id"))
    for reference in (selection_state or {}).get("references") or []:
        if isinstance(reference, dict):
            add(reference.get("type"), reference.get("id"))
    return out[:60]


def _suggested_inputs(journeys: list[str], refs: list[dict]) -> list[dict]:
    """Starting arguments for bindings from the turn's own references (ids only); the presenter may use or ignore them."""
    by_type: dict[str, list[str]] = {}
    for reference in refs:
        by_type.setdefault(reference["type"], []).append(reference["id"])
    out = []
    drafts = by_type.get("draft") or by_type.get("post") or []
    if "J01" in journeys and drafts:
        out.append({"binding": "drafts_list", "inputs": {"ids": drafts[:10]}})
        out.append({"binding": "draft_read", "inputs": {"draftId": drafts[0]}})
    if "J02" in journeys and by_type.get("job"):
        out.append({"binding": "job_detail", "inputs": {"jobId": by_type["job"][0]}})
    if "J05" in journeys and by_type.get("campaign"):
        out.append({"binding": "campaign_detail", "inputs": {"campaignId": by_type["campaign"][0]}})
    if "J08" in journeys and by_type.get("automation"):
        out.append({"binding": "automation_detail", "inputs": {"automationId": by_type["automation"][0]}})
        out.append({"binding": "automation_history", "inputs": {"automationId": by_type["automation"][0]}})
    assets = [i for i in by_type.get("asset") or [] if re.match(r"^[0-9a-f]{32}$", i)]
    if "J03" in journeys and assets:
        out.append({"binding": "library_item", "inputs": {"assetId": assets[0]}})
    return [s for s in out if s["binding"] in ui_domain.QUERIES][:12]


def _counts(result: dict, refs: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for reference in refs:
        counts[reference["type"]] = counts.get(reference["type"], 0) + 1
    return {"references": counts, "pendingApprovals": len(result.get("pendingApprovals") or []),
            "changed": len(result.get("changedEntities") or []), "generatedAssets": len(result.get("generatedAssets") or []),
            "warnings": len(result.get("warnings") or [])}


def _tool_states(result: dict) -> list[dict]:
    return [{"tool": str(a.get("tool"))[:64], "status": str(a.get("status"))[:16], "effect": str(a.get("effect"))[:24]}
            for a in result.get("toolActivity") or [] if isinstance(a, dict)][:40]


def egress_decision(result: dict, *, scope: str = "workspace") -> dict:
    """The presenter may only use the cloud processor the parent turn already used, and only receives the projection."""
    usage = result.get("usage") or {}
    metered = usage.get("billing") == "metered" and result.get("composedBy") == "manager"
    if scope == "founder":
        metered = bool(result.get("founder")) or metered
    route = next((r for r in result.get("routes") or [] if isinstance(r, dict) and r.get("agent") in ("rafii_manager", "rafii_founder_manager")), None) \
        or next((r for r in result.get("routes") or [] if isinstance(r, dict)), {})
    return {"allowed": bool(metered), "provider": route.get("provider") if metered else None, "processorModel": usage.get("route"),
            "reason": "parent_turn_processor" if metered else "parent_not_metered",
            "inputs": "binding schemas, counts, kinds, states, rule labels and opaque references only", "privateText": False}


def project_ui_context(cur, auth, verified_result, surface, selection_state, *, flags=None):  # lane D
    """The authorized projection of a completed turn for one artifact (see module docstring). It also carries the
    server manifest (`manifest`, never sent to a model or browser as is) built from the same journeys for this member."""
    from . import ui_capabilities
    result = verified_result if isinstance(verified_result, dict) else {}
    scope = getattr(auth, "scope", None) or "workspace"
    if surface not in ui_contracts.UI_SURFACES or (surface == "founder") != (scope == "founder"):
        surface = "founder" if scope == "founder" else "chat"
    handoff = result.get("ui") if isinstance(result.get("ui"), dict) else {}
    journeys = [j for j in handoff.get("journeyIds") or [] if j in (ui_contracts.FOUNDER_JOURNEYS if scope == "founder" else ui_contracts.CONSUMER_JOURNEYS)]
    if not journeys:
        journeys = detect_journeys(result, "", scope=scope)
    refs = _refs(result, selection_state if isinstance(selection_state, dict) else None)
    groups = component_groups(journeys)
    projection = {"journey_ids": journeys, "component_group_ids": groups, "egress_decision": egress_decision(result, scope=scope),
                  "allowed_context": {"refs": refs, "counts": _counts(result, refs), "toolStates": _tool_states(result), "language": result.get("language") or "en",
                                      "surface": surface, "suggestedInputs": _suggested_inputs(journeys, refs),
                                      "selection": [r for r in refs if r in ((selection_state or {}).get("references") or [])][:12] if isinstance(selection_state, dict) else [],
                                      "ruleLabels": ["unknown is not zero", "prepared is not applied", "published only when verified"]},
                  "fallback_text": str(result.get("answerText") or "")[:12000]}
    manifest = ui_capabilities.build_manifest(cur, auth, projection, scope=scope, flags=flags)
    projection.update({"manifest_id": manifest["manifestId"], "manifest": manifest,
                       "data_bindings": [{"name": q["name"], "description": q["description"], "argsSchema": q["argsSchema"], "refreshMinSeconds": q["refreshMinSeconds"],
                                          "pageSize": q["pageSize"], "dataShape": q.get("dataShape") or ui_domain.data_shape(q["name"]),
                                          "journey": ui_domain.QUERIES[q["name"]].journey} for q in manifest["queries"]],
                       "action_bindings": [{"actionId": a["actionId"], "label": a["label"], "effect": a["effect"], "requiresConfirmation": a["requiresConfirmation"],
                                            "inputSchema": a["inputSchema"], "journey": ui_domain.ACTIONS[a["actionId"]].journey} for a in manifest["actions"]]})
    return projection


def presenter_view(projection: dict) -> dict:
    """Exactly what B may put in a presenter prompt: no fallback text, no server-only manifest metadata."""
    return {"journeyIds": list(projection.get("journey_ids") or []), "componentGroups": list(projection.get("component_group_ids") or []),
            "dataBindings": list(projection.get("data_bindings") or []), "actionBindings": list(projection.get("action_bindings") or []),
            "context": {k: v for k, v in (projection.get("allowed_context") or {}).items() if k in ("refs", "counts", "toolStates", "language", "surface",
                                                                                                  "suggestedInputs", "selection", "ruleLabels")}}
