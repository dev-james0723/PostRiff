"""An intentionally bounded deterministic adapter. It never calls a provider."""
from typing import Protocol

PLATFORMS = ("LinkedIn", "Instagram", "Threads")
LANGUAGES = ("English", "繁體中文")
SAMPLE_TEXT = "The community garden hosts a free seed-swap on Saturday. Visitors can bring seeds or simply come to learn. The event includes a beginner planting demonstration."
SAMPLE_FACTS = [
    ("The community garden hosts a free seed-swap on Saturday.", "社區花園將於星期六舉辦免費種子交換活動。"),
    ("Visitors can bring seeds or simply come to learn.", "參加者可以帶種子來，也可以單純來學習。"),
    ("The event includes a beginner planting demonstration.", "活動包括適合新手的種植示範。"),
]


class AgentAdapter(Protocol):
    id: str
    version: str
    def generate(self, request: dict) -> dict: ...


class FixtureAdapter:
    id = "deterministic-preview"
    version = "1.0.0"

    def generate(self, request):
        platform, language = request["platform"], request["language"]
        if platform not in PLATFORMS or language not in LANGUAGES:
            raise ValueError("Choose a supported preview platform and language.")
        chinese = language == "繁體中文"
        facts = request["facts"]
        warnings = ["Deterministic writing preview. No language model was called."]
        unknowns = ["Timing, location, outcomes and personal experience not supplied in approved facts remain unknown."]
        if facts:
            lines = []
            for fact in facts:
                paired = next((zh for en, zh in SAMPLE_FACTS if fact["text"] == en), None)
                if chinese and paired and fact.get("fixture"):
                    lines.append(paired)
                else:
                    # Preserve unverified-language user text as attributed quotation, never fake translation.
                    lines.append(("來源原文：" if chinese else "Source note: ") + "“" + fact["text"] + "”")
                    if chinese:
                        warnings.append("Custom source quotations are preserved in their original language; translation needs review.")
            evidence = "\n".join(("• " if platform != "Threads" else "") + line for line in lines)
        else:
            evidence = ("待補充：請加入可核實的例子或來源。" if chinese else "To develop: add a verifiable example or source.")
            unknowns.append("No approved factual source was supplied. This is an idea outline, not an established claim.")
        openings = {
            "LinkedIn": ["A small idea worth a closer look.", "What would make this useful in practice?", "Start with what we can actually support."],
            "Instagram": ["Something to pause for. 🌱", "Save a little room for a new idea.", "A small starting point, with room to grow."],
            "Threads": ["A thought to open up:", "What would you add to this?", "A small idea. A useful conversation."],
        }
        zh_openings = {
            "LinkedIn": ["一個值得仔細想想的小點子。", "怎樣才能讓這個想法真正有用？", "先從有根據的資訊開始。"],
            "Instagram": ["留一點時間，讓新想法發芽。🌱", "小小的起點，也可以慢慢生長。", "今天，給自己一個新的觀察。"],
            "Threads": ["想和大家聊聊這個點子：", "你會怎樣補充這個想法？", "從一個小問題開始聊起。"],
        }
        options = (zh_openings if chinese else openings)[platform][:]
        if request.get("shortOpenings"):
            options[0] = "一個小起點。" if chinese else "A small start."
        if request.get("tone") == "direct":
            options[0] = "從這裡開始。" if chinese else "Start here."
        elif request.get("tone") == "reflective":
            options[0] = "有一個問題，值得多想一步。" if chinese else "There is a question worth sitting with."
        closing = {
            "LinkedIn": "What is one practical question you would ask before taking the next step?",
            "Instagram": "Keep this as a starting point. What would you like to explore?\n\n#Community #Learning",
            "Threads": "What is missing here? Add your perspective.",
        }
        zh_closing = {
            "LinkedIn": "在採取下一步之前，你會先問哪一個實際問題？",
            "Instagram": "先收藏這個起點。你最想探索哪一部分？\n\n#社區 #一起學習",
            "Threads": "還缺少甚麼？想聽聽你的看法。",
        }
        idea = request["idea"].strip()
        if request.get("sample") and idea == "Share the seed swap as a learning opportunity":
            idea = "一起交換種子，也交換種植心得" if chinese else "A seed swap is also a chance to exchange what we know"
        label = "主題（作者提供）：" if chinese else "Topic supplied by author: "
        topic = (label + idea) if idea else ("待確認主題" if chinese else "Topic to confirm")
        text = "\n\n".join([options[0], topic, evidence, (zh_closing if chinese else closing)[platform]])
        return {"text": text, "openings": options, "sourceIds": sorted({f["sourceId"] for f in facts}), "warnings": list(dict.fromkeys(warnings)), "unknowns": unknowns}


def routes():
    return [
        {"id": FixtureAdapter.id, "label": "Deterministic preview", "status": "tested-by-local-checks", "version": FixtureAdapter.version, "detail": "Local authored templates and approved source quotations; no model, network, credits or automatic fallback."},
        {"id": "codex", "label": "Codex", "status": "untested", "detail": "No alpha authentication, capability or model execution has been qualified. Personal Studio bindings are not reused."},
        {"id": "claude", "label": "Claude", "status": "untested", "detail": "Planned adapter; no alpha authentication or model execution tested."},
        {"id": "google", "label": "Google", "status": "untested", "detail": "Planned adapter; no alpha authentication or model execution tested."},
        {"id": "managed", "label": "PostRiff managed writing", "status": "blocked", "detail": "Provider and billing are not provisioned in this private alpha."},
    ]
