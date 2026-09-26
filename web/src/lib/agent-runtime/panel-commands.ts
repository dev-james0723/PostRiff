/**
 * Spoken requests the Rafii panel carries out at once, in the browser, without a model turn (Contract 4 in
 * docs/design/rafii-live-agent/CONTRACTS.md): end the call, mute, stop talking, change how Rafii talks, open the style
 * settings, open a page, start a guide. Matching is deliberately conservative: only a whole request that is nothing but
 * one of these intents matches ("bye", "take me to Channels", "教我點樣連接 Instagram"). Anything longer or mixed
 * ("write a bye-bye post for my followers") goes to the agent exactly as before.
 *
 * English, Cantonese and Mandarin share one set of phrase lists: text is normalised first (width, case, punctuation,
 * apostrophes, and the simplified characters these phrases use are mapped to traditional ones).
 *
 * Pages come from the route manifest's titles (plus a few Chinese names), guides from the guide manifest's keywords.
 * Style changes use fixed English sentences chosen by enum value; the person's own words never become instructions.
 *
 * Pure (no React, no browser APIs), so `web/tests/panel-commands.test.cjs` loads it in node.
 */
import guideManifestJson from '../site-agent/guide-manifest.json';
import routeManifestJson from '../site-agent/route-manifest.json';
import { DETAILS, INITIATIVE, LANGUAGES, PACES, PRESETS, TONES, VOICES, type AgentStylePatch } from './style';

export interface CatalogRoute {
  id: string;
  pattern: string;
  title: string;
  navigable?: boolean;
}

export interface CatalogGuide {
  id: string;
  routeId: string;
  title: string;
  keywords: string[];
}

export interface PanelCatalog {
  routes: CatalogRoute[];
  guides: CatalogGuide[];
}

export const DEFAULT_CATALOG: PanelCatalog = {
  routes: (routeManifestJson as { routes: CatalogRoute[] }).routes,
  guides: (guideManifestJson as { guides: CatalogGuide[] }).guides
};

export type PanelCommand =
  | { kind: 'end_call' }
  | { kind: 'mute' }
  | { kind: 'stop_speaking' }
  /** `confirm`: the one sentence Rafii says once the change is saved. */
  | { kind: 'style'; patch: AgentStylePatch; confirm: string }
  | { kind: 'open_style' }
  | { kind: 'navigate'; href: string; routeId: string; title: string }
  | { kind: 'guide'; guideId: string; title: string };

/** A `voice_command` block from the agent's answer (Contract 2), checked field by field. */
export type VoiceCommand = { command: 'end_call' } | { command: 'mute' } | { command: 'stop_speaking' } | { command: 'style'; style: AgentStylePatch };

/** A request longer than this (normalised) is never a panel command. */
const MAX_COMMAND_CHARS = 120;

/* ------------------------------------------------------------------------------------------------------------------ */
/* Normalising                                                                                                         */
/* ------------------------------------------------------------------------------------------------------------------ */

/** Simplified → traditional, only for the characters the phrase lists and manifests use. */
const S2T = new Map(
  (
    '见見 会會 线線 挂掛 断斷 头頭 这這 样樣 听聽 阵陣 迟遲 该該 谢謝 么麼 烦煩 请請 帮幫 吗嗎 啰囉 静靜 关關 闭閉 麦麥 风風 声聲 讲講 ' +
    '别別 说說 点點 简簡 长長 话話 详詳 细細 释釋 节節 转轉 换換 广廣 东東 粤粵 语語 国國 华華 设設 变變 个個 开開 启啟 带帶 进進 给給 ' +
    '显顯 页頁 览覽 总總 灵靈 动動 历曆 图圖 库庫 体體 频頻 队隊 数數 据據 员員 审審 计計 记記 录錄 忆憶 周週 顾顧 报報 资資 帐帳 账帳 ' +
    '单單 隐隱 联聯 络絡 范範 应應 连連 结結 户戶 号號 绑綁 写寫 预預 约約 时時 发發 布佈 间間 检檢 气氣 载載 网網 寻尋 额額 积積 划劃 ' +
    '传傳 电電 没沒'
  )
    .split(' ')
    .map((pair) => [pair.charAt(0), pair.charAt(1)] as const)
);

const HAN = /\p{Script=Han}/u;
const isHan = (ch: string) => ch !== '' && HAN.test(ch);

/** Lower case, half width, traditional characters, no punctuation or apostrophes, single spaces (none between CJK). */
export function normalizeRequest(text: string): string {
  let out = String(text ?? '').normalize('NFKC').toLowerCase();
  out = out.replace(/[\u0027\u2018\u2019\u02bc\u0060\u00b4]/g, '');
  out = Array.from(out, (ch) => S2T.get(ch) ?? ch).join('');
  out = out.replace(/&/g, ' and ').replace(/[^\p{L}\p{N}\s]+/gu, ' ').replace(/\s+/g, ' ').trim();
  return out.replace(/(\p{Script=Han})\s+(?=\p{Script=Han})/gu, '$1');
}

/** `phrase` begins `text` as whole words (a CJK phrase needs no space after it). */
function startsWithPhrase(text: string, phrase: string): boolean {
  if (!phrase || !text.startsWith(phrase)) return false;
  const next = text.charAt(phrase.length);
  return next === '' || next === ' ' || isHan(next) || isHan(phrase.charAt(phrase.length - 1));
}

function endsWithPhrase(text: string, phrase: string): boolean {
  if (!phrase || !text.endsWith(phrase)) return false;
  const before = text.charAt(text.length - phrase.length - 1);
  return before === '' || before === ' ' || isHan(before) || isHan(phrase.charAt(0));
}

function longestFirst(list: readonly string[]): string[] {
  return [...new Set(list.map(normalizeRequest).filter(Boolean))].toSorted((a, b) => b.length - a.length);
}

function stripEnds(text: string, lead: readonly string[], trail: readonly string[]): string {
  let out = text;
  for (let changed = true; changed && out; ) {
    changed = false;
    const head = lead.find((word) => startsWithPhrase(out, word));
    if (head) {
      out = out.slice(head.length).trim();
      changed = true;
    }
    const tail = trail.find((word) => endsWithPhrase(out, word));
    if (tail) {
      out = out.slice(0, out.length - tail.length).trim();
      changed = true;
    }
  }
  return out;
}

/** "drafts" → "draft" (Latin words of five letters or more; "access" and "news" stay as they are). */
function singular(text: string): string {
  return text
    .split(' ')
    .map((word) => (word.length >= 5 && /^[a-z]+s$/.test(word) && !word.endsWith('ss') ? word.slice(0, -1) : word))
    .join(' ');
}

/** The words after a cue that starts `text`, or null when no cue starts it. */
function afterCue(text: string, cues: readonly string[]): string | null {
  const cue = cues.find((item) => startsWithPhrase(text, item));
  return cue === undefined ? null : text.slice(cue.length).trim();
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Goodbye                                                                                                             */
/* ------------------------------------------------------------------------------------------------------------------ */

const FAREWELLS = [
  'bye', 'bye bye', 'byebye', 'bye now', 'goodbye', 'good bye', 'see you', 'see ya', 'see you later', 'see you soon', 'see you tomorrow',
  'talk to you later', 'talk to you soon', 'talk to you tomorrow', 'ill talk to you later', 'ill talk to you soon', 'talk later', 'talk soon',
  'catch you later', 'good night', 'goodnight', 'night night', 'take care', 'have a good day', 'have a nice day', 'have a good night',
  'have a good one', 'gotta go', 'got to go', 'i gotta go', 'i have to go', 'ive got to go', 'i need to go', 'i must go', 'i should go', 'im off',
  'thats all for now', 'thats all for today', 'thats it for now', 'thats it for today', 'hang up', 'hang up the call', 'end the call', 'end call',
  'end this call', 'end voice', 'end voice mode', 'stop the call', 'stop voice mode', 'close the call', 'finish the call',
  '拜拜', '拜', '再見', '再會', '我走先', '走先', '我走喇', '我要走喇', '我要走了', '收線', '收綫', '掛斷', '掛線', '掛斷電話', '掛電話', '掛咗佢',
  '我掛了', '掛了', '就咁先', '先咁', '先這樣', '下次再傾', '下次傾', '遲啲再傾', '遲啲傾', '遲點再傾', '遲點再聊', '遲點聊', '回頭聊', '回頭見',
  '下次聊', '下次再聊', '下次見', '遲啲見', '一陣見', '聽日見', '明天見', '晚安', '早唞'
];

/**
 * "That's all" ends the call only with a thank-you or a goodbye ("that's all, thanks"): alone it often answers a
 * question about the work ("anything else for the caption?").
 */
const DONE_WITH_THANKS = ['thats all', 'that is all', 'thats everything', '就係咁多', '冇嘢喇', '冇其他嘢喇', '就這些', '就這些了', '沒有了'];
const THANKS = [
  'thanks', 'thank you', 'thanks a lot', 'thank you so much', 'thanks so much', 'thank you very much', 'many thanks', 'cheers',
  '唔該', '唔該晒', '唔該你', '多謝', '多謝晒', '多謝你', '謝謝', '謝謝你'
];

/** Words that may surround a goodbye without changing it ("ok bye", "no, see you tomorrow", "得喇唔該晒拜拜"). */
const FAREWELL_EXTRAS = [
  'ok', 'okay', 'alright', 'all right', 'right', 'well', 'so', 'yeah', 'yes', 'yep', 'no', 'nope', 'nah', 'cool', 'great', 'perfect', 'good', 'nice',
  'lovely', 'awesome', 'then', 'now', 'for now', 'for today', 'for tonight', 'tonight', 'tomorrow', 'later', 'soon', 'again', 'thats it',
  'nothing else', 'im good', 'im done', 'all good', 'rafii', 'raffi', 'rafi', 'you can', 'can you', 'could you', 'please', 'just', 'hey', 'oh', 'um',
  'uh', 'hmm', 'and', 'everyone', 'mate', 'friend',
  '好', '好啦', '好喇', '好吖', '好的', '得', '得喇', '得啦', '冇喇', '唔使喇', '不用了', '嗯', '咁', '咁樣', '那', '那麼', '就', '先', '啦', '喇', '吖',
  '呀', '啊', '喔', '哦', '囉', '咯', '吧', '了', '噢', '喂'
];

type FarewellKind = 'bye' | 'done' | 'thanks' | 'extra';

const FAREWELL_TERMS: { text: string; kind: FarewellKind }[] = (() => {
  const terms = new Map<string, FarewellKind>();
  const add = (list: readonly string[], kind: FarewellKind) => {
    for (const text of longestFirst(list)) if (!terms.has(text)) terms.set(text, kind);
  };
  add(FAREWELLS, 'bye');
  add(DONE_WITH_THANKS, 'done');
  add(THANKS, 'thanks');
  add(FAREWELL_EXTRAS, 'extra');
  return [...terms.entries()].map(([text, kind]) => ({ text, kind })).toSorted((a, b) => b.text.length - a.text.length);
})();

/**
 * A normalised request made only of goodbyes and the words around them: at least one goodbye, or "that's all" with a
 * thank-you.
 */
function farewellIn(normalized: string): boolean {
  let rest = normalized;
  const seen = new Set<FarewellKind>();
  while (rest) {
    const term = FAREWELL_TERMS.find((item) => startsWithPhrase(rest, item.text));
    if (!term) return false;
    seen.add(term.kind);
    rest = rest.slice(term.text.length).trim();
  }
  return seen.has('bye') || (seen.has('done') && seen.has('thanks'));
}

/** The whole request is a goodbye (or an explicit "hang up"), in English, Cantonese or Mandarin. */
export function isFarewell(text: string): boolean {
  const normalized = normalizeRequest(text);
  return normalized.length > 0 && normalized.length <= MAX_COMMAND_CHARS && farewellIn(normalized);
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Mute, stop, style                                                                                                   */
/* ------------------------------------------------------------------------------------------------------------------ */

/** Politeness around a command ("could you …", "… please", "唔該 …啦"), removed before matching. */
const POLITE_LEAD = longestFirst([
  'hey', 'hi', 'hello', 'ok', 'okay', 'alright', 'all right', 'right', 'so', 'well', 'oh', 'um', 'uh', 'er', 'hmm', 'please', 'can you', 'could you',
  'would you', 'will you', 'can we', 'could we', 'can i', 'could i', 'i want to', 'i wanna', 'i would like to', 'id like to', 'i want you to',
  'i need you to', 'lets', 'let us', 'just', 'now', 'go ahead and', 'rafii', 'raffi', 'rafi',
  '好', '好啦', '好喇', '得', '得喇', '得啦', '喂', '嗯', '咁', '那', '那麼', '就', '唔該', '唔該你', '唔該晒', '麻煩你', '麻煩', '請', '請你', '你',
  '幫我', '同我', '可唔可以', '可以', '可不可以', '能不能', '你可以', '我想', '我要', '我想你', '不如'
]);
const POLITE_TRAIL = longestFirst([
  'please', 'thanks', 'thank you', 'now', 'right now', 'for me', 'rafii', 'raffi', 'rafi', 'from now on', 'again',
  '啦', '喇', '吖', '呀', '啊', '喔', '哦', '囉', '咯', '吧', '了', '先', '唔該', '唔該晒', '謝謝', '多謝', '好嗎', '好唔好', '得唔得', '得嗎', '呢',
  '嘞', '喎', '嗎', '㗎', '一下', '先得', '先可以'
]);

const coreOf = (normalized: string) => stripEnds(normalized, POLITE_LEAD, POLITE_TRAIL);
const phraseSet = (list: readonly string[]) => new Set(list.map((phrase) => coreOf(normalizeRequest(phrase))).filter(Boolean));

const MUTE = phraseSet([
  'mute', 'mute me', 'mute my mic', 'mute my microphone', 'mute the mic', 'mute the microphone', 'mute mic', 'mute microphone', 'mute myself',
  'turn off my mic', 'turn off my microphone', 'turn off the mic', 'turn off the microphone', 'turn my mic off', 'turn the mic off',
  'turn my microphone off', 'switch off my mic', 'switch my mic off', 'mic off', 'microphone off', 'stop listening', 'stop listening to me',
  '靜音', '閂咪', '閂埋個咪', '閂咗個咪', '閂麥', '閂麥克風', '熄咪', '熄埋個咪', '關咪', '關麥', '關閉咪', '關閉麥克風', '關掉麥克風', '關掉咪',
  '唔好聽住', '停止收音', '別聽了', '不要聽了'
]);

const STOP_TALKING = phraseSet([
  'stop talking', 'stop speaking', 'stop talking now', 'be quiet', 'quiet', 'quiet down', 'shh', 'shhh', 'shush', 'hush', 'silence',
  'enough talking', 'you can stop talking', 'stop reading', 'stop reading it out', 'stop reading that', 'no more talking', 'stop the talking',
  'stop your talking', 'dont talk',
  '收聲', '唔好講', '唔好再講', '停止講嘢', '唔好講嘢', '咪講住', '咪講', '靜啲', '靜一靜', '安靜', '安靜啲', '安靜一點', '別說了', '別講了',
  '不要說了', '不要講了', '別說話', '不要說話', '停止說話', '停一停'
]);

const OPEN_STYLE = phraseSet([
  'open style settings', 'open the style settings', 'open your style settings', 'style settings', 'open the style picker', 'style picker',
  'open tone settings', 'tone settings', 'open tone and delivery', 'open tone and delivery settings', 'tone and delivery',
  'tone and delivery settings', 'change your voice', 'switch your voice', 'change your tone', 'change your style', 'change how you talk',
  'change how you speak', 'change the way you talk', 'change the way you speak', 'change your speaking style', 'change how rafii talks',
  'change how rafii speaks',
  '改你嘅語氣', '改聲', '轉聲', '換聲', '換把聲', '轉把聲', '改把聲', '換個聲音', '換聲音', '轉聲音', '改聲音', '換一個聲音', '換個聲', '語氣設定',
  '聲音設定', '打開語氣設定', '打開聲音設定', '改說話方式', '改變說話方式'
]);

interface StyleIntent {
  patch: AgentStylePatch;
  confirm: string;
  phrases: string[];
}

const LANGUAGE_WORDS: { language: 'en' | 'yue' | 'cmn'; label: string; words: string[]; zh: string[] }[] = [
  { language: 'en', label: 'English', words: ['english'], zh: ['英文', '英語'] },
  { language: 'yue', label: 'Cantonese', words: ['cantonese'], zh: ['廣東話', '粵語', '廣府話'] },
  { language: 'cmn', label: 'Mandarin', words: ['mandarin', 'putonghua'], zh: ['普通話', '國語', '華語'] }
];
const LANGUAGE_CUES = [
  'switch to', 'switch to speaking', 'switch back to', 'go back to', 'speak', 'speak in', 'talk in', 'talk to me in', 'answer in',
  'answer me in', 'change to', 'change the language to', 'switch the language to', 'lets speak', 'lets talk in', 'can we speak', 'can we talk in'
];
const LANGUAGE_CUES_ZH = ['講', '說', '同我講', '同我說', '轉', '轉做', '轉返', '轉用', '改用', '改講', '轉講', '講返', '說回', '換成', '切換到', '切換成'];
const LANGUAGE_AFTER_ZH = ['講', '說', '答', '回答', '同我講', '同我說'];

const STYLE_INTENTS: StyleIntent[] = [
  {
    patch: { pace: 'slower' },
    confirm: 'Okay, I’ll speak a little slower.',
    phrases: [
      'slower', 'slow down', 'slow down a bit', 'slow down a little', 'speak slower', 'talk slower', 'speak slowly', 'talk slowly', 'speak more slowly',
      'talk more slowly', 'speak a bit slower', 'speak a little slower', 'talk a bit slower', 'talk a little slower', 'a bit slower', 'a little slower',
      'not so fast', 'youre talking too fast', 'youre speaking too fast', 'you talk too fast', 'you speak too fast', 'you are talking too fast',
      'you are speaking too fast',
      '慢啲', '慢少少', '慢一點', '慢點', '講慢啲', '講慢少少', '講慢一點', '講慢點', '講得慢啲', '說慢一點', '說慢點', '說慢些', '說得慢一點', '放慢啲',
      '放慢少少', '慢慢講', '你講太快', '你講得太快', '講太快', '你說太快', '你說得太快', '說太快', '語速慢啲', '語速慢一點', '慢一點說', '慢點說'
    ]
  },
  {
    patch: { pace: 'faster' },
    confirm: 'Okay, I’ll speak a little faster.',
    phrases: [
      'speak faster', 'talk faster', 'speak quicker', 'talk quicker', 'speak more quickly', 'talk more quickly', 'speak a bit faster',
      'speak a little faster', 'talk a bit faster', 'talk a little faster', 'a bit faster', 'a little faster', 'youre talking too slowly',
      'youre talking too slow', 'youre speaking too slowly', 'you talk too slow', 'you talk too slowly', 'you speak too slowly', 'you speak too slow',
      '講快啲', '講快少少', '講快一點', '講快點', '講得快啲', '說快一點', '說快點', '說快些', '說得快一點', '你講太慢', '你講得太慢', '講太慢', '你說太慢',
      '你說得太慢', '說太慢', '語速快啲', '語速快一點', '快一點說', '快點說'
    ]
  },
  {
    patch: { detail: 'concise' },
    confirm: 'Okay, I’ll keep my answers short.',
    phrases: [
      'shorter answers', 'short answers', 'shorter replies', 'short replies', 'give me shorter answers', 'give me short answers',
      'keep your answers short', 'keep your answers shorter', 'keep answers short', 'keep your replies short', 'answer shorter',
      'answer more briefly', 'answer briefly', 'be brief', 'be more brief', 'be briefer', 'be concise', 'be more concise', 'talk less',
      'dont talk so much', 'less talking', 'answer in one sentence', 'one sentence answers', 'get to the point', 'straight to the point',
      '講短啲', '講短少少', '講簡短啲', '簡短啲講', '簡短啲答', '答短啲', '答簡短啲', '回答短一點', '回答簡短一點', '說短一點', '說短點', '簡短一點說',
      '簡單啲講', '講重點', '說重點', '直接講重點', '長話短說', '少講啲', '講少啲', '唔好講咁長', '不要說那麼長', '別說那麼多'
    ]
  },
  {
    patch: { detail: 'detailed' },
    confirm: 'Okay, I’ll give you more detail.',
    phrases: [
      'more detailed answers', 'longer answers', 'give me longer answers', 'give me more detailed answers', 'answer in more detail',
      'answer in detail', 'be more detailed', 'explain things in more detail',
      '講詳細啲', '講詳細少少', '講詳細一點', '答詳細啲', '回答詳細一點', '說詳細一點', '說詳細點', '解釋詳細啲', '詳細啲解釋', '詳細啲講', '詳細一點說',
      '講多啲細節'
    ]
  },
  ...LANGUAGE_WORDS.map(({ language, label, words, zh }) => ({
    patch: { language },
    confirm: `Okay, I’ll answer in ${label} from now on.`,
    phrases: [
      ...LANGUAGE_CUES.flatMap((cue) => words.map((word) => `${cue} ${word}`)),
      ...LANGUAGE_CUES_ZH.flatMap((cue) => zh.map((name) => cue + name)),
      ...LANGUAGE_AFTER_ZH.flatMap((after) => zh.map((name) => '用' + name + after))
    ]
  }))
];

const STYLE_INDEX: Map<string, StyleIntent> = (() => {
  const index = new Map<string, StyleIntent>();
  for (const intent of STYLE_INTENTS) for (const phrase of phraseSet(intent.phrases)) if (!index.has(phrase)) index.set(phrase, intent);
  return index;
})();

/** The fixed sentence GPT-Live is given for each style value (never the person's words). */
const STYLE_LINES = {
  tone: {
    friendly: 'From now on, sound warm and friendly.',
    professional: 'From now on, sound calm and professional.',
    playful: 'From now on, sound light and playful.',
    direct: 'From now on, be plain and direct.'
  },
  detail: {
    concise: 'From now on, keep answers to one short sentence.',
    balanced: 'From now on, keep answers to one to three sentences.',
    detailed: 'From now on, give more detail and explain the steps.'
  },
  pace: { slower: 'From now on, speak a little slower.', normal: 'From now on, speak at a normal pace.', faster: 'From now on, speak a little faster.' },
  language: {
    auto: 'From now on, answer in the language the user is speaking.',
    en: 'From now on, answer in English.',
    yue: 'From now on, answer in Cantonese.',
    cmn: 'From now on, answer in Mandarin.'
  },
  initiative: { ask: 'From now on, suggest next steps only when the user asks.', suggest: 'From now on, suggest one helpful next step when it fits.' }
} as const;

const STYLE_FIELDS = { tone: TONES, detail: DETAILS, pace: PACES, voice: VOICES, language: LANGUAGES, initiative: INITIATIVE } as const;

/** Only known style fields with allowed values survive; null when nothing does. */
export function sanitizeStylePatch(raw: unknown): AgentStylePatch | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, allowed] of Object.entries(STYLE_FIELDS)) {
    const value = source[key];
    if (typeof value === 'string' && (allowed as readonly string[]).includes(value)) out[key] = value;
  }
  if (typeof source.preset === 'string' && Object.prototype.hasOwnProperty.call(PRESETS, source.preset)) out.preset = source.preset;
  if (source.chosen === true) out.chosen = true;
  return Object.keys(out).length ? (out as AgentStylePatch) : null;
}

/**
 * The instruction lines for a style change, one fixed sentence per changed field (a preset expands to its fields).
 * The voice itself can't change mid-call, so it has no line.
 */
export function styleInstructions(patch: AgentStylePatch): string[] {
  const clean = sanitizeStylePatch(patch);
  if (!clean) return [];
  const merged: Partial<Record<'tone' | 'detail' | 'pace' | 'language' | 'initiative', string>> = { ...(clean.preset ? PRESETS[clean.preset].style : {}) };
  for (const field of ['tone', 'detail', 'pace', 'language', 'initiative'] as const) if (clean[field]) merged[field] = clean[field];
  const lines: string[] = [];
  for (const field of ['tone', 'detail', 'pace', 'language', 'initiative'] as const) {
    const value = merged[field];
    const line = value ? (STYLE_LINES[field] as Record<string, string>)[value] : undefined;
    if (line) lines.push(line);
  }
  return lines;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Pages and guides                                                                                                    */
/* ------------------------------------------------------------------------------------------------------------------ */

/** Everyday names for pages, beside their manifest titles ("open my plan", "打開日曆"). */
const ROUTE_ALIASES: Record<string, string[]> = {
  home: ['home page', 'homepage', '主頁', '首頁'],
  overview: ['概覽', '總覽'],
  ideas: ['靈感', '點子'],
  automations: ['自動化'],
  calendar: ['日曆', '月曆', '行事曆'],
  library: ['media library', '圖庫', '媒體庫'],
  channels: ['頻道', '渠道'],
  queue: ['approvals', '隊列', '審批'],
  analytics: ['stats', 'statistics', '數據', '數據分析'],
  inbox: ['comments', '收件箱'],
  members: ['team', '成員'],
  brand: ['品牌'],
  memory: ['記憶'],
  weekly: ['每週回顧', '週報'],
  personalization: ['個人化'],
  profile: ['個人資料'],
  notifications: ['通知'],
  billing: ['usage', 'plan', 'credits', '用量', '計劃', '帳單', '額度'],
  privacy: ['私隱', '隱私'],
  models: ['模型'],
  help: ['help center', 'help centre', '幫助', '說明'],
  contact: ['support', '聯絡支援', '客服']
};
/** A named view of a page (the Queue's Drafts tab). */
const VIEW_ALIASES: { routeId: string; href: string; title: string; names: string[] }[] = [
  { routeId: 'queue', href: '/app/queue?view=drafts', title: 'Drafts', names: ['drafts', '草稿'] }
];

const NAV_CUES = longestFirst([
  'open up', 'open', 'go to', 'go back to', 'take me to', 'take me back to', 'take me', 'bring me to', 'bring up', 'show me', 'show', 'navigate to',
  'jump to', 'switch to', 'head to', 'head over to', 'go over to', 'pull up', 'let me see', 'i want to see', 'get me to',
  '打開', '開', '開啟', '去', '去到', '帶我去', '帶我入', '帶我返', '轉去', '轉到', '返去', '返', '跳去', '跳到', '入去', '進入', '睇下', '睇吓', '睇',
  '俾我睇', '給我看', '看看', '看一下', '顯示', '切換到', '前往'
]);
const NAV_LEAD = longestFirst(['the', 'my', 'our', 'a', 'to', 'into', '我嘅', '我的', '個', '嗰個', '那個', '這個', '一下']);
const NAV_TRAIL = longestFirst(['page', 'pages', 'tab', 'screen', 'section', 'view', 'area', '頁', '頁面', '版面', '嗰頁', '嗰度', '一下', '吓']);

const GUIDE_CUES = longestFirst([
  'show me how to', 'show me how i can', 'show me how i', 'show me how we', 'show me how', 'teach me how to', 'teach me how', 'teach me to',
  'teach me', 'walk me through how to', 'walk me through', 'guide me through how to', 'guide me through', 'guide me', 'help me learn how to',
  'how do i', 'how can i', 'how would i', 'how should i', 'how to', 'how do you', 'how do we', 'how can we', 'i want to learn how to',
  'i dont know how to',
  '教我點樣', '教下我點樣', '教吓我點樣', '教我點', '教我', '教下我', '教吓我', '示範點樣', '示範下點樣', '示範下', '示範', '點樣', '點先可以', '我點樣',
  '我應該點樣', '應該點樣', '要點樣', '怎麼', '怎樣', '如何', '要怎麼', '教我怎麼', '教我如何', '我要怎麼', '我該怎麼', '該怎麼'
]);
/** Words a guide topic may carry beside its keywords ("how do I connect MY account", "點樣設定一個自動化"). */
const GUIDE_FILLERS = [
  'a', 'an', 'the', 'my', 'our', 'new', 'first', 'another', 'to', 'on', 'onto', 'in', 'into', 'for', 'with', 'from', 'of', 'up', 'set up',
  'setup', 'set', 'use', 'using', 'do', 'i', 'we', 'can', 'it', 'some', 'add', 'make', 'get', 'turn on', 'switch on', 'enable', 'start', 'create',
  'pick', 'choose', 'check', 'see', 'find', 'open', 'go', 'and', 'or', 'here', 'there', 'where', 'at', 'is', 'are', 'change', 'edit', 'manage',
  'more', 'one', 'rafii', 'raffi', 'rafi',
  '一個', '個', '我', '我嘅', '我的', '嘅', '的', '啲', '一下', '下', '吓', '做', '整', '設定', '設置', '開', '開啟', '打開', '加', '新增', '新', '用',
  '使用', '喺', '在', '上', '入', '到', '同', '和', '及', '先', '可以', '要', '去', '揀', '選', '選擇', '改', '買', '查', '睇', '搵', '找'
];
/**
 * Guide keywords that name something the person usually wants answered rather than taught ("how do I check the
 * weather"): those requests go to the agent, which can look it up or offer the guide when search is off.
 */
const CONTENT_WORDS = new Set(['weather', 'news', 'google', '天氣']);

interface RouteTarget {
  href: string;
  routeId: string;
  title: string;
}

interface CatalogIndex {
  routes: Map<string, RouteTarget>;
  /** Guide keywords and topic fillers, longest first; a filler has no guides. */
  guideTerms: { text: string; guides: string[] }[];
  guideTitles: Map<string, string>;
}

const indexes = new WeakMap<PanelCatalog, CatalogIndex>();

function indexOf(catalog: PanelCatalog): CatalogIndex {
  const cached = indexes.get(catalog);
  if (cached) return cached;
  const routes = new Map<string, RouteTarget>();
  const add = (name: string, target: RouteTarget) => {
    const key = singular(normalizeRequest(name));
    if (key && !routes.has(key)) routes.set(key, target);
  };
  for (const route of catalog.routes) {
    // Only pages that open without an id (a conversation or a help article needs one).
    if (route.navigable === false || route.pattern.includes('[')) continue;
    const target = { href: route.pattern, routeId: route.id, title: route.title };
    for (const name of [route.title, route.id.replace(/_/g, ' '), ...(ROUTE_ALIASES[route.id] ?? [])]) add(name, target);
  }
  for (const view of VIEW_ALIASES) {
    if (!catalog.routes.some((route) => route.id === view.routeId)) continue;
    for (const name of view.names) add(name, { href: view.href, routeId: view.routeId, title: view.title });
  }
  const terms = new Map<string, Set<string>>();
  for (const guide of catalog.guides) {
    for (const keyword of guide.keywords) {
      const text = singular(normalizeRequest(keyword));
      if (!text || CONTENT_WORDS.has(text)) continue;
      terms.set(text, (terms.get(text) ?? new Set()).add(guide.id));
    }
  }
  for (const filler of GUIDE_FILLERS) {
    const text = singular(normalizeRequest(filler));
    if (text && !terms.has(text)) terms.set(text, new Set());
  }
  const guideTerms = [...terms.entries()].map(([text, guides]) => ({ text, guides: [...guides] })).toSorted((a, b) => b.text.length - a.text.length);
  const index = { routes, guideTerms, guideTitles: new Map(catalog.guides.map((guide) => [guide.id, guide.title])) };
  indexes.set(catalog, index);
  return index;
}

/** "show me how to connect Instagram" → connect_account: the topic must be nothing but one guide's keywords and fillers. */
function matchGuide(core: string, index: CatalogIndex): PanelCommand | null {
  const topic = afterCue(core, GUIDE_CUES);
  if (!topic) return null;
  let rest = singular(topic);
  const hits = new Map<string, { count: number; longest: number }>();
  while (rest) {
    const term = index.guideTerms.find((item) => startsWithPhrase(rest, item.text));
    if (!term) return null;
    for (const guide of term.guides) {
      const hit = hits.get(guide) ?? { count: 0, longest: 0 };
      hits.set(guide, { count: hit.count + 1, longest: Math.max(hit.longest, term.text.length) });
    }
    rest = rest.slice(term.text.length).trim();
  }
  const ranked = [...hits.entries()].toSorted(([, a], [, b]) => b.count - a.count || b.longest - a.longest);
  const [best, second] = ranked;
  if (!best) return null;
  // Two guides fit equally well: the agent decides.
  if (second && second[1].count === best[1].count && second[1].longest === best[1].longest) return null;
  return { kind: 'guide', guideId: best[0], title: index.guideTitles.get(best[0]) ?? best[0] };
}

/** "take me to Channels", "open my plan", "打開日曆": the topic must be exactly one page's name. */
function matchNavigation(core: string, index: CatalogIndex): PanelCommand | null {
  const rest = afterCue(core, NAV_CUES);
  if (!rest) return null;
  const topic = singular(stripEnds(rest, NAV_LEAD, NAV_TRAIL));
  const target = topic ? index.routes.get(topic) : undefined;
  return target ? { kind: 'navigate', ...target } : null;
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Public API                                                                                                          */
/* ------------------------------------------------------------------------------------------------------------------ */

/** The panel command a whole spoken request asks for, or null (the agent takes it). */
export function matchPanelCommand(text: string, catalog: PanelCatalog = DEFAULT_CATALOG): PanelCommand | null {
  const normalized = normalizeRequest(text);
  if (!normalized || normalized.length > MAX_COMMAND_CHARS) return null;
  if (farewellIn(normalized)) return { kind: 'end_call' };
  const core = coreOf(normalized);
  if (!core) return null;
  if (MUTE.has(core)) return { kind: 'mute' };
  if (STOP_TALKING.has(core)) return { kind: 'stop_speaking' };
  const style = STYLE_INDEX.get(core);
  if (style) return { kind: 'style', patch: { ...style.patch }, confirm: style.confirm };
  if (OPEN_STYLE.has(core)) return { kind: 'open_style' };
  const index = indexOf(catalog);
  return matchGuide(core, index) ?? matchNavigation(core, index);
}

/** The one sentence Rafii says once a panel command is done; null when saying nothing is the point ("stop talking"). */
export function confirmation(command: PanelCommand): string | null {
  switch (command.kind) {
    case 'end_call':
      return 'Bye for now; I’m ending the call.';
    case 'mute':
      return 'Your microphone is off now; tap Unmute when you want to talk again.';
    case 'stop_speaking':
      return null;
    case 'style':
      return command.confirm;
    case 'open_style':
      return 'I’ve opened the settings for how I talk.';
    case 'navigate':
      return `Opening ${command.title} now.`;
    case 'guide':
      return `Starting the “${command.title}” guide; follow the pointer on screen.`;
  }
}

function field(value: unknown, key: string): unknown {
  return value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined;
}

/**
 * The `voice_command` blocks in an agent answer (`result.blocks`, or the site agent's message blocks), each command
 * once, in the order they are carried out: style, mute, stop talking, end the call.
 */
export function voiceCommandsIn(response: unknown): VoiceCommand[] {
  const lists = [field(field(response, 'result'), 'blocks'), field(field(field(field(response, 'siteAgent'), 'message'), 'siteAgent'), 'blocks')];
  const seen = new Set<'mute' | 'stop_speaking' | 'end_call'>();
  const styles: AgentStylePatch[] = [];
  for (const list of lists) {
    if (!Array.isArray(list)) continue;
    for (const block of list) {
      if (field(block, 'type') !== 'voice_command') continue;
      const command = field(block, 'command');
      if (command === 'style') {
        const patch = sanitizeStylePatch(field(block, 'style'));
        if (patch) styles.push(patch);
      } else if (command === 'mute' || command === 'stop_speaking' || command === 'end_call') {
        seen.add(command);
      }
    }
  }
  const out: VoiceCommand[] = styles.length ? [{ command: 'style', style: styles.reduce<AgentStylePatch>((all, patch) => ({ ...all, ...patch }), {}) }] : [];
  for (const command of ['mute', 'stop_speaking', 'end_call'] as const) if (seen.has(command)) out.push({ command });
  return out;
}
