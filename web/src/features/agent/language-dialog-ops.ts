import type { LocaleTag } from '@/lib/api/types';

/**
 * A selected drafting destination as the language dialog reads it. Today `useChannelLanguages`
 * items are `{ platform, languages }`; Stream A extends them to `{ key, platform, channelId?,
 * languages }` (one item per account). Both shapes satisfy this type.
 */
export interface LanguageSelectionItem<P extends string = string> {
  key?: string;
  platform: P;
  channelId?: string | null;
  /** null until the person picks: the destination follows what the workspace remembers. */
  languages: LocaleTag[] | null;
}

/** The slice of `useChannelLanguages` the dialog commits through (method syntax keeps it assignable from the hook). */
export interface LanguageDialogApi<P extends string = string> {
  languagesOf(item: LanguageSelectionItem<P>): LocaleTag[];
  change(target: string, index: number, tag: LocaleTag): void;
  add(target: string, tag: LocaleTag): void;
  remove(target: string, index: number): void;
  useEverywhere(tag: LocaleTag): void;
  suggestions?: { tag: LocaleTag; reason: string }[];
  settings?: { channels: Record<string, LocaleTag[]> };
}

/** Languages a destination may carry, mirroring the hook's cap. */
export const MAX_LANGUAGES = 4;

/** Stable identity for dialog state: the hook's key when it has one, else platform (+ account). */
export function stateKey(item: LanguageSelectionItem): string {
  return item.key ?? (item.channelId ? `${item.platform}:${item.channelId}` : item.platform);
}

/**
 * What `change/add/remove` are addressed by: the hook's key once Stream A lands (assumed to be the
 * first argument of those methods), the platform today.
 */
export function apiTarget(item: LanguageSelectionItem): string {
  return item.key ?? item.platform;
}

export type LanguageOp<P extends string = string> =
  | { kind: 'change'; item: LanguageSelectionItem<P>; index: number; tag: LocaleTag }
  | { kind: 'add'; item: LanguageSelectionItem<P>; tag: LocaleTag }
  | { kind: 'remove'; item: LanguageSelectionItem<P>; index: number }
  | { kind: 'everywhere'; tag: LocaleTag };

/** Dedupe and cap a staged list the way the hook will. */
export function cleanLanguages(list: readonly LocaleTag[]): LocaleTag[] {
  return Array.from(new Set(list)).slice(0, MAX_LANGUAGES);
}

/**
 * The hook calls needed to turn each destination's current languages into the staged ones. With a
 * shared language, one `useEverywhere` covers every selected destination. Ops on one destination
 * must run one per render (the hook computes each update from its own latest state), so the dialog
 * drains them sequentially rather than firing them in one handler.
 */
export function planLanguageOps<P extends string>(items: readonly LanguageSelectionItem<P>[], current: (item: LanguageSelectionItem<P>) => LocaleTag[], staged: Record<string, readonly LocaleTag[]>, shared: LocaleTag | null): LanguageOp<P>[] {
  if (shared) {
    if (!items.length) return [];
    const already = items.every((item) => {
      const list = current(item);
      return list.length === 1 && list[0] === shared;
    });
    return already ? [] : [{ kind: 'everywhere', tag: shared }];
  }
  const ops: LanguageOp<P>[] = [];
  for (const item of items) {
    const before = current(item);
    const after = cleanLanguages(staged[stateKey(item)] ?? before);
    if (!after.length) continue;
    const overlap = Math.min(before.length, after.length);
    for (let index = 0; index < overlap; index += 1) {
      if (before[index] !== after[index]) ops.push({ kind: 'change', item, index, tag: after[index] });
    }
    for (let index = overlap; index < after.length; index += 1) ops.push({ kind: 'add', item, tag: after[index] });
    for (let index = before.length - 1; index >= overlap; index -= 1) ops.push({ kind: 'remove', item, index });
  }
  return ops;
}

/** Run one planned op against the hook (call with the hook object from the current render). */
export function runLanguageOp<P extends string>(api: LanguageDialogApi<P>, op: LanguageOp<P>) {
  switch (op.kind) {
    case 'change':
      api.change(apiTarget(op.item), op.index, op.tag);
      break;
    case 'add':
      api.add(apiTarget(op.item), op.tag);
      break;
    case 'remove':
      api.remove(apiTarget(op.item), op.index);
      break;
    case 'everywhere':
      api.useEverywhere(op.tag);
      break;
  }
}
