/**
 * Channel folder rules (Rafii v9): pure functions over connection ids. A folder never owns an
 * account; selection is one deduplicated set of connection ids shared by every folder. The server
 * (`src/postriff_phase2/channel_folders.py`) enforces the same limits and messages.
 */
import type { ChannelFolder } from '@/lib/api/types';

export const FOLDER_NAME_MAX = 40;
export const FOLDER_MAX = 50;
export const FOLDER_SHELF = 4;
export const FOLDER_SYMBOLS = ['folder', 'spark', 'music', 'briefcase', 'heart', 'globe'] as const;
export type FolderSymbol = (typeof FOLDER_SYMBOLS)[number];

/** A connected account as the picker sees it. `connected` is false when the connection no longer exists. */
export interface FolderAccount {
  id: string;
  platform: string;
  account: string;
  state?: string;
  connected: boolean;
}

export type SelectionState = 'empty' | 'none' | 'mixed' | 'all';

export interface FolderSelection {
  state: SelectionState;
  /** Selected members that are still connected. */
  count: number;
  /** Members that are still connected. */
  total: number;
  /** Members whose connection has gone; they never count as selectable. */
  missing: string[];
}

export interface FolderSource {
  id: string;
  name: string;
  accountIds: string[];
}

export interface FolderContext {
  sources: FolderSource[];
}

const connectedIds = (accounts: FolderAccount[]) => new Set(accounts.filter((a) => a.connected).map((a) => a.id));

/** Valid, deduplicated connection ids in the order given. */
export function cleanSelection(ids: readonly string[] | null | undefined, accounts: FolderAccount[]): string[] {
  const valid = connectedIds(accounts);
  return Array.from(new Set(Array.isArray(ids) ? ids : [])).filter((id) => valid.has(id));
}

export function selectionState(folder: Pick<ChannelFolder, 'accountIds'>, selected: readonly string[], accounts: FolderAccount[]): FolderSelection {
  const valid = connectedIds(accounts);
  const members = folder.accountIds.filter((id) => valid.has(id));
  const missing = folder.accountIds.filter((id) => !valid.has(id));
  const set = new Set(selected);
  const count = members.filter((id) => set.has(id)).length;
  return { state: members.length === 0 ? 'empty' : count === 0 ? 'none' : count === members.length ? 'all' : 'mixed', count, total: members.length, missing };
}

/** Tap none/some → add every valid member; tap all → remove them. Unrelated selections stay. */
export function toggleGroup(selected: readonly string[], folder: Pick<ChannelFolder, 'accountIds'>, accounts: FolderAccount[]): string[] {
  const current = cleanSelection(selected, accounts);
  const members = cleanSelection(folder.accountIds, accounts);
  return selectionState(folder, current, accounts).state === 'all' ? current.filter((id) => !members.includes(id)) : cleanSelection([...current, ...members], accounts);
}

export function normalizeName(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();
}

export interface FolderInput {
  id?: string;
  name: string;
  symbol?: string;
  pinned?: boolean;
  accountIds: string[];
}

/** Mirrors the server rules; throws an Error whose message can be shown next to the field. */
export function validateFolder(input: FolderInput, folders: ChannelFolder[], accounts: FolderAccount[], keepIds: readonly string[] = []): FolderInput & { symbol: FolderSymbol; pinned: boolean } {
  const name = normalizeName(input.name);
  if (!name) throw new Error('Give your folder a name.');
  if (name.length > FOLDER_NAME_MAX) throw new Error(`Keep the folder name within ${FOLDER_NAME_MAX} characters.`);
  if (folders.some((f) => f.id !== input.id && f.name.toLocaleLowerCase() === name.toLocaleLowerCase())) throw new Error('That folder name is already in use. Try another.');
  const valid = connectedIds(accounts);
  const keep = new Set(keepIds);
  const accountIds = Array.from(new Set(input.accountIds)).filter((id) => valid.has(id) || keep.has(id));
  if (accountIds.filter((id) => valid.has(id)).length === 0) throw new Error('Choose at least one connected account.');
  if (!input.id && folders.length >= FOLDER_MAX) throw new Error(`This workspace already has ${FOLDER_MAX} folders. Delete one before adding another.`);
  const symbol = (FOLDER_SYMBOLS as readonly string[]).includes(input.symbol ?? '') ? (input.symbol as FolderSymbol) : 'folder';
  return { ...input, name, accountIds, symbol, pinned: input.pinned === true };
}

export function copyName(name: string, folders: ChannelFolder[]): string {
  const names = new Set(folders.map((f) => f.name.toLocaleLowerCase()));
  const base = name.slice(0, FOLDER_NAME_MAX - 8);
  let label = `${base} copy`;
  let n = 2;
  while (names.has(label.toLocaleLowerCase())) label = `${base} copy ${n++}`;
  return label;
}

/** Search matches the folder name, its members' platforms and handles. */
export function folderMatches(folder: ChannelFolder, query: string, accounts: FolderAccount[]): boolean {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const parts = [folder.name];
  for (const id of folder.accountIds) {
    const a = byId.get(id);
    if (a) parts.push(a.platform, a.account);
  }
  return parts.join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

export function accountMatches(account: FolderAccount, query: string): boolean {
  return `${account.platform} ${account.account}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

/** Pinned first, stable within each section; the compact shelf shows at most four unless searching or expanded. */
export function visibleFolders(folders: ChannelFolder[], query: string, all: boolean, accounts: FolderAccount[], limit = FOLDER_SHELF): ChannelFolder[] {
  const sorted = folders
    .map((f, i) => ({ f, i }))
    .toSorted((a, b) => Number(Boolean(b.f.pinned)) - Number(Boolean(a.f.pinned)) || a.i - b.i)
    .map((x) => x.f);
  const filtered = query.trim() ? sorted.filter((f) => folderMatches(f, query, accounts)) : sorted;
  return all || query.trim() ? filtered : filtered.slice(0, limit);
}

/** Whether Move up/down applies: only within the folder's pinned or unpinned section. */
export function canMove(folders: ChannelFolder[], id: string, delta: -1 | 1): boolean {
  const ordered = visibleFolders(folders, '', true, [], Infinity);
  const index = ordered.findIndex((f) => f.id === id);
  const target = index + delta;
  return index >= 0 && target >= 0 && target < ordered.length && Boolean(ordered[target].pinned) === Boolean(ordered[index].pinned);
}

/**
 * The folders a selection came from, captured at commit time so later edits never rewrite a
 * draft's label. Members without a live connection are left out of the snapshot: they were never
 * selectable, so they must not make a full selection read as "customized".
 */
export function snapshotContext(folders: ChannelFolder[], ids: readonly string[], accounts?: FolderAccount[]): FolderContext {
  const valid = accounts ? connectedIds(accounts) : null;
  return {
    sources: Array.from(new Set(ids)).flatMap((id) => {
      const f = folders.find((x) => x.id === id);
      return f ? [{ id: f.id, name: f.name, accountIds: f.accountIds.filter((member) => !valid || valid.has(member)) }] : [];
    })
  };
}

/** "Festival", "Festival, customized", "2 folders", "3 accounts" or "No accounts". */
export function selectionLabel(selected: readonly string[], context: FolderContext | null | undefined): string {
  if (!selected.length) return 'No accounts';
  const sources = context?.sources ?? [];
  if (!sources.length) return `${selected.length} ${selected.length === 1 ? 'account' : 'accounts'}`;
  const base = Array.from(new Set(sources.flatMap((f) => f.accountIds)));
  const same = base.length === selected.length && base.every((id) => selected.includes(id));
  return (sources.length === 1 ? sources[0].name : `${sources.length} folders`) + (same ? '' : ', customized');
}
