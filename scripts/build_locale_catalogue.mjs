#!/usr/bin/env node
// Builds the locale catalogue shared by the Python backend and the web app.
//
//   node scripts/build_locale_catalogue.mjs
//
// Writes src/postriff_phase2/locale_catalogue.json and web/src/lib/locales/catalogue.generated.json
// (identical bytes; tests/test_postriff_locales.py fails when they differ). Researched locales are
// written by hand below; every other language comes from this Node's ICU/CLDR names at build time,
// so no browser ever calls Intl.DisplayNames for them at runtime and server and client agree.
// Research: docs/postriff-language-registers.md. Plan: docs/postriff-worldwide-languages-plan.md.
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = '2026-09-16.1';
const GUIDE_DIR = 'skills/postriff-content-engine/references/locales';

const FAMILIES = [
  ['zh', 'Chinese', '中文'], ['en', 'English', ''], ['es', 'Spanish', 'Español'], ['pt', 'Portuguese', 'Português'],
  ['fr', 'French', 'Français'], ['de', 'German', 'Deutsch'], ['eu', 'More of Europe', ''], ['as', 'East & Southeast Asia', ''],
  ['sa', 'South Asia', ''], ['me', 'Arabic, Hebrew & Persian', ''], ['more', 'More languages', '']
];

// Full guides for the first wave; every other researched locale has a compact guide.
const FIRST_WAVE = new Set(['en-GB', 'zh-Hans-CN', 'zh-Hant-HK', 'en-US', 'yue-Hant-HK', 'zh-Hant-TW', 'zh-Hans-SG', 'ja-JP', 'ko-KR', 'es-MX', 'pt-BR', 'fr-FR']);

// Grammar that shows the writer's gender (verbs, adjectives, particles or self-reference).
const GENDERED = new Set(['hi-IN', 'hi-Latn-IN', 'mr-IN', 'ur-PK', 'pl-PL', 'ru-RU', 'uk-UA', 'fr-FR', 'fr-CA', 'it-IT',
  'es-ES', 'es-MX', 'es-AR', 'es-CO', 'es-US', 'es-419', 'pt-BR', 'pt-PT', 'ar-001', 'ar-EG', 'ar-SA', 'ar-LB', 'ar-MA', 'he-IL',
  'th-TH', 'ja-JP', 'vi-VN']);
const CHARACTER_COUNTED = new Set(['zh', 'yue', 'ja', 'th']);

// tag, family, name in the language, English name, prompt name (null = English name), search aliases, names used in "write it in …", parent
const TUNED = [
  ['zh-Hant-HK', 'zh', '繁體中文（香港）', 'Chinese — Traditional (Hong Kong)', 'Standard written Chinese as used in Hong Kong (Traditional characters, Hong Kong vocabulary)', 'hong kong|hk|香港|港|繁體|繁体|traditional|書面語|书面语|written chinese|macau|澳門|澳门|hong kong sar|中國香港|中国香港', 'hong kong chinese|港式中文|香港中文|港式書面語', null],
  ['yue-Hant-HK', 'zh', '廣東話（香港）', 'Cantonese (Hong Kong)', 'Written Cantonese as used in Hong Kong (Traditional characters)', 'cantonese|canto|廣東話|广东话|粵語|粤语|廣府話|港式|口語|口语|hong kong|hk|香港|繁體|繁体|zh-yue', 'cantonese|hong kong cantonese|廣東話|广东话|粵語|粤语|口語', 'zh-Hant-HK'],
  ['zh-Hant-TW', 'zh', '繁體中文（台灣）', 'Chinese — Traditional (Taiwan)', 'Taiwan Mandarin (Traditional characters, Taiwan vocabulary)', 'taiwan|tw|台灣|臺灣|台湾|國語|国语|華語|mandarin|繁體|繁体|traditional|正體|正体', 'taiwanese mandarin|taiwanese chinese|台灣中文|臺灣中文|台灣華語|台灣國語', null],
  ['zh-Hans-CN', 'zh', '简体中文（中国）', 'Chinese — Simplified (China)', 'Mandarin Chinese as written in mainland China (Simplified characters)', 'mainland|china|cn|prc|中国|中國|大陆|大陸|中国大陆|中國大陸|内地|內地|普通话|普通話|mandarin|putonghua|简体|簡體|simplified', 'mandarin|mainland chinese|普通话|普通話|大陆中文|大陸中文|内地中文|內地中文|大陸簡體|大陆简体', null],
  ['zh-Hans-SG', 'zh', '简体中文（新加坡）', 'Chinese — Simplified (Singapore)', 'Singapore Chinese (Simplified characters, Singapore vocabulary)', 'singapore|sg|新加坡|华文|華文|malaysia|马来西亚|馬來西亞|简体|simplified', 'singapore chinese|新加坡华文', null],
  ['en-US', 'en', 'English (US)', 'English (United States)', 'American English', 'american|usa|us|united states|america', 'american english|us english|美式英文|美國英文|美国英文', null],
  ['en-GB', 'en', 'English (UK)', 'English (United Kingdom)', 'British English', 'british|uk|britain|england|gb|united kingdom', 'british english|uk english|英式英文|英國英文|英国英文', null],
  ['en-GB-scotland', 'en', 'English (Scotland)', 'Scottish English', 'Scottish Standard English', 'scottish|scotland|scots english|alba', 'scottish english', 'en-GB'],
  ['en-IE', 'en', 'English (Ireland)', 'Irish English', null, 'irish|ireland|eire|éire', 'irish english', null],
  ['en-AU', 'en', 'English (Australia)', 'Australian English', null, 'australian|aussie|australia|oz', 'australian english', null],
  ['en-NZ', 'en', 'English (New Zealand)', 'New Zealand English', null, 'kiwi|nz|new zealand|aotearoa', 'new zealand english|kiwi english', null],
  ['en-CA', 'en', 'English (Canada)', 'Canadian English', null, 'canadian|canada', 'canadian english', null],
  ['en-IN', 'en', 'English (India)', 'Indian English', null, 'indian|india', 'indian english', null],
  ['en-SG', 'en', 'English (Singapore)', 'Singapore English', null, 'singapore|singlish|sg', 'singapore english|singlish', null],
  ['es-ES', 'es', 'Español (España)', 'Spanish (Spain)', 'Spanish as written in Spain', 'castellano|castilian|spain|espana|españa|european spanish', 'castilian|castilian spanish|castellano', null],
  ['es-MX', 'es', 'Español (México)', 'Spanish (Mexico)', 'Mexican Spanish', 'mexican|mexicano|mexico|méxico|latino', 'mexican spanish', 'es-419'],
  ['es-AR', 'es', 'Español (Argentina)', 'Spanish (Argentina)', 'Rioplatense Spanish as written in Argentina (voseo)', 'argentine|argentino|argentina|rioplatense|uruguay|voseo', 'argentine spanish|rioplatense', 'es-419'],
  ['es-CO', 'es', 'Español (Colombia)', 'Spanish (Colombia)', 'Colombian Spanish', 'colombian|colombiano|colombia', 'colombian spanish', 'es-419'],
  ['es-US', 'es', 'Español (Estados Unidos)', 'Spanish (United States)', 'Spanish for US Hispanic readers', 'us spanish|hispanic|latino|spanglish', 'us spanish', 'es-419'],
  ['es-419', 'es', 'Español (Latinoamérica)', 'Spanish (Latin America)', 'Neutral Latin American Spanish', 'latam|latin american|latinoamericano|latinoamerica|latinoamérica|neutral spanish', 'latin american spanish|latam spanish', null],
  ['pt-BR', 'pt', 'Português (Brasil)', 'Portuguese (Brazil)', 'Brazilian Portuguese', 'brazilian|brasileiro|brasil|brazil|br', 'brazilian portuguese|portugues brasileiro|português brasileiro', null],
  ['pt-PT', 'pt', 'Português (Portugal)', 'Portuguese (Portugal)', 'European Portuguese', 'european portuguese|portugal', 'european portuguese', null],
  ['fr-FR', 'fr', 'Français (France)', 'French (France)', 'French as written in France', 'francais|français|france', 'french from france', null],
  ['fr-CA', 'fr', 'Français (Canada)', 'French (Canada)', 'Québec French', 'quebecois|québécois|quebec|québec|canadian french', 'quebec french|quebecois|québécois|canadian french', null],
  ['de-DE', 'de', 'Deutsch (Deutschland)', 'German (Germany)', 'German as written in Germany', 'deutsch|germany|deutschland', '', null],
  ['de-AT', 'de', 'Deutsch (Österreich)', 'German (Austria)', 'Austrian German', 'austrian|osterreich|österreich|austria', 'austrian german', 'de-DE'],
  ['de-CH', 'de', 'Deutsch (Schweiz)', 'German (Switzerland)', 'Swiss Standard German (no ß)', 'swiss german|schweizerdeutsch|swiss|schweiz|suisse', 'swiss german', 'de-DE'],
  ['it-IT', 'eu', 'Italiano', 'Italian', null, 'italiano|italy|italia', 'italian|italiano', null],
  ['nl-NL', 'eu', 'Nederlands', 'Dutch (Netherlands)', null, 'dutch|nederlands|holland|netherlands', 'dutch|nederlands', null],
  ['pl-PL', 'eu', 'Polski', 'Polish', null, 'polish|polska|poland', 'polish|polski', null],
  ['tr-TR', 'eu', 'Türkçe', 'Turkish', null, 'turkish|turkce|türkiye|turkiye|turkey', 'turkish|türkçe|turkce', null],
  ['ru-RU', 'eu', 'Русский', 'Russian', null, 'russian|russkiy|russia|россия', 'russian|русский', null],
  ['uk-UA', 'eu', 'Українська', 'Ukrainian', null, 'ukrainian|ukrainska|ukraine|україна', 'ukrainian|українська', null],
  ['ja-JP', 'as', '日本語', 'Japanese', null, 'japanese|nihongo|日文|日語|日语|japan|日本|jp', 'japanese|日文|日語|日语|日本語', null],
  ['ko-KR', 'as', '한국어', 'Korean', null, 'korean|hangugeo|韓文|韩文|韓語|korea|한국', 'korean|韓文|韩文|韓語|한국어', null],
  ['th-TH', 'as', 'ไทย', 'Thai', null, 'thai|thailand|ภาษาไทย|泰文', 'thai|泰文', null],
  ['vi-VN', 'as', 'Tiếng Việt', 'Vietnamese', null, 'vietnamese|tieng viet|vietnam|viet nam|越南文', 'vietnamese|越南文|tiếng việt', null],
  ['id-ID', 'as', 'Bahasa Indonesia', 'Indonesian', null, 'indonesian|indonesia|bahasa', 'indonesian|bahasa indonesia', null],
  ['ms-MY', 'as', 'Bahasa Melayu', 'Malay (Malaysia)', 'Malaysian Malay', 'malay|melayu|malaysia|bahasa malaysia|马来文|馬來文', 'malay|bahasa melayu', null],
  ['fil-PH', 'as', 'Filipino', 'Filipino', 'Filipino (Tagalog, Taglish as usual on social media)', 'tagalog|taglish|pilipinas|philippines|pinoy|tl', 'filipino|tagalog|taglish', null],
  ['hi-IN', 'sa', 'हिन्दी', 'Hindi', 'Hindi (Devanagari script)', 'hindi|हिंदी|india|bharat', 'hindi|हिंदी|हिन्दी', null],
  ['hi-Latn-IN', 'sa', 'Hinglish', 'Hindi in Roman script (Hinglish)', 'Hindi written in Roman (Latin) script, as in Hinglish social posts', 'hinglish|roman hindi|romanized hindi|hindi latin', 'hinglish|roman hindi', null],
  ['bn-IN', 'sa', 'বাংলা (ভারত)', 'Bengali (India)', 'Bengali as written in West Bengal', 'bengali|bangla|west bengal|kolkata|বাংলা', 'bengali|bangla', null],
  ['bn-BD', 'sa', 'বাংলা (বাংলাদেশ)', 'Bengali (Bangladesh)', 'Bengali as written in Bangladesh', 'bangladesh|bangladeshi|bengali|bangla|dhaka|বাংলাদেশ', 'bangladeshi bengali', 'bn-IN'],
  ['ta-IN', 'sa', 'தமிழ்', 'Tamil', null, 'tamil|tanglish|tamil nadu|தமிழ்', 'tamil', null],
  ['te-IN', 'sa', 'తెలుగు', 'Telugu', null, 'telugu|తెలుగు', 'telugu', null],
  ['mr-IN', 'sa', 'मराठी', 'Marathi', null, 'marathi|मराठी', 'marathi', null],
  ['ur-PK', 'sa', 'اردو', 'Urdu', 'Urdu (Arabic script, Nastaliq)', 'urdu|pakistan|roman urdu|اردو', 'urdu', null],
  ['ar-001', 'me', 'العربية الفصحى', 'Arabic (Modern Standard)', 'Modern Standard Arabic for a pan-Arab audience', 'arabic|msa|fusha|فصحى|arabi|العربية', 'arabic|standard arabic|fusha|العربية', null],
  ['ar-EG', 'me', 'العربية (مصر)', 'Arabic (Egypt)', 'Egyptian Arabic (dialect, Arabic script)', 'egyptian|masri|مصري|egypt', 'egyptian arabic|masri', null],
  ['ar-SA', 'me', 'العربية (السعودية)', 'Arabic (Saudi Arabia)', 'Gulf (Saudi) Arabic (dialect, Arabic script)', 'saudi|gulf|khaleeji|خليجي|uae|emirati', 'saudi arabic|gulf arabic|khaleeji', null],
  ['ar-LB', 'me', 'العربية (لبنان)', 'Arabic (Lebanon)', 'Levantine (Lebanese) Arabic (dialect, Arabic script)', 'lebanese|levantine|shami|شامي|syria|jordan|palestine', 'lebanese arabic|levantine arabic|shami', null],
  ['ar-MA', 'me', 'العربية (المغرب)', 'Arabic (Morocco)', 'Moroccan Darija (Arabic script)', 'darija|الدارجة|moroccan|maghreb|algeria|tunisia', 'moroccan arabic|darija', null],
  ['he-IL', 'me', 'עברית', 'Hebrew', null, 'hebrew|ivrit|israel|עברית', 'hebrew|עברית', null],
  ['fa-IR', 'me', 'فارسی', 'Persian', 'Persian (Iran)', 'persian|farsi|iran|parsi|فارسی', 'persian|farsi|فارسی', null]
];

// A language with no region: valid, drafts with the family guide, and the composer reminds the person to pick one.
const REGIONLESS = [
  ['en', 'en', 'English', 'English', 'English (no region chosen)', 'english|英文|英語|英语', 'english|英文|英語|英语'],
  ['zh-Hant', 'zh', '繁體中文', 'Traditional Chinese', 'Chinese in Traditional characters (no region chosen)', 'traditional chinese|繁體|繁体|繁中|正體', 'traditional chinese|繁體中文|繁体中文|繁中|繁體|繁体|chinese|中文'],
  ['zh-Hans', 'zh', '简体中文', 'Simplified Chinese', 'Chinese in Simplified characters (no region chosen)', 'simplified chinese|简体|簡體|简中', 'simplified chinese|简体中文|簡體中文|简中|簡體|简体'],
  ['es', 'es', 'Español', 'Spanish', 'Spanish (no region chosen)', 'spanish|espanol|西班牙文', 'spanish|español|espanol'],
  ['pt', 'pt', 'Português', 'Portuguese', 'Portuguese (no region chosen)', 'portuguese|portugues', 'portuguese|português|portugues'],
  ['fr', 'fr', 'Français', 'French', 'French (no region chosen)', 'french|francais|法文', 'french|français|francais|法文'],
  ['de', 'de', 'Deutsch', 'German', 'German (no region chosen)', 'german|deutsch|德文', 'german|deutsch|德文'],
  ['ar', 'me', 'العربية', 'Arabic', 'Arabic (no region chosen)', 'arabic|عربي', '']
];

// Accepted on input only; never stored.
const INPUT_ALIASES = {
  'zh-hk': 'zh-Hant-HK', 'zh-tw': 'zh-Hant-TW', 'zh-cn': 'zh-Hans-CN', 'zh-sg': 'zh-Hans-SG', 'zh-mo': 'zh-Hant-MO',
  'zh-yue': 'yue-Hant-HK', 'yue': 'yue-Hant-HK', 'yue-hk': 'yue-Hant-HK', 'yue-hant': 'yue-Hant-HK',
  'tl': 'fil-PH', 'tl-ph': 'fil-PH', 'fil': 'fil-PH', 'iw': 'he-IL', 'iw-il': 'he-IL', 'he': 'he-IL', 'in': 'id-ID', 'in-id': 'id-ID', 'zsm': 'ms-MY',
  'arz': 'ar-EG', 'arz-eg': 'ar-EG', 'ary': 'ar-MA', 'ary-ma': 'ar-MA', 'apc': 'ar-LB', 'ajp': 'ar-LB', 'apc-lb': 'ar-LB',
  'cmn-cn': 'zh-Hans-CN', 'cmn-tw': 'zh-Hant-TW', 'cmn-hans-cn': 'zh-Hans-CN', 'cmn-hant-tw': 'zh-Hant-TW'
};
// Values stored before locale tags existed.
const LEGACY = { 'English': 'en', '繁體中文': 'zh-Hant' };

// A channel's usual language (its channel skill's planning language, resolved to a region).
const USUAL = {
  Xiaohongshu: 'zh-Hans-CN', Weibo: 'zh-Hans-CN', Douyin: 'zh-Hans-CN', Bilibili: 'zh-Hans-CN', Zhihu: 'zh-Hans-CN',
  'WeChat Channels': 'zh-Hans-CN', Kuaishou: 'zh-Hans-CN', 'Tencent QQ': 'zh-Hans-CN', 'Feishu / Lark': 'zh-Hans-CN',
  Dcard: 'zh-Hant-TW', note: 'ja-JP', 'LINE Official Account': 'ja-JP', 'Naver Blog': 'ko-KR', 'KakaoTalk Channel': 'ko-KR',
  Moj: 'hi-IN', ShareChat: 'hi-IN'
};

const ISO = 'af am as az be bg bo br bs ca ce co cs cy da dv dz ee el eo et eu ff fi fo fy ga gd gl gn gu gv ha haw hr ht hu hy ia ig is iu jv ka kk kl km kn ks ku ky la lb lg ln lo lt lv mg mi mk ml mn mt my nb ne nn oc om or os pa ps qu rm rn ro rw sa sc sd se si sk sl sm sn so sq sr st su sv sw tg ti tk tn to ts tt ug uz wo xh yi yo zu ceb hmn chr'.split(' ');
const REGIONAL_EXTRA = [['zh-Hant-MO', 'zh', 'zh-Hant-HK'], ['en-HK', 'en', null], ['en-PH', 'en', null], ['en-ZA', 'en', null], ['en-NG', 'en', null],
  ['es-CL', 'es', 'es-419'], ['es-PE', 'es', 'es-419'], ['es-VE', 'es', 'es-419'], ['pt-AO', 'pt', 'pt-PT'], ['pt-MZ', 'pt', 'pt-PT'],
  ['fr-BE', 'fr', 'fr-FR'], ['fr-CH', 'fr', 'fr-FR'], ['nl-BE', 'eu', 'nl-NL'], ['it-CH', 'eu', 'it-IT'], ['ar-AE', 'me', 'ar-SA'],
  ['ar-JO', 'me', 'ar-LB'], ['ar-DZ', 'me', 'ar-MA'], ['ar-TN', 'me', 'ar-MA'], ['ta-LK', 'sa', 'ta-IN'], ['ta-SG', 'sa', 'ta-IN'], ['ms-SG', 'as', 'ms-MY']];
const RTL = new Set(['ar', 'fa', 'ur', 'he', 'ps', 'sd', 'ug', 'yi', 'dv', 'ckb']);

function split(tag) { return tag.split('-'); }
function flagFor(tag) {
  const parts = split(tag);
  if (parts.some((p) => p.toLowerCase() === 'scotland')) return String.fromCodePoint(0x1F3F4, 0xE0067, 0xE0062, 0xE0073, 0xE0063, 0xE0074, 0xE007F);
  const region = parts.slice(1).find((p) => /^[A-Z]{2}$/.test(p) || /^[0-9]{3}$/.test(p));
  if (!region) return String.fromCodePoint(0x1F310);
  if (region === '419') return String.fromCodePoint(0x1F30E);
  if (/^[0-9]{3}$/.test(region)) return String.fromCodePoint(0x1F30D);
  return String.fromCodePoint(...[...region].map((c) => 0x1F1E6 + c.charCodeAt(0) - 65));
}
function glyphsFor(tag) {
  const t = tag.toLowerCase();
  if (/^(zh-hant-(hk|mo)|yue)/.test(t)) return 'hk';
  if (/^zh-hant/.test(t)) return 'tw';
  if (/^zh/.test(t)) return 'cn';
  if (/^ja/.test(t)) return 'ja';
  if (/^ko/.test(t)) return 'ko';
  if (/^ur/.test(t)) return 'ur';
  if (/^(ar|fa|ps)(-|$)/.test(t)) return 'ar';
  if (/^he/.test(t)) return 'he';
  return null;
}
const list = (s) => (s ? s.split('|').filter(Boolean) : []);
const guidePath = (tag) => `${GUIDE_DIR}/${tag}.md`;

const entries = [];
for (const [tag, family, native, english, promptName, aliases, namedAs, parent] of TUNED) {
  const base = split(tag)[0];
  entries.push({ tag, family, native, english, promptName: promptName || english, aliases: list(aliases), namedAs: list(namedAs),
    tier: 'tuned', guide: `references/locales/${tag}.md`, guideDepth: FIRST_WAVE.has(tag) ? 'full' : 'compact', reviewed: false,
    regionless: false, parent, dir: RTL.has(base) ? 'rtl' : 'ltr', glyphs: glyphsFor(tag), flag: flagFor(tag),
    countUnit: CHARACTER_COUNTED.has(base) ? 'characters' : 'words', gendered: GENDERED.has(tag) });
}
for (const [tag, family, native, english, promptName, aliases, namedAs] of REGIONLESS) {
  const base = split(tag)[0];
  entries.push({ tag, family, native, english, promptName, aliases: list(aliases), namedAs: list(namedAs), tier: 'available', guide: null,
    guideDepth: null, reviewed: false, regionless: true, parent: null, dir: RTL.has(base) ? 'rtl' : 'ltr', glyphs: glyphsFor(tag),
    flag: flagFor(tag), countUnit: CHARACTER_COUNTED.has(base) ? 'characters' : 'words', gendered: false });
}
const englishNames = new Intl.DisplayNames(['en'], { type: 'language', fallback: 'none' });
const regionNames = new Intl.DisplayNames(['en'], { type: 'region', style: 'short', fallback: 'none' });
const autonym = (tag) => { try { return new Intl.DisplayNames([tag], { type: 'language', fallback: 'none' }).of(tag) || null; } catch { return null; } };
const known = new Set(entries.map((e) => e.tag));
// Only scripts with letter case; Georgian has a separate capital alphabet that names never use.
const capitalise = (s) => (s && /^[\p{Script=Latin}\p{Script=Greek}\p{Script=Cyrillic}\p{Script=Armenian}]/u.test(s) ? s.charAt(0).toLocaleUpperCase() + s.slice(1) : s);
// Language part plus a short region part, so no label says "SAR China" (standards research §2–3).
const NAME_OVERRIDES = { 'zh-Hant-MO': ['繁體中文（澳門）', 'Chinese — Traditional (Macao)'] };
function regionalNames(tag) {
  if (NAME_OVERRIDES[tag]) return NAME_OVERRIDES[tag];
  const parts = split(tag), base = parts[0], region = parts.at(-1);
  const english = `${englishNames.of(base)} (${regionNames.of(region)})`;
  let native = english;
  try {
    const own = capitalise(new Intl.DisplayNames([tag], { type: 'language', fallback: 'none' }).of(base));
    const ownRegion = new Intl.DisplayNames([tag], { type: 'region', style: 'short', fallback: 'none' }).of(region);
    if (own && ownRegion) native = `${own} (${ownRegion})`;
  } catch { /* keep the English name */ }
  return [native, english];
}
for (const [tag, family, parent] of REGIONAL_EXTRA) {
  if (!englishNames.of(tag) || known.has(tag)) continue;
  const [native, english] = regionalNames(tag);
  const region = split(tag).at(-1);
  const base = split(tag)[0];
  entries.push({ tag, family, native, english, promptName: english,
    aliases: [regionNames.of(region), region].filter(Boolean).map((s) => s.toLowerCase()), namedAs: [], tier: 'available', guide: null,
    guideDepth: null, reviewed: false, regionless: false, parent, dir: RTL.has(base) ? 'rtl' : 'ltr', glyphs: glyphsFor(tag),
    flag: flagFor(tag), countUnit: CHARACTER_COUNTED.has(base) ? 'characters' : 'words', gendered: false });
  known.add(tag);
}
const tunedBases = new Set(entries.map((e) => split(e.tag)[0]));
const more = [];
for (const code of ISO) {
  if (tunedBases.has(code)) continue;
  const english = englishNames.of(code);
  if (!english || english === code) continue;
  more.push({ tag: code, family: 'more', native: capitalise(autonym(code)) || english, english, promptName: english, aliases: [], namedAs: [english.toLowerCase()],
    tier: 'available', guide: null, guideDepth: null, reviewed: false, regionless: true, parent: null, dir: RTL.has(code) ? 'rtl' : 'ltr',
    glyphs: glyphsFor(code), flag: flagFor(code), countUnit: 'words', gendered: false });
}
more.sort((a, b) => a.english.localeCompare(b.english, 'en'));
entries.push(...more);

for (const e of entries) {
  if (e.guide && !existsSync(resolve(ROOT, 'skills/postriff-content-engine', e.guide))) {
    console.warn(`missing guide for ${e.tag}: ${e.guide}`);
  }
  if (Intl.getCanonicalLocales(e.tag)[0] !== e.tag) throw new Error(`not canonical: ${e.tag} → ${Intl.getCanonicalLocales(e.tag)[0]}`);
}

const catalogue = {
  version: VERSION,
  generatedBy: 'scripts/build_locale_catalogue.mjs',
  icu: process.versions.icu,
  cldr: process.versions.cldr,
  families: FAMILIES.map(([id, label, native]) => ({ id, label, native })),
  legacy: LEGACY,
  inputAliases: INPUT_ALIASES,
  usual: USUAL,
  defaultLocale: 'en',
  familyGuides: ['zh', 'en', 'es', 'pt', 'fr', 'de', 'ar'],
  entries
};
const json = JSON.stringify(catalogue, null, 1) + '\n';
for (const out of ['src/postriff_phase2/locale_catalogue.json', 'web/src/lib/locales/catalogue.generated.json']) {
  const path = resolve(ROOT, out);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, json);
}
console.log(`${entries.length} locales (${entries.filter((e) => e.tier === 'tuned').length} researched) · ICU ${process.versions.icu} / CLDR ${process.versions.cldr}`);
