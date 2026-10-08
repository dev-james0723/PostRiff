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
# Retrieval workstream extension (T04, 2026-10-08): more frequent Simplified -> Traditional pairs.
_S2T_MORE = (
    "优優 伟偉 伤傷 举舉 义義 乌烏 乔喬 乱亂 争爭 亏虧 亚亞 亩畝 仅僅 从從 仑侖 仓倉 仪儀 伞傘 伪偽 佣傭 侠俠 侣侶 侦偵 侧側 侨僑 俭儉 "
    "债債 倾傾 偿償 储儲 兑兌 党黨 兰蘭 兴興 养養 兽獸 内內 册冊 军軍 农農 冯馮 冻凍 净淨 凉涼 减減 凤鳳 凭憑 凯凱 击擊 刘劉 则則 刚剛 "
    "创創 删刪 刹剎 剂劑 剑劍 劝勸 励勵 劲勁 劳勞 势勢 勋勳 协協 卢盧 卫衛 却卻 厂廠 压壓 厌厭 厕廁 厨廚 参參 双雙 叙敘 叠疊 叹嘆 吓嚇 "
    "吕呂 启啟 吴吳 呐吶 呜嗚 咏詠 哑啞 响響 哗嘩 唤喚 啰囉 啸嘯 喷噴 嘱囑 围圍 圆圓 圣聖 坏壞 块塊 坚堅 坛壇 坝壩 坟墳 垒壘 垦墾 墙牆 "
    "壮壯 壳殼 够夠 头頭 夹夾 夺奪 奋奮 妆妝 妇婦 娱娛 娄婁 婴嬰 宁寧 宝寶 宠寵 审審 宪憲 宽寬 宾賓 寻尋 将將 尔爾 尘塵 尝嘗 属屬 岂豈 "
    "岗崗 岭嶺 峡峽 币幣 帐帳 带帶 帮幫 庄莊 庆慶 废廢 异異 弃棄 弯彎 归歸 彻徹 径徑 忆憶 忧憂 怜憐 总總 恳懇 悦悅 惧懼 惨慘 惩懲 愤憤 "
    "愿願 戏戲 战戰 执執 扩擴 扰擾 抚撫 抢搶 护護 拟擬 拦攔 挂掛 挡擋 挤擠 挥揮 捞撈 损損 换換 据據 掷擲 揽攬 摊攤 撑撐 攒攢 敛斂 斋齋 "
    "斩斬 旷曠 昼晝 显顯 晋晉 晒曬 晓曉 暂暫 杀殺 权權 极極 构構 栋棟 栏欄 树樹 桥橋 梦夢 检檢 欧歐 歼殲 毁毀 毕畢 毙斃 泼潑 泻瀉 洒灑 "
    "浅淺 浆漿 浇澆 浊濁 测測 济濟 浏瀏 浑渾 涌湧 涛濤 渊淵 渐漸 渔漁 滞滯 滤濾 滥濫 滨濱 潜潛 澜瀾 灭滅 灿燦 烂爛 烛燭 烟煙 烦煩 烧燒 "
    "热熱 焕煥 犹猶 狭狹 猎獵 玛瑪 环環 琼瓊 疯瘋 痒癢 痴癡 盏盞 监監 盐鹽 盘盤 矿礦 砖磚 础礎 碍礙 祷禱 禅禪 秃禿 积積 称稱 稣穌 稳穩 "
    "穷窮 窃竊 竖豎 笋筍 筹籌 箩籮 粪糞 紧緊 纠糾 纤纖 纬緯 纵縱 纷紛 纹紋 纺紡 绅紳 绑綁 绒絨 绕繞 绘繪 绣繡 绳繩 缓緩 缝縫 缠纏 罢罷 "
    "罗羅 翘翹 耻恥 聋聾 肤膚 肿腫 胀脹 胆膽 胁脅 脉脈 腊臘 舰艦 舱艙 芦蘆 苍蒼 茧繭 荡蕩 荣榮 荫蔭 莲蓮 莹瑩 萝蘿 蔼藹 虫蟲 虾蝦 蚀蝕 "
    "蚁蟻 蛮蠻 蜡蠟 衔銜 补補 衬襯 袭襲 装裝 规規 览覽 觉覺 诊診 谊誼 谋謀 谎謊 谜謎 谣謠 谦謙 谨謹 贡貢 贤賢 贴貼 贷貸 贺賀 赋賦 赔賠 "
    "赖賴 赠贈 赵趙 轨軌 轩軒 软軟 轰轟 辈輩 输輸 辞辭 辩辯 迹跡 适適 逊遜 遥遙 邹鄒 郁鬱 酿釀 鉴鑑 钓釣 钞鈔 钥鑰 钩鉤 铃鈴 铜銅 铭銘 "
    "铺鋪 锅鍋 锋鋒 锐銳 锦錦 闪閃 闯闖 闸閘 阁閣 阔闊 阶階 陕陝 隶隸 雳靂 靓靚 韵韻 顽頑 颁頒 颂頌 颗顆 颠顛 饥飢 饰飾 饺餃 饼餅 馈饋 "
    "马馬 驳駁 驻駐 驼駝 骂罵 骄驕 骗騙 骚騷 鲁魯 鸣鳴 鹅鵝 鹰鷹 红紅 纪紀 纯純 纳納 细細 终終 绍紹 给給 络絡 绝絕 绩績 维維 综綜 绿綠 "
    "编編 缘緣 缩縮 职職 联聯 聪聰 肃肅 胜勝 胶膠 脑腦 脚腳 脸臉 艰艱 苏蘇 苹蘋 荐薦 药藥 莱萊 蓝藍 虑慮 虽雖 誉譽 训訓 议議 访訪 诉訴 "
    "译譯 试試 诗詩 诚誠 询詢 详詳 误誤 谁誰 谈談 贝貝 负負 财財 责責 败敗 货貨 贵貴 贸貿 赏賞 赢贏 赶趕 趋趨 跃躍 践踐 踪蹤 轻輕 载載 "
    "较較 辅輔 辆輛 辉輝 边邊 达達 迁遷 远遠 连連 迟遲 递遞 逻邏 遗遺 邓鄧 邻鄰 郑鄭 酱醬 释釋 针針 银銀 锁鎖 错錯 键鍵 镜鏡 闭閉 闲閒 "
    "闹鬧 阅閱 阳陽 阴陰 阵陣 陆陸 陈陳 险險 随隨 隐隱 雾霧 静靜 韩韓 顶頂 顺順 须須 顾顧 顿頓 额額 饮飲 饱飽 驱驅 驾駕 骑騎 鲜鮮 鸟鳥 "
    "鸭鴨 麦麥 黄黃 齐齊 齿齒 龙龍 龟龜 怀懷 杰傑 弥彌 弹彈 强強 当當 态態 恶惡 惊驚 惯慣 扫掃 扬揚 担擔 拥擁 敌敵 数數 杨楊 枪槍 沟溝 "
    "没沒 泪淚 泽澤 洁潔 浓濃 涂塗 润潤 涨漲 温溫 湿濕 满滿 滚滾 灯燈 灵靈 灾災 炉爐 炼煉 牵牽 状狀 独獨 狮獅 猫貓 献獻 琐瑣 画畫 畅暢 "
    "疗療 皱皺 盖蓋 睁睜 矫矯 硕碩 礼禮 祸禍 离離 种種 笔筆 笼籠 筑築 签簽 篮籃 粮糧 揾搵 揿撳 咸鹹 着著 干乾 里裡 冲沖 尽盡 余餘 云雲 "
    "叶葉 汇匯 脏髒"
)
# Traditional variants and one-to-many Simplified characters fold to one canonical form, so 頭髮/头发, 幹部/干部,
# 關係/关系, 臺灣/台湾 and 帳戶/账户 match. Folding only affects matching; stored text is never rewritten.
_VARIANT_PAIRS = (
    "髮發 幹乾 係系 繫系 臺台 颱台 檯台 麵面 麪面 裏裡 鬆松 範范 衝沖 儘盡 誌志 徵征 週周 鬥斗 捲卷 採采 醜丑 穀谷 緻致 纔才 錶表 闆板 "
    "薑姜 鬍胡 迴回 彙匯 穫獲 臟髒 曆歷 鍾鐘 復複 籤簽 嚐嘗 歎嘆 菸煙 噁惡 製制 帳賬 麽麼 綫線 爲為 衞衛 啓啟 眞真 峯峰 羣群 僞偽 敎教 "
    "鷄雞 牀床 綉繡 舖鋪 衆眾"
)
S2T = {}
for pair in (_S2T_PAIRS + " " + _S2T_MORE + " " + _VARIANT_PAIRS).split():
    if len(pair) == 2 and pair[0] != pair[1]:
        S2T.setdefault(pair[0], pair[1])
# Resolve chains (e.g. 帐→帳→賬) so fold() is idempotent: every character maps straight to its canonical form.
for _source in list(S2T):
    _target, _seen = S2T[_source], {_source}
    while _target in S2T and _target not in _seen:
        _seen.add(_target)
        _target = S2T[_target]
    S2T[_source] = _target
S2T = {k: v for k, v in S2T.items() if k != v}

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
    # PostgreSQL's parser indexes the stored term "don't" as the lexemes "don" and "t", so the query splits the same way
    # (joining the halves into "dont" would never match).
    terms = []
    for t in query_terms(query):
        cleaned = re.sub(r"[^0-9a-zÀ-ɏ㐀-䶿一-鿿豈-﫿぀-ヿ가-힯']", "", t)
        terms += [part for part in cleaned.split("'") if part]
    terms = list(dict.fromkeys(terms))
    return " & ".join(terms) if terms else None
