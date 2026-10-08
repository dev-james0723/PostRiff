'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { parseAsArrayOf, parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import {
  DEFAULT_LIBRARY_STATE,
  LIBRARY_DENSITIES,
  LIBRARY_KINDS,
  LIBRARY_SCOPES,
  LIBRARY_SORTS,
  LIBRARY_USAGE,
  LIBRARY_VIEW_MODES,
  isSafeId,
  safeQuery,
  sanitizeIds,
  type LibraryUrlState
} from '@/lib/library/url-state';

/**
 * Library navigation state in the address (UI spec §5, A051). `replace` keeps typing out of the history stack; going to
 * a draft and coming back restores the same query, scope, filters, sort, view, density, selection and open item.
 * View mode and density are also remembered per viewer (a convenience only; the address wins when it has them).
 */
const PARAMS = {
  q: parseAsString.withDefault(''),
  scope: parseAsStringLiteral(LIBRARY_SCOPES).withDefault(DEFAULT_LIBRARY_STATE.scope),
  collection: parseAsString.withDefault(''),
  use: parseAsStringLiteral(LIBRARY_USAGE).withDefault(DEFAULT_LIBRARY_STATE.use),
  kind: parseAsStringLiteral(LIBRARY_KINDS).withDefault(DEFAULT_LIBRARY_STATE.kind),
  tag: parseAsString.withDefault(''),
  sort: parseAsStringLiteral(LIBRARY_SORTS).withDefault(DEFAULT_LIBRARY_STATE.sort),
  mode: parseAsStringLiteral(LIBRARY_VIEW_MODES).withDefault(DEFAULT_LIBRARY_STATE.mode),
  density: parseAsStringLiteral(LIBRARY_DENSITIES).withDefault(DEFAULT_LIBRARY_STATE.density),
  sel: parseAsArrayOf(parseAsString).withDefault([]),
  asset: parseAsString.withDefault('')
};

const VIEW_KEY = 'rafii-library-view';

function readViewPreference(): Partial<Pick<LibraryUrlState, 'mode' | 'density'>> {
  try {
    const raw = window.localStorage.getItem(VIEW_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as { mode?: unknown; density?: unknown };
    return {
      ...((LIBRARY_VIEW_MODES as readonly unknown[]).includes(parsed.mode) ? { mode: parsed.mode as LibraryUrlState['mode'] } : {}),
      ...((LIBRARY_DENSITIES as readonly unknown[]).includes(parsed.density) ? { density: parsed.density as LibraryUrlState['density'] } : {})
    };
  } catch {
    return {};
  }
}

function writeViewPreference(mode: LibraryUrlState['mode'], density: LibraryUrlState['density']) {
  try {
    window.localStorage.setItem(VIEW_KEY, JSON.stringify({ mode, density }));
  } catch {
    /* private mode or blocked storage: the address still carries the view */
  }
}

export function useLibraryUrlState() {
  const [raw, setRaw] = useQueryStates(PARAMS, { history: 'replace', scroll: false });

  const state: LibraryUrlState = useMemo(
    () => ({
      q: safeQuery(raw.q),
      scope: raw.scope,
      collection: isSafeId(raw.collection) ? raw.collection : '',
      use: raw.use,
      kind: raw.kind,
      tag: raw.tag.slice(0, 80),
      sort: raw.sort,
      mode: raw.mode,
      density: raw.density,
      sel: sanitizeIds(raw.sel),
      asset: isSafeId(raw.asset) ? raw.asset : ''
    }),
    [raw]
  );

  const update = useCallback(
    (patch: Partial<LibraryUrlState>) => {
      const next: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(patch)) {
        if (key === 'q') next.q = safeQuery(value) || null;
        else if (key === 'sel') {
          const ids = sanitizeIds(value);
          next.sel = ids.length ? ids : null;
        } else if (key === 'collection' || key === 'asset') next[key] = isSafeId(value) ? value : null;
        else if (key === 'tag') next.tag = typeof value === 'string' && value ? value.slice(0, 80) : null;
        else next[key] = value === DEFAULT_LIBRARY_STATE[key as keyof LibraryUrlState] ? null : value;
      }
      void setRaw(next as Parameters<typeof setRaw>[0]);
    },
    [setRaw]
  );

  // The remembered view applies once, only when the address does not already say.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const preference = readViewPreference();
    const patch: Partial<LibraryUrlState> = {};
    if (raw.mode === DEFAULT_LIBRARY_STATE.mode && preference.mode && preference.mode !== raw.mode) patch.mode = preference.mode;
    if (raw.density === DEFAULT_LIBRARY_STATE.density && preference.density && preference.density !== raw.density) patch.density = preference.density;
    if (Object.keys(patch).length) update(patch);
  }, [raw.mode, raw.density, update]);

  useEffect(() => {
    if (restored.current) writeViewPreference(state.mode, state.density);
  }, [state.mode, state.density]);

  return { state, update };
}
