/**
 * Post languages as locale tags (docs/postriff-worldwide-languages-plan.md), mirroring
 * `src/postriff_phase2/locales.py` over the same generated catalogue. Pure and import-free so
 * `node --test` can load it directly; the app imports it through `./index`.
 */

export type LocaleTag = string;

export interface LocaleEntry {
  tag: LocaleTag;
  family: string;
  native: string;
  english: string;
  promptName: string;
  aliases: string[];
  namedAs: string[];
  tier: 'tuned' | 'available';
  guide: string | null;
  guideDepth: 'full' | 'compact' | null;
  reviewed: boolean;
  regionless: boolean;
  parent: LocaleTag | null;
  dir: 'ltr' | 'rtl';
  glyphs: 'hk' | 'tw' | 'cn' | 'ja' | 'ko' | 'ar' | 'ur' | 'he' | null;
  flag: string;
  countUnit: 'characters' | 'words';
  gendered: boolean;
}

export interface Catalogue {
  version: string;
  families: { id: string; label: string; native: string }[];
  legacy: Record<string, LocaleTag>;
  inputAliases: Record<string, LocaleTag>;
  usual: Record<string, LocaleTag>;
  defaultLocale: LocaleTag;
  familyGuides: string[];
  entries: LocaleEntry[];
}

export interface SearchResult {
  entry: LocaleEntry;
  score: number;
  /** The alias that matched, when it isn't one of the entry's names. */
  alias: string | null;
}

export interface NamedLanguage {
  tag: LocaleTag;
  said: string;
  start: number;
}

export interface MessageLanguages {
  /** Languages named in a clause without a channel: they apply to every channel. */
  all: NamedLanguage[] | null;
  perPlatform: Map<string, NamedLanguage[]>;
}

const TAG = /^[a-z]{2,3}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|\d{3}))?(?:-(?:[a-z0-9]{5,8}|\d[a-z0-9]{3}))*$/;
const PUNCTUATION = /[()（）·,，、\-_/]+/g;
const TOKEN = "[^\\s,.;:!?()，。、；：！？「」“”\"']+";
const WORDS = new RegExp(`^${TOKEN}(?:[ \\t]+${TOKEN}){0,2}`);
const ENGLISH_TRIGGER = /\b(?:in|into|using)\s+/gi;
const CJK_TRIGGER = /[用以成做]\s?/g;
const JOIN = /^\s*(?:\band\b|&|\/|\bor\b|同|和|及|、|與|与|或)\s*/i;
const CLAUSE_SPLIT = /[，,。;；\n!?！？]+|\.\s/;
const FAMILY_SAID = new Set(['chinese', '中文']);
// U+0300–U+036F only: other scripts' combining marks (Devanagari, Thai vowels) are part of the letter.
const COMBINING_MARKS = new RegExp(`[${String.fromCharCode(0x300)}-${String.fromCharCode(0x36f)}]`, 'g');

export const PLATFORM_WORDS: [string, RegExp][] = [
  ['LinkedIn', /linkedin|領英|领英/gi],
  ['Xiaohongshu', /xiaohongshu|rednote|\bxhs\b|小紅書|小红书/gi],
  ['Instagram', /instagram|\binsta\b|\big\b/gi],
  ['Threads', /\bthreads\b/gi],
  ['X', /twitter|x\.com|推特/gi]
];

/** Case-, accent- and width-insensitive form for matching names and aliases. */
export function fold(value: string): string {
  return (value || '')
    .normalize('NFKC')
    .toLowerCase()
    .normalize('NFD')
    .replace(COMBINING_MARKS, '')
    .normalize('NFC')
    .replace(PUNCTUATION, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isAscii(value: string) {
  return [...value].every((ch) => ch.charCodeAt(0) < 128);
}

function truncations(tag: string) {
  const parts = tag.split('-');
  return parts.map((_, i) => parts.slice(0, parts.length - i).join('-'));
}

function shape(parts: string[]) {
  return parts.map((part, i) => {
    if (i === 0) return part;
    if (part.length === 4 && /^[a-z]+$/.test(part)) return part[0].toUpperCase() + part.slice(1);
    if ((part.length === 2 && /^[a-z]+$/.test(part)) || /^\d{3}$/.test(part)) return part.toUpperCase();
    return part;
  });
}

function levenshtein(a: string, b: string) {
  if (Math.abs(a.length - b.length) > 2) return 9;
  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) {
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    previous = current;
  }
  return previous[b.length];
}

export function createLocales(catalogue: Catalogue) {
  const byTag = new Map(catalogue.entries.map((e) => [e.tag, e]));
  const byLower = new Map(catalogue.entries.map((e) => [e.tag.toLowerCase(), e.tag]));
  const bases = new Set(catalogue.entries.map((e) => e.tag.split('-')[0].toLowerCase()));
  const names = new Map<string, LocaleTag>();
  const named = new Map<string, LocaleTag>();
  for (const e of catalogue.entries) {
    for (const name of [e.native, e.english]) if (!names.has(fold(name))) names.set(fold(name), e.tag);
    for (const said of e.namedAs) if (!named.has(fold(said))) named.set(fold(said), e.tag);
  }
  const unspaced = catalogue.entries
    .flatMap((e) => e.namedAs.filter((said) => !isAscii(said)).map((said) => [said, e.tag] as const))
    .toSorted((a, b) => b[0].length - a[0].length);
  const searchKeys = catalogue.entries.map((e) => ({
    entry: e,
    fields: [
      ...[e.native, e.english].map((raw) => ({ raw, key: fold(raw), name: true })),
      ...[...e.aliases, ...e.namedAs, e.tag].map((raw) => ({ raw, key: fold(raw), name: false }))
    ].filter((f) => f.key)
  }));

  function canonical(value: unknown, familyOk = false): LocaleTag | null {
    if (typeof value !== 'string') return null;
    const raw = value.trim();
    if (!raw || raw.length > 64) return null;
    if (catalogue.legacy[raw]) return catalogue.legacy[raw];
    const lower = raw.replace(/_/g, '-').toLowerCase();
    if (catalogue.inputAliases[lower]) return catalogue.inputAliases[lower];
    if (byLower.has(lower)) return byLower.get(lower)!;
    const byName = names.get(fold(raw));
    if (byName) return byName;
    if (!TAG.test(lower)) return null;
    const parts = shape(lower.split('-'));
    if (!bases.has(parts[0])) return null;
    if (parts[0] === 'zh' || parts[0] === 'yue') {
      if (parts.length === 1) return familyOk ? parts[0] : null;
      if (parts[1].length !== 4) parts.splice(1, 0, ['HK', 'MO', 'TW'].includes(parts[1]) ? 'Hant' : 'Hans');
    }
    const tag = parts.join('-');
    if (parts.length === 1 && !byTag.has(tag)) {
      const listed = catalogue.entries.filter((e) => e.tag.split('-')[0] === tag);
      if (listed.length === 1) return listed[0].tag;
    }
    return byLower.get(tag.toLowerCase()) ?? tag;
  }

  function entry(value: unknown): LocaleEntry | null {
    const tag = canonical(value, true);
    if (!tag) return null;
    const listed = byTag.get(tag);
    if (listed) return listed;
    for (const candidate of truncations(tag).slice(1)) {
      const base = byTag.get(candidate);
      if (base) {
        const region = tag.split('-').at(-1);
        return { ...base, tag, native: `${base.native} (${region})`, english: `${base.english} (${region})`, promptName: `${base.promptName} (${region})`,
          tier: 'available', guide: null, guideDepth: null, reviewed: false, regionless: false, parent: candidate, aliases: [], namedAs: [] };
      }
    }
    const regional = catalogue.entries.find((e) => e.tag.split('-')[0] === tag);
    if (regional && !tag.includes('-')) return { ...regional, tag, regionless: true, tier: 'available', guide: null, guideDepth: null, parent: regional.tag };
    if (tag === 'zh' || tag === 'yue') {
      return { tag, family: 'zh', native: '中文', english: 'Chinese', promptName: 'Chinese', aliases: [], namedAs: [], tier: 'available', guide: null, guideDepth: null,
        reviewed: false, regionless: true, parent: null, dir: 'ltr', glyphs: null, flag: '🌐', countUnit: 'characters', gendered: false };
    }
    return null;
  }

  function scopeChain(value: unknown): LocaleTag[] {
    const tag = canonical(value, true);
    const chain: LocaleTag[] = [];
    const seen = new Set<string>();
    let current: string | null = tag;
    while (current && !seen.has(current)) {
      seen.add(current);
      for (const candidate of truncations(current)) if (!chain.includes(candidate)) chain.push(candidate);
      current = entry(current)?.parent ?? null;
    }
    return chain;
  }

  const same = (a: unknown, b: unknown) => {
    const left = canonical(a, true);
    return left !== null && left === canonical(b, true);
  };

  function search(query: string, limit = 60): SearchResult[] {
    const q = fold(query);
    if (!q) return [];
    const wide = q.length >= 2 || !isAscii(q);
    const results: SearchResult[] = [];
    for (const { entry: e, fields } of searchKeys) {
      let best = 0;
      let via: (typeof fields)[number] | null = null;
      for (const f of fields) {
        let s = 0;
        if (f.key === q) s = f.name ? 100 : 95;
        else if (f.key.startsWith(q)) s = f.name ? 85 : 80;
        else if (f.key.split(' ').some((w) => w.startsWith(q))) s = f.name ? 75 : 70;
        else if (wide && f.key.includes(q)) s = 45;
        if (s > best) {
          best = s;
          via = f;
        }
      }
      if (!best || !via) continue;
      const alias = !via.name && fold(via.raw) !== fold(e.english) && via.raw !== e.tag ? via.raw : null;
      results.push({ entry: e, score: best + (e.guide ? 6 : 0) - (e.regionless ? 1 : 0), alias });
    }
    const order = new Map(catalogue.entries.map((e, i) => [e.tag, i]));
    return results.toSorted((a, b) => b.score - a.score || order.get(a.entry.tag)! - order.get(b.entry.tag)!).slice(0, limit);
  }

  function didYouMean(query: string): string | null {
    const q = fold(query);
    if (q.length < 4 || !isAscii(q)) return null;
    let best: string | null = null;
    let distance = 3;
    for (const { fields } of searchKeys) {
      for (const f of fields) {
        if (!isAscii(f.key)) continue;
        for (const word of [f.key, ...f.key.split(' ')]) {
          const d = levenshtein(q, word);
          if (d < distance) {
            distance = d;
            best = word === f.key ? f.raw : (f.raw.split(/\s+/).find((part) => fold(part) === word) ?? word);
          }
        }
      }
    }
    return distance <= 2 ? best : null;
  }

  function saidAt(text: string, index: number): { tag: LocaleTag; said: string } | null {
    const rest = text.slice(index);
    const words = WORDS.exec(rest);
    if (words) {
      const list = words[0].split(/\s+/);
      for (let size = list.length; size >= 1; size--) {
        const span = new RegExp(`^${TOKEN}${`[ \\t]+${TOKEN}`.repeat(size - 1)}`).exec(rest);
        const tag = span ? named.get(fold(span[0])) : undefined;
        if (span && tag) return { tag, said: span[0] };
      }
    }
    for (const [said, tag] of unspaced) if (rest.startsWith(said)) return { tag: named.get(fold(said)) ?? tag, said };
    return null;
  }

  /** Languages named as instructions: after "in / into / using" or 用 / 以 / 成 / 做, plus languages joined to one. */
  function namedLanguages(text: string): NamedLanguage[] {
    const hits = new Map<number, NamedLanguage>();
    const take = (start: number, found: { tag: LocaleTag; said: string }) => {
      if (!hits.has(start)) hits.set(start, { ...found, start });
      let end = start + found.said.length;
      for (let i = 0; i < 3; i++) {
        const joined = JOIN.exec(text.slice(end));
        if (!joined || !joined[0].length) break;
        const next = saidAt(text, end + joined[0].length);
        if (!next) break;
        if (!hits.has(end + joined[0].length)) hits.set(end + joined[0].length, { ...next, start: end + joined[0].length });
        end = end + joined[0].length + next.said.length;
      }
    };
    for (const m of text.matchAll(ENGLISH_TRIGGER)) {
      const found = saidAt(text, m.index! + m[0].length);
      if (found) take(m.index! + m[0].length, found);
    }
    for (const m of text.matchAll(CJK_TRIGGER)) {
      const found = saidAt(text, m.index! + m[0].length);
      if (found && !isAscii(found.said)) take(m.index! + m[0].length, found);
    }
    return [...hits.values()].toSorted((a, b) => a.start - b.start);
  }

  /** Per clause, a run of languages belongs to the channel run just before it, else just after; no channel → every channel. */
  function parseMessageLanguages(text: string): MessageLanguages {
    const result: MessageLanguages = { all: null, perPlatform: new Map() };
    for (const clause of (text || '').split(CLAUSE_SPLIT)) {
      const languages = namedLanguages(clause);
      if (!languages.length) continue;
      const events: ({ at: number; kind: 'l'; hit: NamedLanguage } | { at: number; kind: 'c'; platform: string })[] = languages.map((hit) => ({ at: hit.start, kind: 'l' as const, hit }));
      for (const [platform, pattern] of PLATFORM_WORDS) {
        const found = new RegExp(pattern.source, pattern.flags).exec(clause);
        if (found) events.push({ at: found.index, kind: 'c', platform });
      }
      events.sort((a, b) => a.at - b.at);
      if (!events.some((e) => e.kind === 'c')) {
        result.all = languages;
        continue;
      }
      const runs: { kind: 'l' | 'c'; items: typeof events; used: boolean }[] = [];
      for (const event of events) {
        const last = runs.at(-1);
        if (last && last.kind === event.kind) last.items.push(event);
        else runs.push({ kind: event.kind, items: [event], used: false });
      }
      runs.forEach((run, i) => {
        if (run.kind !== 'l') return;
        const target = runs[i - 1] && !runs[i - 1].used ? runs[i - 1] : runs[i + 1] && !runs[i + 1].used ? runs[i + 1] : null;
        if (!target) return;
        target.used = true;
        const hits = run.items.flatMap((e) => (e.kind === 'l' ? [e.hit] : []));
        for (const e of target.items) if (e.kind === 'c') result.perPlatform.set(e.platform, hits);
      });
    }
    return result;
  }

  /** A channel's languages once the message has spoken; a family name keeps picks already in it. */
  function effectiveLanguages(platform: string, current: LocaleTag[], parsed: MessageLanguages): { tag: LocaleTag; fromMessage: boolean; said?: string }[] {
    const hits = parsed.perPlatform.get(platform) ?? parsed.all;
    if (!hits) return current.map((tag) => ({ tag, fromMessage: false }));
    const out: { tag: LocaleTag; fromMessage: boolean; said?: string }[] = [];
    for (const hit of hits) {
      const family = FAMILY_SAID.has(fold(hit.said)) ? 'zh' : hit.tag;
      const fitting = entry(family)?.regionless ? current.filter((tag) => tag !== family && scopeChain(tag).includes(family)) : [];
      if (fitting.length) fitting.forEach((tag) => out.push({ tag, fromMessage: false }));
      else out.push({ tag: hit.tag, fromMessage: true, said: hit.said });
    }
    const seen = new Set<string>();
    return out.filter((item) => !seen.has(item.tag) && Boolean(seen.add(item.tag)));
  }

  return {
    catalogue,
    entries: catalogue.entries,
    canonical,
    entry,
    same,
    scopeChain,
    search,
    didYouMean,
    namedLanguages,
    parseMessageLanguages,
    effectiveLanguages,
    usualFor: (platform: string): LocaleTag | null => catalogue.usual[platform] ?? null,
    displayName: (value: unknown) => entry(value)?.native ?? (typeof value === 'string' ? value : ''),
    englishName: (value: unknown) => entry(value)?.english ?? (typeof value === 'string' ? value : ''),
    flag: (value: unknown) => entry(value)?.flag ?? '🌐'
  };
}

export type Locales = ReturnType<typeof createLocales>;
