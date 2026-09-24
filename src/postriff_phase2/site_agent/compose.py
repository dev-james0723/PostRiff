"""Grounded answers without a model (site agent §7.6, §10.1, §10.2, §18).

Every answer here is assembled from what the tools actually returned: help passages (cited), live workspace facts
(named as such) and allowlisted links. When the evidence does not answer the question the answer says so. This is
the answer whenever no model may phrase it (preview writer, unavailable or over-budget writer, a viewer, an invalid
model answer), and it is also the source of the facts a model receives.

The panel's own framing sentences are localised (English, Traditional Chinese); help passages are quoted in the
language they are written in.
"""
from __future__ import annotations

import re

from . import compose_reads, contracts, routes

TEXT = {
    "en": {
        "hello": "Hi, I'm Rafii. I can explain this page, find where something is, check why a post didn't go out, write drafts or set up an automation.",
        "unknown": "I couldn't find this in Rafii's help, so I won't guess.",
        "unknown_steps": "You can browse the help articles, or contact support with the details below.",
        "open": "Open {title}",
        "opening": "Opening {title}.",
        "page": "**{title}**: {summary}",
        "no_problem": "I don't see a post that failed, is held or is uncertain, and nothing is waiting for approval.",
        "waiting": "{n} post(s) are waiting for approval. Nothing publishes until someone with the approve permission approves that exact post.",
        "unscheduled": "{n} draft(s) were never scheduled, so they have no publish time yet.",
        "stale": "The page I was given isn't one Rafii knows, so I answered without it.",
        "no_draft": "Open the draft you want me to check (Queue → Drafts), then ask again.",
        "draft_checked": "Here's what stands between this draft and scheduling.",
        "memory": "These are the files Rafii writes from. They are rebuilt from your voice profile, brand context and accepted preferences; I can't change them myself.",
        "privacy": "Here's what may leave Rafii right now.",
        "billing": "Here's what's left on your plan.",
        "models": "These are the writers this deployment offers.",
        "support": "I've put together a content-free summary you can send to support. Nothing is sent until you send it yourself.",
        "no_model": "Answered from Rafii's help and your workspace, without a writer model.",
        "help_quote": "",
        "capability": "Here's what each account can do, as verified now.",
        "forbidden": {
            "credentials_refusal": "I can't show passwords, tokens or keys, and I never read them. Account connections are managed on Channels, and your own API tokens on API & integrations.",
            "destructive_privacy": "I can't delete an account or workspace data from a chat. Only the owner can do that, on Privacy & data, with its own confirmation.",
            "destructive_channels": "I can't disconnect accounts from a chat. You can do it on Channels; approved posts for that account will then be held.",
            "paid": "I can't buy credits or change your plan. You can do that yourself on Usage & plan.",
            "external_representation_inbox": "I don't reply to comments or send messages for you. Replies are written and approved one at a time in the Inbox.",
            "external_representation_queue": "I can't publish or approve anything from a chat. A post goes out only after someone with the approve permission approves that exact post.",
            "setting_memory": "Only an owner can turn cloud memory or web research on or off, on the Memory page. I can't switch them from a chat.",
            "role_roles": "Your role in this workspace can't create drafts or automations. An owner or admin can change your role on Members.",
            "destructive_queue": "I can't delete anything from a chat. Drafts are set aside or deleted in Queue → Drafts, automations on Automations, and sources on Ideas, each with its own confirmation.",
        },
    },
    "zh-Hant": {
        "hello": "你好，我係 Rafii。我可以解釋呢一頁、幫你搵嘢喺邊、查點解一篇 post 冇出到、寫草稿，或者設定自動化。",
        "unknown": "我喺 Rafii 嘅說明入面搵唔到答案，所以唔會亂估。",
        "unknown_steps": "你可以睇下說明文章，或者用下面嘅資料聯絡支援。",
        "open": "打開 {title}",
        "opening": "而家帶你去 {title}。",
        "page": "**{title}**：{summary}",
        "no_problem": "我見唔到有失敗、被暫停（held）或者未確定（uncertain）嘅 post，亦冇嘢等緊批核。",
        "waiting": "有 {n} 篇 post 等緊批核。未有具批核權限嘅人批准嗰篇確切內容之前，乜都唔會發佈。",
        "unscheduled": "有 {n} 份草稿從未排程，所以未有發佈時間。",
        "stale": "你而家嗰一頁 Rafii 唔認得，所以我冇用佢嚟答。",
        "no_draft": "請先打開你想我檢查嘅草稿（佇列 → 草稿），再問一次。",
        "draft_checked": "以下係呢份草稿排程之前要處理嘅嘢。",
        "memory": "呢啲係 Rafii 寫嘢時參考嘅檔案，由你嘅語氣設定、品牌資料同已接受嘅偏好生成；我自己改唔到佢哋。",
        "privacy": "以下係而家可能離開 Rafii 嘅資料。",
        "billing": "以下係你方案仲剩返嘅額度。",
        "models": "以下係呢個部署提供嘅寫作模型。",
        "support": "我整理咗一份唔含內容嘅摘要，你可以自己寄俾支援團隊；你未寄出之前乜都唔會送出。",
        "no_model": "呢個答案直接來自 Rafii 說明同你嘅工作區，冇用寫作模型。",
        "help_quote": "（以下係 Rafii 說明原文）",
        "capability": "以下係每個帳戶而家經驗證嘅能力。",
        "forbidden": {
            "credentials_refusal": "我唔可以顯示密碼、token 或者金鑰，我亦唔會讀取佢哋。帳戶連接喺「Channels」管理，你自己嘅 API token 喺「API & integrations」。",
            "destructive_privacy": "我唔可以喺對話入面刪除帳戶或者工作區資料。只有擁有者可以喺「Privacy & data」做，而且要另外確認。",
            "destructive_channels": "我唔可以喺對話入面斷開帳戶。你可以喺「Channels」自己做；嗰個帳戶已批准嘅 post 會被暫停。",
            "paid": "我唔可以幫你買點數或者改方案。你可以喺「Usage & plan」自己做。",
            "external_representation_inbox": "我唔會幫你回覆留言或者發訊息。回覆要喺「Inbox」逐條寫好再批准。",
            "external_representation_queue": "我唔可以喺對話入面發佈或者批准任何嘢。一篇 post 只會喺具批核權限嘅人批准嗰篇確切內容之後先會發出。",
            "setting_memory": "只有擁有者可以喺「Memory」頁開關雲端記憶或者網上研究，我唔可以喺對話入面改。",
            "role_roles": "你喺呢個工作區嘅角色唔可以建立草稿或者自動化。擁有者或者管理員可以喺「Members」幫你改角色。",
            "destructive_queue": "我唔可以喺對話入面刪除任何嘢。草稿喺「佇列 → 草稿」擱置或者刪除，自動化喺「Automations」，素材喺「Ideas」，每樣都有自己嘅確認步驟。",
        },
    },
}


def t(language: str, key: str, **values) -> str:
    table = TEXT.get(language) or TEXT["en"]
    template = table.get(key) if key in table else TEXT["en"][key]
    return template.format(**values) if values else template


def _sentences(text: str, limit: int = 700) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("。"))
    return cut[: end + 1] if end > limit // 3 else cut.rstrip() + "…"


def citation_objects(passages: list[dict], retrieved_at: str, used=None) -> list[dict]:
    out = []
    for index, passage in enumerate(passages):
        if used is not None and passage["ref"] not in used:
            continue
        out.append({"id": f"cit_{index + 1}", "ref": passage["ref"], "documentId": passage["documentId"], "title": passage["title"],
                    "section": passage["section"], "href": passage["href"], "retrievedAt": retrieved_at, "authority": passage["sourceType"]})
    return out


def facts(results: dict) -> list[dict]:
    """Short, labelled workspace facts (W1…) from tool results, for the model and for 'what Rafii used'."""
    out = []

    def add(tool, text):
        out.append({"ref": f"W{len(out) + 1}", "tool": tool, "text": text})

    for tool_id, result in results.items():
        data = result.get("data") if result.get("ok") else None
        if not data:
            continue
        if tool_id == "workspace.summary":
            c = data["counts"]
            add(tool_id, f"Your role: {data['workspace']['role']}. Drafts not scheduled: {c['draftsUnscheduled']}; reviews waiting for approval: {c['reviewsWaiting']} "
                         f"(expired: {c['reviewsExpired']}); jobs waiting: {c['jobsWaiting']}, in flight: {c['jobsInFlight']}, held: {c['jobsHeld']}, failed: {c['jobsFailed']}, "
                         f"uncertain: {c['jobsUncertain']}, verified: {c['jobsVerified']}; accounts connected: {c['accountsConnected']}; automations active: {c['automationsActive']}, "
                         f"paused: {c['automationsPaused']}, draft: {c['automationsDraft']}.")
        elif tool_id == "channels.capabilities":
            for row in data["accounts"]:
                add(tool_id, f"{row['platform']} account {row['account']}: connection {row['connectionState']}; publish level {row['levels'].get('publish')}; "
                             f"can publish now: {'yes' if row['canPublish'] else 'no'} ({row['publishReason']})" + ("; demo account" if row["demo"] else ""))
            if data.get("unconnected"):
                u = data["unconnected"]
                add(tool_id, f"{u['platform']}: no account connected; can publish: {'yes' if u['canPublish'] else 'no'} ({u['publishReason']})")
        elif tool_id == "queue.summary":
            for item in data["waitingApproval"]:
                add(tool_id, f"A {item['platform']} post for {item['account']} at {item['publishAt']} is waiting for approval" + (" (its review window closed)" if item["expired"] else "") + ".")
            for job in data["attention"]:
                add(tool_id, f"A {job['platform']} post for {job['account']} at {job['publishAt']} is {job['state']}: {job['meaning']}" + (f" Last event: {job['lastEvent']['message']}" if job.get("lastEvent") and job["lastEvent"].get("message") else ""))
            for job in data["upcoming"]:
                add(tool_id, f"A {job['platform']} post for {job['account']} is approved for {job['publishAt']} ({job['state']}).")
            if data["draftsUnscheduled"]:
                add(tool_id, f"{data['draftsUnscheduled']} draft(s) have never been scheduled.")
        elif tool_id == "job.get":
            if data.get("kind") == "review":
                add(tool_id, f"This {data['platform']} post for {data['account']} at {data['publishAt']} is a review with status {data['state']}. {data['meaning']}")
            else:
                add(tool_id, f"This {data['platform']} post for {data['account']} at {data['publishAt']} is {data['state']} ({data['title']}). {data['meaning']}"
                             + (f" Last event: {data['lastEvent']['message']}" if data.get("lastEvent") and data["lastEvent"].get("message") else "")
                             + (" It is on a demo account, so nothing is really published." if data.get("demo") else ""))
        elif tool_id == "draft.get":
            add(tool_id, f"The {data['platform']} draft ({data['language']}) has {data['characters']} characters" + (f" of a {data['limit']} limit" if data.get("limit") else "")
                         + f"; unknown details: {len(data['unknowns'])}; warnings: {len(data['warnings'])}; needs review: {'yes' if data['needsReview'] else 'no'}; scheduled: {'yes' if data['scheduled'] else 'no'}.")
        elif tool_id == "automation.list":
            for a in data["automations"]:
                add(tool_id, f"Automation “{a['name']}” is {a['status']}; schedule: {a['schedule']}; policy: {a['policy'] or 'not chosen'}; platforms: {', '.join(a['platforms'])}.")
        elif tool_id == "automation.get":
            add(tool_id, f"Automation “{data['name']}” is {data['status']}; {data.get('scheduleText') or ''}; policy: {data.get('policy') or 'drafts only'}.")
        elif tool_id == "automation.explain":
            if data.get("text"):
                add(tool_id, data["text"])
            for line in data.get("lines") or []:
                add(tool_id, line if isinstance(line, str) else str(line))
        elif tool_id == "memory.summary":
            add(tool_id, "Memory files: " + "; ".join(f"{f['name']} ({f['purpose']})" for f in data["files"]) + f". Preferences waiting for an owner's decision: {data['pendingPreferences']}. Cloud memory: {'on' if data['egress'].get('cloud') else 'off'}.")
        elif tool_id == "privacy.egress_state":
            add(tool_id, f"Cloud memory: {'on' if data['cloudMemory'] else 'off'}; web research: {'on' if data['webResearch'] else 'off'} for this workspace; chosen writer class: {(data['writer'] or {}).get('class') or 'unknown'}.")
        elif tool_id == "entitlements.summary":
            add(tool_id, f"Plan: {data.get('plan') or 'unknown'}; writing batches left: {data.get('writingBatchesRemaining')}; media credits left: {data.get('mediaCreditsRemaining')}; publishing included: {data.get('canPublish')}; budget status: {data.get('budgetStatus')}.")
        elif tool_id == "models.summary":
            for m in data["models"]:
                add(tool_id, f"Writer {m['label']}: {'available' if m['qualified'] else 'unavailable'} ({m['costClass']})" + (f" — {m['detail']}" if not m["qualified"] and m.get("detail") else ""))
        elif tool_id == "route.describe":
            add(tool_id, f"Page {data['title']}: {data['summary']}" + ("" if data["canOpen"] else f" ({data['reason']})"))
    return out[:24]


def _nav(route_id, query=None, *, label=None, reason=None, auto=False, language="en"):
    route = routes.by_id(route_id)
    href = routes.href(route_id, query=query or {})
    if route is None or href is None:
        return None
    return contracts.navigation(label or t(language, "open", title=route["title"]), href, route_id, reason=reason, auto=auto)


def _help_blocks(help_result, language, *, max_passages=1, lead=True):
    blocks, used = [], []
    if not help_result or not help_result.get("ok"):
        return blocks, used
    data = help_result["data"]
    if not data.get("sufficient"):
        return blocks, used
    passages = data["passages"][:max_passages]
    for passage in passages:
        used.append(passage["ref"])
    if lead and passages:
        quote = t(language, "help_quote")
        blocks.append(contracts.text((quote + "\n\n" if quote else "") + _sentences(passages[0]["text"])))
    return blocks, used


def compose(classification: dict, page: dict, plan: dict, results: dict, *, language: str, trace_id: str, retrieved_at: str, text: str = "") -> dict:
    """{"blocks", "text", "citations", "grounding", "facts", "refs"} built only from `results`."""
    intent = classification["intent"]
    blocks: list[dict] = []
    used: list[str] = []
    help_result = results.get("help.search")
    passages = (help_result or {}).get("data", {}).get("passages", []) if help_result and help_result.get("ok") else []
    get = lambda tool_id: (results.get(tool_id) or {}).get("data") if (results.get(tool_id) or {}).get("ok") else None  # noqa: E731
    lines: list[str] = []
    read = compose_reads.compose(intent, classification, results, text) if intent in compose_reads.HANDLERS else None
    if read is not None:
        ordered = ([contracts.text("\n".join(read["lines"]))] if read["lines"] else []) + read["blocks"]
        nav = read.get("nav")
        if nav and nav.split("?")[0] != page.get("route"):
            matched = routes.match(nav.split("?")[0])
            if matched:
                ordered.append(contracts.navigation(t(language, "open", title=matched["route"]["title"]), nav, matched["route"]["id"]))
        cites = []
        if passages and help_result["data"].get("sufficient") and intent in ("reviews", "publishing", "status"):
            cites = citation_objects(passages[:1], retrieved_at, used={passages[0]["ref"]})
            ordered.append(contracts.citations(cites))
        plain = "\n\n".join(b["text"] for b in ordered if b["type"] == "text")
        return {"blocks": ordered, "text": plain, "citations": cites, "grounding": {"required": True, "sufficient": read["grounded"], "missing": [] if read["grounded"] else ["The item could not be read."]},
                "facts": facts(results) + read_facts(read), "refs": read["refs"]}

    if page.get("stale") and intent in ("page", "diagnose"):
        blocks.append(contracts.warning(t(language, "stale"), "stale_context"))

    if intent == "greeting":
        lines.append(t(language, "hello"))
    elif intent == "forbidden":
        category = classification["forbidden"]["category"]
        route_id = classification["forbidden"]["routeId"]
        key = "credentials_refusal" if category == "secret" else ("paid" if category == "paid" else f"{category}_{route_id}")
        table = (TEXT.get(language) or TEXT["en"])["forbidden"]
        lines.append(table.get(key) or TEXT["en"]["forbidden"].get(key) or TEXT["en"]["forbidden"]["external_representation_queue"])
        if passages and help_result["data"].get("sufficient"):
            used.append(passages[0]["ref"])
    elif intent == "page":
        described = get("route.describe")
        if described:
            lines.append(t(language, "page", title=described["title"], summary=described["summary"]))
        live = _page_live_lines(page, results, language)
        lines.extend(live)
        extra, refs = _help_blocks(help_result, language, lead=not live)
        blocks.extend(extra)
        used.extend(refs)
    elif intent == "navigate":
        nav = plan.get("navigate")
        if nav:
            described = get("route.describe")
            title = described["title"] if described else routes.by_id(nav[0])["title"]
            explicit = bool(classification.get("explicit"))
            if described and not described["canOpen"]:
                lines.append(described["reason"])
            else:
                lines.append(t(language, "opening", title=title) if explicit else f"{title}: {routes.by_id(nav[0])['summary']}")
        extra, refs = _help_blocks(help_result, language)
        blocks.extend(extra)
        used.extend(refs)
        if not nav and not refs:
            lines.append(t(language, "unknown"))
    elif intent == "diagnose":
        blocks.extend(_diagnose_blocks(results, language))
        if not blocks and get("queue.summary"):
            lines.extend(_queue_lines(get("queue.summary"), language))
        explained = get("automation.explain")
        if explained and explained.get("text"):
            lines.append(explained["text"])
        if passages and help_result["data"].get("sufficient"):
            used.append(passages[0]["ref"])
        if not blocks and not lines:
            extra, refs = _help_blocks(help_result, language)
            blocks.extend(extra)
            used.extend(refs)
    elif intent == "capability":
        caps = get("channels.capabilities")
        if caps:
            lines.append(t(language, "capability"))
            for row in caps["accounts"]:
                lines.append(f"- **{row['platform']} · {row['account']}**: publish {row['levels'].get('publish') or 'Unsupported'}. {row['publishReason']}")
            if caps.get("unconnected"):
                lines.append(f"- **{caps['unconnected']['platform']}**: {caps['unconnected']['publishReason']}")
        extra, refs = _help_blocks(help_result, language, lead=not caps or not caps["accounts"])
        blocks.extend(extra)
        used.extend(refs)
    elif intent == "review":
        draft = get("draft.get")
        if draft is None:
            lines.append(t(language, "no_draft"))
        else:
            lines.append(t(language, "draft_checked"))
            blocks.append(_draft_card(draft))
        if passages and help_result["data"].get("sufficient"):
            used.append(passages[0]["ref"])
    elif intent == "memory":
        summary = get("memory.summary")
        if summary:
            lines.append(t(language, "memory"))
            lines.extend(f"- **{f['name']}**: {f['purpose']}" for f in summary["files"])
            if summary["pendingPreferences"]:
                lines.append(f"{summary['pendingPreferences']} learned preference(s) are waiting for an owner's decision.")
            lines.append("Cloud memory is " + ("on" if summary["egress"].get("cloud") else "off") + " for this workspace.")
        if passages and help_result["data"].get("sufficient"):
            used.append(passages[0]["ref"])
    elif intent == "privacy":
        state = get("privacy.egress_state")
        if state:
            lines.append(t(language, "privacy"))
            lines.append(f"- Cloud memory: {'on' if state['cloudMemory'] else 'off'}" + (f" ({state['withheldBoundaries']} private boundary item(s) are never shared)" if state.get("withheldBoundaries") else ""))
            lines.append(f"- Web research: {'on' if state['webResearch'] else 'off'}")
            writer = state.get("writer") or {}
            if writer.get("class"):
                lines.append(f"- Your chosen writer runs {'on your own machine' if writer['class'] == 'local' else 'in the cloud' if writer['class'] == 'cloud' else 'without a model'}.")
        extra, refs = _help_blocks(help_result, language, lead=not state)
        blocks.extend(extra)
        used.extend(refs)
    elif intent == "billing":
        plan_data = get("entitlements.summary")
        if plan_data:
            lines.append(t(language, "billing"))
            lines.append(f"- Writing batches left: {plan_data.get('writingBatchesRemaining') if plan_data.get('writingBatchesRemaining') is not None else 'unknown'}")
            lines.append(f"- Media credits left: {plan_data.get('mediaCreditsRemaining') if plan_data.get('mediaCreditsRemaining') is not None else 'unknown'}")
            if plan_data.get("canPublish") is not None:
                lines.append(f"- Publishing included right now: {'yes' if plan_data['canPublish'] else 'no'}")
        extra, refs = _help_blocks(help_result, language, lead=not plan_data)
        blocks.extend(extra)
        used.extend(refs)
    elif intent == "models":
        models = get("models.summary")
        if models:
            lines.append(t(language, "models"))
            for m in models["models"]:
                lines.append(f"- **{m['label']}**: {'available' if m['qualified'] else 'unavailable'}" + ("" if m["qualified"] or not m.get("detail") else f" — {m['detail']}"))
        extra, refs = _help_blocks(help_result, language, lead=not models)
        blocks.extend(extra)
        used.extend(refs)
    elif intent == "support":
        lines.append(t(language, "support"))
        summary = [f"Page: {page.get('title') or 'unknown'}", f"Question type: {classification['intent']}"]
        href = routes.href("contact", query={"topic": "support"})
        blocks.append(contracts.handoff(trace_id, summary, href))
        if passages and help_result["data"].get("sufficient"):
            used.append(passages[0]["ref"])
    else:
        extra, refs = _help_blocks(help_result, language, max_passages=2)
        blocks.extend(extra)
        used.extend(refs)
        if not refs:
            lines.append(t(language, "unknown"))
            lines.append(t(language, "unknown_steps"))

    nav_block = None
    if plan.get("navigate"):
        route_id, query = plan["navigate"]
        described = get("route.describe")
        if not (described and not described.get("canOpen")):
            nav_block = _nav(route_id, query, auto=bool(classification.get("explicit")) and intent == "navigate", language=language)
    elif intent in ("page", "diagnose", "capability", "memory", "privacy", "billing", "models", "review"):
        nav_block = _follow_link(intent, page, results, language)
    if intent in ("explain", "unknown") and not used:
        nav_block = _nav("help", language=language)

    text_block = contracts.text("\n".join(lines)) if lines else None
    ordered = ([text_block] if text_block else []) + blocks + ([nav_block] if nav_block else [])
    cites = citation_objects(passages, retrieved_at, used=set(used)) if used else []
    if cites:
        ordered.append(contracts.citations(cites))
    grounded = bool(cites) or any(b["type"] in ("diagnostic_card",) for b in ordered) or intent in ("greeting", "forbidden") or bool(_live_used(intent, results))
    plain = "\n\n".join(b["text"] for b in ordered if b["type"] == "text")
    missing = [] if grounded else ["No help article or workspace record answered this."]
    return {"blocks": ordered, "text": plain, "citations": cites, "grounding": {"required": classification.get("requiresGrounding", True), "sufficient": grounded, "missing": missing},
            "facts": facts(results), "refs": _refs(results)}


def _refs(results: dict) -> list[dict]:
    """The items a diagnosis or review named, for "that post" later."""
    out = []
    job = (results.get("job.get") or {}).get("data") if (results.get("job.get") or {}).get("ok") else None
    if job:
        out.append({"type": "review" if job.get("kind") == "review" else "job", "id": job.get("reviewId") or job.get("jobId"), "title": f"{job.get('platform')} post"})
    draft = (results.get("draft.get") or {}).get("data") if (results.get("draft.get") or {}).get("ok") else None
    if draft:
        out.append({"type": "draft", "id": draft["draftId"], "title": f"{draft['platform']} draft"})
    explained = (results.get("automation.explain") or {}).get("data") if (results.get("automation.explain") or {}).get("ok") else None
    if explained and explained.get("automationId"):
        out.append({"type": "automation", "id": explained["automationId"], "title": "automation"})
    queue = (results.get("queue.summary") or {}).get("data") if (results.get("queue.summary") or {}).get("ok") else None
    if queue:
        out += [{"type": "job", "id": j["jobId"], "title": f"{j['platform']} post"} for j in queue["attention"]]
        out += [{"type": "review", "id": w["reviewId"], "title": f"{w['platform']} post"} for w in queue["waitingApproval"]]
    return [r for r in out if r.get("id")][:12]


def read_facts(read: dict) -> list[dict]:
    """The lines and list items of a read answer as W-facts, so a writer model phrases only what was read."""
    out = []
    for block in read["blocks"]:
        if block.get("type") == "result_list":
            for item in block["items"]:
                out.append(" · ".join(x for x in (block["title"], item.get("title"), item.get("excerpt"), item.get("meta")) if x))
        elif block.get("type") == "diagnostic_card":
            out.append(" · ".join([block["title"], block["status"], block.get("cause") or ""] + block.get("steps", [])))
    out = [line for line in read["lines"] if line] + out
    return [{"ref": f"R{i + 1}", "tool": "read", "text": line[:400]} for i, line in enumerate(out[:30])]


def _live_used(intent, results):
    return [k for k, v in results.items() if v.get("ok") and k not in ("help.search", "help.get", "route.describe", "ui.navigate", "ui.show_help")]


def _page_live_lines(page, results, language):
    family = page.get("routeFamily")
    out = []
    summary = (results.get("workspace.summary") or {}).get("data") if (results.get("workspace.summary") or {}).get("ok") else None
    queue = (results.get("queue.summary") or {}).get("data") if (results.get("queue.summary") or {}).get("ok") else None
    if queue:
        out.extend(_queue_lines(queue, language, quiet=True))
    elif summary and family in ("home", "overview", "agent", "ideas"):
        c = summary["counts"]
        if c["reviewsWaiting"]:
            out.append(t(language, "waiting", n=c["reviewsWaiting"]))
        if c["draftsUnscheduled"]:
            out.append(t(language, "unscheduled", n=c["draftsUnscheduled"]))
    automations = (results.get("automation.list") or {}).get("data") if (results.get("automation.list") or {}).get("ok") else None
    if automations and automations["automations"]:
        active = sum(1 for a in automations["automations"] if a["status"] == "active")
        out.append(f"You have {len(automations['automations'])} automation(s); {active} active.")
    caps = (results.get("channels.capabilities") or {}).get("data") if (results.get("channels.capabilities") or {}).get("ok") else None
    if caps:
        ready = sum(1 for row in caps["accounts"] if row["canPublish"])
        out.append(f"{len(caps['accounts'])} account(s) connected; {ready} can publish right now.")
    return out


def _queue_lines(queue, language, quiet=False):
    out = []
    waiting = [w for w in queue["waitingApproval"] if not w["expired"]]
    if waiting:
        out.append(t(language, "waiting", n=len(waiting)))
    if queue["draftsUnscheduled"] and not quiet:
        out.append(t(language, "unscheduled", n=queue["draftsUnscheduled"]))
    if not waiting and not queue["attention"] and not quiet:
        out.insert(0, t(language, "no_problem"))
    return out


def _diagnose_blocks(results, language):
    out = []
    job = (results.get("job.get") or {}).get("data") if (results.get("job.get") or {}).get("ok") else None
    if job:
        if job.get("kind") == "review":
            out.append(contracts.diagnostic(f"{job.get('platform')} · {job.get('account')}", job["state"],
                                            evidence=[f"Publish time: {job.get('publishAt')}"], cause=job["meaning"], steps=job["steps"],
                                            links=[{"label": "Open in Queue", "href": routes.href("queue")}]))
        else:
            evidence = [f"Publish time: {job.get('publishAt')}", f"Attempts: {job.get('attempts')}"]
            if job.get("lastEvent") and job["lastEvent"].get("message"):
                evidence.append(f"Last event: {job['lastEvent']['message']}")
            if job.get("demo"):
                evidence.append("Demo account: nothing is really published there.")
            out.append(contracts.diagnostic(f"{job.get('platform')} · {job.get('account')}", job["title"], evidence=evidence, cause=job["meaning"],
                                            steps=job["steps"], verified=True, links=[{"label": "Open in Queue", "href": routes.href("queue", query={"job": job["jobId"]})}]))
    queue = (results.get("queue.summary") or {}).get("data") if (results.get("queue.summary") or {}).get("ok") else None
    if queue:
        for item in queue["attention"][:2]:
            evidence = [f"Publish time: {item.get('publishAt')}"] + ([f"Last event: {item['lastEvent']['message']}"] if item.get("lastEvent") and item["lastEvent"].get("message") else [])
            out.append(contracts.diagnostic(f"{item.get('platform')} · {item.get('account')}", item["title"], evidence=evidence, cause=item["meaning"], steps=item["steps"],
                                            links=[{"label": "Open in Queue", "href": routes.href("queue", query={"job": item["jobId"]})}]))
        waiting = [w for w in queue["waitingApproval"]][:2]
        for item in waiting:
            state = "Review window closed" if item["expired"] else "Waiting for approval"
            cause = ("Its publish time passed before anyone approved it." if item["expired"] else "Nothing publishes until someone with the approve permission approves this exact post.")
            steps = ["Prepare the draft again with a new time from Queue → Drafts."] if item["expired"] else ["Open it in the Queue and approve it, or change the draft first."]
            out.append(contracts.diagnostic(f"{item.get('platform')} · {item.get('account')}", state, evidence=[f"Publish time: {item.get('publishAt')}"], cause=cause, steps=steps,
                                            links=[{"label": "Open in Queue", "href": routes.href("queue")}]))
    caps = (results.get("channels.capabilities") or {}).get("data") if (results.get("channels.capabilities") or {}).get("ok") else None
    if caps:
        blocked = [row for row in caps["accounts"] if not row["canPublish"]]
        for row in blocked[:3]:
            out.append(contracts.diagnostic(f"{row['platform']} · {row['account']}", "Can't publish right now", evidence=[f"Connection: {row['connectionState'].replace('_', ' ')}", f"Publish level: {row['levels'].get('publish')}"],
                                            cause=row["publishReason"], steps=["Open Channels to re-verify or reconnect this account."] if row["publishCode"] in ("reauthorize", "disconnected") else [],
                                            links=[{"label": "Open Channels", "href": routes.href("channels")}]))
        if caps.get("unconnected"):
            u = caps["unconnected"]
            out.append(contracts.diagnostic(u["platform"], "Not connected" if u["publishCode"] == "not_connected" else "Can't publish here", cause=u["publishReason"],
                                            links=[{"label": "Open Channels", "href": routes.href("channels")}]))
        if not blocked and not caps.get("unconnected") and caps["accounts"]:
            out.append(contracts.diagnostic("Connected accounts", "All accounts can publish", evidence=[f"{row['platform']} · {row['account']}" for row in caps["accounts"][:4]]))
    models = (results.get("models.summary") or {}).get("data") if (results.get("models.summary") or {}).get("ok") else None
    if models:
        unavailable = [m for m in models["models"] if not m["qualified"]]
        chosen = next((m for m in models["models"] if m["id"] == models.get("selected")), None)
        if chosen and not chosen["qualified"]:
            out.append(contracts.diagnostic(chosen["label"], "Unavailable", cause=chosen.get("detail"), links=[{"label": "Open Models & providers", "href": routes.href("models")}]))
        elif unavailable:
            out.append(contracts.diagnostic("Writers", f"{len(unavailable)} unavailable", evidence=[f"{m['label']}: {m.get('detail') or 'unavailable'}" for m in unavailable[:3]],
                                            links=[{"label": "Open Models & providers", "href": routes.href("models")}]))
    return out


def _draft_card(draft):
    evidence = [f"{draft['platform']} · {draft.get('account') or 'no account chosen'} · {draft['language']}"]
    if draft.get("limit"):
        evidence.append(f"Length: {draft['characters']} of {draft['limit']} characters")
    steps = []
    if draft["overLimit"]:
        steps.append(f"Shorten it to {draft['limit']} characters or fewer.")
    if draft["unknowns"]:
        steps.append("Confirm or remove the unknown details: " + "; ".join(draft["unknowns"][:3]))
    if draft["warnings"]:
        steps.append("Read and acknowledge its warnings when you schedule it.")
    if draft["needsReview"]:
        steps.append("Review the draft (it was marked for review after a change).")
    if draft["blockedByRetraction"]:
        steps.append("Draft it again: a source it used was retracted.")
    if not steps:
        steps.append("Nothing blocks it: schedule it from Queue → Drafts.")
    status = "Scheduled" if draft["scheduled"] else ("Needs work" if len(steps) > 1 or draft["overLimit"] or draft["unknowns"] else "Ready to schedule")
    return contracts.diagnostic("Draft check", status, evidence=evidence, steps=steps, links=[{"label": "Open Drafts", "href": routes.href("queue", query={"view": "drafts"})}])


def _follow_link(intent, page, results, language):
    target = {"capability": "channels", "memory": "memory", "privacy": "memory", "billing": "billing", "models": "models", "review": None}.get(intent)
    if intent == "diagnose":
        if "channels.capabilities" in results:
            target = "channels"
        elif "automation.explain" in results:
            data = (results.get("automation.explain") or {}).get("data") or {}
            if data.get("automationId"):
                return _nav("automations", {"edit": data["automationId"]}, label="Open the automation", language=language)
            target = "automations"
        elif "models.summary" in results:
            target = "models"
        elif "queue.summary" in results and page.get("routeFamily") not in ("queue",):
            target = "queue"
    if target is None or target == page.get("routeId"):
        return None
    return _nav(target, language=language)
