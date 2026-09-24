/**
 * Pure selection helpers for the Content Library: search, category and app-fit filters, pairing
 * routes and the composer intent hint. Filters and views only change what is represented; they never
 * change the staged choice (DNA v8 §13.1, §13.5, §13.6).
 */
import { CATEGORIES, PAIRINGS_BY_ID, PLATFORMS, TAXONOMY, categoryInfo, platformInfo, type Dimension, type Pairing, type TaxonomyItem } from './taxonomy';

export const ALL = 'all';

export interface LibraryFilters {
  query: string;
  /** Category id for the current dimension, or `all`. */
  category: string;
  /** Suggested-app-fit platform id, or `all`. */
  platform: string;
}

export const EMPTY_FILTERS: LibraryFilters = { query: '', category: ALL, platform: ALL };

/** Taxonomy platform id → channel directory slug (`web/src/config/channels.ts`, `ChannelIcon`). */
export const PLATFORM_SLUGS: Record<string, string> = {
  instagram: 'instagram',
  linkedin: 'linkedin',
  threads: 'threads',
  x: 'x',
  facebook: 'facebook',
  red: 'xiaohongshu'
};

const PLATFORM_ALIASES: Record<string, string> = {
  instagram: 'instagram',
  linkedin: 'linkedin',
  threads: 'threads',
  x: 'x',
  twitter: 'x',
  facebook: 'facebook',
  red: 'red',
  xiaohongshu: 'red',
  rednote: 'red',
  小紅書: 'red',
  小红书: 'red'
};

/** Resolves an app platform name (`LinkedIn`, `Xiaohongshu`, a slug) to the taxonomy's platform id, or null. */
export function platformFitId(value: string | null | undefined): string | null {
  if (!value) return null;
  const key = value.trim().toLowerCase().replace(/\s+/g, '');
  const id = PLATFORM_ALIASES[key];
  return id && platformInfo(id) ? id : null;
}

/** The app-fit options: every taxonomy platform, or only those the caller can draft for, in taxonomy order. */
export function platformOptions(platformsForFit?: string[]): { value: string; label: string }[] {
  const wanted = platformsForFit ? new Set(platformsForFit.map(platformFitId).filter((id): id is string => id !== null)) : null;
  const list = wanted ? PLATFORMS.filter((platform) => wanted.has(platform.id)) : PLATFORMS;
  return [{ value: ALL, label: 'All app fits' }, ...list.map((platform) => ({ value: platform.id, label: platform.label }))];
}

export function itemsOf(dimension: Dimension): TaxonomyItem[] {
  return TAXONOMY.filter((item) => item.dimension === dimension);
}

/** Category options with live counts (DNA §22.4): `All editorial types · 31`, then each category. */
export function categoryOptions(dimension: Dimension): { value: string; label: string; count: number }[] {
  const items = itemsOf(dimension);
  const all = { value: ALL, label: dimension === 'editorial' ? 'All editorial types' : 'All native formats', count: items.length };
  return [all, ...CATEGORIES[dimension].map((category) => ({ value: category.id, label: category.label, count: items.filter((item) => item.category === category.id).length }))];
}

export function categoryTitle(dimension: Dimension, category: string): string {
  if (category === ALL) return dimension === 'editorial' ? 'All editorial types' : 'All native formats';
  return categoryInfo(dimension, category)?.label ?? category;
}

/** Everything a search term can hit: title, id, description, family, tags and the category label. */
export function searchText(item: TaxonomyItem): string {
  return [item.title, item.id, item.description, item.family, ...item.tags, categoryInfo(item.dimension, item.category)?.label ?? ''].join(' ').toLowerCase();
}

export function matchesFilters(item: TaxonomyItem, filters: LibraryFilters): boolean {
  if (filters.category !== ALL && item.category !== filters.category) return false;
  if (filters.platform !== ALL && !item.platforms.includes(filters.platform)) return false;
  const query = filters.query.trim().toLowerCase();
  return !query || searchText(item).includes(query);
}

export function filterItems(dimension: Dimension, filters: LibraryFilters): TaxonomyItem[] {
  return itemsOf(dimension).filter((item) => matchesFilters(item, filters));
}

/** Count and wording for the applied-filter line; the search term is not a filter. */
export function activeFilters(dimension: Dimension, filters: LibraryFilters): { count: number; summary: string } {
  const parts: string[] = [];
  if (filters.category !== ALL) parts.push(categoryTitle(dimension, filters.category));
  if (filters.platform !== ALL) parts.push(platformInfo(filters.platform)?.label ?? filters.platform);
  return { count: parts.length, summary: parts.join(' · ') };
}

/** An item's pairing routes, narrowed to the app-fit filter, at most `limit` (the prototype shows two). */
export function pairingsFor(item: TaxonomyItem, platform: string = ALL, limit = 2): Pairing[] {
  const routes = item.pairings.map((id) => PAIRINGS_BY_ID[id]).filter((pairing): pairing is Pairing => Boolean(pairing));
  const narrowed = platform === ALL ? routes : routes.filter((pairing) => pairing.platforms.includes(platform));
  return narrowed.slice(0, limit);
}

export type ComposerIntent = 'post' | 'thread' | 'carousel' | 'video';

/** Composer intent hint for a native format (the prototype's `legacyFormat`); a UI hint, not a backend value. */
export function intentFor(nativeId: string | null | undefined): ComposerIntent {
  if (nativeId === 'thread') return 'thread';
  if (nativeId === 'carousel' || nativeId === 'document') return 'carousel';
  if (nativeId === 'short_vertical_video' || nativeId === 'long_video' || nativeId === 'livestream') return 'video';
  return 'post';
}
