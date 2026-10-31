/**
 * Note Garden progress (SPEC "Progress storage"): best stars, finished levels, "open all levels" and the sound
 * settings, kept only in this browser's localStorage under one versioned key. No names, IDs, timestamps or answer
 * history. Every storage call is guarded: private mode, a full quota or blocked storage means progress simply is not
 * remembered. No imports, so node's test runner loads it directly (`web/tests/music-game-progress.test.mjs`).
 */

export const STORAGE_KEY = 'rafii.noteGarden.v1';
const VERSION = 1;
const LEVELS = [1, 2, 3, 4] as const;

export type Volume = 'soft' | 'medium';
export type Progress = {
  v: number;
  best: Record<number, number>;
  done: Record<number, boolean>;
  allOpen: boolean;
  muted: boolean;
  volume: Volume;
};
type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function defaultProgress(): Progress {
  return { v: VERSION, best: { 1: 0, 2: 0, 3: 0, 4: 0 }, done: { 1: false, 2: false, 3: false, 4: false }, allOpen: false, muted: false, volume: 'medium' };
}

function sanitize(raw: unknown): Progress {
  const fresh = defaultProgress();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fresh;
  const data = raw as Record<string, unknown>;
  if (data.v !== VERSION) return fresh;
  const best = (data.best && typeof data.best === 'object' ? data.best : {}) as Record<string, unknown>;
  const done = (data.done && typeof data.done === 'object' ? data.done : {}) as Record<string, unknown>;
  for (const level of LEVELS) {
    const stars = best[level];
    // Whole stars only, never rounded up: a tampered 1.6 is 1 star.
    if (typeof stars === 'number' && Number.isFinite(stars)) fresh.best[level] = Math.min(3, Math.max(0, Math.floor(stars)));
    fresh.done[level] = done[level] === true;
  }
  fresh.allOpen = data.allOpen === true;
  fresh.muted = data.muted === true;
  fresh.volume = data.volume === 'soft' ? 'soft' : 'medium';
  return fresh;
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

export function recordRun(progress: Progress, level: number, stars: number): Progress {
  return {
    ...progress,
    best: { ...progress.best, [level]: Math.max(progress.best[level] ?? 0, stars) },
    done: { ...progress.done, [level]: true }
  };
}

export const withMuted = (progress: Progress, muted: boolean): Progress => ({ ...progress, muted });
export const withVolume = (progress: Progress, volume: Volume): Progress => ({ ...progress, volume });
export const withAllOpen = (progress: Progress, allOpen: boolean): Progress => ({ ...progress, allOpen });

/**
 * Grown-ups "Reset progress": deletes the key. A sound choice the grown-up made (muted or soft) is written back so a
 * reset never surprises a child with sound; nothing else survives.
 */
export function resetProgress(storage: StorageLike | undefined, progress: Progress): Progress {
  const next = { ...defaultProgress(), muted: progress.muted, volume: progress.volume };
  try {
    storage?.removeItem(STORAGE_KEY);
  } catch {
    // Storage blocked: nothing was remembered anyway.
  }
  if (next.muted || next.volume !== 'medium') saveProgress(storage, next);
  return next;
}
