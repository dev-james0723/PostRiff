'use client';

/**
 * Server results for a typed picker query (chat-context SPEC §4.3, §5.9): `workspace.search` through
 * `GET /site-agent/search`, debounced 250 ms, only for at least one Han/Kana/Hangul character or two Latin characters.
 * Local results (the snapshot) show at once; server results merge in by id and win; an error keeps the local ones.
 */
import { useEffect, useMemo, useState } from 'react';

import type { PickerSearchResult } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

import { mergeResults, wantsServer, type PickerCategory } from './matcher';
import { CATEGORY_ORDER, type PickerItem } from './picker-items';

export const SEARCH_DEBOUNCE_MS = 250;
export const LEGACY_SERVER_CATEGORIES: readonly PickerCategory[] = [
  'posts',
  'templates',
  'accounts',
  'folders',
  'sources',
  'library'
];

export function serverCategories(
  categories?: readonly PickerCategory[]
): PickerCategory[] {
  return (categories ?? LEGACY_SERVER_CATEGORIES).filter((category) =>
    LEGACY_SERVER_CATEGORIES.includes(category)
  );
}

/** The server's groups flattened in the list's order, keeping only the categories asked for. */
export function serverItems(
  result: PickerSearchResult | null | undefined,
  categories?: readonly PickerCategory[]
): PickerItem[] {
  if (!result?.categories) return [];
  const wanted = categories?.length
    ? CATEGORY_ORDER.filter((category) => categories.includes(category))
    : CATEGORY_ORDER;
  return wanted.flatMap((category) => (result.categories[category] ?? []) as PickerItem[]);
}

/** The request key for a query, or '' when the query stays local (too short, or searching is off). */
export function searchKey(
  query: string,
  enabled: boolean,
  categories?: readonly PickerCategory[]
): string {
  const supported = serverCategories(categories);
  return enabled && supported.length > 0 && wantsServer(query)
    ? JSON.stringify([query, supported])
    : '';
}

export function usePickerSearch(
  query: string,
  local: readonly PickerItem[],
  opts: { enabled: boolean; categories?: readonly PickerCategory[] }
): PickerItem[] {
  const { api, workspaceId } = useWorkspaceApi();
  const key = searchKey(query, opts.enabled, opts.categories);
  const [server, setServer] = useState<{ key: string; items: PickerItem[] | null } | null>(null);

  useEffect(() => {
    if (!key) return;
    let alive = true;
    const [text, categories] = JSON.parse(key) as [string, PickerCategory[]];
    const timer = setTimeout(() => {
      api.siteAgentSearch(workspaceId, text, categories).then(
        (result) => {
          if (alive) setServer({ key, items: serverItems(result, categories) });
        },
        () => {
          // Degrade to local results; the list never shows an error for a typeahead.
          if (alive) setServer({ key, items: null });
        }
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [api, workspaceId, key]);

  const fromServer = server && server.key === key ? server.items : null;
  return useMemo(
    () => (key ? mergeResults(local, fromServer) : [...local]),
    [key, local, fromServer]
  );
}
