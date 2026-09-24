"""What is the person asking Rafii? (site agent §2.2, §5.4)

A deterministic, bilingual (English, Traditional Chinese, Cantonese) reading of one message in its page context. It
fixes the answer class, the risk, the entities and the procedures before any model sees the message: a model may
phrase the answer later, but it never chooses what Rafii may do. Requests that belong to the writing pipeline (a
draft now, a post at a time, an automation, a standing writing instruction) are recognised with the detectors that
pipeline already uses, so the side panel and Home read the same message the same way.

Order matters and is deliberate: forbidden effects first (so "publish this now" is never drafted), then questions
about Rafii itself (so "what do you remember?" is not stored as a memory instruction), then writing requests, then
automation changes, then the guide classes.
"""
from __future__ import annotations

import re

from .. import intent as writing_intent, workflow_parse
from . import routes

INTENTS = ("greeting", "page", "navigate", "diagnose", "capability", "review", "memory", "privacy", "billing", "models",
           "support", "explain", "unknown", "operate", "edit", "forbidden", "status", "attention", "reviews", "publishing", "campaign",
           "calendar", "brand", "voice", "drafts", "search", "schedule", "compound", "clarify")
RISKS = ("read", "client_action", "workspace_mutation", "paid", "external_representation", "destructive", "secret")
GUIDE = ("greeting", "page", "navigate", "diagnose", "capability", "review", "memory", "privacy", "billing", "models", "support", "explain", "unknown",
         "status", "attention", "reviews", "publishing", "campaign", "calendar", "brand", "voice", "drafts", "search")

_I = re.I
FORBIDDEN = (
    ("secret", re.compile(r"\b(?:show|give|tell|reveal|what(?:'s| is| are)|send|print|display|share|copy|paste|export)\b[^.?!\n]{0,40}\b(?:api[ -]?keys?|access[ -]?tokens?|refresh[ -]?tokens?|oauth[ -]?tokens?|bearer|tokens?|passwords?|secrets?|credentials?|cookies?|private keys?)\b"
                          r"|(?:睇|話|俾|畀|給|顯示|透露|講|傳|複製).{0,10}(?:密碼|金鑰|密鑰|憑證|token|Token|cookie)", _I), "channels"),
    ("destructive", re.compile(r"\b(?:delete|remove|erase|wipe|close|terminate)\b[^.?!\n]{0,24}\b(?:my\s+|the\s+|this\s+)?(?:account|workspace|everything|all\s+(?:my\s+|of\s+my\s+)?data)\b"
                               r"|刪除.{0,6}(?:帳戶|帳號|工作區|全部|所有)|(?:cancel|end)\s+(?:my\s+)?subscription|取消訂閱", _I), "privacy"),
    ("destructive", re.compile(r"\b(?:disconnect|unlink|revoke)\b[^.?!\n]{0,30}\b(?:account|accounts|linkedin|instagram|threads|twitter|x|channel|channels|connection)\b|斷開|解除連結|取消連接", _I), "channels"),
    # Any other delete (never "remove LinkedIn from the automation", which is an automation change).
    ("destructive", re.compile(r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+)?(?:delete|remove|erase|discard|trash|bin|get\s+rid\s+of)\b(?![^.?!\n]*\bfrom\b)|(?:刪除|刪咗|删除|清除|丟棄)", _I), "queue"),
    ("paid", re.compile(r"\b(?:buy|purchase|pay\s+for|upgrade|subscribe|top[ -]?up|add\s+(?:a\s+)?(?:card|payment))\b|(?:買|購買|增值|升級|訂閱).{0,6}(?:點數|額度|方案|計劃|plan)", _I), "billing"),
    ("external_representation", re.compile(r"\b(?:reply|respond|answer|dm|message)\b[^.?!\n]{0,24}\b(?:comments?|dms?|followers?|fans?|them|him|her|this\s+comment|people)\b|回覆.{0,6}(?:留言|評論|佢哋)|私訊", _I), "inbox"),
    ("external_representation", re.compile(r"\b(?:publish|post|send|push|release|approve|share)\b\s+(?:it|this|that|them|these|those|everything|all(?:\s+of\s+them)?|the\s+(?:draft|post|review|job|queue)s?|my\s+(?:draft|post)s?)\b"
                                           r"|(?:即刻|馬上|而家|依家|立即)?(?:發佈|發布|出|批准|審批|approve)(?:咗)?(?:佢|呢篇|呢個|佢哋|全部|所有)", _I), "queue"),
    ("setting", re.compile(r"\b(?:turn|switch|toggle)\s+(?:on|off)\b[^.?!\n]{0,30}\b(?:cloud|memory|research|egress)\b|\b(?:enable|disable|allow)\b[^.?!\n]{0,20}\b(?:cloud\s+memory|web\s+research|research|cloud)\b|(?:開|閂|開啟|關閉).{0,6}(?:雲端|研究)", _I), "memory"),
)
GREETING = re.compile(r"^\s*(?:hi|hello|hey|yo|hiya|thanks|thank\s+you|thx|ty|good\s+(?:morning|afternoon|evening)|你好|哈囉|哈佬|早晨|多謝|唔該|謝謝|thank\s*u)[\s!.。！~]*$", _I)
PAGE = re.compile(r"\b(?:this|the\s+current|current)\s+(?:page|screen|tab|view)\b|\bwhat\s+(?:can|do|should)\s+i\s+do\s+here\b|\bwhat\s+(?:am\s+i|i\s+am|i'm)\s+looking\s+at\b|\bwhere\s+am\s+i\b|^\s*what(?:'s|\s+is)\s+this\s*\??\s*$|^\s*help\s*\??$"
                  r"|\b(?:what|which)\s+(?:page|screen|tab|view)\s+(?:am\s+i|is\s+this|are\s+we)\b"
                  r"|(?:呢|這|依)(?:頁|個頁|版|度|個畫面)|呢度(?:做|係|可以做)(?:咩|乜)|我(?:而家)?喺邊", _I)
NAVIGATE = re.compile(r"\bwhere\s+(?:do|can|should|would)\s+i\b|\bwhere(?:'s|\s+is|\s+are|\s+do\s+i\s+find)\b|\bhow\s+do\s+i\s+(?:get|go)\s+to\b|\btake\s+me\b|\bbring\s+me\b|\bgo\s+to\b|\bnavigate\s+to\b|^\s*open\b|\bopen\s+(?:the\s+)?[a-z& ]{2,30}\s+page\b"
                      r"|喺邊|邊度|點去|帶我去|去(?:返)?(?:邊|個)|打開|開(?:返)?(?:個)?.{0,6}頁", _I)
TAKE_ME = re.compile(r"\btake\s+me\b|\bbring\s+me\b|\bgo\s+to\b|\bnavigate\s+to\b|^\s*open\b|帶我去|打開", _I)
DIAGNOSE = re.compile(r"\bwhy\b|\bwhat\s+happened\b|\bnot\s+(?:working|publishing|published|posting|posted|showing|sending|loading|going\s+out)\b|\b(?:didn'?t|hasn'?t|isn'?t|wasn'?t|won'?t|can'?t|cannot|couldn'?t)\b|\bfail(?:ed|ing|s)?\b|\berror\b|\bstuck\b|\bheld\b|\buncertain\b|\bdisabled\b|\bgr[ae]yed\b|\bbroken\b|\bmissing\b"
                      r"|點解|為何|為什麼|唔得|冇出|未出|出唔到|發唔到|失敗|錯誤|卡住|用唔到|撳唔到|灰咗|冇反應|唔work", _I)
CAPABILITY = re.compile(r"\b(?:direct|assisted|bridge|unsupported|capabilit(?:y|ies))\b|\bcan\s+(?:rafii|it|you|i)\s+(?:publish|post|schedule)\s+(?:to|on)\b|\bdoes\s+[a-z ]{2,20}\s+support\b|支援|支持|可唔可以(?:發|出|post)|能唔能夠", _I)
MEMORY = re.compile(r"\bwhat\s+do\s+you\s+(?:know|remember)\b|\bmemory\b|\bbrand\s+brain\b|\bremember(?:ed|s)?\b|\bforget\b|記憶|品牌大腦|你記得|記住咗|記得咩|記得乜", _I)
PRIVACY = re.compile(r"\bprivacy\b|\bprivate\b|\bcloud\b|\begress\b|\bleave\s+(?:rafii|the\s+server)\b|\bwho\s+can\s+see\b|\bdata\s+(?:leave|leaves|go|goes|sent)\b|\bshare\s+my\s+data\b|私隱|隱私|雲端|資料.{0,4}(?:去|傳|畀)|邊個睇到", _I)
BILLING = re.compile(r"\bbill(?:ing)?\b|\bplan\b|\bcredits?\b|\bbatch(?:es)?\b|\ballowance\b|\busage\b|\bcosts?\b|\bprice|\bpricing\b|\bcharg(?:e|ed|es)\b|\binvoice\b|\btrial\b|\bsubscription\b|\bbudget\b|\bstop-?line\b|收費|費用|幾錢|計劃|方案|點數|額度|用量|試用|訂閱|預算", _I)
MODELS = re.compile(r"\bmodels?\b|\bwriters?\b|\bproviders?\b|\bclaude\b|\bcodex\b|\bgpt\b|\bopenai\b|\bgemini\b|\bwhich\s+ai\b|\bllm\b|模型|供應商|邊個\s*AI", _I)
REVIEW = re.compile(r"\b(?:review|check|feedback|improve|critique|proofread)\b[^.?!\n]{0,20}\b(?:draft|post|caption|this|it)\b|(?:睇下|檢查|改善|俾意見|畀意見).{0,6}(?:草稿|篇|帖|文|post)", _I)
SUPPORT = re.compile(r"\b(?:contact|talk\s+to|speak\s+to|reach)\s+(?:support|a\s+human|someone|the\s+team|a\s+person)\b|\btried\s+everything\b|\bstill\s+(?:broken|failing|not\s+working)\b|\bbug\b|\bsupport\b|客服|真人|支援團隊|報告問題|試咗好多", _I)
QUESTION = re.compile(r"\?\s*$|？\s*$|^\s*(?:what|how|why|when|which|who|can|could|does|do|is|are|should|will|where)\b|係咩|咩嚟|點樣|點用|乜嘢|咩意思|點解|可唔可以|係唔係|有冇|點算", _I)
WRITE_ZH = re.compile(r"(?:幫我|同我|可唔可以|可以|請)?(?:寫|草擬|撰寫|整|作)(?:一|個|篇|段|則)?.{0,10}(?:post|帖|貼文|文案|caption|文章|thread|內容)", _I)
EDIT_EN = re.compile(r"^\s*(?:please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+to\s+|let'?s\s+)?(?:change|move|switch|update|edit|set|make|reschedule|shift|turn\s+(?:off|on)|stop|pause|resume|restart|remove|add|drop|use)\b", _I)
TRANSFORM = re.compile(r"\b(?:shorten|shorter|trim|tighten|condense|lengthen|longer|expand|continue|finish|rewrite|rephrase|reword|redo|polish|punch\s+up)\b"
                       r"|\bmake\s+(?:it|this|that)\s+(?:shorter|longer|punchier|warmer|more|less|sound)\b|\b(?:alternate|alternative|other|new|more|different)\s+(?:hooks?|openings?|intros?|headlines?|first\s+lines?)\b"
                       r"|\b(?:adapt|turn|convert|repurpose|rework|reshape)\b[^.?!\n]{0,40}\b(?:for|into|to)\s+(?:an?\s+)?(?:instagram|linkedin|threads|x|twitter|xiaohongshu|facebook|tiktok|youtube|thread|carousel|version|posts?)\b"
                       r"|\bsounds?\s+(?:more\s+)?like\s+me\b|\bin\s+my\s+(?:own\s+)?(?:usual\s+)?voice\b"
                       r"|縮短|精簡|改寫|重寫|改成|改做|轉做|轉成|延續|續寫|另一個開頭|換個開頭|似我啲|用我嘅語氣", _I)
SCHEDULE_EXISTING = re.compile(r"\b(?:schedule|book|queue|slot)\b\s+(?:it|this|that|these|the\s+(?:draft|post|second\s+one|first\s+one|last\s+one)|my\s+draft)\b"
                               r"|\b(?:move|reschedule|shift|push|postpone)\b\s+(?:it|this|that|the\s+(?:post|draft|one)|my\s+post|[a-z]+day'?s\s+post)\b[^.?!\n]{0,24}\b(?:to|until|for)\b"
                               r"|\bmark\s+(?:it|this|that)\s+(?:as\s+)?ready\s+for\s+review\b|(?:排|安排|改期|推遲|移去|搬去).{0,6}(?:星期|禮拜|聽日|今日|下個)", _I)
CAMPAIGN_POST = re.compile(r"\b(?:create|write|draft|make)\b[^.?!\n]{0,40}\b(?:post|draft|caption)\b[^.?!\n]{0,40}\b(?:for|based\s+on|from|about)\s+(?:this|that|the|my|our)\s+campaign\b", _I)
STATUS = re.compile(r"\bstatus\s+of\s+(?:this|that|the)\b|\bwhat(?:'s|\s+is)\s+the\s+status\b|\bwhich\s+(?:platform|account|channel)\s+is\s+(?:this|that|it)\b|\bwhat\s+(?:still\s+)?needs?\s+(?:to\s+be\s+)?(?:done|completed|finished)\b"
                    r"|\bwhat(?:'s|\s+is)\s+(?:still\s+)?(?:left|missing)\s+(?:here|for\s+this)\b|\bwhat\s+am\s+i\s+(?:currently\s+)?working\s+on\b|\bwhat\s+campaign\s+is\s+(?:this|that)\b"
                    r"|\bhas\s+(?:this|it|that)\s+been\s+(?:published|posted|scheduled|approved)\b|\bexplain\s+what\s+i(?:'m|\s+am)\s+looking\s+at\b|(?:呢個|呢篇).{0,6}(?:狀態|進度|咩平台)|仲差咩|仲要做咩", _I)
BRAND = re.compile(r"\bbrand\s+(?:voice|guidelines?|rules?|tone|identity|values?|guidance)\b|\btarget\s+audience\b|\baudience\b|\b(?:avoid|banned|off[- ]limits)\b|\bguidelines?\b|\bguidance\b|\bon[- ]brand\b|\boff[- ]brand\b"
                   r"|品牌(?:語氣|指引|規則|形象)|目標(?:受眾|觀眾|讀者)|受眾|要避免|唔好用", _I)
VOICE = re.compile(r"\b(?:my|our)\s+(?:writing\s+)?voice\b|\bhow\s+do\s+i\s+(?:normally\s+|usually\s+|typically\s+)?(?:open|start|begin|write|end|close)\b|\bpatterns?\b[^.?!\n]{0,30}\b(?:learn(?:ed|t)|my\s+writing)\b"
                   r"|\bsounds?\s+like\s+me\b|\bvoice\s+profile\b|\blearn(?:ed|t)\s+from\s+my\b|\b(?:linkedin|instagram|threads|x)\s+voice\b|我嘅(?:語氣|風格|寫法)|點樣開頭|似唔似我|學到", _I)
REVIEWS = re.compile(r"\bwaiting\s+for\s+(?:my\s+)?(?:review|approval)\b|\bneeds?\s+my\s+(?:review|approval)\b|\bwhat\s+(?:do\s+i\s+)?(?:need\s+to\s+|should\s+i\s+)?review\b|\brejected\b|\breturned\b|\bsent\s+back\b"
                     r"|\breviewer(?:'s)?\s+(?:feedback|notes?|comments?)\b|\bfeedback\b|等(?:緊)?(?:審批|審核|批准)|退回|被拒|審批意見", _I)
PUBLISHING = re.compile(r"\bwhat\s+(?:has\s+)?(?:published|posted|went\s+out|failed)\b|\bpublished\s+(?:today|this\s+week|yesterday|last\s+week)\b|\b(?:has|have|did)\s+(?:this|it|anything|the\s+post)\s+(?:been\s+)?(?:publish|post)"
                        r"|\bcan\s+(?:this|it)\s+be\s+retried\b|\bretry\b|\bwhich\s+platform\s+was\s+(?:this|it)\s+published\b|\bfailed\s+posts?\b|發佈咗(?:咩|未)|出咗(?:咩|未)|失敗咗|重試", _I)
CALENDAR = re.compile(r"\bwhat(?:'s|\s+is|\s+do\s+i\s+have)\s+(?:scheduled|planned|on\s+the\s+calendar|coming\s+up)\b|\bscheduled\s+(?:this|next|for|on|today|tomorrow)\b|\b(?:open|free|empty)\s+(?:day|slot|time)\b"
                      r"|\bcontent\s+gaps?\b|\bgaps?\s+(?:this|next|in)\b|\btoo\s+close\s+together\b|\bclose\s+together\b|排咗(?:咩|啲咩)|空檔|太近|有冇(?:位|空)", _I)
CAMPAIGN = re.compile(r"\bcampaigns?\b|推廣活動|宣傳活動", _I)
# "What did Alex post last week?": Rafii has no reader for members' activity, so it never attributes posts to a person.
PERSON_ACTIVITY = re.compile(r"\bwhat\s+(?:did|has|have)\s+(?!(?:i|we|you|rafii|it|they|he|she|the|this|that|my|our)\b)([A-Za-z][\w'-]{1,30})\s+"
                             r"(?:post|posted|write|written|wrote|publish|published|schedule|scheduled|draft|drafted|approve|approved|share|shared)\b", _I)
# A campaign question stays a read of the campaign unless it asks why something broke or asks for a change.
CAMPAIGN_WHY = re.compile(r"\bwhy\b|點解|\bfail(?:ed|ing|s|ure)?\b|\berror\b|\bstuck\b|\bbroken\b", _I)
# "Explain what I'm looking at" with nothing selected is about the page; "what am I working on" is about recent drafts.
PAGE_STATUS = re.compile(r"\blooking\s+at\b|\bhere\b|呢度", _I)
WORKING_ON = re.compile(r"\bworking\s+on\b", _I)
CAMPAIGN_CONTEXT = re.compile(r"\bobjective\b|\bgoal\b|\bplanned\b|\bmissing\b|\bcovered\b|\bgaps?\b|\blast\s+week\b|\bdrafts?\s+belong\b", _I)
ATTENTION = re.compile(r"\bpay\s+attention\b|\bneeds?\s+(?:my\s+)?attention\b|\bwhat\s+should\s+i\s+(?:do|focus\s+on|look\s+at)\b|\bneglect(?:ed|ing)?\b|\brepetitive\b|\brepeat(?:ing|ed)?\s+myself\b"
                       r"|\bconflict\s+with\s+(?:the\s+)?campaign\b|要留意|需要注意|有咩要跟進", _I)
SEARCH = re.compile(r"^\s*(?:please\s+)?(?:find|search(?:\s+for)?|look\s+for|locate|show\s+(?:me\s+)?(?:everything|all|posts?|drafts?|content)\b)|\bwhere\s+did\s+i\s+(?:use|write|say|mention)\b|\bmention(?:s|ing)?\b"
                    r"|\beverything\s+(?:related|about)\b|\bposts?\s+about\b|\bdrafts?\s+about\b|^\s*(?:搵|搜尋|幫我搵)", _I)
DRAFTS_LIST = re.compile(r"\b(?:my\s+)?(?:unfinished|recent|latest|open|unscheduled|current)\s+drafts?\b|\bdrafts?\s+(?:i|we)\s+(?:worked|was\s+working|were\s+working)\s+on\b|\bwhat\s+drafts?\b|未完成(?:嘅)?草稿|最近(?:嘅)?草稿", _I)
COMPOUND_FIND = re.compile(r"\b(?:find|look\s+up|locate|pull\s+up)\b", _I)
COMPOUND_CREATE = re.compile(r"\b(?:create|write|draft|make|generate|prepare)\b[^.?!\n,]{0,48}\b(?:post|draft|caption|version|thread)\b", _I)
COMPOUND_SCHEDULE = re.compile(r"\b(?:schedule|place|put|slot|book)\b[^.?!\n]{0,48}\b(?:slot|day|time|next\s+week|this\s+week|calendar|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
                               r"|\b(?:next|first|earliest)\s+(?:suitable\s+|available\s+|empty\s+|open\s+|free\s+)?(?:slot|day)\b", _I)
COMPOUND_GAPS = re.compile(r"\bwhat(?:'s|\s+is)\s+(?:still\s+)?missing\b|\b(?:content\s+)?gaps?\b", _I)
EDIT_ZH = re.compile(r"(?:改|轉|移|暫停|停|恢復|刪除|取消).{0,10}(?:自動化|個自動|嗰個自動)|(?:自動化).{0,10}(?:改|轉|移|暫停|停|恢復)", _I)

ROUTE_WORDS = (
    ("queue", r"\bqueue\b|\bjobs?\b|佇列|隊列|排隊"), ("queue_drafts", r"\bdrafts?\s+tab\b|\bmy\s+drafts\b|草稿(?:區|夾)?"),
    ("calendar", r"\bcalendar\b|日曆|行事曆|月曆"), ("channels", r"\bchannels?\b|\bconnections?\b|\bconnect(?:ed)?\b|\baccounts?\b|頻道|連接|帳戶|帳號"),
    ("automations", r"\bautomations?\b|自動化"), ("memory", r"\bmemory\b|\bbrand\s+brain\b|記憶"), ("brand", r"\bbrand\b|\bvoice\b|品牌|聲音|語氣"),
    ("billing", r"\bbilling\b|\bplan\b|\bcredits?\b|\busage\b|收費|方案|計劃|額度|用量"), ("models", r"\bmodels?\b|\bproviders?\b|\bwriters?\b|模型|供應商"),
    ("privacy", r"\bprivacy\b|\bexport\b|\bdelete\s+my\s+data\b|私隱|匯出"), ("members", r"\bmembers?\b|\binvit(?:e|ation)s?\b|\bteam\b|成員|邀請"),
    ("roles", r"\broles?\b|\bpermissions?\b|角色|權限"), ("audit", r"\baudit\b|審計"), ("analytics", r"\banalytics\b|\bstats\b|\binsights?\b|分析|數據"),
    ("inbox", r"\binbox\b|\bcomments?\b|\breplies\b|收件|留言"), ("library", r"\blibrary\b|\bmedia\b|\bimages?\b|\bphotos?\b|圖庫|圖片|媒體"),
    ("ideas", r"\bideas?\b|\bsources?\b|素材|來源|靈感"), ("overview", r"\boverview\b|\bdashboard\b|總覽|概覽"), ("home", r"\bhome\b|\bcompose\b|主頁|首頁"),
    ("profile", r"\bprofile\b|\bpassword\b|\b2fa\b|\btwo[- ]factor\b|\bpasskeys?\b|\bsessions?\b|個人資料|雙重認證"),
    ("notifications", r"\bnotifications?\b|\bemails?\s+(?:settings|preferences)\b|通知"), ("api", r"\bapi\b|\btokens?\s+page\b|\bintegrations?\b"),
    ("help", r"\bhelp\s+(?:articles?|center|page)\b|說明|幫助"),
)
_ROUTE_RES = [(route_id, re.compile(pattern, _I)) for route_id, pattern in ROUTE_WORDS]
_THIS = re.compile(r"\b(?:this|that|it|the\s+(?:selected|current|open))\b|呢個|呢篇|依個|呢條|佢", _I)


def language(text: str) -> str:
    return "zh-Hant" if re.search(r"[㐀-鿿]", text or "") else "en"


def platforms(text: str) -> list[str]:
    marked = writing_intent.mark_platform_x(text) if hasattr(writing_intent, "mark_platform_x") else text
    try:
        return list(dict.fromkeys(writing_intent._platform_mentions(marked)))
    except Exception:  # noqa: BLE001 — entity hints never block a turn
        return []


def target_routes(text: str) -> list[str]:
    return [route_id for route_id, pattern in _ROUTE_RES if pattern.search(text)]


def classify(text: str, page: dict, *, automation_names=(), in_automation_context: bool = False, focus: dict | None = None) -> dict:
    """The typed reading of one message (§5.4). Deterministic; `procedureIds` come from procedures.select.
    `focus` is the item the message is about when the page or the conversation names one (references.resolve)."""
    text = text or ""
    lang = language(text)
    question = bool(QUESTION.search(text))
    focus = focus or page.get("selectedEntity")
    entities = {"platforms": platforms(text), "routes": target_routes(text), "refersToSelection": bool(_THIS.search(text)),
                "automation": None, "focus": focus}
    base = {"language": lang, "entities": entities, "question": question, "requiresGrounding": True, "forbidden": None,
            "operate": None, "confidence": 0.9}

    for category, pattern, route_id in FORBIDDEN:
        if pattern.search(text) and not (category == "external_representation" and route_id == "queue" and _is_new_content(text)):
            risk = "external_representation" if category in ("external_representation",) else ("workspace_mutation" if category == "setting" else category)
            return {**base, "intent": "forbidden", "risk": risk, "forbidden": {"category": category, "routeId": route_id}}
    if GREETING.search(text):
        return {**base, "intent": "greeting", "risk": "read", "requiresGrounding": False}
    # Questions about what Rafii remembers are not standing instructions to remember something.
    if MEMORY.search(text) and question:
        return {**base, "intent": "memory", "risk": "read"}
    person = PERSON_ACTIVITY.search(text)
    if person and not platforms(person.group(1)):
        entities["person"] = person.group(1)[:40]
        return {**base, "intent": "publishing", "risk": "read"}
    if (CAMPAIGN.search(text) and question and not CAMPAIGN_WHY.search(text) and not CAMPAIGN_POST.search(text)
            and not (EDIT_EN.search(text) or EDIT_ZH.search(text) or workflow_parse.is_edit(text))):
        # "What is still missing in this campaign?", "What happened in this campaign last week?": the campaign's own
        # record (objective, platforms, runs), even when an automation of it is selected.
        return {**base, "intent": "campaign", "risk": "read"}
    about_automation = workflow_parse.refers_to_automation(text, list(automation_names), in_automation_context)
    if about_automation and question and (workflow_parse.is_explain(text) or DIAGNOSE.search(text)):
        entities["automation"] = "explain"
        return {**base, "intent": "diagnose", "risk": "read"}
    steps = [kind for kind, pattern in (("find", COMPOUND_FIND), ("gaps", COMPOUND_GAPS), ("create", COMPOUND_CREATE), ("schedule", COMPOUND_SCHEDULE)) if pattern.search(text)]
    if len(steps) >= 2 and ("create" in steps or "schedule" in steps) and len(text) > 40:
        # Several steps in one message: each runs or is reported on its own (service._compound); nothing is guessed.
        return {**base, "intent": "compound", "risk": "workspace_mutation", "steps": steps}
    item = focus if focus and focus.get("type") in ("draft", "job", "review") else None
    automation_focus = (focus or {}).get("type") in ("automation", "campaign") or (not item and workflow_parse.refers_to_automation(text, list(automation_names), in_automation_context))
    if TRANSFORM.search(text) and not re.search(r"\bwhy\b|點解", text, _I) and (item or _THIS.search(text) or entities["platforms"]) and not automation_focus:
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "transform", "requiresGrounding": False}
    if SCHEDULE_EXISTING.search(text) and not question and not automation_focus:
        # Moving an automation's day is an automation change (a proposal), not a post's schedule.
        return {**base, "intent": "schedule", "risk": "workspace_mutation"}
    if CAMPAIGN_POST.search(text):
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "campaign_post", "requiresGrounding": False}
    if writing_intent.is_automation_request(text) and not (question and DIAGNOSE.search(text)):
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "automation", "requiresGrounding": False}
    if workflow_parse.is_drafting_request(text) or (WRITE_ZH.search(text) and not question):
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "draft", "requiresGrounding": False}
    if workflow_parse.is_scheduled_post(text) and not question:
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "schedule", "requiresGrounding": False}
    if writing_intent.is_memory_instruction(text) and not question:
        return {**base, "intent": "operate", "risk": "workspace_mutation", "operate": "memory", "requiresGrounding": False}
    if about_automation and (workflow_parse.is_edit(text) or EDIT_EN.search(text) or EDIT_ZH.search(text)) and not re.search(r"\bwhy\b|點解", text, _I):
        return {**base, "intent": "edit", "risk": "workspace_mutation"}
    if about_automation and (workflow_parse.is_explain(text) or DIAGNOSE.search(text)):
        entities["automation"] = "explain"
        return {**base, "intent": "diagnose", "risk": "read"}
    if STATUS.search(text):
        if not focus and PAGE_STATUS.search(text):
            return {**base, "intent": "page", "risk": "read"}
        if not focus and WORKING_ON.search(text):
            return {**base, "intent": "drafts", "risk": "read"}
        # Without an item on the page or in the conversation, the answer searches for the one named, or says it can't find it.
        return {**base, "intent": "status", "risk": "read"}
    if ATTENTION.search(text):
        return {**base, "intent": "attention", "risk": "read"}
    if REVIEWS.search(text) and not (DIAGNOSE.search(text) and item):
        return {**base, "intent": "reviews", "risk": "read"}
    if PUBLISHING.search(text) and not (item and re.search(r"\bwhy\b|點解", text, _I)):
        return {**base, "intent": "status" if item and re.search(r"\b(?:this|it|that)\b", text, _I) else "publishing", "risk": "read"}
    if CAMPAIGN.search(text) or (CAMPAIGN_CONTEXT.search(text) and focus and focus.get("type") == "automation"):
        return {**base, "intent": "campaign", "risk": "read"}
    if CALENDAR.search(text):
        return {**base, "intent": "calendar", "risk": "read"}
    if BRAND.search(text) and not VOICE.search(text.replace("brand voice", "")):
        return {**base, "intent": "brand", "risk": "read"}
    if VOICE.search(text):
        return {**base, "intent": "voice", "risk": "read"}
    if DRAFTS_LIST.search(text):
        return {**base, "intent": "drafts", "risk": "read"}
    if SEARCH.search(text):
        return {**base, "intent": "search", "risk": "read"}
    if REVIEW.search(text):
        return {**base, "intent": "review", "risk": "read"}
    if SUPPORT.search(text):
        return {**base, "intent": "support", "risk": "read"}
    if PAGE.search(text):
        return {**base, "intent": "page", "risk": "read"}
    if NAVIGATE.search(text) and (entities["routes"] or TAKE_ME.search(text)):
        return {**base, "intent": "navigate", "risk": "client_action", "explicit": bool(TAKE_ME.search(text))}
    if CAPABILITY.search(text):
        return {**base, "intent": "capability", "risk": "read"}
    if DIAGNOSE.search(text):
        return {**base, "intent": "diagnose", "risk": "read"}
    if PRIVACY.search(text):
        return {**base, "intent": "privacy", "risk": "read"}
    if MEMORY.search(text):
        return {**base, "intent": "memory", "risk": "read"}
    if MODELS.search(text):
        return {**base, "intent": "models", "risk": "read"}
    if BILLING.search(text):
        return {**base, "intent": "billing", "risk": "read"}
    if NAVIGATE.search(text):
        return {**base, "intent": "navigate", "risk": "client_action", "explicit": bool(TAKE_ME.search(text))}
    if question:
        return {**base, "intent": "explain", "risk": "read", "confidence": 0.6}
    return {**base, "intent": "unknown", "risk": "read", "confidence": 0.3}


def _is_new_content(text: str) -> bool:
    """"Post about my concert at 4 PM" is new content for the writing pipeline, not a request to publish something."""
    return bool(re.search(r"\b(?:post|publish|share)\s+(?:this|it|that)\s+(?:about|on\s+the\s+topic)\b", text, _I)) or workflow_parse.is_scheduled_post(text)
