/**
 * Readable names for the ids the voice import and the profile review show: trait dimensions, platforms, language
 * tags and the reasons a post was left out. English, Traditional Chinese and Simplified Chinese, the three locales
 * Brand Brain speaks. An id this file has not met is turned into words, never shown raw.
 */

export type Language = 'en' | 'zh-Hant' | 'zh-Hans';
export type Triple = readonly [en: string, hant: string, hans: string];

export function pick(language: Language, value: Triple): string {
  return value[language === 'zh-Hant' ? 1 : language === 'zh-Hans' ? 2 : 0];
}

/** Every dimension the local rules, the AI analysis and the corpus analysis can report. */
export const TRAIT_LABELS: Record<string, Triple> = {
  language: ['Language', '語言', '语言'],
  code_switching: ['Mixing languages', '中英夾雜', '中英夹杂'],
  formality: ['Formality', '正式程度', '正式程度'],
  warmth: ['Warmth', '親切感', '亲切感'],
  humor: ['Humour', '幽默感', '幽默感'],
  vocabulary: ['Vocabulary', '用詞', '用词'],
  person: ['Point of view', '人稱', '人称'],
  sentence_length: ['Sentence length', '句子長度', '句子长度'],
  paragraph_length: ['Paragraph length', '段落長度', '段落长度'],
  openings: ['Openings', '開頭方式', '开头方式'],
  narrative_structure: ['Story structure', '敘事結構', '叙事结构'],
  calls_to_action: ['Calls to action', '行動呼籲', '行动号召'],
  promotional_intensity: ['Promotional tone', '宣傳力度', '宣传力度'],
  emoji: ['Emoji', '表情符號', '表情符号'],
  hashtags: ['Hashtags', '主題標籤', '话题标签'],
  punctuation: ['Punctuation', '標點符號', '标点符号'],
  platform_differences: ['Differences between platforms', '平台之間的差異', '平台之间的差异'],
  recurring_patterns: ['Recurring patterns', '重複出現的模式', '重复出现的模式'],
  tone: ['Tone', '語氣', '语气'],
  sentence_rhythm: ['Sentence rhythm', '句子節奏', '句子节奏'],
  opening_shape: ['How posts open', '貼文如何開頭', '帖子如何开头'],
  closing_shape: ['How posts end', '貼文如何收結', '帖子如何收尾'],
  vocabulary_register: ['Word choice', '用詞與語域', '用词与语域'],
  structure: ['Structure', '結構', '结构'],
  topics: ['Topics', '主題', '主题'],
  reader_address: ['How readers are addressed', '如何稱呼讀者', '如何称呼读者'],
  direction: ['Direction I want', '我想要的方向', '我想要的方向']
};

/**
 * A trait's name. Import traits carry their base dimension; a scoped or interpreted trait's own id is the dimension
 * plus a suffix (`emoji:instagram`, `tone.ai:linkedin`, `direction-1`), so the base is read from the id when absent.
 */
export function traitLabel(id: string, language: Language, dimension?: string | null): string {
  const base = (dimension || id).split(/[.:]/)[0].replace(/-\d+$/, '');
  const known = TRAIT_LABELS[base];
  if (known) return pick(language, known);
  const words = base.replace(/[_-]+/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : id;
}

const PLATFORMS: Record<string, string> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  threads: 'Threads',
  x: 'X',
  linkedin: 'LinkedIn',
  mastodon: 'Mastodon',
  bluesky: 'Bluesky',
  youtube: 'YouTube',
  tiktok: 'TikTok'
};

/** The platform's own name for a provider id (`linkedin` → LinkedIn). Brand names are not translated. */
export function platformName(provider: string): string {
  const id = provider.trim().toLowerCase();
  return PLATFORMS[id] ?? (id ? id[0].toUpperCase() + id.slice(1) : provider);
}

const LANGUAGES: Record<string, Triple> = {
  en: ['English', '英文', '英文'],
  'zh-Hant': ['Traditional Chinese', '繁體中文', '繁体中文'],
  'zh-Hans': ['Simplified Chinese', '簡體中文', '简体中文'],
  yue: ['Cantonese', '廣東話', '粤语'],
  mixed: ['Chinese and English mixed', '中英夾雜', '中英夹杂'],
  und: ['Language not identified', '未能識別語言', '未能识别语言']
};

export function languageName(tag: string, language: Language): string {
  const known = LANGUAGES[tag];
  return known ? pick(language, known) : tag;
}

/** Reasons in the order the receipt lists them. `manual` is the person's own "leave this post out". */
export const EXCLUSION_ORDER = ['repost', 'duplicate', 'rafii_published', 'too_short', 'other_author', 'outdated', 'manual'] as const;

const EXCLUSIONS: Record<string, { one: string; many: string; hant: string; hans: string }> = {
  repost: { one: 'repost', many: 'reposts', hant: '篇轉發', hans: '篇转发' },
  duplicate: { one: 'duplicate', many: 'duplicates', hant: '篇重複', hans: '篇重复' },
  rafii_published: { one: 'post written with Rafii', many: 'posts written with Rafii', hant: '篇由 Rafii 撰寫', hans: '篇由 Rafii 撰写' },
  too_short: { one: 'too short to learn from', many: 'too short to learn from', hant: '篇太短，無法學習', hans: '篇太短，无法学习' },
  other_author: { one: 'written by someone else', many: 'written by someone else', hant: '篇由他人撰寫', hans: '篇由他人撰写' },
  outdated: { one: 'marked as old style', many: 'marked as old style', hant: '篇標記為舊風格', hans: '篇标记为旧风格' },
  manual: { one: 'left out by you', many: 'left out by you', hant: '篇由你排除', hans: '篇由你排除' }
};

/** "40 reposts", "1 duplicate", "40 篇轉發". An unknown reason keeps its words. */
export function exclusionPhrase(reason: string, count: number, language: Language, format: (value: number) => string = String): string {
  const known = EXCLUSIONS[reason];
  if (!known) return `${format(count)} ${reason.replace(/_/g, ' ')}`;
  if (language === 'en') return `${format(count)} ${count === 1 ? known.one : known.many}`;
  return `${format(count)} ${language === 'zh-Hant' ? known.hant : known.hans}`;
}

/** Why one post is left out, as a short label on the post. */
export function exclusionLabel(reason: string, language: Language): string {
  const labels: Record<string, Triple> = {
    repost: ['Repost', '轉發', '转发'],
    duplicate: ['Duplicate', '重複', '重复'],
    rafii_published: ['Written with Rafii', '由 Rafii 撰寫', '由 Rafii 撰写'],
    too_short: ['Too short', '太短', '太短'],
    other_author: ['Someone else wrote it', '他人撰寫', '他人撰写'],
    outdated: ['Old style', '舊風格', '旧风格'],
    manual: ['Left out by you', '由你排除', '由你排除']
  };
  const known = labels[reason];
  return known ? pick(language, known) : reason.replace(/_/g, ' ');
}
