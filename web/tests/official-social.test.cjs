const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function readings() {
  const { outputText } = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/lib/channels/native-readings.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const module = { exports: {} }; new Function('module', 'exports', outputText)(module, module.exports); return module.exports;
}

test('native readings preserve reply hierarchy and provider URNs', () => {
  const { nativeComments } = readings();
  const thread = nativeComments({ data: [{ id: '22', text: 'Reply', replied_to: '21', root_post: '20' }] })[0];
  assert.equal(thread.parentId, '21'); assert.equal(thread.rootId, '20');
  assert.equal(nativeComments({ elements: [{ id: '9', commentUrn: 'urn:li:comment:(urn:li:activity:8,9)', message: { text: 'Hello' }, object: 'urn:li:share:8' }] })[0].id, 'urn:li:comment:(urn:li:activity:8,9)');
  const nested = nativeComments({ elements: [{ id: '10', commentUrn: 'urn:li:comment:(urn:li:activity:8,10)', parentComment: 'urn:li:comment:(urn:li:activity:8,9)', object: 'urn:li:activity:8' }] })[0];
  assert.equal(nested.parentId, 'urn:li:comment:(urn:li:activity:8,9)'); assert.equal(nested.rootId, 'urn:li:activity:8');
  const youtube = nativeComments({ items: [{ snippet: { videoId: 'video', topLevelComment: { id: 'top', snippet: { textOriginal: 'Top' } } }, replies: { comments: [{ id: 'child', snippet: { textOriginal: 'Child', parentId: 'top' } }] } }] });
  assert.equal(youtube[1].parentId, 'top'); assert.equal(youtube[1].rootId, 'video');
});

test('unavailable metrics remain unavailable; a provider zero remains zero', () => {
  const { nativeMetricRows } = readings();
  assert.deepEqual(nativeMetricRows({ error: 'Permission missing', views: null }), []);
  assert.deepEqual(nativeMetricRows({ id: 123, views: 0 }), [{ name: 'views', value: 0 }]);
  assert.deepEqual(nativeMetricRows({ data: [{ name: 'views', values: [{ value: 12 }] }] }), [{ name: 'views.values[0].value', value: 12 }]);
  assert(!nativeMetricRows({ likes: 10 }).some(row => /reach|impressions/.test(row.name)));
});
