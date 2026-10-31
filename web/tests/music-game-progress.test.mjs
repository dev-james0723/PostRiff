/** Note Garden local progress (SPEC "Progress storage"): one versioned key, nothing personal, never throws. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  STORAGE_KEY,
  defaultProgress,
  loadProgress,
  recordRun,
  resetProgress,
  saveProgress,
  withAllOpen,
  withMuted,
  withVolume
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

const DEFAULT = {
  v: 1,
  best: { 1: 0, 2: 0, 3: 0, 4: 0 },
  done: { 1: false, 2: false, 3: false, 4: false },
  allOpen: false,
  muted: false,
  volume: 'medium'
};

test('the key and the default value match the SPEC', () => {
  assert.equal(STORAGE_KEY, 'rafii.noteGarden.v1');
  assert.deepEqual(defaultProgress(), DEFAULT);
  assert.deepEqual(loadProgress(memoryStorage()), DEFAULT);
});

test('save then load round-trips, under one key only, with no names, ids or timestamps', () => {
  const storage = memoryStorage();
  const p = withVolume(withMuted(withAllOpen(recordRun(defaultProgress(), 1, 2), true), true), 'soft');
  assert.equal(saveProgress(storage, p), true);
  assert.deepEqual([...storage.data.keys()], [STORAGE_KEY]);
  assert.deepEqual(Object.keys(JSON.parse(storage.data.get(STORAGE_KEY))).sort(), ['allOpen', 'best', 'done', 'muted', 'v', 'volume']);
  assert.deepEqual(loadProgress(storage), p);
});

test('recordRun marks the level done and keeps the best stars', () => {
  let p = recordRun(defaultProgress(), 2, 3);
  p = recordRun(p, 2, 1);
  assert.equal(p.best[2], 3);
  assert.equal(p.done[2], true);
  assert.equal(p.done[3], false);
});

test('corrupt, foreign or other-version data falls back to defaults instead of crashing', () => {
  for (const raw of ['not json', '[]', 'null', '42', '{"v":2,"best":{"1":3}}', '{"best":{"1":3}}']) {
    assert.deepEqual(loadProgress(memoryStorage({ [STORAGE_KEY]: raw })), DEFAULT, raw);
  }
});

test('stored values are sanitised: unknown keys dropped, stars whole numbers 0..3, unknown volume -> medium', () => {
  const raw = JSON.stringify({ v: 1, best: { 1: 7, 2: -2, 3: 1.6, 4: 'x', 9: 3 }, done: { 1: true, 2: 'yes' }, allOpen: 1, muted: 'true', volume: 'loud', name: 'Ada' });
  assert.deepEqual(loadProgress(memoryStorage({ [STORAGE_KEY]: raw })), {
    ...DEFAULT,
    best: { 1: 3, 2: 0, 3: 1, 4: 0 },
    done: { 1: true, 2: false, 3: false, 4: false }
  });
});

test('storage that throws (private mode, quota, blocked) never breaks the game', () => {
  assert.deepEqual(loadProgress(throwing), DEFAULT);
  assert.equal(saveProgress(throwing, DEFAULT), false);
  assert.deepEqual(resetProgress(throwing, withMuted(DEFAULT, true)), withMuted(DEFAULT, true));
  assert.deepEqual(loadProgress(undefined), DEFAULT);
  assert.equal(saveProgress(undefined, DEFAULT), false);
});

test('reset deletes the key; only a non-default sound choice is written back', () => {
  const storage = memoryStorage();
  const played = recordRun(recordRun(defaultProgress(), 1, 3), 2, 2);
  saveProgress(storage, withAllOpen(played, true));
  assert.deepEqual(resetProgress(storage, withAllOpen(played, true)), DEFAULT);
  assert.equal(storage.data.has(STORAGE_KEY), false, 'key deleted');

  saveProgress(storage, withMuted(played, true));
  const after = resetProgress(storage, withVolume(withMuted(played, true), 'soft'));
  assert.deepEqual(after, { ...DEFAULT, muted: true, volume: 'soft' });
  assert.deepEqual(loadProgress(storage), after);
});
