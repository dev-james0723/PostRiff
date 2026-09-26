/**
 * The chip state machine for one composer (chat-context SPEC §11.4). Pure: a reducer plus selectors, no React and
 * relative imports only (node --test transpiles it).
 *
 *   added ─▶ preparing ─▶ uploading(p%) ─▶ checking ─▶ ready ─┬─▶ (reference) reading ─▶ read | read_failed(retry)
 *      │          │              │              │              └─▶ (post) ready
 *      └──────────┴──────────────┴──────────────┴─▶ failed(message, retry)        removed ─▶ (5 s undo) ─▶ gone
 *
 * `fields` sends only settled chips (ready, read, read failed); `blockers` are the chips still preparing, uploading
 * or checking, and send waits for them (§4.7). A removed chip stays undoable for 5 s; only when it expires does the
 * caller abort an in-flight upload (`expired`).
 */
import {
  LIMITS,
  nextSlot,
  requestFields,
  setPostRole,
  type Chip,
  type MediaRole,
  type PostRole,
  type RequestFields
} from './chips';

export const UNDO_MS = 5_000;
export const UPLOAD_STOPPED = 'Upload stopped. Try again.';

export const LIMIT_MESSAGES = {
  attachments: 'Up to 4 photos and videos per message.',
  videos: 'One video per message.',
  posts: 'Up to 3 posts per message.',
  references: 'Up to 12 items per message.'
} as const;

export interface Removed {
  chip: Chip;
  index: number;
  at: number;
}

export interface AttachmentsState {
  chips: Chip[];
  removed: Removed[];
}

export const EMPTY: AttachmentsState = { chips: [], removed: [] };

export type UploadPhase = 'preparing' | 'uploading' | 'checking';

export type AttachmentsAction =
  | { type: 'add'; chip: Chip }
  | { type: 'upload'; key: string; status: UploadPhase; progress?: number }
  | { type: 'uploaded'; key: string; id: string; meta?: Chip['meta'] }
  | { type: 'failed'; key: string; message: string }
  | { type: 'retry'; key: string }
  | { type: 'role'; key: string; role: PostRole | MediaRole }
  | { type: 'reading'; key: string }
  | { type: 'read'; key: string; note: string; milliCredits?: number }
  | { type: 'readFailed'; key: string }
  | { type: 'remove'; key: string; at: number }
  | { type: 'undo'; key?: string; at: number }
  | { type: 'expire'; at: number }
  | { type: 'clearSent'; keys: readonly string[] }
  | { type: 'restore'; chips: readonly Chip[] };

const isMedia = (chip: Pick<Chip, 'kind'>) => chip.kind === 'image' || chip.kind === 'video';

function identity(chip: Pick<Chip, 'kind' | 'id'>): string {
  return `${isMedia(chip) ? 'asset' : chip.kind}:${chip.id}`;
}

/** Why `chip` can't join `chips` (a limit message, or "duplicate"), or null when it can. */
export function refusal(chips: readonly Chip[], chip: Chip): string | null {
  // A chip still uploading has no server id yet, so it can't duplicate anything.
  if (!chip.upload || chip.upload.status === 'ready') {
    if (
      chips.some(
        (other) =>
          identity(other) === identity(chip) && (!other.upload || other.upload.status === 'ready')
      )
    )
      return 'duplicate';
  }
  if (isMedia(chip)) {
    const media = chips.filter(isMedia);
    if (media.length >= LIMITS.attachments) return LIMIT_MESSAGES.attachments;
    if (chip.kind === 'video' && media.some((other) => other.kind === 'video'))
      return LIMIT_MESSAGES.videos;
    return null;
  }
  const references = chips.filter((other) => !isMedia(other));
  if (references.length >= LIMITS.references) return LIMIT_MESSAGES.references;
  if (
    chip.kind === 'post' &&
    references.filter((other) => other.kind === 'post').length >= LIMITS.posts
  )
    return LIMIT_MESSAGES.posts;
  return null;
}

function patch(
  state: AttachmentsState,
  key: string,
  change: (chip: Chip) => Chip
): AttachmentsState {
  let changed = false;
  const chips = state.chips.map((chip) => {
    if (chip.key !== key) return chip;
    changed = true;
    return change(chip);
  });
  return changed ? { ...state, chips } : state;
}

export function reduce(state: AttachmentsState, action: AttachmentsAction): AttachmentsState {
  switch (action.type) {
    case 'add': {
      if (
        state.chips.some((chip) => chip.key === action.chip.key) ||
        refusal(state.chips, action.chip)
      )
        return state;
      const chip =
        isMedia(action.chip) && !action.chip.slot
          ? { ...action.chip, slot: nextSlot(state.chips) ?? undefined }
          : action.chip;
      return { ...state, chips: [...state.chips, chip] };
    }
    case 'upload':
      return patch(state, action.key, (chip) => ({
        ...chip,
        upload: {
          status: action.status,
          ...(action.status === 'uploading'
            ? { progress: Math.max(0, Math.min(100, Math.round(action.progress ?? 0))) }
            : {})
        }
      }));
    case 'uploaded':
      return patch(state, action.key, (chip) => ({
        ...chip,
        id: action.id,
        meta: { ...chip.meta, ...action.meta },
        upload: { status: 'ready' }
      }));
    case 'failed':
      return patch(state, action.key, (chip) => ({
        ...chip,
        upload: { status: 'failed', message: action.message }
      }));
    case 'retry':
      return patch(state, action.key, (chip) =>
        chip.upload?.status === 'failed' ? { ...chip, upload: { status: 'preparing' } } : chip
      );
    case 'role': {
      const target = state.chips.find((chip) => chip.key === action.key);
      if (!target) return state;
      if (target.kind === 'post') {
        if (action.role !== 'rework' && action.role !== 'inspire') return state;
        return { ...state, chips: setPostRole(state.chips, action.key, action.role) };
      }
      if (!isMedia(target) || (action.role !== 'post' && action.role !== 'reference')) return state;
      // A read note belongs to the asset, so switching back to Reference keeps it.
      return patch(state, action.key, (chip) => ({ ...chip, role: action.role }));
    }
    case 'reading':
      return patch(state, action.key, (chip) => ({ ...chip, read: { status: 'reading' } }));
    case 'read':
      return patch(state, action.key, (chip) => ({
        ...chip,
        read: {
          status: 'read',
          note: action.note,
          ...(action.milliCredits !== undefined ? { milliCredits: action.milliCredits } : {})
        }
      }));
    case 'readFailed':
      return patch(state, action.key, (chip) => ({ ...chip, read: { status: 'failed' } }));
    case 'remove': {
      const index = state.chips.findIndex((chip) => chip.key === action.key);
      if (index < 0) return state;
      return {
        chips: state.chips.filter((chip) => chip.key !== action.key),
        removed: [...state.removed, { chip: state.chips[index], index, at: action.at }]
      };
    }
    case 'undo': {
      const live = state.removed.filter((item) => action.at - item.at < UNDO_MS);
      const item = action.key ? live.find((entry) => entry.chip.key === action.key) : live.at(-1);
      if (!item || refusal(state.chips, item.chip)) return state;
      const chips = [...state.chips];
      chips.splice(Math.min(item.index, chips.length), 0, item.chip);
      return { chips, removed: state.removed.filter((entry) => entry !== item) };
    }
    case 'expire': {
      const removed = state.removed.filter((item) => action.at - item.at < UNDO_MS);
      return removed.length === state.removed.length ? state : { ...state, removed };
    }
    case 'clearSent': {
      const sent = new Set(action.keys);
      return { ...state, chips: state.chips.filter((chip) => !sent.has(chip.key)) };
    }
    case 'restore': {
      let next: AttachmentsState = { chips: [], removed: [] };
      for (const chip of action.chips) next = reduce(next, { type: 'add', chip });
      return next;
    }
  }
}

/** Removed chips whose undo window has passed: abort their pending uploads (a committed asset only detaches). */
export function expired(state: AttachmentsState, at: number): Chip[] {
  return state.removed.filter((item) => at - item.at >= UNDO_MS).map((item) => item.chip);
}

/** Chips that settled and can go out: uploaded (or never uploaded), not failed. */
export function settled(chips: readonly Chip[]): Chip[] {
  return chips.filter((chip) => !chip.upload || chip.upload.status === 'ready');
}

/** The exact request fields (SPEC §5.1): identical bytes for the estimate, the quote and the turn. */
export function fields(state: AttachmentsState, opts: { imageGeneration: boolean }): RequestFields {
  return requestFields(settled(state.chips), opts);
}

/** The keys `fields` sent, so a successful send clears only those (§4.7). */
export function sentKeys(state: AttachmentsState, opts: { imageGeneration: boolean }): string[] {
  return opts.imageGeneration ? [] : settled(state.chips).map((chip) => chip.key);
}

export function blockers(state: AttachmentsState): Chip[] {
  return state.chips.filter(
    (chip) =>
      chip.upload &&
      (chip.upload.status === 'preparing' ||
        chip.upload.status === 'uploading' ||
        chip.upload.status === 'checking')
  );
}

/** The send button's waiting line, or null (SPEC §13 "Send states"). */
export function blockerMessage(state: AttachmentsState): string | null {
  const count = blockers(state).length;
  if (!count) return null;
  return count === 1
    ? 'Waiting for 1 upload to finish.'
    : `Waiting for ${count} uploads to finish.`;
}

export function readingMessage(state: AttachmentsState): string | null {
  const count = state.chips.filter((chip) => chip.read?.status === 'reading').length;
  if (!count) return null;
  return count === 1 ? 'Reading 1 photo…' : `Reading ${count} photos…`;
}

// --- persistence (SPEC §11.5) -------------------------------------------------------------------------------------------

export interface SavedChip {
  kind: Chip['kind'];
  id: string;
  label: string;
  role?: PostRole | MediaRole;
  slot?: Chip['slot'];
  /** It was still uploading when saved: it comes back failed, never ready. */
  stopped?: true;
}

/** What survives a reload: settled chips as they are, unfinished uploads as `stopped`; failed ones are left out. */
export function toSaved(chips: readonly Chip[]): SavedChip[] {
  return chips.flatMap((chip): SavedChip[] => {
    if (chip.upload?.status === 'failed') return [];
    const unfinished = Boolean(chip.upload && chip.upload.status !== 'ready');
    return [
      {
        kind: chip.kind,
        id: chip.id,
        label: chip.label,
        ...(chip.role ? { role: chip.role } : {}),
        ...(chip.slot ? { slot: chip.slot } : {}),
        ...(unfinished ? { stopped: true as const } : {})
      }
    ];
  });
}

/**
 * Saved chips back as chips, re-checked against what the snapshot still offers (`available`: kind+id keys of
 * existing, ready, visible items — `allPickerItems`). Missing ones are dropped and returned for the live region;
 * unfinished uploads come back failed with "Upload stopped. Try again."
 */
export function fromSaved(
  saved: readonly SavedChip[],
  available: ReadonlySet<string>,
  keyFor: (chip: SavedChip, index: number) => string
): { chips: Chip[]; dropped: SavedChip[] } {
  const chips: Chip[] = [];
  const dropped: SavedChip[] = [];
  saved.forEach((item, index) => {
    const base: Chip = {
      key: keyFor(item, index),
      kind: item.kind,
      id: item.id,
      label: item.label,
      ...(item.role ? { role: item.role } : {}),
      ...(item.slot ? { slot: item.slot } : {})
    };
    if (item.stopped) {
      chips.push({ ...base, upload: { status: 'failed', message: UPLOAD_STOPPED } });
      return;
    }
    if (!available.has(`${item.kind}:${item.id}`)) {
      dropped.push(item);
      return;
    }
    chips.push(base);
  });
  return { chips, dropped };
}
