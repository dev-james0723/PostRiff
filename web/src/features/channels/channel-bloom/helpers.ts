/**
 * Pure helpers for Channel Bloom (Rafii v9 folders). No React, no DOM: everything here is
 * exercised by `channel-bloom.test.cjs`. Selection maths stays in `lib/channels/folders.ts`;
 * this module turns those readings into the dialog's words and layout decisions.
 */
import type { ChannelFolder, Phase2State } from '@/lib/api/types';
import { selectionState, type FolderAccount, type FolderSelection, type FolderSymbol } from '@/lib/channels/folders';

export type Phase2Channel = Phase2State['channels'][number];

/** The picker's view of `state.phase2.channels`: a connection counts as connected until it is revoked. */
export function toFolderAccounts(channels: readonly Phase2Channel[] | null | undefined): FolderAccount[] {
  return (channels ?? []).map((c) => ({ id: c.id, platform: c.platform, account: c.account, state: c.displayState, connected: c.revoked !== true }));
}

export type Draftable = (platform: string) => boolean;

export const draftableFrom = (platforms: readonly string[]): Draftable => {
  const set = new Set(platforms);
  return (platform) => set.has(platform);
};

/** `ready` can be a destination; `missing` has no live connection; `unavailable` is connected on a platform drafting cannot write for yet. */
export type MemberStatus = 'ready' | 'missing' | 'unavailable';

export function memberStatus(id: string, accounts: readonly FolderAccount[], draftable: Draftable): MemberStatus {
  const account = accounts.find((a) => a.id === id);
  if (!account || !account.connected) return 'missing';
  return draftable(account.platform) ? 'ready' : 'unavailable';
}

/**
 * Accounts as destination candidates. Only a connected account on a draftable platform can be
 * picked, so for selection maths an unavailable account reads as not connected; the display
 * keeps the two apart through `memberStatus`.
 */
export function pickableAccounts(accounts: readonly FolderAccount[], draftable: Draftable): FolderAccount[] {
  return accounts.map((a) => ({ ...a, connected: a.connected && draftable(a.platform) }));
}

export interface FolderReading extends FolderSelection {
  /** Members that are connected but cannot be drafted for yet. Never counted as selectable. */
  unavailable: string[];
}

export function readFolder(folder: Pick<ChannelFolder, 'accountIds'>, selected: readonly string[], accounts: readonly FolderAccount[], draftable: Draftable): FolderReading {
  const info = selectionState(folder, selected, pickableAccounts(accounts, draftable));
  const missing = info.missing.filter((id) => memberStatus(id, accounts, draftable) === 'missing');
  const unavailable = info.missing.filter((id) => memberStatus(id, accounts, draftable) === 'unavailable');
  return { ...info, missing, unavailable };
}

export const plural = (n: number, noun: string, plural = `${noun}s`) => `${n} ${n === 1 ? noun : plural}`;

/** "3 accounts" (none selected), "2 of 3 selected", "3 selected", or the empty reading. */
export function folderStateText(info: Pick<FolderReading, 'state' | 'count' | 'total'>): string {
  if (info.state === 'empty') return 'No accounts to select';
  if (info.state === 'all') return `${info.total} selected`;
  if (info.state === 'mixed') return `${info.count} of ${info.total} selected`;
  return plural(info.total, 'account');
}

/** "1 no longer connected · 2 not available for drafting", or null when every member is selectable. */
export function membersNote(info: Pick<FolderReading, 'missing' | 'unavailable'>): string | null {
  const parts: string[] = [];
  if (info.missing.length) parts.push(`${info.missing.length} no longer connected`);
  if (info.unavailable.length) parts.push(`${info.unavailable.length} not available for drafting`);
  return parts.length ? parts.join(' · ') : null;
}

/**
 * Where the inspector goes on a shelf with `columns` cards per row: after the last card of the
 * row that holds the inspected card, or after the last card when that row is incomplete.
 * Returns -1 when nothing is inspected or the shelf is empty.
 */
export function inspectorSlot(index: number, count: number, columns = 2): number {
  if (index < 0 || count <= 0 || index >= count) return -1;
  return Math.min(Math.floor(index / columns) * columns + columns - 1, count - 1);
}

export const draftReason = (platform: string) => `Drafting is not available for ${platform} yet`;
export const MISSING_REASON = 'No longer connected';

export const doneLabel = (count: number) => `Done · ${plural(count, 'account')} selected`;

export const toggleFeedback = (removing: boolean, changed: number) => `${removing ? 'Removed' : 'Added'} ${plural(changed, 'account')}. Overlapping folders updated.`;

export const SYMBOL_LABELS: Record<FolderSymbol, string> = { folder: 'Folder', spark: 'Spark', music: 'Music', briefcase: 'Work', heart: 'Personal', globe: 'Global' };

/** Which accounts a folder shows on its shelf card: the first three members with a known account. */
export function peekAccounts(folder: Pick<ChannelFolder, 'accountIds'>, accounts: readonly FolderAccount[], limit = 3): { shown: FolderAccount[]; more: number } {
  const known = folder.accountIds.map((id) => accounts.find((a) => a.id === id)).filter((a): a is FolderAccount => Boolean(a));
  return { shown: known.slice(0, limit), more: Math.max(0, known.length - limit) };
}
