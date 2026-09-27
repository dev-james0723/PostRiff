import type { SnapshotSource } from '@/lib/api/types';

const GENERIC_TITLES = new Set(['pasted source', 'source note', 'untitled source']);
const TITLE_LIMIT = 72;

function compact(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function shortened(value: string) {
  const clean = compact(value);
  return clean.length > TITLE_LIMIT ? `${clean.slice(0, TITLE_LIMIT - 1).trimEnd()}…` : clean;
}

/**
 * Sources created only to bind a Home request to its run remain in the workspace for provenance,
 * but they are not reusable Context Pocket material unless the person explicitly saves them again.
 */
export function isReusableContextSource(source: SnapshotSource) {
  return source.active && source.kind !== 'voice_sample' && source.origin?.kind !== 'quick_start';
}

export function pocketSources(sources: SnapshotSource[] | undefined) {
  return (sources ?? []).filter(isReusableContextSource);
}

/**
 * Older quick-start sources used generic titles such as "Pasted source". Keep their IDs/provenance,
 * but show enough of the actual source to distinguish them instead of rendering duplicate labels.
 */
export function pocketSourceTitle(source: SnapshotSource) {
  const title = compact(source.title ?? '');
  if (title && !GENERIC_TITLES.has(title.toLocaleLowerCase('en-US'))) return title;

  const text = shortened(source.text ?? '');
  if (text) return text;
  if (source.origin?.host) return source.origin.host;

  if (source.kind === 'idea') return 'Saved idea';
  if (source.kind === 'link') return 'Saved link';
  if (source.kind === 'document') return 'Saved file';
  return 'Saved source';
}
