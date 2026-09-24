"""Procedures: which tools answer which kind of question (site agent §8.3, §8.4).

A procedure is a small, fixed recipe: the tools it reads, in order, with arguments taken from the classification and
the server-validated page context. Structured procedures (diagnosis) always read live state before any help text,
because live state outranks documentation (§6.3). The model never adds a write tool to a recipe.
"""
from __future__ import annotations

from . import routes, timeframe

CATALOG = {
    "answer_product_question": "Answer a question about Rafii from its help.",
    "explain_current_page": "Explain the page the person is on, with its live state.",
    "navigate_to_feature": "Point to, or open, the page where something is done.",
    "diagnose_run": "Explain one post's publishing state from its record.",
    "diagnose_queue": "Find why a post did not go out when no post is selected.",
    "diagnose_automation": "Explain an automation's run from its stored history.",
    "diagnose_connection": "Explain why an account cannot publish or needs reconnecting.",
    "diagnose_model": "Explain why a writer or model is unavailable.",
    "explain_capability": "Explain Direct, Assisted, Bridge and Unsupported with the live level.",
    "review_draft": "Check a draft against limits, unknowns and warnings.",
    "memory_explanation": "Say what Rafii remembers and who decides.",
    "privacy_and_egress": "Say what may leave Rafii and what stays.",
    "billing_and_credits": "Say what is left of the plan and why a paid step stopped.",
    "models_and_writers": "Say which writers are available and how they are paid.",
    "support_escalation": "Prepare a content-free support handoff.",
    "modify_automation": "Propose a change to an automation for a person to apply.",
    "policy_block": "Explain why Rafii will not do this from chat and where it is done.",
    "entity_status": "Say the status of the selected item and what it still needs.",
    "attention_overview": "List what needs attention: stored facts, then derived observations.",
    "review_queue": "List what waits for approval or review, and what was returned and why.",
    "publishing_state": "Say what was verified as published, what is scheduled, failed, uncertain or held.",
    "campaign_overview": "Describe a campaign from its brief, automations, drafts, runs and derived gaps.",
    "calendar_overview": "List what is scheduled in a range, with empty days and posts close together.",
    "brand_guidance": "Quote the stored Brand Brain; check a draft against its stated rules.",
    "voice_explanation": "Quote the approved voice profile and the preferences learned per platform.",
    "draft_listing": "List recent and unfinished drafts with what each still needs.",
    "workspace_search": "Find matching drafts, sources, campaigns, automations and posts.",
    "schedule_draft": "Propose preparing an exact review of a draft at a time; approval stays a separate step.",
    "greeting": "Say hello and what Rafii can do here.",
}

PAGE_READS = {
    "queue": ("queue.summary", {}), "calendar": ("queue.summary", {}), "channels": ("channels.capabilities", {}),
    "automations": ("automation.list", {}), "memory": ("memory.summary", {}), "brand": ("memory.summary", {}),
    "billing": ("entitlements.summary", {}), "models": ("models.summary", {}), "home": ("workspace.summary", {}),
    "overview": ("workspace.summary", {}), "agent": ("workspace.summary", {}), "ideas": ("workspace.summary", {}),
}
FORBIDDEN_HELP = {"queue": ("approvals chat is not approval", ["help_approvals"]), "inbox": ("replies approve one at a time", ["help_inbox"]),
                  "channels": ("disconnect connect account tokens", ["help_channels"]), "billing": ("billing plan allowance", ["help_billing"]),
                  "privacy": ("delete account export", ["help_account"]), "memory": ("cloud memory owner switches", ["help_privacy_models", "help_memory"]),
                  "roles": ("roles permissions editor viewer", ["help_roles_members"])}
RUNBOOKS = {"diagnose_queue": ["help_ts_awaiting_approval", "help_ts_held_job", "help_ts_uncertain_result", "help_queue"],
            "diagnose_run": ["help_ts_awaiting_approval", "help_ts_held_job", "help_ts_uncertain_result", "help_queue"],
            "diagnose_connection": ["help_ts_expired_connection", "help_capability_levels", "help_channels"],
            "diagnose_model": ["help_ts_writer_unavailable", "help_privacy_models"], "diagnose_automation": ["help_ts_automation_not_publishing", "help_automations"],
            "explain_capability": ["help_capability_levels"], "review_draft": ["help_queue", "help_approvals"], "memory_explanation": ["help_memory", "help_privacy_models"],
            "privacy_and_egress": ["help_privacy_models", "help_ideas_sources"], "billing_and_credits": ["help_billing"],
            "models_and_writers": ["help_privacy_models", "help_ts_writer_unavailable"], "support_escalation": ["help_agent_guide"]}
ALIAS = {"queue_drafts": ("queue", {"view": "drafts"})}


def target(classification: dict) -> tuple[str | None, dict]:
    """The page the message points at, from the words it uses (never from the model)."""
    for route_id in classification["entities"]["routes"]:
        if route_id in ALIAS:
            return ALIAS[route_id]
        if routes.by_id(route_id):
            return route_id, {}
    return None, {}


def select(classification: dict, page: dict, text: str, *, automation_count: int = 0, now: float | None = None, zone: str | None = None) -> dict:
    """{"procedures": [...], "tools": [(id, args)], "navigate": (routeId, query) | None}."""
    intent = classification["intent"]
    entity = classification["entities"].get("focus") or page.get("selectedEntity") or {}
    frame = timeframe.parse(text, now, zone) if now is not None else None
    family = page.get("routeFamily")
    query = text[:400]
    tools: list[tuple[str, dict]] = []
    navigate = None
    procedures: list[str] = []

    def add(tool_id, args=None):
        if len(tools) < 6 and (tool_id, args or {}) not in tools:
            tools.append((tool_id, args or {}))

    if intent == "greeting":
        procedures.append("greeting")
        if family in PAGE_READS:
            add(*PAGE_READS[family])
    elif intent == "forbidden":
        procedures.append("policy_block")
        route_id = classification["forbidden"]["routeId"]
        add("route.describe", {"routeId": route_id})
        help_query, documents = FORBIDDEN_HELP.get(route_id, (query, []))
        add("help.search", {"query": help_query, "documents": documents})
        navigate = (route_id, {})
        if route_id == "queue" and entity.get("type") in ("job", "review"):
            navigate = ("queue", {"job": entity["id"]})
    elif intent == "page":
        procedures.append("explain_current_page")
        if page.get("routeId"):
            add("route.describe", {"routeId": page["routeId"]})
            if family in PAGE_READS:
                add(*PAGE_READS[family])
            add("help.search", {"query": f"{page.get('title') or ''} {query}".strip()[:400], "routeFamily": family or "",
                                "documents": list((routes.by_id(page["routeId"]) or {}).get("helpDocs") or [])})
        else:
            add("help.search", {"query": query})
    elif intent == "navigate":
        procedures.append("navigate_to_feature")
        route_id, extra = target(classification)
        if route_id:
            navigate = (route_id, extra)
            add("route.describe", {"routeId": route_id})
        add("help.search", {"query": query, "documents": list((routes.by_id(route_id) or {}).get("helpDocs") or []) if route_id else []})
    elif intent == "diagnose":
        if classification["entities"].get("automation") == "explain":
            procedures.append("diagnose_automation")
            args = {"question": query}
            if entity.get("type") == "automation":
                args["automationId"] = entity["id"]
            add("automation.explain", args)
            add("help.search", {"query": "automation did not publish " + query})
        elif entity.get("type") in ("job", "review"):
            procedures.append("diagnose_run")
            add("job.get", {"jobId": entity["id"]})
            add("help.search", {"query": query})
        elif entity.get("type") == "draft":
            procedures.append("review_draft")
            add("draft.get", {"draftId": entity["id"]})
            add("help.search", {"query": query})
        elif classification["entities"]["platforms"] or family == "channels" or any(r == "channels" for r in classification["entities"]["routes"]):
            procedures.append("diagnose_connection")
            platforms = classification["entities"]["platforms"]
            add("channels.capabilities", {"platform": platforms[0]} if platforms else {})
            add("help.search", {"query": query})
        elif family == "models" or any(r == "models" for r in classification["entities"]["routes"]) or "model" in text.lower() or "writer" in text.lower():
            procedures.append("diagnose_model")
            add("models.summary")
            add("help.search", {"query": "writer model unavailable " + query})
        else:
            procedures.append("diagnose_queue")
            add("queue.summary")
            if automation_count:
                add("automation.explain", {"question": query})
            add("help.search", {"query": query})
    elif intent == "capability":
        procedures.append("explain_capability")
        platforms = classification["entities"]["platforms"]
        add("channels.capabilities", {"platform": platforms[0]} if platforms else {})
        add("help.search", {"query": "capability levels " + query})
    elif intent == "review":
        procedures.append("review_draft")
        if entity.get("type") == "draft":
            add("draft.get", {"draftId": entity["id"]})
        add("help.search", {"query": "draft review unknowns warnings schedule"})
    elif intent == "memory":
        procedures.append("memory_explanation")
        add("memory.summary")
        add("help.search", {"query": query})
    elif intent == "privacy":
        procedures.append("privacy_and_egress")
        add("privacy.egress_state")
        add("help.search", {"query": query})
    elif intent == "billing":
        procedures.append("billing_and_credits")
        add("entitlements.summary")
        add("help.search", {"query": query})
    elif intent == "models":
        procedures.append("models_and_writers")
        add("models.summary")
        add("privacy.egress_state")
        add("help.search", {"query": query})
    elif intent == "support":
        procedures.append("support_escalation")
        add("workspace.summary")
        add("help.search", {"query": query})
    elif intent == "edit":
        procedures.append("modify_automation")
        add("automation.list")
    elif intent == "status":
        procedures.append("entity_status")
        if entity.get("type") in ("job", "review", "draft", "automation", "source"):
            add("entity.status", {"type": entity["type"], "id": entity["id"]})
            add("help.search", {"query": query})
        else:
            # Nothing selected: find what the message names; the answer lists matches or says nothing matched.
            add("content.search", {"query": query})
    elif intent == "attention":
        procedures.append("attention_overview")
        add("attention.summary")
    elif intent == "reviews":
        procedures.append("review_queue")
        add("reviews.list")
        add("help.search", {"query": "approval review returned " + query, "documents": ["help_approvals", "help_ts_awaiting_approval"]})
    elif intent == "publishing":
        procedures.append("publishing_state")
        add("publishing.summary", {"start": frame["start"], "end": frame["end"], "label": frame["label"]} if frame else {})
        add("help.search", {"query": "published verified uncertain failed " + query, "documents": ["help_queue", "help_ts_uncertain_result"]})
    elif intent == "campaign":
        procedures.append("campaign_overview")
        if entity.get("type") in ("automation", "campaign"):
            add("campaign.get", {"campaignId": entity["id"]})
        else:
            add("campaign.list", {"query": query})
    elif intent == "calendar":
        procedures.append("calendar_overview")
        args = {"start": frame["start"], "end": frame["end"], "label": frame["label"]} if frame else {}
        if classification["entities"]["platforms"]:
            args["platform"] = classification["entities"]["platforms"][0]
        add("calendar.range", args)
    elif intent == "brand":
        procedures.append("brand_guidance")
        add("brand.summary")
        if entity.get("type") == "draft":
            add("draft.get", {"draftId": entity["id"]})
    elif intent == "voice":
        procedures.append("voice_explanation")
        platforms = classification["entities"]["platforms"]
        add("voice.profile", {"platform": platforms[0]} if len(platforms) == 1 else {})
        if entity.get("type") == "draft":
            add("draft.get", {"draftId": entity["id"]})
    elif intent == "drafts":
        procedures.append("draft_listing")
        add("content.search", {"query": "", "kinds": ["draft"]})
    elif intent == "search":
        procedures.append("workspace_search")
        args = {"query": query}
        if frame:
            args.update(since=frame["start"], until=frame["end"], label=frame["label"])
        if classification["entities"]["platforms"]:
            args["platform"] = classification["entities"]["platforms"][0]
        add("content.search", args)
    else:
        procedures.append("answer_product_question")
        add("help.search", {"query": query})
        route_id, extra = target(classification)
        if route_id:
            add("route.describe", {"routeId": route_id})
    preferred = [doc for name in procedures for doc in RUNBOOKS.get(name, [])]
    if preferred:
        tools = [(tool_id, {**args, "documents": args.get("documents") or preferred}) if tool_id == "help.search" else (tool_id, args) for tool_id, args in tools]
    return {"procedures": procedures, "tools": tools, "navigate": navigate}
