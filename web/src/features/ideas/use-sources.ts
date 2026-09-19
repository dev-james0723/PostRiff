'use client';

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { SnapshotSource, SnapshotState, SnapshotVariant, SourcePolicy } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/*
 * Narrow local types over the workspace snapshot. The presenter sends each source row whole
 * (`domain._present` deep-copies state), so these fields reach the browser even though the
 * shared `SnapshotSource` type does not declare them yet.
 */

export interface SourceFact {
  id: string;
  text: string;
  approved: boolean;
  locator?: string;
}

/** Where a web-research page came from (`ideas._research`). */
export interface SourceOrigin {
  kind: string;
  url?: string;
  host?: string;
  query?: string;
  published?: string;
  fetchedAt?: string;
}

export interface UseApproval {
  actor?: string;
  at?: number | string;
  factsDigest?: string;
}

export interface IdeaSource extends Omit<SnapshotSource, 'facts'> {
  facts: SourceFact[];
  createdAt?: string | number;
  withdrawnAt?: string | number;
  unknowns?: string[];
  origin?: SourceOrigin | null;
  useApprovals?: UseApproval[];
}

export function ideaSources(state: SnapshotState | undefined): IdeaSource[] {
  return (state?.sources ?? []).map((source) => {
    const row = source as IdeaSource;
    return { ...row, facts: Array.isArray(row.facts) ? row.facts : [] };
  });
}

/** Domain rows store ISO-8601 strings; hosted rows may store epoch seconds. Returns epoch seconds. */
export function toEpoch(value: string | number | null | undefined): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value) {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed / 1000;
  }
  return null;
}

export const isWeb = (source: IdeaSource) => source.origin?.kind === 'web_research';

/* ---------- filters ---------- */

export type FilterId = 'all' | 'ideas' | 'text' | 'links' | 'web' | 'withdrawn';

export const FILTERS: { id: FilterId; label: string; empty: string; match: (source: IdeaSource) => boolean }[] = [
  { id: 'all', label: 'All', empty: 'Nothing here yet.', match: (s) => s.active },
  { id: 'ideas', label: 'Ideas', empty: 'No ideas yet.', match: (s) => s.active && s.kind === 'idea' },
  { id: 'text', label: 'Text & files', empty: 'No pasted text or files yet.', match: (s) => s.active && !isWeb(s) && ['text', 'document', 'sample'].includes(s.kind) },
  { id: 'links', label: 'Links', empty: 'No links yet.', match: (s) => s.active && s.kind === 'link' },
  { id: 'web', label: 'From the web', empty: 'No pages from web research yet.', match: (s) => s.active && isWeb(s) },
  { id: 'withdrawn', label: 'Withdrawn', empty: 'Nothing has been withdrawn.', match: (s) => !s.active }
];

/** Newest first; rows without a creation time keep their stored order at the end. */
export function sortSources(sources: IdeaSource[]) {
  return sources
    .map((source, index) => ({ source, index, at: toEpoch(source.createdAt) ?? 0 }))
    .toSorted((a, b) => b.at - a.at || b.index - a.index)
    .map((row) => row.source);
}

/* ---------- labels ---------- */

export const KIND_LABEL: Record<string, string> = { idea: 'Idea', text: 'Text', document: 'File', link: 'Link', sample: 'Sample' };

export function kindLabel(source: IdeaSource) {
  return isWeb(source) ? 'Web page' : (KIND_LABEL[source.kind] ?? source.kind);
}

export const POLICIES: { id: SourcePolicy; label: string; badge: string; note: string }[] = [
  { id: 'public_quote', label: 'Quote it', badge: 'Quotable', note: 'Your own words. Drafts may quote them publicly.' },
  { id: 'rewrite_approval', label: 'Rewrite, then approve use', badge: 'Rewrite · approve use', note: 'Never quoted. Drafts rewrite it, and you approve public use before scheduling.' },
  { id: 'internal_reference', label: 'Internal only', badge: 'Internal only', note: 'Kept for internal summaries; left out of public drafts.' },
  { id: 'prohibited', label: 'Do not use', badge: 'Do not use', note: 'Kept here, left out of every draft.' }
];

export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/* ---------- drafts that use a source ---------- */

export function variantsUsing(state: SnapshotState | undefined, sourceId: string): SnapshotVariant[] {
  return (state?.variants ?? []).filter((variant) => (variant.sourceIds ?? []).includes(sourceId));
}

/** `retract_source` marks every variant that cites the source; the ones not already blocked are the new blocks. */
export function wouldBlock(state: SnapshotState | undefined, sourceId: string) {
  return variantsUsing(state, sourceId).filter((variant) => !variant.blockedByRetraction).length;
}

/* ---------- public-use approval ---------- */

/**
 * The server's `source_policy.facts_digest`: SHA-256 of `json.dumps([{id, text}…], sort_keys=True,
 * separators=(",", ":"), ensure_ascii=False)` over the approved facts. `JSON.stringify` of `{id, text}`
 * objects produces the same bytes (keys already sorted, same escapes). The server re-checks the digest
 * on `source_use_approve`, so a mismatch can only ever refuse an approval, never grant one.
 */
export async function factsDigest(facts: SourceFact[]): Promise<string | null> {
  if (typeof crypto === 'undefined' || !crypto.subtle) return null;
  const approved = facts.filter((fact) => fact.approved).map((fact) => ({ id: fact.id, text: fact.text }));
  const bytes = new TextEncoder().encode(JSON.stringify(approved));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** `true`/`false` once computed; `undefined` while hashing or where the browser cannot hash. */
export type UseState = boolean | undefined;

/** Whether each source's current approved facts carry a public-use approval (`source_policy.use_approved`). */
export function useUseApprovals(sources: IdeaSource[]) {
  const [result, setResult] = useState<Record<string, UseState>>({});
  const signature = useMemo(
    () =>
      JSON.stringify(
        sources
          .filter((s) => s.active && s.sourcePolicy === 'rewrite_approval')
          .map((s) => [s.id, s.facts.filter((f) => f.approved).map((f) => [f.id, f.text]), (s.useApprovals ?? []).map((u) => u.factsDigest)])
      ),
    [sources]
  );
  useEffect(() => {
    let disposed = false;
    const rows = JSON.parse(signature) as [string, [string, string][], (string | undefined)[]][];
    void Promise.all(
      rows.map(async ([id, approved, digests]) => {
        const current = await factsDigest(approved.map(([factId, text]) => ({ id: factId, text, approved: true })));
        return [id, current === null ? undefined : digests.includes(current)] as const;
      })
    ).then((pairs) => {
      if (!disposed) setResult(Object.fromEntries(pairs));
    });
    return () => {
      disposed = true;
    };
  }, [signature]);
  return result;
}

/* ---------- errors ---------- */

/** Toasts the server's own message; a revision conflict reloads the snapshot and keeps whatever was typed. */
export function useActError() {
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  return useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 409) {
        void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        if (/changed/i.test(err.message)) {
          toast.error('This workspace changed in another tab. It has been reloaded; what you typed is kept.');
          return;
        }
      }
      toast.error(err instanceof ApiError ? err.message : fallback);
    },
    [client, workspaceId]
  );
}

/* ---------- layout ---------- */

function subscribeMedia(query: string) {
  return (notify: () => void) => {
    const list = window.matchMedia(query);
    list.addEventListener('change', notify);
    return () => list.removeEventListener('change', notify);
  };
}

/** `null` until the browser answers, so nothing that depends on the width renders during hydration. */
export function useMedia(query: string): boolean | null {
  const subscribe = useMemo(() => subscribeMedia(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => null
  );
}

/** Drafts are written in 繁體中文 when the text is CJK, the same detection the API and Home use. */
export const detectLanguage = (text: string) => (/[一-鿿]/.test(text) ? '繁體中文' : 'English');

export const LINK_PATTERN = /^https?:\/\/\S+$/;

export function hostOf(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}
