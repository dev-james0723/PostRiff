/**
 * Rafii's slash commands (docs/design/rafii-live-agent/CONTRACTS.md, Contract 7). `@` adds context; `/` asks Rafii to
 * do one thing.
 *
 * - An agent command goes to Rafii: the typed text as the message plus `command: {name, args}` (`commandPayload`).
 *   The server maps the name to a fixed instruction; permissions, consent and credits still apply.
 * - A client command runs here through the panel actions and never reaches the server. It reports success only after
 *   calling a handler that exists; with no handler registered on this screen it says it can't do that here.
 *
 * Pure apart from `panelActions()`, so `web/tests/rafii-commands.test.cjs` loads it with `ts.transpileModule`.
 */
import guideManifestJson from '@/lib/site-agent/guide-manifest.json';
import routeManifestJson from '@/lib/site-agent/route-manifest.json';
import type { ManifestRoute, RouteManifest } from '@/lib/site-agent/routes';
import { panelActions, type PanelActions } from './panel-actions';
import { PRESETS, type PresetId } from './style';

export type CommandGroup = 'write' | 'look_up' | 'images' | 'plan' | 'rafii';

/** The menu's headings, in the order the menu shows them. */
export const COMMAND_GROUPS: readonly { id: CommandGroup; label: string }[] = [
  { id: 'write', label: 'Write' },
  { id: 'look_up', label: 'Look up' },
  { id: 'images', label: 'Images' },
  { id: 'plan', label: 'Plan' },
  { id: 'rafii', label: 'Rafii' }
];

/** What a command takes after its name: nothing, words it can do without, or words it needs. */
export type CommandTakes = 'none' | 'optional' | 'required';

export interface CommandContext {
  /** The panel abilities to use; the registered ones by default. */
  actions?: Readonly<PanelActions>;
}

export interface SlashCommand {
  /** English, lower case: `/name`. */
  name: string;
  /** Other words for the same command, lower case, including Chinese (`/寫`, `/天氣`). Unique across commands. */
  aliases: string[];
  group: CommandGroup;
  /** One sentence for the menu. */
  description: string;
  /** What to type after the name, shown muted in the menu; '' when the command takes nothing. */
  argsHint: string;
  takes: CommandTakes;
  kind: 'client' | 'agent';
  /** Client commands only: runs in the browser through the panel actions; resolves to a short confirmation or null. */
  execute?: (args: string, ctx?: CommandContext) => Promise<string | null> | string | null;
}

export interface GuideEntry {
  id: string;
  routeId: string;
  title: string;
  summary: string;
  keywords: string[];
}

export const COMMANDS: SlashCommand[] = [
  // Write
  { name: 'write', aliases: ['draft', '寫', '寫post', '出post', '写', '写post'], group: 'write', kind: 'agent', takes: 'required', argsHint: 'your idea', description: 'Draft a post for the accounts you chose.' },
  { name: 'rewrite', aliases: ['edit', '改寫', '改', '改写'], group: 'write', kind: 'agent', takes: 'required', argsHint: 'how to change it', description: 'Rewrite the latest draft in this conversation.' },
  { name: 'translate', aliases: ['翻譯', '翻译'], group: 'write', kind: 'agent', takes: 'required', argsHint: 'language', description: 'Translate the latest draft into another language.' },
  { name: 'hashtags', aliases: ['hashtag', 'tags', '標籤', '标签'], group: 'write', kind: 'agent', takes: 'optional', argsHint: 'topic (optional)', description: 'Suggest hashtags for the latest draft.' },
  { name: 'caption', aliases: ['文案', '配文'], group: 'write', kind: 'agent', takes: 'optional', argsHint: 'notes (optional)', description: 'Write a caption for the attached or latest image.' },
  { name: 'repurpose', aliases: ['adapt', 'crosspost', '轉平台', '转平台'], group: 'write', kind: 'agent', takes: 'required', argsHint: 'platforms', description: 'Adapt the latest draft for other platforms.' },
  { name: 'ideas', aliases: ['brainstorm', '靈感', '諗主意', '灵感', '點子', '点子'], group: 'write', kind: 'agent', takes: 'required', argsHint: 'topic', description: "Suggest post ideas on a topic, using web search when it's allowed." },
  // Look up
  { name: 'search', aliases: ['research', 'web', 'lookup', '搜尋', '上網', '搜', '搜索', '上网'], group: 'look_up', kind: 'agent', takes: 'required', argsHint: 'question', description: 'Search the web and answer with sources and dates; if web search is off, the owner can turn it on under Memory.' },
  { name: 'weather', aliases: ['forecast', '天氣', '天气'], group: 'look_up', kind: 'agent', takes: 'required', argsHint: 'place', description: "Get the current weather and today's forecast for a place." },
  { name: 'stats', aliases: ['analytics', 'performance', '數據', '表現', '数据', '表现'], group: 'look_up', kind: 'agent', takes: 'none', argsHint: '', description: 'See how your recent posts performed.' },
  { name: 'review', aliases: ['todo', 'attention', '待辦', '要處理', '待办', '要处理'], group: 'look_up', kind: 'agent', takes: 'none', argsHint: '', description: 'See what needs your attention, such as posts waiting for approval.' },
  // Images
  { name: 'image', aliases: ['picture', 'photo', '整圖', '圖片', '生成圖片', '图片', '生成图片', '畫圖', '画图'], group: 'images', kind: 'agent', takes: 'required', argsHint: 'description', description: 'Create an image from a description within the approved task allowance.' },
  // Plan
  { name: 'schedule', aliases: ['排程', '預約', '预约', '定時', '定时'], group: 'plan', kind: 'agent', takes: 'required', argsHint: 'when', description: 'Prepare a posting plan for you to approve; nothing is published.' },
  { name: 'automation', aliases: ['auto', 'recurring', '自動化', '自動', '自动化', '自动', '定期'], group: 'plan', kind: 'agent', takes: 'required', argsHint: 'what should happen', description: 'Set up an automation from a description.' },
  // Rafii
  { name: 'skills', aliases: ['skill', '技能'], group: 'rafii', kind: 'agent', takes: 'none', argsHint: '', description: 'List the writing skills Rafii can use.' },
  { name: 'guide', aliases: ['teach', 'howto', 'tour', 'learn', '教我', '教學', '點樣', '教学', '怎麼', '怎么', '如何'], group: 'rafii', kind: 'client', takes: 'required', argsHint: 'topic', description: 'Walk through a task step by step, right on the page.', execute: runGuide },
  { name: 'open', aliases: ['go', 'goto', '打開', '開', '去', '打开', '开', '前往'], group: 'rafii', kind: 'client', takes: 'required', argsHint: 'page', description: 'Go to a page in Rafii.', execute: openPage },
  { name: 'style', aliases: ['tone', '語氣', '風格', '语气', '风格'], group: 'rafii', kind: 'client', takes: 'optional', argsHint: 'friendly, concise or explainer', description: 'Change how Rafii talks to you.', execute: changeStyle },
  { name: 'voice', aliases: ['call', 'talk', '語音', '講嘢', '语音'], group: 'rafii', kind: 'client', takes: 'none', argsHint: '', description: 'Talk to Rafii by voice.', execute: startVoice },
  { name: 'new', aliases: ['clear', 'reset', '新對話', '新对话', '重新開始', '重新开始'], group: 'rafii', kind: 'client', takes: 'none', argsHint: '', description: 'Start a new conversation.', execute: newConversation },
  // Null: nothing to say, the menu itself is the answer (the menu picks it as a bare `/`, which lists every command).
  { name: 'help', aliases: ['commands', '?', '幫助', '指令', '帮助'], group: 'rafii', kind: 'client', takes: 'none', argsHint: '', description: 'Show every command.', execute: () => null }
];

/** How a typed command word compares: full-width forms folded (`／` → `/`, `ｗ` → `w`) and lower case. */
export function commandKey(text: string): string {
  return text.normalize('NFKC').toLowerCase().trim();
}

const HAN = /\p{Script=Han}/u;
const KEYS = new Map<string, SlashCommand>();
for (const command of COMMANDS) for (const key of [command.name, ...command.aliases]) KEYS.set(commandKey(key), command);

/**
 * `/name args` at the start of a message (`／` counts as `/`; the name or any alias, in any case) → the command and its
 * trimmed arguments, or null for plain text. Chinese is typed without spaces, so `/天氣香港` and `/weather香港` are
 * `/weather 香港`; `/writehello` stays plain text.
 */
export function parseSlash(text: string): { command: SlashCommand; args: string } | null {
  const match = /^[/／](\S+)([\s\S]*)$/.exec(text.trim());
  if (!match) return null;
  const [, word, rest] = match;
  for (let end = word.length; end > 0; end--) {
    const head = commandKey(word.slice(0, end));
    const command = KEYS.get(head);
    if (!command) continue;
    if (end === word.length) return { command, args: rest.trim() };
    if (HAN.test(head.slice(-1)) || HAN.test(word.charAt(end))) return { command, args: (word.slice(end) + rest).trim() };
  }
  return null;
}

/** The `command` part of an `agent/turns` payload: the allowlisted name and at most 1,000 characters of plain text. */
export function commandPayload(parsed: { command: SlashCommand; args: string }): { name: string; args: string } {
  return { name: parsed.command.name, args: Array.from(parsed.args).slice(0, 1000).join('') };
}

// ---- Matching words to pages, guides and styles ------------------------------------------------------------------

const ROUTES = (routeManifestJson as RouteManifest).routes;
/** Pages `/open` may go to: navigable manifest routes whose path needs no id. */
export const OPENABLE_PAGES: ManifestRoute[] = ROUTES.filter((route) => route.navigable !== false && !route.pattern.includes('['));
export const GUIDES: GuideEntry[] = (guideManifestJson as { guides: GuideEntry[] }).guides;

/** Words people use for each page beyond its title, in English and Chinese. */
export const PAGE_WORDS: Record<string, string[]> = {
  home: ['home', 'start', 'write', 'new post', '主頁', '首頁', '主页', '首页'],
  overview: ['overview', 'dashboard', '概覽', '總覽', '概览', '总览'],
  ideas: ['ideas', 'sources', '靈感', '來源', '灵感', '来源', '素材'],
  automations: ['automations', 'recurring', '自動化', '自动化'],
  calendar: ['calendar', 'schedule', '日曆', '月曆', '行事曆', '日历', '月历', '排程'],
  library: ['library', 'media', 'images', 'photos', '圖庫', '媒體庫', '相簿', '图库', '媒体库'],
  channels: ['channels', 'accounts', 'connections', 'social accounts', '頻道', '渠道', '帳戶', '帳號', '频道', '账户', '账号'],
  queue: ['queue', 'approvals', 'drafts', 'scheduled posts', '隊列', '待發', '審批', '草稿', '队列', '审批'],
  analytics: ['analytics', 'stats', 'performance', 'insights', '數據', '分析', '表現', '数据', '表现'],
  inbox: ['inbox', 'comments', 'replies', '收件箱', '留言', '評論', '回覆', '评论', '回复'],
  members: ['members', 'team', 'invite', 'people', '成員', '團隊', '成员', '团队'],
  roles: ['roles', 'permissions', '角色', '權限', '权限'],
  audit: ['audit log', 'activity log', 'log', '審計', '紀錄', '审计', '记录'],
  brand: ['brand', 'brand voice', 'writing voice', '品牌'],
  memory: ['memory', 'brand brain', 'web search', '記憶', '记忆'],
  weekly: ['weekly', 'weekly review', 'this week', '每週', '週報', '每周', '周报'],
  personalization: ['personalization', 'personalisation', 'preferences', '個人化', '偏好', '个性化'],
  profile: ['profile', 'settings', 'account settings', 'my account', 'security', 'password', 'two step', '2fa', '個人資料', '帳戶設定', '个人资料', '账户设置'],
  notifications: ['notifications', 'emails', 'alerts', '通知', '提醒'],
  billing: ['billing', 'plan', 'usage', 'credits', 'media credits', 'subscription', 'top up', '用量', '計劃', '方案', '額度', '積分', '訂閱', '增值', '计划', '额度', '积分', '订阅'],
  privacy: ['privacy', 'data', 'export', 'delete account', '私隱', '隱私', '隐私', '匯出', '导出'],
  models: ['models', 'writer', 'writers', 'ai', 'ai model', '模型', '寫手', '写手'],
  api: ['api', 'integrations', 'tokens', 'api tokens', '整合', '集成'],
  help: ['help', 'help articles', 'articles', 'faq', '幫助', '說明', '帮助', '说明'],
  contact: ['contact', 'support', 'contact support', '聯絡', '客服', '支援', '联系', '支持']
};

/** More words for each guide than the manifest's keywords: simplified Chinese and other platforms. Ids stay the manifest's. */
export const GUIDE_WORDS: Record<string, string[]> = {
  connect_account: ['ig', 'facebook', 'tiktok', 'youtube', 'pinterest', '连接', '连结', '频道', '账户', '账号', '绑定', '设定频道'],
  write_first_post: ['写', '写post', '發帖', '发帖'],
  schedule_draft: ['预约', '定时', '发布时间'],
  approve_post: ['审批', '检查'],
  set_up_voice: ['语气', '写作风格', '样本'],
  create_automation: ['自动', '自动化', '每周', '每週'],
  upload_image: ['上传', '照片', '图片', '图库'],
  turn_on_web_search: ['上网', '网上搜索', '搜索', '天气', '新聞', '新闻'],
  choose_model: ['写手'],
  check_plan: ['额度', '积分', '计划', '点数', '點數']
};

const PRESET_WORDS: Record<PresetId, string[]> = {
  friendly: ['friendly', 'warm', 'casual', '友善', '親切', '友好', '亲切'],
  concise: ['concise', 'short', 'shorter', 'brief', 'direct', 'to the point', '精簡', '簡潔', '簡短', '精简', '简洁', '简短'],
  explainer: ['explainer', 'explain', 'detailed', 'detail', 'step by step', '詳細', '詳盡', '解釋', '详细', '详尽', '解释']
};

const longestFirst = (list: string[]) => list.toSorted((a, b) => b.length - a.length);
const PAGE_LEAD = longestFirst(['please', 'can you', 'could you', 'take me to', 'bring me to', 'navigate to', 'switch to', 'jump to', 'go to', 'goto', 'open up', 'open', 'show me', 'show', 'to', 'the', 'my', 'our', '請', '请', '幫我', '帮我', '帶我去', '带我去', '我想去', '我要去', '打開', '打开', '前往', '去', '開', '开', '睇下', '睇', '看看', '看', '我的', '我嘅']);
const PAGE_TAIL = longestFirst(['page', 'pages', 'tab', 'screen', 'section', 'view', 'settings', 'please', '頁面', '页面', '頁', '页', '版面', '設定', '设置', '設置']);
const GUIDE_LEAD = longestFirst(['please', 'can you', 'could you', 'show me how to', 'show me how', 'show me', 'teach me how to', 'teach me to', 'teach me', 'tell me how to', 'how do i', 'how can i', 'how do you', 'how to', 'help me', 'walk me through', 'guide me through', 'i want to', 'i need to', '請', '请', '教我', '教下我', '點樣', '点样', '怎樣', '怎样', '怎麼', '怎么', '如何', '我想', '我要', '幫我', '帮我', '可唔可以']);
const GUIDE_TAIL = longestFirst(['please', '呀', '啊', '嗎', '吗', '呢']);

/** Lower case, punctuation as spaces, and a space where Chinese meets other letters ("連接ig" → "連接 ig"). */
function normalize(text: string): string {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]+/gu, ' ')
    .replace(/(\p{Script=Han})(?=[^\p{Script=Han}\s])|([^\p{Script=Han}\s])(?=\p{Script=Han})/gu, '$1$2 ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** A rough English stem, so "channel" and "channels", or "connect" and "connecting", compare equal. */
function stem(word: string): string {
  if (HAN.test(word)) return word;
  let out = word;
  if (out.length > 4 && out.endsWith('s') && !out.endsWith('ss')) out = out.slice(0, -1);
  if (out.length > 5 && out.endsWith('ing')) out = out.slice(0, -3);
  else if (out.length > 4 && out.endsWith('ed')) out = out.slice(0, -2);
  if (out.length > 3 && out.endsWith('e')) out = out.slice(0, -1);
  return out;
}

function stems(text: string): string {
  return text.split(' ').map(stem).join(' ');
}

/** Whole words for English ("my channels page" has "channels"), plain containment for Chinese. */
function containsPhrase(text: string, phrase: string): boolean {
  if (!phrase) return false;
  if (HAN.test(phrase)) return text.replace(/ /g, '').includes(phrase.replace(/ /g, ''));
  return ` ${stems(text)} `.includes(` ${stems(phrase)} `);
}

/** Filler around the words that matter ("take me to the … page", "教我 …"); never strips everything. */
function strip(text: string, lead: string[], tail: string[]): string {
  let out = text;
  let changed = true;
  while (changed) {
    changed = false;
    for (const word of lead) {
      if (out !== word && (HAN.test(word) ? out.startsWith(word) : out.startsWith(`${word} `))) {
        out = out.slice(word.length).trim();
        changed = true;
        break;
      }
    }
    for (const word of tail) {
      if (out !== word && (HAN.test(word) ? out.endsWith(word) : out.endsWith(` ${word}`))) {
        out = out.slice(0, -word.length).trim();
        changed = true;
        break;
      }
    }
  }
  return out;
}

function distance(a: string, b: string): number {
  if (Math.abs(a.length - b.length) > 2) return 3;
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) row[j] = Math.min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    previous = row;
  }
  return previous[b.length];
}

/** How well a request names one page word: exact 100, start typed 80, named inside a longer request 70, part 60, typo 50. */
function pageScore(query: string, name: string): number {
  if (!query || !name) return 0;
  if (query === name || stems(query) === stems(name)) return 100;
  const han = HAN.test(query) || HAN.test(name);
  if (name.startsWith(query) && (han || query.length >= 2)) return 80;
  if (containsPhrase(query, name) && name.replace(/ /g, '').length >= (han ? 2 : 3)) return 70;
  if (han) return 0;
  if (query.length >= 3 && name.includes(query)) return 60;
  if (query.length >= 4 && distance(query, name) <= (query.length >= 7 ? 2 : 1)) return 50;
  return 0;
}

/**
 * The pages a request names: one page is a match, several are a question back, none is none. Titles, ids and the
 * words above count; a path (`/app/queue`) must match exactly. A match found only after dropping filler ranks one point
 * below a match of the whole request, so "account settings" is Profile while "privacy settings" is Privacy & data.
 */
export function findPages(query: string, pages: ManifestRoute[] = OPENABLE_PAGES): ManifestRoute[] {
  const raw = query.trim();
  if (raw.startsWith('/')) {
    const path = raw.split(/[?#\s]/)[0].replace(/(.)\/+$/, '$1');
    return pages.filter((page) => page.pattern === path);
  }
  const full = normalize(raw);
  if (!full) return [];
  const stripped = strip(full, PAGE_LEAD, PAGE_TAIL);
  let best = 0;
  let found: ManifestRoute[] = [];
  for (const page of pages) {
    const names = [page.id.replace(/_/g, ' '), page.title, ...(PAGE_WORDS[page.id] ?? [])].map(normalize);
    const score = Math.max(...names.map((name) => Math.max(pageScore(full, name), stripped !== full ? pageScore(stripped, name) - 1 : 0)));
    if (score > best) {
      best = score;
      found = [page];
    } else if (score > 0 && score === best) {
      found.push(page);
    }
  }
  return found;
}

function guideScore(guide: GuideEntry, full: string, asked: string): number {
  const keywords = [...guide.keywords, ...(GUIDE_WORDS[guide.id] ?? [])].map(normalize);
  const whole = [normalize(guide.title), guide.id.replace(/_/g, ' '), ...keywords];
  if (whole.some((phrase) => phrase === asked || stems(phrase) === stems(asked))) return 1000;
  let score = 0;
  // Every keyword the request mentions counts; longer, more specific keywords count more.
  for (const keyword of keywords) if (containsPhrase(full, keyword)) score += 10 + keyword.replace(/ /g, '').length;
  if (score) return score;
  // Still typing, or a small typo: a keyword that starts with, or is one letter away from, a word of the request.
  for (const word of asked.split(' ')) {
    const han = HAN.test(word);
    if (!han && word.length < 3) continue;
    for (const keyword of keywords) {
      if (keyword.startsWith(word) || (!han && word.length >= 5 && distance(word, keyword) <= 1)) score += 2;
    }
  }
  return score;
}

/** The guides a request asks for (the guide manifest's keywords and titles): one is a match, several are a question back. */
export function findGuides(query: string, guides: GuideEntry[] = GUIDES): GuideEntry[] {
  const full = normalize(query);
  if (!full) return [];
  const asked = strip(full, GUIDE_LEAD, GUIDE_TAIL);
  let best = 0;
  let found: GuideEntry[] = [];
  for (const guide of guides) {
    const score = guideScore(guide, full, asked);
    if (score > best) {
      best = score;
      found = [guide];
    } else if (score > 0 && score === best) {
      found.push(guide);
    }
  }
  return found;
}

/** The style preset a request names (`concise`, `Explain in detail`, `友善`, `詳細`); null when none or more than one. */
export function findPreset(query: string): PresetId | null {
  const asked = normalize(query);
  if (!asked) return null;
  const ids = Object.keys(PRESETS) as PresetId[];
  const hits = ids.filter((id) => [id, PRESETS[id].label, ...PRESET_WORDS[id]].some((word) => containsPhrase(asked, normalize(word))));
  return hits.length === 1 ? hits[0] : null;
}

// ---- Client commands -----------------------------------------------------------------------------------------------

function actionsOf(ctx?: CommandContext): Readonly<PanelActions> {
  return ctx?.actions ?? panelActions();
}

function clip(text: string, max = 40): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

function orList(items: string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} or ${items[items.length - 1]}`;
}

const quoted = (text: string) => `“${text}”`;

function openPage(args: string, ctx?: CommandContext): string {
  const navigate = actionsOf(ctx).navigate;
  if (!navigate) return "I can't open pages from here.";
  const query = args.trim();
  if (!query) return 'Which page? For example: /open Channels.';
  const pages = findPages(query);
  if (pages.length === 0) return `No page matches ${quoted(clip(query))}. Try Channels, Queue or Calendar.`;
  if (pages.length > 1) return `More than one page matches ${quoted(clip(query))}: ${orList(pages.slice(0, 4).map((page) => page.title))}. Which one?`;
  const [page] = pages;
  try {
    navigate(page.pattern);
  } catch {
    return `I couldn't open ${page.title}.`;
  }
  return `Opening ${page.title}.`;
}

async function runGuide(args: string, ctx?: CommandContext): Promise<string> {
  const startGuide = actionsOf(ctx).startGuide;
  if (!startGuide) return "I can't start guides from here.";
  const query = args.trim();
  const guides = query ? findGuides(query) : [];
  const examples = orList(GUIDES.slice(0, 3).map((guide) => quoted(guide.title)));
  if (guides.length === 0) return `${query ? `I don't have a guide for ${quoted(clip(query))}.` : 'Which guide?'} Try ${examples}.`;
  if (guides.length > 1) return `More than one guide fits: ${orList(guides.slice(0, 3).map((guide) => quoted(guide.title)))}. Which one?`;
  const [guide] = guides;
  let started = false;
  try {
    // The handler resolves false when the guide can't run on this screen.
    started = (await startGuide(guide.id)) !== false;
  } catch {
    started = false;
  }
  return started ? `Starting the guide: ${guide.title}.` : `I couldn't start the guide ${quoted(guide.title)} here.`;
}

async function changeStyle(args: string, ctx?: CommandContext): Promise<string> {
  const actions = actionsOf(ctx);
  const query = args.trim();
  const preset = query ? findPreset(query) : null;
  if (preset) {
    if (!actions.setStyle) return "I can't change the style from here.";
    try {
      await actions.setStyle({ preset, chosen: true });
    } catch {
      return "I couldn't save the style. Try again.";
    }
    return `Style set to ${PRESETS[preset].label}.`;
  }
  if (!actions.openStyle) return "I can't open the style settings from here.";
  try {
    actions.openStyle();
  } catch {
    return "I couldn't open the style settings.";
  }
  return query ? 'Opening the style settings. Choose Friendly, Concise or Explain in detail.' : 'Opening the style settings.';
}

function startVoice(_args: string, ctx?: CommandContext): string {
  const start = actionsOf(ctx).startVoice;
  if (!start) return "I can't start Voice Mode from here.";
  try {
    start();
  } catch {
    return "I couldn't start Voice Mode.";
  }
  return 'Starting Voice Mode.';
}

function newConversation(_args: string, ctx?: CommandContext): string {
  const start = actionsOf(ctx).newConversation;
  if (!start) return "I can't start a new conversation from here.";
  try {
    start();
  } catch {
    return "I couldn't start a new conversation.";
  }
  return 'Started a new conversation.';
}
