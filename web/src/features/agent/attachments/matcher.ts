/**
 * Typeahead matching for the `@` list (chat-context SPEC §4.3), the web twin of `site_agent.reads.picker_query` /
 * `picker_search` (shared vectors: tests/fixtures/picker-queries.json). NFKC + lowercase on both sides; a whole-word
 * category alias (Traditional, Simplified, English) switches the list to that group and the rest filters within it;
 * a platform alias switches to accounts on that platform. Ranking: prefix > word start > substring > recency.
 * No `@/` imports (node --test transpiles it).
 */

export type PickerCategory =
  | 'posts'
  | 'templates'
  | 'accounts'
  | 'folders'
  | 'sources'
  | 'skills'
  | 'connectors'
  | 'library';

export const CATEGORY_ALIASES: Record<PickerCategory, readonly string[]> = {
  posts: ['帖子', '帖', '貼文', '贴文', '草稿', '文章', 'post', 'posts', 'draft', 'drafts'],
  templates: ['範本', '范本', '模板', 'template', 'templates'],
  accounts: ['帳號', '账号', '帳戶', '账户', '頻道', '频道', 'account', 'accounts', 'channel'],
  folders: ['資料夾', '资料夹', '文件夾', '文件夹', 'folder', 'folders'],
  sources: ['來源', '来源', '素材', '資料', '资料', 'source', 'sources', 'note', 'notes'],
  skills: ['技能', '技巧', 'skill', 'skills'],
  connectors: ['連接', '连接', 'connector', 'connectors', 'connected', 'app', 'apps'],
  library: [
    '相',
    '相片',
    '照片',
    '圖片',
    '图片',
    '圖',
    '图',
    '影片',
    '視頻',
    '视频',
    'photo',
    'photos',
    'image',
    'picture',
    'video',
    'videos',
    'library'
  ]
};

export const PLATFORM_ALIASES: Record<string, readonly string[]> = {
  Instagram: ['ig', 'insta', 'instagram'],
  LinkedIn: ['li', 'linkedin', '領英', '领英'],
  X: ['x', 'twitter', '推特'],
  Threads: ['threads'],
  Xiaohongshu: ['小紅書', '小红书', 'red', 'xhs', 'xiaohongshu']
};

const KIND_CATEGORY: Record<string, PickerCategory> = {
  post: 'posts',
  template: 'templates',
  account: 'accounts',
  folder: 'folders',
  source: 'sources',
  skill: 'skills',
  connector_item: 'connectors',
  image: 'library',
  video: 'library'
};

export function normalize(value: string): string {
  return value.normalize('NFKC').toLowerCase().trim();
}

export interface ParsedQuery {
  text: string;
  category: PickerCategory | null;
  platform: string | null;
}

/** Mirror of `reads.picker_query`: a leading `@`/`＠` is ignored; a whole-word alias picks a group or a platform. */
export function parseQuery(query: string): ParsedQuery {
  const text = normalize(query).replace(/^@+/, '').trim();
  for (const [category, aliases] of Object.entries(CATEGORY_ALIASES) as [
    PickerCategory,
    readonly string[]
  ][]) {
    for (const alias of [...aliases].toSorted((a, b) => b.length - a.length)) {
      const a = normalize(alias);
      if (text === a || text.startsWith(`${a} `))
        return { text: text.slice(a.length).trim(), category, platform: null };
    }
  }
  for (const [platform, aliases] of Object.entries(PLATFORM_ALIASES)) {
    for (const alias of aliases) {
      const a = normalize(alias);
      if (text === a || text.startsWith(`${a} `))
        return { text: text.slice(a.length).trim(), category: 'accounts', platform };
    }
  }
  return { text, category: null, platform: null };
}

export interface PickerItemLike {
  kind: string;
  id: string;
  label: string;
  sublabel?: string;
  platform?: string;
  updatedAt?: number | null;
  /** Extra text to match (a post's body, an account name). */
  search?: string;
}

/** 3 prefix, 2 word start, 1 substring, 0 no match. An empty needle matches everything (recents). */
export function score(needle: string, ...haystacks: (string | undefined)[]): number {
  if (!needle) return 1;
  let best = 0;
  for (const raw of haystacks) {
    if (!raw) continue;
    const text = normalize(raw);
    const at = text.indexOf(needle);
    if (at < 0) continue;
    const before = at > 0 ? text[at - 1] : '';
    best = Math.max(best, at === 0 ? 3 : /[\p{L}\p{N}]/u.test(before) ? 1 : 2);
  }
  return best;
}

export function categoryOf(item: PickerItemLike): PickerCategory | null {
  return KIND_CATEGORY[item.kind] ?? null;
}

/**
 * The items that match `query`, best first. Items are expected newest first when they carry no `updatedAt`;
 * the original order breaks ties.
 */
export function rank<T extends PickerItemLike>(
  query: string,
  items: readonly T[]
): { category: PickerCategory | null; items: T[] } {
  const parsed = parseQuery(query);
  const scored = items
    .map((item, index) => ({ item, index, category: categoryOf(item) }))
    .filter(
      ({ item, category }) =>
        (!parsed.category || category === parsed.category) &&
        (!parsed.platform || item.platform === parsed.platform)
    )
    .map((row) => ({
      ...row,
      score: score(parsed.text, row.item.label, row.item.sublabel, row.item.search)
    }))
    .filter((row) => row.score > 0);
  scored.sort(
    (a, b) =>
      b.score - a.score || (b.item.updatedAt ?? 0) - (a.item.updatedAt ?? 0) || a.index - b.index
  );
  return { category: parsed.category, items: scored.map((row) => row.item) };
}

/** Server results win by id; local results show until the server answers (SPEC §4.3). */
export function mergeResults<T extends { kind: string; id: string }>(
  local: readonly T[],
  server: readonly T[] | null
): T[] {
  if (!server) return [...local];
  const seen = new Set(server.map((item) => `${item.kind}:${item.id}`));
  return [...server, ...local.filter((item) => !seen.has(`${item.kind}:${item.id}`))];
}

/** Whether a typed query is worth a server search: one Han/Kana/Hangul character, or two Latin characters. */
export function wantsServer(query: string): boolean {
  const text = parseQuery(query).text;
  return (
    /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(text) ||
    Array.from(text).length >= 2
  );
}
