const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const React = require('react');
const { createLoader, SRC } = require('./agent-ui-journeys/_load.cjs');
const { createHarness } = require('./agent-ui-client-harness.cjs');

test('private frames load only on demand and release their URLs on paging, hide and workspace change', async t => {
  const requests = [], revoked = [], created = [];
  let workspaceId = 'first';
  const api = { creativeReferenceFrames: (...args) => new Promise(resolve => requests.push({ args, resolve })) };
  const { ReferenceContactSheet } = createLoader({ stubs: {
    [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ api, workspaceId }) },
    [path.join(SRC, 'components/ui/button')]: { Button: ({ children, ...props }) => React.createElement('button', props, children) }
  } }).load('src/features/creative-video/reference-contact-sheet');
  t.mock.method(URL, 'createObjectURL', blob => { created.push(blob); return 'blob:private-' + created.length; });
  t.mock.method(URL, 'revokeObjectURL', url => revoked.push(url));
  const harness = createHarness(React);
  const project = { id: 'project', referenceAssetId: 'private-video', revision: 2 };
  const render = () => harness.render(React.createElement(ReferenceContactSheet, { project }));
  async function answer(index, shot) {
    requests[index].resolve({ page: index, pageCount: 2, totalShots: 5, frames: [{
      shotIndex: shot, startMs: 100, endMs: 600, timeMs: 375, width: 40, height: 30, jpeg: '/9j/2Q==' }] });
    await new Promise(resolve => setImmediate(resolve));
  }
  try {
    render();
    assert.equal(requests.length, 0);
    harness.click(harness.button('Show shot frames'));
    assert.deepEqual(requests[0].args.slice(0, 4), ['first', 'project', 2, 0]);
    await answer(0, 0);
    assert.equal(created[0].type, 'image/jpeg');
    assert.match(harness.container.textContent, /Shot 1.*Frame at 0.375 s/);
    harness.click(harness.button('Next shots'));
    assert.deepEqual(revoked, ['blob:private-1']);
    assert.equal(requests[0].args[4].aborted, true);
    assert.deepEqual(requests[1].args.slice(0, 4), ['first', 'project', 2, 1]);
    await answer(1, 4);
    assert.match(harness.container.textContent, /Shot 5/);
    workspaceId = 'second';
    render();
    assert.deepEqual(revoked, ['blob:private-1', 'blob:private-2']);
    assert.ok(harness.button('Show shot frames'));
    assert.doesNotMatch(harness.container.textContent, /Shot 5/);
    harness.click(harness.button('Show shot frames'));
    await answer(2, 1);
    harness.click(harness.button('Hide shot frames'));
    assert.deepEqual(revoked, ['blob:private-1', 'blob:private-2', 'blob:private-3']);
    harness.click(harness.button('Show shot frames'));
    harness.click(harness.button('Hide shot frames'));
    await answer(3, 2);
    assert.equal(created.length, 3);
    assert.equal(requests[3].args[4].aborted, true);
  } finally { harness.cleanup(); }
});

test('Reference analysis opens the frame viewer explicitly and aborts its request when the analysis closes', t => {
  const requests = [];
  const api = { creativeReferenceFrames: (...args) => { requests.push(args); return new Promise(() => {}); } };
  const { BlueprintDetails } = createLoader({ stubs: {
    [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ api, workspaceId: 'unit' }) },
    [path.join(SRC, 'features/creative-video/media')]: { PrivateVideo: () => null },
    [path.join(SRC, 'components/ui/button')]: { Button: ({ children, ...props }) => React.createElement('button', props, children) }
  } }).load('src/features/creative-video/blueprint-details');
  // Next Link schedules an idle intersection check on the browser's self global.
  const originalSelf = Object.getOwnPropertyDescriptor(globalThis, 'self');
  Object.defineProperty(globalThis, 'self', { configurable: true, value: globalThis });
  t.after(() => { if (originalSelf) Object.defineProperty(globalThis, 'self', originalSelf); else delete globalThis.self; });
  const harness = createHarness(React);
  const project = { id: 'example', revision: 4, referenceAssetId: 'ref',
    context: { brand: 'Sample', preferences: [] },
    analysis: { fps: 24, durationMs: 3000, scenes: [{ startMs: 0, endMs: 3000 }] } };
  try {
    harness.render(React.createElement(BlueprintDetails, { project }));
    assert.equal(harness.button('Show shot frames'), null);
    const disclosure = harness.find('details');
    harness.act(() => disclosure.props.onToggle({ currentTarget: { open: true } }));
    assert.equal(requests.length, 0);
    harness.click(harness.button('Show shot frames'));
    assert.deepEqual(requests[0].slice(0, 4), ['unit', 'example', 4, 0]);
    harness.act(() => disclosure.props.onToggle({ currentTarget: { open: false } }));
    assert.equal(requests[0][4].aborted, true);
    assert.equal(harness.button('Hide shot frames'), null);
  } finally { harness.cleanup(); }
});
