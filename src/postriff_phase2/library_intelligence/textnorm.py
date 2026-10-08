"""Versioned multilingual normalization for lexical search (engineering spec §8).

Postgres `simple` tsvector sees an unspaced CJK run as one token, and English stemming is wrong for Chinese. Segments
store `search_terms`: NFKC + casefold Latin words, plus CJK unigrams and overlapping bigrams after folding Simplified
to Traditional (the more specific script), so 演奏会/演奏會 and mixed Cantonese/English text match the same terms. The
raw text is never altered: this only feeds the index. NORMALIZER_VERSION is stored per segment; a change requires a
reindex of that generation, never a silent mixture.
"""
from __future__ import annotations

import re
import unicodedata

NORMALIZER_VERSION = 1
MAX_TERMS = 4000

# Common Simplified -> Traditional folds (characters frequent in creator/brand/music text). The mapping only folds
# characters for matching; it never rewrites stored content. Owned by the retrieval workstream; extend with tests.
_S2T_PAIRS = (
    "会會 乐樂 演演 奏奏 门門 们們 这這 个個 来來 时時 间間 为為 说說 对對 发發 现現 动動 后後 经經 过過 还還 进進 开開 关關 于於 与與 业業 东東 两兩 "
    "长長 问問 题題 学學 习習 书書 读讀 写寫 听聽 见見 观觀 视視 记記 录錄 报報 纸紙 网網 页頁 线線 节節 课課 师師 练練 钢鋼 琴琴 曲曲 谱譜 声聲 音音 "
    "调調 级級 场場 厅廳 剧劇 团團 队隊 员員 艺藝 术術 欢歡 迎迎 谢謝 请請 让讓 认認 识識 讲講 话話 语語 词詞 汉漢 国國 际際 华華 区區 历歷 "
    "广廣 东東 湾灣 岛島 湾灣 门門 澳澳 号號 码碼 电電 话話 邮郵 购購 买買 卖賣 价價 钱錢 费費 单單 账賬 预預 约約 订訂 务務 产產 品品 "
    "质質 量量 标標 准準 设設 计計 图圖 样樣 颜顏 色色 风風 格格 简簡 体體 繁繁 旧舊 新新 张張 片片 视視 频頻 拍拍 摄攝 剪剪 辑輯 "
    "资資 料料 档檔 案案 库庫 组組 织織 级級 别別 类類 项項 目目 务務 实實 际際 验驗 证證 确確 认認 应應 该該 么麼 吗嗎 呢呢 吧吧 "
    "们們 爱愛 恋戀 亲親 妈媽 爷爺 孙孫 儿兒 岁歲 龄齡 寿壽 喜喜 欢歡 乐樂 难難 简簡 单單 复複 杂雜 断斷 续續 继繼 统統 "
    "传傳 统統 现現 代代 选選 择擇 决決 定定 准準 备備 办辦 处處 理理 结結 果果 变變 化化 运運 营營 销銷 广廣 告告 赛賽 获獲 奖獎 "
    "领領 导導 专專 业業 运運 气氣 时時 钟鐘 点點 钟鐘 末末 晚晚 场場 门門 票票 观觀 众眾 场場 馆館 闻聞 乐樂 队隊 "
    "评評 论論 赞贊 转轉 发發 帖帖 关關 注注 粉粉 丝絲 账帳 户戶 登登 录錄 链鏈 接接 邮郵 箱箱 无無 个個 万萬 亿億 两兩 几幾 "
    "饭飯 馆館 鸡雞 鱼魚 肉肉 汤湯 茶茶 酒酒 车車 轮輪 铁鐵 飞飛 机機 场場 站站 楼樓 层層 园園 区區 县縣 镇鎮 乡鄉 "
)
S2T = {}
for pair in _S2T_PAIRS.split():
    if len(pair) == 2 and pair[0] != pair[1]:
        S2T.setdefault(pair[0], pair[1])

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]")
TOKEN = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]+|[0-9a-zÀ-ɏ]+(?:['’][a-z]+)?")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(S2T.get(ch, ch) for ch in text)


def _cjk_terms(run: str) -> list[str]:
    chars = list(run)
    out = list(chars)
    out += [a + b for a, b in zip(chars, chars[1:])]
    return out


def tokens(text: str) -> list[str]:
    """Index terms for one text: Latin words, digits and CJK unigrams+bigrams. Order preserved, duplicates kept
    once, bounded to MAX_TERMS so a huge segment cannot bloat the index row."""
    seen, out = set(), []
    for match in TOKEN.finditer(fold(text)):
        piece = match.group(0)
        terms = _cjk_terms(piece) if CJK.match(piece) else [piece.replace("’", "'")]
        for term in terms:
            if term not in seen:
                seen.add(term)
                out.append(term)
                if len(out) >= MAX_TERMS:
                    return out
    return out


def search_terms(text: str) -> str:
    """The stored `pr_library_segments.search_terms` value (space separated, safe for to_tsvector('simple'))."""
    return " ".join(tokens(text))


def query_terms(query: str) -> list[str]:
    """Terms a query must match. CJK runs use bigrams (single characters only for one-character runs) so a short
    phrase stays precise; Latin words match whole terms."""
    out = []
    for match in TOKEN.finditer(fold(query)):
        piece = match.group(0)
        if CJK.match(piece):
            out += [piece] if len(piece) == 1 else [a + b for a, b in zip(piece, piece[1:])]
        else:
            out.append(piece.replace("’", "'"))
    return list(dict.fromkeys(out))[:64]


def tsquery(query: str) -> str | None:
    """A to_tsquery('simple', …) string built only from normalized terms (no user operators reach Postgres)."""
    terms = [re.sub(r"[^0-9a-zÀ-ɏ㐀-䶿一-鿿豈-﫿぀-ヿ가-힯']", "", t) for t in query_terms(query)]
    terms = [t.replace("'", "") for t in terms if t.replace("'", "")]
    return " & ".join(terms) if terms else None
