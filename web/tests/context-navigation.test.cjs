const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(relative) {
  const file = path.join(__dirname, '..', 'src', relative);
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, { fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const markers = load('features/context-navigation/markers.ts');
const media = load('lib/media/now-playing.ts');

test('thread map clusters 1001 turns without dropping exact marker identities', () => {
  const items = Array.from({ length: 1001 }, (_, index) => ({ kind: 'user_request', messageId: `m-${index}`, seq: index + 1, excerpt: `Turn ${index}`, at: index }));
  const groups = markers.clusterNavigation(items);
  assert.ok(groups.length <= 36);
  assert.deepEqual(groups.flat().map(markers.navigationId), items.map((item) => item.messageId));
  assert.deepEqual(markers.clusterNavigation(items.slice(0, 3)).map((group) => group.length), [1, 1, 1]);
});

test('one player store replaces playback and clears track on close', () => {
  const store = media.useNowPlaying;
  store.getState().open({ workspaceId: 'w', assetId: 'a', title: 'First', url: '/one' });
  store.getState().setPosition(12.5, 90);
  assert.equal(store.getState().seconds, 12.5);
  store.getState().open({ workspaceId: 'w', assetId: 'b', title: 'Second', url: '/two', startAt: 42 });
  assert.equal(store.getState().track.assetId, 'b');
  assert.equal(store.getState().seconds, 42);
  assert.equal(store.getState().duration, null);
  store.getState().close();
  assert.equal(store.getState().track, null);
  assert.equal(store.getState().playing, false);
});

test('Media Session handlers seek and pause when supported and no-op when absent', () => {
  const handlers = new Map();
  const positions = [];
  const session = { setActionHandler: (name, handler) => handlers.set(name, handler), setPositionState: (state) => positions.push(state), metadata: null };
  let played = 0, paused = 0;
  const video = { currentTime: 20, duration: 100, playbackRate: 1, play: () => { played++; return Promise.resolve(); }, pause: () => { paused++; } };
  const detach = media.attachMediaSession(session, video, 'Test');
  handlers.get('seekbackward')({ seekOffset: 8 });
  assert.equal(video.currentTime, 12);
  handlers.get('seekforward')({ seekOffset: 15 });
  assert.equal(video.currentTime, 27);
  handlers.get('seekto')({ seekTime: 65 });
  handlers.get('play')({}); handlers.get('pause')({});
  assert.equal(video.currentTime, 65);
  assert.equal(played, 1); assert.equal(paused, 1);
  media.updateMediaPosition(session, video);
  assert.equal(positions[0].position, 65);
  video.duration = Infinity;
  media.updateMediaPosition(session, video);
  assert.equal(positions.length, 1);
  detach();
  assert.equal(handlers.get('play'), null);
  assert.doesNotThrow(() => media.attachMediaSession(undefined, video, 'Unsupported')());
  assert.doesNotThrow(() => media.updateMediaPosition(undefined, video));
});


test('single-page Home conversation navigation never shares a cache key with paginated conversation navigation', () => {
  const home = fs.readFileSync(path.join(__dirname, '..', 'src', 'features', 'agent', 'home-view.tsx'), 'utf8');
  const conversation = fs.readFileSync(path.join(__dirname, '..', 'src', 'features', 'agent', 'conversation-view.tsx'), 'utf8');
  assert.match(home, /keys\.conversations\(workspaceId\), 'navigation'/);
  assert.match(conversation, /keys\.conversations\(workspaceId\), 'navigation-pages'/);
  assert.doesNotMatch(conversation, /keys\.conversations\(workspaceId\), 'navigation'\], initialPageParam/);
});
