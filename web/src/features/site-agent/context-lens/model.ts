/**
 * Context Lens (Agent Experience P1.1): what the next typed message to Rafii will use, as chips the person can inspect and
 * remove. The server decides every item (`POST /agent/context-lens`, agent_runtime_v2/context_lens.py) and re-resolves it
 * when the message is sent; this module only words it and keeps the person's removals for the next message. A removal is
 * sent as `contextLens.exclude` and honoured on the server for that message; nothing here can add context.
 *
 * Dependency-free on purpose (no `@/` imports), so web/tests/context-lens.test.cjs can load it directly.
 */

export type LensLanguage = 'en' | 'zh-Hant' | 'zh-Hans';
export type LensStatus = 'included' | 'removed' | 'unavailable' | 'denied';
export type LensKind = 'workspace' | 'page' | 'selection' | 'screen' | 'visible_state' | 'reference' | 'attachment' | 'view_selection' | 'conversation' | 'work' | 'style';

export interface LensItem {
  id: string;
  kind: LensKind;
  status: LensStatus;
  removable: boolean;
  source: string;
  permission: string;
  observedAt: string;
  expiresAt: string | null;
  reason?: string;
  role?: string;
  routeId?: string;
  title?: string;
  entityType?: string;
  entityId?: string;
  detail?: string;
  count?: number;
  keys?: string[];
  refKind?: string;
  mediaKind?: string;
  messages?: number;
  images?: number;
  approvals?: number;
  lastTask?: boolean;
}

export interface LensPreview {
  version: string;
  enabled: boolean;
  visibleStateEnabled: boolean;
  observedAt: string;
  expiresAt: string;
  items: LensItem[];
  ambiguity: { status: 'no_selection' } | null;
}

/** The person's display language for Rafii's own copy (English, Traditional or Simplified Chinese; others read English). */
export function lensLanguage(locale: string | null | undefined): LensLanguage {
  const tag = String(locale || 'en').replaceAll('_', '-').toLowerCase();
  if (!tag.startsWith('zh') && !tag.startsWith('yue')) return 'en';
  return /hans|-(cn|sg|my)(-|$)/.test(tag) ? 'zh-Hans' : 'zh-Hant';
}

type Copy = Record<string, readonly [string, string, string]>;

/** [English, Traditional Chinese (Hong Kong), Simplified Chinese]. */
export const COPY = {
  region: ['Context for your next message', '下一則訊息會用到的資料', '下一条消息会用到的资料'],
  checking: ['Checking what Rafii will use…', '正在確認 Rafii 會用到的資料…', '正在确认 Rafii 会用到的资料…'],
  failed: ['Couldn’t show what Rafii will use. Your message still follows your permissions.', '未能顯示 Rafii 會用到的資料。你的訊息仍會按你的權限處理。', '无法显示 Rafii 会用到的资料。你的消息仍会按你的权限处理。'],
  retry: ['Check again', '再檢查一次', '再检查一次'],
  more: ['{count} more', '另外 {count} 項', '另外 {count} 项'],
  fewer: ['Show fewer', '顯示較少', '显示较少'],
  remove: ['Remove {label} from your next message', '從下一則訊息移除「{label}」', '从下一条消息移除“{label}”'],
  restore: ['Put {label} back', '放回「{label}」', '放回“{label}”'],
  inspect: ['About {label}', '關於「{label}」', '关于“{label}”'],
  close: ['Close', '關閉', '关闭'],
  removedNow: ['{label} won’t be used for your next message.', '下一則訊息不會用到「{label}」。', '下一条消息不会用到“{label}”。'],
  restoredNow: ['{label} will be used again.', '會再用到「{label}」。', '会再用到“{label}”。'],
  noSelection: ['No item selected', '未有選取項目', '未选取项目'],
  noSelectionWhy: ['Nothing is selected or attached, so Rafii will ask which one you mean instead of guessing.', '你未有選取或附加任何項目，Rafii 會先問你指的是哪一個，不會亂猜。', '你没有选取或附加任何项目，Rafii 会先问你指的是哪一个，不会乱猜。'],
  nextOnly: ['Removing something applies to your next message only.', '移除只適用於下一則訊息。', '移除只适用于下一条消息。'],
  dataOnly: ['Rafii treats all of this as information, never as instructions.', 'Rafii 只會把這些當作資料，絕不會當作指示。', 'Rafii 只会把这些当作资料，绝不会当作指令。'],
  checkedAt: ['Checked at {time}', '於 {time} 檢查', '于 {time} 检查'],
  newConversation: ['Start a new conversation', '開始新對話', '开始新对话'],
  // Chip labels.
  workspace: ['Workspace · {role}', '工作區 · {role}', '工作区 · {role}'],
  page: ['{title} page', '{title} 頁面', '{title} 页面'],
  unknownPage: ['A page Rafii doesn’t know', 'Rafii 不認識的頁面', 'Rafii 不认识的页面'],
  selection: ['Selected {entity}', '已選取的{entity}', '已选取的{entity}'],
  screen: ['What’s on screen', '畫面上的內容', '屏幕上的内容'],
  visible_state: ['Filters and view', '篩選和檢視', '筛选和视图'],
  view_selection: ['Your picks ({count})', '你的選擇（{count}）', '你的选择（{count}）'],
  conversation: ['This conversation', '這個對話', '这个对话'],
  work: ['Work in progress', '進行中的工作', '进行中的工作'],
  style: ['Your Rafii style', '你的 Rafii 風格', '你的 Rafii 风格'],
  photo: ['Photo', '相片', '照片'],
  video: ['Video', '影片', '视频'],
  attachment: ['Attachment', '附件', '附件'],
  // Why each item is there.
  whyWorkspace: ['Rafii always knows your workspace and role. Every action is checked against your permissions, so this can’t be removed.', 'Rafii 一定知道你的工作區和角色。每個操作都會按你的權限檢查，所以這項不能移除。', 'Rafii 一定知道你的工作区和角色。每个操作都会按你的权限检查，所以这项不能移除。'],
  whyPage: ['Rafii knows which page you’re on so it can answer about it and show you around. It never reads what you type into the page.', 'Rafii 知道你在哪個頁面，方便回答和帶你操作。它不會讀取你在頁面上輸入的內容。', 'Rafii 知道你在哪个页面，方便回答和带你操作。它不会读取你在页面上输入的内容。'],
  whySelection: ['The item selected on this page. Rafii re-checks it in this workspace before using it.', '這個頁面上已選取的項目。Rafii 使用前會在這個工作區重新核對。', '这个页面上已选取的项目。Rafii 使用前会在这个工作区重新核对。'],
  whyScreen: ['The headings, buttons and tabs you can see ({count}). Never typed text, private areas or files.', '你看到的標題、按鈕和分頁（{count} 項），絕不包括輸入的文字、私人區域或檔案。', '你看到的标题、按钮和标签（{count} 项），绝不包括输入的文字、私人区域或文件。'],
  whyVisible: ['The filters, dates and tabs this page is showing.', '這個頁面正在顯示的篩選、日期和分頁。', '这个页面正在显示的筛选、日期和标签。'],
  whyReference: ['You added this to your message.', '你把這項加到訊息裡。', '你把这项加到消息里。'],
  whyAttachment: ['You attached this to your message.', '你把這項附加到訊息。', '你把这项附加到消息。'],
  whyViewSelection: ['What you picked in the interactive view.', '你在互動畫面中選擇的項目。', '你在互动视图中选择的项目。'],
  whyConversation: ['The recent messages ({messages}) and images ({images}) in this conversation. To start without them, open a new conversation.', '這個對話最近的訊息（{messages}）和圖片（{images}）。如想不用這些，可以開始新對話。', '这个对话最近的消息（{messages}）和图片（{images}）。如果不想用这些，可以开始新对话。'],
  whyWork: ['Work Rafii is doing for you here and decisions waiting for you ({approvals}), so nothing is repeated or lost. This can’t be removed.', 'Rafii 正在這裡為你處理的工作和等你決定的事項（{approvals}），確保不會重複或遺漏，所以不能移除。', 'Rafii 正在这里为你处理的工作和等你决定的事项（{approvals}），确保不会重复或遗漏，所以不能移除。'],
  whyStyle: ['How you asked Rafii to talk. Remove it to use the default style for your next message.', '你要求 Rafii 用的說話方式。移除後，下一則訊息會用預設風格。', '你要求 Rafii 用的说话方式。移除后，下一条消息会用默认风格。'],
  // Status.
  statusRemoved: ['Removed. Rafii won’t use this for your next message.', '已移除。下一則訊息不會用到這項。', '已移除。下一条消息不会用到这项。'],
  statusUnavailable: ['Not used: it isn’t in this workspace or isn’t ready.', '不會使用：它不在這個工作區，或者未準備好。', '不会使用：它不在这个工作区，或者尚未准备好。'],
  statusUnknownPage: ['Not used: Rafii doesn’t know this page.', '不會使用：Rafii 不認識這個頁面。', '不会使用：Rafii 不认识这个页面。'],
  statusDenied: ['Not used: your role or Rafii’s permissions don’t allow it.', '不會使用：你的角色或 Rafii 的權限不允許。', '不会使用：你的角色或 Rafii 的权限不允许。'],
  notUsedShort: ['not used', '不會使用', '不会使用'],
  removedShort: ['removed', '已移除', '已移除']
} as const satisfies Copy;

export type CopyKey = keyof typeof COPY;

const ROLE: Copy = {
  owner: ['Owner', '擁有人', '所有者'],
  admin: ['Admin', '管理員', '管理员'],
  editor: ['Editor', '編輯', '编辑'],
  approver: ['Approver', '審批人', '审批人'],
  viewer: ['Viewer', '檢視者', '查看者']
};

const ENTITY: Copy = {
  draft: ['draft', '草稿', '草稿'],
  job: ['post', '帖子', '帖子'],
  review: ['post', '帖子', '帖子'],
  automation: ['automation', '自動化', '自动化'],
  source: ['source', '來源', '来源'],
  connection: ['account', '帳戶', '账户'],
  asset: ['file', '檔案', '文件'],
  memory_proposal: ['memory suggestion', '記憶建議', '记忆建议'],
  automation_run: ['automation run', '自動化執行', '自动化运行']
};

const REFERENCE: Copy = {
  post: ['Post', '帖子', '帖子'],
  source: ['Source', '來源', '来源'],
  template: ['Template', '範本', '模板'],
  account: ['Account', '帳戶', '账户'],
  folder: ['Folder', '資料夾', '文件夹'],
  skill: ['Skill', '技能', '技能'],
  connector_item: ['Linked item', '連結項目', '链接项目']
};

function pick(entry: readonly [string, string, string] | undefined, lang: LensLanguage, fallback = ''): string {
  if (!entry) return fallback;
  return entry[lang === 'zh-Hant' ? 1 : lang === 'zh-Hans' ? 2 : 0];
}

export function t(key: CopyKey, lang: LensLanguage, values: Record<string, string | number> = {}): string {
  return pick(COPY[key], lang).replace(/\{([a-z]+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole));
}

/** The short chip text. Details from the workspace (a platform, a source title) are the person's own data, shown as text. */
export function chipLabel(item: LensItem, lang: LensLanguage): string {
  const withDetail = (base: string) => (item.detail ? `${base} · ${item.detail}` : base);
  switch (item.kind) {
    case 'workspace':
      return t('workspace', lang, { role: pick(ROLE[item.role ?? ''], lang, item.role ?? '') });
    case 'page':
      return item.title ? t('page', lang, { title: item.title }) : t('unknownPage', lang);
    case 'selection':
      return withDetail(t('selection', lang, { entity: pick(ENTITY[item.entityType ?? ''], lang, item.entityType ?? '') }));
    case 'screen':
      return t('screen', lang);
    case 'visible_state':
      return t('visible_state', lang);
    case 'reference':
      return withDetail(pick(REFERENCE[item.refKind ?? ''], lang, item.refKind ?? ''));
    case 'attachment':
      return t(item.mediaKind === 'video' ? 'video' : item.mediaKind === 'image' ? 'photo' : 'attachment', lang);
    case 'view_selection':
      return t('view_selection', lang, { count: item.count ?? 0 });
    case 'conversation':
      return t('conversation', lang);
    case 'work':
      return item.title ? `${t('work', lang)} · ${item.title}` : t('work', lang);
    case 'style':
      return t('style', lang);
    default:
      return item.kind;
  }
}

/** Why the item is there (the first line of its details). */
export function whyLine(item: LensItem, lang: LensLanguage): string {
  switch (item.kind) {
    case 'workspace':
      return t('whyWorkspace', lang);
    case 'page':
      return t('whyPage', lang);
    case 'selection':
      return t('whySelection', lang);
    case 'screen':
      return t('whyScreen', lang, { count: item.count ?? 0 });
    case 'visible_state':
      return t('whyVisible', lang);
    case 'reference':
      return t('whyReference', lang);
    case 'attachment':
      return t('whyAttachment', lang);
    case 'view_selection':
      return t('whyViewSelection', lang);
    case 'conversation':
      return t('whyConversation', lang, { messages: item.messages ?? 0, images: item.images ?? 0 });
    case 'work':
      return t('whyWork', lang, { approvals: item.approvals ?? 0 });
    case 'style':
      return t('whyStyle', lang);
    default:
      return '';
  }
}

/** The status line, or null for an item that will be used. */
export function statusLine(item: LensItem, lang: LensLanguage, removedHere: boolean): string | null {
  if (removedHere || item.status === 'removed') return t('statusRemoved', lang);
  if (item.status === 'unavailable') return t(item.reason === 'unknown_page' ? 'statusUnknownPage' : 'statusUnavailable', lang);
  if (item.status === 'denied') return t('statusDenied', lang);
  return null;
}

/** "Checked at 14:05" in the person's language and time zone, or null when the time can't be read. */
export function checkedLine(item: LensItem, lang: LensLanguage, timeZone?: string): string | null {
  const at = Date.parse(item.observedAt);
  if (!Number.isFinite(at)) return null;
  let time: string;
  try {
    time = new Intl.DateTimeFormat(lang, { hour: '2-digit', minute: '2-digit', ...(timeZone ? { timeZone } : {}) }).format(new Date(at));
  } catch {
    time = new Date(at).toISOString().slice(11, 16);
  }
  return t('checkedAt', lang, { time });
}

/**
 * "this", "this one", "these", "呢個", "這個", "这个" without naming the item (time words like "this week" don't count). Kept in step
 * with context_lens.DEICTIC on the server, which adds the matching "ask, don't guess" note for the model.
 */
const DEICTIC = /\b(?:this|these)\b(?!\s+(?:week|month|year|morning|afternoon|evening|tonight|weekend|time|quarter|season|spring|summer|autumn|fall|winter)\b)|\bthat\s+one\b|(?:呢個|呢篇|呢張|這個|這篇|這張|这个|这篇|这张)(?!星期|禮拜|礼拜|月|週|周|年)/i;

export function isDeictic(text: string): boolean {
  return DEICTIC.test(text || '');
}

const NAMED: readonly LensKind[] = ['selection', 'reference', 'attachment', 'view_selection'];

/** Whether the panel should say "No item selected" for what is being typed: it points at "this" and nothing will be used for it. */
export function noSelection(preview: LensPreview | null, text: string, removed: ReadonlySet<string>): boolean {
  if (!preview || !isDeictic(text)) return false;
  return !preview.items.some((item) => NAMED.includes(item.kind) && item.status === 'included' && !removed.has(item.id));
}

/** The removals to send with the next message: only ids the current preview lists as removable (a stale one is dropped). */
export function exclusionsFor(preview: LensPreview | null, removed: ReadonlySet<string>): string[] {
  if (!preview) return [];
  const listed = new Set(preview.items.filter((item) => item.removable && (item.status === 'included' || item.status === 'removed')).map((item) => item.id));
  return [...removed].filter((id) => listed.has(id)).sort().slice(0, 48);
}

/**
 * The chips in reading order: the page, then what the person can remove, then the basics that always apply, then what
 * they removed, then what won't be used.
 */
export function chips(preview: LensPreview | null, removed: ReadonlySet<string>): LensItem[] {
  if (!preview) return [];
  const rank = (item: LensItem) => {
    if (removed.has(item.id) || item.status === 'removed') return 3;
    if (item.status !== 'included') return 4;
    if (item.kind === 'page') return 0;
    return item.removable ? 1 : 2;
  };
  return preview.items.map((item, index) => ({ item, index })).sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index).map(({ item }) => item);
}

/** Whether a chip's item will be used for the next message (included by the server and not removed here). */
export function used(item: LensItem, removed: ReadonlySet<string>): boolean {
  return item.status === 'included' && !removed.has(item.id);
}

/**
 * The preview request for the current panel state: the page, the conversation and the attached images, never the message
 * being typed. Removals stay in the panel until the message is sent (the server re-resolves everything then).
 */
export function previewBody(input: { conversationId: string | null; pageContext: unknown; attachments: readonly { assetId: string }[] }): Record<string, unknown> {
  return {
    ...(input.conversationId ? { conversationId: input.conversationId } : {}),
    pageContext: input.pageContext,
    ...(input.attachments.length ? { attachments: input.attachments.map((item) => ({ assetId: item.assetId, role: 'reference' })) } : {})
  };
}
