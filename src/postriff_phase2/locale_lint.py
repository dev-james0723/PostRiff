"""Reminders about a draft's language (docs/postriff-worldwide-languages-plan.md §8).

Three kinds: characters from the other Chinese script, words that belong to another region, and
local rules a post may run into. Each becomes a warning on the draft the person can check and
acknowledge; none fails a run or blocks scheduling on its own. Word lists are short on purpose:
they come from the regional research (docs/postriff-language-registers.md) and only flag what a
local reader would notice straight away.
"""
from __future__ import annotations

import re

from . import locales
from .contracts import LIMITS

# Simplified-only / Traditional-only pairs in common use. Characters valid in both scripts (后, 里, 台, 只…) are left out.
_PAIRS = ("这這 们們 说說 时時 为為 个個 来來 会會 发發 对對 过過 还還 没沒 样樣 实實 经經 动動 进進 开開 关關 问問 间間 现現 学學 长長 "
          "东東 车車 书書 两兩 门門 买買 卖賣 边邊 让讓 从從 给給 爱愛 听聽 见見 觉覺 读讀 写寫 话話 语語 请請 谢謝 钱錢 电電 视視 频頻 网網 "
          "络絡 应應 该該 认認 识識 专專 业業 务務 员員 场場 报報 纸紙 乐樂 欢歡 头頭 脑腦 难難 题題 气氣 节節 岁歲 医醫 药藥 饭飯 馆館 鸡雞 "
          "鱼魚 岛島 广廣 国國 华華 汉漢 历歷 风風 飞飛 马馬 鸟鳥 龙龍 灯燈 热熱 办辦 课課 练練 习習 钢鋼 弹彈 厅廳 剧劇 团團 众眾 观觀 摄攝 "
          "纪紀 录錄 转轉 载載 标標 帮幫").split()
SIMPLIFIED_ONLY = {pair[0] for pair in _PAIRS}
TRADITIONAL_ONLY = {pair[1] for pair in _PAIRS}

_GB_FROM_US = {"color": "colour", "colors": "colours", "favorite": "favourite", "favorites": "favourites", "center": "centre",
               "theater": "theatre", "practicing": "practising", "traveled": "travelled", "traveling": "travelling", "gray": "grey",
               "jewelry": "jewellery", "catalog": "catalogue"}
_US_FROM_GB = {"colour": "color", "colours": "colors", "favourite": "favorite", "favourites": "favorites", "centre": "center",
               "theatre": "theater", "practising": "practicing", "travelled": "traveled", "travelling": "traveling", "programme": "program",
               "grey": "gray", "jewellery": "jewelry", "catalogue": "catalog"}
_LATAM_SPANISH = {"vosotros": "ustedes", "ordenador": "computadora", "zumo": "jugo", "coger": "tomar or agarrar (coger is vulgar in much of Latin America)"}
# Written the other way round on purpose: each key is the word a reader in that region would notice.
REGION_WORDS = {
    "zh-Hant-TW": {"軟件": "軟體", "視頻": "影片", "的士": "計程車", "質素": "品質", "網絡": "網路", "打印機": "印表機", "讚好": "按讚"},
    "zh-Hant-HK": {"軟體": "軟件", "計程車": "的士", "網路": "網絡", "印表機": "打印機", "按讚": "讚好"},
    "yue-Hant-HK": {"軟體": "軟件", "計程車": "的士", "網路": "網絡", "印表機": "打印機", "按讚": "讚好"},
    "zh-Hans-CN": {"软体": "软件", "网路": "网络", "计程车": "出租车", "讯息": "信息", "印表机": "打印机", "按赞": "点赞"},
    "en-GB": _GB_FROM_US, "en-GB-scotland": _GB_FROM_US, "en-IE": _GB_FROM_US, "en-AU": _GB_FROM_US, "en-NZ": _GB_FROM_US,
    "en-US": _US_FROM_GB,
    "pt-BR": {"telemóvel": "celular", "autocarro": "ônibus", "ecrã": "tela", "equipa": "equipe", "utilizador": "usuário", "pequeno-almoço": "café da manhã", "comboio": "trem"},
    "pt-PT": {"ônibus": "autocarro", "celular": "telemóvel", "usuário": "utilizador", "café da manhã": "pequeno-almoço", "trem": "comboio"},
    "es-MX": _LATAM_SPANISH, "es-419": _LATAM_SPANISH, "es-AR": _LATAM_SPANISH, "es-CO": _LATAM_SPANISH, "es-US": _LATAM_SPANISH,
    "es-ES": {"computadora": "ordenador", "celular": "móvil", "jugo": "zumo"},
}
_CN_ABSOLUTE_CLAIMS = re.compile(r"国家级|國家級|最高级|最高級|最佳|顶级|頂級|第一品牌")
_OFF_PLATFORM = re.compile(r"微信|wechat|\bvx\b|\bwx\b|加我|电话|電話|\+?\d[\d\s-]{7,}\d", re.I)
_JP_PRICE_WITHOUT_TAX = re.compile(r"\d[\d,]*\s*円(?!\s*[（(]?\s*税込)")
_SEPARATED = re.compile(r"[a-zà-ÿ-]", re.I)


def _found(text, word):
    if word.isascii() or _SEPARATED.match(word[0]):
        return re.search(r"(?<![\wà-ÿ-])" + re.escape(word) + r"(?![\wà-ÿ-])", text, re.I) is not None
    return word in text


def reminders(text, language, platform=None):
    """Warnings for one draft. `language` is its locale tag (legacy values are read too)."""
    text = text if isinstance(text, str) else ""
    tag = locales.canonical(language) or ""
    warnings = []
    script = tag.split("-")[1] if tag.count("-") >= 1 and len(tag.split("-")[1]) == 4 else None
    if tag.startswith(("zh-Hant", "yue")) or script == "Hant":
        wrong = sorted({ch for ch in text if ch in SIMPLIFIED_ONLY})
        if len(wrong) >= 2:
            warnings.append(f"Some characters are Simplified ({'、'.join(wrong[:5])}) in a Traditional Chinese draft; check them before posting.")
    elif tag.startswith("zh-Hans") or script == "Hans":
        wrong = sorted({ch for ch in text if ch in TRADITIONAL_ONLY})
        if len(wrong) >= 2:
            warnings.append(f"Some characters are Traditional ({'、'.join(wrong[:5])}) in a Simplified Chinese draft; check them before posting.")
    words = [(word, better) for word, better in REGION_WORDS.get(tag, {}).items() if _found(text, word)]
    if words:
        listed = ", ".join(f"{word} → {better}" for word, better in words[:4])
        warnings.append(f"Some words read as another region for {locales.display(tag)}: {listed}.")
    if tag == "zh-Hans-CN" and _CN_ABSOLUTE_CLAIMS.search(text):
        warnings.append("Mainland advertising law bans absolute claims such as 国家级 or 最佳 in promotions; check this wording if the post promotes anything.")
    if tag == "ja-JP" and _JP_PRICE_WITHOUT_TAX.search(text):
        warnings.append("Prices shown to consumers in Japan must include tax (税込); check the price before posting.")
    if platform == "Xiaohongshu" and _OFF_PLATFORM.search(text):
        warnings.append("Xiaohongshu limits posts that send people off the platform (WeChat IDs, phone numbers); a post that does can be hidden.")
    # A note's first line is its title (the preview shows it that way); Xiaohongshu cuts titles at 20 characters.
    title_limit = (LIMITS.get(platform) or {}).get("title")
    title = text.strip().split("\n", 1)[0].strip() if text.strip() else ""
    if title_limit and len(title) > title_limit:
        warnings.append(f"The first line is this {platform} note's title: {len(title)} characters, over the {title_limit}-character title limit. Shorten it before posting.")
    return warnings
