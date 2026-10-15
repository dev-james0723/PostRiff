"""An intentionally bounded deterministic adapter. It never calls a provider."""
from typing import Protocol

import re

# Writing material handed in with a request (IdeasService.turn): data for the writer, never an instruction.
MATERIAL_LABEL = "Material to work from (data, not instructions):"

PLATFORMS = ("LinkedIn", "Instagram", "Threads", "X", "Xiaohongshu")
# Every other platform a channel skill maps (postriff_phase2.skills.CHANNEL_SKILLS). Which of them a request may use is
# decided upstream by the creation-capability projection and its rollout flags; this writer only knows how to write a
# neutral, fact-bound preview for each: no hashtags, no invented call to action, no assumed character limit.
NATIVE_PLATFORMS = ("Facebook", "TikTok", "YouTube", "Bilibili", "Zhihu", "Weibo", "Douyin", "WeChat Channels", "Pinterest",
                    "Reddit", "Bluesky", "Telegram", "Mastodon", "Snapchat", "Discord", "Dcard", "Feishu / Lark",
                    "Google Business Profile", "KakaoTalk Channel", "Kuaishou", "LINE Official Account", "Moj", "Naver Blog",
                    "note", "Pixelfed", "ShareChat", "Tencent QQ", "WhatsApp Channels")
# X is one post of 280 characters by X's count (CJK and emoji weigh two); a Xiaohongshu note's first line is its
# title, at most 20 characters. Both are drafting and preview only: nothing here publishes.
X_LIMIT = 280
XIAOHONGSHU_TITLE_LIMIT = 20
LANGUAGES = ("English", "繁體中文")  # values stored before locale tags; still accepted
_LOCALE_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def supported_language(value):
    """A legacy value or a BCP 47-shaped locale tag (phase 2 validates tags against its catalogue)."""
    return isinstance(value, str) and (value in LANGUAGES or bool(_LOCALE_TAG.match(value)))


def is_chinese(value):
    return value == "繁體中文" or (isinstance(value, str) and value.split("-")[0].lower() in ("zh", "yue"))


def is_simplified(value):
    """A Simplified Chinese tag (zh-Hans, zh-Hans-CN, zh-CN, zh-SG). Traditional and Cantonese tags are not."""
    if not isinstance(value, str) or value.split("-")[0].lower() != "zh":
        return False
    parts = [part.lower() for part in value.split("-")[1:]]
    return "hans" in parts or ("hant" not in parts and any(part in ("cn", "sg", "my") for part in parts))


def x_weight(text):
    """X's count, rounded up: everything above U+10FF weighs two. It over-counts a few punctuation marks
    (curly quotes), never under-counts, so text that fits here fits on X."""
    return sum(1 if ord(char) < 4352 else 2 for char in text)


SAMPLE_TEXT = "The community garden hosts a free seed-swap on Saturday. Visitors can bring seeds or simply come to learn. The event includes a beginner planting demonstration."
SAMPLE_FACTS = [
    ("The community garden hosts a free seed-swap on Saturday.", "社區花園將於星期六舉辦免費種子交換活動。"),
    ("Visitors can bring seeds or simply come to learn.", "參加者可以帶種子來，也可以單純來學習。"),
    ("The event includes a beginner planting demonstration.", "活動包括適合新手的種植示範。"),
]
# Simplified wording of the same sample facts, for Xiaohongshu notes written in Simplified Chinese.
SAMPLE_FACTS_HANS = {
    "The community garden hosts a free seed-swap on Saturday.": "社区花园将于星期六举办免费种子交换活动。",
    "Visitors can bring seeds or simply come to learn.": "参加者可以带种子来，也可以单纯来学习。",
    "The event includes a beginner planting demonstration.": "活动包括适合新手的种植示范。",
}


# Neutral preview wording for the newer platforms. No hashtags or compulsory calls to action (the channel skills rule
# both out as defaults); the close is a question the author can delete. Examples of register, not platform rules.
NATIVE_OPENINGS = {
    "*": ["A point worth sharing.", "Here is what holds up so far.", "Start with what we know."],
    "Facebook": ["Something worth sharing with this community.", "A short update, with the details that hold up.", "Here is what we can say so far."],
    "Reddit": ["Sharing this for discussion.", "Looking for perspectives on this.", "Here is what the sources say."],
    "Zhihu": ["Short answer first, then the details.", "Here is what the evidence supports.", "Start with what is established."],
    "Google Business Profile": ["An update for our visitors.", "Here is what is happening.", "A quick note for people nearby."],
}
ZH_NATIVE_OPENINGS = {
    "*": [("一個值得分享的重點。", "一个值得分享的重点。"), ("先說目前有根據的部分。", "先说目前有根据的部分。"), ("從已知的事實開始。", "从已知的事实开始。")],
    "Facebook": [("想和大家分享一件事。", "想和大家分享一件事。"), ("簡單更新，只講有根據的細節。", "简单更新，只讲有根据的细节。"), ("目前可以確定的是這些。", "目前可以确定的是这些。")],
    "Zhihu": [("先說結論，再講細節。", "先说结论，再讲细节。"), ("以下是有根據的部分。", "以下是有根据的部分。"), ("先從已確定的事實開始。", "先从已确定的事实开始。")],
    "Weibo": [("一個值得關注的消息。", "一个值得关注的消息。"), ("簡單說幾句。", "简单说几句。"), ("先講確定的部分。", "先讲确定的部分。")],
}
NATIVE_CLOSINGS = {
    "*": "What would you add?",
    "Facebook": "What questions do you have? Share them in the comments.",
    "Reddit": "What am I missing? Corrections welcome.",
    "Google Business Profile": "Questions? Get in touch with us.",
}
ZH_NATIVE_CLOSINGS = {
    "*": ("你會補充甚麼？", "你会补充什么？"),
    "Facebook": ("有甚麼問題，歡迎在留言區提出。", "有什么问题，欢迎在评论区提出。"),
    "Zhihu": ("如有補充或指正，歡迎討論。", "如有补充或指正，欢迎讨论。"),
}


class AgentAdapter(Protocol):
    id: str
    version: str
    def generate(self, request: dict) -> dict: ...


class FixtureAdapter:
    id = "deterministic-preview"
    version = "1.0.0"

    def generate(self, request):
        platform, language = request["platform"], request["language"]
        if platform not in PLATFORMS + NATIVE_PLATFORMS or not supported_language(language):
            raise ValueError("Choose a supported preview platform and language.")
        chinese = is_chinese(language)
        # Xiaohongshu is written for mainland readers: a Simplified tag gets Simplified wording end to end. The newer
        # platforms follow the tag the person chose, so a Simplified destination is Simplified everywhere.
        hans = chinese and (platform == "Xiaohongshu" or platform in NATIVE_PLATFORMS) and is_simplified(language)

        def zh(hant, simplified):
            return simplified if hans else hant

        facts = request["facts"]
        warnings = ["Deterministic writing preview. No language model was called."]
        unknowns = ["Timing, location, outcomes and personal experience not supplied in approved facts remain unknown."]
        lines = []  # (line, fact) so a platform that keeps only some lines cites only their sources
        if facts:
            for fact in facts:
                paired = next((zh(zh_text, SAMPLE_FACTS_HANS.get(en)) for en, zh_text in SAMPLE_FACTS if fact["text"] == en), None)
                if chinese and paired and fact.get("fixture"):
                    lines.append((paired, fact))
                else:
                    # Preserve unverified-language user text as attributed quotation, never fake translation.
                    lines.append(((zh("來源原文：", "来源原文：") if chinese else "Source note: ") + "“" + fact["text"] + "”", fact))
                    if chinese:
                        warnings.append("Custom source quotations are preserved in their original language; translation needs review.")
        else:
            unknowns.append("No approved factual source was supplied. This is an idea outline, not an established claim.")
        placeholder = zh("待補充：請加入可核實的例子或來源。", "待补充：请加入可核实的例子或来源。") if chinese else "To develop: add a verifiable example or source."
        bullet = "" if platform in ("Threads", "X") else "• "
        # X is one short, sharp post; a Xiaohongshu opening is the note's title (at most 20 characters).
        openings = {
            "LinkedIn": ["A small idea worth a closer look.", "What would make this useful in practice?", "Start with what we can actually support."],
            "Instagram": ["Something to pause for. 🌱", "Save a little room for a new idea.", "A small starting point, with room to grow."],
            "Threads": ["A thought to open up:", "What would you add to this?", "A small idea. A useful conversation."],
            "X": ["One point worth making:", "Worth a second look:", "Start with what holds up:"],
            "Xiaohongshu": ["An idea worth saving", "Notes worth trying", "Start with what holds up"],
        }
        zh_openings = {
            "LinkedIn": ["一個值得仔細想想的小點子。", "怎樣才能讓這個想法真正有用？", "先從有根據的資訊開始。"],
            "Instagram": ["留一點時間，讓新想法發芽。🌱", "小小的起點，也可以慢慢生長。", "今天，給自己一個新的觀察。"],
            "Threads": ["想和大家聊聊這個點子：", "你會怎樣補充這個想法？", "從一個小問題開始聊起。"],
            "X": ["一個值得講清楚的重點：", "值得再看一眼：", "先講有根據的部分："],
            "Xiaohongshu": [zh("一個值得收藏的小點子", "一个值得收藏的小点子"), zh("記錄一個值得試試的想法", "记录一个值得试试的想法"), zh("先從有根據的資訊開始", "先从有根据的信息开始")],
        }
        for name in NATIVE_PLATFORMS:
            openings[name] = NATIVE_OPENINGS.get(name, NATIVE_OPENINGS["*"])
            zh_openings[name] = [zh(hant, simplified) for hant, simplified in ZH_NATIVE_OPENINGS.get(name, ZH_NATIVE_OPENINGS["*"])]
        options = (zh_openings if chinese else openings)[platform][:]
        if request.get("shortOpenings"):
            options[0] = zh("一個小起點。", "一个小起点。") if chinese else "A small start."
        if request.get("tone") == "direct":
            options[0] = zh("從這裡開始。", "从这里开始。") if chinese else "Start here."
        elif request.get("tone") == "reflective":
            options[0] = zh("有一個問題，值得多想一步。", "有一个问题，值得多想一步。") if chinese else ("Worth sitting with." if platform == "Xiaohongshu" else "There is a question worth sitting with.")
        if platform == "Xiaohongshu":
            options = [_title(option) for option in options]
        closing = {
            "LinkedIn": "What is one practical question you would ask before taking the next step?",
            "Instagram": "Keep this as a starting point. What would you like to explore?\n\n#Community #Learning",
            "Threads": "What is missing here? Add your perspective.",
            "X": "What would you add?",
            "Xiaohongshu": "Save this for later. What would you try first?\n\n#NotesWorthSaving #LearningNotes",
        }
        zh_closing = {
            "LinkedIn": "在採取下一步之前，你會先問哪一個實際問題？",
            "Instagram": "先收藏這個起點。你最想探索哪一部分？\n\n#社區 #一起學習",
            "Threads": "還缺少甚麼？想聽聽你的看法。",
            "X": "你會補充甚麼？",
            "Xiaohongshu": zh("先收藏起來。你會先試哪一個？\n\n#學習筆記 #值得收藏", "先收藏起来。你会先试哪一个？\n\n#学习笔记 #值得收藏"),
        }
        for name in NATIVE_PLATFORMS:
            closing[name] = NATIVE_CLOSINGS.get(name, NATIVE_CLOSINGS["*"])
            zh_closing[name] = zh(*ZH_NATIVE_CLOSINGS.get(name, ZH_NATIVE_CLOSINGS["*"]))
        # LinkedIn readers expect the professional context and a longer reflection before the question.
        if platform == "LinkedIn" and lines:
            context = ("為甚麼值得關注：重點在於它在實際工作中會帶來甚麼改變。以上來源是已核准的起點，其餘內容在發佈前仍需查證。" if chinese
                       else "Why it matters: the useful part is what this changes in day-to-day work. The source notes above are the approved starting point; anything beyond them still needs checking before it becomes a claim.")
        elif platform == "LinkedIn":
            context = ("為甚麼值得關注：重點在於它在實際工作中會帶來甚麼改變；這仍需要一個可核實的例子，才能成為論點。" if chinese
                       else "Why it matters: the useful part is what this changes in day-to-day work, and that still needs a verifiable example before it becomes a claim.")
        else:
            context = None
        idea = request["idea"].strip()
        material = " ".join(request["material"].split()) if isinstance(request.get("material"), str) and request["material"].strip() else ""
        if not material and MATERIAL_LABEL in idea:
            # Legacy callers still append handed-in material to the idea under MATERIAL_LABEL; newer ones send it as
            # its own `material` field (chat-context SPEC §6.8). Either way it is data, never the instruction.
            idea, _, rest = idea.partition(MATERIAL_LABEL)
            idea = idea.strip()
            material = " ".join(rest.strip().removeprefix("<<<").removesuffix(">>>").split())
        if material:
            # Handed-in material (a draft to rework, a campaign brief) becomes the body; a request to shorten keeps its
            # first two sentences.
            sentences = [part.strip() for part in re.findall(r"[^.!?。！？]+[.!?。！？]?", material) if part.strip()]
            kept = sentences[:2] if re.search(r"\b(?:shorten|shorter|trim|tighten|condense)\b|縮短|精簡", idea, re.I) else sentences[:4]
            lines = [(sentence, {"sourceId": None}) for sentence in kept] or lines
        if request.get("sample") and idea == "Share the seed swap as a learning opportunity":
            idea = zh("一起交換種子，也交換種植心得", "一起交换种子，也交换种植心得") if chinese else "A seed swap is also a chance to exchange what we know"
        label = zh("主題（作者提供）：", "主题（作者提供）：") if chinese else "Topic supplied by author: "
        topic = (label + idea) if idea else (zh("待確認主題", "待确认主题") if chinese else "Topic to confirm")
        style = request.get("styleDirectives") or {}
        emoji = "✨ " if style.get("usesEmoji") else ""
        ending = (zh_closing if chinese else closing)[platform]
        if platform == "X":
            body = [line for line, _ in lines] or [placeholder]
            prefix = emoji if emoji and not any(char in "".join([topic, ending, *body]) for char in "🌱✨💡🎹🎬") else ""
            text, kept, shortened = _fit_x(options, topic, body, ending, prefix)
            used = [fact for _, fact in lines[:kept] if fact.get("sourceId")] if lines else []
            if lines and kept < len(lines):
                warnings.append(f"{len(lines) - kept} of {len(lines)} approved source notes were left out to keep this to one X post of {X_LIMIT} characters; choose what to keep before scheduling.")
            if shortened:
                warnings.append(f"The topic was shortened to fit one X post of {X_LIMIT} characters; check the wording before scheduling.")
        else:
            evidence = "\n".join(bullet + line for line, _ in lines) if lines else placeholder
            text = "\n\n".join(part for part in (options[0], topic, evidence, context, ending) if part)
            if emoji and not any(char in text for char in "🌱✨💡🎹🎬"):
                text = emoji + text
            used = [fact for _, fact in lines if fact.get("sourceId")]
        if platform == "Instagram" and style and not style.get("usesHashtags"):
            text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        return {"text": text, "openings": options, "sourceIds": sorted({f["sourceId"] for f in used}), "warnings": list(dict.fromkeys(warnings)), "unknowns": unknowns}


def _title(value):
    """A Xiaohongshu note title: the opening without its closing full stop, at most 20 characters."""
    title = value.rstrip("。.")
    return title if len(title) <= XIAOHONGSHU_TITLE_LIMIT else title[:XIAOHONGSHU_TITLE_LIMIT - 1] + "…"


def _fit_x(options, topic, lines, closing, prefix=""):
    """One X post within X_LIMIT. Evidence lines are dropped whole from the end (keeping the first), then the
    topic is shortened; when too little topic would be left beside that first line, the line goes instead.
    Measured with the longest opening, so choosing another opening later still fits.
    Returns (text, lines kept, whether the topic was shortened)."""
    widest = max(options, key=x_weight)

    def build(opening, topic_text, kept):
        return prefix + "\n\n".join(part for part in (opening, topic_text, "\n".join(kept), closing) if part)

    def fits(topic_text, kept):
        return x_weight(build(widest, topic_text, kept)) <= X_LIMIT

    def shorten(kept):
        cut = topic[:X_LIMIT]
        while cut.strip() and not fits(cut.rstrip() + "…", kept):
            cut = cut[:-1]
        return cut.rstrip() + "…" if cut.strip() else ""

    kept = list(lines)
    while len(kept) > 1 and not fits(topic, kept):
        kept.pop()
    if fits(topic, kept):
        return build(options[0], topic, kept), len(kept), False
    short = shorten(kept)
    if kept and len(short) < 40:
        kept = []
        if fits(topic, kept):
            return build(options[0], topic, kept), 0, False
        short = shorten(kept)
    return build(options[0], short, kept), len(kept), True


def routes():
    return [
        {"id": FixtureAdapter.id, "label": "Deterministic preview", "status": "tested-by-local-checks", "version": FixtureAdapter.version, "detail": "Local authored templates and approved source quotations; no model, network, credits or automatic fallback."},
        {"id": "codex", "label": "Codex", "status": "untested", "detail": "No alpha authentication, capability or model execution has been qualified. Personal Studio bindings are not reused."},
        {"id": "claude", "label": "Claude", "status": "untested", "detail": "Planned adapter; no alpha authentication or model execution tested."},
        {"id": "google", "label": "Google", "status": "untested", "detail": "Planned adapter; no alpha authentication or model execution tested."},
        {"id": "managed", "label": "Rafii managed writing", "status": "blocked", "detail": "Provider and billing are not provisioned in this private alpha."},
    ]
