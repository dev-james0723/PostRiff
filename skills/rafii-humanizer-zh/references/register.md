# Chinese locale and register reference

Authority order for vocabulary and register:

1. the workspace's approved glossary and `VOICE.md`;
2. the customer's own approved posts;
3. the source text;
4. this table.

Usage varies within every region, so the table is a guard against drift, not a
style mandate. The humanizer never converts between scripts or regions. It only
avoids introducing the wrong ones.

## Regional vocabulary (do not convert between columns)

| Meaning | zh-Hans (Mainland) | zh-Hant-TW | zh-Hant-HK / yue |
|---|---|---|---|
| software | 软件 | 軟體 | 軟件 |
| video | 视频 | 影片 | 影片 / 片 |
| information | 信息 | 資訊 | 資訊 |
| network, internet | 网络 | 網路 | 網絡 |
| quality | 质量 | 品質 | 質素 / 質量 |
| project | 项目 | 專案 | 項目 / project |
| user | 用户 | 使用者 / 用戶 | 用戶 |
| default | 默认 | 預設 | 預設 |
| program | 程序 | 程式 | 程式 |
| server | 服务器 | 伺服器 | 伺服器 |
| data | 数据 | 資料 / 數據 | 數據 / 資料 |
| support (a feature) | 支持 | 支援 | 支援 |
| SMS | 短信 | 簡訊 | 短訊 / SMS |
| email | 邮件 / 电子邮件 | 郵件 / 電子郵件 / email | 電郵 / email |
| print | 打印 | 列印 | 打印 |
| screen | 屏幕 | 螢幕 | 屏幕 / 熒幕 |
| taxi | 出租车 | 計程車 | 的士 |
| bus | 公交车 | 公車 | 巴士 |
| bicycle | 自行车 | 腳踏車 | 單車 |
| potato | 土豆 / 马铃薯 | 馬鈴薯 | 薯仔 |
| ice cream | 冰淇淋 | 冰淇淋 | 雪糕 |
| blog | 博客 | 部落格 | 網誌 / blog |
| area unit | 平方米 | 坪 / 平方公尺 | 平方呎 |

Units, currencies and measures are facts. Never convert them (a 坪 value is not
a 平方呎 value). Singapore and Malaysia zh-Hans keep local terms such as 巴刹
(market), 德士 (taxi) and 组屋 (public housing). Do not "correct" them into
Mainland terms.

## Script integrity

- One text uses one script. The detector's `zh.script_markers` flags Simplified-only
  characters in Traditional copy, and the reverse.
- Never auto-convert inside this pass. Conversion is one-to-many: 发 → 發 or 髮;
  后 → 後 or 后; 干 → 幹, 乾 or 干; 面 → 面 or 麵; 里 → 裡 or 里; 台 → 台, 臺 or 颱;
  云 → 雲 or 云. Wrong conversions change meaning. Localisation is a separate,
  reviewed step.
- Keep the customer's character variants. Hong Kong writers may use 裏, 綫, 着
  or 衞. Taiwan writers may use 裡, 線, 著 or 衛. Do not normalise either set.

## Hong Kong: 書面語 and 口語

| | zh-Hant-HK (書面語) | yue-Hant-HK (口語) |
|---|---|---|
| Typical use | notices, press releases, corporate and government copy, formal announcements, print | Instagram, Threads and Facebook captions, community replies, local ads, quoted speech |
| Grammar words | 是, 的, 了, 在, 沒有, 他們, 這個, 甚麼 | 係, 嘅, 咗, 喺, 冇, 佢哋, 呢個, 乜嘢 or 咩 |
| Particles | none, except in quotes | 㗎, 喎, 囉, 啦, 吖, 嘛, 啫, 嘞, only where the voice uses them |
| Example | 本會將於下月舉行周年大會，請會員於月底前登記。 | 下個月開周年大會，記得月尾前登記呀！ |

The two examples are the same content in two registers. Choose one according to
the brief and the voice. Do not switch registers to "sound human", and never
switch inside one text block.

Signals that a yue text is Mandarin in disguise, which is worth fixing when the
target is yue:

- 讓我們 or 我們 used with Cantonese particles. Use 我哋.
- 唔單止…仲係… used as a fake contrast.
- 書面 connectors (因此, 此外, 與此同時) in a casual caption.
- 喺呢個瞬息萬變嘅時代 openers.
- 啦 or 喎 attached to every sentence.

A register difference is not an error. 口語 in a caption the voice approves stays
口語. 書面語 in a formal notice stays 書面語.

## Taiwan (zh-Hant-TW)

- Use Taiwan vocabulary (see the table) and 「」 quotes, unless the voice uses “”.
- Casual 喔, 啦, 欸 and 耶 are fine where the voice uses them. 注音文 (ㄉ, ㄇ) and
  internet slang are never defaults.
- Formal Taiwan copy commonly uses 敬請, 本公司 and 即日起. These are register,
  not AI tells.

## Code-switching (EN↔ZH)

- Hong Kong office Cantonese and Taiwan and Mainland tech copy switch naturally:
  - 今個 project 嘅 deadline 係 Friday
  - book 位
  - check 下
  - send 份 notes 畀大家
  - 開個 PR
  - roadmap
  - KPI

  Keep the English words exactly, including their case, spelling and plurals.
- Do not translate them into Chinese (deadline stays deadline, not 截止日期), and
  do not add code-switching the voice lacks.
- Keep bilingual names and pairs as written: 「Flow 月費計劃」 and
  中文名 (English Name).
- For spacing between CJK and Latin text, follow the source or house style. The
  conventions differ (with or without a space) and both are acceptable.
- Weekdays, times and numbers written in English inside Chinese copy (Friday,
  7:30pm) are still dates and numbers for the meaning check.

## Punctuation

| | zh-Hans | zh-Hant (TW, HK) |
|---|---|---|
| Quotes | “” and ‘’ | 「」 and 『』 (“” also seen, so follow the source) |
| Book titles | 《》 | 《》 and 〈〉 |
| Ellipsis | …… | …… |
| Dash | —— (clue only when dense) | —— |

Use full-width punctuation in Chinese sentences and half-width inside English,
code, URLs and numbers. Casual HK or TW captions sometimes use half-width
punctuation throughout. When the voice does that, it is voice, not an error.
