/** D11: Sentry starts on confirmed (committed) non-play routes only; one import, at most one init, no deadline. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSentryStarter } from '../src/lib/sentry-starter.ts';

function harness({ enabled = true, failLoad = false } = {}) {
  const state = { path: '/play/note-garden', loads: 0, inits: [], resolveLoad: null };
  const starter = createSentryStarter({
    enabled,
    isPlay: (p) => p === '/play' || p.startsWith('/play/'),
    currentPath: () => state.path,
    load: () => {
      state.loads++;
      return new Promise((resolve, reject) => {
        state.resolveLoad = () => (failLoad ? reject(new Error('chunk failed')) : resolve({ sdk: true }));
      });
    },
    init: (mod) => state.inits.push({ mod, path: state.path })
  });
  return { state, starter };
}
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

test('a visit that boots on /play does not even load the SDK', async () => {
  const { state, starter } = harness();
  assert.equal(await starter.ensure('/play/note-garden'), null);
  assert.equal(state.loads, 0);
});

test('/play boot -> /pricing commit -> back to /play before the import resolves: no init; next non-play commit: exactly one', async () => {
  const { state, starter } = harness();
  state.path = '/pricing';
  const first = starter.ensure('/pricing');
  state.path = '/play/note-garden'; // the child went back before the chunk arrived
  const again = starter.ensure('/play/note-garden');
  state.resolveLoad();
  await first;
  await again;
  assert.deepEqual(state.inits, [], 'never initialised while the page shows /play');
  state.path = '/pricing';
  await starter.ensure('/pricing');
  await starter.ensure('/pricing');
  await starter.ensure('/');
  assert.equal(state.loads, 1, 'one import');
  assert.deepEqual(state.inits.map((i) => i.path), ['/pricing'], 'exactly one init, on a non-play page');
  assert.equal(starter.started(), true);
});

test('a slow transition has no deadline: /play shown for a long time, then /pricing commits -> init', async () => {
  const { state, starter } = harness();
  for (let i = 0; i < 1000; i++) await Promise.resolve(); // far longer than the old 300-frame cut-off, nothing called
  state.path = '/pricing';
  const pending = starter.ensure('/pricing');
  state.resolveLoad();
  await pending;
  assert.equal(state.inits.length, 1);
});

test('the committed path is re-checked against the current location after the import', async () => {
  const { state, starter } = harness();
  state.path = '/play/note-garden'; // location still on /play although a non-play commit was reported
  const pending = starter.ensure('/pricing');
  state.resolveLoad();
  await pending;
  assert.deepEqual(state.inits, [], 'stays pending');
  state.path = '/pricing';
  await starter.ensure('/pricing');
  assert.equal(state.inits.length, 1);
});

test('booting on a normal page initialises straight away, once', async () => {
  const { state, starter } = harness();
  state.path = '/pricing';
  const a = starter.ensure('/pricing');
  const b = starter.ensure('/pricing');
  state.resolveLoad();
  await Promise.all([a, b]);
  await flush();
  assert.equal(state.loads, 1);
  assert.equal(state.inits.length, 1);
});

test('disabled (no DSN or switched off): never loads; a failed chunk load stays silent', async () => {
  const off = harness({ enabled: false });
  off.state.path = '/pricing';
  assert.equal(await off.starter.ensure('/pricing'), null);
  assert.equal(off.state.loads, 0);
  const broken = harness({ failLoad: true });
  broken.state.path = '/pricing';
  const pending = broken.starter.ensure('/pricing');
  broken.state.resolveLoad();
  assert.equal(await pending, null);
  assert.equal(broken.state.inits.length, 0);
});
