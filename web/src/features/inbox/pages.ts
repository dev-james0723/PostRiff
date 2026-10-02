/**
 * Inbox paging rules, pure (`node --test web/tests/inbox-pages.test.mjs`).
 *
 * The first page of conversations refreshes on its own (a sync, an approved reply); older pages are loaded on demand.
 * A refreshed first page must never drop what the person already loaded: conversations never leave the Inbox, so one
 * that is no longer on the first page slid down (newer comments arrived) and is kept with the older pages.
 */

/** The older items to keep after the first page changed from `previousFirst` to `nextFirst`. */
export function retainLoaded<T>(previousFirst: readonly T[], nextFirst: readonly T[], older: readonly T[], key: (item: T) => string): T[] {
  const onFirst = new Set(nextFirst.map(key));
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of [...previousFirst, ...older]) {
    const id = key(item);
    if (onFirst.has(id) || seen.has(id)) continue;
    seen.add(id);
    out.push(item);
  }
  return out;
}

/** Pages loaded, one after another, while looking for a linked conversation before asking to keep looking. */
export const SEEK_PAGES = 6;

/**
 * Where a search for a conversation that isn't loaded yet stands (a follow-up's Reply, a notification link):
 * `seeking` while more pages can be loaded within this search, `more` once this search's pages are used up, `missing`
 * when everything is loaded and it isn't there, `idle` when there is nothing to look for.
 */
export function seekState({ wanted, found, loaded, cursor, pages }: {
  wanted: string | null;
  found: boolean;
  loaded: boolean;
  cursor: string | null;
  pages: number;
}): 'idle' | 'seeking' | 'more' | 'missing' {
  if (!wanted || found || !loaded) return 'idle';
  if (!cursor) return 'missing';
  return pages < SEEK_PAGES ? 'seeking' : 'more';
}
