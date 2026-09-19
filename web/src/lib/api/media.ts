import type { QueryCache } from '@tanstack/react-query';

/** Media URLs belong to the shared query, so unmounting one thumbnail never breaks another. */
export function releaseCachedMedia(cache: QueryCache, revoke = (url: string) => URL.revokeObjectURL(url)) {
  const urls = new Map<string, string>();
  return cache.subscribe((event) => {
    const query = event.query;
    if (query.queryKey[0] !== 'media') return;
    const previous = urls.get(query.queryHash);
    const data = query.state.data;
    const next = event.type !== 'removed' && typeof data === 'string' && data.startsWith('blob:') ? data : undefined;
    if (next === previous) return;
    if (next) urls.set(query.queryHash, next);
    else urls.delete(query.queryHash);
    // Let observers finish the current render when a refetch replaces the URL.
    if (previous) setTimeout(() => revoke(previous), 0);
  });
}
