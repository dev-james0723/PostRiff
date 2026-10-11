const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Execute the actual canonical-ID resolver and selection handlers without calling Google.
function selectionControls(options = {}) {
  const file = path.resolve(__dirname, '../src/features/youtube/creator-view.tsx');
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const wanted = new Set(['videoSelectionId', 'pick']);
  const functions = [];
  const printer = ts.createPrinter();
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name && wanted.delete(node.name.text)) {
      functions.push(printer.printNode(ts.EmitHint.Unspecified, node, source));
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.equal(wanted.size, 0, 'Selection functions must be present in the production component.');
  const input = `export function load(bindings) {
    const { tab, lastRead, setVideoId, setTitle, setDescription, setError,
      setPlaylistId, setItemId, setPrivacy, setCommentId, setStream, setBroadcast, setChatId } = bindings;
    ${functions.join('\n')}
    return { videoSelectionId, pick };
  }`;
  const { outputText } = ts.transpileModule(input, {
    fileName: 'youtube-selection.tsx',
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  const state = { videoId: '', playlistId: '', itemId: '', title: '', description: '', privacy: '', error: '', ...options.initialState };
  const controls = mod.exports.load({
    tab: options.tab || 'videos',
    lastRead: options.lastRead,
    setVideoId: (value) => { state.videoId = value; },
    setPlaylistId: (value) => { state.playlistId = value; },
    setItemId: (value) => { state.itemId = value; },
    setTitle: (value) => { state.title = value; },
    setDescription: (value) => { state.description = value; },
    setPrivacy: (value) => { state.privacy = value; },
    setError: (value) => { state.error = value; }
  });
  return { ...controls, state };
}

test('uploads select nested video IDs, preserve playlist item IDs, and reject unavailable or conflicting IDs', () => {
  const { videoSelectionId, pick, state } = selectionControls();
  const itemId = 'VVVzeW50aGV0aWMtaXRlbS5hYmNkZWZnaGlqaw';
  const videoId = 'abcdefghijk';
  const uploadsItem = Object.freeze({
    kind: 'youtube#playlistItem', id: itemId,
    contentDetails: Object.freeze({ videoId })
  });
  const before = JSON.stringify(uploadsItem);
  assert.equal(videoSelectionId(uploadsItem), videoId);
  pick(uploadsItem);
  assert.equal(state.videoId, videoId, 'Processing, management, scheduling and captions share this selected Video ID.');
  assert.equal(state.title, '', 'Missing provider titles must not be invented.');
  assert.equal(state.description, '');
  assert.equal(JSON.stringify(uploadsItem), before, 'The official resource and playlist-item ID must remain unchanged.');
  assert.equal(videoSelectionId({ kind: 'youtube#video', id: videoId }), videoId);
  assert.equal(videoSelectionId({ id: itemId, snippet: { resourceId: { videoId } } }), videoId);
  assert.equal(videoSelectionId({ ...uploadsItem, snippet: { resourceId: { videoId } } }), videoId);
  for (const item of [
    { kind: 'youtube#playlistItem', id: videoId },
    { kind: 'youtube#video', id: 'bad' },
    { id: itemId },
    { ...uploadsItem, contentDetails: { videoId: 'bad' } },
    { ...uploadsItem, contentDetails: { videoId: itemId } },
    { ...uploadsItem, contentDetails: { videoId: ' abcdefghijk' } },
    { ...uploadsItem, contentDetails: { videoId: 123 } },
    { ...uploadsItem, snippet: { resourceId: { videoId: 'lmnopqrstuv' } } }
  ]) {
    assert.equal(videoSelectionId(item), undefined);
    state.videoId = videoId;
    pick(item);
    assert.equal(state.videoId, '', 'Reject invalid selection instead of retaining the previous action target.');
    assert.ok(state.error.includes('valid YouTube video ID'));
  }
});

test('playlist membership selection preserves playlist metadata and fills separate membership/video targets', () => {
  const metadata = {
    playlistId: 'PLsynthetic-selected-playlist', title: 'Selected playlist title',
    description: 'Selected playlist description', privacy: 'unlisted'
  };
  const { pick, state } = selectionControls({
    tab: 'playlists', lastRead: { resource: 'playlist_items', query: { playlistId: metadata.playlistId } },
    initialState: { ...metadata, itemId: 'previous-item', videoId: 'lmnopqrstuv' }
  });
  const item = Object.freeze({
    kind: 'youtube#playlistItem', id: 'VVVzeW50aGV0aWMtaXRlbS5hYmNkZWZnaGlqaw',
    contentDetails: Object.freeze({ videoId: 'abcdefghijk' }),
    snippet: Object.freeze({ title: 'Video title', description: 'Video description' }),
    status: Object.freeze({ privacyStatus: 'public' })
  });
  const assertMetadataPreserved = () => {
    for (const [key, value] of Object.entries(metadata)) assert.equal(state[key], value, key);
  };
  pick(item);
  assert.equal(state.itemId, item.id, 'Removal/reorder target the playlist membership ID.');
  assert.equal(state.videoId, item.contentDetails.videoId, 'Episode/video controls use the nested video ID.');
  assertMetadataPreserved();
  // playlist_items requests snippet-only today; that official nested ID works too.
  pick({ id: item.id, snippet: { resourceId: { videoId: 'abcdefghijk' }, title: 'Video title' } });
  assert.equal(state.itemId, item.id);
  assert.equal(state.videoId, 'abcdefghijk');
  assertMetadataPreserved();
  for (const invalid of [
    { ...item, id: '' }, { ...item, id: 'invalid/item' }, { ...item, id: 'x'.repeat(257) },
    { ...item, contentDetails: {} }, { ...item, contentDetails: { videoId: 'bad' } }
  ]) {
    state.itemId = item.id;
    state.videoId = 'abcdefghijk';
    pick(invalid);
    assert.equal(state.itemId, '', 'Invalid membership cannot retain an old removal/reorder target.');
    assert.equal(state.videoId, '', 'Invalid membership cannot retain an old video target.');
    assert.ok(state.error.includes('valid item or video ID'));
    assertMetadataPreserved();
  }
});
