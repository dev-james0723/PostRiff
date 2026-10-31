/**
 * Note Garden progress: best stars per level and the sound setting, kept only in this browser's localStorage.
 * No names, accounts or anything personal. Every storage call is guarded: private mode, a full quota or blocked
 * storage simply means progress is not remembered. Type-only import, so node's test runner loads it directly.
 */
import type { LevelId } from './curriculum';

export const STORAGE_KEY = 'rafii.noteGarden.progress';
export const PROGRESS_VERSION = 1;

export type Progress = { version: number; stars: Partial<Record<LevelId, number>>; muted: boolean };
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const LEVEL_IDS: LevelId[] = ['pitch', 'staff', 'beats', 'motion'];

export function defaultProgress(): Progress {
  return { version: PROGRESS_VERSION, stars: {}, muted: false };
}

function sanitize(raw: unknown): Progress {
  const fresh = defaultProgress();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fresh;
  const data = raw as { version?: unknown; stars?: unknown; muted?: unknown };
  if (data.version !== PROGRESS_VERSION) return fresh;
  const stars: Progress['stars'] = {};
  if (data.stars && typeof data.stars === 'object') {
    for (const id of LEVEL_IDS) {
      const value = (data.stars as Record<string, unknown>)[id];
      if (typeof value !== 'number' || !Number.isFinite(value)) continue;
      const clamped = Math.min(3, Math.max(0, Math.floor(value)));
      if (clamped > 0) stars[id] = clamped;
    }
  }
  return { version: PROGRESS_VERSION, stars, muted: data.muted === true };
}

export function loadProgress(storage: StorageLike | undefined): Progress {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    return raw ? sanitize(JSON.parse(raw)) : defaultProgress();
  } catch {
    return defaultProgress();
  }
}

export function saveProgress(storage: StorageLike | undefined, progress: Progress): boolean {
  if (!storage) return false;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(progress));
    return true;
  } catch {
    return false;
  }
}

export function recordStars(progress: Progress, level: LevelId, stars: number): Progress {
  const best = Math.max(progress.stars[level] ?? 0, stars);
  return { ...progress, stars: { ...progress.stars, [level]: best } };
}

export function withMuted(progress: Progress, muted: boolean): Progress {
  return { ...progress, muted };
}

/** Clears every star but keeps the sound setting, then stores the result. */
export function resetProgress(storage: StorageLike | undefined, progress: Progress): Progress {
  const next = withMuted(defaultProgress(), progress.muted);
  saveProgress(storage, next);
  return next;
}
