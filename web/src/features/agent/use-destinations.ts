'use client';

/**
 * The composer's committed destination selection, keyed by connection id (Rafii v9 §3, D4).
 *
 * Channel Bloom stages its own changes and hands the result to `commit` on Done; this hook holds
 * what the composer actually drafts for: the selected account ids, the platforms drafted without
 * an account (the existing "drafts only" behaviour) and the folder context the selection came
 * from, snapshotted at commit time so later folder edits never rewrite a draft's label.
 *
 * Persisted for the browser session per workspace (`sessionStorage`, never the URL) so a page
 * change does not lose the choice. Nothing here is a fact about the workspace: folders live in
 * the snapshot, and the ids are cleaned against the live accounts on every read.
 */
import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { cleanSelection, selectionLabel, type FolderAccount, type FolderContext } from '@/lib/channels/folders';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export interface DestinationSelection {
  /** `Phase2State.channels[].id` values the composer drafts for. */
  selected: string[];
  /** Platforms drafted without an account. */
  platformOnly: string[];
  /** The folders the selection came from, or null when it was picked account by account. */
  context: FolderContext | null;
}

export interface DestinationCommit {
  accountIds: string[];
  context?: FolderContext | null;
  /** Omitted: the platform-only choices stay as they are. */
  platformOnly?: string[];
}

const EMPTY: DestinationSelection = Object.freeze({ selected: [], platformOnly: [], context: null }) as DestinationSelection;
const PREFIX = 'rafii.destinations.';
const EVENT = 'rafii-destinations-change';
const cache = new Map<string, DestinationSelection>();

export const destinationsStorageKey = (workspaceId: string) => `${PREFIX}${workspaceId}`;

const strings = (value: unknown): string[] => (Array.isArray(value) ? Array.from(new Set(value.filter((v): v is string => typeof v === 'string' && v.length > 0))) : []);

function decodeContext(value: unknown): FolderContext | null {
  if (!value || typeof value !== 'object' || !Array.isArray((value as { sources?: unknown }).sources)) return null;
  const sources = ((value as { sources: unknown[] }).sources ?? []).flatMap((s) => {
    if (!s || typeof s !== 'object') return [];
    const { id, name, accountIds } = s as { id?: unknown; name?: unknown; accountIds?: unknown };
    return typeof id === 'string' && typeof name === 'string' ? [{ id, name, accountIds: strings(accountIds) }] : [];
  });
  return sources.length ? { sources } : null;
}

/** Tolerant decoding: anything malformed reads as an empty selection rather than a broken page. */
export function decodeDestinations(raw: string | null | undefined): DestinationSelection {
  if (!raw) return EMPTY;
  try {
    const data = JSON.parse(raw) as { version?: unknown; selected?: unknown; platformOnly?: unknown; context?: unknown };
    if (!data || typeof data !== 'object' || data.version !== 1) return EMPTY;
    const selected = strings(data.selected);
    const platformOnly = strings(data.platformOnly);
    const context = decodeContext(data.context);
    return selected.length || platformOnly.length || context ? { selected, platformOnly, context } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function read(workspaceId: string): DestinationSelection {
  if (!workspaceId || typeof window === 'undefined') return EMPTY;
  const cached = cache.get(workspaceId);
  if (cached) return cached;
  let value = EMPTY;
  try {
    value = decodeDestinations(window.sessionStorage.getItem(destinationsStorageKey(workspaceId)));
  } catch {
    value = EMPTY;
  }
  cache.set(workspaceId, value);
  return value;
}

function write(workspaceId: string, value: DestinationSelection) {
  const empty = !value.selected.length && !value.platformOnly.length && !value.context;
  cache.set(workspaceId, empty ? EMPTY : value);
  try {
    if (empty) window.sessionStorage.removeItem(destinationsStorageKey(workspaceId));
    else window.sessionStorage.setItem(destinationsStorageKey(workspaceId), JSON.stringify({ version: 1, ...value }));
  } catch {
    /* storage blocked: the choice lasts for this page */
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void) {
  window.addEventListener(EVENT, callback);
  return () => window.removeEventListener(EVENT, callback);
}

/**
 * `accounts` (from `toFolderAccounts(state.phase2.channels)`) cleans the stored ids against the
 * live connections; without it the ids are returned as stored.
 */
export function useDestinations(accounts?: FolderAccount[]) {
  const { workspaceId } = useWorkspaceApi();
  const stored = useSyncExternalStore(subscribe, () => read(workspaceId), () => EMPTY);
  const selected = useMemo(() => (accounts ? cleanSelection(stored.selected, accounts) : stored.selected), [accounts, stored.selected]);

  const commit = useCallback(
    (next: DestinationCommit) => {
      const current = read(workspaceId);
      write(workspaceId, {
        selected: strings(next.accountIds),
        platformOnly: next.platformOnly ? strings(next.platformOnly) : current.platformOnly,
        context: next.context === undefined ? current.context : (next.context ?? null)
      });
    },
    [workspaceId]
  );

  const setPlatformOnly = useCallback(
    (platforms: string[]) => {
      const current = read(workspaceId);
      write(workspaceId, { ...current, platformOnly: strings(platforms) });
    },
    [workspaceId]
  );

  const clear = useCallback(() => write(workspaceId, EMPTY), [workspaceId]);

  return {
    /** Connection ids, cleaned against `accounts` when given. */
    selected,
    /** Platforms drafted without an account. */
    platformOnly: stored.platformOnly,
    /** The folder context captured on Done. */
    context: stored.context,
    /** What Channel Bloom's `onCommit` delivers: `{ accountIds, context }`. */
    commit,
    setPlatformOnly,
    clear,
    /** "Festival", "Festival, customized", "2 folders", "3 accounts" or "No accounts". */
    summary: selectionLabel(selected, stored.context)
  };
}

export type Destinations = ReturnType<typeof useDestinations>;
