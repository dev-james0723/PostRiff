import type { OwnedPost, OwnedPostPage } from '@/lib/api/types';

export const MAX_PREVIEW_PAGES = 4;
export const MAX_SELECTED_POSTS = 50;

/** Append only a continuous, bounded page chain for one authenticated account. */
export function appendOwnedPage(pages: OwnedPostPage[], next: OwnedPostPage, cursor?: string): OwnedPostPage[] {
  if (!cursor) {
    if (next.coverage?.startedFromBeginning === false) throw new Error('This is not the beginning of the retrieved history. Reload it.');
    return [next];
  }
  const previous = pages.at(-1);
  if (!previous || previous.nextCursor !== cursor || pages.length >= MAX_PREVIEW_PAGES) throw new Error('The page chain ended or reached its preview limit.');
  if (previous.connectionId !== next.connectionId || previous.providerAccountId !== next.providerAccountId) throw new Error('The connected account changed. Reload the posts.');
  if (next.nextCursor && (next.nextCursor === cursor || pages.some((page) => page.nextCursor === next.nextCursor))) throw new Error('The provider repeated a cursor. Further coverage cannot be confirmed.');
  return [...pages, next];
}

export function loadedPosts(pages: OwnedPostPage[]): OwnedPost[] {
  const posts = new Map<string, OwnedPost>();
  for (const page of pages) for (const post of page.posts) posts.set(post.id, post);
  return [...posts.values()];
}

/** One encrypted receipt per selected page; never send edits as provider-authored text. */
export function selectedReceipts(pages: OwnedPostPage[], selected: string[], now = Date.now() / 1000): { receipt: string; postIds: string[] }[] {
  if (!selected.length || selected.length > MAX_SELECTED_POSTS || new Set(selected).size !== selected.length) throw new Error('Choose between 1 and 50 distinct posts.');
  const available = new Map<string, OwnedPostPage>();
  for (const page of pages) for (const post of page.posts) available.set(post.id, page);
  const groups = new Map<OwnedPostPage, string[]>();
  for (const id of selected) {
    const page = available.get(id);
    if (!page || page.expiresAt <= now) throw new Error('A selected post is unavailable or its preview expired. Reload before retaining it.');
    groups.set(page, [...(groups.get(page) ?? []), id]);
  }
  if (groups.size > MAX_PREVIEW_PAGES) throw new Error('Retain from at most four verified pages at once.');
  return [...groups].map(([page, postIds]) => ({ receipt: page.receipt, postIds }));
}

export function coverageSummary(pages: OwnedPostPage[]): string {
  const posts = loadedPosts(pages);
  const dates = posts.map((post) => Date.parse(post.publishedAt)).filter(Number.isFinite).toSorted((a, b) => a - b);
  const format = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
  const range = dates.length ? ` from ${format.format(dates[0])}–${format.format(dates.at(-1)!)}` : '';
  const loaded = posts.length ? `Loaded ${posts.length} posts${range}.` : 'No eligible captions in the retrieved pages.';
  const complete = pages.length > 0 && pages[0].coverage?.startedFromBeginning === true && pages.at(-1)?.coverage?.endReached === true;
  const coverage = complete ? 'Pagination reached the end of the API-visible results; excluded or inaccessible material is not counted.' : 'Coverage is incomplete; search includes only loaded posts.';
  const undated = posts.length - dates.length;
  return `${loaded} ${coverage}${undated ? ` ${undated} posts have no verified date.` : ''}`;
}
