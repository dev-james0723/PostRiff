/**
 * Reads platform export files in the browser. A file is recognised by what it contains first and by its name
 * second; a file with a known name and a layout nobody has seen gives zero posts and a note instead of a guess.
 * Nothing here uploads, fetches or throws.
 */
import { facebookLayout, looksLikeFacebook, parseFacebook } from './facebook';
import { instagramLayout, looksLikeInstagram, parseInstagram } from './instagram';
import { looksLikeLinkedIn, parseLinkedIn } from './linkedin';
import { looksLikeMastodon, parseMastodon } from './mastodon';
import { emptyExport } from './meta';
import { parseJson } from './text';
import { looksLikeThreads, parseThreads, THREADS_LAYOUT } from './threads';
import { combineNotes, parseX, xSection } from './x';
import type { CombinedExport, ExportFile, ExportItem, ExportProvider, ParsedExport } from './types';

/** The post files of each export, by name. A folder pick opens these and nothing else. */
const POST_FILES: [RegExp, ExportProvider][] = [
  [/(^|\/)posts_\d+\.json$/i, 'instagram'],
  [/(^|\/)your_posts[a-z_]*_\d+\.json$/i, 'facebook'],
  [/(^|\/)threads_and_replies\.json$/i, 'threads'],
  [/(^|\/)(tweets?|note-tweet|community-tweet)(-part\d+)?\.js$/i, 'x'],
  [/(^|\/)shares\.csv$/i, 'linkedin'],
  [/(^|\/)outbox\.json$/i, 'mastodon']
];

const normalise = (name: string) => name.replace(/\\/g, '/');

function providerByName(name: string): ExportProvider | null {
  return POST_FILES.find(([pattern]) => pattern.test(normalise(name)))?.[1] ?? null;
}

export function isPostFile(name: string): boolean {
  return providerByName(name) !== null;
}

/** What a picked file is, from its extension alone, before any of it is read. */
export function fileKind(name: string): 'text' | 'html' | 'archive' | 'other' {
  const extension = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase() ?? '';
  if (['json', 'js', 'csv'].includes(extension)) return 'text';
  if (['html', 'htm'].includes(extension)) return 'html';
  if (['zip', 'tar', 'gz', 'tgz', '7z', 'rar'].includes(extension)) return 'archive';
  return 'other';
}

type Inspection = { provider: ExportProvider; layout: string; parse: () => ParsedExport };

function inspect(file: ExportFile): Inspection | null {
  const name = normalise(file.name);
  const section = xSection(file.text);
  if (section === 'other') return null;
  if (section) return { provider: 'x', layout: section, parse: () => parseX(file.text) };
  if (looksLikeLinkedIn(file.text)) return { provider: 'linkedin', layout: 'shares', parse: () => parseLinkedIn(file.text) };

  const json = parseJson(file.text);
  if (looksLikeMastodon(json)) return { provider: 'mastodon', layout: 'outbox', parse: () => parseMastodon(json) };
  if (looksLikeThreads(json)) return { provider: 'threads', layout: THREADS_LAYOUT, parse: () => parseThreads(json) };
  if (looksLikeInstagram(json)) {
    const layout = instagramLayout(name);
    return { provider: 'instagram', layout, parse: () => parseInstagram(json, layout) };
  }
  if (looksLikeFacebook(json)) {
    const layout = facebookLayout(name);
    return { provider: 'facebook', layout, parse: () => parseFacebook(json, layout) };
  }

  const named = providerByName(name);
  if (!named) return null;
  const note = json === undefined && !/\.csv$/i.test(name) ? 'not_json' : 'unknown_shape';
  return { provider: named, layout: 'unknown', parse: () => emptyExport(named, 'unknown', [note]) };
}

/** Which platform's post file this is and which layout generation, or `null` when it is not an export post file. */
export function detectExport(file: ExportFile): { provider: ExportProvider; layout: string } | null {
  const found = inspect(file);
  return found ? { provider: found.provider, layout: found.layout } : null;
}

export function parseExport(file: ExportFile): ParsedExport | null {
  return inspect(file)?.parse() ?? null;
}

/** One result per platform: counts summed, one record per id (the first file wins), and an X note joined to its shortened post. */
export function combineExports(parsed: ParsedExport[]): CombinedExport[] {
  const groups = new Map<ExportProvider, CombinedExport>();
  const seen = new Map<ExportProvider, Set<string>>();
  for (const part of parsed) {
    const group = groups.get(part.provider) ?? { ...emptyExport(part.provider, part.layout), files: 0 };
    const ids = seen.get(part.provider) ?? new Set<string>();
    groups.set(part.provider, group);
    seen.set(part.provider, ids);
    group.files++;
    if (group.layout !== part.layout) group.layout = 'mixed';
    group.skipped.unsupported += part.skipped.unsupported;
    group.skipped.empty += part.skipped.empty;
    group.local.notPublic += part.local.notPublic;
    group.local.reposts += part.local.reposts;
    for (const note of part.notes) if (!group.notes.includes(note)) group.notes.push(note);
    for (const item of part.items) {
      if (ids.has(item.externalId)) continue;
      ids.add(item.externalId);
      group.items.push(item);
    }
  }
  return [...groups.values()].map((group) => (group.provider === 'x' ? { ...group, items: combineNotes(group.items) } : group));
}

/** Oldest and newest post time in a set of records, for the summary shown before anything is sent. */
export function itemRange(items: ExportItem[]): { oldest: string; newest: string } | null {
  let oldest = '';
  let newest = '';
  for (const item of items) {
    if (!item.publishedAt) continue;
    if (!oldest || item.publishedAt < oldest) oldest = item.publishedAt;
    if (!newest || item.publishedAt > newest) newest = item.publishedAt;
  }
  return oldest ? { oldest, newest } : null;
}

export type { CombinedExport, ExportFile, ExportItem, ExportNote, ExportProvider, ParsedExport } from './types';
