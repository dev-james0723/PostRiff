'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import type { LibraryFilters, LibraryScope, LibrarySearchRequest, SearchCoverage, SearchHit, SearchResponse } from '@/lib/api/library-intelligence-types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * Library intelligence availability. The status route says which features are switched on; while it is missing
 * (`library_capability_unavailable`), switched off or failing, the deterministic Library is the whole product.
 */
export function useLibraryIntelligence() {
  const { api, workspaceId } = useWorkspaceApi();
  const status = useQuery({
    queryKey: ['library-intelligence-status', workspaceId],
    queryFn: () => api.libraryIntelligenceStatus(workspaceId),
    enabled: Boolean(workspaceId),
    retry: false,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false
  });
  const flags = status.data?.flags ?? {};
  return {
    status,
    /** The intelligence routes answer at all (per-item reads may still be unavailable). */
    reachable: status.isSuccess,
    retrieval: status.isSuccess && flags.retrieval === true,
    flags
  };
}

/** The route or feature is not in this build (or switched off), as opposed to a request that failed this time. */
export function isCapabilityUnavailable(error: unknown) {
  return error instanceof ApiError && ((error.status === 503 && error.code === 'library_capability_unavailable') || error.status === 404 || error.status === 501);
}

export interface LibrarySearchState {
  /** True while a query is waiting for its answer. */
  loading: boolean;
  hits: SearchHit[];
  coverage: SearchCoverage | null;
  facets: SearchResponse['facets'] | null;
  warnings: string[];
  nextCursor: string | null;
  /** The request failed for this query; the page falls back to the deterministic list. */
  failed: string | null;
  /** The intelligence search is not in this build or is switched off: stop trying this session. */
  unavailable: boolean;
  queryId: string | null;
  loadingMore: boolean;
  totalHits: SearchResponse['totalHits'] | null;
}

const EMPTY: LibrarySearchState = { loading: false, hits: [], coverage: null, facets: null, warnings: [], nextCursor: null, failed: null, unavailable: false, queryId: null, loadingMore: false, totalHits: null };

/**
 * Exact and semantic search over the entire permitted scope (UI spec §5). Each new request aborts the obsolete one
 * through its AbortController, so a slow answer for an old query never replaces a newer one. An exact query needs no
 * conversation: the text box is the whole interface.
 */
export function useLibrarySearch({
  enabled,
  query,
  scope,
  filters,
  debounceMs = 220
}: {
  enabled: boolean;
  query: string;
  scope: LibraryScope;
  filters: LibraryFilters;
  debounceMs?: number;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [state, setState] = useState<LibrarySearchState>(EMPTY);
  const unavailable = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const request: LibrarySearchRequest = { query: query.trim(), scope, filters, purpose: 'browse', limit: 60 };
  const requestKey = JSON.stringify(request);

  useEffect(() => {
    controller.current?.abort();
    if (!enabled || unavailable.current || !request.query) {
      setState((current) => ({ ...EMPTY, unavailable: current.unavailable }));
      return;
    }
    const abort = new AbortController();
    controller.current = abort;
    setState((current) => ({ ...current, loading: true, failed: null }));
    const timer = window.setTimeout(() => {
      api
        .librarySearch(workspaceId, JSON.parse(requestKey) as LibrarySearchRequest, abort.signal)
        .then((response) => {
          if (abort.signal.aborted) return;
          setState({
            loading: false,
            loadingMore: false,
            hits: response.hits,
            coverage: response.coverage,
            facets: response.facets ?? null,
            warnings: response.warnings ?? [],
            nextCursor: response.nextCursor,
            failed: null,
            unavailable: false,
            queryId: response.queryId,
            totalHits: response.totalHits ?? null
          });
        })
        .catch((error: unknown) => {
          if (abort.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')) return;
          if (isCapabilityUnavailable(error)) {
            unavailable.current = true;
            setState({ ...EMPTY, unavailable: true });
            return;
          }
          setState({ ...EMPTY, failed: error instanceof Error ? error.message : 'Search didn’t finish.' });
        });
    }, debounceMs);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
    // requestKey carries the query, scope and filters.
  }, [api, workspaceId, enabled, requestKey, request.query, debounceMs]);

  const loadMore = useCallback(() => {
    const cursor = state.nextCursor;
    if (!cursor || state.loadingMore) return;
    const abort = new AbortController();
    controller.current = abort;
    setState((current) => ({ ...current, loadingMore: true }));
    api
      .librarySearch(workspaceId, { ...(JSON.parse(requestKey) as LibrarySearchRequest), cursor }, abort.signal)
      .then((response) => {
        if (abort.signal.aborted) return;
        setState((current) => ({
          ...current,
          loadingMore: false,
          hits: [...current.hits, ...response.hits],
          coverage: response.coverage,
          facets: response.facets ?? current.facets,
          warnings: response.warnings ?? current.warnings,
          nextCursor: response.nextCursor
        }));
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        // An expired cursor or a revision change asks for a fresh search rather than a silent gap.
        setState((current) => ({ ...current, loadingMore: false, nextCursor: null, warnings: [...current.warnings, error instanceof ApiError && error.status === 409 ? 'The Library changed. Search again to see the rest.' : 'More results couldn’t load. Search again to retry.'] }));
      });
  }, [api, workspaceId, requestKey, state.nextCursor, state.loadingMore]);

  useEffect(() => () => controller.current?.abort(), []);

  return { ...state, active: enabled && !state.unavailable && Boolean(request.query), loadMore };
}

export interface HitGroup {
  assetId: string;
  first: SearchHit;
  hits: SearchHit[];
}

/** One result per item, in rank order, carrying its passages and moments. */
export function groupHits(hits: readonly SearchHit[]): HitGroup[] {
  const groups = new Map<string, HitGroup>();
  for (const hit of hits) {
    const key = hit.assetRef.assetId;
    const group = groups.get(key);
    if (group) group.hits.push(hit);
    else groups.set(key, { assetId: key, first: hit, hits: [hit] });
  }
  return [...groups.values()];
}
