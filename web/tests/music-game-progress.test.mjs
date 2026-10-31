import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PROGRESS_VERSION,
  STORAGE_KEY,
  defaultProgress,
  loadProgress,
  recordStars,
  resetProgress,
  saveProgress,
  withMuted
} from '../src/lib/music-game/progress.ts';

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k)
  };
}

const throwing = {
  getItem() { throw new Error('SecurityError'); },
  setItem() { throw new Error('QuotaExceededError'); },
  removeItem() { throw new Error('SecurityError'); }
};

test('a fresh device starts with no stars and sound on', () => {
  assert.deepEqual(loadProgress(memoryStorage()), { version: PROGRESS_VERSION, stars: {}, muted: false });
  assert.deepEqual(defaultProgress(), { version: PROGRESS_VERSION, stars: {}, muted: false });
});

test('progress survives a save/load round trip under one versioned key', () => {
  const storage = memoryStorage();
  const progress = withMuted(recordStars(defaultProgress(), 'pitch', 2), true);
  assert.equal(saveProgress(storage, progress), true);
  assert.deepEqual([...storage.data.keys()], [STORAGE_KEY]);
  assert.deepEqual(loadProgress(storage), progress);
});

test('recordStars keeps the best score and never lowers it', () => {
  let p = recordStars(defaultProgress(), 'staff', 3);
  p = recordStars(p, 'staff', 1);
  assert.equal(p.stars.staff, 3);
});

test('corrupt, foreign or older-version data falls back to a clean start instead of crashing', () => {
  for (const raw of ['not json', '[]', 'null', '{"version":0,"stars":{"pitch":3}}', '{"version":99}']) {
    assert.deepEqual(loadProgress(memoryStorage({ [STORAGE_KEY]: raw })), defaultProgress(), raw);
  }
});

test('stored values are sanitised: unknown levels dropped, stars clamped to whole 0..3', () => {
  const raw = JSON.stringify({ version: PROGRESS_VERSION, stars: { pitch: 7, staff: -2, beats: 1.6, motion: 'x', secret: 3 }, muted: 'yes', name: 'Ada' });
  const loaded = loadProgress(memoryStorage({ [STORAGE_KEY]: raw }));
  assert.deepEqual(loaded, { version: PROGRESS_VERSION, stars: { pitch: 3, beats: 1 }, muted: false });
});

test('storage that throws (private mode, quota, blocked) never breaks the game', () => {
  assert.deepEqual(loadProgress(throwing), defaultProgress());
  assert.equal(saveProgress(throwing, defaultProgress()), false);
  assert.deepEqual(resetProgress(throwing, withMuted(defaultProgress(), true)), withMuted(defaultProgress(), true));
  assert.deepEqual(loadProgress(undefined), defaultProgress());
  assert.equal(saveProgress(undefined, defaultProgress()), false);
});

test('reset clears stars but keeps the sound setting', () => {
  const storage = memoryStorage();
  const progress = withMuted(recordStars(recordStars(defaultProgress(), 'pitch', 3), 'staff', 2), true);
  saveProgress(storage, progress);
  const after = resetProgress(storage, progress);
  assert.deepEqual(after, { version: PROGRESS_VERSION, stars: {}, muted: true });
  assert.deepEqual(loadProgress(storage), after);
});
