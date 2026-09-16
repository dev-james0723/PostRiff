# Regional language styles for PostRiff drafts

Status: **research, Stage 1** · 2026-09-16 · companion to [`postriff-worldwide-languages-plan.md`](postriff-worldwide-languages-plan.md)

PostRiff should write a post the way a local would, in the author's own voice. This document
collects what that means for each proposed tuned locale: script and spelling, punctuation, the
words that give a region away, particles, formality, language mixing, tone on social media,
platform habits, formats, names, and sensitivities. Each entry ends with a short **prompt guide**,
the part that becomes `skills/postriff-content-engine/references/locales/<tag>.md`.

## How to read it

- **General knowledge only.** Nothing here describes a particular person. How one author writes
  lives in their voice profile and memory.
- **Every entry has a confidence line and a "Native check" list.** Formats, spelling and
  typography are mostly well sourced. Social-media tone, emoji and hashtag habits often rest on
  thin sources and are marked Low. A locale's guide should earn the "Tuned" badge only after a
  native speaker has gone through its Native check list.
- **Sources are cited per entry.** Research ran as eight parallel passes and hit a shared
  web-search cap partway through, so later sections lean more on pages fetched directly
  (Unicode CLDR, Microsoft style guides, government manuals, Wikipedia/Wiktionary). Citations
  taken from search-result text rather than an opened page are marked as such.
- **Illustrative phrases are written for this document**, not copied from posts.

## Findings that shape the product

1. **Converting is not localising.** OpenCC's Taiwan mode maps about 818 phrases, its Hong Kong
   mode about 82, and nothing produces written Cantonese. Every locale is drafted natively.
2. **Hong Kong is a continuum.** Posts run from standard written Chinese through a blend to full
   written Cantonese, and usually drop in single English words (book, check) rather than whole
   English clauses. Hence two entries, `zh-Hant-HK` and `yue-Hant-HK`, plus the author's own mixing
   habits from their voice profile.
3. **Names don't follow script.** The Hong Kong Philharmonic writes 莫扎特 (like the mainland) but
   蕭邦, 德布西 and 拉赫曼尼諾夫 (like Taiwan); Taiwan writes 莫札特; Beijing writes 肖邦, 德彪西.
   Names an author uses often belong in their own glossary, not in a locale guide.
4. **Grammar reveals the writer's gender** in Hindi, Urdu, Marathi, Polish, Russian, Ukrainian,
   Arabic and Hebrew verbs; French, Italian, Spanish and Portuguese adjectives; Thai polite
   particles; Japanese and Vietnamese self-reference. The model must never guess.
5. **Address forms are the loudest regional marker.** Argentina uses vos even in ads; Colombia
   uses usted between friends; "você" can read as rude in Portugal; Spain alone says vosotros.
6. **Local words are rare in public posts.** Scots forms are a small minority even in Scottish
   tweets; Singlish, Irish and Australian slang work the same way. Guides say "one or two natural
   touches", not caricature.
7. **Models drift to the formal standard.** Measured Arabic "dialect" output from a model still
   carried about a third Modern Standard Arabic. Dialect guides say explicitly "not MSA".
8. **Formats give a post away before words do.** Month names differ across Arabic regions; Thai
   uses Buddhist Era years; Québec writes `25,50 $` and `18 h 30`; India groups ₹12,34,567;
   Persian needs zero-width non-joiners (می‌خواهم).
9. **Some rules are law, not style**: ad labelling in Japan and Korea, tax-inclusive prices in
   Japan, banned superlatives (国家级, 最佳) under mainland advertising law, Xiaohongshu penalties
   for sharing WeChat IDs, Thailand's royal defamation law. These become reminders on a draft.
10. **Script choice can be its own entry.** Romanized Hindi outnumbers Devanagari on social media,
    so `hi-Latn-IN` is a picker entry. Arabizi spelling follows each country's second language,
    so it fits better as an optional "Latin letters" setting on specific Arabic locales than as a
    generic `ar-Latn` entry.
11. **Counting differs by platform.** X weights CJK as 2; Bluesky counts graphemes; LINE and TikTok
    count UTF-16 units; Threads may count UTF-8 bytes (needs a live test).
12. **No vendor baseline for the markets that matter most here.** Microsoft publishes no style
    guide for Hong Kong Chinese, Cantonese, most regional English, Austrian or Swiss German, or
    country-level Arabic. These researched guides are the product's differentiator, and native
    review matters most for them.

## Locale index

| Tag | Name in the language | English | Section |
|---|---|---|---|
| `zh-Hant-HK` | 香港書面語（繁體中文）· Chinese (Traditional, Hong Kong) | 香港書面語（繁體中文）· Chinese (Traditional, Hong Kong) | Chinese family |
| `yue-Hant-HK` | 香港粵語（廣東話書寫）· Cantonese, written (Hong Kong) | 香港粵語（廣東話書寫）· Cantonese, written (Hong Kong) | Chinese family |
| `zh-Hant-TW` | 繁體中文（台灣）· Chinese (Traditional, Taiwan) | 繁體中文（台灣）· Chinese (Traditional, Taiwan) | Chinese family |
| `zh-Hans-CN` | 简体中文（中国大陆）· Chinese (Simplified, Mainland China) | 简体中文（中国大陆）· Chinese (Simplified, Mainland China) | Chinese family |
| `zh-Hans-SG` | 简体中文（新加坡）· Chinese (Simplified, Singapore) | 简体中文（新加坡）· Chinese (Simplified, Singapore) | Chinese family |
| `en-US` | English (United States) | American English | English family |
| `en-GB` | English (United Kingdom) | British English | English family |
| `en-GB-scotland` | Scottish Standard English | Scottish English | English family |
| `en-IE` | English (Ireland) | Irish English / Hiberno-English | English family |
| `en-AU` | English (Australia) | Australian English | English family |
| `en-NZ` | English (New Zealand) | New Zealand English | English family |
| `en-CA` | English (Canada) | Canadian English | English family |
| `en-IN` | English (India) | Indian English | English family |
| `en-SG` | English (Singapore) | Singapore English | English family |
| `es-ES` | Español de España | Spanish (Spain) | Spanish & Portuguese |
| `es-MX` | Español de México | Spanish (Mexico) | Spanish & Portuguese |
| `es-AR` | Español rioplatense | Spanish (Argentina) | Spanish & Portuguese |
| `es-CO` | Español de Colombia | Spanish (Colombia) | Spanish & Portuguese |
| `es-US` | Español de Estados Unidos | Spanish (United States) | Spanish & Portuguese |
| `es-419` | Español latinoamericano neutro | Neutral Latin American Spanish | Spanish & Portuguese |
| `pt-BR` | Português do Brasil | Portuguese (Brazil) | Spanish & Portuguese |
| `pt-PT` | Português europeu | Portuguese (Portugal) | Spanish & Portuguese |
| `fr-FR` | Français (France) | French (France) | European languages |
| `fr-CA` | Français (Québec) | French (Canada, Québec) | European languages |
| `de-DE` | Deutsch (Deutschland) | German (Germany) | European languages |
| `de-AT` | Deutsch (Österreich) | German (Austria) | European languages |
| `de-CH` | Deutsch (Schweiz) | German (Switzerland) | European languages |
| `it-IT` | Italiano | Italian (Italy) | European languages |
| `nl-NL` | Nederlands (Nederland) | Dutch (Netherlands) | European languages |
| `pl-PL` | Polski | Polish (Poland) | European languages |
| `tr-TR` | Türkçe | Turkish (Türkiye) | European languages |
| `ru-RU` | Русский | Russian (Russia) | European languages |
| `uk-UA` | Українська | Ukrainian (Ukraine) | European languages |
| `ja-JP` | 日本語 | Japanese | East & Southeast Asia |
| `ko-KR` | 한국어 | Korean | East & Southeast Asia |
| `th-TH` | ภาษาไทย | Thai | East & Southeast Asia |
| `vi-VN` | Tiếng Việt | Vietnamese | East & Southeast Asia |
| `id-ID` | Bahasa Indonesia | Indonesian | East & Southeast Asia |
| `ms-MY` | Bahasa Melayu | Malay (Malaysia) | East & Southeast Asia |
| `fil-PH` | Filipino | Filipino (Tagalog, incl. Taglish) | East & Southeast Asia |
| `hi-IN` | हिन्दी | Hindi | South Asia |
| `hi-Latn-IN` | Hinglish (Roman Hindi) | Romanized Hindi | South Asia |
| `bn-IN` | বাংলা | Bengali (India) | South Asia |
| `bn-BD` | বাংলা (বাংলাদেশ) | Bengali (Bangladesh) | South Asia |
| `ta-IN` | தமிழ் | Tamil (India) | South Asia |
| `te-IN` | తెలుగు | Telugu | South Asia |
| `mr-IN` | मराठी | Marathi | South Asia |
| `ur-PK` | اردو | Urdu (Pakistan) | South Asia |
| `ar` | العربية الفصحى | Modern Standard Arabic (pan-Arab) | Arabic, Hebrew & Persian |
| `ar-EG` | مصري | Egyptian Arabic | Arabic, Hebrew & Persian |
| `ar-SA` | سعودي / خليجي | Saudi (Gulf) Arabic, with UAE note | Arabic, Hebrew & Persian |
| `ar-LB` | لبناني | Lebanese (Levantine) Arabic | Arabic, Hebrew & Persian |
| `ar-MA` | الدارجة المغربية | Moroccan Darija | Arabic, Hebrew & Persian |
| `he-IL` | עברית | Hebrew (Israel) | Arabic, Hebrew & Persian |
| `fa-IR` | فارسی | Persian (Iran), with Dari note | Arabic, Hebrew & Persian |

The tag `ar` in the Arabic section is proposed to be stored as `ar-001` (see the standards section, §1).


---

## Chinese family

Research date: 2026-09-16. Citations use one numbering scheme for the whole file. Each entry's **Sources** lists only the numbers it cites, and the Family notes end with the full list. "Observed" means I counted or saw something on a live page that day (the [10] log). Example phrases I wrote myself are marked *illustrative*.

---

### Family notes

**What the five share.** The four `zh-*` locales share one grammar, Modern Standard Written Chinese. They differ in script, glyph standard, punctuation, vocabulary, how foreign names are transliterated, and which platforms people post on. `yue-Hant-HK` is a different written register: Cantonese grammar words and sentence-final particles, in the same Traditional script as `zh-Hant-HK` [17][23]. CLDR maps a bare `yue` to `yue-Hant-HK`, `zh-HK` to `zh-Hant-HK`, `zh-TW` and `zh-Hant` to `zh-Hant-TW`, and a bare `zh` to `zh-Hans-CN` [1].

**Converting characters does not localize a post.**
- OpenCC's `s2t`, `s2tw` and `s2hk` convert characters and fix regional glyph shapes. They do not change vocabulary [5][6].
- Only the phrase modes change words. `s2twp` has about 818 Taiwan phrase mappings, such as 軟件→軟體, 網絡→網路, 視頻→影片, 出租車→計程車, 打印機→印表機, 信息→資訊, 項目→專案 and 默認→預設 [7].
- The Hong Kong phrase mode, `s2hkp`, has only about 82 entries. Most are Cantonese-style film-name transliterations (史匹堡 for Spielberg). A few are IT terms (服務器→伺服器, 搜索→搜尋, 隱私權→私隱權) [7].
- By design, OpenCC does not rewrite sentences or colloquial usage (except in the `*p` modes), and it leaves ambiguous cases unconverted [6]. Where a word has several possible outputs, some OpenCC builds simply take the first [5].
- Phrase mapping can also get it wrong. 項目→專案 is right for "project" but wrong for "event" in 比賽項目 (*illustrative*).
- The Hong Kong government's own writing manual warns that conversion software swaps whole words: its examples are 電腦→計算機 and 資料庫→數據庫. It tells writers to proofread afterwards [8].
- No converter produces Cantonese.
- **Implication for PostRiff:** draft natively in the target locale. Never produce `zh-Hant-TW` or `zh-Hant-HK` by converting `zh-Hans`.

**Glyph standards differ even within Traditional.** OpenCC's Hong Kong variant table turns 說/衛/溫/稅/戶 into 説/衞/温/税/户. Its Taiwan table turns 着/裏/峯/麪/羣 into 著/裡/峰/麵/群 [7]. Keyboards on phones produce a mix, so these shapes matter far less on social media than in print.

**Official style guidance is uneven.** Microsoft publishes a Chinese (Simplified) guide and a Chinese (Traditional) guide, which is Taiwan-based. Its index lists no separate Hong Kong guide [2][3][4]. Hong Kong guidance therefore rests on the Civil Service Bureau manuals, CLDR and observed media practice [1][8][10][12].

**How to tell the five apart at a glance**

| | `zh-Hant-HK` | `yue-Hant-HK` | `zh-Hant-TW` | `zh-Hans-CN` | `zh-Hans-SG` |
|---|---|---|---|---|---|
| Script | Traditional (HK glyph shapes in formal type) | Traditional plus Cantonese characters (嘅 咗 嚟 㗎) | Traditional (MOE shapes: 著, 裡) | Simplified (通用规范汉字表) | Simplified (mainland set) |
| Quote marks | 「」『』 in media and press releases (the CSB manual itself shows “”) | 「」, or none in casual posts | 「」『』 (MOE) | “”‘’ (GB/T 15834) | “”‘’ |
| Signature words | 的士, 巴士, 軟件, 網上/網絡, 質素, 讚好 | 係, 冇, 佢, 嘅 + 的士, 單車 | 計程車, 捷運, 軟體, 網路, 影片, 按讚 | 出租车, 公交, 软件, 视频, 信息, 点赞 | 德士, 组屋, 巴刹, 脚车 |
| Signature particles | Few (standard 呢, 吧, 嗎) | 啦, 喎, 㗎, 囉, 咋 | 喔, 欸, 耶, 啦 | 啊, 呀, 哈; slang such as 绝了 | 啦, 咯, 嘛 |
| Typical platforms | Facebook and Instagram brand pages, press releases, LinkedIn | Instagram, Threads, Facebook, LIHKG, WhatsApp | Threads, Instagram, Facebook, Dcard, PTT, LINE | Xiaohongshu, Weibo, Douyin, WeChat | Facebook, Instagram, WhatsApp, Zaobao-style news |
| Money | HK$ / $ / 港元 | $ / 蚊 | NT$ / 元 / 新台幣 | ¥ / 元 | S$ / $ / 新元 |
| Short date | 16/9/2026 | 16/9 (practice; CLDR `yue` says y/M/d) | 2026/9/16 | 2026/9/16 | 16/09/26 |

Dates follow CLDR short patterns [1], except the yue cell, which follows HK practice (see that entry). Platform rows come from the entry sections below. The HK "蚊" and SG "S$" usages come from everyday practice rather than a source (see each entry's Native check).

**Punctuation shared across the family.** All five use full-width 。，、；：？！, ellipsis …… and dash ——, each two character-widths [8][9].
- The full stop sits bottom-left in mainland type and centred in Taiwan and Hong Kong type. That is a font matter, not something the drafting model controls [9].
- The dot between parts of a foreign name or title is · in mainland text [9]. Taiwan's MOE handbook shows ． and ‧ is common [9][11]. The HK government manual uses • (《天淨沙•秋思》) [8].

**Sources (family notes):** [1] [2] [3] [4] [5] [6] [7] [8] [9] [10] [11] [12] [17] [23]. The full list is below.

**Full source list for this file**

1. Unicode CLDR JSON (delimiters, Gregorian and ROC calendars, numbers, currencies, likely subtags for zh, zh-Hant, zh-Hant-HK, zh-Hant-MO, zh-Hans-SG, zh-Hans-MY, yue) — https://github.com/unicode-org/cldr-json
2. Microsoft Localization Style Guides index — https://learn.microsoft.com/en-us/globalization/reference/microsoft-style-guides
3. Microsoft, Chinese (Traditional) Localization Style Guide — https://download.microsoft.com/download/2/9/3/293e6d41-ba40-451b-a41e-94bdb6242ae3/zho-twn-StyleGuide.pdf
4. Microsoft, Chinese (Simplified) Localization Style Guide — https://download.microsoft.com/download/1/5/9/159cb91c-b61b-4385-97ca-80ccc7ff1fa0/zho-chn-StyleGuide.pdf
5. OpenCC README and configuration list (s2t, s2hk, s2hkp, s2tw, s2twp…) — https://github.com/BYVoid/OpenCC ; first-candidate behaviour noted in port docs seen in search results, e.g. https://github.com/yichen0831/opencc-python
6. OpenCC, DESIGN_PRINCIPLES.md — https://github.com/BYVoid/OpenCC/blob/master/DESIGN_PRINCIPLES.md
7. OpenCC dictionaries HKPhrases.txt, TWPhrases.txt, HKVariants.txt, TWVariants.txt and config s2hkp.json — https://github.com/BYVoid/OpenCC/tree/master/data
8. Civil Service Bureau, Official Languages Division, 《政府公文寫作手冊》第三版・總論 (2019) — https://csb.gov.hk/english/publication/files/general_principles_3ed.pdf
9. Wikipedia, "Chinese punctuation" — https://en.wikipedia.org/wiki/Chinese_punctuation
10. Observation log, fetched 2026-09-16 (counts of quote marks and vocabulary on each homepage or listing):
    - HK: https://www.info.gov.hk/gia/general/202609/15c.htm, https://news.rthk.hk/rthk/ch/latest-news.htm and https://www.hk01.com/ all use 「」 and no “”. HK01 had 影片, 網絡, 資訊, 手機 and the headline fragment 「最Hit」; RTHK had 網絡, 單車, 周末, 質量 ×2 and 品質 ×1.
    - Macau: https://www.gov.mo/zh-hant/ uses “” ×14 and 「」 ×0; https://www.exmoo.com/ uses 「」 ×26.
    - Taiwan: https://www.cna.com.tw/list/aall.aspx uses 「」 ×31 and 台灣 ×63, with 公車, 手機, 品質, 新台幣, and 地鐵 for foreign metros. https://www.ettoday.net/ has 影片, 網路, 捷運. A PAR magazine headline in search results reads 「台日交流」.
    - Mainland: http://www.xinhuanet.com/ uses “” ×80, with 视频, 网络, 互联网, 信息, 点击.
    - Singapore: https://www.zaobao.com.sg/ uses “” with 视频, 网络, 资讯, 质量, 地铁, 组屋, 周末.
    - Malaysia: https://www.sinchew.com.my/ uses “” with 视频 ×45, 巴刹, 点赞, 令吉 ×35; https://www.chinapress.com.my/ uses “”.
11. ROC Ministry of Education, 《重訂標點符號手冊》修訂版 — 引號 https://language.moe.gov.tw/001/upload/files/site_content/m0001/hau/h6.htm ; 書名號 https://language.moe.gov.tw/001/upload/files/site_content/m0001/hau/h12.htm
12. CSB Official Languages Division newsletter (issue 29), 邵敬敏 lecture summary 「香港詞語的特點」 — https://www.csb.gov.hk/hkgcsb/ol/news/no29/p05_8.pdf
13. Wikipedia (zh), 漢語地區用詞差異列表 — https://zh.wikipedia.org/zh-tw/%E6%B1%89%E8%AF%AD%E5%9C%B0%E5%8C%BA%E7%94%A8%E8%AF%8D%E5%B7%AE%E5%BC%82%E5%88%97%E8%A1%A8
14. Leisure and Cultural Services Department (HK), Chinese homepage and ticketing page (observed 資訊, 程式, 數據, 網上, 手機) — https://www.lcsd.gov.hk/tc/
15. Hong Kong Philharmonic Orchestra, concert listings (observed 蕭邦, 莫扎特, 拉赫曼尼諾夫, 貝多芬, 布拉姆斯, 浦羅哥菲夫, 蕭斯達高維契, 柴可夫斯基, 拉威爾, 海頓, 馬勒, 巴赫, 獨奏會, 網上, 港鐵; titles 《海》, 第二十二鋼琴協奏曲) — https://www.hkphil.org/tc/concert ; https://www.hkphil.org/tc/concert/mao-fujita-plays-rachmaninov
16. 香港網絡大典, 「讚好」 (seen in search results) — https://evchk.fandom.com/zh/wiki/%E8%AE%9A%E5%A5%BD
17. Wikipedia, "Hong Kong Cantonese" — https://en.wikipedia.org/wiki/Hong_Kong_Cantonese
18. Wikipedia, "Mainland China" — https://en.wikipedia.org/wiki/Mainland_China
19. Wikipedia, "Hong Kong national security law" (disambiguation: the 2020 national law and the 2024 Safeguarding National Security Ordinance) — https://en.wikipedia.org/wiki/Hong_Kong_national_security_law
20. Wiktionary, 妳 — https://en.wiktionary.org/wiki/%E5%A6%B3
21. Wikipedia (zh) variant display titles queried via the MediaWiki API (Chopin: zh-cn/sg/my 肖邦, zh-hk/tw/mo 蕭邦; Mozart: zh-cn/sg 莫扎特, zh-hk/tw 莫札特) — https://zh.wikipedia.org/wiki/%E5%BC%97%E9%9B%B7%E5%BE%B7%E9%87%8C%E5%85%8B%C2%B7%E8%82%96%E9%82%A6
22. Chen, Katherine Hoi Ying (2005), "The Social Distinctiveness of Two Code-mixing Styles in Hong Kong", ISB4 Proceedings, Cascadilla — http://www.lingref.com/isb/4/039ISB4.PDF
23. Wikipedia, "Written Cantonese" — https://en.wikipedia.org/wiki/Written_Cantonese
24. Wikipedia (zh), 支語 / 支語警察 — https://zh.wikipedia.org/zh-tw/%E6%94%AF%E8%AA%9E%E8%AD%A6%E5%AF%9F
25. 粵典 words.hk, 廣東話句末助詞列表 — https://words.hk/faiman/view/691/%E5%BB%A3%E6%9D%B1%E8%A9%B1%20%E5%8F%A5%E6%9C%AB%E5%8A%A9%E8%A9%9E%20%E5%88%97%E8%A1%A8
26. Cantonese Notes, 「舉例講下一啲粵文常見嘅錯別字及其建議寫法」 (2019) — https://cantonesenotes.home.blog/2019/07/25/same-examples-of-cantonese-typos-and-correction-suggestions/
27. Snow, Don (2004), *Cantonese as Written Language*, HKU Press (publisher description), plus the search-result summary of research on HK diglossia citing Snow 2004 and Bauer 2018 — https://hkupress.hku.hk/index.php?route=product%2Fproduct&product_id=1221 ; https://www.researchgate.net/publication/324451046_Cantonese_as_written_language_in_Hong_Kong
28. Gonzales, W. D. W. & Tsang, Y. M. (2023), "The Sociolinguistics of Code-switching in Hong Kong's Digital Landscape… on WhatsApp", *Journal of English and Applied Linguistics* — https://animorepository.dlsu.edu.ph/jeal/vol2/iss1/2/
29. Wikipedia, "LIHKG" (seen in search results) — https://en.wikipedia.org/wiki/LIHKG
30. Wikipedia, "Dcard" — https://en.wikipedia.org/wiki/Dcard
31. ROC MOE, 《重編國語辭典修訂本》 site (observed 臺北 and 臺中 in official addresses) — https://dict.revised.moe.edu.tw/
32. Wikipedia, "Taiwanese Mandarin" — https://en.wikipedia.org/wiki/Taiwanese_Mandarin
33. Wikipedia (zh), 注音文 — https://zh.wikipedia.org/zh-tw/%E6%B3%A8%E9%9F%B3%E6%96%87
34. Wikipedia, "Threads (social network)" — https://en.wikipedia.org/wiki/Threads_(social_network)
35. Wikipedia, "PTT Bulletin Board System" — https://en.wikipedia.org/wiki/PTT_Bulletin_Board_System
36. Wikipedia, "Taiwanese Hokkien" (MOE recommended characters) — https://en.wikipedia.org/wiki/Taiwanese_Hokkien
37. National Performing Arts Center (Taiwan), NSO and NTSO pages (seen in search results: 莫札特…第二十一號鋼琴協奏曲, 德布西《海》, 蕭邦, 柴科夫斯基, 「NTSO拉赫曼尼諾夫鋼琴協奏曲全集」) — https://www.npac-ntch.org/npac/zh/info/nso ; https://npac-ntch.org/programs/7452-NTSO%E6%8B%89%E8%B5%AB%E6%9B%BC%E5%B0%BC%E8%AB%BE%E5%A4%AB%E9%8B%BC%E7%90%B4%E5%8D%94%E5%A5%8F%E6%9B%B2%E5%85%A8%E9%9B%86-II
38. VoiceTube Taiwan blog, 「按讚除了 like…」 (title seen in search results) — https://tw.blog.voicetube.com/archives/39877/
39. State Council notice publishing 《通用规范汉字表》 (2013) — https://www.gov.cn/zwgk/2013-08/19/content_2469793.htm
40. 《中华人民共和国广告法》 (2015 revision), Article 9 — https://zh.wikisource.org/wiki/%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD%E5%B9%BF%E5%91%8A%E6%B3%95_(2015%E5%B9%B4)
41. Wikipedia, "Weibo" — https://en.wikipedia.org/wiki/Weibo
42. Wikipedia, "Xiaohongshu" — https://en.wikipedia.org/wiki/Xiaohongshu
43. Wikipedia (zh), YYDS (mentions 绝绝子, 集美) — https://zh.wikipedia.org/wiki/YYDS
44. Wiktionary, 集美 and 種草 — https://en.wiktionary.org/wiki/%E9%9B%86%E7%BE%8E ; https://en.wiktionary.org/wiki/%E7%A8%AE%E8%8D%89
45. Wikipedia, "Chinese Internet slang" — https://en.wikipedia.org/wiki/Chinese_Internet_slang
46. National Centre for the Performing Arts (Beijing), ticket page (observed 肖邦 and 萧邦 ×1 each, 莫扎特, 德彪西, 拉赫玛尼诺夫, 普罗科菲耶夫, 贝多芬, 钢琴独奏音乐会, 周末) — http://ticket.chncpa.org/product-1040646.html
47. Wikipedia, "Singaporean Mandarin" — https://en.wikipedia.org/wiki/Singaporean_Mandarin
48. Wikipedia (zh), 新加坡华语 — https://zh.wikipedia.org/zh-sg/%E6%96%B0%E5%8A%A0%E5%9D%A1%E5%8D%8E%E8%AF%AD
49. Singapore Mandarin Council (推广华语理事会), 新加坡华语资料库 — https://www.languagecouncils.sg/mandarin/ch/learning-resources/singaporean-mandarin-database
50. Wikipedia (zh), 马来西亚华语 — https://zh.wikipedia.org/zh-my/%E9%A9%AC%E6%9D%A5%E8%A5%BF%E4%BA%9A%E5%8D%8E%E8%AF%AD
51. Wikipedia, "Malaysian Mandarin" — https://en.wikipedia.org/wiki/Malaysian_Mandarin
52. Wikipedia, "Maintenance of Religious Harmony Act" — https://en.wikipedia.org/wiki/Maintenance_of_Religious_Harmony_Act

---

### 香港書面語（繁體中文）· Chinese (Traditional, Hong Kong) — `zh-Hant-HK`

**Where it's used / platforms:**
- Hong Kong speaks Cantonese but writes Standard Written Chinese (書面語) in formal settings. Written Cantonese carries a stigma in schools and official writing [27].
- `zh-Hant-HK` is the register of government press releases, RTHK and HK01 news, cultural bodies such as the HK Phil and LCSD, school and corporate notices, and professional bios [10][14][15].
- On social media it appears on institutional and brand pages on Facebook, Instagram, LinkedIn and YouTube, and in event announcements.
- Personal accounts usually drift toward Cantonese or a blend of the two (see `yue-Hant-HK`).
- **Macau (`zh-Hant-MO`):** treat it as this entry with swaps.
  - Currency: MOP$ / 澳門元. CLDR date and time patterns match HK's [1].
  - Quotes: local media use 「」, but the government portal uses “” [10].
  - Vocabulary: largely HK-like.

**Script & spelling:**
- Traditional characters. The official glyph shapes differ slightly from Taiwan's (説, 衞, 温, 税, 户) [7].
- Phones and fonts mix shapes, so be consistent within a post rather than fighting user input.
- The government manual supports the Hong Kong Supplementary Character Set for local characters [8].
- Hong Kong has its own word shapes and word orders. Use 質素 (not 素質), 私隱 (not 隱私), 擠擁 (not 擁擠), 取錄 (not 錄取), 銜頭 (not 頭銜) and 飯盒 (not 盒飯) [12].
- Loan transliterations follow Cantonese sound: 梳化 (sofa), 三文治 (sandwich), 荷里活 (Hollywood) [12].
- Some shared words mean different things here: 人士 is used loosely (自僱人士) and 檢討 is neutral rather than self-critical [12].

**Punctuation & typography:**
- Quote marks: 「」 outside, 『』 inside. This is CLDR's HK setting and what press releases, RTHK and HK01 use [1][10].
- **Sources disagree.** The CSB writing manual (2019) points writers to the PRC punctuation standard, prints its examples with “ ”, and says corner brackets were traditionally for vertical text [8]. For social posts, 「」 is the safe HK choice.
- Titles: 《》 for books, albums, works and programmes; 〈〉 for articles or chapters, or a title nested inside 《》 [8].
- Use full-width ，。、；：！？. The dash —— and ellipsis …… take two character widths [8].
- Headlines often use a full-width space as a separator [10].
- Spacing between Chinese and English is inconsistent in HK posts; many writers use none.

**Words that mark the region:**

| Concept | zh-Hant-HK | Siblings |
|---|---|---|
| taxi | 的士 [13] | yue 的士 · TW 計程車 · CN 出租车 · SG 德士 |
| software | 軟件 [13] | yue 軟件 · TW 軟體 · CN 软件 · SG 软件 |
| video (online) | 影片, 短片 [10][13] | yue 片 / 條片 · TW 影片 · CN 视频 · SG 视频 |
| bus | 巴士 [17] | yue 巴士 · TW 公車 · CN 公交车 · SG 巴士 |
| quality | 質素 (service, people); 品質 (goods) [12][13] | yue 質素 · TW 品質 · CN 质量 / 素质 · SG 质量 |
| information | 資訊 [14] | yue 資訊 / 資料 · TW 資訊 · CN 信息 · SG 资讯 / 信息 |
| internet / online | 網絡, 互聯網; 網上 [14][15] | yue 網上 · TW 網路 · CN 网络 / 网上 · SG 网络 |
| program (software) | 程式, 應用程式 [14] | yue app / 程式 · TW 程式 · CN 程序 / 应用 · SG 应用程序 |
| programme (TV, concert) | 節目 | yue 節目 · TW 節目 · CN 节目 · SG 节目 |
| mobile phone | 手機 (智能電話) [13][14] | yue 手機 · TW 手機 · CN 手机 · SG 手机 |
| subway | 港鐵 (MTR), 地鐵 [15] | yue 港鐵 · TW 捷運 · CN 地铁 · SG 地铁 (MRT) |
| bicycle | 單車 [12] | yue 單車 · TW 腳踏車 / 單車 · CN 自行车 · SG 脚车 |
| printer | 打印機 | yue printer / 打印機 · TW 印表機 · CN 打印机 · SG 打印机 |
| data | 數據, 資料 [14] | yue data / 數據 · TW 資料 · CN 数据 · SG 数据 |
| click | 點擊, 按 | yue 撳 / click · TW 點選 · CN 点击 · SG 点击 |
| like (social) | 讚好 [16] | yue 讚 / like · TW 按讚 · CN 点赞 · SG 点赞 |
| concert / recital | 音樂會, 獨奏會 [15] | yue 音樂會 · TW 音樂會 / 獨奏會 · CN 独奏音乐会 · SG 音乐会 |
| piano lesson | 鋼琴課 | yue 琴堂 / 學琴 · TW 鋼琴課 · CN 钢琴课 · SG 钢琴课 |
| weekend | 週末, 周末 [10] | yue 星期六日 · TW 週末 · CN 周末 · SG 周末 |
| "awesome" | 精彩, 出色 | yue 正 / 好正 / 勁 · TW 超讚 · CN 太棒了 / 绝了 · SG 很棒 |

**Particles, interjections & fillers:**
- Standard written particles (嗎, 呢, 吧, 啊) are used sparingly. Announcements often use none.
- Warmth usually comes from word choice (誠邀, 歡迎, 期待與你見面; *illustrative*), not particles.
- Once Cantonese particles (啦, 呀, 㗎) or 嘅/咗 appear, the post has moved into the blended or Cantonese register. Do that only when the user's voice does.

**Formality & address:**
- Use 你/你們 for the audience in most social copy. Use 各位/大家 for groups.
- 您 and very formal forms appear in service and official letters. Using them in a casual post reads stiff.
- 妳 (female "you") is used in Traditional-script writing in HK and Taiwan [20]. Don't assume the reader's gender: use 你.
- Microsoft's Traditional guide advises role nouns (讀者, 顧客) or 其 instead of 他/她 for generic people [3].
- Say 先生/女士 only when the gender is known.

**Mixing languages:**
- Institutions often post the Chinese paragraph and then an English one.
- Even in 書面語, English brand, product, programme and venue names are commonly kept. Headlines insert English words (「最Hit」) [10].
- Personal English names (Name + Chinese surname) are normal.
- In speech, the mainstream HK habit is inserting single English words into a Chinese base rather than switching whole clauses [22]. Formal posts use fewer insertions.

**Tone & humour on social:**
- Institutional HK copy is concise, factual and understated. Hard-sell superlatives read as advertising (硬銷).
- Humour and wordplay mostly live in Cantonese; formal Chinese stays polite.
- Stating achievements plainly (獲邀, 榮獲) is fine. Piling adjectives (最頂尖, 史上最強) reads as bragging.
- *Observation-based (Medium): check with a native reader.*

**Platform habits:**
- Instagram and Facebook event posts often have a short hook, then an info block with emoji bullets (📍 venue, 🗓 date, ⏰ time, 🎟 tickets), then a call to action. Examples: 「立即購票」, 「詳情請瀏覽」, 「連結見 bio」 (*illustrative*).
- Hashtags come at the end and mix Chinese and English (#香港 #hongkong).
- Spam signals: a long hashtag wall, Simplified characters mixed in (which reads like cross-border marketing), or all-caps English.

**Formats:**
- Dates: 2026年9月16日 (long). Short is 16/9/2026 (d/M/y); with weekday, 16/9（週三）[1]. Government documents may write years in Chinese numerals (二零二六年) [8].
- Time: CLDR short form is 下午3:00 (ah:mm) [1]. Posts also use 7:30pm or 晚上7時30分.
- Numbers: 1,234.5. Prose uses 萬/億. CLDR's HK compact format uses K/M (1.2K) [1].
- Currency: HK$ before the number; the CLDR display name is 港元 [1]. Listings often write just $ [15].
- Government documents use Chinese numerals for one to ten (十年, 兩個) [8]. Arabic numerals are fine in posts.

**Names of people & works:**
- Classical transliterations used by the HK Phil [15]:
  - Same as Taiwan: 蕭邦 (Chopin), 德布西 (Debussy), 拉赫曼尼諾夫 (Rachmaninoff).
  - Same as the mainland: 莫扎特 (Mozart).
  - Hong Kong only: 浦羅哥菲夫 (Prokofiev), 蕭斯達高維契 (Shostakovich).
  - Also: 貝多芬, 布拉姆斯, 柴可夫斯基, 拉威爾, 海頓, 馬勒, 巴赫.
- Wikipedia's zh-hk variant shows 莫札特 [21], which conflicts with HK Phil usage. Trust institutional usage and keep a curated glossary.
- Numbered works often omit 號 (莫扎特第二十二鋼琴協奏曲, 拉赫曼尼諾夫第二交響曲). Titles take 《》 (《海》) [15].
- Film and celebrity names follow Cantonese-sound conventions (史提芬·史匹堡) [7].

**Sensitivities:**
- Post-2020 Hong Kong operates under the National Security Law and the 2024 Safeguarding National Security Ordinance [19]. Keep drafts free of political slogans and protest references unless the user explicitly supplies them.
- Official usage calls the rest of the PRC 內地 (政制及內地事務局) [18]. Don't present Hong Kong as a country.
- Mainland words (視頻, 質量 for service) or Simplified characters can read as not local. Forum culture sometimes calls such words 支語 [24].

**Search aliases:** Hong Kong Chinese, Traditional Chinese (Hong Kong), Chinese (Hong Kong), zh-HK, zh_HK, zh-Hant-HK, HK, 香港, 香港中文, 繁體中文（香港）, 繁中 香港, 港式中文, 書面語, 正式中文, Hongkonger, 香港人, Macau, Macao, 澳門, zh-MO, zh-Hant-MO, 澳門中文

**Prompt guide (≤120 words):**
Write Hong Kong standard written Chinese (書面語) in Traditional characters. Use 「」 for quotes and 《》 for works. Use Hong Kong vocabulary: 的士, 巴士, 軟件, 網上/網絡, 資訊, 質素 (service), 單車, 讚好. Never use Taiwan forms (軟體, 網路, 計程車) or mainland forms (視頻, 信息, 質量 for service). Keep grammar standard (是, 的, 了, 沒有) and add no Cantonese particles unless the user's own samples do. Keep English brand, venue and personal English names as given. Use HK transliterations (蕭邦, 莫扎特, 德布西). Write money as HK$ or $ and dates as 2026年9月16日 or 16/9. Keep the tone concise and understated, with no stacked superlatives.

**Confidence:**
- Where used: High
- Script & spelling: High (HK-specific words); Medium (how strictly glyph shapes matter on social)
- Punctuation: High for 「」 in media; sources disagree (manual uses “”)
- Words: High for taxi, bus, software, bicycle, like; Medium for printer, click, piano lesson
- Particles: Medium
- Formality: Medium
- Mixing: Medium
- Tone: Low–Medium (observational)
- Platform habits: Medium (observational)
- Formats: High (CLDR); Medium (everyday time styles)
- Names: High for HK Phil forms
- Sensitivities: High
- Aliases: High

**Native check:**
- Would an HK reader find 「」 or “” more natural in a brand post in 2026? Does anyone read “” as mainland-leaning?
- Is 質量 in RTHK copy now neutral in HK, or still marked [10]?
- 場刊 vs 節目表 for a printed concert programme.
- Is 鋼琴課 or 琴堂 more natural in HK written copy?
- The time style in posts: 下午3時, 下午3:00 or 3pm?
- Does 您 read as stiff or as polite in HK brand captions?
- `zh-Hant-MO`: which quote marks do Macau brands use, and are there Macau-only words to add?

**Sources:** [1] [3] [7] [8] [10] [12] [13] [14] [15] [16] [17] [18] [19] [20] [21] [22] [24] [27]

---

### 香港粵語（廣東話書寫）· Cantonese, written (Hong Kong) — `yue-Hant-HK`

**Where it's used / platforms:**
- Written Cantonese is widely used in informal writing: chat, social networks, forums, tabloids, advertising, subtitles and comics [23][27].
- It is avoided in school and official writing [27].
- Typical homes: personal Instagram, Threads and Facebook captions; YouTube titles and comments; WhatsApp; and LIHKG, a Hong Kong multi-category forum that writes in Cantonese [29].
- Many local brands (food, lifestyle, gyms, tutors) caption in Cantonese to sound like a neighbour rather than an institution.

**Script & spelling:**
- Traditional characters plus Cantonese characters, many built on the 口 radical (嘅, 咗, 嚟, 噉) [23].
- Core forms compared with Standard Written Chinese [23]: 係/是, 唔/不, 冇/沒有, 佢/他·她, 嘅/的, 咗/了, 緊/正在.
- Other everyday forms: 啲 (some, a bit), 咁 (so, like this), 哋 (plural: 我哋, 你哋, 佢哋), 喺 (at), 嘢 (thing), 睇 (look), 俾/畀 (give), 嚟 (come), 乜嘢 (what), 點解 (why), 而家 (now), 嗰 (that), 邊個 (who), 啱 (right).
- **Grammar also differs:**
  - Comparatives: 佢高過我 vs 他比我高 (*illustrative*).
  - Adverb after the verb: 你行先 vs 你先走 (*illustrative*).
  - Object order with "give": 俾本書我 (*illustrative*).
- **Non-standard spellings.** 既 (for 嘅), 左 (咗), 架 (㗎), 野 (嘢), 黎 (嚟), 岩 (啱) and 番 (返) are very common [25][26].
  - They come from homophone typing with input methods that lack Cantonese characters [26].
  - Latin stand-ins: D for 啲, 7 for 柒 [23].
  - They read casual, young or hasty. Treat them as the user's personal habit, never as the default.

**Punctuation & typography:**
- Same marks as `zh-Hant-HK` (「」 quotes, 《》 titles).
- Casual posts often drop the full stop and break lines instead. They end with emoji, 「！！」 or 「…」.
- English words sit inside the sentence with or without spaces.
- CLDR's Cantonese data uses 上晝/下晝 for AM/PM and 港幣 for HKD [1].

**Words that mark the region:**

| Concept | yue-Hant-HK | Siblings |
|---|---|---|
| taxi | 的士 [17] | HK 的士 · TW 計程車 · CN 出租车 · SG 德士 |
| software | 軟件 | HK 軟件 · TW 軟體 · CN 软件 · SG 软件 |
| video | 片, 條片 (睇片) | HK 影片 · TW 影片 · CN 视频 · SG 视频 |
| bus | 巴士 [17] | HK 巴士 · TW 公車 · CN 公交车 · SG 巴士 |
| quality | 質素 | HK 質素 / 品質 · TW 品質 · CN 质量 · SG 质量 |
| information | 資訊, 資料 | HK 資訊 · TW 資訊 · CN 信息 · SG 资讯 |
| internet / online | 網上, 上網 | HK 網絡 / 網上 · TW 網路 · CN 网络 · SG 网络 |
| program / app | app, 程式 | HK 程式 · TW 程式 · CN 程序 · SG 应用程序 |
| programme | 節目 | HK 節目 · TW 節目 · CN 节目 · SG 节目 |
| mobile phone | 手機 | HK 手機 · TW 手機 · CN 手机 · SG 手机 |
| subway | 港鐵, 地鐵 | HK 港鐵 · TW 捷運 · CN 地铁 · SG 地铁 |
| bicycle | 單車 | HK 單車 · TW 腳踏車 · CN 自行车 · SG 脚车 |
| printer | printer, 打印機 | HK 打印機 · TW 印表機 · CN 打印机 · SG 打印机 |
| data | data, 數據 | HK 數據 · TW 資料 · CN 数据 · SG 数据 |
| click | 撳, click | HK 點擊 · TW 點選 · CN 点击 · SG 点击 |
| like (social) | 讚, like (俾個 like) | HK 讚好 · TW 按讚 · CN 点赞 · SG 点赞 |
| concert / recital | 音樂會, concert | HK 音樂會 / 獨奏會 · TW 獨奏會 · CN 音乐会 · SG 音乐会 |
| piano lesson | 琴堂, 學琴 | HK 鋼琴課 · TW 鋼琴課 · CN 钢琴课 · SG 钢琴课 |
| weekend | 星期六日, 週末 | HK 週末 · TW 週末 · CN 周末 · SG 周末 |
| "awesome" | 正, 好正, 勁, 好犀利 | HK 精彩 · TW 超讚 · CN 太棒了 / 绝了 · SG 很棒 |

**Particles, interjections & fillers:** functions paraphrased from words.hk [25]. Example phrases are *illustrative*.
- **啦 laa1:** suggestion, request or gentle push. 一齊嚟啦
- **喇 laa3:** new situation or done. 開售喇
- **喎 wo3 / wo5:** noticing something, a mild contrast, or relaying what someone said. 原來咁易喎
- **囉 lo1 / lo3:** it's obvious, resignation, or a firm view. 咪試吓囉
- **㗎 gaa3 / gaa4:** affirming or explaining (gaa3); a surprised or challenging question (gaa4). 好好聽㗎
- **咩 me1:** a surprised or rhetorical yes-no question. 你未聽過咩？
- **呀 aa3:** softens a statement, or marks a question or enthusiasm.
- **啫 ze1:** "just, nothing serious". 小小意思啫
- **嘛 maa3:** "as you know". 
- **吖 aa1:** a soft imperative or offer.
- **咋 zaa3:** "only, less than you'd think". 仲有兩個位咋
- **噃 bo3:** a reminder.
- **啩 gwaa3:** a guess.
- **添 tim1:** "on top of that", or mild regret.

Particles stack, for example 㗎喇 [25]. Interjections include 嘩, 唉, 喂 and 哈哈. Spoken-style fillers include 其實, 即係 and 咁. Draft with about one particle per sentence or clause. A particle on every line sounds childish; none at all sounds like 書面語.

**Formality & address:**
- Use 你/你哋, 大家 and 各位. 您 is essentially a Mandarin or formal-writing form and sounds out of place in Cantonese.
- 佢/佢哋 is gender-neutral, which removes the 他/她 problem.
- Don't assume gender with 靚仔/靚女 or with 妳 [20].

**How it differs from `zh-Hant-HK`, and the blend:** HK social posts sit on a continuum [23][27].
1. Pure 書面語: notices and press-style posts.
2. 書面語 body with Cantonese pronouns or particles at emotional moments. Example: 感謝大家嘅支持！ (*illustrative*). This is very common on brand and personal pages.
3. Full Cantonese.
4. Cantonese with English words inserted.

A typical local post opens in Cantonese, lays out the facts (date, time, venue, price) in neutral lines, and closes with a Cantonese call to action. Example: 想嚟嘅快啲留位啦 (*illustrative*).

Signs of a non-native blend:
- 的 and 嘅 in the same clause.
- Switching between 是 and 係.
- 了 after a Cantonese verb (睇了 instead of 睇咗).
- Mandarin-only words inside Cantonese (什麼 for 乜嘢, 東西 for 嘢).

**Mixing languages:**
- English words are inserted and take Cantonese grammar, as in "check 咗" [17]. The mainstream HK style inserts single English nouns, verbs and adjectives into a Cantonese base. Alternating whole English clauses marks a different, non-mainstream style [22].
- On WhatsApp, switching fills gaps, builds rapport and signals Hong Kong identity [28].
- Established loans are written in characters: 的士, 巴士, 士多, 波, 菲林, 朱古力, 三文治, 貼士 [17].
- Newer ones stay in Latin letters: book 位, confirm, present, chill, send 俾你 (*illustrative*).

**Tone & humour on social:**
- Self-deprecating, teasing and pun-based humour is common.
- Openly showing off reads as 曬 (flaunting). Hard selling reads as 硬銷.
- Understatement plus a friendly nudge works better. Example: 有興趣可以 PM 我 (*illustrative*).
- *Medium; check with a native reader.*

**Platform habits:**
- Instagram and Threads: short lines, moderate emoji, English or bilingual hashtags at the end.
- LIHKG: its own crude or in-group slang, not a brand register [29].
- Calls to action: 「link 喺 bio」, 「PM 我」, 「即刻留位」 (*illustrative*).
- Spam signals: many repeated hashtags, or a hard-sell list of superlatives.

**Formats:**
- Same as `zh-Hant-HK`.
- Colloquial forms: 7點半, 禮拜六 / 星期六, $300 or 300蚊, 下晝, 夜晚 [1].
- **Date mismatch:** CLDR's `yue` short date is y/M/d (2026/9/16) [1], but `zh-Hant-HK` in CLDR, and HK practice, is day-first (16/9) [1]. For HK Cantonese posts use day-first, or write 9月16日 to avoid ambiguity.

**Names of people & works:**
- As in `zh-Hant-HK` [15].
- Casual posts often keep composers and works in English (Chopin 嘅 Ballade; *illustrative*). Pick one convention per post.

**Sensitivities:**
- The same political constraints as `zh-Hant-HK` [19].
- Avoid vulgar Cantonese, including character or number stand-ins such as 7 [23], and LIHKG in-group slang.

**Search aliases:** Cantonese, written Cantonese, spoken-style Cantonese, Canto, HK Cantonese, Hong Kong Cantonese, Hongkongese, yue, yue-HK, yue-Hant, zh-yue, 廣東話, 广东话, 粵語, 粤语, 粵文, 廣府話, 白話, 口語, 港式, 港式廣東話, 香港話, HK, 香港

**Prompt guide (≤120 words):**
Write the way Hong Kong people post in Cantonese: Traditional characters and Cantonese grammar words (係, 唔, 冇, 佢, 嘅, 咗, 緊, 啲, 喺, 嚟). Never put 的, 了, 是 or 什麼 into Cantonese clauses. End some sentences with a fitting particle: 啦 (suggestion), 喇 (new state), 㗎 (explaining), 喎 (noticing), 咋 ("only"). Don't put one on every line. Insert single English words naturally (book, check, confirm) but don't alternate whole English sentences. Spell 嘅, 咗, 㗎, 嘢 in standard form, not 既, 左, 架, 野, unless the user's samples do. Give facts (date, time, venue, price) as plain lines. Use 「」 for quotes and $ or HK$ for money.

**Confidence:**
- Where used: High
- Script & spelling: High for core forms; Medium for how non-standard spellings are perceived
- Punctuation: Medium
- Words: High for taxi, bus, bicycle; Medium for printer, click, piano lesson, "awesome"
- Particles: High for functions; Medium for the density advice
- Formality: Medium
- Blend: Medium (analysis grounded in [23][27])
- Mixing: High
- Tone: Medium
- Platform habits: Medium
- Formats: Medium
- Names: Medium
- Sensitivities: High
- Aliases: High

**Native check:**
- Are 既, 左, 架 still judged "wrong", or as neutral youth style, in 2026 brand captions?
- Particle density: how many feel natural in a four- or five-line caption?
- 琴堂 vs 鋼琴堂 vs 鋼琴課 in speech-style writing.
- Is 300蚊 acceptable in a price line for a paid event, or should it be $300?
- Short dates in Cantonese posts: 16/9 or 9/16? CLDR `yue` data says y/M/d.
- Does a 書面語 facts block inside a Cantonese post feel natural, or should it stay Cantonese throughout?

**Sources:** [1] [15] [17] [19] [20] [22] [23] [25] [26] [27] [28] [29]

---

### 繁體中文（台灣）· Chinese (Traditional, Taiwan) — `zh-Hant-TW`

**Where it's used / platforms:**
- Everyday writing in Taiwan.
- Threads caught on early in Taiwan, where Twitter/X had never been widely used, and it featured in the 2024 election campaign [34].
- Instagram, Facebook fan pages, YouTube and LINE are mainstream.
- Dcard: an anonymous forum started by university students in 2011, with a young user base; it later expanded to Hong Kong, Macau and Japan [30].
- PTT: a text-based BBS founded in 1995, with 推/噓 up- and down-voting and its own 鄉民 culture [35].

**Script & spelling:**
- Traditional characters with MOE standard shapes: 著, 裡, 峰, 麵, 群 (not 着, 裏, 峯, 麪, 羣) [7].
- **臺 vs 台:** the education ministry's own site writes 臺北 and 臺中 [31]. Mainstream media and daily writing use 台 (台灣 ×63 on the CNA homepage) [10]. Use 台 in social posts unless the user writes 臺.
- 妳 is widely used for a female "you" [20].
- 注音文 (writing ㄉ for 的, ㄏㄏ for laughter) grew out of BBS culture. Some boards ban it and many find it hard to read [33]. Don't use it.
- Taiwanese Hokkien words use the MOE's recommended characters [36].

**Punctuation & typography:**
- MOE: 「」 first, 『』 inside. Sentence-final punctuation goes inside the quote [11].
- MOE titles: 《》 for books, albums, films, newspapers and documents; 〈〉 for articles, chapters, single songs and paintings. For example 〈望春風〉 [11].
- The MOE handbook shows ． as the separating dot [11]; ‧ is common in practice [9].
- Microsoft's Traditional guide puts a half-width space between Chinese and Latin letters or digits in product text [3]. Social posts vary.
- Wave dashes (～) and XD are frequent in casual writing (Medium).

**Words that mark the region:**

| Concept | zh-Hant-TW | Siblings |
|---|---|---|
| taxi | 計程車 (colloquially 小黃) [7][32] | HK 的士 · yue 的士 · CN 出租车 · SG 德士 |
| software | 軟體 [7][32] | HK 軟件 · yue 軟件 · CN 软件 · SG 软件 |
| video | 影片 (視訊 = video call or stream) [7][10] | HK 影片 · yue 條片 · CN 视频 · SG 视频 |
| bus | 公車 [10][13] | HK 巴士 · yue 巴士 · CN 公交车 · SG 巴士 |
| quality | 品質 [10][13] | HK 質素 · yue 質素 · CN 质量 · SG 质量 |
| information | 資訊 (訊息 = message) [7] | HK 資訊 · yue 資料 · CN 信息 · SG 资讯 |
| internet / online | 網路, 網際網路 [7] | HK 網絡 · yue 網上 · CN 网络 · SG 网络 |
| program (software) | 程式, 應用程式, App [7] | HK 程式 · yue app · CN 程序 · SG 应用程序 |
| programme | 節目, 節目單 | HK 節目 · yue 節目 · CN 节目 · SG 节目 |
| mobile phone | 手機 (formal 行動電話) [7][10] | HK 手機 · yue 手機 · CN 手机 · SG 手机 |
| subway | 捷運 (地鐵 for foreign metros) [10][32] | HK 港鐵 · yue 港鐵 · CN 地铁 · SG 地铁 |
| bicycle | 腳踏車, 單車 [7] | HK 單車 · yue 單車 · CN 自行车 · SG 脚车 |
| printer | 印表機 [7] | HK 打印機 · yue printer · CN 打印机 · SG 打印机 |
| data | 資料 (also 數據) [7] | HK 數據 · yue data · CN 数据 · SG 数据 |
| click | 點選, 點擊 [7] | HK 點擊 · yue 撳 · CN 点击 · SG 点击 |
| like (social) | 按讚, 讚 [38] | HK 讚好 · yue 讚 · CN 点赞 · SG 点赞 |
| concert / recital | 音樂會, 獨奏會 [37] | HK 音樂會 · yue concert · CN 独奏音乐会 · SG 音乐会 |
| piano lesson | 鋼琴課 | HK 鋼琴課 · yue 琴堂 · CN 钢琴课 · SG 钢琴课 |
| weekend | 週末 (weekday 週三) [1] | HK 週末 · yue 星期六日 · CN 周末 · SG 周末 |
| "awesome" | 超讚, 好猛, 太神了 | HK 精彩 · yue 好正 · CN 太棒了 · SG 很棒 |

**Particles, interjections & fillers:** Taiwan Mandarin is rich in sentence-final particles, including 啦, 耶 and 吧 [32]. Examples are *illustrative*.
- **喔:** friendly reminder or softener. 記得來喔
- **欸:** getting attention or surprise. 欸，真的假的
- **啦:** casual insistence or reassurance. 沒關係啦
- **耶:** excited emphasis. 好好聽耶
- **吧:** suggestion. 一起去吧
- **捏 / 餒:** cute spellings of 呢 or 內, for playful or young posts. 好可愛捏
- **齁:** an exasperated "right?".
- **蛤:** "huh?".
- Laughter: 哈哈哈, XD, 笑死.

**Formality & address:**
- Microsoft uses 您 for singular "you" in products and 你們 (not 您們) for plural [3]. Social posts mostly use 你 for warmth.
- Use 大家 and 各位 for groups. Brand pages often speak as 小編.
- Avoid 妳 unless the user writes it [20].
- Microsoft's guide replaces 外勞 with 移工, 大陸妹 with 中國籍女性, and 黑名單/白名單 with 封鎖清單/允許清單. It also prefers 同仁 or 各位 over gendered group address [3].

**Mixing languages:**
- English brand names and short English words are common.
- Japanese loans via Hokkien: 便當, 達人 [32]. Hokkien words: 歹勢, 夯 [32].
- A light Hokkien touch reads local. Heavy Hokkien from a non-Hokkien voice reads forced.

**Tone & humour on social:**
- Warm, polite and chatty. Self-deprecation and cute softening work well.
- Sponsored-sounding superlatives (史上最強, 必買) read as 業配 (paid placement).
- Mainland vocabulary draws "支語" criticism. The label itself is controversial, and some flagged words are really Cantonese or old Chinese [24].
- *Medium; check with a native reader.*

**Platform habits:**
- Threads: conversational first-person posts with few or no hashtags.
- Instagram: moderate emoji, place hashtags (#台北 #台中).
- Dcard and PTT: forum titles often carry a bracketed tag such as [心得] or [情報] (Medium).
- Calls to action: 「點連結報名」, 「私訊小編」, 「記得按讚追蹤」 (*illustrative*).
- Spam signals: "加LINE" invitations, emoji walls, Simplified characters, mainland slang.

**Formats:**
- Dates: 2026/9/16 short; 9/16（週三）with weekday; 2026年9月16日 long [1].
- The ROC era appears in government and forms: 民國115年 = 2026. CLDR's ROC calendar uses 民國 [1].
- Time uses flexible day periods: 下午3:00, 晚上7:30, 凌晨 [1].
- Numbers group with commas. Large numbers compact to 萬/億 (1.2萬) [1].
- Currency: CLDR name 新台幣, symbol $ [1]. Posts use NT$ or 元 (e.g. 500元), and 塊 colloquially.

**Names of people & works:**
- Transliterations: 蕭邦, 莫札特 (≠ HK and CN 莫扎特), 德布西, 拉赫曼尼諾夫 and 柴科夫斯基 appear in NSO/NTSO listings [37]. Beethoven is 貝多芬 in all regions.
- Numbered works keep 號: 第二十一號鋼琴協奏曲 [37].
- Put single pieces or songs in 〈〉 and albums in 《》 [11].
- Foreign full names take the separating dot [11].

**Sensitivities:**
- Naming: write 台灣, never 中國台灣 or 台灣省.
- The pan-green side prefers 中國 for the PRC and the pan-blue side 中國大陸, so naming signals politics [18]. For neutral posts, avoid the topic or follow the user.
- Avoid mainland vocabulary and slang [24], and the dated terms listed under Formality [3].

**Search aliases:** Taiwan, Taiwanese, Taiwanese Mandarin, Traditional Chinese (Taiwan), Chinese (Taiwan), zh-TW, zh_TW, zh-Hant-TW, zh-Hant, TW, ROC, Formosa, 台灣, 臺灣, 台湾, 繁體中文, 正體中文, 繁中, 國語, 華語, 台灣華語, 台式中文

**Prompt guide (≤120 words):**
Write Taiwan Mandarin in Traditional characters (著, 裡; 台 in casual posts). Use 「」 quotes, 《》 for albums and books, 〈〉 for single songs or pieces. Use Taiwan vocabulary: 軟體, 網路, 影片, 資訊, 品質, 計程車, 捷運, 按讚, 印表機. Avoid mainland forms (視頻, 質量, 信息, 網絡, 優化), which read as foreign and draw criticism. Keep the tone warm and polite, with light particles where natural (喔, 欸, 啦, 耶, 吧). Use 你 and not 妳 unless known. Use Taiwan names (蕭邦, 莫札特, 德布西) and 第…號 for numbered works. Write dates as 9/16（週三）, times as 晚上7:30, money as NT$ or 元.

**Confidence:**
- Where used: High
- Script & spelling: High; Medium for the 臺/台 split
- Punctuation: High
- Words: High for taxi, software, network, printer, metro; Medium for "awesome" and piano lesson
- Particles: Medium (only 啦, 耶, 吧 verified by source)
- Formality: High for Microsoft's rules; Medium for social norms
- Mixing: High
- Tone: Medium
- Platform habits: Medium
- Formats: High
- Names: High
- Sensitivities: High
- Aliases: High

**Native check:**
- Are 捏 and 餒 still current, or already dated?
- Are PTT-style [心得] tags natural for Dcard titles?
- Is 台 vs 臺 ever noticed in a brand post?
- Is 單車 vs 腳踏車 generational or regional?
- Which "awesome" words feel current (超讚, 好猛, 太神)?
- How many hashtags do Taiwanese Threads users actually use?

**Sources:** [1] [3] [7] [9] [10] [11] [13] [18] [20] [24] [30] [31] [32] [33] [34] [35] [36] [37] [38]

---

### 简体中文（中国大陆）· Chinese (Simplified, Mainland China) — `zh-Hans-CN`

**Where it's used / platforms:**
- **Xiaohongshu (rednote):** image and video "notes" and 种草-style recommendations. Early users were mostly young urban women. It suspends accounts that move users off-platform, for example by sharing WeChat contacts [42][44].
- **Weibo:** #topic# tags, trending lists, posts up to 2,000 characters [41].
- **Also:** Douyin short-video captions; WeChat (public-account articles, Moments, Channels); Bilibili; Zhihu.

**Script & spelling:**
- Simplified characters per 《通用规范汉字表》 (State Council, 2013). It has three levels and is the standard for general public use [39].
- Traditional characters in a mainland post read as Hong Kong or Taiwan, or as a deliberate artistic choice.
- Pinyin or Latin abbreviations appear in casual posts. Examples are yyds (永远的神, from esports) [43] and NB [45].

**Punctuation & typography:**
- GB/T 15834-2011: horizontal text uses “ ” and then ‘ ’. Corner brackets are for vertical text [9].
- 《》 for all titles, 〈〉 for a title nested inside one. Full-width marks; the full stop sits bottom-left in type [9].
- · separates the parts of foreign names [9].
- Microsoft's Simplified guide spaces Latin letters and digits away from Chinese in product text [4]. Many social posts don't.
- Xiaohongshu titles often use 【】 and emoji as bullets (Medium).

**Words that mark the region:**

| Concept | zh-Hans-CN | Siblings |
|---|---|---|
| taxi | 出租车 (打车) [7][13] | HK 的士 · yue 的士 · TW 計程車 · SG 德士 |
| software | 软件 [13] | HK 軟件 · yue 軟件 · TW 軟體 · SG 软件 |
| video | 视频 [10] | HK 影片 · yue 條片 · TW 影片 · SG 视频 |
| bus | 公交车, 公交 [13] | HK 巴士 · yue 巴士 · TW 公車 · SG 巴士 |
| quality | 质量 (素质 for people) [12][13] | HK 質素 · yue 質素 · TW 品質 · SG 质量 |
| information | 信息 [7][10] | HK 資訊 · yue 資料 · TW 資訊 · SG 资讯 |
| internet / online | 网络, 互联网; 网上 [10] | HK 網絡 · yue 網上 · TW 網路 · SG 网络 |
| program (software) | 程序, 应用, App [7] | HK 程式 · yue app · TW 程式 · SG 应用程序 |
| programme | 节目, 节目单 | HK 節目 · yue 節目 · TW 節目 · SG 节目 |
| mobile phone | 手机 [10] | HK 手機 · yue 手機 · TW 手機 · SG 手机 |
| subway | 地铁 [13] | HK 港鐵 · yue 港鐵 · TW 捷運 · SG 地铁 |
| bicycle | 自行车; 单车 for shared bikes [13] | HK 單車 · yue 單車 · TW 腳踏車 · SG 脚车 |
| printer | 打印机 [7] | HK 打印機 · yue printer · TW 印表機 · SG 打印机 |
| data | 数据 [7] | HK 數據 · yue data · TW 資料 · SG 数据 |
| click | 点击 [10] | HK 點擊 · yue 撳 · TW 點選 · SG 点击 |
| like (social) | 点赞 | HK 讚好 · yue 讚 · TW 按讚 · SG 点赞 |
| concert / recital | 音乐会, 独奏音乐会 [46] | HK 獨奏會 · yue concert · TW 獨奏會 · SG 音乐会 |
| piano lesson | 钢琴课 | HK 鋼琴課 · yue 琴堂 · TW 鋼琴課 · SG 钢琴课 |
| weekend | 周末 (weekday 周三) [1][46] | HK 週末 · yue 星期六日 · TW 週末 · SG 周末 |
| "awesome" | 太棒了, 绝了, 牛; dated: yyds, 绝绝子 [43] | HK 精彩 · yue 好正 · TW 超讚 · SG 很棒 |

**Particles, interjections & fillers:**
- Common particles: 啊, 呀, 啦, 哦, 呢, 吧, 嘛. Laughter: 哈哈哈.
- Community address terms: 家人们, 宝子们, 姐妹们.
- 集美 (from 姐妹) began as affectionate and now often reads sarcastic or offensive [44]. Treat trendy address terms as perishable.
- 种草 means making someone want to buy; 拔草 is the opposite [44].
- 绝绝子 and 集美 spread in the same wave as yyds [43]. By 2026 they read dated or parodic.

**Formality & address:**
- Microsoft's Simplified guide uses 你 (not 您) in products and omits pronouns where it can [4]. That contrasts with its Taiwan guide [3].
- 您 suits customer service and older audiences.
- 家人们 and 姐妹们 are livestream and community styles. 姐妹们 assumes a female audience, so use 大家 unless the user targets women.
- Microsoft's guide avoids 剩女, 娘炮, 女秘书 (use 秘书), 老外 (use 外国人) and 乡下人 (use 农村人) [4].

**Mixing languages:**
- English brand and product names stay as written. Some English lifestyle words appear on Xiaohongshu.
- Pinyin initialisms and Latin slang are informal [43][45]. Keep them out of professional posts unless the user uses them.

**Tone & humour on social:**
- Xiaohongshu rewards a first-person, "I tried it" tone with practical detail. Obvious ads get penalised as marketing.
- Weibo is more public-commentary and fan-driven.
- Advertising law bans 国家级, 最高级 and 最佳-type terms in ads [40]. Platforms also scan for similar absolute claims. Promotional drafts should use concrete facts, not superlatives.
- Humble-bragging draws mockery.
- *Medium for the social norms.*

**Platform habits:**
- **Weibo:** #话题# with a hash mark on both sides [41].
- **Xiaohongshu:** an emoji-rich title; short paragraphs with emoji bullets; single-# topic tags at the end; no external links, phone numbers or WeChat IDs [42]. Calls to action: 「点赞收藏」, 「评论区聊聊」 (*illustrative*).
- **Douyin:** a short caption plus #tags.
- **WeChat public accounts:** longer articles with subheadings.
- **Spam signals:** 引流 (moving users off-platform), extreme superlatives, emoji and hashtag walls.

**Formats:**
- Dates: 2026年9月16日 long; 2026/9/16 short; 9/16周三 with weekday [1].
- Time: 24-hour (19:30) by default in CLDR [1]. Posts also write 晚上7点.
- Numbers: commas; compact 万/亿 (1.2万) [1].
- Currency: symbol ¥, name 人民币 [1]. Posts also write 元, 块 colloquially, or RMB.

**Names of people & works:**
- Composer names observed at the NCPA [46]: 肖邦 (萧邦 also appears), 莫扎特, 德彪西, 拉赫玛尼诺夫, 普罗科菲耶夫, 贝多芬. A recital is 钢琴独奏音乐会.
- All titles take 《》, and foreign names take · [9].

**Sensitivities:**
- Platforms filter by keyword aggressively and delete fast [41]. Users evade with homophones such as 河蟹 [45]. Brand drafts should avoid political topics rather than use evasions.
- PRC usage pairs 大陆 with Taiwan and uses 内地 relative to Hong Kong and Macau [18].
- Never list Taiwan, Hong Kong or Macau as countries. Use 国家和地区 and 中国香港 or 中国台湾 in lists (Medium; standard practice, not directly sourced).
- Microsoft's guide uses 朝鲜 (not 北朝鲜) [4].
- Advertising law also applies [40].

**Search aliases:** Simplified Chinese, Chinese (China), Chinese (Simplified), Mandarin, Putonghua, Mainland Chinese, PRC, China, CN, zh-CN, zh_CN, zh-Hans, zh-Hans-CN, 中文, 简体中文, 简中, 普通话, 汉语, 国语 (mainland usage rare), 中国大陆, 大陆, 内地

**Prompt guide (≤120 words):**
Write mainland Simplified Chinese with “” quotes and 《》 for every title. Use mainland vocabulary: 视频, 软件, 网络, 信息, 质量, 出租车, 地铁, 点赞, 音乐会. Never use Taiwan or Hong Kong forms (軟體, 網路, 的士, 影片 for online video). Match the platform: Xiaohongshu gets a first-person tone, emoji bullets, short lines, #tags at the end, and no links or WeChat IDs. Weibo uses #话题#. Don't use ad-banned superlatives (国家级, 最高级, 最佳) or similar absolute claims. Avoid political topics and never list 台湾 or 香港 as countries. Use slang sparingly and skip dated memes (绝绝子, yyds). Use mainland names (肖邦, 德彪西, 拉赫玛尼诺夫), ¥ or 元 for money, and 19:30 or 晚上7点 for time.

**Confidence:**
- Where used: High
- Script: High
- Punctuation: High
- Words: High
- Particles and slang: Medium (slang turns over fast)
- Formality: Medium
- Mixing: Medium
- Tone: Medium
- Platform habits: High for Weibo and the Xiaohongshu link ban; Medium for layout habits
- Formats: High
- Names: High
- Sensitivities: High for the law, filtering and 内地/大陆; Medium for list-naming practice
- Aliases: High

**Native check:**
- Which address terms and praise words are current in September 2026 (家人们, 宝子们, 绝了)?
- Does Xiaohongshu still use single-# tags, and how many?
- Which "absolute" words beyond the statute (第一, 顶级, 唯一) trigger platform warnings for arts or education posts?
- Is 萧邦 still seen in mainland arts marketing, or only 肖邦?
- For piano-teaching accounts, is 钢琴课 or 钢琴陪练 more natural?

**Sources:** [1] [4] [7] [9] [10] [12] [13] [18] [39] [40] [41] [42] [43] [44] [45] [46]

---

### 简体中文（新加坡）· Chinese (Simplified, Singapore) — `zh-Hans-SG`

*Written as differences from `zh-Hans-CN`, plus a Malaysia note.*

**Where it's used / platforms:**
- Singapore Chinese (华语/华文) news, community groups, education, arts and business.
- Social platforms are the same global ones as English-language Singapore (Facebook, Instagram, WhatsApp, TikTok, YouTube). Many posts are bilingual.
- *Platform list is Low confidence: not directly sourced.*

**Script & spelling:**
- Simplified characters. Singapore used Traditional until 1969, had its own simplification list from 1969 to 1976, and then fully adopted the mainland set [47].
- Standard grammar in formal writing. Colloquial speech shows Hokkien and Cantonese influence, for example 先 after the verb [48].

**Punctuation & typography:** “” quotes (CLDR and Zaobao) [1][10]; 《》 titles. Otherwise the same as mainland.

**Words that mark the region:**

| Concept | zh-Hans-SG | Siblings |
|---|---|---|
| taxi | 德士 [47][48] | HK 的士 · yue 的士 · TW 計程車 · CN 出租车 |
| software | 软件 [13] | HK 軟件 · yue 軟件 · TW 軟體 · CN 软件 |
| video | 视频 [10] | HK 影片 · yue 條片 · TW 影片 · CN 视频 |
| bus | 巴士 [47] | HK 巴士 · yue 巴士 · TW 公車 · CN 公交车 |
| quality | 质量 [10] | HK 質素 · yue 質素 · TW 品質 · CN 质量 |
| information | 资讯, 信息 [10] | HK 資訊 · yue 資料 · TW 資訊 · CN 信息 |
| internet / online | 网络 [10] | HK 網絡 · yue 網上 · TW 網路 · CN 网络 |
| program (software) | 应用程序, App [13] | HK 程式 · yue app · TW 程式 · CN 程序 |
| programme | 节目 | HK 節目 · yue 節目 · TW 節目 · CN 节目 |
| mobile phone | 手机 [10] | HK 手機 · yue 手機 · TW 手機 · CN 手机 |
| subway | 地铁 (MRT) [10] | HK 港鐵 · yue 港鐵 · TW 捷運 · CN 地铁 |
| bicycle | 脚车 [48] | HK 單車 · yue 單車 · TW 腳踏車 · CN 自行车 |
| printer | 打印机 [13] | HK 打印機 · yue printer · TW 印表機 · CN 打印机 |
| data | 数据 | HK 數據 · yue data · TW 資料 · CN 数据 |
| click | 点击 | HK 點擊 · yue 撳 · TW 點選 · CN 点击 |
| like (social) | 点赞, like | HK 讚好 · yue 讚 · TW 按讚 · CN 点赞 |
| concert / recital | 音乐会 | HK 獨奏會 · yue concert · TW 獨奏會 · CN 独奏音乐会 |
| piano lesson | 钢琴课 | HK 鋼琴課 · yue 琴堂 · TW 鋼琴課 · CN 钢琴课 |
| weekend | 周末 [10] | HK 週末 · yue 星期六日 · TW 週末 · CN 周末 |
| "awesome" | 很棒, 厉害 | HK 精彩 · yue 好正 · TW 超讚 · CN 太棒了 |

Local words with no mainland counterpart:
- 组屋 (public HDB flat) [10][48]
- 巴刹 (market, from Malay *pasar*) [47]
- 巴仙 (percent) [47]
- 乐龄 (senior) [48]
- 甘榜 (village, from *kampung*) [47]
- 罗厘 (lorry) [48]
- 拥车证 (Certificate of Entitlement) [48]
- 固本 (coupon) [48]

The Singapore Mandarin Council keeps a 新加坡华语资料库 of culturally specific terms [49].

**Particles, interjections & fillers:** 啦, 咯, 嘛 and other Hokkien- or Cantonese-influenced particles in casual writing [48][51]. The English-side "lah" belongs to Singlish captions, not Chinese ones. Avoid Taiwan-style 喔/耶 stacking and mainland meme slang.

**Formality & address:** Same as mainland. Use 大家 or 各位; 您 for elders and customers.

**Mixing languages:**
- Loans from Malay (巴刹, 甘榜), Hokkien and English (巴仙) [47].
- Local acronyms and place names usually stay in English inside Chinese copy (MRT, HDB) (Medium).

**Tone & humour on social:** Practical and friendly. Community events often mention 乐龄 audiences (Low).

**Platform habits:** Bilingual captions are common. No Weibo-style #话题#; use plain #tags (Low).

**Formats:**
- CLDR short date: dd/MM/yy (16/09/26) [1]. Long: 2026年9月16日 [1].
- Time: 下午3:00 [1].
- Currency: CLDR symbol $, name 新加坡元 [1]. Posts often use S$ or 新元.
- Compact numbers: 万 [1].

**Names of people & works:** Wikipedia's zh-sg variant gives 肖邦 and 莫扎特, following the mainland [21]. *Low confidence: no Singapore arts-organisation source verified.*

**Sensitivities:** Race and religion are legally protected areas. The Maintenance of Religious Harmony Act was passed in 1990 and amended in 2019 [52]. Avoid commentary on either.

**Malaysia note (`zh-Hans-MY`):**
- Simplified characters and “” quotes (Sin Chew, China Press) [10].
- Currency: RM or 令吉. CLDR has no main symbol, only a narrow RM, with the name 马来西亚令吉 [1][10].
- Sin Chew uses 视频, 点赞 and 巴刹 [10]. 德士 and 巴士 are shared with Singapore [50].
- Cantonese (Klang Valley) and Hokkien (north) influence varies by region. Particles include 啦, 咯, 嘛 [50].
- Speakers switch to Malay or English for local terms even when a Mandarin term exists [51].
- Standards body: 马来西亚华语规范理事会 [50].
- CLDR's MY short date is y/M/d [1]. Everyday practice may differ (see Native check).

**Search aliases:** Singapore Chinese, Singaporean Mandarin, Chinese (Singapore), Mandarin (Singapore), zh-SG, zh_SG, zh-Hans-SG, SG, 新加坡, 新加坡华语, 新加坡华文, 华文, 华语, 狮城, 星洲, Malaysian Chinese, Malaysian Mandarin, Chinese (Malaysia), zh-MY, zh-Hans-MY, MY, 马来西亚, 马来西亚华语, 大马, 马华, 新马

**Prompt guide (≤120 words):**
Write Singapore Chinese in Simplified characters with “” quotes and standard grammar. Use Singapore words where they fit: 德士, 巴士, 组屋, 巴刹, 脚车, 乐龄. Keep local acronyms and place names in English (MRT, HDB). A light 啦 or 咯 is fine in casual posts. Avoid mainland meme slang and Taiwan particle stacking. Write money as S$ or 新元, dates as 16/9/2026 or 2026年9月16日, and times as 下午3:00. Stay away from race and religion. For `zh-Hans-MY`, use RM or 令吉 and Malaysian place names, and allow a little Cantonese or Hokkien flavour only if the user's samples show it.

**Confidence:**
- Where used: Low
- Script: High
- Punctuation: High
- Words: High for local terms; Medium for printer, program, "awesome"
- Particles: Medium
- Formality: Medium
- Mixing: Medium
- Tone: Low
- Platform habits: Low
- Formats: High (CLDR)
- Names: Low
- Sensitivities: High
- Malaysia note: Medium

**Native check:**
- Do Singapore and Malaysia arts groups write 肖邦 or 萧邦, 莫扎特 or 莫札特, 德彪西 or 德布西?
- Singapore: 独奏会 or 独奏音乐会?
- Malaysia: is the everyday date d/M/y (CLDR says y/M/d)?
- Is S$ or plain $ normal in Singapore Chinese captions?
- How much English (MRT, HDB, "lah") is natural inside Chinese captions for a professional account?

**Sources:** [1] [10] [13] [21] [47] [48] [49] [50] [51] [52]

---

### Open questions

1. **Blend control for Hong Kong.** Should the yue/zh-HK pair be one locale with a register slider (書面語 → blend → full Cantonese) rather than two picker entries? HK posts sit on a continuum, and the user's samples should set where.
2. **User habits vs defaults.** When a user's samples show 既/左/架, 臺, or no spaces between Chinese and English, the style guide should defer to the user. How should the guide and the voice profile rank against each other?
3. **Name glossary.** Classical-music transliterations differ by region in ways converters and Wikipedia variants get wrong (Wikipedia zh-hk says 莫札特; the HK Phil uses 莫扎特). A curated per-locale glossary with a "keep English names" option seems necessary.
4. **Macau and Malaysia depth.** Is `zh-Hant-MO` an alias of HK with currency and quote swaps, or its own Tier 1? The Macau government uses “” while Macau media use 「」. Malaysia's date and name conventions are unverified.
5. **Slang shelf life.** Mainland slang ages fast (集美 turned sarcastic). Should the CN guide ship no slang by default, with a refresh cadence for an allow-list?
6. **Platform rules drift.** Xiaohongshu's link and contact bans, and advertising-law word lists, change over time. Consistent with "remind, don't block": surface these as reminders on the draft, never as failures.
7. **No Microsoft zh-HK guide.** HK guidance rests on CSB manuals, CLDR and observation. A native reviewer pass on the HK and yue entries is the highest-value check.
8. **Conversion pipeline.** If any Traditional/Simplified conversion stays in the product (e.g. repurposing a zh-CN draft), use it only as a pre-step followed by a locale vocabulary rewrite. `s2hkp`'s roughly 82 entries cannot localize to Hong Kong.


---

## English family

Research date: 2026-09-16. Scope: `en-US`, `en-GB`, `en-GB-scotland`, `en-IE`, `en-AU`, `en-NZ`, `en-CA`, `en-IN`, `en-SG`. Source numbers are global to this file; each entry lists the ones it cites.

### Family notes

**How the entries fit together.** `en-US` and `en-GB` are full entries. The others are written as deltas: `en-GB-scotland`, `en-IE`, `en-AU` and `en-IN` against `en-GB`, `en-SG` against `en-GB`, `en-NZ` against `en-AU`, and `en-CA` against `en-US`. Anything a delta leaves out is the same as its sibling.

**Five points that hold across the family**

1. **Spelling is the cheapest marker and the easiest to get wrong.** Pick one system and keep to it for the whole post. Canadian spelling is its own mix (-our + -ize + travelled + program) [47][48][49]. Australian style goes by the first spelling Macquarie lists [35].
2. **Wider audience, fewer local words.** Large Twitter studies found people use fewer local or non-standard words when they expect a bigger audience. Scottish users used fewer Scots forms in hashtagged referendum tweets than in their everyday tweets [22]. A public post should carry lighter dialect than a reply.
3. **How much self-promotion people accept is the biggest tone difference.** US audiences accept outcomes stated plainly. UK readers, and by several accounts other Commonwealth readers, tend to read the same claim as arrogance and respond better to specifics and shared credit [12][38].
4. **The same word can be mild in one variety and rude in another.** "fanny" (US: bottom; UK/IE/AU: vulgar) [16], "pissed" (US: angry; UK: drunk) [17], and "root" (AU: sex) [40] are the classic traps.
5. **Formats come from CLDR, with caveats.** Week start: Sunday in US, CA, IN and SG; Monday in GB, IE, AU and NZ [7]. CLDR's preferred clock is 24-hour for GB and IE and 12-hour for the rest [8], but everyday UK social posts use "7pm" freely [3][6].

**Comparison table**

| Locale | Spelling pattern | Quote style (editorial) | Date (numeric · written) | Signature words | Tone in one phrase |
|---|---|---|---|---|---|
| `en-US` | -ize, -or, -er, traveled, program | double " ", commas/periods inside | 9/16/26 · September 16, 2026 | mom, vacation, apartment, college | upbeat, direct, outcome-first |
| `en-GB` | -ise (media), -our, -re, travelled, programme | single common in books, double in BBC-style journalism; punctuation placed by logic | 16/09/2026 · 16 September 2026 | mum, flat, holiday, reckon | understated, dry, self-deprecating |
| `en-GB-scotland` | as en-GB | as en-GB | as en-GB | wee, aye, outwith, How? (= why) | dry, blunt, deadpan; Scots forms mostly in replies |
| `en-IE` | as en-GB | as en-GB | 16/09/2026 · 16 September 2026 | grand, craic, giving out, fair play | warm, slagging, deflates pretension |
| `en-AU` | Macquarie first spelling (-ise, -our) | single (government style) | 16/9/26 · 16 September 2026 | arvo, heaps, reckon, no worries | casual, egalitarian, wary of tall poppies |
| `en-NZ` | British-based, Māori words with macrons | single and double both used | 16/09/2026 · 16 September 2026 | kia ora, whānau, togs, sweet as | low-key, friendly, modest |
| `en-CA` | -our + -ize + -re + travelled; program; cheque | double, US placement | 2026-09-16 (official) · September 16, 2026 | toque, washroom, loonie, eh | friendly, polite, less brash than US |
| `en-IN` | British (-ise, -our) | not verified | 16/09/2026 or 16-09-2026 · 16 September 2026 | prepone, lakh, crore, kindly | warm, respectful, formal-leaning |
| `en-SG` | British (-ise, -our) | not verified | 16/9/26 · 16 September 2026 | chope, shiok, kiasu, lah (Singlish) | efficient; Singlish is playful and in-group |

---

### English (United States) · American English — `en-US`

**Where it's used / platforms:** United States. It is also the default "English" of most global platforms and AI tools, so it is the variety the drafting model drifts towards unless told otherwise. Main channels: Instagram, LinkedIn, X, Threads, Facebook, TikTok, YouTube.

**Script & spelling:** -ize/-yze (organize, analyze), -or (color, honor), -er (center, theater, although some venues keep "Theatre" in their names), a single l before a suffix (traveled, canceled), program, defense, license, catalog, gray, check (bank), tire, curb. "Practice" is both noun and verb.

**Punctuation & typography:**
- Double quotation marks, with single marks for a quote inside a quote.
- AP style puts periods and commas inside the closing quote every time, and other marks only when they belong to the quoted words [13].
- AP spaces the em dash on both sides [14]. Book and Chicago style closes it up (general practice).
- AP leaves out the serial comma in a simple list, but Chicago uses it [15]. Both are common on social media.
- Abbreviations take a period: Mr., Dr., Mrs. [5]. AP writes "a.m./p.m." and drops ":00" [14]. Casual posts often write "7pm" or "7 PM".

**Words that mark the region:**

| concept | en-US | sibling locales |
|---|---|---|
| mother | mom | mum (GB, AU, NZ); mam/mammy (IE, unverified); mom (CA) |
| where you live | apartment | flat (GB, IE); unit/apartment (AU) |
| time off | vacation | holiday (GB, IE, AU, NZ) |
| higher education | college, school | uni (GB, AU, NZ) |
| waiting in order | line | queue (GB, IE, AU, NZ, SG) |
| the round-ball sport | soccer | football (GB, IE); soccer/football (AU) |
| the school subject | math | maths (GB, IE, AU, NZ, IN, SG) |
| waist pouch | fanny pack | bum bag (GB) [16][17] |
| supporting a team | root for | barrack for (AU, unverified); "root" is sexual in AU [40] |

**Particles, interjections & fillers:** "so" and "super" as intensifiers, "awesome", "love this", "y'all" (Southern, but widely used online), "gonna/wanna" in casual posts. Keep them light, because a pile of them reads as teen-brand copy.

**Formality & address:** First names by default, even with senior people. Titles show up mainly in medicine ("Dr.") and politics. Greetings are simple ("Hi everyone").

**Mixing languages:** Some Spanish in Latino communities (Spanglish). Don't add it unless the user writes that way.

**Tone & humour on social:** Direct and outcome-first. Stating an achievement plainly ("I built…") comes across as confident, not arrogant [12]. Enthusiasm and sincerity are accepted. Launch clichés (illustrative: "Thrilled to announce…") are so common they read as boilerplate. Humblebrags and invented stats read as salesy.

**Platform habits:** A clear call to action is normal (illustrative: "Tickets at the link in bio"). Keep hashtags few and specific. Short paragraphs with line breaks are standard on LinkedIn and Instagram. Spam signals: ALL CAPS, strings of emoji, "DM me to learn more", stacks of more than about 5 hashtags. (Low confidence: no corpus source.)

**Formats:**
- Dates: 9/16/26; September 16, 2026 [9].
- Time: 12-hour [8].
- Week starts on Sunday [7].
- Money: $1,234.56, symbol before the amount.
- Units: imperial. °F, miles, pounds, feet and inches, cups and ounces in recipes.

**Names of people & works:**
- AP puts quotation marks around titles of books, songs, TV shows, poems and works of art, not italics [14]. Book style uses italics, which most platforms can't show, so use quotes or plain Title Case.
- US usage follows the composer's own spelling "Rachmaninoff" [18][19].
- Generic titles (Piano Concerto No. 2) are usually left unquoted (unverified for AP).

**Sensitivities:**
- "Pissed" means angry in the US but drunk in Britain [17].
- "Fanny" is mild in the US but vulgar in UK, IE and AU [16].
- "Rooting for" reads as a double entendre to Australian and New Zealand readers [40].
- Politically coded vocabulary splits audiences sharply, so keep neutral unless the brief takes a side.

**Search aliases:** American, American English, US, U.S., USA, United States, America, US English, General American, Yankee English

**Prompt guide (≤120 words):** Write in American English. Use -ize/-or/-er spellings, a single l in "traveled", and "program". Use double quotes, with commas and periods inside them. Dates look like "September 16" or 9/16. Times use 12 hours ("7:30 PM" or "7:30 p.m."). Use dollars and imperial units. Lead with the point or outcome and state accomplishments plainly and confidently, without hedging. Warmth and enthusiasm are fine, but avoid stock launch phrases and invented numbers. Give one clear call to action. Use few, specific hashtags. Never use "fanny" or "pissed" loosely if the post may reach UK or Australian readers.

**Confidence:**
- Where/platforms: High
- Spelling: High
- Punctuation: High (AP/Chicago split noted)
- Words: High
- Particles: Medium
- Formality: Medium
- Mixing: Medium
- Tone: Medium (marketing-blog source)
- Platform habits: Low
- Formats: High
- Names & works: Medium
- Sensitivities: High

**Native check:**
- Is a spaced em dash (AP) or a closed one (book style) more natural in personal social posts?
- Are "7pm", "7 PM" or "7 p.m." most common in creator posts?
- How strongly does "thrilled to announce" read as a cliché among US LinkedIn users?
- Do US classical audiences and presenters use "Rachmaninoff" consistently?

**Sources:** [5] [7] [8] [9] [12] [13] [14] [15] [16] [17] [18] [19] [40]

---

### English (United Kingdom) · British English — `en-GB`

**Where it's used / platforms:** England, Wales, Scotland and Northern Ireland. Scottish-specific markers are in `en-GB-scotland`. Main channels are the same as en-US. LinkedIn, Instagram, X/Threads and Facebook community groups are strong.

**Script & spelling:**
- Most UK newspapers use -ise [1], and so does GOV.UK ("organise", "modelling") [3].
- Oxford -ize is also correct British (OUP, *Nature*), but *The Times* dropped it in 1992 [1]. For everyday social posts, use -ise.
- -our, -re (centre, metre), travelled/cancelled, programme (but a computer "program").
- Noun/verb pairs: practice/practise, licence/license.
- defence, cheque, grey, tyre, kerb, aluminium.
- The BBC's list of accepted -ise verbs includes finalise and publicise [4].

**Punctuation & typography:**
- Quote marks: single marks are more usual in UK books, while journalism often uses double [2]. GOV.UK uses double for direct speech and single for unusual terms and titles [3].
- Punctuation goes by logic: outside the closing quote unless it belongs to the quoted words [2].
- No full stop after contractions: Mr, Dr, Mrs, Revd [5]. GOV.UK also drops them in abbreviations generally (BBC, eg) [3].
- Times are written "5:30pm" [3], and "7.30pm" with a dot is also common [6].
- Dashes: the spaced en dash ( – ) is widespread in UK publishing (not verified here).
- The serial comma is optional, and many UK outlets leave it out (not verified here).

**Words that mark the region:**

| concept | en-GB | sibling locales |
|---|---|---|
| mother | mum | mom (US, CA); mam (IE, unverified) |
| where you live | flat | apartment (US, CA) |
| time off | holiday | vacation (US, CA) |
| university | uni | college (US) |
| waiting in order | queue | line (US) |
| the round-ball sport | football | soccer (US; often AU) |
| the school subject | maths | math (US, CA) |
| phone | mobile | cell phone (US), cell (CA) |
| thanks, informal | cheers | thanks (US) |
| think / eager | reckon / keen | also AU, NZ, IE |
| drunk | pissed | angry (US) [17] |

**Particles, interjections & fillers:** "a bit", "quite" (usually meaning "fairly"), "to be fair", "lovely", "brilliant", "cheers", "mate". Regional or youth forms ("innit", "proper", "ta") should only appear if the user uses them.

**Formality & address:** First names and a light "Hi all". A kiss sign-off ("x") is common among friends but out of place for a brand (Low).

**Mixing languages:** Welsh greetings in Wales (illustrative: "Diolch" for thanks). Scots and Gaelic: see the Scottish entry. Multicultural London slang among young people: don't imitate it.

**Tone & humour on social:**
- English social life runs on irony, understatement and self-deprecation, and people avoid anything that sounds earnest or too eager [11].
- On LinkedIn, overt self-promotion reads as arrogance. What works is concrete detail, named methods, honest setbacks and team credit [12].
- Use exclamation marks sparingly. A dry aside lands better than hype.
- Sincerity works when it's specific.

**Platform habits:** Fewer hashtags than US posts. A soft call to action (illustrative: "Tickets are on sale now if you fancy it"). Salesy urgency and superlatives read as spam. (Low confidence: no corpus source.)

**Formats:**
- Dates: 16/09/2026; "4 June 2017" with no comma [3][9].
- Time: 24-hour in timetables, 12-hour in everyday writing [6]. CLDR prefers 24-hour [8], but social posts use "7pm".
- Week starts on Monday [7].
- Money: £1,250, and "£75" rather than "£75.00" [3]. Media shorthand "£5m" (general practice).
- Units: mixed. Miles and mph on roads, pints, body weight in stone; °C and metric elsewhere (general practice).

**Names of people & works:**
- Sports teams take plural verbs ("England are…") [4], a strong British marker.
- Titles: book style uses italics. GOV.UK puts publication titles in single quotes [3].
- Composer spellings: European organisations and record labels often use "Rachmaninov" [18]. Scholarly catalogues also use -ov, while the composer himself used -off [19]. Follow the UK venue's own spelling (see Native check).

**Sensitivities:**
- Don't use "British" when you mean "English", or the other way round, and don't use "Anglo" for British [4].
- The UK is Great Britain plus Northern Ireland [4]. "British Isles" irritates many Irish readers [29].
- Wales dislikes "the Principality" as a name for itself [4].
- "Scotch" is only for whisky and a few foods [4].
- Derry/Londonderry is politically coded [30].
- "Fanny" is vulgar [16].

**Search aliases:** British, British English, UK, U.K., United Kingdom, Britain, Great Britain, England, English (England), Welsh English, Northern Irish, Brit, BrE, Queen's English, King's English, RP

**Prompt guide (≤120 words):** Write in British English. Use -ise, -our and -re spellings, "travelled" and "programme". No full stop after Mr or Dr. Punctuation goes outside quotes unless it belongs to the quote. Dates look like "16 September". Times look like "7pm" or "7.30pm". Use £ without ".00". Treat team names as plural ("the band are…"). Understate. Show credibility through specifics and team credit, not claims. Allow a light, dry or self-deprecating line. Go easy on exclamation marks and hype. Use a soft call to action. Never use "English" when you mean "British". Use mum, holiday, queue, maths and uni.

**Confidence:**
- Where/platforms: High
- Spelling: High
- Punctuation: Medium (Guardian style guide couldn't be fetched; dash and serial comma unverified)
- Words: High
- Particles: Medium
- Formality: Medium
- Mixing: Low
- Tone: Medium-High
- Platform habits: Low
- Formats: High
- Names & works: Medium
- Sensitivities: High

**Native check:**
- For personal posts, which is more natural: single or double quotes, and a spaced en dash or a closed em dash?
- "7pm" vs "7.30pm" vs "7:30pm": is there any generational split?
- Do BBC Proms, Gramophone and UK orchestras consistently use "Rachmaninov"?
- Is "x" as a sign-off acceptable for a solo creator's public post?

**Sources:** [1] [2] [3] [4] [5] [6] [7] [8] [9] [11] [12] [16] [17] [18] [19] [29] [30]

---

### Scottish Standard English · Scottish English — `en-GB-scotland` (delta against `en-GB`)

**Where it's used / platforms:**
- The IANA registry defines the variant subtag `scotland` (prefix `en`) as Scottish Standard English. This is a different thing from the Scots *language*, `sco` [20].
- Scottish Standard English is the educated, formal end of a continuum that runs to broad Scots. Many speakers switch between the two depending on the situation [21].
- This entry covers SSE with the light Scots touches normal in social posts. It is **not** written Scots.

**Script & spelling:** Same as en-GB. How much Scots shows up in ordinary posts:
- **It's a small minority.** In a year of tweets geotagged to Scotland (2013–14), Scots forms were rare next to their standard equivalents, per million words [22]:
  - "oot" 181 vs "out" 3,053
  - "tae" 186 vs "to" about 20,000
  - "fae" 77 vs "from" 2,485
  - "dinny" 62 vs "don't" 2,880
- **Swearing is the exception.** "Shite" (428) came close to "shit" (764).
- **Scots appears more in replies to individuals** than in hashtagged posts aimed at a wide audience [22][24].
- **Spelling varies by region and person** (cannae/canny/cani, with "canna" in the north-east) [24].

**Punctuation & typography:** Same as en-GB.

**Words that mark the region:** Distinctive terms found by data (not by stereotype) include aye, naw, ach, awfy, braw, bairns, weans, crabbit, feart, greetin, hunners, belter, manky, raging and steamin [22].

| concept | en-GB-scotland | en-GB |
|---|---|---|
| small | wee | little, small |
| yes (casual) | aye | yeah |
| outside the scope of | outwith (fine even in formal writing) [21][25] | outside |
| why? (esp. Glasgow/West) | How? [21][67] | Why? |
| child | bairn (East) / wean (West) [22] | kid |
| live (somewhere) | stay [21] | live |
| wait for | wait on [21] | wait for |
| lots | hunners [22] | loads |
| gloomy wet weather | dreich (frequency unverified) | grim |

**Everyday vs caricature:**
- Natural in ordinary posts: wee, aye, outwith, "How?", "waiting on", and dreich in weather posts.
- Caricature: stock tourist phrases ("och aye the noo"), and heavy "braw", "bonnie", "lassie" or "laddie" in brand copy. "Scottish Twitter" humour pages mark Scottishness with respellings plus wee and aye [23], so overdoing them reads as parody.

**Particles, interjections & fillers:** aye, naw, ach, eh (discourse markers found in the data [22]). Contemporary slang such as "defos" and "bevy" appears too [22]. Use it only if the user does.

**Formality & address:** Same as en-GB. Use Scottish institutional terms where relevant: depute, provost, procurator fiscal, interdict [21], First Minister, Scottish Government [3].

**Mixing languages:** Scots and Gaelic. Using more Scots vocabulary correlated with pro-independence hashtags [22], so heavy Scots can read as a political signal.

**Tone & humour on social:** Dry, deadpan and ready to puncture pomposity, like en-GB but blunter. Public posts stay close to standard English [22]. (Medium-Low: tone evidence is indirect.)

**Formats:** Same as en-GB (£, Monday week start).

**Names of people & works:** People are Scottish or Scots. "Scotch" is only for whisky and some foods; "whisky" has no "e" [4][26].

**Sensitivities:**
- Never call Scottish people English, or use "England" for the UK or Britain [4].
- Independence is still a live, divisive issue. Avoid Yes/No-coded hashtags and slogans [22].
- "Fanny" is also a common Scottish insult [22].
- Avoid Old Firm football and sectarian references (general caution).

**Search aliases:** Scottish, Scottish English, Scottish Standard English, SSE, Scotland, Scots English, Glaswegian, Edinburgh, Highland English, Doric (NOT this entry), Scots language `sco` (NOT this entry), Gaelic (NOT this entry)

**Prompt guide (≤120 words):** Write standard British English as a Scottish person would post it. Use -ise spellings, £ and "16 September". Allow at most one or two natural Scotticisms where they fit: "wee", "aye", "outwith", "dreich" (weather) or "waiting on". Do not respell words in Scots (tae, oot, cannae) in public posts unless the user writes that way. Never use stock phrases like "och aye the noo" or tourist-brand Scots. Say Scottish, not Scotch (except whisky), and never "English" for Scottish. Keep the tone dry and understated. Avoid independence-coded hashtags or slogans.

**Confidence:**
- Where/platforms: High
- Spelling & Scots frequency: High (2014 data; may have shifted)
- Words: Medium-High
- Everyday vs caricature: Medium
- Particles: Medium
- Formality: Medium
- Mixing: Medium
- Tone: Low-Medium
- Formats: High
- Names & works: High
- Sensitivities: High

**Native check:**
- How common are "dreich", "braw" and "the now" in 2026 posts from people under 35?
- Does "How?" meaning "why" read as broad West-coast or neutral?
- Would a Scottish arts organisation use "wee" in a public announcement?
- Does TikTok today carry more written Scots than the 2014 Twitter data showed?

**Sources:** [3] [4] [20] [21] [22] [23] [24] [25] [26] [67]

---

### English (Ireland) · Irish English / Hiberno-English — `en-IE` (delta against `en-GB`)

**Where it's used / platforms:** Republic of Ireland. Northern Ireland shares many Hiberno-English features but falls under the UK politically. Channels as en-GB, plus local Facebook groups.

**Script & spelling:** Same as en-GB (-ise, -our; unverified against an Irish style guide). Keep the fada (accent) in Irish words and names: Taoiseach, Dáil, Garda/Gardaí [27], Seán.

**Punctuation & typography:** Same as en-GB. Single quotes are "more usual" in Ireland, as in the UK [2].

**Words that mark the region:**

| concept | en-IE | en-GB |
|---|---|---|
| fine / OK | grand [27][28] | fine |
| fun, news | craic [27] | banter / what's new |
| complain, scold | give out (to) [28] | tell off |
| that man | your man / yer man [27] | that guy |
| thing, gadget | yoke [27] | thingy |
| cupboard | press [27] | cupboard |
| groceries | messages [27] | shopping |
| excellent | deadly, savage (younger speakers) [27][28] | brilliant |
| well done | fair play [28] | well done |
| funny | gas [28] | hilarious |
| teasing | slagging [28] | taking the mick |
| just did X | I'm after eating [27] | I've just eaten |

**Particles, interjections & fillers:** "sure look", tag phrases like "so it is", plural "ye/yous" [27]. Keep "ye" out of brand posts unless the user writes it.

**Mixing languages:** A few Irish words are common: sláinte, céad míle fáilte [27], bualadh bos (a round of applause) [31]. Write them correctly, with fadas.

**Tone & humour on social:** Slagging (affectionate teasing), sarcasm, irony, self-deprecation and understatement. "Not too bad" can mean things are going well [28]. Open boasting invites a slagging, so frame wins with luck, a team or a wry aside.

**Formats:** 16/09/2026, "16 September 2026" [9]. 24-hour preferred in CLDR [8]. Week starts on Monday [7]. Euro (€), written before the amount (general practice).

**Names of people & works:** Same as en-GB. Keep the fadas in people's names.

**Sensitivities:**
- Avoid "British Isles". The Irish government has avoided it since at least 1969 and uses "Ireland and Britain" or "these islands" [29].
- Never describe Irish people or places as British.
- Derry/Londonderry divides nationalists and unionists [30].
- "Fanny" is vulgar [16].
- Write "craic", not "crack".

**Search aliases:** Irish, Irish English, Hiberno-English, Ireland, Republic of Ireland, ROI, Éire, Dublin, Cork, Irish slang (Northern Irish → en-GB; Irish language `ga` is NOT this entry)

**Prompt guide (≤120 words):** Write in Irish English. Spelling and punctuation are British (-ise, -our, no full stop after Mr). Use €, "16 September" and Monday-first weeks. Keep the fadas on Irish words and names (Taoiseach, Seán). Sound warm and conversational, with understatement and a light self-deprecating touch. Frame achievements modestly, because boasting invites slagging. At most one or two natural markers: "grand", "the craic", "fair play", "delighted". Don't pile up stage-Irish clichés ("top o' the morning", "to be sure"). Never write "British Isles" or call Ireland British.

**Confidence:**
- Spelling: Medium
- Punctuation: Medium
- Words: High
- Particles: Medium
- Mixing: Medium
- Tone: Medium (non-academic source)
- Formats: High
- Sensitivities: High

**Native check:**
- Is "delighted" (as in "delighted to share") the natural Irish announcement word?
- Does "mam" rather than "mum" dominate social posts?
- Do Irish readers find "St Patty's Day" and "Gaelic" (for the Irish language) grating? Unverified.
- Metric vs stones and pints in casual posts.

**Sources:** [2] [7] [8] [9] [16] [27] [28] [29] [30] [31]

---

### English (Australia) · Australian English — `en-AU` (delta against `en-GB`)

**Where it's used / platforms:** Australia. Channels as en-GB, with Instagram and Facebook very strong.

**Script & spelling:** Follow the first spelling Macquarie Dictionary lists (the headword), as the Australian Government Style Manual advises [35]. In practice that means -ise, -our, -re and travelled. "Program" may be the Australian norm (see Native check).

**Punctuation & typography:**
- Single quotation marks, with double only for a quote inside a quote [32].
- Spaced en dashes. The Style Manual's example list "Walter, Yana and Aya" has no serial comma [33].
- "10 am", lower case with a space [34].

**Words that mark the region:**

| concept | en-AU | en-GB / en-NZ |
|---|---|---|
| afternoon | arvo [37][39] | afternoon |
| breakfast | brekkie [37] | breakfast |
| lots | heaps [39] | loads; heaps (NZ) |
| flip-flops | thongs [39] | flip-flops; jandals (NZ) |
| cooler | esky [39] | cool box; chilly bin (NZ) |
| petrol station / bottle shop | servo / bottle-o [39] | petrol station / off-licence |
| duvet | doona [39] | duvet |
| sunglasses | sunnies [37] | sunglasses |
| football (code varies) | footy [39] | football |

**Particles, interjections & fillers:** "mate", "no worries", "how ya going", "reckon" and "keen" are everyday [39]. Words like "strewth", "crikey" and "sheila" are caricature, not current speech [39].

**Formality & address:** Very informal. First names everywhere. Shortened words (-ie, -o) signal solidarity and a relaxed register [37][38].

**Mixing languages:** Aboriginal-language place names. Use community languages only if the user does.

**Tone & humour on social:**
- Egalitarian and casual, with a wariness of "tall poppies": people who stand out or seem to rank themselves above others get cut down [38]. The Conversation notes the evidence that this is uniquely Australian is thin [38].
- Frame wins as shared or lucky and use a self-mocking line. Superlatives read as try-hard.

**Formats:**
- Dates: "Thursday 14 August 2025" with no commas [34]; short form 16/9/26 [9].
- Time: 12-hour [8], "10 am" [34].
- Week starts on Monday [7].
- Money: $ (A$ only when readers might confuse it with other dollars).
- Units: metric.

**Sensitivities:**
- "Root" means sex, and "rooted" means exhausted or broken [40]. Avoid "rooting for".
- "Fanny" is vulgar [16].
- Capitalise Indigenous, First Nations and Aboriginal and Torres Strait Islander peoples. Use a specific group's name when known [36].

**Search aliases:** Australian, Australian English, Aussie, Aussie English, Australia, AU, Oz, Strine, Sydney, Melbourne

**Prompt guide (≤120 words):** Write in Australian English. Use Macquarie-style spelling (-ise, -our, travelled), single quotation marks, spaced en dashes, "10 am" and "16 September". Use $ and metric. Keep it relaxed and friendly. Everyday shortenings are fine in moderation ("arvo", "brekkie", "heaps", "keen", "no worries"). Never use caricature words ("strewth", "crikey", "sheila"). Avoid anything that reads as big-noting yourself: share credit, understate and allow a self-deprecating line. Never use "root/rooting for" or "fanny". Capitalise First Nations, Indigenous, and Aboriginal and Torres Strait Islander.

**Confidence:**
- Spelling: Medium-High
- Punctuation: High (government style; social usage may differ)
- Words: High
- Particles: Medium
- Tone: Medium
- Formats: High
- Sensitivities: High

**Native check:**
- Is "program" or "programme" preferred in AU arts and events posts?
- Do everyday AU social posts use double quotes despite government style?
- Is "barrack for" still current among people under 40?
- When do small organisations include an Acknowledgement of Country in social posts?

**Sources:** [7] [8] [9] [16] [32] [33] [34] [35] [36] [37] [38] [39] [40]

---

### English (New Zealand) · New Zealand English — `en-NZ` (delta against `en-AU`)

**Where it's used / platforms:** Aotearoa New Zealand. Channels as en-AU.

**Script & spelling:**
- British-based: -ise, -our, -re, cancelled [41].
- Māori loanwords take macrons (tohutō). Macrons have become standard since about 2015 [42], and Stuff adopted them in September 2017 [44]. Leaving them out now reads as careless.
- Don't add an English "s" to Māori plurals or possessives [43].
- Some iwi (e.g. Waikato-Tainui) write long vowels as double vowels instead [43].

**Punctuation & typography:** Both single and double quotes are in use [2]. Otherwise as en-GB.

**Words that mark the region:**

| concept | en-NZ | en-AU |
|---|---|---|
| flip-flops | jandals [41] | thongs |
| swimwear | togs [41] | swimmers |
| cooler | chilly bin [41] | esky |
| corner shop | dairy [41] | milk bar / servo |
| holiday home | bach (north) / crib (south) [41] | shack |
| hiking | tramping [41] | bushwalking |
| hello / thanks | kia ora [42] | g'day / cheers |
| extended family | whānau [42] | family |
| food / work | kai / mahi [42] | food / work |
| good / be strong | ka pai / kia kaha [42] | good on ya / stay strong |

Other common loanwords: aroha, hui, koha, mana, taonga, tamariki, puku, Pākehā, Aotearoa [42].

**Particles, interjections & fillers:** "sweet as", "chur" (thanks), "yeah nah" [46]. The "eh" tag is used more in New Zealand than in Canada [41].

**Mixing languages:** Mixing te reo Māori into English is normal and widely understood: greetings, sign-offs, whānau, mahi.

**Tone & humour on social:** Low-key and modest. Tall-poppy wariness applies as in Australia [38].

**Formats:** 16/09/2026 [9]. 12-hour [8]. Week starts on Monday [7]. $ (NZ$ when ambiguous). Metric.

**Sensitivities:**
- Te reo naming is politically live. The coalition government has pushed agencies to put English names first (e.g. "NZ Transport Agency Waka Kotahi") [45].
- Follow the user's own usage of "Aotearoa" and of Māori words, and don't use Māori concepts as decoration.
- Getting macrons wrong reads as disrespect [44].
- Don't call New Zealanders Australian.

**Search aliases:** New Zealand, NZ, Kiwi, Kiwi English, New Zealand English, Aotearoa, Aotearoa New Zealand, Auckland, Wellington

**Prompt guide (≤120 words):** Write in New Zealand English. Spelling is British-based (-ise, -our). Use "16 September", $ and metric. Keep the tone understated, friendly and modest, with no hype. Te reo Māori words are welcome where natural ("kia ora", "whānau", "mahi", "ka pai"). Always use correct macrons and never add an English "s" to Māori plurals. Use NZ words, not Australian ones: jandals, togs, chilly bin, tramping. Light Kiwi touches ("sweet as") only if the voice is casual. Follow the user's lead on "Aotearoa" and don't use Māori concepts decoratively.

**Confidence:**
- Spelling & macrons: High
- Words: High
- Particles: Medium (travel-blog source)
- Mixing: Medium-High
- Tone: Medium
- Formats: High
- Sensitivities: Medium-High

**Native check:**
- Should te reo words be italicised or glossed on first use? (The NZ guidance wasn't readable here.)
- Does a non-Māori small business using "kia ora" or "whānau" read as warm or as box-ticking in 2026?
- Is "chur" still current or dated?

**Sources:** [2] [7] [8] [9] [38] [41] [42] [43] [44] [45] [46]

---

### English (Canada) · Canadian English — `en-CA` (delta against `en-US`)

**Where it's used / platforms:** English-speaking Canada. It sits beside French (fr-CA), especially in Quebec. Channels as en-US.

**Script & spelling (the key difference from US):**
- British-style -our and -re: colour, labour, centre, sombre [47][48].
- US-style -ize: organize [47][49].
- Doubled l: travelled, cancelled [49][50].
- program (not programme), cheque, judgment [48]; defence [50].
- Noun/verb pairs: licence/license, practice/practise [49].
- US-style tire and curb [49].
- The Canadian Oxford Dictionary is the reference [47].

**Punctuation & typography:**
- Double quotes placed US-style, and Mr. with a period [49].
- Canadian Press style leaves out the serial comma [48].
- Dates and times: see Formats.

**Words that mark the region:**

| concept | en-CA | en-US |
|---|---|---|
| knit winter hat | toque / tuque [51] | beanie |
| public toilet | washroom [50] | restroom |
| $1 coin | loonie [51] | dollar coin |
| coffee, 2 cream 2 sugar | double-double [51] | — |
| 24-pack of beer | two-four [51] | case |
| eager student | keener [51] | overachiever |
| parking garage | parkade [51] | parking garage |
| electricity (bill) | hydro [50] | power / electric |
| coloured pencil | pencil crayon [50] | colored pencil |

**Particles, interjections & fillers:** "eh" as a tag asking for agreement [50]. It's a known stereotype, so use at most once.

**Mixing languages:** French is everywhere in public life (bilingual names, Quebec). Use it only as the user does.

**Tone & humour on social:** Close to US but more modest. Visible self-promotion costs more socially in Commonwealth markets than in the US [12] (Low-Medium).

**Formats:**
- Numeric dates are mixed, so avoid 01/02/03. The Government of Canada recommends YYYY-MM-DD for all-numeric dates [54]. CLDR also uses 2026-09-16 as the short form and "September 16, 2026" as the long form [9].
- Time: 12-hour with "a.m./p.m." [9].
- Week starts on Sunday [7].
- Money: $ (C$ when ambiguous).
- Units: metric officially, but most people give height and weight in feet and pounds, and many set ovens in °F. Weather is in °C, and km/h and litres are standard [52].

**Sensitivities:**
- Capitalise Indigenous Peoples, First Nations, Inuit and Métis. "Inuit people" is redundant, and "Aboriginal" is dated outside legal use [53].
- Don't treat Canada as part of "America" or use US holidays and dates (Canadian Thanksgiving is in October; general knowledge).

**Search aliases:** Canadian, Canadian English, Canada, CA, CanE, Toronto, Vancouver, Canuck, North American English (non-US)

**Prompt guide (≤120 words):** Write in Canadian English. Use colour/centre/cheque/defence but organize/realize (-ize), travelled with double l, and "program". Use double quotes placed US-style and Mr. with a period. Write dates as "September 16, 2026" or 2026-09-16 and never an ambiguous 09/10/26. Use "7 p.m.", $ and metric (°C, km), though personal height and weight may be imperial. The tone is friendly, polite and a notch less self-promotional than US copy. Use Canadian words only where natural (washroom, toque, loonie). "Eh" at most once, or not at all. Capitalise Indigenous Peoples, First Nations, Inuit and Métis.

**Confidence:**
- Spelling: High
- Punctuation: Medium
- Words: High
- Particles: Medium
- Tone: Low-Medium
- Formats: High
- Sensitivities: High

**Native check:**
- Do casual Canadian posts actually hold to -our, or drift to US spelling on phones with US keyboards?
- Is "a.m./p.m." or "am/pm" more common in social posts?
- Does "eh" in brand copy read as self-parody?

**Sources:** [7] [9] [12] [47] [48] [49] [50] [51] [52] [53] [54]

---

### English (India) · Indian English — `en-IN` (delta against `en-GB`)

**Where it's used / platforms:** India and the Indian diaspora. English is a professional and pan-regional link language. LinkedIn, Instagram, X, YouTube and WhatsApp are strong. Hinglish (Hindi-English mixing) is a *separate* register and not this entry.

**Script & spelling:** British: colour, realise, travelling [55]. US spellings creep into tech and corporate writing (see Native check).

**Punctuation & typography:** Not verified from an Indian style guide. Assume en-GB with some US influence (Low).

**Words that mark the region:**

| concept | en-IN | en-GB |
|---|---|---|
| move earlier | prepone [55][56] | bring forward |
| reply / get back to | revert [55] | get back to |
| graduate | pass out [55] | graduate |
| away from home town | out of station [55] | away |
| handle what's required | do the needful [55][56] | take care of it |
| squeeze in / make room | kindly adjust [57] | budge up |
| 100,000 / 10 million | lakh / crore [55][58] | hundred thousand / ten million |
| cramming for exams | mugging [56] | cramming |
| person who eats meat | non-veg [57] | meat-eater |

**How these are perceived:**
- "Prepone", "lakh" and "crore" are accepted Indian English. The OED records "do the needful" as current in India [56].
- Outside India, "do the needful" is obsolete and "revert" (meaning reply) confuses people [66]. Both can read as bureaucratic or get mocked in global audiences.
- Keep them for India-facing posts in the user's own voice.

**Particles, interjections & fillers:** "na" ("isn't it?"), "yaar" (mate), and the respectful suffix "-ji" [55]. These are casual or code-mixed, so use them only if the user does.

**Formality & address:** "Sir/Madam" and "aunty/uncle" for elders [55][57]. Professional posts lean polite and appreciative.

**Mixing languages:** Hinglish is common among urban young people and online [55]. Default to English unless the brief is code-mixed.

**Tone & humour on social:** Warm, celebratory and gratitude-forward. Credit to mentors, family and teams is common (Low: no corpus source).

**Formats:**
- Dates: DD/MM/YYYY or DD-MM-YYYY. The long form "21 October 2022" is common, but some papers write "October 21, 2022" [59].
- Time: 12-hour [8][59].
- Week starts on Sunday [7][59].
- Money: ₹ before the amount, grouped as ₹12,34,567.00 (3 digits, then 2s) [10][58]. Large sums in lakh/crore ("₹2.5 crore") [55]. "Rs" is also common (unverified).
- Units: metric.

**Sensitivities:**
- Avoid skin-tone descriptors like the matrimonial-ad cliché "wheatish" [56].
- Handle religion, caste and region with care.
- Don't invent Hinglish or regional slang.
- Don't "correct" legitimate Indian usages like "prepone" when the audience is Indian.

**Search aliases:** Indian, Indian English, India, IndE, Desi English, Bharat, Delhi, Mumbai, Bangalore (Hinglish is NOT this entry)

**Prompt guide (≤120 words):** Write in Indian English for an Indian audience. Use British spelling (colour, realise), "16 September 2026", 12-hour times and ₹ with Indian digit grouping (₹12,50,000), using lakh/crore for large sums. The tone is warm, respectful and appreciative, and thanking mentors, teams and family is natural. Plain, polite English beats slang. Indian usages like "prepone" are fine, but avoid dated officialese ("do the needful", "kindly revert") unless the user writes that way. Don't add Hindi words or Hinglish unless the user's own voice does. Never use skin-tone descriptors.

**Confidence:**
- Spelling: High
- Punctuation: Low
- Words: High
- Perception: Medium
- Particles: Medium
- Formality: Medium
- Tone: Low
- Formats: High
- Sensitivities: Medium

**Native check:**
- Quote style and Mr/Mr. in Indian social posts.
- Are "₹" or "Rs" more common in casual posts?
- How do urban professionals under 35 perceive "do the needful" and "revert"?
- LinkedIn norms: is "Humbled and honoured to share" standard or mocked?

**Sources:** [7] [8] [10] [55] [56] [57] [58] [59] [66]

---

### English (Singapore) · Singapore English — `en-SG` (delta against `en-GB`)

**Where it's used / platforms:** Singapore. Instagram, TikTok, Facebook, LinkedIn and Telegram.
- Two registers: Standard Singapore English (formal) and Singlish (colloquial). Scholars since 1990 mostly describe these as two distinct varieties that speakers switch between deliberately [60].
- Government stance: the Speak Good English Movement (since 2000) promotes standard English [60][62]. By 2015–16 it was distinguishing Singlish from standard English rather than trying to eliminate it, and agencies have used Singlish online [60].

**Script & spelling:** British: colour, realise [61].

**Punctuation & typography:** Assume en-GB (not verified).

**Words that mark the region:**

| concept | en-SG | en-GB |
|---|---|---|
| reserve a seat/table | chope [61] | save |
| ground floor of public housing | void deck [61] | — |
| residential suburbs | heartlands [61] | suburbs |
| aubergine | brinjal [61] | aubergine |
| delicious, satisfying | shiok [60] | lovely |
| afraid of missing out | kiasu [60] | — |
| oh no! | alamak [60] | oh no |
| too deep / abstruse | cheem [60] | heavy |

**Particles, interjections & fillers (Singlish):** These come at the end of a sentence and change tone, not content:

| particle | what it does |
|---|---|
| lah | reassures or softens a command, or emphasises [63] |
| leh | more tentative [63] |
| lor | resigned "that's how it is" [63] |
| meh | sceptical question [63] |
| hor | seeks agreement or warns [63] |
| sia | emphasis or amazement [63] |

- Pitch changes the meaning ("lah" has several tones) [63]. Swapping "meh" for "mah" turns doubt into assertion [64].
- Sources disagree on origins (Malay/Hokkien vs Cantonese) [63][64].

**Formality & address:** Brands and institutions write Standard Singapore English. Singlish shows up in casual, humorous or community content [60].

**Mixing languages:** Singlish draws loanwords from Malay, Mandarin and Hokkien [61]. Use it only when the user's voice does.

**Tone & humour on social:** Efficient and pragmatic in standard posts. In-group humour often runs on Singlish and self-mockery about being "kiasu" (Low).

**Formats:** 16/9/26; "16 September 2026" [9]. 12-hour ("7:30 pm") [8][9]. Week starts on Sunday [7]. Money: $ or S$ (S$ when readers might confuse it with other dollars). Metric.

**Sensitivities:**
- Singlish written by outsiders or brands easily reads as try-hard or mocking.
- Models that produce realistic Singlish inherit its dated style, while "neutral" models sound inauthentic [65]. Match the user's own Singlish samples; don't generate a stereotype.
- Handle race and religion with particular care (general caution).

**Search aliases:** Singapore, Singaporean, Singapore English, SgE, Standard Singapore English, Singlish, SG, Manglish (Malaysia is NOT this entry)

**Prompt guide (≤120 words):** Write in Standard Singapore English: British spelling (colour, realise), "16 September", 12-hour time and $/S$. Keep it clear, efficient and friendly. Only use Singlish if the user's own writing does, and then mirror their particles and frequency exactly. Typically that's one or two sentence-final particles like "lah" (reassuring) or "sia" (emphasis), never stacked or used in every sentence. Local terms (chope, void deck, hawker) are fine where natural. Never write exaggerated, stereotyped Singlish or mock the variety.

**Confidence:**
- Where/registers: High
- Spelling: High
- Punctuation: Low
- Words: High
- Particles: Medium (origins disputed)
- Formality: Medium
- Tone: Low
- Formats: High
- Sensitivities: Medium

**Native check:**
- Spelling of particles online ("lah" vs "la", "sia" vs "sial") and whether they're set off with a comma.
- Is "S$" or "$" more common in local business posts?
- Does Singlish in a small business's Instagram caption read as friendly or unprofessional?
- Are "hawker" or "makan" safe neutral words?

**Sources:** [7] [8] [9] [60] [61] [62] [63] [64] [65]

---

### Open questions

1. **Guardian style guide was blocked.** It couldn't be fetched, so the en-GB rules on quote style, dashes and the serial comma rest on Wikipedia, GOV.UK and a 2000s BBC styleguide. A UK editor should confirm them.
2. **Microsoft English Style Guide wasn't opened.** Its localisation guides (en-GB and others) weren't retrieved. It is worth pulling for UI-adjacent conventions.
3. **No corpus on platform habits.** There's no evidence here on emoji density, hashtag counts or call-to-action norms by region; every "Platform habits" line is Low confidence. The fix is a small labelled sample of native posts per locale.
4. **Time format.** CLDR prefers 24-hour for GB and IE, but social copy uses "7pm". Should PostRiff format times by CLDR or by social convention?
5. **Scots and Singlish as registers.** Should `en-GB-scotland` have a "Scots flavour" level, and should `en-SG` have a Singlish register toggle, rather than leaving it to inference from the voice profile? The data says local forms are rare in wide-audience posts [22].
6. **Scottish frequency data is old.** The only numbers are from 2013–14 Twitter and may not reflect TikTok-era writing.
7. **Northern Ireland.** Should it get a locale or variant of its own? It is en-GB politically but shares Hiberno-English vocabulary.
8. **Composer spellings.** The Rachmaninov/Rachmaninoff split looks institutional (European labels and catalogues vs the composer's own spelling) rather than strictly by country. A check of house styles at major concert venues in each country is needed before hard-coding.
9. **en-IN and en-SG typography.** Quote style, "Mr" vs "Mr." and "Rs" vs "₹" are unverified.
10. **Politically live naming.** How should PostRiff default: "Aotearoa New Zealand" vs "New Zealand", Acknowledgement of Country in AU posts, Derry/Londonderry? The likely answer is to mirror the user and never inject.

### Sources

1. Wikipedia, "Oxford spelling" — https://en.wikipedia.org/wiki/Oxford_spelling
2. Wikipedia, "Quotation marks in English" — https://en.wikipedia.org/wiki/Quotation_marks_in_English
3. GOV.UK, "A to Z style guide" — https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/style-guides/a-to-z-style-guide/
4. John Allen, *The BBC News Styleguide* (BBC Training & Development, PDF copy) — https://www.peteburns.com/downloads/BBC%20news%20styleguide.pdf
5. Wikipedia, "Full stop" (abbreviations: truncations vs contractions) — https://en.wikipedia.org/wiki/Full_stop
6. Wikipedia, "Date and time notation in the United Kingdom" — https://en.wikipedia.org/wiki/Date_and_time_notation_in_the_United_Kingdom
7. Unicode CLDR JSON, supplemental `weekData.json` — https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-core/supplemental/weekData.json
8. Unicode CLDR JSON, supplemental `timeData.json` — https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-core/supplemental/timeData.json
9. Unicode CLDR JSON, `ca-gregorian.json` for en, en-GB, en-IE, en-AU, en-NZ, en-CA, en-IN, en-SG — https://github.com/unicode-org/cldr-json/tree/main/cldr-json/cldr-dates-full/main (e.g. https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-dates-full/main/en-GB/ca-gregorian.json)
10. Unicode CLDR JSON, en-IN `numbers.json` — https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-numbers-full/main/en-IN/numbers.json
11. Kate Fox, *Watching the English* — summaries seen in search results (Goodreads and others) — https://www.goodreads.com/book/show/288448.Watching_the_English
12. Blueberry Media, "Personal branding UK vs US: how LinkedIn strategy differs (2026)" — https://blueberry-media.co.uk/blog/linkedin-personal-branding-uk-vs-us
13. AP Stylebook on X, punctuation with quotation marks (seen in search results) — https://x.com/APStylebook/status/1125428925285507079
14. University of Houston Honors College, "Basic AP Style Rules" (PDF) — https://www.uh.edu/honors/about/news-events/communications/basic-ap-style-rules-.pdf
15. Erin Brenner, "AP Style and the Serial Comma", Right Touch Editing — https://www.righttouchediting.com/2024/10/03/ap-style-and-the-serial-comma/
16. Wikipedia, "Fanny" — https://en.wikipedia.org/wiki/Fanny
17. An American's Guide to British Life, "Accidentally Scandalous: Words That Will Make You Blush in Britain" (seen in search results) — https://anamericansguidetobritishlife.substack.com/p/accidentally-scandalous-words-that
18. Slippedisc, "Rachmani-non? Rachmanin-off!" (2021) — https://slippedisc.com/2021/04/rachmani-non-rachmanin-off/
19. Tunitemusic, "Which one is it, Rachmaninoff or Rachmaninov?" — https://tunitemusic.com/post/which-one-is-it-rachmaninoff-or-rachmaninov/
20. IANA Language Subtag Registry (entries `scotland`, `sco`) — https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry
21. Wikipedia, "Scottish English" — https://en.wikipedia.org/wiki/Scottish_English
22. Shoemark, Sur, Shrimpton, Murray & Goldwater (2017), "Aye or naw, whit dae ye hink? Scottish independence and linguistic identity on social media", EACL — https://aclanthology.org/E17-1116.pdf
23. Hamish Pottinger (2021), "Language Standards in an Unstandardised Language: The Orthographies and Ideologies of Scots Users on Twitter", *Journal of Languages, Texts, and Society* 5 — https://www.nottingham.ac.uk/research/groups/languagestextssociety/documents/lts-journal/issue-5/language-standards-in-an-unstandardised-language-the-orthographies-and-ideologies-of-scots-users-on-twitter.pdf
24. E Jamieson & Sadie Ryan (2019), "How Twitter is helping the Scots language thrive in the 21st century", The Conversation — https://theconversation.com/how-twitter-is-helping-the-scots-language-thrive-in-the-21st-century-121783
25. Scots Language Centre, "OUTWITH prep outside, beyond" (seen in search results) — https://www.scotslanguage.com/articles/view/id/1884
26. Diversity Style Guide, "Scotch, Scots, Scottish" (seen in search results) — https://www.diversitystyleguide.com/glossary/scotch-scots-scottish/
27. Wikipedia, "Hiberno-English" — https://en.wikipedia.org/wiki/Hiberno-English
28. Settle.ie, "Irish Slang Explained: 'Grand', 'Craic' & 50+ Words Decoded" — https://settle.ie/guides/irish-slang-expressions/
29. History Ireland, "'British Isles'… a constant irritant" (seen in search results) — https://historyireland.com/british-isles-a-constant-irritant/
30. Wikipedia, "Derry/Londonderry name dispute" — https://en.wikipedia.org/wiki/Derry/Londonderry_name_dispute
31. Justin McNamara, "What's the craic? The origins of 7 Hiberno-English expressions", RTÉ Brainstorm (2025) — https://www.rte.ie/brainstorm/2025/0204/1494590-whats-the-craic-origins-hiberno-english-expressions/
32. Australian Government Style Manual, "Quotation marks" (seen in search results) — https://www.stylemanual.gov.au/grammar-punctuation-and-conventions/punctuation/quotation-marks
33. Australian Government Style Manual, "Dashes" (seen in search results) — https://www.stylemanual.gov.au/grammar-punctuation-and-conventions/punctuation/dashes
34. Australian Government Style Manual, "Dates and time" (seen in search results) — https://www.stylemanual.gov.au/grammar-punctuation-and-conventions/numbers-and-measurements/dates-and-time
35. Australian Government Style Manual, "Always use an Australian dictionary" (seen in search results) — https://www.stylemanual.gov.au/style-manual-resources/government-writing-handbook/editors-tips/always-use-australian-dictionary
36. Australian Government Style Manual, "Aboriginal and Torres Strait Islander peoples" (seen in search results) — https://www.stylemanual.gov.au/accessible-and-inclusive-content/inclusive-language/aboriginal-and-torres-strait-islander-peoples
37. The Conversation, "Brekkies, barbies, mozzies: why do Aussies shorten so many words?" — https://theconversation.com/brekkies-barbies-mozzies-why-do-aussies-shorten-so-many-words-192616
38. The Conversation, "Australia and New Zealand are plagued by 'tall poppy syndrome'. But would a cure be worse than the disease?" — https://theconversation.com/australia-and-new-zealand-are-plagued-by-tall-poppy-syndrome-but-would-a-cure-be-worse-than-the-disease-245355
39. Wikipedia, "Australian English vocabulary" — https://en.wikipedia.org/wiki/Australian_English_vocabulary
40. ABC News, "From rooting to #BonkBan: A history of Australian slang terms for sex" (2018) — https://www.abc.net.au/news/2018-03-01/from-rooting-to-bonking-a-history-of-australian-sex-terms/9492856
41. Wikipedia, "New Zealand English" — https://en.wikipedia.org/wiki/New_Zealand_English
42. Wikipedia, "List of English words of Māori origin" — https://en.wikipedia.org/wiki/List_of_English_words_of_M%C4%81ori_origin
43. NZ Digital government, "Te reo Māori" content design guidance (seen in search results) — https://www.digital.govt.nz/standards-and-guidance/design-and-ux/content-design-guidance/inclusive-language/te-reo-maori
44. Stuff, "Why Stuff is introducing macrons for te reo Māori words" and "Use of tohutō (macrons) a sign of respect" (seen in search results) — https://www.stuff.co.nz/national/96578644/why-stuff-is-introducing-macrons-for-te-reo-maori-words ; https://www.stuff.co.nz/national/maori-language-week/106500621/use-of-tohut-macrons-a-sign-of-respect
45. RNZ, "Government updates official branding to highlight English over te reo Māori"; Te Ao Māori News, "How the government's push for English-first names is tracking" (seen in search results) — https://www.rnz.co.nz/news/political/595776/government-updates-official-branding-to-highlight-english-over-te-reo-maori ; https://www.teaonews.co.nz/2024/04/08/how-the-governments-push-for-english-first-names-is-tracking/
46. Bren on the Road, "The Ultimate Guide To New Zealand Slang" and related slang guides (seen in search results) — https://brenontheroad.com/travellers-guide-new-zealand-slang/
47. Language Portal of Canada, Writing Tips Plus: "spelling: international variations", "sombre, somber" (seen in search results) — https://nos-langues.canada.ca/en/writing-tips-plus/spelling-international-variations
48. The Canadian Press Stylebook cheat sheet (New Canadian Media) and CP style excerpts (seen in search results) — https://www.newcanadianmedia.ca/wp-content/uploads/2021/05/The-Canadian-Press-Stylebook_-Cheat-sheet-for-NCM-writers-1.pdf
49. Knowadays, "A Quick Guide to Canadian English" — https://knowadays.com/blog/proofreading-tips-a-quick-guide-to-canadian-english/
50. Wikipedia, "Canadian English" — https://en.wikipedia.org/wiki/Canadian_English
51. Dictionary.com, "Canadian Slang: A Guide To Bunny Hugs, Loonies, And More" — https://www.dictionary.com/e/canadian-slang/
52. Research Co. (2022), "Few Canadians Want to Go Back to Imperial Measurement System" (seen in search results) — https://researchco.ca/2022/08/15/how-canadians-measure/
53. Language Portal of Canada, "capitalization: Indigenous person, Indigenous people, Indigenous People, Indigenous Peoples" (seen in search results) — https://our-languages.canada.ca/en/writing-tips-plus/capitalization-indigenous-person-people
54. Language Portal of Canada, "FAQs on Writing the Date"; Government of Canada, "Data Reference Standard on Date and Time Format" (seen in search results) — https://our-languages.canada.ca/en/favourite-articles/faqs-on-writing-the-date ; https://www.canada.ca/en/government/system/digital-government/digital-government-innovations/enabling-interoperability/gc-enterprise-data-reference-standards/data-reference-standard-date-time-format.html
55. Wikipedia, "Indian English" — https://en.wikipedia.org/wiki/Indian_English
56. Shashi Tharoor, "Please do the needful", The Week (2018) — https://www.theweek.in/columns/shashi-tharoor/2018/07/21/please-do-the-needful.html
57. Shashi Tharoor, "'Kindly adjust' to our English", The Week (2018) — https://www.theweek.in/columns/shashi-tharoor/2018/05/25/kindly-adjust-to-our-english.html
58. Wikipedia, "Indian numbering system" (seen in search results) — https://en.wikipedia.org/wiki/Indian_numbering_system
59. Wikipedia, "Date and time notation in India" — https://en.wikipedia.org/wiki/Date_and_time_notation_in_India
60. Wikipedia, "Singlish" — https://en.wikipedia.org/wiki/Singlish
61. Wikipedia, "Singapore English" — https://en.wikipedia.org/wiki/Singapore_English
62. Speak Good English Movement, Language Councils Singapore — https://www.languagecouncils.sg/goodenglish/
63. Search results on Singlish particles: A. F. Gupta, "Epistemic modalities and the discourse particles of Singapore"; "Ethnicity and Tone Production on Singlish Particles", *Languages* 7(3):243 (2022) — https://people.bu.edu/bfraser/Pragmatically%20Oriented/Gupta%20-%20Epistemic%20Modalities.doc ; https://doi.org/10.3390/languages7030243
64. The Language Closet, "Adventures in Colloquial Singaporean English (Singlish) – More Particles" (2017) — https://thelanguagecloset.com/2017/05/31/adventures-in-colloquial-singaporean-english-singlish-more-particles/
65. "Stylistic Evolution and LLM Neutrality in Singlish Language", arXiv:2601.06580 — https://arxiv.org/abs/2601.06580
66. Languagehat, "Do the Needful" (seen in search results) — https://languagehat.com/do-the-needful/
67. Busuu Blog, "10 Scottish phrases (& how to use them)" (seen in search results) — https://blog.busuu.com/scottish-expressions/


---

## Spanish & Portuguese families

Research date: 2026-09-16. Source numbers are global across this file. "(search result)" means the claim was checked against the search-result text only, because the page itself blocked the fetcher (rae.es returns 403 / a Cloudflare challenge). Short phrases marked *illustrative* were written for this file and are not quotes.

### Family notes

**Spanish.** All eight Spanish tags share one written standard, kept by RAE and ASALE (the association of the Spanish-language academies). The regional differences a reader notices in a post fall in five places:
1. How "you" is said: tú, vos, usted, and whether the plural is vosotros or ustedes.
2. Which past tense is used for something that happened today.
3. Everyday words, and taboo words that are harmless in another country.
4. Laughter and filler words.
5. How numbers and money are written.

Spain is the only variety that uses *vosotros* in everyday speech. Across Latin America, *ustedes* is the plural at every level of familiarity [51][5]. Voseo, meaning *vos* with its own verb endings (vos tenés), is the prestige form in Argentina and Uruguay. In Chile and much of Central America it is regional or informal [30][31]. Microsoft's guide says "neutral" Spanish "does not refer to any specific dialect of the language" [6]. In practice it is a way of avoiding region-marked words, not a variety anyone actually speaks.

**Portuguese.** Portuguese has two written standards, Brazilian and European. The 1990 Orthographic Agreement (AO90) unified most spelling, but both spellings of many words remain valid (facto/fato, receção/recepção, António/Antônio, económico/econômico) [20]. The differences that matter most are grammatical:
- "You": você in Brazil, tu or no pronoun in Portugal [17][53].
- Actions in progress: the gerund in Brazil, *estar a* + infinitive in Portugal [16].
- Pronoun position: before the verb in Brazilian speech, after it in European Portuguese [18].

Angola, Mozambique, Cape Verde, Guinea-Bissau, São Tomé and Timor-Leste follow the European norm when they have no national standard of their own [59].

**Address forms (what to default to in a social post)**

| Tag | 1 reader, casual | 1 reader, formal | Several readers | Typical brand voice on social |
|---|---|---|---|---|
| es-ES | tú | usted | vosotros (casual) / ustedes (formal) | tú + vosotros [5] |
| es-MX | tú | usted | ustedes | tú for consumer products [4] |
| es-AR | vos (vos tenés) | usted | ustedes | vos, also used in advertising [30] |
| es-CO | tú **or** usted (usted is often affectionate) | usted | ustedes | mixed, so copy the author (Low) [34][35] |
| es-US | tú | usted | ustedes | tú [7] |
| es-419 | tú | usted | ustedes | tú for consumer products, usted for enterprise products [6] |
| pt-BR | você (tu in the South and parts of the North-east) | o senhor / a senhora | vocês | você [9][61] |
| pt-PT | tu, or a verb with no pronoun | o senhor / a senhora, or the person's name | vocês | no "você": use the verb alone or tu [8][17] |

**Four signature words**

| Tag | Signature words |
|---|---|
| es-ES | vale · móvil · ordenador · zumo |
| es-MX | celular · computadora · popote · chido |
| es-AR | vos + tenés · colectivo · campera · dale |
| es-CO | computador · pitillo · chévere/bacano · parce |
| es-US | rentar · celular · Spanglish tags · $9.99 |
| es-419 | celular · computadora · jugo · ustedes (no regional slang) |
| pt-BR | ônibus · celular · tela · legal |
| pt-PT | autocarro · telemóvel · ecrã · fixe |

**Laughter & fillers**

| Tag | Laughter | Fillers / particles |
|---|---|---|
| es-ES | jajaja, jaja, xD | pues, vale, tío/tía, o sea |
| es-MX | jajaja, jsjs | pues, güey, órale, este…, o sea |
| es-AR | jajaja, jaja, jsjs | che, dale, re-, boludo (see Sensitivities) |
| es-CO | jajaja, jsjs | pues, parce, listo, qué pena, de una |
| es-US | jajaja, lol, haha | pues, o sea, English tags (like, so) |
| es-419 | jajaja | none region-marked (avoid) |
| pt-BR | kkkk, haha(ha), rsrs (older users) | né, tipo, gente, beleza, mano |
| pt-PT | ahah, haha, lol (sources disagree, see pt-PT) | pá, tipo, pronto, fixe, bué |

**Currency & number format** (CLDR defaults [10]; practice notes in each entry)

| Tag | Decimal / thousands | Currency example | Time |
|---|---|---|---|
| es-ES | , / . (no separator at 4 digits) | 1500 € · 12.500,50 € | 24 h (20:30) |
| es-MX | . / , | $1,500.50 (MXN or MX$ if ambiguous) | 12 h, a.m./p.m. (CLDR) |
| es-AR | , / . | $ 1.500,50 · US$ 100 | CLDR says 12 h; in practice often 24 h (native check) |
| es-CO | , / . | $ 45.000 (COP) | 12 h, a. m./p. m. (CLDR) |
| es-US | . / , | $1,500.50 | 12 h |
| es-419 | CLDR: . / , (but AR, CO, UY use , / .) | name the currency | 12 h |
| pt-BR | , / . | R$ 1.500,50 | 24 h |
| pt-PT | , / space (no separator at 4 digits) | 1500 € · 12 500,50 € | 24 h |

**Confidence:** High for address forms and formats; Medium for the signature words; Low–Medium for laughter and fillers.

**Sources:** [4] [5] [6] [7] [8] [9] [10] [16] [17] [18] [20] [30] [31] [34] [35] [51] [53] [59] [61] (full titles and URLs under each entry below)

---

### Español de España · Spanish (Spain) — `es-ES`

**Where it's used / platforms:** Spain, including the Canary Islands, Ceuta and Melilla. Spain has 39.7 M social-media identities (82.9% of the population). YouTube reaches 82.9%, Instagram 51.8%, LinkedIn 45.9% (unusually high), TikTok 47.1% of adults, and X 21.7% [52]. Castilian Spanish is spoken alongside co-official Catalan/Valencian, Galician, Basque and Aranese in their own regions [49].

**Script & spelling:** Latin script with ñ, á é í ó ú and ü. Spain writes **vídeo** with an accent, while Latin America writes **video** [5][7]. The pan-Hispanic norms of RAE/ASALE apply everywhere. Month and weekday names are lowercase (general norm).

**Punctuation & typography:** Opening ¿ and ¡ are required in ordinary writing. The RAE accepts dropping them in short single-sentence messages such as social posts and chats [2]. In posts meant to read as carefully written, keep them. For printed text the RAE recommends angle quotes «» first, then “ ”, then ‘ ’ [3]. Microsoft's Spain guide uses curly “ ” in its own documentation [5], and both kinds appear online. The RAE recommends a space as the thousands separator and accepts either comma or point for decimals [11]. In everyday Spanish practice the point groups thousands and the comma marks decimals (12.500,50) [10].

**Words that mark the region:**

| concept | es-ES | sibling locales |
|---|---|---|
| car | coche [39] | carro (MX, CO) · auto (AR, UY) |
| computer | ordenador [39] | computadora (MX, AR) · computador (CO) |
| mobile phone | móvil [39] | celular (Latin America) · celu (AR, colloquial) |
| bus | autobús, bus; guagua in the Canaries [41] | camión (MX) · colectivo/bondi (AR) · bus/buseta (CO) |
| juice | zumo [39] | jugo (Latin America) |
| cool / awesome | guay, mola [39][45] | chido/padre (MX) · copado (AR) · chévere/bacano (CO) |
| kid | crío, chaval (general; native check) | chamaco/chavo (MX) · pibe (AR) · pelado (CO) [39] |
| apartment | piso [39] | departamento (MX, AR) · apartamento (CO) |
| money (colloquial) | pasta [44] | lana (MX) · guita/plata (AR) · plata (CO) [39] |
| to take / grab | coger (neutral here) | tomar/agarrar; coger is vulgar in MX/AR [4][7] |
| popcorn | palomitas [43] | palomitas (MX) · pochoclo (AR) · crispetas (CO) |
| straw | pajita [42] | popote (MX) · pajita/sorbete (AR) · pitillo (CO) |
| jacket | chaqueta, cazadora [44] | chamarra (MX) · campera (AR) · chaqueta (CO) |
| concert / piano lesson | concierto / clase de piano | same everywhere (AR also says recital for pop shows; native check) |
| OK / sure | vale [45] | órale/va (MX) · dale (AR) · listo/de una (CO) |

**Particles, interjections & fillers:** *vale* signals agreement, closes a topic, or fills a pause [45]. *Tío/tía* means dude [45]. Also *pues*, *o sea*, *venga* (let's go, or OK, bye) and *hombre* (for emphasis). Laughter is usually *jajaja*. The RAE form "ja, ja, ja" is for formal text [47].

**Formality & address:** Use *tú* for one reader and *vosotros/os/vuestro* for a group. Microsoft Spain uses tú and vosotros, not ustedes [5]. *Usted/ustedes* is for formal, institutional or older audiences. Western Andalusia and the Canaries use ustedes as the casual plural (general knowledge; native check). Spain prefers the **present perfect** for events inside the current time frame, as in *hoy he ensayado* (illustrative). Latin America mostly uses the simple past here. Buenos Aires uses the compound past about 13% of the time against 58% in Spain [31][46]. Gendered agreement: *estoy cansado/cansada*, *encantado/encantada*, *bienvenidos/bienvenidas*. Never guess the author's gender. Use a neutral rewrite such as *te damos la bienvenida* (illustrative).

**Mixing languages:** English marketing words appear in business and LinkedIn posts (*feedback*, *networking*). This is common but noticeable, so copy the author's habit (Low). Short Catalan, Galician or Basque greetings are natural only for authors from those regions (native check).

**Tone & humour on social:** The tone is direct, dry and ironic. There are fewer exclamation marks than in Mexican or Brazilian posts, and hype language reads as salesy. These are observed patterns without a strong source (Low).

**Platform habits:** LinkedIn reach is high [52], and first-person career posts are normal there. On Instagram, captions are short with a few emojis. WhatsApp is ubiquitous, but DataReportal gives no figure for it (Low).

**Formats:** Money is written 25 €, 1500 €, 12.500 € (symbol after, non-breaking space; no separator at four digits) [10]. Dates are 16/9/26 or *16 de septiembre de 2026*. Time is 24-hour, 20:30 [10].

**Names of people & works:** Russian names are transcribed Spanish-style, so *Chaikovski* is preferred to *Tchaikovsky* [12] and *Rajmáninov* follows the same rules. Concert programmes and streaming services often keep the English spelling, so copy the author (native check). Established titles are translated (*El lago de los cisnes*), and Latin-script names stay as they are (Schumann).

**Sensitivities:**
- The co-official languages are languages, not dialects [49]. Regional identity and independence politics are sensitive.
- The RAE advises against *americano* for people from the US and recommends *estadounidense* [48].
- The RAE rejects @, x and -e endings as "ajeno a la morfología del español, además de innecesario" [13]. Doubled forms (*todos y todas*) are common in political and institutional texts. -e forms (*todes*) are politically marked, so use them only if the author does.

**Search aliases:** Spanish, español, espanol, castellano, Castilian, Spain, España, Espana, Spanish (Spain), Peninsular Spanish, European Spanish, español peninsular, es-ES, Madrid, Barcelona

**Prompt guide (≤120 words):** Write peninsular Spanish (Spain). Address one reader as tú and a group as vosotros (os, vuestro), not ustedes. Use Spain vocabulary: móvil, ordenador, coche, zumo, piso, vale, guay. *Coger* is neutral here. For things that happened today or this week, use the present perfect (*hoy he tocado*). Open questions and exclamations with ¿ and ¡. Write prices as 25 € or 12.500 €, and times in 24-hour form (20:30). Keep exclamation marks, emojis and hype modest. Prefer dry, direct warmth. Say *estadounidense*, not *americano*, for the US. Don't assume the author's gender in agreement (cansado/cansada). Use inclusive -e forms only if the author already does.

**Confidence:** High for address, perfect tense, punctuation and formats. Medium for vocabulary. Low for tone and platform habits.

**Native check:** kid words (crío/chaval); the ustedes plural in western Andalusia and the Canaries; how often guay sounds dated; the tone and emoji norms; «» versus “ ” in social posts.

**Sources:**
- [2] @RAEinforma on X, opening ¿ in short messages (search result) — https://x.com/RAEinforma/status/1067385171563945984
- [3] RAE–ASALE, DPD «comillas» (search result) — https://www.rae.es/dpd/comillas
- [4] Microsoft, Spanish (Mexico) Localization Style Guide — https://download.microsoft.com/download/9/0/1/9016efc5-6455-4a9d-ae78-ed3df93b2851/spa-mex-StyleGuide.pdf
- [5] Microsoft, Spanish (Spain) Localization Style Guide — https://download.microsoft.com/download/9/a/1/9a19beca-597c-417b-a2c2-0f1ea5a1e6c3/spa-esp-StyleGuide.pdf
- [7] Microsoft, Spanish (US) Style Guide — https://download.microsoft.com/download/8/9/a/89ae1f7a-6c96-4f75-b51c-5590735ee810/spa-usa-StyleGuide.pdf
- [10] Unicode CLDR JSON (numbers, currencies, gregorian dates) — https://github.com/unicode-org/cldr-json
- [11] RAE, Ortografía: separador decimal; separador de millares (search results) — https://www.rae.es/ortograf%C3%ADa/los-n%C3%BAmeros-decimales-y-el-separador-decimal · https://www.rae.es/ortograf%C3%ADa/los-n%C3%BAmeros-enteros-y-el-separador-de-millares
- [12] FundéuRAE, «Chaikovski, preferible a Tchaikovsky» — https://fundeu.do/chaikovski-preferible-a-tchaikovsky/
- [13] RAE, Informe sobre el lenguaje inclusivo (2020) — https://www.rae.es/sites/default/files/Informe_lenguaje_inclusivo.pdf
- [31] Wikipedia (es), Español rioplatense — https://es.wikipedia.org/wiki/Espa%C3%B1ol_rioplatense
- [39] Wikcionario (es) entries: coche, carro, auto, ordenador, computadora, computador, celular, jugo, piso, pibe, chamaco, pelado, lana, guita, guay, chido, copado, chévere, bacano — https://es.wiktionary.org/wiki/
- [41] Wikipedia (es), Autobús — https://es.wikipedia.org/wiki/Autob%C3%BAs
- [42] Wikipedia (es), Pajita — https://es.wikipedia.org/wiki/Pajita
- [43] La Nación, «De canguil a cotufas…» (search result) — https://www.lanacion.com.ar/estados-unidos/de-canguil-a-cotufas-como-se-les-dice-a-las-palomitas-de-maiz-en-los-distintos-paises-latinos-nid29112025/
- [44] Linguno, chaqueta/campera/cazadora/chamarra; FluentU, money slang (search results) — https://www.linguno.com/wordComparison/esp/chaqueta-campera-cazadora-chamarra/ · https://www.fluentu.com/blog/spanish/money-in-spanish-slang/
- [45] La Página del Español, «10 palabras que escucharás en España»; Instituto Hispánico de Murcia, youth slang (search results) — https://paginadelespanol.com/10-palabras-que-escucharas-en-espana/ · https://ihdemu.com/en/dictionary-spanish-youth-slang/
- [46] Handy Spanish, pretérito perfecto vs indefinido (search result) — https://handyspanish.com/podcast/54-preterito-perfecto-vs-indefinido-diferencia-entre-colombia-espana-y-mexico/
- [47] RAE, «¿Es válido escribir la risa "jajaja"?» (search result) — https://www.rae.es/duda-linguistica/es-valido-escribir-la-risa-jajaja
- [48] @RAEinforma on X, «americano» / «estadounidense» (search result) — https://x.com/RAEinforma/status/1886697554152161660
- [49] Wikipedia (es), Lenguas de España — https://es.wikipedia.org/wiki/Lenguas_de_Espa%C3%B1a
- [52] DataReportal, Digital 2025: Spain — https://datareportal.com/reports/digital-2025-spain

---

### Español de México · Spanish (Mexico) — `es-MX`

**Where it's used / platforms:** Mexico is the largest Spanish-speaking country, and Mexican usage shapes much US and pan-regional content [37]. It has 93.0 M social-media identities (70.7%). Facebook reaches 70.7% of the population, TikTok 91.7% of adults, YouTube 63.6%, Messenger 43.3%, Instagram 37.1%, LinkedIn 19.8% and X 12.8% [52]. Facebook and TikTok matter more here than in Spain.

**Script & spelling:** Same alphabet as Spain. Write *video* without an accent [7]. Words from Nahuatl are everyday vocabulary (*papalote*, kite; *molcajete*, stone mortar) [37].

**Punctuation & typography:** ¿ and ¡ follow the same rule as Spain [2]. Microsoft's Mexico guide uses curly “ ” quotes, noting that the norm prefers «» [4]. Numbers use a **decimal point and comma thousands** (1,250.50) [10].

**Words that mark the region:**

| concept | es-MX | sibling locales |
|---|---|---|
| car | carro, coche (both used; native check) [39] | coche (ES) · auto (AR) · carro (CO) |
| computer | computadora [4][39] | ordenador (ES) · computador (CO) |
| mobile phone | celular [39] | móvil (ES) |
| bus | camión, pesero, micro [41] | autobús (ES) · colectivo (AR) · buseta (CO) |
| juice | jugo | zumo (ES) |
| cool / awesome | chido, padre [39] | guay (ES) · copado (AR) · chévere (CO) |
| kid | chamaco, chavo [39] | crío (ES) · pibe (AR) · pelado (CO) |
| apartment | departamento, depa | piso (ES) · apartamento (CO) |
| money (colloquial) | lana [39] | pasta (ES) · guita (AR) · plata (CO) |
| to take / grab | agarrar, tomar (**not** coger) [4] | coger is fine in ES |
| popcorn | palomitas [43] | pochoclo (AR) · crispetas (CO) |
| straw | popote (pitillo is vulgar here) [42] | pajita (ES) · pitillo (CO) |
| jacket | chamarra (chaqueta has a vulgar sense) [40][44] | chaqueta (ES, CO) · campera (AR) |
| OK / sure | órale, va, sale [38][39] | vale (ES) · dale (AR) · listo (CO) |

**Particles, interjections & fillers:** *órale* (agreement or encouragement), *ándale*, and *-le* on imperatives (*córrele*, hurry) [37]. *¿Qué tan…?* replaces Spain's *¿cómo de…?* [37]. *Güey* is colloquial and can address a trusted person or mean "fool" [38], so use it only in very casual voices. Other fillers: *pues*, *este…*, *o sea*, *ahorita*. Laughter: *jajaja*, and *jsjs* among younger users (Low) [47].

**Formality & address:** Use *tú* by default for consumer or creator content [4] and *ustedes* for groups, never vosotros [51]. *Usted* fits banks, government, older audiences and customer care (Medium). The simple past is preferred (*hoy fui al ensayo*) [37][46]. Gendered agreement: *cansado/cansada*, *invitados/invitadas*. Don't assume.

**Mixing languages:** English influence is strong in the north and in tech and marketing [37]. English brand terms are normal. Full Spanglish reads as US-Mexican, not Mexico-Mexican (Low).

**Tone & humour on social:** The tone is warmer and more effusive than in Spain. Diminutives are affectionate (*cafecito*, *ahorita*), and exclamation marks and emojis are more frequent. Wordplay with double meanings (albur) is a national humour genre, so check drafts for accidental double meanings. These are observed patterns (Low).

**Platform habits:** Posts should be written with Facebook and TikTok in mind first [52]. WhatsApp is the default for direct contact (Low, not measured). LinkedIn reach is smaller than in Spain [52].

**Formats:** $1,250 or $1,250.50. Add MXN or MX$ when readers could confuse the currency with dollars [10]. Dates are 16/09/26 or *16 de septiembre de 2026*. CLDR gives 12-hour time with a.m./p.m. (7:30 p.m.), though 24-hour time appears in schedules [10].

**Names of people & works:** The pan-Hispanic transcription rules apply (*Chaikovski*) [12]. In practice Mexican media and venues often keep the English or original spelling (native check). Titles are Spanish where established.

**Sensitivities:**
- Avoid *coger* (vulgar) [4][7], *chaqueta* in its vulgar sense [40], and *pitillo* [42].
- *Pinche* and *pendejo* are insults, not neutral words [39].
- Use *estadounidense* for people from the US [48]. Avoid "gringo" in brand voice.
- Inclusive language: doubled forms are common in institutional texts. The RAE rejects -e forms [13]. Adoption in Mexico is not documented here (Low).

**Search aliases:** Spanish (Mexico), Mexican Spanish, español de México, español mexicano, mexicano, Mexico, México, Mexico City, CDMX, Latin American Spanish, Latino, es-MX

**Prompt guide (≤120 words):** Write Mexican Spanish. Address readers as tú (usted only for a formal institutional voice); the plural is ustedes, never vosotros. Use Mexican vocabulary: celular, computadora, camión (bus), departamento, popote, chamarra, lana for money in casual voices. Never use *coger* for "take" (use agarrar or tomar), and avoid *chaqueta* and *pitillo*. Prefer the simple past (*hoy fui*). Warmth and diminutives are natural. Use chido, padre, órale or güey only when the author's voice is casual. Write money as $1,250.50, adding MXN if foreigners read it. Say *estadounidense* for the US. Don't assume the author's gender.

**Confidence:** High for address, taboo words, and number and currency formats. Medium for vocabulary. Low for tone, humour and platform habits.

**Native check:** carro versus coche frequency; jsjs; 12- versus 24-hour time on event posts; the tone of brands using usted; spelling of Russian names in Mexican concert programmes.

**Sources:**
- [2] @RAEinforma on X, opening ¿ in short messages (search result) — https://x.com/RAEinforma/status/1067385171563945984
- [4] Microsoft, Spanish (Mexico) Localization Style Guide — https://download.microsoft.com/download/9/0/1/9016efc5-6455-4a9d-ae78-ed3df93b2851/spa-mex-StyleGuide.pdf
- [7] Microsoft, Spanish (US) Style Guide — https://download.microsoft.com/download/8/9/a/89ae1f7a-6c96-4f75-b51c-5590735ee810/spa-usa-StyleGuide.pdf
- [10] Unicode CLDR JSON — https://github.com/unicode-org/cldr-json
- [12] FundéuRAE, «Chaikovski, preferible a Tchaikovsky» — https://fundeu.do/chaikovski-preferible-a-tchaikovsky/
- [13] RAE, Informe sobre el lenguaje inclusivo (2020) — https://www.rae.es/sites/default/files/Informe_lenguaje_inclusivo.pdf
- [37] Wikipedia (es), Español mexicano — https://es.wikipedia.org/wiki/Espa%C3%B1ol_mexicano
- [38] Academia Mexicana de la Lengua, Diccionario breve de mexicanismos, «güey» — https://academia.org.mx/consultas/obras-de-consulta-en-linea/diccionario-breve-de-mexicanismos-de-guido-gomez-de-silva/item/gueey
- [39] Wikcionario (es): carro, computadora, celular, chido, chamaco, lana, órale, pinche, pendejo, güey — https://es.wiktionary.org/wiki/
- [40] Wikcionario (es), chaqueta — https://es.wiktionary.org/wiki/chaqueta
- [41] Wikipedia (es), Autobús — https://es.wikipedia.org/wiki/Autob%C3%BAs
- [42] Wikipedia (es), Pajita — https://es.wikipedia.org/wiki/Pajita
- [43] La Nación, «De canguil a cotufas…» (search result) — https://www.lanacion.com.ar/estados-unidos/de-canguil-a-cotufas-como-se-les-dice-a-las-palomitas-de-maiz-en-los-distintos-paises-latinos-nid29112025/
- [44] Linguno, chaqueta/campera/cazadora/chamarra (search result) — https://www.linguno.com/wordComparison/esp/chaqueta-campera-cazadora-chamarra/
- [46] Handy Spanish, perfecto vs indefinido (search result) — https://handyspanish.com/podcast/54-preterito-perfecto-vs-indefinido-diferencia-entre-colombia-espana-y-mexico/
- [47] Revista Central, «La risa de Internet» (search result) — https://www.revistacentral.com.mx/tecnologia/risa-escrita-significados-whatsapp
- [48] @RAEinforma on X, «americano» (search result) — https://x.com/RAEinforma/status/1886697554152161660
- [51] Wikipedia (en), Spanish language in the Americas — https://en.wikipedia.org/wiki/Spanish_language_in_the_Americas
- [52] DataReportal, Digital 2025: Mexico — https://datareportal.com/reports/digital-2025-mexico

---

### Español rioplatense · Spanish (Argentina) — `es-AR` (delta)

**Where it's used / platforms:** Argentina (for Uruguay, see the note below). Argentina has 32.2 M social-media identities (70.3%). Facebook reaches 63.5% of the population, Instagram 63.1%, TikTok 71.8% of adults and LinkedIn 32.8% [52].

**Script & spelling:** Same as `es-MX`.

**Punctuation & typography:** Same as `es-MX`, except numbers use a **decimal comma and point thousands** (15.000,50) [10].

**Words that mark the region:** See the shared tables. Markers: *auto, compu, celu, colectivo/bondi, departamento, campera, pochoclo, pileta* (pool), *frutilla* (strawberry), *laburo* (work), *plata/guita* [31][39][41].

**Particles, interjections & fillers:** *che* (to get attention), *dale* (OK, go on), *re-* as an intensifier (*re lindo*) [31], *copado* (cool) [39]. *Boludo* works like "dude" between friends but is also an insult [39][66].

**Formality & address:** **Voseo is the prestige norm** and appears in formal writing and advertising [30][31]. Present tense: *vos tenés, sos, podés*. Imperative: *tocá, vení, mirá* (illustrative). The plural is ustedes. The RAE calls these verb endings "voseo verbal" [1]. Careful writing often keeps the tú-form subjunctive (*que vos tengas*) (native check). The simple past is strongly preferred: Buenos Aires uses the compound past about 13% of the time against 58% in Spain [31]. Brands address readers as vos.

**Mixing languages:** Italian influence and lunfardo slang are part of everyday vocabulary [31]. English appears in tech and marketing (Low).

**Tone & humour on social:** Ironic, fast and self-deprecating, with exaggeration through *re-* (Low).

**Platform habits:** Instagram is as strong as Facebook [52]. Otherwise same as `es-MX` (Low).

**Formats:** $ 15.000 or $ 1.250,50. Mark dollars as US$ [10]; *u$s* and *USD* are also seen (native check). CLDR gives 12-hour time, but written schedules often use 24-hour times or "21 h" (native check) [10].

**Names of people & works:** Same as `es-MX`.

**Sensitivities:**
- *Coger*, *concha*, *cajeta* and *pija* are vulgar [4][39].
- *Pendejo* means kid or teen: disparaging, but not the Mexican insult [39].
- Inclusive e/x/@ forms are politicised. Buenos Aires city limited them in schools in 2022 [14], and the national government banned them in official documents in 2024 [15]. Use them only if the author does.
- Say Malvinas, not Falklands (general knowledge).

**Uruguay note:** Montevideo often mixes *tú* with voseo verbs (*tú tenés*), and younger speakers are moving toward *vos* [32][33]. Vocabulary differs: *ómnibus* (bus), *ta* (OK), *bo* (hey), *gurí/botija* (kid), *championes* (sneakers) [32][41]. Numbers use a decimal comma [10].

**Search aliases:** Argentine Spanish, Spanish (Argentina), español argentino, castellano rioplatense, rioplatense, River Plate Spanish, porteño, Buenos Aires, voseo, vos, Uruguay, uruguayo, Uruguayan Spanish, es-AR, es-UY

**Prompt guide (≤120 words):** Write Rioplatense Spanish (Argentina). Use vos with voseo verbs (vos tenés, sos, podés; imperatives tocá, vení, mirá) and ustedes for groups. Prefer the simple past (*hoy toqué*). Use Argentine vocabulary: celu, compu, auto, colectivo, departamento, campera, pochoclo, plata. Use *dale* for OK and *re* as an intensifier, sparingly. Never use *coger*, *concha* or *cajeta*. Use *boludo* only if the author's own voice does, and never toward the reader. Write money as $ 15.000 (US$ for dollars) with decimal commas. For Uruguay, keep the voseo verbs but switch vocabulary (ómnibus, ta, gurí).

**Confidence:** High for voseo, past tense, taboo words and number formats. Medium for vocabulary. Low for tone.

**Native check:** subjunctive voseo in writing; 24-hour time in posts; US$ vs u$s vs USD; whether *recital* is still the common word for pop concerts.

**Sources:**
- [1] RAE–ASALE, DPD «voseo» (search result) — https://www.rae.es/dpd/voseo
- [4] Microsoft, Spanish (Mexico) Localization Style Guide (coger flagged for Latin America) — https://download.microsoft.com/download/9/0/1/9016efc5-6455-4a9d-ae78-ed3df93b2851/spa-mex-StyleGuide.pdf
- [10] Unicode CLDR JSON (es-AR, es-UY) — https://github.com/unicode-org/cldr-json
- [14] CNN en Español (2022), inclusive language in Buenos Aires schools — https://cnnespanol.cnn.com/2022/06/10/lenguaje-inclusivo-buenos-aires-argentina-escuelas-orix
- [15] CNN en Español (2024), ban in official documents — https://cnnespanol.cnn.com/2024/02/27/milei-prohibe-leguaje-inclusivo-documentos-oficiales-orix-arg
- [30] Wikipedia (es), Voseo — https://es.wikipedia.org/wiki/Voseo
- [31] Wikipedia (es), Español rioplatense — https://es.wikipedia.org/wiki/Espa%C3%B1ol_rioplatense
- [32] Wikipedia (es), Español uruguayo — https://es.wikipedia.org/wiki/Espa%C3%B1ol_uruguayo
- [33] Cáceres, «Las fronteras del voseo en el Río de la Plata: vos tenés, tú tenés…» (CVC; search result) — https://cvc.cervantes.es/ensenanza/biblioteca_ele/publicaciones_centros/PDF/saopaulo_2008/21_walter-caceres.pdf
- [39] Wikcionario (es): pibe, guita, copado, dale, boludo, concha, cajeta, pija, pendejo — https://es.wiktionary.org/wiki/
- [41] Wikipedia (es), Autobús — https://es.wikipedia.org/wiki/Autob%C3%BAs
- [52] DataReportal, Digital 2025: Argentina — https://datareportal.com/reports/digital-2025-argentina
- [66] El Universal, «Qué significa el término boludo en Argentina» (search result) — https://www.eluniversal.com.mx/destinos/que-significa-el-termino-boludo-en-argentina/

---

### Español de Colombia · Spanish (Colombia) — `es-CO` (delta)

**Where it's used / platforms:** Colombia has 36.8 M social-media identities (69.2%). Facebook reaches 69.2% of the population, TikTok 79.5% of adults, YouTube 57.6%, Instagram 38.4% and LinkedIn 30.1% [52].

**Script & spelling:** Same as `es-MX`.

**Punctuation & typography:** Same as `es-MX`, except CLDR gives a **decimal comma and point thousands** [10]. Point decimals also appear in practice (native check).

**Words that mark the region:** *computador* [39], *carro*, *celular*, *bus/buseta* [41], *apartamento*, *crispetas / maíz pira* [43], *pitillo* (straw) [42], *plata*, *tinto* (black coffee), *chévere/bacano* (cool) [34][39], *parce/parcero* (mate; Antioquia, the coffee region, Valle, Bogotá) [39].

**Particles, interjections & fillers:**
- *Qué pena* is an apology or softener, not "what a shame".
- *Regálame* is a polite "could I have".
- *De una* means right away, and *pilas* means watch out [36].
- *Listo* means OK (native check).
- Diminutives use *-ico* after t (*momentico*) [34].

**Formality & address:** This is the key difference. **Usted is used even between intimates** in much of the interior, which is called "ustedeo" [34]. In Bogotá, usted dominates with family, at work and with strangers, while tú is linked to women, young people and some upper-class speech [35]. *Vos* is used in the Paisa region and Valle, *tú* on the Caribbean coast, and *sumercé* in Boyacá and Cundinamarca [34][35]. For posts, copy the author. Tú suits young national consumer audiences, and a warm usted is not cold here. The simple past is preferred [46].

**Mixing languages:** Anglicisms appear in business. Medellín slang (parlache) spreads through music [39] (Low).

**Tone & humour on social:** Courteous, softened requests and affectionate diminutives (Low).

**Platform habits:** Facebook and TikTok come first [52]. Otherwise same as `es-MX` (Low).

**Formats:** $ 45.000; decimals are rarely shown for COP. Add COP for foreign readers [10]. CLDR gives 12-hour time with a. m./p. m. [10].

**Names of people & works:** Same as `es-MX`.

**Sensitivities:**
- *Coger* is neutral locally (*coger un bus*) but sexual elsewhere, so avoid it in posts that travel abroad [36].
- Avoid narco stereotypes (general).
- Inclusive-language adoption was not verified (Low).

**Search aliases:** Colombian Spanish, Spanish (Colombia), español colombiano, español de Colombia, colombiano, Colombia, Bogotá, rolo, paisa, costeño, ustedeo, es-CO

**Prompt guide (≤120 words):** Write Colombian Spanish. Match the author's address: tú for young or casual audiences, or usted, which is natural and warm here. Never use vosotros. Use Colombian vocabulary: computador, carro, celular, bus, apartamento, pitillo, crispetas, plata. Use chévere or bacano for "cool" and listo or de una for "OK". Courtesy softeners fit (qué pena, regálame), and diminutives use -ico after t (momentico). Use *parce* only in casual voices. Avoid *coger* in posts that foreigners read. Prefer the simple past. Write money as $ 45.000 without decimals, adding COP for foreign readers.

**Confidence:** High for ustedeo and regional address. Medium for vocabulary and fillers. Low for tone and number practice.

**Native check:** decimal-separator practice; *listo*; brand tú versus usted on Instagram and TikTok; whether Paisa voseo is common in written social posts.

**Sources:**
- [10] Unicode CLDR JSON (es-CO) — https://github.com/unicode-org/cldr-json
- [34] Wikipedia (es), Español colombiano — https://es.wikipedia.org/wiki/Espa%C3%B1ol_colombiano
- [35] «¿Tú o usted? Estigmatización del tuteo en Bogotá» (SciELO México; search result) and «Usted, tú, sumercé y vos… Bogotá» (search result) — https://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S2448-82242017000200035 · https://www.researchgate.net/publication/343725634_USTED_TU_SUMERCE_Y_VOS_FORMAS_PRONOMINALES_DE_TRATAMIENTO_EN_EL_ESPANOL_DE_BOGOTA_COLOMBIA
- [36] Gerente Colombiano (2026), colombianismos que confunden a equipos internacionales — https://gerentecolombiano.com.co/que-pena-regalame-o-chevere-los-colombianismos-que-pueden-generar-confusion-en-reuniones-con-equipos-internacionales/
- [39] Wikcionario (es): computador, chévere, bacano, parce, parcero, pelado — https://es.wiktionary.org/wiki/
- [41] Wikipedia (es), Autobús — https://es.wikipedia.org/wiki/Autob%C3%BAs
- [42] Wikipedia (es), Pajita — https://es.wikipedia.org/wiki/Pajita
- [43] La Nación, «De canguil a cotufas…» (search result) — https://www.lanacion.com.ar/estados-unidos/de-canguil-a-cotufas-como-se-les-dice-a-las-palomitas-de-maiz-en-los-distintos-paises-latinos-nid29112025/
- [46] Handy Spanish, perfecto vs indefinido (search result) — https://handyspanish.com/podcast/54-preterito-perfecto-vs-indefinido-diferencia-entre-colombia-espana-y-mexico/
- [52] DataReportal, Digital 2025: Colombia — https://datareportal.com/reports/digital-2025-colombia

---

### Español de Estados Unidos · Spanish (United States) — `es-US` (delta)

**Where it's used / platforms:** US Hispanic and Latino audiences of varied origin; the largest group is of Mexican origin. 75% of US Latinos can hold a conversation in Spanish, but only 34% of the third generation and beyond can [27]. Many readers are bilingual or English-dominant.

**Script & spelling:** Same as `es-MX` (*video*, no accent) [7].

**Punctuation & typography:** Same as `es-MX`, with a decimal point [10].

**Words that mark the region:** Broadly Latin American words (celular, computadora, carro, jugo) plus **estadounidismos** recognised by the academies (*rentar*, *van*, *email*) [50]. Microsoft's US guide flags *coger* as offensive and uses *la PC* [7].

**Particles, interjections & fillers:** Follow the author's heritage (pues, órale, dale, wepa), and don't mix regions in one post. *Lol* and *haha* sit alongside *jajaja* (Low).

**Formality & address:** Use *tú* by default [7] and *ustedes* for groups. Don't assume the reader's origin or level of Spanish: 54% of Latinos who don't speak Spanish have been made to feel bad about it by other Latinos [27]. Avoid "real Latinos speak Spanish" framing.

**Mixing languages:** 63% use **Spanglish** at least sometimes and 40% often; the figure is 72% in the second generation [27]. Natural code-switching happens at the level of phrases or tags ("Happy Friday, mi gente" — illustrative), not word-by-word calques. Academy-aligned voices treat *espanglish* and US Spanish as different things [50].

**Tone & humour on social:** Bicultural references and warmth (Low).

**Platform habits:** Same platforms as US English audiences. Bilingual captions are common (Low, not researched here).

**Formats:** $1,250.99 [10]. CLDR's short date is d/M/y, which clashes with the US month-first habit, so **spell dates out** (*10 de septiembre*). Time is 12-hour [10].

**Names of people & works:** Same as `es-MX`. English spellings (Tchaikovsky) are normal for bilingual readers (Low).

**Sensitivities:**
- Only 4% of US Latinos use *Latinx* for themselves [28]. Default to *latino/latina* or *hispano*.
- Avoid *coger* [7].
- Don't assume immigration status.

**Search aliases:** US Spanish, Spanish (United States), español de Estados Unidos, español estadounidense, Hispanic, Latino, Latina, Latinx, Spanglish, espanglish, Chicano, Tex-Mex, Miami, Nuyorican, es-US

**Prompt guide (≤120 words):** Write Spanish for US Hispanic readers. Use tú, and ustedes for groups. Choose widely understood Latin American words (celular, computadora, carro, jugo) and US-established terms where natural (rentar). Switch into English only for whole phrases or tags, and only when the author's voice mixes languages; never calque word by word. Avoid *coger*. Write money as $25.99. Spell out dates (10 de septiembre) to avoid day/month confusion. Default to latino/latina or hispano; use Latinx or Latine only if the author does. Don't assume the reader's country of origin, immigration status or Spanish fluency.

**Confidence:** High for the Pew data and formats. Medium for vocabulary. Low for tone.

**Native check:** acceptability of *aplicar* (apply for a job) and *textear* in brand voice; laughter forms; whether Latine is gaining ground.

**Sources:**
- [7] Microsoft, Spanish (US) Style Guide — https://download.microsoft.com/download/8/9/a/89ae1f7a-6c96-4f75-b51c-5590735ee810/spa-usa-StyleGuide.pdf
- [10] Unicode CLDR JSON (es-US) — https://github.com/unicode-org/cldr-json
- [27] Pew Research Center (2023), Latinos and Spanish: Views and Experience — https://www.pewresearch.org/race-and-ethnicity/2023/09/20/latinos-views-of-and-experiences-with-the-spanish-language/
- [28] Pew Research Center (2024), Latinx awareness has doubled… only 4% use it — https://www.pewresearch.org/race-and-ethnicity/2024/09/12/latinx-awareness-has-doubled-among-u-s-hispanics-since-2019-but-only-4-percent-use-it/
- [50] UFM, «Estadounidismos y espanglish» — https://educacion.ufm.edu/estadounidismos-y-espanglish/

---

### Español latinoamericano neutro · Neutral Latin American Spanish — `es-419` (delta)

**Where it's used / platforms:** Posts for readers in several Latin American countries at once: regional brands, courses, apps. "Neutral" is a **strategy, not a variety**. Microsoft says it "does not refer to any specific dialect of the language" and means choosing terms that suit a multinational audience [6]. A study of "neutral" dubbing found a patchwork of national norms and calques, which local audiences such as Argentine viewers found odd [29]. For platform data, use the entries for the target countries.

**Script & spelling:** Same as `es-MX` (*video*) [7].

**Punctuation & typography:** ¿ ¡ as in `es-MX`. For numbers, see Formats.

**Words that mark the region:** The aim is to mark none. Choose words that are safe everywhere:
- *celular*, *jugo*
- *vehículo/automóvil* instead of carro/auto/coche
- *vivienda* instead of departamento/apartamento/piso
- *genial/increíble* instead of chido/copado/chévere/guay
- *de acuerdo/perfecto* instead of vale/órale/dale/listo

Microsoft avoids computadora/computador/ordenador altogether by writing "PC" or "equipo" [6].

**Particles, interjections & fillers:** *jajaja* is safe. Avoid region-marked fillers (che, güey, parce, heavy *pues*).

**Formality & address:** *tú* for one reader, *ustedes* for a group, no vos or vosotros [29][6]. Microsoft uses tú for consumer products and usted for enterprise products [6]. Use the simple past [46].

**Mixing languages:** Only widely used English tech terms.

**Tone & humour on social:** Warmth has to come from wording, not regional particles. A creator's personal voice rarely suits es-419, and posts can read as dubbing-like or corporate (Low).

**Platform habits:** Depends on the target countries; see `es-MX`, `es-AR`, `es-CO`.

**Formats:** **No neutral number format exists.** CLDR's es-419 default is 1,250.50, but Argentina, Colombia and Uruguay write 1.250,50 [10]. Round figures ("15 mil") and always name the currency (USD, MXN, COP).

**Names of people & works:** Same as `es-MX`.

**Sensitivities:** Avoid words that are taboo anywhere: *coger* [4][7], *chaqueta* [40], *pitillo* [42], *concha*, *cajeta* [39].

**Limits of neutral:**
1. Numbers and currency (see Formats).
2. Loss of local warmth.
3. An artificial feel [29].
4. If most readers are in one country, use that country's locale instead.

**Search aliases:** Latin American Spanish, Spanish (Latin America), español latinoamericano, español neutro, neutral Spanish, international Spanish, español internacional, LatAm Spanish, LATAM, Latino, Hispanic, es-419

**Prompt guide (≤120 words):** Write pan-regional Latin American Spanish for readers in several countries. Use tú for one reader and ustedes for groups; no vos or vosotros verb forms. Pick words understood everywhere and avoid national slang (no chido, copado, chévere, vale, guay, parce, güey). Replace split words with neutral ones: celular, computadora or "equipo", vehículo, vivienda, jugo. Never use coger, chaqueta, pitillo or concha. Use the simple past and correct ¿ ¡. Avoid separator-dependent numbers: round them ("15 mil") and name the currency (USD, MXN, COP). Carry warmth through wording, not regional particles.

**Confidence:** High on the limits and the numbers problem. Medium on which words are safe everywhere.

**Native check:** whether *palomitas* and *departamento* are understood everywhere; whether readers find es-419 posts natural or corporate.

**Sources:**
- [4] Microsoft, Spanish (Mexico) Localization Style Guide — https://download.microsoft.com/download/9/0/1/9016efc5-6455-4a9d-ae78-ed3df93b2851/spa-mex-StyleGuide.pdf
- [6] Microsoft, Spanish (Neutral) Style Guide — https://download.microsoft.com/download/4/3/1/431d9836-40dc-4f2b-aafc-def5c7b5d0f3/spa-neu-StyleGuide.pdf
- [7] Microsoft, Spanish (US) Style Guide — https://download.microsoft.com/download/8/9/a/89ae1f7a-6c96-4f75-b51c-5590735ee810/spa-usa-StyleGuide.pdf
- [10] Unicode CLDR JSON (es-419 vs es-AR, es-CO, es-UY) — https://github.com/unicode-org/cldr-json
- [29] Montilla Martos, «El español "neutro" de los doblajes: intenciones y realidades», Carabela 50 (CVC) — https://cvc.cervantes.es/ensenanza/biblioteca_ele/carabela/pdf/50/50_191.pdf
- [39] Wikcionario (es): concha, cajeta — https://es.wiktionary.org/wiki/
- [40] Wikcionario (es), chaqueta — https://es.wiktionary.org/wiki/chaqueta
- [42] Wikipedia (es), Pajita — https://es.wikipedia.org/wiki/Pajita
- [46] Handy Spanish, perfecto vs indefinido (search result) — https://handyspanish.com/podcast/54-preterito-perfecto-vs-indefinido-diferencia-entre-colombia-espana-y-mexico/

---

### Português do Brasil · Portuguese (Brazil) — `pt-BR`

**Where it's used / platforms:** Brazil, with about 203 M native speakers [60]. It has 144 M social-media identities (67.8%). YouTube reaches 67.8% of the population, Instagram 66.2%, Facebook 52.6%, TikTok 56.4% of adults, LinkedIn 38.1% and X 7.5% [52]. WhatsApp is central to daily life but is not measured in the report (Low).

**Script & spelling:** AO90 is mandatory in Brazil since 1 January 2016 [20]. The diaeresis is gone (*pinguim*) and so are accents like *idéia* → *ideia* [19]. Spellings that still differ from Portugal: **econômico, Antônio, fato** (fact), **recepção, registrar** [20][60][8].

**Punctuation & typography:** Curly quotes “ ”. Angle quotes are little known, and Brazilian keyboards lack them [58]. Numbers use a decimal comma and point thousands [10]. Exclamation marks are common in casual posts (Low).

**Words that mark the region:**

| concept | pt-BR | pt-PT |
|---|---|---|
| bus | ônibus [53] | autocarro |
| train | trem [53] | comboio |
| mobile phone | celular [53] | telemóvel |
| breakfast | café da manhã [53] | pequeno-almoço |
| screen | tela [53][9] | ecrã [8] |
| user | usuário [9] | utilizador [8] |
| team | equipe (work), time (sports, casual) [53] | equipa |
| juice / ice cream | suco / sorvete [53] | sumo / gelado |
| bathroom | banheiro [53] | casa de banho |
| queue | fila [54] | bicha |
| cool | legal, bacana [55] | fixe, giro [55] |
| money (colloquial) | grana [55] | (native check) |
| OK / sure | beleza, tá bom, valeu [55] | está bem, pronto, ok (native check) |
| suit | terno [54] | fato |

**Particles, interjections & fillers:** *né?* (right?), *tipo* (like), *gente* (to address followers), *beleza* (OK) [55], *mano* (bro, São Paulo; native check). Laughter:
- ***kkkk*** is the most Brazilian, used for genuinely funny things among young and close audiences.
- ***haha(ha)*** is more neutral and suits professional or less intimate posts.
- ***rsrs*** is older internet style and can sound forced or passive-aggressive [22].

**Formality & address:** Use **você/vocês** for readers. Microsoft's Brazil guide addresses readers with você throughout [9]. *Tu* is common in Rio Grande do Sul, Santa Catarina and parts of the North and North-east, often with third-person verbs (*tu vai*) [61]. *A gente* = "we" is frequent in speech and preferred by younger speakers [62]. Brazilian speech puts pronouns **before the verb** (*me conta*, *te amo*); formal written Brazilian and European norms are closer to each other [18]. Actions in progress use the gerund (*estou ensaiando*) [16]. Brazil often drops the article before possessives (*meu livro*) [53]. Gendered agreement: *obrigado* if the author is a man, *obrigada* if a woman; also *cansado/cansada* and *animado/animada*. Never guess.

**Mixing languages:** English marketing words are common (*feedback*, *insights*, *live*, *post*) (Low).

**Tone & humour on social:** Warm and emotive: affectionate diminutives (*-inho*: *cafezinho*, *rapidinho*), emoji-rich captions, direct appeals to *gente*. Self-promotion on LinkedIn and Instagram is accepted when framed as gratitude or learning (Low, observed patterns).

**Platform habits:** Instagram and WhatsApp come first [52], and Reels and TikTok are strong. LinkedIn reach is large in absolute terms [52].

**Formats:** **R$ 49,90** (symbol, non-breaking space, comma decimals) [10]. Dates are 16/09/2026. Time is 24-hour (19:30); informal *19h* or *19h30* is common in event posts (native check) [10].

**Names of people & works:** No fixed norm for transcribing Russian names [63]. Brazilian press and pt.wikipedia use forms like *Tchaikovski* or *Tchaikovsky*, and Rachmaninoff or Rachmaninov varies [63]. Copy the author's form. Titles are translated where established (*O Lago dos Cisnes*).

**Sensitivities:**
- Words that are harmless in Portugal: *rapariga* (a pejorative regional sense in Brazil) [56], *bicha* (queue in Portugal, a gay slur in Brazil) [55], *puto* (a kid in Portugal; angry or vulgar in Brazil) [55], *propina* (a school fee in Portugal, a bribe in Brazil) [55].
- Neutral-language forms (*todes*, *elu*): the Supreme Court (STF) struck down a state ban on formal grounds in 2023 [24]. Law 15.263/2025 tells public administration "não usar novas formas de flexão de gênero e de número" [25]. Some government ministers used *todes* in 2023 [26]. The topic is politically charged, so use these forms only if the author does.

**Search aliases:** Portuguese (Brazil), Brazilian Portuguese, português brasileiro, português do Brasil, portugues, brasileiro, Brasil, Brazil, Brazilian, PT-BR, pt-BR, português

**Prompt guide (≤120 words):** Write Brazilian Portuguese. Address readers as você/vocês; *a gente* for "we" suits casual posts. In casual writing, put pronouns before the verb (me conta, se inscreve). Use the gerund for ongoing actions (estou ensaiando). Use Brazilian vocabulary and spelling: celular, ônibus, trem, tela, usuário, equipe, café da manhã, econômico, fato. Warmth, diminutives (-inho) and emojis are natural. Use kkkk for casual laughter and haha for neutral. Write money as R$ 49,90 and times as 24-hour (19h30). Avoid rapariga, bicha, puto and propina in their Portugal senses. Choose obrigado or obrigada by the author's gender; don't assume.

**Confidence:** High for grammar markers, vocabulary, spelling and formats. Medium for laughter and fillers. Low for tone and self-promotion norms.

**Native check:** the "19h30" format; *mano*; emoji and exclamation density by platform; LinkedIn norms.

**Sources:**
- [8] Microsoft, Portuguese (Portugal) Localization Style Guide — https://download.microsoft.com/download/9/9/5/995a8ca6-383c-439d-9db0-cd457c9c2724/por-prt-StyleGuide.pdf
- [9] Microsoft, Portuguese (Brazil) Localization Style Guide — https://download.microsoft.com/download/8/e/3/8e349e32-9eb9-4b63-9909-7586b94a24dd/por-bra-StyleGuide.pdf
- [10] Unicode CLDR JSON (pt) — https://github.com/unicode-org/cldr-json
- [16] Ciberdúvidas, «O gerúndio e a perífrase estar a + infinitivo» — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/o-gerundio-e-a-perifrase-estar-a--infinitivo/34913
- [18] Ciberdúvidas, «Colocação pronominal: português do Brasil x português europeu» — https://ciberduvidas.iscte-iul.pt/artigos/rubricas/idioma/colocacao-pronominal-portugues-do-brasil-x-portugues-europeu/5754
- [19] Wikipedia, Portuguese Language Orthographic Agreement of 1990 — https://en.wikipedia.org/wiki/Portuguese_Language_Orthographic_Agreement_of_1990
- [20] Wikipédia, Acordo Ortográfico de 1990 — https://pt.wikipedia.org/wiki/Acordo_Ortogr%C3%A1fico_de_1990
- [22] Chega de Fiu Fiu, «Qual é a diferença entre kkkkkk, hahaha e rsrsrs?» — https://chegadefiufiu.com.br/qual-e-a-diferenca-entre-kkkkkk-hahaha-e-rsrsrs/
- [24] STF Notícias (2023), Rondônia neutral-language ban — https://noticias.stf.jus.br/postsnoticias/stf-entende-que-proibicao-de-linguagem-neutra-em-rondonia-invade-competencia-da-uniao-sobre-educacao/
- [25] Lei nº 15.263/2025, art. 5º, XI — https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/L15263.htm
- [26] Wikipédia, Linguagem neutra — https://pt.wikipedia.org/wiki/Linguagem_neutra
- [52] DataReportal, Digital 2025: Brazil — https://datareportal.com/reports/digital-2025-brazil
- [53] Dicio, «Português de Portugal e a diferença com o português do Brasil» — https://www.dicio.com.br/portugues-de-portugal-e-a-diferenca-com-o-portugues-do-brasil/
- [54] Ciberdúvidas, «20 palavras semanticamente diferentes em Portugal e no Brasil» — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/20-palavras-semanticamente-diferentes-em-portugal-e-no-brasil/14050
- [55] Wikcionário (pt): legal, bacana, grana, beleza, bicha, puto, propina, fixe, giro — https://pt.wiktionary.org/wiki/
- [56] Priberam, «rapariga» — https://dicionario.priberam.org/rapariga
- [58] Wikipédia, Aspas — https://pt.wikipedia.org/wiki/Aspas
- [60] Wikipédia, Português brasileiro — https://pt.wikipedia.org/wiki/Portugu%C3%AAs_brasileiro
- [61] «A variável sexo/gênero e o uso de tu/você no Sul do Brasil» (Signum; search result) — https://ojs.uel.br/revistas/uel/index.php/signum/article/download/20205/16677/100550
- [62] «Nós e a gente no português falado culto do Brasil» (DELTA; search result) — https://www.scielo.br/j/delta/a/KQmrjr5yGgL49JPWMSGGhSj/?lang=pt
- [63] Ciberdúvidas, «Russo-português»; «A grafia em português de nomes russos» (search results) — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/russo-portugues/556 · https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/a-grafia-em-portugues-de-nomes-russos/23347

---

### Português europeu · Portuguese (Portugal) — `pt-PT`

**Where it's used / platforms:** Portugal, including Madeira and the Azores. It is also the reference norm for Portuguese-speaking Africa and Timor-Leste (see note) [59]. Portugal has 7.49 M social-media identities (71.9%). YouTube reaches 71.9%, Facebook 59.5%, Instagram 57.6%, **LinkedIn 53.7%** (very high), TikTok 41.9% of adults and X 17.8% [52].

**Script & spelling:** AO90 has been mandatory for the state since January 2012, and the transition ended in May 2015 [19][20]. Silent consonants were dropped (*ação*, *ótimo*). Pronounced consonants and European forms remain: **facto, receção, económico, António, registar** [20][8]. Some writers and publications still reject AO90, so older spellings (*acção*) appear (native check).

**Punctuation & typography:** Angle quotes « » are traditional and have their own keys on Portuguese keyboards. Curly quotes are increasingly common online [58], and Microsoft's Portugal guide uses “ ” [8]. The thousands separator is a space, with none at four digits (1500; 12 500) [10].

**Words that mark the region:** See the pt-BR table. Also *miúdo/puto* (kid) [55], *giro* (cute or nice), *porreiro* (great) [55], *gajo* (guy; a jocular word for "a Portuguese" in Brazil) [55], *casa de banho*, *fato*, *bicha* (queue) [53][54].

**Particles, interjections & fillers:** ***pá*** is a casual vocative and filler, specific to Portugal [56]. Also ***fixe*** (cool) [55], ***bué*** (very, a lot; Angolan in origin and youth-marked; in Brazil the word means crying) [55][57], *tipo*, *pronto* (OK, well; native check).
- **Laughter: sources disagree.** A Brazilian article says Portugal also uses *kkkk* [23]. That source is weak, and observed patterns suggest *ahah*, *haha* and *lol*, with *kkkk* read as Brazilian. Avoid *kkkk* (native check).

**Formality & address:** **Avoid "você" as direct address.** It can sound condescending or rude to many Portuguese readers. Portuguese speakers themselves drop the pronoun and use a third-person verb (*Sabe onde…?*), use the person's name, or use *tu* with people they are close to [17]. Microsoft's Portugal guide avoids "você" by rephrasing (*Não pode fechar…*) [8]. For casual creator posts, *tu* (*inscreve-te*) or a group address with *vocês* verbs works (Medium). Progressive: **estar a + infinitive** (*estou a ensaiar*) [16]. The gerund survives regionally in Alentejo, the Algarve and the islands [16]. Pronouns go **after the verb** in main clauses (*conta-me*, *amo-te*) [18]. Gendered agreement: *obrigado/obrigada* by the author's gender; don't assume.

**Mixing languages:** Brazilian influence through YouTube and streaming is debated. A linguist told Observador that seeing a brazilianism as an invasion is a sign of insecurity [64]. English marketing terms are common (Low).

**Tone & humour on social:** More restrained than pt-BR: fewer exclamation marks, understatement, and self-deprecating humour (Low).

**Platform habits:** LinkedIn reach is exceptional [52], so professional posts matter. Facebook still matters for older audiences [52].

**Formats:** **49,90 €** or **1500 €** (symbol after, non-breaking space) [10]. Dates are 16/09/26 or *16 de setembro de 2026*. Time is 24-hour (21:00; *21h* is common, native check) [10]. Large numbers use the long scale officially: *mil milhões* is 10⁹. One localization guide renders 16 billion as "16 biliões" [8], which conflicts with that, so native check.

**Names of people & works:** No fixed norm. Portuguese traditionally followed French transcription (*Tchaikovski*) [63]. Copy the author.

**Sensitivities:**
- Direct *você* [17].
- Assuming Portuguese = Brazilian: Brazilian vocabulary, *kkkk* or gerunds read as foreign.
- Neutral forms (*todes*) are debated. Government equality bodies publish inclusive-language guides that mostly favour neutral rewording [65]. Use *todes* only if the author does.

**Portuguese-speaking Africa note:** Angola, Mozambique, Cape Verde, Guinea-Bissau and São Tomé follow the **European norm** in writing [59], so pt-PT is the closer base. Angola and Mozambique have not fully adopted AO90. Sources disagree on Mozambique's ratification (Council of Ministers 2012 vs "not ratified") [20][21]. Local currencies (Kz, MT, CVE) and local slang (*bué* came from Luanda) [57] should come from the author. CLDR pt-AO and pt-MZ use space thousands and a trailing currency symbol [10].

**Search aliases:** Portuguese (Portugal), European Portuguese, português europeu, português de Portugal, portugues, Portugal, português, Lisbon, Lisboa, Iberian Portuguese, PT-PT, pt-PT, Angola, Moçambique, Mozambique, Cabo Verde

**Prompt guide (≤120 words):** Write European Portuguese (Portugal). Never address the reader as "você". Use tu for a casual, close audience, or a verb with no pronoun (Sabe que…?). Use estar a + infinitive for ongoing actions (estou a ensaiar), never the gerund. Put pronouns after the verb in main clauses (inscreve-te, conta-me). Use Portugal vocabulary and spelling: telemóvel, autocarro, comboio, ecrã, utilizador, equipa, pequeno-almoço, facto, receção, económico, registar. Keep the tone more restrained than Brazilian: fewer exclamation marks and emojis, and no kkkk. Write money as 49,90 € and times as 24-hour. Choose obrigado or obrigada by the author's gender.

**Confidence:** High for você, estar a, clitics, AO90 and vocabulary. Medium for fillers. Low for laughter, tone and time style.

**Native check:** laughter forms; *pronto*; *21h* versus *21:00*; bilião versus mil milhões in everyday media; how common anti-AO90 spelling is on social; brand use of tu.

**Sources:**
- [8] Microsoft, Portuguese (Portugal) Localization Style Guide — https://download.microsoft.com/download/9/9/5/995a8ca6-383c-439d-9db0-cd457c9c2724/por-prt-StyleGuide.pdf
- [10] Unicode CLDR JSON (pt-PT, pt-AO, pt-MZ) — https://github.com/unicode-org/cldr-json
- [16] Ciberdúvidas, «O gerúndio e a perífrase estar a + infinitivo»; «Uso do gerúndio em Portugal» (search result) — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/o-gerundio-e-a-perifrase-estar-a--infinitivo/34913 · https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/uso-do-gerundio-em-portugal/34023
- [17] Ciberdúvidas, «Por que é melhor não tratar ninguém por "você" em Portugal» — https://ciberduvidas.iscte-iul.pt/artigos/rubricas/idioma/por-que-e-melhor-nao-tratar-ninguem-por-voce-em-portugal/4577
- [18] Ciberdúvidas, «Colocação pronominal: português do Brasil x português europeu» — https://ciberduvidas.iscte-iul.pt/artigos/rubricas/idioma/colocacao-pronominal-portugues-do-brasil-x-portugues-europeu/5754
- [19] Wikipedia, Portuguese Language Orthographic Agreement of 1990 — https://en.wikipedia.org/wiki/Portuguese_Language_Orthographic_Agreement_of_1990
- [20] Wikipédia, Acordo Ortográfico de 1990 — https://pt.wikipedia.org/wiki/Acordo_Ortogr%C3%A1fico_de_1990
- [21] e-Global, «Angola e Moçambique mantêm Acordo Ortográfico por ratificar» — https://e-global.pt/noticias/lusofonia/angola/angola-e-mocambique-mantem-acordo-ortografico-por-ratificar/
- [23] ND+, «Kkkkk, 55555, LOL, 23333, jajaja…» — https://ndmais.com.br/cultura/kkkkk-55555-lol-23333-jajaja-conheca-as-risadas-online-mais-comuns-no-mundo/
- [52] DataReportal, Digital 2025: Portugal — https://datareportal.com/reports/digital-2025-portugal
- [53] Dicio, «Português de Portugal e a diferença com o português do Brasil» — https://www.dicio.com.br/portugues-de-portugal-e-a-diferenca-com-o-portugues-do-brasil/
- [54] Ciberdúvidas, «20 palavras semanticamente diferentes em Portugal e no Brasil» — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/20-palavras-semanticamente-diferentes-em-portugal-e-no-brasil/14050
- [55] Wikcionário (pt): fixe, bué, giro, porreiro, gajo, puto — https://pt.wiktionary.org/wiki/
- [56] Priberam, «pá» — https://dicionario.priberam.org/p%C3%A1
- [57] Ciberdúvidas, «Bué de…» (search result) — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/bue-de/388
- [58] Wikipédia, Aspas — https://pt.wikipedia.org/wiki/Aspas
- [59] Wikipédia, Português europeu — https://pt.wikipedia.org/wiki/Portugu%C3%AAs_europeu
- [63] Ciberdúvidas, «Russo-português» (search result) — https://ciberduvidas.iscte-iul.pt/consultorio/perguntas/russo-portugues/556
- [64] Observador, interview with Fernando Venâncio on brazilianisms (search result) — https://observador.pt/especiais/fernando-venancio-linguista-ver-um-brasileirismo-como-uma-invasao-e-coisa-de-gente-insegura/
- [65] CIG, Guia de Promoção para uma Linguagem Inclusiva (2025; search result) — https://www.cig.gov.pt/iniciativas-nacionais/wp-content/uploads/2025/07/Guia-de-Promocao-Para-uma-Linguagem-Inclusiva_VF.pdf

---

## Open questions

1. **pt-PT laughter.** The one source found [23] says Portugal writes *kkkk* too, which conflicts with observed patterns. A native reviewer or a corpus of Portuguese posts is needed before the prompt guide bans *kkkk* outright.
2. **24-hour vs 12-hour time in es-AR, es-CO and es-MX.** CLDR gives 12-hour time for all three [10], but event posts, especially in Argentina, often look 24-hour. Before hard-coding the format, check a sample of real event posts.
3. **es-US date order.** CLDR gives d/M/y, while US habit is month-first. The guide sidesteps this by spelling dates out. Confirm the UI does the same.
4. **The pt-PT "billion".** The official long scale (mil milhões = 10⁹) conflicts with Microsoft's "16 biliões" [8]. The same trap exists in Spanish (billón = 10¹², general knowledge; DPD not fetched).
5. **Colombian decimals.** CLDR uses a comma [10], but point decimals appear in practice. This needs a native check.
6. **Inclusive-language status not verified** for Mexico, Colombia, Uruguay (including any 2022 education rule), Spain and Portugal. Only Argentina [14][15], Brazil [24][25] and the RAE [13] were confirmed. The Wikipedia claim that some Brazilian ministers used *todes* in 2023 [26] was not checked against primary news.
7. **Mozambique and AO90.** Sources disagree [20][21]. Treat Angola and Mozambique as "European norm, pre-AO90 spellings still common".
8. **Tone, emoji and LinkedIn self-promotion norms** by country rest on observation, not studies (all Low). A small review of native posts per locale would firm these up.
9. **Pages that could not be opened.** The RAE and DPD blocked automated fetches, so voseo details [1], quote guidance [3] and number rules [11] come from search-result text. The web-search budget ran out before car, jacket and bus words could be cross-checked beyond Wiktionary and Wikipedia.


---

## European languages

Research file 04 for the PostRiff region-aware language picker. Compiled 2026-09-16. Citations [n] use one numbering scheme for the whole file. Sources used by several locales ([1]–[6]) are listed under Family notes. Every other source is listed in the entry that uses it first, and later entries point back to it by number.

A note on the evidence. The Microsoft localization guides ([6] and the per-locale guides) were written for software and documentation, not for social posts. They are reliable for typography, formats and grammar habits. For social tone they only hint at a trend. Where no source covered social-media habits directly, the section says so and the item goes into "Native check". Example phrases marked *illustrative* were written for this file; none is copied from a real post.

---

### Family notes

#### Comparison table

| Locale | T/V default on social | Quotes (primary / nested) | Decimal · grouping | Currency (CLDR default) | Short date · time |
|---|---|---|---|---|---|
| fr-FR | Brands split: **tu** on consumer Instagram/TikTok, **vous** on LinkedIn/B2B [9]. A person speaking to followers uses plural **vous** | « … » with inner no-break spaces / “ … ” [7] | 1 234,56 (U+202F narrow no-break space) [1] | 1 234,50 € [1][7] | 05/09/2026 · 18:30 [1] |
| fr-CA | **tu** far more common than in France [20]; plural **vous** for an audience | « … » (inner spaces in print, none needed on social [18]) | 1 234,56 (U+00A0) [1] | 1 234,50 $ [1][29] | 2026-09-05 · 18 h 30 [1] |
| de-DE | **du** rising for consumer brands (IKEA, Apple, Aldi) [38]; **Sie** for B2B/regulated | „ … “ / ‚ … ‘ [5][34] | 1.234,56 [1][34] | 1.234,50 € [1] | 05.09.2026 · 18:30 [1] |
| de-AT | as de-DE (native check) | „ … “ | 1 234,56 (plain numbers), 1.234,50 in money [1] | € 1.234,50 [1] | 05.09.2026 · 18:30 [1] |
| de-CH | as de-DE (native check) | « … » no spaces / ‹ … › [45][47] | Official: 1 234 567 and 88,5 m; CLDR: 1'234.56 [1][45] | CHF 1'234.50 [1]; official Fr. 23.50 [45] | Official 2.9.2026 · 14.30 Uhr [45]; CLDR 05.09.26 · 18:30 [1] |
| it-IT | **tu** (Microsoft UI uses tu [48]) | « … » / “ … ” [5] | 1.234,56 (4-digit numbers ungrouped) [1] | 1234,50 € [1] (€ 1.234,50 also common, native check) | 05/09/2026 · 18:30 [1] |
| nl-NL | **je** (growing trend [51][52]) | “ … ” / ‘ … ’ (also „ … ”) [5] | 1.234,56 [1][51] | € 1.234,50 [1] | 05-09-2026 · 18:30 [1] |
| nl-BE | mixed u / je (native check) | as nl-NL | 1.234,56 [1] | € 1.234,50 [1] | 5/09/2026 · 18:30 [1] |
| pl-PL | **ty** for consumer brands (Microsoft uses capital *Ty* [59]); **Państwo** formal | „ … ” / « … » [5][59] | 12 345,6; 4-digit ungrouped [1] | 1234,50 zł [1] | 5.09.2026 · 18:30 [1] |
| tr-TR | **siz** default (Microsoft UI [62]); **sen** for youthful voices (native check) | “ … ” / ‘ … ’ [5] | 1.234,56 [1] | ₺1.234,50 [1] (1.234,50 TL common, native check) | 5.09.2026 · 18:30; %25 [1] |
| ru-RU | **вы** (lower case in UI [67]; **Вы** in letters [69]) | «ёлочки» / „лапки“ [5] | 1 234,56 [1] | 1 234,50 ₽ [1] | 05.09.2026 · 18:30 [1] |
| uk-UA | **ви**; friendlier tone allowed online [72] | « … » / „ … “ [5] | 1 234,56 [1] | 1 234,50 ₴ [1] (грн common) | 05.09.2026 · 18:30 [1] |

All twelve locales use the 24-hour clock and a decimal comma in running text. The exception is Swiss money amounts, which use a decimal point [45].

#### Cross-cutting findings

1. **The writer's gender shows up in the grammar.** In Polish, Russian and Ukrainian the first-person past tense marks it: *zrobiłem/zrobiłam*, *я сделал/сделала*, *зробив/зробила* [79][69][73]. French and Italian adjectives and participles do the same (*je suis ravi/ravie*, *sono emozionato/emozionata*). The drafting model must take gender from the writer profile. When the profile doesn't give it, rephrase with the present tense, "we", or an impersonal form, which is the approach Microsoft's Polish guide takes [59]. German, Dutch and Turkish verbs don't mark the writer's gender.
2. **Gender-inclusive spelling is a political choice in every market here.** France: the point médian was banned in schools and the Senate voted against it [13][14][15]. Québec: banned in government communications since September 2025 [28]. Germany: Bavaria banned gender symbols in schools and authorities in 2024 [37]. Italy: the schwa and asterisk were barred in schools in 2025 [4]. Mirror whatever the writer already does. If there's no signal, use neutral nouns or paired forms, never symbols.
3. **No-break spaces often get lost on social platforms.** The OQLF says to leave them out when a platform can't handle them [18]. Output should still be clean Unicode where it helps (U+202F / U+00A0), with a plain-space fallback.
4. **Names of foreign people and works are spelled differently in each language.** Wikidata labels [2] show the Wikipedia title for each language. Concert programmes may use other spellings, for example German *Tschaikowsky*.

| English | fr | de | it | nl | pl | tr | ru | uk |
|---|---|---|---|---|---|---|---|---|
| Tchaikovsky | Tchaïkovski | Tschaikowski | Čajkovskij | Tsjaikovski | Czajkowski | Çaykovski | Чайковский | Чайковський |
| Rachmaninoff | Rachmaninov | Rachmaninow | Rachmaninov | Rachmaninov | Rachmaninow | Rahmaninov | Рахманинов | Рахманінов |
| Stravinsky | Stravinsky | Strawinsky | Stravinskij | Stravinsky | Strawinski | Stravinsky | Стравинский | Стравінський |
| J. S. Bach | Jean-Sébastien Bach | Johann Sebastian Bach | = de | = de | = de | = de | Иоганн Себастьян Бах | Йоганн Себастьян Бах |
| Handel | Haendel | Händel | Händel | Handel | Händel | Handel | Гендель | Гендель |
| Chopin | Frédéric Chopin | Frédéric Chopin | Fryderyk Chopin | Frédéric Chopin | Fryderyk Chopin | Frédéric Chopin | Фредерик Шопен | Фридерик Шопен |
| Liszt | Franz Liszt | Franz Liszt | Franz Liszt | Franz Liszt | Ferenc Liszt | Franz Liszt | Ференц Лист | Ференц Ліст |
| The Nutcracker | Casse-noisette | Der Nussknacker | Lo schiaccianoci | (De) Notenkraker | Dziadek do orzechów | Fındıkkıran | Щелкунчик | Лускунчик |

**Sources (shared):**
- [1] Unicode CLDR 48 data via ICU 78.3 in Node.js `Intl` (NumberFormat and DateTimeFormat run locally, 2026-09-16); cross-checked against cldr-numbers-full — https://cdn.jsdelivr.net/npm/cldr-numbers-full/main/de-AT/numbers.json
- [2] Wikidata item labels (Q7315, Q131861, Q7314, Q1339, Q7302, Q1268, Q41309, Q193705) — https://www.wikidata.org/wiki/Q7315
- [3] Wikipedia, "T–V distinction" — https://en.wikipedia.org/wiki/T%E2%80%93V_distinction
- [4] Wikipedia, "Gender neutrality in languages with grammatical gender" — https://en.wikipedia.org/wiki/Gender_neutrality_in_languages_with_grammatical_gender
- [5] Wikipedia, "Quotation mark" (per-language summary table) — https://en.wikipedia.org/wiki/Quotation_mark
- [6] Microsoft, "Microsoft Localization Style Guides" (index) — https://learn.microsoft.com/en-us/globalization/reference/microsoft-style-guides

---

### Français (France) · French (France) — `fr-FR`

**Where it's used / platforms:** Metropolitan and overseas France. The Toubon Law requires French in commercial advertising but exempts non-commercial private web publishing [12].

**Script & spelling:** Latin script with diacritics. Keep the œ ligature (*cœur*, *sœur*) and accents on capitals (*À bientôt*, *État*). Weekdays and months are lower case (*samedi 5 septembre*).

**Punctuation & typography:** Imprimerie nationale practice: a narrow no-break space (U+202F) before `; ! ?`, and a full no-break space before `:` and inside « » [8]. Microsoft simplifies this to a no-break space before all four marks [7]. Quotes are « » with “ ” for nested quotes. Punctuation that isn't part of the quote goes outside it. French uses fewer semicolons than English [7].

**Words that mark the region:**

| Concept | fr-FR | fr-CA | fr-BE / fr-CH |
|---|---|---|---|
| weekend | week-end | fin de semaine [22] | week-end |
| email | mail, e-mail (official term: courriel [10]) | courriel [31] | mail |
| shopping | faire du shopping, faire les magasins | magasiner [24] | — |
| breakfast / lunch / dinner | petit-déjeuner / déjeuner / dîner | déjeuner / dîner / souper [24] | déjeuner / dîner / souper [32][33] |
| 70 / 80 / 90 | soixante-dix / quatre-vingts / quatre-vingt-dix | as fr-FR | septante / quatre-vingts or huitante / nonante [32][33][78] |
| hashtag | hashtag (official: mot-dièse [10]) | mot-clic [19] | hashtag |
| podcast | podcast | balado [23] | podcast |

**Particles, interjections & fillers:** Online French is full of *du coup*, *en fait*, *genre*, *en vrai*, *de base*, and intensifiers like *trop* and *grave* [11]. Common abbreviations: mdr, ptdr, jsp, stp [12]. Keep abbreviations out of professional posts. *Illustrative:* "Bon, du coup, on se retrouve samedi ?"

**Formality & address:** A writer speaking to followers usually uses plural *vous*, which avoids the T/V choice (*illustrative:* "Merci à vous d'être venus"). Brands use tu or vous depending on platform and audience [9]. A 2012 report found vous declining on social media [3]. Microsoft's UI uses vous [7]. **Gender:** agreement shows the writer's gender (*ravi/ravie*, *allé/allée*), so never guess. If gender is unknown, rephrase (*illustrative:* "Quelle joie de vous retrouver"). **Écriture inclusive:** the point médian (*lecteur·rice·s*) is contested. A 2021 circular barred it in schools [15], the Conseil d'État upheld that ban [14], and the Senate adopted a bill against inclusive writing in October 2023 [13]. Unless the writer already uses it, choose epicene wording or paired forms, as Microsoft recommends (*l'équipe*, *toutes et tous*) [7].

**Mixing languages:** Marketing English is common (*live*, *story*, *save the date*; illustrative). Official replacements (*courriel*, *mot-dièse*) exist [10]. How much people use them is a native check.

**Tone & humour on social:** No source. Irony and understatement are assumed safer than hype (Low).

**Platform habits:** No French-specific source (Low).

**Formats:** 1 234,56 · 25,5 % · 1 234,50 € · 05/09/2026 or *5 septembre 2026* · 18:30 (18 h 30 is also seen) [1][7].

**Names of people & works:** Use French exonyms: Tchaïkovski, Rachmaninov, Haendel, Jean-Sébastien Bach, *Casse-noisette* [2]. Titles go in « » when italics aren't available.

**Sensitivities:** Inclusive writing is political (above). Anglicism-heavy copy can draw purist criticism in cultural or public contexts [12].

**Search aliases:** French, Français, Francais, French (France), France, Parisian French, Metropolitan French, français de France, langue française, fr_FR

**Prompt guide (≤120 words):** Write in France French. Put a narrow no-break space before ; ! ? and a no-break space before : and inside « ». Use « » quotes. Address followers with plural "vous". Use "tu" only if the writer's brand voice already does. Never assume the writer's gender. If the profile doesn't give it, rephrase to avoid gendered adjectives and participles. Prefer epicene wording to the point médian unless the writer uses it. Use France vocabulary (week-end, mail, déjeuner = lunch). Use the French spelling of foreign names (Tchaïkovski, Haendel). Format numbers as 1 234,56 and 12,50 €, dates as 5 septembre 2026, times as 18:30. Keep informal fillers ("du coup", "trop") only for casual personal voices.

**Confidence:** Typography and formats High. Address trends Medium. Tone and platform habits Low.

**Native check:** Whether people type the space before ! and ? on phones. *18 h 30* vs *18:30* in posts. tu/vous norms for creators and music institutions. Whether *courriel* sounds bureaucratic.

**Sources:**
- [7] Microsoft, French (France) Localization Style Guide — https://download.microsoft.com/download/c/7/9/c7921dbd-4531-4a4e-8490-e4656d739f3d/fra-fra-StyleGuide.pdf
- [8] Wikipédia (fr), "Espace fine insécable" (search result) — https://fr.wikipedia.org/wiki/Espace_fine_ins%C3%A9cable
- [9] Mathilde David, "Tutoyer ou vouvoyer" (search result, with related results) — https://www.mathildedavid.fr/tutoyer-ou-vouvoyer/
- [10] FranceTerme, "Mot-dièse" and "COURRIEL" — https://www.culture.fr/franceterme/terme/COGE792 · https://www.culture.fr/franceterme/Clin-d-aeil/COURRIEL
- [11] MAE, "Comprendre le langage des jeunes sur les réseaux sociaux" (search result) — https://www.mae.fr/famille/guides/guide-langage-ados-reseaux-sociaux
- [12] Wikipedia, "Toubon Law" — https://en.wikipedia.org/wiki/Loi_Toubon ; Linternaute, "MDR" (search result) — https://www.linternaute.fr/dictionnaire/fr/definition/mdr/
- [13] France 24, "Le point médian de la discorde" (search result) — https://www.france24.com/fr/france/20231031-le-point-m%C3%A9dian-de-la-discorde-l-%C3%A9criture-inclusive-dans-le-viseur-du-l%C3%A9gislateur
- [14] Conseil d'État, "L'interdiction de recourir à certains éléments de l'écriture inclusive … est légale" (search result) — https://www.conseil-etat.fr/actualites/l-interdiction-de-recourir-a-certains-elements-de-l-ecriture-inclusive-notamment-le-point-median-pour-l-enseignement-est-legale
- [15] Café pédagogique, "Écriture inclusive : la circulaire est publiée" (search result) — https://www.cafepedagogique.net/2021/05/09/ecriture-inclusive-la-circulaire-est-publiee/
- Shared: [1], [2], [3]

---

### Français (Québec) · French (Canada, Québec) — `fr-CA`

**Where it's used / platforms:** Québec, plus francophone communities elsewhere in Canada. The Charter of the French Language requires French in commercial material, and Bill 96 tightened signage and trademark rules from June 2025 [30].

**Script & spelling:** Same spelling as France, plus OQLF-recommended terms. Keep accents in hashtags and write multi-word tags in PascalCase (*#FinDeSemaine*) [19].

**Punctuation & typography:** No space before `; ! ?`. A no-break space before `:`. Spaces inside « » in formal text [16][17]. On social: drop no-break spaces when the platform can't handle them, use « » instead of italics with no inner spaces, and leave off the final period if you like. Avoid all-caps, which reads as shouting [18].

**Words that mark the region:**

| Concept | fr-CA | fr-FR |
|---|---|---|
| weekend | fin de semaine | week-end [22] |
| email / newsletter / podcast | courriel / infolettre / balado | mail / newsletter / podcast [23][31] |
| to go shopping | magasiner | faire du shopping [24] |
| lunch / dinner | dîner / souper | déjeuner / dîner [24] |
| girlfriend / boyfriend, buddy | blonde / chum | copine / copain [24] |
| car (informal) | char | voiture [24] |
| "you're welcome" | bienvenue | de rien [24] |
| corner store | dépanneur | épicerie [24] |
| selfie | égoportrait (official), selfie (common) | selfie [23] |

**Particles, interjections & fillers:** *pis* (= puis, "and then"), *tsé* (= tu sais), *ben* (= bien), *c'est plate* ("it's boring / too bad") [26]. Also *pantoute* ("not at all") and *niaiser* ("to kid around, waste time") [24]. The religious swear words (*sacres*: tabarnak, câlice, crisse, osti) are stronger than sexual swearing, and softened forms (*tabarouette*) are much milder [25]. *Illustrative:* "Pis là, on se voit samedi?"

**Formality & address:** Using tu from the first meeting is much more common in Québec than elsewhere [20]. Microsoft's fr-CA guide uses vous in the UI but tu for Copilot prompts [16]. A writer addressing an audience still uses plural *vous*. Gender agreement works as in fr-FR. **Inclusive writing:** the OQLF recommends epicene wording (paired forms, neutral terms) and advises against the point médian and *iel* [27]. On 24 September 2025 Québec banned *iel*, *toustes* and shortened paired forms such as *agent•e•s* from government communications [28]. For very short social texts the OQLF accepts parentheses such as *invité(e)s* [18].

**Mixing languages:** Public writing avoids anglicisms more strictly than France, and *courriel* and *balado* caught on [23][31]. *Égoportrait* and *mot-clic* compete with English [23]. Casual speech borrows English (native check).

**Tone & humour on social:** No source. Assumed warm and direct (Low).

**Platform habits:** Put hashtags inside the sentence or at the end, separated by spaces or vertical bars. Keep each one short [19]. The OQLF warns against SMS spelling and abbreviations in public posts [21].

**Formats:** 1 234,56 · 25,50 $ (symbol after the number, with a space) · *$ CA* / *$ US* to tell dollars apart [29] · 2026-09-05 or *le 5 septembre 2026* · 18 h 30 [1].

**Names of people & works:** Same exonyms as France (Tchaïkovski) [2]. Titles in « » with no inner spaces on social [18].

**Sensitivities:** Language law [30] and inclusive-writing policy [28]. France-only words (*week-end*, *mail*) read as non-local (native check).

**Search aliases:** Québécois, Quebecois, Québec French, Quebec French, Canadian French, French (Canada), français québécois, français canadien, Québec, Quebec, Montréal French, Montreal French, fr_CA

**Prompt guide (≤120 words):** Write in Québec French, not France French. No space before ; ! ? and a no-break space before :. On social, « » may have no inner spaces. Use Québec terms: fin de semaine, courriel, infolettre, balado, magasiner, dîner = lunch, souper = dinner. Don't use week-end, mail or shopping. Casual voices may use pis, tsé, ben, c'est plate, but never sacres. Use plural "vous" for an audience. Don't assume the writer's gender. Prefer epicene wording. No point médian, no "iel". Money is 25,50 $ and time is 18 h 30. Hashtags keep accents and use PascalCase.

**Confidence:** Typography, terminology and policy High (OQLF primary sources). Informal markers Medium. Social tone Low.

**Native check:** How far *égoportrait*, *mot-clic* and *infolettre* have really caught on on social. Brand tu/vous norms on Québec Instagram and Facebook. Which English borrowings (*cute*, *full*, *checker*) sound natural rather than sloppy.

**Sources:**
- [16] Microsoft, French (Canada) Localization Style Guide — https://download.microsoft.com/download/5/6/8/568628ff-0646-4740-a052-d8bd97ecdcf8/fra-can-StyleGuide.pdf
- [17] OQLF BDL, "Espacement avant et après les signes de ponctuation et les symboles" — https://vitrinelinguistique.oqlf.gouv.qc.ca/22039/la-typographie/espacement/espacement-avant-et-apres-les-signes-de-ponctuation-et-les-symboles
- [18] OQLF BDL, "Typographie et ponctuation" (rédaction dans les réseaux sociaux) — https://vitrinelinguistique.oqlf.gouv.qc.ca/25377/la-redaction-et-la-communication/redaction-dans-les-reseaux-sociaux/typographie-et-ponctuation
- [19] OQLF BDL, "Intégration d'hyperliens : mots-clics, mentions et URL" — https://vitrinelinguistique.oqlf.gouv.qc.ca/25387/la-redaction-et-la-communication/redaction-dans-les-reseaux-sociaux/integration-dhyperliens-mots-clics-mentions-et-url
- [20] OQLF BDL, "Contextes d'emploi du vouvoiement et du tutoiement" — https://vitrinelinguistique.oqlf.gouv.qc.ca/25140/la-redaction-et-la-communication/protocole-et-activites-publiques/contextes-demploi-du-vouvoiement-et-du-tutoiement
- [21] OQLF BDL, "Principes généraux de la rédaction dans les réseaux sociaux" — https://vitrinelinguistique.oqlf.gouv.qc.ca/25374/la-redaction-et-la-communication/redaction-dans-les-reseaux-sociaux/principes-generaux-de-la-redaction-dans-les-reseaux-sociaux
- [22] OQLF BDL, "L'emprunt déconseillé week" (search result) — https://vitrinelinguistique.oqlf.gouv.qc.ca/25413/les-emprunts-a-langlais/emprunts-integraux/lemprunt-deconseille-week
- [23] États de langue, "Quel rayonnement pour « divulgâcher » et autres néologismes québécois" — https://etatslangue.wordpress.com/2023/08/24/quel-rayonnement-pour-divulgacher-et-autres-neologismes-quebecois-dans-la-francophonie/ ; OQLF GDT "balado", "égoportrait" (search results)
- [24] Wikipedia, "Quebec French lexicon" — https://en.wikipedia.org/wiki/Quebec_French_lexicon
- [25] Wikipedia, "Quebec French profanity" — https://en.wikipedia.org/wiki/Quebec_French_profanity
- [26] Je Parle Québécois, "Pis" and "Plate" (search results) — https://www.je-parle-quebecois.com/lexique/definition/pis.html ; Guichet du savoir, "C'est plate" — https://www.guichetdusavoir.org/question/voir/54005
- [27] OQLF BDL, "Rédaction épicène et autres styles d'écriture dits inclusifs" (search result) — https://vitrinelinguistique.oqlf.gouv.qc.ca/25421/banque-de-depannage-linguistique/la-redaction-et-la-communication/feminisation-et-redaction-epicene/redaction-epicene/redaction-epicene-et-autres-styles-decriture-dits-inclusifs
- [28] La Presse, "Communications gouvernementales : Québec interdit l'écriture inclusive" (2025-09-24, search result) — https://www.lapresse.ca/actualites/2025-09-24/communications-gouvernementales/quebec-interdit-l-ecriture-inclusive.php
- [29] Language Portal of Canada, "Sommes d'argent et unités monétaires" — https://our-languages.canada.ca/en/cles-de-la-redaction/sommes-dargent-et-unites-monetaires
- [30] Wikipedia, "Charter of the French Language" — https://en.wikipedia.org/wiki/Charter_of_the_French_Language
- [31] Elon.io, "Anglicismes : Québec et France" (search result) — https://elon.io/grammar/french/regional/anglicismes-quebec-vs-france
- Shared: [1], [2]

#### Note: French in Belgium (`fr-BE`) and Switzerland (`fr-CH`)

Both follow France's spelling and « » quotes. Differences a reader notices at once:
- **Numbers:** *septante* (70) and *nonante* (90) in both countries. Belgium keeps *quatre-vingts* for 80. In Switzerland *huitante* is used in Vaud, Valais and Fribourg, while Geneva, Neuchâtel and Jura say *quatre-vingts* [32][33][78].
- **Meals:** *déjeuner / dîner / souper* for breakfast, lunch and dinner, as in Québec [32][33].
- **Swiss words:** *natel* (mobile phone), *panosse* (mop), and *adieu* used as a greeting [32].
- **Belgian words:** *kot* (student room), *dringuelle* (tip), and *s'il vous plaît* said when handing something over [33].
- **Formats:** CLDR fr-CH writes 1'234,56 but money as 1'234.50 CHF [1]. fr-BE follows France: 1 234,50 €, with 5/09/26 as the short date [1].

Confidence Medium. Native check: *GSM* for a mobile in Belgium, and whether Swiss French social posts keep the space inside « ».

- [32] Wikipedia, "Swiss French" — https://en.wikipedia.org/wiki/Swiss_French
- [33] Wikipedia, "Belgian French" — https://en.wikipedia.org/wiki/Belgian_French
- [78] numbersinfrench.com, "Numbers in Swiss French: Septante, Huitante, Nonante by Canton" (search result) — https://numbersinfrench.com/numbers-in-swiss-french/

---

### Deutsch (Deutschland) · German (Germany) — `de-DE`

**Where it's used / platforms:** Germany. Austrian and Swiss standards are covered in the deltas below.

**Script & spelling:** Nouns are capitalised. ß follows long vowels (*Straße*); ss follows short ones (*Fluss*). **Sie/Ihr/Ihnen is always capitalised.** *du/dein* is lower case. Capital *Du* is optional in letters, emails and personal messages, but not in adverts [35]. English parts of compounds are hyphenated (*Social-Media-Post*) [34].

**Punctuation & typography:** Quotes are „…“ with ‚…‘ nested. Books may use »…« [5][34]. Put a no-break space inside *z. B.* and *d. h.* [34]. No space before ! or ?.

**Words that mark the region:**

| Concept | de-DE | de-AT | de-CH |
|---|---|---|---|
| January | Januar | Jänner [42] | Januar |
| tomato / potato | Tomate / Kartoffel | Paradeiser / Erdapfel [42][43] | Tomate / Kartoffel |
| bread roll / bag | Brötchen / Tüte | Semmel / Sackerl [42] | † |
| bicycle | Fahrrad | Fahrrad | Velo [46] |
| to park / to grill | parken / grillen | parken / grillen | parkieren / grillieren [46] |
| ice cream / chicken | Eis / Hähnchen | Eis / † | Glace / Poulet [46] |
| ticket | Fahrkarte, Ticket | Fahrkarte, Ticket | Billett [46] |
| hello | Hallo; Moin (north) | Grüß Gott, Servus [39] | Grüezi, Grüessech [39] |

† = needs native check.

**Particles, interjections & fillers:** Modal particles carry tone. *ja* marks shared knowledge [40]; *doch*, *mal*, *halt* and *eben* soften or shrug. *Illustrative:* "Schaut doch mal vorbei!", "Ist halt so." Youth intensifiers such as *mega*, *krass* and *echt* only suit casual voices.

**Formality & address:** Brands choose consciously and stay consistent. *du* is used by IKEA, Apple and Aldi. *Sie* suits finance, law, IT security and older audiences [38]. Microsoft's UI uses *Sie*, but *du* for under-18s and for Copilot prompts [34]. For an audience, casual plural is *ihr/euch* (illustrative). German verbs don't show the writer's gender, but job nouns do (*Pianist/Pianistin*). **Gendern:** the forms are *Leser\*innen* (asterisk), *Leser:innen* (colon), *LeserInnen* (Binnen-I) and *Leser_innen* [4]. On 15 December 2023 the Rechtschreibrat said such word-internal marks are not part of core German orthography [36]. Bavaria banned them in schools, universities and authorities from 1 April 2024, and other states restrict them in schools [37]. Microsoft avoids the symbols and uses neutral nouns or plurals instead [34]. Mirror the writer. Otherwise use *alle*, *Team*, *Mitwirkende*, or paired forms.

**Mixing languages:** English platform words are normal (*Post*, *Story*, *liken*; illustrative). "Denglisch" is pejorative: the Duden calls it derogatory, and the Verein Deutsche Sprache campaigns against it. Pseudo-anglicisms like *Handy*, *Beamer* and *Public Viewing* are German-only [41].

**Tone & humour on social:** No source. Directness is assumed (Low).

**Platform habits:** No German-specific source. PascalCase compound hashtags (*#Klavierabend*; illustrative) (Low).

**Formats:** 1.234,56 · 1.234,50 € · 25,5 % · 05.09.2026 or *5. September 2026* · 18:30 Uhr [1][34].

**Names of people & works:** Tschaikowski (Wikipedia label; *Tschaikowsky* is also common), Rachmaninow, Strawinsky, Händel, *Der Nussknacker* [2]. Titles go in „…“.

**Sensitivities:** Avoid phrases with Nazi associations. *Jedem das Seine* was the Buchenwald gate slogan, and adverts using it were withdrawn in 2009 and 2018 [44]. *Gendern* is politically divisive [37]. *Moin* and *Grüß Gott* signal region [39], so don't mix them.

**Search aliases:** German, Deutsch, German (Germany), Deutschland, Germany, Hochdeutsch, Standard German, Standarddeutsch, Bundesdeutsch, Allemand, de_DE

**Prompt guide (≤120 words):** Write in Germany Standard German. Use „…“ quotes. Always capitalise Sie/Ihr/Ihnen. Write du/dein in lower case. Pick du or Sie to match the writer's existing voice and keep it throughout. If there's no signal, use du for creative and personal posts and Sie for B2B or institutional ones. Use modal particles (doch, mal, halt) for natural spoken warmth. Don't use gender symbols unless the writer does. Prefer neutral nouns or paired forms. Keep English to established platform terms. Format numbers as 1.234,50 €, dates as 5. September 2026, times as 18:30 Uhr. Use German name spellings (Tschaikowski, Händel). Avoid Nazi-associated set phrases.

**Confidence:** Orthography and formats High. Address trends Medium. Tone and platform habits Low.

**Native check:** How common *du* is on German LinkedIn. How to handle *ihr* vs *Sie* when addressing concert audiences. *Tschaikowski* vs *Tschaikowsky* in current German concert marketing.

**Sources:**
- [34] Microsoft, German Localization Style Guide — https://aka.ms/german-styleguide
- [35] Duden, "Groß- oder Kleinschreibung von „du/Du" und „ihr/Ihr"" — https://www.duden.de/sprachwissen/sprachratgeber/Gross-oder-Kleinschreibung-von-duDu-und-ihrIhr
- [36] Rat für deutsche Rechtschreibung, "Geschlechtergerechte Schreibung: Erläuterungen, Begründung und Kriterien vom 15.12.2023" (search result) — https://www.rechtschreibrat.com/geschlechtergerechte-schreibung-erlaeuterungen-begruendung-und-kriterien-vom-15-12-2023/
- [37] Forschung & Lehre, "Bayern verbietet Gendern an Schulen, Hochschulen und Behörden" (search result) — https://www.forschung-und-lehre.de/politik/bayern-verbietet-gendern-in-schulen-hochschulen-und-behoerden-6318
- [38] Lexware, "Kundenansprache-1x1: Duzen, siezen, gendern?" — https://www.lexware.de/wissen/marketing-vertrieb/kundenansprache/
- [39] Wikipedia, "Grüß Gott" — https://en.wikipedia.org/wiki/Gr%C3%BC%C3%9F_Gott
- [40] Wikipedia, "Modal particle" — https://en.wikipedia.org/wiki/Modal_particle
- [41] Wikipedia, "Denglisch" — https://en.wikipedia.org/wiki/Denglisch
- [44] Wikipedia, "Jedem das Seine" — https://en.wikipedia.org/wiki/Jedem_das_Seine
- Shared: [1], [2], [4], [5]; cited in table: [42], [43], [46] (listed under de-AT / de-CH)

---

### Deutsch (Österreich) · German (Austria) — `de-AT`

**Where it's used / platforms:** Austria. The *Österreichisches Wörterbuch* has defined the official standard since 1951 [42].

**Script & spelling:** Same as de-DE (ß is kept).

**Punctuation & typography:** Same as de-DE.

**Words that mark the region:** *Jänner, Paradeiser, Erdäpfel, Topfen, Obers, Marille, Semmel, Sackerl* (see the de-DE table) [42]. In 1995 Protocol No. 10 of Austria's EU accession treaty gave 23 Austrian food terms equal status in EU law (e.g. *Karfiol, Kren, Ribisel, Obers*) [43]. Research reports that *Paradeiser*, *Sackerl* and *Jänner* have stayed stable in the Austrian press [43].

**Particles, interjections & fillers:** Greetings are *Grüß Gott* and *Servus* [39]. *eh*, *gell* and *oida* are unsourced (native check).

**Formality & address:** As de-DE. Grammar marker: *ich bin gesessen/gestanden* (perfect with *sein*) [42].

**Mixing languages:** Same as de-DE.

**Tone & humour on social:** No source (Low).

**Platform habits:** Same as de-DE.

**Formats:** CLDR puts € before the amount (€ 1.234,50) and groups plain numbers with a space (1 234,56) [1]. Dates 05.09.2026; time 18:30.

**Names of people & works:** Same as de-DE.

**Sensitivities:** Don't "correct" Austrian words to German ones, and don't present Austria as Germany. Austrian vocabulary is a point of identity [42][43].

**Search aliases:** Austrian German, Österreichisch, Österreichisches Deutsch, Austria, Österreich, Wienerisch, Viennese, de_AT

**Prompt guide (≤120 words):** Write Austrian Standard German. Use Austrian vocabulary where it applies: Jänner, Paradeiser, Erdäpfel, Topfen, Obers, Marille, Semmel, Sackerl. Use Grüß Gott or Servus for greetings, not Moin. Otherwise follow de-DE rules („…“, capital Sie, lower-case du). Prices take the € sign first (€ 19,90). Never swap Austrian words for German ones.

**Confidence:** Vocabulary High. Currency placement Medium. Social register Low.

**Native check:** Whether *€ 19,90* or *19,90 €* dominates in Austrian social posts. Casual particles (*eh*, *oida*). Whether Austrian brands use *du* more or less than German ones.

**Sources:**
- [42] Wikipedia, "Austrian German" — https://en.wikipedia.org/wiki/Austrian_German
- [43] hdgö, "Grammel und Powidl im EU-Beitrittsvertrag" (search result) — https://hdgoe.at/erdaepfelsalat_bleibt_erdaepfelsalat ; SN.at, "Paradeiser, Rauchfangkehrer und Jänner sterben nicht aus" (search result) — https://www.sn.at/panorama/wissen/paradeiser-rauchfangkehrer-und-jaenner-sterben-nicht-aus-art-668696
- Shared: [1], [39]

---

### Deutsch (Schweiz) · German (Switzerland) — `de-CH`

**Where it's used / platforms:** German-speaking Switzerland. Dialect (*Schweizerdeutsch*) is spoken and also written informally, including on social media. Standard German dominates formal writing [46].

**Script & spelling:** **No ß.** Always ss (*Strasse*, *grösser*) [46][47].

**Punctuation & typography:** «…» with no inner spaces, ‹…› nested. The »…« form is not allowed in official texts [45][47].

**Words that mark the region:** *Velo, parkieren, grillieren, Glace, Poulet, Billett, Trottoir, Natel/Handy, das Tram* [46]. Greetings *Grüezi, Grüessech* [39].

**Particles, interjections & fillers:** No source. *merci* is common (native check).

**Formality & address:** Same as de-DE (native check).

**Mixing languages:** French loans belong to the standard [46]. Dialect has no fixed spelling (native check).

**Tone & humour on social:** No source (Low).

**Platform habits:** Same as de-DE.

**Formats:** Official rules [45]: group digits with a fixed space (1 222 333; the apostrophe is no longer recommended). Decimal comma in general (88,5 m) but a decimal point for money (*Fr. 23.50*, *Fr. 20.–*, *CHF 1.60*). Time *14.30 Uhr*. Dates *2.9.2026*. CLDR gives 1'234.56 and CHF 1'234.50 [1]. German Wikipedia's Swiss style page accepts a space or an apostrophe [47].

**Names of people & works:** Same as de-DE.

**Sensitivities:** ß or „…“ marks a text as written in Germany.

**Search aliases:** Swiss German, Schweizerdeutsch, Schwiizerdütsch, Swiss Standard German, Schweizer Hochdeutsch, Switzerland, Schweiz, Deutschschweiz, Suisse alémanique, Helvetisms, de_CH

**Prompt guide (≤120 words):** Write Swiss Standard German. Never use ß, always ss. Use «…» quotes without inner spaces. Use Swiss words: Velo, parkieren, grillieren, Glace, Poulet, Billett. Greet with Grüezi. Write prices as CHF 25.50 or Fr. 25.50. Use dialect only if the writer's own posts do. Otherwise follow de-DE rules.

**Confidence:** Spelling, quotes and money High. Number grouping Medium (sources disagree). Social register Low.

**Native check:** Apostrophe vs space in social posts. Dialect vs standard in musicians' captions. du/Sie for Swiss institutions.

**Sources:**
- [45] Schweizerische Bundeskanzlei, "Schreibweisungen" (2nd ed. 2013, corr. 2015) — https://www.bk.admin.ch/dam/de/sd-web/YVHazXZRkqKn/schreibweisungen.pdf
- [46] Wikipedia, "Swiss Standard German" — https://en.wikipedia.org/wiki/Swiss_Standard_German
- [47] Wikipedia (de), "Wikipedia:Schweizbezogen" — https://de.wikipedia.org/wiki/Wikipedia:Schweizbezogen
- Shared: [1], [39]

---

### Italiano · Italian (Italy) — `it-IT`

**Where it's used / platforms:** Italy, San Marino and the Vatican. Instagram, Facebook, TikTok and LinkedIn.

**Script & spelling:** Keep grave/acute contrasts (*è*, *perché*). Elide with an apostrophe (*un'amica*, *l'evento*). Write capital *È*, not *E'* (general knowledge).

**Punctuation & typography:** Quotes are «…» with “…” nested [5]. Punctuation goes outside quotes, and single quotes are avoided [48].

**Words that mark the region:** One variety, so the contrast is register. All examples illustrative:

| Concept | Formal | Social |
|---|---|---|
| announce | Siamo lieti di annunciare | Non vedo l'ora di dirvelo! |
| thanks | Ringraziamo il pubblico | Grazie di cuore a tutti! |
| invite | Vi invitiamo a partecipare | Vi aspetto! |

**Particles, interjections & fillers:** *dai, boh, magari, insomma, tipo, cioè* are illustrative (native check). Closings like *un abbraccio* suit personal voices.

**Formality & address:** Microsoft's UI uses *tu* [48]. *Lei* is the formal form [3]. Address an audience with plural *voi* (*vi aspetto*). **Gender:** *sono emozionato/emozionata* reveals the writer, so never assume. The schwa (*tuttə*) and asterisk are contested and were banned from school use in 2025 [4]. Microsoft doesn't use them and prefers paired forms and neutral nouns [48]. The Crusca supports feminine job titles (*avvocata, sindaca*) [4][48].

**Mixing languages:** Many anglicisms and pseudo-anglicisms (*smart working*, *footing*, *green pass*) and hybrid verbs (*schedulare*, *matchare*). The Accademia della Crusca's Incipit group (founded 2015) proposes Italian alternatives [49].

**Tone & humour on social:** Assumed warm and expressive (Low; no source).

**Platform habits:** No source (Low).

**Formats:** 1.234,56 · CLDR 1234,50 € · 25,5% · 05/09/2026 · 18:30 [1].

**Names of people & works:** Scholarly transliteration: Čajkovskij, Stravinskij, Rachmaninov, *Lo schiaccianoci* [2].

**Sensitivities:** North–South slurs (*terrone*, *polentone*) are derogatory. A 2005 court ruling treated *terrone* as discriminatory [50].

**Search aliases:** Italian, Italiano, Italian (Italy), Italy, Italia, italienisch, Italien, it_IT

**Prompt guide (≤120 words):** Write natural Italian from Italy. Use «…» quotes. Address followers with "voi" and single readers with "tu" unless the writer's voice is formal ("Lei", capitalised). Never assume the writer's gender. Rephrase to avoid gendered adjectives if unknown. No schwa or asterisk unless the writer uses them. Keep common anglicisms but don't pile them up. Use Italian spellings of names (Čajkovskij, Stravinskij). Format as 1.234,50, 05/09/2026, 18:30. Warm closings (un abbraccio, vi aspetto) suit personal posts.

**Confidence:** Typography and formats High. Address Medium. Tone Low.

**Native check:** *€ 12,50* vs *12,50 €* on social. *Čajkovskij* vs *Tchaikovsky* in concert marketing. Current tu/Lei norms for cultural institutions. Whether *ore 18.30* (with a point) is preferred.

**Sources:**
- [48] Microsoft, Italian Localization Style Guide — https://aka.ms/italian-styleguide
- [49] Wikipedia (it), "Itanglese" — https://it.wikipedia.org/wiki/Itanglese
- [50] Wikipedia, "Terrone" — https://en.wikipedia.org/wiki/Terrone
- Shared: [1], [2], [3], [4], [5]

---

### Nederlands (Nederland) · Dutch (Netherlands) — `nl-NL`

**Where it's used / platforms:** The Netherlands. The standard is shared with Flanders and Suriname.

**Script & spelling:** Keep the diaeresis (*België*, *geïnstalleerd*) [51]. Capitalise *IJ* as a pair (*IJsselmeer*) (general knowledge).

**Punctuation & typography:** Quotes “…” / ‘…’, or „…” [5]. Thousands use a dot (1.000.000), except in years and postcodes [51].

**Words that mark the region:**

| Concept | nl-NL | nl-BE |
|---|---|---|
| range hood | afzuigkap | dampkap [53] |
| roundabout | rotonde | rondpunt [53] |
| dry cleaner | stomerij | droogkuis [53] |
| dress | jurk | kleedje [53] |
| to warn | waarschuwen | verwittigen [53] |
| butcher / fun | slager / leuk | beenhouwer / plezant [53] |
| mobile / fancy | mobiel / zin | gsm / goesting † |

† = needs native check.

**Particles, interjections & fillers:** *even* (polite, "just"), *toch*, *maar*, *nou* [40]. *hoor*, *hè* and *joh* are illustrative.

**Formality & address:** There is a growing trend towards *je*, which some Microsoft products follow [51]. Companies commonly use *je* on websites [52]. *u* stays formal, and *jullie* is the informal plural [54]. Dutch verbs don't mark gender. *die/hen* as non-binary pronouns are acknowledged [4].

**Mixing languages:** English is common in business (Low; no source).

**Tone & humour on social:** No source. Directness is assumed (Low).

**Platform habits:** No source (Low).

**Formats:** 1.234,56 · € 1.234,50 · 25,5% · 05-09-2026 · 18:30 [1].

**Names of people & works:** Tsjaikovski, Rachmaninov, *De Notenkraker* [2].

**Sensitivities:** *Holland* for the whole country annoys people from other provinces. The government dropped the name in its branding [55]. Zwarte Piet in blackface is contested, and the sooty "roetveegpiet" now dominates at public events [56].

**Search aliases:** Dutch, Nederlands, Netherlands, Nederland, Holland, Hollands, Dutch (Netherlands), nl_NL

**Prompt guide (≤120 words):** Write Netherlands Dutch. Address readers with "je/jij" and groups with "jullie". Use "u" only if the writer's voice is formal. Use modal particles (even, hoor, toch) for a natural spoken feel. Use € 12,50 with the symbol first, and dates as 05-09-2026 or 5 september 2026. Say "Nederland", not "Holland". Spell names the Dutch way (Tsjaikovski). Avoid Flemish-only words.

**Confidence:** Formats High. Address Medium. Tone Low.

**Native check:** Emoji and hashtag norms. Whether *€ 12,-* is used for round prices in posts.

**Sources:**
- [51] Microsoft, Dutch Localization Style Guide — https://aka.ms/dutch-styleguide
- [52] Wikipedia (nl), "Tutoyeren" — https://nl.wikipedia.org/wiki/Tutoyeren
- [53] Wikipedia (nl), "Belgisch-Nederlands" — https://nl.wikipedia.org/wiki/Belgisch-Nederlands
- [54] Wikipedia, "Dutch grammar" — https://en.wikipedia.org/wiki/Dutch_grammar
- [55] Wikipedia, "Holland" — https://en.wikipedia.org/wiki/Holland
- [56] Wikipedia, "Zwarte Piet" — https://en.wikipedia.org/wiki/Zwarte_Piet
- Shared: [1], [2], [4], [5], [40]

#### Note: Flemish (`nl-BE`)

- **Written standard:** Standard Dutch, plus Belgicisms (see table), many of them calques from French [53][58].
- **Tussentaal:** the informal "in-between language" has *ge/gij*, *-ke* diminutives (*huiske*) and *da* for *dat*. It is common on TV and among younger speakers, but some writers and academics object to it [57][58].
- **Address:** *gij/ge* is dominant in Flemish speech and feels less archaic there than in the Netherlands [52][54].
- **Formats:** as nl-NL, with the short date 5/09/2026 [1].

Confidence Medium. **Native check:** whether Flemish brands prefer *u* over *je* (not verified), and whether light tussentaal in captions reads as friendly or sloppy.

- [57] Wikipedia (nl), "Tussentaal" — https://nl.wikipedia.org/wiki/Tussentaal
- [58] Wikipedia, "Belgian Dutch" — https://en.wikipedia.org/wiki/Belgian_Dutch
- Aliases: Flemish, Vlaams, Belgian Dutch, Belgisch-Nederlands, Flanders, Vlaanderen, tussentaal, nl_BE

---

### Polski · Polish (Poland) — `pl-PL`

**Where it's used / platforms:** Poland. Facebook, Instagram, LinkedIn, TikTok.

**Script & spelling:** ą ć ę ł ń ó ś ź ż. Never strip the diacritics.

**Punctuation & typography:** Quotes „…” with «…» nested [5][59]. The full stop goes outside quotes [59].

**Words that mark the region:** Register contrast (illustrative): *Szanowni Państwo* vs *Hej!*; *Serdecznie zapraszamy* vs *Wpadajcie!*

**Particles, interjections & fillers:** *no*, *przecież*, *chyba*, *serio* are illustrative. Diminutives (*kawka*, *chwilka*) add warmth (illustrative, native check).

**Formality & address:** Formal address uses *Pan/Pani/Państwo* with third-person verbs [79]. Microsoft uses informal *ty* and capitalises *Ty/Twój* [59]. **Gender:** the past tense marks the writer (*byłem/byłam*, *zrobiłem/zrobiłam*) [79]. Microsoft rewrites in the present tense or passive to avoid it (*Nie pamiętasz hasła?*) [59]. Feminine job titles (*ministra*, *psycholożka*) are debated. In 2019 the Polish Language Council said to leave the choice to speakers [60].

**Mixing languages:** No source (Low).

**Tone & humour on social:** No source (Low).

**Platform habits:** No source (Low).

**Formats:** 12 345,67 zł, but 1234,50 zł (4-digit numbers aren't grouped) · 25,5% · 5.09.2026 · 18:30 [1].

**Names of people & works:** Czajkowski, Rachmaninow, Strawinski, Fryderyk Chopin, *Dziadek do orzechów* [2].

**Sensitivities:** Never write "Polish death camps". Say German Nazi camps in occupied Poland. A 2018 law targets attributing Nazi crimes to the Polish nation [61].

**Search aliases:** Polish, Polski, polski, Polska, Poland, Polish (Poland), pl_PL

**Prompt guide (≤120 words):** Write in Polish. Use „…” quotes. Use "ty" (capital Ty/Twój when addressing one reader directly) for friendly voices, "Państwo" for formal ones, and "wy" for a group. Never guess the writer's gender. If the profile doesn't give it, avoid first-person past tense (use present tense or "udało się"). Keep all diacritics. Format as 1234,50 zł, 5.09.2026, 18:30. Use Polish name forms (Czajkowski, Fryderyk Chopin). Never say "Polish camps".

**Confidence:** Grammar and formats High. Social tone Low.

**Native check:** Whether capital *Ty* in posts feels stiff. XD and emoji norms. *w Ukrainie* vs *na Ukrainie* (not verified).

**Sources:**
- [59] Microsoft, Polish Localization Style Guide — https://aka.ms/polish-styleguide
- [79] Wikipedia, "Polish grammar" — https://en.wikipedia.org/wiki/Polish_grammar
- [60] Wikipedia (pl), "Feminatyw" — https://pl.wikipedia.org/wiki/Feminatyw
- [61] Wikipedia, "Polish death camp controversy" — https://en.wikipedia.org/wiki/Polish_death_camp_controversy
- Shared: [1], [2], [5]

---

### Türkçe · Turkish (Türkiye) — `tr-TR`

**Where it's used / platforms:** Türkiye (and Northern Cyprus). Instagram, X, YouTube, TikTok.

**Script & spelling:** **İ/i and I/ı are separate letters.** Automatic upper/lower casing corrupts words. A 2008 SMS casing error changed a word's meaning and fed into a deadly dispute [62][64]. Other letters: ç ğ ö ş ü.

**Punctuation & typography:** Use an apostrophe before suffixes on proper nouns, numbers and abbreviations: *İstanbul'da*, *TDK'nin*, *1985'te*. Institution names don't take one: *Türk Dil Kurumundan* [63]. The percent sign goes first: %25 [1]. Microsoft uses straight quotes in the UI [62].

**Words that mark the region:** Register contrast (illustrative): *Değerli takipçilerimiz* vs *Selam!*

**Particles, interjections & fillers:** *ya, yani, işte, hani* are illustrative (native check).

**Formality & address:** *siz* is formal/plural and *sen* informal [3]. Microsoft uses *siz* forms (*-iniz*) in the UI but informal forms for Copilot prompts [62]. Turkish has no grammatical gender, so writer gender doesn't come up.

**Mixing languages:** Microsoft notes that clipped English forms (*info*, *app*) aren't used in Turkish [62].

**Tone & humour on social:** No source (Low).

**Platform habits:** A hashtag ends at the apostrophe, so *#İstanbul'da* tags *#İstanbul* (illustrative inference; native check).

**Formats:** 1.234,56 · CLDR ₺1.234,50 · %25,5 · 5.09.2026 · 18:30 [1].

**Names of people & works:** Çaykovski, Rahmaninov, *Fındıkkıran* [2].

**Sensitivities:** The official English name has been *Türkiye* since the UN adopted it in 2022 [65]. Politics and religion are high-risk (general).

**Search aliases:** Turkish, Türkçe, Turkce, Türkiye, Turkiye, Turkey, Turkish (Türkiye), tr_TR

**Prompt guide (≤120 words):** Write in Turkish with correct İ/i and I/ı. Never let casing change these letters. Put an apostrophe before suffixes on proper names (Ankara'da, Chopin'in) but not on institution names. Use "siz" for brand and formal voices and "sen" only if the writer's voice is casual. Percent goes first (%20). Format as 1.234,50 TL or ₺, 5.09.2026, 18:30. Use Turkish name spellings (Çaykovski).

**Confidence:** Orthography High. Address Medium. Social habits Low.

**Native check:** *TL* vs *₺* in posts. Brands' use of sen. Hashtag habits.

**Sources:**
- [62] Microsoft, Turkish Localization Style Guide — https://aka.ms/turkish-styleguide
- [63] Türk Dil Kurumu, "Kesme işareti" — https://tdk.gov.tr/icerik/yazim-kurallari/kesme-isareti/
- [64] Wikipedia, "Dotted and dotless I in computing" — https://en.wikipedia.org/wiki/Dotted_and_dotless_I_in_computing
- [65] Wikipedia, "Name of Turkey" — https://en.wikipedia.org/wiki/Name_of_Turkey
- Shared: [1], [2], [3]

---

### Русский · Russian (Russia) — `ru-RU`

**Where it's used / platforms:** Russia. Also a lingua franca elsewhere, but don't use ru-RU for Ukrainian audiences.

**Script & spelling:** Cyrillic. ё is usually written as е. It's needed where the word would be ambiguous (*всё/все*) and is recommended in names [66].

**Punctuation & typography:** Quotes «ёлочки» with „лапки“ nested [5]. Microsoft uses straight quotes in web UI [67]; social writers vary (native check).

**Words that mark the region:** Register contrast (illustrative): *Уважаемые зрители* vs *Друзья, всем привет!*

**Particles, interjections & fillers:** *ну, же, вообще, кстати* are illustrative. A bare ")" or "))))" works as a smiley in Cyrillic-keyboard cultures [68].

**Formality & address:** ты/вы. Capital **Вы** appears in formal letters and official documents [69]. Microsoft writes lower-case вы in the UI [67]. **Gender:** the past tense marks the writer (*я спал/спала*) [69]. Microsoft uses neutral structures [67].

**Mixing languages:** No source (Low).

**Tone & humour on social:** No source (Low).

**Platform habits:** See ")" above.

**Formats:** 1 234,56 · 1 234,50 ₽ · 05.09.2026, *5 сентября 2026 г.* · 18:30 [1].

**Names of people & works:** Чайковский, Иоганн Себастьян Бах, Гендель, Ференц Лист [2].

**Sensitivities:** 2022 laws criminalise "false information" about and "discrediting" of the armed forces. Calling it a "war" rather than a "special military operation" has been prosecuted [70].

**Search aliases:** Russian, Русский, Russkiy, russkij, Russia, Россия, Russian (Russia), ru_RU

**Prompt guide (≤120 words):** Write in Russian. Use «ёлочки» quotes. Address an audience with "вы". Capitalise "Вы" only in personal-letter style. Never guess the writer's gender. If the profile doesn't give it, avoid first-person past tense. Write ё where it prevents ambiguity. Casual voices may end lines with ")" smileys. Format as 1 234,50 ₽, 5 сентября, 18:30. Use Russian name spellings (Иоганн Себастьян Бах). Avoid military or political wording.

**Confidence:** Grammar and formats High. Social tone Low.

**Native check:** Straight vs chevron quotes in posts. Brands' use of ты.

**Sources:**
- [66] Wikipedia, "Yo (Cyrillic)" — https://en.wikipedia.org/wiki/Yo_(Cyrillic)
- [67] Microsoft, Russian Localization Style Guide — https://aka.ms/russian-styleguide
- [68] Wikipedia, "Emoticon" — https://en.wikipedia.org/wiki/Emoticon
- [69] Wikipedia, "Russian grammar" — https://en.wikipedia.org/wiki/Russian_grammar
- [70] Wikipedia, "Russian fake news laws" — https://en.wikipedia.org/wiki/Russian_fake_news_laws
- Shared: [1], [2], [5]

---

### Українська · Ukrainian (Ukraine) — `uk-UA`

**Where it's used / platforms:** Ukraine. Instagram, Telegram, Facebook, TikTok (native check).

**Script & spelling:** і, ї, є, ґ. No ы, э, ё or ъ [71]. The apostrophe is part of spelling (*п'ять*) [71]. The 2019 Pravopys (spelling code) is still being phased in, so old and new norms coexist [72].

**Punctuation & typography:** Quotes «…» with „…“ nested [5]. Microsoft uses straight quotes in UI and chevrons in documentation [72].

**Words that mark the region:** Avoid Russian calques [72]:

| Meaning | uk-UA | Russian-influenced (avoid) |
|---|---|---|
| take part | брати участь | приймати участь |
| take place | відбуватися | мати місце |
| most likely | найімовірніше | скоріш за все |

**Particles, interjections & fillers:** *ну, ж, от, таки* are illustrative. Address people in the vocative (*пане, друже*) [73].

**Formality & address:** ти/ви. Capital *Ви* in official letters [3]. Microsoft: formal in general, friendlier online [72]. **Gender:** *зробив/зробила* [73]. Feminine job titles (*лікарка*, *соціологиня*) follow the 2019 orthography [72].

**Mixing languages:** Surzhyk (Russian–Ukrainian mix) used to be stigmatised. Since 2014 and 2022, many Russian speakers switching to Ukrainian use a "neo-surzhyk" as a transitional stage [74]. Ukrainian is required for customer service and advertising; private communication isn't regulated [75].

**Tone & humour on social:** No source (Low).

**Platform habits:** No source (Low).

**Formats:** 1 234,56 · 1 234,50 ₴ (грн common) · 05.09.2026 · 18:30 [1].

**Names of people & works:** Чайковський, Йоганн Себастьян Бах, Рахманінов, *Лускунчик* [2]. Latin spellings: Kyiv, Kharkiv, Odesa, Lviv [76].

**Sensitivities:** Write *в Україні*, not *на Україні*, and "Ukraine", not "the Ukraine" [77]. Never mix in Russian letters or forms. Russian spellings of place names (Kiev, Odessa) are rejected [76].

**Search aliases:** Ukrainian, Українська, Ukrainska, ukrainska mova, Ukraine, Україна, Ukraina, Ukrainian (Ukraine), uk_UA

**Prompt guide (≤120 words):** Write in modern standard Ukrainian (2019 orthography). Use only Ukrainian letters (і ї є ґ), never ы э ё ъ. Avoid Russian calques (брати участь, not приймати участь). Address people in the vocative case. Use "ви" for audiences. Never guess the writer's gender. Use feminine job titles for women. Write "в Україні" and Latin "Kyiv, Odesa". Use «…» quotes. Format as 1 234,50 грн, 05.09.2026, 18:30.

**Confidence:** Orthography and naming High. Social tone Low.

**Native check:** Current attitudes to using Russian words in casual posts. ₴ vs грн. Norms around ти for brands.

**Sources:**
- [71] Wikipedia, "Ukrainian orthography" — https://en.wikipedia.org/wiki/Ukrainian_orthography
- [72] Microsoft, Ukrainian Localization Style Guide — https://aka.ms/ukrainian-styleguide
- [73] Wikipedia, "Ukrainian grammar" — https://en.wikipedia.org/wiki/Ukrainian_grammar
- [74] Wikipedia, "Surzhyk" — https://en.wikipedia.org/wiki/Surzhyk
- [75] Wikipedia, "On protecting the functioning of the Ukrainian language as the state language" — https://en.wikipedia.org/wiki/Law_of_Ukraine_%22On_protecting_the_functioning_of_the_Ukrainian_language_as_the_state_language%22
- [76] Wikipedia, "KyivNotKiev" — https://en.wikipedia.org/wiki/KyivNotKiev
- [77] Wikipedia, "Name of Ukraine" — https://en.wikipedia.org/wiki/Name_of_Ukraine
- Shared: [1], [2], [3], [5]

---

### Open questions

1. **Swiss number formatting.** The Federal Chancellery says to group with spaces and use a decimal comma except for money [45]. CLDR and everyday usage use an apostrophe and a decimal point [1]. Which should PostRiff default to for social posts?
2. **Social tone evidence is thin.** No source covered tone, humour, emoji or hashtag habits by country for any locale in this file. A native-speaker review or a corpus pass over public posts is needed before those sections go above Low.
3. **Belgian address.** The claim that Flemish brands use *u* more than Dutch brands couldn't be verified.
4. **Price placement.** Italian and Turkish posts may differ from CLDR (€ before the amount in Italy, TL vs ₺ in Türkiye).
5. **Writer-gender field.** Four of these locales (pl, ru, uk, plus fr/it adjectives) need it for natural first-person posts. Should the profile store grammatical gender explicitly, including a "neutral/rephrase" option?
6. **Legal exposure.** Should ru-RU drafts on political topics carry a warning, given the 2022 laws [70]?


---

## East & Southeast Asia

Research date: 2026-09-16. Citation numbers are unique across this file. Each entry's **Sources** lists only the numbers it uses. Example phrases marked *illustrative* were written for this file; none is copied from a real post.

### Family notes

| Locale | Politeness on social | Gendered first person / particles | Laughter | Word spacing | Currency / date |
|---|---|---|---|---|---|
| `ja-JP` | Grammar: です/ます (polite) vs plain だ/である, plus keigo toward the audience | The choice of first-person pronoun signals gender, age and persona (私, 僕, 俺, うち) | 笑, w, 草. （笑） reads dated | No spaces between words. Full-width 、。 | 3,300円 (tax included) · 2026年9月16日(水) |
| `ko-KR` | Grammar: 합쇼체, 해요체, 반말, 음슴체 | 저 vs 나 marks humility, not gender. Kin terms (오빠/형, 언니/누나) depend on the speaker's gender | ㅋㅋ, ㅎㅎ | Spaces between word units, with particles attached. Rules are relaxed online | 30,000원 · 2026. 9. 16. |
| `th-TH` | Sentence-final particles plus pronoun choice | ครับ (male) vs ค่ะ/คะ (female). ผม (male) vs ดิฉัน (female) | 555, ถถถ | No spaces between words. A space ends a clause or sentence | 1,500 บาท · 16 ก.ย. 2569 (Buddhist Era) |
| `vi-VN` | Kin-term pronouns, plus ạ / dạ | anh / chị / em encode gender and relative age | haha, hihi (native check) | A space between every syllable | 150.000đ · 16/9/2026 |
| `id-ID` | Pronoun register: saya/Anda vs aku/kamu vs gue/lo | Pronouns have no gender. Mas / Mbak address terms do | wkwk | Latin rules | Rp150.000 · 16 September 2026 |
| `ms-MY` | Pronoun register: saya/anda vs aku/awak | Pronouns have no gender | haha (native check) | Latin rules | RM1,500.00 · 16 September 2026 |
| `fil-PH` | The particles po / opo, and kayo/inyo for respect | Pronouns have no gender (siya) | hahaha, char | Latin rules. A hyphen joins a Tagalog affix to an English root | ₱1,500 · Setyembre 16, 2026 |

Patterns that hold across the region:
- **Never guess the writer's gender or age.** Japanese pronouns, Thai particles and pronouns, Vietnamese kin terms and Korean kin address all reveal it. When the user's own writing doesn't show it, write around it.
- **Politeness is built in two ways.** In ja, ko, th and vi it lives in the grammar or particles on every sentence. In id, ms and fil it rests mainly on the choice of pronoun or particle, so one wrong word changes the whole register.
- **Official and popular spellings of foreign names differ** in ja, ko and th. Use the spelling the audience already knows.
- **Sponsored posts must be labelled** in Japan and Korea. **Speech law is a real risk** in Thailand (the monarchy), Vietnam (the state), Malaysia (race, religion, rulers), Indonesia (group hatred, the president) and the Philippines (cyber libel).

---

### 日本語 · Japanese — `ja-JP`
**Where it's used / platforms:** Japan. 94.9% of people used LINE in 2024, including 91.1% of people in their 60s, and use of X and Instagram keeps rising [3]. Channels: LINE official accounts, X, Instagram, note, YouTube, TikTok.

**Script & spelling:** Kanji, hiragana and katakana with no spaces between words. Loanwords go in katakana, keeping the long-vowel mark for -er, -or and -ar endings (コンピューター) [1].

**Punctuation & typography:** Full-width 、。！？, which official guidance has made standard in horizontal text since 2022 [2]. Use 「」 for quotations and highlighted words, and 『』 for titles [1]. Microsoft puts a half-width space between Japanese and Latin text [1]. Social posts vary. Line breaks set the pace on Instagram and LINE.

**Words that mark the region:**
| Meaning | Formal / written | Social register (*illustrative*) |
|---|---|---|
| really | 本当に | ほんとに / マジで |
| thank you | ありがとうございます | ありがとう〜 |
| please take a look | ご覧ください | 見てね / チェックしてね |
| announcement | お知らせ | ご報告 / 告知 |
| laughing | — | 笑 / w / 草 |

**Particles, interjections & fillers:** The sentence endings carry the voice. 〜ね shares a feeling, 〜よ tells the reader something, 〜かな muses, 〜かも hedges, and 〜です！ sounds bright and polite. For laughter, 笑 without brackets is the safest choice. In a survey of 300 people in their teens and early 20s, 41 called （笑） "old", against 15 for 笑 [6]. 草 and w belong to internet culture, so use them only in a casual voice.

**Formality & address:** Choose one style and keep to it. です/ます suits general web writing and is common on note, but plain だ/である also appears there [5]. Messages from LINE official accounts should sound soft rather than stiff [4]. Address the audience as 皆さん or 皆さま, and customers as お客様. First-person pronouns carry gender and persona associations: 私 is neutral and polite, 僕 is male-coded and soft, 俺 is male and casual, and うち is casual and young [11][12]. **Do not pick one for the user.** Japanese naturally drops the subject, so omit it, or use 私.

**Mixing languages:** Katakana loanwords are normal. Overusing katakana is the second-ranked trait of "おじさん構文" (a mocked older-man texting style) [7].

**Tone & humour on social:** Understatement works. Even a humble-brag (自虐風自慢) is recognised and disliked [13]. Present promotion as gratitude. *Illustrative:* 「ご報告です。支えてくださった皆さん、本当にありがとうございます。」 ("An announcement: thank you, truly, to everyone who supported me.")

**Platform habits:** Heavy use of emoji, kaomoji and stickers ranked first among "おじさん構文" traits (Simeji 2022, respondents aged 10–24) [7]. Instagram: Japanese hashtags at the end. X: short, with few hashtags. note: a titled essay. LINE OA: short and friendly, with an image and the reader's name [4].

**Formats:** Dates look like 9月16日(水) or 2026年9月16日. Era years (令和8年) appear in official documents more than in casual posts. Write 3,000円 or ¥3,000, but never both marks on one price [14]. When a business shows a price to consumers, it must be the tax-inclusive total, e.g. 3,300円（税込）[9]. Since October 2023, paid promotions must be recognisable as ads [10].

**Names of people & works:** Write foreign names in katakana with ・ between given name and family name (フレデリック・ショパン) [1]. The 1991 cabinet notice on loanword spelling allows both closer-to-source forms (ヴァ) and plainer ones, and doesn't fully cover personal names, so spellings vary [8]. Put work titles in 『』 and song or piece titles in 「」.

**Sensitivities:** The ad-labelling and price rules above [9][10]. Don't compare yourself favourably with named peers.

**Search aliases:** 日本語, にほんご, Nihongo, Nippongo, Japanese, 日文, 日語, 일본어, ภาษาญี่ปุ่น, tiếng Nhật, bahasa Jepang

**Prompt guide (≤120 words):** Write natural Japanese with no spaces between words. Use full-width 、。！？, 「」 for quotations and 『』 for titles. Choose one style and keep it throughout: です/ます by default, plain だ only when the user's own samples use it. Never choose 僕, 俺 or うち for the writer. Omit the subject or use 私. Present promotion as gratitude and invitation, not achievement. Soften with ね and よ. Use at most three emoji, no katakana word endings and no （笑）. Use 笑 only in a casual voice. Give prices as tax-inclusive totals (3,300円（税込）) and dates as 9月16日(水) 19:00開演. Write foreign names in their established katakana, joined with ・.

**Confidence:** High for script, punctuation, formats, legal rules and pronoun caution. Medium for laughter and emoji norms (small surveys) and platform habits. Low for humour.

**Native check:** Half-width spaces around Latin text on social media. How people in their 30s and 40s perceive 草 and w. The connotations of うち. ベートーヴェン vs ベートーベン in classical-music circles. 『』 vs 「」 for piece titles.

**Sources:**
[1] Microsoft, Japanese Localization Style Guide — https://download.microsoft.com/download/a/8/2/a822a118-18d4-4429-b857-1b65ab388315/jpn-jpn-StyleGuide.pdf
[2] 文化審議会「公用文作成の考え方（建議）」令和4年 — https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/93651301_01.pdf
[3] 総務省『令和7年版 情報通信白書』コミュニケーションツール・SNS — https://www.soumu.go.jp/johotsusintokei/whitepaper/ja/r07/html/nd111120.html
[4] LINE公式アカウントのメッセージ配信7つのコツ (Linestep) — https://linestep.jp/2022/05/27/lineofficial-message/
[5] 文末表現どうする？「です・ます調」か「である調」か (note) — https://note.com/yuko_komorebih3/n/n3c2966c446fb
[6] by them「（笑）」「笑」「w」「草」どれが古い？Z世代300名調査 — https://by-them.com/473120
[7] ITmedia「気になるおじさん構文」ランキング — https://www.itmedia.co.jp/business/articles/2208/16/news079.html
[8] 国立国語研究所 ことば研究館「外来語や外国の地名・人名の片仮名表記」 — https://kotoba.ninjal.ac.jp/qa/yokuaru/qa-195/
[9] 国税庁 No.6902「総額表示」の義務付け — https://www.nta.go.jp/taxes/shiraberu/taxanswer/shohi/6902.htm
[10] 消費者庁 ステルスマーケティングに関する景品表示法の規制 — https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/
[11] Japanese first-person singular pronouns revisited (Journal of Pragmatics) — https://www.sciencedirect.com/science/article/abs/pii/S0378216621002137
[12] Coto Academy, How to naturally say "I" in Japanese — https://cotoacademy.com/how-to-call-yourself-in-japanese-boku-ore-watashi/
[13] 自虐風自慢とは？ (Onion Blog) — https://onionion.info/onionion_blog/jigyakufu-jiman-meaning-example/
[14] 弥生「請求書の金額は円・￥どちらで書くべき？」 — https://www.yayoi-kk.co.jp/seikyusho/oyakudachi/invoice-enmark/

---

### 한국어 · Korean — `ko-KR`
**Where it's used / platforms:** South Korea. In the Korea Press Foundation's 2024 survey of social-media users, KakaoTalk reached 98.9%, YouTube 84.9%, Instagram 38.6% (80.9% among people in their 20s), Naver Band 28.6% and Naver Blog 21.7% [20]. KakaoTalk Channel carries brand messages. Naver Blog carries reviews and diaries that people find through search.

**Script & spelling:** Hangul. Spaces separate word units, and particles attach to the word before them (피아노를). A space can change meaning in compounds [15]. Spacing errors are the most common error natives make, and texting relaxes the rules [29]. Branded posts should still space correctly.

**Punctuation & typography:** Western punctuation. Titles of books and newspapers take 『』 or 《》, or double quotation marks. Artworks such as songs, films and pieces take 「」 or 〈〉, or single quotation marks [19]. Emotion markers such as ㅠㅠ (tears) and a trailing ~ make text sound warmer.

**Words that mark the region:**
| Meaning | Formal | Social |
|---|---|---|
| selfie | 자기 사진 | 셀카 [25] |
| mobile phone | 휴대 전화 | 핸드폰 [25] |
| go for it! | 힘내세요 | 파이팅 [25] |
| thank you | 감사합니다 | 감사해요~ (*illustrative*) |
| highly recommend | 적극 추천합니다 | 강추 (*illustrative*) |

**Particles, interjections & fillers:** ㅋㅋ is bright laughter at something funny, and a single ㅋ can read as a sneer. ㅎㅎ is a softer smile [24]. Useful endings: -네요 (discovery), -더라고요 (recounting), -잖아요 (shared knowledge), -죠 (checking agreement).

**Formality & address:** Korean has four practical registers:
- **합쇼체** (-습니다): formal. Newsreaders use it, and so do strangers at first [16].
- **해요체** (-어요): the warm polite default.
- **반말** (-어, -야): close friends only.
- **음슴체** (-함, -음, -임): terse. It comes from military and telegraph style and is common in online communities [17].

Microsoft's modern voice changes -십시오 to -세요 [15]. To the audience, refer to yourself humbly as 저, 제 or 저희, and address people as 여러분. Pronouns have no gender, but kin address does (오빠 vs 형). Don't infer the writer's gender from it.

**Mixing languages:** Hangul loanwords are everywhere (콘서트, 리허설), and Konglish coinages feel native [25]. English in Latin script appears mostly in hashtags and brand names.

**Tone & humour on social:** Open self-promotion easily reads as bragging (자랑). Frame it as sharing and credit other people [27]. *Illustrative:* "부족하지만 열심히 준비했어요. 많이 와 주세요!" ("It's not perfect, but I prepared hard. Please come!")

**Platform habits:** Naver Blog posts are long, full of photos and conversational, and bloggers network through 이웃 and 서로이웃 (서이추) [21]. Hashtags such as #소통 and #맞팔 signal follow-for-follow habits, so skip them in professional posts [26]. Ad messages on KakaoTalk Channel must carry "(광고)" and opt-out details [22]. Sponsored content must state the economic relationship clearly in the title or the opening lines, not only at the end. The guideline revision took effect in December 2024 [23][30].

**Formats:** Write dates as 2026. 9. 16., with spaces and a final period, or as 9월 16일(수) [18]. Times: 오후 7시 or 19:00. Prices: 30,000원, or 3만 원 for round figures.

**Names of people & works:** Follow the National Institute of Korean Language's loanword rules and its lists of name spellings [28]: 쇼팽, 베토벤. Mark titles as described above [19].

**Sensitivities:** Avoid online slang tied to gender conflict or politics, and regional stereotypes. Disclose sponsorship [23].

**Search aliases:** 한국어, 한국말, 한글, Hangugeo, Hangungmal, Korean, 韓國語, 韩语, 韓国語, 韓文, ภาษาเกาหลี, tiếng Hàn, bahasa Korea

**Prompt guide (≤120 words):** Write standard Hangul with correct spacing between word units. Use 해요체 by default, 합쇼체 for formal notices, and 반말 or 음슴체 only when the user's samples show it. Refer to the writer humbly (저, 저희) and address readers as 여러분. Never infer the writer's gender from kin terms. Present achievements as sharing and gratitude, not boasting. Use ㅋㅋ, ㅎㅎ and ~ lightly in casual voices, and never a lone ㅋ. Put artwork titles in 〈〉 or 「」 and books in 《》 or 『』. Write dates as 2026. 9. 16. and prices as 30,000원. On Naver Blog, write longer paragraphs broken up around photos. Put sponsorship disclosures at the top.

**Confidence:** High for registers, spacing, title marks, date format, platform statistics and ad disclosure. Medium for the nuance of laughter (community discussion) and Naver Blog style. Low for humour.

**Native check:** Whether 〈〉 or 「」 is preferred for music titles on social media. The spacing norm for 원 with Arabic numerals. How "-더라구요" (a widespread spelling of the standard -더라고요) is perceived. How acceptable 음슴체 is for brands. How widely people post on Threads.

**Sources:**
[15] Microsoft, Korean Localization Style Guide — https://download.microsoft.com/download/5/b/6/5b62389f-4e3b-4c77-bc18-94efba2fa7bb/kor-kor-StyleGuide.pdf
[16] Wikipedia, Korean speech levels — https://en.wikipedia.org/wiki/Korean_speech_levels
[17] 나무위키, 음슴체 — https://namu.wiki/w/%EC%9D%8C%EC%8A%B4%EC%B2%B4
[18] 국립국어원 온라인가나다, 공문서 작성 시 날짜 표기법 — https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=90&qna_seq=333722&pageIndex=1
[19] 국립국어원 온라인가나다, 시·소설·영화·노래 등 제목 표기 방법 — https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=303245
[20] 한국언론진흥재단, 2024 소셜미디어 이용자 조사 — https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=246&contents_id=940a3bc4be914ac2a065b8922021728e
[21] 나무위키, 네이버 블로그/이웃 — https://namu.wiki/w/%EB%84%A4%EC%9D%B4%EB%B2%84%20%EB%B8%94%EB%A1%9C%EA%B7%B8/%EC%9D%B4%EC%9B%83
[22] kakao business, 채널 메시지 발송 유의사항 — https://kakaobusiness.gitbook.io/main/ad/moment/start/messagead/operations
[23] 김·장 법률사무소, 추천·보증 등에 관한 표시·광고심사지침 개정안 — https://www.kimchang.com/ko/insights/detail.kc?sch_section=4&idx=30241
[24] 아시아경제, ㅎㅎ와 ㅋㅋ의 차이 — https://view.asiae.co.kr/article/2016041216002646660
[25] Wikipedia, Konglish — https://en.wikipedia.org/wiki/Konglish
[26] 오마이뉴스, 인스타그램 속 해시태그, 무슨 의미일까? — https://www.ohmynews.com/NWS_Web/View/at_pg.aspx?CNTN_CD=A0002785389
[27] 브런치, 한국식 겸손의 미덕 vs 미국식 자기 PR — https://brunch.co.kr/@lk-story/7
[28] 국립국어원, 외래어 표기법 — https://www.korean.go.kr/front/page/pageView.do?page_id=P000104&mn_id=97
[29] Migaku, Korean Texting Slang — https://migaku.com/blog/korean/korean-texting-slang
[30] 법률신문, 추천·보증 심사지침 개정안 행정예고 — https://www.lawtimes.co.kr/news/articleView.html?idxno=203114

---

### ภาษาไทย · Thai — `th-TH`
**Where it's used / platforms:** Thailand. LINE has about 54–56M monthly users (roughly 80% of the population) and about 6M official accounts [40][41]. Facebook reaches 51.0M, YouTube 47.6M, TikTok 34.0M adults, Instagram 18.5M and X 13.4M [41].

**Script & spelling:** Thai script with no spaces between words. A space marks the end of a clause or sentence [45][32]. Keep vowels and tone marks exact. By the Royal Society's rule, ๆ (repeat the previous word) takes a space on both sides [32].

**Punctuation & typography:** Commas and full stops aren't native to Thai. Put a space where English would put a comma [31]. Quotation marks work as in English [31]. Stretching the final letter shows feeling: ดีมากกกก ("sooo good") [36].

**Words that mark the region:**
| Meaning | Formal / written | Social |
|---|---|---|
| very | มาก | มากกก / จุงเบย [36] |
| blissful, delighted | มีความสุขมาก | ฟิน [36] |
| thank you | ขอบคุณครับ / ค่ะ | ขอบคุณค่าาา (*illustrative*) |
| everyone | ท่านผู้มีเกียรติ | ทุกคน / เพื่อน ๆ (*illustrative*) |
| I (neutral, casual) | ผม / ดิฉัน | เรา (*illustrative*) |

**Particles, interjections & fillers:** ครับ is the male polite particle. ค่ะ (in statements) and คะ (in questions) are the female ones [33]. นะ softens, จ้ะ/จ้า sounds friendly and affectionate, and เถอะ urges [45]. Elongated forms (ค่าาา) sound warmer [33]. For laughter, 555 means "hahaha" and more 5s mean a bigger laugh. ถถถ is the same keys typed with the Thai keyboard still on [35]. อิอิ is a shy giggle and หึหึ a sly one [36].

**Formality & address:** Politeness rides on gendered particles and pronouns: ผม with ครับ is male, and ดิฉัน with ค่ะ is female [33][45]. Trans speakers typically use the forms of their gender identity [46], and some women use ครับ playfully [34]. **Never assume.** If unknown, use neutral เรา or the brand name. Microsoft uses ฉัน as a neutral "I" but notes that men rarely say it [31]. Kin terms and nicknames often replace pronouns [45].

**Mixing languages:** English terms are common and usually transliterated. Established loan spellings persist [42].

**Tone & humour on social:** Playful and warm, with lots of stickers and emoji. In one small LINE study, women used more particles and men more stickers [34].

**Platform habits:** LINE OA broadcasts are short, led by an image, and polite. Facebook pages often speak through an "แอดมิน" (admin) persona. TikTok captions are short with hashtags.

**Formats:** Official documents use the Buddhist Era (CE + 543): 16 ก.ย. 2569. CE years appear in unofficial contexts, so add พ.ศ. or ค.ศ. when the era is unclear [37]. Thai digits (๑๒๓) appear mostly in government documents, and no regulation requires them [37][38]. Abbreviate months as ม.ค., ก.พ. and so on [31]. Prices: 1,500 บาท or ฿1,500. Times: 19.00 น.

**Names of people & works:** The Royal Society's transliteration rules use no tone marks unless the source language is tonal, and keep established spellings [42]. Official and popular forms differ: Thai Wikipedia writes Chopin as ชอแป็ง, and the popular spelling โชแปง redirects there [43].

**Sensitivities:** Under Section 112, defaming the king, queen, heir or regent carries 3–15 years per count, and shares and likes have been investigated [39]. Keep the monarchy out of marketing, jokes and imagery. If royalty must be mentioned, use royal vocabulary (ราชาศัพท์) correctly. For example, don't put ทรง in front of a word that is already royal [44]. Treat Buddhism and monks with respect.

**Search aliases:** ภาษาไทย, Phasa Thai, Thai, Siamese, Central Thai, 泰语, 泰語, タイ語, 태국어, tiếng Thái, bahasa Thai

**Prompt guide (≤120 words):** Write Thai with no spaces between words. Use a space only between clauses or sentences, and use no commas or full stops. Never assign ครับ or ค่ะ unless the user's profile or samples show which one. Otherwise use neutral เรา or the brand name and soften with นะ. Match the user's particle style (ค่ะ vs ค่าาา). Use 555 or emoji for laughter in casual voices only. Write years in the Buddhist Era, adding พ.ศ. when it could be unclear, with Arabic digits. Prices look like 1,500 บาท and times like 19.00 น. Never mention the monarchy in promotional or humorous posts. Use familiar Thai spellings for foreign names.

**Confidence:** High for script, spacing, particle gender, era, digits and legal risk. Medium for slang and platform habits. Low for humour.

**Native check:** ดีๆ vs ดี ๆ in casual posts. The age connotations of คับ, ค่า and งับ. ชอแป็ง vs โชแปง among classical-music audiences. Two-digit BE years (16/9/69). Hashtag habits on X and TikTok.

**Sources:**
[31] Microsoft, Thai Localization Style Guide — https://download.microsoft.com/download/3/f/2/3f236167-639e-46f2-8201-554c36bcbf31/tha-tha-StyleGuide.pdf
[32] สำนักงานราชบัณฑิตยสภา, การเว้นวรรค — http://legacy.orst.go.th/?page_id=629
[33] Thailand Foundation, How to use "Krub" and "Kha" in the Thai language — https://thailandfoundation.or.th/how-to-use-krub-and-kha-in-the-thai-language/
[34] Jitpaisarnwattana, N. (2018), Gender-Differential Tendencies in LINE Use: A Case of Thailand, Journal of English Studies 13(1) — https://so04.tci-thaijo.org/index.php/jsel/article/download/159701/115439/439794
[35] Khaosod English, Why do Thai people type 55555 when they laugh online? — https://www.khaosodenglish.com/life/2026/08/26/why-do-thai-people-type-55555-when-they-laugh-online/
[36] ThaiLearn, Thai Internet Slang — https://thailearn.app/guides/thai-internet-slang
[37] Wikipedia, Date and time notation in Thailand — https://en.wikipedia.org/wiki/Date_and_time_notation_in_Thailand
[38] PostToday, ไม่มีข้อบังคับใช้ "เลขไทย" ในหนังสือราชการ — https://www.posttoday.com/politics/684511
[39] Wikipedia, Lèse-majesté in Thailand — https://en.wikipedia.org/wiki/L%C3%A8se-majest%C3%A9_in_Thailand
[40] LY Corporation, How LINE Has Become Thailand's Everyday Life — https://www.lycorp.co.jp/en/story/20251205/line_thailand.html
[41] DataReportal, Digital 2025: Thailand — https://datareportal.com/reports/digital-2025-thailand
[42] วิกิพีเดีย, หลักเกณฑ์การทับศัพท์ของราชบัณฑิตยสถานและสำนักงานราชบัณฑิตยสภา — https://th.wikipedia.org/wiki/%E0%B8%AB%E0%B8%A5%E0%B8%B1%E0%B8%81%E0%B9%80%E0%B8%81%E0%B8%93%E0%B8%91%E0%B9%8C%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B8%97%E0%B8%B1%E0%B8%9A%E0%B8%A8%E0%B8%B1%E0%B8%9E%E0%B8%97%E0%B9%8C%E0%B8%82%E0%B8%AD%E0%B8%87%E0%B8%A3%E0%B8%B2%E0%B8%8A%E0%B8%9A%E0%B8%B1%E0%B8%93%E0%B8%91%E0%B8%B4%E0%B8%95%E0%B8%A2%E0%B8%AA%E0%B8%96%E0%B8%B2%E0%B8%99%E0%B9%81%E0%B8%A5%E0%B8%B0%E0%B8%AA%E0%B8%B3%E0%B8%99%E0%B8%B1%E0%B8%81%E0%B8%87%E0%B8%B2%E0%B8%99%E0%B8%A3%E0%B8%B2%E0%B8%8A%E0%B8%9A%E0%B8%B1%E0%B8%93%E0%B8%91%E0%B8%B4%E0%B8%95%E0%B8%A2%E0%B8%AA%E0%B8%A0%E0%B8%B2
[43] วิกิพีเดีย, เฟรเดริก ชอแป็ง — https://th.wikipedia.org/wiki/%E0%B9%80%E0%B8%9F%E0%B8%A3%E0%B9%80%E0%B8%94%E0%B8%A3%E0%B8%B4%E0%B8%81_%E0%B9%82%E0%B8%8A%E0%B9%81%E0%B8%9B%E0%B8%87
[44] Wongnai, คำราชาศัพท์ที่คนไทยชอบใช้ผิด — https://www.wongnai.com/articles/royal-words
[45] Wikipedia, Thai language — https://en.wikipedia.org/wiki/Thai_language
[46] Sex Differentiation in Thai LGBTQ Movies, Journal of Studies in the Field of Humanities — https://so04.tci-thaijo.org/index.php/abc/article/view/274006

---

### Tiếng Việt · Vietnamese — `vi-VN`
**Where it's used / platforms:** Vietnam. Advertising reach in early 2025: Facebook 76.2M, YouTube 62.3M, TikTok 40.9M adults, Instagram 10.6M, X 6.29M [57]. Zalo reports about 83.1M monthly users (Q1 2026) and is the default messenger [56].

**Script & spelling:** Latin script (chữ Quốc ngữ) whose diacritics mark tones and vowels. Leaving them out changes or blurs meaning, so always write them all. Every syllable is separated by a space. Since 1975, media usage has shifted toward the Northern dialect [49].

**Punctuation & typography:** Latin punctuation, with no comma before và or hoặc [47]. Numbers use a period for thousands and a comma for decimals: 1.526 and 5,25 [47].

**Words that mark the region:**
| Meaning | North (Hà Nội) | Central / South (Sài Gòn) |
|---|---|---|
| spoon | thìa | muỗng [50] |
| pig, pork | lợn | heo [51] |
| pineapple | dứa | thơm [52] |
| "okay?" softener | nhé | nha [53] |
| "so, like that" | thế | vậy, written "z" online [54] |

**Particles, interjections & fillers:** nhé and nha soften invitations. ạ and dạ add deference (*illustrative:* "Dạ, em cảm ơn ạ" — "Yes, thank you [respectful]"). ơi calls to people ("Mọi người ơi!" — "Everyone!"). nhỉ asks for agreement. Teencode spellings (k for không, f for ph) are still used by young people but criticised as damaging standard Vietnamese [55]. Avoid them in public or professional voices.

**Formality & address:** Vietnamese has no neutral "I" or "you". Each term encodes age, gender and relationship [48]:
- **tôi** is formal and neutral.
- **mình** is intimate [48].
- **tớ / cậu** are used between young friends [48].
- **bạn** ("friend") works as a neutral way to address readers, and Microsoft uses it for "you" [47].

anh, chị and em fix both parties' age and gender. **Never choose them for the writer.** Microsoft avoids gendered kin pronouns in generic references [47]. Brand pages often write mình or chúng mình to bạn or các bạn (native check).

**Mixing languages:** Some English lifestyle and tech words stay untranslated in Latin script (livestream, check-in). How far this goes depends on the audience (native check).

**Tone & humour on social:** Warm, community-minded and meme-literate. Regional flavour (nha, z) signals a Southern, casual voice.

**Platform habits:** Facebook fanpages and groups are central. Zalo official accounts handle customer messaging [56]. TikTok captions are short with hashtags.

**Formats:** Dates: 16/9/2026, or ngày 16 tháng 9 năm 2026. Money: 150.000đ, 150.000 ₫, or VND in formal contexts [47]. Times: 19:30 or 19h30 (native check).

**Names of people & works:** Western names keep their original spelling and diacritics (Frédéric Chopin) rather than a Vietnamese phonetic form [59]. Put titles in quotation marks.

**Sensitivities:** Content judged to oppose the state or harm national security is illegal, and bloggers have been prosecuted. Decree 72/2013 limited social accounts to "personal information" [58]. Avoid political commentary and territorial references.

**Search aliases:** Tiếng Việt, Tieng Viet, Việt ngữ, Vietnamese, Annamese, 越南语, 越南語, ベトナム語, 베트남어, ภาษาเวียดนาม, bahasa Vietnam

**Prompt guide (≤120 words):** Write Vietnamese with every diacritic correct and never in no-diacritic form. Address readers as bạn or các bạn. Use the first person the user uses (tôi, mình or the brand name). Never assign anh, chị or em without knowing the writer's age and gender. Soften with nhé, or nha when the voice is Southern, and use ạ for deference to elders or customers. Keep regional vocabulary consistent within a post. Avoid teencode. Write money as 150.000đ and dates as 16/9/2026. Keep Western names in their original spelling. Avoid political commentary.

**Confidence:** High for diacritics, number formats, the pronoun system and regional vocabulary. Medium for brand pronoun habits and platform habits. Low for humour and laughter conventions.

**Native check:** Laughter forms (haha, hihi, :)), =))). How acceptable "150k" is. Whether 19h30 or 19:30 is more common. Brand first-person choice (mình, chúng mình, "Ad", "shop"). Whether Southern particles feel natural to Northern audiences. Current enforcement under 2024 decrees (not verified here).

**Sources:**
[47] Microsoft, Vietnamese Localization Style Guide — https://download.microsoft.com/download/b/f/e/bfecb1b4-21ab-48fd-a48c-c2471b026f8f/vie-vnm-StyleGuide.pdf
[48] Wikipedia, Vietnamese pronouns — https://en.wikipedia.org/wiki/Vietnamese_pronouns
[49] Wikipedia, Vietnamese dialects — https://en.wikipedia.org/wiki/Vietnamese_dialects
[50] Wiktionary, muỗng — https://en.wiktionary.org/wiki/mu%E1%BB%97ng
[51] Wiktionary, heo — https://en.wiktionary.org/wiki/heo
[52] Wiktionary, thơm — https://en.wiktionary.org/wiki/th%C6%A1m
[53] Wiktionary, nha — https://en.wiktionary.org/wiki/nha
[54] Wiktionary, vậy — https://en.wiktionary.org/wiki/v%E1%BA%ADy
[55] Wikipedia tiếng Việt, Teencode — https://vi.wikipedia.org/wiki/Teencode
[56] Wikipedia, Zalo — https://en.wikipedia.org/wiki/Zalo
[57] DataReportal, Digital 2025: Vietnam — https://datareportal.com/reports/digital-2025-vietnam
[58] Wikipedia, Internet censorship in Vietnam — https://en.wikipedia.org/wiki/Internet_censorship_in_Vietnam
[59] Wikipedia tiếng Việt, Frédéric Chopin — https://vi.wikipedia.org/wiki/Fr%C3%A9d%C3%A9ric_Chopin

---

### Bahasa Indonesia · Indonesian — `id-ID`
**Where it's used / platforms:** Indonesia. Advertising reach in early 2025: YouTube 143M, Facebook 122M, TikTok 108M adults, Instagram 103M, X 25.2M [65].

**Script & spelling:** Latin script. The standard is EYD Edition V, issued by the language agency Badan Bahasa in 2022 to replace EBI, and the dictionary is KBBI [61]. Standard Indonesian is used in formal settings, while vernacular varieties dominate daily talk [67]. Social posts use colloquial spellings freely.

**Punctuation & typography:** Latin punctuation. EYD V italicises titles of books, films, albums and podcasts [61]. Social platforms have no italics, so quotation marks are the fallback. Numbers use a period for thousands and a comma for decimals [60].

**Words that mark the region:**
| Meaning | Standard (baku) | Social / colloquial |
|---|---|---|
| not | tidak | nggak / gak (*illustrative*) |
| already | sudah | udah (*illustrative*) |
| very | sangat | banget (*illustrative*) |
| I / you | saya / Anda | aku / kamu, or gue / lo in Jakarta [62] |
| free of charge | gratis | gratis. Malay "percuma" means "pointless" here [70] |

**Particles, interjections & fillers:** dong (it's obvious, go on), sih and deh (emphasis or hedging), kok (pushing back on doubt), lho or loh (surprise), nih (pointing something out), kan (seeking confirmation) [62]. Laughter is wkwk, repeated for emphasis and only in humorous texting [63].

**Formality & address:**
- **saya / Anda** is the professional default. Anda is capitalised [60].
- **aku / kamu** is warm and casual.
- **gue / lo** came into Jakarta slang from Hokkien through Betawi [62]. It reads as Jakarta youth speech.

Pronouns have no gender. Address terms such as Mas and Mbak do, so don't assign them to the writer.

**Mixing languages:** "Bahasa Jaksel" (South Jakarta speech) mixes in English fillers such as "which is", "literally" and "basically". It is tied to affluent urban youth and often mocked [62]. Use it only when the user writes that way.

**Tone & humour on social:** Friendly and meme-literate. Particles do the emotional work that emoji do elsewhere.

**Platform habits:** Captions on Instagram and TikTok are casual and full of hashtags. For a broad national audience, use general colloquial Indonesian rather than Jakarta slang.

**Formats:** Money: Rp150.000, with no space and no period after Rp [64]. Dates: 16 September 2026. Times: 19.00 WIB. Always name the time zone (WIB, WITA or WIT).

**Names of people & works:** Keep foreign names in their original spelling. Italicise titles in formal text [61].

**Sensitivities:** The ITE Law covers online defamation and hate speech, and it has been used against critics. The 2023 Criminal Code, in force from 2026, criminalises insulting the president and state institutions [66]. Avoid SARA topics (ethnicity, religion, race, inter-group relations).

**Search aliases:** Bahasa Indonesia, Indonesian, Indonesia, bahasa Indo, Melayu Indonesia, 印尼语, 印尼語, インドネシア語, 인도네시아어, ภาษาอินโดนีเซีย, tiếng Indonesia

**Prompt guide (≤120 words):** Match the register to the user: saya/Anda for professional voices, aku/kamu for friendly ones, and gue/lo only when the user writes Jakarta slang. Use colloquial spellings (nggak, udah, banget) only in casual voices. Add feeling through particles (dong, sih, deh, kok, nih) rather than stacks of emoji. Keep English mixing light unless the user writes Jaksel. Write money as Rp150.000 and times as 19.00 WIB. Put titles in quotation marks. Avoid religion, ethnicity and politics in promotional posts, and never insult people or institutions.

**Confidence:** High for spelling standard, number and currency formats, pronoun registers and legal risk. Medium for particles and Jaksel perception. Low for platform habits and humour.

**Native check:** Whether "kamu" or "Anda" is the norm for lifestyle and arts brands. Whether "Kak" works as a neutral address to followers. Informal abbreviations (150rb, 1,5jt). Whether quotation marks or capitalisation is preferred for titles on social media.

**Sources:**
[60] Microsoft, Indonesian Localization Style Guide — https://download.microsoft.com/download/c/2/8/c2804555-f6ed-4db9-9e3b-ddf754159bd3/ind-idn-StyleGuide.pdf
[61] Wikipedia bahasa Indonesia, Ejaan yang Disempurnakan — https://id.wikipedia.org/wiki/Ejaan_yang_Disempurnakan
[62] Wikipedia, Indonesian slang — https://en.wikipedia.org/wiki/Indonesian_slang
[63] Wiktionary, wkwkwk — https://en.wiktionary.org/wiki/wkwkwk
[64] Wikipedia, Indonesian rupiah — https://en.wikipedia.org/wiki/Indonesian_rupiah
[65] DataReportal, Digital 2025: Indonesia — https://datareportal.com/reports/digital-2025-indonesia
[66] Wikipedia, Internet censorship in Indonesia — https://en.wikipedia.org/wiki/Internet_censorship_in_Indonesia
[67] Wikipedia, Indonesian language — https://en.wikipedia.org/wiki/Indonesian_language
[70] Wiktionary, percuma — https://en.wiktionary.org/wiki/percuma

---

### Bahasa Melayu · Malay (Malaysia) — `ms-MY`
**Where it's used / platforms:** Malaysia. Advertising reach in early 2025: YouTube 25.1M, Facebook 23.1M, TikTok 19.3M adults, Instagram 15.5M, Messenger 11.1M, X 5.1M [76]. Audiences are multilingual.

**Script & spelling:** Rumi (Latin) is the legal script, and Jawi is not legally prescribed [72]. The standard is set by Dewan Bahasa dan Pustaka (Kamus Dewan, Tatabahasa Dewan) [68]. Loanwords follow English, while Indonesian follows Dutch: televisyen vs televisi [69].

**Punctuation & typography:** Latin punctuation. Microsoft writes "anda" in lower case mid-sentence, unlike Indonesian "Anda" [68][60].

**Words that mark the region:** Differences from `id-ID`:
| Meaning | ms-MY | id-ID |
|---|---|---|
| car | kereta | mobil. In Indonesian, kereta means "train" [71] |
| free of charge | percuma | gratis. In Indonesian, percuma means "pointless" [70] |
| post office | pejabat pos | kantor pos [69] |
| you all / we / they (colloquial) | korang / kitorang / diorang | kalian / kami / mereka [72] |

False friends: *butuh* is vulgar in Malaysia, and *banci* means "census" in Malaysia but is a slur in Indonesia [69].

**Particles, interjections & fillers:** lah softens and builds solidarity. lor signals impatience or "obviously". meh marks a doubtful question [73].

**Formality & address:** saya/anda is standard and polite [68]. Colloquial speech uses the plural forms above [72]. Pronouns have no gender.

**Mixing languages:** Bahasa rojak (Malay–English mixing) is common but irritates purists [72]. Manglish mixes English with Malay, Hokkien, Cantonese and Tamil. It is discouraged in schools but common online [73].

**Tone & humour on social:** Relaxed and code-switching, with humour that often turns on shared Malaysian references.

**Platform habits:** Posts may be bilingual. Choose one base language per post and let particles add the local colour.

**Formats:** RM150, or RM1,500.00, with no space after RM [74]. Dates: 16 September 2026.

**Names of people & works:** Keep foreign names in their original spelling.

**Sensitivities:** The Sedition Act covers content that brings the Rulers into contempt, stirs ill-will between races, or questions Article 153, which protects the special position of the Malays. Since the 2015 amendments it may also cover reposting [75]. Keep race, religion and royalty out of jokes and marketing.

**Search aliases:** Bahasa Melayu, Bahasa Malaysia, BM, Malay, Melayu, Malaysian, 马来语, 馬來語, マレー語, 말레이어, ภาษามลายู, tiếng Mã Lai

**Prompt guide (≤120 words):** Write Malaysian Malay, not Indonesian: kereta (car), percuma (free), -syen spellings, and "anda" in lower case. Never use butuh. Use saya/anda for polite voices and colloquial forms (korang, kitorang) for casual ones. Add lah sparingly. Use Manglish or rojak only if the user does. Write prices as RM150 and dates as 16 September 2026. Avoid race, religion and royalty.

**Confidence:** High for vocabulary deltas, currency and legal risk. Medium for particles and mixing. Low for humour and platform habits.

**Native check:** Casual first and second person (aku/kau, awak) on social media. Laughter forms. Whether "wkwk" has crossed over. Sensitivity around religious vocabulary in cross-community posts.

**Sources:**
[60] Microsoft, Indonesian Localization Style Guide (as above)
[68] Microsoft, Malay (Malaysia) Localization Style Guide — https://download.microsoft.com/download/97c8474f-dd92-459b-9349-07993da9166a/may-mys-StyleGuide.pdf
[69] Wikipedia, Comparison of Standard Malay and Indonesian — https://en.wikipedia.org/wiki/Comparison_of_Standard_Malay_and_Indonesian
[70] Wiktionary, percuma — https://en.wiktionary.org/wiki/percuma
[71] Wiktionary, kereta — https://en.wiktionary.org/wiki/kereta
[72] Wikipedia, Malaysian Malay — https://en.wikipedia.org/wiki/Malaysian_Malay
[73] Wikipedia, Manglish — https://en.wikipedia.org/wiki/Manglish
[74] Wikipedia, Malaysian ringgit — https://en.wikipedia.org/wiki/Malaysian_ringgit
[75] Wikipedia, Sedition Act 1948 — https://en.wikipedia.org/wiki/Sedition_Act_1948
[76] DataReportal, Digital 2025: Malaysia — https://datareportal.com/reports/digital-2025-malaysia

---

### Filipino · Filipino (Tagalog, incl. Taglish) — `fil-PH`
**Where it's used / platforms:** Philippines. Advertising reach in early 2025: Facebook 90.8M, TikTok 62.3M adults, Messenger 61.8M, YouTube 57.7M, Instagram 22.9M, X 9.29M [84].

**Script & spelling:** Latin script, following the 2013 national orthography (Ortograpiyang Pambansa) from the Commission on the Filipino Language (KWF). *ng* means "of" and *nang* means "when" or "so that". New English borrowings may keep their spelling, and proper nouns always do [81].

**Punctuation & typography:** A hyphen joins a Tagalog affix to an English root: nag-delete, i-update, ma-save [77][81].

**Words that mark the region:**
| Meaning | Formal Filipino | Social Taglish (*illustrative*) |
|---|---|---|
| thank you for your support | Maraming salamat sa inyong suporta | Thank you so much sa support! |
| we're excited | Kami ay nasasabik | Super excited kami! |
| just kidding | Nagbibiro lang | Char / charot [80] |
| see you there | Magkita-kita tayo | See you there, guys! |

**Particles, interjections & fillers:** po and opo mark respect toward the person addressed [79]. char and charot mean "just kidding" and come from gay slang [80]. Laughter is hahaha.

**Formality & address:** Use po/opo toward elders, customers and strangers [79]. Microsoft's casual interface voice uses ka and iyo and avoids the formal kayo and inyo [77]. Pronouns have no gender (siya).

**Mixing languages:** Taglish is the de facto lingua franca of the urban, educated middle class, even though prescriptivists discourage it [78]. Coño English is English-dominant mixing associated with wealthy Manila families [78].

**Tone & humour on social:** Warm, teasing and self-mocking. "Char" undercuts a boast.

**Platform habits:** Facebook and Messenger dominate [84]. Captions often switch language between sentences.

**Formats:** Money: ₱1,500, also written PHP or P [82]. Dates put the month first: Enero 1, 2013 [77] or September 16, 2026.

**Names of people & works:** Proper nouns keep their original spelling [81].

**Sensitivities:** Cyber libel carries heavier penalties than print libel, and insults as mild as "incompetent" have led to charges [83]. Never name or attack people.

**Search aliases:** Filipino, Wikang Filipino, Pilipino, Tagalog, Wikang Tagalog, Taglish, Tag-lish, Pinoy, 他加禄语, 他加祿語, タガログ語, 필리핀어, 타갈로그어, ภาษาตากาล็อก, tiếng Tagalog

**Prompt guide (≤120 words):** Default to natural Taglish, switching between English and Filipino inside or between sentences, unless the user writes pure English or formal Filipino. Hyphenate Tagalog affixes on English roots (i-update, nag-share). Add po/opo when addressing elders, customers or a respected audience. Keep humour warm and self-deprecating, and use "char" only in casual voices. Write prices as ₱1,500 and dates month-first. Never insult named people.

**Confidence:** High for orthography, currency, date order and legal risk. Medium for Taglish norms and po usage. Low for humour and slang currency.

**Native check:** Whether brands use "po" in captions or only in replies. Whether "sana all" and "lodi" are still current. How far professional posts lean toward English. Laughter forms (HAHAHA vs hahaha).

**Sources:**
[77] Microsoft, Filipino Localization Style Guide — https://download.microsoft.com/download/25b05cb0-c8ad-41f0-be2e-30335c6ceb6a/fil-fil-StyleGuide.pdf
[78] Wikipedia, Taglish — https://en.wikipedia.org/wiki/Taglish
[79] Wiktionary, po (Tagalog) — https://en.wiktionary.org/wiki/po#Tagalog
[80] Wiktionary, charot — https://en.wiktionary.org/wiki/charot
[81] Wikipedia, Filipino orthography — https://en.wikipedia.org/wiki/Filipino_orthography
[82] Wikipedia, Philippine peso sign — https://en.wikipedia.org/wiki/Philippine_peso_sign
[83] Wikipedia, Cybercrime Prevention Act of 2012 — https://en.wikipedia.org/wiki/Cybercrime_Prevention_Act_of_2012
[84] DataReportal, Digital 2025: Philippines — https://datareportal.com/reports/digital-2025-philippines

---

## Open questions

1. **Gender and persona input.** ja, ko, th and vi all need the writer's gendered or age-marked choices: Japanese 僕 vs 私, Thai ครับ vs ค่ะ, Vietnamese anh/chị/em. Should PostRiff store an explicit "self-reference and particle" preference per person, learned from their past posts, rather than inferring it from a brief?
2. **Regional sub-varieties.** Northern vs Southern Vietnamese, and Jakarta vs national Indonesian, change vocabulary and particles. Should these be style options inside the locale rather than separate tags?
3. **Channel-level register.** Japanese note vs X, and Korean Naver Blog vs Instagram, differ enough that each locale × channel pair may need its own register default.
4. **Legal disclosure rules.** Japan's stealth-marketing rules, Korea's FTC disclosure placement and Japan's tax-inclusive price rule are hard rules. In line with "remind, don't block", they should appear as reminders on the draft. Thai, Indonesian, Malaysian and Philippine rules on sponsored posts were not researched.
5. **Not verified this round (web search budget ran out):** Vietnamese Decree 147/2024 and the 2018 Cybersecurity Law details; Malaysia's Online Safety Act and platform licensing (2025); Thai, Vietnamese and Malay laughter conventions beyond 555; brand pronoun habits in vi-VN and id-ID; Thai and Vietnamese transliteration practice in classical-music media.


---

## South Asia

Research date: 16 September 2026. Source numbers [n] run through the whole file, and each entry lists the ones it uses. Example phrases marked *illustrative* were written for this file; none are copied from posts. [29] is my own count of characters on major news sites that day. It shows publishing practice, not what ordinary users type.

### Family notes

| Locale | Script, direction | Address forms (intimate / familiar / polite) | Writer's gender on 1st-person verbs? | Digits and grouping in practice | Key platforms |
|---|---|---|---|---|---|
| `hi-IN` | Devanagari, LTR | तू / तुम / आप | **Yes** (गया / गई) | Western 0–9; lakh–crore 12,34,567; ₹ before | YouTube, Instagram, WhatsApp, ShareChat, Moj, Facebook, X |
| `hi-Latn-IN` | Latin, LTR | tu / tum / aap | **Yes** (gaya / gayi) | Western; "1.5 lakh", "2 crore" | Instagram, WhatsApp, YouTube comments, X |
| `bn-IN` | Bengali, LTR | তুই / তুমি / আপনি | No | Bengali ০–৯ and Western both seen; লাখ/কোটি; ₹ before | Facebook, WhatsApp, YouTube, ShareChat, Moj |
| `bn-BD` | Bengali, LTR | same | No | Bengali ০–৯ dominant; ৳ / টাকা | Facebook, TikTok, YouTube |
| `ta-IN` | Tamil, LTR | நீ / நீங்க(ள்) | No (3rd person yes) | Western; லட்சம்/கோடி | YouTube, Instagram, WhatsApp, ShareChat, Moj |
| `te-IN` | Telugu, LTR | నువ్వు / మీరు | No (3rd person yes) | Western; లక్ష/కోటి | YouTube, Instagram, WhatsApp, ShareChat, Moj |
| `mr-IN` | Devanagari (Balbodh), LTR | तू / तुम्ही / आपण | **Yes** (गेलो / गेले) | Devanagari ०–९ and Western both; लाख/कोटी | YouTube, Instagram, WhatsApp, ShareChat, Moj |
| `ur-PK` | Perso-Arabic (Nastaliq), **RTL** | تُو / تم / آپ | **Yes** (گیا / گئی) | Western digits; comma grouping disputed (see ur-PK) | TikTok, YouTube, Facebook, Snapchat, Instagram, WhatsApp |

**Patterns shared across the region**
- **Hindi and Urdu share one spoken grammar.** They divide by script and by formal vocabulary. Devanagari with Sanskrit words is read as Hindu, and Perso-Arabic script with Persian words as Muslim [12][14]. Picking a script or a vocabulary register sends an identity signal.
- **Writing these languages in Latin letters is widespread and has no standard spelling.** Google's Dakshina paper finds "no commonly used standard Latin script orthography" (Roark et al.) for these languages. People type rough phonetic spellings, and Urdu speakers do this even though Urdu keyboards exist [16].
- **Gender:** in Hindi, Urdu and Marathi, first-person verbs show the writer's gender [12][48]. Bengali and Telugu don't mark it in the first person [32][46], and neither does Tamil (Medium, grammar source silent). Ways to stay neutral, backed by Microsoft's guidance [1][6] and the grammar sources [12]:
  - the perfective with ने, where the verb agrees with the object (मैंने … किया);
  - dative-subject phrasing (मुझे … लगा / مجھے … لگا);
  - plural हम / ہم;
  - noun phrases with no finite verb.
- **Brand address is formal.** Microsoft and Mozilla address the user as आप, আপনি, நீங்கள், మీరు, आपण and آپ [1][2][3][4][5][6][8]. Creators often step down one level (तुम, তুমি, நீங்க).
- **Numbers:** CLDR uses lakh–crore grouping (#,##,##0) for hi, bn, ta, te and mr, and 3-digit grouping for ur. The default digits are Western for hi, ta, te and ur, Bengali for bn and Devanagari for mr [9].
- **Invisible characters.** Unicode uses ZWJ to force half-forms and ZWNJ to block conjuncts [10]. On news sites [29] I found:
  - stray joiners inside ordinary Hindi words;
  - regular ZWNJ after a final virama in Telugu loanwords;
  - inconsistent ZWJ/ZWNJ in the Bengali cluster র‍্য.

  Microsoft's own bn-IN style guide mixes the correct danda U+0964 with the look-alike U+09F7 [2][29]. **Rules for PostRiff:** never add joiners to hashtags, and always output U+0964 for the danda.
- **Regional platforms:** ShareChat lists 15 languages (Wikipedia includes English) [20]. Moj lists 12 [21]. **Neither offers Urdu**, so `ur-PK` should not be routed to them.

**Confidence:** Script, address and CLDR data: High. Platform mix: Medium (ad-reach estimates [27][37][56]).

**Sources:** [1]–[10], [12], [14], [16], [20], [21], [27], [29], [32], [37], [46], [48], [56]. Full list below each entry.

---

### हिन्दी · Hindi — `hi-IN`

**Where it's used / platforms:**
- North and central India, and a link language elsewhere.
- Devanagari Hindi is at home in news, devotional content, family WhatsApp groups, and ShareChat and Moj language feeds [20][21].
- In a 2014–15 study of bilingual users' tweets, Devanagari tweets leaned factual and official, while personal opinion appeared in Roman Hindi [17]. See `hi-Latn-IN`.

**Script & spelling:**
- **Nasals:** Microsoft prefers anusvara in common words (पंप, कंप्यूटर), chandrabindu for nasal vowels (जाएँ, दिखाएँ), and लिए over लिये [1]. Social posts often write जाएं. Pick one style per post.
- **Nukta:** keep it where readers expect it (ज़रूर, ख़ास). Microsoft drops it in फोटो and फाइल [1]. Don't over-apply it.

**Punctuation & typography:**
- **Sources disagree on the full stop.** Microsoft uses "." [1] and Mozilla uses । [8]. News sites split too: a Dainik Bhaskar article used । and BBC Hindi used "." [29].
- Short captions often end with no punctuation, or with "!".
- Use U+0964, never a pipe "|". No space before % [1].

**Words that mark the region:** stiff (Sanskritised) versus natural on social

| Stiff | Natural | Gloss |
|---|---|---|
| पुनः प्रयास करें | दुबारा कोशिश करें | try again [1] |
| चयन करें | चुनें | choose [1] |
| अतः | इसलिए | therefore [1] |
| आवश्यक | ज़रूरी | necessary (*illustrative*) |
| प्रतीक्षा | इंतज़ार | wait (*illustrative*) |

**Particles, interjections & fillers (*illustrative*):** ना (*na*, "right?/please"), तो (*to*, "so"), भी (*bhi*, "also"), बस (*bas*, "that's all"), यार (*yaar*, "mate"), अरे (*arey*, "hey"), एकदम (*ekdam*, "totally").

**Formality & address:**
- **Brands:** आप with polite imperatives (देखें / देखिए). Mozilla calls ढूँढो-type imperatives rude [8].
- **Creators:** तुम. Keep तू for intimate or devotional voices. Add जी after names and roles.
- **Gender:** first-person verbs mark the writer's gender: गया/गई, करता/करती हूँ, करूँगा/करूँगी [12]. Neutral options (*illustrative*): मैंने नया गाना रिकॉर्ड किया ("I recorded a new song"; the verb agrees with the song), मुझे बहुत अच्छा लगा ("I loved it").

**Mixing languages:**
- English nouns in Devanagari are normal (वीडियो, लिंक, लाइव). Since 2011 the Home Ministry has allowed officials to use English words in Hindi notes [15].
- Keep brand names in Latin script [1][8].

**Tone & humour on social:**
- Warm, emotional and family-centred, with film dialogue and couplets.
- Bilingual Twitter users switched to Hindi for negative opinion and swearing [17]. A switch into Hindi signals strong feeling.

**Platform habits:**
- Set festival formulas, e.g. दिवाली की हार्दिक शुभकामनाएँ ("warm Diwali wishes", *illustrative*).
- Hashtags appear in both scripts (Low).

**Formats:**
- **Digits:** Western 0–9. The constitution specifies the "international form of Indian numerals" [13], and Mozilla and news sites use them [8][29].
- **Money:** ₹1,25,000 (lakh–crore grouping, ₹ first, no space) [9][24]. Also "1.5 लाख", "2 करोड़".
- **Dates:** d/M/yy, or 16 सितंबर 2026 [8][9].

**Names of people & works:** transliterate by sound. Wikipedia uses बीथोवेन and a German-based मोत्सार्ट [28]; the English-based मोज़ार्ट is also common (Low).

**Sensitivities:**
- **Hindi–Urdu:** vocabulary carries religious identity [14]. Never "purify" or "Urdu-ise" the writer's words.
- **Non-Hindi audiences:** don't default to Hindi for them [42].
- **Caste:** no caste labels. In 2018 media were advised to say "Scheduled Castes" rather than "Dalit" [25].
- **Kashmir:** place names are politically loaded [26].

**Search aliases:** Hindi, हिन्दी, हिंदी, Hindī, Standard Hindi, Devanagari Hindi, Khari Boli, Hindustani, हिंदुस्तानी

**Prompt guide (≤120 words):** Write Devanagari Hindi the way people speak it every day, not textbook Hindi: prefer ज़रूरी, इंतज़ार and English loanwords (वीडियो, लिंक) over आवश्यक, प्रतीक्षा and पुनः. Address the audience as आप with देखें/कीजिए imperatives unless the voice profile uses तुम. Never guess the writer's gender: avoid गया/गई and करता/करती; use मैंने…किया, मुझे…लगा or noun phrases. Use Western digits, lakh–crore grouping and ₹ before the amount (₹1,25,000). End sentences with । (U+0964), or with nothing in short captions, and be consistent. Keep brand names in Latin script. Never put zero-width characters inside hashtags.

**Confidence:**
- High: script, formats, address, gender.
- Medium: punctuation (sources disagree).
- Low: tone and platform habits.

**Native check:**
- Danda or full stop for creator voices?
- जाएं or जाएँ on social?
- The Central Hindi Directorate spelling standard was unreachable, so it is unverified.

**Sources:** [1] [8] [9] [12] [13] [14] [15] [17] [20] [21] [24] [25] [26] [28] [29] [42]

---

### Hinglish (Roman Hindi) · Romanized Hindi — `hi-Latn-IN`

**Where it's used / platforms:**
- **Instagram captions, WhatsApp chats and statuses, YouTube comments, X.** The evidence:
  - YouTube comments: 52% Romanised Hindi, 46% English, 1% Devanagari (Palakodety et al. 2021, via Wikipedia) [15].
  - Twitter 2014–15, bilingual users: Roman Hindi 8% plus Roman mixed 15%, against Devanagari Hindi 12% [17].
  - Vendor online survey (n=744, 2020): 58% prefer reading Hindi in Latin letters, 25% Devanagari; 75% among Gen Z [19].
  - Romanization grows out of Latin keyboards and informal chat [16].
- **Recommendation: make this its own picker entry (a script choice), and treat English mixing as a separate voice setting.**
  - Script is a hard output rule, not a matter of style.
  - The grammar is Hindi, so this is not a trait of `en-IN`.
  - Hinglish mixing also happens in Devanagari [15], so the mixing slider should work on both `hi-IN` and `hi-Latn-IN`.

**Script & spelling:**
- Basic Latin letters only, no diacritics. Nobody writes academic forms like *kyā*.
- Spelling varies from person to person [16]. Common variants (*illustrative*): hai/h, nahi/nahin/nhi, kya/kia, bahut/bohot/bht, accha/acha.
- **Watch for collisions:** "main/mai/me" can mean मैं ("I") or में ("in").
- Keep each word spelled the same way throughout a post.

**Punctuation & typography:**
- Latin punctuation, often loose: "…", "!!", emoji line breaks.
- Lower-case sentences are acceptable. Capitalise brand names.

**Words that mark the region (*illustrative*):**

| Pattern | Example | Gloss |
|---|---|---|
| English verb + *karo/karna* | try karke dekho | give it a try |
| English noun + Hindi case marker | link bio mein hai | link's in bio |
| Hindi intensifiers | ekdam mast, zabardast | totally great |
| *ho gaya* completion | shoot done ho gaya | the shoot's done |

**Particles, interjections & fillers (*illustrative*):** na, yaar, bas, matlab ("I mean"), arey, bhai/bro (to followers), sach mein ("seriously"), uff.

**Formality & address:**
- aap for brands, tum for peer creators. tu only if the voice profile uses it.
- **Gender:** gaya/gayi, karta/karti hoon [12]. Neutral options (*illustrative*): "maine pehli baar live perform kiya" ("I performed live for the first time"), "mujhe bahut maza aaya" ("I had so much fun").

**Mixing languages:**
- English words appear in their English spelling, not transliterated.
- In a 2014 Facebook study, nearly all long threads were multilingual and most posts were in Roman script [17][18].
- Google's Gboard offers QWERTY transliteration layouts and a Hinglish option [59].

**Tone & humour on social:**
- Chatty, fast, full of memes. Heavy use of film-dialogue quotes, sarcasm and self-deprecation.
- Personal opinion lives in this register [17].

**Platform habits:**
- Reel captions are short, with hooks such as "wait for it" and "save karo".
- YouTube titles often pair Roman Hindi with English keywords.
- Hashtags are usually English or Roman (#diwali).

**Formats:** ₹499 or Rs 499; "1.5 lakh", "2 cr"; dates like "16 Sept" or 16/09 [9][24].

**Names of people & works:** use the standard English spelling (Beethoven, Mozart).

**Sensitivities:**
- **Same as `hi-IN`.**
- Roman Hindi reads as urban and young, and can shut out older or regional readers.
- **Cross-border readers:** Roman Urdu is mutually intelligible with Roman Hindi [51], so Pakistani readers may be reading too.

**Search aliases:** Hinglish, Roman Hindi, Romanized Hindi, Romanised Hindi, Hindi in English letters, Latin-script Hindi, hi-Latn, हिंग्लिश

**Prompt guide (≤120 words):** Write Hindi grammar in Latin letters, the way urban Indians type on Instagram and WhatsApp: no diacritics, no scholarly transliteration ("kya", "nahi", "accha"). Spell each word the same way throughout. Mix English nouns and verbs into Hindi sentences ("try karke dekho", "link bio mein hai"). Don't switch to whole English sentences unless the voice profile does. Use "aap" for brands and "tum" for creators. Never guess the writer's gender: prefer "maine…kiya" and "mujhe laga" over "main gaya/gayi". Write money as ₹499 and big numbers as "1.5 lakh". Use no Devanagari.

**Confidence:**
- High: script practice (several independent sources agree).
- Medium: prevalence figures (dated, or from vendor or secondary sources).
- Low: spelling variants and platform habits.

**Native check:**
- Which spellings (nahi/nhi, bahut/bohot) read as natural rather than sloppy in brand posts?
- Is "h" for "hai" acceptable outside chat?

**Sources:** [9] [12] [15] [16] [17] [18] [19] [24] [51] [59]

---

### বাংলা · Bengali (India) — `bn-IN`

**Where it's used / platforms:**
- West Bengal, Tripura and Assam's Barak Valley. The Kolkata standard is the reference.
- Bengali feeds exist on ShareChat and Moj [20][21].
- Facebook and WhatsApp are strong (Low, not measured here).

**Script & spelling:**
- **Register:** the standard colloquial written form (চলিত ভাষা) is the norm. The older literary form (সাধু ভাষা) is now limited to some official signs and documents [30].
- **Letters:** khanda ta ৎ appears word-finally and before some conjuncts [33].
- **English words:** Microsoft accepts them written in Bengali script when people use them daily: ওয়ালেট, ক্লাউড, ডিভাইস [2].
- **র + ya-phala:** the ra + ya cluster needs ZWJ or ZWNJ, and even major outlets encode it inconsistently [29].

**Punctuation & typography:**
- **Dari (।) ends sentences.** Unicode uses the shared U+0964 [10][11]. Other punctuation follows English [33].
- **Watch the look-alike:** Microsoft's bn-IN guide itself uses U+09F7 (a fraction sign) as a dari 34 times [2][29]. Always output U+0964.
- Microsoft calls for curly double quotes “ ” and no single quotes [2].
- West Bengal papers use the dari [29].

**Words that mark the region:** West Bengal versus Bangladesh

| West Bengal (bn-IN) | Bangladesh (bn-BD) | Gloss |
|---|---|---|
| জল | পানি | water [31] |
| স্নান | গোসল | bath [31] |
| মাসি | খালা | maternal aunt [31] |
| পিসি | ফুফু | paternal aunt [31] |
| নিমন্ত্রণ | দাওয়াত | invitation [31] |
| নুন | লবণ | salt [30] |
| নমস্কার | আসসালামু আলাইকুম | greeting [30] |

These choices follow religion and upbringing as much as the border [31][34]. Don't infer the writer's faith from them.

**Particles, interjections & fillers (*illustrative*):** তো (*to*, "so"), না (*na*, tag), তাই (*tai*, "so"), গো (*go*, affectionate vocative), রে (*re*, casual vocative), দারুণ (*darun*, "great"), উফ (*uff*), আরে (*are*, "hey"), ব্যাস (*byas*, "that's it").

**Formality & address:**
- **Three levels:** তুই (very familiar), তুমি (familiar), আপনি (polite). Verbs inflect for this politeness level, not for gender [32].
- **Brands:** Microsoft uses আপনি only [2]. Creators often use তুমি (*illustrative*: দেখে নাও, "take a look").
- **Gender:** no first-person gender marking. Some nouns are gendered (ছাত্র/ছাত্রী), so use neutral nouns [2].

**Mixing languages:** English noun + করা/করুন (শেয়ার করুন, "please share"). Roman Bengali appears in chats [16] (Low for West Bengal).

**Tone & humour on social:** wordplay, literary allusion, food and football banter, nostalgia around Durga Puja (Low, general observation).

**Platform habits:** festival greetings such as শুভ নববর্ষ ("Happy New Year") at Poila Baishakh [35] and শুভ বিজয়া after Durga Puja (*illustrative*).

**Formats:**
- **Digits:** CLDR bn-IN defaults to Bengali digits, with ₹ before the amount (₹১,২৩,৪৫৬.০০) [9]. West Bengal papers mix Bengali and Western digits, while BBC Bangla uses Bengali digits [29].
- **Large numbers:** লাখ / কোটি [24].
- **Dates:** d/M/yy [9]. Poila Baishakh falls on 14 or 15 April in West Bengal [35].

**Names of people & works:** Wikipedia uses German-based spellings বেটহোফেন and মোৎসার্ট [28]. English-based spellings are also seen (Low).

**Sensitivities:**
- **Religion:** Hindu/Muslim vocabulary and greetings carry identity [30]. Match the voice profile and don't mix sets.
- **Not Bangladesh:** never treat Bangladeshi and West Bengal audiences as one.
- **Kolkata rivalries:** East-Bengal-origin (Bangal) versus West-Bengal-origin (Ghoti) banter is affectionate but can sting (Low).

**Search aliases:** Bengali, Bangla, বাংলা, Bengali (India), West Bengal Bengali, Kolkata Bengali, Banglish, Roman Bengali

**Prompt guide (≤120 words):** Write standard colloquial Bengali (চলিত), never সাধু ভাষা. Use West Bengal vocabulary (জল, স্নান, মাসি, নমস্কার) unless the voice profile shows Bangladeshi or Muslim usage, and never mix the two sets in one post. Address followers as আপনি for brands and তুমি for creators; avoid তুই unless the profile uses it. End sentences with । (U+0964, never U+09F7). English nouns may appear in Bengali script with করুন/করো. Put ₹ before amounts and use লাখ/কোটি. Match the profile's digit choice (Bengali ০–৯ or Western) and stick to it within a post.

**Confidence:**
- High: script, dari, address forms, vocabulary pairs.
- Medium: digits.
- Low: tone and platform habits.

**Native check:**
- Bengali or Western digits for Instagram captions in Kolkata?
- Is তুমি acceptable for brand voices?
- Paschimbanga Bangla Akademi spelling rules were not verified.

**Sources:** [2] [9] [10] [11] [16] [20] [21] [24] [28] [29] [30] [31] [32] [33] [34] [35]

---

### বাংলা (বাংলাদেশ) · Bengali (Bangladesh) — `bn-BD`

*Delta entry: only what differs from `bn-IN`.*

**Where it's used / platforms:**
- Ad-reach estimates for late 2025 [37]:
  - Facebook: about 64.0M
  - TikTok: about 56.2M adults
  - YouTube: about 49.8M
  - Instagram: about 9.2M
  - X: about 1.2M
- Speakers call the language বাংলা.

**Words that mark the region:**
- **Everyday vocabulary** leans Perso-Arabic: পানি, গোসল, খালা, ফুফু, দাওয়াত [31].
- **Greetings:** আসসালামু আলাইকুম is common [30]. Word choice follows religion and upbringing as well as country [31][34], so Hindu Bangladeshis may use নমস্কার and জল (Medium). Don't assume the writer's faith.

**Formats:**
- **Digits:** Bengali digits are dominant. Prothom Alo's homepage used Bengali digits only [29]. CLDR bn defaults to Bengali digits with ৳ after the amount (১,২৩,৪৫৬.০০৳) [9]. Writing টাকা after the number is also common (Low).
- **Calendar:** Pohela Boishakh is fixed on 14 April [35].
- **Key dates:** 21 February (Language Movement, International Mother Language Day) [30], 26 March and 16 December.

**Sensitivities:**
- **Cultural symbols are contested:** the Pohela Boishakh procession was renamed in 2025 and 2026 [36]. Use the current name.
- Keep 1971 and politics neutral. Avoid Indian framing (₹, Kolkata slang).
- Microsoft publishes no bn-BD style guide [7].

**Search aliases:** Bangla, বাংলা, Bangladeshi Bengali, Bengali (Bangladesh), Dhaka Bangla, প্রমিত বাংলা

**Prompt guide (≤120 words):** Write Bangladeshi standard Bangla: use পানি, গোসল, খালা, ফুফু, দাওয়াত where a Bangladeshi writer would, but don't add religious greetings the brief doesn't ask for. Use Bengali digits and টাকা or ৳, with লাখ/কোটি. End sentences with ।. Use Bangladesh's calendar (Pohela Boishakh on 14 April). Avoid Kolkata slang and Indian references. Keep 1971, national symbols and politics neutral and factual.

**Confidence:** High: vocabulary, digits. Medium: platforms, calendar. Low: ৳ placement.

**Native check:**
- ৳ before or after the number?
- Bangla Academy spelling rules for loanwords were not verified.

**Sources:** [7] [9] [29] [30] [31] [34] [35] [36] [37]

---

### தமிழ் · Tamil (India) — `ta-IN`

**Where it's used / platforms:**
- Tamil Nadu and Puducherry.
- **Sri Lanka and Singapore:** Tamil is official in both [38]. Sri Lankan Tamil is more conservative and keeps older words and forms [43], so avoid Chennai slang for Jaffna readers. Consider separate `ta-LK` and `ta-SG` entries.
- Tamil feeds exist on ShareChat and Moj [20][21], and Tamil was among ShareChat's most active languages in 2018 [22].

**Script & spelling:**
- **Grantha letters** (ஜ ஷ ஸ ஹ ஸ்ரீ) write sounds borrowed from Sanskrit and other languages [38].
- **Purism:** the Pure Tamil movement replaced many Sanskrit words, and some readers still prefer native Tamil terms [38].
- **The ஃ letter** helps write foreign sounds such as f (ஃபேஸ்புக், *illustrative*).
- **Latin-script names** take Tamil suffixes after a hyphen (Instagram-இல்) [3].
- **Register:** Tamil is diglossic. Written/literary Tamil (centamil) is used for formal writing and news; spoken Tamil (koṭuntamil) dominates cinema, TV and popular media [38][39].

**Punctuation & typography:** English punctuation and the full stop [3], as seen on BBC Tamil [29]. Microsoft advises hyphens rather than en or em dashes [3].

**Words that mark the region:** written versus spoken (*illustrative*)

| Written | Spoken (captions, reels) | Gloss |
|---|---|---|
| இருக்கிறது | இருக்கு | there is |
| வருகிறேன் | வரேன் | I'm coming |
| அவர்கள் | அவங்க | they |
| நீங்கள் | நீங்க | you (polite) |
| என்ன செய்கிறீர்கள்? | என்ன பண்றீங்க? | what are you doing? |

**Particles, interjections & fillers (*illustrative*):** -ஆ (question), -ஏ (emphasis), -உம் ("also"), -ங்க (polite ending), பா (*pa*, friendly), அய்யோ (*aiyo*), சூப்பர், செம (*sema*, "superb") [44], மொக்க (*mokka*, "lame") [44].

**Formality & address:**
- **Address followers as நீங்கள்/உங்கள்.** Microsoft marks நீ/உனக்கு as incorrect [3]. On social, use the spoken நீங்க.
- **Third person:** use அவர் rather than அவன் or அவள் [3][41].
- **Gender:** first-person verbs don't mark gender (நான் வந்தேன்), but third-person verbs do (வந்தான் / வந்தாள் / வந்தார்) (Medium). The intimate vocatives டா and டி are gendered, so avoid them.

**Mixing languages:**
- **Tanglish** means both Tamil–English code-mixing and Tamil written in Latin letters [40].
- **Pattern:** English verb + பண்ணு (share பண்ணுங்க, "please share"), or Tamil case endings on English words [40].
- Advertisers use it [40].

**Tone & humour on social:** film-dialogue memes, wordplay and Chennai slang [44], plus pride in Tamil (Low).

**Platform habits:** greetings for தைப் பொங்கல் (mid-January) and தமிழ்ப் புத்தாண்டு (14 April), e.g. இனிய பொங்கல் நல்வாழ்த்துகள் ("happy Pongal", *illustrative*).

**Formats:**
- **Western digits.** Tamil numerals are traditional only [38], and news sites use Western digits [29].
- **Money and large numbers:** ₹ before the amount with lakh grouping [9]; லட்சம் / கோடி [24].
- **Dates:** d/M/yy [9].

**Names of people & works:** Wikidata gives பேத்தோவன் and மோட்ஸார்ட் [28]. Some writers avoid Grantha letters in names.

**Sensitivities:**
- **Hindi imposition is the top risk.** Agitations in 1937–40 and 1965 shaped state politics, and parties protested a 2014 order giving Hindi priority on government social media [42]. Never use Hindi words, Hindi greetings or "national language" framing.
- **Sanskrit versus Tamil purism** [38].
- Keep caste identity and Sri Lankan Tamil politics out.

**Search aliases:** Tamil, தமிழ், Tamizh, Thamizh, Tanglish, Roman Tamil, Tamil (India), Chennai Tamil

**Prompt guide (≤120 words):** Pick one register per post: clear modern written Tamil for announcements, and spoken forms (இருக்கு, பண்ணலாம், நீங்க) for creator captions and reels. Don't mix the two in one sentence. Address followers as நீங்க/நீங்கள், never நீ, and avoid gendered டா/டி. Tanglish is natural: English word + பண்ணுங்க, or Latin brand names with a hyphen and a Tamil suffix. Never use Hindi words or Hindi festival greetings. Use Tamil festival names. Write Western digits, ₹ before amounts, and லட்சம்/கோடி.

**Confidence:**
- High: address forms, sensitivities, digits.
- Medium: written/spoken table, gender.
- Low: humour and platform habits.

**Native check:**
- How to spell spoken forms (பண்றீங்க vs பண்ணுறீங்க).
- வாழ்த்துகள் vs வாழ்த்துக்கள் for brands.
- How far Tanglish goes in brand captions.

**Sources:** [3] [9] [20] [21] [22] [24] [28] [29] [38] [39] [40] [41] [42] [43] [44]

---

### తెలుగు · Telugu — `te-IN`

**Where it's used / platforms:**
- Andhra Pradesh and Telangana.
- Telugu was among ShareChat's most active languages in 2018 [22], and among those dominating political images there in 2019 [23].
- ShareChat and Moj both carry it [20][21].

**Script & spelling:**
- The standard is based on the central (Coastal Andhra) dialect. Telangana speech shows Persian and Arabic influence [45].
- News sites put a ZWNJ after a final virama before a suffix, as with English names + -కు [29]. Keep it.

**Punctuation & typography:** full stop and commas, as on BBC Telugu [29].

**Words that mark the region:** formal versus natural (Microsoft [4])

| Formal | Natural | Gloss |
|---|---|---|
| చేయగల సామర్థ్యం ఉంది | చేయగలరు | can do |
| ఇదేకాకుండా | అదనంగా / కూడా | also |

**Particles, interjections & fillers (*illustrative*):** కదా (*kadaa*, "right?"), -అండి (polite ending), అబ్బా (*abbaa*), సూపర్.

**Formality & address:**
- **Address followers as మీరు,** as Microsoft does [4]. మీరు is also the plural "you" [46]; నువ్వు is intimate.
- **Gender:** first-person verbs aren't gendered (వెళ్ళాను), but third-person ones are (వెళ్ళాడు / వెళ్ళింది) [46]. Use వారు or name + గారు when gender is unknown.

**Mixing languages:** English words in Telugu script + చేయండి (షేర్ చేయండి, "please share", *illustrative*). Microsoft accepts transliterated English [4].

**Tone & humour on social:** film-dialogue memes, family and festival warmth (Low).

**Platform habits:** greetings for Sankranti and Ugadi, and Bathukamma posts in Telangana (Low).

**Formats:** Western digits [29]; ₹ first with lakh grouping; లక్ష / కోటి [9][24]. CLDR's short date format is dd-MM-yy [9].

**Names of people & works:** Wikidata uses బీథోవెన్ and మొజార్ట్ [28].

**Sensitivities:** don't rank Andhra or Telangana speech as more "correct" (Low). Avoid caste surnames as descriptors.

**Search aliases:** Telugu, తెలుగు, Tenglish, Roman Telugu, Telugu (India)

**Prompt guide (≤120 words):** Write modern standard Telugu as used in news and film, not old literary (grānthika) Telugu. Address followers as మీరు; use నువ్వు only if the profile does. For third persons of unknown gender, use వారు or name + గారు. English words may appear in Telugu script with చేయండి; keep the ZWNJ after a final virama before a suffix. Use Western digits, ₹ before amounts and లక్ష/కోటి. Respect both Andhra and Telangana speech.

**Confidence:**
- High: address forms, digits.
- Medium: ZWNJ practice.
- Low: fillers, tone, Andhra–Telangana sensitivities.

**Native check:**
- How natural are Telangana forms in brand posts?
- Which vocatives are gendered?

**Sources:** [4] [9] [20] [21] [22] [23] [24] [28] [29] [45] [46]

---

### मराठी · Marathi — `mr-IN`

**Where it's used / platforms:**
- Maharashtra and Goa. The standard follows print and academic usage, historically Pune [47].
- ShareChat and Moj have Marathi feeds [20][21].

**Script & spelling:**
- **Script:** Balbodh-style Devanagari, which keeps some vowel sounds Hindi drops [47]. Uses ळ; the eyelash ra is encoded with ऱ or ZWJ [10].
- **Loanwords differ from Hindi:** व्ह for v and झ for z (बीथोव्हेन, मोझार्ट; Hindi writes मोज़ार्ट) [28].

**Punctuation & typography:** full stop, not a danda [5][29]; “ ” or ‘ ’ quotes [5].

**Words that mark the region (*illustrative*):** आहे ("is"), खूप ("very"), काय ("what"). Hindi है or बहुत is an instant giveaway. Captions use spoken contractions (आलाय, करतोय).

**Particles, interjections & fillers (*illustrative*):** ना, रे (vocative), अरे, बरं (*bara*, "okay"), मस्त and भारी ("great").

**Formality & address:**
- **Pronouns:** तू / तुम्ही / आपण. आपण is very formal and also means inclusive "we" [48]. Microsoft uses आपण [5]; social brands often use तुम्ही (Low).
- **Gender:** first- and second-person verbs mark it [48] (मी गेलो/गेले). Neutral option: मला खूप आवडलं ("I loved it", *illustrative*).

**Mixing languages:** assimilated English nouns (पेन, शर्ट) [47].

**Tone & humour on social:** local pride and festival nostalgia (Low).

**Platform habits:** posts for Gudi Padwa, Ganeshotsav and Marathi Bhasha Din (27 February) [47].

**Formats:** CLDR defaults to Devanagari digits [9]; Lokmat and Loksatta mix both, BBC Marathi uses Western [29]. Use one system per post. ₹; लाख / कोटी [24].

**Names of people & works:** use Marathi spellings (बीथोव्हेन, मोझार्ट) [28].

**Sensitivities:**
- Marathi's classical-language status (October 2024) is a point of pride [47].
- Hindi-flavoured Marathi grates; Marathi versus Hindi is live in Mumbai (Low). Keep caste out.

**Search aliases:** Marathi, मराठी, Minglish, Roman Marathi, Marathi (India)

**Prompt guide (≤120 words):** Write real Marathi, not Hindi in Devanagari: use आहे, खूप, काय and Marathi loan spellings (व्हिडिओ, मोझार्ट). Address followers as तुम्ही; keep आपण for very formal notices, since it can also mean "we". Never guess the writer's gender: avoid मी गेलो/गेले and करतो/करते; use मला…आवडलं or noun phrases. End sentences with a full stop, not a danda. Use one digit system per post, ₹ before amounts, and लाख/कोटी.

**Confidence:**
- High: script, address forms, gender.
- Medium: digits.
- Low: brand pronoun choice, tone, Mumbai sensitivities.

**Native check:**
- तुम्ही or आपण for brand Instagram?
- Are Devanagari digits still expected on social?

**Sources:** [5] [9] [10] [20] [21] [24] [28] [29] [47] [48]

---

### اردو · Urdu (Pakistan) — `ur-PK`

**Where it's used / platforms:**
- Pakistan's national language.
- Ad reach, late 2025: TikTok 79.9M adults, YouTube 54.3M, Facebook 52.9M [56].
- X was blocked from February 2024 to May 2025 [55].
- No Urdu on ShareChat or Moj [20][21].
- Standards body: National Language Promotion Department [53].

**Script & spelling:** Perso-Arabic, RTL, Nastaliq [49]. Devices without Nastaliq fall back to Naskh [49]; iOS 11+ ships Noto Nastaliq [50].

**Punctuation & typography:**
- **Use ۔ ، ؟ ؛, not Latin marks** [49]. Microsoft notes Urdu "does not use full stop" [6], and BBC Urdu follows this [29].
- No em dash [6].
- Put Latin hashtags and links on the last line so RTL text doesn't reorder them (practical note).

**Words that mark the region:** ornate versus modern (Microsoft [6])

| Ornate | Modern | Gloss |
|---|---|---|
| کیجئے | کریں | do (polite) |
| گراں قدر معلومات | اہم معلومات | important info |

**Particles, interjections & fillers (*illustrative*):** یار, بس, واہ, ارے; ماشاءاللہ (praise), ان شاء اللہ (plans).

**Formality & address:**
- **Pronouns:** تو / تم / آپ [12]; use آپ for brands [6].
- **Gender:** Microsoft prefers مجھے سمجھ آ گئی over میں سمجھ گئی, and ہم … چاہتے ہیں over a feminine first-person verb [6].

**Mixing languages:**
- English loans take Urdu grammar (ایپ, ویب سائٹیں) [6].
- **Roman Urdu** is informal and spelled irregularly [51], and common even though Urdu keyboards exist [16][57]. Candidate `ur-Latn-PK` entry.

**Tone & humour on social:** poetic couplets, cricket, family occasions (Low).

**Platform habits:** عید مبارک and رمضان مبارک greetings; 14 August posts (*illustrative*).

**Formats:**
- **Digits:** Western, as in BBC Urdu, Jang and Express [29]; also CLDR's default [9].
- **Grouping is disputed:** CLDR uses 1,234,567 [9], but Wikipedia says Pakistan officially uses lakh/crore [24].
- **Money and dates:** "Rs 500" [52]; 16 ستمبر، 2026 [9].

**Names of people & works:** Wikidata uses بیتھوون and موزارٹ [28].

**Sensitivities:**
- **Hindi–Urdu identity** [14].
- **Religion:** add ﷺ after the Prophet's name; many find leaving it out disrespectful [54]. Avoid sectarian labels.
- **Kashmir:** each side uses different terms [26].

**Search aliases:** Urdu, اردو, Pakistani Urdu, Urdu (Pakistan), Roman Urdu, Nastaliq Urdu

**Prompt guide (≤120 words):** Write modern Pakistani Urdu in Urdu script, using everyday words (کریں، اہم) rather than ornate forms (کیجئے، گراں قدر). End sentences with ۔ and use ، and ؟. Address followers as آپ. Never guess the writer's gender: prefer مجھے … لگا or ہم … چاہتے ہیں. Use Western digits, "Rs" before amounts, and لاکھ/کروڑ. Put Latin hashtags and links on the final line. Add ﷺ after the Prophet's name. Avoid India–Pakistan and sectarian topics.

**Confidence:**
- High: punctuation, address forms, register.
- Medium: digits, platforms.
- Low: grouping, Android rendering, tone.

**Native check:**
- Grouping: 1,00,000 or 100,000?
- Is Roman Urdu acceptable for brand posts?
- How does Urdu render on Android Instagram?

**Sources:** [6] [9] [12] [14] [16] [20] [21] [24] [26] [28] [29] [49] [50] [51] [52] [53] [54] [55] [56] [57]

---

### Source list

1. Microsoft, Hindi Localization Style Guide. https://download.microsoft.com/download/2/b/5/2b543b85-0ed4-49a7-8b3a-98ffa7addcfb/hin-ind-StyleGuide.pdf
2. Microsoft, Bangla (India) Localization Style Guide. https://download.microsoft.com/download/3/a/c/3ac7e8b5-a15c-498e-a73e-c824a82b6347/ben-ind-StyleGuide.pdf
3. Microsoft, Tamil Localization Style Guide. https://download.microsoft.com/download/5/0/7/5076DAEA-8D54-4294-A1DE-B274230CEEC1/tam-tam-StyleGuide.pdf
4. Microsoft, Telugu Localization Style Guide. https://download.microsoft.com/download/3/9/2/39283c08-4592-4de9-b0fa-bccce6535cef/tel-ind-StyleGuide.pdf
5. Microsoft, Marathi Localization Style Guide. https://download.microsoft.com/download/4/8/8/4889f570-623c-4c8b-a42f-51d64e4474aa/mar-ind-StyleGuide.pdf
6. Microsoft, Urdu (Pakistan) Localization Style Guide. https://download.microsoft.com/download/d/a/0/da076f1d-0fc1-4336-9b9b-97159456bae9/urd-pak-StyleGuide.pdf
7. Microsoft Localization Style Guides index. https://github.com/MicrosoftDocs/globalization/blob/main/globalization/reference/microsoft-style-guides.md
8. Mozilla L10n Style Guide, Hindi (hi-IN). https://mozilla-l10n.github.io/styleguides/hi-IN/
9. Unicode CLDR JSON: numbers, currencies, ca-gregorian for hi, bn, bn-IN, ta, te, mr, ur. https://github.com/unicode-org/cldr-json
10. The Unicode Standard 18.0, Chapter 12 (South and Central Asia-I). https://www.unicode.org/versions/Unicode18.0.0/core-spec/chapter-12/
11. Wikipedia, Danda. https://en.wikipedia.org/wiki/Danda
12. Wikipedia, Hindustani grammar. https://en.wikipedia.org/wiki/Hindustani_grammar
13. Wikipedia, Hindi (Article 343; Sanskritised register). https://en.wikipedia.org/wiki/Hindi
14. Wikipedia, Hindi–Urdu controversy. https://en.wikipedia.org/wiki/Hindi%E2%80%93Urdu_controversy
15. Wikipedia, Hinglish (cites Palakodety, KhudaBukhsh & Jayachandran 2021; Times of India 2011). https://en.wikipedia.org/wiki/Hinglish
16. Roark et al. (2020), Processing South Asian Languages Written in the Latin Script: the Dakshina Dataset, LREC. https://arxiv.org/abs/2007.01176
17. Rudra, Rijhwani, Bali & Choudhury (2016), Understanding Language Preference for Expression of Opinion and Sentiment: What do Hindi-English Speakers do on Twitter?, EMNLP. https://aclanthology.org/D16-1121.pdf
18. Bali, Sharma, Choudhury & Vyas (2014), "I am borrowing ya mixing?" An Analysis of English-Hindi Code Mixing in Facebook. https://aclanthology.org/W14-3914.pdf
19. Milestone Localization, Hinglish: A Report on Usage and Popularity in India (survey, 2020). https://www.milestoneloc.com/guide-to-hinglish-language/
20. Wikipedia, ShareChat. https://en.wikipedia.org/wiki/ShareChat
21. Wikipedia, Moj. https://en.wikipedia.org/wiki/Moj
22. Scroll.in (2018), ShareChat: the no-English social media app. https://scroll.in/article/897154/sharechat-the-no-english-social-media-app-that-indian-politicians-are-flocking-to
23. Agarwal, Garimella, Joglekar, Sastry & Tyson (2020), Characterising User Content on a Multi-lingual Social Network. https://arxiv.org/abs/2004.11480
24. Wikipedia, Indian numbering system. https://en.wikipedia.org/wiki/Indian_numbering_system
25. Wikipedia, Dalit (2018 I&B Ministry advisory). https://en.wikipedia.org/wiki/Dalit
26. Wikipedia, Kashmir conflict. https://en.wikipedia.org/wiki/Kashmir_conflict
27. DataReportal, Digital 2026: India. https://datareportal.com/reports/digital-2026-india
28. Wikidata labels and sitelinks: Q255 (Beethoven), Q254 (Mozart). https://www.wikidata.org/wiki/Q255 · https://www.wikidata.org/wiki/Q254
29. Author's character-level check of published text, 16 Sep 2026: bhaskar.com (homepage and one article), amarujala.com, navbharattimes.indiatimes.com, lokmat.com, loksatta.com, prothomalo.com, sangbadpratidin.in, eisamay.com, bartamanpatrika.com, eenadu.net, dinamani.com, dailythanthi.com, jang.com.pk, express.pk, and BBC Hindi, Marathi, Bengali, Tamil, Telugu and Urdu (homepages and one article each); plus the Unicode code points in [2].
30. Wikipedia, Bengali language. https://en.wikipedia.org/wiki/Bengali_language
31. Wikipedia, Bengali vocabulary. https://en.wikipedia.org/wiki/Bengali_vocabulary
32. Wikipedia, Bengali grammar. https://en.wikipedia.org/wiki/Bengali_grammar
33. Wikipedia, Bengali alphabet. https://en.wikipedia.org/wiki/Bengali_alphabet
34. Liberty Wingspan, "Bengali Bites: Pani vs. Jol". https://libertywingspan.com/52757/ae/bengali-bites-pani-vs-jol/
35. Wikipedia, Pohela Boishakh. https://en.wikipedia.org/wiki/Pohela_Boishakh
36. Wikipedia, Mangal Shobhajatra. https://en.wikipedia.org/wiki/Mangal_Shobhajatra
37. DataReportal, Digital 2026: Bangladesh. https://datareportal.com/reports/digital-2026-bangladesh
38. Wikipedia, Tamil language. https://en.wikipedia.org/wiki/Tamil_language
39. Wikipedia, Diglossia (Tamil). https://en.wikipedia.org/wiki/Diglossia
40. Wikipedia, Tanglish. https://en.wikipedia.org/wiki/Tanglish
41. Wikipedia, Tamil grammar. https://en.wikipedia.org/wiki/Tamil_grammar
42. Wikipedia, Anti-Hindi agitations of Tamil Nadu. https://en.wikipedia.org/wiki/Anti-Hindi_agitations_of_Tamil_Nadu
43. Wikipedia, Sri Lankan Tamil dialects. https://en.wikipedia.org/wiki/Sri_Lankan_Tamil_dialects
44. Wikipedia, Madras Bashai. https://en.wikipedia.org/wiki/Madras_Bashai
45. Wikipedia, Telugu language. https://en.wikipedia.org/wiki/Telugu_language
46. Wikipedia, Telugu grammar. https://en.wikipedia.org/wiki/Telugu_grammar
47. Wikipedia, Marathi language. https://en.wikipedia.org/wiki/Marathi_language
48. Wikipedia, Marathi grammar. https://en.wikipedia.org/wiki/Marathi_grammar
49. Wikipedia, Urdu alphabet. https://en.wikipedia.org/wiki/Urdu_alphabet
50. Wikipedia, Nastaliq (digital typography). https://en.wikipedia.org/wiki/Nastaliq
51. Wikipedia, Roman Urdu. https://en.wikipedia.org/wiki/Roman_Urdu
52. Wikipedia, Pakistani rupee. https://en.wikipedia.org/wiki/Pakistani_rupee
53. Wikipedia, National Language Promotion Department. https://en.wikipedia.org/wiki/National_Language_Promotion_Department
54. Wikipedia, Islamic honorifics. https://en.wikipedia.org/wiki/Islamic_honorifics
55. Wikipedia, Censorship of Twitter (Pakistan). https://en.wikipedia.org/wiki/Censorship_of_Twitter
56. DataReportal, Digital 2026: Pakistan. https://datareportal.com/reports/digital-2026-pakistan
57. The World (PRX), 15 Aug 2013, Pakistani scholars concerned that Urdu script being lost to technology. https://theworld.org/stories/2013/08/15/pakistani-scholars-concerned-urdu-script-being-lost-technology
58. Ansari, Ali & Khan (2020), Use of Roman Script for Writing Urdu Language, International Journal of Linguistics and Culture 1(2). http://ijlc.wum.edu.pk/index.php/ojs/article/download/20/25/44
59. FoneArena, Gboard now supports 22 Indian languages, gets transliteration (seen in search results). https://www.fonearena.com/blog/218344/gboard-now-supports-22-indian-languages-gets-transliteration-in-hindi-tamil-telugu-and-more.html

---

### Open questions

1. **Picker design.** `hi-Latn-IN` is recommended as its own entry. Should `ur-Latn-PK` (Roman Urdu), `ta-Latn-IN` (written Tanglish) and `bn-Latn` follow? Roman Hindi has figures [15][17][19]; the others are documented only qualitatively [16][40][51][58].
2. **Hindi full stop.** Microsoft uses "." and Mozilla uses ।, and news sites split too [1][8][29]. Should the default follow the writer's samples?
3. **Pakistani digit grouping.** CLDR's 1,234,567 conflicts with the "lakh/crore officially used" claim [9][24]. This needs a Pakistani source (State Bank or major newspapers).
4. **Bengali and Marathi digits.** CLDR defaults to native digits, but practice is mixed [9][29]. Is the default "match the voice profile, else native digits"?
5. **Marathi brand pronoun:** आपण (Microsoft) or तुम्ही (assumed on social)?
6. **Unverified standards.** The Central Hindi Directorate site was unreachable, and Bangla Academy / Paschimbanga Bangla Akademi spelling rules weren't checked. Tamil and Telugu state standards weren't consulted.
7. **ShareChat's English support.** Wikipedia lists English [20]; the 2018 report says it was dropped [22]. Check the current app.
8. **Nastaliq on Android social apps.** Does Instagram or WhatsApp on common Android phones show Urdu in Nastaliq or Naskh [49][50]? Consider pre-post image text for Urdu.
9. **Recent language-politics events** (three-language policy disputes after 2020) weren't verified. The drafting model should avoid language-politics topics entirely.
10. **Tamil variants.** Should `ta-LK` and `ta-SG` become separate entries, given Sri Lankan Tamil's conservatism [43]?
11. **Stray zero-width joiners.** Should PostRiff strip them from Indic hashtags at publish time [29]?


---

## Arabic, Hebrew & Persian

Research file 07 (Middle East & RTL), compiled 2026-09-16. Covers `ar`, `ar-EG`, `ar-SA` (+ `ar-AE`), `ar-LB` (+ JO/SY/PS), `ar-MA` (+ DZ/TN), `he-IL`, `fa-IR` (+ `fa-AF`), and whether Arabizi (`ar-Latn`) needs its own picker entry. Digits, separators, currency symbols, month names and week data come straight from Unicode CLDR JSON [5]. The session's web-search quota ran out partway through, so later checks relied on fetching known pages directly. Items that still needed a search are listed under "Native check".

### Family notes

**Diglossia in practice.** Every Arabic-speaking audience reads in two layers. Modern Standard Arabic (فصحى) is nobody's mother tongue; it is the language of print, news, law and school [10]. The dialect (عامية / دارجة) is what people actually post in. A 2025 study of a major Saudi news account on X found its own tweets were 78% standard-register, while replies to them were 88% colloquial [8]. Industry guides agree: use dialect for warmth with consumers, and MSA for authority or for reaching several countries at once, even though MSA then sounds formal and institutional [51][50]. For a drafting model the bigger risk runs the other way, because LLMs slide into MSA. A 2025 Saudi-dialect paper measured 32.6% "MSA leakage" in a baseline model's supposedly dialect output [9]. That is why every dialect prompt guide below includes an explicit "not MSA" instruction.

**Arabic varieties at a glance.** Spellings are illustrative, because online spelling isn't standardised.

| Locale | "what" | "now" | "I want" | "very" | "good / OK" | Negation | Future | "September" (CLDR) | Digits in common use | Largest platforms (ad reach, late 2025) |
|---|---|---|---|---|---|---|---|---|---|---|
| `ar` MSA | ماذا / ما | الآن | أريد | جدًا | جيد / حسنًا | لا، لم، لن، ليس | سـ / سوف | سبتمبر (or أيلول) | Western per Microsoft [1]; CLDR `ar` = Western [5] | depends on target markets |
| `ar-EG` | إيه | دلوقتي | عايز / عاوز | أوي | كويس | ما…ش، مش | هـ / حـ | سبتمبر | both [31]; CLDR default ٠١٢ [5] | Facebook 51.6M, YouTube 49.3M, TikTok 48.8M (18+); X 4.6M [44] |
| `ar-SA` | وش (Najdi) / إيش (Hijazi) | الحين / دحين | أبي / أبغى | مرة | زين / كويس | ما، مو | بـ / حـ (Hijazi) | سبتمبر | Western gaining [31]; CLDR default ٠١٢ [5] | TikTok 38.6M (18+), YouTube 27.5M, Snapchat 25.3M, X 15.0M [43] |
| `ar-AE` | شو | الحين | أبا / باغي | وايد | زين | مب / مش / ما | بـ / بيـ | سبتمبر | CLDR default Western [5] | TikTok 12.5M, LinkedIn 10.0M, Facebook 9.7M [48] |
| `ar-LB` | شو | هلّق / هلّأ | بدّي | كتير | منيح | ما، مش | رح (+ عم progressive) | أيلول | CLDR default ٠١٢ [5]; Western common (check) | Facebook 3.45M, Instagram 2.95M, TikTok 4.58M (18+) [46] |
| `ar-JO` | شو | هسّا | بدّي | كثير / كتير | منيح / كويس | ما، مش | رح / ح | أيلول | CLDR default ٠١٢ [5] | not collected |
| `ar-MA` | شنو / آش | دابا | بغيت | بزاف | مزيان | ما…ش | غادي / غا | شتنبر | Western only [31] | Facebook 22.8M, YouTube 21.6M, TikTok 16.7M (18+); X 1.1M [45] |
| `ar-DZ` | واش | (check) | نحب (check) | بزاف | مليح | ما…ش | راح / رايح | سبتمبر (جانفي، أوت) | Western [5] | not collected |
| `ar-TN` | شنوّة / شنيّة | توّة | نحب | برشا | باهي | ما…ش، موش | باش | سبتمبر (جانفي، أوت) | Western [5] | not collected |

Row sources: Egyptian [11]; Hijazi [15]; Najdi/Gulf [16][18][19]; Emirati [17]; Lebanese [13]; Jordanian [14]; Moroccan [20][21][24]; Algerian [22]; Tunisian [23]; month names and digit defaults [5].

**Two cheap region tells.**
- **Month names.** Egypt and the Gulf say يناير … سبتمبر. The Levant and Iraq say كانون الثاني … أيلول. Algeria and Tunisia say جانفي … أوت. Morocco says يناير، ماي، يوليوز، غشت، شتنبر [5]. A Cairo brand writing "٥ أيلول" is wrong on sight.
- **The letter "g" in foreign names.** Arabic Wikipedia labels Google جوجل and lists غوغل and قوقل as aliases. Egyptian Wikipedia writes the "J" of Jackson as چ, because ج is pronounced /g/ in Cairo. Moroccan Wikipedia uses ڭ (ڭووڭل) [42][11].

**RTL rendering checklist for the app**
1. **Base direction.** Set `dir` explicitly from the chosen locale in the composer, the preview and any export. With `dir="auto"`, a post that starts with a Latin brand name, @handle or digit lays out LTR, because paragraph direction comes from the first strong character [6].
2. **Isolate embedded LTR runs** (brand names, URLs, handles, codes) with `<bdi>` or FSI…PDI (U+2068…U+2069). UAX #9 recommends isolates over the older embeddings [6].
3. **Test neutral characters at run boundaries**: "!", "?", ")", quotes and a trailing emoji after a Latin word. They take the paragraph's direction and can jump to the wrong side [7].
4. **Plan for pasting into apps you don't control.** Avoid opening an RTL post with a Latin word or a number. If it can't be avoided, offer an optional leading RLM (U+200F) and test on each platform [6].
5. **Never strip** U+200C (ZWNJ; Persian needs it inside words), U+200E/U+200F, or U+0640 tatweel in sanitisers, trimming, dedupe or tokenisers [59].
6. **Don't normalise** Persian ی/ک (U+06CC/U+06A9) to Arabic ي/ك, or the reverse [60].
7. **Digit shape is a per-locale setting.** CLDR defaults (`ar-EG`/`ar-SA`/`ar-LB` → ٠١٢, `ar-AE`/`ar-MA` → 012, `fa` → ۰۱۲, `he` → 012) [5] don't always match social usage [1][31]. Never convert digits inside URLs, handles, phone numbers or codes.
8. **Hashtags can't contain spaces.** Multi-word Arabic, Hebrew and Persian tags use underscores (e.g. #رمضان_كريم), and punctuation stays outside the tag.
9. **Hebrew prefixes** before a Latin word or number take a hyphen (ב-Azure) [2]. Keep the pair together when wrapping lines.
10. **Fonts.**
    - Persian ۴۵۶ are separate code points from Arabic ٤٥٦ [60], and Moroccan text needs ڭ.
    - The Saudi riyal sign U+20C1 (Unicode 17.0) is still missing from many fonts [35].
    - The UAE dirham sign has no code point until Unicode 18.0 (U+20C3) [36].
    - Fall back to ر.س / د.إ or SAR / AED.
11. **Mirroring.** Mirror directional UI chrome, but not logos, media or digits.

**Confidence:** High for CLDR data, the bidi rules and the Saudi register study. Medium for the marker table, which draws on encyclopaedic summaries and dictionary entries. Platform figures are ad-reach estimates, not active users.

**Sources:** [1] [5] [6] [7] [8] [9] [10] [11] [13]–[24] [31] [35] [36] [42]–[48] [50] [51] [59] [60]. Full titles and URLs are in each entry's Sources and in the Source list at the end of Open questions.

---

### العربية الفصحى · Modern Standard Arabic (pan-Arab) — `ar`

**Where it's used / platforms:** MSA is the shared written standard of 20+ states, with no native speakers [10]. On social media it is used by news outlets, governments, NGOs, religious pages and pan-Arab brands. A Saudi news account posted in standard Arabic while its replies came back colloquial [8]. Choose `ar` for multi-country briefs, institutional topics or formal authors. It reads stiff in personal, humorous or reply-style posts, in single-market consumer promotions [51][50], and whenever it calques English [1].

**Script & spelling:** Arabic script, right to left. Leave out tashkeel unless a word would be ambiguous [1]. Get the initial hamza right (أ / إ / ا) [1], and keep ة / ه and ى / ي distinct.

**Punctuation & typography:**
- ، and ؟ with no space before and one after [1]; semicolon ؛.
- Straight quotes mark names and titles [1].
- Tatweel (ـ) is for justification or decoration [32]. In a post it works as a rare stylistic stretch (illustrative: مبـــروك, "congrats!"), and never inside hashtags.

**Words that mark the region:**

| Concept | `ar` (MSA) | Sibling locales |
|---|---|---|
| what | ماذا / ما | إيه (EG), وش / إيش (SA), شو (LB / AE), شنو (MA) |
| now | الآن | دلوقتي, الحين, هلّق, دابا |
| I want | أريد | عايز, أبي / أبغى, بدّي, بغيت |
| very | جدًا | أوي, مرة, كتير, بزاف |
| good | جيد | كويس, زين, منيح, مزيان |
| not / will | لا، لم، لن، ليس / سـ، سوف | مش / هـ, مو / بـ, مش / رح, ما…ش / غادي |

**Particles, interjections & fillers:** Few fillers; use connectors such as لكن، بل، إذن، أيضًا, preferring أيضًا to كذلك [1]. Use إن شاء الله and الحمد لله where a local writer would, not as decoration. No هههه.

**Formality & address:**
- "You" is gendered (أنتَ / أنتِ; تستطيع / تستطيعين).
- For mixed audiences use the plural (يمكنكم), a verbal noun (التسجيل متاح الآن) or a generic form (يُرجى…). Name both genders for roles (معلم ومعلمة) [1].
- Microsoft lists جماعة / شباب as non-inclusive stand-ins for "guys"; prefer الجميع [1].
- First-person adjectives reveal the author's gender (سعيد / سعيدة), so match the profile.

**Mixing languages:**
- Keep brand names in Latin script, without ال.
- In a genitive, put the Latin name after the Arabic noun (الجداول البيانية لبرنامج Excel) [1].
- No regional loans, such as Maghrebi French, in a pan-Arab post.

**Tone & humour on social:** Light, warm MSA with short sentences and the present tense [1]. Dialect punchlines break the register.

**Platform habits:** MSA on LinkedIn, YouTube descriptions and news-style X posts; Instagram and TikTok captions usually switch to each market's dialect [51].

**Formats:**
- **Digits.** Microsoft advises Western digits as "becoming standard almost all over the Arab World" [1], and CLDR `ar` agrees [5]. CLDR's Egypt, Saudi and Levant locales default to ٠١٢ with ٫ ٬ [5].
- **Formal counting.** Write 1 as a word, 2 as the dual (طالبان), and rephrase 0 (لا يوجد) [1].
- **Dates.** d/M/y [5]. The Hijri suffix is هـ; year 1448 began around 16 June 2026 [33].
- **Currency.** For pan-Arab posts, name the currency in words or use USD.

**Names of people & works:** Arabic Wikipedia labels include بيتهوفن, شوبان, باخ and موزارت (alias موتسارت) [42]. Foreign "g" appears as ج, غ or ق (جوجل / غوغل / قوقل) [42]; keep one spelling per post.

**Sensitivities:** Keep disputed places out of examples [1]. Arab states say "Arabian Gulf", while Iran and the UN say "Persian Gulf"; plain الخليج is neutral [40]. Western Sahara [41] and Palestine/Israel naming vary by market. For Ramadan, رمضان مبارك and رمضان كريم are both common [34].

**Search aliases:** Arabic, العربية, Arabi, Fusha, Fus'ha, فصحى, MSA, Modern Standard Arabic, Standard Arabic, pan-Arab, White Arabic

**Prompt guide (≤120 words):** Write clear, modern Standard Arabic, neither classical nor dialect. Keep sentences short, join them with و or ثم, and prefer the present tense. Use ، ؟ ؛ with no space before. Address mixed audiences in the plural (يمكنكم، تابعونا) or with verbal nouns; never default to masculine singular. Match the author's gender in first-person adjectives. Don't calque English: no قم بـ, الخاص بك or يتسنى لك. Keep brand names in Latin script without ال. Use Western digits unless house style differs. No dialect words, no هههه, no Arabizi. Use religious phrases only where a local writer naturally would.

**Confidence:** High for typography and address [1][5]. Medium for "when MSA reads stiff", which rests on one study [8] and two industry guides [50][51].

**Native check:** Digits in pan-Arab captions (Microsoft and CLDR disagree). «» vs "". Whether copywriters call this register "white Arabic". Any current objection to رمضان كريم.

**Sources:**
[1] Microsoft, Arabic Localization Style Guide: https://download.microsoft.com/download/5/6/d/56d1774f-ac3f-4ad9-80af-a6dfd5df419d/ara-sau-StyleGuide.pdf
[5] Unicode CLDR JSON (numbers, currencies, dates, weekData): https://github.com/unicode-org/cldr-json
[8] Alqahtani & Albawardi (2025), Levels of Arabic Language in Saudi Tweets: https://www.richtmann.org/journal/index.php/ajis/article/download/14200/13856/48335
[10] Wikipedia, Modern Standard Arabic: https://en.wikipedia.org/wiki/Modern_Standard_Arabic
[32] Wikipedia, Kashida: https://en.wikipedia.org/wiki/Kashida
[33] Wikipedia, Islamic calendar: https://en.wikipedia.org/wiki/Islamic_calendar
[34] Wikipedia, Ramadan: https://en.wikipedia.org/wiki/Ramadan
[40] Wikipedia, Persian Gulf naming dispute: https://en.wikipedia.org/wiki/Persian_Gulf_naming_dispute
[41] Wikipedia, Western Sahara: https://en.wikipedia.org/wiki/Western_Sahara
[42] Wikidata labels, e.g. Beethoven Q255, Chopin Q1268, Mozart Q254, Google Q95: https://www.wikidata.org/wiki/Q255
[50] Multi Marketer, Social Media Marketing in Egypt: Complete 2026 Guide: https://multi-marketer.com/en/social-media-marketing-egypt-complete-guide/
[51] 23HubLab, Scaling Paid Ads Across Arabic-Speaking Markets: https://23hublab.com/scaling-paid-ads-across-arabic-speaking-markets/

---

### مصري · Egyptian Arabic — `ar-EG`

**Where it's used / platforms:** Cairo-based Egyptian Arabic is written in Arabic script for local readers and appears in novels, comics, advertising and some newspapers [11]. Egyptian film and TV made it the most widely understood dialect in the region [11]. Facebook is the largest platform (51.6M), followed by YouTube (49.3M), TikTok (48.8M adults) and Messenger (37.0M); X is small at 4.6M [44]. Brands use عامية for mass-market posts, فصحى for corporate and press content, and English or a mix for premium audiences [50].

**Script & spelling:**
- Spelled close to speech: دلوقتي، إيه، كده، ده / دي.
- ج is pronounced /g/, and ق is usually a glottal stop in speech but kept as ق in writing [11].
- The j sound of foreign names may be written چ [42].
- Casual typing often drops hamza (انا) and writes final ي as ى (فى) (check).

**Punctuation & typography:** Same as `ar`. Casual posts stack marks (!!؟) and repeat letters (illustrative: حلوووو, "so nice"); use both sparingly.

**Words that mark the region:**

| Concept | `ar-EG` | Sibling locales |
|---|---|---|
| what | إيه | شو (LB), وش / إيش (SA), شنو (MA) |
| now | دلوقتي | هلّق, الحين, دابا |
| I want | عايز / عايزة | بدّي, أبي / أبغى, بغيت |
| very | أوي | كتير, مرة, بزاف |
| good | كويس | منيح, زين, مزيان |
| not | مش / ما…ش (ماعرفش) | مش, مو, ما…ش |
| will | هـ (هنبدأ) | رح, بـ, غادي |
| this | ده / دي | هيدا, هذا, هاد |
| bread | عيش | خبز (MSA) [42] |

**Particles, interjections & fillers:** Illustrative: يا جماعة ("folks"), يعني, خلاص, بجد ("seriously"), طب ("so / well"), يلا. Laughter is هههه. إن شاء الله and الحمد لله are used where the meaning fits.

**Formality & address:**
- "You" (إنت / إنتي) and participles (عايز / عايزة) are gendered.
- First-person forms reveal the author's gender (مبسوط / مبسوطة); take it from the profile, never default to male.
- For mixed audiences use the plural imperative (illustrative: جرّبوا، قولولنا, "try it", "tell us").
- حضرتك gives a polite service tone (check how often brands use it).

**Mixing languages:** Brands commonly mix Arabic with English [50]. Young people use Latin-script "Franco" with English-style spellings [25][26]. In drafts, stick to established loans (illustrative: أونلاين، لايف، أوفر) unless the author writes Franco.

**Tone & humour on social:** Quick and self-aware, with meme captions and comment-bait questions (illustrative: "إنتوا فريق إيه؟", "which team are you?"). Film one-liners (إفيهات) are a shared reference pool (check).

**Platform habits:** Facebook for long, comment-driven captions; TikTok and Reels for short hooks in عامية. X is minor [44].

**Formats:**
- **Currency.** EGP is ج.م. or E£ [5]; in text write جنيه.
- **Digits.** CLDR defaults to ٠١٢ with ٫ ٬ [5], but Egypt uses both systems [31].
- **Dates and time.** d/M/y and a 12-hour clock [5].
- **Week.** Starts Saturday, with a Friday–Saturday weekend [5] and a Sunday–Thursday workweek [39].
- **Calendars.** CLDR lists the Coptic calendar for Egypt too [5].

**Names of people & works:** Egyptian Wikipedia writes بيتهوفين and موتسارت (MSA: بيتهوفن), plus جوجل and انستجرام [42].

**Sensitivities:** Avoid political commentary unless the brief requires it. Egypt is Muslim-majority with a Coptic Christian community, so greet both communities' holidays correctly; Coptic Christmas is 7 January.

**Search aliases:** Egyptian, Egyptian Arabic, مصري, مصرى, المصرية, Masri, Masry, Ammiya, عامية مصرية, 3amya, Cairene, Egypt, Franco

**Prompt guide (≤120 words):** Write in Egyptian colloquial (عامية مصرية) in Arabic script, not MSA; if a sentence could run in a newspaper, rewrite it. Use Egyptian markers naturally: إيه، دلوقتي، عايز/عايزة، أوي، كويس، ده/دي، مش, and future هـ (هنبدأ). Match the author's gender in first-person forms (مبسوط/مبسوطة). Address mixed audiences in the plural (جرّبوا، قولولنا). Light English loans are fine (أونلاين، لايف). Never use Levantine or Gulf words (شو، هلق، وش، الحين). Give prices in جنيه. Keep humour quick and self-aware, and use religious phrases only where they fit.

**Confidence:** Medium-High. Markers [11], platforms [44], brand register from industry sources [50].

**Native check:** ى-for-ي and dropped hamza in brand captions. حضرتك in brand posts. Digit style in online prices. Whether writers use هـ or حـ for the future.

**Sources:**
[5] Unicode CLDR JSON: https://github.com/unicode-org/cldr-json
[11] Wikipedia, Egyptian Arabic: https://en.wikipedia.org/wiki/Egyptian_Arabic
[25] Wikipedia, Arabic chat alphabet: https://en.wikipedia.org/wiki/Arabic_chat_alphabet
[26] Shehadi & Wintner (2022), Identifying Code-switching in Arabizi: https://aclanthology.org/2022.wanlp-1.18.pdf
[31] Wikipedia, Eastern Arabic numerals: https://en.wikipedia.org/wiki/Eastern_Arabic_numerals
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[42] Wikidata labels (Q255, Q254, Q95, Q209330, Q7802, Q2831): https://www.wikidata.org/wiki/Q7802
[44] DataReportal, Digital 2026: Egypt: https://datareportal.com/reports/digital-2026-egypt
[50] Multi Marketer, Social Media Marketing in Egypt 2026: https://multi-marketer.com/en/social-media-marketing-egypt-complete-guide/

---

### سعودي / خليجي · Saudi (Gulf) Arabic, with UAE note — `ar-SA`

**Where it's used / platforms:** Saudi Arabia has Najdi, Hijazi, Eastern, Southern and Northern dialects [8]. Urban Riyadh Najdi carries the prestige [16], and Jeddah and Mecca speak Hijazi [15]. Platform reach [43]:
- TikTok 38.6M (18+), YouTube 27.5M, Snapchat 25.3M.
- X reaches 15.0M, about 43% of the population, which makes it a real public square.

News accounts post in MSA, and replies come back in dialect [8]. Brands use dialect for warmth and MSA to signal professional authority [51]. In the 2017 Arab Youth Survey, 68% of Gulf youth spoke English daily, yet 90% called Arabic central to their identity [30].

**Script & spelling:**
- Arabic script, with dialect spellings: وش، إيش، أبي، أبغى، الحين، دحين، مرة، زين، مو.
- Najdi [ts]/[dz] for k/g [16] is rarely spelled out.
- Informal loans may write "g" as ق (قوقل) [42].

**Punctuation & typography:** Same as `ar`.

**Words that mark the region:**

| Concept | `ar-SA` (Najdi · Hijazi) | Sibling locales |
|---|---|---|
| what | وش · إيش [18][15] | شو (AE / LB), إيه (EG) |
| now | الحين · دحين [15] | الحين (AE), هلّق, دلوقتي |
| I want | أبي · أبغى [15] | أبا / باغي (AE) [17], بدّي, عايز |
| very | مرة [19][15] | وايد (AE) [17], كتير, أوي |
| good | زين · كويس [15] | زين (AE), منيح |
| not | ما · مو [15] | مب / مش (AE) [17], مش |
| will | بـ · حـ [15] | بـ / بيـ (AE) [17], رح, هـ |
| why / where | ليش · فين [15] | ليه (EG), وين (LB) |

**Particles, interjections & fillers:** Illustrative: والله، يعني، خلاص، يا هلا، حيّاكم ("welcome"), تكفى ("please, I beg you"; Najdi). Laughter is هههه; خخخ is reported for the Gulf (check) [68].

**Formality & address:**
- "You" is gendered, and first-person adjectives carry the author's gender (مبسوط / مبسوطة).
- Brands address audiences in the plural (illustrative: حيّاكم، اطلبوا).
- Don't use Egyptian حضرتك. Gulf respect phrases differ (illustrative: طال عمرك, "may your life be long"; check).

**Mixing languages:** English enters business and tech posts. Arabizi is a Saudi youth code, driven partly by keyboard habits and not used with parents [29]. Keep drafts in Arabic script.

**Tone & humour on social:** Replies on X are the most openly colloquial space [8]. Football and national occasions drive hashtag waves. The hospitality register (يا هلا، حيّاكم) suits brand welcomes.

**Platform habits:** X for news and trends, Snapchat for everyday diary-style content, TikTok for the widest reach [43].

**Formats:**
- **Currency.** SAR is ر.س. [5]. The new riyal sign (February 2025) is U+20C1 in Unicode 17.0, but fonts lag [35]; write ريال or ر.س.
- **Digits.** CLDR defaults to ٠١٢ with ٫ ٬ [5], but Western digits are increasingly favoured [31] and Microsoft uses them [1].
- **Calendars.** Gregorian plus Umm al-Qura Hijri [5]. Government salaries moved to the Gregorian calendar in 2016; Hijri stays for religious purposes [33].
- **Week.** Starts Sunday, with a Friday–Saturday weekend [5][39].

**UAE note (`ar-AE`):**
- **Markers.** شو، الحين، أبا / باغي، وايد، زين. Negation is مب in the north, مش in Abu Dhabi and ما on the east coast. Future is بـ / بيـ [17].
- **Audience.** Expat-heavy: LinkedIn's reach (10.0M) tops Facebook's (9.7M) [48]. English-first brand posts with Arabic versions are common.
- **Formats.** AED is د.إ / Dhs. The 2025 dirham sign waits for U+20C3 in Unicode 18.0 [36]. CLDR defaults to Western digits, a Monday week start and a Saturday–Sunday weekend [5].

**Names of people & works:** Same as `ar`. Informal loans may write g as ق [42].

**Sensitivities:** Write الخليج العربي or الخليج, never "Persian Gulf" [40]. Keep religion, the royal family and government beyond commentary or jokes. Imagery tends conservative (check category norms).

**Search aliases:** Saudi, Saudi Arabic, سعودي, اللهجة السعودية, Gulf Arabic, Khaleeji, خليجي, Najdi, نجدي, Hijazi, Hejazi, حجازي, Emirati, إماراتي, UAE Arabic

**Prompt guide (≤120 words):** Write in Saudi colloquial as used on X and Snapchat, in Arabic script, not MSA; if a line sounds like a news bulletin, rewrite it. Default to the urban Riyadh (Najdi) voice, or Hijazi if the author is from Jeddah or Mecca. Use وش/إيش، الحين، أبي/أبغى، مرة (very)، زين، مو, and future بـ. Never mix in Egyptian or Levantine words (إيه، دلوقتي، شو، هلق). Match the author's gender in first person. Address audiences in the plural (حيّاكم، جرّبوا). Write الخليج. Give prices in ريال.

**Confidence:** Medium. High for register [8] and formats [5][35]. Medium for Najdi markers, which come from dictionary entries [18][19]; Hijazi is better documented [15].

**Native check:** Najdi أبي / وين / بـ-future as defaults. خخخ in KSA today. Digits in brand captions. UAE brand default: Emirati, MSA or English.

**Sources:**
[1] Microsoft, Arabic Localization Style Guide: https://download.microsoft.com/download/5/6/d/56d1774f-ac3f-4ad9-80af-a6dfd5df419d/ara-sau-StyleGuide.pdf
[5] Unicode CLDR JSON: https://github.com/unicode-org/cldr-json
[8] Alqahtani & Albawardi (2025), Levels of Arabic Language in Saudi Tweets: https://www.richtmann.org/journal/index.php/ajis/article/download/14200/13856/48335
[15] Wikipedia, Hejazi Arabic: https://en.wikipedia.org/wiki/Hejazi_Arabic
[16] Wikipedia, Najdi Arabic: https://en.wikipedia.org/wiki/Najdi_Arabic
[17] Wikipedia, Emirati Arabic: https://en.wikipedia.org/wiki/Emirati_Arabic
[18] Wiktionary, وش: https://en.wiktionary.org/wiki/وش
[19] Wiktionary, مرة: https://en.wiktionary.org/wiki/مرة
[29] A Sociolinguistic Analysis of the Use of Arabizi in Social Media Among Saudi Arabians (seen in search results): https://www.researchgate.net/publication/336867106_A_Sociolinguistic_Analysis_of_the_Use_of_Arabizi_in_Social_Media_Among_Saudi_Arabians
[30] Arab News, Arabic still vital, but English used daily, poll finds (Arab Youth Survey 2017): https://www.arabnews.com/node/1094121/middle-east
[31] Wikipedia, Eastern Arabic numerals: https://en.wikipedia.org/wiki/Eastern_Arabic_numerals
[33] Wikipedia, Islamic calendar: https://en.wikipedia.org/wiki/Islamic_calendar
[35] Wikipedia, Saudi riyal: https://en.wikipedia.org/wiki/Saudi_riyal
[36] Wikipedia, United Arab Emirates dirham: https://en.wikipedia.org/wiki/United_Arab_Emirates_dirham
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[40] Wikipedia, Persian Gulf naming dispute: https://en.wikipedia.org/wiki/Persian_Gulf_naming_dispute
[42] Wikidata label for Google (Q95): https://www.wikidata.org/wiki/Q95
[43] DataReportal, Digital 2026: Saudi Arabia: https://datareportal.com/reports/digital-2026-saudi-arabia
[48] DataReportal, Digital 2026: United Arab Emirates: https://datareportal.com/reports/digital-2026-united-arab-emirates
[51] 23HubLab, Scaling Paid Ads Across Arabic-Speaking Markets: https://23hublab.com/scaling-paid-ads-across-arabic-speaking-markets/
[68] NaTakallam, How People Express Laughter in Different Languages (seen in search results): https://natakallam.com/blog/how-people-express-laughter-in-different-languages/

---

### لبناني · Lebanese (Levantine) Arabic — `ar-LB`

**Where it's used / platforms:** Beirut-centred North Levantine. Levantine makes up 12–23% of vernacular Arabic content online [12]. Facebook (3.45M) and Instagram (2.95M) are close, TikTok reaches 4.58M adults, and X is small at 555K [46].

**Script & spelling:** Arabic script for public posts; Arabizi is strong in informal writing [13][25]. The glottal stop is spelled ق or أ (هلّق / هلّأ) [13].

**Punctuation & typography:** Same as `ar`.

**Words that mark the region:**

| Concept | `ar-LB` [13] | Sibling locales |
|---|---|---|
| what / now | شو / هلّق | إيه / دلوقتي (EG); شو / هسّا (JO) [14] |
| I want / very / good | بدّي / كتير / منيح | عايز / أوي / كويس (EG) |
| not / will / -ing | مش، ما / رح / عم | مش / هـ / بـ (EG) |
| this | هيدا / هيدي | ده (EG), هاد (MA) |
| September | أيلول [5] | سبتمبر (EG / SA), شتنبر (MA) |

**Particles, interjections & fillers:** Illustrative: يلّا، خلص ("done"), ولو ("of course"), شو في؟ ("what's up?"). French and English words drop into sentences (merci, bravo) [13].

**Formality & address:** Same gender rules as `ar`. Match the author's first-person gender and address audiences in the plural (جرّبوا).

**Mixing languages:** Switching between Arabic, French and English is an everyday norm ("Hi, kifak, ça va?") [13]. One or two Latin-script words per post is natural; write whole English sentences only if the author does.

**Tone & humour on social:** Wry. Multilingual jokes only work if the switching feels native.

**Platform habits:** Instagram is nearly on par with Facebook [46].

**Formats:** LBP is ل.ل. and people say ليرة (check) [5]. The economy is heavily dollarised [37], so $ prices are common (check). CLDR defaults to ٠١٢ digits [5]. Weekend Saturday–Sunday [5][39].

**Names of people & works:** Same as `ar`.

**Sensitivities:** Sectarian politics, the conflict with Israel and refugees are all charged, so take no sides. Mark both Christian and Muslim holidays.

**Jordan / Syria / Palestine notes:** Jordan uses هسّا for "now" and كويس (urban) vs منيح (rural) [14], with a Saturday week start [5]. Damascus writing is close to Lebanese [12]. For Palestinian audiences use فلسطين. All three use Levantine month names [5].

**Search aliases:** Levantine, Lebanese, لبناني, Libnani, Lebnani, Shami, شامي, Syrian, سوري, Jordanian, أردني, Palestinian, فلسطيني, Levant

**Prompt guide (≤120 words):** Write in Lebanese colloquial in Arabic script, not MSA. Use شو، هلّق، بدّي، كتير، منيح، هيدا/هيدي، مش, future رح and progressive عم. One or two French or English words in Latin script are natural (merci, weekend), but no full English sentences unless the author writes them. Match the author's gender in first person; address audiences in the plural. Use Levantine month names (أيلول). No Egyptian or Gulf words.

**Confidence:** Medium. Markers are documented [13][14]; script share and pricing are not.

**Native check:** Arabic-script vs Arabizi share on brand accounts. $ pricing. ق vs أ. Separate JO/SY/PS entries?

**Sources:**
[5] Unicode CLDR JSON: https://github.com/unicode-org/cldr-json
[12] Wikipedia, Levantine Arabic: https://en.wikipedia.org/wiki/Levantine_Arabic
[13] Wikipedia, Lebanese Arabic: https://en.wikipedia.org/wiki/Lebanese_Arabic
[14] Wikipedia, Jordanian Arabic: https://en.wikipedia.org/wiki/Jordanian_Arabic
[25] Wikipedia, Arabic chat alphabet: https://en.wikipedia.org/wiki/Arabic_chat_alphabet
[37] Wikipedia, Lebanese pound: https://en.wikipedia.org/wiki/Lebanese_pound
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[46] DataReportal, Digital 2026: Lebanon: https://datareportal.com/reports/digital-2026-lebanon

---

### الدارجة المغربية · Moroccan Darija — `ar-MA`

**Where it's used / platforms:** Darija is the language of Moroccan TV entertainment and advertising, with Casablanca and Rabat as the norm [20]. Online it constantly switches with MSA [28]. Facebook reaches 22.8M, YouTube 21.6M and TikTok 16.7M adults; X has 1.08M [45].

**Script & spelling:** Arabic script, or a loosely standardised Latin chat system using 3, 7 and 9 [20]. In Latin script "ch" stands for ش [25]. In Arabic script /g/ is ڭ (إنسطاڭرام) [42].

**Punctuation & typography:** Same as `ar`, with Western digits [31].

**Words that mark the region:**

| Concept | `ar-MA` | Algeria · Tunisia |
|---|---|---|
| what / now | شنو، آش / دابا [20] | واش / (check) · شنوّة / توّة [22][23] |
| want / very | بغيت / بزاف [20][24] | نحب / بزاف · نحب / برشا [22][23] |
| good | مزيان [21] | مليح · باهي [22][23] |
| not / will | ما…ش / غادي، غا [20] | ما…ش / رايح · موش / باش [22][23] |
| January / September | يناير / شتنبر [5] | جانفي / سبتمبر (both) [5] |

**Particles, interjections & fillers:** Illustrative, check: واخا ("OK"), صافي ("fine / that's it"), والله.

**Formality & address:** "You" is نتا / نتي, plural نتوما (illustrative). لالّة ("lady", from Amazigh) is respectful [20]. Match the author's gender and address audiences in the plural.

**Mixing languages:** French loans (portable, tobis "bus"), Spanish loans in the north and an Amazigh substrate [20]. Because of the colonial past, French signals class; keep it light.

**Tone & humour on social:** Playful Darija memes (check).

**Platform habits:** Facebook and YouTube lead [45].

**Formats:** MAD is د.م., said درهم (DH on tags: check) [5]. Decimal comma and dot grouping (1.250,50), 24-hour time [5]. Monday–Friday workweek [39].

**Names of people & works:** ڭ for g [42].

**Sensitivities:** Morocco calls Western Sahara its "southern provinces"; a UN resolution in October 2025 backed its autonomy plan [41]. Avoid maps entirely, because Algeria backs the Polisario Front. No jokes about the monarchy or religion.

**Algeria / Tunisia notes:** Algeria borrows heavily from French and writes in both scripts [22]; one Arabizi corpus is 36% French tokens [26]. Its weekend is Friday–Saturday [39]. Tunisians often write in Latin script online [23][27]. Both use a decimal comma [5]. A Moroccan draft fits neither country.

**Search aliases:** Moroccan, Moroccan Arabic, Darija, الدارجة, مغربي, Maghrebi, Algerian, جزائري, Dziri, Tunisian, تونسي, Tounsi, Derja, North African Arabic

**Prompt guide (≤120 words):** Write in Moroccan Darija (Casablanca/Rabat norm) in Arabic script unless the author writes Latin-script Darija. Not MSA, and never Egyptian or Levantine. Use شنو/آش، دابا، بغيت، بزاف، مزيان، ما…ش, future غادي/غا and progressive كا. Write /g/ as ڭ. Short French loans are fine; don't stack them. Use Western digits, a decimal comma and prices in درهم. Match the author's gender. Don't mention Western Sahara, maps or the monarchy unless the brief requires it.

**Confidence:** Medium. Markers are documented [20][22][23]; script share and pricing are not.

**Native check:** Arabic vs Latin script share. Whether French words go in Latin letters. واخا / صافي. DH pricing. Separate DZ / TN entries?

**Sources:**
[5] Unicode CLDR JSON: https://github.com/unicode-org/cldr-json
[20] Wikipedia, Moroccan Arabic: https://en.wikipedia.org/wiki/Moroccan_Arabic
[21] Wiktionary, مزيان: https://en.wiktionary.org/wiki/مزيان
[22] Wikipedia, Algerian Arabic: https://en.wikipedia.org/wiki/Algerian_Arabic
[23] Wikipedia, Tunisian Arabic: https://en.wikipedia.org/wiki/Tunisian_Arabic
[24] Wikipedia, Varieties of Arabic: https://en.wikipedia.org/wiki/Varieties_of_Arabic
[25] Wikipedia, Arabic chat alphabet: https://en.wikipedia.org/wiki/Arabic_chat_alphabet
[26] Shehadi & Wintner (2022), Identifying Code-switching in Arabizi: https://aclanthology.org/2022.wanlp-1.18.pdf
[27] Fourati et al. (2020), TUNIZI: https://arxiv.org/abs/2004.14303
[28] Samih & Maier (2016), An Arabic-Moroccan Darija Code-Switched Corpus: https://aclanthology.org/L16-1658.pdf
[31] Wikipedia, Eastern Arabic numerals: https://en.wikipedia.org/wiki/Eastern_Arabic_numerals
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[41] Wikipedia, Western Sahara: https://en.wikipedia.org/wiki/Western_Sahara
[42] Wikidata labels, Google Q95 and Instagram Q209330 (ary): https://www.wikidata.org/wiki/Q209330
[45] DataReportal, Digital 2026: Morocco: https://datareportal.com/reports/digital-2026-morocco

---

### עברית · Hebrew (Israel) — `he-IL`

**Where it's used / platforms:** Israel. YouTube 7.01M, Facebook 5.05M, Instagram 5.00M, TikTok 4.49M adults, LinkedIn 3.10M; X 0.88M [47].

**Script & spelling:** Hebrew script, right to left, without niqqud in everyday text [52].

**Punctuation & typography:**
- Geresh ׳ marks foreign sounds (ג׳ צ׳ ז׳) and abbreviations; gershayim ״ marks acronyms (צה״ל). Online, ' and " usually stand in [52][53].
- A prefix attached to a Latin word or number takes a hyphen (ב-Azure) [2].
- Punctuation goes outside quotation marks [2].

**Words that mark the region:**

| Concept | Casual Israeli | Neutral |
|---|---|---|
| OK / cool | סבבה [58] | בסדר |
| great | אחלה | מצוין |
| let's go | יאללה | בואו |
| bottom line | תכלס | בשורה התחתונה |

Casual forms other than סבבה are illustrative.

**Particles, interjections & fillers:** Illustrative: כאילו ("like"), בקיצור ("anyway"), וואלה ("really?"). Laughter is חחח [57].

**Formality & address:**
- Present-tense verbs and adjectives carry gender even in the first person (אני אוהב / אוהבת), so match the author.
- For audiences, Microsoft recommends plural imperatives (לחצו), gender-identical forms (שלך, איתך) and future-tense questions (האם אוכל?), with slashes (כותב/ת) only as a last resort [2].
- The Academy treats the masculine as generic but has formed a gender committee [54].
- Dot, slash and double-ending forms (דרוש.ה, חבריםות) appear in activist and municipal writing [54][55][56]. Use them only if the author does.

**Mixing languages:** English loans are written in Hebrew letters (illustrative: פוסט, לייק). Brand names and acronyms stay in Latin script [2].

**Tone & humour on social:** Direct and informal. English-style jokes can sound childish in Hebrew [2].

**Platform habits:** YouTube is largest; Facebook and Instagram have equal reach [47].

**Formats:**
- **Currency.** ₪ or ש״ח.
- **Dates and time.** d.M.y and H:mm [5].
- **Week.** Starts Sunday, with a Friday–Saturday weekend [5][39].
- **Calendar.** CLDR lists the Hebrew calendar [5]; greetings are שנה טובה and שבת שלום.

**Names of people & works:** בטהובן, שופן, מוצרט, באך, and מייקל ג'קסון, with the geresh marking j [42].

**Sensitivities:** War, hostages and memorial days call for a subdued tone and no promotions. Don't assume every audience is Jewish or Hebrew-speaking. Shabbat norms vary.

**Search aliases:** Hebrew, עברית, Ivrit, Modern Hebrew, Israeli Hebrew, Israeli

**Prompt guide (≤120 words):** Write everyday Israeli Hebrew without niqqud, short and direct. Match the author's gender in every first-person verb and adjective. Address audiences with plural imperatives (נסו, כתבו לנו) or gender-identical forms (שלך, איתך); use slash or dot forms only if the author does. Hyphenate prefixes before Latin names and numbers (ב-Instagram, ב-2026). Use ׳ and ״ correctly (ג׳, צה״ל). Use casual markers (סבבה, יאללה) only in casual voices. Give prices in ₪, and keep exclamation marks rare.

**Confidence:** High for typography and address [2][52]. Medium for slang and tone.

**Native check:** Emoji and exclamation-mark norms. Dot forms on brand accounts. Shabbat posting. Digits vs words under 10.

**Sources:**
[2] Microsoft, Hebrew Localization Style Guide: https://download.microsoft.com/download/a/2/f/a2ff07cc-afca-4db8-9ed7-fd1b706abf1c/heb-isr-StyleGuide.pdf
[5] Unicode CLDR JSON: https://github.com/unicode-org/cldr-json
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[42] Wikidata labels (Q255, Q1268, Q254, Q1339, Q2831): https://www.wikidata.org/wiki/Q2831
[47] DataReportal, Digital 2026: Israel: https://datareportal.com/reports/digital-2026-israel
[52] Wikipedia, Hebrew punctuation: https://en.wikipedia.org/wiki/Hebrew_punctuation
[53] Wikipedia, Gershayim: https://en.wikipedia.org/wiki/Gershayim
[54] The Jewish Independent, Hebrew is changing to become compatible with gender justice: https://thejewishindependent.com.au/hebrew-is-changing-to-become-compatible-with-gender-justice/
[55] Moment, Can Hebrew Be Gender-Neutral?: https://momentmag.com/can-hebrew-be-gender-neutral/
[56] Citizen Café TLV, Multi Gender in Modern Hebrew: https://www.citizencafetlv.com/blog/multi-gender-hebrew/
[57] Wikipedia, LOL (equivalents in other languages): https://en.wikipedia.org/wiki/LOL
[58] Wiktionary, סבבה: https://en.wiktionary.org/wiki/סבבה

---

### فارسی · Persian (Iran), with Dari note — `fa-IR`

**Where it's used / platforms:** Iran and its diaspora. Instagram, Telegram, X, YouTube and TikTok are blocked and reached through VPNs; WhatsApp was unblocked in December 2024 [65]. There was a near-total blackout from 8 January 2026 [65]. Platform counts are unreliable [49].

**Script & spelling:**
- Use Persian پ چ ژ گ and Persian ی / ک, not Arabic ي / ك [60].
- ZWNJ (نیم‌فاصله) joins parts of one word: می‌خواهم [59], کتاب‌ها, بزرگ‌تر [61].
- Casual posts use Tehrani colloquial forms (illustrative: می‌خوام, "I want") [66].

**Punctuation & typography:** Persian comma ، [3]; «» quotation marks, never single quotes [3]; ؟. Use parentheses rather than em dashes [3].

**Words that mark the region:**

| Concept | `fa-IR` | `fa-AF` (Dari) |
|---|---|---|
| Month 1 / Month 6 | فروردین / شهریور [5] | حمل / سنبله [5] |
| September | سپتامبر [5] | سپتمبر [5] |
| thanks | مرسی، ممنون (illustrative) | تشکر (check) |

**Particles, interjections & fillers:** Illustrative: خب، حالا، دیگه، یعنی. Laughter is خخخ or ههه [68].

**Formality & address:** No grammatical gender; pronouns are neutral [3]. شما is polite, تو intimate [67]. Brands use شما in a friendly tone, and formal and colloquial Persian differ sharply [3], so keep one register per post.

**Mixing languages:** French and English loans (مرسی) sit alongside Academy coinages [67]. Latin-script Fingilish persists in chat [64].

**Tone & humour on social:** Warm; verse quotations are common (check).

**Platform habits:** Instagram and Telegram lead (check).

**Formats:**
- **Calendar.** Solar Hijri is the default [5]; year 1405 began at Nowruz in March 2026 [62]. Dates are y/M/d [5].
- **Digits.** ۰–۹ with ٫ ٬ [5].
- **Currency.** The rial is official, but prices are in toman (1 toman = 10 rials) [38]. Parliament approved dropping four zeros in October 2025 [38][69], so always name تومان or ریال.
- **Week.** Starts Saturday; the weekend is Friday [5].

**Names of people & works:** بتهوون، شوپن، موتسارت، گوگل، اینستاگرام [42].

**Sensitivities:** Always write خلیج فارس [40]. Protest and hijab imagery can endanger users inside Iran. Arabic spellings make text read as Arabic.

**Dari note (`fa-AF`):** Months use zodiac names [5][62], و is pronounced [w] [63], and "Dari" vs "Farsi" is a political choice [63]. Currency is AFN ؋ [5]. Microsoft adapts Iranian resources to Dari usage [4]. Weekend data conflicts between CLDR and Wikipedia [5][39].

**Search aliases:** Persian, Farsi, فارسی, Parsi, Iranian Persian, Dari, دری, Afghan Persian, Fingilish, Pinglish

**Prompt guide (≤120 words):** Write contemporary Iranian Persian with Persian letters (ی ک پ چ ژ گ), never Arabic ي ك. Put ZWNJ inside words (می‌خوام، پست‌ها، بزرگ‌ترین). Choose one register: friendly colloquial for personal posts, neutral written for brands. Address readers as شما. Use « » for quotes, ، for commas and Persian digits ۰–۹. Give dates in the Solar Hijri calendar and prices in تومان unless told otherwise. Write خلیج فارس. No Arabic words or spellings.

**Confidence:** High for typography and formats [3][5][59][60]. Medium for social habits. Low for Dari vocabulary.

**Native check:** Colloquial verb endings on brand accounts. Current platform mix. Dari vocabulary. Iran and Afghanistan weekends.

**Sources:**
[3] Microsoft, Persian (fa-IR) Localization Style Guide: https://download.microsoft.com/download/3/e/c/3ec58a9a-70ff-4a31-8cfd-d185983111be/fas-irn-StyleGuide.pdf
[4] Microsoft, Dari Style Guide: https://download.microsoft.com/download/c/2/2/c22971fc-8ec3-4b96-8a7f-ded6b8994c4a/prs-afg-styleguide.pdf
[5] Unicode CLDR JSON (incl. cldr-cal-persian-full): https://github.com/unicode-org/cldr-json
[38] Wikipedia, Iranian rial: https://en.wikipedia.org/wiki/Iranian_rial
[39] Wikipedia, Workweek and weekend: https://en.wikipedia.org/wiki/Workweek_and_weekend
[40] Wikipedia, Persian Gulf naming dispute: https://en.wikipedia.org/wiki/Persian_Gulf_naming_dispute
[42] Wikidata labels (Q255, Q1268, Q254, Q95, Q209330): https://www.wikidata.org/wiki/Q1268
[49] DataReportal, Digital 2026: Iran: https://datareportal.com/reports/digital-2026-iran
[59] Wikipedia, Zero-width non-joiner: https://en.wikipedia.org/wiki/Zero-width_non-joiner
[60] Wikipedia, Persian alphabet: https://en.wikipedia.org/wiki/Persian_alphabet
[61] parsi-lint, Linter for Persian content: missing ZWNJ cases (seen in search results): https://github.com/ssepehrnoush/parsi-lint
[62] Wikipedia, Solar Hijri calendar: https://en.wikipedia.org/wiki/Solar_Hijri_calendar
[63] Wikipedia, Dari: https://en.wikipedia.org/wiki/Dari
[64] Wikipedia, Fingilish: https://en.wikipedia.org/wiki/Fingilish
[65] Wikipedia, Internet censorship in Iran: https://en.wikipedia.org/wiki/Internet_censorship_in_Iran
[66] Wikipedia, Tehrani accent: https://en.wikipedia.org/wiki/Tehrani_accent
[67] Wikipedia, Persian language: https://en.wikipedia.org/wiki/Persian_language
[68] NaTakallam, How People Express Laughter in Different Languages (seen in search results): https://natakallam.com/blog/how-people-express-laughter-in-different-languages/
[69] Iran International, Iran's parliament approves plan to remove four zeros from national currency (seen in search results): https://www.iranintl.com/en/202510050305

---

### Arabizi (`ar-Latn`): does it merit a picker entry?

**Short answer:** Offer it as a script option attached to a region, not as a standalone top-level locale.

**What it is.** Arabizi writes Arabic in Latin letters with digits standing in for missing sounds [25]:
- 2 = hamza or q, 3 = ʿayn, 5 = kh, 6 = ṭ, 7 = ḥ
- 8 = gh (mainly Lebanese), 9 = ṣ or q (Gulf)

It also goes by Arabish and Franco-Arabic ("Franco") [25]. People keep using it on devices that can type Arabic, and multinational ads use it, but it never appears in formal settings [25].

**Where it's common.** Evidence is qualitative; no cross-country share figures turned up.
- **Lebanon and Egypt.** Research corpora are built from Lebanese and Egyptian social posts [26]. Lebanese Arabic is written in Latin script online [13].
- **Tunisia.** Latin-script Tunisian is common online [23]. TUNIZI is a set of 9k+ Tunisian social comments written only in Arabizi [27].
- **Algeria.** Written in both scripts [22]; one corpus is 36% French tokens [26].
- **Morocco.** Has a loosely standardised Latin chat system [20].
- **Saudi Arabia and the Gulf.** A youth peer code, not used with parents [29].

**Why it has to inherit a region.** Spelling follows the local contact language. Moroccan writers use "ch" for ش under French influence, while Egyptians use y / w under English influence [25]. The markers are dialect-specific too. So a generic `ar-Latn` would produce spellings no community uses.

**Recommendation:**
- Add a "Latin letters (Arabizi)" toggle under `ar-LB`, `ar-EG`, `ar-MA`, and any future `ar-TN` / `ar-DZ`, stored as `ar-Latn-LB`, `ar-Latn-EG` and so on. Default it to off.
- Put Arabizi, Franco, Arabish, 3arabizi and عربيزي in search aliases.
- Load the regional guide plus a small romanisation table.

Illustrative examples:
- Lebanese "shu 3am ta3mil?" means "what are you doing?"
- Egyptian "3ayez a3raf" means "I want to know".
- Tunisian "nheb barcha" means "I like it a lot".

**Confidence:** Medium that it exists and is region-specific. Low on how common it is in each country today.

**Native check:** How common Arabizi is on brand and creator accounts vs private chats in 2026, per country.

---

### Open questions

1. **Digits.** Microsoft's Saudi guide says Western digits across the Arab world [1], but CLDR defaults Egypt, Saudi Arabia and the Levant to ٠١٢ [5]. Pick a per-locale default with native reviewers, and let authors override it.
2. **Najdi vs Hijazi.** Should `ar-SA` expose both as sub-voices, or default to Riyadh-Najdi and infer Hijazi from the author profile?
3. **More Arabic locales.** Do Jordan, Syria, Palestine, Iraq, Kuwait, Algeria and Tunisia get their own Tier-1 entries? Their markers and month names differ from the parent entries [5][14][22][23].
4. **Gender-inclusive forms.** How should Arabic (سجّل/ي) and Hebrew (דרוש.ה) inclusive forms be handled? Match the author's past usage, or offer a brand-level setting?
5. **Author gender.** Arabic and Hebrew first-person forms need it, so the author profile must hold it or the model must ask.
6. **LLM default to MSA.** The drafting model's pull toward MSA [9] needs a check step, e.g. a dialect-marker lint that flags drafts with no regional markers.
7. **Calendars and currency.** Hijri and Solar Hijri dates in scheduling UI. Toman vs rial during Iran's redenomination [38]. Dirham-sign fallback until Unicode 18 [36].
8. **Weekends.** Iran's and Afghanistan's weekend days conflict between CLDR and Wikipedia [5][39]; verify before scheduling defaults.
9. **Unverified items.** Laughter (خخخ in the Gulf), Egyptian ى-for-ي typing, Moroccan DH pricing and Lebanese $ pricing all need confirmation from native reviewers.

**Source list (all entries):** [1] Microsoft Arabic Localization Style Guide, https://download.microsoft.com/download/5/6/d/56d1774f-ac3f-4ad9-80af-a6dfd5df419d/ara-sau-StyleGuide.pdf · [2] Microsoft Hebrew Localization Style Guide, https://download.microsoft.com/download/a/2/f/a2ff07cc-afca-4db8-9ed7-fd1b706abf1c/heb-isr-StyleGuide.pdf · [3] Microsoft Persian Localization Style Guide, https://download.microsoft.com/download/3/e/c/3ec58a9a-70ff-4a31-8cfd-d185983111be/fas-irn-StyleGuide.pdf · [4] Microsoft Dari Style Guide, https://download.microsoft.com/download/c/2/2/c22971fc-8ec3-4b96-8a7f-ded6b8994c4a/prs-afg-styleguide.pdf · [5] Unicode CLDR JSON, https://github.com/unicode-org/cldr-json · [6] UAX #9 Unicode Bidirectional Algorithm, https://www.unicode.org/reports/tr9/ · [7] W3C, Unicode Bidirectional Algorithm basics, https://www.w3.org/International/articles/inline-bidi-markup/uba-basics · [8] Levels of Arabic Language in Saudi Tweets, https://www.richtmann.org/journal/index.php/ajis/article/download/14200/13856/48335 · [9] Saudi-Dialect-ALLaM, https://arxiv.org/pdf/2508.13525 · [10] Wikipedia, Modern Standard Arabic · [11] Wikipedia, Egyptian Arabic · [12] Wikipedia, Levantine Arabic · [13] Wikipedia, Lebanese Arabic · [14] Wikipedia, Jordanian Arabic · [15] Wikipedia, Hejazi Arabic · [16] Wikipedia, Najdi Arabic · [17] Wikipedia, Emirati Arabic · [18] Wiktionary, وش · [19] Wiktionary, مرة · [20] Wikipedia, Moroccan Arabic · [21] Wiktionary, مزيان · [22] Wikipedia, Algerian Arabic · [23] Wikipedia, Tunisian Arabic · [24] Wikipedia, Varieties of Arabic · [25] Wikipedia, Arabic chat alphabet · [26] Identifying Code-switching in Arabizi, https://aclanthology.org/2022.wanlp-1.18.pdf · [27] TUNIZI, https://arxiv.org/abs/2004.14303 · [28] Arabic-Moroccan Darija Code-Switched Corpus, https://aclanthology.org/L16-1658.pdf · [29] Arabizi among Saudi Arabians (ResearchGate) · [30] Arab News, Arab Youth Survey 2017 · [31] Wikipedia, Eastern Arabic numerals · [32] Wikipedia, Kashida · [33] Wikipedia, Islamic calendar · [34] Wikipedia, Ramadan · [35] Wikipedia, Saudi riyal · [36] Wikipedia, UAE dirham · [37] Wikipedia, Lebanese pound · [38] Wikipedia, Iranian rial · [39] Wikipedia, Workweek and weekend · [40] Wikipedia, Persian Gulf naming dispute · [41] Wikipedia, Western Sahara · [42] Wikidata labels · [43]–[49] DataReportal Digital 2026 (Saudi Arabia, Egypt, Morocco, Lebanon, Israel, UAE, Iran) · [50] Multi Marketer Egypt guide · [51] 23HubLab Arabic ads guide · [52] Wikipedia, Hebrew punctuation · [53] Wikipedia, Gershayim · [54] The Jewish Independent, Hebrew and gender · [55] Moment, Can Hebrew Be Gender-Neutral? · [56] Citizen Café TLV, Multi Gender Hebrew · [57] Wikipedia, LOL · [58] Wiktionary, סבבה · [59] Wikipedia, Zero-width non-joiner · [60] Wikipedia, Persian alphabet · [61] parsi-lint (GitHub) · [62] Wikipedia, Solar Hijri calendar · [63] Wikipedia, Dari · [64] Wikipedia, Fingilish · [65] Wikipedia, Internet censorship in Iran · [66] Wikipedia, Tehrani accent · [67] Wikipedia, Persian language · [68] NaTakallam, laughter in different languages · [69] Iran International, rial redenomination.


---

## Cross-cutting standards & engineering

Research date: 2026-09-16. Scope: the standards and engineering facts behind PostRiff's region-aware language picker, not the language varieties themselves.

**How the checks were run.** Tag and name results come from scripts run locally in this research folder, not from memory:

- **Node:** `node --version` → **v25.9.0**, with `process.versions` icu **78.3**, cldr **48.0**, unicode **17.0**.
- **IANA registry:** downloaded and parsed; `File-Date: 2026-08-08` [1].
- **CLDR:** XML fetched from the `main` branch, which is CLDR **49** (dev), one version ahead of Node's data [2][3][4][5][9].
- **Chromium check:** one rendering check in the desktop app's built-in Chromium 152 on macOS.

Confidence labels: **High** means checked against a primary spec, registry or source code. **Medium** means official docs plus inference. **Low** means secondary sources or untested.

### TL;DR

| Topic | Recommendation |
|---|---|
| Stored tags | Keep the candidate list almost as it is. Change **`ar` → `ar-001`** for the pan-Arab Modern Standard Arabic entry. Keep `ar` only as a language-only fallback. Keep `ar-EG`, not `arz`. Canonicalise input with `Intl.getCanonicalLocales` plus a small alias map (`zh-HK`→`zh-Hant-HK`, `zh-yue`/`yue`/`yue-HK`→`yue-Hant-HK`, `tl`→`fil`, `arz`→`ar-EG`, `ary`→`ar-MA`, `apc`/`ajp`→`ar-LB`). |
| Display names | Build the names once at build time from CLDR/ICU, split into a *language* part and a *short region* part. Hand-write overrides for about 15 Tier 1 entries. Don't call `Intl.DisplayNames` at runtime for Tier 1: V8, Safari and Firefox capitalise differently, and a Next.js page rendered on the server would then not match the client. |
| Sensitive names | Use CLDR `alt="short"` region names ("Hong Kong", "香港", "Taiwan", "台灣"). No flags. Call the column "Region" / 地區, never "Country". |
| Search | NFKC → NFD → strip **only** U+0300–U+036F → NFC → İ/ı fold → lower-case → katakana→hiragana. Add a hand-made alias table for Chinese names. Don't bundle OpenCC for search. |
| Combobox | A trigger button opens a dialog popover. Inside it, an editable combobox (`aria-autocomplete="list"`) drives a grouped listbox. Announce the result count in a polite live region. On phones, use a modal sheet whose rows are real focusable options. |
| Rendering | Put `lang="<stored tag>"` and `dir="auto"` on every preview body and draft textarea. Add `unicode-bidi: plaintext` on textareas. Give `:lang()` font stacks for zh-HK/yue, zh-TW, zh-CN, ja and ur (Nastaliq). Never use `word-break: break-all` or `letter-spacing` on post text. |
| Counting | There is no single "character". X counts weighted units (CJK = 2), Threads says emoji count in UTF-8 bytes, Bluesky counts graphemes plus a byte cap, LINE counts UTF-16 units, TikTok counts UTF-16 "runes" and YouTube descriptions count bytes. Count per platform, and warn rather than block. |

---

### 1. Tag validity

**Confidence: High** for the registry and Intl results. **Medium** for what LLM vendors expect.

#### 1.1 Registry and `Intl` results for every candidate

Every candidate tag is well formed and registered [1]. `Intl.getCanonicalLocales` leaves all 54 Tier 1 candidates unchanged in Node v25.9.0 / ICU 78.3. The last column shows what `new Intl.NumberFormat(tag).resolvedOptions().locale` falls back to. That shows whether the runtime actually has data for the tag.

| Tag | IANA registry (2026-08-08) | `Intl.getCanonicalLocales` | `maximize()` | `minimize()` | `NumberFormat` resolves to |
|---|---|---|---|---|---|
| `zh-Hant-HK` | redundant tag (registered, valid) | `zh-Hant-HK` | `zh-Hant-HK` | `zh-HK` | `zh-Hant-HK` |
| `yue-Hant-HK` | registered; in macrolanguage `zh` | `yue-Hant-HK` | `yue-Hant-HK` | `yue` | `yue-Hant-HK` |
| `zh-Hant-TW` | redundant tag (registered, valid) | `zh-Hant-TW` | `zh-Hant-TW` | `zh-TW` | `zh-Hant-TW` |
| `zh-Hans-CN` | redundant tag (registered, valid) | `zh-Hans-CN` | `zh-Hans-CN` | `zh` | `zh-Hans-CN` |
| `zh-Hans-SG` | redundant tag (registered, valid) | `zh-Hans-SG` | `zh-Hans-SG` | `zh-SG` | `zh-Hans-SG` |
| `en-US` | registered | `en-US` | `en-Latn-US` | `en` | `en-US` |
| `en-GB` | registered | `en-GB` | `en-Latn-GB` | `en-GB` | `en-GB` |
| `en-GB-scotland` | registered; variant `scotland` prefix en ✓ | `en-GB-scotland` | `en-Latn-GB-scotland` | `en-GB-scotland` | `en-GB` |
| `en-IE` | registered | `en-IE` | `en-Latn-IE` | `en-IE` | `en-IE` |
| `en-AU` | registered | `en-AU` | `en-Latn-AU` | `en-AU` | `en-AU` |
| `en-NZ` | registered | `en-NZ` | `en-Latn-NZ` | `en-NZ` | `en-NZ` |
| `en-CA` | registered | `en-CA` | `en-Latn-CA` | `en-CA` | `en-CA` |
| `en-IN` | registered | `en-IN` | `en-Latn-IN` | `en-IN` | `en-IN` |
| `en-SG` | registered | `en-SG` | `en-Latn-SG` | `en-SG` | `en-SG` |
| `es-ES` | registered | `es-ES` | `es-Latn-ES` | `es` | `es-ES` |
| `es-MX` | registered | `es-MX` | `es-Latn-MX` | `es-MX` | `es-MX` |
| `es-AR` | registered | `es-AR` | `es-Latn-AR` | `es-AR` | `es-AR` |
| `es-CO` | registered | `es-CO` | `es-Latn-CO` | `es-CO` | `es-CO` |
| `es-US` | registered | `es-US` | `es-Latn-US` | `es-US` | `es-US` |
| `es-419` | redundant tag (registered, valid) | `es-419` | `es-Latn-419` | `es-419` | `es-419` |
| `pt-BR` | registered | `pt-BR` | `pt-Latn-BR` | `pt` | `pt-BR` |
| `pt-PT` | registered | `pt-PT` | `pt-Latn-PT` | `pt-PT` | `pt-PT` |
| `fr-FR` | registered | `fr-FR` | `fr-Latn-FR` | `fr` | `fr-FR` |
| `fr-CA` | registered | `fr-CA` | `fr-Latn-CA` | `fr-CA` | `fr-CA` |
| `de-DE` | registered | `de-DE` | `de-Latn-DE` | `de` | `de-DE` |
| `de-AT` | registered | `de-AT` | `de-Latn-AT` | `de-AT` | `de-AT` |
| `de-CH` | registered | `de-CH` | `de-Latn-CH` | `de-CH` | `de-CH` |
| `it-IT` | registered | `it-IT` | `it-Latn-IT` | `it` | `it-IT` |
| `nl-NL` | registered | `nl-NL` | `nl-Latn-NL` | `nl` | `nl-NL` |
| `pl-PL` | registered | `pl-PL` | `pl-Latn-PL` | `pl` | `pl-PL` |
| `tr-TR` | registered | `tr-TR` | `tr-Latn-TR` | `tr` | `tr-TR` |
| `ru-RU` | registered | `ru-RU` | `ru-Cyrl-RU` | `ru` | `ru-RU` |
| `uk-UA` | registered | `uk-UA` | `uk-Cyrl-UA` | `uk` | `uk-UA` |
| `ja-JP` | registered | `ja-JP` | `ja-Jpan-JP` | `ja` | `ja-JP` |
| `ko-KR` | registered | `ko-KR` | `ko-Kore-KR` | `ko` | `ko-KR` |
| `th-TH` | registered | `th-TH` | `th-Thai-TH` | `th` | `th-TH` |
| `vi-VN` | registered | `vi-VN` | `vi-Latn-VN` | `vi` | `vi-VN` |
| `id-ID` | registered; in macrolanguage `ms` | `id-ID` | `id-Latn-ID` | `id` | `id-ID` |
| `ms-MY` | registered; `ms` = macrolanguage | `ms-MY` | `ms-Latn-MY` | `ms` | `ms-MY` |
| `fil-PH` | registered | `fil-PH` | `fil-Latn-PH` | `fil` | `fil-PH` |
| `hi-IN` | registered | `hi-IN` | `hi-Deva-IN` | `hi` | `hi-IN` |
| `hi-Latn-IN` | registered | `hi-Latn-IN` | `hi-Latn-IN` | `hi-Latn` | `hi-Latn-IN` |
| `bn-IN` | registered | `bn-IN` | `bn-Beng-IN` | `bn-IN` | `bn-IN` |
| `ta-IN` | registered | `ta-IN` | `ta-Taml-IN` | `ta` | `ta-IN` |
| `te-IN` | registered | `te-IN` | `te-Telu-IN` | `te` | `te-IN` |
| `mr-IN` | registered | `mr-IN` | `mr-Deva-IN` | `mr` | `mr-IN` |
| `ur-PK` | registered | `ur-PK` | `ur-Arab-PK` | `ur` | `ur-PK` |
| `ar` | registered; `ar` = macrolanguage | `ar` | `ar-Arab-EG` | `ar` | `ar` |
| `ar-EG` | registered; `ar` = macrolanguage | `ar-EG` | `ar-Arab-EG` | `ar` | `ar-EG` |
| `ar-SA` | registered; `ar` = macrolanguage | `ar-SA` | `ar-Arab-SA` | `ar-SA` | `ar-SA` |
| `ar-LB` | registered; `ar` = macrolanguage | `ar-LB` | `ar-Arab-LB` | `ar-LB` | `ar-LB` |
| `ar-MA` | registered; `ar` = macrolanguage | `ar-MA` | `ar-Arab-MA` | `ar-MA` | `ar-MA` |
| `he-IL` | registered | `he-IL` | `he-Hebr-IL` | `he` | `he-IL` |
| `fa-IR` | registered; `fa` = macrolanguage | `fa-IR` | `fa-Arab-IR` | `fa` | `fa-IR` |
| `en` | registered | `en` | `en-Latn-US` | `en` | `en` |
| `zh-Hant` | redundant tag (registered, valid) | `zh-Hant` | `zh-Hant-TW` | `zh-TW` | `zh-Hant` |
| `zh-Hans` | redundant tag (registered, valid) | `zh-Hans` | `zh-Hans-CN` | `zh` | `zh-Hans` |
| `es` | registered | `es` | `es-Latn-ES` | `es` | `es` |
| `pt` | registered | `pt` | `pt-Latn-BR` | `pt` | `pt` |
| `fr` | registered | `fr` | `fr-Latn-FR` | `fr` | `fr` |
| `de` | registered | `de` | `de-Latn-DE` | `de` | `de` |
| `ar-001` | registered; `ar` = macrolanguage | `ar-001` | `ar-Arab-001` | `ar-001` | `ar-001` |
| `zh-yue` | redundant tag, deprecated → yue | `RangeError: Invalid language tag: zh-yue` **(changed)** | `—` | `—` | `—` |
| `tl-PH` | registered | `fil-PH` **(changed)** | `fil-Latn-PH` | `fil` | `fil-PH` |
| `arz-EG` | registered; in macrolanguage `ar` | `arz-EG` | `arz-Arab-EG` | `arz` | `en-US` |
| `zsm-MY` | registered; in macrolanguage `ms` | `ms-MY` **(changed)** | `ms-Latn-MY` | `ms` | `ms-MY` |
| `cmn-Hant-TW` | registered; in macrolanguage `zh` | `zh-Hant-TW` **(changed)** | `zh-Hant-TW` | `zh-TW` | `zh-Hant-TW` |
| `iw-IL` | registered; `iw` deprecated → `he` | `he-IL` **(changed)** | `he-Hebr-IL` | `he` | `he-IL` |
| `in-ID` | registered; `in` deprecated → `id`; in macrolanguage `ms` | `id-ID` **(changed)** | `id-Latn-ID` | `id` | `id-ID` |

#### 1.2 Specific questions

- **`scotland`.** This is a registered variant ("Scottish Standard English"), added 2007-08-31, with `Prefix: en` [1]. `en-GB-scotland` satisfies the prefix. Runtimes format it as plain `en-GB`. Don't use the Unicode subdivision extension (`en-GB-u-sd-gbsct`) as the stored value, for two reasons:
  - `Intl.DisplayNames.of()` throws `RangeError` on any tag with an extension. The same happens for `zh-yue` and private-use `-x-` tags (tested).
  - The variant already says exactly what we mean.
- **`yue` vs `zh-yue`.**
  - In the registry, `zh-yue` is a *redundant* tag, deprecated 2009-07-29 with `Preferred-Value: yue` [1]. CLDR aliases `zh_yue`→`yue` [2].
  - V8 **throws** `Invalid language tag: zh-yue`, because Unicode locale identifiers do not allow extlang. Accept it only through an alias map.
  - `yue` maximises to `yue-Hant-HK` [3]. CLDR has both `yue_Hant_HK` and `yue_Hans` locale data.
  - Store the explicit script: `yue-Hant-HK`.
- **`es-419`.** Registered redundant tag "Latin American Spanish" [1]. CLDR makes it the parent of `es-MX`, `es-AR`, `es-CO` and `es-US` [5]. Google Cloud Speech uses `es-419` and `es-US` [7].
- **`hi-Latn`.** Valid, because `hi` has `Suppress-Script: Deva` and Latn is a meaningful non-default script [1].
  - CLDR has a `hi_Latn` locale whose English `alt="variant"` name is **"Hinglish"** [9]. Its parent locale is **`en_IN`** [5].
  - CLDR matching treats `hi_Latn`→`hi_Deva` as distance 20, one way [4].
- **`fil` vs `tl`.** Both are registered [1]. CLDR aliases `tl`→`fil` ("legacy") [2], and `Intl.getCanonicalLocales('tl-PH')` returns `fil-PH`. Store `fil-PH`.
- **Arabic.**
  - `ar` is a macrolanguage. `arz` (Egyptian), `ary` (Moroccan), `apc` (Levantine; `ajp` deprecated 2023 → `apc`) and `afb` (Gulf) are individual languages inside it [1].
  - W3C's general advice leans towards specific subtags: "In most cases you should try to use the more specific subtags" [6]. The same article suggests `arb` over `ar`.
  - Implementations go the other way. CLDR aliases `arb`→`ar`, `cmn`→`zh`, `zsm`→`ms` and `pes`→`fa` as "macrolanguage" replacements [2]. It has **no `arz` or `afb` locale data** (`common/main/arz.xml` returns 404).
  - Node falls back to **`en-US`** formatting for `arz-EG` and `apc-LB`. `Intl.DisplayNames(['arz'])` returns the English "Egyptian Arabic", and `apc` has no name at all.
  - CLDR's matcher treats `arz`→`ar` and `ary`→`ar` as close, one-way matches (distance 10) [4].
  - Vendors: Google Cloud Speech uses `ar-EG`, `ar-SA`, `ar-LB` and `ar-MA` [7]. Azure Translator exposes only `ar` [8].
  - CLDR's territory data still records `arz` for 64% of Egypt, `ary` for 87% of Morocco and `apc` for Lebanon [5]. So the colloquial varieties are real, but no tooling keys on those codes.
  - **Store `ar-EG` / `ar-MA` / `ar-LB` / `ar-SA`.** Record register (MSA vs colloquial) as PostRiff metadata in the style guide, not in the tag.
- **Bare `ar` means Egypt to the runtime.** `ar` maximises to **`ar-Arab-EG`** [3]. For a neutral pan-Arab MSA entry use **`ar-001`**, which CLDR names "Modern Standard Arabic" / "العربية الفصحى الحديثة" / 現代標準阿拉伯文 [9]. `Intl` supports it. RFC 4647-style truncation still falls back to `ar` for systems that don't know it.
- **`ms`.** A macrolanguage, and `id` is also listed inside `ms` [1]. CLDR aliases `zsm`→`ms` [2], and `zsm-MY` canonicalises to `ms-MY`. Store `ms-MY`.
- **Chinese.** The tags `zh-Hant-HK`, `zh-Hant-TW`, `zh-Hans-CN`, `zh-Hans-SG`, `zh-Hant` and `zh-Hans` are all registered "redundant" tags [1]. Legacy `zh-HK`/`zh-TW` maximise to the Hant forms [3]. CLDR makes `zh_Hant_MO` a child of `zh_Hant_HK` [5], which is useful for fallback.
- **Kosovo (XK).** `XK` is not an assigned region in the IANA registry; it sits in the private-use range `XA..XZ` [1]. CLDR uses it for Kosovo [9]. Don't put it in Tier 1.

**Recommendation for PostRiff:**
- **Canonical Tier 1 tags.** Keep the candidate list as the stored values, with one change: replace the Tier 1 `ar` entry with **`ar-001`** and keep bare `ar` only as a language-only fallback.
- **Normalise on write** in both TypeScript and Python:
  1. Lower-case and trim.
  2. Map through a small alias table: `zh-yue|yue|yue-HK → yue-Hant-HK`, `zh-HK → zh-Hant-HK`, `zh-TW → zh-Hant-TW`, `zh-CN → zh-Hans-CN`, `zh-SG → zh-Hans-SG`, `zh-MO → zh-Hant-MO`, `arz(-EG) → ar-EG`, `ary(-MA) → ar-MA`, `apc|ajp(-LB) → ar-LB`, `tl → fil`, `iw → he`, `in → id`, `zsm → ms`, `cmn-* → zh-*`.
  3. Run `Intl.getCanonicalLocales`.
  4. Reject anything with `-u-`, `-t-` or `-x-` extensions.
- **Script subtags.** Keep them for Chinese and Cantonese and never store the minimised form (`zh`, `yue`). Omit scripts that are `Suppress-Script` defaults (no `en-Latn-US`).
- **Fallback chain.** Build it from CLDR `parentLocales` plus truncation, e.g. `zh-Hant-MO → zh-Hant-HK → zh-Hant`, `es-MX → es-419 → es`, `hi-Latn-IN → hi-Latn → en-IN`. Don't hand-roll it.
- **Python side.** Ship one generated JSON (tags, aliases, parents) so the Python backend never re-derives the rules.

---

### 2. Display names

**Confidence: High** for the Node output. **Medium** for other engines, which I inferred from source code and did not run.

#### 2.1 Output (Node v25.9.0, ICU 78.3, CLDR 48.0)

Each cell is `new Intl.DisplayNames([locale], {type:'language', languageDisplay}).of(tag)`. The autonym columns use `locale = tag`. `dialect` (the default) uses special regional names such as "Flemish"; `standard` always uses "Language (Region)" [10].

| Tag | Autonym (dialect) | Autonym (standard) | English (dialect) | English (standard) | zh-Hant-HK (dialect) | zh-Hant-HK (standard) |
|---|---|---|---|---|---|---|
| `zh-Hant-HK` | 中文（繁體字，中國香港特別行政區） | 中文（繁體字，中國香港特別行政區） | Chinese (Traditional, Hong Kong SAR China) | Chinese (Traditional, Hong Kong SAR China) | 中文（繁體字，中國香港特別行政區） | 中文（繁體字，中國香港特別行政區） |
| `yue-Hant-HK` | 粵語 (繁體，中國香港特別行政區) | 粵語 (繁體，中國香港特別行政區) | Cantonese (Traditional, Hong Kong SAR China) | Cantonese (Traditional, Hong Kong SAR China) | 廣東話（繁體字，中國香港特別行政區） | 廣東話（繁體字，中國香港特別行政區） |
| `zh-Hant-TW` | 中文（繁體，台灣） | 中文（繁體，台灣） | Chinese (Traditional, Taiwan) | Chinese (Traditional, Taiwan) | 中文（繁體字，台灣） | 中文（繁體字，台灣） |
| `zh-Hans-CN` | 中文（简体，中国） | 中文（简体，中国） | Chinese (Simplified, China) | Chinese (Simplified, China) | 中文（簡體字，中國） | 中文（簡體字，中國） |
| `zh-Hans-SG` | 中文（简体，新加坡） | 中文（简体，新加坡） | Chinese (Simplified, Singapore) | Chinese (Simplified, Singapore) | 中文（簡體字，新加坡） | 中文（簡體字，新加坡） |
| `en-US` | American English | English (United States) | American English | English (United States) | 美國英文 | 英文（美國） |
| `en-GB` | British English | English (United Kingdom) | British English | English (United Kingdom) | 英國英文 | 英文（英國） |
| `en-GB-scotland` | British English (Scottish Standard English) | English (United Kingdom, Scottish Standard English) | British English (Scottish Standard English) | English (United Kingdom, Scottish Standard English) | 英國英文（蘇格蘭標準英語） | 英文（英國，蘇格蘭標準英語） |
| `en-IE` | English (Ireland) | English (Ireland) | English (Ireland) | English (Ireland) | 英文（愛爾蘭） | 英文（愛爾蘭） |
| `en-AU` | Australian English | English (Australia) | Australian English | English (Australia) | 澳洲英文 | 英文（澳洲） |
| `en-NZ` | English (New Zealand) | English (New Zealand) | English (New Zealand) | English (New Zealand) | 英文（紐西蘭） | 英文（紐西蘭） |
| `en-CA` | Canadian English | English (Canada) | Canadian English | English (Canada) | 加拿大英文 | 英文（加拿大） |
| `en-IN` | English (India) | English (India) | English (India) | English (India) | 英文（印度） | 英文（印度） |
| `en-SG` | English (Singapore) | English (Singapore) | English (Singapore) | English (Singapore) | 英文（新加坡） | 英文（新加坡） |
| `es-ES` | español de España | español (España) | European Spanish | Spanish (Spain) | 歐洲西班牙文 | 西班牙文（西班牙） |
| `es-MX` | español de México | español (México) | Mexican Spanish | Spanish (Mexico) | 墨西哥西班牙文 | 西班牙文（墨西哥） |
| `es-AR` | español (Argentina) | español (Argentina) | Spanish (Argentina) | Spanish (Argentina) | 西班牙文（阿根廷） | 西班牙文（阿根廷） |
| `es-CO` | español (Colombia) | español (Colombia) | Spanish (Colombia) | Spanish (Colombia) | 西班牙文（哥倫比亞） | 西班牙文（哥倫比亞） |
| `es-US` | español (Estados Unidos) | español (Estados Unidos) | Spanish (United States) | Spanish (United States) | 西班牙文（美國） | 西班牙文（美國） |
| `es-419` | español latinoamericano | español (Latinoamérica) | Latin American Spanish | Spanish (Latin America) | 拉丁美洲西班牙文 | 西班牙文（拉丁美洲） |
| `pt-BR` | português (Brasil) | português (Brasil) | Brazilian Portuguese | Portuguese (Brazil) | 巴西葡萄牙文 | 葡萄牙文（巴西） |
| `pt-PT` | português europeu | português (Portugal) | European Portuguese | Portuguese (Portugal) | 歐洲葡萄牙文 | 葡萄牙文（葡萄牙） |
| `fr-FR` | français (France) | français (France) | French (France) | French (France) | 法文（法國） | 法文（法國） |
| `fr-CA` | français canadien | français (Canada) | Canadian French | French (Canada) | 加拿大法文 | 法文（加拿大） |
| `de-DE` | Deutsch (Deutschland) | Deutsch (Deutschland) | German (Germany) | German (Germany) | 德文（德國） | 德文（德國） |
| `de-AT` | Österreichisches Deutsch | Deutsch (Österreich) | Austrian German | German (Austria) | 奧地利德文 | 德文（奧地利） |
| `de-CH` | Schweizer Hochdeutsch | Deutsch (Schweiz) | Swiss High German | German (Switzerland) | 瑞士德語 | 德文（瑞士） |
| `it-IT` | italiano (Italia) | italiano (Italia) | Italian (Italy) | Italian (Italy) | 意大利文（意大利） | 意大利文（意大利） |
| `nl-NL` | Nederlands (Nederland) | Nederlands (Nederland) | Dutch (Netherlands) | Dutch (Netherlands) | 荷蘭文（荷蘭） | 荷蘭文（荷蘭） |
| `pl-PL` | polski (Polska) | polski (Polska) | Polish (Poland) | Polish (Poland) | 波蘭文（波蘭） | 波蘭文（波蘭） |
| `tr-TR` | Türkçe (Türkiye) | Türkçe (Türkiye) | Turkish (Türkiye) | Turkish (Türkiye) | 土耳其文（土耳其） | 土耳其文（土耳其） |
| `ru-RU` | русский (Россия) | русский (Россия) | Russian (Russia) | Russian (Russia) | 俄文（俄羅斯） | 俄文（俄羅斯） |
| `uk-UA` | українська (Україна) | українська (Україна) | Ukrainian (Ukraine) | Ukrainian (Ukraine) | 烏克蘭文（烏克蘭） | 烏克蘭文（烏克蘭） |
| `ja-JP` | 日本語 (日本) | 日本語 (日本) | Japanese (Japan) | Japanese (Japan) | 日文（日本） | 日文（日本） |
| `ko-KR` | 한국어(대한민국) | 한국어(대한민국) | Korean (South Korea) | Korean (South Korea) | 韓文（南韓） | 韓文（南韓） |
| `th-TH` | ไทย (ไทย) | ไทย (ไทย) | Thai (Thailand) | Thai (Thailand) | 泰文（泰國） | 泰文（泰國） |
| `vi-VN` | Tiếng Việt (Việt Nam) | Tiếng Việt (Việt Nam) | Vietnamese (Vietnam) | Vietnamese (Vietnam) | 越南文（越南） | 越南文（越南） |
| `id-ID` | Indonesia (Indonesia) | Indonesia (Indonesia) | Indonesian (Indonesia) | Indonesian (Indonesia) | 印尼文（印尼） | 印尼文（印尼） |
| `ms-MY` | Melayu (Malaysia) | Melayu (Malaysia) | Malay (Malaysia) | Malay (Malaysia) | 馬來文（馬來西亞） | 馬來文（馬來西亞） |
| `fil-PH` | Filipino (Pilipinas) | Filipino (Pilipinas) | Filipino (Philippines) | Filipino (Philippines) | 菲律賓文（菲律賓） | 菲律賓文（菲律賓） |
| `hi-IN` | हिन्दी (भारत) | हिन्दी (भारत) | Hindi (India) | Hindi (India) | 印地文（印度） | 印地文（印度） |
| `hi-Latn-IN` | Hindi (Latin, Bharat) | Hindi (Latin, Bharat) | Hindi (Latin, India) | Hindi (Latin, India) | 印地文（拉丁字母，印度） | 印地文（拉丁字母，印度） |
| `bn-IN` | বাংলা (ভারত) | বাংলা (ভারত) | Bangla (India) | Bangla (India) | 孟加拉文（印度） | 孟加拉文（印度） |
| `ta-IN` | தமிழ் (இந்தியா) | தமிழ் (இந்தியா) | Tamil (India) | Tamil (India) | 泰米爾文（印度） | 泰米爾文（印度） |
| `te-IN` | తెలుగు (భారతదేశం) | తెలుగు (భారతదేశం) | Telugu (India) | Telugu (India) | 泰盧固文（印度） | 泰盧固文（印度） |
| `mr-IN` | मराठी (भारत) | मराठी (भारत) | Marathi (India) | Marathi (India) | 馬拉地文（印度） | 馬拉地文（印度） |
| `ur-PK` | اردو (پاکستان) | اردو (پاکستان) | Urdu (Pakistan) | Urdu (Pakistan) | 烏爾都文（巴基斯坦） | 烏爾都文（巴基斯坦） |
| `ar` | العربية | العربية | Arabic | Arabic | 阿拉伯文 | 阿拉伯文 |
| `ar-EG` | العربية (مصر) | العربية (مصر) | Arabic (Egypt) | Arabic (Egypt) | 阿拉伯文（埃及） | 阿拉伯文（埃及） |
| `ar-SA` | العربية (المملكة العربية السعودية) | العربية (المملكة العربية السعودية) | Arabic (Saudi Arabia) | Arabic (Saudi Arabia) | 阿拉伯文（沙地阿拉伯） | 阿拉伯文（沙地阿拉伯） |
| `ar-LB` | العربية (لبنان) | العربية (لبنان) | Arabic (Lebanon) | Arabic (Lebanon) | 阿拉伯文（黎巴嫩） | 阿拉伯文（黎巴嫩） |
| `ar-MA` | العربية (المغرب) | العربية (المغرب) | Arabic (Morocco) | Arabic (Morocco) | 阿拉伯文（摩洛哥） | 阿拉伯文（摩洛哥） |
| `he-IL` | עברית (ישראל) | עברית (ישראל) | Hebrew (Israel) | Hebrew (Israel) | 希伯來文（以色列） | 希伯來文（以色列） |
| `fa-IR` | فارسی (ایران) | فارسی (ایران) | Persian (Iran) | Persian (Iran) | 波斯文（伊朗） | 波斯文（伊朗） |
| `en` | English | English | English | English | 英文 | 英文 |
| `zh-Hant` | 繁體中文 | 中文（繁體） | Traditional Chinese | Chinese (Traditional) | 繁體中文 | 中文（繁體字） |
| `zh-Hans` | 简体中文 | 中文（简体） | Simplified Chinese | Chinese (Simplified) | 簡體中文 | 中文（簡體字） |
| `yue` | 粵語 | 粵語 | Cantonese | Cantonese | 廣東話 | 廣東話 |
| `yue-Hant` | 粵語 (繁體) | 粵語 (繁體) | Cantonese (Traditional) | Cantonese (Traditional) | 廣東話（繁體字） | 廣東話（繁體字） |
| `zh-HK` | 中文（中國香港特別行政區） | 中文（中國香港特別行政區） | Chinese (Hong Kong SAR China) | Chinese (Hong Kong SAR China) | 中文（中國香港特別行政區） | 中文（中國香港特別行政區） |
| `zh-TW` | 中文（台灣） | 中文（台灣） | Chinese (Taiwan) | Chinese (Taiwan) | 中文（台灣） | 中文（台灣） |
| `es` | español | español | Spanish | Spanish | 西班牙文 | 西班牙文 |
| `pt` | português | português | Portuguese | Portuguese | 葡萄牙文 | 葡萄牙文 |
| `ar-001` | العربية الفصحى الحديثة | العربية (العالم) | Modern Standard Arabic | Arabic (world) | 現代標準阿拉伯文 | 阿拉伯文（世界） |
| `arz` | Egyptian Arabic | Egyptian Arabic | Egyptian Arabic | Egyptian Arabic | 埃及阿拉伯文 | 埃及阿拉伯文 |
| `hi-Latn` | Hindi (Latin) | Hindi (Latin) | Hindi (Latin) | Hindi (Latin) | 印地語（拉丁文） | 印地文（拉丁字母） |

#### 2.2 Entries with poor or missing output

| Tag | Problem seen | Proposed English | Proposed autonym | Proposed zh-Hant-HK UI |
|---|---|---|---|---|
| `zh-Hant-HK` | Long political form "Hong Kong SAR China" / 中國香港特別行政區; "繁體字" suffix only in the HK locale | Chinese — Traditional (Hong Kong) | 繁體中文（香港） | 繁體中文（香港） |
| `yue-Hant-HK` | Autonym mixes half-width parentheses with a full-width comma: `粵語 (繁體，中國香港特別行政區)`. The HK locale says 廣東話 while the `yue` locale says 粵語 [9] | Cantonese (Hong Kong) | 廣東話（香港） (alias 粵語) | 廣東話（香港） |
| `zh-Hant-TW` | Pattern differs from HK/CN (`中文（繁體，台灣）` vs `繁體字`) | Chinese — Traditional (Taiwan) | 繁體中文（台灣） | 繁體中文（台灣） |
| `zh-Hans-CN` / `zh-Hans-SG` | Fine, but reads inconsistently next to the overrides | Chinese — Simplified (China) / (Singapore) | 简体中文（中国） / 简体中文（新加坡） | 簡體中文（中國） / 簡體中文（新加坡） |
| `en-GB-scotland` | "British English (Scottish Standard English)" | English (Scotland) | English (Scotland) | 英文（蘇格蘭） |
| `hi-Latn-IN` | Autonym comes back in English with "Bharat": "Hindi (Latin, Bharat)". CLDR's `alt="variant"` "Hinglish" can't be reached through `Intl` [9] | Hinglish (Hindi in Latin script) | Hinglish | 印地英語（Hinglish） |
| `ar` / `ar-001` | `ar` is just "العربية". `ar-001` under `languageDisplay:'standard'` gives "Arabic (world)" / "阿拉伯文（世界）" | Arabic — Modern Standard | العربية الفصحى | 現代標準阿拉伯文 |
| `ar-LB` | Output is fine ("العربية (لبنان)"). It says nothing about register or Arabizi, which the variety research should add as a sublabel | Arabic (Lebanon) | العربية (لبنان) | 阿拉伯文（黎巴嫩） |
| `ar-SA` | Long autonym "العربية (المملكة العربية السعودية)"; `style:'short'` does not shorten it | Arabic (Saudi Arabia) | العربية (السعودية) | 阿拉伯文（沙地阿拉伯） |
| `es-419` | Fine: "Latin American Spanish" / "español latinoamericano". Standard form is "Spanish (Latin America)" | Spanish (Latin America) | español (Latinoamérica) | 西班牙文（拉丁美洲） |
| `th-TH` | Autonym repeats itself: "ไทย (ไทย)" | Thai (Thailand) | ภาษาไทย | 泰文（泰國） |
| `id-ID` | Autonym repeats itself: "Indonesia (Indonesia)" | Indonesian | Bahasa Indonesia | 印尼文 |
| `ms-MY` | "Melayu (Malaysia)" is acceptable | Malay (Malaysia) | Bahasa Melayu (Malaysia) | 馬來文（馬來西亞） |
| `de-CH` | zh-Hant-HK dialect name "瑞士德語" mixes 語 into the 文 series | German (Switzerland) | Deutsch (Schweiz) | 德文（瑞士） |
| `bn-IN` | English says "Bangla", but users search "Bengali" | Bengali / Bangla (India) | বাংলা (ভারত) | 孟加拉文（印度） |
| `en-US`, `en-AU`, … | `dialect` mixes "American English" with "English (Ireland)", which sorts badly | English (US), English (Australia) … | same | 英文（美國）… |

Other things I found:

- **`style:'short'`** switches to CLDR's `alt="short"` names, e.g. "Chinese (Traditional, Hong Kong)" and "English (UK)" / 英文（英國）.
- **`fallback:'code'`** returns the raw code (`apc`, `afb`) when CLDR has no name. Detect this with `fallback:'none'`.
- **Capitalisation differs by engine, so the same call returns different strings:**
  - V8 (Chrome/Node) opens ICU LocaleDisplayNames with `UDISPCTX_CAPITALIZATION_NONE` [11].
  - JavaScriptCore (Safari) [12] and Gecko (Firefox) [13] use `UDISPCTX_CAPITALIZATION_FOR_STANDALONE`.
  - CLDR marks many locales' language names `titlecase-firstword` for stand-alone use (Spanish, for example) [9].
  - So Chrome shows "español de España" while Safari and Firefox are expected to show "Español de España". This is inferred from source code; I didn't run it in those browsers.
- **Data versions differ too:**
  - Firefox bundles its own ICU copy [14].
  - V8 names come from CLDR shipped with the runtime [73].
  - Safari runs on Apple's ICU build (not verified here).
  - `Intl.DisplayNames` has shipped since Chrome 81, Firefox 86 and Safari 14.1 [15].
  - Any runtime call in a Next.js page that renders on both server (Node ICU) and client (browser ICU) can produce a hydration mismatch.

**Recommendation for PostRiff:**
- **Generate a static `locales.json` at build time** from the pinned Node ICU, or better from `cldr-json`. For each locale store `autonym = {language, region}` in the locale's own language and `names[uiLocale] = {language, region}` for each UI language. Use `type:'region', style:'short'` for the region part.
- **Render the label as two lines:** line 1 is the autonym with locale-correct brackets (full-width `（）` for CJK), line 2 is the name in the UI language. Keep the language and region halves apart so sorting and grouping don't depend on CLDR's dialect names.
- **Commit hand-written overrides** for the ~15 Tier 1 entries in §2.2.
- **Runtime `Intl.DisplayNames`** is only for the long tail (non-Tier 1). Call it on the client, with `fallback:'none'`, and hide entries that return `undefined`.

---

### 3. Politically sensitive region names

**Confidence: High** for the CLDR data. **Medium** for product behaviour: I checked official docs, not live UIs.

**CLDR region names** (`main` branch; values Node also returns) [9]:

| Code | en (default / `alt=short`) | zh (Hans) | zh_Hant (TW) | zh_Hant_HK | yue | ja |
|---|---|---|---|---|---|---|
| HK | Hong Kong SAR China / **Hong Kong** | 中国香港特别行政区 / 香港 | 中國香港特別行政區 / 香港 | inherits | 中國香港特別行政區 / 香港 | 中華人民共和国香港特別行政区 / 香港 |
| MO | Macao SAR China / **Macao** | 中国澳门特别行政区 / 澳门 | 中國澳門特別行政區 / 澳門 | inherits | same as zh_Hant | …マカオ特別行政区 / マカオ |
| TW | Taiwan (no alt) | 台湾 | 台灣 | inherits | 台灣 | 台湾 |
| PS | Palestinian Territories / **Palestine** | 巴勒斯坦领土 / 巴勒斯坦 | 巴勒斯坦自治區 / 巴勒斯坦 | 巴勒斯坦領土 | 巴勒斯坦自治區 / 巴勒斯坦 | パレスチナ自治区 / パレスチナ |
| XK | Kosovo | 科索沃 | 科索沃 | inherits | 科索沃 | コソボ |
| EH | Western Sahara | 西撒哈拉 | 西撒哈拉 | inherits | 西撒哈拉 | 西サハラ |

The IANA registry, which follows ISO 3166, lists TW as "Taiwan, Province of China", HK as "Hong Kong" and PS as "State of Palestine". It has no XK [1]. CLDR's translation guidance says to "Strive for names that will be acceptable to the largest audience" [16].

**How the big platforms name Chinese variants:**

| Product | How Chinese variants are named |
|---|---|
| Apple App Store Connect | Two localisations only: **Chinese (Simplified)** and **Chinese (Traditional)**. Traditional is the default for Hong Kong, Macau and Taiwan storefronts [17] |
| Google Play Console | **Chinese (Hong Kong)** `zh-HK`, **Chinese (Taiwan)** `zh-TW`, **Chinese (PRC)** `zh-CN` [18] |
| Microsoft Windows language packs | **Chinese (Traditional, Hong Kong SAR)** `zh-HK` (marked "No longer used. See zh-TW"), **Chinese (Traditional, Taiwan)** `zh-TW`, **Chinese (Simplified, China)** `zh-CN` [19] |

**Recommendation for PostRiff:**
- **Name varieties by script first, place second, using CLDR short names.**
  - **English UI:** "Chinese — Traditional (Hong Kong)", "Chinese — Traditional (Taiwan)", "Chinese — Simplified (China)", "Chinese — Simplified (Singapore)", "Cantonese (Hong Kong)".
  - **Traditional Chinese UI:** 繁體中文（香港）, 繁體中文（台灣）, 簡體中文（中國）, 簡體中文（新加坡）, 廣東話（香港）.
- **Avoid in visible labels:** "SAR", "Province", "PRC", "ROC", "Mainland", and flags.
- **Wording:** call the grouping "Region / 地區", never "Country / 國家".
- **Search aliases:** keep the long and alternative forms here so nobody is blocked from finding an entry: "Hong Kong SAR", 中國香港, 港, 臺灣, 台湾, Taiwan, PRC, 中国大陆, 內地.
- **Sub-national variety** (Scotland): use the variant name as text.
- **Palestinian or Western Sahara locales, if ever added:** use CLDR short names (Palestine / 巴勒斯坦) and no maps.

---

### 4. Search normalization

**Confidence: High.** Every behaviour below was tested in Node v25.9.0.

**Test results:**

| Input | Technique | Result | Verdict |
|---|---|---|---|
| `Español`, `Tiếng Việt`, `Français` | NFKD + strip `\p{M}` | espanol, tieng viet, francais | ✓ |
| `हिन्दी` | NFKD + strip `\p{M}` | **हनद** (vowel signs and virama deleted) | ✗ This breaks Indic, Thai and Arabic. Strip only U+0300–U+036F |
| `한국어` | NFKD | 8 conjoining jamo | ✗ Recompose with NFC after stripping |
| `ＥＮＧＬＩＳＨ`, `ｶﾀｶﾅ` | NFKC | english, カタカナ | ✓ width folding |
| `İ` | `toLowerCase()` | `i̇` (2 code points) | ✗ Map İ→i and ı→i first; `toLocaleLowerCase('tr')` gives `i` |
| `ı` vs `i` | `Intl.Collator(undefined,{sensitivity:'base',usage:'search'})` | not equal | ✗ Collator doesn't fold dotless ı |
| `カタカナ` vs `かたかな`, `ｶﾀｶﾅ` vs `カタカナ`, `ss` vs `ß`, `o` vs `ø` | same Collator | equal | ✓ but only for whole strings. `Intl` has no substring search |
| `简体` vs `簡體` | same Collator | not equal | ✗ Needs aliases |

**A tested search-key function (no dependencies):**

```ts
export function searchKey(s: string): string {
  let t = s.normalize('NFKC').normalize('NFD')
    .replace(/[̀-ͯ]/g, '')          // Latin/Greek/Cyrillic diacritics only
    .normalize('NFC');                         // keeps Hangul and Indic intact
  t = t.replace(/İ|ı/g, 'i').toLowerCase();
  t = t.replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60)); // katakana→hiragana
  return t.replace(/\s+/g, ' ').trim();
}
// Español→espanol, ＥＮＧＬＩＳＨ→english, ｶﾀｶﾅ→かたかな, İstanbul→istanbul, हिन्दी unchanged
```

Add a five-entry map for letters NFD doesn't decompose: đ→d, ł→l, ø→o, æ→ae, ß→ss.

**Chinese Traditional/Simplified matching.**
- **OpenCC for JS** (`opencc-js` 1.4.2, MIT AND Apache-2.0) [59]:
  - Its `t2cn` UMD bundle is 109 KB and `full.js` is 1.2 MB (jsDelivr file listing). Both are too big to ship for a picker.
  - The picker needs only the roughly 100 Han characters that appear in language and region names.
- **Libraries:** `match-sorter` 8.3 (MIT, depends on `remove-accents`), `fuse.js` 7.5 (Apache-2.0, no dependencies) and `cmdk` 1.1 (MIT, Radix dependencies). None handles T/S Chinese or Indic safely by itself. With ~800 entries, fold-then-`includes` plus a ranking step is fast enough.
- **Romaji:** `wanakana` 5.3 (MIT) is only worth adding if users should type romaji to find Japanese.

**Recommendation for PostRiff:**
- **Precompute a `searchKey` per entry** over: autonym, UI-language names, tag, and aliases. Aliases include both scripts (简体/簡體/繁体/繁體, 广东话/廣東話, 粤语/粵語, 台湾/臺灣/台灣), English endonym variants (Bengali/Bangla, Farsi/Persian, Tagalog/Filipino, Hinglish) and common codes (`zh-hk`, `yue`, `arz`).
- **Hard-code the aliases** in the locale data. Optionally generate the Simplified forms of Traditional names **at build time** with `opencc-js`, as a dev dependency only.
- **Match** by prefix on word starts first, then substring.
- **Rank:** exact tag match, then Tier 1, then browser-suggested, then alphabetical by `Intl.Collator(uiLocale)`.
- **Runtime dependencies:** none.

---

### 5. Accessible combobox

**Confidence: Medium-High.** The spec and patterns are solid. Screen reader behaviour varies, so test on real devices.

**Which pattern fits the design (trigger button → popover → search input + grouped list):**
- **Select-only combobox** [21]. `role="combobox"` sits on a non-editable element, the popup is a listbox, type-ahead is supported, and there is no text input. That matches a picker **without** search.
- **Editable combobox with list autocomplete** [22]. The input carries `role="combobox"`, `aria-autocomplete="list"`, `aria-controls`, `aria-expanded` and `aria-activedescendant`, and it filters a `listbox`. That is the search part.
- **The design combines both:**
  1. A **button** (`aria-haspopup="dialog"`, `aria-expanded`) opens a **non-modal dialog/popover** on desktop, or a modal sheet on mobile.
  2. Inside it, an **editable combobox with list autocomplete** controls a **listbox**.
  3. Options are grouped with `role="group"` + `aria-labelledby` pointing at each group heading [23].
- **React Aria.** Its `Select` + `Autocomplete` + `SearchField` + `ListBox`/`ListBoxSection`/`Header` composition implements this layout, with "virtual focus" (`aria-activedescendant`) keeping DOM focus in the input [25][26]. PostRiff's `web/package.json` already depends on `react-aria-components` ^1.21.1 (and `cmdk` ^1.1.1), so this needs no new library.
- **Simpler alternative.** One editable combobox, with the trigger being the input itself. That means fewer focus hops for assistive tech, but it's less compact in a toolbar.

**Required roles and attributes:**

| Element | Roles and attributes |
|---|---|
| Trigger | `<button>`, `aria-haspopup="dialog"` (or `listbox` if there's no search), `aria-expanded`, `aria-controls`. Accessible name includes the current value, e.g. "Language: 繁體中文（香港）" |
| Popover | `role="dialog"` with `aria-labelledby` (a visible title "Language") |
| Search input | `role="combobox"`, `aria-autocomplete="list"`, `aria-expanded="true"`, `aria-controls=<listbox id>`, `aria-activedescendant=<option id>`. APG: "DOM focus is maintained on the combobox" [20] |
| Listbox | `role="listbox"` + `aria-label` |
| Groups | `role="group"` + `aria-labelledby` pointing at "Suggested", "Tuned", "All languages" [23] |
| Options | `role="option"`, `aria-selected` on the chosen option, and a `lang` attribute on the autonym span so screen readers switch voice |

**Keyboard** [20]:
- Down/Up move the active option.
- Home/End jump to the ends.
- Enter selects and closes.
- Escape closes and returns focus to the trigger.
- Typing filters.
- Alt+Down opens without moving.
- Tab should close the popover and move on; the listbox is not a tab stop.

**Result count.** The APG examples don't announce counts [22]. GOV.UK's accessible-autocomplete uses a live status region whose text comes from a configurable function that receives the option count [29]. Use a visually hidden `role="status"` (`aria-live="polite"`) updated about 300 ms after typing stops, e.g. "12 languages" or "No languages match 'xyz'".

**Focus return.** When the dialog closes, focus goes back to the element that opened it [24].

**Mobile bottom sheet:**
- Use the modal-dialog pattern: `aria-modal="true"`, focus contained, a visible Close button, and focus returned to the trigger [24].
- Put the search field at the top.
- Make rows real focusable options with DOM focus (roving `tabindex`), not only `aria-activedescendant`. VoiceOver swipe navigation moves through DOM elements.
- Don't auto-open the keyboard (no `autoFocus` on touch). It hides half the list, so let the user tap Search.

**Known issues:**
- **iOS VoiceOver:** "VoiceOver on iOS did not always announce the edit field for comboboxes" [27]. The same study found inconsistent option-menu interaction, and expandable listboxes using `aria-expanded` "entirely broken" on macOS/iOS VoiceOver.
- **Native `<datalist>`** is not a shortcut. Recent VoiceOver/iPadOS and Android bugs include iOS 26 suggestions covering the input [28].
- **APG's own warning:** the examples warn of support gaps "especially for mobile/touch devices" [22].

**Recommendation for PostRiff:**
- **Build on React Aria's** `Select` + `Autocomplete` + `SearchField` + `ListBox` sections, as used in [26].
- **Add** a debounced `role="status"` count, `lang` on autonyms, and a trigger name that includes the current value.
- **Below 768 px,** render the same collection in a modal sheet with DOM-focus rows.
- **Test on real devices:** VoiceOver macOS Safari, VoiceOver iOS Safari, TalkBack Chrome and NVDA Firefox.

---

### 6. Rendering

**Confidence:** (a) **Medium-High**, (b) **High**, (c) **Medium** (Urdu line-height values are judgement, not measured).

**(a) `lang` and CJK glyphs:**
- **The standard.** W3C: "User-agents can (and do) use language information to select language-appropriate fonts" [30]. The same Han code point takes Simplified, Traditional, Japanese or Korean shapes depending on language. CSS Fonts 4 ties the content language to the OpenType language system used for glyph substitution [34].
- **Pan-CJK fonts.** Source Han Sans and Noto Sans CJK ship SC, TC, **HK**, JP and KR variants. Their language-specific and OTC builds swap regional glyphs via `locl`. That "requires an app that supports language tagging and the OpenType 'locl' GSUB feature" [32]. Region-specific subset fonts (e.g. "Noto Sans HK", "Source Han Sans HK") hard-wire one region [31][32].
- **Android (AOSP `fonts.xml`).** Han fallback families exist only for `zh-Hans`, `zh-Hant,zh-Bopo`, `ja` and `ko`, with **no HK family** [33]. Stock Android draws `zh-HK` text with TC (Taiwan) forms unless the page supplies an HK web font. OEM builds may differ.
- **Chromium 152 on macOS (my test).**
  - The same string rendered with `font-family:sans-serif` visibly switched to Japanese forms (e.g. 令) under `lang="ja"`, compared with `zh-*`.
  - `lang="en"` fell back to a Chinese face.
  - PingFang HK, TC and SC all rendered when named explicitly.
  - At 96 px I couldn't reliably tell HK from TW apart in a screenshot, so this test proves the mechanism, not the HK/TW difference.
- **Windows:** not verified here.

**(b) RTL:**
- **User-generated text.** Use `dir="auto"` or `<bdi>`. W3C: "tightly wrap every opposite-direction phrase in markup that sets its base direction" [35]. Where markup isn't possible, use RLI/PDI isolates (U+2067/U+2069) [35].
- **`unicode-bidi: plaintext`** sets direction per paragraph from each paragraph's first strong character [36]. Chrome 48, Firefox 50 and Safari 11 support it [15]. MDN warns authors not to override `unicode-bidi` in general [36], but `plaintext` on a textarea is the one case where markup isn't available.
- **Previews.** In an RTL post, wrap each URL, @mention and #hashtag token in `<bdi>` (or `dir="ltr"` for URLs) so trailing punctuation doesn't jump.

**(c) Complex scripts:**
- **Thai, Lao, Khmer and Myanmar** break lines by dictionary lookup, which "is not 100% perfect" [39]. Line breaking and hyphenation depend on the `lang` tag [39].
- **Thai justification:** `text-justify: inter-character` fails in Gecko, Blink and WebKit [40].
- **CJK:** `line-break` (loose/normal/strict) applies to CJK and depends on `lang` [38]. `word-break: keep-all` affects CJK only; `break-all` splits Latin and Thai words anywhere. `auto-phrase` is Chrome 119+ only (not Firefox; Safari preview) [37][15].
- **Devanagari:** letter-spacing splits conjuncts, and line breaking or first-letter styling can break orthographic syllables (W3C gap analysis, 2025-05-31) [41].
- **Grapheme segmentation:** UAX #29 rule GB9c keeps consonant–virama–consonant together [57]. ICU 78 counted `नमस्ते` as 3 graphemes, so truncate with `Intl.Segmenter`, never with `.slice()`.
- **Arabic script generally:** W3C's Arabic-script gap analysis tracks the remaining bidi, justification and line-layout gaps, and notes Arabic and Persian have no hyphenation [42].
- **Urdu.** Android AOSP maps `und-Arab` only to Noto Naskh Arabic, with **no Nastaliq** [33], so Urdu on stock Android renders in Naskh style unless a web font is loaded. macOS ships `NotoNastaliq.ttc` in `/System/Library/Fonts` (observed locally). Noto Nastaliq Urdu is OFL-1.1 [43]. Nastaliq's tall stacked forms need extra line height (judgement; tune by eye).

**Recommendation for PostRiff.** Put these on every preview body and draft textarea:

```css
/* element: <div class="post-text" lang="{tag}" dir="auto"> / <textarea lang="{tag}" dir="auto"> */
.post-text, textarea.draft { unicode-bidi: plaintext; white-space: pre-wrap;
  overflow-wrap: anywhere; word-break: normal; line-break: auto; letter-spacing: 0; }
:lang(zh-Hant-HK), :lang(yue) { font-family: "PingFang HK", "Noto Sans HK", "Source Han Sans HK", "Microsoft JhengHei", sans-serif; }
:lang(zh-Hant-TW) { font-family: "PingFang TC", "Noto Sans TC", "Source Han Sans TC", "Microsoft JhengHei", sans-serif; }
:lang(zh-Hans)    { font-family: "PingFang SC", "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif; }
:lang(ja)         { font-family: "Hiragino Sans", "Noto Sans JP", "Yu Gothic", sans-serif; }
:lang(ur)         { font-family: "Noto Nastaliq Urdu", serif; line-height: 2.2; }
:lang(zh), :lang(yue), :lang(ja) { line-break: strict; }
```

- **Fonts.** Load Noto Sans HK and Noto Nastaliq Urdu as web fonts, only when a draft uses those locales. Don't rely on `lang` alone for `yue`; I haven't verified whether browsers map `yue` to HK fallback fonts.
- **Tokens.** Render URLs, mentions and hashtags in the preview inside `<bdi>`.
- **Truncation.** Use `Intl.Segmenter`, and never apply `letter-spacing` or `text-transform` to user text.

---

### 7. Platform character counting

**Confidence: Medium.** X, Bluesky, LINE, TikTok and YouTube are backed by official docs or specs. Threads is ambiguous. Instagram and LinkedIn don't state a unit. Facebook, Xiaohongshu and Weibo app limits are not verified.

**How the same strings measure** (Node v25.9.0 / ICU 78.3; X column uses the twitter-text v3 weights, emoji = 2, no URLs):

| Sample | UTF-16 units (JS .length) | Code points | Graphemes | UTF-8 bytes | X weighted (v3, approx) |
|---|---|---|---|---|---|
| English "Hello world" | 11 | 11 | 11 | 11 | 11 |
| Chinese 你好世界 | 4 | 4 | 4 | 12 | 8 |
| Cantonese 我哋喺度 | 4 | 4 | 4 | 12 | 8 |
| Japanese こんにちは | 5 | 5 | 5 | 15 | 10 |
| Korean 안녕하세요 | 5 | 5 | 5 | 15 | 10 |
| Thai สวัสดีครับ | 10 | 10 | 7 | 30 | 10 |
| Hindi नमस्ते | 6 | 6 | 3 | 18 | 6 |
| Tamil வணக்கம் | 7 | 7 | 5 | 21 | 7 |
| Arabic مرحبا | 5 | 5 | 5 | 10 | 5 |
| Urdu خوش آمدید | 9 | 9 | 9 | 17 | 9 |
| Vietnamese Việt Nam | 8 | 8 | 8 | 10 | 9 |
| Emoji 👍 | 2 | 1 | 1 | 4 | 2 |
| Emoji 👍🏽 | 4 | 2 | 1 | 8 | 2 |
| Emoji family 👨‍👩‍👧‍👦 | 11 | 7 | 1 | 25 | 2 |
| Flag 🇭🇰 | 4 | 2 | 1 | 8 | 2 |
| Curly quote “ok” | 4 | 4 | 4 | 8 | 4 |
| CJK ext-B 𠮷 | 2 | 1 | 1 | 4 | 2 |

**Platform limits and units:**

| Platform | Limit | Unit | CJK | Thai / Devanagari / Arabic | Emoji | Source |
|---|---|---|---|---|---|---|
| **X** | 280 weighted | Weighted code points after **NFC**. Code points 0–4351 (U+0000–U+10FF), U+2000–200D, U+2010–201F and U+2032–2037 count 1; everything else counts 2 | **2 each** (Han, kana, Hangul) | **1 each**: all below U+10FF. Vietnamese precomposed letters (U+1Exx) count **2** | 2 per emoji, including ZWJ sequences | [44][45] "All URLs are wrapped with t.co shortener and count as 23 characters" [44] |
| **Threads** | 500 | Docs: "Emojis are counted as the number of UTF-8 bytes." [46]. Postiz changed its whole-text count to UTF-8 bytes after 175 rejections ("Param text must be at most 500 characters long"), merged 2026-09-15 [47] | **Unclear.** If the whole text is counted in bytes, ~166 Han characters | Thai/Devanagari are 3 bytes each | 4–25 bytes | [46][47]. Also a maximum of 5 links per post [46] |
| **Instagram** caption | 2,200 | "characters" (unit unspecified). Also 30 hashtags and 20 @tags | ? | ? | ? | [48] |
| **Facebook** post | not verified | — | — | — | — | not verified |
| **LinkedIn** post | 3,000 | "characters" (unit unspecified) | ? | ? | ? | [49]. The Posts API `commentary` uses "little" format: `\| { } @ [ ] ( ) < > # \ * _ ~` must be backslash-escaped, and the full-width `＃` is a valid hashtag sign [50] |
| **TikTok** (API) | Video `title` 2,200 | "UTF-16 runes" | 1 | 1 | 2 (surrogate pairs) | [51] |
| **YouTube** | Title 100 characters; description **5,000 bytes** | Title in characters; description in bytes. `<` and `>` are not allowed | Description: 3 bytes each (≈1,666 Han) | 3 bytes | 4+ | [52] |
| **Xiaohongshu** | Title ≤20 字. Body ~1,000 字 standard; long-form notes accept 1,000+ | 字. Counting of Latin/emoji not verified | 1 | ? | ? | [53] (press report, not official docs) |
| **Weibo** | API `statuses/share`: ≤140 汉字 | 汉字 (half-width rule not verified) | 1 | ? | ? | [54]. App limits (2,000/5,000) not verified |
| **LINE** (Messaging API) | Text message 5,000 | **UTF-16 code units**; action labels and template text count grapheme clusters | 1 (BMP), 2 (Ext-B) | 1 | 2 | [55] "The Messaging API counts text characters in UTF-16 code units (16-bit)." |
| **Bluesky** | **300 graphemes** and 3,000 bytes | Graphemes plus UTF-8 bytes | 1 grapheme / 3 bytes | Graphemes (a conjunct is 1) | 1 grapheme | [56][57] |

What this means for each script:
- **CJK** hits limits first on X (×2) and on byte-counted fields: YouTube descriptions, Bluesky's byte cap, and Threads if bytes are counted (×3).
- **Thai and Devanagari** are cheap on X (weight 1), but grapheme counts (Bluesky) and code-unit counts (LINE, TikTok) differ a lot. `नमस्ते` is 6 code units but 3 graphemes.
- **Emoji** vary most: 👨‍👩‍👧‍👦 is 11 UTF-16 units, 7 code points, 1 grapheme, 25 bytes and weight 2 on X.
- **Grapheme counts depend on the Unicode/ICU version** in use (GB9c) [57], so browser and server counts can disagree for Indic text.

**Recommendation for PostRiff:**
- **Implement one `measure(platform, text)`** that returns `{used, limit, unit}` with units `x-weighted | utf16 | codepoint | grapheme | utf8`, plus a URL rule for X.
- **Per-platform choices:**
  - X: use the official `twitter-text` library (licence not checked here) or port the four ranges from `config/v3.json` [45].
  - Threads: count UTF-8 bytes until tested otherwise. It's the safe reading, and label it "Threads API limit".
- **Surfacing:**
  - Show the counter as a reminder ("≈ 34 over for Threads API") and never block drafting.
  - Keep the metric table above as unit tests. Add a live-API test for Threads CJK before trusting either reading.

---

### 8. Lint tooling for "wrong region" reminders

**Confidence: Medium-High.** Licences and activity come from GitHub/npm/PyPI metadata fetched today. Detection works in principle; accuracy is untested.

**(a) OpenCC**
- **Core:** Apache-2.0; release 1.4.2 on 2026-08-22; last push 2026-09-09 (GitHub API) [58].
- **Configs:** `s2t`, `t2s`, `s2tw`, `tw2s`, `s2hk`, `hk2s`, **`s2twp`**, **`tw2sp`**, `t2tw`, `tw2t`, `t2hk`, `hk2t`, `s2hkp`, `hk2sp`, `t2jp`, `jp2t` [58].
- **Dictionaries:** `TWPhrases.txt` has ~825 lines, **`HKPhrases.txt` ~89** [60]. opencc-js warns that the HK phrase set "is still developing and currently small; use with care" [59].
- **Diagnostic CLI modes** [58]:
  - `--segmentation`
  - `--inspect`, which gives per-stage output. The README example shows stage 2 turning mainland 數據庫/連接池 into Taiwan 資料庫/連線池.
  - `--ambiguities` (JSONL spans for one-to-many mappings)
- **Detection.** OpenCC has **no detect-region mode**. Running `s2twp --inspect` (or diffing `s2tw` against `s2twp` output) marks mainland vocabulary as the spans the phrase stage changes. The reverse (`tw2sp`) marks Taiwan vocabulary in a mainland draft.
- **Ports:**
  - **JS:** `opencc-js` 1.4.2 (MIT AND Apache-2.0, in step with upstream). Also listed as official: `opencc-wasm`, `opencc-data` and `opencc-py` (pre-release) [58][59].
  - **Python:** official binding `OpenCC` 1.4.2 on PyPI (Apache-2.0). `opencc-python-reimplemented` 0.1.7 hasn't been pushed since 2023-12.
  - **`zhconv`:** GitHub says MIT, PyPI says GPLv2+. It uses MediaWiki data, so check the licence before using it.

**(b) English spelling**
- **VarCon:** "information to convert between American, British, Canadian, and Australian spellings" [61]. Tags: A (US), B (British -ise), Z (British -ize/Oxford), C (Canadian), D (Australian). There are variant-level markers too. Licence is permissive BSD-style, with Ispell-derived notices [61].
- **SCOWL:** "MIT-like" [62].
- **LanguageTool `en-GB/replace.txt`:** ~81 US→UK *vocabulary* pairs (airplane→aeroplane). LGPL [63].

**(c) Portuguese and Spanish**
- **LanguageTool pt-PT:** `pt-PT/replace.txt` holds ~320 Brazil→Portugal vocabulary pairs (arquivo=ficheiro, equipe=equipa, concreto=betão) [63]. `pt-BR/replace.txt` holds the reverse (castanho=marrom). The data is CC BY-SA 3.0, from Portuguese Wikipedia and Wiktionary lists [63].
- **LanguageTool Spanish:** the module has **no** regional folders (only `replace.txt`, `grammar.xml`, …) [63]. I found no comparably clean, licensed es-ES vs es-419 vocabulary list.

**Recommendation for PostRiff:**
- **Chinese reminders:** run OpenCC server-side through the official Python `OpenCC` 1.4.2 binding (Apache-2.0), using the `--inspect` stage diff to flag likely mainland terms in `zh-Hant-TW` and `zh-Hant-HK` drafts. Keep HK flags low-severity because the HK dictionary is small.
- **English and Portuguese:** generate JSON maps at build time from VarCon (using only common SCOWL levels, to avoid rare-word false positives) and from LanguageTool's pt-PT/pt-BR lists. Keep CC BY-SA attribution in a NOTICE file.
- **en-GB:** accept both -ise and -ize, since Z (Oxford) spelling is legitimate.
- **Spanish:** hand-curate a short list with the variety research.
- **Surfacing:** every finding is a reminder on the draft, never a failed run.

---

### 9. Microsoft, Apple and Google localization style guides

**Confidence: High** for Microsoft (index plus resolved download filenames). **Medium** for Apple and Google.

**Microsoft.** Index: `https://learn.microsoft.com/en-us/globalization/reference/microsoft-style-guides` [64]. The codes below come from the PDF filenames each `aka.ms/<lang>-styleguide` link redirects to (`download.microsoft.com/.../<code>-StyleGuide.pdf`) [72].

| Tier 1 locale | Microsoft guide (code) |
|---|---|
| zh-Hans-CN | Chinese (Simplified) `zho-chn` |
| zh-Hant-TW | Chinese (Traditional) `zho-twn` |
| zh-Hant-HK, yue-Hant-HK, zh-Hans-SG | **none**. The closest are `zho-twn` and `zho-chn` |
| en-GB | English (United Kingdom) `eng-gbr` |
| en-US | not in the list; the English Microsoft Writing Style Guide covers it |
| en-GB-scotland, en-IE, en-AU, en-NZ, en-CA, en-IN, en-SG | **none** |
| es-ES / es-MX / es-US | `spa-esp` / `spa-mex` / `spa-usa` |
| es-419, es-AR, es-CO | **none** by country. The index lists "Spanish (Neutral)" `spa-neu` |
| pt-BR / pt-PT | `por-bra` / `por-prt` |
| fr-FR / fr-CA | French (France), link listed but filename not resolved / `fra-can` |
| de-DE | German `deu-deu`. **No** de-AT or de-CH guide |
| it-IT, nl-NL, pl-PL, tr-TR, ru-RU, uk-UA | `ita-ita`, `nld-nld`, `pol-pol`, `tur-tur`, `rus-rus`, `ukr-ukr` |
| ja-JP, ko-KR, th-TH, vi-VN, id-ID | `jpn-jpn`, `kor-kor`, `tha-tha`, `vie-vnm`, `ind-idn` |
| ms-MY | Malay (Malaysia) `may-mys`. A Brunei guide also exists |
| fil-PH | Filipino `fil-fil` |
| hi-IN / hi-Latn-IN | Hindi `hin-ind` / **none** for Latin script |
| bn-IN, ta-IN, te-IN, mr-IN | Bangla (India) `ben-ind`, Tamil `tam-tam`, Telugu `tel-ind`, Marathi `mar-ind` |
| ur-PK | Urdu `urd-pak` |
| ar, ar-EG, ar-SA, ar-LB, ar-MA | a single "Arabic" guide `ara-sau` (Saudi). **No** country variants |
| he-IL / fa-IR | `heb-isr` / `fas-irn` |

**Apple.** The public Localization page offers no downloadable glossaries or style guides. It says Xcode now supplies language-specific style guidelines to its translation agents, and points to the HIG right-to-left guidance [65].

**Google.** The public developer style guide has a single English "write for a global audience" page, not per-language guides [66].

**Recommendation for PostRiff:**
- **Where a guide exists,** the variety research should cite it with its Microsoft code as a baseline source for Tier 1 locales. Note it where we deliberately diverge: social media register is looser than Microsoft UI text.
- **Where none exists** (HK, Cantonese, SG, most English regions, es-AR/CO, de-AT/CH, Arabic countries, Hinglish), our own researched guides are the product's differentiator. Flag those guides as "no vendor baseline".

---

### 10. Flags vs languages

**Confidence: Medium-High.**

- **W3C.** Its guidance on indicating a link's language says plainly: "Flags represent countries, not languages." [67].
- **Smashing Magazine (Vitaly Friedman, 2022-05-04)** [68] recommends:
  - no flags for languages;
  - labelling languages in their own language ("Deutsch", not "German");
  - keeping language and region/location as separate choices;
  - search or autocomplete for long lists;
  - no automatic redirects based on IP or browser language: "We can't confidently infer users' preferences without asking them first." [68]
- **Flags in PostRiff.** They would be actively wrong for `es-419`, `ar-001` and `en-GB-scotland`, and politically loaded for HK and TW (§3).

**Recommendation for PostRiff:**
- **No flag icons** anywhere in the picker, including chips on drafts.
- **Each row** shows the autonym (with `lang` set) on line 1 and the UI-language name on line 2.
- **Region** appears as text. A small script badge (繁/简, Latn) is fine where script disambiguates.
- **Groups** are named by region or continent as text, never by flag.

---

### 11. Browser-detected suggestions

**Confidence: Medium** for mechanics and privacy. **Low** for how HK users actually configure their browsers: I found no data.

- **The API.** `navigator.languages` is ordered by preference, and `navigator.language` is its first element [69]. Chrome and Safari add language-only fallbacks to `Accept-Language` [69].
- **Privacy trimming.** The list is cut down in "Safari (always) and Chrome's incognito mode, where only one language is listed" [69]. A Privacy Sandbox explainer proposes sending only the top language by default; it is an early design sketch, not shipped [71].
- **Accept-Language alone is unreliable.** W3C: it is "not a good idea to use the HTTP Accept-Language header alone" [70]. Users rarely change defaults, share machines, or have language-only values.
- **What the desktop app's Chromium on macOS reported (tested):** tags like `zh-Hant-US` and `ja-US`, i.e. each macOS preferred language combined with the OS region. The region subtag reflects the **OS region setting**, not the dialect the user writes. A HK user with a US-region Mac would present `zh-Hant-US`.
- **What CLDR expects in HK:** zh_Hant 95%, yue 90%, en 51% [5]. CLDR's matcher already groups `zh_Hant_$cnsar` (HK/MO) and treats `yue`→`zh` as a one-way match [4].
- **Parent chains** `zh_Hant_MO → zh_Hant_HK`, `en_HK/en_SG/en_IN → en_001` and `es_MX/es_AR/es_CO/es_US → es_419` [5] allow sensible mapping. `@formatjs/intl-localematcher` 0.9.0 (MIT) implements CLDR best-fit matching.

**Recommendation for PostRiff:**
- **Compute suggestions client-side only.** Candidates: `navigator.languages` mapped through `intl-localematcher` to Tier 1, plus the IANA time zone PostRiff already reads through `web/src/hooks/use-local-time-zone.ts` (Asia/Hong_Kong → HK variants), plus the workspace's existing locale.
- **Show them in a "Suggested" group**, e.g. for a zh-Hant device in Asia/Hong_Kong: 繁體中文（香港）, 廣東話（香港）, English (Hong Kong→UK style).
- **Never auto-select silently.** Pre-highlight at most, and confirm on first run.
- **Don't send** the raw `navigator.languages` array or time zone to the server or to analytics. Persist only the tag the user picked.
- **Treat an empty or single-language list as normal** (Safari).

---

### Sources

1. IANA, *Language Subtag Registry* (File-Date 2026-08-08). https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry
2. Unicode CLDR, `common/supplemental/supplementalMetadata.xml` (main). https://github.com/unicode-org/cldr/blob/main/common/supplemental/supplementalMetadata.xml
3. Unicode CLDR, `common/supplemental/likelySubtags.xml`. https://github.com/unicode-org/cldr/blob/main/common/supplemental/likelySubtags.xml
4. Unicode CLDR, `common/supplemental/languageInfo.xml` (languageMatching). https://github.com/unicode-org/cldr/blob/main/common/supplemental/languageInfo.xml
5. Unicode CLDR, `common/supplemental/supplementalData.xml` (territoryInfo, parentLocales). https://github.com/unicode-org/cldr/blob/main/common/supplemental/supplementalData.xml
6. W3C Internationalization, *Choosing a Language Tag*. https://www.w3.org/International/questions/qa-choosing-language-tags
7. Google Cloud, *Speech-to-Text supported languages*. https://docs.cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages
8. Microsoft Learn, *Language support – Translator*. https://learn.microsoft.com/en-us/azure/ai-services/translator/language-support
9. Unicode CLDR, `common/main/{en,zh,zh_Hant,zh_Hant_HK,yue,ja,es}.xml` (main, CLDR 49 dev). https://github.com/unicode-org/cldr/tree/main/common/main
10. MDN, *Intl.DisplayNames() constructor*. https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DisplayNames/DisplayNames
11. V8 source, `src/objects/js-display-names.cc`. https://github.com/v8/v8/blob/main/src/objects/js-display-names.cc
12. WebKit source, `Source/JavaScriptCore/runtime/IntlDisplayNames.cpp`. https://github.com/WebKit/WebKit/blob/main/Source/JavaScriptCore/runtime/IntlDisplayNames.cpp
13. Firefox source, `intl/components/src/DisplayNames.cpp`. https://github.com/mozilla-firefox/firefox/blob/main/intl/components/src/DisplayNames.cpp
14. Firefox Source Docs, *ICU*. https://firefox-source-docs.mozilla.org/intl/icu.html
15. MDN browser-compat-data (Intl.DisplayNames, Intl.Segmenter, word-break, unicode-bidi, line-break). https://github.com/mdn/browser-compat-data
16. Unicode CLDR, *Country/Region (Territory) Names* (translation guide). https://cldr.unicode.org/translation/displaynames/countryregion-territory-names
17. Apple, *App Store Connect – App Store localizations*. https://developer.apple.com/help/app-store-connect/reference/app-store-localizations
18. Google Play Console Help, *supported languages table*. https://support.google.com/googleplay/android-developer/table/4419860
19. Microsoft Learn, *Available Language Packs for Windows*. https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/available-language-packs-for-windows
20. W3C WAI-ARIA APG, *Combobox Pattern*. https://www.w3.org/WAI/ARIA/apg/patterns/combobox/
21. W3C WAI-ARIA APG, *Select-Only Combobox Example*. https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-select-only/
22. W3C WAI-ARIA APG, *Editable Combobox With List Autocomplete Example*. https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/
23. W3C WAI-ARIA APG, *Listbox with Grouped Options*. https://www.w3.org/WAI/ARIA/apg/patterns/listbox/examples/listbox-grouped/
24. W3C WAI-ARIA APG, *Dialog (Modal) Pattern*. https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/
25. React Aria, *Autocomplete*. https://react-aria.adobe.com/Autocomplete
26. React Aria, *Select*. https://react-aria.adobe.com/Select
27. Sarah Higley, *Select Your Poison, part 2* (24 Accessibility, 2019). https://www.24a11y.com/2019/select-your-poison-part-2/
28. Adrian Roselli, *Under-Engineered Comboboxen?* https://adrianroselli.com/2023/06/under-engineered-comboboxen.html
29. alphagov, *accessible-autocomplete* README. https://github.com/alphagov/accessible-autocomplete
30. W3C Internationalization, *Why use the language attribute?* https://www.w3.org/International/questions/qa-lang-why
31. Adobe Fonts, *Source Han Sans* README (release branch). https://github.com/adobe-fonts/source-han-sans/tree/release
32. Noto Fonts, *noto-cjk Sans* README. https://github.com/notofonts/noto-cjk/blob/main/Sans/README.md
33. AOSP, `frameworks/base/data/fonts/fonts.xml` (main). https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/data/fonts/fonts.xml
34. W3C, *CSS Fonts Module Level 4*. https://www.w3.org/TR/css-fonts-4/
35. W3C Internationalization, *Inline markup and bidirectional text in HTML*. https://www.w3.org/International/articles/inline-bidi-markup/
36. MDN, *unicode-bidi*. https://developer.mozilla.org/en-US/docs/Web/CSS/unicode-bidi
37. MDN, *word-break*. https://developer.mozilla.org/en-US/docs/Web/CSS/word-break
38. MDN, *line-break*. https://developer.mozilla.org/en-US/docs/Web/CSS/line-break
39. W3C Internationalization, *Approaches to line breaking*. https://www.w3.org/International/articles/typography/linebreak
40. W3C, *Thai Gap Analysis* (Group Draft Note, 2025-06-01). https://www.w3.org/TR/thai-gap/
41. W3C, *Devanagari Gap Analysis* (2025-05-31). https://www.w3.org/TR/deva-gap/
42. W3C, *Arabic script gap analysis* (index). https://w3c.github.io/alreq/gap-analysis/
43. Noto Fonts, *nastaliq* README (OFL-1.1). https://github.com/notofonts/nastaliq
44. X Developer Platform, *Counting characters*. https://docs.x.com/fundamentals/counting-characters
45. twitter-text, `config/v3.json`. https://github.com/twitter/twitter-text/blob/master/config/v3.json
46. Meta for Developers, *Threads API – Posts*. https://developers.facebook.com/docs/threads/posts
47. gitroomhq/postiz-app, *PR #1946: count Threads post length in UTF-8 bytes*. https://github.com/gitroomhq/postiz-app/pull/1946
48. Meta for Developers, *Instagram Platform – IG User Media*. https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/
49. Microsoft Learn (LinkedIn), *UGC Post API*. https://learn.microsoft.com/en-us/linkedin/compliance/integrations/shares/ugc-post-api
50. Microsoft Learn (LinkedIn), *little Text Format*. https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format
51. TikTok for Developers, *Content Posting API – Direct Post reference*. https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
52. Google for Developers, *YouTube Data API – Videos resource*. https://developers.google.com/youtube/v3/docs/videos
53. 新浪科技, 小红书可以长文了：正文可发千字以上 (2025-07-04). https://finance.sina.com.cn/tech/roll/2025-07-04/doc-infeimam9386885.shtml
54. 微博开放平台, `statuses/share`. https://open.weibo.com/wiki/2/statuses/share
55. LINE Developers, *Character counting in a text*. https://developers.line.biz/en/docs/messaging-api/text-character-count/
56. Bluesky, `lexicons/app/bsky/feed/post.json` and AT Protocol *Lexicon* spec. https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/post.json · https://atproto.com/specs/lexicon
57. Unicode, *UAX #29 Unicode Text Segmentation* (rev. 49). https://www.unicode.org/reports/tr29/
58. BYVoid, *OpenCC* README and GitHub API metadata. https://github.com/BYVoid/OpenCC
59. nk2028, *opencc-js* README; npm registry and jsDelivr file listing. https://github.com/nk2028/opencc-js
60. OpenCC `data/dictionary` (TWPhrases.txt, HKPhrases.txt). https://github.com/BYVoid/OpenCC/tree/master/data/dictionary
61. Kevin Atkinson, *VARCON README*. http://wordlist.aspell.net/varcon-readme/
62. en-wl, *SCOWL wordlist* README. https://github.com/en-wl/wordlist
63. LanguageTool, `languagetool-language-modules/{pt,es,en}` rule resources (`pt-PT/replace.txt`, `pt-BR/replace.txt`, `en-GB/replace.txt`). https://github.com/languagetool-org/languagetool
64. Microsoft Learn, *Microsoft Localization Style Guides*. https://learn.microsoft.com/en-us/globalization/reference/microsoft-style-guides
65. Apple Developer, *Localization*. https://developer.apple.com/localization/
66. Google developer documentation style guide, *Write for a global audience*. https://developers.google.com/style/translation
67. W3C Internationalization, *Indicating the language of a link destination*. https://www.w3.org/International/questions/qa-link-lang
68. Vitaly Friedman, *Designing A Better Language Selector*, Smashing Magazine (2022-05-04). https://www.smashingmagazine.com/2022/05/designing-better-language-selector/
69. MDN, *Navigator: languages property*. https://developer.mozilla.org/en-US/docs/Web/API/Navigator/languages
70. W3C Internationalization, *Accept-Language used for locale setting*. https://www.w3.org/International/questions/qa-accept-lang-locales
71. explainers-by-googlers, *Reduce Accept-Language*. https://github.com/explainers-by-googlers/reduce-accept-language
72. Microsoft download redirect targets for `https://aka.ms/<language>-styleguide` (resolved 2026-09-16 via HTTP `Location` headers).
73. V8, *Intl.DisplayNames* feature explainer. https://v8.dev/features/intl-displaynames

Local test scripts used for the tables (in this research folder): `lsr.py`, `canon.mjs`, `canon_table.py`, `dn.mjs`, `region.mjs`, `misc.mjs`, `fold.mjs` and `count.mjs`. Package metadata came from registry.npmjs.org, pypi.org and api.github.com, fetched on 2026-09-16.

---

### Open questions

1. **Threads CJK counting.** Does the Threads API count *all* text in UTF-8 bytes (≈166 Han characters max) or only emoji? Meta's docs mention only emoji [46], and Postiz inferred the stricter rule from failures [47]. Needs one live API test with a 200-character Chinese post.
2. **`yue` font fallback.** Do Chrome, Safari and Firefox map `lang="yue"` / `yue-Hant-HK` to HK/TC Han fonts, or treat it as an unknown language? The `:lang(yue)` font stack works around this either way, but on Android the answer decides whether a web font is mandatory.
3. **Safari and Firefox display-name output.** The capitalisation difference is inferred from engine source [11][12][13]. Actual strings, and which CLDR version Safari's ICU carries, weren't checked in those browsers.
4. **Facebook, Xiaohongshu and Weibo limits.** No official, current (2026) documentation was opened for Facebook's post limit, Xiaohongshu's half-width counting, or Weibo's in-app 2,000/5,000 limits and whether two half-width characters count as one 字.
5. **Instagram and LinkedIn units.** Is "characters" UTF-16 units, code points or graphemes? That matters for emoji-heavy captions. Does LinkedIn's little-format backslash escaping count toward the 3,000?
6. **Arabic register in the picker.** With `ar-EG` etc. as stored tags, should Egyptian or Levantine *colloquial* be a separate picker row (a sublabel on the same tag) or a style option inside one row? That's a decision for the variety research.
7. **Cantonese label.** 廣東話 (CLDR zh_Hant_HK name, common in HK) or 粵語 (CLDR `yue` autonym) as the primary autonym. The variety research should decide; keep the other as a search alias.
8. **HK browser language settings.** I found no data on what HK users' `navigator.languages` look like (`zh-HK`, `zh-Hant-HK`, `zh-TW` or `en-*`). Consider logging anonymised, opt-in picker choices against a suggested-or-not flag, never the raw array.
9. **Windows CJK fallback.** Microsoft JhengHei/YaHei are named in the CSS stack from general knowledge; Windows' `lang`-driven Han font selection wasn't tested.
10. **twitter-text licence and maintenance** in 2026 wasn't checked. Porting the 4 ranges from `v3.json` [45] avoids depending on it.
